from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from game_bot.config.loader import PROJECT_ROOT
from game_bot.core.models import MatchResult, Point, Rect, StateDetectionResult


@dataclass
class ScriptContext:
    hwnd: int
    script_id: str
    run_id: str | None = None
    step_index: int = 0
    screenshot_path: Path | None = None
    last_match: MatchResult | None = None
    last_match_click_point: Point | None = None
    last_match_click_region: Rect | None = None
    last_state: StateDetectionResult | None = None
    variables: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    background_mode: bool = False

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = f"{self.script_id}_{datetime.now().strftime('%Y%m%d-%H%M%S')}_{uuid4().hex[:8]}"

    @property
    def run_dir(self) -> Path:
        return PROJECT_ROOT / "runtime" / "scripts" / str(self.run_id)

    @property
    def screenshots_dir(self) -> Path:
        return self.run_dir / "screenshots"

    @property
    def debug_dir(self) -> Path:
        return self.run_dir / "debug"

    def screenshot_output_path(self, step_name: str) -> Path:
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        return self.screenshots_dir / f"{self.step_index:04d}_{step_name}.png"

    def transient_screenshot_output_path(self, step_name: str) -> Path:
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        return self.screenshots_dir / f".{self.step_index:04d}_{step_name}.tmp.png"

    def debug_output_path(self, step_name: str, suffix: str) -> Path:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        return self.debug_dir / f"{self.step_index:04d}_{step_name}_{suffix}.png"
