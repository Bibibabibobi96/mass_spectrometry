"""Shared detector-blind occupancy scoring; no geometry compiler or file I/O."""
from __future__ import annotations

import math
from typing import Any

from msplatform.contracts.machine_contracts import ContractError
from msplatform.contracts.particle_state import binary64_serialization_close as _close


SELECTION_ORDER = [
    "maximize_pulse_eligible_count",
    "minimize_normalized_xyz_spread_norm",
    "minimize_normalized_xyz_centroid_distance",
    "select_earlier_time",
]


def _pulse_candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, ...]:
    return (
        -int(candidate["pulse_eligible_count"]),
        float(candidate["normalized_xyz_spread_norm"]),
        float(candidate["normalized_xyz_centroid_distance"]),
        float(candidate["candidate_time_us"]),
    )


def pulse_candidate_concentration(
    centered_means_mm: dict[str, float], population_sigmas_mm: dict[str, float],
    normalization_bounds: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Normalize observed moments using declared geometry, including rectangles.

    Callers retain their established moment accumulator: this helper neither
    changes streaming summation nor infers eligibility or drops particles.
    """
    centroid, spread = {}, {}
    for axis in "xyz":
        half = float(normalization_bounds[axis]["full_width_mm"]) / 2.0
        mean, sigma = float(centered_means_mm[axis]), float(population_sigmas_mm[axis])
        if not all(math.isfinite(v) for v in (half, mean, sigma)) or half <= 0 or sigma < 0:
            raise ContractError("pulse concentration requires finite moments and positive geometry widths")
        centroid[axis], spread[axis] = mean / half, sigma / half
    return {
        "normalized_xyz_centroid": centroid,
        "normalized_xyz_centroid_distance": math.sqrt(sum(v * v for v in centroid.values())),
        "normalized_xyz_spread": spread,
        "normalized_xyz_spread_norm": math.sqrt(sum(v * v for v in spread.values())),
    }



def select_actual_occupancy_pulse(
    observations_by_time: dict[float, list[dict]], census_by_time: dict[float, list[dict]],
    candidate_times_us: list[float], capture_bounds: dict, *, frame_id: str,
) -> dict:
    """Rank recorded live occupancy; no detector outcome or trajectory interpolation.

    Column-wise NumPy mean and population SD retain the established local
    checkpoint accumulator and observation order, including binary64 ties.
    """
    import numpy as np

    candidates = []
    for time in candidate_times_us:
        life = census_by_time[time]
        unsupported = [r["particle_id"] for r in life if r["status"] == "numerical_unsupported"]
        active_ids = {r["particle_id"] for r in life if r["status"] == "active"}
        rows = [r for r in observations_by_time[time] if r["particle_id"] in active_ids]
        eligible = [r for r in rows if all(
            capture_bounds[a]["minimum_mm"] < r[f"{a}_mm"] < capture_bounds[a]["maximum_mm"] for a in "xyz")]
        candidate = dict(candidate_time_us=time, pulse_eligible_count=len(eligible),
                         eligible_ids=[r["particle_id"] for r in eligible],
                         unsupported_ids=unsupported, rankable=not unsupported and bool(eligible))
        if candidate["rankable"]:
            columns = {a: np.asarray([row[f"{a}_mm"] for row in eligible], dtype=float) for a in "xyz"}
            candidate.update(pulse_candidate_concentration(
                {a: float(np.mean(columns[a])) - capture_bounds[a]["center_mm"] for a in "xyz"},
                {a: float(np.std(columns[a], ddof=0)) for a in "xyz"}, capture_bounds))
        candidates.append(candidate)
    ranked = sorted((c for c in candidates if c["rankable"]), key=_pulse_candidate_sort_key)
    return dict(status="selected" if ranked else "no_supported_eligible_candidate",
                selected_time_us=ranked[0]["candidate_time_us"] if ranked else None,
                selection_order=SELECTION_ORDER, selected=ranked[0] if ranked else None,
                candidates=candidates, capture_bounds_native_mm=capture_bounds, native_frame_id=frame_id,
                selection_uses_future_terminal_outcome=False)


# Historical native checkpoint decisions remain detector-blind analysis.
ROLE = "single_reflection_actual_occupancy_pulse_decision"
_STATE = ("x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us")


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _capture_bounds(geometry: dict) -> dict:
    """Use the actual square OA bore and repeller/grid1 planes in assembly axes."""
    g = geometry["accelerator_projection"]
    width = g["bore_width_mm"]
    planes = (g["repeller_front_z_mm"], g["grid1_z_mm"])
    if (not _finite(width) or width <= 0 or any(not _finite(v) for v in planes)
            or planes[0] >= planes[1]):
        raise ValueError("actual OA first-gap geometry is invalid")
    bounds = {}
    for axis, low, high in (
        ("x", g["axis_x_mm"]-width/2, g["axis_x_mm"]+width/2),
        ("y", g["axis_y_mm"]-width/2, g["axis_y_mm"]+width/2),
        ("z", *planes),
    ):
        if not all(_finite(value) for value in (low, high)):
            raise ValueError("actual OA first-gap bounds are nonfinite")
        bounds[axis] = dict(minimum_mm=low, maximum_mm=high, center_mm=(low+high)/2,
                            full_width_mm=high-low)
    return bounds


def select_discovery_pulse(
    *, births_us: dict[int, float], snapshots: list[dict],
    terminal_times_us: dict[int, float], candidate_times_us: list[float],
    frontend_geometry: dict, pulse_width_us: float, input_records: dict,
) -> dict:
    """Use only actual births, snapshots, lifetime endpoints and first-gap geometry.

    Terminal times establish whether each original particle is alive at a
    candidate; causes, detector results and later positions are not inputs.
    No supported candidate is a retained negative decision, never a fake pulse.
    The managed caller verifies the three small input records before this API.
    """
    if set(input_records) != {"collection", "request", "frontend_geometry"}:
        raise ValueError("decision requires collection/request/frontend_geometry records")
    if not _finite(pulse_width_us) or pulse_width_us <= 0:
        raise ValueError("positive finite pulse width required")
    if (not candidate_times_us or any(not _finite(t) for t in candidate_times_us)
            or candidate_times_us != sorted(set(candidate_times_us))):
        raise ValueError("candidate times must be finite and strictly increasing")
    if (not births_us or any(type(pid) is not int or pid <= 0 for pid in births_us)
            or set(terminal_times_us) != set(births_us)):
        raise ValueError("actual birth/terminal lifetimes must cover the complete execution cohort")
    for pid, birth in births_us.items():
        end = terminal_times_us[pid]
        if (not _finite(birth) or not _finite(end)
                or (end < birth and not _close(end, birth))):
            raise ValueError(f"particle {pid}: invalid actual lifetime")
    observations = {time: [] for time in candidate_times_us}
    by_id_time = {}
    for row in snapshots:
        pid, target, actual = row["particle_id"], row["candidate_time_us"], row["instrument_time_us"]
        if type(pid) is not int or pid not in births_us or not _finite(target) or target not in observations:
            raise ValueError("snapshot ID or candidate is outside frozen execution cohort/plan")
        if ((pid, target) in by_id_time or not _finite(actual)
                or any(not _finite(row[field]) for field in _STATE)):
            raise ValueError("duplicate or nonfinite actual snapshot")
        if not _close(actual, target):
            raise ValueError("candidate snapshot lacks actual native time support; interpolation is forbidden")
        birth, end = births_us[pid], terminal_times_us[pid]
        if ((actual < birth and not _close(actual, birth))
                or (actual > end and not _close(actual, end))):
            raise ValueError(f"particle {pid}: snapshot outside actual lifetime")
        by_id_time[pid, target] = row
        observations[target].append(row)
    census, counts = {}, []
    for time in candidate_times_us:
        rows = []
        tally = dict(candidate_time_us=time, execution_cohort_count=len(births_us), not_born=0,
                     active=0, already_terminal=0, numerical_unsupported=0)
        for pid, birth in births_us.items():
            end = terminal_times_us[pid]
            if time < birth and not _close(time, birth):
                status = "not_born"
            elif time >= end or _close(time, end):
                status = "already_terminal"
            elif (pid, time) not in by_id_time:
                status = "numerical_unsupported"
            else:
                status = "active"
            tally[status] += 1
            rows.append(dict(particle_id=pid, instrument_time_us=time, status=status))
        census[time] = rows
        counts.append(tally)
    selection = select_actual_occupancy_pulse(
        observations, census, candidate_times_us, _capture_bounds(frontend_geometry),
        frame_id=frontend_geometry["composition_plan"]["assembly_frame_id"])
    selection["execution_cohort_count"] = len(births_us)
    selection["candidate_status_counts"] = counts
    success = selection["status"] == "selected"
    decision = dict(schema_version=2, role=ROLE,
        status="success" if success else "no_supported_candidate",
        input_records=dict(input_records), candidate_times_us=list(candidate_times_us),
        pulse_width_us=pulse_width_us, selection=selection,
        selection_uses_future_terminal_outcome=False)
    if success:
        decision["actual_pulse_time_us"] = selection["selected_time_us"]
    return decision
