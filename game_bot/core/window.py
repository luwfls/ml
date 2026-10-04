import ctypes
import time
from ctypes import wintypes

from game_bot.core.geometry import rect_from_origin_size
from game_bot.core.models import Point, Rect, Size, WindowInfo
from game_bot.core.process import get_process_name, process_name_matches

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


class POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

try:
    shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

user32.EnumWindows.argtypes = (EnumWindowsProc, wintypes.LPARAM)
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(RECT))
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(RECT))
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(POINT))
user32.ClientToScreen.restype = wintypes.BOOL
user32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(POINT))
user32.ScreenToClient.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = ()
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
user32.AttachThreadInput.restype = wintypes.BOOL
user32.SetFocus.argtypes = (wintypes.HWND,)
user32.SetFocus.restype = wintypes.HWND
user32.SetActiveWindow.argtypes = (wintypes.HWND,)
user32.SetActiveWindow.restype = wintypes.HWND
user32.IsIconic.argtypes = (wintypes.HWND,)
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = (
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = ()
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
user32.SetWindowLongW.restype = ctypes.c_long

SW_SHOW = 5
SW_RESTORE = 9
HWND_TOP = wintypes.HWND(0)
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_FRAMECHANGED = 0x0020
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000


class WindowError(RuntimeError):
    pass


class WindowNotFoundError(WindowError):
    pass


class WindowApiError(WindowError):
    pass


def list_windows_by_title(
    title: str,
    *,
    exact: bool = False,
    visible_only: bool = True,
) -> list[tuple[int, str]]:
    title = title.strip()
    if not title:
        raise ValueError("Window title is required")

    matches: list[tuple[int, str]] = []
    needle = title if exact else title.lower()

    def callback(hwnd: int, _lparam: int) -> bool:
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True

        window_title = get_window_title(hwnd)
        if not window_title:
            return True

        matched = window_title == needle if exact else needle in window_title.lower()
        if matched:
            matches.append((hwnd, window_title))
        return True

    if not user32.EnumWindows(EnumWindowsProc(callback), 0):
        raise _api_error("EnumWindows", None)

    return matches


def find_window_by_title(
    title: str,
    *,
    exact: bool = False,
    visible_only: bool = True,
) -> int:
    matches = list_windows_by_title(title, exact=exact, visible_only=visible_only)
    if not matches:
        mode = "exact" if exact else "contains"
        visibility = "visible windows" if visible_only else "all windows"
        raise WindowNotFoundError(f"No {visibility} matched title by {mode}: {title}")
    return matches[0][0]


def list_windows_by_process_name(
    process_name: str,
    *,
    visible_only: bool = True,
) -> list[tuple[int, str, int, str]]:
    process_name = process_name.strip()
    if not process_name:
        raise ValueError("Process name is required")

    matches: list[tuple[int, str, int, str]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True

        pid = get_window_process_id(hwnd)
        actual_process_name = get_process_name(pid)
        if process_name_matches(actual_process_name, process_name):
            matches.append((hwnd, get_window_title(hwnd), pid, actual_process_name))
        return True

    if not user32.EnumWindows(EnumWindowsProc(callback), 0):
        raise _api_error("EnumWindows", None)

    return matches


def find_window_by_process_name(
    process_name: str,
    *,
    visible_only: bool = True,
) -> int:
    matches = list_windows_by_process_name(process_name, visible_only=visible_only)
    if not matches:
        visibility = "visible windows" if visible_only else "all windows"
        raise WindowNotFoundError(f"No {visibility} belonged to process: {process_name}")
    return matches[0][0]


def get_window_process_id(hwnd: int) -> int:
    _ensure_window(hwnd)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def is_window_alive(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def get_window_rect(hwnd: int) -> Rect:
    _ensure_window(hwnd)
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise _api_error("GetWindowRect", hwnd)
    return Rect(rect.left, rect.top, rect.right, rect.bottom)


def get_client_size(hwnd: int) -> Size:
    _ensure_window(hwnd)
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise _api_error("GetClientRect", hwnd)

    size = Size(rect.right - rect.left, rect.bottom - rect.top)
    if size.width <= 0 or size.height <= 0:
        raise WindowError("Client area size is zero; the window may be minimized or not rendered")
    return size


def client_to_screen(hwnd: int, x: int, y: int) -> Point:
    _ensure_window(hwnd)
    point = POINT(x, y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise _api_error("ClientToScreen", hwnd)
    return Point(point.x, point.y)


def screen_to_client(hwnd: int, x: int, y: int) -> Point:
    _ensure_window(hwnd)
    point = POINT(x, y)
    if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
        raise _api_error("ScreenToClient", hwnd)
    return Point(point.x, point.y)


def get_cursor_screen_position() -> Point:
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise _api_error("GetCursorPos", None)
    return Point(point.x, point.y)


def is_window_foreground(hwnd: int) -> bool:
    _ensure_window(hwnd)
    return user32.GetForegroundWindow() == hwnd


def bring_window_to_foreground(hwnd: int, *, wait_ms: int = 200) -> WindowInfo:
    _ensure_window(hwnd)

    foreground_hwnd = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None) if foreground_hwnd else 0
    attached_threads: list[int] = []

    try:
        for thread_id in (foreground_thread, target_thread):
            if thread_id and thread_id != current_thread and thread_id not in attached_threads:
                if user32.AttachThreadInput(current_thread, thread_id, True):
                    attached_threads.append(thread_id)

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)

        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
        user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, flags)
        user32.BringWindowToTop(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for thread_id in reversed(attached_threads):
            user32.AttachThreadInput(current_thread, thread_id, False)

    if wait_ms > 0:
        time.sleep(wait_ms / 1000)

    if not is_window_foreground(hwnd):
        raise WindowError(
            "Failed to bring window to foreground with AttachThreadInput. "
            "Run this tool with the same privilege level as the target window."
        )

    return get_window_info(hwnd)


def move_window(hwnd: int, left: int, top: int, *, wait_ms: int = 100) -> WindowInfo:
    info = get_window_info(hwnd)
    return dock_window_to_rect(
        hwnd,
        Rect(left, top, left + info.window_rect.width, top + info.window_rect.height),
        wait_ms=wait_ms,
    )


def resize_window(hwnd: int, width: int, height: int, *, wait_ms: int = 100) -> WindowInfo:
    _ensure_window(hwnd)
    if width <= 0 or height <= 0:
        raise ValueError("Window width and height must be positive integers")

    info = get_window_info(hwnd)
    return dock_window_to_rect(
        hwnd,
        Rect(info.window_rect.left, info.window_rect.top, info.window_rect.left + width, info.window_rect.top + height),
        wait_ms=wait_ms,
    )


def dock_window_to_rect(
    hwnd: int,
    rect: Rect,
    *,
    client_area: bool = False,
    wait_ms: int = 100,
    activate: bool = True,
) -> WindowInfo:
    _ensure_window(hwnd)
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError("Window rect must have positive width and height")

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, SW_SHOW)

    left = rect.left
    top = rect.top
    width = rect.width
    height = rect.height

    if client_area:
        info = get_window_info(hwnd)
        border_left = info.client_origin_screen.x - info.window_rect.left
        border_top = info.client_origin_screen.y - info.window_rect.top
        border_right = info.window_rect.right - (info.client_origin_screen.x + info.client_size.width)
        border_bottom = info.window_rect.bottom - (info.client_origin_screen.y + info.client_size.height)
        left -= border_left
        top -= border_top
        width += border_left + border_right
        height += border_top + border_bottom

    flags = SWP_SHOWWINDOW if activate else SWP_NOZORDER | SWP_NOACTIVATE
    insert_after = HWND_TOP if activate else wintypes.HWND(0)
    if not user32.SetWindowPos(hwnd, insert_after, left, top, width, height, flags):
        raise _api_error("SetWindowPos", hwnd)

    if wait_ms > 0:
        time.sleep(wait_ms / 1000)

    return get_window_info(hwnd)


def set_window_topmost(hwnd: int, enabled: bool = True, *, wait_ms: int = 100) -> WindowInfo:
    _ensure_window(hwnd)
    info = get_window_info(hwnd)
    insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if not user32.SetWindowPos(hwnd, insert_after, info.window_rect.left, info.window_rect.top, 0, 0, flags):
        raise _api_error("SetWindowPos(HWND_TOPMOST)", hwnd)
    if wait_ms > 0:
        time.sleep(wait_ms / 1000)
    return get_window_info(hwnd)


def screen_size() -> Size:
    return Size(user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def prepare_window_for_automation(
    hwnd: int,
    *,
    rect: Rect | None = None,
    topmost: bool = True,
    wait_ms: int = 100,
) -> WindowInfo:
    _ensure_window(hwnd)
    if rect is not None:
        info = dock_window_to_rect(hwnd, rect, client_area=False, wait_ms=wait_ms, activate=False)
    else:
        info = get_window_info(hwnd)
    if topmost:
        info = set_window_topmost(hwnd, enabled=True, wait_ms=wait_ms)
    return info


def get_window_info(hwnd: int) -> WindowInfo:
    _ensure_window(hwnd)
    title = get_window_title(hwnd)
    window_rect = get_window_rect(hwnd)
    client_size = get_client_size(hwnd)
    client_origin_screen = client_to_screen(hwnd, 0, 0)
    client_rect_screen = rect_from_origin_size(client_origin_screen, client_size)

    return WindowInfo(
        hwnd=hwnd,
        title=title,
        window_rect=window_rect,
        client_size=client_size,
        client_origin_screen=client_origin_screen,
        client_rect_screen=client_rect_screen,
    )


def ensure_window_client_size(hwnd: int, width: int, height: int, *, wait_ms: int = 100) -> WindowInfo:
    _ensure_window(hwnd)
    if width <= 0 or height <= 0:
        raise ValueError("Target client size must be positive integers")

    info = get_window_info(hwnd)
    if info.client_size.width == width and info.client_size.height == height:
        return info

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        if wait_ms > 0:
            time.sleep(wait_ms / 1000)
        info = get_window_info(hwnd)

    try:
        info = dock_window_to_rect(
            hwnd,
            Rect(
                info.client_origin_screen.x,
                info.client_origin_screen.y,
                info.client_origin_screen.x + width,
                info.client_origin_screen.y + height,
            ),
            client_area=True,
            wait_ms=wait_ms,
            activate=False,
        )
    except WindowApiError as exc:
        raise WindowError(
            "Failed to restore target window size. Windows denied resizing the target window; "
            "run this tool with the same privilege level as the target window, or restore it manually. "
            f"Target client size: {width}x{height}. {exc}"
        ) from exc
    if (info.client_size.width != width or info.client_size.height != height) and wait_ms > 0:
        time.sleep(wait_ms / 1000)
        info = get_window_info(hwnd)
    return info


def _ensure_window(hwnd: int) -> None:
    if not is_window_alive(hwnd):
        raise WindowError(f"Invalid or closed window handle: {hwnd}")


def _api_error(api_name: str, hwnd: int | None) -> WindowApiError:
    code = ctypes.get_last_error()
    target = f" hwnd={hwnd}" if hwnd is not None else ""
    return WindowApiError(f"{api_name} failed{target}; winerror={code}")


def toggle_window_fullscreen(hwnd: int, saved: dict, *, wait_ms: int = 100) -> bool:
    """Toggle borderless fullscreen on hwnd. saved is a mutable dict for state.
    Returns True if now fullscreen, False if restored to normal."""
    _ensure_window(hwnd)

    if saved.get("fullscreen"):
        style: int = saved["style"]
        rect: Rect = saved["rect"]
        user32.SetWindowLongW(hwnd, GWL_STYLE, style)
        flags = SWP_SHOWWINDOW | SWP_FRAMECHANGED
        if not user32.SetWindowPos(hwnd, HWND_TOP, rect.left, rect.top, rect.width, rect.height, flags):
            raise _api_error("SetWindowPos(restore)", hwnd)
        saved["fullscreen"] = False
        if wait_ms > 0:
            time.sleep(wait_ms / 1000)
        return False

    current_style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    current_rect = get_window_rect(hwnd)
    saved["style"] = current_style
    saved["rect"] = current_rect
    new_style = current_style & ~(WS_CAPTION | WS_THICKFRAME)
    user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
    s = screen_size()
    flags = SWP_SHOWWINDOW | SWP_FRAMECHANGED
    if not user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, s.width, s.height, flags):
        user32.SetWindowLongW(hwnd, GWL_STYLE, current_style)
        raise _api_error("SetWindowPos(fullscreen)", hwnd)
    saved["fullscreen"] = True
    if wait_ms > 0:
        time.sleep(wait_ms / 1000)
    return True
