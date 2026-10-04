import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil

import cv2
import numpy as np

from game_bot.config.loader import PROJECT_ROOT
from game_bot.core.models import Rect

TEMPLATES_DIR = PROJECT_ROOT / "templates"
ICON_TEMPLATES_DIR = TEMPLATES_DIR / "icons"
PROJECT_ROOT_RESOLVED = PROJECT_ROOT.resolve()
TEMPLATES_DIR_RESOLVED = TEMPLATES_DIR.resolve()
ICON_TEMPLATES_DIR_RESOLVED = ICON_TEMPLATES_DIR.resolve()
BACKUP_DIR = PROJECT_ROOT / "runtime" / "backups" / "templates"
DELETED_TEMPLATE_DIR = BACKUP_DIR / "deleted"
SUPPORTED_TEMPLATE_EXTENSIONS = {".png"}
GROUP_REFERENCE_PREFIX = "group:"
_TEMPLATE_INFO_CACHE: dict[Path, tuple[int, int, "TemplateInfo"]] = {}


@dataclass(frozen=True)
class TemplateInfo:
    path: Path
    relative_path: str
    group: str
    width: int
    height: int
    stddev: float
    valid: bool
    message: str


@dataclass(frozen=True)
class TemplateGroupInfo:
    path: Path
    relative_path: str
    name: str
    template_count: int


@dataclass(frozen=True)
class TemplateImportResult:
    info: TemplateInfo
    backup_path: Path | None = None


@dataclass(frozen=True)
class TemplateDeleteResult:
    path: Path
    backup_path: Path


@dataclass(frozen=True)
class TemplateRenameResult:
    old_path: Path
    new_path: Path
    metadata_old_path: Path | None = None
    metadata_new_path: Path | None = None
    metadata_renamed: bool = False


@dataclass(frozen=True)
class TemplateCopyResult:
    source_path: Path
    new_path: Path
    metadata_source_path: Path | None = None
    metadata_new_path: Path | None = None
    metadata_copied: bool = False


@dataclass(frozen=True)
class TemplateGroupRenameResult:
    old_path: Path
    new_path: Path
    updated_templates: tuple[Path, ...]


@dataclass(frozen=True)
class TemplateGroupDeleteResult:
    path: Path


@dataclass(frozen=True)
class TemplateGroupCopyResult:
    source_path: Path
    target_path: Path
    copied_templates: tuple[Path, ...]


@dataclass(frozen=True)
class TemplateMetadataSaveResult:
    path: Path
    metadata_path: Path
    info: TemplateInfo


class TemplateManagerError(RuntimeError):
    pass


def list_templates(folder: str | Path | None = None) -> list[TemplateInfo]:
    root = _resolve_template_root(folder) if folder is not None else TEMPLATES_DIR
    if not root.exists():
        return []
    paths = sorted(path for path in root.rglob("*.png") if path.is_file())
    return [_inspect_template_resolved(path) for path in paths]


def list_template_groups(*, include_root: bool = False) -> list[TemplateGroupInfo]:
    ICON_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    groups: list[TemplateGroupInfo] = []
    if include_root:
        groups.append(
            TemplateGroupInfo(
                path=ICON_TEMPLATES_DIR,
                relative_path=_project_relative(ICON_TEMPLATES_DIR),
                name="",
                template_count=_count_group_templates(ICON_TEMPLATES_DIR),
            )
        )
    for path in sorted(dir_path for dir_path in ICON_TEMPLATES_DIR.rglob("*") if dir_path.is_dir()):
        group_name = _group_name_for_path(path)
        if group_name is None:
            continue
        groups.append(
            TemplateGroupInfo(
                path=path,
                relative_path=_project_relative(path),
                name=group_name,
                template_count=_count_group_templates(path),
            )
        )
    return groups


def create_template_group(name: str | Path) -> TemplateGroupInfo:
    group_path = _resolve_group_path(name, require_non_empty=True)
    group_path.mkdir(parents=True, exist_ok=True)
    return TemplateGroupInfo(
        path=group_path,
        relative_path=_project_relative(group_path),
        name=_group_name_for_path(group_path) or "",
        template_count=_count_group_templates(group_path),
    )


