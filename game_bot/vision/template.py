from functools import lru_cache
import json
from datetime import datetime
from math import isfinite
from pathlib import Path

import cv2
import numpy as np

from game_bot.config.loader import PROJECT_ROOT, ensure_runtime_dirs
from game_bot.core.geometry import rect_center
from game_bot.core.models import MatchResult, Rect, TemplateImage

DEBUG_DIR = PROJECT_ROOT / "runtime" / "debug"
DEFAULT_TEMPLATE_SCALE_FACTORS = (1.0, 0.95, 1.05, 0.9, 1.1)


class TemplateError(RuntimeError):
    pass


def load_template(template_path: str | Path) -> TemplateImage:
    path = _resolve_path(template_path)
    image = _read_template_image(path)
    height, width = image.shape[:2]
    return TemplateImage(path=path, width=width, height=height)


def match_template(
    image_path: str | Path,
    template_path: str | Path,
    *,
    threshold: float = 0.85,
    region: Rect | None = None,
    scales: tuple[float, ...] | list[float] | None = None,
    debug_path: str | Path | None = None,
    exclude_boxes: tuple[Rect, ...] | list[Rect] | None = None,
    brightness_ratio_min: float = 0.4,
) -> MatchResult:
    source_path = _resolve_path(image_path)
    template = load_template(template_path)
    source = _read_image(source_path)
    template_image = _read_template_image(template.path)
    _validate_template_image(template_image, template.path)

    search_image = source
    offset_x = 0
    offset_y = 0
    if region is not None:
        _validate_region(region, source_path, source.shape[1], source.shape[0])
        search_image = source[region.top : region.bottom, region.left : region.right]
        offset_x = region.left
        offset_y = region.top

    best = None
    for scale in _normalize_scales(scales, template.path, source.shape[1], source.shape[0]):
        scaled_template = _scale_template_image(template_image, scale)
        height, width = scaled_template.shape[:2]
        if width > search_image.shape[1] or height > search_image.shape[0]:
            continue

        result = cv2.matchTemplate(search_image, scaled_template, cv2.TM_CCOEFF_NORMED)
        _suppress_excluded_matches(result, exclude_boxes or (), offset_x, offset_y, width, height)
        _, max_score, _, max_location = cv2.minMaxLoc(result)
        if best is None or max_score > best[0]:
            best = (float(max_score), max_location, width, height, scale)

    if best is None:
        raise TemplateError("Template is larger than the search image or region for all requested scales.")

    max_score, max_location, width, height, scale = best
    left = offset_x + max_location[0]
    top = offset_y + max_location[1]
    box = Rect(left, top, left + width, top + height)
    center = rect_center(box)
    found = max_score >= threshold

    brightness_ratio = 1.0
    if brightness_ratio_min > 0.0:
        best_scaled = _scale_template_image(template_image, scale)
        region_img = search_image[max_location[1]:max_location[1] + height, max_location[0]:max_location[0] + width]
        tmpl_mean = float(cv2.cvtColor(best_scaled, cv2.COLOR_BGR2GRAY).mean())
        region_mean = float(cv2.cvtColor(region_img, cv2.COLOR_BGR2GRAY).mean())
        if tmpl_mean > 0:
            brightness_ratio = region_mean / tmpl_mean
        if brightness_ratio < brightness_ratio_min:
            found = False

    output_debug_path = Path(debug_path) if debug_path is not None else None
    if output_debug_path is not None:
        save_match_debug_image(source, box, max_score, found, output_debug_path, scale=scale)

    return MatchResult(
        found=found,
        score=max_score,
        box=box,
        center=center,
        template_path=template.path,
        image_path=source_path,
        debug_path=output_debug_path,
        scale=scale,
        brightness_ratio=brightness_ratio,
    )


def default_debug_path(image_path: str | Path, *, suffix: str = "match") -> Path:
    ensure_runtime_dirs()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = Path(image_path).stem
    return DEBUG_DIR / f"{timestamp}_{stem}_{suffix}.png"


