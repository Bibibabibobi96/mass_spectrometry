"""Compare old and coupled longitudinal theories with paired particle results.

The old reference keeps the accelerator transit time fixed at the nominal
source position and applies energy dependence only to the reflectron.  The
coupled reference includes the source-position-dependent accelerator transit
in the complete release-to-detector time.  Both predictions use the exact
same particle ``Z0Mm`` values and the same baseline fields.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]

from projects.oa_tof.analysis.accelerator_time_focus import accelerator_state
from projects.oa_tof.analysis.oatof_oaaccelerator_coupling import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
    accelerator_normalized_time_to_focus,
    coupled_flight_time_s,
)
from projects.oa_tof.analysis.reflectron_dual_stage_solver import (
    normalized_flight_time_mm_sqrt_v,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_particle_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"particle CSV is empty: {path}")
    return (
        np.asarray([float(row["Z0Mm"]) for row in rows], dtype=float),
        np.asarray([float(row["TofUs"]) for row in rows], dtype=float),
    )


def predict_times_us(
    baseline: dict[str, Any], mass_to_charge_th: float, source_z_mm: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return energy, old-theory TOF and coupled-theory TOF arrays."""

    geometry = baseline["geometry_mm"]
    derivation = baseline["geometry_derivation"]
    voltage = baseline["electrodes_V"]
    accelerator_design = derivation["accelerator"]
    accelerator = accelerator_state(
        float(voltage["repeller"]),
        float(voltage["grid1"]),
        float(accelerator_design["d1_mm"]),
        float(accelerator_design["d2_mm"]),
    )
    local_release_mm = source_z_mm - float(geometry["accelerator_repeller_z"])
    energy_v = (
        accelerator.repeller_relative_v
        - accelerator.field1_v_per_mm * local_release_mm
    )
    stage1_length = float(geometry["L_stage1"])
    stage2_length = float(geometry["L_stage2"])
    stage1_drop = float(voltage["midgrid"] - voltage["entgrid"])
    stage1_field = stage1_drop / stage1_length
    stage2_field = float(voltage["backplate"] - voltage["midgrid"]) / stage2_length
    upstream = float(geometry["L_flight"] - geometry["accelerator_focus_z"])
    downstream = float(geometry["L_flight"] - geometry["detector_z"])

    coupled_us = np.asarray(
        [
            1.0e6
            * coupled_flight_time_s(
                energy,
                mass_to_charge_th,
                accelerator,
                upstream,
                downstream,
                stage1_drop,
                stage1_field,
                stage2_field,
            )
            for energy in energy_v
        ],
        dtype=float,
    )

    nominal_energy = accelerator.nominal_energy_per_charge_v
    nominal_accelerator_time = accelerator_normalized_time_to_focus(
        nominal_energy, accelerator
    )
    scale = 1.0e3 * math.sqrt(
        (mass_to_charge_th * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C) / 2.0
    )
    old_us = np.asarray(
        [
            scale
            * (
                nominal_accelerator_time
                + normalized_flight_time_mm_sqrt_v(
                    energy,
                    upstream + downstream,
                    stage1_drop,
                    stage1_field,
                    stage2_field,
                )
            )
            for energy in energy_v
        ],
        dtype=float,
    )
    return energy_v, old_us, coupled_us


def comparison_metrics(actual_us: np.ndarray, predicted_us: np.ndarray) -> dict[str, float]:
    error_us = actual_us - predicted_us
    actual_centered = actual_us - np.mean(actual_us)
    predicted_centered = predicted_us - np.mean(predicted_us)
    correlation = float(np.corrcoef(actual_us, predicted_us)[0, 1])
    slope, intercept = np.polyfit(predicted_us, actual_us, 1)
    calibrated_residual = actual_us - (intercept + slope * predicted_us)
    return {
        "actual_mean_us": float(np.mean(actual_us)),
        "predicted_mean_us": float(np.mean(predicted_us)),
        "bias_actual_minus_prediction_ns": float(np.mean(error_us) * 1.0e3),
        "absolute_rmse_ns": float(np.sqrt(np.mean(error_us**2)) * 1.0e3),
        "maximum_absolute_error_ns": float(np.max(np.abs(error_us)) * 1.0e3),
        "actual_sample_std_ns": float(np.std(actual_us, ddof=1) * 1.0e3),
        "predicted_sample_std_ns": float(np.std(predicted_us, ddof=1) * 1.0e3),
        "centered_rmse_ns": float(
            np.sqrt(np.mean((actual_centered - predicted_centered) ** 2)) * 1.0e3
        ),
        "particlewise_correlation": correlation,
        "best_fit_slope": float(slope),
        "best_fit_residual_std_ns": float(
            np.std(calibrated_residual, ddof=1) * 1.0e3
        ),
        "actual_min_us": float(np.min(actual_us)),
        "actual_max_us": float(np.max(actual_us)),
        "predicted_min_us": float(np.min(predicted_us)),
        "predicted_max_us": float(np.max(predicted_us)),
    }


def compare_dataset(
    baseline: dict[str, Any], mass_to_charge_th: float, path: Path
) -> dict[str, Any]:
    source_z, actual = _load_particle_csv(path)
    energy, old, coupled = predict_times_us(baseline, mass_to_charge_th, source_z)
    old_metrics = comparison_metrics(actual, old)
    coupled_metrics = comparison_metrics(actual, coupled)
    return {
        "particle_csv": str(path.resolve()),
        "particle_csv_sha256": _sha256(path),
        "particle_count": int(actual.size),
        "source_correlated_energy_range_V": [float(np.min(energy)), float(np.max(energy))],
        "old_reflectron_local_theory": old_metrics,
        "new_coupled_release_to_detector_theory": coupled_metrics,
        "new_vs_old_improvement_percent": {
            "absolute_rmse": 100.0
            * (1.0 - coupled_metrics["absolute_rmse_ns"] / old_metrics["absolute_rmse_ns"]),
            "centered_rmse": 100.0
            * (1.0 - coupled_metrics["centered_rmse_ns"] / old_metrics["centered_rmse_ns"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=PROJECT_ROOT / "config" / "baseline.json")
    parser.add_argument("--mass-to-charge-th", type=float, default=524.0)
    parser.add_argument("--comsol-csv", type=Path, required=True)
    parser.add_argument("--simion-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    report = {
        "schema_version": 1,
        "role": "oa_tof_longitudinal_theory_particlewise_validation",
        "baseline": str(args.baseline.resolve()),
        "baseline_sha256": _sha256(args.baseline),
        "mass_to_charge_Th": args.mass_to_charge_th,
        "old_theory_definition": (
            "nominal constant accelerator transit plus energy-dependent local "
            "dual-stage-reflectron time"
        ),
        "new_theory_definition": (
            "source-correlated accelerator transit plus dual-stage-reflectron "
            "time from release to detector"
        ),
        "datasets": {
            "comsol": compare_dataset(
                baseline, args.mass_to_charge_th, args.comsol_csv
            ),
            "simion": compare_dataset(
                baseline, args.mass_to_charge_th, args.simion_csv
            ),
        },
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
