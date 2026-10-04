import ctypes
import threading
from ctypes import wintypes
from typing import Callable

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("ptX", wintypes.LONG),
        ("ptY", wintypes.LONG),
    ]


_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = ctypes.c_int
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NONE = 0x0000
VK_F12 = 0x7B


class HotkeyRegistrationError(RuntimeError):
    pass


def register_global_hotkey(
    vk: int,
    callback: Callable[[], None],
    *,
    modifiers: int = MOD_NONE,
    hotkey_id: int = 1,
) -> Callable[[], None]:
    """Register a global hotkey. Returns an unregister callable."""
    thread_id_holder: list[int] = []
    ready = threading.Event()
    error_holder: list[Exception] = []

    def _message_loop() -> None:
        tid = _kernel32.GetCurrentThreadId()
        thread_id_holder.append(tid)

        if not _user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
            err = ctypes.get_last_error()
            error_holder.append(HotkeyRegistrationError(f"RegisterHotKey failed: winerror={err}"))
            ready.set()
            return

        ready.set()
        msg = _MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                try:
                    callback()
                except Exception:
                    pass

        _user32.UnregisterHotKey(None, hotkey_id)

    t = threading.Thread(target=_message_loop, daemon=True, name="hotkey-listener")
    t.start()
    ready.wait(timeout=2.0)

    if error_holder:
        raise error_holder[0]

    def unregister() -> None:
        if thread_id_holder:
            _user32.PostThreadMessageW(thread_id_holder[0], WM_QUIT, 0, 0)

    return unregister
