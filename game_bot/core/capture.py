import ctypes
from ctypes import wintypes
from datetime import datetime
from multiprocessing import get_context
from pathlib import Path
from queue import Empty
from time import sleep
from typing import Any, Literal

import cv2
import mss
import mss.tools
import numpy as np

from game_bot.config.loader import PROJECT_ROOT, ensure_runtime_dirs
from game_bot.core.dm import BoundDmWindow, DmError
from game_bot.core.geometry import offset_rect
from game_bot.core.models import CaptureResult, Rect, Size
from game_bot.core.window import bring_window_to_foreground, get_window_info

SCREENSHOTS_DIR = PROJECT_ROOT / "runtime" / "screenshots"
DEFAULT_CAPTURE_TIMEOUT_MS = 3000
DEFAULT_CAPTURE_RETRIES = 2
DEFAULT_CAPTURE_RETRY_DELAY_MS = 200

CaptureBackend = Literal["auto", "window", "desktop", "dm"]

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


class BITMAPINFO(ctypes.Structure):
    _fields_ = (("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3))


user32.GetDC.argtypes = (wintypes.HWND,)
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
user32.PrintWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = (
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
)
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = (
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
)
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteObject.restype = wintypes.BOOL


class CaptureError(RuntimeError):
    pass


def default_screenshot_path(hwnd: int, *, suffix: str = "client") -> Path:
    ensure_runtime_dirs()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return SCREENSHOTS_DIR / f"{timestamp}_hwnd{hwnd:08x}_{suffix}.png"


def _capture_mss_direct(monitor: dict[str, int], path: Path) -> None:
    try:
        with mss.mss() as screenshotter:
            image = screenshotter.grab(monitor)
            mss.tools.to_png(image.rgb, image.size, output=str(path))
    except Exception as exc:
        raise CaptureError(f"mss backend failed: {type(exc).__name__}: {exc}") from exc

    if not path.exists():
        raise CaptureError(f"mss backend completed but did not create output file: {path}")


def _read_saved_image(path: Path, backend_name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise CaptureError(f"{backend_name} backend failed to read saved image: {path}")
    return image


def _bitmap_to_image(memory_dc: wintypes.HDC, bitmap: wintypes.HBITMAP, width: int, height: int) -> np.ndarray:
    bitmap_info = BITMAPINFO()
    bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bitmap_info.bmiHeader.biWidth = width
    bitmap_info.bmiHeader.biHeight = -height
    bitmap_info.bmiHeader.biPlanes = 1
    bitmap_info.bmiHeader.biBitCount = 32
    bitmap_info.bmiHeader.biCompression = BI_RGB

    buffer = ctypes.create_string_buffer(width * height * 4)
    scan_lines = gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(bitmap_info), DIB_RGB_COLORS)
    if scan_lines == 0:
        raise _api_error("GetDIBits")

    return np.frombuffer(buffer, dtype=np.uint8).reshape((height, width, 4))[:, :, :3]


def _save_image(path: Path, image: np.ndarray, backend_name: str) -> None:
    extension = path.suffix or ".png"
    ok, encoded = cv2.imencode(extension, image)
    if not ok:
        raise CaptureError(f"{backend_name} backend failed to encode image: {path}")
    try:
        path.write_bytes(encoded.tobytes())
    except OSError as exc:
        raise CaptureError(f"{backend_name} backend failed to save image: {path}: {exc}") from exc
    if not path.exists():
        raise CaptureError(f"{backend_name} backend completed but did not create output file: {path}")


def _capture_gdi(monitor: dict[str, int], path: Path) -> None:
    width = monitor["width"]
    height = monitor["height"]
    source_dc = user32.GetDC(None)
    if not source_dc:
        raise _api_error("GetDC")

    memory_dc = None
    bitmap = None
    old_object = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(source_dc)
        if not memory_dc:
            raise _api_error("CreateCompatibleDC")
        bitmap = gdi32.CreateCompatibleBitmap(source_dc, width, height)
        if not bitmap:
            raise _api_error("CreateCompatibleBitmap")
        old_object = gdi32.SelectObject(memory_dc, bitmap)
        if not old_object:
            raise _api_error("SelectObject")
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, source_dc, monitor["left"], monitor["top"], SRCCOPY):
            raise _api_error("BitBlt")

        _save_image(path, _bitmap_to_image(memory_dc, bitmap, width, height), "gdi")
    finally:
        if old_object and memory_dc:
            gdi32.SelectObject(memory_dc, old_object)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, source_dc)


def _crop_client_region(image: np.ndarray, region: Rect | None) -> np.ndarray:
    if region is None:
        return image
    height, width = image.shape[:2]
    left = max(0, min(region.left, width))
    top = max(0, min(region.top, height))
    right = max(0, min(region.right, width))
    bottom = max(0, min(region.bottom, height))
    if right <= left or bottom <= top:
        raise CaptureError(f"Invalid client capture region: {format_rect(region)}")
    return image[top:bottom, left:right]


