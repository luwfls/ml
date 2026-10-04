import json
import mimetypes
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from game_bot.config.loader import CONFIG_DIR, PROJECT_ROOT, load_popups, load_settings, parse_yaml_text
from game_bot.core.capture import CaptureError, capture_client_to_file
from game_bot.core.input import click_client, drag_client, press_key
from game_bot.core.models import Point, Rect, Size, WindowInfo
from game_bot.core.window import (
    WindowError,
    bring_window_to_foreground,
    dock_window_to_rect,
    ensure_window_client_size,
    find_window_by_process_name,
    find_window_by_title,
    get_cursor_screen_position,
    get_window_info,
    is_window_alive,
    move_window,
    prepare_window_for_automation,
    resize_window,
    screen_size,
    screen_to_client,
    set_window_topmost,
    toggle_window_fullscreen,
)
from game_bot.scripted.context import ScriptContext
from game_bot.scripted.priority_match import PriorityTemplateCandidate, scan_priority_templates, select_best_priority_match
from game_bot.scripted.runtime import ScriptRuntime, TemplateProbeResult
from game_bot.scripted.loop_manager import TemplateLoopProcessManager
from game_bot.scripted.loop_script import (
    _execute_template_actions,
    _metadata_bool,
    _template_precondition_templates,
    safe_template_loop_script_path,
    sync_loop_dirs_rename,
)
from game_bot.vision.template import default_debug_path, match_template
from game_bot.vision.templates import (
    copy_template,
    copy_template_group,
    create_template_group,
    crop_template_from_image,
    delete_template,
    delete_template_group,
    expand_template_references,
    inspect_template,
    list_template_groups,
    list_templates,
    rename_template,
    rename_template_group,
    save_template_metadata,
)
from game_bot.workflow.engine import create_workflow_context, run_workflow
from game_bot.workflow.loader import WORKFLOWS_DIR, load_workflow, parse_workflow
from game_bot.workflow.recorder import WorkflowRecorder

TEMPLATES_DIR = PROJECT_ROOT / "templates"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
BACKUP_DIR = RUNTIME_DIR / "backups"
ALLOWED_IMAGE_ROOTS = (TEMPLATES_DIR.resolve(), RUNTIME_DIR.resolve())
DEFAULT_TEMPLATE_MATCH_THRESHOLD = 0.85
_TEMPLATE_METADATA_CACHE: dict[Path, tuple[int, int, dict[str, Any] | None]] = {}


@dataclass
class WindowWorkbenchServer:
    server: ThreadingHTTPServer
    thread: threading.Thread
    host: str
    port: int
    startup_window: dict[str, Any] | None = None
    startup_error: str | None = None

    def url(self, path: str = "/") -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"http://{self.host}:{self.port}{path}"

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def start_window_workbench_server(
    editor_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
) -> WindowWorkbenchServer:
    handler, state = _handler_for(editor_path)
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bound_host, bound_port = server.server_address
    _register_window_hotkeys(state)
    return WindowWorkbenchServer(
        server=server,
        thread=thread,
        host=str(bound_host),
        port=int(bound_port),
        startup_window=state.get("startup_window"),
        startup_error=state.get("startup_error"),
    )


