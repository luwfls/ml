import json
import subprocess
import sys
import threading
import time
from typing import Protocol

from game_bot.config.loader import load_settings
from game_bot.core.adb import AdbClient, AdbError, AndroidDisplayInfo, ClientToAndroidMapper
from game_bot.core.dm import BoundDmInput, DmError
from game_bot.core.models import InputResult, Point
from game_bot.core.window import client_to_screen, get_client_size, is_window_alive

SCROLL_SPEED_INTERVALS_MS = {
    "min": 160,
    "slow": 120,
    "normal": 60,
    "fast": 20,
}
INPUT_SUBPROCESS_TIMEOUT_SECONDS = 10
INPUT_SUBPROCESS_RETRIES = 1
_INPUT_SUBPROCESS_LOCK = threading.Lock()

VIRTUAL_KEYS = {
    "esc": 0x1B,
    "escape": 0x1B,
    "enter": 0x0D,
    "return": 0x0D,
    "space": 0x20,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}

ANDROID_KEYCODES = {
    "esc": 111,
    "escape": 111,
    "enter": 66,
    "return": 66,
    "space": 62,
    "tab": 61,
    "backspace": 67,
    "delete": 112,
    "up": 19,
    "down": 20,
    "left": 21,
    "right": 22,
}

ADB_SCROLL_DURATIONS_MS = {
    "min": 700,
    "slow": 550,
    "normal": 350,
    "fast": 200,
}


class InputError(RuntimeError):
    pass


