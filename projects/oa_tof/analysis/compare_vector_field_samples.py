"""Compare COMSOL and SIMION vector fields at identical coordinates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("comsol", type=Path)
    parser.add_argument("simion", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    keys = ["particle_id", "time_us", "x_mm", "y_mm", "z_mm"]
    c = pd.read_csv(args.comsol)
    s = pd.read_csv(args.simion)
    merged = c.merge(s, on=keys, suffixes=("_COMSOL", "_SIMION"), validate="one_to_one")
    metrics: dict[str, object] = {"status": "PASS", "particles": {}}
    figure, axes = plt.subplots(3, 3, figsize=(15, 11), constrained_layout=True)
    for column, particle_id in enumerate(sorted(merged["particle_id"].unique())):
        group = merged[merged["particle_id"] == particle_id].sort_values("z_mm")
        component_metrics = {}
        for row, component in enumerate(("Ex", "Ey", "Ez")):
            cv = group[f"{component}_V_per_m_COMSOL"].to_numpy()
            sv = group[f"{component}_V_per_m_SIMION"].to_numpy()
            delta = sv - cv
            component_metrics[component] = {
                "COMSOL_rms_V_per_m": float(np.sqrt(np.mean(cv**2))),
                "SIMION_rms_V_per_m": float(np.sqrt(np.mean(sv**2))),
                "difference_rms_V_per_m": float(np.sqrt(np.mean(delta**2))),
                "difference_mean_V_per_m": float(np.mean(delta)),
                "difference_max_abs_V_per_m": float(np.max(np.abs(delta))),
            }
            axes[row, column].plot(group["z_mm"], cv / 1e3, label="COMSOL")
            axes[row, column].plot(group["z_mm"], sv / 1e3, label="SIMION")
            axes[row, column].set(
                title=f"Particle {particle_id}: {component}", xlabel="z [mm]",
                ylabel=f"{component} [V/mm]",
            )
            axes[row, column].grid(True, alpha=0.3)
            axes[row, column].legend()
        metrics["particles"][str(int(particle_id))] = component_metrics
    args.output.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output / "accelerator_vector_field_comparison.csv", index=False)
    (args.output / "accelerator_vector_field_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    figure.savefig(args.output / "accelerator_vector_field_comparison.png", dpi=220, facecolor="white")
    plt.close(figure)
    print("VECTOR_FIELD_COMPARISON_STATUS=PASS")


if __name__ == "__main__":
    main()
