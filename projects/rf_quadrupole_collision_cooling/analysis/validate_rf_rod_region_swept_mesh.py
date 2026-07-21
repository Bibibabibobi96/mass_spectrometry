"""Validate the RF uniform-rod swept-mesh candidate contract."""

from __future__ import annotations

import json
import math
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "config" / "rf_rod_region_swept_mesh_candidate.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(path: Path = CONTRACT_PATH) -> dict:
    contract = load(path)
    if contract.get("schema_version") != 1 or contract.get("status") != "approved_for_solver_validation":
        raise ValueError("RF swept-mesh candidate identity is invalid")
    resolved = load(PROJECT_ROOT / contract["inputs"]["resolved_geometry"])
    shield = load(PROJECT_ROOT / contract["inputs"]["continuous_shield"])
    g = resolved["geometry_mm"]
    geometry = contract["geometry_mm"]
    expected = {
        "z_min": float(g["rod_z_min"]),
        "z_max": float(shield["three_dimensional_fringe_field_screen"]["local_mesh_partition_z_min_mm"]),
        "length": float(shield["three_dimensional_fringe_field_screen"]["local_mesh_partition_z_min_mm"]) - float(g["rod_z_min"]),
        "shield_inner_radius": 19.776,
        "physical_work_radius_r0": float(g["field_radius_r0"]),
        "diagnostic_radius_max": 0.9 * float(g["field_radius_r0"]),
    }
    for key, value in expected.items():
        if not math.isclose(float(geometry.get(key, -1.0)), value, abs_tol=1e-12):
            raise ValueError(f"RF swept-mesh geometry changed: {key}")
    transverse = contract["transverse_mesh"]
    if transverse.get("source_face_method") != "free_triangular" or transverse.get("maximum_element_size_mm") != [0.2, 0.1]:
        raise ValueError("RF swept transverse mesh sequence changed")
    localized = contract["localized_transverse_mesh"]
    if localized.get("reference_profile") != "full_vacuum_hmax_0p2":
        raise ValueError("RF swept localized mesh reference changed")
    if localized.get("work_core_radius_mm_candidates") != [6.0, 8.0, 10.0]:
        raise ValueError("RF swept localized work-core radius sequence changed")
    if localized.get("outer_vacuum_hmax_mm") != [1.0, 0.5] or localized.get("axial_layers") != 40:
        raise ValueError("RF swept localized mesh sequence changed")
    required_core_radius = expected["diagnostic_radius_max"] + float(localized["work_core_hmax_mm"])
    if any(float(radius) < required_core_radius - 1e-12 for radius in localized["work_core_radius_mm_candidates"]):
        raise ValueError("RF swept localized core lacks a full-element diagnostic buffer")
    if any(float(radius) <= expected["physical_work_radius_r0"] for radius in localized["work_core_radius_mm_candidates"]):
        raise ValueError("RF swept localized partition must not be tangent to the rod tips at r0")
    if not math.isclose(float(localized.get("transition_minimum_element_size_mm", -1.0)), 0.02, abs_tol=1e-12):
        raise ValueError("RF swept localized transition minimum size changed")
    axial = contract["axial_mesh"]
    if axial.get("method") != "equidistant_swept_prism_layers" or axial.get("layer_count") != [20, 40]:
        raise ValueError("RF swept axial layer sequence changed")
    length = expected["length"]
    derived = [length / count for count in axial["layer_count"]]
    if any(not math.isclose(float(actual), expected_value, abs_tol=1e-12) for actual, expected_value in zip(axial["nominal_layer_thickness_mm"], derived)):
        raise ValueError("RF swept axial layer thickness is stale")
    field = contract["field_contract"]
    if field.get("rod_potential_pattern_V") != [100.0, -100.0, 100.0, -100.0] or field.get("sample_z_mm") != [10.0, 45.6, 77.2]:
        raise ValueError("RF swept field contract changed")
    acceptance = contract["acceptance"]
    if acceptance.get("logical_operator") != "AND" or acceptance.get("particle_acceptance_allowed") is not False:
        raise ValueError("RF swept acceptance contract is invalid")
    if acceptance.get("physics_domain_mesh_coverage_and_problem_free") is not True:
        raise ValueError("RF swept physics-domain mesh coverage gate is missing")
    if acceptance.get("global_geometry_mesh_completion_required") is not False:
        raise ValueError("RF swept mesh must not require unused conductor volume meshes")
    if contract["future_multipole_promotion"].get("common_implementation_allowed_now") is not False:
        raise ValueError("RF swept mesh may not be promoted to common before another multipole validation")
    return contract


if __name__ == "__main__":
    candidate = validate()
    print(f"RF_ROD_REGION_SWEPT_MESH=PASS LAYERS={','.join(str(value) for value in candidate['axial_mesh']['layer_count'])} COMMON_ALLOWED=false")
