"""Validate the frozen full-device RF hybrid-mesh candidate."""

from __future__ import annotations

import json
import math
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "config" / "rf_hybrid_mesh_candidate.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(path: Path = CONTRACT_PATH) -> dict:
    contract = load(path)
    if contract.get("schema_version") != 1 or contract.get("status") != "approved_for_solver_validation":
        raise ValueError("RF hybrid mesh identity is invalid")
    resolved = load(PROJECT_ROOT / contract["inputs"]["resolved_geometry"])
    uniform = load(PROJECT_ROOT / contract["inputs"]["uniform_mesh_contract"])
    g = resolved["geometry_mm"]
    geometry = contract["geometry_mm"]
    expected = {
        "model_z_min": 0.0,
        "model_z_max": float(g["exit_enclosure_front_wall_end_z"]),
        "shield_inner_radius": 19.776,
        "uniform_region_z_min": float(g["rod_z_min"]) + 4.0,
        "uniform_region_z_max": 81.4,
        "fine_core_radius": 8.0,
    }
    for key, value in expected.items():
        if not math.isclose(float(geometry.get(key, -1.0)), value, abs_tol=1e-12):
            raise ValueError(f"RF hybrid geometry changed: {key}")
    mesh = contract["uniform_region_mesh"]
    if mesh != {
        "method": "free_triangular_source_and_swept_prisms",
        "fine_core_and_rod_boundary_hmax_mm": 0.2,
        "outer_vacuum_hmax_mm": 1.0,
        "axial_layers": 40,
    }:
        raise ValueError("RF hybrid uniform mesh is not the selected swept candidate")
    if contract["end_region_mesh"]["fine_core_hmax_mm_sequence"] != [0.5, 0.25, 0.125]:
        raise ValueError("RF hybrid end-region sequence changed")
    if contract["field_sampling"]["hard_field_convergence_radius_max_mm"] >= contract["field_sampling"]["aperture_edge_radius_mm"]:
        raise ValueError("RF hybrid hard field region must exclude the ideal aperture edge")
    acceptance = contract["acceptance"]
    if acceptance.get("particle_tracking_allowed_only_after_field_pass") is not False:
        raise ValueError("RF hybrid particle diagnostic must not be blocked by a local field ratio alone")
    if acceptance.get("particle_diagnostic_allowed_after_problem_free_paired_fields") is not True:
        raise ValueError("RF hybrid functional arbitration is not explicit")
    if acceptance.get("local_field_maximum_is_diagnostic_not_a_standalone_veto") is not True:
        raise ValueError("RF hybrid local-field interpretation changed")
    evidence = contract["n100_functional_arbitration_evidence"]
    if evidence.get("status") != "low_cost_mesh_and_shared_clock_functional_chain_qualified":
        raise ValueError("RF hybrid downstream arbitration state changed")
    if evidence.get("classification_change_count") != 0 or evidence.get("hmax_0p125_run_allowed") is not False:
        raise ValueError("RF hybrid stop rule changed")
    if not math.isclose(float(evidence.get("retained_low_cost_mesh_end_hmax_mm", -1)), 0.5, abs_tol=1e-12):
        raise ValueError("RF hybrid low-cost mesh changed")
    projection = evidence.get("static_oatof_projection", {})
    if projection.get("mesh_decision") != "RETAIN_LOW_COST_FOR_NEXT_STAGE":
        raise ValueError("RF hybrid static downstream mesh decision changed")
    if not math.isclose(float(projection.get("transmission_absolute_difference", -1)), 0.01, abs_tol=1e-12):
        raise ValueError("RF hybrid downstream loss sensitivity changed")
    pulse = evidence.get("shared_clock_pulse", {})
    if pulse.get("status") != "PASS" or pulse.get("timed_pulse_hits") != 44 or pulse.get("held_off_control_hits") != 0:
        raise ValueError("RF hybrid shared-clock pulse evidence changed")
    if uniform["localized_transverse_mesh"]["work_core_radius_mm_candidates"] != [6.0, 8.0, 10.0]:
        raise ValueError("RF hybrid input swept contract changed")
    return contract


if __name__ == "__main__":
    candidate = validate()
    print("RF_HYBRID_MESH=PASS PAIRED_PARTICLE_DIAGNOSTIC_ALLOWED=true")
