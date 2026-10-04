from __future__ import annotations

import json
import random
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

from game_bot.config.loader import PROJECT_ROOT, load_popups, load_regions, load_settings, load_targets
from game_bot.core.capture import capture_client_to_file
from game_bot.core.input import click_client, drag_client, press_key, scroll_client
from game_bot.core.models import ActionResult, MatchResult, Point, Rect, TargetSpec
from game_bot.core.window import bring_window_to_foreground, find_window_by_process_name, find_window_by_title, get_client_size, get_window_info, get_window_title, is_window_alive, is_window_foreground, user32
from game_bot.vision.template import match_template
from game_bot.workflow.context import WorkflowContext
from game_bot.workflow.models import WorkflowNodeDefinition, WorkflowNodeResult


class WorkflowNodeExecutionError(RuntimeError):
    pass


DEFAULT_DELAY_AFTER_MS = 500
DEFAULT_TEMPLATE_MATCH_RETRIES = 3
DEFAULT_TEMPLATE_MATCH_RETRY_INTERVAL_MS = 1000


@dataclass(frozen=True)
class PopupRule:
    name: str
    templates: tuple[str, ...]
    threshold: float = 0.85
    action: str = "esc"
    enabled: bool = True


@dataclass(frozen=True)
class TemplateMatchExecution:
    found: bool
    status: str
    message: str
    best_result: MatchResult
    debug_paths: tuple[Path, ...]


