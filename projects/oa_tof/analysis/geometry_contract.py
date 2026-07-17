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
RESOLVED_PATH = PROJECT_ROOT / "config" / "resolved_geometry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _close(label: str, actual: float, expected: float, tolerance: float = 1e-10) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(f"inconsistent {label}: {actual} != {expected}")


def resolve_contract() -> dict[str, Any]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    mode = json.loads(MODE_PATH.read_text(encoding="utf-8"))
    geometry = baseline["geometry_mm"]
    accelerator = baseline["geometry_derivation"]["accelerator"]
    source = baseline["particle_source"]

    _close("accelerator length", geometry["L_accel"], accelerator["d1_mm"] + accelerator["d2_mm"])
    _close("accelerator grid1", geometry["accelerator_grid1_z"], geometry["accelerator_repeller_z"] + accelerator["d1_mm"])
    _close("accelerator grid2", geometry["accelerator_grid2_z"], geometry["accelerator_grid1_z"] + accelerator["d2_mm"])
    _close("focus plane", geometry["accelerator_focus_z"], geometry["accelerator_grid2_z"] + accelerator["focus_drift_after_grid2_mm"])
    _close("reflectron length", geometry["L_reflectron"], geometry["L_stage1"] + geometry["L_stage2"])
    _close("source center z", source["center_z_mm"], geometry["accelerator_repeller_z"] + accelerator["d1_mm"] / 2)

    build = mode["simion"]["geometry_build"]
    marker = mode["simion"]["detector_marker"]
    coordinate = baseline["coordinate_convention"]
    accelerator_half = geometry["accelerator_bore_half"] + geometry["accelerator_ring_width"] + geometry["accelerator_insulation_gap"] + geometry["accelerator_shield_wall"]
    accelerator_local_z_min = -geometry["accelerator_repeller_thickness"] - geometry["accelerator_rear_clearance"] - geometry["accelerator_shield_wall"]
    accelerator_local_z_max = geometry["L_accel"] + geometry["accelerator_front_vacuum_margin"]
    detector_half = marker["active_radius_mm"] + build["detector"]["margin_xy_mm"]

    instances = [
        {"name": "reflectron.pa0", "x_mm": coordinate["reflectron_axis"][0], "y_mm": coordinate["reflectron_axis"][1], "z_mm": geometry["L_flight"], "az_deg": -90.0,
         "nx": math.ceil((geometry["L_reflectron"] + geometry["ring_thickness"] + geometry["shield_axial_gap"] + geometry["shield_endcap_thickness"]) / build["reflectron"]["cell_axial_mm"]) + 1,
         "ny": math.ceil((geometry["flight_tube_r"] + geometry["flight_tube_wall"]) / build["reflectron"]["cell_radial_mm"]) + 1, "nz": 1, "cell_mm": build["reflectron"]["cell_axial_mm"]},
        {"name": "accelerator.pa0", "x_mm": coordinate["accelerator_axis_x"] - accelerator_half, "y_mm": -accelerator_half,
         "z_mm": geometry["accelerator_repeller_z"] + accelerator_local_z_min, "az_deg": 0.0,
         "nx": round(2 * accelerator_half / build["accelerator"]["cell_xy_mm"]) + 1,
         "ny": round(2 * accelerator_half / build["accelerator"]["cell_xy_mm"]) + 1,
         "nz": round((accelerator_local_z_max - accelerator_local_z_min) / build["accelerator"]["cell_z_mm"]) + 1,
         "cell_mm": build["accelerator"]["cell_xy_mm"]},
        {"name": "flight_tube_ground.pa0", "x_mm": coordinate["reflectron_axis"][0], "y_mm": coordinate["reflectron_axis"][1], "z_mm": geometry["shield_outer_z_min"], "az_deg": -90.0,
         "nx": math.ceil((geometry["L_flight"] - geometry["shield_outer_z_min"]) / build["flight_tube"]["cell_axial_mm"]) + 1,
         "ny": math.ceil((geometry["flight_tube_r"] + geometry["flight_tube_wall"]) / build["flight_tube"]["cell_radial_mm"]) + 1, "nz": 1, "cell_mm": build["flight_tube"]["cell_axial_mm"]},
        {"name": "detector_ground.pa0", "x_mm": coordinate["detector_x"] - detector_half, "y_mm": -detector_half,
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
            "baseline": "config/baseline.json",
            "baseline_sha256": _sha256(BASELINE_PATH),
            "mode": "config/modes/formal.json",
            "mode_sha256": _sha256(MODE_PATH),
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
            "particles": particle["paired_validation_count"],
            "initial_energy_mean_ev": particle["initial_energy_mean_ev"],
            "initial_energy_sigma_ev": particle["initial_energy_sigma_ev"],
        },
        "simion_runtime": {**mode["simion"], "routine_particles": particle["routine_count"]},
        "simion_geometry_build": build,
        "comsol_runtime": mode["comsol"],
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
