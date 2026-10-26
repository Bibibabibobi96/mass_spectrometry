"""Shared detector-blind occupancy scoring; no geometry compiler or file I/O."""
from __future__ import annotations

import math
from typing import Any

from common.contracts.machine_contracts import ContractError


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
