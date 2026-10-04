from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from game_bot.config.loader import PROJECT_ROOT
from game_bot.core.models import MatchResult, Point, Rect, StateDetectionResult


@dataclass
class WorkflowContext:
    hwnd: int
    workflow_id: str
    run_id: str
    step_index: int = 0
    screenshot_path: Path | None = None
    last_match: MatchResult | None = None
    last_match_click_point: Point | None = None
    last_match_click_region: Rect | None = None
    last_match_click_points: list[Point] = field(default_factory=list)
    last_match_click_regions: list[Rect] = field(default_factory=list)
    last_state: StateDetectionResult | None = None
    variables: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    process_name: str | None = None
    window_title: str | None = None
    exact: bool = False
    workflow_stack: list[str] = field(default_factory=list)

    @property
    def run_dir(self) -> Path:
        return PROJECT_ROOT / "runtime" / "workflows" / self.run_id

    @property
    def screenshots_dir(self) -> Path:
        return self.run_dir / "screenshots"

    @property
    def debug_dir(self) -> Path:
        return self.run_dir / "debug"

    def screenshot_output_path(self, node_id: str) -> Path:
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        return self.screenshots_dir / f"{self.step_index:04d}_{node_id}.png"

    def debug_output_path(self, node_id: str, suffix: str) -> Path:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        return self.debug_dir / f"{self.step_index:04d}_{node_id}_{suffix}.png"
