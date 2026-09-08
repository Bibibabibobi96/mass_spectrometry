"""Component-level P1/P2-to-Stripe phase-space hand-off for joint solves.

The source-to-analyser trajectory is evaluated by the finite three-dimensional
solver.  This module deliberately does not approximate either triangular
prism.  In the manufactured topology the ion undergoes a negative-mirror
pre-reflection between P1 and P2, then traverses the positive-side Stripe
bands after P2 before reaching the selected slow-drift phase origin:
the first post-P2 mirror turn at the registered function coordinate ``y=0``.
For the manufactured path P2 is exited along positive project z, so this is
the positive mirror turn.
Its ``z`` coordinate is observed from the Stripe-on three-dimensional
trajectory rather than imposed from a mechanical endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from common.contracts.particle_physics import kinetic_energy_ev
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def audit_two_prism_voltage_definition(contract: dict[str, Any]) -> dict[str, Any]:
    """Classify whether the two pre-Stripe prism voltages are structurally defined.

    In the project-symmetric ``y-z`` transport, the two voltages are two
    physical unknowns.  The compatible Mirror--Stripe solution supplies the
    slow kinetic energy/direction, while the first post-P2 mirror turn must
    occur at the registered function coordinate ``y=0``.  These are the two
    physical targets.  At that event ``v_z=0`` and ``z`` is an event-localized
    full-field result; ``x=0`` follows from symmetry and is not an independently
    steerable residual.
    """
    if not isinstance(contract, dict):
        raise CandidateContractError("two-prism definition audit needs a contract object")
    transport = contract.get("prism_transport")
    model = transport.get("two_prism_injection_l0") if isinstance(transport, dict) else None
    if not isinstance(model, dict):
        raise CandidateContractError("two-prism definition audit needs prism_transport.two_prism_injection_l0")
    try:
        prism_ids = (
            int(transport["first_prism"]["electrode_id"]),
            int(transport["second_prism"]["electrode_id"]),
        )
        origin_y = float(
            contract["dual_stripe_l0"]["theory_function_coordinate_registration"]
            ["function_y_zero_project_y_mm"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("two-prism definition audit lacks prism identities or function-origin y") from error
    if prism_ids[0] == prism_ids[1] or not math.isfinite(origin_y):
        raise CandidateContractError("two-prism identities must be distinct and the function-origin y finite")
    geometry = contract.get("prisms")
    electrodes = geometry.get("electrodes") if isinstance(geometry, dict) else None
    shields = geometry.get("ground_shields") if isinstance(geometry, dict) else None
    if not isinstance(electrodes, list) or not isinstance(shields, list):
        raise CandidateContractError("two-prism definition audit needs prism and grounded-shield geometry")
    second_electrodes = [item for item in electrodes if isinstance(item, dict) and item.get("id") == prism_ids[1]]
    if len(second_electrodes) != 1:
        raise CandidateContractError("two-prism definition audit needs exactly one P2 geometry")
    p2_station = second_electrodes[0].get("station")
    matching_shields = [item for item in shields if isinstance(item, dict) and item.get("station") == p2_station]
    if len(matching_shields) != 1:
        raise CandidateContractError("two-prism definition audit needs exactly one grounded shield at the P2 station")
    aperture = matching_shields[0].get("cross_aperture")
    try:
        mechanical_z = tuple(float(value) for value in aperture["z_mm"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("P2 shield must declare its cross-aperture z bounds") from error
    if len(mechanical_z) != 2 or not all(math.isfinite(value) for value in mechanical_z) or not mechanical_z[0] < mechanical_z[1]:
        raise CandidateContractError("P2 shield cross-aperture z bounds must be finite and ordered")

    common = {
        "unknowns": [
            f"prism_1_id_{prism_ids[0]}_voltage_v",
            f"prism_2_id_{prism_ids[1]}_voltage_v",
        ],
        "unknown_count": 2,
        "independent_target_conditions_before_finite_3d_jacobian": [
            f"first_post_P2_mirror_turn_project_y_equals_{origin_y:g}_mm",
            "positive_project_y_slow_kinetic_energy_from_the_compatible_Mirror_Stripe_solution",
        ],
        "event_or_symmetry_conditions_not_counted_as_voltage_residuals": [
            "phase_origin_mirror_turn_has_v_z_equals_0_by_event_definition",
            "turn_project_z_is_observed_from_the_Stripe_on_full_field_trajectory",
            "project_x_equals_0_is_invariant_under_x_symmetric_geometry_and_voltages",
        ],
        "forbidden_implicit_fast_phase_substitutions": [
            "prism_triangle_centroid",
            "grounded_shield_aperture_centroid",
            "CAD_bounding_box_center",
        ],
        "p2_exit_mechanical_acceptance": {
            "project_z_open_interval_mm": [mechanical_z[0], mechanical_z[1]],
            "source": f"P2_station_grounded_shield_id_{matching_shields[0].get('id')}_cross_aperture",
            "semantics": "a collision-free P2-exit bound only; the later drift-origin turn lies in the positive mirror",
        },
    }
    phase = model.get("drift_phase_origin_authority")
    if not isinstance(phase, dict) or phase.get("status") != "derived_design_authority":
        raise CandidateContractError("two-prism definition needs the derived drift-phase-origin authority")
    required = {
        "event": "first_post_P2_stripe_on_mirror_turn",
        "target_project_z_rule": "not_an_independent_target__observe_the_Stripe_on_full_field_turn__bare_mirror_turn_is_seed_only",
        "fast_velocity_condition": "v_z=0 with outward positive-z motion reversing toward negative z",
    }
    for key, expected in required.items():
        if phase.get(key) != expected:
            raise CandidateContractError(f"drift-phase-origin authority has an incompatible {key}")
    try:
        target_y = float(phase["target_project_y_mm"])
        target_x = float(phase["target_project_x_mm"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("slow-drift-origin authority needs finite x/y targets") from error
    source = str(phase.get("source", ""))
    if not math.isfinite(target_y) or not math.isfinite(target_x) or target_y != origin_y or target_x != 0.0 or not source:
        raise CandidateContractError("drift-phase-origin authority conflicts with the project symmetry/function origin")
    if "target_project_z_mm" in phase:
        raise CandidateContractError("mirror-turn z must be derived rather than entered as a fixed target")
    return {
        **common,
        "status": "two_physical_targets_declared__finite_3d_jacobian_pending",
        "drift_phase_origin_event": phase["event"],
        "derived_turn_z_rule": phase["target_project_z_rule"],
        "drift_phase_authority_source": source,
        "independent_voltage_constraint_rank_before_finite_3d_jacobian": None,
        "nullity_before_finite_3d_jacobian": None,
        "publication_gate": "closed_until_scaled_finite_3d_jacobian_is_full_column_rank_and_compatible",
    }


def _finite_vector(values: Sequence[float], label: str) -> tuple[float, float, float]:
    if len(values) != 3:
        raise CandidateContractError(f"{label} must have exactly three project-frame components")
    result = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _unit(values: Sequence[float], label: str) -> tuple[float, float, float]:
    vector = _finite_vector(values, label)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        raise CandidateContractError(f"{label} must be nonzero")
    return tuple(value / norm for value in vector)


@dataclass(frozen=True)
class ProjectPhaseSpaceState:
    """One project-frame trajectory state at a named physical hand-off."""

    position_mm: tuple[float, float, float]
    velocity_mm_per_us: tuple[float, float, float]

    def __post_init__(self) -> None:
        _finite_vector(self.position_mm, "phase-space position")
        _unit(self.velocity_mm_per_us, "phase-space velocity")

    @property
    def unit_direction_project(self) -> tuple[float, float, float]:
        return _unit(self.velocity_mm_per_us, "phase-space velocity")


@dataclass(frozen=True)
class TwoPrismTransportObservation:
    """One collision-free source -> P1/pre-reflection/P2 -> origin-turn trajectory."""

    source: ProjectPhaseSpaceState
    prism_1: ProjectPhaseSpaceState
    drift_phase_origin: ProjectPhaseSpaceState
    completed_without_electrode_collision: bool

    def __post_init__(self) -> None:
        if self.completed_without_electrode_collision is not True:
            raise CandidateContractError("P1/P2 hand-off must reject an electrode-collision trajectory")


def _state_from_event(event: dict[str, Any], label: str) -> ProjectPhaseSpaceState:
    try:
        position = tuple(float(event[key]) for key in ("x_mm", "y_mm", "z_mm"))
        velocity = tuple(float(event[key]) for key in ("vx_mm_us", "vy_mm_us", "vz_mm_us"))
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} event has no complete finite phase-space state") from error
    return ProjectPhaseSpaceState(position, velocity)


def observation_from_simion_events(
    events: Sequence[dict[str, Any]],
    source: ProjectPhaseSpaceState,
    *, ion_number: int = 1,
) -> TwoPrismTransportObservation:
    """Extract the first post-P2 Stripe-on mirror turn used as drift origin."""
    if not isinstance(ion_number, int) or isinstance(ion_number, bool) or ion_number <= 0:
        raise CandidateContractError("P1/P2 event receipt needs one positive ion identity")
    ion_events = [event for event in events if event.get("ion") == ion_number]
    if any(event.get("kind") in {"terminal", "splat"} and event.get("splat", event.get("code")) == -1
           for event in ion_events):
        raise CandidateContractError("P1/P2 hand-off cannot consume an electrode-collision event")
    prism_passes = [event for event in ion_events if event.get("kind") == "prism_pass"]
    p1 = [event for event in prism_passes if event.get("n") == 1]
    p2 = [event for event in prism_passes if event.get("n") == 2]
    pre_reflections = [event for event in ion_events if event.get("kind") == "pre_injection_mirror_turn"]
    phase_origins = [event for event in ion_events if event.get("kind") == "drift_phase_origin"]
    if any(len(events) != 1 for events in (
        p1, pre_reflections, p2, phase_origins,
    )):
        raise CandidateContractError(
            "P1/P2 hand-off needs one P1 pass, the negative-mirror pre-reflection, "
            "one P2 pass, and one post-P2 phase-origin mirror turn"
        )
    ordered = (p1[0], pre_reflections[0], p2[0], phase_origins[0])
    if any(float(left["t_us"]) >= float(right["t_us"])
           for left, right in zip(ordered, ordered[1:])):
        raise CandidateContractError("P1/pre-reflection/P2/Stripe path events are not in physical order")
    p1_state = _state_from_event(p1[0], "P1")
    origin_state = _state_from_event(phase_origins[0], "post-P2 mirror-turn phase origin")
    if origin_state.position_mm[2] <= 0.0 or origin_state.velocity_mm_per_us[1] <= 0.0:
        raise CandidateContractError("drift phase origin must be the outbound positive-z mirror turn")
    if abs(origin_state.velocity_mm_per_us[2]) > 1e-9:
        raise CandidateContractError("drift phase origin must have event-localized v_z=0")
    return TwoPrismTransportObservation(source, p1_state, origin_state, True)


def prism_handoff_residuals(
    observation: TwoPrismTransportObservation,
    *,
    target_turn_y_mm: float,
    target_slow_kinetic_energy_per_charge_v: float,
    particle_mass_th: float,
    charge_state: int,
) -> tuple[tuple[str, float], ...]:
    """Return the two independent residuals controlled by the two prism voltages.

    The first residual sets the actual post-P2 mirror turn on the registered
    ``y=0`` function origin.  The second sets the slow energy partition.  The
    turn's ``v_z=0`` is an event definition, its ``z`` is a full-field result,
    and ``x=0`` is a symmetry diagnostic rather than an extra voltage target.
    """
    target_y = float(target_turn_y_mm)
    target_energy = float(target_slow_kinetic_energy_per_charge_v)
    mass = float(particle_mass_th)
    if not all(math.isfinite(value) for value in (target_y, target_energy, mass)):
        raise CandidateContractError("P1/P2 turn targets must be finite")
    if target_energy <= 0.0 or mass <= 0.0 or not isinstance(charge_state, int) or isinstance(charge_state, bool) or charge_state == 0:
        raise CandidateContractError("P1/P2 slow-energy residual needs positive mass/energy and nonzero integer charge")
    actual = observation.drift_phase_origin
    actual_slow_energy_ev = kinetic_energy_ev(mass, 0.0, actual.velocity_mm_per_us[1] * 1000.0, 0.0)
    actual_slow_energy_per_charge_v = actual_slow_energy_ev / abs(charge_state)
    return (
        ("P1_P2_phase_origin_turn_y_mm", actual.position_mm[1] - target_y),
        ("P1_P2_slow_kinetic_energy_per_charge_v", actual_slow_energy_per_charge_v - target_energy),
    )
