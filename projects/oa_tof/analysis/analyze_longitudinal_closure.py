"""Close the oa-TOF longitudinal field/mapping diagnosis from saved data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


KEY_COLUMNS = ["region", "sample_index", "x_mm", "y_mm", "z_mm"]


def analyze_axis_profiles(comsol_path: Path, simion_path: Path) -> dict[str, dict]:
    comsol = pd.read_csv(comsol_path)
    simion = pd.read_csv(simion_path)
    required_comsol = set(KEY_COLUMNS + ["potential_V", "Ez_V_per_m"])
    required_simion = set(KEY_COLUMNS + ["Ez_V_per_m"])
    if not required_comsol.issubset(comsol.columns):
        raise ValueError("COMSOL axis profile lacks required columns")
    if not required_simion.issubset(simion.columns):
        raise ValueError("SIMION axis profile lacks required columns")
    merged = comsol.merge(
        simion,
        on=KEY_COLUMNS,
        how="inner",
        validate="one_to_one",
        suffixes=("_COMSOL", "_SIMION"),
    )
    if len(merged) != len(comsol) or len(merged) != len(simion):
        raise ValueError("Axis profiles do not contain identical sample coordinates")

    result: dict[str, dict] = {}
    for region, frame in merged.groupby("region", sort=False):
        frame = frame.sort_values("z_mm")
        z_m = frame["z_mm"].to_numpy(dtype=float) * 1.0e-3
        comsol_ez = frame["Ez_V_per_m_COMSOL"].to_numpy(dtype=float)
        simion_ez = frame["Ez_V_per_m_SIMION"].to_numpy(dtype=float)
        potential = frame["potential_V"].to_numpy(dtype=float)
        if len(frame) < 5 or not np.all(np.diff(z_m) > 0):
            raise ValueError(f"Region {region!r} needs at least five increasing z samples")
        potential_gradient_ez = -np.gradient(potential, z_m, edge_order=2)
        interior = slice(2, -2)
        cross_solver_delta = simion_ez - comsol_ez
        interpolation_delta = potential_gradient_ez - comsol_ez
        cross_solver_rms = float(np.sqrt(np.mean(cross_solver_delta**2)))
        interpolation_rms = float(
            np.sqrt(np.mean(interpolation_delta[interior] ** 2))
        )
        result[str(region)] = {
            "samples": int(len(frame)),
            "z_min_mm": float(frame["z_mm"].iloc[0]),
            "z_max_mm": float(frame["z_mm"].iloc[-1]),
            "simion_minus_comsol_ez_mean_V_per_m": float(
                np.mean(cross_solver_delta)
            ),
            "simion_minus_comsol_ez_rms_V_per_m": cross_solver_rms,
            "simion_minus_comsol_ez_max_abs_V_per_m": float(
                np.max(np.abs(cross_solver_delta))
            ),
            "integrated_ez_COMSOL_V": float(np.trapezoid(comsol_ez, z_m)),
            "integrated_ez_SIMION_V": float(np.trapezoid(simion_ez, z_m)),
            "integrated_ez_SIMION_minus_COMSOL_V": float(
                np.trapezoid(cross_solver_delta, z_m)
            ),
            "comsol_endpoint_potential_drop_V": float(
                potential[0] - potential[-1]
            ),
            "comsol_potential_gradient_minus_direct_ez_rms_V_per_m": (
                interpolation_rms
            ),
            "comsol_gradient_rms_fraction_of_cross_solver_rms": float(
                interpolation_rms / cross_solver_rms
            ),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comsol-axis", type=Path, required=True)
    parser.add_argument("--simion-axis", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
    mapping = comparison["comparison"]["paired_tof_difference"]["source_mapping"]
    axis = analyze_axis_profiles(args.comsol_axis, args.simion_axis)
    source = axis["accelerator_source"]
    result = {
        "schema_version": 1,
        "status": "PASS",
        "axis_profiles": axis,
        "paired_tof_difference_source_mapping": mapping,
        "closure": {
            "source_comsol_gradient_rms_fraction_of_cross_solver_rms": source[
                "comsol_gradient_rms_fraction_of_cross_solver_rms"
            ],
            "tof_delta_variance_explained_by_z_quadratic": mapping[
                "z_quadratic_r_squared"
            ],
            "tof_delta_full_minus_z_quadratic_r_squared": (
                mapping["z2_energy_xy_r_squared"] - mapping["z_quadratic_r_squared"]
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"LONGITUDINAL_CLOSURE=PASS OUTPUT={args.output}")


if __name__ == "__main__":
    main()
