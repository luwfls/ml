from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from game_bot.core.models import Point, Rect, Size

_ACTIVE_VIEWPORT_RE = re.compile(
    r"Viewport\s+INTERNAL:.*?orientation=(?P<orientation>\d+).*?"
    r"logicalFrame=\[(?P<left>\d+),\s*(?P<top>\d+),\s*(?P<right>\d+),\s*(?P<bottom>\d+)\].*?"
    r"isActive=\[1\]",
    re.IGNORECASE,
)
_WM_SIZE_RE = re.compile(r"(?:Physical|Override) size:\s*(?P<width>\d+)x(?P<height>\d+)", re.IGNORECASE)
_ORIENTATION_RE = re.compile(r"orientation=(?P<orientation>[0-3])", re.IGNORECASE)


class AdbError(RuntimeError):
    pass


@dataclass(frozen=True)
class AndroidDisplayInfo:
    logical_size: Size
    orientation: int
    viewport: Rect
    source: str


@dataclass(frozen=True)
class ClientToAndroidMapper:
    client_size: Size
    logical_size: Size
    viewport: Rect | None = None

    def __post_init__(self) -> None:
        if self.client_size.width <= 0 or self.client_size.height <= 0:
            raise AdbError(f"Invalid client size: {self.client_size}")
        if self.logical_size.width <= 0 or self.logical_size.height <= 0:
            raise AdbError(f"Invalid Android logical size: {self.logical_size}")
        viewport = self.effective_viewport
        if viewport.width <= 0 or viewport.height <= 0:
            raise AdbError(f"Invalid Android viewport: {viewport}")
        if (
            viewport.left < 0
            or viewport.top < 0
            or viewport.right > self.logical_size.width
            or viewport.bottom > self.logical_size.height
        ):
            raise AdbError(
                f"Android viewport is outside the logical display: viewport={viewport}, "
                f"logical_size={self.logical_size}"
            )

    @property
    def effective_viewport(self) -> Rect:
        return self.viewport or Rect(0, 0, self.logical_size.width, self.logical_size.height)

    def map_point(self, point: Point) -> Point:
        if (
            point.x < 0
            or point.y < 0
            or point.x >= self.client_size.width
            or point.y >= self.client_size.height
        ):
            raise AdbError(
                f"Client point is outside the window: point={point}, client_size={self.client_size}"
            )
        viewport = self.effective_viewport
        x = viewport.left + round((point.x + 0.5) * viewport.width / self.client_size.width - 0.5)
        y = viewport.top + round((point.y + 0.5) * viewport.height / self.client_size.height - 0.5)
        return Point(
            max(viewport.left, min(viewport.right - 1, x)),
            max(viewport.top, min(viewport.bottom - 1, y)),
        )


class AdbClient:
    def __init__(
        self,
        executable: str | Path,
        serial: str,
        *,
        timeout_seconds: float = 10,
    ) -> None:
        self.executable = Path(executable)
        self.serial = str(serial).strip()
        self.timeout_seconds = float(timeout_seconds)
        if not self.serial:
            raise AdbError("ADB serial is required; implicit device selection is not allowed")
        if self.timeout_seconds <= 0:
            raise AdbError("ADB timeout_seconds must be positive")

    def run(self, *args: str) -> str:
        if not self.executable.is_file():
            raise AdbError(f"ADB executable does not exist: {self.executable}")
        command = [str(self.executable), "-s", self.serial, *map(str, args)]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdbError(
                f"ADB command timed out after {self.timeout_seconds:g}s for serial={self.serial}: {command}"
            ) from exc
        except OSError as exc:
            raise AdbError(f"Failed to run ADB for serial={self.serial}: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise AdbError(
                f"ADB command failed: exit={completed.returncode}, serial={self.serial}, "
                f"command={command}, detail={detail or '<no output>'}"
            )
        return completed.stdout.strip()

    def shell(self, *args: str) -> str:
        return self.run("shell", *args)

    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(int(x)), str(int(y)))

    def swipe(self, start: Point, end: Point, duration_ms: int) -> None:
        self.shell(
            "input",
            "swipe",
            str(start.x),
            str(start.y),
            str(end.x),
            str(end.y),
            str(max(0, int(duration_ms))),
        )

    def keyevent(self, keycode: int) -> None:
        self.shell("input", "keyevent", str(int(keycode)))

    def query_active_display(self) -> AndroidDisplayInfo:
        input_dump = self.shell("dumpsys", "input")
        try:
            return parse_active_display(input_dump)
        except AdbError as primary_error:
            wm_size = self.shell("wm", "size")
            try:
                return parse_display_fallback(input_dump, wm_size)
            except AdbError as fallback_error:
                raise AdbError(
                    f"Could not determine Android active logical display for serial={self.serial}; "
                    f"dumpsys error={primary_error}; wm fallback error={fallback_error}"
                ) from fallback_error


def parse_active_display(text: str) -> AndroidDisplayInfo:
    normalized = " ".join(str(text).split())
    matches = list(_ACTIVE_VIEWPORT_RE.finditer(normalized))
    if not matches:
        raise AdbError("dumpsys input did not contain an active INTERNAL logical viewport")
    match = matches[-1]
    viewport = Rect(
        int(match.group("left")),
        int(match.group("top")),
        int(match.group("right")),
        int(match.group("bottom")),
    )
    if viewport.width <= 0 or viewport.height <= 0:
        raise AdbError(f"dumpsys input returned an invalid active viewport: {viewport}")
    return AndroidDisplayInfo(
        logical_size=Size(viewport.right, viewport.bottom),
        orientation=int(match.group("orientation")),
        viewport=viewport,
        source="dumpsys input active logicalFrame",
    )


def parse_display_fallback(input_dump: str, wm_size: str) -> AndroidDisplayInfo:
    size_matches = list(_WM_SIZE_RE.finditer(str(wm_size)))
    if not size_matches:
        raise AdbError(f"wm size returned no physical or override size: {wm_size!r}")
    size_match = size_matches[-1]
    physical = Size(int(size_match.group("width")), int(size_match.group("height")))
    orientation_matches = list(_ORIENTATION_RE.finditer(str(input_dump)))
    if not orientation_matches:
        raise AdbError("dumpsys input returned no display orientation for wm size fallback")
    orientation = int(orientation_matches[-1].group("orientation"))
    logical = Size(physical.height, physical.width) if orientation in {1, 3} else physical
    viewport = Rect(0, 0, logical.width, logical.height)
    return AndroidDisplayInfo(
        logical_size=logical,
        orientation=orientation,
        viewport=viewport,
        source="wm size plus dumpsys orientation fallback",
    )
