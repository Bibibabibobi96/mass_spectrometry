"""Pure lifetime facts and complete-cohort arithmetic over caller-selected IDs.

No particle state, device status, observation, physical loss or survival is
inferred here. Callers own clocks, source/terminal evidence, category meanings
and selection. Missing observations must receive an explicit caller category.
Relative weights are positive statistical weights, never charge or current.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import math
from numbers import Real
from typing import TypedDict

CENSUS_SCHEMA_VERSION = 1


class LifetimePosition(TypedDict):
    before_start: bool
    terminal_reached: bool


class CohortPartition(TypedDict):
    schema_version: int
    mother_particle_ids: list[int]
    mother_count: int
    particle_ids_by_category: dict[str, list[int]]
    counts: dict[str, int]
    weighting: str
    mother_weight_sum: float
    weight_sums: dict[str, float]


class SubsetEfficiency(TypedDict):
    schema_version: int
    mother_particle_ids: list[int]
    numerator_particle_ids: list[int]
    denominator_particle_ids: list[int]
    numerator_count: int
    denominator_count: int
    count_fraction: float | None
    weighting: str
    numerator_weight_sum: float
    denominator_weight_sum: float
    relative_weight_fraction: float | None
    undefined_reason: str | None


def _finite(value: Real, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real number")
    number = float(value)
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise ValueError(f"{label} must be finite" + (" and nonnegative" if nonnegative else ""))
    return number


def _ids(values: Iterable[int], label: str) -> tuple[list[int], set[int]]:
    ordered, seen = [], set()
    for pid in values:
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or pid in seen:
            raise ValueError(f"{label} requires unique positive original integer IDs")
        ordered.append(pid)
        seen.add(pid)
    return ordered, seen


def _weights(mother: list[int], supplied: Mapping[int, Real] | None) -> tuple[dict[int, float], str]:
    if supplied is None:
        return {pid: 1. for pid in mother}, "unit"
    if not isinstance(supplied, Mapping):
        raise ValueError("relative_weights must be a complete ID mapping or explicit None for unit weights")
    _, supplied_ids = _ids(supplied, "relative weight IDs")
    if supplied_ids != set(mother):
        raise ValueError("relative weight IDs must exactly match the complete mother cohort")
    weights = {pid: _finite(supplied[pid], "relative weight") for pid in mother}
    if any(weight <= 0 for weight in weights.values()):
        raise ValueError("relative weights must be strictly positive")
    return weights, "relative"


def _weight_sum(ids: Iterable[int], weights: Mapping[int, float]) -> float:
    try:
        result = math.fsum(weights[pid] for pid in ids)
    except OverflowError as exc:
        raise ValueError("relative weight sum must be finite") from exc
    if not math.isfinite(result):
        raise ValueError("relative weight sum must be finite")
    return result


def lifetime_position(
    query_time_us: Real, start_time_us: Real, terminal_time_us: Real | None, *,
    start_tolerance_us: Real, terminal_tolerance_us: Real,
) -> LifetimePosition:
    """Return boundary facts for a start-inclusive, terminal-exclusive interval.

    All times are supplied in the same caller-declared clock; no epoch or unit
    conversion occurs. Start may mean birth or component admission. A query
    within start tolerance is not before start; a query within terminal
    tolerance has reached termination. Before-start takes precedence if these
    tolerance regions overlap. Terminal before start is invalid.

    A missing terminal only means terminal_reached is false. Neither false
    flag proves that a particle is alive or observed. Tolerances are explicit
    finite nonnegative values; no default comparison tolerance is invented.
    """
    query = _finite(query_time_us, "query time")
    start = _finite(start_time_us, "start time")
    start_tol = _finite(start_tolerance_us, "start tolerance", nonnegative=True)
    terminal_tol = _finite(terminal_tolerance_us, "terminal tolerance", nonnegative=True)
    terminal = None if terminal_time_us is None else _finite(terminal_time_us, "terminal time")
    if terminal is not None and terminal < start:
        raise ValueError("terminal time precedes start time")
    before = query < start and abs(query-start) > start_tol
    reached = not before and terminal is not None and (query >= terminal or abs(query-terminal) <= terminal_tol)
    return dict(before_start=before, terminal_reached=reached)


def partition_cohort(
    mother_ids: Iterable[int], classifications: Iterable[tuple[int, str]], *,
    categories: Sequence[str], relative_weights: Mapping[int, Real] | None,
) -> CohortPartition:
    """Count exactly one caller classification per original mother ID.

    Categories are caller-owned labels, not a shared physical-status enum.
    Unknown, duplicate, unclassified IDs or undeclared labels fail. Empty
    mothers are allowed with empty classifications. Output IDs follow mother
    order and category mappings follow declared category order.

    relative_weights is required: None explicitly declares equal unit weights;
    otherwise its positive finite mapping must cover the entire mother cohort.
    No missing weight is filled, no weight is normalized, and no input mutates.
    """
    mother, mother_set = _ids(mother_ids, "mother cohort")
    if (isinstance(categories, (str, bytes)) or not categories or
            any(not isinstance(label, str) or not label for label in categories) or
            len(set(categories)) != len(categories)):
        raise ValueError("categories must be unique nonempty explicit labels")
    weights, weighting = _weights(mother, relative_weights)
    assigned = {}
    for pid, label in classifications:
        if isinstance(pid, bool) or not isinstance(pid, int) or pid not in mother_set:
            raise ValueError("classification ID is outside the original mother cohort")
        if pid in assigned:
            raise ValueError("duplicate classification for a mother ID")
        if label not in categories:
            raise ValueError("classification category is undeclared")
        assigned[pid] = label
    if set(assigned) != mother_set:
        raise ValueError("classifications do not close the complete mother cohort")
    groups = {label: [pid for pid in mother if assigned[pid] == label] for label in categories}
    return dict(schema_version=CENSUS_SCHEMA_VERSION, mother_particle_ids=mother, mother_count=len(mother),
                particle_ids_by_category=groups, counts={label: len(ids) for label, ids in groups.items()},
                weighting=weighting, mother_weight_sum=_weight_sum(mother, weights),
                weight_sums={label: _weight_sum(ids, weights) for label, ids in groups.items()})


def subset_efficiency(
    mother_ids: Iterable[int], numerator_ids: Iterable[int], denominator_ids: Iterable[int], *,
    relative_weights: Mapping[int, Real] | None,
) -> SubsetEfficiency:
    """Return count and relative-weight fractions for an explicit subset ratio.

    Numerator must be a subset of denominator, and denominator a subset of the
    unique mother IDs. All subset IDs must also be unique. Missing observation
    does not authorize removing an ID from the declared denominator.
    Output selections retain mother order. Empty denominator has zero sums,
    null fractions and undefined_reason='empty_denominator'.

    None explicitly means unit weights; it must not stand for an unknown
    injected weight authority. A supplied mapping covers the entire mother.
    Callers lacking full-chain weight evidence must publish that weighted
    result as unavailable, rather than treating subset weights as a mother.
    """
    mother, mother_set = _ids(mother_ids, "mother cohort")
    _, numerator = _ids(numerator_ids, "numerator")
    _, denominator = _ids(denominator_ids, "denominator")
    if not numerator <= denominator or not denominator <= mother_set:
        raise ValueError("efficiency requires numerator subset of denominator subset of mother")
    weights, weighting = _weights(mother, relative_weights)
    _weight_sum(mother, weights)
    numerator_order = [pid for pid in mother if pid in numerator]
    denominator_order = [pid for pid in mother if pid in denominator]
    numerator_weight = _weight_sum(numerator_order, weights)
    denominator_weight = _weight_sum(denominator_order, weights)
    return dict(schema_version=CENSUS_SCHEMA_VERSION, mother_particle_ids=mother,
                numerator_particle_ids=numerator_order, denominator_particle_ids=denominator_order,
                numerator_count=len(numerator), denominator_count=len(denominator),
                count_fraction=len(numerator)/len(denominator) if denominator else None,
                weighting=weighting, numerator_weight_sum=numerator_weight,
                denominator_weight_sum=denominator_weight,
                relative_weight_fraction=numerator_weight/denominator_weight if denominator else None,
                undefined_reason=None if denominator else "empty_denominator")
