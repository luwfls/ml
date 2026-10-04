from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from game_bot.workflow.context import WorkflowContext
from game_bot.workflow.models import WorkflowNodeResult

if TYPE_CHECKING:
    from game_bot.workflow.engine import WorkflowRunResult


class WorkflowRecorder:
    def __init__(self, context: WorkflowContext, *, on_entry: Callable[[dict[str, Any]], None] | None = None):
        self.context = context
        self.run_dir = context.run_dir
        self.trace_path = self.run_dir / "trace.jsonl"
        self.summary_path = self.run_dir / "summary.json"
        self.on_entry = on_entry
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def record_event(
        self,
        *,
        step: int,
        node_id: str,
        node_type: str,
        status: str,
        message: str,
        success: bool | None = None,
        next_node: str | None = None,
    ) -> None:
        self._append_entry(
            {
                "step": step,
                "node_id": node_id,
                "node_type": node_type,
                "success": success,
                "status": status,
                "message": message,
                "next_node": next_node,
                "screenshot": None,
                "debug": [],
                "elapsed_ms": None,
            }
        )

    def record_step(self, result: WorkflowNodeResult) -> None:
        entry = {
            "step": self.context.step_index,
            "node_id": result.node_id,
            "node_type": result.node_type,
            "success": result.success,
            "status": result.status,
            "message": result.message,
            "next_node": result.next_node,
            "screenshot": _path_str(result.screenshot_path),
            "debug": [_path_str(path) for path in result.debug_paths],
            "elapsed_ms": result.elapsed_ms,
        }
        if result.match_result is not None:
            entry["match"] = _jsonable(result.match_result)
        if result.action_result is not None:
            entry["action"] = _jsonable(result.action_result)
        self._append_entry(entry)

    def write_summary(self, result: WorkflowRunResult) -> None:
        summary = {
            "workflow_id": result.workflow_id,
            "run_id": result.run_id,
            "success": result.success,
            "status": result.status,
            "final_node": result.final_node,
            "steps": len(result.steps),
            "message": result.message,
            "trace": str(self.trace_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_entry(self, entry: dict[str, Any]) -> None:
        with self.trace_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if self.on_entry is not None:
            self.on_entry(dict(entry))


def _path_str(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
