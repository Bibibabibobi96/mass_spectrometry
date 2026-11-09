"""Pair already validated particle events without choosing scientific equality.

Callers own the original cohort, event validity, units, field selection and
numerical/stochastic acceptance. Event order and repeated event names are
preserved. No source IDs are generated and no rows are read from files.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any


def group_particle_events(
    rows: Iterable[Mapping[str, Any]], particle_ids: Iterable[int], *,
    key: Callable[[Mapping[str, Any]], int] | None = None,
) -> dict[int, list[Mapping[str, Any]]]:
    """Group once in supplied cohort order; unknown IDs cannot be discarded.

The optional key only adapts an existing caller's ID representation, such as
an integer encoded in its CSV row. Cohort/event validation stays with callers.
"""
    grouped: dict[int, list[Mapping[str, Any]]] = {pid: [] for pid in particle_ids}
    for row in rows:
        grouped[row['particle_id'] if key is None else key(row)].append(row)
    return grouped


def iter_particle_event_fields(
    left: Mapping[int, Sequence[Mapping[str, Any]]],
    right: Mapping[int, Sequence[Mapping[str, Any]]], *,
    particle_ids: Iterable[int], fields: Sequence[str],
) -> Iterator[tuple[int, int, str, Any, Any]]:
    """Yield cohort/event/field pairs; (-1, event_count) precedes unequal lists.

Only overlapping events have field pairs, as in the existing replay reports.
Callers retain the count mismatch and decide equality for every scalar pair.
"""
    for pid in particle_ids:
        before, after = left[pid], right[pid]
        if len(before) != len(after):
            yield pid, -1, 'event_count', len(before), len(after)
        for index, (a, b) in enumerate(zip(before, after)):
            for field in fields:
                yield pid, index, field, a[field], b[field]
