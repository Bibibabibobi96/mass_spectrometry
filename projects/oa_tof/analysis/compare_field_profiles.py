"""Compare solver-exported oa-TOF axis electric-field profiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "config" / "resolved_geometry.json"


def region_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    comsol = frame["COMSOL_Ez_V_per_m"].to_numpy()
    simion = frame["SIMION_Ez_V_per_m"].to_numpy()
    difference = simion - comsol
    nonzero = np.abs(comsol) > 100.0
    relative = 100.0 * difference[nonzero] / comsol[nonzero]
    return {
        "points": int(len(frame)),
        "comsol_mean_Ez_V_per_m": float(np.mean(comsol)),
        "simion_mean_Ez_V_per_m": float(np.mean(simion)),
        "mean_difference_V_per_m": float(np.mean(difference)),
        "rms_difference_V_per_m": float(np.sqrt(np.mean(difference**2))),
        "maximum_absolute_difference_V_per_m": float(np.max(np.abs(difference))),
        "relative_difference_mean_pct": float(np.mean(relative)),
        "relative_difference_rms_pct": float(np.sqrt(np.mean(relative**2))),
        "relative_difference_min_pct": float(np.min(relative)),
        "relative_difference_max_pct": float(np.max(relative)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("comsol", type=Path)
    parser.add_argument("simion", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    geometry = contract["geometry_mm"]

    comsol = pd.read_csv(args.comsol)
    simion = pd.read_csv(args.simion)
    required = {"region", "sample_index", "x_mm", "y_mm", "z_mm", "Ez_V_per_m"}
    for label, frame in (("COMSOL", comsol), ("SIMION", simion)):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{label} field CSV misses columns: {sorted(missing)}")
    merged = comsol.merge(
        simion,
        on=["region", "sample_index"],
        suffixes=("_COMSOL", "_SIMION"),
        validate="one_to_one",
    )
    for coordinate in ("x_mm", "y_mm", "z_mm"):
        error = np.max(
            np.abs(
                merged[f"{coordinate}_COMSOL"].to_numpy()
                - merged[f"{coordinate}_SIMION"].to_numpy()
            )
        )
        if error > 1.0e-8:
            raise ValueError(f"Field sample {coordinate} mismatch: {error} mm")
    merged = merged.rename(
        columns={
            "x_mm_COMSOL": "x_mm",
            "y_mm_COMSOL": "y_mm",
            "z_mm_COMSOL": "z_mm",
            "Ez_V_per_m_COMSOL": "COMSOL_Ez_V_per_m",
            "Ez_V_per_m_SIMION": "SIMION_Ez_V_per_m",
        }
    )
    merged["SIMION_minus_COMSOL_Ez_V_per_m"] = (
        merged["SIMION_Ez_V_per_m"] - merged["COMSOL_Ez_V_per_m"]
    )
    merged["relative_difference_pct"] = 100.0 * (
        merged["SIMION_minus_COMSOL_Ez_V_per_m"] / merged["COMSOL_Ez_V_per_m"]
    )

    metrics = {
        region: region_metrics(frame)
        for region, frame in merged.groupby("region", sort=False)
    }
    source = merged[merged["region"] == "accelerator_source"]
    accelerator = merged[merged["region"] == "accelerator_full"]
    reflectron = merged[merged["region"] == "reflectron"]
    reflectron_boundaries_mm = np.asarray(
        [
            geometry["L_flight"],
            geometry["L_flight"] + geometry["L_stage1"],
            geometry["L_flight"] + geometry["L_reflectron"],
        ]
    )
    boundary_distance = np.min(
        np.abs(
            reflectron["z_mm"].to_numpy()[:, None]
            - reflectron_boundaries_mm[None, :]
        ),
        axis=1,
    )
    reflectron_interior = reflectron[boundary_distance > 0.30]
    metrics["reflectron_interior"] = region_metrics(reflectron_interior)
    metrics["reflectron_interior"]["excluded_boundary_distance_mm"] = 0.30

    figure, axes = plt.subplots(2, 2, figsize=(13.5, 8.5), constrained_layout=True)
    for label in ("COMSOL", "SIMION"):
        axes[0, 0].plot(
            source["z_mm"], source[f"{label}_Ez_V_per_m"] / 1.0e3, label=label
        )
    axes[0, 0].set(
        xlabel="Source z [mm]", ylabel="Ez [V/mm]", title="Release-region axis field"
    )
    axes[0, 0].legend()

    axes[0, 1].plot(source["z_mm"], source["relative_difference_pct"], color="black")
    axes[0, 1].axhline(0, color="0.5", linestyle="--")
    axes[0, 1].set(
        xlabel="Source z [mm]",
        ylabel="(SIMION-COMSOL)/COMSOL [%]",
        title="Release-region solver difference",
    )

    for label in ("COMSOL", "SIMION"):
        axes[1, 0].plot(
            accelerator["z_mm"],
            accelerator[f"{label}_Ez_V_per_m"] / 1.0e3,
            label=label,
        )
        axes[1, 1].plot(
            reflectron["z_mm"],
            reflectron[f"{label}_Ez_V_per_m"] / 1.0e3,
            label=label,
        )
    axes[1, 0].set(
        xlabel="Accelerator z [mm]", ylabel="Ez [V/mm]", title="Accelerator axis field"
    )
    axes[1, 1].set(
        xlabel="Reflectron z [mm]", ylabel="Ez [V/mm]", title="Reflectron axis field"
    )
    for axis in axes.flat:
        axis.grid(True, alpha=0.3)
    axes[1, 0].legend()
    axes[1, 1].legend()

    args.output.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output / "axis_field_comparison.csv", index=False)
    (args.output / "axis_field_metrics.json").write_text(
        json.dumps({"status": "PASS", "regions": metrics}, indent=2), encoding="utf-8"
    )
    figure.savefig(args.output / "axis_field_comparison.png", dpi=220, facecolor="white")
    plt.close(figure)
    print("FIELD_PROFILE_COMPARISON_STATUS=PASS")


if __name__ == "__main__":
    main()
