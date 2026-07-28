"""Characterize axial fringe-field harmonics for 3D RF-shield candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ORDERS = (2, 6, 10)
REQUIRED_COLUMNS = {
    "shield_inner_radius_mm",
    "mesh_hmax_mm",
    "sample_z_mm",
    "sample_radius_mm",
    "theta_rad",
    "potential_V",
    "Ex_V_per_m",
    "Ey_V_per_m",
    "Ez_V_per_m",
}


def harmonic_row(group: pd.DataFrame) -> dict[str, float]:
    ordered = group.sort_values("theta_rad")
    theta = ordered["theta_rad"].to_numpy(float)
    potential = ordered["potential_V"].to_numpy(float)
    if len(theta) < 16 or not np.all(np.diff(theta) > 0.0):
        raise ValueError("azimuth samples must be unique, ordered and sufficiently dense")
    row = {
        "shield_inner_radius_mm": float(ordered["shield_inner_radius_mm"].iloc[0]),
        "mesh_hmax_mm": float(ordered["mesh_hmax_mm"].iloc[0]),
        "sample_z_mm": float(ordered["sample_z_mm"].iloc[0]),
        "sample_radius_mm": float(ordered["sample_radius_mm"].iloc[0]),
    }
    for order in ORDERS:
        cosine = 2.0 * float(np.mean(potential * np.cos(order * theta)))
        sine = 2.0 * float(np.mean(potential * np.sin(order * theta)))
        row[f"order_{order}_cosine_V"] = cosine
        row[f"order_{order}_sine_V"] = sine
        row[f"order_{order}_amplitude_V"] = float(np.hypot(cosine, sine))
    main = row["order_2_amplitude_V"]
    row["order_6_relative_to_order_2"] = row["order_6_amplitude_V"] / main if main > 0.0 else np.nan
    row["order_10_relative_to_order_2"] = row["order_10_amplitude_V"] / main if main > 0.0 else np.nan
    transverse = np.hypot(
        ordered["Ex_V_per_m"].to_numpy(float), ordered["Ey_V_per_m"].to_numpy(float)
    )
    axial = ordered["Ez_V_per_m"].to_numpy(float)
    row["transverse_field_rms_V_per_m"] = float(np.sqrt(np.mean(np.square(transverse))))
    row["axial_field_rms_V_per_m"] = float(np.sqrt(np.mean(np.square(axial))))
    row["axial_to_transverse_rms"] = (
        row["axial_field_rms_V_per_m"] / row["transverse_field_rms_V_per_m"]
        if row["transverse_field_rms_V_per_m"] > 0.0
        else np.nan
    )
    return row


def characterize(samples: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(samples.columns)
    if missing:
        raise ValueError(f"shield 3D field table is missing columns: {sorted(missing)}")
    keys = ["shield_inner_radius_mm", "mesh_hmax_mm", "sample_z_mm", "sample_radius_mm"]
    rows = [harmonic_row(group) for _, group in samples.groupby(keys, sort=True)]
    return pd.DataFrame(rows).sort_values(keys).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    samples = pd.concat((pd.read_csv(path) for path in args.input), ignore_index=True)
    harmonics = characterize(samples)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    harmonics.to_csv(args.output_dir / "rf_continuous_shield_3d_harmonics.csv", index=False)
    report = {
        "schema_version": 1,
        "role": "rf_continuous_grounded_shield_3d_field_characterization",
        "status": "CHARACTERIZED",
        "shield_inner_radius_mm": sorted(harmonics["shield_inner_radius_mm"].unique().tolist()),
        "mesh_hmax_mm": sorted(harmonics["mesh_hmax_mm"].unique().tolist(), reverse=True),
        "sample_z_mm": sorted(harmonics["sample_z_mm"].unique().tolist()),
        "reported_orders": list(ORDERS),
        "selection_allowed": False,
        "n100_allowed": False,
        "claim_limit": "3D unit-field characterization only; convergence and functional budgets remain separate gates.",
    }
    (args.output_dir / "rf_continuous_shield_3d_metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("RF_CONTINUOUS_SHIELD_3D_ANALYSIS=PASS SELECTION_ALLOWED=false N100_ALLOWED=false")


if __name__ == "__main__":
    main()