def execute_node(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    started_at = perf_counter()
    try:
        if node.type == "screenshot":
            return _finish_node(node, context, _execute_screenshot(node, context), started_at)
        if node.type == "template_match":
            return _finish_node(node, context, _execute_template_match(node, context), started_at)
        if node.type == "wait_template_state":
            return _finish_node(node, context, _execute_wait_template_state(node, context), started_at)
        if node.type == "not_match":
            return _finish_node(node, context, _execute_not_match(node, context), started_at)
        if node.type == "click":
            return _finish_node(node, context, _execute_click(node, context), started_at)
        if node.type == "scroll":
            return _finish_node(node, context, _execute_scroll(node, context), started_at)
        if node.type == "drag":
            return _finish_node(node, context, _execute_drag(node, context), started_at)
        if node.type == "key":
            return _finish_node(node, context, _execute_key(node, context), started_at)
        if node.type == "wait":
            return _finish_node(node, context, _execute_wait(node, context), started_at)
        if node.type == "loop":
            return _finish_node(node, context, _execute_loop(node, context), started_at)
        if node.type == "pause":
            return _finish_node(node, context, _execute_pause(node, context), started_at)
        if node.type == "end":
            return _finish_node(node, context, _execute_end(node, context), started_at)
        if node.type == "branch":
            return _finish_node(node, context, _execute_branch(node, context), started_at)
        if node.type == "workflow":
            return _finish_node(node, context, _execute_workflow(node, context), started_at)
    except Exception as exc:
        return _finish_node(
            node,
            context,
            WorkflowNodeResult(
                success=False,
                status="error",
                node_id=node.id,
                node_type=node.type,
                message=str(exc),
                screenshot_path=context.screenshot_path,
            ),
            started_at,
        )

    return _finish_node(
        node,
        context,
        WorkflowNodeResult(
            success=False,
            status="unsupported_node_type",
            node_id=node.id,
            node_type=node.type,
            message=f"Unsupported workflow node type: {node.type}",
            screenshot_path=context.screenshot_path,
        ),
        started_at,
    )


def _execute_screenshot(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    output_path = context.screenshot_output_path(node.id)
    hwnd = _resolve_screenshot_hwnd(node, context)
    bring_to_front = _parse_optional_bool(node.params.get("bring_to_front"), "bring_to_front", False)
    foreground_wait_ms = _non_negative_int(node.params.get("foreground_wait_ms", 200), "foreground_wait_ms")
    backend = _capture_backend_from_param(node.params.get("capture_backend", node.params.get("backend")), "desktop")
    result = capture_client_to_file(
        hwnd,
        output_path,
        bring_to_front=bring_to_front,
        foreground_wait_ms=foreground_wait_ms,
        backend=backend,
    )
    context.hwnd = result.hwnd
    context.screenshot_path = result.path
    return WorkflowNodeResult(
        success=True,
        status="captured",
        node_id=node.id,
        node_type=node.type,
        message=f"Screenshot captured from hwnd {result.hwnd}.",
        screenshot_path=result.path,
    )


def _execute_template_match(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    max_retries = node.retries if node.retries > 0 else DEFAULT_TEMPLATE_MATCH_RETRIES
    retry_interval_ms = _non_negative_int(
        node.params.get("retry_interval_ms", DEFAULT_TEMPLATE_MATCH_RETRY_INTERVAL_MS),
        "retry_interval_ms",
    )
    probe_popups = _parse_optional_bool(node.params.get("probe_popups"), "probe_popups", True)
    match = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        match = _match_templates(node, context, "template_match")
        if match.found or attempt >= max_retries:
            break
        if probe_popups:
            popup_message = _dismiss_gift_popup_if_present(node, context)
            if popup_message:
                context.variables["last_gift_popup_recovery"] = popup_message
        if not context.dry_run and retry_interval_ms > 0:
            sleep(retry_interval_ms / 1000)

    if match is None:
        raise WorkflowNodeExecutionError("template_match did not execute.")

    action_result = None
    message = f"{match.message} attempts={attempts}."
    if match.found and _parse_optional_bool(node.params.get("click"), "click", False):
        action_result = _click_match_result(node, context)
        message = f"{message} {action_result.message}"
    return WorkflowNodeResult(
        success=match.found and (action_result is None or action_result.success),
        status="matched_clicked" if action_result is not None and action_result.success else match.status,
        node_id=node.id,
        node_type=node.type,
        message=message,
        screenshot_path=context.screenshot_path,
        debug_paths=match.debug_paths,
        match_result=match.best_result,
        action_result=action_result,
    )


def _execute_not_match(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    match = _match_templates(node, context, "not_match")
    return WorkflowNodeResult(
        success=not match.found,
        status=match.status,
        node_id=node.id,
        node_type=node.type,
        message=match.message,
        screenshot_path=context.screenshot_path,
        debug_paths=match.debug_paths,
        match_result=match.best_result,
    )


def _execute_wait_template_state(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    timeout_ms = _non_negative_int(node.timeout_ms if node.timeout_ms is not None else 5000, "timeout_ms")
    poll_interval_ms = _non_negative_int(node.params.get("poll_interval_ms", 300), "poll_interval_ms")
    click_enabled = _parse_optional_bool(node.params.get("click"), "click", False)
    started_at = perf_counter()
    attempts = 0
    debug_paths: list[Path] = []

    while True:
        attempts += 1
        match = _match_templates(node, context, "wait_template_state")
        debug_paths.extend(match.debug_paths)
        if match.found:
            action_result = None
            message = f"{match.message} attempts={attempts}."
            if click_enabled:
                action_result = _click_match_result(node, context)
                message = f"{message} {action_result.message}"
            status = "found" if action_result is None else "matched_clicked" if action_result.success else "click_failed"
            return WorkflowNodeResult(
                success=action_result is None or action_result.success,
                status=status,
                node_id=node.id,
                node_type=node.type,
                message=message,
                screenshot_path=context.screenshot_path,
                debug_paths=tuple(debug_paths),
                match_result=match.best_result,
                action_result=action_result,
            )

        elapsed_ms = round((perf_counter() - started_at) * 1000)
        if context.dry_run or elapsed_ms >= timeout_ms:
            message = (
                f"Dry-run wait_template_state stopped after {attempts} attempts. {match.message}"
                if context.dry_run
                else f"wait_template_state timeout after {elapsed_ms} ms and {attempts} attempts. {match.message}"
            )
            return WorkflowNodeResult(
                success=False,
                status="timeout",
                node_id=node.id,
                node_type=node.type,
                message=message,
                screenshot_path=context.screenshot_path,
                debug_paths=tuple(debug_paths),
                match_result=match.best_result,
            )

        remaining_ms = timeout_ms - elapsed_ms
        wait_ms = min(poll_interval_ms, remaining_ms)
        if wait_ms > 0:
            sleep(wait_ms / 1000)


def _match_templates(
    node: WorkflowNodeDefinition,
    context: WorkflowContext,
    required_by: str,
) -> TemplateMatchExecution:
    output_path = context.screenshot_output_path(node.id)
    hwnd = _resolve_screenshot_hwnd(node, context)
    bring_to_front = _parse_optional_bool(node.params.get("bring_to_front"), "bring_to_front", False)
    foreground_wait_ms = _non_negative_int(node.params.get("foreground_wait_ms", 200), "foreground_wait_ms")
    backend = _capture_backend_from_param(node.params.get("capture_backend"), "auto")
    screenshot = capture_client_to_file(
        hwnd,
        output_path,
        bring_to_front=bring_to_front,
        foreground_wait_ms=foreground_wait_ms,
        backend=backend,
    )
    context.hwnd = screenshot.hwnd
    context.screenshot_path = screenshot.path

    target = node.params.get("target")
    threshold = float(node.params.get("threshold", 0.85))
    region = _parse_optional_region(node.params.get("region"))
    scales = _parse_scales(node.params["scales"]) if "scales" in node.params else None

    if target is not None:
        target_spec = _load_target_spec(str(target))
        template_paths = (target_spec.template_path,)
        threshold = target_spec.threshold
        scales = target_spec.scales
        if target_spec.region_name is not None:
            region = _load_region(target_spec.region_name)
    else:
        template_paths = _parse_template_paths(node.params.get("templates")) or _parse_template_paths(node.params.get("template"))

    if not template_paths:
        raise WorkflowNodeExecutionError(f"{required_by} requires template, templates, or target.")

    save_debug = bool(node.params.get("save_debug", False))
    results = []
    debug_paths = []
    for index, template_path in enumerate(template_paths):
        debug_path = None
        if save_debug:
            suffix = "match" if len(template_paths) == 1 else f"match_{index}"
            debug_path = context.debug_output_path(node.id, suffix)
        result = match_template(
            context.screenshot_path,
            template_path,
            threshold=threshold,
            region=region,
            scales=scales,
            debug_path=debug_path,
        )
        results.append(result)
        if result.debug_path is not None:
            debug_paths.append(result.debug_path)

    found_results = [result for result in results if result.found]
    best_result = max(found_results or results, key=lambda result: result.score)
    context.last_match = best_result
    context.last_match_click_regions = _resolve_match_click_regions(node, context, best_result) if found_results else []
    context.last_match_click_points = [_rect_center(region) for region in context.last_match_click_regions]
    context.last_match_click_region = context.last_match_click_regions[0] if context.last_match_click_regions else None
    context.last_match_click_point = context.last_match_click_points[0] if context.last_match_click_points else None
    status = "found" if found_results else "not_found"
    if not found_results:
        context.last_match_click_regions = []
        context.last_match_click_points = []
        context.last_match_click_region = None
        context.last_match_click_point = None
    return TemplateMatchExecution(
        found=bool(found_results),
        status=status,
        message=(
            f"Template match {status}, score={best_result.score:.6f}, "
            f"template={best_result.template_path}, checked={len(template_paths)}."
        ),
        best_result=best_result,
        debug_paths=tuple(debug_paths),
    )


def _dismiss_gift_popup_if_present(node: WorkflowNodeDefinition, context: WorkflowContext) -> str | None:
    for popup_rule in _load_popup_rules():
        popup_node = WorkflowNodeDefinition(
            id=f"{node.id}_{popup_rule.name}_popup_probe",
            type="template_match",
            params={
                "templates": list(popup_rule.templates),
                "threshold": popup_rule.threshold,
                "save_debug": bool(node.params.get("save_debug", False)),
            },
        )
        popup_match = _match_templates(popup_node, context, "gift_popup_probe")
        if not popup_match.found:
            continue
        if context.dry_run:
            return (
                f"Popup detected in dry-run: rule={popup_rule.name}, "
                f"template={popup_match.best_result.template_path}, action={popup_rule.action}."
            )
        action_result = _execute_popup_action(context, popup_rule)
        return (
            f"Popup detected: rule={popup_rule.name}, template={popup_match.best_result.template_path}, "
            f"action={popup_rule.action}. {action_result.message}"
        )
    return None


def _load_popup_rules() -> tuple[PopupRule, ...]:
    config = load_popups()
    raw_rules = config.get("rules", []) if isinstance(config, dict) else []
    rules: list[PopupRule] = []
    for index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, dict):
            raise WorkflowNodeExecutionError(f"Popup rule at index {index} must be a mapping.")
        name = str(raw_rule.get("name", f"popup_{index + 1}")).strip() or f"popup_{index + 1}"
        enabled = bool(raw_rule.get("enabled", True))
        action = str(raw_rule.get("action", "esc")).strip().lower() or "esc"
        threshold = float(raw_rule.get("threshold", 0.85))
        templates = _parse_template_paths(raw_rule.get("templates")) or _parse_template_paths(raw_rule.get("template"))
        if not templates:
            raise WorkflowNodeExecutionError(f"Popup rule '{name}' requires template or templates.")
        rules.append(
            PopupRule(
                name=name,
                templates=tuple(str(path) for path in templates),
                threshold=threshold,
                action=action,
                enabled=enabled,
            )
        )
    return tuple(rule for rule in rules if rule.enabled)


def _execute_popup_action(context: WorkflowContext, popup_rule: PopupRule) -> ActionResult:
    if popup_rule.action == "esc":
        return press_key(context.hwnd, "esc")
    raise WorkflowNodeExecutionError(f"Unsupported popup action: {popup_rule.action}")


def _execute_workflow(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    workflow_path = _required_param_str(node, "workflow")
    max_depth = _non_negative_int(node.params.get("max_depth", 20), "max_depth")
    start_node = _optional_str(node.params.get("start_node"))
    resolved_path = _resolve_path(workflow_path)

    if len(context.workflow_stack) >= max_depth:
        raise WorkflowNodeExecutionError(f"workflow max_depth exceeded: {max_depth}")
    if resolved_path in context.workflow_stack:
        stack = " -> ".join(path.name for path in [*context.workflow_stack, resolved_path])
        raise WorkflowNodeExecutionError(f"Recursive workflow reference: {stack}")

    from game_bot.workflow.engine import run_workflow
    from game_bot.workflow.loader import load_workflow
    from game_bot.workflow.recorder import WorkflowRecorder

    child_workflow = load_workflow(resolved_path)
    context.workflow_stack.append(resolved_path)
    previous_workflow_id = context.workflow_id
    context.workflow_id = child_workflow.id
    try:
        result = run_workflow(
            child_workflow,
            context,
            start_node=start_node,
            recorder=WorkflowRecorder(context),
        )
    finally:
        context.workflow_id = previous_workflow_id
        context.workflow_stack.pop()

    return WorkflowNodeResult(
        success=result.success,
        status="workflow_completed" if result.success else "workflow_failed",
        node_id=node.id,
        node_type=node.type,
        message=(
            f"Workflow {child_workflow.id} finished with status={result.status}, "
            f"steps={len(result.steps)}, final_node={result.final_node}: {result.message}"
        ),
        next_node=node.next if result.success else node.on_fail,
        screenshot_path=context.screenshot_path,
    )


def _execute_click(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    action_result = _click_resolved_points(node, context, _resolve_click_points(node, context))
    return WorkflowNodeResult(
        success=action_result.success,
        status="clicked" if action_result.success else "click_failed",
        node_id=node.id,
        node_type=node.type,
        message=action_result.message,
        screenshot_path=context.screenshot_path,
        action_result=action_result,
    )


def _click_match_result(node: WorkflowNodeDefinition, context: WorkflowContext) -> ActionResult:
    point_from = str(node.params.get("click_point_from", "last_match.center"))
    points = _resolve_click_points_from(point_from, context)
    offset = node.params.get("click_offset", node.params.get("offset", (0, 0)))
    if not isinstance(offset, (list, tuple)) or len(offset) != 2:
        raise WorkflowNodeExecutionError("template_match click_offset must be [dx, dy].")
    return _click_resolved_points(node, context, [Point(point.x + int(offset[0]), point.y + int(offset[1])) for point in points])


def _click_resolved_points(node: WorkflowNodeDefinition, context: WorkflowContext, points: list[Point]) -> ActionResult:
    if not points:
        raise WorkflowNodeExecutionError("click requires at least one resolved point.")
    click_region_interval_ms = _non_negative_int(node.params.get("click_region_interval_ms", 0), "click_region_interval_ms")
    results = []
    for index, point in enumerate(points):
        if index > 0 and click_region_interval_ms > 0 and not context.dry_run:
            sleep(click_region_interval_ms / 1000)
        result = _click_resolved_point(node, context, point)
        results.append(result)
        if not result.success:
            clicked = ", ".join(f"({item.client_point.x}, {item.client_point.y})" for item in results if item.client_point is not None)
            return ActionResult(
                success=False,
                action="click",
                hwnd=context.hwnd,
                message=f"Click sequence failed at #{index + 1}/{len(points)}. clicked=[{clicked}]. {result.message}",
                client_point=result.client_point,
                screen_point=result.screen_point,
            )
    if len(results) == 1:
        return results[0]
    last = results[-1]
    clicked = ", ".join(f"({point.x}, {point.y})" for point in points)
    return ActionResult(
        success=True,
        action="click",
        hwnd=context.hwnd,
        message=f"Clicked {len(points)} points in order: {clicked}. Last result: {last.message}",
        client_point=last.client_point,
        screen_point=last.screen_point,
    )


def _click_resolved_point(node: WorkflowNodeDefinition, context: WorkflowContext, point: Point) -> ActionResult:
    duration_ms = _non_negative_int(node.params.get("duration_ms", 50), "duration_ms")
    clicks = _positive_int(node.params.get("clicks", 1), "clicks")
    interval_ms = _non_negative_int(node.params.get("interval_ms", 0), "interval_ms")
    if context.dry_run:
        return ActionResult(
            success=True,
            action="click",
            hwnd=context.hwnd,
            message=f"Dry-run click skipped at client point ({point.x}, {point.y}), clicks={clicks}.",
            client_point=point,
        )
    input_result = click_client(
        context.hwnd,
        point.x,
        point.y,
        duration_ms=duration_ms,
        clicks=clicks,
        interval_ms=interval_ms,
    )
    return ActionResult(
        success=input_result.success,
        action="click",
        hwnd=context.hwnd,
        message=input_result.message,
        client_point=input_result.client_point,
        screen_point=input_result.screen_point,
    )


def _execute_scroll(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    direction = str(node.params.get("direction", "down")).strip().lower()
    if direction not in {"up", "down"}:
        raise WorkflowNodeExecutionError(f"scroll direction must be up or down: {direction}")
    distance = _positive_int(node.params.get("distance", 1), "distance")
    speed = node.params.get("speed", "min")
    if context.dry_run:
        action_result = ActionResult(
            success=True,
            action="scroll",
            hwnd=context.hwnd,
            message=f"Dry-run scroll skipped: direction={direction}, distance={distance}, speed={speed}.",
        )
    else:
        input_result = scroll_client(context.hwnd, direction=direction, distance=distance, speed=speed)
        action_result = ActionResult(
            success=input_result.success,
            action="scroll",
            hwnd=context.hwnd,
            message=input_result.message,
        )
    return WorkflowNodeResult(
        success=action_result.success,
        status="scrolled" if action_result.success else "scroll_failed",
        node_id=node.id,
        node_type=node.type,
        message=action_result.message,
        screenshot_path=context.screenshot_path,
        action_result=action_result,
    )


def _execute_drag(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    start_point = _resolve_drag_start_point(node, context)
    direction = str(node.params.get("direction", "left")).strip().lower()
    distance = _positive_int(node.params.get("distance", 1), "distance")
    duration_ms = _non_negative_int(node.params.get("duration_ms", 300), "duration_ms")
    steps = _positive_int(node.params.get("steps", 12), "steps")
    end_point = _drag_end_point(start_point, direction=direction, distance=distance)
    if context.dry_run:
        action_result = ActionResult(
            success=True,
            action="drag",
            hwnd=context.hwnd,
            message=(
                f"Dry-run drag skipped: start=({start_point.x}, {start_point.y}) "
                f"end=({end_point.x}, {end_point.y}) direction={direction} distance={distance} "
                f"duration_ms={duration_ms} steps={steps}."
            ),
            client_point=end_point,
        )
    else:
        input_result = drag_client(
            context.hwnd,
            start_point.x,
            start_point.y,
            direction=direction,
            distance=distance,
            duration_ms=duration_ms,
            steps=steps,
        )
        action_result = ActionResult(
            success=input_result.success,
            action="drag",
            hwnd=context.hwnd,
            message=input_result.message,
            client_point=input_result.client_point,
            screen_point=input_result.screen_point,
        )
    return WorkflowNodeResult(
        success=action_result.success,
        status="dragged" if action_result.success else "drag_failed",
        node_id=node.id,
        node_type=node.type,
        message=action_result.message,
        screenshot_path=context.screenshot_path,
        action_result=action_result,
    )


def _execute_key(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    key = str(node.params.get("key", "")).strip()
    if not key:
        raise WorkflowNodeExecutionError("key node requires key.")
    duration_ms = _non_negative_int(node.params.get("duration_ms", 50), "duration_ms")
    if context.dry_run:
        action_result = ActionResult(
            success=True,
            action="key",
            hwnd=context.hwnd,
            message=f"Dry-run key skipped: {key}.",
        )
    else:
        before_hwnd = int(user32.GetForegroundWindow())
        before_title = get_window_title(before_hwnd) if before_hwnd and is_window_alive(before_hwnd) else ""
        target_foreground_before = is_window_foreground(context.hwnd)
        if not target_foreground_before:
            bring_window_to_foreground(context.hwnd)
            before_hwnd = int(user32.GetForegroundWindow())
            before_title = get_window_title(before_hwnd) if before_hwnd and is_window_alive(before_hwnd) else ""
            target_foreground_before = is_window_foreground(context.hwnd)
        input_result = press_key(context.hwnd, key, duration_ms=duration_ms)
        after_hwnd = int(user32.GetForegroundWindow())
        after_title = get_window_title(after_hwnd) if after_hwnd and is_window_alive(after_hwnd) else ""
        target_foreground_after = is_window_foreground(context.hwnd)
        message = (
            f"{input_result.message}; "
            f"foreground_before={before_hwnd} '{before_title}' target_before={target_foreground_before}; "
            f"foreground_after={after_hwnd} '{after_title}' target_after={target_foreground_after}"
        )
        action_result = ActionResult(
            success=input_result.success,
            action="key",
            hwnd=context.hwnd,
            message=message,
        )
    return WorkflowNodeResult(
        success=action_result.success,
        status="key_sent" if action_result.success else "key_failed",
        node_id=node.id,
        node_type=node.type,
        message=action_result.message,
        screenshot_path=context.screenshot_path,
        action_result=action_result,
    )


def _execute_wait(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    duration_ms = _non_negative_int(node.params.get("duration_ms", 0), "duration_ms")
    if not context.dry_run and duration_ms > 0:
        sleep(duration_ms / 1000)
    return WorkflowNodeResult(
        success=True,
        status="waited",
        node_id=node.id,
        node_type=node.type,
        message=f"Waited {duration_ms} ms." if not context.dry_run else f"Dry-run wait skipped: {duration_ms} ms.",
        screenshot_path=context.screenshot_path,
    )


def _execute_loop(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    variable_name = _required_param_str(node, "variable")
    raw_limit = node.params.get("times", node.params.get("count", node.params.get("limit")))
    if raw_limit is None:
        raise WorkflowNodeExecutionError("loop node requires times, count, or limit.")
    limit = _positive_int(
        raw_limit,
        "times",
    )
    step = _positive_int(node.params.get("step", 1), "step")
    start = int(node.params.get("start", 0))
    current = int(context.variables.get(variable_name, start))
    next_value = current + step
    context.variables[variable_name] = next_value
    continuing = next_value < limit
    status = "loop_continue" if continuing else "loop_done"
    return WorkflowNodeResult(
        success=True,
        status=status,
        node_id=node.id,
        node_type=node.type,
        message=(
            f"Loop counter '{variable_name}' advanced from {current} to {next_value} "
            f"(limit={limit}, step={step})."
        ),
        screenshot_path=context.screenshot_path,
    )


def _execute_pause(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    reason = str(node.params.get("reason", "paused"))
    return WorkflowNodeResult(
        success=False,
        status="paused",
        node_id=node.id,
        node_type=node.type,
        message=reason,
        screenshot_path=context.screenshot_path,
    )


def _execute_end(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    result = str(node.params.get("result", "success"))
    return WorkflowNodeResult(
        success=True,
        status="ended",
        node_id=node.id,
        node_type=node.type,
        message=result,
        screenshot_path=context.screenshot_path,
    )


def _execute_branch(node: WorkflowNodeDefinition, context: WorkflowContext) -> WorkflowNodeResult:
    condition = str(node.params.get("condition", ""))
    if condition != "last_match.found":
        raise WorkflowNodeExecutionError(f"Unsupported branch condition: {condition}")
    matched = context.last_match is not None and context.last_match.found
    next_node = node.params.get("true" if matched else "false")
    if next_node is not None:
        next_node = str(next_node)
    return WorkflowNodeResult(
        success=matched,
        status="true" if matched else "false",
        node_id=node.id,
        node_type=node.type,
        message=f"Branch condition {condition} is {matched}.",
        next_node=next_node,
        screenshot_path=context.screenshot_path,
    )


def _resolve_click_points(node: WorkflowNodeDefinition, context: WorkflowContext) -> list[Point]:
    if "point_from" in node.params:
        points = _resolve_click_points_from(str(node.params["point_from"]), context)
    else:
        value = node.params.get("point")
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise WorkflowNodeExecutionError(
                "click node requires point: [x, y], point_from: last_match.center, "
                "last_match.click_region.center/random, last_match.click_regions.center/random, or random.client."
            )
        points = [Point(int(value[0]), int(value[1]))]

    offset = node.params.get("offset", (0, 0))
    if not isinstance(offset, (list, tuple)) or len(offset) != 2:
        raise WorkflowNodeExecutionError("click offset must be [dx, dy].")
    return [Point(point.x + int(offset[0]), point.y + int(offset[1])) for point in points]


def _resolve_drag_start_point(node: WorkflowNodeDefinition, context: WorkflowContext) -> Point:
    if "point_from" in node.params:
        return _resolve_click_point_from(str(node.params["point_from"]), context)
    value = node.params.get("point")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise WorkflowNodeExecutionError(
            "drag node requires point: [x, y] or point_from: last_match.center, "
            "last_match.click_region.center/random, last_match.click_regions.center/random, or random.client."
        )
    return Point(int(value[0]), int(value[1]))


def _drag_end_point(start: Point, *, direction: str, distance: int) -> Point:
    normalized = direction.strip().lower()
    if normalized == "left":
        return Point(start.x - distance, start.y)
    if normalized == "right":
        return Point(start.x + distance, start.y)
    if normalized == "up":
        return Point(start.x, start.y - distance)
    if normalized == "down":
        return Point(start.x, start.y + distance)
    raise WorkflowNodeExecutionError(f"drag direction must be left, right, up, or down: {direction}")


def _random_client_point(context: WorkflowContext) -> Point:
    size = get_client_size(context.hwnd)
    return Point(random.randint(0, size.width - 1), random.randint(0, size.height - 1))


def _random_point_in_rect(rect: Rect) -> Point:
    if rect.width <= 0 or rect.height <= 0:
        raise WorkflowNodeExecutionError(f"Cannot choose random point from empty rect: {rect}")
    return Point(random.randint(rect.left, rect.right - 1), random.randint(rect.top, rect.bottom - 1))


def _rect_center(rect: Rect) -> Point:
    return Point(rect.left + rect.width // 2, rect.top + rect.height // 2)


def _resolve_click_point_from(point_from: str, context: WorkflowContext) -> Point:
    return _resolve_click_points_from(point_from, context)[0]


def _resolve_click_points_from(point_from: str, context: WorkflowContext) -> list[Point]:
    if point_from == "random.client":
        return [_random_client_point(context)]
    if point_from == "last_match.center":
        if context.last_match is None:
            raise WorkflowNodeExecutionError("point_from last_match.center requires a previous match result.")
        return [context.last_match.center]
    if point_from == "last_match.click_region.center":
        if context.last_match_click_point is None:
            raise WorkflowNodeExecutionError(
                "point_from last_match.click_region.center requires a previous template_match with click_region."
            )
        return [context.last_match_click_point]
    if point_from == "last_match.click_region.random":
        if context.last_match_click_region is None:
            raise WorkflowNodeExecutionError(
                "point_from last_match.click_region.random requires a previous template_match with click_region."
            )
        return [_random_point_in_rect(context.last_match_click_region)]
    if point_from == "last_match.click_regions.center":
        if not context.last_match_click_points:
            raise WorkflowNodeExecutionError(
                "point_from last_match.click_regions.center requires a previous template_match with click_regions."
            )
        return list(context.last_match_click_points)
    if point_from == "last_match.click_regions.random":
        if not context.last_match_click_regions:
            raise WorkflowNodeExecutionError(
                "point_from last_match.click_regions.random requires a previous template_match with click_regions."
            )
        return [_random_point_in_rect(region) for region in context.last_match_click_regions]
    raise WorkflowNodeExecutionError(f"Unsupported click point_from: {point_from}")


def _resolve_match_click_region(node: WorkflowNodeDefinition, context: WorkflowContext, match: MatchResult) -> Rect | None:
    regions = _resolve_match_click_regions(node, context, match)
    return regions[0] if regions else None


def _resolve_match_click_regions(node: WorkflowNodeDefinition, context: WorkflowContext, match: MatchResult) -> list[Rect]:
    value, coordinate_space = _click_regions_value_and_space(node, match.template_path)
    if value is None:
        return [match.box]
    regions = [
        _convert_click_region(region, space, context, match)
        for region, space in _parse_region_specs("click_regions", value, coordinate_space)
    ]
    return regions or [match.box]


def _convert_click_region(region: Rect, coordinate_space: str, context: WorkflowContext, match: MatchResult) -> Rect:
    if coordinate_space == "screen":
        origin = get_window_info(context.hwnd).client_origin_screen
        return Rect(region.left - origin.x, region.top - origin.y, region.right - origin.x, region.bottom - origin.y)
    if coordinate_space == "window":
        return region
    return Rect(
        match.box.left + round(region.left * match.scale),
        match.box.top + round(region.top * match.scale),
        match.box.left + round(region.right * match.scale),
        match.box.top + round(region.bottom * match.scale),
    )


def _click_regions_value_and_space(node: WorkflowNodeDefinition, template_path: Path) -> tuple[Any, str]:
    if node.params.get("click_regions") is not None:
        return node.params.get("click_regions"), str(node.params.get("click_region_coordinate_space", "template"))
    if node.params.get("click_region") is not None:
        return node.params.get("click_region"), str(node.params.get("click_region_coordinate_space", "template"))
    metadata = _template_metadata(template_path)
    if metadata is None:
        return None, "template"
    if metadata.get("click_regions") is not None:
        return metadata.get("click_regions"), str(metadata.get("coordinate_space", "template"))
    return metadata.get("click_region"), str(metadata.get("coordinate_space", "template"))


def _click_region_value_and_space(node: WorkflowNodeDefinition, template_path: Path) -> tuple[Any, str]:
    return _click_regions_value_and_space(node, template_path)


def _template_metadata(template_path: Path) -> dict[str, Any] | None:
    metadata_path = template_path.with_suffix(".json")
    if not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    return metadata


def _template_metadata_click_region(template_path: Path) -> Any:
    metadata = _template_metadata(template_path)
    return metadata.get("click_region") if metadata is not None else None


def _resolve_screenshot_hwnd(node: WorkflowNodeDefinition, context: WorkflowContext) -> int:
    settings_game = load_settings().get("game", {})
    exact = _parse_optional_bool(node.params.get("exact"), "exact", context.exact)

    if "hwnd" in node.params:
        hwnd = _parse_hwnd_param(node.params["hwnd"])
        if not is_window_alive(hwnd):
            raise WorkflowNodeExecutionError(f"Configured screenshot hwnd is not alive: {hwnd}")
        context.hwnd = hwnd
        return hwnd

    process_name = _first_non_empty_str(
        node.params.get("process_name"),
        context.process_name,
        settings_game.get("process_name"),
    )
    if process_name is not None:
        hwnd = find_window_by_process_name(process_name)
        context.hwnd = hwnd
        return hwnd

    title = _first_non_empty_str(
        node.params.get("title"),
        context.window_title,
        settings_game.get("window_title"),
    )
    if title is not None:
        hwnd = find_window_by_title(title, exact=exact)
        context.hwnd = hwnd
        return hwnd

    if is_window_alive(context.hwnd):
        return context.hwnd

    raise WorkflowNodeExecutionError(
        f"No live screenshot target window. hwnd={context.hwnd}, process_name={process_name}, title={title}, exact={exact}."
    )


def _parse_template_paths(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple)):
        paths = tuple(str(item).strip() for item in value if str(item).strip())
        if not paths:
            raise WorkflowNodeExecutionError("templates cannot be empty.")
        return paths
    raise WorkflowNodeExecutionError("templates must be a string or list of strings.")


def _load_target_spec(name: str) -> TargetSpec:
    targets = load_targets()
    data = targets.get(name)
    if not isinstance(data, dict):
        raise WorkflowNodeExecutionError(f"Unknown target: {name}")
    target_type = str(data.get("type", "template"))
    template = data.get("template")
    if target_type == "template" and template is None:
        raise WorkflowNodeExecutionError(f"Template target '{name}' requires template.")
    return TargetSpec(
        name=name,
        type=target_type,
        template_path=_resolve_path(str(template)) if template is not None else PROJECT_ROOT,
        threshold=float(data.get("threshold", 0.85)),
        region_name=str(data.get("region")) if data.get("region") is not None else None,
        scales=_parse_scales(data["scales"]) if "scales" in data else None,
    )


def _load_region(name: str) -> Rect:
    regions = load_regions()
    value = regions.get(name)
    if value is None:
        raise WorkflowNodeExecutionError(f"Unknown region: {name}")
    return _parse_region_value(name, value)


def _parse_optional_region(value: Any) -> Rect | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _load_region(value)
    return _parse_region_value("region", value)


def _parse_region_values(name: str, value: Any) -> list[Rect]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)) and len(value) == 4 and not any(isinstance(item, (list, tuple, dict)) for item in value):
        return [_parse_region_value(name, value)]
    if isinstance(value, (list, tuple)):
        return [_parse_region_value(f"{name}[{index}]", item) for index, item in enumerate(value)]
    return [_parse_region_value(name, value)]


def _parse_region_specs(name: str, value: Any, default_coordinate_space: str) -> list[tuple[Rect, str]]:
    fallback_space = "template" if default_coordinate_space == "mixed" else default_coordinate_space
    if value is None:
        return []
    if _is_plain_region_value(value):
        return [(_parse_region_value(name, value), fallback_space)]
    if isinstance(value, dict) and value.get("region") is not None:
        return [(_parse_region_value(name, value.get("region")), str(value.get("coordinate_space") or fallback_space))]
    if isinstance(value, (list, tuple)):
        specs: list[tuple[Rect, str]] = []
        for index, item in enumerate(value):
            item_name = f"{name}[{index}]"
            if isinstance(item, dict) and item.get("region") is not None:
                specs.append((_parse_region_value(item_name, item.get("region")), str(item.get("coordinate_space") or fallback_space)))
            else:
                specs.append((_parse_region_value(item_name, item), fallback_space))
        return specs
    return [(_parse_region_value(name, value), fallback_space)]


def _is_plain_region_value(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 4 and not any(isinstance(item, (list, tuple, dict)) for item in value)


def _parse_region_value(name: str, value: Any) -> Rect:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        left, top, right, bottom = value
    elif isinstance(value, dict):
        left = value.get("left")
        top = value.get("top")
        right = value.get("right")
        bottom = value.get("bottom")
    else:
        raise WorkflowNodeExecutionError(f"Region '{name}' must be a four-item list or mapping.")
    region = Rect(int(left), int(top), int(right), int(bottom))
    if region.width <= 0 or region.height <= 0:
        raise WorkflowNodeExecutionError(f"Region '{name}' must have positive width and height.")
    return region


def _parse_scales(value: Any) -> tuple[float, ...]:
    if isinstance(value, (int, float, str)):
        raw_scales = (value,)
    elif isinstance(value, (list, tuple)):
        raw_scales = tuple(value)
    else:
        raise WorkflowNodeExecutionError("scales must be a number or list of numbers.")
    if not raw_scales:
        raise WorkflowNodeExecutionError("scales cannot be empty.")
    scales = tuple(float(scale) for scale in raw_scales)
    if any(not isfinite(scale) or scale <= 0 for scale in scales):
        raise WorkflowNodeExecutionError(f"scales must be positive finite numbers: {scales}")
    return scales


def _non_negative_int(value: Any, field_name: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise WorkflowNodeExecutionError(f"{field_name} must be a non-negative integer.")
    return parsed


def _positive_int(value: Any, field_name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise WorkflowNodeExecutionError(f"{field_name} must be a positive integer.")
    return parsed


def _parse_optional_bool(value: Any, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise WorkflowNodeExecutionError(f"{field_name} must be a boolean value.")


def _capture_backend_from_param(value: Any, default: str) -> str:
    backend = str(value or default).strip().lower()
    if backend not in {"auto", "window", "desktop", "dm"}:
        raise WorkflowNodeExecutionError(f"capture_backend must be auto, window, desktop, or dm: {backend}")
    return backend


def _parse_hwnd_param(value: Any) -> int:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value.strip(), 0)
    except ValueError as exc:
        raise WorkflowNodeExecutionError("hwnd must be a decimal or hex integer.") from exc
    raise WorkflowNodeExecutionError("hwnd must be a decimal or hex integer.")


def _required_param_str(node: WorkflowNodeDefinition, field_name: str) -> str:
    value = _optional_str(node.params.get(field_name))
    if value is None:
        raise WorkflowNodeExecutionError(f"{node.type} node requires {field_name}.")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_non_empty_str(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _resolve_path(path: str) -> str:
    resolved = PROJECT_ROOT / path
    if path.startswith(('/', '\\')) or (len(path) > 1 and path[1] == ':'):
        return path
    return str(resolved)


def _finish_node(
    node: WorkflowNodeDefinition,
    context: WorkflowContext,
    result: WorkflowNodeResult,
    started_at: float,
) -> WorkflowNodeResult:
    delay_after_ms = _non_negative_int(node.params.get("delay_after_ms", DEFAULT_DELAY_AFTER_MS), "delay_after_ms")
    if not context.dry_run and delay_after_ms > 0:
        sleep(delay_after_ms / 1000)
    return _with_elapsed(result, started_at)


def _with_elapsed(result: WorkflowNodeResult, started_at: float) -> WorkflowNodeResult:
    return WorkflowNodeResult(
        success=result.success,
        status=result.status,
        node_id=result.node_id,
        node_type=result.node_type,
        message=result.message,
        next_node=result.next_node,
        screenshot_path=result.screenshot_path,
        debug_paths=result.debug_paths,
        match_result=result.match_result,
        action_result=result.action_result,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
    )
