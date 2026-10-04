from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any

import yaml

from game_bot.config.loader import PROJECT_ROOT, load_yaml_config
from game_bot.core.models import Point, Rect
from game_bot.core.window import get_window_info
from game_bot.scripted.context import ScriptContext
from game_bot.scripted.priority_match import PriorityTemplateCandidate, scan_priority_templates, select_best_priority_match
from game_bot.scripted.runtime import ScriptPause, ScriptRuntime, TemplateProbeResult
from game_bot.vision.template import match_template

STATE_SCRIPTS_DIR = PROJECT_ROOT / "state_scripts"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
TEMPLATE_ICONS_DIR = TEMPLATES_DIR / "icons"
UNRECOGNIZED_TEMPLATE_KEEP_LIMIT = 20
DEFAULT_TEMPLATE_MATCH_THRESHOLD = 0.85
DEFAULT_LOOP_DIR = "通用"


@dataclass(frozen=True)
class TemplateLoopScriptDefinition:
    id: str
    path: Path
    start_flows: tuple[str, ...]
    loop_dirs: tuple[str, ...]
    end_template: str | None
    completion_count: int
    scales: tuple[float, ...]
    save_debug: bool
    no_match_recovery_rounds: int
    no_match_recovery_wait_ms: int

    @property
    def log_path(self) -> Path:
        return self.path.with_suffix(".log")


class TemplateLoopScriptError(RuntimeError):
    pass


class _TemplateLoopFinished(RuntimeError):
    def __init__(self, result: str = "success") -> None:
        super().__init__(result)
        self.result = result


class _TeeWriter:
    def __init__(self, file, stream=None) -> None:
        self.file = file
        self.stream = _utf8_text_stream(stream)

    def write(self, text: str) -> int:
        self.file.write(text)
        self.file.flush()
        if self.stream is not None:
            self.stream.write(text)
            self.stream.flush()
        return len(text)

    def flush(self) -> None:
        self.file.flush()
        if self.stream is not None:
            self.stream.flush()


def _utf8_text_stream(stream):
    if stream is None:
        return None
    if getattr(stream, "encoding", "") == "utf-8":
        return stream
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        return stream
    return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", write_through=True)


def _interactive_stdout_stream():
    stream = sys.__stdout__
    try:
        return stream if stream is not None and stream.isatty() else None
    except Exception:
        return None


def list_template_loop_scripts() -> list[str]:
    if not STATE_SCRIPTS_DIR.exists():
        return []
    names = []
    for path in _state_script_files():
        if is_template_loop_script_file(path):
            names.append(path.stem)
    return sorted(names)


def list_template_loop_script_files() -> list[Path]:
    if not STATE_SCRIPTS_DIR.exists():
        return []
    return sorted(path for path in _state_script_files() if is_template_loop_script_file(path))


def is_template_loop_script_file(path: str | Path) -> bool:
    try:
        data = load_yaml_config(path)
    except Exception:
        return False
    root = _script_root(data)
    return isinstance(root, dict) and bool(_string_tuple(root.get("loop_dirs")))


