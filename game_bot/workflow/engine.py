from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import sys
from time import sleep
from uuid import uuid4

from game_bot.core.window import WindowError, bring_window_to_foreground
from game_bot.workflow.context import WorkflowContext
from game_bot.workflow.models import WorkflowDefinition, WorkflowNodeResult
from game_bot.workflow.nodes import execute_node
from game_bot.workflow.recorder import WorkflowRecorder

TERMINAL_NODE_TYPES = {"end", "pause"}
TERMINAL_STATUSES = {"ended", "paused", "max_steps_exceeded", "max_failures_exceeded"}


@dataclass(frozen=True)
class WorkflowRunResult:
    success: bool
    status: str
    workflow_id: str
    run_id: str
    steps: tuple[WorkflowNodeResult, ...]
    final_node: str | None
    message: str


def create_workflow_context(
    workflow: WorkflowDefinition,
    hwnd: int,
    *,
    run_id: str | None = None,
    dry_run: bool = False,
    process_name: str | None = None,
    window_title: str | None = None,
    exact: bool = False,
) -> WorkflowContext:
    resolved_run_id = run_id or f"{workflow.id}_{datetime.now().strftime('%Y%m%d-%H%M%S')}_{uuid4().hex[:8]}"
    return WorkflowContext(
        hwnd=hwnd,
        workflow_id=workflow.id,
        run_id=resolved_run_id,
        dry_run=dry_run,
        process_name=process_name,
        window_title=window_title,
        exact=exact,
    )


def run_workflow_step(
    workflow: WorkflowDefinition,
    context: WorkflowContext,
    node_id: str,
) -> WorkflowNodeResult:
    node = workflow.nodes.get(node_id)
    if node is None:
        return WorkflowNodeResult(
            success=False,
            status="missing_node",
            node_id=node_id,
            node_type="unknown",
            message=f"Workflow node does not exist: {node_id}",
            screenshot_path=context.screenshot_path,
        )
    result = execute_node(node, context)
    next_node = decide_next_node(workflow, result)
    if result.next_node == next_node:
        return result
    return WorkflowNodeResult(
        success=result.success,
        status=result.status,
        node_id=result.node_id,
        node_type=result.node_type,
        message=result.message,
        next_node=next_node,
        screenshot_path=result.screenshot_path,
        debug_paths=result.debug_paths,
        match_result=result.match_result,
        action_result=result.action_result,
        elapsed_ms=result.elapsed_ms,
    )


