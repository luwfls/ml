from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game_bot.config.loader import PROJECT_ROOT
from game_bot.vision.templates import ICON_TEMPLATES_DIR, TemplateManagerError, rename_template

TEXT_FILE_SUFFIXES = {
    ".py",
    ".yaml",
    ".yml",
    ".html",
    ".md",
    ".txt",
    ".json",
}
SKIP_DIR_NAMES = {"venv", "runtime", "__pycache__", ".git"}
SECOND_LEVEL_PREFIXES = {"地图"}


@dataclass(frozen=True)
class MovePlan:
    source: Path
    destination_group: str
    destination_relative_path: str


def infer_group_candidate(stem: str, all_stems: set[str]) -> str | None:
    parts = stem.split("_")
    if len(parts) == 1 and any(other != stem and other.startswith(f"{stem}_") for other in all_stems):
        return stem

    if len(parts) >= 2:
        if parts[0] in SECOND_LEVEL_PREFIXES and parts[1]:
            return f"{parts[0]}_{parts[1]}"
        return parts[0] or None

    stripped = re.sub(r"\d+$", "", stem).strip()
    if stripped and stripped != stem:
        return stripped
    return None


def build_move_plans() -> list[MovePlan]:
    root_templates = sorted(path for path in ICON_TEMPLATES_DIR.glob("*.png") if path.is_file())
    all_stems = {path.stem for path in root_templates}
    candidates = {path: infer_group_candidate(path.stem, all_stems) for path in root_templates}
    counts = Counter(candidate for candidate in candidates.values() if candidate)

    plans: list[MovePlan] = []
    for path in root_templates:
        group = candidates[path]
        if not group or counts[group] < 2:
            continue
        plans.append(
            MovePlan(
                source=path,
                destination_group=group,
                destination_relative_path=f"templates/icons/{group}/{path.name}",
            )
        )
    return plans


def replace_template_references(mapping: dict[str, str]) -> list[Path]:
    updated: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_FILE_SUFFIXES:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.is_relative_to(ICON_TEMPLATES_DIR):
            continue

        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        rewritten = original
        for old, new in mapping.items():
            rewritten = rewritten.replace(old, new)

        if rewritten == original:
            continue
        path.write_text(rewritten, encoding="utf-8")
        updated.append(path)
    return updated


def apply_move_plans(plans: list[MovePlan]) -> tuple[list[MovePlan], list[Path]]:
    mapping = {
        f"templates/icons/{plan.source.name}": plan.destination_relative_path
        for plan in plans
    }

    applied: list[MovePlan] = []
    for plan in plans:
        rename_template(plan.source, plan.source.name, group=plan.destination_group)
        applied.append(plan)

    updated_files = replace_template_references(mapping)
    return applied, updated_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-group root templates by filename prefix.")
    parser.add_argument("--apply", action="store_true", help="Move template files and rewrite text references.")
    args = parser.parse_args()

    plans = build_move_plans()
    if not plans:
        print("No templates matched the auto-grouping rule.")
        return 0

    print("Planned groups:")
    grouped = Counter(plan.destination_group for plan in plans)
    for group_name, count in sorted(grouped.items()):
        print(f"  {group_name}: {count}")

    for plan in plans:
        print(f"  MOVE templates/icons/{plan.source.name} -> {plan.destination_relative_path}")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to perform the migration.")
        return 0

    try:
        applied, updated_files = apply_move_plans(plans)
    except TemplateManagerError as exc:
        print(f"Failed: {exc}")
        return 1

    print(f"\nMoved {len(applied)} templates.")
    print(f"Updated {len(updated_files)} referencing files.")
    for path in updated_files:
        print(f"  UPDATED {path.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
