"""Validate the solver-neutral S1 local joint-field characterization contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

try:
    import build_interface_handoff as handoff
except ModuleNotFoundError:
    from projects.rf_quadrupole_collision_cooling.analysis import build_interface_handoff as handoff


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_s1_joint_field.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def close_vector(left: list[float], right: list[float]) -> bool:
    return len(left) == len(right) and all(
        math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)
        for a, b in zip(left, right)
    )


def validate(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = load(path)
    if contract.get("schema_version") != 1 or contract.get("stage") != "S1":
        raise ValueError("S1 joint-field contract identity is invalid")
    if contract.get("status") != "field_characterized_n100_physical_port_runtime_ready":
        raise ValueError("S1 joint-field contract is not ready for N=100 physical-port runtime")

    inputs = contract["inputs"]
    interface = load(PROJECT_ROOT / inputs["interface_contract"])
    rf = load(PROJECT_ROOT / inputs["rf_resolved_geometry"])
    load((PROJECT_ROOT / inputs["oatof_baseline"]).resolve())
    oatof_mode = load((PROJECT_ROOT / inputs["oatof_formal_mode"]).resolve())
    pulse_timing = load(PROJECT_ROOT / inputs["pulse_timing_policy"])
    if pulse_timing.get("method") != "selected_species_ballistic_port_survivor_x_centroid":
        raise ValueError("S1 pulse timing policy is not the state-driven centroid scheduler")
    shield = load(PROJECT_ROOT / inputs["rf_continuous_shield_candidate"])
    if shield.get("status") != "smallest_radius_retained_for_s1_candidate_validation":
        raise ValueError("S1 continuous RF shield radius is not retained for candidate validation")
    shield_geometry = shield["candidate_geometry_mm"]
    if not math.isclose(float(shield_geometry.get("selected_inner_radius_mm", -1.0)), 19.776, abs_tol=1e-12):
        raise ValueError("S1 continuous RF shield candidate radius differs from 19.776 mm")
    experiment = load(PROJECT_ROOT / inputs["field_performance_experiment"])
    if experiment.get("role") != "rf_to_oatof_field_to_particle_performance_calibration_plan":
        raise ValueError("S1 field-performance experiment identity is invalid")
    if experiment.get("formal_baseline_policy", {}).get("formal_baseline_count") != 1:
        raise ValueError("RF-to-oa performance calibration must retain one formal baseline")
    registration = contract["nominal_registration"]
    source_pose = registration["source_component_pose"]
    target_pose = registration["target_component_pose"]
    derived = handoff.derive_target_from_source_pose(
        source_pose["rotation_component_to_instrument"],
        source_pose["translation_mm"],
        target_pose["rotation_component_to_instrument"],
        target_pose["translation_mm"],
    )
    expected_rotation = [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    if derived["rotation_source_to_target"] != expected_rotation:
        raise ValueError("S1 nominal rotation does not map RF +z to oa +x")
    source_exit = handoff.transform_phase_space(
        registration["source_exit_center_local_mm"],
        [0.0, 0.0, 1.0],
        derived["rotation_source_to_target"],
        derived["translation_mm"],
    )
    target_entry = interface["boundaries"]["target_entry_surface"]["center_mm"]
    if not close_vector(source_exit["position_mm"], target_entry):
        raise ValueError("S1 source exit does not coincide with the oa entry face")
    if not close_vector(registration["source_exit_center_instrument_mm"], target_entry):
        raise ValueError("S1 declared source-exit center differs from the interface contract")
    if not close_vector(registration["target_entry_center_instrument_mm"], target_entry):
        raise ValueError("S1 declared target-entry center differs from the interface contract")
    if float(registration["direct_mating_gap_mm"]) != 0.0:
        raise ValueError("S1 must remain the zero-gap direct-mating reference")

    local = contract["local_domain"]
    source_exit_z = float(interface["boundaries"]["source_exit_surface"]["z_mm"])
    if not math.isclose(float(local["rf_local_z_max_mm"]), source_exit_z, abs_tol=1e-12):
        raise ValueError("S1 RF geometry must be trimmed at the handoff plane")
    if float(local["rf_local_z_max_mm"]) >= float(rf["geometry_mm"]["exit_enclosure_z_max"]):
        raise ValueError("S1 local domain includes forbidden standalone acceptance hardware")
    if not math.isclose(
        float(local.get("rf_shield_inner_radius_mm", -1.0)),
        float(shield_geometry["selected_inner_radius_mm"]), abs_tol=1e-12,
    ):
        raise ValueError("S1 local-domain RF shield radius differs from the retained candidate")
    if not math.isclose(float(local.get("rf_shield_numerical_wall_thickness_mm", -1.0)), 1.0, abs_tol=1e-12):
        raise ValueError("S1 numerical RF shield wall thickness changed")
    if local.get("rf_shield_wall_thickness_claim_allowed") is not False:
        raise ValueError("S1 numerical RF shield wall may not become a mechanical claim")
    if [float(value) for value in local.get("oatof_downstream_buffer_diagnostic_mm", [])] != [5.0, 15.0, 30.0]:
        raise ValueError("S1 downstream local-domain convergence values are not frozen")
    if [float(value) for value in local.get("legacy_external_vacuum_diagnostic_margin_mm", [])] != [1.0, 10.0, 30.0]:
        raise ValueError("S1 historical outer-vacuum diagnostics are not preserved")
    if local.get("external_vacuum_field_domain_included") is not False:
        raise ValueError("S1 shielded candidate must exclude external vacuum")
    if "350 mm" not in local.get("interior_vacuum_rule", ""):
        raise ValueError("S1 must explicitly forbid the 350 mm connector sweep domain")
    forbidden = " ".join(local["excluded"]).lower()
    if not all(name in forbidden for name in ("flight tube", "reflectron", "detector", "particle")):
        raise ValueError("S1 local-domain exclusions are incomplete")

    aperture = interface["connector"]["entry_aperture_design"]
    sweep = contract["port_sweep"]
    if sweep["shape"] != aperture["shape"]:
        raise ValueError("S1 port shape differs from the interface contract")
    if not math.isclose(
        float(sweep["full_height_z_mm"]),
        float(aperture["design_full_height_z_mm"]), abs_tol=1e-12,
    ):
        raise ValueError("S1 port height differs from the frozen 90% theory value")
    widths = [float(value) for value in sweep["full_width_y_mm"]]
    reference_width = float(
        aperture["field_uniformity_reference"]["closed_shield_contiguous_full_width_y_mm"]
    )
    if not widths or any(value <= 0.0 or value > reference_width for value in widths):
        raise ValueError("S1 width sweep exceeds the closed-shield L0 reference")
    if widths != sorted(set(widths), reverse=True):
        raise ValueError("S1 width sweep must be unique and descending")
    if not math.isclose(float(sweep.get("closed_control_full_width_y_mm", -1.0)), 0.0, abs_tol=1e-12):
        raise ValueError("S1 closed local-domain control must have zero opening width")
    if not math.isclose(
        float(sweep.get("closed_control_evaluation_full_width_y_mm", -1.0)),
        reference_width, abs_tol=1e-12,
    ):
        raise ValueError("S1 closed control must be evaluated over the formal source width")
    if "exact +/- port half-width" not in sweep.get("sampling_rule", ""):
        raise ValueError("S1 field sampling must include the exact port edge")
    if sweep.get("selection_allowed") is not True:
        raise ValueError("S1 field characterization must retain one N=100 runtime candidate")
    if not math.isclose(float(sweep.get("selected_n100_candidate_full_width_y_mm", -1.0)), widths[0], abs_tol=1e-12):
        raise ValueError("S1 N=100 runtime must use the largest characterized width")
    release_offset = float(sweep.get("particle_release_offset_inside_outer_face_mm", math.nan))
    if not math.isclose(release_offset, 0.001, abs_tol=1e-12):
        raise ValueError("S1 particle release offset must remain explicit and inside the outer shield face")
    if "no performance or Formal selection" not in sweep.get("selection_scope", ""):
        raise ValueError("S1 N=100 width selection overstates its authority")

    basis = contract["field_basis"]
    if basis.get("shared_geometry_required") is not True:
        raise ValueError("RF and oa field bases must use one joint geometry")
    pattern = [float(value) for value in basis["rf_unit"]["rod_differential_pattern_V"]]
    if pattern != [100.0, -100.0, 100.0, -100.0]:
        raise ValueError("S1 RF unit-field rod pattern is invalid")
    field_reference = aperture["field_uniformity_reference"]
    if field_reference.get("status") != "closed_shield_diagnostic_reference_only":
        raise ValueError("S1 closed-shield field reference has excessive authority")
    if field_reference.get("hard_gate_allowed") is not False:
        raise ValueError("S1 closed-shield field reference must not be a hard gate")
    thresholds = field_reference.get("diagnostic_alert_thresholds", {})
    required_metrics = {
        "ez_profile_relative_rms",
        "potential_profile_relative_rms",
        "transverse_field_relative_rms",
    }
    if set(thresholds) != required_metrics or any(float(value) <= 0.0 for value in thresholds.values()):
        raise ValueError("S1 field-uniformity thresholds are incomplete")
    evaluation = contract["evaluation"]
    numerical = contract["numerical_qualification"]
    if numerical.get("strategy_id") != "formal_oatof_accelerator_local_mesh_v1":
        raise ValueError("S1 mesh strategy identity is invalid")
    if numerical.get("global_mesh_auto_level") != 6:
        raise ValueError("S1 global mesh level differs from the formal oaTOF model")
    mode_comsol = oatof_mode["comsol"]
    if not math.isclose(
        float(numerical.get("accelerator_routine_hmax_mm", -1.0)),
        float(mode_comsol["routine_accelerator_hmax_mm"]), abs_tol=1e-12,
    ) or not math.isclose(
        float(numerical.get("accelerator_convergence_hmax_mm", -1.0)),
        float(mode_comsol["convergence_accelerator_hmax_mm"]), abs_tol=1e-12,
    ):
        raise ValueError("S1 accelerator mesh sizes differ from the formal oaTOF mode")
    if not math.isclose(float(numerical.get("release_volume_hmax_mm", -1.0)), 0.1, abs_tol=1e-12):
        raise ValueError("S1 release-volume refinement differs from the formal oaTOF mesh")
    if not math.isclose(float(numerical.get("connector_diagnostic_hmax_mm", -1.0)), 0.25, abs_tol=1e-12):
        raise ValueError("S1 connector diagnostic hmax is not frozen")
    if numerical.get("closed_control_required_before_port_selection") is not True:
        raise ValueError("S1 port selection requires a closed local-domain control")
    if numerical.get("convergence_order") != [
        "accelerator_hmax_1.0_mm",
        "accelerator_hmax_0.5_mm",
        "connector_diagnostic_hmax_0.25_mm",
    ]:
        raise ValueError("S1 accelerator-mesh convergence order is not frozen")
    if not math.isclose(float(numerical.get("conditional_refinement_hmax_mm", -1.0)), 0.125, abs_tol=1e-12):
        raise ValueError("S1 conditional connector refinement is not frozen")
    if not math.isclose(
        float(numerical.get("maximum_numerical_uncertainty_fraction_of_performance_budget", -1.0)),
        0.2, abs_tol=1e-12,
    ):
        raise ValueError("S1 performance-scaled numerical uncertainty budget is not frozen")
    if numerical.get("opened_outer_domain_convergence_required") is not True:
        raise ValueError("S1 must qualify the opened interior-domain truncation")
    controls = numerical.get("diagnostic_controls", [])
    if len(controls) != 2 or "RF hardware omitted" not in controls[1]:
        raise ValueError("S1 RF-hardware isolation control is not frozen")
    permissions = contract["permissions"]
    if evaluation.get("logical_operator") != "AND_for_hard_constraints_only" or evaluation.get("pass_allowed") is not False:
        raise ValueError("S1 characterization must remain an AND gate without PASS authority")
    if evaluation.get("field_reference_role") != "diagnostic_alert_only":
        raise ValueError("S1 legacy field thresholds must remain diagnostic")
    if evaluation.get("field_reference_alert_clear_required_for_s1_pass") is not False:
        raise ValueError("S1 field-reference alert may not directly control PASS")
    leakage = evaluation.get("maximum_relative_field_leakage", {})
    if not math.isclose(float(leakage.get("n100_runtime_precheck_limit", -1.0)), 1e-4, abs_tol=1e-15):
        raise ValueError("S1 N=100 leakage precheck limit changed")
    if leakage.get("hard_performance_gate") is not False:
        raise ValueError("S1 field leakage precheck may not replace particle performance")
    if any(float(leakage[key]) >= float(leakage["n100_runtime_precheck_limit"]) for key in (
        "oatof_static_upstream_measured", "rf_peak_near_oatof_source_measured"
    )):
        raise ValueError("S1 field leakage does not authorize N=100 runtime")
    if permissions != {
        "candidate_geometry_generation_allowed": True,
        "field_solve_allowed": True,
        "particle_runtime_allowed": True,
        "formal_asset_modification_allowed": False,
    }:
        raise ValueError("S1 characterization permissions are invalid")
    return contract


def main() -> None:
    contract = validate()
    widths = contract["port_sweep"]["full_width_y_mm"]
    print(
        "S1_JOINT_FIELD_CONTRACT=PASS "
        f"WIDTHS_MM={','.join(str(value) for value in widths)} "
        "FIELD_SOLVE_ALLOWED=true PARTICLE_RUNTIME_ALLOWED=true"
    )


if __name__ == "__main__":
    main()
