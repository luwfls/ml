from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from game_bot.config.loader import PROJECT_ROOT
from game_bot.scripted.loop_script import (
    STATE_SCRIPTS_DIR,
    TemplateLoopScriptDefinition,
    TemplateLoopScriptError,
    is_template_loop_script_file,
    load_template_loop_script,
    parse_template_loop_script,
    safe_template_loop_script_path,
    template_loop_definition_payload,
)


@dataclass
class ManagedTemplateLoopProcess:
    filename: str
    process: subprocess.Popen | None = None
    status: str = "idle"
    pid: int | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    exit_code: int | None = None
    message: str = ""
    stopped_by_user: bool = False
    hwnd: int | None = None
    dry_run: bool = False
    background_mode: bool = False
    output_thread: threading.Thread | None = None
    log_path: Path | None = None
    recent_failure_events: list[dict[str, Any]] = field(default_factory=list)
    latest_unrecognized_path: str | None = None
    paused: bool = False


@dataclass
class TemplateLoopProcessManager:
    _processes: dict[str, ManagedTemplateLoopProcess] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def list_flows(self) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh_locked()
            process_payloads = dict(self._processes)
        flows = []
        for path in _candidate_script_files():
            if not is_template_loop_script_file(path):
                continue
            flows.append(self._flow_payload_for_path(path, process_payloads.get(path.name)))
        return sorted(flows, key=lambda item: item.get("filename", ""))

    def get_flow(self, filename: str) -> dict[str, Any]:
        path = safe_template_loop_script_path(filename)
        with self._lock:
            self._refresh_locked()
            process = self._processes.get(path.name)
        return self._flow_payload_for_path(path, process)

    def save_flow(
        self,
        filename: str,
        *,
        start_flows: tuple[str, ...],
        loop_dirs: tuple[str, ...],
        end_template: str | None,
        completion_count: int = 1,
    ) -> dict[str, Any]:
        path = safe_template_loop_script_path(filename)
        data = {
            "script": {
                "id": path.stem,
                "start_flows": list(start_flows),
                "loop_dirs": list(loop_dirs),
                "completion_count": max(1, int(completion_count)),
            }
        }
        if end_template:
            data["script"]["end_template"] = end_template
        definition = parse_template_loop_script(data, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dump_yaml(data), encoding="utf-8")
        return self._definition_payload(definition, self._processes.get(path.name))

    def start_flow(
        self,
        filename: str,
        *,
        hwnd: int,
        dry_run: bool = False,
        background_mode: bool = True,
        run_start_flows_first: bool = False,
    ) -> dict[str, Any]:
        path = safe_template_loop_script_path(filename)
        definition = load_template_loop_script(path)
        with self._lock:
            self._refresh_locked()
            existing = self._processes.get(path.name)
            if existing is not None and _is_running(existing.process):
                raise TemplateLoopScriptError(f"Flow is already running: {path.name}")

            definition.log_path.parent.mkdir(parents=True, exist_ok=True)
            definition.log_path.write_text("", encoding="utf-8")
            command = [
                str(_python_executable()),
                str(PROJECT_ROOT / "tools" / "run_template_loop_script.py"),
                str(path),
                "--hwnd",
                str(int(hwnd)),
                "--no-prepare",
            ]
            if dry_run:
                command.append("--dry-run")
            if background_mode:
                command.append("--background")
            if run_start_flows_first:
                command.append("--run-start-flows-first")
            command.append("--no-log-file")
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                env=dict(os.environ, PYTHONUTF8="1"),
            )
            managed = ManagedTemplateLoopProcess(
                filename=path.name,
                process=process,
                status="running",
                pid=process.pid,
                started_at=datetime.now().isoformat(timespec="seconds"),
                stopped_at=None,
                exit_code=None,
                message="running",
                stopped_by_user=False,
                hwnd=int(hwnd),
                dry_run=bool(dry_run),
                background_mode=bool(background_mode),
                log_path=definition.log_path,
            )
            managed.output_thread = threading.Thread(
                target=_pump_process_output,
                args=(managed, definition.log_path),
                name=f"template-loop-log-{path.stem}",
                daemon=True,
            )
            managed.output_thread.start()
            self._processes[path.name] = managed
            return self._definition_payload(definition, managed)

    def pause_flow(self, filename: str) -> dict[str, Any]:
        path = safe_template_loop_script_path(filename)
        definition = load_template_loop_script(path)
        with self._lock:
            self._refresh_locked()
            managed = self._processes.get(path.name)
            if managed is None or not _is_running(managed.process):
                raise TemplateLoopScriptError(f"Flow is not running: {path.name}")
            path.with_suffix(".pause").touch()
            managed.paused = True
            managed.status = "paused"
            managed.message = "paused by user"
            return self._definition_payload(definition, managed)

    def resume_flow(self, filename: str) -> dict[str, Any]:
        path = safe_template_loop_script_path(filename)
        definition = load_template_loop_script(path)
        with self._lock:
            self._refresh_locked()
            managed = self._processes.get(path.name)
            if managed is None or not _is_running(managed.process):
                raise TemplateLoopScriptError(f"Flow is not running: {path.name}")
            path.with_suffix(".pause").unlink(missing_ok=True)
            managed.paused = False
            managed.status = "running"
            managed.message = "resumed by user"
            return self._definition_payload(definition, managed)

    def stop_flow(self, filename: str) -> dict[str, Any]:
        path = safe_template_loop_script_path(filename)
        path.with_suffix(".pause").unlink(missing_ok=True)
        definition = load_template_loop_script(path)
        with self._lock:
            self._refresh_locked()
            managed = self._processes.get(path.name)
            if managed is None or managed.process is None or managed.process.poll() is not None:
                managed = managed or ManagedTemplateLoopProcess(filename=path.name)
                killed = _kill_orphan_template_loop_processes(path)
                managed.status = "stopped"
                managed.stopped_at = datetime.now().isoformat(timespec="seconds")
                managed.message = f"force-killed orphan_count={killed}" if killed else "not running"
                self._processes[path.name] = managed
                return self._definition_payload(definition, managed)

            managed.stopped_by_user = True
            managed.status = "stopping"
            managed.message = "force killing process"
            _force_kill_pid(managed.process.pid)
            orphan_killed = _kill_orphan_template_loop_processes(path, exclude_pids={managed.process.pid})
            try:
                managed.exit_code = managed.process.wait(timeout=1)
                managed.status = "stopped"
                managed.stopped_at = datetime.now().isoformat(timespec="seconds")
                managed.message = f"force-killed exit_code={managed.exit_code} orphan_count={orphan_killed}"
            except subprocess.TimeoutExpired:
                managed.status = "stopping"
                managed.message = f"force kill sent orphan_count={orphan_killed}"
            return self._definition_payload(definition, managed)

    def stop_all_flows(self) -> list[dict[str, Any]]:
        stopped: list[dict[str, Any]] = []
        with self._lock:
            self._refresh_locked()
            running_filenames = [
                filename
                for filename, managed in self._processes.items()
                if _is_running(managed.process)
            ]
        for filename in running_filenames:
            try:
                stopped.append(self.stop_flow(filename))
            except Exception:
                continue
        orphan_killed = _kill_orphan_template_loop_processes()
        if orphan_killed:
            stopped.append({
                "filename": "*",
                "status": "stopped",
                "running": False,
                "process_message": f"force-killed orphan_count={orphan_killed}",
            })
        return stopped

    def read_log(self, filename: str, *, max_chars: int = 20000) -> str:
        path = safe_template_loop_script_path(filename)
        log_path = path.with_suffix(".log")
        if not log_path.is_file():
            return ""
        text = log_path.read_text(encoding="utf-8", errors="replace")
        return text[-max_chars:] if max_chars > 0 else text

    def failure_events(self, filename: str, *, limit: int = 20) -> dict[str, Any]:
        path = safe_template_loop_script_path(filename)
        with self._lock:
            self._refresh_locked()
            managed = self._processes.get(path.name)
            events = list(managed.recent_failure_events if managed is not None else [])
            latest_path = managed.latest_unrecognized_path if managed is not None else None
            running = _is_running(managed.process) if managed is not None else False
        capped_limit = max(1, min(100, int(limit or 20)))
        return {
            "filename": path.name,
            "running": running,
            "failures": events[-capped_limit:],
            "latest_unrecognized_path": latest_path,
        }

    def delete_flow(self, filename: str) -> None:
        path = safe_template_loop_script_path(filename)
        with self._lock:
            self._refresh_locked()
            managed = self._processes.get(path.name)
            if managed is not None and _is_running(managed.process):
                raise TemplateLoopScriptError(f"Flow is running, stop before deleting: {path.name}")
            self._processes.pop(path.name, None)
        if not path.is_file():
            raise TemplateLoopScriptError(f"Flow not found: {path.name}")
        path.unlink()

    def _flow_payload_for_path(self, path: Path, managed: ManagedTemplateLoopProcess | None) -> dict[str, Any]:
        try:
            definition = load_template_loop_script(path)
            return self._definition_payload(definition, managed)
        except Exception as exc:
            payload = {
                "id": path.stem,
                "filename": path.name,
                "path": str(path.resolve()),
                "log_path": str(path.with_suffix(".log").resolve()),
                "start": [],
                "loopDir": [],
                "end": "",
                "completion_count": 1,
                "completionCount": 1,
                "valid": False,
                "message": str(exc),
            }
            payload.update(_process_payload(managed))
            return payload

    def _definition_payload(
        self,
        definition: TemplateLoopScriptDefinition,
        managed: ManagedTemplateLoopProcess | None,
    ) -> dict[str, Any]:
        payload = template_loop_definition_payload(definition)
        payload.update(_process_payload(managed))
        return payload

    def _refresh_locked(self) -> None:
        for managed in self._processes.values():
            process = managed.process
            if process is None:
                continue
            exit_code = process.poll()
            if exit_code is None:
                continue
            if managed.exit_code == exit_code and managed.status in {"completed", "failed", "stopped"}:
                continue
            managed.exit_code = int(exit_code)
            managed.paused = False
            managed.stopped_at = managed.stopped_at or datetime.now().isoformat(timespec="seconds")
            if managed.stopped_by_user:
                managed.status = "stopped"
                managed.message = f"killed exit_code={exit_code}"
            elif exit_code == 0:
                managed.status = "completed"
                managed.message = "completed"
            else:
                managed.status = "failed"
                managed.message = managed.message or f"exit_code={exit_code}"