def _suppress_excluded_matches(result, exclude_boxes: tuple[Rect, ...] | list[Rect], offset_x: int, offset_y: int, width: int, height: int) -> None:
    for box in exclude_boxes:
        left = int(round(box.left - offset_x - width + 1))
        top = int(round(box.top - offset_y - height + 1))
        right = int(round(box.right - offset_x))
        bottom = int(round(box.bottom - offset_y))
        left = max(0, min(left, result.shape[1]))
        top = max(0, min(top, result.shape[0]))
        right = max(0, min(right, result.shape[1]))
        bottom = max(0, min(bottom, result.shape[0]))
        if right > left and bottom > top:
            result[top:bottom, left:right] = -1.0


def save_match_debug_image(
    image,
    box: Rect,
    score: float,
    found: bool,
    output_path: str | Path,
    *,
    scale: float = 1.0,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    debug_image = image.copy()
    color = (0, 255, 0) if found else (0, 0, 255)
    cv2.rectangle(debug_image, (box.left, box.top), (box.right, box.bottom), color, 2)
    center = rect_center(box)
    cv2.drawMarker(debug_image, (center.x, center.y), color, markerType=cv2.MARKER_CROSS, markerSize=16, thickness=2)
    cv2.putText(
        debug_image,
        f"score={score:.3f} found={found} scale={scale:.3f}",
        (box.left, max(18, box.top - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
        cv2.LINE_AA,
    )
    if not _write_png(path, debug_image):
        raise TemplateError(f"Failed to save debug image: {path}")
    return path


def _normalize_scales(
    scales: tuple[float, ...] | list[float] | None,
    template_path: Path,
    source_width: int,
    source_height: int,
) -> tuple[float, ...]:
    if scales is None:
        normalized = _metadata_scales(template_path, source_width, source_height) or DEFAULT_TEMPLATE_SCALE_FACTORS
    else:
        normalized = tuple(float(scale) for scale in scales)
    if not normalized:
        raise TemplateError("At least one template scale is required.")
    for scale in normalized:
        if not isfinite(scale) or scale <= 0:
            raise TemplateError(f"Template scale must be a positive finite number: {scale}")
    return tuple(dict.fromkeys(round(float(scale), 6) for scale in normalized))


def _metadata_scales(template_path: Path, source_width: int, source_height: int) -> tuple[float, ...] | None:
    metadata_path = template_path.with_suffix(".json")
    if not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    size = metadata.get("window_client_size")
    if not isinstance(size, dict):
        return None
    base_width = float(size.get("width") or 0)
    base_height = float(size.get("height") or 0)
    if base_width <= 0 or base_height <= 0:
        return None
    scale_x = source_width / base_width
    scale_y = source_height / base_height
    scale = (scale_x + scale_y) / 2
    return tuple(scale * factor for factor in DEFAULT_TEMPLATE_SCALE_FACTORS)


def _scale_template_image(image, scale: float):
    if scale == 1.0:
        return image
    height, width = image.shape[:2]
    scaled_width = max(1, round(width * scale))
    scaled_height = max(1, round(height * scale))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    scaled = cv2.resize(image, (scaled_width, scaled_height), interpolation=interpolation)
    _validate_template_image(scaled, Path(f"scaled template at {scale:.3f}"))
    return scaled


def _resolve_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved


def _read_image(path: Path):
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise TemplateError(f"Failed to read image: {path}")
    return image


def _read_template_image(path: Path):
    return _read_template_image_cached(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=256)
def _read_template_image_cached(path_str: str, _mtime_ns: int):
    return _read_image(Path(path_str))


def _write_png(path: Path, image) -> bool:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        return False
    encoded.tofile(str(path))
    return True


def _validate_template_image(image, path: Path) -> None:
    if float(image.std()) == 0.0:
        raise TemplateError(f"Template has no visual variance and cannot be matched reliably: {path}")


def _validate_region(region: Rect, source_path: Path, width: int, height: int) -> None:
    if region.left < 0 or region.top < 0 or region.right > width or region.bottom > height:
        raise TemplateError(f"Region is outside image bounds for {source_path}: {region}")
    if region.width <= 0 or region.height <= 0:
        raise TemplateError(f"Region must have positive width and height: {region}")