def rename_template_group(old_name: str | Path, new_name: str | Path) -> TemplateGroupRenameResult:
    old_path = _resolve_group_path(old_name, require_non_empty=True)
    if not old_path.exists() or not old_path.is_dir():
        raise TemplateManagerError(f"Template group does not exist: {old_path}")
    new_path = _resolve_group_path(new_name, require_non_empty=True)
    if old_path == new_path:
        raise TemplateManagerError("Source and destination template groups are the same directory.")
    if new_path.exists():
        raise TemplateManagerError(f"Template group already exists: {new_path}")

    updated_templates: list[Path] = []
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old_relative = _group_name_for_path(old_path) or ""
    try:
        old_path.rename(new_path)
        for template_path in sorted(new_path.rglob("*.png")):
            metadata_path = template_path.with_suffix(".json")
            if not metadata_path.exists():
                continue
            _update_template_metadata(metadata_path, template_path)
            updated_templates.append(template_path)
    except OSError as exc:
        if new_path.exists() and not old_path.exists():
            try:
                new_path.rename(old_path)
            except OSError:
                pass
        raise TemplateManagerError(f"Failed to rename template group: {old_relative} -> {_group_name_for_path(new_path) or ''}") from exc
    return TemplateGroupRenameResult(old_path=old_path, new_path=new_path, updated_templates=tuple(updated_templates))


def delete_template_group(name: str | Path) -> TemplateGroupDeleteResult:
    group_path = _resolve_group_path(name, require_non_empty=True)
    if not group_path.exists() or not group_path.is_dir():
        raise TemplateManagerError(f"Template group does not exist: {group_path}")
    if _count_group_templates(group_path):
        raise TemplateManagerError(f"Template group is not empty: {group_path}")
    if any(group_path.iterdir()):
        raise TemplateManagerError(f"Template group is not empty: {group_path}")
    try:
        group_path.rmdir()
    except OSError as exc:
        raise TemplateManagerError(f"Failed to delete template group: {group_path}") from exc
    return TemplateGroupDeleteResult(path=group_path)


def copy_template_group(source_name: str | Path, target_name: str | Path) -> TemplateGroupCopyResult:
    source_path = _resolve_group_path(source_name, require_non_empty=True)
    if not source_path.exists() or not source_path.is_dir():
        raise TemplateManagerError(f"Template group does not exist: {source_path}")
    target_path = _resolve_group_path(target_name, require_non_empty=True)
    if source_path == target_path:
        raise TemplateManagerError("Source and destination template groups are the same directory.")
    if target_path.exists():
        raise TemplateManagerError(f"Template group already exists: {target_path}")

    template_paths = tuple(sorted(path for path in source_path.rglob("*.png") if path.is_file()))
    if not template_paths:
        raise TemplateManagerError(f"Template group has no PNG templates: {source_path}")

    copied_templates: list[Path] = []
    try:
        for template_path in template_paths:
            relative_path = template_path.relative_to(source_path)
            destination_path = (target_path / relative_path).resolve()
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template_path, destination_path)

            metadata_source = template_path.with_suffix(".json")
            if metadata_source.exists() and metadata_source.is_file():
                metadata_destination = destination_path.with_suffix(".json")
                shutil.copy2(metadata_source, metadata_destination)
                _update_template_metadata(metadata_destination, destination_path)
            copied_templates.append(destination_path)
    except Exception:
        if target_path.exists():
            shutil.rmtree(target_path, ignore_errors=True)
        raise

    return TemplateGroupCopyResult(
        source_path=source_path,
        target_path=target_path,
        copied_templates=tuple(copied_templates),
    )


def save_template_metadata(path: str | Path, metadata: dict[str, object]) -> TemplateMetadataSaveResult:
    resolved = _resolve_template_path(path)
    if resolved.suffix.lower() not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise TemplateManagerError("Only PNG template metadata can be saved.")
    if not resolved.exists() or not resolved.is_file():
        raise TemplateManagerError(f"Template file does not exist: {resolved}")
    data = dict(metadata)
    data["template"] = resolved.stem
    data["group"] = _template_group(resolved)
    metadata_path = resolved.with_suffix(".json")
    metadata_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return TemplateMetadataSaveResult(path=resolved, metadata_path=metadata_path, info=inspect_template(resolved))


