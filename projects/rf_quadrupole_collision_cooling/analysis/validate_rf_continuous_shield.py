"""Validate the solver-neutral continuous grounded RF shield candidate."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_continuous_grounded_shield_candidate.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = load(path)
    if contract.get("schema_version") != 1 or contract.get("status") != "approved_parameter_sweep_for_solver_validation":
        raise ValueError("continuous RF shield candidate identity is invalid")
    inputs = contract["inputs"]
    rf = load(PROJECT_ROOT / inputs["rf_resolved_geometry"])
    audit = contract["audit"]
    if audit.get("formal_geometry_already_shielded") is not False or audit.get("cad_authority_present") is not False:
        raise ValueError("continuous RF shield audit overstates current authority")

    geometry = contract["candidate_geometry_mm"]
    rf_geometry = rf["geometry_mm"]
    rod_outer = float(rf_geometry["rod_center_radius"]) + float(rf_geometry["rod_radius"])
    expected = {
        "rf_local_z_min": float(rf_geometry["entrance_plate_z_max"]),
        "rf_local_z_max": float(rf_geometry["exit_enclosure_z_min"]),
        "rod_outer_extent": rod_outer,
    }
    if geometry.get("cross_section") != "circular_cylinder_coaxial_with_rf_axis":
        raise ValueError("continuous RF shield must remain coaxial and cylindrical")
    for key, value in expected.items():
        if not math.isclose(float(geometry.get(key, -1.0)), value, abs_tol=1e-12):
            raise ValueError(f"continuous RF shield derived value changed: {key}")
    ratios = [float(value) for value in geometry.get("inner_radius_ratio_to_rod_outer_extent_sweep", [])]
    radii = [float(value) for value in geometry.get("inner_radius_mm_sweep", [])]
    if ratios != [1.5, 2.0, 3.0] or len(radii) != len(ratios):
        raise ValueError("continuous RF shield radius sweep is not frozen")
    if any(not math.isclose(radius, ratio * rod_outer, abs_tol=1e-12) for ratio, radius in zip(ratios, radii)):
        raise ValueError("continuous RF shield radius sweep is not derived from the rod extent")
    if any(radius <= rod_outer for radius in radii):
        raise ValueError("continuous RF shield intersects the RF rods")
    if geometry.get("selected_inner_radius_mm") is not None:
        raise ValueError("continuous RF shield radius may not be selected before validation")
    if geometry.get("oa_accelerator_outer_size_dependency_allowed") is not False:
        raise ValueError("RF shield size must be independent of oa accelerator size")
    if geometry.get("field_model_wall_thickness_required") is not False:
        raise ValueError("electrostatic candidate should use a conductive boundary without meshing wall thickness")
    if geometry.get("cad_wall_thickness_mm") is not None:
        raise ValueError("mechanical wall thickness has not been selected")

    screen = contract["two_dimensional_field_screen"]
    if [float(value) for value in screen.get("rod_potential_pattern_V", [])] != [100.0, -100.0, 100.0, -100.0]:
        raise ValueError("continuous RF shield unit-field pattern is invalid")
    if screen.get("global_mesh_auto_level") != 6:
        raise ValueError("continuous RF shield 2D global mesh level is not frozen")
    if [float(value) for value in screen.get("local_maximum_element_size_mm", [])] != [0.2, 0.1]:
        raise ValueError("continuous RF shield local mesh sequence is invalid")
    if [float(value) for value in screen.get("sample_radius_fraction_of_r0", [])] != [0.25, 0.5, 0.75, 0.9]:
        raise ValueError("continuous RF shield radial samples are invalid")
    if screen.get("azimuth_samples_per_radius") != 72 or screen.get("reported_fourier_orders") != [2, 6, 10]:
        raise ValueError("continuous RF shield harmonic sampling is invalid")
    evidence = contract["two_dimensional_screen_evidence"]
    if evidence.get("status") != "characterized_candidates_reduced_for_3d_validation":
        raise ValueError("continuous RF shield 2D evidence status is invalid")
    if [float(value) for value in evidence.get("retained_inner_radius_mm_for_3d", [])] != [19.776, 26.368]:
        raise ValueError("continuous RF shield 3D candidates are not frozen")
    if evidence.get("selected_inner_radius_mm") is not None:
        raise ValueError("2D evidence may not select the physical shield")
    if float(evidence["radius_19p776_mesh_0p2_to_0p1"]["field_magnitude_rms_relative_change"]) >= 1e-4:
        raise ValueError("continuous RF shield coarse 2D mesh is not sufficiently stable")

    fringe = contract["three_dimensional_fringe_field_screen"]
    if fringe.get("status") != "characterized_mesh_pair_and_radius_pair":
        raise ValueError("continuous RF shield 3D field status is invalid")
    if [float(value) for value in fringe.get("inner_radius_mm", [])] != [19.776, 26.368]:
        raise ValueError("continuous RF shield 3D radius sequence is invalid")
    if fringe.get("external_vacuum_included") is not False or fringe.get("feedthroughs_included") is not False:
        raise ValueError("continuous RF shield 3D scope overstates the candidate geometry")
    if [float(value) for value in fringe.get("rod_potential_pattern_V", [])] != [100.0, -100.0, 100.0, -100.0]:
        raise ValueError("continuous RF shield 3D unit-field pattern is invalid")
    if fringe.get("global_mesh_auto_level") != 6:
        raise ValueError("continuous RF shield 3D global mesh level is not frozen")
    if fringe.get("global_mesh_auto_level_particle_stability_sequence") != [6, 5, 4, 3, 2]:
        raise ValueError("continuous RF shield 3D global refinement sequence changed")
    if not math.isclose(float(fringe.get("physical_work_region_radius_r0_mm", -1.0)), float(rf_geometry["field_radius_r0"]), abs_tol=1e-12):
        raise ValueError("continuous RF shield physical work-region radius changed")
    if not math.isclose(float(fringe.get("local_mesh_partition_radius_mm", -1.0)), 3.6, abs_tol=1e-12):
        raise ValueError("continuous RF shield 3D mesh-partition radius changed")
    if not math.isclose(float(fringe.get("local_mesh_partition_z_min_mm", -1.0)), 81.4, abs_tol=1e-12):
        raise ValueError("continuous RF shield 3D mesh-partition start changed")
    if not math.isclose(float(fringe.get("local_mesh_partition_z_max_mm", -1.0)), float(rf_geometry["exit_enclosure_front_wall_end_z"]), abs_tol=1e-12):
        raise ValueError("continuous RF shield 3D mesh-partition end changed")
    if [float(value) for value in fringe.get("local_maximum_element_size_mm", [])] != [0.5, 0.25]:
        raise ValueError("continuous RF shield 3D local mesh sequence is invalid")
    if [float(value) for value in fringe.get("sample_z_mm", [])] != [45.6, 83.4, 85.4, 87.4, 89.4, 90.2]:
        raise ValueError("continuous RF shield 3D axial sample sequence is invalid")
    if [float(value) for value in fringe.get("sample_radius_fraction_of_r0", [])] != [0.25, 0.5, 0.75, 0.9]:
        raise ValueError("continuous RF shield 3D radial samples are invalid")
    if not math.isclose(float(fringe.get("boundary_evaluation_inset_mm", -1.0)), 0.001, abs_tol=1e-12):
        raise ValueError("continuous RF shield 3D boundary evaluation inset changed")
    if fringe.get("azimuth_samples_per_radius") != 72 or fringe.get("reported_fourier_orders") != [2, 6, 10]:
        raise ValueError("continuous RF shield 3D harmonic sampling is invalid")
    evidence_3d = contract["three_dimensional_screen_evidence"]
    if evidence_3d.get("status") != "field_characterized_particle_function_unresolved":
        raise ValueError("continuous RF shield 3D evidence status is invalid")
    if evidence_3d.get("selected_inner_radius_mm") is not None:
        raise ValueError("continuous RF shield 3D evidence may not select a radius")
    core = evidence_3d["maximum_relative_vector_rms_fringe_region_r_le_2_mm"]
    if not math.isclose(float(core["hmax_0p5_to_0p25"]), 0.028413851866361545, abs_tol=1e-15):
        raise ValueError("continuous RF shield 3D mesh evidence changed")
    if not math.isclose(float(core["radius_19p776_to_26p368_at_hmax_0p5"]), 0.003273830831381418, abs_tol=1e-15):
        raise ValueError("continuous RF shield 3D radius evidence changed")
    transport = contract["n100_transport_screen"]
    if transport.get("status") != "approved_for_auto4_auto3_paired_particle_diagnostic":
        raise ValueError("continuous RF shield N=100 diagnostic status is invalid")
    if transport.get("particle_count") != 100 or transport.get("selection_allowed") is not False:
        raise ValueError("continuous RF shield N=100 contract is invalid")
    expected_transport = {
        "rf_peak_V": 139.81792,
        "rf_frequency_Hz": 1100000.0,
        "rf_phase_rad": 0.0,
        "rf_steps_per_period": 80,
        "maximum_particle_age_us": 80.0,
        "nominal_handoff_z_mm": float(rf_geometry["exit_enclosure_front_wall_end_z"]),
        "handoff_evaluation_inset_mm": 0.001,
    }
    for key, value in expected_transport.items():
        if not math.isclose(float(transport.get(key, -1.0)), value, abs_tol=1e-12):
            raise ValueError(f"continuous RF shield N=100 setting changed: {key}")
    if transport.get("source_particle_table_sha256") != "555A5F46B3D2EE58027F600ECC23912FC2180F74DDE4E63EC8A2EC6574C264DF":
        raise ValueError("continuous RF shield N=100 source identity changed")
    particle_evidence = contract["n100_mesh_sensitivity_evidence"]
    if particle_evidence.get("status") != "failed_local_hmax_pair_global_background_refinement_required":
        raise ValueError("continuous RF shield N=100 evidence status is invalid")
    if particle_evidence.get("acceptance_decision") != "FAIL" or particle_evidence.get("classification_change_count") != 5:
        raise ValueError("continuous RF shield N=100 FAIL evidence changed")
    if particle_evidence.get("classification_changed_particle_ids") != [2, 10, 56, 62, 97]:
        raise ValueError("continuous RF shield N=100 classification evidence changed")
    background = contract["global_background_field_evidence"]
    if background.get("status") != "auto4_auto3_particle_pair_approved":
        raise ValueError("continuous RF shield global background evidence status is invalid")
    midpoint = background["auto3_midpoint_relative_to_converged_2d"]
    if float(midpoint["quadrupole_amplitude"]) >= 0.002 or float(midpoint["transverse_field_rms"]) >= 0.002:
        raise ValueError("continuous RF shield auto3 midpoint is not sufficiently close to the converged 2D reference")

    electrical = contract["electrical_contract"]
    if float(electrical.get("potential_V", 1.0)) != 0.0:
        raise ValueError("continuous RF shield must retain the common 0 V reference")
    if electrical.get("external_vacuum_field_domain_required") is not False:
        raise ValueError("continuous RF shield must exclude external vacuum from the electric-field domain")
    if electrical.get("interior_vacuum_only") is not True:
        raise ValueError("continuous RF shield field domain must remain interior-only")
    if electrical.get("feedthrough_claim_allowed") is not False:
        raise ValueError("unmodeled RF feedthroughs may not receive a shielding claim")

    validation = contract["required_candidate_validation"]
    if validation.get("logical_operator") != "AND" or not all(
        value is True for key, value in validation.items() if key != "logical_operator"
    ):
        raise ValueError("continuous RF shield validation requirements are incomplete")
    permissions = contract["permissions"]
    if permissions.get("formal_asset_modification_allowed") is not False:
        raise ValueError("continuous RF shield candidate may not modify formal assets")
    if permissions.get("formal_promotion_allowed") is not False:
        raise ValueError("continuous RF shield candidate may not promote itself")
    return contract


def main() -> None:
    contract = validate()
    geometry = contract["candidate_geometry_mm"]
    print(
        "RF_CONTINUOUS_GROUNDED_SHIELD=PASS "
        f"INNER_RADIUS_SWEEP_MM={','.join(str(value) for value in geometry['inner_radius_mm_sweep'])} "
        "FORMAL_PROMOTION_ALLOWED=false"
    )


if __name__ == "__main__":
    main()
