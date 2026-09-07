"""Component-level P1/P2-to-Stripe phase-space hand-off for joint solves.

The source-to-Stripe trajectory is evaluated by the finite three-dimensional
solver.  This module deliberately does not approximate either triangular
prism: it validates a recorded path and converts its final Stripe crossing
into the five independent residual components required by a fixed target
position and unit direction.  The target is derived by the same Mirror-Stripe
trial that supplies the other joint residuals.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


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