def _validate_backend_image(image: np.ndarray, backend_name: str) -> None:
    if image.size == 0:
        raise CaptureError(f"{backend_name} backend produced an empty image")
    if np.all(image == image.reshape(-1, image.shape[-1])[0]):
        raise CaptureError(f"{backend_name} backend produced a blank single-color image")


def _capture_window_print_window(hwnd: int, width: int, height: int, path: Path, *, region: Rect | None = None) -> None:
    source_dc = user32.GetDC(hwnd)
    if not source_dc:
        raise _api_error("GetDC(hwnd)")

    memory_dc = None
    bitmap = None
    old_object = None
    errors = []
    try:
        memory_dc = gdi32.CreateCompatibleDC(source_dc)
        if not memory_dc:
            raise _api_error("CreateCompatibleDC")
        bitmap = gdi32.CreateCompatibleBitmap(source_dc, width, height)
        if not bitmap:
            raise _api_error("CreateCompatibleBitmap")
        old_object = gdi32.SelectObject(memory_dc, bitmap)
        if not old_object:
            raise _api_error("SelectObject")

        for flags in (PW_CLIENTONLY, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            ctypes.set_last_error(0)
            if not user32.PrintWindow(hwnd, memory_dc, flags):
                errors.append(f"PrintWindow flags={flags} failed with Windows error {ctypes.get_last_error()}")
                continue
            try:
                image = _crop_client_region(_bitmap_to_image(memory_dc, bitmap, width, height), region)
                _validate_backend_image(image, "window")
                _save_image(path, image, "window")
                return
            except CaptureError as exc:
                errors.append(f"PrintWindow flags={flags}: {exc}")

        if gdi32.BitBlt(memory_dc, 0, 0, width, height, source_dc, 0, 0, SRCCOPY):
            try:
                image = _crop_client_region(_bitmap_to_image(memory_dc, bitmap, width, height), region)
                _validate_backend_image(image, "window")
                _save_image(path, image, "window")
                return
            except CaptureError as exc:
                errors.append(f"client BitBlt: {exc}")
        else:
            errors.append(f"client BitBlt failed with Windows error {ctypes.get_last_error()}")

        raise CaptureError("; ".join(errors) or "window backend failed without an error message")
    finally:
        if old_object and memory_dc:
            gdi32.SelectObject(memory_dc, old_object)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, source_dc)


def _validate_capture_region(region: Rect, width: int, height: int, backend_name: str) -> None:
    if region.left < 0 or region.top < 0 or region.right > width or region.bottom > height:
        raise CaptureError(
            f"{backend_name} backend region is outside client bounds: {format_rect(region)}; "
            f"client_width={width} client_height={height}"
        )
    if region.width <= 0 or region.height <= 0:
        raise CaptureError(f"{backend_name} backend region must have positive width and height: {format_rect(region)}")


def _capture_dm(hwnd: int, width: int, height: int, path: Path, *, region: Rect | None = None) -> None:
    capture_region = region or Rect(0, 0, width, height)
    _validate_capture_region(capture_region, width, height, "dm")

    try:
        with BoundDmWindow(hwnd) as dm:
            result = dm.capture_png(
                capture_region.left,
                capture_region.top,
                capture_region.right,
                capture_region.bottom,
                str(path),
            )
    except DmError as exc:
        raise CaptureError(f"dm backend failed to capture hwnd={hwnd}: {exc}") from exc

    if result != 1:
        raise CaptureError(f"dm backend CapturePng failed: result={result}, path={path}")
    if not path.exists():
        raise CaptureError(f"dm backend completed but did not create output file: {path}")

    image = _read_saved_image(path, "dm")
    _validate_backend_image(image, "dm")
    expected_height = capture_region.height
    expected_width = capture_region.width
    actual_height, actual_width = image.shape[:2]
    if actual_width != expected_width or actual_height != expected_height:
        raise CaptureError(
            f"dm backend produced unexpected image size: actual={actual_width}x{actual_height}, "
            f"expected={expected_width}x{expected_height}"
        )


def _capture_worker(monitor: dict[str, int], output_path: str, result_queue: Any) -> None:
    try:
        _capture_mss_direct(monitor, Path(output_path))
        result_queue.put(("ok", ""))
    except BaseException as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _capture_once_with_timeout(monitor: dict[str, int], path: Path, timeout_ms: int) -> None:
    context = get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=_capture_worker, args=(monitor, str(path), result_queue))
    process.start()
    process.join(timeout_ms / 1000)

    if process.is_alive():
        process.terminate()
        process.join(1)
        raise CaptureError(f"Capture timed out after {timeout_ms} ms")

    try:
        status, message = result_queue.get_nowait()
    except Empty:
        if process.exitcode == 0 and path.exists():
            return
        raise CaptureError(f"Capture worker exited with code {process.exitcode}")

    if status == "error":
        raise CaptureError(message)
    if not path.exists():
        raise CaptureError(f"Capture worker completed but did not create output file: {path}")