def _pump_process_output(managed: ManagedTemplateLoopProcess, log_path: Path) -> None:
    process = managed.process
    if process is None or process.stdout is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"[template-loop:{managed.filename}] "
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            for line in process.stdout:
                text = str(line or "")
                if not text:
                    continue
                stripped = text.rstrip("\r\n")
                if stripped:
                    managed.message = stripped[:200]
                console_line = f"{prefix}{text}"
                sys.stdout.write(console_line)
                sys.stdout.flush()
                log_file.write(text)
                log_file.flush()
                event = _failure_event_from_line(managed.filename, stripped)
                if event is not None:
                    managed.recent_failure_events.append(event)
                    managed.recent_failure_events[:] = managed.recent_failure_events[-20:]
                    screenshot_path = event.get("screenshot_path")
                    if screenshot_path:
                        managed.latest_unrecognized_path = str(screenshot_path)
    except Exception as exc:
        managed.message = f"log pump failed: {exc}"


def _failure_event_from_line(filename: str, line: str) -> dict[str, Any] | None:
    text = str(line or "").strip()
    if not text:
        return None
    if not re.search(r"未识别|未匹配|没有模板达到阈值|没有可用模板匹配结果|脚本暂停|脚本异常退出|异常|错误|失败", text):
        return None
    screenshot_path = _text_after_marker(text, "未识别截图已放入未识别目录=") or _text_after_marker(text, "未识别截图已放入第一组模板=")
    round_match = re.search(r"第\s*(\d+)\s*轮", text)
    best_template_match = re.search(r"最高得分模板=([^，；]+)", text)
    best_score_match = re.search(r"得分=([0-9.]+)", text)
    event: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "filename": filename,
        "kind": _failure_event_kind(text),
        "level": "error" if re.search(r"异常|错误|失败", text) else "warning",
        "message": text,
    }
    if round_match:
        event["round"] = int(round_match.group(1))
    if best_template_match:
        event["best_template"] = best_template_match.group(1).strip()
    if best_score_match:
        try:
            event["best_score"] = float(best_score_match.group(1))
        except ValueError:
            pass
    if screenshot_path:
        event["screenshot_path"] = screenshot_path
    return event


