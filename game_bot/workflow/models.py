from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from game_bot.core.models import ActionResult, MatchResult


@dataclass(frozen=True)
class WorkflowTransition:
    when: str
    to: str


@dataclass(frozen=True)
class WorkflowNodeDefinition:
    id: str
    type: str
    name: str | None = None
    next: str | None = None
    on_fail: str | None = None
    timeout_ms: int | None = None
    retries: int = 0
    description: str | None = None
    transitions: tuple[WorkflowTransition, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    start: str
    nodes: dict[str, WorkflowNodeDefinition]
    max_steps: int = 100
    max_failures: int = 3


@dataclass(frozen=True)
class WorkflowNodeResult:
    success: bool
    status: str
    node_id: str
    node_type: str
    message: str
    next_node: str | None = None
    screenshot_path: Path | None = None
    debug_paths: tuple[Path, ...] = ()
    match_result: MatchResult | None = None
    action_result: ActionResult | None = None
    elapsed_ms: int | None = None
