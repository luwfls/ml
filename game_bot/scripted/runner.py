from __future__ import annotations

from collections.abc import Callable

from game_bot.config.loader import load_settings
from game_bot.core.models import Rect
from game_bot.core.window import (
    WindowInfo,
    WindowError,
    ensure_window_client_size,
    find_window_by_process_name,
    find_window_by_title,
    get_window_info,
    prepare_window_for_automation,
)
from game_bot.scripted.context import ScriptContext
from game_bot.scripted.loop_script import (
    list_template_loop_scripts,
    run_template_loop_script_by_name,
)

ScriptEntry = Callable[[int], ScriptContext]


def list_scripts() -> list[str]:
    return sorted(list_template_loop_scripts())


def resolve_script(name: str) -> Callable[..., ScriptContext]:
    if name in set(list_template_loop_scripts()):
        return lambda hwnd, *, dry_run=False, background_mode=False: run_template_loop_script_by_name(
            name,
            hwnd,
            dry_run=dry_run,
            background_mode=background_mode,
        )
    available = ", ".join(list_scripts())
    raise ValueError(f"Unknown scripted flow: {name}. Available: {available}")


def find_default_game_window() -> int:
    settings = load_settings()
    game = settings.get("game") or {}
    process_name = str(game.get("process_name") or "").strip()
    window_title = str(game.get("window_title") or "").strip()
    title_first = str(game.get("window_mode") or "").strip().lower() == "android_emulator"
    attempts: list[str] = []
    candidates = (("title", window_title), ("process", process_name)) if title_first else (("process", process_name), ("title", window_title))
    for kind, value in candidates:
        if not value:
            continue
        try:
            return find_window_by_title(value) if kind == "title" else find_window_by_process_name(value)
        except WindowError as exc:
            attempts.append(f"{kind}={value!r}: {exc}")
    if attempts:
        raise WindowError("No configured game window found; " + " | ".join(attempts))
    raise ValueError("No game.process_name or game.window_title configured in settings.yaml")


def prepare_game_window(hwnd: int) -> WindowInfo:
    settings = load_settings()
    game = settings.get("game") or {}
    window_size = game.get("window_size") or {}
    width = int(window_size.get("width") or 0)
    height = int(window_size.get("height") or 0)

    info = get_window_info(hwnd)
    if width > 0 and height > 0:
        info = ensure_window_client_size(hwnd, width, height)
        info = prepare_window_for_automation(
            hwnd,
            rect=Rect(
                info.window_rect.left,
                info.window_rect.top,
                info.window_rect.left + info.window_rect.width,
                info.window_rect.top + info.window_rect.height,
            ),
            topmost=True,
        )
    else:
        info = prepare_window_for_automation(hwnd, topmost=True)
    return info


def run_script_by_name(name: str, hwnd: int, *, dry_run: bool = False, background_mode: bool = False) -> ScriptContext:
    script = resolve_script(name)
    return script(hwnd, dry_run=dry_run, background_mode=background_mode)
