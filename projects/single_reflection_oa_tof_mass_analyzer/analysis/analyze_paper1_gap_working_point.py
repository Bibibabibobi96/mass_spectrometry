"""Report the frozen-source connector-gap working-point mechanism experiment.

Peak metrics are always calculated from every detector hit in each arm.  ID
pairing is used only for the bootstrap uncertainty calculation; it is never a
filter for either arm's peak width or transmission denominator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common.analysis.peak_metrics import (
    AnalysisSettings,
    _bootstrap_resolution_batch,
    compute_peak_metrics,
)

RESOLUTION_TIME_BASIS = "detector_time_minus_pulse_effective_time"


def _hits(run_root: Path) -> pd.DataFrame:
    """Load all hits and verify their canonical pulse-relative clock in us."""

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    if summary.get("resolution_time_basis") != RESOLUTION_TIME_BASIS:
        raise ValueError(f"missing or unsupported resolution time basis: {run_root}")
    if summary.get("clock_basis") != "canonical_instrument_time_us":
        raise ValueError(f"missing or unsupported instrument clock basis: {run_root}")
    pulse = summary.get("pulse_effective_time_us")
    if pulse is None or not np.isfinite(float(pulse)):
        raise ValueError(f"missing or nonfinite effective pulse time: {run_root}")
    table = pd.read_csv(run_root / "results" / "single_flight_particle_checkpoints.csv")
    required = {"event", "particle_id", "instrument_time_us", "pulse_effective_elapsed_us"}
    if not required.issubset(table.columns):
        raise ValueError(f"missing detector clock or identity columns: {run_root}")
    result = table.loc[table["event"].eq("detector_crossing")].copy()
    if result.empty or result["particle_id"].isna().any() or result["particle_id"].duplicated().any():
        raise ValueError(f"invalid detector-hit table: {run_root}")
    instrument = result["instrument_time_us"].to_numpy(dtype=float)
    elapsed = result["pulse_effective_elapsed_us"].to_numpy(dtype=float)
    if not np.all(np.isfinite(instrument)) or not np.all(np.isfinite(elapsed)) or np.any(elapsed <= 0):
        raise ValueError(f"nonfinite or nonpositive detector clock: {run_root}")
    # Both columns are canonical derived values; only floating-point arithmetic
    # and text roundoff are allowed, not a physical time shift or a second epoch.
    scale = np.maximum.reduce([np.abs(instrument), np.abs(elapsed), np.full(elapsed.shape, abs(float(pulse)))])
    tolerance = 8 * np.finfo(float).eps * np.maximum(scale, 1.0)
    if np.any(np.abs(instrument - float(pulse) - elapsed) > tolerance):
        raise ValueError(f"pulse-relative detector clock contradicts instrument epoch: {run_root}")
    return result.sort_values("particle_id")


def _arm_metrics(run_root: Path, mother_count: int) -> dict[str, Any]:
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    hits = _hits(run_root)
    times = hits["pulse_effective_elapsed_us"].to_numpy(dtype=float)
    peak, _ = compute_peak_metrics(times, 100.0)
    quantiles = np.quantile(times, [0.05, 0.25, 0.5, 0.75, 0.95])
    census = {name: int(value) for name, value in summary["census"].items()}
    return {
        "run_id": run_root.name,
        "resolution_time_basis": RESOLUTION_TIME_BASIS,
        "pulse_effective_time_us": float(summary["pulse_effective_time_us"]),
        "instrument_clock_peak_is_resolution_claim": False,
        "detector_hit_count": int(hits.shape[0]),
        "mother_count": int(mother_count),
        "detector_fraction_of_pre_pulse": float(hits.shape[0] / census["launched"]),
        "detector_fraction_of_mother": float(hits.shape[0] / mother_count),
        "peak": {
            key: peak[key]
            for key in (
                "mean_tof_us",
                "direct_fwhm_tof_ns",
                "mass_resolution",
                "direct_fwhm_mass_Da",
                "significant_kde_modes",
                "tail_fraction_outside_3sigma",
                "tof_skewness",
                "tof_excess_kurtosis",
            )
        },
        "quantile_width_ns": {
            "p05_p95": float((quantiles[4] - quantiles[0]) * 1.0e3),
            "p25_p75": float((quantiles[3] - quantiles[1]) * 1.0e3),
        },
        "census": census,
        "loss_counts_from_pre_pulse": {
            "accelerator_grid1_or_before": census["launched"] - census["accelerator_grid1_forward"],
            "accelerator_interior": census["accelerator_grid1_forward"] - census["local_accelerator_exit"],
            "after_accelerator_before_detector": census["local_accelerator_exit"] - census["detector_crossing"],
        },
        "loss_counts_from_mother": {
            "before_pre_pulse_release": int(mother_count - census["launched"]),
            "accelerator_grid1_or_before": census["launched"] - census["accelerator_grid1_forward"],
            "accelerator_interior": census["accelerator_grid1_forward"] - census["local_accelerator_exit"],
            "after_accelerator_before_detector": census["local_accelerator_exit"] - census["detector_crossing"],
        },
    }


def _paired_resolution_gain(
    inherited_times: np.ndarray, adjusted_times: np.ndarray, *, seed: int, resamples: int,
) -> dict[str, Any]:
    """Return signed paired R gains using the unchanged canonical KDE kernel.

    Inputs are positive pulse-relative times (us), already sorted by particle ID.
    Unlike the cross-solver absolute-difference diagnostic, the denominator is
    the inherited arm and negative values retain deterioration.
    """

    if resamples <= 0 or inherited_times.size != adjusted_times.size:
        raise ValueError("paired gain requires positive resamples and equal populations")
    rng = np.random.default_rng(seed)
    settings = AnalysisSettings()
    gains = np.full(resamples, np.nan)
    differences = np.full(resamples, np.nan)
    # Reuse the common vectorized FWHM implementation without changing its
    # cross-solver API or allocating all bootstrap KDE grids at once.
    for start in range(0, resamples, 16):
        stop = min(start + 16, resamples)
        indices = rng.integers(0, inherited_times.size, size=(stop - start, inherited_times.size))
        inherited = _bootstrap_resolution_batch(inherited_times[indices], 100.0, settings)
        adjusted = _bootstrap_resolution_batch(adjusted_times[indices], 100.0, settings)
        gains[start:stop] = 100.0 * (adjusted / inherited - 1.0)
        differences[start:stop] = adjusted - inherited
    valid = np.isfinite(gains) & np.isfinite(differences)
    # Same finite-replicate rule as both common KDE bootstrap entry points.
    if np.count_nonzero(valid) < 0.95 * resamples:
        raise ValueError("fewer than 95 percent of paired bootstrap replicates are finite")
    return {
        "method": "paired particle-ID bootstrap using canonical direct KDE FWHM",
        "resolution_time_basis": RESOLUTION_TIME_BASIS,
        "quantity": "100 * (R_adjusted / R_inherited - 1)",
        "denominator": "inherited_working_point_resolution",
        "seed": seed,
        "resamples_requested": resamples,
        "resamples_valid": int(np.count_nonzero(valid)),
        "resamples_invalid": int(resamples - np.count_nonzero(valid)),
        "resolution_change_pct": dict(zip(
            ("lower_95", "median", "upper_95"), np.percentile(gains[valid], [2.5, 50, 97.5]).tolist(),
        )),
        "resolution_difference": dict(zip(
            ("lower_95", "median", "upper_95"), np.percentile(differences[valid], [2.5, 50, 97.5]).tolist(),
        )),
    }


def _comparison(
    inherited_root: Path, adjusted_root: Path, mother_count: int, seed: int, resamples: int = 1000,
) -> dict[str, Any]:
    inherited_hits = _hits(inherited_root)
    adjusted_hits = _hits(adjusted_root)
    inherited = _arm_metrics(inherited_root, mother_count)
    adjusted = _arm_metrics(adjusted_root, mother_count)
    inherited_ids = set(inherited_hits["particle_id"])
    adjusted_ids = set(adjusted_hits["particle_id"])
    if inherited_ids != adjusted_ids:
        raise ValueError("paired bootstrap requires identical detector-hit IDs for this experiment")
    bootstrap = _paired_resolution_gain(
        inherited_hits["pulse_effective_elapsed_us"].to_numpy(dtype=float),
        adjusted_hits["pulse_effective_elapsed_us"].to_numpy(dtype=float),
        resamples=resamples,
        seed=seed,
    )
    direction = (
        "adjusted_higher_resolution"
        if adjusted["peak"]["mass_resolution"] > inherited["peak"]["mass_resolution"]
        else "adjusted_lower_resolution"
    )
    return {
        "full_hit_metric_policy": "each arm uses all of its own detector hits; no common-hit peak-width filter",
        "paired_bootstrap_population": "all detector hits, whose ID sets are identical in this comparison",
        "paired_detector_id_sets_identical": True,
        "paired_detector_id_count": len(inherited_ids),
        "inherited": inherited,
        "source_z_vz_adjusted": adjusted,
        "resolution_direction": direction,
        "resolution_change_pct": float(
            100.0
            * (adjusted["peak"]["mass_resolution"] / inherited["peak"]["mass_resolution"] - 1.0)
        ),
        "paired_bootstrap": bootstrap,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gap-mm", type=float, required=True)
    parser.add_argument("--mother-count", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--inherited", type=Path, required=True)
    parser.add_argument("--adjusted", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"report already exists; publish a new analysis run: {args.output}")
    report = {
        "schema_version": 2,
        "role": "paper1_connector_gap_working_point_comparison",
        "scope": "frozen collisionless independent-particle RF source to OA-TOF simulation",
        "connector_gap_mm": args.gap_mm,
        "resolution_time_basis": RESOLUTION_TIME_BASIS,
        "comparison": _comparison(args.inherited, args.adjusted, args.mother_count, args.seed, args.resamples),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PAPER1_GAP_WORKING_POINT_REPORT=PASS OUTPUT={args.output}")


if __name__ == "__main__":
    main()
