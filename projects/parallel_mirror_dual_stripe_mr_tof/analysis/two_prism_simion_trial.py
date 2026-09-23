"""Materialize and analyze one finite-3D P1/P2 voltage trial.

The trial reuses the reviewed PA geometry.  It combines the independently
derived mirror/Stripe point and the separately calibrated accelerator focus
point, then changes only the two prism voltages.  The source starts in
accelerator gap 1 with the mirror/Stripe-selected near-5-eV slow kinetic energy
in +project-y; the accelerator field supplies the fast -project-z energy.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C,
    kinetic_energy_ev,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    resolve_drift_phase_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    load_verified_bunch_source_receipt,
    solver_problem_identity_from_trial_receipt,
    source_cohort_identity,
    validate_fixed_global_pulse_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import (
    _full_path_timeout_us,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight import (
    resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_stripe_shape_adapter import (
    native_stripe_geometry_projection_sha256,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_mirror_voltage_bounds,
    derive_two_zone_placement,
    load_contract,
    mirror_power_supply_limits,
    resolve_trajectory_profile,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    FLY_COMPLETED,
    parse_events,
    summarize_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
    observation_from_simion_events,
    prism_handoff_residuals,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CandidateContractError(f"expected an object in {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_GLOBAL_PULSE_TIME_BASIS = "ion_time_of_flight_us_from_common_tob_zero_release"


def _apply_trajectory_step_scale(
    trajectory_profile: dict[str, Any], trajectory_step_scale: float,
) -> dict[str, Any]:
    scale = _finite(trajectory_step_scale, "trajectory step scale")
    if not 0 < scale <= 1:
        raise CandidateContractError("trajectory step scale must be in (0, 1]")
    if scale == 1:
        return trajectory_profile
    profile = dict(trajectory_profile)
    base_profile_id = str(profile["profile_id"])
    base_maximum_step_us = _finite(
        profile["maximum_step_us"], "base maximum trajectory step",
    )
    profile.update({
        "profile_id": f"{base_profile_id}__step_scale_{scale:.12g}",
        "base_profile_id": base_profile_id,
        "base_maximum_step_us": base_maximum_step_us,
        "step_scale": scale,
        "maximum_step_us": base_maximum_step_us * scale,
        "purpose": (
            f"{profile['purpose']}; run-local numerical refinement "
            "of one frozen source interval"
        ),
    })
    return profile


def _accelerator_energy_binding(
    accelerator: dict[str, Any], analyzer_axial_energy_per_charge_v: float,
) -> dict[str, float]:
    """Validate the calibrated accelerator command against its physical target."""
    analyzer_target = _finite(
        analyzer_axial_energy_per_charge_v, "analyser selected axial energy",
    )
    applied = _finite(
        accelerator.get("energy_per_charge_v"),
        "accelerator applied net-gain parameter",
    )
    target = _finite(
        accelerator.get("target_axial_energy_per_charge_v"),
        "accelerator target axial energy",
    )
    correction = _finite(
        accelerator.get("finite_3d_gain_correction_v"),
        "accelerator finite-3D gain correction",
    )
    if abs(target - analyzer_target) > 1e-9:
        raise CandidateContractError(
            "accelerator target axial energy and analyser selected axial energy differ"
        )
    if abs((applied - correction) - target) > 1e-9:
        raise CandidateContractError(
            "accelerator applied net-gain parameter, finite-3D correction, and "
            "target axial energy are inconsistent"
        )
    return {
        "applied_net_gain_parameter_v": applied,
        "target_axial_energy_per_charge_v": target,
        "finite_3d_gain_correction_v": correction,
    }


def _resolve_trial_geometry(
    reviewed_geometry_contract: dict[str, Any],
    current_topology_contract: dict[str, Any],
    accelerator_placement_contract: dict[str, Any],
) -> dict[str, Any]:
    """Resolve reviewed conductors with the two consumed accelerator overrides."""
    resolved_contract = copy.deepcopy(reviewed_geometry_contract)
    reviewed_accelerator = resolved_contract.get("accelerator")
    placement_accelerator = accelerator_placement_contract.get("accelerator")
    if not isinstance(reviewed_accelerator, dict) or not isinstance(
        placement_accelerator, dict,
    ):
        raise CandidateContractError("accelerator geometry projection is unavailable")
    for key in ("component_source_cylinder", "focus_y_anchor"):
        value = placement_accelerator.get(key)
        if not isinstance(value, dict):
            raise CandidateContractError(f"accelerator geometry projection lacks {key}")
        reviewed_accelerator[key] = copy.deepcopy(value)
    return resolve_geometry(
        resolved_contract,
        inherited_dual_stripe_topology_contract=current_topology_contract,
    )


def _schema5_native_source_state(
    stripe_summary: dict[str, Any], contract: dict[str, Any], selected_energy_v: float,
) -> tuple[dict[str, Any], float]:
    """Validate the exact-K native materialization that owns the +y source energy."""
    if (
        stripe_summary.get("schema_version") != 5
        or stripe_summary.get("role") != "mrtof_dual_stripe_exact_k_downstream_operating_seed"
        or stripe_summary.get("status")
        != "native_shape_source_energy_inverse_and_stripe_on_exact_k_complete"
    ):
        raise CandidateContractError("P1/P2 source requires the schema-5 native Stripe seed")
    selected = stripe_summary.get("selected_exact_k_operating_point")
    root = stripe_summary.get("native_stripe_spatial_shape_root")
    seed = stripe_summary.get("selected_seed")
    materialized = seed.get("native_spatial_return_materialization") if isinstance(seed, dict) else None
    if not all(isinstance(value, dict) for value in (selected, root, seed, materialized)):
        raise CandidateContractError("schema-5 Stripe seed lacks its selected point, shape, or materialization")
    nominal = contract.get("nominal")
    accelerator_energy = contract.get("accelerator_energy_contract")
    prism_transport = contract.get("prism_transport")
    energy_partition = (
        prism_transport.get("energy_partition")
        if isinstance(prism_transport, dict) else None
    )
    if (
        not isinstance(nominal, dict)
        or not isinstance(accelerator_energy, dict)
        or not isinstance(energy_partition, dict)
    ):
        raise CandidateContractError("MR-TOF contract lacks its fixed axial/source energy authorities")
    materialized_energy = _finite(
        materialized.get("axial_energy_per_charge_v"),
        "native Stripe materialization axial energy",
    )
    stripe_energy = _finite(selected.get("axial_energy_per_charge_v"), "Stripe selected energy")
    reference_energy = _finite(
        accelerator_energy.get("net_gain_reference_center_per_charge_v"),
        "contract net-gain reference centre",
    )
    search_half_range = _finite(
        accelerator_energy.get("net_gain_center_search_half_range_per_charge_v"),
        "contract net-gain search half-range",
    )
    nominal_energy = _finite(nominal.get("energy_per_charge_v"), "contract nominal energy")
    if reference_energy <= 0.0 or search_half_range < 0.0 or nominal_energy != reference_energy:
        raise CandidateContractError("MR-TOF contract net-gain reference authorities differ")
    if not reference_energy - search_half_range <= selected_energy_v <= reference_energy + search_half_range:
        raise CandidateContractError("selected exact-K energy is outside the contract search envelope")
    if any(abs(value - selected_energy_v) > 1e-9 for value in (
        materialized_energy, stripe_energy,
    )):
        raise CandidateContractError("native Stripe and mirror selected energies differ")
    materialized_root = materialized.get("shape_root")
    seed_biases = _vector(seed.get("stripe_biases_v"), 2, "native Stripe seed biases")
    materialized_biases = _vector(
        materialized.get("stripe_biases_v"), 2, "native Stripe materialization biases",
    )
    expected_geometry_identity = (
        "canonical_json_sha256:"
        f"{native_stripe_geometry_projection_sha256(contract)}"
    )
    if (
        materialized_root != root
        or materialized_biases != seed_biases
        or root.get("geometry_input_identity_source") != expected_geometry_identity
        or _finite(seed.get("nominal_kappa_1"), "native Stripe seed kappa")
        != _finite(root.get("kappa_1"), "native Stripe shape kappa")
        or _finite(selected.get("kappa_1"), "Stripe selected-point kappa")
        != _finite(root.get("kappa_1"), "native Stripe shape kappa")
    ):
        raise CandidateContractError("schema-5 Stripe materialization shape identity is inconsistent")
    source_energy = _finite(
        materialized.get("source_slow_energy_per_charge_v"),
        "native Stripe materialization source slow energy",
    )
    contract_source_energy = _finite(
        energy_partition.get("drift_kinetic_energy_ev"),
        "contract source slow energy",
    )
    if source_energy <= 0.0 or source_energy != contract_source_energy:
        raise CandidateContractError("native Stripe source slow energy differs from the fixed source contract")
    return seed, source_energy


def load_schema5_native_source_state(
    stripe_summary: dict[str, Any], contract: dict[str, Any], selected_energy_v: float,
) -> tuple[dict[str, Any], float]:
    """Public strict loader for the contract-bound schema-5 native Stripe source."""
    return _schema5_native_source_state(stripe_summary, contract, selected_energy_v)


def _fixed_mirror_stripe_source_state(
    authority: dict[str, Any],
    mirror_summary: dict[str, Any],
    stripe_summary: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[dict[str, Any], float, float, list[float], float]:
    """Validate the fixed-grid mirror/variable-slow-energy downstream receipt."""
    if (
        authority.get("schema_version") != 1
        or authority.get("role")
        != "mrtof_fixed_mirror_stripe_downstream_operating_authority"
        or authority.get("status") != "success"
    ):
        raise CandidateContractError("fixed mirror/Stripe downstream authority is invalid")
    if (
        mirror_summary.get("schema_version") != 1
        or mirror_summary.get("role") != "mrtof_mirror_turn_fixed_grid_validation"
        or mirror_summary.get("status") != "success"
    ):
        raise CandidateContractError("fixed mirror summary identity is invalid")
    if (
        stripe_summary.get("schema_version") != 3
        or stripe_summary.get("role")
        != "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family"
        or stripe_summary.get("status")
        != "fixed_grid_native_mirror_exact_K_slow_energy_and_spatial_return_inverse_complete"
    ):
        raise CandidateContractError("fixed-mirror Stripe summary identity is invalid")
    seed = stripe_summary.get("selected_seed")
    materialized = (
        seed.get("native_spatial_return_materialization")
        if isinstance(seed, dict) else None
    )
    if not isinstance(seed, dict) or not isinstance(materialized, dict):
        raise CandidateContractError("fixed-mirror Stripe summary lacks its materialization")
    axial = _finite(authority.get("axial_energy_per_charge_v"), "fixed mirror axial energy")
    slow = _finite(authority.get("slow_energy_per_charge_v"), "selected slow energy")
    target_k = _finite(authority.get("target_period_ratio"), "fixed mirror/Stripe target K")
    predicted_k = _finite(
        authority.get("predicted_period_ratio"), "fixed mirror/Stripe predicted K",
    )
    mirror_voltages = _vector(
        authority.get("mirror_voltages_v"), 5, "fixed-grid mirror voltages",
    )
    stripe_biases = _vector(
        authority.get("stripe_biases_v"), 2, "fixed-mirror Stripe biases",
    )
    if slow <= 0.0 or axial <= 0.0 or not math.isclose(
        target_k, predicted_k, rel_tol=0.0, abs_tol=1e-12,
    ):
        raise CandidateContractError("fixed mirror/Stripe energy or K identity is invalid")
    expected = (
        _finite(seed.get("selected_axial_energy_per_charge_v"), "Stripe axial energy"),
        _finite(seed.get("selected_exact_K_slow_energy_per_charge_v"), "Stripe slow energy"),
        _finite(seed.get("target_drift_period_ratio"), "Stripe target K"),
        _finite(seed.get("predicted_continuous_oscillation_count"), "Stripe predicted K"),
    )
    materialized_biases = _vector(
        materialized.get("stripe_biases_v"), 2, "materialized Stripe biases",
    )
    if (
        expected != (axial, slow, target_k, predicted_k)
        or _vector(seed.get("stripe_biases_v"), 2, "Stripe seed biases") != stripe_biases
        or materialized_biases != stripe_biases
        or _finite(materialized.get("axial_energy_per_charge_v"), "materialized axial energy")
        != axial
        or _finite(materialized.get("source_slow_energy_per_charge_v"), "materialized slow energy")
        != slow
    ):
        raise CandidateContractError("fixed mirror/Stripe authority differs from its source summary")
    energy_contract = contract.get("accelerator_energy_contract")
    if not isinstance(energy_contract, dict):
        raise CandidateContractError("MR-TOF contract lacks its accelerator energy envelope")
    reference = _finite(
        energy_contract.get("net_gain_reference_center_per_charge_v"),
        "contract net-gain reference centre",
    )
    half_range = _finite(
        energy_contract.get("net_gain_center_search_half_range_per_charge_v"),
        "contract net-gain search half-range",
    )
    if not reference - half_range <= axial <= reference + half_range:
        raise CandidateContractError("fixed-grid mirror energy is outside the contract search envelope")
    return seed, slow, axial, mirror_voltages, target_k


def _apply_terminal_mirror_variation(
    *, variation: dict[str, Any] | None, base_voltages: list[float],
    contract: dict[str, Any], axial_energy_v: float,
) -> tuple[list[float], dict[str, Any] | None]:
    if variation is None:
        return base_voltages, None
    if (
        variation.get("schema_version") != 1
        or variation.get("role") != "mrtof_terminal_time_mirror_voltage_variation"
        or variation.get("status") != "screening_candidate_materialized"
        or variation.get("qualification")
        != "diagnostic_only__complete_3d_detector_response_pending"
    ):
        raise CandidateContractError("terminal-time mirror variation identity is invalid")
    base = _vector(
        variation.get("base_mirror_voltages_v"), 5,
        "terminal-time variation base mirror voltages",
    )
    target = _vector(
        variation.get("target_mirror_voltages_v"), 5,
        "terminal-time variation target mirror voltages",
    )
    delta = _vector(
        variation.get("voltage_delta_v"), 4,
        "terminal-time variation voltage delta",
    )
    if base != base_voltages or base[0] != 0.0 or target[0] != 0.0:
        raise CandidateContractError(
            "terminal-time mirror variation is not bound to the selected mirror authority"
        )
    if any(
        not math.isclose(target[index + 1] - base[index + 1], delta[index],
                         rel_tol=0.0, abs_tol=1e-9)
        for index in range(4)
    ):
        raise CandidateContractError("terminal-time mirror variation delta is inconsistent")
    lower, upper = derive_mirror_voltage_bounds(contract, selected_center_v=axial_energy_v)
    if any(
        value < low or value > high
        for value, low, high in zip(target[1:], lower, upper, strict=True)
    ):
        raise CandidateContractError("terminal-time mirror variation violates the mirror envelope")
    identity = {
        "mode": variation.get("mode"),
        "coordinate": variation.get("coordinate"),
        "voltage_delta_v": delta,
        "source_seed": variation.get("source_seed"),
    }
    return target, identity


def _p2_handoff_targets(
    seed: dict[str, Any], contract: dict[str, Any],
) -> tuple[float, float, float]:
    """Derive the positive-turn y and low-field angle from Stripe authority."""
    registration = contract.get("dual_stripe_l0", {}).get(
        "theory_function_coordinate_registration"
    )
    if not isinstance(registration, dict):
        raise CandidateContractError("MR-TOF contract lacks the Stripe function registration")
    target_y = _finite(
        registration.get("function_y_zero_project_y_mm"),
        "Stripe function-y origin in project coordinates",
    )
    angle_degrees = _finite(
        seed.get("nominal_injection_angle_degrees"),
        "native Stripe seed nominal injection angle",
    )
    tangent_ratio = math.tan(math.radians(angle_degrees))
    if not math.isfinite(tangent_ratio) or tangent_ratio <= 0.0:
        raise CandidateContractError(
            "native Stripe seed injection angle must give a finite positive vy/vz tangent"
        )
    return target_y, angle_degrees, tangent_ratio


def _single_center_source_fly2(
    *, mass_th: float, charge_state: int, source_slow_energy_per_charge_v: float,
    focus_y_mm: float, release_z_mm: float,
) -> str:
    """Render the real +y slow-energy release used before -z acceleration."""
    return (
        "particles {\n  coordinates = 0,\n  standard_beam {\n"
        f"    n = 1,\n    tob = 0,\n    mass = {mass_th:.17g},\n    charge = {charge_state},\n"
        f"    ke = {source_slow_energy_per_charge_v * abs(charge_state):.17g},\n"
        "    cwf = 1,\n    color = 0,\n"
        "    direction = vector(0, 1, 0),\n"
        "    position = circle_distribution {\n"
        f"      center = vector(0, {focus_y_mm:.17g}, {release_z_mm:.17g}),\n"
        "      normal = vector(0, 0, -1),\n      radius = 0,\n      fill = true\n"
        "    }\n  }\n}\n"
    )


def _load_frozen_accelerator_pulse_schedule(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    schedule = _load(path)
    if (
        schedule.get("schema_version") not in (1, 2)
        or schedule.get("role") != "mrtof_accelerator_global_pulse_schedule"
        or schedule.get("status") != "frozen"
        or schedule.get("mode") != "fixed_global_time"
        or schedule.get("time_basis") != _GLOBAL_PULSE_TIME_BASIS
    ):
        raise CandidateContractError("accelerator pulse schedule identity is invalid")
    pulse_time = _finite(schedule.get("pulse_off_time_us"), "accelerator pulse-off time")
    if pulse_time <= 0:
        raise CandidateContractError("accelerator pulse-off time must be positive")
    if schedule["schema_version"] == 1:
        source = schedule.get("source")
        if not isinstance(source, dict) or any(
            not isinstance(source.get(key), str) or not source[key]
            for key in (
                "center_run_id", "run_manifest_sha256", "trial_receipt_sha256",
                "observation_sha256", "source_fly2_sha256", "accelerator_receipt_sha256",
            )
        ):
            raise CandidateContractError("accelerator pulse schedule has incomplete source identity")
        if source.get("source_particle_count") != 1:
            raise CandidateContractError("legacy pulse schedules must contain one particle")
    else:
        if (
            not isinstance(schedule.get("source_cohort"), dict)
            or not isinstance(schedule.get("solver_problem_identity"), dict)
            or not isinstance(schedule.get("safe_exit_definition"), dict)
        ):
            raise CandidateContractError("bunch pulse schedule has incomplete frozen identities")
    after_state = schedule.get("after_state")
    if (
        not isinstance(after_state, dict)
        or after_state.get("accelerator_electrode_ids") != list(range(1, 10))
        or after_state.get("voltage_v") != 0.0
    ):
        raise CandidateContractError("accelerator pulse schedule has an invalid grounded state")
    return schedule



def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _vector(value: Any, count: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != count:
        raise CandidateContractError(f"{label} must contain {count} values")
    return [_finite(item, label) for item in value]


def _single_center_source_state(trial: dict[str, Any]) -> tuple[ProjectPhaseSpaceState, dict[str, Any]]:
    """Derive the actual N=1 release state from the frozen source authorities."""
    if trial.get("source_particle_count") != 1:
        raise CandidateContractError("single-center trial observation requires source_particle_count=1")
    position = _vector(trial.get("source_position_project_mm"), 3, "source position")
    direction = _vector(trial.get("source_direction_project"), 3, "source direction")
    direction_norm = math.sqrt(sum(value * value for value in direction))
    if direction_norm <= 0.0:
        raise CandidateContractError("source direction must be nonzero")
    direction = [value / direction_norm for value in direction]
    if direction != [0.0, 1.0, 0.0]:
        raise CandidateContractError(
            "single-center source direction must match the Fly2 +project-y release"
        )
    mass = _finite(trial.get("particle_mass_th"), "particle mass")
    charge = trial.get("charge_state")
    if mass <= 0.0 or not isinstance(charge, int) or isinstance(charge, bool) or charge == 0:
        raise CandidateContractError("source species requires positive mass and nonzero integer charge")
    energy_per_charge = _finite(
        trial.get("source_slow_kinetic_energy_per_charge_v"),
        "source slow kinetic energy per charge",
    )
    if energy_per_charge <= 0.0:
        raise CandidateContractError("source slow kinetic energy per charge must be positive")
    energy_ev = energy_per_charge * abs(charge)
    speed_m_s = math.sqrt(2.0 * energy_ev * ELEMENTARY_CHARGE_C / (mass * AMU_KG))
    velocity = tuple(value * speed_m_s / 1000.0 for value in direction)
    derived_energy_ev = kinetic_energy_ev(mass, *(value * 1000.0 for value in velocity))
    if not math.isclose(derived_energy_ev, energy_ev, rel_tol=1e-12, abs_tol=1e-12):
        raise CandidateContractError("derived source velocity does not preserve source kinetic energy")
    state = ProjectPhaseSpaceState(tuple(position), velocity)
    return state, {
        "position_mm": list(state.position_mm),
        "velocity_mm_per_us": list(state.velocity_mm_per_us),
        "time_us": _finite(trial.get("source_time_of_birth_us"), "source time of birth"),
        "particle_mass_th": mass,
        "charge_state": charge,
        "kinetic_energy_ev": derived_energy_ev,
        "kinetic_energy_per_charge_v": derived_energy_ev / abs(charge),
        "direction_project": list(state.unit_direction_project),
    }


def _accelerator_safe_exit_observation(
    events: list[dict[str, Any]], trial: dict[str, Any], *,
    log_path: Path, trial_receipt_path: Path,
) -> dict[str, Any]:
    """Publish one measured accelerator exit, failing closed on invalid state."""
    exits = [event for event in events if event["kind"] == "accelerator_safe_exit"]
    base: dict[str, Any] = {
        "event_count": len(exits),
        "input_log": {"path": str(log_path.resolve()), "sha256": _sha256(log_path)},
        "trial_identity": {
            "path": str(trial_receipt_path.resolve()),
            "sha256": _sha256(trial_receipt_path),
        },
    }
    if not exits:
        return {**base, "status": "not_observed", "state": None}
    errors: list[str] = []
    if len(exits) != 1:
        errors.append("accelerator_safe_exit_count_must_equal_one")
    event = exits[0]
    try:
        ion = int(event.get("ion"))
        time_us = _finite(event.get("t_us"), "accelerator safe-exit time")
        source_time_us = _finite(
            trial.get("source_time_of_birth_us"), "source time of birth"
        )
        from_instance = int(event.get("from_instance"))
        to_instance = int(event.get("to_instance"))
        position = _vector(
            [event.get(key) for key in ("x_mm", "y_mm", "z_mm")], 3,
            "accelerator safe-exit position",
        )
        velocity = _vector(
            [event.get(key) for key in ("vx_mm_us", "vy_mm_us", "vz_mm_us")], 3,
            "accelerator safe-exit velocity",
        )
        mass = _finite(trial.get("particle_mass_th"), "particle mass")
        charge = trial.get("charge_state")
        accelerator_instance = int(trial.get("accelerator_instance", 3))
        if accelerator_instance != 3:
            errors.append("accelerator_instance_is_invalid")
        if ion != 1:
            errors.append("accelerator_safe_exit_must_belong_to_ion_one")
        if time_us < 0.0:
            errors.append("accelerator_safe_exit_time_must_be_nonnegative")
        if time_us < source_time_us:
            errors.append("accelerator_safe_exit_cannot_precede_source_release")
        if from_instance != accelerator_instance or to_instance == accelerator_instance:
            errors.append("accelerator_safe_exit_instance_transition_is_invalid")
        if velocity[2] >= 0.0:
            errors.append("accelerator_safe_exit_must_travel_toward_negative_project_z")
        if mass <= 0.0 or not isinstance(charge, int) or isinstance(charge, bool) or charge == 0:
            errors.append("accelerator_safe_exit_species_is_invalid")
    except (CandidateContractError, TypeError, ValueError) as error:
        errors.append(str(error))
        position = velocity = []
        time_us = 0.0
        mass = 0.0
        charge = 0
        from_instance = to_instance = 0
    exit_index = next(
        (index for index, candidate in enumerate(events) if candidate is event), -1
    )
    p1_entries = [
        (index, candidate) for index, candidate in enumerate(events)
        if candidate["kind"] == "prism_entry" and candidate.get("n") == 1
    ]
    p1_passes = [
        (index, candidate) for index, candidate in enumerate(events)
        if candidate["kind"] == "prism_pass" and candidate.get("n") == 1
    ]
    if len(p1_entries) > 1:
        errors.append("first_prism_entry_count_exceeds_one")
    elif p1_entries:
        try:
            p1_index, p1_entry = p1_entries[0]
            if (
                p1_index <= exit_index
                or _finite(p1_entry.get("t_us"), "P1 entry time") <= time_us
            ):
                errors.append("accelerator_safe_exit_does_not_precede_P1")
        except CandidateContractError as error:
            errors.append(str(error))
    elif len(p1_passes) > 1:
        errors.append("first_prism_pass_count_exceeds_one")
    elif p1_passes:
        try:
            p1_index, p1_pass = p1_passes[0]
            if (
                p1_index <= exit_index
                or _finite(p1_pass.get("t_us"), "P1 pass time") <= time_us
            ):
                errors.append("accelerator_safe_exit_does_not_precede_P1_pass")
        except CandidateContractError as error:
            errors.append(str(error))
    if errors:
        return {**base, "status": "invalid", "state": None, "errors": errors}
    return {
        **base,
        "status": "observed",
        "state": {
            "ion": 1,
            "time_us": time_us,
            "position_mm": position,
            "velocity_mm_per_us": velocity,
            "particle_mass_th": mass,
            "charge_state": charge,
            "kinetic_energy_ev": kinetic_energy_ev(
                mass, *(value * 1000.0 for value in velocity)
            ),
            "from_instance": from_instance,
            "to_instance": to_instance,
        },
        "p1_ordering": (
            "verified_safe_exit_before_P1_entry"
            if p1_entries
            else (
                "before_P1_pass_only__P1_entry_not_observed"
                if p1_passes else "P1_entry_and_pass_not_observed"
            )
        ),
    }


def _lua_vector(values: list[float]) -> str:
    return "{ " + ", ".join(f"{value:.17g}" for value in values) + " }"


_STATIC_RETURN_KINDS = (
    "drift_phase_return",
    "return_p2_entry",
    "return_p2_pass",
    "return_positive_mirror_turn",
    "detector",
)


def _termination_diagnostic(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate physical electrode contact from project-requested SIMION stops."""
    splats = [event for event in events if event["kind"] == "splat"]
    terminals = [event for event in events if event["kind"] == "terminal"]
    if len(splats) != 1 or len(terminals) != 1:
        return {
            "status": "ambiguous",
            "physical_collision": None,
            "splat_count": len(splats),
            "terminal_count": len(terminals),
        }
    code = int(splats[0]["code"])
    kinds = {
        -1: "physical_electrode_collision",
        1: "programmatic_detector_completion",
        2: "programmatic_timeout",
        4: "programmatic_topology_rejection",
        5: "programmatic_diagnostic_stop",
    }
    kind = kinds.get(code, "unclassified_solver_termination")
    diagnostic: dict[str, Any] = {
        "status": "observed",
        "kind": kind,
        "code": code,
        "physical_collision": code == -1,
        "event": splats[0],
    }
    if code == 4:
        diagnostic["explicit_semantics"] = (
            splats[0].get("termination_kind") == kind
            and splats[0].get("physical_collision") == 0
        )
        diagnostic["reason"] = splats[0].get("reason")
    return diagnostic


