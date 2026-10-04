from __future__ import annotations

from typing import Any

from game_bot.config.loader import load_settings


class DmError(RuntimeError):
    pass


def create_dm() -> Any:
    initialized = False
    pythoncom = None
    try:
        import pythoncom as pythoncom_module
        pythoncom = pythoncom_module
        pythoncom.CoInitialize()
        initialized = True
    except Exception:
        pythoncom = None

    try:
        try:
            import win32com.client
        except ModuleNotFoundError as exc:
            raise DmError("dm input requires pywin32 in the project venv.") from exc

        try:
            dm = win32com.client.Dispatch("dm.dmsoft")
        except Exception as exc:
            raise DmError("Failed to create COM object dm.dmsoft. Register dm.dll and use 32-bit Python.") from exc

        try:
            version = str(dm.Ver())
        except Exception as exc:
            raise DmError("Created dm.dmsoft but Ver() failed.") from exc
        if not version:
            raise DmError("Created dm.dmsoft but Ver() returned empty.")
        return dm
    except Exception:
        if initialized and pythoncom is not None:
            pythoncom.CoUninitialize()
        raise


class BoundDmWindow:
    def __init__(
        self,
        hwnd: int,
        *,
        display: str | None = None,
        mouse: str | None = None,
        keypad: str | None = None,
        mode: int | None = None,
    ) -> None:
        config = _dm_config()
        self.hwnd = hwnd
        self.display = display or str(config.get("display", "gdi"))
        self.mouse = mouse or str(config.get("mouse", "windows"))
        self.keypad = keypad or str(config.get("keypad", "windows"))
        self.mode = int(config.get("bind_mode", 0) if mode is None else mode)
        self.dm = None
        self.version = ""
        self._bound = False
        self._pythoncom = None
        self._com_initialized = False

    def __enter__(self) -> "BoundDmWindow":
        try:
            import pythoncom
            self._pythoncom = pythoncom
            pythoncom.CoInitialize()
            self._com_initialized = True
        except Exception:
            self._pythoncom = None

        try:
            import win32com.client
        except ModuleNotFoundError as exc:
            self._cleanup_com()
            raise DmError("dm input requires pywin32 in the project venv.") from exc

        try:
            self.dm = win32com.client.Dispatch("dm.dmsoft")
            self.version = str(self.dm.Ver())
            result = int(self.dm.BindWindow(self.hwnd, self.display, self.mouse, self.keypad, self.mode))
        except Exception as exc:
            self._cleanup_com()
            raise DmError(f"Failed to bind dm input to hwnd={self.hwnd}: {exc}") from exc
        if result != 1:
            self._cleanup_com()
            raise DmError(
                f"dm.BindWindow failed: result={result}, hwnd={self.hwnd}, "
                f"display={self.display}, mouse={self.mouse}, keypad={self.keypad}, mode={self.mode}"
            )
        self._bound = True
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self._bound and self.dm is not None:
            self.dm.UnBindWindow()
            self._bound = False
        self._cleanup_com()

    def capture_png(self, x1: int, y1: int, x2: int, y2: int, output_path: str) -> int:
        if self.dm is None:
            raise DmError("dm window is not bound")
        return int(self.dm.CapturePng(int(x1), int(y1), int(x2), int(y2), str(output_path)))

    def delay(self, duration_ms: int) -> None:
        if self.dm is None:
            raise DmError("dm window is not bound")
        if duration_ms > 0:
            self.dm.Delay(duration_ms)

    def _cleanup_com(self) -> None:
        self.dm = None
        if self._com_initialized and self._pythoncom is not None:
            self._pythoncom.CoUninitialize()
        self._com_initialized = False


class BoundDmInput(BoundDmWindow):
    def click(self, x: int, y: int, *, button: str = "left", duration_ms: int = 50) -> None:
        if self.dm is None:
            raise DmError("dm input is not bound")
        if button == "left":
            down, up = self.dm.LeftDown, self.dm.LeftUp
        elif button == "right":
            down, up = self.dm.RightDown, self.dm.RightUp
        else:
            raise DmError(f"Unsupported dm mouse button: {button}")
        self.dm.MoveTo(x, y)
        down()
        if duration_ms > 0:
            self.dm.Delay(duration_ms)
        up()

    def press_key(self, virtual_key: int, *, duration_ms: int = 50) -> None:
        if self.dm is None:
            raise DmError("dm input is not bound")
        self.dm.KeyDown(virtual_key)
        if duration_ms > 0:
            self.dm.Delay(duration_ms)
        self.dm.KeyUp(virtual_key)

    def scroll(self, direction: str, *, distance: int = 1, interval_ms: int = 0) -> None:
        if self.dm is None:
            raise DmError("dm input is not bound")
        if direction == "up":
            wheel = self.dm.WheelUp
        elif direction == "down":
            wheel = self.dm.WheelDown
        else:
            raise DmError(f"Unsupported dm scroll direction: {direction}")
        for index in range(distance):
            wheel()
            if index < distance - 1 and interval_ms > 0:
                self.dm.Delay(interval_ms)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, *, duration_ms: int = 300, steps: int = 12) -> None:
        if self.dm is None:
            raise DmError("dm input is not bound")
        if steps <= 0:
            raise DmError("dm drag steps must be a positive integer")
        self.dm.MoveTo(start_x, start_y)
        self.dm.LeftDown()
        step_delay_ms = max(0, int(duration_ms) // steps) if duration_ms > 0 else 0
        for index in range(1, steps + 1):
            progress = index / steps
            current_x = round(start_x + (end_x - start_x) * progress)
            current_y = round(start_y + (end_y - start_y) * progress)
            self.dm.MoveTo(current_x, current_y)
            if step_delay_ms > 0 and index < steps:
                self.dm.Delay(step_delay_ms)
        self.dm.LeftUp()

    def delay(self, duration_ms: int) -> None:
        if self.dm is None:
            raise DmError("dm input is not bound")
        if duration_ms > 0:
            self.dm.Delay(duration_ms)


def _dm_config() -> dict[str, Any]:
    config = load_settings().get("dm", {})
    return config if isinstance(config, dict) else {}
