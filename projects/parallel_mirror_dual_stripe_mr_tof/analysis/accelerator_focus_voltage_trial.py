"""Derive a voltage-only accelerator focus trial on reviewed fixed geometry."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    PhysicsContractError,
    fixed_energy_gap1_focus_sensitivity,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_operating_energy_envelope,
    derive_stage_2_ring_voltages,
    derive_two_zone_focus,
    derive_two_zone_placement,
    load_contract,
    mirror_power_supply_limits,
)

_VOLTAGE_FIELDS = frozenset({"repeller_v", "intermediate_grid_v", "exit_grid_v"})
_NON_GEOMETRY_ACCELERATOR_FIELDS = frozenset({
    "coaxial_return_path",
    "detector_return_path",
    "shape_semantics",
})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accelerator_geometry_contract(accelerator: dict[str, Any]) -> dict[str, Any]:
    """Return the accelerator fields that must remain fixed during voltage trials."""
    excluded = _VOLTAGE_FIELDS | _NON_GEOMETRY_ACCELERATOR_FIELDS
    return {key: copy.deepcopy(value) for key, value in accelerator.items() if key not in excluded}


def _accelerator_pa_compatibility_contract(contract: dict[str, Any]) -> dict[str, Any]:
    simion = contract.get("simion")
    if not isinstance(simion, dict):
        raise CandidateContractError("accelerator voltage trial requires a SIMION contract")
    component_mesh = simion.get("component_mesh_mm_per_gu")
    if not isinstance(component_mesh, dict) or "accelerator" not in component_mesh:
        raise CandidateContractError("SIMION contract lacks the accelerator component mesh")
    if "accelerator_pa_span_mm" not in simion:
        raise CandidateContractError("SIMION contract lacks the accelerator PA span")
    return {
        "component_mesh_mm_per_gu": copy.deepcopy(component_mesh["accelerator"]),
        "pa_span_mm": copy.deepcopy(simion["accelerator_pa_span_mm"]),
    }


def require_reviewed_geometry(current: dict[str, Any], reviewed: dict[str, Any]) -> None:
    """Fail unless a candidate differs from the reviewed assembly only in voltages."""
    for key in ("coordinate_system", "prisms"):
        if current.get(key) != reviewed.get(key):
            raise CandidateContractError(f"current {key} differs from the reviewed PA/IOB contract")
    current_accelerator = current.get("accelerator")
    reviewed_accelerator = reviewed.get("accelerator")
    if not isinstance(current_accelerator, dict) or not isinstance(reviewed_accelerator, dict):
        raise CandidateContractError("voltage trial requires current and reviewed accelerator contracts")
    if accelerator_geometry_contract(current_accelerator) != accelerator_geometry_contract(reviewed_accelerator):
        raise CandidateContractError("current accelerator geometry differs from the reviewed PA/IOB contract")
    if _accelerator_pa_compatibility_contract(current) != _accelerator_pa_compatibility_contract(reviewed):
        raise CandidateContractError("current accelerator PA mesh or span differs from the reviewed PA/IOB contract")


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateContractError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be a finite number")
    return result


def _require_zero_axial_release(contract: dict[str, Any], label: str) -> None:
    accelerator = contract.get("accelerator")
    if not isinstance(accelerator, dict) or accelerator.get("axis") != "z_negative":
        raise CandidateContractError(f"{label} accelerator must accelerate along negative project z")
    source = contract.get("particle_source")
    diagnostic = source.get("accelerator_focus_diagnostic") if isinstance(source, dict) else None
    if not isinstance(diagnostic, dict):
        raise CandidateContractError(f"{label} contract lacks the accelerator focus diagnostic source")
    if diagnostic.get("status") != "diagnostic_only__zero_ke_axial_release":
        raise CandidateContractError(f"{label} accelerator focus source must be the zero-KE axial release")
    initial_energy = _finite_number(
        diagnostic.get("initial_kinetic_energy_ev"),
        f"{label} accelerator focus initial kinetic energy",
    )
    if initial_energy != 0.0:
        raise CandidateContractError(f"{label} accelerator focus source must have zero extraction energy")
    if diagnostic.get("direction_project") != [0, 0, -1]:
        raise CandidateContractError(f"{label} accelerator focus direction must be negative project z")


def _current_axial_energy_partition(
    current: dict[str, Any], reviewed_energy_per_charge_v: float,
) -> float:
    prism_transport = current.get("prism_transport")
    partition = prism_transport.get("energy_partition") if isinstance(prism_transport, dict) else None
    if not isinstance(partition, dict) or partition.get("semantics") != (
        "post_acceleration_total_and_orthogonal_components_per_charge_ev"
    ):
        raise CandidateContractError("current contract lacks the orthogonal energy partition")
    slow_energy = _finite_number(
        partition.get("drift_kinetic_energy_ev"), "current drift kinetic energy",
    )
    fast_energy = _finite_number(
        partition.get("fast_reflection_kinetic_energy_ev"),
        "current fast-reflection kinetic energy",
    )
    total_energy = _finite_number(
        partition.get("total_kinetic_energy_ev"), "current total kinetic energy",
    )
    if slow_energy <= 0.0:
        raise CandidateContractError("current orthogonal slow energy must be positive")
    if not math.isclose(total_energy, slow_energy + fast_energy, rel_tol=0.0, abs_tol=1e-9):
        raise CandidateContractError("current total energy must equal its orthogonal components")
    if not math.isclose(fast_energy, reviewed_energy_per_charge_v, rel_tol=0.0, abs_tol=1e-9):
        raise CandidateContractError(
            "current baseline fast-reflection energy must equal the reviewed legal accelerator net gain"
        )
    return slow_energy


def derive_zero_extraction_energy_focus_seed(
    current: dict[str, Any],
    reviewed: dict[str, Any],
    selected_net_gain_center_v: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scale a reviewed zero-extraction-energy focus into an ideal voltage seed.

    This is only the uniform-field two-zone homogeneity relation.  It preserves
    the reviewed focus distance by scaling every voltage relative to the exit
    grid, and does not qualify the result against the finite three-dimensional
    accelerator field.
    """
    require_reviewed_geometry(current, reviewed)
    _require_zero_axial_release(current, "current")
    selected_energy = _finite_number(
        selected_net_gain_center_v, "selected net-gain centre",
    )
    if selected_energy <= 0.0:
        raise CandidateContractError("selected net-gain centre must be positive")

    # This validates that the reviewed endpoint voltages themselves produce
    # the reviewed declared gain; arbitrary voltage triples are not a seed
    # authority even when their geometry is otherwise identical.
    reviewed_focus = derive_two_zone_focus(reviewed)
    slow_energy = _current_axial_energy_partition(
        current, reviewed_focus.energy_per_charge_v,
    )
    reviewed_accelerator = reviewed["accelerator"]
    reviewed_first_gap_drop = _finite_number(
        reviewed_accelerator.get("repeller_v"), "reviewed repeller voltage",
    ) - _finite_number(
        reviewed_accelerator.get("intermediate_grid_v"),
        "reviewed intermediate-grid voltage",
    )
    if reviewed_first_gap_drop <= 0.0:
        raise CandidateContractError("reviewed first-gap voltage drop must be positive")

    scale = selected_energy / reviewed_focus.energy_per_charge_v
    first_gap_drop = reviewed_first_gap_drop * scale
    trial, receipt = derive_voltage_trial(
        current,
        reviewed,
        first_gap_drop,
        selected_net_gain_center_v=selected_energy,
    )
    trial_focus = derive_two_zone_focus(trial)
    if not math.isclose(
        trial_focus.focus_after_exit_mm,
        reviewed_focus.focus_after_exit_mm,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise CandidateContractError(
            "homogeneous voltage scaling did not preserve the reviewed forward focus"
        )
    receipt.update({
        "qualification": "ideal_uniform_field_seed_only",
        "derivation": "relative_exit_voltage_homogeneity_at_zero_initial_extraction_energy",
        "reviewed_energy_per_charge_v": reviewed_focus.energy_per_charge_v,
        "selected_to_reviewed_energy_scale": scale,
        "reviewed_first_gap_drop_v": reviewed_first_gap_drop,
        "reviewed_focus_after_exit_mm": reviewed_focus.focus_after_exit_mm,
        "forward_focus_after_exit_mm": trial_focus.focus_after_exit_mm,
        "initial_extraction_axis_energy_per_charge_v": 0.0,
        "orthogonal_slow_energy_per_charge_v": slow_energy,
        "orthogonal_slow_energy_role": "excluded_from_the_axial_uniform_field_focus_seed",
        "three_dimensional_field_match": "not_evaluated",
    })
    trial["candidate_derivation"].update({
        "qualification": receipt["qualification"],
        "reviewed_voltage_scale": scale,
        "reviewed_focus_after_exit_mm": reviewed_focus.focus_after_exit_mm,
    })
    return trial, receipt


def derive_voltage_trial(
    current: dict[str, Any], reviewed: dict[str, Any], first_gap_drop_v: float,
    selected_net_gain_center_v: float | None = None,
    finite_3d_gain_correction_v: float = 0.0,
    selected_slow_energy_per_charge_v: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive endpoint/ring voltages while preserving the reviewed physical placement."""
    require_reviewed_geometry(current, reviewed)
    drop = float(first_gap_drop_v)
    if not math.isfinite(drop) or drop <= 0.0:
        raise CandidateContractError("first-gap voltage drop must be finite and positive")
    source = current.get("particle_source", {})
    species = source.get("species", {}) if isinstance(source, dict) else {}
    charge = float(species.get("charge_e", 0.0))
    if not math.isfinite(charge) or charge <= 0.0:
        raise CandidateContractError("accelerator voltage trial requires a positive ion")
    trial = copy.deepcopy(current)
    accelerator = trial["accelerator"]
    gap_1 = float(accelerator["gap_1_mm"])
    release = float(accelerator["release_position_in_gap_1_mm"])
    exit_v = float(accelerator["exit_grid_v"])
    if not all(math.isfinite(value) for value in (gap_1, release, exit_v)) or not 0.0 < release < gap_1:
        raise CandidateContractError("accelerator release must lie strictly inside finite gap 1")
    target_energy_per_charge_v = derive_operating_energy_envelope(
        current, selected_center_v=selected_net_gain_center_v,
    ).selected_net_gain_center_v
    correction_v = float(finite_3d_gain_correction_v)
    if not math.isfinite(correction_v):
        raise CandidateContractError("finite-3D gain correction must be finite")
    commanded_energy_per_charge_v = target_energy_per_charge_v + correction_v
    if commanded_energy_per_charge_v <= 0.0:
        raise CandidateContractError("commanded accelerator gain must be positive")
    # The voltage-trial document is a run-local operating contract.  Make its
    # selected energy internally self-consistent so downstream focus and source
    # materializers never infer the old reference centre from otherwise new
    # endpoint voltages.  The reviewed geometry contract remains untouched.
    trial["nominal"]["energy_per_charge_v"] = commanded_energy_per_charge_v
    trial["accelerator_energy_contract"][
        "net_gain_reference_center_per_charge_v"
    ] = commanded_energy_per_charge_v
    if selected_slow_energy_per_charge_v is not None:
        slow_energy = float(selected_slow_energy_per_charge_v)
        if not math.isfinite(slow_energy) or slow_energy <= 0.0:
            raise CandidateContractError("selected slow-axis energy must be finite and positive")
        partition = trial["prism_transport"]["energy_partition"]
        partition["drift_kinetic_energy_ev"] = slow_energy
        partition["fast_reflection_kinetic_energy_ev"] = target_energy_per_charge_v
        partition["total_kinetic_energy_ev"] = slow_energy + target_energy_per_charge_v
    repeller_v = exit_v + commanded_energy_per_charge_v + drop * release / gap_1
    intermediate_v = repeller_v - drop
    accelerator["repeller_v"] = repeller_v
    accelerator["intermediate_grid_v"] = intermediate_v
    rings = list(derive_stage_2_ring_voltages(
        trial, placement_contract=reviewed,
    ))
    focus = derive_two_zone_focus(trial, require_downstream_focus=False)
    trial["candidate_derivation"] = {
        "role": "fixed_reviewed_geometry_accelerator_voltage_trial",
        "first_gap_drop_v": drop,
        "energy_per_charge_v": commanded_energy_per_charge_v,
        "target_axial_energy_per_charge_v": target_energy_per_charge_v,
        "finite_3d_gain_correction_v": correction_v,
        "selected_slow_energy_per_charge_v": selected_slow_energy_per_charge_v,
        "energy_selection": (
            "explicit_selected_net_gain_center"
            if selected_net_gain_center_v is not None
            else "baseline_reference_center"
        ),
        "physical_placement_source": "reviewed_contract_not_trial_focus",
    }
    receipt = {
        "schema_version": 1,
        "role": "mrtof_fixed_geometry_accelerator_voltage_trial",
        "status": "derived",
        "first_gap_drop_v": drop,
        "energy_per_charge_v": commanded_energy_per_charge_v,
        "target_axial_energy_per_charge_v": target_energy_per_charge_v,
        "finite_3d_gain_correction_v": correction_v,
        "selected_slow_energy_per_charge_v": selected_slow_energy_per_charge_v,
        "energy_selection": trial["candidate_derivation"]["energy_selection"],
        "endpoint_voltages_v": [repeller_v, intermediate_v, exit_v],
        "ring_voltages_v": rings,
        "analytic_focus_after_exit_mm": focus.focus_after_exit_mm,
        "analytic_focus_is_downstream": focus.focus_after_exit_mm >= 0.0,
        "analytic_focus_reference": "signed_ideal_uniform_field_extrapolation_only",
        "semantics": "voltage-only trial; reviewed PA geometry and workbench placement remain invariant",
    }
    return trial, receipt


def derive_focus_calibration_proposal(
    current: dict[str, Any],
    reviewed: dict[str, Any],
    previous_trial: dict[str, Any],
    previous_analysis: dict[str, Any],
    *,
    selected_net_gain_center_v: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Propose one analytic voltage correction from a finite-3D focus residual."""
    require_reviewed_geometry(current, reviewed)
    require_reviewed_geometry(previous_trial, reviewed)
    _require_zero_axial_release(current, "current")
    selected_energy = derive_operating_energy_envelope(
        current, selected_center_v=selected_net_gain_center_v,
    ).selected_net_gain_center_v
    previous_focus = derive_two_zone_focus(
        previous_trial, require_downstream_focus=False,
    )
    if not math.isclose(
        previous_focus.energy_per_charge_v, selected_energy,
        rel_tol=0.0, abs_tol=1e-9,
    ):
        raise CandidateContractError(
            "previous voltage trial net gain differs from the selected run centre"
        )
    expected_count = previous_analysis.get("expected_particle_count")
    focus_count = previous_analysis.get("focus_particle_count")
    if (
        previous_analysis.get("status") != "complete"
        or isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count <= 0
        or isinstance(focus_count, bool)
        or not isinstance(focus_count, int)
        or focus_count != expected_count
    ):
        raise CandidateContractError(
            "previous focus analysis must be complete for every expected particle"
        )
    timing = previous_analysis.get("timing")
    if not isinstance(timing, dict):
        raise CandidateContractError("previous focus analysis lacks timing results")
    residual_z_mm = _finite_number(
        timing.get("first_order_focus_plane_residual_z_mm"),
        "previous finite-interval focus-plane residual",
    )
    placement = derive_two_zone_placement(reviewed)
    target_z_mm = _finite_number(
        previous_analysis.get("target_plane_project_z_mm"),
        "previous focus target plane",
    )
    if not math.isclose(target_z_mm, placement.focus_z_mm, rel_tol=0.0, abs_tol=1e-9):
        raise CandidateContractError(
            "previous focus target plane differs from reviewed geometry"
        )
    accelerator = previous_trial["accelerator"]
    old_drop_v = _finite_number(
        accelerator.get("repeller_v"), "previous trial repeller voltage",
    ) - _finite_number(
        accelerator.get("intermediate_grid_v"),
        "previous trial intermediate-grid voltage",
    )
    try:
        sensitivity = fixed_energy_gap1_focus_sensitivity(
            selected_energy,
            old_drop_v,
            _finite_number(accelerator.get("gap_1_mm"), "accelerator gap 1"),
            _finite_number(accelerator.get("gap_2_mm"), "accelerator gap 2"),
            _finite_number(
                accelerator.get("release_position_in_gap_1_mm"),
                "accelerator release position",
            ),
        )
    except PhysicsContractError as error:
        raise CandidateContractError(str(error)) from error
    project_z_derivative = -sensitivity.focus_drift_derivative_mm_per_v
    if not math.isfinite(project_z_derivative) or project_z_derivative == 0.0:
        raise CandidateContractError(
            "fixed-energy project-z focus derivative must be finite and nonzero"
        )
    new_drop_v = old_drop_v - residual_z_mm / project_z_derivative
    proposal, trial_receipt = derive_voltage_trial(
        current,
        reviewed,
        new_drop_v,
        selected_net_gain_center_v=selected_energy,
    )
    receipt = {
        **trial_receipt,
        "schema_version": 1,
        "role": "mrtof_fixed_geometry_accelerator_focus_calibration_proposal",
        "status": "derived",
        "qualification": "3d_focus_calibration_proposal_only",
        "selected_net_gain_center_v": selected_energy,
        "old_first_gap_drop_v": old_drop_v,
        "new_first_gap_drop_v": new_drop_v,
        "finite_interval_focus_plane_residual_z_mm": residual_z_mm,
        "residual_estimator": (
            "finite_release_interval_quadratic_fit__not_strict_local_derivative"
        ),
        "ideal_focus_derivative_after_exit_mm_per_v": (
            sensitivity.focus_drift_derivative_mm_per_v
        ),
        "project_focus_z_derivative_mm_per_v": project_z_derivative,
        "provider_function": (
            "projects.orthogonal_accelerator.analysis.accelerator_time_focus."
            "fixed_energy_gap1_focus_sensitivity"
        ),
        "provider_identity_authority": "frozen_by_calling_run_manifest",
        "semantics": (
            "One undamped analytic proposal on reviewed fixed geometry; the signed ideal "
            "reference is not evidence that the finite-3D focus moved to the target plane."
        ),
    }
    return proposal, receipt


def materialize(
    current_path: Path, reviewed_path: Path, first_gap_drop_v: float,
    output_path: Path, receipt_path: Path,
    selected_net_gain_center_v: float | None = None,
    finite_3d_gain_correction_v: float = 0.0,
    selected_slow_energy_per_charge_v: float | None = None,
) -> dict[str, Any]:
    current = load_contract(current_path)
    detector_return_path = current["accelerator"]["detector_return_path"]
    reviewed = load_contract(
        reviewed_path,
        inherited_detector_return_path=detector_return_path,
        inherited_mirror_power_supply_limits_v=mirror_power_supply_limits(current),
    )
    trial, receipt = derive_voltage_trial(
        current, reviewed, first_gap_drop_v, selected_net_gain_center_v,
        finite_3d_gain_correction_v,
        selected_slow_energy_per_charge_v,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(trial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt.update({
        "source_contract_sha256": _sha256(current_path),
        "reviewed_contract_sha256": _sha256(reviewed_path),
        "trial_contract_sha256": _sha256(output_path),
    })
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--reviewed", required=True, type=Path)
    parser.add_argument("--first-gap-drop-v", required=True, type=float)
    parser.add_argument("--selected-net-gain-center-v", type=float)
    parser.add_argument("--finite-3d-gain-correction-v", type=float, default=0.0)
    parser.add_argument("--selected-slow-energy-per-charge-v", type=float)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    arguments = parser.parse_args()
    receipt = materialize(
        arguments.current, arguments.reviewed, arguments.first_gap_drop_v,
        arguments.output, arguments.receipt, arguments.selected_net_gain_center_v,
        arguments.finite_3d_gain_correction_v,
        arguments.selected_slow_energy_per_charge_v,
    )
    print(f"MRTOF_ACCELERATOR_VOLTAGE_TRIAL=PASS drop_v={receipt['first_gap_drop_v']:.12g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
