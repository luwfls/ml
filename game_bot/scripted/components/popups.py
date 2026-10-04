from __future__ import annotations

from game_bot.scripted.runtime import ScriptRuntime


def dismiss_configured_popup(runtime: ScriptRuntime, *, step_prefix: str = "popup_probe") -> bool:
    _ = (runtime, step_prefix)
    return False