def _static_return_diagnostic(
    events: list[dict[str, Any]], target_k: float,
) -> dict[str, Any]:
    """Validate the unique P2-to-positive-mirror static return event chain."""
    selected = {kind: [event for event in events if event["kind"] == kind]
                for kind in _STATIC_RETURN_KINDS}
    errors: list[str] = []
    if any(event["kind"] == "prism_voltage_switch" for event in events):
        errors.append("prism_voltage_switch_forbidden")
    if any(event["kind"] in {"return_p1_entry", "return_p1_pass"} for event in events):
        errors.append("return_p1_forbidden__p1_is_injection_only")
    if any(event["kind"] == "nonmirror_reversal" for event in events):
        errors.append("nonmirror_vz_reversal_observed")
    for kind, matches in selected.items():
        if len(matches) != 1:
            errors.append(f"{kind}_count_must_equal_one")
    if all(len(selected[kind]) == 1 for kind in _STATIC_RETURN_KINDS):
        times = [float(selected[kind][0]["t_us"]) for kind in _STATIC_RETURN_KINDS]
        if any(later <= earlier for earlier, later in zip(times, times[1:])):
            errors.append("static_return_events_out_of_order")
        if float(selected["return_p2_entry"][0].get("vz_mm_us", 0.0)) <= 0.0:
            errors.append("return_p2_entry_must_travel_positive_z")
        if float(selected["return_p2_pass"][0].get("vz_mm_us", 0.0)) <= 0.0:
            errors.append("return_p2_pass_must_travel_positive_z")
        positive_turn = selected["return_positive_mirror_turn"][0]
        if (float(positive_turn.get("z_mm", 0.0)) <= 0.0
                or abs(float(positive_turn.get("vz_mm_us", math.inf))) > 1.0e-12):
            errors.append("return_positive_mirror_turn_must_be_positive_z_vz_zero")
        detector = selected["detector"][0]
        if int(detector.get("direction_z", 0)) != -1:
            errors.append("static_detector_hit_must_travel_negative_z")
        if float(detector.get("z_mm", 0.0)) <= 0.0:
            errors.append("static_detector_hit_must_be_in_positive_z_half_space")
    safe_exits = [event for event in events if event["kind"] == "accelerator_safe_exit"]
    inferred_reentry = False
    if len(safe_exits) == 1:
        safe_exit = safe_exits[0]
        accelerator_instance = int(safe_exit["from_instance"])
        inferred_reentry = any(
            event["kind"] == "instance_transition"
            and float(event["t_us"]) > float(safe_exit["t_us"])
            and int(event["instance"]) == accelerator_instance
            for event in events
        )
    if any(event["kind"] == "accelerator_reentry" for event in events) or inferred_reentry:
        errors.append("accelerator_reentry_after_safe_exit_forbidden")
    if any(event["kind"] == "post_return_mirror_turn" for event in events):
        errors.append("legacy_post_return_mirror_turn_forbidden")
    terminals = [event for event in events if event["kind"] == "terminal"]
    splats = [event for event in events if event["kind"] == "splat"]
    if len(terminals) != 1 or int(terminals[0].get("splat", 0)) != 1:
        errors.append("detector_terminal_must_be_unique_splat_one")
    if len(splats) != 1 or int(splats[0].get("code", 0)) != 1:
        errors.append("detector_splat_must_be_unique_code_one")
    event_contract_ok = not errors
    detector_observed = len(selected["detector"]) == 1
    result: dict[str, Any] = {
        "status": "detector_hit" if event_contract_ok else (
            "invalid_static_return" if detector_observed else "detector_not_observed"
        ),
        "event_contract_ok": event_contract_ok,
        "required_event_order": list(_STATIC_RETURN_KINDS),
        "event_counts": {kind: len(matches) for kind, matches in selected.items()},
        "errors": errors,
        "termination": _termination_diagnostic(events),
    }
    if detector_observed:
        result["first_detector_event"] = selected["detector"][0]
    if len(selected["drift_phase_return"]) == 1:
        phase_return = selected["drift_phase_return"][0]
        result["fractional_k"] = phase_return.get("k", phase_return.get("fractional_k"))
        result["fractional_k_minus_target"] = (
            float(result["fractional_k"]) - target_k
            if result["fractional_k"] is not None else None
        )
    return result


