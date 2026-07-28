"""Resolve the human-edited oa-TOF design and run mode once."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = PROJECT_ROOT / "config" / "baseline.json"
MODE_PATH = PROJECT_ROOT / "config" / "modes" / "formal.json"
NUMERICS_PATH = PROJECT_ROOT / "config" / "formal_solver_numerics.json"
RESOLVED_PATH = PROJECT_ROOT / "config" / "resolved_geometry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _close(label: str, actual: float, expected: float, tolerance: float = 1e-10) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(f"inconsistent {label}: {actual} != {expected}")


def _input_label(path: Path, run_role: str) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return f"run_input:{run_role}"


def _require_exact_keys(document: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(document) - allowed
    if unknown:
        raise ValueError(f"{label} contains cross-layer or unknown fields: {sorted(unknown)}")


def _validate_layers(baseline: dict[str, Any], science: dict[str, Any], numerics: dict[str, Any]) -> None:
    if "seed" in baseline.get("particle_source", {}):
        raise ValueError("science baseline must not contain particle_source.seed; freeze it in the run instance")
    _require_exact_keys(science, {"schema_version", "role", "mode", "contract_layers", "particle"}, "science contract")
    if science.get("role") != "oa_tof_formal_science_contract" or science.get("mode") != "formal":
        raise ValueError("unsupported formal science contract")
    if science.get("contract_layers") != ["science", "solver_numerics", "run_instance"]:
        raise ValueError("formal science contract has an invalid layer declaration")
    _require_exact_keys(numerics, {"schema_version", "role", "comsol", "simion"}, "solver numerics contract")
    if numerics.get("role") != "oa_tof_formal_solver_numerics":
        raise ValueError("unsupported formal solver numerics contract")
    if not isinstance(science.get("particle"), dict) or not isinstance(numerics.get("comsol"), dict) or not isinstance(numerics.get("simion"), dict):
        raise ValueError("formal contracts are missing required science or solver sections")


def resolve_contract(
    baseline_path: Path = BASELINE_PATH,
    mode_path: Path = MODE_PATH,
    numerics_path: Path = NUMERICS_PATH,
) -> dict[str, Any]:
    baseline_path = Path(baseline_path)
    mode_path = Path(mode_path)
    numerics_path = Path(numerics_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    numerics = json.loads(numerics_path.read_text(encoding="utf-8"))
    _validate_layers(baseline, mode, numerics)
    geometry = baseline["geometry_mm"]
    accelerator = baseline["geometry_derivation"]["accelerator"]
    source = baseline["particle_source"]

    _close("accelerator length", geometry["L_accel"], accelerator["d1_mm"] + accelerator["d2_mm"])
    _close("accelerator grid1", geometry["accelerator_grid1_z"], geometry["accelerator_repeller_z"] + accelerator["d1_mm"])
    _close("accelerator grid2", geometry["accelerator_grid2_z"], geometry["accelerator_grid1_z"] + accelerator["d2_mm"])
    _close("focus plane", geometry["accelerator_focus_z"], geometry["accelerator_grid2_z"] + accelerator["focus_drift_after_grid2_mm"])
    _close("reflectron length", geometry["L_reflectron"], geometry["L_stage1"] + geometry["L_stage2"])
    _close("source center z", source["center_z_mm"], geometry["accelerator_repeller_z"] + accelerator["d1_mm"] / 2)

    build = numerics["simion"]["geometry_build"]
    marker = numerics["simion"]["detector_marker"]
    if not 0 < marker["capture_depth_mm"] < marker["absorber_thickness_mm"]:
        raise ValueError("detector capture depth must lie inside the numerical absorber")
    if marker["capture_arm_distance_mm"] <= marker["front_margin_z_mm"]:
        raise ValueError("detector capture arm distance must exceed the PA front margin")
    coordinate = baseline["coordinate_convention"]
    if coordinate.get("frame_id") != "oatof_global":
        raise ValueError("oa-TOF baseline coordinate frame must be oatof_global")
    accelerator_half = geometry["accelerator_bore_half"] + geometry["accelerator_ring_width"] + geometry["accelerator_insulation_gap"] + geometry["accelerator_shield_wall"]
    accelerator_local_z_min = -geometry["accelerator_repeller_thickness"] - geometry["accelerator_rear_clearance"] - geometry["accelerator_shield_wall"]
    accelerator_local_z_max = geometry["L_accel"] + geometry["accelerator_front_vacuum_margin"]
    detector_half = marker["active_radius_mm"] + build["detector"]["margin_xy_mm"]

    instances = [
        {"role": "flight_tube_shield", "workbench_index": 1, "priority_number": 1, "name": "flight_tube_ground.pa0", "x_mm": coordinate["reflectron_axis"][0], "y_mm": coordinate["reflectron_axis"][1], "z_mm": geometry["shield_outer_z_min"], "az_deg": -90.0,
         "nx": math.ceil((geometry["L_flight"] - geometry["shield_outer_z_min"]) / build["flight_tube"]["cell_axial_mm"]) + 1,
         "ny": math.ceil((geometry["flight_tube_r"] + geometry["flight_tube_wall"]) / build["flight_tube"]["cell_radial_mm"]) + 1, "nz": 1, "cell_mm": build["flight_tube"]["cell_axial_mm"]},
        {"role": "reflectron", "workbench_index": 2, "priority_number": 2, "name": "reflectron.pa0", "x_mm": coordinate["reflectron_axis"][0], "y_mm": coordinate["reflectron_axis"][1], "z_mm": geometry["L_flight"], "az_deg": -90.0,
         "nx": math.ceil((geometry["L_reflectron"] + geometry["ring_thickness"] + geometry["shield_axial_gap"] + geometry["shield_endcap_thickness"]) / build["reflectron"]["cell_axial_mm"]) + 1,
         "ny": math.ceil((geometry["flight_tube_r"] + geometry["flight_tube_wall"]) / build["reflectron"]["cell_radial_mm"]) + 1, "nz": 1, "cell_mm": build["reflectron"]["cell_axial_mm"]},
        {"role": "accelerator", "workbench_index": 3, "priority_number": 3, "name": "accelerator.pa0", "x_mm": coordinate["accelerator_axis_x"] - accelerator_half, "y_mm": -accelerator_half,
         "z_mm": geometry["accelerator_repeller_z"] + accelerator_local_z_min, "az_deg": 0.0,
         "nx": round(2 * accelerator_half / build["accelerator"]["cell_xy_mm"]) + 1,
         "ny": round(2 * accelerator_half / build["accelerator"]["cell_xy_mm"]) + 1,
         "nz": round((accelerator_local_z_max - accelerator_local_z_min) / build["accelerator"]["cell_z_mm"]) + 1,
         "cell_mm": build["accelerator"]["cell_xy_mm"]},
        {"role": "detector", "workbench_index": 4, "priority_number": 4, "name": "detector_ground.pa0", "x_mm": coordinate["detector_x"] - detector_half, "y_mm": -detector_half,
         "z_mm": marker["active_plane_z_mm"] - marker["back_margin_z_mm"] - marker["absorber_thickness_mm"], "az_deg": 0.0,
         "nx": round(2 * detector_half / marker["cell_xy_mm"]) + 1,
         "ny": round(2 * detector_half / marker["cell_xy_mm"]) + 1,
         "nz": round((marker["front_margin_z_mm"] + marker["absorber_thickness_mm"] + marker["back_margin_z_mm"]) / marker["cell_z_mm"]) + 1,
         "cell_mm": marker["cell_xy_mm"]},
    ]

    particle = mode["particle"]
    return {
        "schema_version": 1,
        "role": "oa_tof_resolved_contract_do_not_edit",
        "inputs": {
            "baseline": _input_label(baseline_path, "candidate_baseline.json"),
            "baseline_sha256": _sha256(baseline_path),
            "mode": _input_label(mode_path, "candidate_science_mode.json"),
            "mode_sha256": _sha256(mode_path),
            "solver_numerics": _input_label(
                numerics_path, "candidate_solver_numerics.json"
            ),
            "solver_numerics_sha256": _sha256(numerics_path),
        },
        "coordinate_convention": coordinate,
        "geometry_derivation": baseline["geometry_derivation"],
        "geometry_mm": geometry,
        "particle_source": source,
        "electrodes_V": baseline["electrodes_V"],
        "rings": baseline["rings"],
        "validation_target": {
            "mass_amu": particle["mass_amu"],
            "charge_state": particle["charge_state"],
            "particles": particle["statistical_count"],
            "initial_energy_mean_ev": particle["initial_energy_mean_ev"],
            "initial_energy_sigma_ev": particle["initial_energy_sigma_ev"],
        },
        "particle_count_policy": {
            "default_check_count": particle["default_check_count"],
            "statistical_count": particle["statistical_count"],
            "specialty_counts_require_explicit_purpose": True,
        },
        "simion_runtime": {
            **numerics["simion"],
            "routine_particles": particle["statistical_count"],
        },
        "simion_geometry_build": build,
        "comsol_runtime": numerics["comsol"],
        "simion_detector_marker": marker,
        "grid_policy": baseline["grid_policy"],
        "derived": {
            "simion_instances": instances,
            "field_sample_points_mm": {
                "source_center": [coordinate["accelerator_axis_x"], 0.0, source["center_z_mm"]],
                "accelerator_mid": [coordinate["accelerator_axis_x"], 0.0, (geometry["accelerator_grid1_z"] + geometry["accelerator_grid2_z"]) / 2],
                "accelerator_exit": [coordinate["accelerator_axis_x"], 0.0, geometry["accelerator_grid2_z"] - build["accelerator"]["cell_z_mm"]],
                "drift_mid": [coordinate["reflectron_axis"][0], coordinate["reflectron_axis"][1], (marker["active_plane_z_mm"] + geometry["L_flight"]) / 2],
                "reflectron_stage1": [coordinate["reflectron_axis"][0], coordinate["reflectron_axis"][1], geometry["L_flight"] + geometry["L_stage1"] / 2],
                "reflectron_stage2": [coordinate["reflectron_axis"][0], coordinate["reflectron_axis"][1], geometry["L_flight"] + geometry["L_stage1"] + geometry["L_stage2"] / 2],
            },
        },
    }


def serialized(contract: dict[str, Any]) -> str:
    return json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
