"""Validate the solver-neutral S2 passive connector geometry contract."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
    from . import build_interface_handoff
except ImportError:  # Direct script execution from the project Static gate.
    import build_interface_handoff


PROJECT_ROOT = Path(__file__).parents[1]
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json"


def _load_relative(path: str) -> dict[str, Any]:
    resolved = (PROJECT_ROOT / path).resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _assert_close(actual: float, expected: float, name: str) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{name} differs: expected {expected}, got {actual}")


def validate_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """Validate inherited geometry, rigid poses and fail-closed S2 permissions."""
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("role") != "rf_to_oatof_s2_passive_grounded_connector_candidate":
        raise ValueError("S2 connector role differs")
    if contract.get("stage") != "S2":
        raise ValueError("S2 connector stage differs")

    stage_plan = _load_relative(contract["inputs"]["stage_plan"])
    if stage_plan.get("current_stage") not in {"S2", "S3", "S4", "S5"}:
        raise ValueError("stage plan has not reached or inherited S2")
    stage = next(item for item in stage_plan["stages"] if item["id"] == "S2")
    if stage.get("status") != "nominal_no_pulse_particle_function_passed_stage_unqualified":
        raise ValueError("S2 stage status differs")

    dependency_contract = _load_relative(contract["inputs"]["explicit_dependencies"])
    if dependency_contract.get("role") != "rf_to_oatof_s2_explicit_source_dependencies":
        raise ValueError("S2 dependency-contract role differs")
    if dependency_contract.get("consumer_project") != "rf_quadrupole_collision_cooling":
        raise ValueError("S2 dependency consumer differs")
    dependencies = dependency_contract.get("dependencies", [])
    if {item.get("id") for item in dependencies} != {
        "oatof_baseline",
        "oatof_accelerator_geometry_builder",
    }:
        raise ValueError("S2 explicit dependency set differs")
    for dependency in dependencies:
        provider = dependency.get("provider_project")
        source = Path(str(dependency.get("source_repo_path", "")))
        expected_prefix = Path("projects") / str(provider)
        if provider != "oa_tof" or source.parts[:2] != expected_prefix.parts:
            raise ValueError(f"S2 dependency {dependency.get('id')} escapes oa_tof")
        if not (PROJECT_ROOT.parents[1] / source).is_file():
            raise ValueError(f"S2 dependency {dependency.get('id')} source is missing")
    policy = dependency_contract.get("runtime_policy", {})
    if not policy.get("verify_source_and_frozen_sha256_equal") or policy.get("allow_directory_search"):
        raise ValueError("S2 dependency runtime policy is not fail-closed")

    s1 = _load_relative(contract["inputs"]["s1_joint_field"])
    rf = _load_relative(contract["inputs"]["rf_resolved_geometry"])
    interface = _load_relative(contract["inputs"]["interface_reference"])
    registration = contract["nominal_registration"]
    gap_mm = float(registration["connector_gap_mm"])
    if gap_mm < 0.0:
        raise ValueError("S2 connector gap cannot be negative")

    rotation = registration["source_component_pose"]["rotation_component_to_instrument"]
    build_interface_handoff.validate_rotation_matrix(rotation)
    if rotation != s1["nominal_registration"]["source_component_pose"]["rotation_component_to_instrument"]:
        raise ValueError("S2 source rotation must inherit S1")

    target_center = interface["boundaries"]["target_entry_surface"]["center_mm"]
    if registration["target_entry_center_instrument_mm"] != target_center:
        raise ValueError("S2 target entry center differs from the interface reference")
    expected_source_center = [target_center[0] - gap_mm, target_center[1], target_center[2]]
    if registration["source_exit_center_instrument_mm"] != expected_source_center:
        raise ValueError("S2 source exit center does not realize the frozen gap")

    local_center = registration["source_exit_center_local_mm"]
    rotated_center = [sum(rotation[row][col] * local_center[col] for col in range(3)) for row in range(3)]
    expected_translation = [expected_source_center[index] - rotated_center[index] for index in range(3)]
    for index, value in enumerate(registration["source_component_pose"]["translation_mm"]):
        _assert_close(value, expected_translation[index], f"source translation[{index}]")

    geometry = contract["passive_connector_geometry"]
    if geometry.get("zero_gap_supported") is not True:
        raise ValueError("S2 geometry must support direct mating at zero gap")
    if geometry.get("cavity", {}).get("creation_condition") != "connector_gap_mm > 0":
        raise ValueError("S2 connector-domain creation rule differs")
    source_radius = float(interface["boundaries"]["source_exit_surface"]["physical_aperture"]["radius_mm"])
    _assert_close(geometry["upstream_clear_aperture"]["radius_mm"], source_radius, "upstream aperture radius")
    _assert_close(geometry["cavity"]["inner_radius_mm"], source_radius, "connector cavity radius")
    _assert_close(geometry["length_mm"], gap_mm, "connector length")
    _assert_close(geometry["axial_extent_x_mm"][1] - geometry["axial_extent_x_mm"][0], gap_mm, "connector axial extent")

    downstream = geometry["downstream_entry_aperture"]
    _assert_close(downstream["full_width_y_mm"], s1["port_sweep"]["selected_n100_candidate_full_width_y_mm"], "oa port width")
    _assert_close(downstream["full_height_z_mm"], s1["port_sweep"]["full_height_z_mm"], "oa port height")
    if downstream["center_mm"] != target_center:
        raise ValueError("S2 downstream aperture center differs")
    if geometry["secondary_internal_aperture_allowed"] or geometry["active_electrode_allowed"]:
        raise ValueError("S2 must remain a passive connector without a second aperture")

    fields = contract["field_ownership"]
    _assert_close(fields["common_ground_V"], 0.0, "common ground")
    if fields["oa_extraction_pulse_included"]:
        raise ValueError("S2 must not include oa pulse capture")
    field_candidate = contract["no_pulse_field_candidate"]
    if field_candidate["required_field_bases"] != ["oatof_static", "rf_unit_100_V"]:
        raise ValueError("S2 no-pulse field bases differ")
    unit_pattern = [abs(float(value)) for value in s1["field_basis"]["rf_unit"]["rod_differential_pattern_V"]]
    if any(value != float(field_candidate["rf_unit_voltage_V"]) for value in unit_pattern):
        raise ValueError("S2 RF unit voltage differs from the inherited rod pattern")
    if set(field_candidate["required_probe_locations"]) != {
        "rf_rod_region_off_axis",
        "rf_exit_center",
        "connector_midpoint",
        "oatof_entry_center",
        "oatof_ideal_source_center",
    }:
        raise ValueError("S2 no-pulse field probes differ")
    if not 0 < float(field_candidate["rf_off_axis_probe_radius_mm"]) < float(rf["geometry_mm"]["field_radius_r0"]):
        raise ValueError("S2 RF off-axis probe must remain inside r0")
    mesh = field_candidate["mesh"]
    if mesh["global_auto_level"] != 6 or mesh["convergence_claim_allowed"]:
        raise ValueError("S2 no-pulse field mesh scope differs")
    if float(mesh["accelerator_hmax_mm"]) <= 0 or float(mesh["connector_and_port_hmax_mm"]) <= 0:
        raise ValueError("S2 no-pulse field mesh sizes must be positive")
    _assert_close(
        field_candidate["boundary_probe_inset_mm"],
        s1["port_sweep"]["particle_release_offset_inside_outer_face_mm"],
        "S2 boundary probe inset",
    )
    permissions = contract["permissions"]
    if not permissions["field_solve_allowed"] or not permissions["particle_runtime_allowed"]:
        raise ValueError("S2 must authorize the field and nominal N=100 particle candidate")
    if not stage["static_contract"]["field_solve_allowed"]:
        raise ValueError("S2 stage plan does not authorize the no-pulse field candidate")
    if not stage["static_contract"]["particle_runtime_allowed"]:
        raise ValueError("S2 stage plan does not authorize the nominal particle candidate")
    if permissions["s2_stage_pass_allowed"] or permissions["formal_promotion_allowed"]:
        raise ValueError("Static S2 contract cannot authorize qualification or promotion")
    evidence = contract["geometry_build_evidence"]
    if evidence["status"] != "PASS" or evidence["run_id"] != stage["geometry_build_evidence"]["run_id"]:
        raise ValueError("S2 geometry-build evidence differs from the stage plan")
    if evidence["connector_domain_count"] < 1 or evidence["port_domain_count"] < 1:
        raise ValueError("S2 geometry-build vacuum selections are empty")
    if evidence["mesh_built"] or evidence["physics_created"] or evidence["field_solved"] or evidence["particle_runtime_executed"]:
        raise ValueError("S2 build-only evidence contains an unauthorized runtime step")
    field_evidence = contract["no_pulse_field_evidence"]
    stage_field_evidence = stage["no_pulse_field_evidence"]
    if field_evidence["status"] != "PASS" or field_evidence["run_id"] != stage_field_evidence["run_id"]:
        raise ValueError("S2 no-pulse field evidence differs from the stage plan")
    if field_evidence["field_bases_solved"] != 2 or field_evidence["probe_count"] != 5:
        raise ValueError("S2 no-pulse field evidence is incomplete")
    if not field_evidence["all_probe_values_finite"] or float(field_evidence["rf_off_axis_field_norm_V_per_m"]) <= 0:
        raise ValueError("S2 no-pulse field evidence is nonfinite or physically trivial")
    if field_evidence["particle_runtime_executed"] or field_evidence["oa_extraction_pulse_included"]:
        raise ValueError("S2 no-pulse field evidence contains unauthorized runtime physics")
    if field_evidence["mesh_convergence_claimed"] or field_evidence["s2_stage_passed"] or field_evidence["formal_gate_passed"]:
        raise ValueError("S2 no-pulse field evidence overclaims qualification")
    particles = contract["functional_candidate"]
    if particles["source_particles"] != 100 or not particles["source_run_id"].endswith("__n100__r02"):
        raise ValueError("S2 particle source identity differs")
    if particles["source_event_path"] != "results/rf_hybrid_mesh_n100_events.csv":
        raise ValueError("S2 particle source event path differs")
    if particles["source_operating_point"] != "rf_to_oatof_100amu_5eV":
        raise ValueError("S2 particle source operating point differs")
    if particles["rf_steps_per_period"] < 40 or float(particles["connector_transit_time_margin_factor"]) < 1:
        raise ValueError("S2 particle integration controls are invalid")
    if particles["minimum_oatof_entry_crossings"] < 1:
        raise ValueError("S2 particle candidate must require an oa-entry crossing")
    if particles["minimum_detector_hits"] is not None:
        raise ValueError("S2 passive-connector scope must not claim downstream detector hits")
    if set(particles["required_census"]) != {
        "rf_exit", "connector_entry", "connector_wall_loss",
        "downstream_entry_wall_loss", "oatof_entry",
    }:
        raise ValueError("S2 particle census differs")
    particle_evidence = contract["nominal_particle_evidence"]
    stage_particle_evidence = stage["nominal_particle_evidence"]
    if particle_evidence["status"] != "PASS" or particle_evidence["run_id"] != stage_particle_evidence["run_id"]:
        raise ValueError("S2 nominal particle evidence differs from the stage plan")
    if particle_evidence["source_particles"] != 100:
        raise ValueError("S2 nominal particle evidence input count differs")
    if particle_evidence["oatof_entry_crossings"] + particle_evidence["downstream_entry_wall_losses"] != 100:
        raise ValueError("S2 nominal particle evidence census is incomplete")
    if particle_evidence["oatof_entry_crossings"] < particles["minimum_oatof_entry_crossings"]:
        raise ValueError("S2 nominal particle evidence misses the functional minimum")
    if particle_evidence["maximum_clock_residual_us"] > particles["audit_tolerances"]["clock_residual_us"]:
        raise ValueError("S2 nominal particle clock residual exceeds the contract")
    if particle_evidence["maximum_energy_velocity_relative_residual"] > particles["audit_tolerances"]["energy_velocity_relative_residual"]:
        raise ValueError("S2 nominal particle energy residual exceeds the contract")
    if particle_evidence["oa_extraction_pulse_included"] or particle_evidence["mesh_convergence_claimed"]:
        raise ValueError("S2 nominal particle evidence contains unauthorized claims")
    if particle_evidence["s2_stage_passed"] or particle_evidence["formal_gate_passed"]:
        raise ValueError("S2 nominal particle evidence overclaims qualification")
    return contract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract = validate_contract(args.contract)
    gap_mm = contract["nominal_registration"]["connector_gap_mm"]
    print(
        "S2_PASSIVE_CONNECTOR=PASS "
        f"GAP_MM={gap_mm:g} FIELD_SOLVE_ALLOWED=true PARTICLE_RUNTIME_ALLOWED=true"
    )


if __name__ == "__main__":
    main()
