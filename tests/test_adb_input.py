from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from game_bot.core.adb import (
    AdbClient,
    AdbError,
    ClientToAndroidMapper,
    parse_active_display,
    parse_display_fallback,
)
from game_bot.core.input import AdbInputBackend, DmInputBackend, InputError, input_backend_from_name
from game_bot.core.models import Point, Rect, Size


DUMPSYS_ACTIVE = """
Input Reader State:
  Viewports:
    Viewport INTERNAL: displayId=0, uniqueId=local:1, port=0, orientation=1,
      logicalFrame=[0, 0, 2560, 1440], physicalFrame=[0, 0, 2560, 1440],
      deviceSize=[2560, 1440], isActive=[1]
"""


class CoordinateMapperTests(unittest.TestCase):
    def test_verified_client_point_mapping(self) -> None:
        mapper = ClientToAndroidMapper(Size(1018, 632), Size(2560, 1440))
        self.assertEqual(mapper.map_point(Point(572, 591)), Point(1439, 1347))

    def test_edges_are_clamped(self) -> None:
        mapper = ClientToAndroidMapper(Size(1018, 632), Size(2560, 1440))
        self.assertEqual(mapper.map_point(Point(0, 0)), Point(1, 1))
        self.assertEqual(mapper.map_point(Point(1017, 631)), Point(2558, 1438))

    def test_viewport_offset_is_applied(self) -> None:
        mapper = ClientToAndroidMapper(
            Size(100, 100),
            Size(300, 200),
            Rect(20, 10, 220, 110),
        )
        self.assertEqual(mapper.map_point(Point(50, 50)), Point(120, 60))

    def test_out_of_bounds_client_point_fails(self) -> None:
        mapper = ClientToAndroidMapper(Size(100, 100), Size(300, 200))
        with self.assertRaises(AdbError):
            mapper.map_point(Point(100, 50))


class DisplayParsingTests(unittest.TestCase):
    def test_active_logical_frame_wins(self) -> None:
        info = parse_active_display(DUMPSYS_ACTIVE)
        self.assertEqual(info.logical_size, Size(2560, 1440))
        self.assertEqual(info.orientation, 1)
        self.assertEqual(info.viewport, Rect(0, 0, 2560, 1440))

    def test_portrait_physical_size_rotates_for_landscape_fallback(self) -> None:
        info = parse_display_fallback("orientation=1", "Physical size: 1440x2560")
        self.assertEqual(info.logical_size, Size(2560, 1440))

    def test_fallback_requires_orientation(self) -> None:
        with self.assertRaises(AdbError):
            parse_display_fallback("no orientation", "Physical size: 1440x2560")


class AdbClientTests(unittest.TestCase):
    def test_tap_command_always_selects_serial(self) -> None:
        with TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "adb.exe"
            executable.touch()
            completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            with patch("game_bot.core.adb.subprocess.run", return_value=completed) as run:
                AdbClient(executable, "emulator-5554").tap(1439, 1347)
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [str(executable), "-s", "emulator-5554", "shell", "input", "tap", "1439", "1347"],
        )

    def test_nonzero_exit_is_actionable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "adb.exe"
            executable.touch()
            completed = subprocess.CompletedProcess([], 1, stdout="", stderr="device offline")
            with patch("game_bot.core.adb.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(AdbError, "device offline"):
                    AdbClient(executable, "emulator-5554").tap(1, 2)

    def test_timeout_is_wrapped(self) -> None:
        with TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "adb.exe"
            executable.touch()
            with patch(
                "game_bot.core.adb.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["adb"], 1),
            ):
                with self.assertRaisesRegex(AdbError, "timed out"):
                    AdbClient(executable, "emulator-5554", timeout_seconds=1).tap(1, 2)


class AdbInputBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = unittest.mock.Mock()
        self.client.serial = "emulator-5554"
        self.client.query_active_display.return_value = parse_active_display(DUMPSYS_ACTIVE)
        self.backend = AdbInputBackend(client=self.client)

    @patch("game_bot.core.input.client_to_screen", return_value=Point(3389, 591))
    @patch("game_bot.core.input.get_client_size", return_value=Size(1018, 632))
    def test_click_maps_coordinates(self, _size, _screen) -> None:
        result = self.backend.click_client(123, 572, 591)
        self.client.tap.assert_called_once_with(1439, 1347)
        self.assertEqual(result.backend, "adb")
        self.assertIn("android=(1439, 1347)", result.message)

    def test_right_click_fails(self) -> None:
        with self.assertRaisesRegex(InputError, "right click"):
            self.backend.click_client(123, 1, 1, button="right")

    @patch("game_bot.core.input.is_window_alive", return_value=True)
    def test_escape_uses_verified_keycode(self, _alive) -> None:
        self.backend.press_key(123, "esc")
        self.client.keyevent.assert_called_once_with(111)

    @patch("game_bot.core.input.is_window_alive", return_value=True)
    def test_unknown_key_fails(self, _alive) -> None:
        with self.assertRaisesRegex(InputError, "Unsupported ADB key"):
            self.backend.press_key(123, "a")

    @patch("game_bot.core.input.client_to_screen", return_value=Point(10, 10))
    @patch("game_bot.core.input.is_window_alive", return_value=True)
    @patch("game_bot.core.input.get_client_size", return_value=Size(1018, 632))
    def test_drag_maps_both_ends(self, _size, _alive, _screen) -> None:
        self.backend.drag_client(123, 572, 591, direction="up", distance=100, duration_ms=300)
        self.client.swipe.assert_called_once_with(Point(1439, 1347), Point(1439, 1119), 300)

    @patch("game_bot.core.input.get_client_size", return_value=Size(1018, 632))
    def test_content_down_scroll_swipes_finger_up(self, _size) -> None:
        self.backend.scroll_client(123, direction="down", distance=1, speed="normal")
        start, end, duration = self.client.swipe.call_args.args
        self.assertGreater(start.y, end.y)
        self.assertEqual(duration, 350)


class BackendFactoryTests(unittest.TestCase):
    def test_explicit_adb_backend(self) -> None:
        with patch("game_bot.core.input.load_settings", return_value={"adb": {"serial": "emulator-5554"}}):
            self.assertIsInstance(input_backend_from_name("adb"), AdbInputBackend)

    def test_explicit_dm_backend(self) -> None:
        self.assertIsInstance(input_backend_from_name("dm"), DmInputBackend)

    def test_unknown_backend_fails(self) -> None:
        with self.assertRaisesRegex(InputError, "Unsupported input backend"):
            input_backend_from_name("unknown")


if __name__ == "__main__":
    unittest.main()