def sync_loop_dirs_rename(old_name: str, new_name: str) -> list[str]:
    """Scan all state script YAMLs and replace loop_dirs references to old_name with new_name.

    Returns the list of script stems that were updated.
    """
    try:
        old_canonical = _group_name_for_path(_resolve_group_path(old_name))
    except Exception:
        return []
    if not old_canonical:
        return []

    updated: list[str] = []
    for path in _state_script_files():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        has_script_wrapper = isinstance(data.get("script"), dict)
        root: dict[str, Any] = data["script"] if has_script_wrapper else data
        loop_dirs_raw = root.get("loop_dirs")
        if loop_dirs_raw is None:
            continue

        try:
            dirs = _string_tuple(loop_dirs_raw)
        except Exception:
            continue

        new_dirs: list[str] = []
        changed = False
        for entry in dirs:
            try:
                canonical = _group_name_for_path(_resolve_group_path(entry))
            except Exception:
                new_dirs.append(entry)
                continue
            if canonical == old_canonical:
                new_dirs.append(new_name)
                changed = True
            else:
                new_dirs.append(entry)

        if not changed:
            continue

        root["loop_dirs"] = new_dirs
        try:
            path.write_text(
                yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            updated.append(path.stem)
        except Exception:
            pass

    return updated


def load_template_loop_script(name_or_path: str | Path) -> TemplateLoopScriptDefinition:
    path = _template_loop_script_path(name_or_path)
    return parse_template_loop_script(load_yaml_config(path), path)


def parse_template_loop_script(data: dict[str, Any], path: str | Path) -> TemplateLoopScriptDefinition:
    script_path = Path(path)
    root = _script_root(data)
    if not isinstance(root, dict):
        raise TemplateLoopScriptError(f"Template loop script root must be a mapping: {script_path}")

    start_flows = _dedupe_strings(_string_tuple(root.get("start_flows")))

    loop_dirs = _dedupe_strings(_string_tuple(root.get("loop_dirs")))
    if not loop_dirs:
        raise TemplateLoopScriptError(f"Template loop script requires at least one loop_dirs entry: {script_path}")
    if DEFAULT_LOOP_DIR not in loop_dirs and (TEMPLATE_ICONS_DIR / DEFAULT_LOOP_DIR).is_dir():
        loop_dirs = (*loop_dirs, DEFAULT_LOOP_DIR)

    end_template = _optional_text(root.get("end_template", root.get("end")))
    completion_count = max(1, int(_first_present(
        root,
        "completion_count",
        "completionCount",
        "success_count",
        "successCount",
        "max_success",
        "maxSuccess",
        default=1,
    ) or 1))
    scales = _normalize_loop_scales(root.get("scales"))
    save_debug = _bool_value(root.get("save_debug", root.get("saveDebug", False)))
    no_match_recovery_rounds = max(1, int(root.get("no_match_recovery_rounds", 3)))
    no_match_recovery_wait_ms = max(0, int(root.get("no_match_recovery_wait_ms", 1000)))

    definition = TemplateLoopScriptDefinition(
        id=str(root.get("id") or script_path.stem).strip() or script_path.stem,
        path=script_path.resolve(),
        start_flows=start_flows,
        loop_dirs=loop_dirs,
        end_template=_normalize_template_reference(end_template) if end_template else None,
        completion_count=completion_count,
        scales=scales,
        save_debug=save_debug,
        no_match_recovery_rounds=no_match_recovery_rounds,
        no_match_recovery_wait_ms=no_match_recovery_wait_ms,
    )
    _resolve_loop_templates(definition)
    if definition.end_template:
        _resolve_template_path(definition.end_template)
    return definition


def run_template_loop_script_by_name(
    name_or_path: str | Path,
    hwnd: int,
    *,
    dry_run: bool = False,
    background_mode: bool = False,
    run_start_flows_first: bool = False,
    log_to_file: bool = True,
) -> ScriptContext:
    definition = load_template_loop_script(name_or_path)
    if not log_to_file:
        return _run_template_loop_script(
            definition,
            hwnd,
            dry_run=dry_run,
            background_mode=background_mode,
            run_start_flows_first=run_start_flows_first,
            flow_stack=(str(definition.path.resolve()),),
        )
    definition.log_path.parent.mkdir(parents=True, exist_ok=True)
    with definition.log_path.open("w", encoding="utf-8") as log_file:
        writer = _TeeWriter(log_file, _interactive_stdout_stream())
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            return _run_template_loop_script(
                definition,
                hwnd,
                dry_run=dry_run,
                background_mode=background_mode,
                run_start_flows_first=run_start_flows_first,
                flow_stack=(str(definition.path.resolve()),),
            )


def _run_nested_template_loop_script(
    name_or_path: str | Path,
    runtime: ScriptRuntime,
    *,
    parent_definition: TemplateLoopScriptDefinition,
) -> ScriptContext | None:
    definition = load_template_loop_script(name_or_path)
    stack = tuple(runtime.context.variables.get("state_flow_stack") or ())
    flow_key = str(definition.path.resolve())
    if flow_key in stack:
        _log(
            f"跳过递归状态流程：{definition.id}；"
            f"调用链={', '.join(Path(item).stem for item in stack)}"
        )
        return None

    _log(f"开始执行状态流程：{definition.id}（调用方：{parent_definition.id}）")
    previous_stack = runtime.context.variables.get("state_flow_stack")
    runtime.context.variables["state_flow_stack"] = [*stack, flow_key]
    try:
        nested_context = _run_template_loop_script(
            definition,
            runtime.hwnd,
            dry_run=runtime.context.dry_run,
            background_mode=runtime.context.background_mode,
            run_start_flows_first=True,
            flow_stack=(*stack, flow_key),
        )
        runtime.context.hwnd = nested_context.hwnd
        runtime.context.last_match = nested_context.last_match
        runtime.context.screenshot_path = nested_context.screenshot_path
        _log(f"状态流程执行完成：{definition.id}")
        return nested_context
    finally:
        if previous_stack is None:
            runtime.context.variables.pop("state_flow_stack", None)
        else:
            runtime.context.variables["state_flow_stack"] = previous_stack


def _check_pause_file(pause_file: Path) -> None:
    if not pause_file.exists():
        return
    _log("脚本已暂停，等待继续...")
    while pause_file.exists():
        time.sleep(0.5)
    _log("脚本已继续")


def _run_template_loop_script(
    definition: TemplateLoopScriptDefinition,
    hwnd: int,
    *,
    dry_run: bool,
    background_mode: bool,
    run_start_flows_first: bool = False,
    flow_stack: tuple[str, ...] = (),
) -> ScriptContext:
    context = ScriptContext(
        hwnd=hwnd,
        script_id=definition.id,
        dry_run=dry_run,
        background_mode=background_mode,
    )
    runtime = ScriptRuntime(context)
    context.variables["template_loop_script_path"] = str(definition.path)
    context.variables["template_loop_log_path"] = str(definition.log_path)
    context.variables["state_flow_stack"] = list(flow_stack)
    context.variables["start_flows"] = list(definition.start_flows)
    context.variables["loop_dirs"] = list(definition.loop_dirs)
    if definition.end_template:
        context.variables["end_template"] = definition.end_template

    all_loop_templates = _resolve_loop_templates(definition)
    loop_templates = _primary_loop_templates(all_loop_templates)
    fallback_templates = _fallback_loop_templates(all_loop_templates)
    end_templates = _definition_end_templates(definition, loop_templates)
    context.variables["completion_count"] = definition.completion_count
    context.variables["end_templates"] = [_project_relative(path) for path in end_templates]
    context.variables["non_standalone_templates"] = [
        _project_relative(path) for path in all_loop_templates if _template_is_non_standalone(path)
    ]
    context.variables["fallback_templates"] = [_project_relative(path) for path in fallback_templates]
    _log(f"启动模板循环脚本：{definition.id}（配置：{definition.path}）")
    _log(f"日志文件：{definition.log_path}")
    _log(f"恢复入口状态流程：{', '.join(definition.start_flows)}")
    _log(
        f"循环检测目录：{', '.join(definition.loop_dirs)}；模板数={len(loop_templates)}；"
        f"默认模板阈值={DEFAULT_TEMPLATE_MATCH_THRESHOLD:.3f}；缩放={','.join(f'{scale:.3f}' for scale in definition.scales)}；"
        f"保存调试图={'是' if definition.save_debug else '否'}；"
        f"无命中恢复前等待轮数={definition.no_match_recovery_rounds}；"
        f"无命中轮间等待={definition.no_match_recovery_wait_ms}ms"
    )
    _log(f"完成次数：{definition.completion_count}")
    if end_templates:
        _log(f"结束标识模板：{', '.join(_project_relative(path) for path in end_templates)}")
    non_standalone_templates = [_project_relative(path) for path in all_loop_templates if _template_is_non_standalone(path)]
    if non_standalone_templates:
        _log(f"非单独触发模板不参与 loop 主扫描：{', '.join(non_standalone_templates)}")
    if fallback_templates:
        _log(f"兜底模板不参与 loop 主扫描，仅整轮无命中时执行：{', '.join(_project_relative(path) for path in fallback_templates)}")

    pause_file = definition.path.with_suffix(".pause")
    try:
        runtime.focus()
        if run_start_flows_first:
            _log(f"启动前执行入口状态流程：{', '.join(definition.start_flows)}")
            _run_start_flows(runtime, definition, flow_stack=flow_stack)

        loop_index = 1
        no_match_rounds = 0
        while True:
            _check_pause_file(pause_file)
            result = _run_loop_once(
                runtime,
                definition,
                loop_templates=loop_templates,
                fallback_templates=fallback_templates,
                end_templates=end_templates,
                loop_index=loop_index,
            )
            if result == "no_template_matched":
                no_match_rounds += 1
                if no_match_rounds < definition.no_match_recovery_rounds:
                    _log(
                        f"连续无命中 {no_match_rounds}/{definition.no_match_recovery_rounds}，"
                        f"先等待后继续完整 loop，不执行恢复组件"
                    )
                    if definition.no_match_recovery_wait_ms > 0:
                        runtime.wait(
                            definition.no_match_recovery_wait_ms,
                            note="wait before no-match recovery",
                        )
                    loop_index += 1
                    continue
                _log(
                    f"连续无命中 {no_match_rounds}/{definition.no_match_recovery_rounds}，"
                    f"执行入口状态流程"
                )
                _run_start_flows(runtime, definition, flow_stack=flow_stack)
                no_match_rounds = 0
                loop_index += 1
                continue
            no_match_rounds = 0
            if result is not None:
                context.variables["result"] = result
                _log(f"脚本完成：流程结束原因=结果返回；结果={result}")
                break
            loop_index += 1
    except _TemplateLoopFinished as exc:
        context.variables["result"] = exc.result
        _log(f"脚本完成：流程结束原因=模板 action finish；结果={exc.result}")
    except ScriptPause as exc:
        context.variables["pause_reason"] = exc.reason
        _log(f"脚本暂停：原因={exc.reason}")
        _delete_transient_screenshot_if_current(context)
        raise
    except Exception as exc:
        context.variables["error"] = str(exc)
        _log(f"脚本异常退出：错误={exc}")
        _delete_transient_screenshot_if_current(context)
        raise
    finally:
        pause_file.unlink(missing_ok=True)
    return context


def _run_start_flows(
    runtime: ScriptRuntime,
    definition: TemplateLoopScriptDefinition,
    *,
    flow_stack: tuple[str, ...],
) -> None:
    if not definition.start_flows:
        _log("未配置入口状态流程，跳过入口恢复")
        return
    runtime.context.variables["state_flow_stack"] = list(flow_stack)
    for flow_name in definition.start_flows:
        _log(f"本轮没有命中模板，执行入口状态流程：{flow_name}")
        _run_nested_template_loop_script(flow_name, runtime, parent_definition=definition)
        _log(f"入口状态流程执行完成：{flow_name}")


def _execute_state_flow_action(
    runtime: ScriptRuntime,
    action: dict[str, Any],
    *,
    current_definition: TemplateLoopScriptDefinition,
) -> None:
    flow_name = _optional_text(action.get("flow") or action.get("name"))
    if flow_name is None:
        raise TemplateLoopScriptError("Template flow action requires a flow or name.")
    _run_nested_template_loop_script(flow_name, runtime, parent_definition=current_definition)


def _run_loop_once(
    runtime: ScriptRuntime,
    definition: TemplateLoopScriptDefinition,
    *,
    loop_templates: tuple[Path, ...],
    fallback_templates: tuple[Path, ...],
    end_templates: tuple[Path, ...],
    loop_index: int,
) -> str | None:
    step_name = f"template_loop_{loop_index:04d}"
    screenshot_path = runtime.context.transient_screenshot_output_path(step_name)
    capture = runtime.capture_client(screenshot_path)

    def skip_template(candidate: PriorityTemplateCandidate) -> tuple[Path, int, int] | None:
        limit_reached, limit, count = _template_match_limit_reached(runtime.context, candidate.path)
        return (candidate.path, count, limit or 0) if limit_reached else None

    def probe_template(candidate: PriorityTemplateCandidate) -> TemplateProbeResult:
        exclude_boxes = _template_match_position_boxes(runtime.context, candidate.path) if _template_avoid_same_position(candidate.path) else None
        probe = _match_on_capture(
            runtime,
            capture.path,
            candidate.path,
            threshold=_template_match_threshold(candidate.path),
            scales=definition.scales,
            save_debug=definition.save_debug,
            step_name=step_name,
            suffix=f"loop_{candidate.index:03d}",
            exclude_boxes=exclude_boxes,
        )
        return _apply_template_preconditions(
            runtime,
            probe,
            scales=definition.scales,
            save_debug=definition.save_debug,
            step_name=step_name,
            suffix=f"pre_{candidate.index:03d}",
        )

    priority_result = scan_priority_templates(
        loop_templates,
        priority_for=_template_priority,
        probe_template=probe_template,
        skip_template=skip_template,
    )
    best_probe = priority_result.best_probe
    probes = list(priority_result.probes)
    found_probes = list(priority_result.found)
    skipped_due_to_limit = list(priority_result.skipped)
    flagged_probes = _flagged_template_probes(
        runtime,
        capture.path,
        definition,
        loop_index=loop_index,
        step_name=step_name,
        known_probes=probes,
        loop_templates=loop_templates,
        end_templates=end_templates,
    )
    success_probes = [probe for probe in flagged_probes if probe.found and _template_is_success_template(probe.match.template_path)]
    end_probes = [probe for probe in flagged_probes if probe.found and probe.match.template_path.resolve() in {path.resolve() for path in end_templates}]

    if skipped_due_to_limit:
        skipped_text = "；".join(
            f"{_project_relative(path)} 已命中 {count}/{limit} 次"
            for path, count, limit in skipped_due_to_limit
        )
        _log(f"第 {loop_index} 轮：以下模板因达到分组内匹配次数上限而跳过：{skipped_text}")

    if success_probes:
        success_probe = _select_best_probe(success_probes)
        success_count = _record_success_template_match(runtime.context, success_probe.match.template_path)
        runtime.context.last_match = success_probe.match
        if success_count >= definition.completion_count:
            _log(
                f"第 {loop_index} 轮：流程结束原因=成功累计已达到完成次数；"
                f"成功累计={success_count}/{definition.completion_count}；"
                f"模板={_project_relative(success_probe.match.template_path)}"
            )
            _execute_template_actions(
                runtime,
                success_probe,
                scales=definition.scales,
                save_debug=definition.save_debug,
                current_definition=definition,
            )
            runtime.context.step_index += 1
            _delete_file_if_exists(capture.path)
            return "completion_count_reached"
        _log(
            f"第 {loop_index} 轮：命中成功标识模板；"
            f"成功累计={success_count}/{definition.completion_count}；"
            f"模板={_project_relative(success_probe.match.template_path)}"
        )

    if end_probes:
        end_probe = _select_best_probe(end_probes)
        runtime.context.last_match = end_probe.match
        _log(
            f"第 {loop_index} 轮：流程结束原因=命中结束标识模板；"
            f"模板={_project_relative(end_probe.match.template_path)}；得分={end_probe.match.score:.3f}"
        )
        _execute_template_actions(
            runtime,
            end_probe,
            scales=definition.scales,
            save_debug=definition.save_debug,
            current_definition=definition,
        )
        _delete_file_if_exists(capture.path)
        return "end_template_matched"

    if not found_probes:
        fallback_handled = _execute_fallback_template(
            runtime,
            capture.path,
            definition,
            fallback_templates=fallback_templates,
            loop_index=loop_index,
            step_name=step_name,
        )
        if fallback_handled:
            _log(f"第 {loop_index} 轮：兜底模板 action 执行完成，下一轮将重新执行完整模板循环")
            _delete_file_if_exists(capture.path)
            return None

        unrecognized_path = _save_unrecognized_template_candidate(runtime, definition, capture.path, loop_index=loop_index)
        if best_probe is not None:
            runtime.context.last_match = best_probe.match
            _log(
                f"第 {loop_index} 轮：没有模板达到阈值；"
                f"最高得分模板={_project_relative(best_probe.match.template_path)}，得分={best_probe.match.score:.3f}；"
                f"未识别截图已放入未识别目录={_project_relative(unrecognized_path)}"
            )
        else:
            _log(f"第 {loop_index} 轮：没有可用模板匹配结果；未识别截图已放入未识别目录={_project_relative(unrecognized_path)}")
        runtime.context.step_index += 1
        return "no_template_matched"

    selected = select_best_priority_match(found_probes, priority_for_match=lambda match: _template_priority(match.template_path))
    assert selected is not None
    selected_priority = _template_priority(selected.match.template_path)
    runtime.context.last_match = selected.match
    match_count = _record_template_match(runtime.context, selected.match.template_path)
    if _template_avoid_same_position(selected.match.template_path):
        _record_template_match_position(runtime.context, selected.match.template_path, selected.match.box)
    limit = _template_group_match_limit(selected.match.template_path)
    limit_text = f"/{limit}" if limit is not None else "/∞"
    # _log(
    #     f"第 {loop_index} 轮：命中模板={_project_relative(selected.match.template_path)}，"
    #     f"优先级={selected_priority}，得分={selected.match.score:.3f}，本轮命中数={len(found_probes)}，"
    #     f"当前模板累计命中={match_count}{limit_text}"
    # )
    _execute_template_actions(
        runtime,
        selected,
        scales=definition.scales,
        save_debug=definition.save_debug,
        current_definition=definition,
    )
    _delete_file_if_exists(capture.path)
    return None


def _execute_fallback_template(
    runtime: ScriptRuntime,
    image_path: Path,
    definition: TemplateLoopScriptDefinition,
    *,
    fallback_templates: tuple[Path, ...],
    loop_index: int,
    step_name: str,
) -> bool:
    if not fallback_templates:
        return False
    for index, template_path in enumerate(sorted(fallback_templates, key=lambda path: (-_template_priority(path), str(path)))):
        limit_reached, limit, count = _template_match_limit_reached(runtime.context, template_path)
        if limit_reached:
            _log(f"第 {loop_index} 轮：兜底模板因达到匹配次数上限跳过：{_project_relative(template_path)} 已命中 {count}/{limit}")
            continue
        probe = _match_on_capture(
            runtime,
            image_path,
            template_path,
            threshold=-1.0,
            scales=definition.scales,
            save_debug=definition.save_debug,
            step_name=step_name,
            suffix=f"fallback_{index:03d}",
        )
        runtime.context.last_match = probe.match
        match_count = _record_template_match(runtime.context, template_path)
        if _template_avoid_same_position(template_path):
            _record_template_match_position(runtime.context, template_path, probe.match.box)
        limit = _template_group_match_limit(template_path)
        limit_text = f"/{limit}" if limit is not None else "/∞"
        _log(
            f"第 {loop_index} 轮：整轮无模板命中，执行兜底模板={_project_relative(template_path)}，"
            f"优先级={_template_priority(template_path)}，当前模板累计命中={match_count}{limit_text}"
        )
        _execute_template_actions(
            runtime,
            probe,
            scales=definition.scales,
            save_debug=definition.save_debug,
            current_definition=definition,
        )
        return True
    return False


def _match_on_capture(
    runtime: ScriptRuntime,
    image_path: Path,
    template_path: Path,
    *,
    threshold: float,
    scales: tuple[float, ...],
    save_debug: bool,
    step_name: str,
    suffix: str,
    exclude_boxes: tuple[Rect, ...] | None = None,
) -> TemplateProbeResult:
    debug_path = runtime.context.debug_output_path(step_name, suffix) if save_debug else None
    match = match_template(
        image_path,
        template_path,
        threshold=threshold,
        scales=scales,
        debug_path=debug_path,
        exclude_boxes=exclude_boxes,
    )
    return TemplateProbeResult(found=match.found, match=match, screenshot_path=image_path, debug_path=debug_path)


def _save_unrecognized_template_candidate(
    runtime: ScriptRuntime,
    definition: TemplateLoopScriptDefinition,
    image_path: Path,
    *,
    loop_index: int,
) -> Path:
    group_path = _resolve_group_path(definition.loop_dirs[0])
    unrecognized_dir = group_path / "未识别"
    unrecognized_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = _unique_template_candidate_path(
        unrecognized_dir / f"unrecognized_{definition.id}_{timestamp}_loop{loop_index:04d}.png"
    )
    shutil.move(str(image_path), str(destination))
    metadata = {
        "template": destination.stem,
        "group": _group_name_for_path(destination.parent),
        "priority": 0,
        "is_non_standalone": True,
        "actions": [{"type": "none", "delay_after_ms": 0}],
        "source": "template_loop_unrecognized",
        "source_script": definition.path.name,
        "run_id": runtime.context.run_id,
        "loop_index": loop_index,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    destination.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_unrecognized_template_dir(unrecognized_dir, keep=UNRECOGNIZED_TEMPLATE_KEEP_LIMIT)
    runtime.context.screenshot_path = destination
    return destination


def _prune_unrecognized_template_dir(directory: Path, *, keep: int) -> None:
    if keep <= 0:
        return
    try:
        images = sorted(
            (path for path in directory.glob("*.png") if path.is_file()),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
    except OSError:
        return
    for image_path in images[keep:]:
        _delete_file_if_exists(image_path)
        _delete_file_if_exists(image_path.with_suffix(".json"))


def _unique_template_candidate_path(path: Path) -> Path:
    if not path.exists() and not path.with_suffix(".json").exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
        if not candidate.exists() and not candidate.with_suffix(".json").exists():
            return candidate
    raise TemplateLoopScriptError(f"Unable to allocate unrecognized template filename: {path}")


def _delete_file_if_exists(path: Path | None) -> None:
    if path is None:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _delete_transient_screenshot_if_current(context: ScriptContext) -> None:
    path = context.screenshot_path
    if path is None:
        return
    if Path(path).name.startswith(".") and Path(path).name.endswith(".tmp.png"):
        _delete_file_if_exists(path)


def _flagged_template_probes(
    runtime: ScriptRuntime,
    image_path: Path,
    definition: TemplateLoopScriptDefinition,
    *,
    loop_index: int,
    step_name: str,
    known_probes: list[tuple[int, TemplateProbeResult]],
    loop_templates: tuple[Path, ...],
    end_templates: tuple[Path, ...],
) -> list[TemplateProbeResult]:
    known_by_path = {probe.match.template_path.resolve(): probe for _index, probe in known_probes}
    flagged_paths: list[Path] = []
    seen: set[Path] = set()
    for path in (*end_templates, *_success_template_paths(loop_templates)):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        flagged_paths.append(resolved)

    probes: list[TemplateProbeResult] = []
    for path in flagged_paths:
        known = known_by_path.get(path)
        if known is not None:
            probes.append(known)
            continue
        limit_reached, limit, count = _template_match_limit_reached(runtime.context, path)
        if limit_reached:
            _log(f"第 {loop_index} 轮：标识模板因达到匹配次数上限跳过：{_project_relative(path)} 已命中 {count}/{limit}")
            continue
        probe = _match_on_capture(
            runtime,
            image_path,
            path,
            threshold=_template_match_threshold(path),
            scales=definition.scales,
            save_debug=definition.save_debug,
            step_name=step_name,
            suffix=f"flagged_{len(probes):03d}",
        )
        probe = _apply_template_preconditions(
            runtime,
            probe,
            scales=definition.scales,
            save_debug=definition.save_debug,
            step_name=step_name,
            suffix=f"flagged_pre_{len(probes):03d}",
        )
        probes.append(probe)
    return probes


def _select_best_probe(probes: list[TemplateProbeResult]) -> TemplateProbeResult:
    return sorted(
        probes,
        key=lambda probe: (_template_priority(probe.match.template_path), probe.match.score, str(probe.match.template_path)),
        reverse=True,
    )[0]


def _apply_template_preconditions(
    runtime: ScriptRuntime,
    probe: TemplateProbeResult,
    *,
    scales: tuple[float, ...],
    save_debug: bool,
    step_name: str,
    suffix: str,
) -> TemplateProbeResult:
    if not probe.found:
        return probe
    required_templates = _template_precondition_templates(probe.match.template_path)
    excluded_templates = _template_postcondition_not_templates(probe.match.template_path)
    if not required_templates and not excluded_templates:
        return probe

    missing: list[str] = []
    for index, template_path in enumerate(required_templates, start=1):
        pre_probe = _match_on_capture(
            runtime,
            probe.screenshot_path,
            template_path,
            threshold=_template_match_threshold(template_path),
            scales=scales,
            save_debug=save_debug,
            step_name=step_name,
            suffix=f"{suffix}_required_{index:02d}",
        )
        if not pre_probe.found:
            missing.append(_project_relative(template_path))

    present_excluded: list[str] = []
    offset = len(required_templates)
    for index, template_path in enumerate(excluded_templates, start=1):
        not_probe = _match_on_capture(
            runtime,
            probe.screenshot_path,
            template_path,
            threshold=_template_match_threshold(template_path),
            scales=scales,
            save_debug=save_debug,
            step_name=step_name,
            suffix=f"{suffix}_excluded_{offset + index:02d}",
        )
        if not_probe.found:
            present_excluded.append(_project_relative(template_path))

    if not missing and not present_excluded:
        details: list[str] = []
        if required_templates:
            details.append(f"后置模板={', '.join(_project_relative(path) for path in required_templates)}")
        if excluded_templates:
            details.append(f"后置非模板={', '.join(_project_relative(path) for path in excluded_templates)}")
        _log(f"模板后置条件满足：模板={_project_relative(probe.match.template_path)}；" + "；".join(details))
        return probe

    reason_parts: list[str] = []
    if missing:
        reason_parts.append(f"缺失后置模板={', '.join(missing)}")
    if present_excluded:
        reason_parts.append(f"命中后置非模板={', '.join(present_excluded)}")
    _log(
        f"模板后置条件不满足，忽略当前命中：模板={_project_relative(probe.match.template_path)}；"
        + "；".join(reason_parts)
    )
    inactive_match = type(probe.match)(
        found=False,
        score=probe.match.score,
        box=probe.match.box,
        center=probe.match.center,
        template_path=probe.match.template_path,
        image_path=probe.match.image_path,
        debug_path=probe.match.debug_path,
        scale=probe.match.scale,
    )
    return TemplateProbeResult(found=False, match=inactive_match, screenshot_path=probe.screenshot_path, debug_path=probe.debug_path)


def _execute_template_actions(
    runtime: ScriptRuntime,
    probe: TemplateProbeResult,
    *,
    scales: tuple[float, ...],
    save_debug: bool,
    current_definition: TemplateLoopScriptDefinition | None = None,
) -> None:
    actions = _template_actions(probe.match.template_path)
    metadata = _template_metadata(probe.match.template_path)
    for action in actions:
        action_type = str(action.get("type") or "").strip()
        if not action_type:
            raise TemplateLoopScriptError(f"Template action requires type: {probe.match.template_path}")
        if action_type == "none":
            delay_after_ms = int(action.get("delay_after_ms", action.get("duration_ms", 500)) or 0)
            _log(f"模板已匹配但配置为无动作：{_project_relative(probe.match.template_path)}")
            if delay_after_ms > 0:
                runtime.wait(delay_after_ms, note=_optional_text(action.get("note")) or f"无动作等待 {probe.match.template_path.name}")
            continue
        if action_type == "click_match":
            runtime.click_match(
                probe,
                use_random_region=bool(action.get("use_random_region", False)),
                delay_after_ms=int(action.get("delay_after_ms", 500)),
                note=_optional_text(action.get("note")),
            )
            continue
        if action_type == "drag_match":
            runtime.drag_match(
                probe,
                direction=str(action.get("direction") or "up"),
                distance=int(action.get("distance", 300)),
                distance_percent=_optional_float(action.get("distance_percent", action.get("distancePercent"))),
                duration_ms=int(action.get("duration_ms", 300)),
                steps=int(action.get("steps", 12)),
                delay_after_ms=int(action.get("delay_after_ms", 500)),
                note=_optional_text(action.get("note")),
            )
            continue
        if action_type == "drag_point":
            runtime.drag_point(
                Point(x=int(action.get("x", 0)), y=int(action.get("y", 0))),
                direction=str(action.get("direction") or "up"),
                distance=int(action.get("distance", 300)),
                duration_ms=int(action.get("duration_ms", 300)),
                steps=int(action.get("steps", 12)),
                delay_after_ms=int(action.get("delay_after_ms", 500)),
                note=_optional_text(action.get("note")),
            )
            continue
        if action_type == "wait":
            runtime.wait(int(action.get("duration_ms", 500)), note=_optional_text(action.get("note")))
            continue
        if action_type == "key":
            runtime.press_key(
                str(action.get("key") or "esc"),
                duration_ms=int(action.get("duration_ms", 50)),
                delay_after_ms=int(action.get("delay_after_ms", 0)),
                loop_count=int(action.get("loop_count", action.get("loopCount", 1)) or 1),
                note=_optional_text(action.get("note")),
            )
            continue
        if action_type == "flow":
            if current_definition is None:
                raise TemplateLoopScriptError(
                    f"Template flow action requires current definition: {probe.match.template_path}"
                )
            _execute_state_flow_action(runtime, action, current_definition=current_definition)
            continue
        if action_type == "template":
            _log(f"忽略旧版 action 指定模板配置，改由动作后指定模板属性执行：{_project_relative(probe.match.template_path)}")
            continue
        if action_type == "log":
            _log(str(action.get("message") or ""))
            continue
        if action_type == "pause":
            raise ScriptPause(str(action.get("reason") or "paused"))
        if action_type == "finish":
            raise _TemplateLoopFinished(str(action.get("result") or "success"))
        raise TemplateLoopScriptError(f"Unsupported template action: {action_type}")

    _wait_for_template_end(
        runtime,
        probe.match.template_path,
        metadata=metadata,
        scales=scales,
        save_debug=save_debug,
    )
    _execute_post_action_template(
        runtime,
        probe.match.template_path,
        metadata=metadata,
        scales=scales,
        save_debug=save_debug,
    )


def _execute_post_action_template(
    runtime: ScriptRuntime,
    template_path: Path,
    *,
    metadata: dict[str, Any],
    scales: tuple[float, ...],
    save_debug: bool,
) -> None:
    template_value = _optional_text(metadata.get("post_action_template") or metadata.get("next_template"))
    if template_value is None:
        return
    action: dict[str, Any] = {"template": template_value}
    action_threshold = metadata.get("post_action_template_threshold", metadata.get("next_template_threshold"))
    if action_threshold not in (None, ""):
        action["threshold"] = action_threshold
    delay_after_ms = metadata.get("post_action_template_delay_ms", metadata.get("next_template_delay_ms"))
    if delay_after_ms not in (None, ""):
        action["delay_after_ms"] = delay_after_ms
    _log(f"模板 action 后继续检查目标模板：源={_project_relative(template_path)}，目标={template_value}")
    _execute_template_reference_action(
        runtime,
        action,
        scales=scales,
        save_debug=save_debug,
        source_step_name=template_path.stem,
    )


def _execute_template_reference_action(
    runtime: ScriptRuntime,
    action: dict[str, Any],
    *,
    scales: tuple[float, ...],
    save_debug: bool,
    source_step_name: str,
) -> None:
    template_value = _optional_text(action.get("template"))
    if not template_value:
        raise TemplateLoopScriptError("Template action requires template.")
    depth = int(runtime.context.variables.get("template_action_depth", 0) or 0)
    if depth >= 3:
        raise TemplateLoopScriptError(f"Template action recursion limit exceeded: {template_value}")

    template_path = _resolve_template_path(template_value)
    action_threshold = _optional_template_match_threshold(action.get("threshold")) or _template_match_threshold(template_path)
    step_name = f"template_action_{source_step_name}_{depth + 1:02d}"
    screenshot_path = runtime.context.transient_screenshot_output_path(step_name)
    capture = runtime.capture_client(screenshot_path)
    probe = _match_on_capture(
        runtime,
        capture.path,
        template_path,
        threshold=action_threshold,
        scales=scales,
        save_debug=save_debug,
        step_name=step_name,
        suffix="template_action",
    )
    runtime.context.last_match = probe.match
    # _log(
    #     f"模板动作检查：得分={probe.match.score:.3f}，是否命中={'是' if probe.found else '否'}，"
    #     f"模板={_project_relative(template_path)}"
    # )
    if not probe.found:
        _delete_file_if_exists(capture.path)
        raise ScriptPause(f"template_action_not_found:{_project_relative(template_path)}")

    runtime.context.variables["template_action_depth"] = depth + 1
    try:
        _execute_template_actions(
            runtime,
            probe,
            scales=scales,
            save_debug=save_debug,
        )
    finally:
        if depth:
            runtime.context.variables["template_action_depth"] = depth
        else:
            runtime.context.variables.pop("template_action_depth", None)
        _delete_file_if_exists(capture.path)

    delay_after_ms = int(action.get("delay_after_ms", 0) or 0)
    if delay_after_ms > 0:
        runtime.wait(delay_after_ms, note=f"模板动作后等待 {template_path.name}")


def _action_start_point(runtime: ScriptRuntime, action: dict[str, Any]) -> Point:
    start_from = _optional_text(action.get("start_from"))
    if start_from == "window_center":
        info = get_window_info(runtime.hwnd)
        return Point(
            x=max(0, info.client_size.width // 2),
            y=max(0, info.client_size.height // 2),
        )
    return Point(x=int(action.get("x", 0)), y=int(action.get("y", 0)))


def _template_metadata(template_path: Path) -> dict[str, Any]:
    metadata_path = template_path.with_suffix(".json")
    if not metadata_path.is_file():
        return {}
    try:
        raw_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_metadata, dict):
        return {}
    return _migrated_template_metadata(raw_metadata)


def _migrated_template_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    data = dict(metadata)
    raw_actions = data.get("actions")
    actions = raw_actions if isinstance(raw_actions, list) else [raw_actions]
    template_action = next((action for action in actions if isinstance(action, dict) and action.get("type") == "template"), None)
    if template_action is not None and not _optional_text(data.get("post_action_template") or data.get("next_template")):
        data["post_action_template"] = template_action.get("template")
        if template_action.get("threshold") not in (None, ""):
            data["post_action_template_threshold"] = template_action.get("threshold")
        if template_action.get("delay_after_ms") not in (None, ""):
            data["post_action_template_delay_ms"] = template_action.get("delay_after_ms")
    if template_action is not None and isinstance(raw_actions, list):
        data["actions"] = [action for action in raw_actions if not (isinstance(action, dict) and action.get("type") == "template")]
    elif template_action is not None:
        data.pop("actions", None)
    return data


def _template_priority(template_path: Path) -> float:
    metadata = _template_metadata(template_path)
    raw_priority = metadata.get("priority")
    if raw_priority in (None, ""):
        return 0.0
    try:
        return float(raw_priority)
    except (TypeError, ValueError):
        return 0.0


def _template_match_threshold(template_path: Path) -> float:
    metadata = _template_metadata(template_path)
    return _optional_template_match_threshold(metadata.get("threshold")) or DEFAULT_TEMPLATE_MATCH_THRESHOLD


def _optional_template_match_threshold(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        threshold = float(value)
    except (TypeError, ValueError) as exc:
        raise TemplateLoopScriptError(f"Template threshold must be a number: {value!r}") from exc
    if not isfinite(threshold) or threshold <= 0 or threshold > 1:
        raise TemplateLoopScriptError(f"Template threshold must be in (0, 1]: {value!r}")
    return threshold


def _template_is_end_template(template_path: Path) -> bool:
    return _metadata_bool(_template_metadata(template_path).get("is_end_template"))


def _template_is_success_template(template_path: Path) -> bool:
    return _metadata_bool(_template_metadata(template_path).get("is_success_template"))


def _template_is_non_standalone(template_path: Path) -> bool:
    metadata = _template_metadata(template_path)
    return _metadata_bool(metadata.get("is_non_standalone") or metadata.get("non_standalone"))


def _template_is_fallback_template(template_path: Path) -> bool:
    metadata = _template_metadata(template_path)
    return _metadata_bool(metadata.get("is_fallback_template") or metadata.get("fallback_template"))


def _template_avoid_same_position(template_path: Path) -> bool:
    metadata = _template_metadata(template_path)
    return _metadata_bool(metadata.get("avoid_same_position") or metadata.get("not_match_same_position"))


def _metadata_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _definition_end_templates(definition: TemplateLoopScriptDefinition, loop_templates: tuple[Path, ...]) -> tuple[Path, ...]:
    templates: list[Path] = []
    seen: set[Path] = set()
    for template_path in loop_templates:
        if not _template_is_end_template(template_path):
            continue
        resolved = template_path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            templates.append(resolved)
    if definition.end_template:
        resolved = _resolve_template_path(definition.end_template)
        if resolved not in seen:
            templates.append(resolved)
    return tuple(templates)


def _success_template_paths(loop_templates: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(path.resolve() for path in loop_templates if _template_is_success_template(path))


def _template_group_match_limit(template_path: Path) -> int | None:
    metadata = _template_metadata(template_path)
    raw_limit = metadata.get("group_match_limit")
    if raw_limit in (None, ""):
        return None
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return None
    return limit if limit >= 1 else None


def _template_precondition_templates(template_path: Path) -> tuple[Path, ...]:
    metadata = _template_metadata(template_path)
    raw_value = (
        metadata.get("postcondition_templates")
        or metadata.get("postcondition_template")
        or metadata.get("precondition_templates")
        or metadata.get("precondition_template")
        or metadata.get("requires_templates")
        or metadata.get("requires_template")
    )
    return _template_references(raw_value)


def _template_postcondition_not_templates(template_path: Path) -> tuple[Path, ...]:
    metadata = _template_metadata(template_path)
    raw_value = (
        metadata.get("postcondition_not_templates")
        or metadata.get("postcondition_not_template")
        or metadata.get("excludes_templates")
        or metadata.get("excludes_template")
    )
    return _template_references(raw_value)


def _template_references(raw_value: Any) -> tuple[Path, ...]:
    if raw_value in (None, "", []):
        return ()
    values = raw_value if isinstance(raw_value, list) else [raw_value]
    templates: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if value in (None, ""):
            continue
        resolved = _resolve_template_path(str(value))
        if resolved in seen:
            continue
        seen.add(resolved)
        templates.append(resolved)
    return tuple(templates)


def _template_match_count(context: ScriptContext, template_path: Path) -> int:
    match_counts = context.variables.setdefault("template_group_match_counts", {})
    key = _project_relative(template_path)
    value = match_counts.get(key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _record_template_match(context: ScriptContext, template_path: Path) -> int:
    match_counts = context.variables.setdefault("template_group_match_counts", {})
    key = _project_relative(template_path)
    count = _template_match_count(context, template_path) + 1
    match_counts[key] = count
    return count


def _record_template_match_position(context: ScriptContext, template_path: Path, box: Rect) -> None:
    positions = context.variables.setdefault("template_group_match_positions", {})
    key = _project_relative(template_path)
    records = positions.setdefault(key, [])
    records.append({"left": box.left, "top": box.top, "right": box.right, "bottom": box.bottom})


def _template_match_position_boxes(context: ScriptContext, template_path: Path) -> tuple[Rect, ...]:
    positions = context.variables.setdefault("template_group_match_positions", {})
    records = positions.get(_project_relative(template_path), [])
    boxes: list[Rect] = []
    if not isinstance(records, list):
        return ()
    for item in records:
        if not isinstance(item, dict):
            continue
        try:
            box = Rect(int(item["left"]), int(item["top"]), int(item["right"]), int(item["bottom"]))
        except (KeyError, TypeError, ValueError):
            continue
        if box.width > 0 and box.height > 0:
            boxes.append(box)
    return tuple(boxes)


def _record_success_template_match(context: ScriptContext, template_path: Path) -> int:
    total = int(context.variables.get("template_success_match_count", 0) or 0) + 1
    context.variables["template_success_match_count"] = total
    per_template = context.variables.setdefault("template_success_match_counts", {})
    key = _project_relative(template_path)
    per_template[key] = int(per_template.get(key, 0) or 0) + 1
    return total


def _template_match_limit_reached(context: ScriptContext, template_path: Path) -> tuple[bool, int | None, int]:
    limit = _template_group_match_limit(template_path)
    count = _template_match_count(context, template_path)
    return (limit is not None and count >= limit, limit, count)


def _coerce_template_actions(
    raw_actions: Any,
    metadata_path: Path,
    *,
    field_name: str,
) -> tuple[dict[str, Any], ...]:
    if raw_actions in (None, ""):
        return ()
    if isinstance(raw_actions, str):
        return ({"type": raw_actions},)
    if isinstance(raw_actions, dict):
        return (raw_actions,)
    if isinstance(raw_actions, list):
        actions = []
        for item in raw_actions:
            if not isinstance(item, dict):
                raise TemplateLoopScriptError(f"Template {field_name} must be mappings: {metadata_path}")
            actions.append(item)
        return tuple(actions)
    raise TemplateLoopScriptError(f"Invalid template {field_name} metadata: {metadata_path}")


def _template_actions(template_path: Path) -> tuple[dict[str, Any], ...]:
    metadata_path = template_path.with_suffix(".json")
    metadata = _template_metadata(template_path)

    raw_actions = metadata.get("actions")
    if raw_actions is None:
        raw_actions = metadata.get("action")
    if raw_actions is None:
        raw_actions = metadata.get("ability")
    if raw_actions in (None, "") or raw_actions == []:
        return ({"type": "click_match", "delay_after_ms": 500},)
    return _coerce_template_actions(raw_actions, metadata_path, field_name="actions")


def _wait_for_template_end(
    runtime: ScriptRuntime,
    template_path: Path,
    *,
    metadata: dict[str, Any],
    scales: tuple[float, ...],
    save_debug: bool,
) -> None:
    end_template_value = _optional_text(metadata.get("end_template"))
    if end_template_value is None:
        return
    end_template_path = _resolve_template_path(end_template_value)
    _log(
        f"模板 {template_path.name} 动作后等待结束模板：{_project_relative(end_template_path)}"
    )
    wait_index = 1
    while True:
        step_name = f"template_end_wait_{template_path.stem}_{wait_index:03d}"
        screenshot_path = runtime.context.transient_screenshot_output_path(step_name)
        capture = runtime.capture_client(screenshot_path)
        probe = _match_on_capture(
            runtime,
            capture.path,
            end_template_path,
            threshold=_template_match_threshold(end_template_path),
            scales=scales,
            save_debug=save_debug,
            step_name=step_name,
            suffix="end_wait",
        )
        runtime.context.last_match = probe.match
        runtime.context.step_index += 1
        # _log(
        #     f"等待结束模板第 {wait_index} 次：得分={probe.match.score:.3f}，"
        #     f"是否命中={'是' if probe.found else '否'}，模板={_project_relative(end_template_path)}"
        # )
        _delete_file_if_exists(capture.path)
        if probe.found:
            return
        runtime.wait(500, note=f"继续等待结束模板 {end_template_path.name}")
        wait_index += 1


def _resolve_loop_templates(definition: TemplateLoopScriptDefinition) -> tuple[Path, ...]:
    templates: list[Path] = []
    seen: set[Path] = set()
    for loop_dir in definition.loop_dirs:
        group_path = _resolve_group_path(loop_dir)
        if not group_path.exists():
            raise TemplateLoopScriptError(f"Loop template directory does not exist: {group_path}")
        for template_path in sorted(path for path in group_path.glob("*.png") if path.is_file()):
            resolved = template_path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            templates.append(resolved)
    if not templates:
        raise TemplateLoopScriptError(f"Loop template directories contain no PNG templates: {', '.join(definition.loop_dirs)}")
    return tuple(templates)


def _primary_loop_templates(templates: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(path for path in templates if not _template_is_non_standalone(path) and not _template_is_fallback_template(path))


def _fallback_loop_templates(templates: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(path for path in templates if _template_is_fallback_template(path))


def _resolve_group_path(group: str | Path) -> Path:
    raw = str(group).strip().replace("\\", "/").strip("/")
    if not raw:
        raise TemplateLoopScriptError("Loop template directory name cannot be empty")
    path = Path(raw)
    if path.is_absolute():
        raise TemplateLoopScriptError("Loop template directory must be relative to templates/icons")
    if raw.startswith("templates/icons/"):
        path = Path(raw.removeprefix("templates/icons/"))
    elif raw.startswith("templates/"):
        raise TemplateLoopScriptError("Loop template directory must be under templates/icons")
    for part in path.parts:
        if part in ("", ".", ".."):
            raise TemplateLoopScriptError(f"Invalid loop template directory segment: {part!r}")
    resolved = (TEMPLATE_ICONS_DIR / path).resolve()
    if not resolved.is_relative_to(TEMPLATE_ICONS_DIR.resolve()):
        raise TemplateLoopScriptError(f"Loop template directory must stay inside {TEMPLATE_ICONS_DIR}: {resolved}")
    return resolved


def _group_name_for_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(TEMPLATE_ICONS_DIR.resolve()).as_posix()
    except ValueError:
        return ""


def _resolve_template_path(value: str | Path | None) -> Path:
    if value in (None, ""):
        raise TemplateLoopScriptError("Template path cannot be empty")
    normalized = _normalize_template_reference(str(value))
    path = Path(normalized)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    if not resolved.is_relative_to(TEMPLATES_DIR.resolve()):
        raise TemplateLoopScriptError(f"Template path must stay inside {TEMPLATES_DIR}: {resolved}")
    if not resolved.is_file():
        raise TemplateLoopScriptError(f"Template file does not exist: {resolved}")
    if resolved.suffix.lower() != ".png":
        raise TemplateLoopScriptError(f"Template file must be PNG: {resolved}")
    return resolved


def _normalize_template_reference(value: str | None) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    normalized = text.replace("\\", "/").strip()
    if normalized.startswith("templates/"):
        return normalized
    if "/" in normalized:
        return f"templates/icons/{normalized}".replace("//", "/")
    name = normalized if normalized.lower().endswith(".png") else f"{normalized}.png"
    return f"templates/icons/{name}"


def _template_loop_script_path(name_or_path: str | Path) -> Path:
    raw = Path(name_or_path)
    if raw.is_absolute():
        path = raw
    elif raw.parent != Path("."):
        path = PROJECT_ROOT / raw
    elif raw.suffix.lower() in {".yaml", ".yml"}:
        path = STATE_SCRIPTS_DIR / raw.name
    else:
        path = STATE_SCRIPTS_DIR / f"{raw.name}.yaml"
    resolved = path.resolve()
    if not resolved.exists():
        raise TemplateLoopScriptError(f"Template loop script file does not exist: {resolved}")
    if not resolved.is_relative_to(STATE_SCRIPTS_DIR.resolve()):
        raise TemplateLoopScriptError(f"Template loop script must stay inside {STATE_SCRIPTS_DIR}: {resolved}")
    return resolved


def safe_template_loop_script_path(filename: str) -> Path:
    name = Path(filename).name
    if not name or name != filename or Path(name).suffix.lower() not in {".yaml", ".yml"}:
        raise TemplateLoopScriptError("Script filename must be a YAML file name without directories.")
    path = (STATE_SCRIPTS_DIR / name).resolve()
    if not path.is_relative_to(STATE_SCRIPTS_DIR.resolve()):
        raise TemplateLoopScriptError(f"Script path must stay inside {STATE_SCRIPTS_DIR}: {path}")
    return path


def template_loop_definition_payload(definition: TemplateLoopScriptDefinition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "filename": definition.path.name,
        "path": str(definition.path),
        "log_path": str(definition.log_path),
        "start": list(definition.start_flows),
        "start_flows": list(definition.start_flows),
        "loopDir": list(definition.loop_dirs),
        "end": definition.end_template or "",
        "end_template": definition.end_template or "",
        "completion_count": definition.completion_count,
        "completionCount": definition.completion_count,
        "scales": list(definition.scales),
        "save_debug": definition.save_debug,
        "valid": True,
        "message": "OK",
    }


def _state_script_files() -> list[Path]:
    return sorted([*STATE_SCRIPTS_DIR.glob("*.yaml"), *STATE_SCRIPTS_DIR.glob("*.yml")])


def _script_root(data: dict[str, Any]) -> dict[str, Any]:
    root = data.get("script") if isinstance(data.get("script"), dict) else data
    return root if isinstance(root, dict) else {}


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, list):
        out = [str(item).strip() for item in value if str(item).strip()]
        return tuple(out)
    raise TemplateLoopScriptError(f"Expected string or list of strings, got: {value!r}")


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _first_present(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value in (None, ""):
        return False
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise TemplateLoopScriptError(f"Expected boolean value, got: {value!r}")


def _normalize_loop_scales(value: Any) -> tuple[float, ...]:
    if value in (None, ""):
        return (1.0,)
    if isinstance(value, (int, float)):
        scales = (float(value),)
    elif isinstance(value, str):
        scales = (float(value.strip()),)
    elif isinstance(value, list):
        scales = tuple(float(item) for item in value)
    else:
        raise TemplateLoopScriptError(f"Expected number or list of numbers for scales, got: {value!r}")
    if not scales:
        raise TemplateLoopScriptError("At least one template scale is required.")
    normalized = []
    for scale in scales:
        if not isfinite(scale) or scale <= 0:
            raise TemplateLoopScriptError(f"Template scale must be a positive finite number: {scale}")
        rounded = round(float(scale), 6)
        if rounded not in normalized:
            normalized.append(rounded)
    return tuple(normalized)


def _dedupe_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _project_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] [template-loop] {message}", flush=True)
