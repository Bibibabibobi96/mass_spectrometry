"""Analyze local COMSOL accelerator mesh convergence against fixed samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from projects.oa_tof.analysis.field_comparison_contract import (
    convergence_decision,
    merge_complete_samples,
)


KEYS = ["particle_id", "time_us", "x_mm", "y_mm", "z_mm"]
COMPONENTS = ("Ex", "Ey", "Ez")


def _component_metrics(reference: np.ndarray, values: np.ndarray) -> dict[str, float]:
    delta = values - reference
    return {
        "field_rms_V_per_m": float(np.sqrt(np.mean(values**2))),
        "difference_rms_V_per_m": float(np.sqrt(np.mean(delta**2))),
        "difference_mean_V_per_m": float(np.mean(delta)),
        "difference_max_abs_V_per_m": float(np.max(np.abs(delta))),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("formal", type=Path)
    parser.add_argument("mesh_scan", type=Path, nargs="+")
    parser.add_argument("simion", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    formal = pd.read_csv(args.formal)
    formal.insert(0, "variant", "formal_original")
    formal.insert(1, "hmax_mm", np.nan)
    scan = pd.concat([pd.read_csv(path) for path in args.mesh_scan], ignore_index=True)
    simion = pd.read_csv(args.simion)
    variants = pd.concat([formal, scan], ignore_index=True, sort=False)
    order = ["formal_original"] + list(dict.fromkeys(scan["variant"].astype(str)))

    metrics: dict[str, object] = {
        "status": "ANALYSIS_COMPLETE",
        "convergence_decision": convergence_decision(),
        "variant_order": order,
        "against_simion": {},
        "successive_comsol_change": {},
    }
    merged_by_variant: dict[str, pd.DataFrame] = {}
    for variant in order:
        frame = variants[variants["variant"] == variant]
        merged = merge_complete_samples(
            frame,
            simion,
            keys=KEYS,
            left_label=f"COMSOL {variant}",
            right_label="SIMION",
            suffixes=("_COMSOL", "_SIMION"),
        )
        merged_by_variant[variant] = merged
        metrics["against_simion"][variant] = {
            component: _component_metrics(
                merged[f"{component}_V_per_m_SIMION"].to_numpy(),
                merged[f"{component}_V_per_m_COMSOL"].to_numpy(),
            )
            for component in COMPONENTS
        }

    for previous, current in zip(order, order[1:]):
        left = merged_by_variant[previous]
        right = merged_by_variant[current]
        metrics["successive_comsol_change"][f"{previous}_to_{current}"] = {
            component: _component_metrics(
                left[f"{component}_V_per_m_COMSOL"].to_numpy(),
                right[f"{component}_V_per_m_COMSOL"].to_numpy(),
            )
            for component in COMPONENTS
        }

    particle_ids = sorted(simion["particle_id"].unique())
    figure, axes = plt.subplots(
        3, len(particle_ids), figsize=(5.2 * len(particle_ids), 11),
        squeeze=False, constrained_layout=True,
    )
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, len(order)))
    for column, particle_id in enumerate(particle_ids):
        simion_particle = simion[simion["particle_id"] == particle_id].sort_values("z_mm")
        for row, component in enumerate(COMPONENTS):
            axis = axes[row, column]
            axis.plot(
                simion_particle["z_mm"], simion_particle[f"{component}_V_per_m"] / 1e3,
                color="black", linewidth=2.2, label="SIMION",
            )
            for color, variant in zip(colors, order):
                group = variants[
                    (variants["variant"] == variant)
                    & (variants["particle_id"] == particle_id)
                ].sort_values("z_mm")
                axis.plot(
                    group["z_mm"], group[f"{component}_V_per_m"] / 1e3,
                    color=color, linewidth=1.3, marker=".", label=variant,
                )
            axis.set(
                title=f"Particle {particle_id}: {component}", xlabel="z [mm]",
                ylabel=f"{component} [V/mm]",
            )
            axis.grid(True, alpha=0.3)
            axis.legend(fontsize=7)

    args.output.mkdir(parents=True, exist_ok=True)
    variants.to_csv(args.output / "comsol_accelerator_mesh_field_samples.csv", index=False)
    (args.output / "accelerator_mesh_convergence_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    figure.savefig(
        args.output / "accelerator_mesh_convergence.png", dpi=220, facecolor="white"
    )
    plt.close(figure)
    print("ACCELERATOR_MESH_ANALYSIS_STATUS=COMPLETE CONVERGENCE=NOT_EVALUATED")


if __name__ == "__main__":
    main()