class InputBackend(Protocol):
    def click_client(
        self,
        hwnd: int,
        x: int,
        y: int,
        *,
        button: str = "left",
        duration_ms: int = 50,
        clicks: int = 1,
        interval_ms: int = 0,
    ) -> InputResult:
        ...

    def drag_client(
        self,
        hwnd: int,
        start_x: int,
        start_y: int,
        *,
        direction: str = "left",
        distance: int = 1,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> InputResult:
        ...

    def press_key(
        self,
        hwnd: int,
        key: str,
        *,
        duration_ms: int = 50,
    ) -> InputResult:
        ...

    def scroll_client(
        self,
        hwnd: int,
        *,
        direction: str = "down",
        distance: int = 1,
        speed: str | int = "min",
    ) -> InputResult:
        ...


class AdbInputBackend:
    name = "adb"

    def __init__(self, *, client: AdbClient | None = None) -> None:
        config = _adb_config()
        self.client = client or AdbClient(
            config.get("executable", "adb.exe"),
            str(config.get("serial", "")),
            timeout_seconds=float(config.get("command_timeout_seconds", 10)),
        )
        gestures = config.get("gestures", {})
        self.scroll_swipe_fraction = float(gestures.get("scroll_swipe_fraction", 0.5))
        self.scroll_anchor_x_percent = float(gestures.get("scroll_anchor_x_percent", 50))
        if not 0 < self.scroll_swipe_fraction < 1:
            raise InputError("adb.gestures.scroll_swipe_fraction must be between 0 and 1")
        if not 0 < self.scroll_anchor_x_percent < 100:
            raise InputError("adb.gestures.scroll_anchor_x_percent must be between 0 and 100")

    def click_client(
        self,
        hwnd: int,
        x: int,
        y: int,
        *,
        button: str = "left",
        duration_ms: int = 50,
        clicks: int = 1,
        interval_ms: int = 0,
    ) -> InputResult:
        if button != "left":
            raise InputError("ADB touch input does not support right click")
        if clicks <= 0:
            raise InputError("clicks must be a positive integer")
        if interval_ms < 0:
            raise InputError("interval_ms must be a non-negative integer")
        mapper, display = self._mapper(hwnd)
        client_point = Point(int(x), int(y))
        android_point = mapper.map_point(client_point)
        try:
            for index in range(clicks):
                self.client.tap(android_point.x, android_point.y)
                if index < clicks - 1 and interval_ms > 0:
                    time.sleep(interval_ms / 1000)
        except AdbError as exc:
            raise InputError(str(exc)) from exc
        screen_point = client_to_screen(hwnd, x, y)
        return InputResult(
            success=True,
            hwnd=hwnd,
            client_point=client_point,
            screen_point=screen_point,
            message=(
                f"Click sent by adb serial={self.client.serial}: client=({x}, {y}) "
                f"client_size={mapper.client_size.width}x{mapper.client_size.height} "
                f"android=({android_point.x}, {android_point.y}) "
                f"logical_size={display.logical_size.width}x{display.logical_size.height} clicks={clicks}; "
                f"duration_ms={duration_ms} has no tap hold semantics"
            ),
            backend=self.name,
        )

    def drag_client(
        self,
        hwnd: int,
        start_x: int,
        start_y: int,
        *,
        direction: str = "left",
        distance: int = 1,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> InputResult:
        direction = _drag_direction(direction)
        distance = int(distance)
        if distance <= 0:
            raise InputError("distance must be a positive integer")
        if steps <= 0:
            raise InputError("steps must be a positive integer")
        end_x, end_y = _drag_end_point(start_x, start_y, direction=direction, distance=distance)
        _ensure_client_point(hwnd, start_x, start_y)
        _ensure_client_point(hwnd, end_x, end_y)
        mapper, display = self._mapper(hwnd)
        android_start = mapper.map_point(Point(start_x, start_y))
        android_end = mapper.map_point(Point(end_x, end_y))
        try:
            self.client.swipe(android_start, android_end, duration_ms)
        except AdbError as exc:
            raise InputError(str(exc)) from exc
        screen_point = client_to_screen(hwnd, end_x, end_y)
        return InputResult(
            success=True,
            hwnd=hwnd,
            client_point=Point(end_x, end_y),
            screen_point=screen_point,
            message=(
                f"Drag sent by adb serial={self.client.serial}: client=({start_x}, {start_y})->({end_x}, {end_y}) "
                f"android=({android_start.x}, {android_start.y})->({android_end.x}, {android_end.y}) "
                f"logical_size={display.logical_size.width}x{display.logical_size.height} "
                f"duration_ms={duration_ms}; steps={steps} is not used by adb swipe"
            ),
            backend=self.name,
        )

    def press_key(
        self,
        hwnd: int,
        key: str,
        *,
        duration_ms: int = 50,
    ) -> InputResult:
        if not is_window_alive(hwnd):
            raise InputError(f"Window is not alive: hwnd={hwnd}")
        keycode = _android_keycode(key)
        try:
            self.client.keyevent(keycode)
        except AdbError as exc:
            raise InputError(str(exc)) from exc
        return InputResult(
            success=True,
            hwnd=hwnd,
            client_point=None,
            screen_point=None,
            message=(
                f"Key sent by adb serial={self.client.serial}: key={key}, keycode={keycode}; "
                f"duration_ms={duration_ms} has no key hold semantics"
            ),
            backend=self.name,
        )

    def scroll_client(
        self,
        hwnd: int,
        *,
        direction: str = "down",
        distance: int = 1,
        speed: str | int = "min",
    ) -> InputResult:
        direction = _scroll_direction(direction)
        distance = int(distance)
        if distance <= 0:
            raise InputError("distance must be a positive integer")
        duration_ms = _adb_scroll_duration_ms(speed)
        mapper, display = self._mapper(hwnd)
        viewport = mapper.effective_viewport
        x = viewport.left + round(viewport.width * self.scroll_anchor_x_percent / 100)
        travel = max(1, round(viewport.height * self.scroll_swipe_fraction))
        center_y = viewport.top + viewport.height // 2
        top_y = max(viewport.top, center_y - travel // 2)
        bottom_y = min(viewport.bottom - 1, center_y + travel // 2)
        if direction == "down":
            start, end = Point(x, bottom_y), Point(x, top_y)
        else:
            start, end = Point(x, top_y), Point(x, bottom_y)
        try:
            for index in range(distance):
                self.client.swipe(start, end, duration_ms)
                if index < distance - 1:
                    time.sleep(0.05)
        except AdbError as exc:
            raise InputError(str(exc)) from exc
        return InputResult(
            success=True,
            hwnd=hwnd,
            client_point=None,
            screen_point=None,
            message=(
                f"Scroll sent by adb serial={self.client.serial}: content_direction={direction}, "
                f"android=({start.x}, {start.y})->({end.x}, {end.y}), distance={distance}, "
                f"duration_ms={duration_ms}, logical_size={display.logical_size.width}x{display.logical_size.height}"
            ),
            backend=self.name,
        )

    def _mapper(self, hwnd: int) -> tuple[ClientToAndroidMapper, AndroidDisplayInfo]:
        client_size = get_client_size(hwnd)
        try:
            display = self.client.query_active_display()
        except AdbError as exc:
            raise InputError(str(exc)) from exc
        return ClientToAndroidMapper(client_size, display.logical_size, display.viewport), display


class DmInputBackend:
    name = "dm"

    def __init__(self, *, use_subprocess: bool = True) -> None:
        self.use_subprocess = use_subprocess

    def click_client(
        self,
        hwnd: int,
        x: int,
        y: int,
        *,
        button: str = "left",
        duration_ms: int = 50,
        clicks: int = 1,
        interval_ms: int = 0,
    ) -> InputResult:
        if button not in {"left", "right"}:
            raise InputError("Only left and right click are supported")
        if clicks <= 0:
            raise InputError("clicks must be a positive integer")
        if interval_ms < 0:
            raise InputError("interval_ms must be a non-negative integer")
        if self.use_subprocess:
            return _run_click_subprocess(
                hwnd,
                x,
                y,
                button=button,
                duration_ms=duration_ms,
                clicks=clicks,
                interval_ms=interval_ms,
            )
        _ensure_client_point(hwnd, x, y)
        screen_point = client_to_screen(hwnd, x, y)

        try:
            with BoundDmInput(hwnd) as dm:
                for index in range(clicks):
                    dm.click(x, y, button=button, duration_ms=duration_ms)
                    if index < clicks - 1 and interval_ms > 0:
                        dm.delay(interval_ms)
        except DmError as exc:
            raise InputError(str(exc)) from exc

        return InputResult(
            success=True,
            hwnd=hwnd,
            client_point=Point(x, y),
            screen_point=screen_point,
            message=f"Click sent by dm at client point ({x}, {y}), screen point ({screen_point.x}, {screen_point.y}), clicks={clicks}",
            backend=self.name,
        )

    def drag_client(
        self,
        hwnd: int,
        start_x: int,
        start_y: int,
        *,
        direction: str = "left",
        distance: int = 1,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> InputResult:
        direction = _drag_direction(direction)
        distance = int(distance)
        if distance <= 0:
            raise InputError("distance must be a positive integer")
        if steps <= 0:
            raise InputError("steps must be a positive integer")
        end_x, end_y = _drag_end_point(start_x, start_y, direction=direction, distance=distance)
        if self.use_subprocess:
            return _run_drag_subprocess(
                hwnd,
                start_x,
                start_y,
                direction=direction,
                distance=distance,
                duration_ms=duration_ms,
                steps=steps,
            )
        _ensure_client_point(hwnd, start_x, start_y)
        _ensure_client_point(hwnd, end_x, end_y)
        screen_point = client_to_screen(hwnd, end_x, end_y)
        try:
            with BoundDmInput(hwnd) as dm:
                dm.drag(start_x, start_y, end_x, end_y, duration_ms=duration_ms, steps=steps)
        except DmError as exc:
            raise InputError(str(exc)) from exc
        return InputResult(
            success=True,
            hwnd=hwnd,
            client_point=Point(end_x, end_y),
            screen_point=screen_point,
            message=(
                f"Drag sent by dm: start=({start_x}, {start_y}) end=({end_x}, {end_y}) "
                f"direction={direction} distance={distance} duration_ms={duration_ms} steps={steps}"
            ),
            backend=self.name,
        )

    def press_key(
        self,
        hwnd: int,
        key: str,
        *,
        duration_ms: int = 50,
    ) -> InputResult:
        if self.use_subprocess:
            return _run_key_subprocess(hwnd, key, duration_ms=duration_ms)
        if not is_window_alive(hwnd):
            raise InputError(f"Window is not alive: hwnd={hwnd}")
        virtual_key = _virtual_key(key)
        try:
            with BoundDmInput(hwnd) as dm:
                dm.press_key(virtual_key, duration_ms=duration_ms)
        except DmError as exc:
            raise InputError(str(exc)) from exc
        return InputResult(
            success=True,
            hwnd=hwnd,
            client_point=None,
            screen_point=None,
            message=f"Key sent by dm: {key}",
            backend=self.name,
        )

    def scroll_client(
        self,
        hwnd: int,
        *,
        direction: str = "down",
        distance: int = 1,
        speed: str | int = "min",
    ) -> InputResult:
        direction = _scroll_direction(direction)
        distance = int(distance)
        if distance <= 0:
            raise InputError("distance must be a positive integer")
        interval_ms = _scroll_speed_interval_ms(speed)
        if self.use_subprocess:
            return _run_scroll_subprocess(hwnd, direction=direction, distance=distance, speed=speed)
        if not is_window_alive(hwnd):
            raise InputError(f"Window is not alive: hwnd={hwnd}")
        try:
            with BoundDmInput(hwnd) as dm:
                dm.scroll(direction, distance=distance, interval_ms=interval_ms)
        except DmError as exc:
            raise InputError(str(exc)) from exc
        return InputResult(
            success=True,
            hwnd=hwnd,
            client_point=None,
            screen_point=None,
            message=f"Scroll sent by dm: direction={direction}, distance={distance}, speed={speed}, interval_ms={interval_ms}",
            backend=self.name,
        )


ForegroundInputBackend = DmInputBackend


def input_backend_from_name(name: str | None) -> InputBackend:
    normalized = str(name or "").strip().lower().replace("-", "_")
    if not normalized or normalized == "auto":
        settings = load_settings()
        input_config = settings.get("input", {})
        configured = input_config.get("backend", "adb") if isinstance(input_config, dict) else "adb"
        normalized = str(configured).strip().lower().replace("-", "_")
    if normalized == "adb":
        return AdbInputBackend()
    if normalized == "dm":
        return DmInputBackend()
    raise InputError(f"Unsupported input backend: {name or normalized}. Use adb or dm.")


def default_input_backend() -> InputBackend:
    return input_backend_from_name(None)


def _direct_backend() -> DmInputBackend:
    return DmInputBackend(use_subprocess=False)


def _input_result_from_payload(payload: dict) -> InputResult:
    client = payload.get("client_point")
    screen = payload.get("screen_point")
    return InputResult(
        success=bool(payload.get("success")),
        hwnd=int(payload.get("hwnd")),
        client_point=Point(int(client["x"]), int(client["y"])) if isinstance(client, dict) else None,
        screen_point=Point(int(screen["x"]), int(screen["y"])) if isinstance(screen, dict) else None,
        message=str(payload.get("message") or ""),
        backend=str(payload.get("backend") or "dm"),
    )


def _run_input_subprocess(args: list[str], *, retries: int = 0) -> InputResult:
    command = [sys.executable, "-m", "game_bot.core.input", *args]
    last_timeout: subprocess.TimeoutExpired | None = None
    with _INPUT_SUBPROCESS_LOCK:
        for attempt in range(retries + 1):
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=INPUT_SUBPROCESS_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                last_timeout = exc
                if attempt < retries:
                    time.sleep(0.2)
                    continue
                detail = _timeout_detail(command, exc)
                raise InputError(detail) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise InputError(f"dm input subprocess failed: exit={completed.returncode}; {detail}")
            try:
                payload = json.loads(completed.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError) as exc:
                raise InputError(f"dm input subprocess returned invalid JSON: {completed.stdout.strip()}") from exc
            if not isinstance(payload, dict):
                raise InputError("dm input subprocess returned invalid payload.")
            return _input_result_from_payload(payload)
    raise InputError(_timeout_detail(command, last_timeout))


def _timeout_detail(command: list[str], exc: subprocess.TimeoutExpired | None) -> str:
    stdout = _timeout_stream_text(exc.stdout if exc is not None else None)
    stderr = _timeout_stream_text(exc.stderr if exc is not None else None)
    details = []
    if stdout:
        details.append(f"stdout={stdout}")
    if stderr:
        details.append(f"stderr={stderr}")
    suffix = f"; {'; '.join(details)}" if details else ""
    return f"dm input subprocess timed out after {INPUT_SUBPROCESS_TIMEOUT_SECONDS}s: {command}{suffix}"


def _timeout_stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return value.strip()


def _run_click_subprocess(
    hwnd: int,
    x: int,
    y: int,
    *,
    button: str,
    duration_ms: int,
    clicks: int,
    interval_ms: int,
) -> InputResult:
    return _run_input_subprocess(
        ["click", str(hwnd), str(x), str(y), button, str(duration_ms), str(clicks), str(interval_ms)],
        retries=INPUT_SUBPROCESS_RETRIES,
    )


def _run_drag_subprocess(
    hwnd: int,
    start_x: int,
    start_y: int,
    *,
    direction: str,
    distance: int,
    duration_ms: int,
    steps: int,
) -> InputResult:
    return _run_input_subprocess(
        ["drag", str(hwnd), str(start_x), str(start_y), direction, str(distance), str(duration_ms), str(steps)],
        retries=INPUT_SUBPROCESS_RETRIES,
    )


def _run_key_subprocess(hwnd: int, key: str, *, duration_ms: int) -> InputResult:
    return _run_input_subprocess(["key", str(hwnd), key, str(duration_ms)], retries=INPUT_SUBPROCESS_RETRIES)


def _run_scroll_subprocess(hwnd: int, *, direction: str, distance: int, speed: str | int) -> InputResult:
    return _run_input_subprocess(["scroll", str(hwnd), direction, str(distance), str(speed)])


def click_client(
    hwnd: int,
    x: int,
    y: int,
    *,
    backend: InputBackend | None = None,
    button: str = "left",
    duration_ms: int = 50,
    clicks: int = 1,
    interval_ms: int = 0,
) -> InputResult:
    selected_backend = backend or default_input_backend()
    return selected_backend.click_client(
        hwnd,
        x,
        y,
        button=button,
        duration_ms=duration_ms,
        clicks=clicks,
        interval_ms=interval_ms,
    )


def click_backend_from_name(name: str | None) -> InputBackend | None:
    return input_backend_from_name(name)


def press_key(
    hwnd: int,
    key: str,
    *,
    backend: InputBackend | None = None,
    duration_ms: int = 50,
) -> InputResult:
    selected_backend = backend or default_input_backend()
    return selected_backend.press_key(hwnd, key, duration_ms=duration_ms)


def scroll_client(
    hwnd: int,
    *,
    backend: InputBackend | None = None,
    direction: str = "down",
    distance: int = 1,
    speed: str | int = "min",
) -> InputResult:
    selected_backend = backend or default_input_backend()
    return selected_backend.scroll_client(hwnd, direction=direction, distance=distance, speed=speed)


def drag_client(
    hwnd: int,
    start_x: int,
    start_y: int,
    *,
    backend: InputBackend | None = None,
    direction: str = "left",
    distance: int = 1,
    duration_ms: int = 300,
    steps: int = 12,
) -> InputResult:
    selected_backend = backend or default_input_backend()
    return selected_backend.drag_client(
        hwnd,
        start_x,
        start_y,
        direction=direction,
        distance=distance,
        duration_ms=duration_ms,
        steps=steps,
    )


def _ensure_client_point(hwnd: int, x: int, y: int) -> None:
    if not is_window_alive(hwnd):
        raise InputError(f"Window is not alive: hwnd={hwnd}")
    size = get_client_size(hwnd)
    if x < 0 or y < 0 or x >= size.width or y >= size.height:
        raise InputError(
            f"Client point is outside the window: x={x} y={y} "
            f"client_width={size.width} client_height={size.height}"
        )


def _virtual_key(key: str) -> int:
    normalized = key.strip().lower()
    if len(normalized) == 1:
        return ord(normalized.upper())
    virtual_key = VIRTUAL_KEYS.get(normalized)
    if virtual_key is None:
        raise InputError(f"Unsupported key: {key}")
    return virtual_key


def _scroll_direction(direction: str) -> str:
    normalized = str(direction).strip().lower()
    if normalized in {"up", "down"}:
        return normalized
    raise InputError(f"Unsupported scroll direction: {direction}. Use up or down.")


def _drag_direction(direction: str) -> str:
    normalized = str(direction).strip().lower()
    if normalized in {"left", "right", "up", "down"}:
        return normalized
    raise InputError(f"Unsupported drag direction: {direction}. Use left, right, up, or down.")


def _drag_end_point(start_x: int, start_y: int, *, direction: str, distance: int) -> tuple[int, int]:
    if direction == "left":
        return start_x - distance, start_y
    if direction == "right":
        return start_x + distance, start_y
    if direction == "up":
        return start_x, start_y - distance
    if direction == "down":
        return start_x, start_y + distance
    raise InputError(f"Unsupported drag direction: {direction}. Use left, right, up, or down.")


def _scroll_speed_interval_ms(speed: str | int) -> int:
    if isinstance(speed, int):
        if speed < 0:
            raise InputError("speed must be non-negative")
        return speed
    text = str(speed).strip().lower()
    if text.isdigit():
        return int(text)
    interval_ms = SCROLL_SPEED_INTERVALS_MS.get(text)
    if interval_ms is None:
        raise InputError(f"Unsupported scroll speed: {speed}. Use min, slow, normal, fast, or a non-negative interval in ms.")
    return interval_ms


def _android_keycode(key: str) -> int:
    normalized = key.strip().lower()
    keycode = ANDROID_KEYCODES.get(normalized)
    if keycode is None:
        raise InputError(f"Unsupported ADB key: {key}. Use a named control key.")
    return keycode


def _adb_scroll_duration_ms(speed: str | int) -> int:
    if isinstance(speed, int):
        if speed < 0:
            raise InputError("speed must be non-negative")
        return speed
    text = str(speed).strip().lower()
    if text.isdigit():
        return int(text)
    duration_ms = ADB_SCROLL_DURATIONS_MS.get(text)
    if duration_ms is None:
        raise InputError(f"Unsupported ADB scroll speed: {speed}. Use min, slow, normal, fast, or milliseconds.")
    return duration_ms


def _adb_config() -> dict:
    config = load_settings().get("adb", {})
    return config if isinstance(config, dict) else {}


def _payload_from_result(result: InputResult) -> dict:
    return {
        "success": result.success,
        "hwnd": result.hwnd,
        "client_point": {"x": result.client_point.x, "y": result.client_point.y} if result.client_point else None,
        "screen_point": {"x": result.screen_point.x, "y": result.screen_point.y} if result.screen_point else None,
        "message": result.message,
        "backend": result.backend,
    }


def _main(argv: list[str]) -> int:
    if not argv:
        raise InputError("Missing input command.")
    command = argv[0]
    backend = _direct_backend()
    if command == "click":
        if len(argv) != 8:
            raise InputError("click command requires hwnd x y button duration_ms clicks interval_ms.")
        result = backend.click_client(
            int(argv[1]),
            int(argv[2]),
            int(argv[3]),
            button=argv[4],
            duration_ms=int(argv[5]),
            clicks=int(argv[6]),
            interval_ms=int(argv[7]),
        )
    elif command == "key":
        if len(argv) != 4:
            raise InputError("key command requires hwnd key duration_ms.")
        result = backend.press_key(int(argv[1]), argv[2], duration_ms=int(argv[3]))
    elif command == "scroll":
        if len(argv) != 5:
            raise InputError("scroll command requires hwnd direction distance speed.")
        result = backend.scroll_client(int(argv[1]), direction=argv[2], distance=int(argv[3]), speed=argv[4])
    elif command == "drag":
        if len(argv) != 8:
            raise InputError("drag command requires hwnd start_x start_y direction distance duration_ms steps.")
        result = backend.drag_client(
            int(argv[1]),
            int(argv[2]),
            int(argv[3]),
            direction=argv[4],
            distance=int(argv[5]),
            duration_ms=int(argv[6]),
            steps=int(argv[7]),
        )
    else:
        raise InputError(f"Unsupported input command: {command}")
    print(json.dumps(_payload_from_result(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
