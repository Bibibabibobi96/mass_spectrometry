"""Component-level P1/P2-to-Stripe phase-space hand-off for joint solves.

The source-to-Stripe trajectory is evaluated by the finite three-dimensional
solver.  This module deliberately does not approximate either triangular
prism: it validates a recorded path and converts its final Stripe crossing
into the five independent residual components required by a fixed target
position and unit direction.  The Mirror-Stripe theory derives the entrance
direction and the ``y=0`` event plane, but not the fast-reflection phase (or
equivalently the target ``z`` coordinate).  The latter therefore needs a
separate design authority before two prism voltages can be claimed as defined.
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
    physical unknowns.  Crossing ``y=0`` defines where the entrance event is
    sampled, and ``x=0`` follows from the symmetric geometry and equal
    left/right electrode voltage; neither is an independently steerable
    voltage residual.  The Stripe theory supplies one incidence-angle target.
    A fast-reflection phase (normally a target project ``z`` at that crossing)
    is the second required target coordinate.
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
        entry_y = float(contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("two-prism definition audit lacks prism identities or Stripe entry y") from error
    if prism_ids[0] == prism_ids[1] or not math.isfinite(entry_y):
        raise CandidateContractError("two-prism identities must be distinct and the Stripe entry y finite")

    common = {
        "unknowns": [
            f"prism_1_id_{prism_ids[0]}_voltage_v",
            f"prism_2_id_{prism_ids[1]}_voltage_v",
        ],
        "unknown_count": 2,
        "independent_target_conditions_before_finite_3d_jacobian": [
            "Stripe_incidence_angle_in_project_yz_from_the_compatible_Mirror_Stripe_solution",
        ],
        "event_or_symmetry_conditions_not_counted_as_voltage_residuals": [
            f"project_y_equals_{entry_y:g}_mm_defines_the_Stripe_crossing_event",
            "project_x_equals_0_is_invariant_under_x_symmetric_geometry_and_voltages",
        ],
        "forbidden_implicit_fast_phase_substitutions": [
            "prism_triangle_centroid",
            "grounded_shield_aperture_centroid",
            "CAD_bounding_box_center",
        ],
    }
    phase = model.get("stripe_entrance_fast_phase_authority")
    if phase is None or (isinstance(phase, dict) and phase.get("status") == "missing"):
        return {
            **common,
            "status": "structurally_underdetermined_missing_fast_phase",
            "independent_voltage_constraint_rank_before_finite_3d_jacobian": 1,
            "nullity_before_finite_3d_jacobian": 1,
            "missing_authority": "Stripe_entry_fast_reflection_phase_or_target_project_z_mm",
            "publication_gate": "closed",
        }
    if not isinstance(phase, dict) or phase.get("status") != "design_authority":
        raise CandidateContractError("Stripe entrance fast-phase authority has an unknown status")
    try:
        target_z = float(phase["target_project_z_mm"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("fast-phase design authority needs target_project_z_mm") from error
    source = str(phase.get("source", ""))
    if not math.isfinite(target_z) or not source:
        raise CandidateContractError("fast-phase target z must be finite and have a named source")
    normalized_source = source.lower().replace("-", "_").replace(" ", "_")
    if any(token in normalized_source for token in ("centroid", "bounding_box", "bbox")):
        raise CandidateContractError("fast phase cannot be inferred from a CAD centroid or bounding box")
    return {
        **common,
        "status": "two_target_coordinates_declared__finite_3d_jacobian_pending",
        "declared_fast_phase_target_project_z_mm": target_z,
        "fast_phase_authority_source": source,
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


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _cross(left: Sequence[float], right: Sequence[float]) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


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
    """One collision-free finite-3-D source -> P1 -> P2 -> Stripe trajectory."""

    source: ProjectPhaseSpaceState
    prism_1: ProjectPhaseSpaceState
    prism_2: ProjectPhaseSpaceState
    stripe_entrance: ProjectPhaseSpaceState
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
    """Extract one collision-free source -> P1 -> P2/Stripe hand-off receipt.

    The first negative-y crossing of the frozen $y=0$ Stripe plane is both
    the physically observed P2 exit and the Stripe entrance.  It avoids an
    invented internal P2 effective plane while retaining separate event names
    in the SIMION log for provenance.
    """
    if not isinstance(ion_number, int) or isinstance(ion_number, bool) or ion_number <= 0:
        raise CandidateContractError("P1/P2 event receipt needs one positive ion identity")
    ion_events = [event for event in events if event.get("ion") == ion_number]
    if any(event.get("kind") in {"terminal", "splat"} and event.get("splat", event.get("code")) == -1
           for event in ion_events):
        raise CandidateContractError("P1/P2 hand-off cannot consume an electrode-collision event")
    p1 = [event for event in ion_events if event.get("kind") == "p1_plane"]
    p2_to_stripe = [event for event in ion_events if event.get("kind") == "p2_to_stripe"]
    if len(p1) != 1 or len(p2_to_stripe) != 1:
        raise CandidateContractError("P1/P2 hand-off needs exactly one forward P1 and P2-to-Stripe event")
    p1_state = _state_from_event(p1[0], "P1")
    stripe_state = _state_from_event(p2_to_stripe[0], "P2-to-Stripe")
    if abs(stripe_state.position_mm[1]) > 1e-9 or stripe_state.velocity_mm_per_us[1] >= 0.0:
        raise CandidateContractError("P2-to-Stripe event must be the inbound frozen y=0 crossing")
    return TwoPrismTransportObservation(source, p1_state, stripe_state, stripe_state, True)


def _target_tangent_basis(target_direction: Sequence[float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return a deterministic orthonormal basis of the target-direction plane."""
    direction = _unit(target_direction, "target Stripe direction")
    references = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    reference = min(references, key=lambda candidate: abs(_dot(direction, candidate)))
    first = _unit(_cross(direction, reference), "target tangent basis 1")
    second = _unit(_cross(direction, first), "target tangent basis 2")
    return first, second


def stripe_handoff_residuals(
    observation: TwoPrismTransportObservation,
    target_position_mm: Sequence[float],
    target_unit_direction_project: Sequence[float],
) -> tuple[tuple[str, float], ...]:
    """Return five independent phase-space residual components.

    Position remains three project-coordinate residuals.  A unit direction has
    only two independent degrees of freedom, so its mismatch is resolved on a
    deterministic target-tangent basis rather than reported as three redundant
    Cartesian components or collapsed into a non-differentiable norm.
    """
    target_position = _finite_vector(target_position_mm, "target Stripe position")
    target_direction = _unit(target_unit_direction_project, "target Stripe direction")
    actual = observation.stripe_entrance
    actual_direction = actual.unit_direction_project
    tangent_1, tangent_2 = _target_tangent_basis(target_direction)
    return (
        ("P1_P2_to_Stripe_position_x_mm", actual.position_mm[0] - target_position[0]),
        ("P1_P2_to_Stripe_position_y_mm", actual.position_mm[1] - target_position[1]),
        ("P1_P2_to_Stripe_position_z_mm", actual.position_mm[2] - target_position[2]),
        ("P1_P2_to_Stripe_direction_tangent_1", _dot(actual_direction, tangent_1)),
        ("P1_P2_to_Stripe_direction_tangent_2", _dot(actual_direction, tangent_2)),
    )
