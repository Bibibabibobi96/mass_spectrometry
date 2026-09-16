"""Component-level P1/P2-to-Stripe phase-space hand-off for joint solves.

The source-to-analyser trajectory is evaluated by the finite three-dimensional
solver.  This module deliberately does not approximate either triangular
prism.  In the manufactured topology the ordered injection path is P1,
negative-mirror pre-reflection, P2, a low-field reference crossing inside the
P2 grounded shield, and the first post-P2 positive-mirror turn.  The two prism
voltages match the signed direction at the reference section and the turn's
slow coordinate.  The turn's fast coordinate is an observed diagnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def audit_two_prism_voltage_definition(contract: dict[str, Any]) -> dict[str, Any]:
    """Classify whether the two pre-Stripe prism voltages are structurally defined.

    In the project-symmetric ``y-z`` transport, the two voltages are two
    physical unknowns.  The compatible Mirror--Stripe solution supplies the
    first positive-mirror turn position and the upstream low-field signed
    ``v_y/v_z`` ratio.
    The negative-mirror turn between P1 and P2 is a required topology event,
    not a voltage residual: P2 has not acted at that event.  ``x=0`` follows
    from symmetry and is not an independently steerable residual.
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
        clearance_z = tuple(
            float(point[1])
            for point in matching_shields[0]["prism_clearance_polygon_yz_mm"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(
            "P2 shield must declare its cross-aperture and prism-clearance z bounds"
        ) from error
    if len(mechanical_z) != 2 or not all(math.isfinite(value) for value in mechanical_z) or not mechanical_z[0] < mechanical_z[1]:
        raise CandidateContractError("P2 shield cross-aperture z bounds must be finite and ordered")
    low_field_lower = max(clearance_z)
    low_field_upper = mechanical_z[1]
    if not all(math.isfinite(value) for value in clearance_z) or not (
        mechanical_z[0] < low_field_lower < low_field_upper
    ):
        raise CandidateContractError("P2 shield geometry has no positive-z low-field section")
    low_field_plane = 0.5 * (low_field_lower + low_field_upper)

    common = {
        "unknowns": [
            f"prism_1_id_{prism_ids[0]}_voltage_v",
            f"prism_2_id_{prism_ids[1]}_voltage_v",
        ],
        "unknown_count": 2,
        "independent_target_conditions_before_finite_3d_jacobian": [
            f"first_post_P2_positive_mirror_turn_project_y_equals_{origin_y:g}_mm",
            "P2_shield_low_field_positive_signed_v_y_over_v_z_from_the_compatible_Mirror_Stripe_solution",
        ],
        "event_or_symmetry_conditions_not_counted_as_voltage_residuals": [
            "one_negative_mirror_turn_between_P1_and_P2_is_a_sequence_diagnostic_only",
            "P2_shield_low_field_reference_crossing_has_positive_v_y_and_positive_v_z",
            "first_post_P2_positive_mirror_turn_has_v_z_equals_zero_by_event_definition",
            "positive_mirror_turn_project_z_is_an_observed_diagnostic_only",
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
            "semantics": "the z bounds geometrically bracket the post-P2 low-field reference section",
        },
        "p2_low_field_reference_section": {
            "project_z_open_interval_mm": [low_field_lower, low_field_upper],
            "reference_plane_z_mm": low_field_plane,
            "derivation": "midpoint_between_positive_P2_clearance_vertex_and_positive_cross_slot_end",
            "field_flatness_status": "requires_finite_3d_field_diagnostic",
        },
    }
    return {
        **common,
        "status": "two_physical_targets_declared__finite_3d_jacobian_pending",
        "handoff_events": [
            "p2_low_field_reference",
            "first_post_P2_positive_mirror_turn",
        ],
        "target_project_y_mm": origin_y,
        "target_tangent_ratio_authority": "explicit_compatible_Mirror_Stripe_solution_input",
        "positive_mirror_turn_z_role": "derived_trajectory_diagnostic_only__not_a_voltage_residual",
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
    """One collision-free P1/P2 trajectory with distinct angle/turn events."""

    source: ProjectPhaseSpaceState
    prism_1: ProjectPhaseSpaceState
    p2_shield_low_field_reference: ProjectPhaseSpaceState
    positive_mirror_turn: ProjectPhaseSpaceState
    completed_without_electrode_collision: bool

    def __post_init__(self) -> None:
        if self.completed_without_electrode_collision is not True:
            raise CandidateContractError("P1/P2 hand-off must reject an electrode-collision trajectory")
        _vx, vy, vz = self.p2_shield_low_field_reference.velocity_mm_per_us
        if vy <= 0.0 or vz <= 0.0:
            raise CandidateContractError(
                "P2-shield low-field reference must have positive project-y and project-z velocity"
            )
        _turn_vx, turn_vy, turn_vz = self.positive_mirror_turn.velocity_mm_per_us
        if (
            self.positive_mirror_turn.position_mm[2] <= 0.0
            or turn_vy <= 0.0
            or abs(turn_vz) > 1e-9
        ):
            raise CandidateContractError(
                "first post-P2 positive-mirror turn must be on +z with vy>0 and event-localized vz=0"
            )


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
    """Extract the post-P2 low-field direction and first positive-mirror turn."""
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
    references = [
        event for event in ion_events
        if event.get("kind") == "p2_low_field_reference"
    ]
    positive_turns = [
        event for event in ion_events if event.get("kind") == "pre_origin_positive_mirror_turn"
    ]
    if any(len(events) != 1 for events in (
        p1, pre_reflections, p2, references, positive_turns,
    )):
        raise CandidateContractError(
            "P1/P2 hand-off needs one P1 pass, the negative-mirror pre-reflection, "
            "one P2 pass, one P2-shield low-field reference crossing, and one "
            "first post-P2 positive-mirror turn"
        )
    ordered = (p1[0], pre_reflections[0], p2[0], references[0], positive_turns[0])
    if any(float(left["t_us"]) >= float(right["t_us"])
           for left, right in zip(ordered, ordered[1:])):
        raise CandidateContractError(
            "P1/pre-reflection/P2/low-field-reference/positive-turn events are not in physical order"
        )
    p1_state = _state_from_event(p1[0], "P1")
    reference_state = _state_from_event(references[0], "P2-shield low-field reference")
    turn_state = _state_from_event(positive_turns[0], "first post-P2 positive-mirror turn")
    return TwoPrismTransportObservation(source, p1_state, reference_state, turn_state, True)


def prism_handoff_residuals(
    observation: TwoPrismTransportObservation,
    *,
    target_positive_mirror_turn_y_mm: float,
    target_tangent_ratio_vy_over_vz: float,
) -> tuple[tuple[str, float], ...]:
    """Return the two independent residuals controlled by the two prism voltages.

    The first residual sets the first post-P2 positive-mirror turn on the
    registered theory-function origin.  The second sets signed ``v_y/v_z`` at
    the upstream low-field section.  Turn ``z`` and ``x=0`` are diagnostics.
    """
    try:
        target_y = float(target_positive_mirror_turn_y_mm)
        target_ratio = float(target_tangent_ratio_vy_over_vz)
    except (TypeError, ValueError) as error:
        raise CandidateContractError("P1/P2 turn/low-field targets must be finite numbers") from error
    if not math.isfinite(target_y) or not math.isfinite(target_ratio):
        raise CandidateContractError("P1/P2 turn/low-field targets must be finite numbers")
    if target_ratio <= 0.0:
        raise CandidateContractError("P1/P2 target entrance tangent ratio must be positive")
    actual_turn = observation.positive_mirror_turn
    reference = observation.p2_shield_low_field_reference
    actual_ratio = reference.velocity_mm_per_us[1] / reference.velocity_mm_per_us[2]
    return (
        ("P1_P2_positive_mirror_turn_y_mm", actual_turn.position_mm[1] - target_y),
        ("P1_P2_P2_shield_low_field_signed_vy_over_vz", actual_ratio - target_ratio),
    )
