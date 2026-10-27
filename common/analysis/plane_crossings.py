"""Find directed plane crossings supported by adjacent recorded states.

This module owns only bounded geometry and occurrence selection. Callers own the
complete cohort, source-record identity, one verified clock, lifetime/sample
selection, species and diagnostic status. No solver, file, frame transformation,
epoch adjustment or particle-state table is introduced here.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
import math
from numbers import Real
from typing import TypeAlias

from common.contracts.rigid_transform import PhaseSpaceState, PlaneSurface

SCHEMA_VERSION = 1
METHOD = "bounded_linear_directed_plane_crossing"
RecordAnchor: TypeAlias = int | str


def _positive_integer(value: object, label: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer, without coercion")


def _identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonempty trimmed string")


def _anchor(value: object) -> None:
    if type(value) is int:
        _positive_integer(value, "record row number")
    else:
        _identifier(value, "record event key")


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{label} must be a finite real number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite real number")
    return result


@dataclass(frozen=True)
class CrossingSample:
    """An existing state with its unchanged particle ID and original record key.

    The anchor is a positive source row number or a nonempty trimmed event key.
    The caller guarantees record identity; repeated event names need distinct
    original record keys. No global record-key index or new key/ID is generated.
    The state uses mm, m/s and absolute instrument us as defined by
    PhaseSpaceState. Its clock identity is verified once by the caller.
    """

    particle_id: int
    anchor: RecordAnchor
    state: PhaseSpaceState

    def __post_init__(self) -> None:
        _positive_integer(self.particle_id, "particle_id")
        _anchor(self.anchor)
        if not isinstance(self.state, PhaseSpaceState):
            raise ValueError("crossing sample requires a PhaseSpaceState")


@dataclass(frozen=True)
class CrossingBracket:
    """Validated version-1 interpolation evidence, not a second state table.

    plane_id resolves against the caller's supplied PlaneSurface mapping.
    occurrence is the one-based count of supported directed crossings after the
    time bound; it makes no claim about events inside unobserved/invalid gaps.
    Original anchors identify the two states. All bracket times use the same
    instrument clock in us. Alpha is in [0, 1], including recorded endpoints.
    Callers interpolate their existing fields and retain their original units.
    """

    particle_id: int
    plane_id: str
    occurrence: int
    lower_anchor: RecordAnchor
    upper_anchor: RecordAnchor
    bracket_start_us: float
    bracket_end_us: float
    bracket_gap_us: float
    interpolation_alpha: float
    schema_version: int = SCHEMA_VERSION
    method: str = METHOD

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION or self.method != METHOD:
            raise ValueError("unsupported crossing bracket schema or method")
        _positive_integer(self.particle_id, "particle_id")
        _identifier(self.plane_id, "plane_id")
        _positive_integer(self.occurrence, "occurrence")
        _anchor(self.lower_anchor)
        _anchor(self.upper_anchor)
        if self.lower_anchor == self.upper_anchor:
            raise ValueError("crossing bracket requires distinct original record anchors")
        start = _finite(self.bracket_start_us, "bracket_start_us")
        end = _finite(self.bracket_end_us, "bracket_end_us")
        gap = _finite(self.bracket_gap_us, "bracket_gap_us")
        alpha = _finite(self.interpolation_alpha, "interpolation_alpha")
        if gap <= 0 or gap != end - start:
            raise ValueError("crossing bracket gap must equal its positive endpoint time difference")
        if not 0 <= alpha <= 1:
            raise ValueError("crossing bracket alpha must be within [0, 1]; extrapolation is forbidden")


def _project(values: tuple[float, float, float], normal: tuple[float, float, float]) -> float:
    result = sum(value * direction for value, direction in zip(values, normal, strict=True))
    if not math.isfinite(result):
        raise ValueError("plane projection exceeds the finite numeric range")
    return result


def iter_bounded_plane_crossings(
    samples: Iterable[CrossingSample], *,
    particle_ids: Iterable[int],
    planes: Mapping[str, PlaneSurface],
    minimum_time_us: float,
    maximum_gap_us: float,
    gap_tolerance_us: float,
    occurrence: int | None = 1,
) -> Iterator[CrossingBracket]:
    """Select first, kth or all supported forward crossings without extrapolation.

    Plane normals define forward direction; reverse the normal for the opposite
    direction. Each bracket includes both plane endpoints and requires strictly
    positive normal velocity at BOTH states and nonzero forward displacement.
    Alpha is (q_plane-q_before)/(q_after-q_before), where q is position dotted
    with the unit normal; no spatial tolerance expands the accepted interval.

    States must be in strictly increasing instrument time for each particle;
    different particles may be interleaved. Samples before minimum_time_us are
    validated but do not anchor any bracket. Adjacent post-bound samples are
    used even after a rejected gap/direction; skipped segments are not bridged.
    Accepted gaps satisfy 0 < gap <= maximum_gap_us + gap_tolerance_us, with a
    finite positive maximum and an explicit finite nonnegative tolerance.

    A crossing at a shared recorded endpoint is counted once by its original
    anchor, not by a fuzzy time comparison. occurrence=1 selects the first,
    a positive integer selects that kth supported event, and None emits all.
    Results are yielded in source-bracket then declared-plane order, before the
    next sample is consumed. An adapter can therefore interpolate its original
    raw fields immediately, retaining only previous/current rows per particle.
    Missing requested occurrences emit nothing; callers retain the full cohort
    and assign their existing diagnostic missing statuses, never inferred loss.

    The caller guarantees one clock and original record identity. All samples
    must use the plane frame. Unknown/duplicate cohort IDs, frame mismatches,
    nonincreasing times and invalid parameters raise ValueError. This is a
    generator: validation happens on iteration, including after an earlier
    result, so consumers must exhaust it before accepting the complete result.
    There is no input mutation, tail filtering, clock reset or unit conversion.
    Memory is bounded by cohort/plane count, independent of trajectory length;
    only the caller's collection of all emitted events grows with event count.
    """
    minimum = _finite(minimum_time_us, "minimum_time_us")
    maximum = _finite(maximum_gap_us, "maximum_gap_us")
    tolerance = _finite(gap_tolerance_us, "gap_tolerance_us")
    if maximum <= 0 or tolerance < 0 or not math.isfinite(maximum + tolerance):
        raise ValueError("maximum gap must be positive and tolerance nonnegative, with a finite sum")
    if occurrence is not None:
        _positive_integer(occurrence, "occurrence")
    cohort = list(particle_ids)
    for pid in cohort:
        _positive_integer(pid, "cohort particle_id")
    if len(set(cohort)) != len(cohort):
        raise ValueError("duplicate cohort particle_id")
    if not isinstance(planes, Mapping) or not planes:
        raise ValueError("planes must be a nonempty mapping of plane IDs to PlaneSurface")
    declared = tuple(planes.items())
    for plane_id, plane in declared:
        _identifier(plane_id, "plane_id")
        if not isinstance(plane, PlaneSurface):
            raise ValueError("each plane must be a PlaneSurface")
    frames = {plane.frame_id for _, plane in declared}
    if len(frames) != 1:
        raise ValueError("all planes must share one frame")
    frame = next(iter(frames))
    projected_planes = {key: _project(plane.center_mm, plane.normal) for key, plane in declared}
    cohort_ids = set(cohort)
    previous: dict[int, CrossingSample] = {}
    last_time: dict[int, float] = {}
    counts: dict[tuple[int, str], int] = {}
    upper_endpoints: dict[tuple[int, str], tuple[RecordAnchor, float]] = {}
    for sample in samples:
        if not isinstance(sample, CrossingSample):
            raise ValueError("samples must contain CrossingSample values")
        pid, state = sample.particle_id, sample.state
        if pid not in cohort_ids:
            raise ValueError(f"unknown particle_id: {pid}")
        if state.frame_id != frame:
            raise ValueError(f"sample/plane frame mismatch for particle {pid}")
        time = state.instrument_time_us
        if pid in last_time and time <= last_time[pid]:
            raise ValueError(f"sample time not increasing for particle {pid}")
        last_time[pid] = time
        if time < minimum:
            continue
        before = previous.get(pid)
        previous[pid] = sample
        if before is None:
            continue
        start = before.state.instrument_time_us
        gap = time - start
        if not math.isfinite(gap):
            raise ValueError("sample time gap exceeds the finite numeric range")
        if gap > maximum + tolerance:
            continue
        for plane_id, plane in declared:
            q0 = _project(before.state.position_mm, plane.normal)
            q1 = _project(state.position_mm, plane.normal)
            qp = projected_planes[plane_id]
            if not q0 <= qp <= q1 or q0 == q1:
                continue
            if (_project(before.state.velocity_m_s, plane.normal) <= 0 or
                    _project(state.velocity_m_s, plane.normal) <= 0):
                continue
            key = pid, plane_id
            if q0 == qp and upper_endpoints.get(key) == (before.anchor, start):
                continue
            numerator, denominator = qp - q0, q1 - q0
            if not math.isfinite(numerator) or not math.isfinite(denominator):
                raise ValueError("crossing interpolation exceeds the finite numeric range")
            alpha = numerator / denominator
            counts[key] = counts.get(key, 0) + 1
            if q1 == qp:
                upper_endpoints[key] = sample.anchor, time
            else:
                upper_endpoints.pop(key, None)
            if occurrence is None or counts[key] == occurrence:
                yield CrossingBracket(
                    particle_id=pid, plane_id=plane_id, occurrence=counts[key],
                    lower_anchor=before.anchor, upper_anchor=sample.anchor,
                    bracket_start_us=start, bracket_end_us=time, bracket_gap_us=gap,
                    interpolation_alpha=alpha,
                )
