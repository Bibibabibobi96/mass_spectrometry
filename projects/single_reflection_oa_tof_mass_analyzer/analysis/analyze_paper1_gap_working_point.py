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
    bootstrap_resolution_difference,
    compute_peak_metrics,
)


def _hits(run_root: Path) -> pd.DataFrame:
    table = pd.read_csv(run_root / "results" / "single_flight_particle_checkpoints.csv")
    result = table.loc[table["event"].eq("detector_crossing")].copy()
    if result.empty or result["particle_id"].duplicated().any():
        raise ValueError(f"invalid detector-hit table: {run_root}")
    return result.sort_values("particle_id")


def _arm_metrics(run_root: Path, mother_count: int) -> dict[str, Any]:
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    hits = _hits(run_root)
    times = hits["instrument_time_us"].to_numpy(dtype=float)
    peak, _ = compute_peak_metrics(times, 100.0)
    quantiles = np.quantile(times, [0.05, 0.25, 0.5, 0.75, 0.95])
    census = {name: int(value) for name, value in summary["census"].items()}
    return {
        "run_id": run_root.name,
        "detector_hit_count": int(hits.shape[0]),
        "mother_count": int(mother_count),
        "detector_fraction_of_pre_pulse": float(hits.shape[0] / census["launched"]),
        "detector_fraction_of_mother": float(hits.shape[0] / mother_count),
        "peak": {
            key: peak[key]
            for key in (
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


def _comparison(inherited_root: Path, adjusted_root: Path, mother_count: int, seed: int) -> dict[str, Any]:
    inherited_hits = _hits(inherited_root)
    adjusted_hits = _hits(adjusted_root)
    inherited = _arm_metrics(inherited_root, mother_count)
    adjusted = _arm_metrics(adjusted_root, mother_count)
    inherited_ids = set(inherited_hits["particle_id"])
    adjusted_ids = set(adjusted_hits["particle_id"])
    if inherited_ids != adjusted_ids:
        raise ValueError("paired bootstrap requires identical detector-hit IDs for this experiment")
    bootstrap = bootstrap_resolution_difference(
        inherited_hits["instrument_time_us"].to_numpy(dtype=float),
        adjusted_hits["instrument_time_us"].to_numpy(dtype=float),
        100.0,
        resamples=1000,
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
    parser.add_argument("--inherited", type=Path, required=True)
    parser.add_argument("--adjusted", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "schema_version": 1,
        "role": "paper1_connector_gap_working_point_comparison",
        "scope": "frozen collisionless independent-particle RF source to OA-TOF simulation",
        "connector_gap_mm": args.gap_mm,
        "comparison": _comparison(args.inherited, args.adjusted, args.mother_count, args.seed),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PAPER1_GAP_WORKING_POINT_REPORT=PASS OUTPUT={args.output}")


if __name__ == "__main__":
    main()