def _handler_for(editor_path: Path):
    editor_path = editor_path.resolve()
    loop_manager = TemplateLoopProcessManager()
    state: dict[str, Any] = {"hwnd": None, "runs": {}, "startup_window": None, "startup_error": None, "fullscreen_state": {}}
    state_lock = threading.Lock()

    class WindowWorkbenchRequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                self._send_html(editor_path)
                return
            if path == "/api/health":
                self._send_json({"ok": True, "name": "monster-job32-window-workbench", "capabilities": _capabilities()})
                return
            if path == "/api/bootstrap":
                with state_lock:
                    startup_window = state["startup_window"]
                    startup_error = state["startup_error"]
                self._send_json(
                    {
                        "ok": True,
                        "capabilities": _capabilities(),
                        "settings": _settings_payload(),
                        "templates": _list_template_payloads(),
                        "template_groups": _list_template_group_payloads(),
                        "workflows": _list_workflows(),
                        "template_loop_flows": loop_manager.list_flows(),
                        "window": startup_window,
                        "startup": {"window_prepared": startup_window is not None, "error": startup_error},
                    }
                )
                return
            if path == "/api/templates":
                self._send_json({"ok": True, "templates": _list_template_payloads(), "template_groups": _list_template_group_payloads()})
                return
            if path == "/api/template-groups":
                self._send_json({"ok": True, "groups": _list_template_group_payloads()})
                return
            if path == "/api/template-preview":
                self._send_image(_safe_image_path(_query_value(parsed, "path"), allowed_roots=(TEMPLATES_DIR.resolve(),)))
                return
            if path == "/api/image-preview":
                self._send_image(_safe_image_path(_query_value(parsed, "path"), allowed_roots=ALLOWED_IMAGE_ROOTS))
                return
            if path == "/api/workflows":
                self._send_json({"ok": True, "workflows": _list_workflows()})
                return
            if path == "/api/template-loop-flows":
                self._send_json({"ok": True, "flows": loop_manager.list_flows()})
                return
            if path.startswith("/api/template-loop-flows/"):
                self._handle_get_template_loop_flow(path, parsed)
                return
            if path == "/api/atomic-workflows":
                self._send_json({"ok": True, "workflows": [item for item in _list_workflows() if item.get("atomic", False)]})
                return
            if path.startswith("/api/workflows/"):
                self._handle_get_workflow(path)
                return
            if path == "/api/window/info":
                self._handle_window_info()
                return
            if path == "/api/window/cursor":
                self._handle_window_cursor()
                return
            if path == "/api/window/screen":
                size = screen_size()
                self._send_json({"ok": True, "screen": _size_dict(size)})
                return
            if path == "/api/workflow-runs":
                self._handle_list_workflow_runs(parsed)
                return
            if path.startswith("/api/workflow-runs/"):
                self._handle_get_workflow_run(path, parsed)
                return
            if path == "/api/scheduler-config":
                self._handle_get_scheduler_config()
                return
            if not path.startswith("/api/"):
                self._send_static_asset(editor_path.parent, path)
                return
            self._send_json({"ok": False, "error": f"Not found: {path}"}, status=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/window/find":
                self._handle_window_find()
                return
            if path == "/api/window/focus":
                self._handle_window_focus()
                return
            if path == "/api/window/topmost":
                self._handle_window_topmost()
                return
            if path == "/api/window/move":
                self._handle_window_move()
                return
            if path == "/api/window/resize":
                self._handle_window_resize()
                return
            if path == "/api/window/remember-size":
                self._handle_window_remember_size()
                return
            if path == "/api/window/fullscreen":
                self._handle_window_fullscreen()
                return
            if path == "/api/window/dock":
                self._handle_window_dock()
                return
            if path == "/api/capture":
                self._handle_capture()
                return
            if path == "/api/template-match":
                self._handle_template_match()
                return
            if path == "/api/template-action":
                self._handle_template_action()
                return
            if path == "/api/template-group-action":
                self._handle_template_group_action()
                return
            if path == "/api/template-group-match":
                self._handle_template_group_match()
                return
            if path == "/api/popup-probe":
                self._handle_popup_probe()
                return
            if path == "/api/template-click":
                self._handle_template_click()
                return
            if path == "/api/template-drag":
                self._handle_template_drag()
                return
            if path == "/api/template-crop":
                self._handle_template_crop()
                return
            if path == "/api/template-groups":
                self._handle_template_group_create()
                return
            if path == "/api/template-group-rename":
                self._handle_template_group_rename()
                return
            if path == "/api/template-group-copy":
                self._handle_template_group_copy()
                return
            if path == "/api/template-group-delete":
                self._handle_template_group_delete()
                return
            if path == "/api/template-unrecognized-clear":
                self._handle_template_unrecognized_clear()
                return
            if path == "/api/template-rename":
                self._handle_template_rename()
                return
            if path == "/api/template-copy":
                self._handle_template_copy()
                return
            if path == "/api/template-metadata":
                self._handle_template_metadata_save()
                return
            if path == "/api/template-delete":
                self._handle_template_delete()
                return
            if path == "/api/template-unrecognized-delete":
                self._handle_template_unrecognized_delete()
                return
            if path == "/api/workflows/validate":
                self._handle_validate_workflow()
                return
            if path == "/api/template-loop-flows":
                self._handle_create_template_loop_flow()
                return
            if path == "/api/template-loop-flows/stop-all":
                self._handle_stop_all_template_loop_flows()
                return
            if path.startswith("/api/template-loop-flows/"):
                self._handle_template_loop_flow_post(path)
                return
            if path.startswith("/api/workflows/"):
                self._handle_save_workflow(path)
                return
            if path == "/api/workflow-runs":
                self._handle_start_workflow_run()
                return
            if path == "/api/workflow-runs/clear-history":
                self._handle_clear_workflow_runs()
                return
            if path.startswith("/api/workflow-runs/") and path.endswith("/stop"):
                self._handle_stop_workflow_run(path)
                return
            if path == "/api/scheduler-config":
                self._handle_save_scheduler_config()
                return
            self._send_json({"ok": False, "error": f"Not found: {path}"}, status=404)

        def do_DELETE(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/template-loop-flows/"):
                self._handle_delete_template_loop_flow(path)
                return
            self._send_json({"ok": False, "error": f"Not found: {path}"}, status=404)

        def _handle_window_info(self) -> None:
            try:
                self._send_json({"ok": True, "window": _window_info_payload(self._current_hwnd())})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_cursor(self) -> None:
            try:
                hwnd = self._current_hwnd()
                screen_point = get_cursor_screen_position()
                client_point = screen_to_client(hwnd, screen_point.x, screen_point.y)
                info = get_window_info(hwnd)
                inside_client = 0 <= client_point.x < info.client_size.width and 0 <= client_point.y < info.client_size.height
                self._send_json(
                    {
                        "ok": True,
                        "cursor": {
                            "screen": _point_dict(screen_point),
                            "client": _point_dict(client_point),
                            "inside_client": inside_client,
                        },
                        "window": _window_info_dict(info),
                    }
                )
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_find(self) -> None:
            try:
                body = self._read_json_body()
                hwnd = _find_target_window(body)
                self._set_current_hwnd(hwnd)
                self._send_json({"ok": True, "window": _window_info_payload(hwnd)})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_focus(self) -> None:
            try:
                info = bring_window_to_foreground(self._current_hwnd())
                self._send_json({"ok": True, "window": _window_info_dict(info)})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_topmost(self) -> None:
            try:
                body = self._read_json_body()
                enabled = bool(body.get("enabled", True))
                hwnd = self._current_hwnd()
                if enabled:
                    info = _prepare_configured_window(hwnd, topmost=True)
                else:
                    info = set_window_topmost(hwnd, enabled=False)
                self._set_current_hwnd(info.hwnd)
                self._send_json({"ok": True, "window": _window_info_dict(info), "topmost": enabled})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_move(self) -> None:
            try:
                body = self._read_json_body()
                info = move_window(self._current_hwnd(), _int_body(body, "left"), _int_body(body, "top"))
                self._send_json({"ok": True, "window": _window_info_dict(info)})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_resize(self) -> None:
            try:
                body = self._read_json_body()
                info = resize_window(self._current_hwnd(), _int_body(body, "width"), _int_body(body, "height"))
                self._send_json({"ok": True, "window": _window_info_dict(info)})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_remember_size(self) -> None:
            try:
                info = get_window_info(self._current_hwnd())
                _save_configured_window_size(info.client_size.width, info.client_size.height)
                self._send_json({"ok": True, "window": _window_info_dict(info), "window_size": {"width": info.client_size.width, "height": info.client_size.height}})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_fullscreen(self) -> None:
            try:
                hwnd = self._current_hwnd()
                with state_lock:
                    fs = state["fullscreen_state"]
                    if fs.get("hwnd") != hwnd:
                        fs.clear()
                        fs["hwnd"] = hwnd
                is_fullscreen = toggle_window_fullscreen(hwnd, fs)
                self._send_json({"ok": True, "fullscreen": is_fullscreen, "window": _window_info_payload(hwnd)})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_get_scheduler_config(self) -> None:
            try:
                config_path = CONFIG_DIR / "scheduler_config.json"
                config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
                self._send_json({"ok": True, "config": config})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_save_scheduler_config(self) -> None:
            try:
                body = self._read_json_body()
                config = body.get("config") if isinstance(body.get("config"), dict) else body
                if not isinstance(config, dict):
                    raise ValueError("config must be a JSON object")
                config_path = CONFIG_DIR / "scheduler_config.json"
                config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_window_dock(self) -> None:
            try:
                body = self._read_json_body()
                rect = _rect_from_body(body)
                info = dock_window_to_rect(
                    self._current_hwnd(),
                    rect,
                    client_area=bool(body.get("client_area", False)),
                    activate=bool(body.get("activate", True)),
                )
                self._send_json({"ok": True, "window": _window_info_dict(info)})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _prepare_current_window_for_capture(self) -> WindowInfo:
            try:
                hwnd = self._current_hwnd()
            except WindowError:
                hwnd = _find_configured_window()
            info = _prepare_configured_window(hwnd, topmost=False)
            self._set_current_hwnd(info.hwnd)
            return info

        def _handle_capture(self) -> None:
            try:
                body = self._read_json_body()
                backend = _capture_backend(body.get("backend", "auto"))
                info = self._prepare_current_window_for_capture()
                result = capture_client_to_file(
                    info.hwnd,
                    bring_to_front=bool(body.get("bring_to_front", False)),
                    backend=backend,
                )
                self._send_json({"ok": True, "capture": _capture_result_dict(result), "window": _window_info_dict(info)})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_match(self) -> None:
            try:
                body = self._read_json_body()
                image_path = _safe_image_path(str(body.get("image_path") or ""), allowed_roots=ALLOWED_IMAGE_ROOTS)
                template_path = _safe_image_path(str(body.get("template_path") or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
                region = _optional_rect(body.get("region"))
                scales = _parse_scales(body.get("scales"))
                debug_path = default_debug_path(image_path)
                result = match_template(
                    image_path,
                    template_path,
                    threshold=float(body.get("threshold") or 0.5),
                    region=region,
                    scales=scales,
                    debug_path=debug_path,
                )
                self._send_json({"ok": True, "match": _match_result_dict(result)})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_action(self) -> None:
            try:
                body = self._read_json_body()
                template_path = _safe_image_path(str(body.get("template_path") or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
                backend = _capture_backend(body.get("backend", "auto"))
                threshold = _optional_template_match_threshold(body.get("threshold")) or _workbench_template_match_threshold(template_path)
                region = _optional_rect(body.get("region"))
                scales = _parse_scales(body.get("scales"))
                info = self._prepare_current_window_for_capture()
                hwnd = info.hwnd
                capture = capture_client_to_file(
                    hwnd,
                    bring_to_front=bool(body.get("bring_to_front", False)),
                    backend=backend,
                )
                debug_path = default_debug_path(capture.path, suffix="template_action")
                match = match_template(
                    capture.path,
                    template_path,
                    threshold=threshold,
                    region=region,
                    scales=scales,
                    debug_path=debug_path,
                )
                probe = _apply_workbench_template_preconditions(
                    TemplateProbeResult(found=match.found, match=match, screenshot_path=capture.path, debug_path=debug_path),
                    scales=scales,
                    debug_suffix="template_action_pre",
                )
                match = probe.match
                action_executed = False
                action_result: dict[str, Any] | None = None
                if probe.found:
                    context = ScriptContext(
                        hwnd=hwnd,
                        script_id="workbench_template_action",
                        screenshot_path=capture.path,
                        dry_run=bool(body.get("dry_run", False)),
                        background_mode=bool(body.get("background_mode", False)),
                    )
                    runtime = ScriptRuntime(context, capture_backend=backend)
                    _execute_template_actions(
                        runtime,
                        probe,
                        scales=scales or (1.0,),
                        save_debug=False,
                    )
                    action_executed = True
                    action_result = {
                        "last_match_click_point": _point_dict(context.last_match_click_point) if context.last_match_click_point else None,
                        "last_match_click_region": _rect_dict(context.last_match_click_region) if context.last_match_click_region else None,
                        "step_index": context.step_index,
                    }
                    self._set_current_hwnd(runtime.hwnd)
                self._send_json(
                    {
                        "ok": True,
                        "capture": _capture_result_dict(capture),
                        "window": _window_info_dict(info),
                        "match": _match_result_dict(match),
                        "action_executed": action_executed,
                        "action": action_result,
                    }
                )
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_group_action(self) -> None:
            try:
                body = self._read_json_body()
                group = str(body.get("group") or "").strip()
                if not group or group == "__all__":
                    raise ValueError("请选择具体模板分组后再执行分组识别。")
                backend = _capture_backend(body.get("backend", "auto"))
                request_threshold = _optional_template_match_threshold(body.get("threshold"))
                region = _optional_rect(body.get("region"))
                scales = _parse_scales(body.get("scales"))
                info = self._prepare_current_window_for_capture()
                hwnd = info.hwnd
                capture = capture_client_to_file(
                    hwnd,
                    bring_to_front=bool(body.get("bring_to_front", False)),
                    backend=backend,
                )
                template_paths = _standalone_group_template_paths(group)

                def probe_template(candidate: PriorityTemplateCandidate) -> TemplateProbeResult:
                    debug_path = default_debug_path(capture.path, suffix=f"group_action_{candidate.index}")
                    threshold = request_threshold or _workbench_template_match_threshold(candidate.path)
                    match = match_template(
                        capture.path,
                        candidate.path,
                        threshold=threshold,
                        region=region,
                        scales=scales,
                        debug_path=debug_path,
                    )
                    probe = TemplateProbeResult(found=match.found, match=match, screenshot_path=capture.path, debug_path=debug_path)
                    return _apply_workbench_template_preconditions(
                        probe,
                        scales=scales,
                        debug_suffix=f"group_action_pre_{candidate.index}",
                    )

                priority_result = scan_priority_templates(
                    template_paths,
                    priority_for=_workbench_template_priority,
                    probe_template=probe_template,
                    ignore_oversized=True,
                )
                matches = [_group_probe_result_dict(probe) for _index, probe in priority_result.found]
                matches.sort(key=_group_match_sort_key, reverse=True)
                selected_probe = select_best_priority_match(
                    priority_result.found,
                    priority_for_match=lambda match: _workbench_template_priority(match.template_path),
                )
                selected = _group_probe_result_dict(selected_probe) if selected_probe else None
                action_executed = False
                action_result: dict[str, Any] | None = None
                if selected_probe:
                    probe = selected_probe
                    context = ScriptContext(
                        hwnd=hwnd,
                        script_id="workbench_template_group_action",
                        screenshot_path=capture.path,
                        dry_run=bool(body.get("dry_run", False)),
                        background_mode=bool(body.get("background_mode", False)),
                    )
                    runtime = ScriptRuntime(context, capture_backend=backend)
                    _execute_template_actions(
                        runtime,
                        probe,
                        scales=scales or (1.0,),
                        save_debug=False,
                    )
                    action_executed = True
                    action_result = {
                        "last_match_click_point": _point_dict(context.last_match_click_point) if context.last_match_click_point else None,
                        "last_match_click_region": _rect_dict(context.last_match_click_region) if context.last_match_click_region else None,
                        "step_index": context.step_index,
                    }
                    self._set_current_hwnd(runtime.hwnd)
                self._send_json(
                    {
                        "ok": True,
                        "group": group,
                        "threshold": request_threshold,
                        "capture": _capture_result_dict(capture),
                        "window": _window_info_dict(info),
                        "matches": matches,
                        "selected_match": selected,
                        "action_executed": action_executed,
                        "action": action_result,
                    }
                )
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_group_match(self) -> None:
            try:
                body = self._read_json_body()
                group = str(body.get("group") or "").strip()
                if not group or group == "__all__":
                    raise ValueError("请选择具体模板分组后再执行分组识别。")
                backend = _capture_backend(body.get("backend", "auto"))
                threshold = float(body.get("threshold") or 0.5)
                region = _optional_rect(body.get("region"))
                scales = _parse_scales(body.get("scales"))
                info = self._prepare_current_window_for_capture()
                hwnd = info.hwnd
                capture = capture_client_to_file(
                    hwnd,
                    bring_to_front=bool(body.get("bring_to_front", False)),
                    backend=backend,
                )
                template_paths = _standalone_group_template_paths(group)

                def probe_template(candidate: PriorityTemplateCandidate) -> TemplateProbeResult:
                    debug_path = default_debug_path(capture.path, suffix=f"group_match_{candidate.index}")
                    match = match_template(
                        capture.path,
                        candidate.path,
                        threshold=threshold,
                        region=region,
                        scales=scales,
                        debug_path=debug_path,
                    )
                    probe = TemplateProbeResult(found=match.found, match=match, screenshot_path=capture.path, debug_path=debug_path)
                    return _apply_workbench_template_preconditions(
                        probe,
                        scales=scales,
                        debug_suffix=f"group_match_pre_{candidate.index}",
                    )

                priority_result = scan_priority_templates(
                    template_paths,
                    priority_for=_workbench_template_priority,
                    probe_template=probe_template,
                    ignore_oversized=True,
                )
                matches = [_group_probe_result_dict(probe) for _index, probe in priority_result.found]
                matches.sort(key=_group_match_sort_key, reverse=True)
                best_result = _group_probe_result_dict(priority_result.best_probe) if priority_result.best_probe else None
                self._send_json(
                    {
                        "ok": True,
                        "group": group,
                        "threshold": threshold,
                        "capture": _capture_result_dict(capture),
                        "window": _window_info_dict(info),
                        "checked": priority_result.checked,
                        "matched": sum(1 for item in matches if item["found"]),
                        "matches": matches,
                        "best_match": matches[0] if matches else best_result,
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_popup_probe(self) -> None:
            try:
                body = self._read_json_body()
                image_path = _safe_image_path(str(body.get("image_path") or ""), allowed_roots=ALLOWED_IMAGE_ROOTS)
                region = _optional_rect(body.get("region"))
                scales = _parse_scales(body.get("scales"))
                send_esc_on_match = bool(body.get("send_esc_on_match", False))
                result = _probe_popup_rules(image_path, region=region, scales=scales)
                if result.get("found") and send_esc_on_match:
                    input_result = press_key(self._current_hwnd(), "esc")
                    result["esc_sent"] = True
                    result["input"] = _input_result_dict(input_result)
                else:
                    result["esc_sent"] = False
                    result["input"] = None
                self._send_json({"ok": True, "popup": result})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_click(self) -> None:
            try:
                body = self._read_json_body()
                x = _int_body(body, "x")
                y = _int_body(body, "y")
                result = click_client(
                    self._current_hwnd(),
                    x,
                    y,
                    button=str(body.get("button") or "left"),
                    duration_ms=int(body.get("duration_ms") or 50),
                    clicks=int(body.get("clicks") or 1),
                    interval_ms=int(body.get("interval_ms") or 0),
                )
                self._send_json({"ok": True, "click": _input_result_dict(result)})
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_drag(self) -> None:
            try:
                body = self._read_json_body()
                start_x = _int_body(body, "start_x")
                start_y = _int_body(body, "start_y")
                direction = str(body.get("direction") or "left")
                distance = int(body.get("distance") or 0)
                duration_ms = int(body.get("duration_ms") or 300)
                steps = int(body.get("steps") or 12)
                result = drag_client(
                    self._current_hwnd(),
                    start_x,
                    start_y,
                    direction=direction,
                    distance=distance,
                    duration_ms=duration_ms,
                    steps=steps,
                )
                self._send_json({
                    "ok": True,
                    "drag": {
                        "start_x": start_x,
                        "start_y": start_y,
                        "direction": direction,
                        "distance": distance,
                        "duration_ms": duration_ms,
                        "steps": steps,
                        "input": _input_result_dict(result),
                    },
                })
            except Exception as exc:
                self._clear_current_if_invalid(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_crop(self) -> None:
            try:
                body = self._read_json_body()
                image_path = _safe_image_path(str(body.get("image_path") or ""), allowed_roots=ALLOWED_IMAGE_ROOTS)
                region = _rect_from_body(body.get("region") or body)
                filename = str(body.get("filename") or f"template_{datetime.now().strftime('%Y%m%d-%H%M%S')}.png")
                group = str(body.get("group") or "").strip()
                result = crop_template_from_image(image_path, region, filename, group=group or None, replace=bool(body.get("replace", False)))
                metadata_path = result.info.path.with_suffix(".json")
                metadata_path.write_text(json.dumps(_template_metadata(body, image_path, region), ensure_ascii=False, indent=2), encoding="utf-8")
                self._send_json({"ok": True, "template": _template_info_dict(inspect_template(result.info.path)), "metadata": str(metadata_path), "backup": str(result.backup_path) if result.backup_path else None})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_group_create(self) -> None:
            try:
                body = self._read_json_body()
                name = str(body.get("name") or "").strip()
                group = create_template_group(name)
                self._send_json({"ok": True, "group": _template_group_dict(group), "groups": _list_template_group_payloads()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_group_rename(self) -> None:
            try:
                body = self._read_json_body()
                old_name = str(body.get("old_name") or body.get("name") or "").strip()
                new_name = str(body.get("new_name") or "").strip()
                result = rename_template_group(old_name, new_name)
                updated_scripts = sync_loop_dirs_rename(old_name, new_name)
                self._send_json(
                    {
                        "ok": True,
                        "old_path": str(result.old_path),
                        "new_path": str(result.new_path),
                        "updated_templates": [_template_info_dict(inspect_template(path)) for path in result.updated_templates],
                        "updated_scripts": updated_scripts,
                        "templates": _list_template_payloads(),
                        "groups": _list_template_group_payloads(),
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_group_copy(self) -> None:
            try:
                body = self._read_json_body()
                source_name = str(body.get("source_name") or body.get("name") or "").strip()
                target_name = str(body.get("target_name") or body.get("new_name") or "").strip()
                result = copy_template_group(source_name, target_name)
                self._send_json(
                    {
                        "ok": True,
                        "source_path": str(result.source_path),
                        "target_path": str(result.target_path),
                        "copied_templates": [_template_info_dict(inspect_template(path)) for path in result.copied_templates],
                        "templates": _list_template_payloads(),
                        "groups": _list_template_group_payloads(),
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_group_delete(self) -> None:
            try:
                body = self._read_json_body()
                name = str(body.get("name") or "").strip()
                result = delete_template_group(name)
                self._send_json({"ok": True, "path": str(result.path), "groups": _list_template_group_payloads()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_unrecognized_clear(self) -> None:
            try:
                body = self._read_json_body()
                if _bool_from_body(body.get("all"), False):
                    result = _clear_all_unrecognized_template_groups()
                else:
                    name = str(body.get("name") or "").strip()
                    result = _clear_unrecognized_template_group(name)
                self._send_json({
                    "ok": True,
                    **result,
                    "templates": _list_template_payloads(),
                    "groups": _list_template_group_payloads(),
                })
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_rename(self) -> None:
            try:
                body = self._read_json_body()
                path = _safe_image_path(str(body.get("path") or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
                filename = str(body.get("filename") or "").strip()
                group = str(body.get("group") or "").strip()
                result = rename_template(path, filename, group=group or None, replace=bool(body.get("replace", False)))
                self._send_json(
                    {
                        "ok": True,
                        "old_path": str(result.old_path),
                        "template": _template_info_dict(inspect_template(result.new_path)),
                        "metadata": str(result.metadata_new_path) if result.metadata_new_path else None,
                        "metadata_renamed": result.metadata_renamed,
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_copy(self) -> None:
            try:
                body = self._read_json_body()
                path = _safe_image_path(str(body.get("path") or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
                filename = str(body.get("filename") or path.name).strip()
                group = str(body.get("target_group") or body.get("group") or "").strip()
                result = copy_template(path, filename, group=group or None, replace=bool(body.get("replace", False)))
                self._send_json(
                    {
                        "ok": True,
                        "source_path": str(result.source_path),
                        "template": _template_info_dict(inspect_template(result.new_path)),
                        "metadata": str(result.metadata_new_path) if result.metadata_new_path else None,
                        "metadata_copied": result.metadata_copied,
                        "templates": _list_template_payloads(),
                        "groups": _list_template_group_payloads(),
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_metadata_save(self) -> None:
            try:
                body = self._read_json_body()
                path = _safe_image_path(str(body.get("path") or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
                metadata = body.get("metadata")
                if not isinstance(metadata, dict):
                    raise ValueError("metadata must be an object.")
                result = save_template_metadata(path, _normalize_template_metadata(metadata))
                self._send_json(
                    {
                        "ok": True,
                        "template": _template_info_dict(result.info),
                        "metadata": str(result.metadata_path),
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_delete(self) -> None:
            try:
                body = self._read_json_body()
                path = _safe_image_path(str(body.get("path") or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
                metadata_path = path.with_suffix(".json")
                result = delete_template(path)
                metadata_backup = None
                if metadata_path.exists():
                    metadata_backup = Path(str(result.backup_path)).with_suffix(".json")
                    shutil.move(str(metadata_path), str(metadata_backup))
                self._send_json({"ok": True, "path": str(result.path), "backup": str(result.backup_path), "metadata_backup": str(metadata_backup) if metadata_backup else None})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_unrecognized_delete(self) -> None:
            try:
                body = self._read_json_body()
                path = _safe_image_path(str(body.get("path") or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
                result = _delete_unrecognized_template_source(path)
                self._send_json({
                    "ok": True,
                    **result,
                    "templates": _list_template_payloads(),
                    "groups": _list_template_group_payloads(),
                })
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_get_workflow(self, path: str) -> None:
            try:
                filename = unquote(path.removeprefix("/api/workflows/"))
                workflow_path = _safe_workflow_path(filename)
                workflow = load_workflow(workflow_path)
                self._send_json({"ok": True, "filename": workflow_path.name, "yaml": workflow_path.read_text(encoding="utf-8"), "model": _workflow_to_editor_model(workflow)})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_validate_workflow(self) -> None:
            try:
                body = self._read_json_body()
                yaml_text = str(body.get("yaml") or "")
                workflow = parse_workflow(parse_yaml_text("<html-workflow>", yaml_text), source="<html-workflow>")
                self._send_json({"ok": True, "workflow": {"id": workflow.id, "name": workflow.name, "nodes": len(workflow.nodes)}})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_save_workflow(self, path: str) -> None:
            try:
                filename = unquote(path.removeprefix("/api/workflows/"))
                workflow_path = _safe_workflow_path(filename)
                body = self._read_json_body()
                yaml_text = str(body.get("yaml") or "")
                parse_workflow(parse_yaml_text(workflow_path, yaml_text), source=workflow_path)
                backup = None
                if workflow_path.exists():
                    backup_dir = BACKUP_DIR / "workflows"
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup = backup_dir / f"{workflow_path.name}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
                    shutil.copy2(workflow_path, backup)
                workflow_path.parent.mkdir(parents=True, exist_ok=True)
                workflow_path.write_text(yaml_text, encoding="utf-8")
                self._send_json({"ok": True, "filename": workflow_path.name, "backup": str(backup) if backup else None})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_get_template_loop_flow(self, path: str, parsed) -> None:
            try:
                suffix = path.removeprefix("/api/template-loop-flows/")
                if suffix.endswith("/failures"):
                    filename = unquote(suffix.removesuffix("/failures"))
                    limit = int(_query_value(parsed, "limit") or 20)
                    failure_payload = loop_manager.failure_events(filename, limit=limit)
                    latest_unrecognized = _template_info_from_unrecognized_path(
                        failure_payload.get("latest_unrecognized_path")
                    )
                    self._send_json({
                        "ok": True,
                        "filename": failure_payload["filename"],
                        "running": failure_payload["running"],
                        "failures": _template_loop_failure_events_payload(failure_payload.get("failures") or []),
                        "latest_unrecognized_template": latest_unrecognized,
                        "unrecognized_template": latest_unrecognized,
                    })
                    return
                if suffix.endswith("/logs"):
                    filename = unquote(suffix.removesuffix("/logs"))
                    max_chars = int(_query_value(parsed, "max_chars") or 20000)
                    log_text = loop_manager.read_log(filename, max_chars=max_chars)
                    self._send_json({
                        "ok": True,
                        "filename": filename,
                        "log": log_text,
                        "unrecognized_template": _latest_unrecognized_template_from_log(log_text),
                    })
                    return
                filename = unquote(suffix)
                self._send_json({"ok": True, "flow": loop_manager.get_flow(filename)})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_create_template_loop_flow(self) -> None:
            try:
                body = self._read_json_body()
                filename = _default_template_loop_filename(str(body.get("filename") or ""))
                if not filename:
                    raise ValueError("Template loop script filename is required.")
                flow = loop_manager.save_flow(
                    filename,
                    start_flows=_strings_from_body(body.get("start_flows", body.get("start"))),
                    loop_dirs=_strings_from_body(body.get("loop_dirs", body.get("loopDir"))),
                    end_template=_optional_text_from_body(body.get("end_template", body.get("end"))),
                    completion_count=_completion_count_from_body(body),
                )
                self._send_json({"ok": True, "flow": flow, "flows": loop_manager.list_flows()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_delete_template_loop_flow(self, path: str) -> None:
            try:
                suffix = path.removeprefix("/api/template-loop-flows/")
                if not suffix or suffix.endswith("/logs") or suffix.endswith("/start") or suffix.endswith("/stop"):
                    raise ValueError(f"Invalid template loop flow delete path: {path}")
                filename = unquote(suffix)
                loop_manager.delete_flow(filename)
                self._send_json({"ok": True, "filename": filename, "flows": loop_manager.list_flows()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_template_loop_flow_post(self, path: str) -> None:
            try:
                suffix = path.removeprefix("/api/template-loop-flows/")
                if suffix.endswith("/start"):
                    filename = unquote(suffix.removesuffix("/start"))
                    body = self._read_json_body()
                    background_mode = bool(body["background_mode"]) if "background_mode" in body else True
                    no_prepare = bool(body["no_prepare"]) if "no_prepare" in body else background_mode
                    try:
                        hwnd = self._current_hwnd()
                    except WindowError:
                        hwnd = _find_configured_window()
                    if not no_prepare:
                        info = _prepare_configured_window(hwnd, topmost=not background_mode)
                        self._set_current_hwnd(info.hwnd)
                        hwnd = info.hwnd
                    flow = loop_manager.start_flow(
                        filename,
                        hwnd=hwnd,
                        dry_run=bool(body.get("dry_run", False)),
                        background_mode=background_mode,
                        run_start_flows_first=bool(body.get("run_start_flows_first", False)),
                    )
                    self._send_json({"ok": True, "flow": flow, "flows": loop_manager.list_flows()})
                    return
                if suffix.endswith("/stop"):
                    filename = unquote(suffix.removesuffix("/stop"))
                    flow = loop_manager.stop_flow(filename)
                    self._send_json({"ok": True, "flow": flow, "flows": loop_manager.list_flows()})
                    return
                if suffix.endswith("/pause"):
                    filename = unquote(suffix.removesuffix("/pause"))
                    flow = loop_manager.pause_flow(filename)
                    self._send_json({"ok": True, "flow": flow, "flows": loop_manager.list_flows()})
                    return
                if suffix.endswith("/resume"):
                    filename = unquote(suffix.removesuffix("/resume"))
                    flow = loop_manager.resume_flow(filename)
                    self._send_json({"ok": True, "flow": flow, "flows": loop_manager.list_flows()})
                    return

                filename = _default_template_loop_filename(unquote(suffix))
                safe_template_loop_script_path(filename)
                body = self._read_json_body()
                flow = loop_manager.save_flow(
                    filename,
                    start_flows=_strings_from_body(body.get("start_flows", body.get("start"))),
                    loop_dirs=_strings_from_body(body.get("loop_dirs", body.get("loopDir"))),
                    end_template=_optional_text_from_body(body.get("end_template", body.get("end"))),
                    completion_count=_completion_count_from_body(body),
                )
                self._send_json({"ok": True, "flow": flow, "flows": loop_manager.list_flows()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_stop_all_template_loop_flows(self) -> None:
            try:
                stopped = loop_manager.stop_all_flows()
                self._send_json({"ok": True, "stopped": stopped, "flows": loop_manager.list_flows()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_start_workflow_run(self) -> None:
            try:
                body = self._read_json_body()
                filename = str(body.get("filename") or "").strip()
                if not filename:
                    raise ValueError("Workflow filename is required.")
                workflow_path = _safe_workflow_path(filename)
                workflow = load_workflow(workflow_path)
                if body.get("title") or body.get("process_name"):
                    hwnd = _find_target_window(body)
                else:
                    try:
                        hwnd = self._current_hwnd()
                    except WindowError:
                        hwnd = _find_configured_window()
                info = _prepare_configured_window(hwnd, topmost=True)
                self._set_current_hwnd(info.hwnd)
                context = create_workflow_context(workflow, info.hwnd, dry_run=bool(body.get("dry_run", False)))
                stop_event = threading.Event()
                run_state = {"run_id": context.run_id, "status": "starting", "workflow_filename": workflow_path.name, "workflow_id": workflow.id, "workflow_name": workflow.name, "step_count": 0, "message": "starting", "final_node": None, "stop_event": stop_event, "thread": None}

                def on_recorder_entry(entry: dict[str, Any]) -> None:
                    step = int(entry.get("step", 0) or 0)
                    status = str(entry.get("status") or "")
                    with state_lock:
                        current = state["runs"].get(context.run_id)
                        if current is None:
                            return
                        current["status"] = "running"
                        completed_steps = step if status == "started" else step + 1
                        current["step_count"] = max(int(current.get("step_count", 0) or 0), completed_steps)
                        current["final_node"] = str(entry.get("node_id") or current.get("final_node") or "")
                        current["message"] = str(entry.get("message") or current.get("message") or "")

                def target() -> None:
                    run_state["status"] = "running"
                    try:
                        recorder = WorkflowRecorder(context, on_entry=on_recorder_entry)
                        result = run_workflow(workflow, context, recorder=recorder, should_stop=stop_event.is_set)
                        run_state.update({"status": result.status, "step_count": len(result.steps), "message": result.message, "final_node": result.final_node, "success": result.success})
                    except Exception as exc:
                        run_state.update({"status": "error", "message": str(exc), "success": False})

                thread = threading.Thread(target=target, daemon=True)
                run_state["thread"] = thread
                with state_lock:
                    state["runs"][context.run_id] = run_state
                thread.start()
                self._send_json({"ok": True, "run": _run_state_dict(run_state)})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_list_workflow_runs(self, parsed) -> None:
            limit = int(_query_value(parsed, "limit") or 50)
            with state_lock:
                runs = list(state["runs"].values())
            self._send_json({"ok": True, "runs": [_run_state_dict(run) for run in runs[-limit:]][::-1]})

        def _handle_get_workflow_run(self, path: str, parsed) -> None:
            try:
                suffix = path.removeprefix("/api/workflow-runs/")
                if suffix.endswith("/logs"):
                    run_id = unquote(suffix.removesuffix("/logs"))
                    limit = int(_query_value(parsed, "limit") or 300)
                    self._send_json({"ok": True, "entries": _read_run_logs(run_id, limit=limit)})
                    return
                run_id = unquote(suffix)
                run = self._run_state(run_id)
                self._send_json({"ok": True, "run": _run_state_dict(run), "summary": _read_run_summary(run_id)})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_stop_workflow_run(self, path: str) -> None:
            try:
                run_id = unquote(path.removeprefix("/api/workflow-runs/").removesuffix("/stop"))
                run = self._run_state(run_id)
                run["stop_event"].set()
                run["status"] = "stopping"
                self._send_json({"ok": True, "run": _run_state_dict(run)})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_clear_workflow_runs(self) -> None:
            with state_lock:
                deleted = [run_id for run_id, run in state["runs"].items() if run.get("status") not in {"running", "starting", "stopping"}]
                for run_id in deleted:
                    del state["runs"][run_id]
            self._send_json({"ok": True, "deleted": deleted})

        def _current_hwnd(self) -> int:
            with state_lock:
                hwnd = state["hwnd"]
            if not hwnd:
                raise WindowError("No current window. Call /api/window/find first.")
            if not is_window_alive(hwnd):
                with state_lock:
                    state["hwnd"] = None
                raise WindowError(f"Current window is closed or invalid: {hwnd}")
            return hwnd

        def _set_current_hwnd(self, hwnd: int) -> None:
            with state_lock:
                state["hwnd"] = hwnd

        def _run_state(self, run_id: str) -> dict[str, Any]:
            with state_lock:
                run = state["runs"].get(run_id)
            if run is None:
                raise ValueError(f"Workflow run not found: {run_id}")
            return run

        def _clear_current_if_invalid(self, exc: Exception) -> None:
            if "Invalid or closed window handle" in str(exc) or "closed or invalid" in str(exc):
                with state_lock:
                    state["hwnd"] = None

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            data = self.rfile.read(length)
            if not data:
                return {}
            return json.loads(data.decode("utf-8"))

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, path: Path) -> None:
            if not path.exists():
                self._send_json({"ok": False, "error": f"HTML file not found: {path}"}, status=404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_static_asset(self, root: Path, request_path: str) -> None:
            try:
                relative = unquote(request_path).lstrip("/")
                path = (root / relative).resolve()
                if not path.is_relative_to(root.resolve()) or not path.exists() or not path.is_file():
                    self._send_json({"ok": False, "error": f"Static asset not found: {request_path}"}, status=404)
                    return
                data = path.read_bytes()
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _send_image(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self._send_json({"ok": False, "error": f"Image not found: {path}"}, status=404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)

    _prepare_startup_window(state, state_lock)
    return WindowWorkbenchRequestHandler, state


def _capabilities() -> dict[str, bool]:
    return {"window": True, "workflow": True, "capture": True, "template": True}


def _settings_game() -> dict[str, Any]:
    settings = load_settings()
    game = settings.get("game", {}) if isinstance(settings, dict) else {}
    return game if isinstance(game, dict) else {}


def _settings_payload() -> dict[str, Any]:
    game = _settings_game()
    window_size = game.get("window_size", {})
    window_rect = game.get("window_rect", {})
    return {
        "game": {
            "window_title": str(game.get("window_title") or ""),
            "process_name": str(game.get("process_name") or ""),
            "window_size": window_size if isinstance(window_size, dict) else {},
            "window_rect": window_rect if isinstance(window_rect, dict) else {},
        }
    }


def _configured_window_size_payload() -> dict[str, int] | None:
    window_size = _settings_payload()["game"].get("window_size")
    if not isinstance(window_size, dict):
        return None
    width = int(window_size.get("width", 0) or 0)
    height = int(window_size.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}


def _save_configured_window_size(width: int, height: int) -> None:
    settings_path = CONFIG_DIR / "settings.yaml"
    settings = load_settings(settings_path)
    game = settings.setdefault("game", {})
    if not isinstance(game, dict):
        game = {}
        settings["game"] = game
    game["window_size"] = {"width": int(width), "height": int(height)}
    _write_yaml(settings_path, settings)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required to save settings.yaml") from exc
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _default_template_loop_filename(filename: str) -> str:
    name = str(filename or "").strip()
    if not name:
        return ""
    if Path(name).suffix.lower() in {".yaml", ".yml"}:
        return name
    return f"{name}.yaml"


def _find_configured_window() -> int:
    game = _settings_game()
    return _find_window_with_fallback(
        title=str(game.get("window_title") or "").strip(),
        process_name=str(game.get("process_name") or "").strip(),
        visible_only=True,
        title_first=str(game.get("window_mode") or "").strip().lower() == "android_emulator",
    )


def _find_window_with_fallback(
    *,
    title: str,
    process_name: str,
    visible_only: bool = True,
    title_first: bool = False,
    exact: bool = False,
) -> int:
    attempts: list[str] = []
    finders = []
    if title_first:
        finders.extend((("title", title), ("process", process_name)))
    else:
        finders.extend((("process", process_name), ("title", title)))
    for kind, value in finders:
        if not value:
            continue
        try:
            if kind == "title":
                return find_window_by_title(value, exact=exact, visible_only=visible_only)
            return find_window_by_process_name(value, visible_only=visible_only)
        except WindowError as exc:
            attempts.append(f"{kind}={value!r}: {exc}")
    if attempts:
        raise WindowError("No configured window found; " + " | ".join(attempts))
    raise WindowError("Window title or process name is required.")


def _register_window_hotkeys(state: dict) -> None:
    from game_bot.core.hotkeys import VK_F12, register_global_hotkey

    def _on_f12() -> None:
        hwnd = state.get("hwnd")
        if not hwnd or not is_window_alive(hwnd):
            try:
                hwnd = _find_configured_window()
            except Exception:
                return
        if not hwnd or not is_window_alive(hwnd):
            return
        fs = state["fullscreen_state"]
        if fs.get("hwnd") != hwnd:
            fs.clear()
            fs["hwnd"] = hwnd
        try:
            toggle_window_fullscreen(hwnd, fs)
        except Exception as exc:
            print(f"[hotkey] fullscreen toggle error: {exc}")

    try:
        register_global_hotkey(VK_F12, _on_f12)
        print("[hotkey] F12 registered: toggle game window fullscreen")
    except Exception as exc:
        print(f"[hotkey] Failed to register F12 hotkey: {exc}")


def _prepare_configured_window(hwnd: int, *, topmost: bool = True, apply_size: bool = True) -> WindowInfo:
    game = _settings_game()
    window_size = game.get("window_size", {})
    if apply_size and isinstance(window_size, dict):
        width = int(window_size.get("width", 0) or 0)
        height = int(window_size.get("height", 0) or 0)
        if width > 0 and height > 0:
            ensure_window_client_size(hwnd, width, height)

    rect_config = game.get("window_rect", {})
    rect = None
    if isinstance(rect_config, dict):
        current = get_window_info(hwnd).window_rect
        width = int(rect_config.get("width") or current.width)
        height = int(rect_config.get("height") or current.height)
        top = int(rect_config.get("top", current.top))
        anchor = str(rect_config.get("anchor", "top_left")).strip().lower()
        if anchor == "top_right":
            right_margin = int(rect_config.get("right", 0) or 0)
            left = screen_size().width - right_margin - width
        else:
            left = int(rect_config.get("left", current.left))
        if width > 0 and height > 0:
            rect = Rect(left, top, left + width, top + height)
    return prepare_window_for_automation(hwnd, rect=rect, topmost=topmost)


def _prepare_startup_window(state: dict[str, Any], state_lock: threading.Lock) -> None:
    try:
        hwnd = _find_configured_window()
        info = _prepare_configured_window(hwnd, topmost=True)
        with state_lock:
            state["hwnd"] = info.hwnd
            state["startup_window"] = _window_info_dict(info)
            state["startup_error"] = None
    except Exception as exc:
        with state_lock:
            state["hwnd"] = None
            state["startup_window"] = None
            state["startup_error"] = str(exc)


def _find_target_window(body: dict[str, Any]) -> int:
    settings = _settings_payload()["game"]
    process_name = str(body.get("process_name") or settings.get("process_name") or "").strip()
    title = str(body.get("title") or settings.get("window_title") or "").strip()
    visible_only = bool(body.get("visible_only", True))
    exact = bool(body.get("exact", False))
    title_first = str(settings.get("window_mode") or "").strip().lower() == "android_emulator"
    if body.get("process_name") or body.get("title"):
        title_first = bool(body.get("title"))
    return _find_window_with_fallback(
        title=title,
        process_name=process_name,
        visible_only=visible_only,
        title_first=title_first,
        exact=exact,
    )


def _window_info_payload(hwnd: int) -> dict[str, Any]:
    return _window_info_dict(get_window_info(hwnd))


def _window_info_dict(info: WindowInfo) -> dict[str, Any]:
    return {
        "hwnd": info.hwnd,
        "title": info.title,
        "window_rect": _rect_dict(info.window_rect),
        "client_size": _size_dict(info.client_size),
        "client_origin_screen": _point_dict(info.client_origin_screen),
        "client_rect_screen": _rect_dict(info.client_rect_screen),
    }


def _capture_result_dict(result) -> dict[str, Any]:
    return {
        "path": str(result.path),
        "hwnd": result.hwnd,
        "title": result.title,
        "rect": _rect_dict(result.rect),
        "size": _size_dict(result.size),
    }


def _match_result_dict(result) -> dict[str, Any]:
    return {
        "found": result.found,
        "score": result.score,
        "box": _rect_dict(result.box),
        "center": _point_dict(result.center),
        "template_path": str(result.template_path),
        "image_path": str(result.image_path),
        "debug_path": str(result.debug_path) if result.debug_path else None,
        "scale": result.scale,
    }


def _input_result_dict(result) -> dict[str, Any]:
    return {
        "success": result.success,
        "hwnd": result.hwnd,
        "client_point": _point_dict(result.client_point) if result.client_point else None,
        "screen_point": _point_dict(result.screen_point) if result.screen_point else None,
        "message": result.message,
        "backend": result.backend,
    }


def _template_info_dict(info) -> dict[str, Any]:
    return {
        "path": str(info.path),
        "relative_path": info.relative_path,
        "group": info.group,
        "width": info.width,
        "height": info.height,
        "stddev": info.stddev,
        "valid": info.valid,
        "message": info.message,
        "metadata": _template_metadata_payload(info.path),
    }


def _group_match_result_dict(result, info) -> dict[str, Any]:
    template = _template_info_dict(info)
    metadata = template.get("metadata") if isinstance(template.get("metadata"), dict) else {}
    return {
        **_match_result_dict(result),
        "template": template,
        "priority": _normalize_priority(metadata.get("priority")),
    }


def _group_match_sort_key(match: dict[str, Any]) -> tuple[int, float, float, str]:
    return (
        1 if bool(match.get("found")) else 0,
        float(match.get("priority") or 0.0),
        float(match.get("score") or 0.0),
        str(match.get("template", {}).get("relative_path") or match.get("template_path") or ""),
    )


def _group_template_paths(group: str) -> tuple[Path, ...]:
    return tuple(
        _safe_image_path(str(template_value or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
        for template_value in expand_template_references([f"group:{group}"])
    )


def _standalone_group_template_paths(group: str) -> tuple[Path, ...]:
    return tuple(
        path
        for path in _group_template_paths(group)
        if not _workbench_template_is_non_standalone(path) and not _workbench_template_is_fallback_template(path)
    )


def _workbench_template_priority(template_path: Path) -> float:
    metadata = _template_metadata_payload(template_path) or {}
    return _normalize_priority(metadata.get("priority"))


def _workbench_template_match_threshold(template_path: Path) -> float:
    metadata = _template_metadata_payload(template_path) or {}
    return _optional_template_match_threshold(metadata.get("threshold")) or DEFAULT_TEMPLATE_MATCH_THRESHOLD


def _optional_template_match_threshold(value: Any) -> float | None:
    if value in (None, ""):
        return None
    threshold = float(value)
    if not isfinite(threshold) or threshold <= 0 or threshold > 1:
        raise ValueError("template threshold must be in (0, 1].")
    return threshold


def _workbench_template_is_non_standalone(template_path: Path) -> bool:
    metadata = _template_metadata_payload(template_path) or {}
    return _metadata_bool(metadata.get("is_non_standalone") or metadata.get("non_standalone"))


def _workbench_template_is_fallback_template(template_path: Path) -> bool:
    metadata = _template_metadata_payload(template_path) or {}
    return _metadata_bool(metadata.get("is_fallback_template") or metadata.get("fallback_template"))


def _workbench_template_postcondition_not_templates(template_path: Path) -> tuple[Path, ...]:
    metadata = _template_metadata_payload(template_path) or {}
    raw_value = (
        metadata.get("postcondition_not_templates")
        or metadata.get("postcondition_not_template")
        or metadata.get("excludes_templates")
        or metadata.get("excludes_template")
    )
    return _workbench_template_references(raw_value)


def _workbench_template_references(raw_value: Any) -> tuple[Path, ...]:
    if raw_value in (None, "", []):
        return ()
    values = raw_value if isinstance(raw_value, list) else [raw_value]
    templates: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if value in (None, ""):
            continue
        resolved = _safe_template_reference(str(value))
        if resolved in seen:
            continue
        seen.add(resolved)
        templates.append(resolved)
    return tuple(templates)


def _group_probe_result_dict(probe: TemplateProbeResult) -> dict[str, Any]:
    return _group_match_result_dict(probe.match, inspect_template(probe.match.template_path))


def _apply_workbench_template_preconditions(
    probe: TemplateProbeResult,
    *,
    scales: tuple[float, ...],
    debug_suffix: str,
) -> TemplateProbeResult:
    if not probe.found:
        return probe
    required_templates = _template_precondition_templates(probe.match.template_path)
    excluded_templates = _workbench_template_postcondition_not_templates(probe.match.template_path)
    if not required_templates and not excluded_templates:
        return probe
    for index, template_path in enumerate(required_templates, start=1):
        debug_path = default_debug_path(probe.screenshot_path, suffix=f"{debug_suffix}_required_{index}")
        pre_match = match_template(
            probe.screenshot_path,
            template_path,
            threshold=_workbench_template_match_threshold(template_path),
            scales=scales,
            debug_path=debug_path,
        )
        if not pre_match.found:
            return _inactive_probe(probe)
    for index, template_path in enumerate(excluded_templates, start=1):
        debug_path = default_debug_path(probe.screenshot_path, suffix=f"{debug_suffix}_excluded_{index}")
        excluded_match = match_template(
            probe.screenshot_path,
            template_path,
            threshold=_workbench_template_match_threshold(template_path),
            scales=scales,
            debug_path=debug_path,
        )
        if excluded_match.found:
            return _inactive_probe(probe)
    return probe


def _inactive_probe(probe: TemplateProbeResult) -> TemplateProbeResult:
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


def _template_group_dict(info) -> dict[str, Any]:
    return {
        "path": str(info.path),
        "relative_path": info.relative_path,
        "name": info.name,
        "template_count": info.template_count,
    }


def _template_metadata_payload(path: Path) -> dict[str, Any] | None:
    metadata_path = path.with_suffix(".json")
    if not metadata_path.is_file():
        _TEMPLATE_METADATA_CACHE.pop(metadata_path, None)
        return None
    try:
        stat = metadata_path.stat()
    except OSError:
        _TEMPLATE_METADATA_CACHE.pop(metadata_path, None)
        return None
    cached = _TEMPLATE_METADATA_CACHE.get(metadata_path)
    if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return dict(cached[2]) if cached[2] is not None else None
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _TEMPLATE_METADATA_CACHE[metadata_path] = (stat.st_mtime_ns, stat.st_size, None)
        return None
    payload = data if isinstance(data, dict) else None
    _TEMPLATE_METADATA_CACHE[metadata_path] = (stat.st_mtime_ns, stat.st_size, payload)
    return dict(payload) if payload is not None else None


def _rect_dict(rect: Rect) -> dict[str, int]:
    return {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom, "width": rect.width, "height": rect.height}


def _size_dict(size: Size) -> dict[str, int]:
    return {"width": size.width, "height": size.height}


def _point_dict(point: Point) -> dict[str, int]:
    return {"x": point.x, "y": point.y}


def _rect_from_body(body: dict[str, Any]) -> Rect:
    if isinstance(body.get("rect"), dict):
        body = body["rect"]
    left = _int_body(body, "left")
    top = _int_body(body, "top")
    if "right" in body and "bottom" in body:
        return Rect(left, top, _int_body(body, "right"), _int_body(body, "bottom"))
    width = _int_body(body, "width")
    height = _int_body(body, "height")
    return Rect(left, top, left + width, top + height)


def _optional_rect(value: Any) -> Rect | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        return _rect_from_body(value)
    if isinstance(value, list) and len(value) == 4:
        left, top, right, bottom = [int(round(float(item))) for item in value]
        return Rect(left, top, right, bottom)
    raise ValueError(f"Invalid rect value: {value}")


def _int_body(body: dict[str, Any], key: str) -> int:
    if key not in body or body[key] in (None, ""):
        raise ValueError(f"Missing integer field: {key}")
    return int(round(float(body[key])))


def _capture_backend(value: Any) -> str:
    backend = str(value or "auto").strip().lower()
    if backend not in {"auto", "window", "desktop", "dm"}:
        raise CaptureError(f"Unsupported capture backend: {backend}")
    return backend


def _query_value(parsed, name: str) -> str:
    values = parse_qs(parsed.query).get(name) or []
    return values[0] if values else ""


def _strings_from_body(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ValueError(f"Expected string or list of strings, got: {value!r}")


def _completion_count_from_body(body: dict[str, Any]) -> int:
    value = _first_present_from_body(
        body,
        "completion_count",
        "completionCount",
        "success_count",
        "successCount",
        "max_success",
        "maxSuccess",
        default=1,
    )
    return max(1, int(value if value not in (None, "") else 1))


def _optional_text_from_body(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _first_present_from_body(body: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in body:
            return body[key]
    return default


def _bool_from_body(value: Any, fallback: bool = False) -> bool:
    if value in (None, ""):
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Expected boolean value, got: {value!r}")


def _safe_image_path(value: str, *, allowed_roots: tuple[Path, ...]) -> Path:
    if not value:
        raise ValueError("Image path is required.")
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise ValueError(f"Image path must stay inside allowed project directories: {resolved}")
    return resolved


def _latest_unrecognized_template_from_log(log_text: str) -> dict[str, Any] | None:
    markers = ("未识别截图已放入未识别目录=", "未识别截图已放入第一组模板=")
    for line in reversed(str(log_text or "").splitlines()):
        marker = next((item for item in markers if item in line), None)
        if marker is None:
            continue
        value = line.split(marker, 1)[1].strip()
        if not value:
            continue
        template_info = _template_info_from_unrecognized_path(value)
        if template_info is not None:
            return template_info
    return None


def _template_info_from_unrecognized_path(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        path = _safe_image_path(text, allowed_roots=(TEMPLATES_DIR.resolve(),))
        if path.is_file():
            return _template_info_dict(inspect_template(path))
    except Exception:
        return None
    return None


def _template_loop_failure_events_payload(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for event in events:
        item = dict(event)
        screenshot_path = item.get("screenshot_path")
        screenshot = _template_info_from_unrecognized_path(screenshot_path)
        if screenshot is not None:
            item["screenshot"] = screenshot
        payload.append(item)
    return payload


def _clear_unrecognized_template_group(name: str) -> dict[str, Any]:
    normalized = str(name or "").replace("\\", "/").strip().strip("/")
    if not normalized or normalized == "__all__" or not normalized.endswith("/未识别"):
        raise ValueError("Only an unrecognized template group can be cleared.")
    group_path = _safe_template_group_path(normalized)
    if not group_path.exists():
        return {"group": normalized, "path": str(group_path), "deleted": 0}
    if not group_path.is_dir():
        raise ValueError(f"Unrecognized template path is not a directory: {group_path}")

    deleted = 0
    for image_path in sorted(group_path.glob("*.png")):
        if not image_path.is_file():
            continue
        metadata_path = image_path.with_suffix(".json")
        image_path.unlink()
        deleted += 1
        if metadata_path.exists() and metadata_path.is_file():
            metadata_path.unlink()
    for metadata_path in sorted(group_path.glob("*.json")):
        if metadata_path.is_file():
            metadata_path.unlink()
    try:
        group_path.rmdir()
    except OSError:
        pass
    return {"group": normalized, "path": str(group_path), "deleted": deleted}


def _clear_all_unrecognized_template_groups() -> dict[str, Any]:
    icon_root = (TEMPLATES_DIR / "icons").resolve()
    if not icon_root.exists():
        return {"all": True, "deleted": 0, "groups": []}
    groups: list[dict[str, Any]] = []
    deleted = 0
    for group_path in sorted(path for path in icon_root.rglob("未识别") if path.is_dir()):
        resolved = group_path.resolve()
        if not resolved.is_relative_to(icon_root):
            continue
        group_name = resolved.relative_to(icon_root).as_posix()
        result = _clear_unrecognized_template_group(group_name)
        groups.append(result)
        deleted += int(result.get("deleted") or 0)
    return {"all": True, "deleted": deleted, "groups": groups}


def _delete_unrecognized_template_source(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    relative = resolved.relative_to((TEMPLATES_DIR / "icons").resolve()).as_posix()
    if "/未识别/" not in f"/{relative}":
        raise ValueError("Only unrecognized template source images can be deleted.")
    if resolved.suffix.lower() != ".png":
        raise ValueError("Only PNG unrecognized source images can be deleted.")
    deleted = False
    metadata_deleted = False
    if resolved.exists() and resolved.is_file():
        resolved.unlink()
        deleted = True
    metadata_path = resolved.with_suffix(".json")
    if metadata_path.exists() and metadata_path.is_file():
        metadata_path.unlink()
        metadata_deleted = True
    try:
        resolved.parent.rmdir()
    except OSError:
        pass
    return {
        "path": str(resolved),
        "deleted": deleted,
        "metadata_deleted": metadata_deleted,
    }


def _safe_template_group_path(name: str) -> Path:
    raw = str(name or "").replace("\\", "/").strip().strip("/")
    if not raw:
        raise ValueError("Template group name is required.")
    path = Path(raw)
    if path.is_absolute():
        raise ValueError("Template group must be relative.")
    for part in path.parts:
        if part in ("", ".", ".."):
            raise ValueError(f"Invalid template group segment: {part!r}")
    resolved = (TEMPLATES_DIR / "icons" / path).resolve()
    if not resolved.is_relative_to((TEMPLATES_DIR / "icons").resolve()):
        raise ValueError(f"Template group path must stay inside templates/icons: {resolved}")
    return resolved


def _safe_workflow_path(filename: str) -> Path:
    name = Path(filename).name
    if not name or name != filename or Path(name).suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Workflow filename must be a YAML file name without directories.")
    path = (WORKFLOWS_DIR / name).resolve()
    if not path.is_relative_to(WORKFLOWS_DIR.resolve()):
        raise ValueError(f"Workflow path must stay inside {WORKFLOWS_DIR}: {path}")
    return path


def _list_template_payloads() -> list[dict[str, Any]]:
    return [_template_info_dict(info) for info in list_templates()]


def _list_template_group_payloads() -> list[dict[str, Any]]:
    return [_template_group_dict(info) for info in list_template_groups(include_root=True)]


def _popup_match_payload(match: dict[str, Any], *, found: bool) -> dict[str, Any]:
    payload = {
        "found": found,
        "rule_name": match.get("rule_name"),
        "action": match.get("action"),
        "threshold": match.get("threshold"),
        "checked": match.get("checked", 0),
    }
    if match.get("match_result") is not None:
        payload["match"] = _match_result_dict(match["match_result"])
    else:
        payload["match"] = None
    return payload


def _probe_popup_rules(image_path: Path, *, region: Rect | None, scales: tuple[float, ...] | None) -> dict[str, Any]:
    popups = load_popups()
    raw_rules = popups.get("rules", []) if isinstance(popups, dict) else []
    best: dict[str, Any] | None = None
    checked = 0
    for index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"Popup rule at index {index} must be a mapping.")
        if not bool(raw_rule.get("enabled", True)):
            continue
        rule_name = str(raw_rule.get("name", f"popup_{index + 1}")).strip() or f"popup_{index + 1}"
        action = str(raw_rule.get("action", "esc")).strip().lower() or "esc"
        threshold = float(raw_rule.get("threshold", 0.85))
        templates = raw_rule.get("templates")
        if isinstance(templates, str):
            templates = [templates]
        if not isinstance(templates, list) or not templates:
            raise ValueError(f"Popup rule '{rule_name}' requires a non-empty templates list.")
        for template_value in expand_template_references(templates):
            template_path = _safe_image_path(str(template_value or ""), allowed_roots=(TEMPLATES_DIR.resolve(),))
            debug_path = default_debug_path(image_path)
            match = match_template(
                image_path,
                template_path,
                threshold=threshold,
                region=region,
                scales=scales,
                debug_path=debug_path,
            )
            checked += 1
            current = {
                "rule_name": rule_name,
                "action": action,
                "threshold": threshold,
                "match_result": match,
                "checked": checked,
            }
            if match.found:
                return _popup_match_payload(current, found=True)
            if best is None or match.score > best["match_result"].score:
                best = current
    if best is None:
        return {"found": False, "rule_name": None, "action": None, "threshold": None, "checked": 0, "match": None}
    return _popup_match_payload(best, found=False)


def _parse_scales(value: Any) -> tuple[float, ...] | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(float(item) for item in value)
    raise ValueError(f"Invalid scales value: {value}")


def _template_metadata(body: dict[str, Any], image_path: Path, region: Rect) -> dict[str, Any]:
    click_regions = _click_regions_from_body(body, region)
    if not click_regions:
        click_regions = [{"region": [0, 0, region.width, region.height], "coordinate_space": "template"}]
    coordinate_space, click_region_payloads = _click_region_metadata_payload(click_regions)
    metadata = {
        "template": body.get("filename"),
        "group": str(body.get("group") or "").strip(),
        "source_image": str(image_path),
        "coordinate_space": coordinate_space,
        "source_region": _rect_dict(region),
        "window_client_size": _configured_window_size_payload(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    metadata["click_region"] = click_region_payloads[0]
    metadata["click_regions"] = click_region_payloads
    body_metadata = body.get("metadata")
    if isinstance(body_metadata, dict):
        normalized = _normalize_template_metadata(body_metadata)
        metadata["threshold"] = normalized.get("threshold", DEFAULT_TEMPLATE_MATCH_THRESHOLD)
        metadata["priority"] = normalized.get("priority", 0)
        metadata["is_end_template"] = bool(normalized.get("is_end_template", False))
        metadata["is_success_template"] = bool(normalized.get("is_success_template", False))
        metadata["is_non_standalone"] = bool(normalized.get("is_non_standalone", False))
        metadata["is_fallback_template"] = bool(normalized.get("is_fallback_template", False))
        metadata["avoid_same_position"] = bool(normalized.get("avoid_same_position", False))
        for key in (
            "group_match_limit",
            "postcondition_templates",
            "postcondition_not_templates",
            "post_action_template",
            "post_action_template_threshold",
            "post_action_template_delay_ms",
            "actions",
            "end_template",
        ):
            if key in normalized:
                metadata[key] = normalized[key]
    else:
        metadata["threshold"] = DEFAULT_TEMPLATE_MATCH_THRESHOLD
        metadata["priority"] = 0
        metadata["is_end_template"] = False
        metadata["is_success_template"] = False
        metadata["is_non_standalone"] = False
        metadata["is_fallback_template"] = False
        metadata["avoid_same_position"] = False
        actions = _template_actions_from_body(body)
        if actions:
            metadata["actions"] = actions
        end_template = _optional_text_from_body(body.get("end_template"))
        if end_template:
            metadata["end_template"] = end_template
    return metadata


def _normalize_template_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in metadata.items() if value not in (None, "")}
    normalized["threshold"] = _optional_template_match_threshold(
        normalized.get("threshold")
    ) or DEFAULT_TEMPLATE_MATCH_THRESHOLD
    normalized["priority"] = _normalize_priority(normalized.get("priority"))
    normalized["is_end_template"] = _bool_from_body(normalized.get("is_end_template"), False)
    normalized["is_success_template"] = _bool_from_body(normalized.get("is_success_template"), False)
    normalized["is_non_standalone"] = _bool_from_body(
        normalized.get("is_non_standalone", normalized.get("non_standalone")),
        False,
    )
    normalized["is_fallback_template"] = _bool_from_body(
        normalized.get("is_fallback_template", normalized.get("fallback_template")),
        False,
    )
    normalized["avoid_same_position"] = _bool_from_body(
        normalized.get("avoid_same_position", normalized.get("not_match_same_position")),
        False,
    )
    normalized.pop("non_standalone", None)
    normalized.pop("fallback_template", None)
    normalized.pop("not_match_same_position", None)
    group_match_limit = _normalize_optional_match_limit(normalized.get("group_match_limit"))
    if group_match_limit is not None:
        normalized["group_match_limit"] = group_match_limit
    else:
        normalized.pop("group_match_limit", None)
    preconditions = _normalize_template_references(
        normalized.get("postcondition_templates")
        or normalized.get("postcondition_template")
        or normalized.get("precondition_templates")
        or normalized.get("precondition_template")
        or normalized.get("requires_templates")
        or normalized.get("requires_template")
    )
    if preconditions:
        normalized["postcondition_templates"] = preconditions
    else:
        normalized.pop("postcondition_templates", None)
    postcondition_nots = _normalize_template_references(
        normalized.get("postcondition_not_templates")
        or normalized.get("postcondition_not_template")
        or normalized.get("excludes_templates")
        or normalized.get("excludes_template")
    )
    if postcondition_nots:
        normalized["postcondition_not_templates"] = postcondition_nots
    else:
        normalized.pop("postcondition_not_templates", None)
    for legacy_key in (
        "postcondition_template",
        "precondition_templates",
        "precondition_template",
        "requires_templates",
        "requires_template",
        "postcondition_not_template",
        "excludes_templates",
        "excludes_template",
    ):
        normalized.pop(legacy_key, None)
    post_action_template = _optional_text_from_body(
        normalized.get("post_action_template") or normalized.get("next_template")
    )
    if post_action_template:
        _safe_template_reference(post_action_template)
        normalized["post_action_template"] = post_action_template
        threshold_value = normalized.get("post_action_template_threshold", normalized.get("next_template_threshold"))
        if threshold_value not in (None, ""):
            threshold = float(threshold_value)
            if threshold <= 0 or threshold > 1:
                raise ValueError("post_action_template_threshold must be in (0, 1].")
            normalized["post_action_template_threshold"] = threshold
        else:
            normalized.pop("post_action_template_threshold", None)
        delay_value = normalized.get("post_action_template_delay_ms", normalized.get("next_template_delay_ms"))
        normalized["post_action_template_delay_ms"] = _non_negative_int(delay_value, 0)
    else:
        normalized.pop("post_action_template", None)
        normalized.pop("post_action_template_threshold", None)
        normalized.pop("post_action_template_delay_ms", None)
    for legacy_key in ("next_template", "next_template_threshold", "next_template_delay_ms"):
        normalized.pop(legacy_key, None)
    actions = _normalize_template_actions(normalized.get("actions"), field_name="actions", allow_click=True)
    if actions:
        normalized["actions"] = actions
    else:
        normalized.pop("actions", None)
    normalized.pop("not_found_actions", None)
    end_template = _optional_text_from_body(normalized.get("end_template"))
    if end_template:
        _safe_template_reference(end_template)
        normalized["end_template"] = end_template
    else:
        normalized.pop("end_template", None)
    return normalized


def _normalize_priority(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_optional_match_limit(value: Any) -> int | None:
    if value in (None, ""):
        return None
    limit = int(value)
    if limit < 1:
        return None
    return limit


def _normalize_template_references(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    references: list[str] = []
    seen: set[str] = set()
    for item in values:
        reference = _optional_text_from_body(item)
        if not reference:
            continue
        _safe_template_reference(reference)
        if reference in seen:
            continue
        seen.add(reference)
        references.append(reference)
    return references


def _normalize_template_actions(value: Any, *, field_name: str, allow_click: bool) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        raw_actions = [value]
    elif isinstance(value, list):
        raw_actions = value
    else:
        raise ValueError(f"{field_name} must be an action object or list of action objects.")
    actions = []
    for index, raw_action in enumerate(raw_actions):
        if not isinstance(raw_action, dict):
            raise ValueError(f"{field_name}[{index}] must be an object.")
        actions.append(_normalize_template_action(raw_action, field_name=field_name, allow_click=allow_click))
    return actions


def _normalize_template_action(action: dict[str, Any], *, field_name: str, allow_click: bool) -> dict[str, Any]:
    action_type = str(action.get("type") or "").strip()
    if not action_type:
        raise ValueError(f"{field_name} action requires type.")
    if action_type == "none":
        if not allow_click:
            raise ValueError("not_found_actions do not support none actions.")
        return _compact_action({
            "type": "none",
            "delay_after_ms": _non_negative_int(action.get("delay_after_ms"), 0),
            "note": _optional_text_from_body(action.get("note")),
        })
    if action_type == "click_match":
        if not allow_click:
            raise ValueError("not_found_actions do not support click actions because no template is matched.")
        return _compact_action({
            "type": "click_match",
            "delay_after_ms": _non_negative_int(action.get("delay_after_ms"), 500),
            "note": _optional_text_from_body(action.get("note")),
        })
    if action_type == "key":
        key = str(action.get("key") or "esc").strip().lower()
        if key not in {"esc", "space"}:
            raise ValueError(f"Unsupported template action key: {key}")
        return _compact_action({
            "type": "key",
            "key": key,
            "duration_ms": _non_negative_int(action.get("duration_ms"), 50),
            "delay_after_ms": _non_negative_int(action.get("delay_after_ms"), 0),
            "loop_count": _positive_int(action.get("loop_count", action.get("loopCount")), 1),
            "note": _optional_text_from_body(action.get("note")),
        })
    if action_type == "drag_match":
        if not allow_click:
            raise ValueError("not_found_actions do not support match-based drag actions.")
        return _compact_action({
            "type": "drag_match",
            "direction": _direction_value(action.get("direction"), "up"),
            "distance": _positive_int(action.get("distance"), 300) if action.get("distance_percent", action.get("distancePercent")) in (None, "") else None,
            "distance_percent": _positive_float(action.get("distance_percent", action.get("distancePercent")), "distance_percent") if action.get("distance_percent", action.get("distancePercent")) not in (None, "") else None,
            "duration_ms": _non_negative_int(action.get("duration_ms"), 300),
            "steps": _positive_int(action.get("steps"), 12),
            "delay_after_ms": _non_negative_int(action.get("delay_after_ms"), 500),
            "note": _optional_text_from_body(action.get("note")),
        })
    if action_type == "drag_point":
        return _compact_action({
            "type": "drag_point",
            "start_from": str(action.get("start_from") or "window_center").strip() or "window_center",
            "x": int(action.get("x", 0) or 0) if action.get("start_from") != "window_center" else None,
            "y": int(action.get("y", 0) or 0) if action.get("start_from") != "window_center" else None,
            "direction": _direction_value(action.get("direction"), "up"),
            "distance": _positive_int(action.get("distance"), 60),
            "duration_ms": _non_negative_int(action.get("duration_ms"), 250),
            "steps": _positive_int(action.get("steps"), 10),
            "delay_after_ms": _non_negative_int(action.get("delay_after_ms"), 300),
            "note": _optional_text_from_body(action.get("note")),
        })
    if action_type == "flow":
        flow_name = _optional_text_from_body(action.get("flow"))
        if not flow_name:
            raise ValueError(f"{field_name} flow action requires flow.")
        flow_filename = flow_name if flow_name.lower().endswith((".yaml", ".yml")) else f"{flow_name}.yaml"
        flow_path = safe_template_loop_script_path(flow_filename)
        if not flow_path.is_file():
            raise ValueError(f"Unknown template loop flow: {flow_name}")
        return {"type": "flow", "flow": flow_name}
    if action_type == "wait" and allow_click:
        return _compact_action({
            "type": "wait",
            "duration_ms": _non_negative_int(action.get("duration_ms"), 500),
            "note": _optional_text_from_body(action.get("note")),
        })
    raise ValueError(f"Unsupported {field_name} action type: {action_type}")


def _safe_template_reference(value: str) -> Path:
    normalized = value.replace("\\", "/").strip()
    if normalized.startswith("templates/"):
        candidate = normalized
    elif "/" in normalized:
        candidate = f"templates/icons/{normalized}"
    else:
        name = normalized if normalized.lower().endswith(".png") else f"{normalized}.png"
        candidate = f"templates/icons/{name}"
    path = _safe_image_path(candidate, allowed_roots=(TEMPLATES_DIR.resolve(),))
    if not path.is_file() or path.suffix.lower() != ".png":
        raise ValueError(f"Template action reference must be an existing PNG template: {value}")
    return path


def _compact_action(action: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in action.items() if value not in (None, "")}


def _positive_int(value: Any, fallback: int) -> int:
    return max(1, int(value if value not in (None, "") else fallback))


def _positive_float(value: Any, field_name: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive.")
    return parsed


def _non_negative_int(value: Any, fallback: int) -> int:
    return max(0, int(value if value not in (None, "") else fallback))


def _direction_value(value: Any, fallback: str) -> str:
    direction = str(value or fallback).strip().lower()
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError(f"Unsupported drag direction: {direction}")
    return direction


def _template_actions_from_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    enabled = bool(body.get("click_action_enabled", False))
    actions: list[dict[str, Any]] = []
    if enabled:
        click_action: dict[str, Any] = {"type": "click_match"}
        delay_after_ms = int(body.get("click_action_delay_after_ms") or 500)
        click_action["delay_after_ms"] = delay_after_ms
        note = _optional_text_from_body(body.get("click_action_note"))
        if note:
            click_action["note"] = note
        actions.append(click_action)
    extra_wait_ms = int(body.get("wait_action_duration_ms") or 0)
    if extra_wait_ms > 0:
        wait_action: dict[str, Any] = {"type": "wait", "duration_ms": extra_wait_ms}
        note = _optional_text_from_body(body.get("wait_action_note"))
        if note:
            wait_action["note"] = note
        actions.append(wait_action)
    return actions


def _click_regions_from_body(body: dict[str, Any], source_region: Rect) -> list[dict[str, Any]]:
    raw_regions = body.get("click_regions")
    if raw_regions in (None, ""):
        raw_region = body.get("click_region")
        region = _optional_rect(raw_region) if raw_region not in (None, "") else None
        return [_click_region_spec(region, source_region)] if region is not None else []
    if not isinstance(raw_regions, list):
        raise ValueError("click_regions must be a list of rectangles.")
    regions = []
    for index, raw_region in enumerate(raw_regions):
        try:
            region = _optional_rect(raw_region)
        except ValueError as exc:
            raise ValueError(f"Invalid click_regions[{index}]: {raw_region}") from exc
        if region is not None:
            regions.append(_click_region_spec(region, source_region))
    return regions


def _click_region_spec(region: Rect, source_region: Rect) -> dict[str, Any]:
    if _rect_contains(source_region, region):
        return {"region": _relative_rect_list(region, source_region), "coordinate_space": "template"}
    return {"region": _rect_list(region), "coordinate_space": "window"}


def _click_region_metadata_payload(regions: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    spaces = [str(item.get("coordinate_space") or "template") for item in regions]
    if spaces and all(space == spaces[0] for space in spaces):
        return spaces[0], [item["region"] for item in regions]
    return "mixed", [
        {"region": item["region"], "coordinate_space": str(item.get("coordinate_space") or "template")}
        for item in regions
    ]


def _rect_contains(outer: Rect, inner: Rect) -> bool:
    return inner.left >= outer.left and inner.top >= outer.top and inner.right <= outer.right and inner.bottom <= outer.bottom


def _rect_list(rect: Rect | None) -> list[int]:
    if rect is None:
        raise ValueError("click region cannot be empty.")
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError(f"click region must have positive width and height: {rect}")
    return [rect.left, rect.top, rect.right, rect.bottom]


def _relative_rect_list(rect: Rect | None, source_region: Rect) -> list[int]:
    absolute = _rect_list(rect)
    return [
        absolute[0] - source_region.left,
        absolute[1] - source_region.top,
        absolute[2] - source_region.left,
        absolute[3] - source_region.top,
    ]


def _list_workflows() -> list[dict[str, Any]]:
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for path in sorted([*WORKFLOWS_DIR.glob("*.yaml"), *WORKFLOWS_DIR.glob("*.yml")]):
        item = {"filename": path.name, "valid": True, "id": "", "name": "", "atomic": False}
        try:
            workflow = load_workflow(path)
            item.update({"id": workflow.id, "name": workflow.name, "nodes": len(workflow.nodes), "atomic": not any(node.type == "workflow" for node in workflow.nodes.values())})
        except Exception as exc:
            item.update({"valid": False, "message": str(exc)})
        out.append(item)
    return out


def _workflow_to_editor_model(workflow) -> dict[str, Any]:
    nodes = []
    for index, node in enumerate(workflow.nodes.values()):
        payload = {"id": node.id, "type": node.type, "name": node.name or "", "next": node.next or "", "on_fail": node.on_fail or "", "timeout_ms": node.timeout_ms, "transitions": [asdict(transition) for transition in node.transitions], "params": node.params, "x": 260, "y": 80 + index * 150}
        nodes.append(payload)
    return {"id": workflow.id, "name": workflow.name, "start": workflow.start, "max_steps": workflow.max_steps, "max_failures": workflow.max_failures, "nodes": nodes}


def _run_state_dict(run: dict[str, Any]) -> dict[str, Any]:
    return {"run_id": run.get("run_id"), "workflow_id": run.get("workflow_id"), "workflow_name": run.get("workflow_name"), "workflow_filename": run.get("workflow_filename"), "status": run.get("status"), "step_count": run.get("step_count", 0), "final_node": run.get("final_node"), "message": run.get("message", ""), "success": run.get("success")}


def _run_dir(run_id: str) -> Path:
    return RUNTIME_DIR / "workflows" / run_id


def _read_run_summary(run_id: str) -> dict[str, Any]:
    path = _run_dir(run_id) / "summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_run_logs(run_id: str, *, limit: int) -> list[dict[str, Any]]:
    path = _run_dir(run_id) / "trace.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"raw": line, "parse_error": "invalid json"})
    return entries