def _failure_event_kind(text: str) -> str:
    if "没有模板达到阈值" in text:
        return "below_threshold"
    if "没有可用模板匹配结果" in text:
        return "no_match_result"
    if "脚本暂停" in text:
        return "pause"
    if "脚本异常退出" in text or "异常" in text or "错误" in text:
        return "error"
    return "match_failure"


def _text_after_marker(text: str, marker: str) -> str | None:
    if marker not in text:
        return None
    return text.split(marker, 1)[1].strip() or None


def _process_payload(managed: ManagedTemplateLoopProcess | None) -> dict[str, Any]:
    if managed is None:
        return {
            "status": "idle",
            "running": False,
            "paused": False,
            "pid": None,
            "started_at": None,
            "stopped_at": None,
            "exit_code": None,
            "process_message": "",
            "hwnd": None,
            "dry_run": False,
            "background_mode": False,
        }
    return {
        "status": managed.status,
        "running": _is_running(managed.process),
        "paused": managed.paused,
        "pid": managed.pid,
        "started_at": managed.started_at,
        "stopped_at": managed.stopped_at,
        "exit_code": managed.exit_code,
        "process_message": managed.message,
        "hwnd": managed.hwnd,
        "dry_run": managed.dry_run,
        "background_mode": managed.background_mode,
    }


