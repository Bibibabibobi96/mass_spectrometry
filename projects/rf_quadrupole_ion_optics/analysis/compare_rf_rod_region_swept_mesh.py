"""Evaluate the frozen RF uniform-rod swept-mesh convergence contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


KEYS = ["sample_radius_mm", "theta_rad"]
FIELD_2D = ["Ex_V_per_m", "Ey_V_per_m"]
FIELD_3D = ["Ex_V_per_m", "Ey_V_per_m", "Ez_V_per_m"]


def relative_vector_rms(candidate: np.ndarray, reference: np.ndarray) -> float:
    delta_rms = float(np.sqrt(np.mean(np.square(candidate - reference))))
    reference_rms = float(np.sqrt(np.mean(np.square(reference))))
    if reference_rms <= 0.0:
        raise ValueError("reference vector RMS must be positive")
    return delta_rms / reference_rms


def ordered(table: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    missing = set(keys + FIELD_3D) - set(table.columns)
    if missing:
        raise ValueError(f"3D swept field table is missing columns: {sorted(missing)}")
    return table.sort_values(keys).reset_index(drop=True)


def localized_comparison(reference: pd.DataFrame, candidate: pd.DataFrame, contract: dict) -> dict:
    keys = ["sample_z_mm"] + KEYS
    reference = ordered(reference, keys)
    candidate = ordered(candidate, keys)
    if len(reference) != len(candidate):
        raise ValueError("localized candidate and full reference have different row counts")
    for key in keys:
        if not np.allclose(reference[key], candidate[key], rtol=0.0, atol=1e-12):
            raise ValueError(f"localized candidate and full reference do not share {key}")

    def grouped(column: str) -> dict[str, float]:
        values = {}
        for value, indices in reference.groupby(column, sort=True).groups.items():
            values[f"{float(value):.12g}"] = relative_vector_rms(
                candidate.loc[indices, FIELD_3D].to_numpy(float),
                reference.loc[indices, FIELD_3D].to_numpy(float),
            )
        return values

    by_z = grouped("sample_z_mm")
    by_radius = grouped("sample_radius_mm")
    axial_groups = []
    for _, group in candidate.groupby(["sample_z_mm", "sample_radius_mm"], sort=True):
        transverse_rms = float(
            np.sqrt(np.mean(np.square(group["Ex_V_per_m"]) + np.square(group["Ey_V_per_m"])))
        )
        axial_rms = float(np.sqrt(np.mean(np.square(group["Ez_V_per_m"]))))
        axial_groups.append(axial_rms / transverse_rms)
    threshold = float(contract["localized_transverse_mesh"]["maximum_relative_vector_rms_to_full_vacuum_reference"])
    axial_threshold = float(contract["acceptance"]["maximum_axial_to_transverse_field_rms"])
    checks = {
        "global_relative_vector_rms": relative_vector_rms(
            candidate[FIELD_3D].to_numpy(float), reference[FIELD_3D].to_numpy(float)
        ) <= threshold,
        "every_axial_section_relative_vector_rms": max(by_z.values()) <= threshold,
        "every_radius_group_relative_vector_rms": max(by_radius.values()) <= threshold,
        "maximum_group_axial_to_transverse_rms": max(axial_groups) <= axial_threshold,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "relative_vector_rms_global": relative_vector_rms(
            candidate[FIELD_3D].to_numpy(float), reference[FIELD_3D].to_numpy(float)
        ),
        "relative_vector_rms_by_z_mm": by_z,
        "relative_vector_rms_by_radius_mm": by_radius,
        "maximum_group_axial_to_transverse_rms": max(axial_groups),
        "checks": checks,
    }


def compare(two_dimensional: pd.DataFrame, coarse: pd.DataFrame, fine: pd.DataFrame, contract: dict) -> dict:
    missing_2d = set(KEYS + FIELD_2D) - set(two_dimensional.columns)
    if missing_2d:
        raise ValueError(f"2D reference table is missing columns: {sorted(missing_2d)}")
    keys_3d = ["sample_z_mm"] + KEYS
    coarse_ordered = ordered(coarse, keys_3d)
    fine_ordered = ordered(fine, keys_3d)
    if len(coarse_ordered) != len(fine_ordered):
        raise ValueError("20-layer and 40-layer tables have different row counts")
    for key in keys_3d:
        if not np.allclose(coarse_ordered[key], fine_ordered[key], rtol=0.0, atol=1e-12):
            raise ValueError(f"swept tables do not share {key}")

    layer_difference = relative_vector_rms(
        coarse_ordered[FIELD_3D].to_numpy(float), fine_ordered[FIELD_3D].to_numpy(float)
    )
    reference_2d = two_dimensional.sort_values(KEYS).reset_index(drop=True)
    comparisons_to_2d: dict[str, float] = {}
    for z_value, group in fine_ordered.groupby("sample_z_mm", sort=True):
        group = group.sort_values(KEYS).reset_index(drop=True)
        if len(group) != len(reference_2d):
            raise ValueError("3D section and 2D reference have different row counts")
        for key in KEYS:
            if not np.allclose(group[key], reference_2d[key], rtol=0.0, atol=1e-12):
                raise ValueError(f"3D section and 2D reference do not share {key}")
        comparisons_to_2d[f"{float(z_value):.12g}"] = relative_vector_rms(
            group[FIELD_2D].to_numpy(float), reference_2d[FIELD_2D].to_numpy(float)
        )

    axial_ratios: dict[str, float] = {}
    for label, table in (("20", coarse_ordered), ("40", fine_ordered)):
        group_ratios = []
        for _, group in table.groupby(["sample_z_mm", "sample_radius_mm"], sort=True):
            transverse_rms = float(
                np.sqrt(np.mean(np.square(group["Ex_V_per_m"]) + np.square(group["Ey_V_per_m"])))
            )
            axial_rms = float(np.sqrt(np.mean(np.square(group["Ez_V_per_m"]))))
            group_ratios.append(axial_rms / transverse_rms)
        axial_ratios[label] = max(group_ratios)

    acceptance = contract["acceptance"]
    checks = {
        "40_layer_relative_vector_rms_to_2d": max(comparisons_to_2d.values())
        <= float(acceptance["maximum_relative_vector_rms_to_converged_2d"]),
        "20_to_40_layer_relative_vector_rms": layer_difference
        <= float(acceptance["maximum_relative_vector_rms_20_to_40_layers"]),
        "40_layer_maximum_group_axial_to_transverse_rms": axial_ratios["40"]
        <= float(acceptance["maximum_axial_to_transverse_field_rms"]),
    }
    return {
        "schema_version": 1,
        "role": "rf_uniform_rod_region_swept_mesh_convergence",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "relative_vector_rms_20_to_40_layers": layer_difference,
        "relative_vector_rms_40_layers_to_2d_by_z_mm": comparisons_to_2d,
        "maximum_relative_vector_rms_40_layers_to_2d": max(comparisons_to_2d.values()),
        "maximum_group_axial_to_transverse_rms": axial_ratios,
        "checks": checks,
        "selected_reference": {"transverse_hmax_mm": 0.2, "axial_layers": 40} if all(checks.values()) else None,
        "claim_limit": "Uniform rod-region field mesh only; entrance/exit hybrid meshing and particle convergence remain unverified.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-2d", required=True, type=Path)
    parser.add_argument("--layers-20", required=True, type=Path)
    parser.add_argument("--layers-40", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--localized", type=Path)
    parser.add_argument("--localized-core-radius-mm", type=float)
    parser.add_argument("--localized-outer-hmax-mm", type=float)
    parser.add_argument("--reference-elements", type=int)
    parser.add_argument("--localized-elements", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    fine = pd.read_csv(args.layers_40)
    report = compare(pd.read_csv(args.reference_2d), pd.read_csv(args.layers_20), fine, contract)
    localized_arguments = (
        args.localized,
        args.localized_core_radius_mm,
        args.localized_outer_hmax_mm,
        args.reference_elements,
        args.localized_elements,
    )
    if any(value is not None for value in localized_arguments):
        if not all(value is not None for value in localized_arguments):
            raise ValueError("all localized comparison arguments must be supplied together")
        localized = localized_comparison(fine, pd.read_csv(args.localized), contract)
        localized["core_radius_mm"] = args.localized_core_radius_mm
        localized["outer_hmax_mm"] = args.localized_outer_hmax_mm
        localized["reference_elements"] = args.reference_elements
        localized["candidate_elements"] = args.localized_elements
        localized["element_reduction_fraction"] = 1.0 - args.localized_elements / args.reference_elements
        report["localized_candidate"] = localized
        report["status"] = "PASS" if report["status"] == "PASS" and localized["status"] == "PASS" else "FAIL"
        report["selected_uniform_region_mesh"] = (
            {
                "core_radius_mm": args.localized_core_radius_mm,
                "core_and_rod_boundary_hmax_mm": 0.2,
                "outer_vacuum_hmax_mm": args.localized_outer_hmax_mm,
                "axial_layers": 40,
            }
            if localized["status"] == "PASS"
            else None
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"RF_ROD_REGION_SWEPT_MESH_CONVERGENCE={report['status']}")
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
