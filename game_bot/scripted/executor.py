from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from game_bot.config.loader import PROJECT_ROOT
from game_bot.scripted.context import ScriptContext
from game_bot.scripted.runtime import ScriptPause, ScriptRuntime

RuntimeStep = Callable[[ScriptRuntime], None]
ScriptBody = Callable[["ScriptExecutor"], None]

TEMPLATES_ICONS_DIR = PROJECT_ROOT / "templates" / "icons"


@dataclass(frozen=True)
class ScriptExecutorConfig:
    script_id: str
    entry_steps: tuple[RuntimeStep, ...] = ()
    template_group: str | None = None
    template_folder: str | Path | None = None


class ScriptExecutor:
    def __init__(self, runtime: ScriptRuntime, config: ScriptExecutorConfig) -> None:
        self.runtime = runtime
        self.context = runtime.context
        self.config = config
        self.template_group = _normalized_group(config.template_group, config.template_folder)
        self.template_folder = _normalized_folder(config.template_folder, self.template_group)
        self.context.variables["template_group"] = self.template_group or ""
        self.context.variables["template_folder"] = self.template_folder or ""

    def run_entry(self) -> None:
        for step in self.config.entry_steps:
            step(self.runtime)

    def template(self, filename: str, *, group: str | None = None, folder: str | Path | None = None) -> str:
        raw = str(filename).strip()
        if not raw:
            raise ValueError("template filename is required")
        if raw.startswith("group:") or "/" in raw or "\\" in raw:
            return raw.replace("\\", "/")

        resolved_group = _normalized_group(group, folder)
        resolved_folder = _normalized_folder(folder, resolved_group)
        base_folder = resolved_folder or self.template_folder or "templates/icons"
        name = raw if raw.lower().endswith(".png") else f"{raw}.png"
        return f"{base_folder}/{name}".replace("\\", "/")

    def templates(
        self,
        *filenames: str,
        group: str | None = None,
        folder: str | Path | None = None,
    ) -> tuple[str, ...]:
        return tuple(self.template(filename, group=group, folder=folder) for filename in filenames)

    def group_reference(self, group: str | None = None) -> str:
        resolved_group = _normalized_group(group, None) or self.template_group
        if not resolved_group:
            raise ValueError("template group is not configured for this executor")
        return f"group:{resolved_group}"


def execute_script(
    hwnd: int,
    *,
    config: ScriptExecutorConfig,
    body: ScriptBody,
    dry_run: bool = False,
    background_mode: bool = False,
) -> ScriptContext:
    context = ScriptContext(
        hwnd=hwnd,
        script_id=config.script_id,
        dry_run=dry_run,
        background_mode=background_mode,
    )
    runtime = ScriptRuntime(context)
    executor = ScriptExecutor(runtime, config)
    runtime.focus()
    try:
        executor.run_entry()
        body(executor)
        runtime.log("script completed")
    except ScriptPause as exc:
        context.variables["pause_reason"] = exc.reason
        runtime.log(f"script paused: {exc.reason}")
        raise
    return context


def _normalized_group(group: str | None, folder: str | Path | None) -> str | None:
    raw_group = str(group or "").strip().replace("\\", "/")
    if raw_group:
        return raw_group

    if folder in (None, ""):
        return None
    raw_folder = str(folder).strip().replace("\\", "/")
    if not raw_folder:
        return None
    if raw_folder.startswith("templates/icons/"):
        derived = raw_folder.removeprefix("templates/icons/").strip("/")
        return derived or None

    resolved = Path(raw_folder)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    try:
        relative = resolved.resolve().relative_to(TEMPLATES_ICONS_DIR.resolve())
    except ValueError:
        return None
    return relative.as_posix() if relative.parts else None


def _normalized_folder(folder: str | Path | None, group: str | None) -> str | None:
    if folder not in (None, ""):
        raw_folder = str(folder).strip().replace("\\", "/").strip("/")
        if raw_folder:
            if raw_folder.startswith("templates/"):
                return raw_folder
            return f"templates/icons/{raw_folder}"
    if group:
        return f"templates/icons/{group}"
    return None
