"""Validate the staged RF-to-oa field-to-particle performance experiment."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = PROJECT_ROOT / "config" / "rf_to_oatof_field_performance_experiment.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(path: Path = DEFAULT_PLAN) -> dict[str, Any]:
    plan = load(path)
    if plan.get("schema_version") != 1 or plan.get("status") != "approved_staged_experiment_plan":
        raise ValueError("field-performance experiment identity is invalid")
    mapping = plan.get("implementation_stage_mapping", {})
    if set(mapping) != {"E0", "E1", "E2", "E3", "E4"}:
        raise ValueError("field-performance experiment is not mapped to implementation stages")

    baseline = plan["formal_baseline_policy"]
    if baseline.get("formal_baseline_count") != 1 or baseline.get("old_baseline_comparison_forbidden") is not True:
        raise ValueError("field-performance experiment must use one current formal baseline")
    if baseline.get("matched_state_replay_role") != "diagnostic_reference_only_not_a_second_baseline":
        raise ValueError("matched-state replay is incorrectly promoted to a baseline")

    axes = plan["coordinate_semantics"]
    if axes.get("aggregate_xy_metric_alone_is_sufficient") is not False:
        raise ValueError("Ex and Ey must be evaluated separately")
    if not all(axis in axes for axis in ("x", "y", "z")):
        raise ValueError("field-performance coordinate semantics are incomplete")

    candidates = plan["candidate_space"]
    if not math.isclose(float(candidates["port_full_height_z_mm"]), 0.9, abs_tol=1e-12):
        raise ValueError("field-performance plan changed the 90% theory-bounded height")
    if [float(value) for value in candidates["port_full_width_y_mm"]] != [1.0, 0.75, 0.5, 0.25]:
        raise ValueError("field-performance width sweep is not frozen")
    if candidates.get("minimum_absolute_transmission") is not None:
        raise ValueError("an absolute transmission requirement has not been authorized")

    stages = plan["experiment_stages"]
    if [stage.get("id") for stage in stages] != ["E0", "E1", "E2", "E3", "E4"]:
        raise ValueError("field-performance stages must remain sequential")
    if [stage.get("particle_count") for stage in stages] != [0, 0, 100, 1000, 1000]:
        raise ValueError("field-performance particle counts are not frozen")
    numerical = stages[1]
    if numerical.get("global_mesh_auto_level") != 6:
        raise ValueError("connection-specific numerical plan changed the formal global mesh level")
    if [float(value) for value in numerical.get("local_accelerator_hmax_mm", [])] != [0.5, 0.25]:
        raise ValueError("connection-specific local mesh sequence is invalid")
    if not math.isclose(float(numerical.get("conditional_hmax_mm", -1.0)), 0.125, abs_tol=1e-12):
        raise ValueError("conditional local refinement is invalid")
    if numerical.get("conditional_hmax_currently_authorized") is not False:
        raise ValueError("0.125 mm refinement must remain blocked pending downstream functional evidence")
    if "opened geometry" not in numerical.get("outer_domain_policy", ""):
        raise ValueError("opened outer-domain convergence is required")
    if "global time" not in stages[2].get("time_policy", ""):
        raise ValueError("N=100 screening must preserve global instrument time")
    if not any("accelerator-reflectron coupled" in item for item in stages[3].get("required_physics", [])):
        raise ValueError("N=1000 confirmation must use coupled oaTOF physics")

    metrics = plan["metrics"]
    if not all(name in metrics for name in ("longitudinal", "injection_x", "lateral_y", "transport")):
        raise ValueError("field-performance metrics are incomplete")
    budgets = plan["provisional_performance_budgets"]
    expected = {
        "minimum_resolving_power_ratio_to_formal_baseline": 0.99,
        "maximum_detector_rms_spot_ratio_to_formal_baseline": 1.05,
        "maximum_detector_r99_fraction_of_active_radius": 0.9,
        "maximum_additional_field_induced_loss_fraction_after_geometric_cut": 0.01,
        "confidence_level": 0.95,
        "maximum_numerical_uncertainty_fraction_of_each_performance_budget": 0.2,
    }
    if budgets.get("logical_operator") != "AND":
        raise ValueError("all hard performance constraints must combine by AND")
    for key, value in expected.items():
        if not math.isclose(float(budgets.get(key, -1.0)), value, abs_tol=1e-12):
            raise ValueError(f"field-performance budget changed: {key}")
    if budgets.get("absolute_resolution_requirement") is not None:
        raise ValueError("absolute resolution requirement has not been frozen")
    if budgets.get("absolute_end_to_end_transmission_requirement") is not None:
        raise ValueError("absolute transmission requirement has not been frozen")

    limits = plan["field_limit_derivation"]
    if limits.get("legacy_closed_shield_threshold_role") != "diagnostic_alert_only":
        raise ValueError("legacy closed-shield thresholds exceed diagnostic authority")
    if limits.get("independent_hard_limits_before_particle_calibration_forbidden") is not True:
        raise ValueError("field limits must be calibrated against particle performance")
    if "0.8 times" not in limits.get("safety_rule", ""):
        raise ValueError("performance-derived field-limit safety factor is missing")

    data = plan["result_data_policy"]
    if data.get("required_particle_events") != ["rf_exit", "oa_entry", "pulse_capture", "detector"]:
        raise ValueError("minimal particle-event dataset is not frozen")
    if data.get("dense_trajectories_default") is not False:
        raise ValueError("dense trajectories must remain opt-in diagnostics")
    mesh_input = plan["rf_mesh_state_input"]
    if mesh_input.get("status") != "shared_clock_functional_chain_qualified_physical_refinement_deferred":
        raise ValueError("RF mesh states are not routed to downstream functional arbitration")
    if mesh_input.get("shared_clock_pulse_run") != "20260722_080000__sim__simion__rf-entry-finite-pulse__n100__r12":
        raise ValueError("shared-clock pulse evidence is not frozen")
    if not math.isclose(float(mesh_input.get("retained_end_hmax_mm", -1)), 0.5, abs_tol=1e-12):
        raise ValueError("RF low-cost mesh selection changed")
    if "shared instrument clock" not in mesh_input.get("required_next_test", ""):
        raise ValueError("downstream mesh arbitration must preserve the shared clock")
    return plan


def main() -> None:
    plan = validate()
    print(
        "RF_TO_OATOF_FIELD_PERFORMANCE_EXPERIMENT=PASS "
        f"STAGES={','.join(stage['id'] for stage in plan['experiment_stages'])} "
        "FORMAL_BASELINES=1"
    )


if __name__ == "__main__":
    main()
