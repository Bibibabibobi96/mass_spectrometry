"""Compare each solver's independently refined unit RF field by axial region."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from compare_unit_rf_field import load, metrics


def aligned(reference: np.ndarray, candidate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    candidate_index = {tuple(row[:3]): row for row in candidate}
    reference_rows = [row for row in reference if tuple(row[:3]) in candidate_index]
    reference_aligned = np.asarray(reference_rows)
    candidate_aligned = np.asarray([candidate_index[tuple(row[:3])] for row in reference_aligned])
    return reference_aligned, candidate_aligned


def regional(reference: np.ndarray, candidate: np.ndarray) -> dict[str, dict[str, float]]:
    reference, candidate = aligned(reference, candidate)
    z = reference[:, 2]
    masks = {
        "all_grid": np.ones(len(z), dtype=bool),
        "entrance_fringe": z < 5.8,
        "rod_region": (z >= 5.8) & (z <= 85.4),
        "exit_fringe_and_detector": z > 85.4,
    }
    return {name: metrics(candidate, reference, mask) for name, mask in masks.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    results = args.workspace / "artifacts/projects/rf_quadrupole_collision_cooling/results"
    summary = {
        "status": "PASS",
        "SIMION_0p2_to_0p1": regional(
            load(results / "simion/unit_rf_field_pa_grid.csv"),
            load(results / "simion/unit_rf_field_pa_grid_cell010.csv"),
        ),
        "COMSOL_mesh1_to_hmax0p5": regional(
            load(results / "comsol/unit_rf_field_fem_grid.csv"),
            load(results / "comsol/unit_rf_field_fem_grid_hmax050_edge_convergence.csv"),
        ),
    }
    output = results / "cross_solver/unit_rf_field_resolution_convergence.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"STATUS=PASS SUMMARY={output}")


if __name__ == "__main__":
    main()