def list_group_template_paths(group: str | Path) -> tuple[Path, ...]:
    group_path = _resolve_group_path(group, require_non_empty=True)
    if not group_path.exists():
        return ()
    return tuple(sorted(path for path in group_path.rglob("*.png") if path.is_file()))


def expand_template_references(
    templates: str | Path | Iterable[str | Path],
) -> tuple[str | Path, ...]:
    values = list(templates) if not isinstance(templates, (str, Path)) else [templates]
    expanded: list[str | Path] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str):
            group_name = _group_reference_name(value)
            if group_name is not None:
                group_paths = list_group_template_paths(group_name)
                if not group_paths:
                    raise TemplateManagerError(f"Template group has no PNG templates: {group_name}")
                for path in group_paths:
                    normalized = _project_relative(path)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    expanded.append(normalized)
                continue
        normalized_value = str(value)
        if normalized_value in seen:
            continue
        seen.add(normalized_value)
        expanded.append(value)
    return tuple(expanded)


def compose_template_references(
    *references: str | Path | Iterable[str | Path],
) -> tuple[str | Path, ...]:
    merged: list[str | Path] = []
    for reference in references:
        if isinstance(reference, (str, Path)):
            merged.append(reference)
            continue
        merged.extend(reference)
    return expand_template_references(merged)


def inspect_template(path: str | Path) -> TemplateInfo:
    resolved = _resolve_template_path(path)
    return _inspect_template_resolved(resolved)


def _inspect_template_resolved(resolved: Path) -> TemplateInfo:
    relative_path = _project_relative_resolved(resolved)
    group = _template_group_resolved(resolved)
    if not resolved.exists():
        return TemplateInfo(resolved, relative_path, group, 0, 0, 0.0, False, "Template file does not exist.")
    try:
        stat = resolved.stat()
    except OSError:
        return TemplateInfo(resolved, relative_path, group, 0, 0, 0.0, False, "Template file does not exist.")
    cached = _TEMPLATE_INFO_CACHE.get(resolved)
    if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]

    image = _read_image(resolved)
    if image is None:
        return TemplateInfo(resolved, relative_path, group, 0, 0, 0.0, False, "Failed to read template image.")

    height, width = image.shape[:2]
    stddev = float(image.std())
    valid = stddev > 0.0
    message = "OK" if valid else "Template has no visual variance."
    info = TemplateInfo(resolved, relative_path, group, width, height, stddev, valid, message)
    _TEMPLATE_INFO_CACHE[resolved] = (stat.st_mtime_ns, stat.st_size, info)
    return info


def delete_template(path: str | Path) -> TemplateDeleteResult:
    resolved = _resolve_template_path(path)
    if resolved.suffix.lower() not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise TemplateManagerError("Only PNG templates can be deleted.")
    if not resolved.exists():
        raise TemplateManagerError(f"Template file does not exist: {resolved}")
    if not resolved.is_file():
        raise TemplateManagerError(f"Template path is not a file: {resolved}")
    return TemplateDeleteResult(path=resolved, backup_path=_move_deleted_template(resolved))


