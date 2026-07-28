"""Pair two RF continuous-shield 3D field tables without declaring acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


KEY_COLUMNS = ["sample_z_mm", "sample_radius_mm", "theta_rad"]
COORD_COLUMNS = ["evaluation_z_mm", "evaluation_radius_mm", "x_mm", "y_mm"]
FIELD_COLUMNS = ["Ex_V_per_m", "Ey_V_per_m", "Ez_V_per_m"]
REQUIRED_COLUMNS = set(KEY_COLUMNS + COORD_COLUMNS + FIELD_COLUMNS)
FRINGE_REGION_Z_MIN_MM = 83.4


def compare(candidate: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    for label, table in (("candidate", candidate), ("reference", reference)):
        missing = REQUIRED_COLUMNS - set(table.columns)
        if missing:
            raise ValueError(f"{label} table is missing columns: {sorted(missing)}")
    left = candidate.sort_values(KEY_COLUMNS).reset_index(drop=True)
    right = reference.sort_values(KEY_COLUMNS).reset_index(drop=True)
    if len(left) != len(right):
        raise ValueError("paired field tables have different row counts")
    for column in KEY_COLUMNS + COORD_COLUMNS:
        if not np.allclose(left[column].to_numpy(float), right[column].to_numpy(float), rtol=0.0, atol=1e-12):
            raise ValueError(f"paired field tables do not share {column}")
    delta = left[FIELD_COLUMNS].to_numpy(float) - right[FIELD_COLUMNS].to_numpy(float)
    reference_field = right[FIELD_COLUMNS].to_numpy(float)
    work = left[KEY_COLUMNS + COORD_COLUMNS].copy()
    work["delta_field_squared"] = np.sum(np.square(delta), axis=1)
    work["reference_field_squared"] = np.sum(np.square(reference_field), axis=1)
    work["boundary_inset_used"] = (
        ~np.isclose(work["sample_z_mm"], work["evaluation_z_mm"], rtol=0.0, atol=1e-12)
        | ~np.isclose(work["sample_radius_mm"], work["evaluation_radius_mm"], rtol=0.0, atol=1e-12)
    )
    rows = []
    for (z_value, radius), group in work.groupby(["sample_z_mm", "sample_radius_mm"], sort=True):
        delta_rms = float(np.sqrt(group["delta_field_squared"].mean()))
        reference_rms = float(np.sqrt(group["reference_field_squared"].mean()))
        rows.append(
            {
                "sample_z_mm": float(z_value),
                "sample_radius_mm": float(radius),
                "delta_field_vector_rms_V_per_m": delta_rms,
                "reference_field_vector_rms_V_per_m": reference_rms,
                "delta_vector_rms_relative_to_reference": delta_rms / reference_rms if reference_rms > 0.0 else np.nan,
                "boundary_inset_used": bool(group["boundary_inset_used"].any()),
            }
        )
    return pd.DataFrame(rows)


def summarize(comparison: pd.DataFrame, comparison_kind: str) -> dict[str, object]:
    relative = comparison["delta_vector_rms_relative_to_reference"]
    nonboundary = comparison.loc[~comparison["boundary_inset_used"], "delta_vector_rms_relative_to_reference"]
    central = comparison.loc[comparison["sample_radius_mm"] <= 2.0, "delta_vector_rms_relative_to_reference"]
    fringe = comparison.loc[comparison["sample_z_mm"] >= FRINGE_REGION_Z_MIN_MM]
    fringe_core = fringe.loc[fringe["sample_radius_mm"] <= 2.0, "delta_vector_rms_relative_to_reference"]
    midplane = comparison.loc[np.isclose(comparison["sample_z_mm"], 45.6), "delta_vector_rms_relative_to_reference"]
    return {
        "schema_version": 1,
        "role": "rf_continuous_grounded_shield_3d_paired_field_comparison",
        "status": "CHARACTERIZED",
        "comparison_kind": comparison_kind,
        "maximum_relative_vector_rms_all_groups": float(relative.max()),
        "maximum_relative_vector_rms_excluding_boundary_inset_groups": float(nonboundary.max()),
        "maximum_relative_vector_rms_r_le_2_mm": float(central.max()),
        "fringe_region_z_min_mm": FRINGE_REGION_Z_MIN_MM,
        "maximum_relative_vector_rms_fringe_region_all_radii": float(fringe["delta_vector_rms_relative_to_reference"].max()),
        "maximum_relative_vector_rms_fringe_region_r_le_2_mm": float(fringe_core.max()),
        "maximum_relative_vector_rms_midplane": float(midplane.max()),
        "acceptance_decision": "UNRESOLVED",
        "claim_limit": "Paired field characterization only. Boundary-adjacent singular fields and particle-performance relevance require separate interpretation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--comparison-kind", required=True, choices=("mesh_convergence", "radius_sensitivity"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = compare(pd.read_csv(args.candidate), pd.read_csv(args.reference))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output_dir / "rf_continuous_shield_3d_paired_field_comparison.csv", index=False)
    (args.output_dir / "rf_continuous_shield_3d_paired_field_metrics.json").write_text(
        json.dumps(summarize(result, args.comparison_kind), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("RF_CONTINUOUS_SHIELD_3D_COMPARISON=PASS ACCEPTANCE_DECISION=UNRESOLVED")


if __name__ == "__main__":
    main()
