"""Compare independently solved COMSOL FEM and SIMION PA unit RF fields."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load(path: Path) -> np.ndarray:
    with path.open(encoding="utf-8", newline="") as handle:
        return np.array([[float(row[name]) for name in ("x_mm", "y_mm", "z_mm", "Ex_V_per_m", "Ey_V_per_m", "Ez_V_per_m")] for row in csv.DictReader(handle)])


def metrics(fem: np.ndarray, pa: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    delta = fem[mask, 3:] - pa[mask, 3:]
    result = {"points": int(mask.sum()), "vector_rms_difference_V_per_m": float(np.sqrt(np.mean(np.sum(delta**2, axis=1)))),
              "vector_relative_rms": float(np.sqrt(np.mean(np.sum(delta**2, axis=1))) / np.sqrt(np.mean(np.sum(pa[mask, 3:]**2, axis=1))))}
    for index, component in enumerate(("Ex", "Ey", "Ez")):
        result[f"{component}_rms_difference_V_per_m"] = float(np.sqrt(np.mean(delta[:, index] ** 2)))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    root = args.workspace / "artifacts/projects/rf_quadrupole_collision_cooling/results"
    pa = load(root / "simion/unit_rf_field_pa_grid.csv")
    fem = load(root / "comsol/unit_rf_field_fem_grid.csv")
    keys = {tuple(row) for row in fem[:, :3]}
    pa = np.array([row for row in pa if tuple(row[:3]) in keys])
    fem_index = {tuple(row[:3]): row for row in fem}
    fem = np.array([fem_index[tuple(row[:3])] for row in pa])
    rod = (pa[:, 2] >= 5.8) & (pa[:, 2] <= 85.4)
    output = root / "cross_solver"
    output.mkdir(parents=True, exist_ok=True)
    mid = np.isclose(pa[:, 2], 45.6) & np.isclose(pa[:, 1], 0.0)
    if np.count_nonzero(mid) < 5:
        raise ValueError("Midpoint transverse line has too few common field samples")
    pa_gradient = np.polyfit(pa[mid, 0], pa[mid, 3], 1)[0]
    fem_gradient = np.polyfit(fem[mid, 0], fem[mid, 3], 1)[0]
    summary = {"status": "PASS", "all_grid": metrics(fem, pa, np.ones(len(pa), dtype=bool)), "rod_region": metrics(fem, pa, rod),
               "midpoint_y0_Ex_gradient_V_per_m_per_mm": {"SIMION_PA": float(pa_gradient), "COMSOL_FEM": float(fem_gradient),
                                                             "relative_difference": float(abs(fem_gradient-pa_gradient)/abs(pa_gradient))}}
    (output / "unit_rf_field_comparison.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    figure, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    axis.plot(pa[mid, 0], pa[mid, 3] / 1e3, label="SIMION PA")
    axis.plot(fem[mid, 0], fem[mid, 3] / 1e3, linestyle="--", label="COMSOL FEM")
    axis.set(title="Independent unit RF field: rod midpoint y=0", xlabel="x (mm)", ylabel="Ex (kV/m)")
    axis.grid(True, alpha=0.3); axis.legend()
    figure.savefig(output / "unit_rf_field_midplane_comparison.png", dpi=190)
    print(f"STATUS=PASS SUMMARY={output / 'unit_rf_field_comparison.json'}")


if __name__ == "__main__":
    main()