def _is_running(process: subprocess.Popen | None) -> bool:
    return process is not None and process.poll() is None


def _force_kill_pid(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        completed = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return completed.returncode == 0
    except Exception:
        return False


def _kill_orphan_template_loop_processes(path: Path | None = None, *, exclude_pids: set[int] | None = None) -> int:
    exclude = set(exclude_pids or set())
    script_path = (PROJECT_ROOT / "tools" / "run_template_loop_script.py").resolve()
    target_path = path.resolve() if path is not None else None
    try:
        command = [
            "wmic",
            "process",
            "where",
            "name='python.exe' or name='pythonw.exe'",
            "get",
            "ProcessId,CommandLine",
            "/format:csv",
        ]
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception:
        return 0
    if completed.returncode != 0:
        return 0

    killed = 0
    script_tokens = {
        str(script_path).lower(),
        str(script_path).replace("\\", "/").lower(),
        "tools\\run_template_loop_script.py",
        "tools/run_template_loop_script.py",
    }
    target_tokens = set()
    if target_path is not None:
        target_tokens = {
            str(target_path).lower(),
            str(target_path).replace("\\", "/").lower(),
            str(target_path.name).lower(),
        }
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("node,commandline,processid"):
            continue
        try:
            command_line, pid_text = line.rsplit(",", 1)
            command_text = command_line.split(",", 1)[1] if "," in command_line else command_line
            pid = int(pid_text.strip())
        except (ValueError, IndexError):
            continue
        if pid in exclude:
            continue
        normalized = command_text.lower()
        if not any(token in normalized for token in script_tokens):
            continue
        if target_tokens and not any(token in normalized for token in target_tokens):
            continue
        if _force_kill_pid(pid):
            killed += 1
    return killed


def _candidate_script_files() -> list[Path]:
    STATE_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([*STATE_SCRIPTS_DIR.glob("*.yaml"), *STATE_SCRIPTS_DIR.glob("*.yml")])


def _log_tail_for_message(filename: str) -> str:
    path = STATE_SCRIPTS_DIR / Path(filename).name
    log_path = path.with_suffix(".log")
    if not log_path.is_file():
        return ""
    for line in reversed(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
        text = line.strip()
        if text:
            return text[:200]
    return ""


def _python_executable() -> Path:
    checked_in = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    return checked_in if checked_in.exists() else Path(sys.executable)


def _dump_yaml(data: dict[str, Any]) -> str:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise TemplateLoopScriptError("PyYAML is required to save template loop scripts") from exc
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