def rename_template(path: str | Path, filename: str, *, group: str | Path | None = None, replace: bool = False) -> TemplateRenameResult:
    source = _resolve_template_path(path)
    if source.suffix.lower() not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise TemplateManagerError("Only PNG templates can be renamed.")
    if not source.exists():
        raise TemplateManagerError(f"Template file does not exist: {source}")
    if not source.is_file():
        raise TemplateManagerError(f"Template path is not a file: {source}")

    destination = _resolve_destination(filename, group=group)
    same_path = source == destination
    same_path_ignore_case = str(source).casefold() == str(destination).casefold()
    if same_path:
        raise TemplateManagerError("Source and destination template are the same file.")
    if destination.exists() and not same_path_ignore_case:
        if not replace:
            raise TemplateManagerError(f"Template already exists: {destination}")

    metadata_source = source.with_suffix(".json")
    metadata_destination = destination.with_suffix(".json")
    metadata_same_ignore_case = str(metadata_source).casefold() == str(metadata_destination).casefold()
    if metadata_destination.exists() and not metadata_same_ignore_case:
        if not replace:
            raise TemplateManagerError(f"Template metadata already exists: {metadata_destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata_renamed = False
    metadata_old_path = metadata_source if metadata_source.exists() else None
    try:
        _rename_path(source, destination)
        if metadata_source.exists():
            _rename_path(metadata_source, metadata_destination)
            metadata_renamed = True
            _update_template_metadata(metadata_destination, destination)
    except OSError as exc:
        if destination.exists() and not source.exists():
            try:
                _rename_path(destination, source)
            except OSError:
                pass
        raise TemplateManagerError(f"Failed to rename template: {source} -> {destination}") from exc
    return TemplateRenameResult(
        old_path=source,
        new_path=destination,
        metadata_old_path=metadata_old_path,
        metadata_new_path=metadata_destination if metadata_renamed else None,
        metadata_renamed=metadata_renamed,
    )



def copy_template(path: str | Path, filename: str, *, group: str | Path | None = None, replace: bool = False) -> TemplateCopyResult:
    source = _resolve_template_path(path)
    if source.suffix.lower() not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise TemplateManagerError("Only PNG templates can be copied.")
    if not source.exists():
        raise TemplateManagerError(f"Template file does not exist: {source}")
    if not source.is_file():
        raise TemplateManagerError(f"Template path is not a file: {source}")

    destination = _resolve_destination(filename, group=group)
    if source == destination or str(source).casefold() == str(destination).casefold():
        raise TemplateManagerError("Source and destination template are the same file.")
    if destination.exists() and not replace:
        raise TemplateManagerError(f"Template already exists: {destination}")

    metadata_source = source.with_suffix(".json")
    metadata_destination = destination.with_suffix(".json")
    if metadata_destination.exists() and not replace:
        raise TemplateManagerError(f"Template metadata already exists: {metadata_destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_existed = destination.exists()
    metadata_destination_existed = metadata_destination.exists()
    metadata_copied = False
    metadata_old_path = metadata_source if metadata_source.exists() else None
    try:
        shutil.copy2(source, destination)
        if metadata_source.exists() and metadata_source.is_file():
            shutil.copy2(metadata_source, metadata_destination)
            metadata_copied = True
            _update_template_metadata(metadata_destination, destination)
    except OSError as exc:
        if destination.exists() and not destination_existed:
            try:
                destination.unlink()
            except OSError:
                pass
        if metadata_destination.exists() and metadata_copied and not metadata_destination_existed:
            try:
                metadata_destination.unlink()
            except OSError:
                pass
        raise TemplateManagerError(f"Failed to copy template: {source} -> {destination}") from exc

    return TemplateCopyResult(
        source_path=source,
        new_path=destination,
        metadata_source_path=metadata_old_path,
        metadata_new_path=metadata_destination if metadata_copied else None,
        metadata_copied=metadata_copied,
    )



def crop_template_from_image(
    image_path: str | Path,
    region: Rect,
    filename: str,
    *,
    group: str | Path | None = None,
    replace: bool = False,
) -> TemplateImportResult:
    source = Path(image_path)
    if not source.is_absolute():
        source = PROJECT_ROOT / source
    source = source.resolve()
    if not source.exists():
        raise TemplateManagerError(f"Source image does not exist: {source}")

    image = _read_image(source)
    if image is None:
        raise TemplateManagerError(f"Failed to read source image: {source}")
    _validate_crop_region(region, source, image.shape[1], image.shape[0])

    cropped = image[region.top : region.bottom, region.left : region.right]
    if float(cropped.std()) == 0.0:
        raise TemplateManagerError("Cropped template has no visual variance.")

    destination = _resolve_destination(filename, group=group)
    backup_path = None
    if destination.exists():
        if not replace:
            raise TemplateManagerError(f"Template already exists: {destination}")
        backup_path = _backup_template(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _write_png(destination, cropped):
        raise TemplateManagerError(f"Failed to save cropped template: {destination}")
    info = inspect_template(destination)
    if not info.valid:
        raise TemplateManagerError(info.message)
    return TemplateImportResult(info=info, backup_path=backup_path)



def import_template(
    source_path: str | Path,
    filename: str,
    *,
    group: str | Path | None = None,
    replace: bool = False,
) -> TemplateImportResult:
    source = Path(source_path).resolve()
    if not source.exists():
        raise TemplateManagerError(f"Source template does not exist: {source}")
    if source.suffix.lower() not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise TemplateManagerError("Only PNG templates are supported for import.")

    source_info = _inspect_external_image(source)
    if not source_info.valid:
        raise TemplateManagerError(source_info.message)

    destination = _resolve_destination(filename, group=group)
    if source == destination:
        raise TemplateManagerError("Source and destination template are the same file.")
    backup_path = None
    if destination.exists():
        if not replace:
            raise TemplateManagerError(f"Template already exists: {destination}")
        backup_path = _backup_template(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    info = inspect_template(destination)
    if not info.valid:
        raise TemplateManagerError(info.message)
    return TemplateImportResult(info=info, backup_path=backup_path)


def _validate_crop_region(region: Rect, source: Path, width: int, height: int) -> None:
    if region.left < 0 or region.top < 0 or region.right > width or region.bottom > height:
        raise TemplateManagerError(f"Crop region is outside image bounds for {source}: {region}")
    if region.width <= 0 or region.height <= 0:
        raise TemplateManagerError(f"Crop region must have positive width and height: {region}")



def _inspect_external_image(path: Path) -> TemplateInfo:
    image = _read_image(path)
    if image is None:
        return TemplateInfo(path, str(path), "", 0, 0, 0.0, False, "Failed to read source image.")
    height, width = image.shape[:2]
    stddev = float(image.std())
    valid = stddev > 0.0
    message = "OK" if valid else "Source template has no visual variance."
    return TemplateInfo(path, str(path), "", width, height, stddev, valid, message)


def _resolve_template_root(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    resolved = resolved.resolve()
    if not resolved.is_relative_to(TEMPLATES_DIR_RESOLVED):
        raise TemplateManagerError(f"Template folder must stay inside {TEMPLATES_DIR}: {resolved}")
    return resolved


def _resolve_template_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    resolved = resolved.resolve()
    if not resolved.is_relative_to(TEMPLATES_DIR_RESOLVED):
        raise TemplateManagerError(f"Template path must stay inside {TEMPLATES_DIR}: {resolved}")
    return resolved


def _resolve_destination(filename: str, *, group: str | Path | None = None) -> Path:
    safe_name = _safe_filename(filename)
    destination = (_resolve_group_path(group) / safe_name).resolve()
    if not destination.is_relative_to(ICON_TEMPLATES_DIR_RESOLVED):
        raise TemplateManagerError(f"Template destination must stay inside {ICON_TEMPLATES_DIR}: {destination}")
    return destination


def _safe_filename(filename: str) -> str:
    raw_name = filename.strip()
    name = Path(raw_name).name.strip()
    if not name:
        raise TemplateManagerError("Template filename is required.")
    if name != raw_name:
        raise TemplateManagerError("Template filename cannot include directories.")
    path_name = Path(name)
    if not path_name.suffix:
        name = f"{name}.png"
    elif path_name.suffix.lower() not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise TemplateManagerError("Template filename must be a PNG file.")
    if any(char in name for char in '<>:"/\\|?*'):
        raise TemplateManagerError("Template filename contains characters that Windows file names do not support.")
    if Path(name).stem.rstrip(" .") != Path(name).stem or name.rstrip(" .") != name:
        raise TemplateManagerError("Template filename cannot end with a space or dot.")
    return name


def _resolve_group_path(group: str | Path | None, *, require_non_empty: bool = False) -> Path:
    if group in (None, ""):
        if require_non_empty:
            raise TemplateManagerError("Template group name is required.")
        return ICON_TEMPLATES_DIR.resolve()

    raw = str(group).strip().replace("\\", "/")
    if not raw:
        if require_non_empty:
            raise TemplateManagerError("Template group name is required.")
        return ICON_TEMPLATES_DIR.resolve()

    path = Path(raw)
    if path.is_absolute():
        raise TemplateManagerError("Template group cannot be an absolute path.")

    parts = []
    for part in path.parts:
        if part in ("", ".", ".."):
            raise TemplateManagerError(f"Invalid template group segment: {part!r}")
        if any(char in part for char in '<>:"/\\|?*'):
            raise TemplateManagerError(f"Template group contains characters that Windows directory names do not support: {part}")
        if part.rstrip(" .") != part:
            raise TemplateManagerError("Template group segments cannot end with a space or dot.")
        parts.append(part)

    resolved = ICON_TEMPLATES_DIR.joinpath(*parts).resolve()
    if not resolved.is_relative_to(ICON_TEMPLATES_DIR_RESOLVED):
        raise TemplateManagerError(f"Template group must stay inside {ICON_TEMPLATES_DIR}: {resolved}")
    return resolved


def _template_group(path: Path) -> str:
    group_name = _group_name_for_path(path.parent)
    return group_name or ""


def _template_group_resolved(path: Path) -> str:
    group_name = _group_name_for_resolved_path(path.parent)
    return group_name or ""


def _group_name_for_path(path: Path) -> str | None:
    resolved = path.resolve()
    return _group_name_for_resolved_path(resolved)


def _group_name_for_resolved_path(resolved: Path) -> str | None:
    if not resolved.is_relative_to(ICON_TEMPLATES_DIR_RESOLVED):
        return None
    relative = resolved.relative_to(ICON_TEMPLATES_DIR_RESOLVED)
    if not relative.parts:
        return ""
    return relative.as_posix()


def _count_group_templates(path: Path) -> int:
    return sum(1 for item in path.rglob("*.png") if item.is_file())


def _group_reference_name(value: str) -> str | None:
    text = value.strip()
    if not text.lower().startswith(GROUP_REFERENCE_PREFIX):
        return None
    group_name = text[len(GROUP_REFERENCE_PREFIX) :].strip()
    if not group_name:
        raise TemplateManagerError("Template group reference must include a group name, for example group:popups")
    return group_name


def _read_image(path: Path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def _write_png(path: Path, image) -> bool:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        return False
    encoded.tofile(str(path))
    return True


def _rename_path(source: Path, destination: Path) -> None:
    if str(source).casefold() == str(destination).casefold() and source != destination:
        temp = source.with_name(f".{source.stem}.{uuid.uuid4().hex}.tmp{source.suffix}")
        source.rename(temp)
        temp.rename(destination)
        return
    source.rename(destination)


def _update_template_metadata(metadata_path: Path, template_path: Path) -> None:
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    data["template"] = template_path.stem
    data["group"] = _template_group(template_path)
    metadata_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _backup_template(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"{path.stem}.{timestamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def _move_deleted_template(path: Path) -> Path:
    relative = path.resolve().relative_to(TEMPLATES_DIR.resolve())
    destination_dir = DELETED_TEMPLATE_DIR.joinpath(*relative.parts[:-1])
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = destination_dir / f"{path.stem}.{timestamp}{path.suffix}"
    counter = 1
    while backup_path.exists():
        backup_path = destination_dir / f"{path.stem}.{timestamp}.{counter}{path.suffix}"
        counter += 1
    try:
        shutil.move(str(path), str(backup_path))
    except OSError as exc:
        raise TemplateManagerError(f"Failed to delete template: {path}") from exc
    return backup_path


def _project_relative(path: Path) -> str:
    try:
        resolved = path if path.is_absolute() else path.resolve()
        return _project_relative_resolved(resolved)
    except ValueError:
        return str(path)


def _project_relative_resolved(resolved: Path) -> str:
    return str(resolved.relative_to(PROJECT_ROOT_RESOLVED)).replace("\\", "/")