def run_workflow(
    workflow: WorkflowDefinition,
    context: WorkflowContext,
    *,
    start_node: str | None = None,
    recorder: WorkflowRecorder | None = None,
    should_stop: Callable[[], bool] | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> WorkflowRunResult:
    node_id = start_node or workflow.start
    results: list[WorkflowNodeResult] = []
    failures = 0
    active_recorder = recorder or WorkflowRecorder(context)

    try:
        bring_window_to_foreground(context.hwnd)
    except WindowError as exc:
        result = _pause_result(context, node_id, "window_focus_failed", str(exc))
        results.append(result)
        active_recorder.record_step(result)
        return _finalize_run(active_recorder, workflow, context, results, result.node_id, result.status, result.message)
    if not context.dry_run:
        sleep(0.5)

    while True:
        if should_stop is not None and should_stop():
            result = _pause_result(context, node_id, "stopped", "Workflow stopped by user.")
            results.append(result)
            active_recorder.record_step(result)
            return _finalize_run(active_recorder, workflow, context, results, result.node_id, result.status, result.message)
        while should_pause is not None and should_pause():
            if should_stop is not None and should_stop():
                result = _pause_result(context, node_id, "stopped", "Workflow stopped by user.")
                results.append(result)
                active_recorder.record_step(result)
                return _finalize_run(active_recorder, workflow, context, results, result.node_id, result.status, result.message)
            sleep(0.1)

        if len(results) >= workflow.max_steps:
            result = _pause_result(context, node_id, "max_steps_exceeded", "Workflow max_steps exceeded.")
            results.append(result)
            active_recorder.record_step(result)
            return _finalize_run(active_recorder, workflow, context, results, result.node_id, result.status, result.message)

        node = workflow.nodes.get(node_id)
        active_recorder.record_event(
            step=context.step_index,
            node_id=node_id,
            node_type=node.type if node is not None else "unknown",
            status="started",
            message=f"Starting node: {node_id}",
            success=None,
        )
        result = run_workflow_step(workflow, context, node_id)
        results.append(result)
        active_recorder.record_step(result)
        _print_step_log(workflow, result)
        context.step_index += 1

        if result.success:
            failures = 0
        else:
            failures += 1

        if result.status in TERMINAL_STATUSES or result.node_type in TERMINAL_NODE_TYPES:
            return _finalize_run(active_recorder, workflow, context, results, result.node_id, result.status, result.message)

        if failures >= workflow.max_failures:
            pause = _pause_result(context, result.node_id, "max_failures_exceeded", "Workflow max_failures exceeded.")
            results.append(pause)
            active_recorder.record_step(pause)
            return _finalize_run(active_recorder, workflow, context, results, pause.node_id, pause.status, pause.message)

        if result.next_node is None:
            status = "completed" if result.success else "stopped"
            message = "Workflow stopped because there is no next node."
            return _finalize_run(active_recorder, workflow, context, results, result.node_id, status, message)

        node_id = result.next_node


def _print_step_log(workflow: WorkflowDefinition, result: WorkflowNodeResult) -> None:
    node = workflow.nodes.get(result.node_id)
    node_name = node.name if node is not None and node.name else result.node_id
    parts = [
        f"流程={workflow.name}({workflow.id})",
        f"节点={node_name}({result.node_id})",
        f"类型={result.node_type}",
        f"状态={result.status}",
        f"成功={result.success}",
    ]
    if result.match_result is not None:
        match = result.match_result
        template = match.template_path.name if hasattr(match.template_path, "name") else str(match.template_path)
        parts.append(
            f"匹配模板={template} 分数={match.score:.6f} 命中={match.found} "
            f"位置=({match.box.left},{match.box.top},{match.box.right},{match.box.bottom}) "
            f"中心=({match.center.x},{match.center.y})"
        )
    if result.action_result is not None:
        action = result.action_result
        action_parts = [f"操作={action.action}"]
        if action.client_point is not None:
            action_parts.append(f"客户区=({action.client_point.x},{action.client_point.y})")
        if action.screen_point is not None:
            action_parts.append(f"屏幕=({action.screen_point.x},{action.screen_point.y})")
        action_parts.append(f"操作结果={action.success}")
        parts.append(" ".join(action_parts))
    parts.append(f"消息={result.message}")
    line = " | ".join(parts)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        safe_line = line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8",
            errors="replace",
        )
        print(safe_line, flush=True)


def decide_next_node(workflow: WorkflowDefinition, result: WorkflowNodeResult) -> str | None:
    if result.status in TERMINAL_STATUSES or result.node_type in TERMINAL_NODE_TYPES:
        return None
    if result.next_node is not None:
        return result.next_node

    node = workflow.nodes.get(result.node_id)
    if node is None:
        return None

    for transition in node.transitions:
        if transition.when == result.status:
            return transition.to
        if transition.when == "success" and result.success:
            return transition.to
        if transition.when == "failure" and not result.success:
            return transition.to

    if result.success:
        return node.next
    return node.on_fail


def _pause_result(context: WorkflowContext, node_id: str | None, status: str, message: str) -> WorkflowNodeResult:
    return WorkflowNodeResult(
        success=False,
        status=status,
        node_id=node_id or "workflow",
        node_type="pause",
        message=message,
        screenshot_path=context.screenshot_path,
    )


def _finalize_run(
    recorder: WorkflowRecorder,
    workflow: WorkflowDefinition,
    context: WorkflowContext,
    steps: list[WorkflowNodeResult],
    final_node: str | None,
    status: str,
    message: str,
) -> WorkflowRunResult:
    result = _run_result(workflow, context, steps, final_node, status, message)
    recorder.write_summary(result)
    return result


def _run_result(
    workflow: WorkflowDefinition,
    context: WorkflowContext,
    steps: list[WorkflowNodeResult],
    final_node: str | None,
    status: str,
    message: str,
) -> WorkflowRunResult:
    return WorkflowRunResult(
        success=status in {"ended", "completed"},
        status=status,
        workflow_id=workflow.id,
        run_id=context.run_id,
        steps=tuple(steps),
        final_node=final_node,
        message=message,
    )
