from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Any, Iterable

from game_bot.core.capture import CaptureError, capture_client_to_file as core_capture_client_to_file
from game_bot.core.input import click_client, drag_client, press_key
from game_bot.core.models import ActionResult, CaptureResult, MatchResult, Point, Rect
from game_bot.core.window import bring_window_to_foreground, get_window_info
from game_bot.scripted.context import ScriptContext
from game_bot.vision.template import match_template
from game_bot.vision.templates import expand_template_references


class ScriptRuntimeError(RuntimeError):
    pass


class ScriptPause(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TemplateProbeResult:
    found: bool
    match: MatchResult
    screenshot_path: Path
    debug_path: Path | None = None


class ScriptRuntime:
    def __init__(self, context: ScriptContext, *, capture_backend: str = "auto") -> None:
        self.context = context
        self.requested_capture_backend = capture_backend
        self.capture_backend = capture_backend

    @property
    def hwnd(self) -> int:
        return self.context.hwnd

    def focus(self) -> None:
        if self.context.background_mode:
            return
        bring_window_to_foreground(self.hwnd)
        if not self.context.dry_run:
            sleep(0.5)

    def wait(self, duration_ms: int, *, note: str | None = None) -> None:
        self._log(note or f"等待 {duration_ms}ms")
        self.context.step_index += 1
        if not self.context.dry_run and duration_ms > 0:
            sleep(duration_ms / 1000)

    def capture_client(self, screenshot_path: str | Path) -> CaptureResult:
        try:
            capture_result = core_capture_client_to_file(self.hwnd, screenshot_path, backend=self.capture_backend)
        except CaptureError as exc:
            if (
                self.requested_capture_backend == "auto"
                and self.context.background_mode
                and self.capture_backend == "dm"
            ):
                self._log(f"后台 dm 截图失败，降级为 auto 截图继续运行：{exc}")
                self.capture_backend = "auto"
                capture_result = core_capture_client_to_file(self.hwnd, screenshot_path, backend=self.capture_backend)
            else:
                raise
        self.context.hwnd = capture_result.hwnd
        self.context.screenshot_path = capture_result.path
        return capture_result

    def press_key(self, key: str, *, duration_ms: int = 50, delay_after_ms: int = 0, loop_count: int = 1, note: str | None = None) -> None:
        count = max(1, int(loop_count or 1))
        self._log(note or (f"按键 {key}" if count == 1 else f"按键 {key} × {count}"))
        for index in range(count):
            if not self.context.dry_run:
                press_key(self.hwnd, key, duration_ms=duration_ms)
            self.context.step_index += 1
            if delay_after_ms > 0:
                self.wait(delay_after_ms, note=f"按键后等待 {key}" if count == 1 else f"按键间隔 {key} {index + 1}/{count}")

    def match_first(
        self,
        templates: str | Path | Iterable[str | Path],
        *,
        threshold: float,
        step_name: str,
        save_debug: bool = True,
        recover_popups: bool = True,
        popup_recovery_attempts: int = 2,
    ) -> TemplateProbeResult:
        if popup_recovery_attempts < 0:
            raise ValueError("popup_recovery_attempts must be a non-negative integer")

        last_probe: TemplateProbeResult | None = None
        max_attempts = popup_recovery_attempts + 1 if recover_popups else 1
        for attempt in range(1, max_attempts + 1):
            current_step_name = step_name if attempt == 1 else f"{step_name}_retry_{attempt}"
            probe = self._match_first_once(
                templates,
                threshold=threshold,
                step_name=current_step_name,
                save_debug=save_debug,
            )
            if probe.found:
                return probe
            last_probe = probe

            if attempt >= max_attempts:
                break
            dismissed = self._dismiss_popup_after_match_failure(
                step_prefix=f"{step_name}_popup_retry_{attempt}",
            )
            if not dismissed:
                break

        assert last_probe is not None
        return last_probe

    def _match_first_once(
        self,
        templates: str | Path | Iterable[str | Path],
        *,
        threshold: float,
        step_name: str,
        save_debug: bool,
    ) -> TemplateProbeResult:
        screenshot_path = self.context.screenshot_output_path(step_name)
        capture_result = self.capture_client(screenshot_path)

        template_list = list(expand_template_references(templates))
        if not template_list:
            raise ScriptRuntimeError("templates cannot be empty")

        best_probe: TemplateProbeResult | None = None
        for index, template in enumerate(template_list):
            debug_path = self.context.debug_output_path(step_name, f"match_{index}") if save_debug else None
            match = match_template(
                capture_result.path,
                template,
                threshold=threshold,
                debug_path=debug_path,
            )
            probe = TemplateProbeResult(
                found=match.found,
                match=match,
                screenshot_path=capture_result.path,
                debug_path=debug_path,
            )
            if probe.found:
                self.context.last_match = match
                self.context.step_index += 1
                self._log(f"{step_name}：命中模板 {match.template_path.name}，得分={match.score:.3f}")
                return probe
            if best_probe is None or match.score > best_probe.match.score:
                best_probe = probe

        assert best_probe is not None
        self.context.last_match = best_probe.match
        self.context.step_index += 1
        self._log(f"{step_name}：未命中；最高得分模板={best_probe.match.template_path.name}，得分={best_probe.match.score:.3f}")
        return best_probe

    def _dismiss_popup_after_match_failure(self, *, step_prefix: str) -> bool:
        from game_bot.scripted.components.popups import dismiss_configured_popup

        dismissed = dismiss_configured_popup(self, step_prefix=step_prefix)
        if dismissed:
            self.context.variables["last_popup_recovery_step"] = step_prefix
        return dismissed

    def click_match(
        self,
        probe: TemplateProbeResult,
        *,
        use_random_region: bool = False,
        delay_after_ms: int = 500,
        note: str | None = None,
    ) -> ActionResult:
        if not probe.found:
            raise ScriptRuntimeError("cannot click an unmatched template")

        point = _match_click_point(probe.match, hwnd=self.hwnd, use_random_region=use_random_region)
        click_region = _match_click_region(probe.match, hwnd=self.hwnd)
        self.context.last_match_click_point = point
        self.context.last_match_click_region = click_region
        self._log(note or f"点击模板 {probe.match.template_path.name}，坐标=({point.x},{point.y})")

        if self.context.dry_run:
            result = ActionResult(
                success=True,
                action="click",
                hwnd=self.hwnd,
                message=f"dry-run 点击坐标 ({point.x}, {point.y})",
                client_point=point,
                screen_point=None,
            )
        else:
            try:
                input_result = click_client(self.hwnd, point.x, point.y)
            except Exception as exc:
                message = str(exc)
                if "timed out" not in message:
                    raise
                self._log(f"点击子进程超时，终止本次流程以避免主进程无响应：{message}")
                raise
            result = ActionResult(
                success=input_result.success,
                action="click",
                hwnd=self.hwnd,
                message=input_result.message,
                client_point=input_result.client_point,
                screen_point=input_result.screen_point,
            )

        self.context.step_index += 1
        if delay_after_ms > 0:
            self.wait(delay_after_ms, note=f"点击后等待 {probe.match.template_path.name}")
        return result

    def drag_match(
        self,
        probe: TemplateProbeResult,
        *,
        direction: str = "up",
        distance: int = 300,
        distance_percent: float | None = None,
        duration_ms: int = 300,
        steps: int = 12,
        delay_after_ms: int = 500,
        note: str | None = None,
    ) -> ActionResult:
        if not probe.found:
            raise ScriptRuntimeError("cannot drag from an unmatched template")

        drag_distance = self._drag_distance_from_percent(direction, distance_percent) if distance_percent is not None else distance
        point = _match_click_point(probe.match, hwnd=self.hwnd, use_random_region=False)
        click_region = _match_click_region(probe.match, hwnd=self.hwnd)
        drag_distance, end_point, was_clamped = self._clamped_drag(point, direction=direction, distance=drag_distance)
        self.context.last_match_click_point = point
        self.context.last_match_click_region = click_region
        clamp_note = f"，原始距离={distance}px" if was_clamped else ""
        self._log(note or f"从模板 {probe.match.template_path.name} 拖拽，方向={direction}，起点=({point.x},{point.y})，距离={drag_distance}px{clamp_note}")

        if self.context.dry_run:
            result = ActionResult(
                success=True,
                action="drag",
                hwnd=self.hwnd,
                message=(
                    f"dry-run 拖拽：从 ({point.x}, {point.y}) 到 ({end_point.x}, {end_point.y})，"
                    f"方向={direction}，距离={drag_distance}"
                ),
                client_point=end_point,
                screen_point=None,
            )
        else:
            input_result = drag_client(
                self.hwnd,
                point.x,
                point.y,
                direction=direction,
                distance=drag_distance,
                duration_ms=duration_ms,
                steps=steps,
            )
            result = ActionResult(
                success=input_result.success,
                action="drag",
                hwnd=self.hwnd,
                message=input_result.message,
                client_point=input_result.client_point,
                screen_point=input_result.screen_point,
            )

        self.context.step_index += 1
        if delay_after_ms > 0:
            self.wait(delay_after_ms, note=f"拖拽后等待 {probe.match.template_path.name}")
        return result

    def drag_point(
        self,
        point: Point,
        *,
        direction: str = "up",
        distance: int = 300,
        distance_percent: float | None = None,
        duration_ms: int = 300,
        steps: int = 12,
        delay_after_ms: int = 500,
        note: str | None = None,
    ) -> ActionResult:
        drag_distance = self._drag_distance_from_percent(direction, distance_percent) if distance_percent is not None else distance
        drag_distance, end_point, was_clamped = self._clamped_drag(point, direction=direction, distance=drag_distance)
        self.context.last_match_click_point = point
        self.context.last_match_click_region = None
        clamp_note = f"，原始距离={distance}px" if was_clamped else ""
        self._log(note or f"从坐标 ({point.x},{point.y}) 拖拽，方向={direction}，距离={drag_distance}px{clamp_note}")

        if self.context.dry_run:
            result = ActionResult(
                success=True,
                action="drag",
                hwnd=self.hwnd,
                message=(
                    f"dry-run 拖拽：从 ({point.x}, {point.y}) 到 ({end_point.x}, {end_point.y})，"
                    f"方向={direction}，距离={drag_distance}"
                ),
                client_point=end_point,
                screen_point=None,
            )
        else:
            input_result = drag_client(
                self.hwnd,
                point.x,
                point.y,
                direction=direction,
                distance=drag_distance,
                duration_ms=duration_ms,
                steps=steps,
            )
            result = ActionResult(
                success=input_result.success,
                action="drag",
                hwnd=self.hwnd,
                message=input_result.message,
                client_point=input_result.client_point,
                screen_point=input_result.screen_point,
            )

        self.context.step_index += 1
        if delay_after_ms > 0:
            self.wait(delay_after_ms, note=f"坐标拖拽后等待 ({point.x},{point.y})")
        return result

    def _drag_distance_from_percent(self, direction: str, distance_percent: float | None) -> int:
        percent = max(1.0, min(100.0, float(distance_percent or 1)))
        info = get_window_info(self.hwnd)
        normalized = direction.strip().lower()
        base = info.client_size.width if normalized in {"left", "right"} else info.client_size.height
        return max(1, round(base * percent / 100))

    def _clamped_drag(self, start: Point, *, direction: str, distance: int) -> tuple[int, Point, bool]:
        requested_distance = max(1, int(distance))
        info = get_window_info(self.hwnd)
        end = _drag_end_point(start, direction=direction, distance=requested_distance)
        clamped_end = Point(
            x=max(0, min(info.client_size.width - 1, end.x)),
            y=max(0, min(info.client_size.height - 1, end.y)),
        )
        if clamped_end == end:
            return requested_distance, end, False
        clamped_distance = _drag_distance_between(start, clamped_end, direction=direction)
        if clamped_distance <= 0:
            raise ScriptRuntimeError(
                f"cannot drag {direction} from client point ({start.x}, {start.y}); "
                f"start is already at the window edge"
            )
        return clamped_distance, clamped_end, True

    def expect_template(
        self,
        templates: str | Path | Iterable[str | Path],
        *,
        threshold: float,
        step_name: str,
        failure_reason: str,
        save_debug: bool = True,
    ) -> TemplateProbeResult:
        probe = self.match_first(templates, threshold=threshold, step_name=step_name, save_debug=save_debug)
        if not probe.found:
            raise ScriptPause(failure_reason)
        return probe

    def _log(self, message: str) -> None:
        print(f"[script:{self.context.script_id} step={self.context.step_index:04d}] {message}", flush=True)

    def log(self, message: str) -> None:
        self._log(message)


def _match_click_point(match: MatchResult, *, hwnd: int, use_random_region: bool) -> Point:
    region = _match_click_region(match, hwnd=hwnd)
    if region is None:
        return match.center
    return Point(
        x=(region.left + region.right) // 2,
        y=(region.top + region.bottom) // 2,
    )


def _match_click_region(match: MatchResult, *, hwnd: int) -> Rect:
    regions = _match_click_regions(match, hwnd=hwnd)
    return regions[0] if regions else match.box


def _match_click_regions(match: MatchResult, *, hwnd: int) -> list[Rect]:
    metadata = _template_metadata(match.template_path)
    if metadata is None:
        return [match.box]

    value = metadata.get("click_regions") if metadata.get("click_regions") is not None else metadata.get("click_region")
    if value is None:
        return [match.box]

    coordinate_space = str(metadata.get("coordinate_space", "template"))
    regions = [
        _convert_click_region(region, coordinate_space=space, hwnd=hwnd, match=match)
        for region, space in _parse_click_region_specs(value, coordinate_space)
    ]
    return regions or [match.box]


def _convert_click_region(region: Rect, *, coordinate_space: str, hwnd: int, match: MatchResult) -> Rect:
    if coordinate_space == "screen":
        origin = get_window_info(hwnd).client_origin_screen
        return Rect(region.left - origin.x, region.top - origin.y, region.right - origin.x, region.bottom - origin.y)
    if coordinate_space == "window":
        return region
    return Rect(
        match.box.left + round(region.left * match.scale),
        match.box.top + round(region.top * match.scale),
        match.box.left + round(region.right * match.scale),
        match.box.top + round(region.bottom * match.scale),
    )


def _parse_click_region_specs(value: Any, default_coordinate_space: str) -> list[tuple[Rect, str]]:
    fallback_space = "template" if default_coordinate_space == "mixed" else default_coordinate_space
    if _is_region_value(value):
        return [(_region_from_value(value), fallback_space)]
    if _is_region_spec(value):
        return [_region_spec_from_value(value, fallback_space)]
    if not isinstance(value, list):
        return []
    specs: list[tuple[Rect, str]] = []
    for item in value:
        if _is_region_value(item):
            specs.append((_region_from_value(item), fallback_space))
        elif _is_region_spec(item):
            specs.append(_region_spec_from_value(item, fallback_space))
    return specs


def _is_region_value(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(isinstance(item, int | float) for item in value)


def _is_region_spec(value: Any) -> bool:
    return isinstance(value, dict) and _is_region_value(value.get("region"))


def _region_spec_from_value(value: dict[str, Any], fallback_space: str) -> tuple[Rect, str]:
    return _region_from_value(value["region"]), str(value.get("coordinate_space") or fallback_space)


def _region_from_value(value: Any) -> Rect:
    return Rect(int(value[0]), int(value[1]), int(value[2]), int(value[3]))


def _template_metadata(template_path: Path) -> dict[str, Any] | None:
    metadata_path = template_path.with_suffix(".json")
    if not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return metadata if isinstance(metadata, dict) else None


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
    return start


def _drag_distance_between(start: Point, end: Point, *, direction: str) -> int:
    normalized = direction.strip().lower()
    if normalized == "left":
        return start.x - end.x
    if normalized == "right":
        return end.x - start.x
    if normalized == "up":
        return start.y - end.y
    if normalized == "down":
        return end.y - start.y
    return 0
