from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Iterable, TypeVar

from game_bot.core.models import MatchResult
from game_bot.scripted.runtime import TemplateProbeResult
from game_bot.vision.template import TemplateError

T = TypeVar("T")


@dataclass(frozen=True)
class PriorityTemplateCandidate:
    index: int
    path: Path
    priority: float


@dataclass(frozen=True)
class PriorityMatchResult(Generic[T]):
    probes: tuple[tuple[int, TemplateProbeResult], ...]
    found: tuple[tuple[int, TemplateProbeResult], ...]
    skipped: tuple[T, ...]
    best_probe: TemplateProbeResult | None
    checked: int


def priority_template_candidates(
    templates: Iterable[Path],
    *,
    priority_for: Callable[[Path], float],
) -> tuple[PriorityTemplateCandidate, ...]:
    candidates = [
        PriorityTemplateCandidate(index=index, path=Path(template_path), priority=float(priority_for(Path(template_path))))
        for index, template_path in enumerate(templates)
    ]
    candidates.sort(key=lambda item: (-item.priority, item.index))
    return tuple(candidates)


def priority_template_groups(
    templates: Iterable[Path],
    *,
    priority_for: Callable[[Path], float],
) -> tuple[tuple[float, tuple[PriorityTemplateCandidate, ...]], ...]:
    groups: list[tuple[float, list[PriorityTemplateCandidate]]] = []
    for candidate in priority_template_candidates(templates, priority_for=priority_for):
        if not groups or groups[-1][0] != candidate.priority:
            groups.append((candidate.priority, []))
        groups[-1][1].append(candidate)
    return tuple((priority, tuple(candidates)) for priority, candidates in groups)


def scan_priority_templates(
    templates: Iterable[Path],
    *,
    priority_for: Callable[[Path], float],
    probe_template: Callable[[PriorityTemplateCandidate], TemplateProbeResult],
    skip_template: Callable[[PriorityTemplateCandidate], T | None] | None = None,
    ignore_oversized: bool = False,
) -> PriorityMatchResult[T]:
    probes: list[tuple[int, TemplateProbeResult]] = []
    found: list[tuple[int, TemplateProbeResult]] = []
    skipped: list[T] = []
    best_probe: TemplateProbeResult | None = None
    checked = 0

    for _priority, candidates in priority_template_groups(templates, priority_for=priority_for):
        priority_found: list[tuple[int, TemplateProbeResult]] = []
        for candidate in candidates:
            skip_value = skip_template(candidate) if skip_template is not None else None
            if skip_value is not None:
                skipped.append(skip_value)
                continue
            try:
                probe = probe_template(candidate)
            except TemplateError as exc:
                if ignore_oversized and "Template is larger than the search image or region" in str(exc):
                    continue
                raise
            checked += 1
            probes.append((candidate.index, probe))
            if best_probe is None or probe.match.score > best_probe.match.score:
                best_probe = probe
            if probe.found:
                priority_found.append((candidate.index, probe))
        if priority_found:
            found.extend(priority_found)
            break

    return PriorityMatchResult(
        probes=tuple(probes),
        found=tuple(found),
        skipped=tuple(skipped),
        best_probe=best_probe,
        checked=checked,
    )


def select_best_priority_match(found: Iterable[tuple[int, TemplateProbeResult]], *, priority_for_match: Callable[[MatchResult], float]) -> TemplateProbeResult | None:
    found_items = list(found)
    if not found_items:
        return None
    found_items.sort(
        key=lambda item: (
            float(priority_for_match(item[1].match)),
            item[1].match.score,
            -item[0],
        ),
        reverse=True,
    )
    return found_items[0][1]