def _mirror_regions(resolved: dict[str, Any]) -> dict[str, list[float]]:
    """Project mirror z regions from the already resolved geometry."""
    boxes = [
        item["box"]
        for key in ("mirror_ground_shields", "mirror_electrodes", "mirror_e_closures")
        for item in resolved[key]
    ]
    return {
        "negative": [min(box[2] for box in boxes if box[5] < 0), max(box[5] for box in boxes if box[5] < 0)],
        "positive": [min(box[2] for box in boxes if box[2] > 0), max(box[5] for box in boxes if box[2] > 0)],
    }


def _verify_manifest_record(path: Path, record: dict[str, Any], label: str) -> None:
    if not path.is_file() or not bool(record.get("exists")):
        raise CandidateContractError(f"{label} is missing")
    if Path(str(record.get("path"))).resolve() != path.resolve():
        raise CandidateContractError(f"{label} path differs from its manifest")
    if int(record.get("bytes", -1)) != path.stat().st_size:
        raise CandidateContractError(f"{label} byte count differs from its manifest")
    if str(record.get("sha256", "")).lower() != _sha256(path).lower():
        raise CandidateContractError(f"{label} hash differs from its manifest")


def freeze_single_center_pulse_schedule(
    *, center_run_path: Path, output_path: Path,
) -> dict[str, Any]:
    """Freeze an N=1 diagnostic global time from a successful exit-triggered run."""
    run_dir = center_run_path.resolve()
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load(manifest_path)
    if (
        manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") != "finite_3d_two_prism_voltage_trial"
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("pulse-schedule source run is not a successful MR-TOF trial")
    trial_path = run_dir / "results" / "two_prism_trial_materialization.json"
    observation_path = run_dir / "results" / "two_prism_trial_observation.json"
    fly2_path = run_dir / "simion" / "downstream_trial_source.input.fly2"
    output_records = {
        Path(str(record.get("path"))).resolve(): record
        for record in manifest.get("outputs", []) if isinstance(record, dict)
    }
    for path, label in (
        (trial_path, "source trial receipt"),
        (observation_path, "source observation"),
    ):
        record = output_records.get(path.resolve())
        if not isinstance(record, dict):
            raise CandidateContractError(f"{label} is not bound by the run manifest")
        _verify_manifest_record(path, record, label)
    fly2_record = (manifest.get("inputs") or {}).get("frozen_source_fly2")
    if not isinstance(fly2_record, dict):
        raise CandidateContractError("source Fly2 is not bound by the run manifest")
    _verify_manifest_record(fly2_path, fly2_record, "source Fly2")
    trial = _load(trial_path)
    observation = _load(observation_path)
    pulse = trial.get("accelerator_pulse") or {}
    diagnostic = observation.get("accelerator_pulse_diagnostic") or {}
    event = diagnostic.get("pulse_off_event")
    if (
        pulse.get("mode") != "initial_exit_triggered_single_center"
        or diagnostic.get("mode") != "initial_exit_triggered_single_center"
        or diagnostic.get("pulse_off_event_count") != 1
        or not isinstance(event, dict)
    ):
        raise CandidateContractError(
            "pulse-schedule source must contain one initial-exit-triggered centre event"
        )
    if (
        trial.get("source_particle_count") != 1
        or trial.get("source_time_of_birth_us") != 0.0
        or trial.get("source_clock_basis") != _GLOBAL_PULSE_TIME_BASIS
    ):
        raise CandidateContractError("pulse-schedule source particle clock is not frozen")
    accelerator_instance = int(trial.get("accelerator_instance", 3))
    if (
        accelerator_instance != 3
        or int(event.get("from_instance", -1)) != accelerator_instance
        or int(event.get("to_instance", accelerator_instance)) == accelerator_instance
    ):
        raise CandidateContractError("pulse-schedule source event is not the first accelerator exit")
    pulse_off_time = _finite(event.get("t_us"), "source accelerator pulse-off time")
    if pulse_off_time <= 0:
        raise CandidateContractError("source accelerator pulse-off time must be positive")
    accelerator_receipt_sha256 = str(
        (trial.get("inputs") or {}).get("accelerator_receipt_sha256", "")
    )
    if not accelerator_receipt_sha256:
        raise CandidateContractError("source trial has no accelerator voltage identity")
    schedule = {
        "schema_version": 1,
        "role": "mrtof_accelerator_global_pulse_schedule",
        "status": "frozen",
        "qualification": "single_center_diagnostic__not_a_bunch_schedule",
        "mode": "fixed_global_time",
        "time_basis": _GLOBAL_PULSE_TIME_BASIS,
        "pulse_off_time_us": pulse_off_time,
        "after_state": {
            "accelerator_electrode_ids": list(range(1, 10)),
            "voltage_v": 0.0,
        },
        "source": {
            "center_run_id": str(manifest["run_id"]),
            "source_particle_count": 1,
            "run_manifest_sha256": _sha256(manifest_path),
            "trial_receipt_sha256": _sha256(trial_path),
            "observation_sha256": _sha256(observation_path),
            "source_fly2_sha256": _sha256(fly2_path),
            "accelerator_receipt_sha256": accelerator_receipt_sha256,
        },
        "derivation": {
            "rule": "first_transition_out_of_declared_accelerator_instance",
            "from_instance": int(event["from_instance"]),
            "to_instance": int(event["to_instance"]),
            "event_position_project_mm": [
                _finite(event.get(key), f"source event {key}")
                for key in ("x_mm", "y_mm", "z_mm")
            ],
            "bunch_safe_exit_envelope": None,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")
    return schedule


def materialize_trial(
    *,
    contract_path: Path,
    accelerator_geometry_contract_path: Path,
    trajectory_contract_path: Path,
    reviewed_contract_path: Path,
    mirror_summary_path: Path,
    stripe_summary_path: Path,
    fixed_mirror_stripe_authority_path: Path | None,
    mirror_voltage_variation_path: Path | None = None,
    accelerator_receipt_path: Path,
    prism_1_v: float,
    prism_2_v: float,
    stripe_biases_override_v: tuple[float, float] | None,
    runtime_fast_adjust_enable: bool,
    pulse_accelerator_until_initial_exit: bool,
    accelerator_safe_exit_only: bool,
    accelerator_pulse_schedule_path: Path | None,
    trajectory_profile_id: str | None,
    fly2_path: Path,
    sidecar_path: Path,
    receipt_path: Path,
    bunch_source_receipt_path: Path | None = None,
    bunch_particle_id_min: int | None = None,
    bunch_particle_id_max: int | None = None,
    accelerator_instance: int = 3,
    trajectory_step_scale: float = 1.0,
    source_y_offset_mm: float = 0.0,
) -> dict[str, Any]:
    if accelerator_instance != 3:
        raise CandidateContractError("workbench accelerator instance must be 3")
    trajectory_contract = load_contract(trajectory_contract_path)
    detector_return_policy = trajectory_contract["accelerator"]["detector_return_path"]
    mirror_supply_limits = mirror_power_supply_limits(trajectory_contract)
    contract = load_contract(
        contract_path, inherited_detector_return_path=detector_return_policy,
        inherited_mirror_power_supply_limits_v=mirror_supply_limits,
    )
    accelerator_geometry_contract = load_contract(
        accelerator_geometry_contract_path,
        inherited_detector_return_path=detector_return_policy,
        inherited_mirror_power_supply_limits_v=mirror_supply_limits,
    )
    reviewed_contract = load_contract(
        reviewed_contract_path, inherited_detector_return_path=detector_return_policy,
        inherited_mirror_power_supply_limits_v=mirror_supply_limits,
    )
    mirror = _load(mirror_summary_path)
    stripe = _load(stripe_summary_path)
    accelerator = _load(accelerator_receipt_path)
    provider_geometry: dict[str, Any] | None = None
    if accelerator.get("role") == "orthogonal_accelerator_mrtof_runtime_receipt":
        if accelerator.get("status") != "published_read_only":
            raise CandidateContractError("provider accelerator receipt is not published read-only")
        projection = accelerator.get("mrtof_projection")
        if not isinstance(projection, dict):
            raise CandidateContractError("provider accelerator receipt lacks its MR projection")
        provider_geometry = projection.get("geometry")
        if not isinstance(provider_geometry, dict):
            raise CandidateContractError("provider accelerator receipt lacks its geometry projection")
        accelerator = projection
    fixed_authority = (
        _load(fixed_mirror_stripe_authority_path)
        if fixed_mirror_stripe_authority_path is not None else None
    )
    if fixed_authority is not None:
        seed, slow_energy, energy, mirror_voltages, authority_target_k = (
            _fixed_mirror_stripe_source_state(
                fixed_authority, mirror, stripe, contract,
            )
        )
    else:
        if mirror.get("status") not in {"success", "exact_k_operating_point_selected"}:
            # Current exact-K summary uses a richer role-specific status.  Require
            # the selected point below instead of accepting arbitrary summaries.
            if not isinstance(mirror.get("selected_operating_point"), dict):
                raise CandidateContractError("mirror summary has no selected exact-K operating point")
        selected_mirror = mirror.get("selected_operating_point")
        selected_stripe = stripe.get("selected_exact_k_operating_point")
        if not all(isinstance(value, dict) for value in (selected_mirror, selected_stripe)):
            raise CandidateContractError("mirror/Stripe summaries do not expose the selected exact-K point")
        energy = _finite(selected_mirror.get("energy_per_charge_v"), "mirror selected energy")
        seed, slow_energy = _schema5_native_source_state(stripe, contract, energy)
        if abs(
            _finite(selected_stripe.get("axial_energy_per_charge_v"), "Stripe selected energy")
            - energy
        ) > 1e-9:
            raise CandidateContractError("mirror and Stripe selected energies differ")
        mirror_voltages = _vector(
            selected_mirror.get("mirror_voltages_v"), 5, "mirror voltages",
        )
        authority_target_k = None
    mirror_voltages, mirror_variation = _apply_terminal_mirror_variation(
        variation=(
            _load(mirror_voltage_variation_path)
            if mirror_voltage_variation_path is not None else None
        ),
        base_voltages=mirror_voltages,
        contract=contract,
        axial_energy_v=energy,
    )
    target_turn_y, target_angle_degrees, target_tangent_ratio = (
        _p2_handoff_targets(seed, contract)
    )
    accelerator_energy = _accelerator_energy_binding(accelerator, energy)
    stripe_biases = _vector(seed.get("stripe_biases_v"), 2, "Stripe biases")
    if stripe_biases_override_v is not None:
        stripe_biases = [
            _finite(stripe_biases_override_v[0], "Stripe 1 override"),
            _finite(stripe_biases_override_v[1], "Stripe 2 override"),
        ]
    endpoint_voltages = _vector(accelerator.get("endpoint_voltages_v"), 3, "accelerator endpoint voltages")
    ring_voltages = _vector(accelerator.get("ring_voltages_v"), 5, "accelerator ring voltages")
    p1 = _finite(prism_1_v, "P1 voltage")
    p2 = _finite(prism_2_v, "P2 voltage")
    phase_contract = resolve_drift_phase_contract(contract)
    target_k = phase_contract.target_period_ratio
    if authority_target_k is not None and not math.isclose(
        authority_target_k, target_k, rel_tol=0.0, abs_tol=1e-12,
    ):
        raise CandidateContractError("fixed mirror/Stripe authority target K differs from the contract")
    pulse_schedule = _load_frozen_accelerator_pulse_schedule(
        accelerator_pulse_schedule_path
    )
    if pulse_accelerator_until_initial_exit and pulse_schedule is not None:
        raise CandidateContractError(
            "event-triggered and fixed-time accelerator pulse modes are mutually exclusive"
        )
    fixed_pulse_off_time = (
        _finite(pulse_schedule["pulse_off_time_us"], "accelerator pulse-off time")
        if pulse_schedule is not None else None
    )
    accelerator_pulse_requested = (
        pulse_accelerator_until_initial_exit or fixed_pulse_off_time is not None
    )
    source_contract = contract["particle_source"]
    species = source_contract["species"]
    bunch_source = (
        load_verified_bunch_source_receipt(bunch_source_receipt_path)
        if bunch_source_receipt_path is not None else None
    )
    if (bunch_particle_id_min is None) != (bunch_particle_id_max is None):
        raise CandidateContractError("bunch particle interval endpoints must be supplied together")
    bunch_selection = None
    if bunch_particle_id_min is not None:
        if bunch_source_receipt_path is None:
            raise CandidateContractError("bunch particle selection requires a frozen source receipt")
        if bunch_particle_id_max < bunch_particle_id_min:
            raise CandidateContractError(
                "managed bunch diagnostics require one or more contiguous particles"
            )
        if pulse_accelerator_until_initial_exit:
            raise CandidateContractError(
                "frozen source interval diagnostics forbid per-particle exit-triggered pulsing"
            )
        bunch_selection = resolve_bunch_source_interval(
            receipt_path=bunch_source_receipt_path,
            particle_id_min=bunch_particle_id_min,
            particle_id_max=bunch_particle_id_max,
        )
    if bunch_source is not None and pulse_accelerator_until_initial_exit:
        raise CandidateContractError(
            "N>1 bunch flights forbid initial_exit_triggered_single_center"
        )
    if bunch_source is not None and abs(
        _finite(bunch_source.get("common_time_of_birth_us"), "bunch common birth time")
    ) > 1.0e-15:
        raise CandidateContractError("MR-TOF batch dispatch requires common tob=0")
    selected_species = bunch_source["species"] if bunch_source is not None else species
    mass = _finite(selected_species.get("mass_th"), "particle mass")
    charge = int(selected_species.get("charge_e"))
    if (
        abs(mass - _finite(species.get("mass_th"), "contract particle mass")) > 1e-12
        or charge != int(species.get("charge_e"))
    ):
        raise CandidateContractError("bunch source species differs from the MR-TOF contract")
    if mass <= 0 or charge == 0 or slow_energy <= 0:
        raise CandidateContractError("P1/P2 source mass, charge, and slow energy must be physical")
    # The analyzer geometry review and the standalone accelerator are separate
    # authorities.  Resolve the release centre from the exact accelerator
    # contract that produced the consumed operating PA; an older analyzer
    # assembly must not translate a newer accelerator source.  Particle spread
    # remains a run input and therefore does not participate in either PA cache
    # identity.
    if provider_geometry is None:
        placement = derive_two_zone_placement(accelerator_geometry_contract)
        release = _finite(
            accelerator_geometry_contract["accelerator"].get(
                "release_position_in_gap_1_mm"
            ),
            "accelerator release",
        )
        aperture_height_y = _finite(
            accelerator_geometry_contract["accelerator"].get("aperture_height_y_mm"),
            "accelerator aperture height y",
        )
        release_z = placement.repeller_z_mm - release
    else:
        if provider_geometry.get("acceleration_direction") != "-z":
            raise CandidateContractError("provider accelerator must accelerate along -z")
        # The active MR contract owns the configurable Workbench y pose.  The
        # provider owns local z dimensions and exit-origin placement; the
        # historical analyzer review must not be required to carry a newer
        # assembly-only pose variable.
        placement = derive_two_zone_placement(contract)
        release = _finite(provider_geometry.get("release_position_in_gap_1_mm"), "provider accelerator release")
        repeller_to_exit = _finite(provider_geometry.get("repeller_to_exit_mm"), "provider repeller-to-exit distance")
        aperture_height_y = _finite(provider_geometry.get("aperture_height_y_mm"), "provider accelerator aperture height y")
        release_z = repeller_to_exit - release
    source_y_offset = _finite(source_y_offset_mm, "accelerator source y offset")
    aperture_half_y = aperture_height_y / 2.0
    if abs(source_y_offset) >= aperture_half_y:
        raise CandidateContractError("accelerator source y offset must remain inside its aperture")
    if bunch_source is not None and source_y_offset != 0.0:
        raise CandidateContractError(
            "a frozen bunch source already owns its centre; do not apply a second y offset"
        )
    center_fly2 = _single_center_source_fly2(
        mass_th=mass,
        charge_state=charge,
        source_slow_energy_per_charge_v=slow_energy,
        focus_y_mm=placement.focus_y_mm + source_y_offset,
        release_z_mm=release_z,
    )
    fly2 = (
        bunch_selection["fly2"] if bunch_selection is not None
        else Path(bunch_source["fly2"]["path"]).read_text(encoding="utf-8")
        if bunch_source is not None else center_fly2
    )
    if pulse_schedule is not None and pulse_schedule["schema_version"] == 1:
        if bunch_source is not None:
            raise CandidateContractError(
                "N>1 bunch flights require a schema-2 fixed-global-time schedule"
            )
        source_identity = pulse_schedule["source"]
        generated_fly2_sha256 = hashlib.sha256(fly2.encode("utf-8")).hexdigest()
        if generated_fly2_sha256.lower() != source_identity["source_fly2_sha256"].lower():
            raise CandidateContractError(
                "accelerator pulse schedule was derived from a different particle source"
            )
        if _sha256(accelerator_receipt_path).lower() != source_identity[
            "accelerator_receipt_sha256"
        ].lower():
            raise CandidateContractError(
                "accelerator pulse schedule was derived from a different accelerator voltage state"
            )
    resolved = _resolve_trial_geometry(
        reviewed_contract,
        # The accelerator voltage trial is an independently versioned voltage
        # receipt and may predate a project-level observation surface.  Bind
        # non-geometric topology/diagnostic authority from the current frozen
        # trajectory contract, as the IOB pose resolver does, while retaining
        # the reviewed contract as the sole physical geometry source.
        trajectory_contract,
        accelerator_geometry_contract,
    )
    detector = resolved["detector"]
    low_field_reference = resolved["two_prism_low_field_reference_section"]
    if low_field_reference.get("qualification") != "candidate_reference_section__not_a_zero_field_claim":
        raise CandidateContractError("resolved P2 reference plane has an invalid qualification")
    low_field_aperture = low_field_reference.get("transit_aperture_project_mm")
    if not isinstance(low_field_aperture, dict):
        raise CandidateContractError("resolved P2 reference plane lacks its transit aperture")
    regions = _mirror_regions(resolved)
    prism_regions: dict[str, list[float]] = {}
    shields_by_station = {
        item["station"]: item for item in reviewed_contract["prisms"]["ground_shields"]
    }
    for index, electrode in enumerate(reviewed_contract["prisms"]["electrodes"], 1):
        # Use the CAD-derived triangular clearance envelope rather than the
        # complete grounded-shield envelope.  The latter extends to the mirror
        # and would falsely place the P2 pass after the low-field reference.
        shield = shields_by_station[electrode["station"]]
        points = [
            (float(point[0]), float(point[1]))
            for point in shield["prism_clearance_polygon_yz_mm"]
        ]
        prism_regions[f"p{index}"] = [
            min(point[0] for point in points), max(point[0] for point in points),
            min(point[1] for point in points), max(point[1] for point in points),
        ]
    simion = contract["simion"]
    trajectory_profile = resolve_trajectory_profile(
        trajectory_contract, trajectory_profile_id,
    )
    trajectory_profile = _apply_trajectory_step_scale(
        trajectory_profile, trajectory_step_scale,
    )
    timeout = _full_path_timeout_us(contract, source_contract, target_k)
    p1_plane = _finite(contract["prism_transport"]["first_prism"]["target_interface"]["coordinate_mm"], "P1 plane")
    p1_acceptance = contract["prisms"]["ground_shields"][0]["rectangular_slots_mm"][0]["box"][1:5:3]
    accelerator_pulse_mode = "static"
    if pulse_accelerator_until_initial_exit:
        accelerator_pulse_mode = "initial_exit_triggered_single_center"
    elif fixed_pulse_off_time is not None:
        accelerator_pulse_mode = "fixed_global_time"
    accelerator_pulse_time_lua = (
        f"accelerator_pulse_off_time_us = {fixed_pulse_off_time:.17g}, "
        if fixed_pulse_off_time is not None else ""
    )
    sidecar = (
        "-- Generated run-local finite-3D P1/P2 voltage trial; do not edit.\n"
        f"return {{ qualification = 'p1_p2_finite_3d_voltage_trial_only', mirror_voltages_v = {_lua_vector(mirror_voltages)}, "
        f"stripe_biases_v = {_lua_vector(stripe_biases)}, prism_voltages_v = {_lua_vector([p1, p2])}, "
        f"accelerator_voltages_v = {_lua_vector(endpoint_voltages)}, accelerator_ring_voltages_v = {_lua_vector(ring_voltages)}, "
        f"first_prism_l0 = {{ target_plane_z_mm = {p1_plane:.17g}, target_plane_x_mm = 0, target_plane_y_acceptance_mm = {_lua_vector([float(v) for v in p1_acceptance])} }}, "
        f"mirror_regions_project = {{ negative = {{ z_min_mm = {regions['negative'][0]:.17g}, z_max_mm = {regions['negative'][1]:.17g} }}, positive = {{ z_min_mm = {regions['positive'][0]:.17g}, z_max_mm = {regions['positive'][1]:.17g} }} }}, "
        f"prism_regions_project = {{ p1 = {{ y_min_mm = {prism_regions['p1'][0]:.17g}, y_max_mm = {prism_regions['p1'][1]:.17g}, z_min_mm = {prism_regions['p1'][2]:.17g}, z_max_mm = {prism_regions['p1'][3]:.17g} }}, p2 = {{ y_min_mm = {prism_regions['p2'][0]:.17g}, y_max_mm = {prism_regions['p2'][1]:.17g}, z_min_mm = {prism_regions['p2'][2]:.17g}, z_max_mm = {prism_regions['p2'][3]:.17g} }} }}, "
        f"p2_low_field_reference = {{ z_mm = {_finite(low_field_reference['reference_plane_project_z_mm'], 'P2 low-field reference z'):.17g}, x_min_mm = {_finite(low_field_aperture['x_mm'][0], 'P2 low-field x minimum'):.17g}, x_max_mm = {_finite(low_field_aperture['x_mm'][1], 'P2 low-field x maximum'):.17g}, y_min_mm = {_finite(low_field_aperture['y_mm'][0], 'P2 low-field y minimum'):.17g}, y_max_mm = {_finite(low_field_aperture['y_mm'][1], 'P2 low-field y maximum'):.17g} }}, "
        f"phase_origin_mirror_side = {phase_contract.origin_mirror_side}, return_mirror_side = {phase_contract.return_mirror_side}, "
        f"detector_box_mm = {_lua_vector([float(v) for v in detector['box']])}, detector_normal_project = '+z', "
        f"trajectory_quality = {float(trajectory_profile['trajectory_quality']):.17g}, maximum_step_us = {float(trajectory_profile['maximum_step_us']):.17g}, "
        f"full_path_timeout_us = {timeout:.17g}, nonaccelerator_scale = {_finite(simion['nonaccelerator_scale'], 'nonaccelerator scale'):.17g}, "
        f"target_drift_period_ratio = {target_k:.17g}, target_half_oscillation_count = {phase_contract.target_half_oscillation_count}, "
        f"runtime_fast_adjust_enable = {'true' if runtime_fast_adjust_enable else 'false'}, "
        f"accelerator_safe_exit_only = {'true' if accelerator_safe_exit_only else 'false'}, "
        f"runtime_accelerator_field_gate_enable = {'true' if accelerator_pulse_requested else 'false'}, "
        f"accelerator_pulse_mode = '{accelerator_pulse_mode}', "
        f"{accelerator_pulse_time_lua}"
        "flight_scope = 'complete_three_dimensional_static_return' }\n"
    )
    fly2_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    fly2_path.write_text(fly2, encoding="utf-8", newline="\n")
    sidecar_path.write_text(sidecar, encoding="utf-8", newline="\n")
    analyzer_values = (
        mirror_voltages
        + mirror_voltages
        + [stripe_biases[0], stripe_biases[0], stripe_biases[1], stripe_biases[1], 0.0, p1, p2, 0.0, 0.0, 0.0]
    )
    receipt = {
        "schema_version": 1,
        "role": "mrtof_finite_3d_two_prism_voltage_trial",
        "status": "materialized",
        "qualification": (
            "contiguous_frozen_bunch_diagnostic__not_formal"
            if bunch_selection is not None
            else "complete_bunch_pilot_or_fixed_clock_trial__performance_pending"
            if bunch_source is not None else "single_center_trial__not_an_operating_point"
        ),
        "flight_scope": "complete_three_dimensional_static_return",
        "selected_axial_energy_per_charge_v": energy,
        "source_slow_kinetic_energy_per_charge_v": slow_energy,
        "source_position_project_mm": (
            None if bunch_source is not None else [
                0.0, placement.focus_y_mm + source_y_offset, release_z,
            ]
        ),
        "source_y_offset_from_accelerator_axis_mm": (
            None if bunch_source is not None else source_y_offset
        ),
        "source_direction_project": None if bunch_source is not None else [0.0, 1.0, 0.0],
        "source_particle_count": (
            len(bunch_selection["particle_ids"])
            if bunch_selection is not None
            else bunch_source["particle_count"] if bunch_source is not None else 1
        ),
        "source_time_of_birth_us": (
            bunch_source["common_time_of_birth_us"] if bunch_source is not None else 0.0
        ),
        "source_clock_basis": _GLOBAL_PULSE_TIME_BASIS,
        "source_cohort": (
            bunch_selection["source_cohort"]
            if bunch_selection is not None
            else source_cohort_identity(bunch_source) if bunch_source is not None else None
        ),
        "source_expected_particle_ids": (
            bunch_selection["particle_ids"]
            if bunch_selection is not None
            else bunch_source["expected_particle_ids"] if bunch_source is not None else [1]
        ),
        "source_selection": (
            bunch_selection["source_cohort"]["selection"]
            if bunch_selection is not None else None
        ),
        "mirror_voltages_v": mirror_voltages,
        "terminal_time_mirror_variation": mirror_variation,
        "stripe_biases_v": stripe_biases,
        "prism_voltages_v": [p1, p2],
        "detector_box_mm": [float(v) for v in detector["box"]],
        "accelerator_endpoint_voltages_v": endpoint_voltages,
        "accelerator_ring_voltages_v": ring_voltages,
        "accelerator_applied_net_gain_parameter_v": accelerator_energy[
            "applied_net_gain_parameter_v"
        ],
        "accelerator_target_axial_energy_per_charge_v": accelerator_energy[
            "target_axial_energy_per_charge_v"
        ],
        "accelerator_finite_3d_gain_correction_v": accelerator_energy[
            "finite_3d_gain_correction_v"
        ],
        "analyzer_electrode_voltages_v": analyzer_values,
        "target_positive_mirror_turn_y_mm": target_turn_y,
        "target_nominal_injection_angle_degrees": target_angle_degrees,
        "target_low_field_tangent_ratio_vy_over_vz": target_tangent_ratio,
        "p2_low_field_reference_section": low_field_reference,
        "drift_phase_contract": phase_contract.as_dict(),
        "p1_p2_handoff_definition": (
            "P1 -> negative-mirror diagnostic turn -> P2 -> low-field Candidate "
            "reference crossing -> first positive-mirror turn"
        ),
        "detector_return_policy_authority": {
            "source": "trajectory_contract",
            "policy": detector_return_policy,
            "legacy_physical_contracts_rebound_without_mutation": True,
        },
        "target_slow_turn_y_mm": _finite(
            contract["dual_stripe_l0"]["manufactured_design_abs_drift_length_L_mm"],
            "manufactured drift length",
        ),
        "target_drift_period_ratio": target_k,
        "target_half_oscillation_count": phase_contract.target_half_oscillation_count,
        "runtime_fast_adjust_enable": bool(runtime_fast_adjust_enable),
        "accelerator_instance": accelerator_instance,
        "accelerator_pulse": {
            "mode": accelerator_pulse_mode,
            "pulse_off_time_us": fixed_pulse_off_time,
            "energized_before_initial_exit": (
                True if pulse_accelerator_until_initial_exit else None
            ),
            "grounded_after_initial_exit": (
                True if pulse_accelerator_until_initial_exit else None
            ),
            "fixed_global_time_applied": fixed_pulse_off_time is not None,
            "qualification": (
                "single_center_event_triggered_schedule__must_be_replaced_by_one_frozen_global_time_for_any_bunch"
                if pulse_accelerator_until_initial_exit
                else (
                    "frozen_global_time_single_center_diagnostic__bunch_qualification_pending"
                    if fixed_pulse_off_time is not None else "static_accelerator"
                )
            ),
        },
        "execution_scope": (
            "accelerator_safe_exit_envelope_only"
            if accelerator_safe_exit_only
            else "complete_three_dimensional_static_return"
        ),
        "particle_mass_th": mass,
        "charge_state": charge,
        "trajectory_profile": trajectory_profile,
        "nonaccelerator_mesh_mm_per_gu": list(
            simion["component_mesh_mm_per_gu"]["analyzer"]
        ),
        "inputs": {
            "contract_sha256": _sha256(contract_path),
            "accelerator_geometry_contract_sha256": _sha256(
                accelerator_geometry_contract_path
            ),
            "trajectory_contract_sha256": _sha256(trajectory_contract_path),
            "reviewed_contract_sha256": _sha256(reviewed_contract_path),
            "mirror_summary_sha256": _sha256(mirror_summary_path),
            "stripe_summary_sha256": _sha256(stripe_summary_path),
            **({
                "fixed_mirror_stripe_authority_sha256": _sha256(
                    fixed_mirror_stripe_authority_path
                ),
            } if fixed_mirror_stripe_authority_path is not None else {}),
            "accelerator_receipt_sha256": _sha256(accelerator_receipt_path),
            **({
                "accelerator_pulse_schedule_sha256": _sha256(
                    accelerator_pulse_schedule_path
                ),
            } if accelerator_pulse_schedule_path is not None else {}),
            **({
                "bunch_source_receipt_sha256": _sha256(bunch_source_receipt_path),
            } if bunch_source_receipt_path is not None else {}),
        },
        "fly2_sha256": _sha256(fly2_path),
        "operating_point_lua_sha256": _sha256(sidecar_path),
    }
    if pulse_schedule is not None and pulse_schedule["schema_version"] == 2:
        if bunch_source is None:
            raise CandidateContractError("bunch pulse schedule requires a frozen bunch source")
        if pulse_schedule["source_cohort"] != receipt["source_cohort"]:
            raise CandidateContractError("pulse schedule source differs from the flight cohort")
        expected_solver_identity = pulse_schedule["solver_problem_identity"]
        actual_solver_identity = solver_problem_identity_from_trial_receipt(receipt)
        if expected_solver_identity != actual_solver_identity:
            differing_fields = sorted(
                key
                for key in set(expected_solver_identity) | set(actual_solver_identity)
                if expected_solver_identity.get(key) != actual_solver_identity.get(key)
            )
            raise CandidateContractError(
                "pulse schedule solver problem differs from the flight; fields="
                + ",".join(differing_fields)
            )
        receipt["accelerator_pulse"]["qualification"] = (
            "complete_bunch_safe_exit_schedule__numerical_convergence_pending"
        )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def analyze_trial(*, log_path: Path, trial_receipt_path: Path, output_path: Path) -> dict[str, Any]:
    trial = _load(trial_receipt_path)
    if trial.get("prism_switch") is not None:
        raise CandidateContractError(
            "active MR-TOF Candidate observation forbids all P1/P2 voltage switching"
        )
    log_text = log_path.read_text(encoding="utf-8")
    events = parse_events(log_text)
    if any(event["kind"] == "prism_voltage_switch" for event in events):
        raise CandidateContractError(
            "active MR-TOF Candidate log contains a forbidden P1/P2 voltage switch"
        )
    pulse_contract = trial.get("accelerator_pulse") or {"mode": "static"}
    pulse_mode = pulse_contract.get("mode")
    if pulse_mode not in {
        "static", "initial_exit_triggered_single_center", "fixed_global_time",
    }:
        raise CandidateContractError("trial has an unsupported accelerator pulse mode")
    exit_pulse_events = [
        event for event in events if event["kind"] == "accelerator_pulse_off"
    ]
    global_pulse_events = [
        event for event in events
        if event["kind"] == "accelerator_global_pulse_applied"
    ]
    if pulse_mode == "initial_exit_triggered_single_center":
        if len(exit_pulse_events) != 1 or global_pulse_events:
            raise CandidateContractError(
                "initial-exit-triggered accelerator trial must emit exactly one pulse-off event"
            )
        accelerator_instance = int(trial.get("accelerator_instance", 3))
        if accelerator_instance != 3:
            raise CandidateContractError("trial has an invalid native accelerator instance")
        if (
            int(exit_pulse_events[0]["from_instance"]) != accelerator_instance
            or int(exit_pulse_events[0]["to_instance"]) == accelerator_instance
        ):
            raise CandidateContractError(
                "accelerator pulse-off event must be the first exit from the declared accelerator instance"
            )
    elif pulse_mode == "fixed_global_time":
        configured_time = _finite(
            pulse_contract.get("pulse_off_time_us"), "fixed accelerator pulse-off time"
        )
        if configured_time <= 0 or exit_pulse_events:
            raise CandidateContractError(
                "fixed-time accelerator trial must define a positive time and emit no exit-triggered pulse event"
            )
        expected_particle_ids = trial.get("source_expected_particle_ids")
        if expected_particle_ids is None:
            expected_particle_ids = [1]
        pulse_validation = validate_fixed_global_pulse_events(
            events=events,
            expected_particle_ids=expected_particle_ids,
            pulse_off_time_us=configured_time,
            time_tolerance_us=max(1e-9, abs(configured_time) * 1e-9),
            accelerator_instance=int(trial.get("accelerator_instance", 3)),
        )
    elif exit_pulse_events or global_pulse_events:
        raise CandidateContractError("static accelerator trial emitted an unexpected pulse-off event")
    pulse_events = exit_pulse_events + global_pulse_events
    kinds: dict[str, int] = {}
    for event in events:
        kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
    result: dict[str, Any] = {
        "schema_version": 1,
        "role": "mrtof_finite_3d_two_prism_trial_observation",
        "status": "p2_low_field_and_positive_mirror_turn_incomplete",
        "qualification": "single_center_trial__not_an_operating_point",
        "prism_voltages_v": trial["prism_voltages_v"],
        "event_counts": kinds,
        "log_sha256": _sha256(log_path),
        "trial_receipt_sha256": _sha256(trial_receipt_path),
        "accelerator_pulse_diagnostic": {
            "mode": pulse_mode,
            "pulse_off_event_count": len(pulse_events),
            "pulse_off_event": pulse_events[0] if pulse_events else None,
            "fixed_global_pulse_validation": (
                pulse_validation if pulse_mode == "fixed_global_time" else None
            ),
            "qualification": pulse_contract.get("qualification"),
        },
    }
    source_particle_count = int(trial.get("source_particle_count", 1))
    source_cohort = trial.get("source_cohort")
    if source_cohort is not None:
        if not isinstance(source_cohort, dict):
            raise CandidateContractError("bunch trial source cohort must be an object")
        expected_ids = trial.get("source_expected_particle_ids")
        if (
            not isinstance(expected_ids, list)
            or len(expected_ids) != source_particle_count
            or any(type(value) is not int for value in expected_ids)
            or expected_ids != list(range(expected_ids[0], expected_ids[0] + source_particle_count))
        ):
            raise CandidateContractError(
                "bunch trial receipt lacks one complete contiguous ordered particle cohort"
            )
        completion_matches = list(FLY_COMPLETED.finditer(log_text))
        reported_splats = (
            int(completion_matches[0].group("splats"))
            if len(completion_matches) == 1 else None
        )
        cohort = summarize_events(
            events,
            _finite(trial.get("target_drift_period_ratio"), "target drift period ratio"),
            reported_splats,
            expected_particle_ids=tuple(expected_ids),
            completion_count=len(completion_matches),
            kinetic_energy_ev=_finite(
                trial.get("selected_axial_energy_per_charge_v"),
                "selected axial energy",
            ),
            mass_th=_finite(trial.get("particle_mass_th"), "particle mass"),
        )
        safe_exit_ids = sorted({
            int(event["ion"])
            for event in events if event["kind"] == "accelerator_safe_exit"
        })
        cohort["accelerator_safe_exit_particle_ids"] = safe_exit_ids
        cohort["accelerator_safe_exit_count"] = len(safe_exit_ids)
        cohort["accelerator_safe_exit_fraction"] = (
            len(safe_exit_ids) / source_particle_count
        )
        cohort["accelerator_safe_exit_complete"] = safe_exit_ids == expected_ids
        result.update({
            "status": "bunch_observed" if cohort["event_integrity_passed"] else "bunch_observation_invalid",
            "qualification": (
                "candidate_bunch_selection_diagnostic__not_formal"
                if trial.get("source_selection") is not None
                else "candidate_bunch__not_formal"
            ),
            "cohort_analysis": cohort,
            "source_release_state": None,
            "accelerator_safe_exit_observation": {
                "status": "complete_cohort_observed" if safe_exit_ids == expected_ids else "incomplete_cohort",
                "particle_ids": safe_exit_ids,
                "expected_particle_ids": expected_ids,
            },
            "termination_diagnostic": {
                "status": "cohort",
                "particle_terminal_count": cohort["particle_terminal_count"],
                "splat_code_histogram": cohort["splat_code_histogram"],
                "all_losses_retained": cohort["all_losses_retained"],
            },
        })
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    source, source_state = _single_center_source_state(trial)
    result["source_release_state"] = source_state
    result["accelerator_safe_exit_observation"] = _accelerator_safe_exit_observation(
        events, trial, log_path=log_path, trial_receipt_path=trial_receipt_path,
    )
    target_k_contract = _finite(trial.get("target_drift_period_ratio"), "target drift period ratio")
    result["termination_diagnostic"] = _termination_diagnostic(events)
    static_return = _static_return_diagnostic(events, target_k_contract)
    result["static_return_diagnostic"] = static_return
    # Keep the runner's established summary field while changing its contents
    # to the only active extraction contract: an unchanged-voltage return.
    result["extraction_diagnostic"] = static_return
    try:
        handoff_events = events
        turn_indices = [
            index for index, event in enumerate(events)
            if event["kind"] == "pre_origin_positive_mirror_turn"
        ]
        if len(turn_indices) == 1:
            # Downstream loss does not erase an already observed injection
            # hand-off.  Validate the prefix independently while retaining
            # the complete unfiltered log for all full-flight diagnostics.
            handoff_events = events[: turn_indices[0] + 1] + [
                {"kind": "terminal", "ion": 1, "splat": 5}
            ]
        observation = observation_from_simion_events(handoff_events, source)
        residuals = prism_handoff_residuals(
            observation,
            target_positive_mirror_turn_y_mm=float(
                trial["target_positive_mirror_turn_y_mm"]
            ),
            target_tangent_ratio_vy_over_vz=float(
                trial["target_low_field_tangent_ratio_vy_over_vz"]
            ),
        )
    except CandidateContractError as error:
        result["incomplete_reason"] = str(error)
        terminals = [event for event in events if event["kind"] in {"splat", "terminal"}]
        result["terminal_events"] = terminals
    else:
        result.update({
            "status": "p2_low_field_and_positive_mirror_turn_observed",
            "p1_state": {
                "position_mm": observation.prism_1.position_mm,
                "velocity_mm_per_us": observation.prism_1.velocity_mm_per_us,
            },
            "p2_low_field_reference_state": {
                "position_mm": observation.p2_shield_low_field_reference.position_mm,
                "velocity_mm_per_us": observation.p2_shield_low_field_reference.velocity_mm_per_us,
            },
            "positive_mirror_turn_state": {
                "position_mm": observation.positive_mirror_turn.position_mm,
                "velocity_mm_per_us": observation.positive_mirror_turn.velocity_mm_per_us,
            },
            "residuals": {name: value for name, value in residuals},
        })
        phase_events = [event for event in events if event["kind"] == "drift_phase_origin"]
        if len(phase_events) != 1:
            raise CandidateContractError("complete trial must contain one drift phase origin")
        phase_time = _finite(phase_events[0].get("t_us"), "drift phase-origin time")
        slow_turns = [
            event for event in events
            if event["kind"] == "slow_turn" and float(event["t_us"]) > phase_time
        ]
        coordinate_returns = [
            event for event in events
            if event["kind"] == "drift_coordinate_return" and float(event["t_us"]) > phase_time
        ]
        exact_phase_returns = [
            event for event in events
            if event["kind"] == "drift_phase_return"
            and float(event["t_us"]) > phase_time
            and float(event["k"]) == target_k_contract
        ]
        return_event_valid = len(coordinate_returns) == 1 or (
            not coordinate_returns and len(exact_phase_returns) == 1
        )
        if not slow_turns or not return_event_valid:
            result["status"] = "full_drift_incomplete"
            result["incomplete_reason"] = (
                "complete trial must observe a post-origin slow turn and either "
                "one coordinate return or one exact target-K phase return"
            )
        else:
            slow_turn_y = _finite(slow_turns[0].get("y_mm"), "observed slow turn y")
            if coordinate_returns:
                coordinate_return = coordinate_returns[0]
                # A coordinate return may occur before the requested target
                # mirror phase.  In that case the ion can reach the physical
                # detector before a target-K turn exists, so there is no
                # legitimate target-phase y sample to report.  Preserve the
                # observed fractional-K residual instead of turning a valid
                # flight into a post-processing failure.
                phase_crossing_y = coordinate_return.get("phase_crossing_y_mm")
                if phase_crossing_y is None:
                    # Older flight programs emitted only the preceding
                    # discrete half-cycle.  Recover the same continuous phase
                    # diagnostic from the latest two same-side mirror turns;
                    # this is observation analysis, not a new trajectory.
                    return_time = _finite(coordinate_return.get("t_us"), "coordinate-return time")
                    candidates = [
                        event for event in events
                        if event["kind"] == "drift_phase_candidate"
                        and phase_time < float(event["t_us"]) <= return_time
                    ]
                    if candidates:
                        latest = candidates[-1]
                        latest_side = 1 if _finite(latest.get("z_mm"), "phase-candidate z") > 0 else -1
                        previous_same_side = next((
                            event for event in reversed(candidates[:-1])
                            if (1 if _finite(event.get("z_mm"), "phase-candidate z") > 0 else -1)
                            == latest_side
                        ), None)
                        if previous_same_side is not None:
                            period = _finite(latest.get("t_us"), "latest phase time") - _finite(
                                previous_same_side.get("t_us"), "previous same-side phase time"
                            )
                            elapsed = return_time - _finite(latest.get("t_us"), "latest phase time")
                            if period > 0.0 and elapsed >= 0.0:
                                coordinate_return["phase_crossing_t_us"] = latest["t_us"]
                                coordinate_return["phase_crossing_y_mm"] = latest["y_mm"]
                                coordinate_return["phase_time_residual_us"] = elapsed
                                coordinate_return["phase_period_us"] = period
                                coordinate_return["fractional_k"] = (
                                    _finite(latest.get("k"), "latest phase K") + elapsed / period
                                )
                                phase_crossing_y = latest["y_mm"]
                fractional_k = _finite(
                    coordinate_return.get("fractional_k"), "observed fractional K"
                )
                exact_coordinate_return = (
                    len(exact_phase_returns) == 1
                    and math.isclose(fractional_k, target_k_contract, rel_tol=0.0, abs_tol=1.0e-12)
                )
                preceding_phase_y = (
                    _finite(phase_crossing_y, "preceding phase crossing y")
                    if phase_crossing_y is not None else None
                )
                target_phase_samples = [
                    event for event in events
                    if event["kind"] == "target_k_phase_sample"
                    and float(event["t_us"]) > phase_time
                    and float(event["k"]) == target_k_contract
                ]
                if len(target_phase_samples) > 1:
                    raise CandidateContractError(
                        "coordinate-return flight has multiple target phase samples"
                    )
                observed_target_phase_y = (
                    _finite(target_phase_samples[0].get("y_mm"), "target-phase sample y")
                    if target_phase_samples else None
                )
                target_phase_y = (
                    preceding_phase_y if exact_coordinate_return else observed_target_phase_y
                )
                return_topology = (
                    "exact_target_k_phase_return" if exact_coordinate_return
                    else "coordinate_return_before_target_phase"
                )
            else:
                fractional_k = float(target_k_contract)
                target_phase_samples = [
                    event for event in events
                    if event["kind"] == "target_k_phase_sample"
                    and float(event["t_us"]) > phase_time
                    and float(event["k"]) == target_k_contract
                ]
                if len(target_phase_samples) != 1:
                    raise CandidateContractError(
                        "exact target-K return requires one target phase sample"
                    )
                target_phase_y = _finite(
                    target_phase_samples[0].get("y_mm"), "target-phase sample y"
                )
                return_topology = "exact_target_k_phase_return"
            target_y = _finite(trial.get("target_slow_turn_y_mm"), "target slow turn y")
            target_k = _finite(trial.get("target_drift_period_ratio"), "target K")
            phase_origin_y = _finite(
                trial.get("target_positive_mirror_turn_y_mm"), "target phase-origin y"
            )
            result["status"] = "full_drift_observed"
            result["slow_turn_y_mm"] = slow_turn_y
            result["fractional_k"] = fractional_k
            result["target_phase_y_mm"] = target_phase_y
            if coordinate_returns:
                result["preceding_phase_y_mm"] = preceding_phase_y
            result["return_topology"] = return_topology
            result["residuals"].update({
                "Stripe_slow_turn_y_minus_L_mm": slow_turn_y - target_y,
                "Stripe_fractional_K_minus_target": fractional_k - target_k,
            })
            if target_phase_y is not None:
                result["residuals"]["Stripe_target_phase_y_minus_origin_mm"] = (
                    target_phase_y - phase_origin_y
                )
            elif coordinate_returns and preceding_phase_y is not None:
                result["residuals"]["Stripe_preceding_phase_y_minus_origin_mm"] = (
                    preceding_phase_y - phase_origin_y
                )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--contract", required=True, type=Path)
    materialize.add_argument("--accelerator-geometry-contract", required=True, type=Path)
    materialize.add_argument("--trajectory-contract", required=True, type=Path)
    materialize.add_argument("--reviewed-contract", required=True, type=Path)
    materialize.add_argument("--mirror-summary", required=True, type=Path)
    materialize.add_argument("--stripe-summary", required=True, type=Path)
    materialize.add_argument("--fixed-mirror-stripe-authority", type=Path)
    materialize.add_argument("--mirror-voltage-variation", type=Path)
    materialize.add_argument("--accelerator-receipt", required=True, type=Path)
    materialize.add_argument("--prism-1-v", required=True, type=float)
    materialize.add_argument("--prism-2-v", required=True, type=float)
    materialize.add_argument("--stripe-1-v", type=float)
    materialize.add_argument("--stripe-2-v", type=float)
    materialize.add_argument("--runtime-fast-adjust-enable", action="store_true")
    materialize.add_argument("--pulse-accelerator-until-initial-exit", action="store_true")
    materialize.add_argument("--accelerator-safe-exit-only", action="store_true")
    materialize.add_argument("--accelerator-pulse-schedule", type=Path)
    materialize.add_argument("--trajectory-profile-id")
    materialize.add_argument("--trajectory-step-scale", type=float, default=1.0)
    materialize.add_argument("--source-y-offset-mm", type=float, default=0.0)
    materialize.add_argument("--bunch-source-receipt", type=Path)
    materialize.add_argument("--bunch-particle-id-min", type=int)
    materialize.add_argument("--bunch-particle-id-max", type=int)
    materialize.add_argument("--workbench-accelerator-instance", required=True, type=int, choices=(2, 3, 7))
    materialize.add_argument("--fly2", required=True, type=Path)
    materialize.add_argument("--sidecar", required=True, type=Path)
    materialize.add_argument("--receipt", required=True, type=Path)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--log", required=True, type=Path)
    analyze.add_argument("--trial-receipt", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    freeze = sub.add_parser("freeze-pulse-schedule")
    freeze.add_argument("--center-run", required=True, type=Path)
    freeze.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "materialize":
        stripe_override = None
        if (args.stripe_1_v is None) != (args.stripe_2_v is None):
            parser.error("--stripe-1-v and --stripe-2-v must be supplied together")
        if args.stripe_1_v is not None:
            stripe_override = (args.stripe_1_v, args.stripe_2_v)
        result = materialize_trial(
            contract_path=args.contract,
            accelerator_geometry_contract_path=args.accelerator_geometry_contract,
            trajectory_contract_path=args.trajectory_contract,
            reviewed_contract_path=args.reviewed_contract,
            mirror_summary_path=args.mirror_summary,
            stripe_summary_path=args.stripe_summary,
            fixed_mirror_stripe_authority_path=args.fixed_mirror_stripe_authority,
            mirror_voltage_variation_path=args.mirror_voltage_variation,
            accelerator_receipt_path=args.accelerator_receipt,
            prism_1_v=args.prism_1_v,
            prism_2_v=args.prism_2_v,
            stripe_biases_override_v=stripe_override,
            runtime_fast_adjust_enable=args.runtime_fast_adjust_enable,
            pulse_accelerator_until_initial_exit=args.pulse_accelerator_until_initial_exit,
            accelerator_safe_exit_only=args.accelerator_safe_exit_only,
            accelerator_pulse_schedule_path=args.accelerator_pulse_schedule,
            trajectory_profile_id=args.trajectory_profile_id,
            trajectory_step_scale=args.trajectory_step_scale,
            source_y_offset_mm=args.source_y_offset_mm,
            bunch_source_receipt_path=args.bunch_source_receipt,
            bunch_particle_id_min=args.bunch_particle_id_min,
            bunch_particle_id_max=args.bunch_particle_id_max,
            accelerator_instance=args.workbench_accelerator_instance,
            fly2_path=args.fly2,
            sidecar_path=args.sidecar,
            receipt_path=args.receipt,
        )
        print(f"MRTOF_TWO_PRISM_TRIAL_MATERIALIZE=PASS P1={result['prism_voltages_v'][0]:.12g} P2={result['prism_voltages_v'][1]:.12g}")
    elif args.command == "analyze":
        result = analyze_trial(log_path=args.log, trial_receipt_path=args.trial_receipt, output_path=args.output)
        print(f"MRTOF_TWO_PRISM_TRIAL_ANALYZE=PASS STATUS={result['status']}")
    else:
        result = freeze_single_center_pulse_schedule(
            center_run_path=args.center_run, output_path=args.output,
        )
        print(
            "MRTOF_ACCELERATOR_PULSE_SCHEDULE=PASS "
            f"TIME_US={result['pulse_off_time_us']:.12g}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