def _capture_with_retries(
    monitor: dict[str, int],
    path: Path,
    *,
    timeout_ms: int,
    retries: int,
    retry_delay_ms: int,
) -> None:
    if timeout_ms <= 0:
        raise CaptureError(f"capture_timeout_ms must be positive: {timeout_ms}")
    if retries < 0:
        raise CaptureError(f"capture_retries must be non-negative: {retries}")
    if retry_delay_ms < 0:
        raise CaptureError(f"capture_retry_delay_ms must be non-negative: {retry_delay_ms}")

    attempts = retries + 1
    last_error: CaptureError | None = None
    for attempt in range(1, attempts + 1):
        try:
            _capture_once_with_timeout(monitor, path, timeout_ms)
            return
        except CaptureError as exc:
            last_error = exc
            if attempt < attempts:
                sleep(retry_delay_ms / 1000)

    raise CaptureError(
        f"Failed to capture client area to {path} after {attempts} attempt(s), "
        f"timeout {timeout_ms} ms: {last_error}"
    )


def capture_client_to_file(
    hwnd: int,
    output_path: str | Path | None = None,
    *,
    region: Rect | None = None,
    bring_to_front: bool = False,
    foreground_wait_ms: int = 200,
    capture_timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS,
    capture_retries: int = DEFAULT_CAPTURE_RETRIES,
    retry_delay_ms: int = DEFAULT_CAPTURE_RETRY_DELAY_MS,
    backend: CaptureBackend = "auto",
) -> CaptureResult:
    if backend not in {"auto", "window", "desktop", "dm"}:
        raise CaptureError(f"Unsupported capture backend: {backend}")

    if bring_to_front:
        info = bring_window_to_foreground(hwnd, wait_ms=foreground_wait_ms)
    else:
        info = get_window_info(hwnd)

    client_rect = Rect(0, 0, info.client_size.width, info.client_size.height)
    result_rect = info.client_rect_screen if region is None else offset_rect(region, info.client_origin_screen.x, info.client_origin_screen.y)
    if region is not None:
        client_rect = region

    if result_rect.width <= 0 or result_rect.height <= 0:
        raise CaptureError(f"Invalid capture rect: {format_rect(result_rect)}")

    path = Path(output_path) if output_path is not None else default_screenshot_path(hwnd)
    path.parent.mkdir(parents=True, exist_ok=True)

    if backend == "dm":
        _capture_dm(hwnd, info.client_size.width, info.client_size.height, path, region=region)
        return CaptureResult(
            path=path,
            hwnd=hwnd,
            title=info.title,
            rect=result_rect,
            size=Size(result_rect.width, result_rect.height),
        )

    window_error: CaptureError | None = None
    if backend in {"auto", "window"}:
        try:
            _capture_window_print_window(hwnd, info.client_size.width, info.client_size.height, path, region=region)
        except CaptureError as exc:
            window_error = exc
            if backend == "window":
                raise CaptureError(f"Failed to capture client area to {path}; rect={format_rect(client_rect)}; window={exc}") from exc
        else:
            return CaptureResult(
                path=path,
                hwnd=hwnd,
                title=info.title,
                rect=result_rect,
                size=Size(result_rect.width, result_rect.height),
            )

    monitor = {
        "left": result_rect.left,
        "top": result_rect.top,
        "width": result_rect.width,
        "height": result_rect.height,
    }

    try:
        _capture_gdi(monitor, path)
    except CaptureError as gdi_error:
        try:
            _capture_with_retries(
                monitor,
                path,
                timeout_ms=capture_timeout_ms,
                retries=capture_retries,
                retry_delay_ms=retry_delay_ms,
            )
        except CaptureError as subprocess_error:
            raise CaptureError(
                f"Failed to capture client area to {path}; rect={format_rect(result_rect)}; "
                f"window={window_error}; gdi={gdi_error}; mss_subprocess={subprocess_error}"
            ) from subprocess_error

    return CaptureResult(
        path=path,
        hwnd=hwnd,
        title=info.title,
        rect=result_rect,
        size=Size(result_rect.width, result_rect.height),
    )


def format_rect(rect: Rect) -> str:
    return (
        f"left={rect.left} top={rect.top} right={rect.right} bottom={rect.bottom} "
        f"width={rect.width} height={rect.height}"
    )


def _api_error(function_name: str) -> CaptureError:
    return CaptureError(f"gdi backend {function_name} failed with Windows error {ctypes.get_last_error()}")
