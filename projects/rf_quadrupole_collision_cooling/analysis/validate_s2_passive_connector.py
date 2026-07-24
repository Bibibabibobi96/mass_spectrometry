"""Validate the solver-neutral S2 passive connector geometry contract."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_ROOT = Path(__file__).parents[1]
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json"
DEFAULT_REGISTRATION = (
    PROJECT_ROOT / "config" / "resolved_rf_to_oatof_s2_spatial_registration.json"
)
DEPENDENCY_CONSUMERS = {
    "s2_passive_connector", "s3_pulse_capture", "s3_end_to_end",
}
S2_DEPENDENCY_IDS = {
    "oatof_baseline", "oatof_accelerator_geometry_builder",
    "oatof_rf_handoff_adapter", "rf_legacy_component_state_migrator",
    "rf_interface_stage_plan", "rf_shared_joint_geometry", "rf_resolved_design",
    "rf_dependency_contract_snapshot", "common_rigid_transform",
    "common_particle_physics", "common_component_particle_state",
    "common_component_particle_state_schema", "common_file_identity",
    "common_spatial_registration", "common_verify_run_manifest",
    "common_artifact_naming", "common_write_run_manifest",
    "common_run_artifact_support", "common_require_powershell7",
    "common_comsol_runner", "common_comsol_resolver",
    "common_comsol_failure_classifier", "common_comsol_environment",
    "common_comsol_startup",
}
DEPENDENCY_COMPATIBILITY_FILENAMES = {
    "oatof_baseline": "oatof_baseline.json",
    "oatof_accelerator_geometry_builder": "oatof_build_accelerator_geometry.m",
}


def _load_relative(path: str, reference_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    resolved = (reference_root / path).resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _assert_close(actual: float, expected: float, name: str) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{name} differs: expected {expected}, got {actual}")


def _json_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer}")
    value = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def validate_contract(
    path: Path = DEFAULT_CONTRACT, reference_root: Path = PROJECT_ROOT,
    registration_path: Path = DEFAULT_REGISTRATION,
) -> dict[str, Any]:
    """Validate inherited geometry, rigid poses and fail-closed S2 permissions."""
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("role") != "rf_to_oatof_s2_passive_grounded_connector_candidate":
        raise ValueError("S2 connector role differs")
    if contract.get("stage") != "S2":
        raise ValueError("S2 connector stage differs")

    stage_plan = _load_relative(contract["inputs"]["stage_plan"], reference_root)
    if stage_plan.get("current_stage") not in {"S2", "S3", "S4", "S5"}:
        raise ValueError("stage plan has not reached or inherited S2")
    stage = next(item for item in stage_plan["stages"] if item["id"] == "S2")
    if stage.get("status") != "nominal_no_pulse_particle_function_passed_stage_unqualified":
        raise ValueError("S2 stage status differs")

    dependency_contract = _load_relative(
        contract["inputs"]["explicit_dependencies"], reference_root)
    if dependency_contract.get("schema_version") != 2:
        raise ValueError("S2 dependency-contract schema differs")
    if dependency_contract.get("role") != "rf_to_oatof_s2_s3_explicit_source_dependencies":
        raise ValueError("S2 dependency-contract role differs")
    if dependency_contract.get("consumer_project") != "rf_quadrupole_collision_cooling":
        raise ValueError("S2 dependency consumer differs")
    if set(dependency_contract.get("consumer_ids", [])) != DEPENDENCY_CONSUMERS:
        raise ValueError("S2 dependency consumer identities differ")
    dependencies = dependency_contract.get("dependencies", [])
    dependency_ids = [item.get("id") for item in dependencies]
    run_input_names = [item.get("run_input_name") for item in dependencies]
    frozen_filenames = [item.get("frozen_filename") for item in dependencies]
    compatibility_filenames = [
        item["compatibility_frozen_filename"] for item in dependencies
        if "compatibility_frozen_filename" in item
    ]
    if (
        not dependencies
        or len(set(dependency_ids)) != len(dependency_ids)
        or len(set(run_input_names)) != len(run_input_names)
        or len(set(frozen_filenames)) != len(frozen_filenames)
        or len(set(compatibility_filenames)) != len(compatibility_filenames)
    ):
        raise ValueError("dependency identities and frozen destinations must be unique")
    for dependency in dependencies:
        dependency_id = dependency.get("id")
        provider = str(dependency.get("provider_project", ""))
        provider_scope = dependency.get("provider_scope")
        provider_root = PurePosixPath(str(dependency.get("provider_repo_path", "")))
        source = PurePosixPath(str(dependency.get("source_repo_path", "")))
        frozen = PurePosixPath(str(dependency.get("frozen_filename", "")))
        consumers = dependency.get("consumers")
        if provider_scope == "project":
            expected_provider_root = PurePosixPath("projects") / provider
        elif provider_scope == "repository_common" and provider == "common":
            expected_provider_root = PurePosixPath("common")
        else:
            raise ValueError(f"dependency {dependency_id} provider scope differs")
        if provider_root != expected_provider_root:
            raise ValueError(f"dependency {dependency_id} provider root differs")
        if (
            source.is_absolute()
            or source.parts[:len(provider_root.parts)] != provider_root.parts
            or ".." in source.parts
        ):
            raise ValueError(f"dependency {dependency_id} escapes its provider")
        if frozen != PurePosixPath("runtime_snapshot") / source or ".." in frozen.parts:
            raise ValueError(f"dependency {dependency_id} frozen path differs")
        compatibility = dependency.get("compatibility_frozen_filename")
        expected_compatibility = DEPENDENCY_COMPATIBILITY_FILENAMES.get(dependency_id)
        if compatibility != expected_compatibility:
            raise ValueError(f"dependency {dependency_id} compatibility path differs")
        if compatibility is not None:
            compatibility_path = PurePosixPath(compatibility)
            if compatibility_path.is_absolute() or ".." in compatibility_path.parts:
                raise ValueError(f"dependency {dependency_id} compatibility path escapes")
        if (
            not isinstance(consumers, list)
            or not consumers
            or not set(consumers) <= DEPENDENCY_CONSUMERS
            or len(set(consumers)) != len(consumers)
        ):
            raise ValueError(f"dependency {dependency_id} consumers differ")
        source_path = reference_root.parents[1].joinpath(*source.parts)
        if "s2_passive_connector" in consumers and not source_path.is_file():
            raise ValueError(f"S2 dependency {dependency.get('id')} source is missing")
    s2_dependency_ids = {
        item["id"] for item in dependencies
        if "s2_passive_connector" in item["consumers"]
    }
    if s2_dependency_ids != S2_DEPENDENCY_IDS:
        raise ValueError("S2 consumer dependency subset differs")
    policy = dependency_contract.get("runtime_policy", {})
    if (
        not policy.get("verify_source_and_frozen_sha256_equal")
        or not policy.get("preserve_repo_relative_snapshot_paths")
        or not policy.get("consumer_scoped_selection_required")
        or policy.get("allow_directory_search")
    ):
        raise ValueError("S2 dependency runtime policy is not fail-closed")

    shared_joint = _load_relative(
        contract["inputs"]["shared_physical_port_joint_geometry"], reference_root
    )
    if shared_joint.get("role") != "rf_to_oatof_shared_physical_port_joint_geometry":
        raise ValueError("S2 shared physical-port authority differs")
    expected_authorities = {
        "rf_resolved_geometry": contract["inputs"]["rf_resolved_geometry"],
        "oatof_baseline": contract["inputs"]["oatof_baseline"],
    }
    if shared_joint.get("authoritative_inputs") != expected_authorities:
        raise ValueError("S2 and shared physical-port authoritative inputs differ")
    rf = _load_relative(contract["inputs"]["rf_resolved_geometry"], reference_root)
    oatof = _load_relative(contract["inputs"]["oatof_baseline"], reference_root)
    source_boundary = shared_joint["physical_boundaries"]["source_exit_surface"]
    target_boundary = shared_joint["physical_boundaries"]["target_entry_surface"]
    expected_source_bindings = {
        "local_center_z_mm": {
            "source_input": "rf_resolved_geometry",
            "json_pointer": "/interfaces_mm/exit/connector_z_max_mm",
        },
        "outward_normal": {
            "source_input": "rf_resolved_geometry",
            "json_pointer": "/coordinate/axial_axis",
            "expected_source_value": "+z",
        },
    }
    if source_boundary.get("bindings") != expected_source_bindings:
        raise ValueError("shared source-exit bindings differ")
    if source_boundary.get("frame_id") != "rf_quadrupole_component":
        raise ValueError("shared source-exit frame differs")
    if source_boundary.get("geometry") != "plane":
        raise ValueError("shared source-exit geometry differs")
    _assert_close(
        source_boundary["local_center_mm"][2],
        _json_pointer(rf, "/interfaces_mm/exit/connector_z_max_mm"),
        "shared source-exit center binding",
    )
    if (
        _json_pointer(rf, "/coordinate/axial_axis") != "+z"
        or source_boundary["outward_normal"] != [0.0, 0.0, 1.0]
    ):
        raise ValueError("shared source-exit normal binding differs")
    aperture = source_boundary["physical_aperture"]
    if aperture.get("source_binding") != {
        "source_input": "rf_resolved_geometry",
        "json_pointer": "/interfaces_mm/exit/aperture_radius_mm",
    }:
        raise ValueError("shared source-exit aperture source differs")
    _assert_close(
        aperture["radius_mm"],
        _json_pointer(rf, "/interfaces_mm/exit/aperture_radius_mm"),
        "shared source-exit aperture binding",
    )
    target_binding = target_boundary["reference_binding"]
    expected_target_pointers = [
        "/coordinate_convention/frame_id",
        "/coordinate_convention/accelerator_axis_x",
        "/geometry_mm/accelerator_bore_half",
        "/geometry_mm/accelerator_ring_width",
        "/geometry_mm/accelerator_insulation_gap",
        "/geometry_mm/accelerator_shield_wall",
        "/particle_source/center_y_mm",
        "/particle_source/center_z_mm",
    ]
    if (
        target_binding.get("source_input") != "oatof_baseline"
        or target_binding.get("json_pointers") != expected_target_pointers
    ):
        raise ValueError("shared target-entry source binding differs")
    target_center_from_oatof = [
        float(oatof["coordinate_convention"]["accelerator_axis_x"])
        - sum(
            float(oatof["geometry_mm"][key])
            for key in (
                "accelerator_bore_half",
                "accelerator_ring_width",
                "accelerator_insulation_gap",
                "accelerator_shield_wall",
            )
        ),
        float(oatof["particle_source"]["center_y_mm"]),
        float(oatof["particle_source"]["center_z_mm"]),
    ]
    if (
        target_boundary.get("frame_id")
        != oatof["coordinate_convention"]["frame_id"]
        or target_boundary.get("center_mm") != target_center_from_oatof
        or target_boundary.get("outward_normal") != [-1.0, 0.0, 0.0]
    ):
        raise ValueError("shared target-entry surface binding differs")
    common_reference = shared_joint["electrical_interface"][
        "common_potential_reference"
    ]
    expected_common_sources = {
        (
            "rf_resolved_geometry",
            "/drive/common_mode_offset_V",
        ): ("rf_axis_reference", "rf_exit_enclosure"),
        (
            "oatof_baseline",
            "/electrodes_V/shield",
        ): ("oatof_accelerator_shield",),
    }
    actual_common_sources = {
        (item["source_input"], item["json_pointer"]): tuple(
            item["electrode_bindings"]
        )
        for item in common_reference["required_equal_source_bindings"]
    }
    if actual_common_sources != expected_common_sources or common_reference["unit"] != "V":
        raise ValueError("shared common-potential bindings differ")
    common_ground = float(common_reference["potential_V"])
    _assert_close(common_ground, rf["drive"]["common_mode_offset_V"], "RF common reference")
    _assert_close(common_ground, oatof["electrodes_V"]["shield"], "oaTOF common reference")
    registration = contract["nominal_registration"]
    gap_mm = float(registration["connector_gap_mm"])
    if gap_mm < 0.0:
        raise ValueError("S2 connector gap cannot be negative")
    spatial = json.loads(registration_path.read_text(encoding="utf-8"))
    if (
        spatial.get("role") != "resolved_spatial_registration_do_not_edit"
        or spatial.get("project_semantics", {}).get("stage") != "S2"
    ):
        raise ValueError("S2 authoritative spatial registration is invalid")
    source_pose = spatial["component_poses"]["rf_quadrupole_component"]
    target_pose = spatial["component_poses"]["oatof_global"]
    if (
        registration["source_component_pose"][
            "rotation_component_to_instrument"
        ] != source_pose["rotation"]
        or registration["source_component_pose"]["translation_mm"]
        != source_pose["translation_mm"]
        or registration["target_component_pose"][
            "rotation_component_to_instrument"
        ] != target_pose["rotation"]
        or registration["target_component_pose"]["translation_mm"]
        != target_pose["translation_mm"]
    ):
        raise ValueError(
            "NEEDS_IMPLEMENTATION: S2 pose differs from resolved registration"
        )
    if not math.isclose(
        gap_mm,
        float(spatial["project_semantics"]["connector_gap_mm"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("S2 connector gap differs from resolved registration")
    rotation = source_pose["rotation"]
    if rotation != shared_joint["nominal_registration"]["source_component_pose"]["rotation_component_to_instrument"]:
        raise ValueError("S2 source rotation must inherit the shared physical-port authority")

    target_center = spatial["resolved_surfaces"]["target_entry"][
        "in_instrument_frame"
    ]["center_mm"]
    if target_boundary["outward_normal"] != spatial["resolved_surfaces"]["target_entry"]["declared"]["normal"]:
        raise ValueError("S2 shared target normal differs from resolved registration")
    if registration["target_entry_center_instrument_mm"] != target_center:
        raise ValueError(
            "NEEDS_IMPLEMENTATION: S2 target entry differs from resolved registration"
        )
    expected_source_center = spatial["resolved_surfaces"]["source_exit"][
        "in_instrument_frame"
    ]["center_mm"]
    if registration["source_exit_center_instrument_mm"] != expected_source_center:
        raise ValueError(
            "NEEDS_IMPLEMENTATION: S2 source exit differs from resolved registration"
        )

    geometry = contract["passive_connector_geometry"]
    if geometry.get("zero_gap_supported") is not True:
        raise ValueError("S2 geometry must support direct mating at zero gap")
    if geometry.get("cavity", {}).get("creation_condition") != "connector_gap_mm > 0":
        raise ValueError("S2 connector-domain creation rule differs")
    source_radius = float(aperture["radius_mm"])
    _assert_close(geometry["upstream_clear_aperture"]["radius_mm"], source_radius, "upstream aperture radius")
    _assert_close(geometry["cavity"]["inner_radius_mm"], source_radius, "connector cavity radius")
    _assert_close(geometry["length_mm"], gap_mm, "connector length")
    _assert_close(geometry["axial_extent_x_mm"][1] - geometry["axial_extent_x_mm"][0], gap_mm, "connector axial extent")

    downstream = geometry["downstream_entry_aperture"]
    _assert_close(downstream["full_width_y_mm"], shared_joint["port_sweep"]["selected_n100_candidate_full_width_y_mm"], "oa port width")
    _assert_close(downstream["full_height_z_mm"], shared_joint["port_sweep"]["full_height_z_mm"], "oa port height")
    if downstream["center_mm"] != target_center:
        raise ValueError("S2 downstream aperture center differs")
    if geometry["secondary_internal_aperture_allowed"] or geometry["active_electrode_allowed"]:
        raise ValueError("S2 must remain a passive connector without a second aperture")

    fields = contract["field_ownership"]
    _assert_close(fields["common_ground_V"], common_ground, "common ground")
    if fields["oa_extraction_pulse_included"]:
        raise ValueError("S2 must not include oa pulse capture")
    field_candidate = contract["no_pulse_field_candidate"]
    if field_candidate["required_field_bases"] != ["oatof_static", "rf_unit_100_V"]:
        raise ValueError("S2 no-pulse field bases differ")
    unit_pattern = [abs(float(value)) for value in shared_joint["field_basis"]["rf_unit"]["rod_differential_pattern_V"]]
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
    if not 0 < float(field_candidate["rf_off_axis_probe_radius_mm"]) < float(
        rf["geometry_mm"]["inscribed_radius_r0"]
    ):
        raise ValueError("S2 RF off-axis probe must remain inside r0")
    mesh = field_candidate["mesh"]
    if mesh["global_auto_level"] != 6 or mesh["convergence_claim_allowed"]:
        raise ValueError("S2 no-pulse field mesh scope differs")
    if float(mesh["accelerator_hmax_mm"]) <= 0 or float(mesh["connector_and_port_hmax_mm"]) <= 0:
        raise ValueError("S2 no-pulse field mesh sizes must be positive")
    _assert_close(
        field_candidate["boundary_probe_inset_mm"],
        shared_joint["port_sweep"]["particle_release_offset_inside_outer_face_mm"],
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
    parser.add_argument("--reference-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--resolved-registration",
        type=Path,
        default=DEFAULT_REGISTRATION,
    )
    args = parser.parse_args()
    contract = validate_contract(
        args.contract,
        args.reference_root,
        args.resolved_registration,
    )
    gap_mm = contract["nominal_registration"]["connector_gap_mm"]
    print(
        "S2_PASSIVE_CONNECTOR=PASS "
        f"GAP_MM={gap_mm:g} FIELD_SOLVE_ALLOWED=true PARTICLE_RUNTIME_ALLOWED=true"
    )


if __name__ == "__main__":
    main()
