"""Finite numerical-source quadrature and exact finite-envelope event checks.

The source model is uniform in position with independent Gaussian velocity
residual. Unequal integration weights estimate moments, not a particle FWHM.
No field or geometry optimizer is provided; theoretical design equations live
in ideal_acceptance_linear_design.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.polynomial import Polynomial
from numpy.typing import NDArray

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    IdealWorkingPoint, NumericalSourceSpec,
)


class DesignDomainError(ValueError):
    """The declared finite source violates the exact ideal event domain."""


@dataclass(frozen=True)
class SourceQuadrature:
    """Finite integration nodes; positions are offsets from the source center."""

    position_offset_mm: NDArray[np.float64]
    residual_m_per_s: NDArray[np.float64]
    weights: NDArray[np.float64]
    full_width_mm: float
    residual_sigma_m_per_s: float
    position_order: int
    residual_order: int


def prepare_source_quadrature(
    spec: NumericalSourceSpec, *, full_width_mm: float,
    residual_sigma_m_per_s: float, position_order: int, residual_order: int,
) -> SourceQuadrature:
    """Integrate a uniform axial position and independent normal velocity residual."""

    if not isinstance(spec, NumericalSourceSpec):
        raise TypeError("spec must be NumericalSourceSpec")
    for name, value in (("full_width_mm", full_width_mm), ("residual_sigma_m_per_s", residual_sigma_m_per_s)):
        if not np.isfinite(value) or value < 0 or (name == "full_width_mm" and value == 0):
            raise ValueError(f"{name} must be finite and {'positive' if name == 'full_width_mm' else 'nonnegative'}")
    for name, order in (("position_order", position_order), ("residual_order", residual_order)):
        if isinstance(order, bool) or not isinstance(order, int) or order < 2:
            raise ValueError(f"{name} must be an integer >= 2")
    x, wx = np.polynomial.legendre.leggauss(position_order)
    r, wr = np.polynomial.hermite.hermgauss(residual_order)
    weights = np.outer(wx / 2.0, wr / np.sqrt(np.pi)).ravel()
    return SourceQuadrature(
        np.repeat(x * full_width_mm / 2.0, residual_order),
        np.tile(r * np.sqrt(2.0) * residual_sigma_m_per_s, position_order),
        weights / np.sum(weights), float(full_width_mm), float(residual_sigma_m_per_s),
        position_order, residual_order,
    )


def _real_interior_roots(polynomial: Polynomial, half_width: float) -> list[float]:
    roots = polynomial.roots()
    return [float(root.real) for root in roots if abs(root.imag) < 1e-10 * max(1.0, abs(root.real))
            and -half_width < root.real < half_width]


def finite_source_envelope(spec: NumericalSourceSpec, point: IdealWorkingPoint,
                     full_width: float, residual_limit: float) -> dict[str, float]:
    """Exact extrema over a finite box, not an infinite-Gaussian guarantee."""

    if not np.isfinite(full_width) or full_width <= 0:
        raise ValueError("full_width must be finite and positive")
    if not np.isfinite(residual_limit) or residual_limit < 0:
        raise ValueError("residual_limit must be finite and nonnegative")
    if spec.affine() != point.design_source:
        raise ValueError("source specification and design source must match")

    half = full_width / 2.0
    center = spec.center_x_mm
    clearance = min(center-half, point.state.zone1_length_mm-center-half)
    if clearance <= 0:
        raise DesignDomainError("source interval touches or exits first acceleration zone")
    root_factor = spec.affine().time_scale_s_per_mm_sqrt_v*1e3
    velocity = Polynomial([spec.center_velocity_m_per_s, spec.velocity_slope_m_per_s_per_mm,
                           spec.velocity_quadratic_m_per_s_per_mm2])
    potential = Polynomial([point.state.repeller_v-point.state.field1_v_per_mm*center,
                            -point.state.field1_v_per_mm])
    candidates = [-half, half]
    for residual in (-residual_limit, residual_limit):
        energy = potential + root_factor**2*(velocity+residual)**2
        candidates.extend(_real_interior_roots(energy.deriv(), half))
        candidates.extend(_real_interior_roots(velocity+residual, half))
    y = np.asarray(candidates)
    local_v = velocity(y)
    minimum = np.min(potential(y)+root_factor**2*(local_v+np.clip(-local_v, -residual_limit, residual_limit))**2)
    maximum = max(np.max(potential(y)+root_factor**2*(local_v+residual)**2) for residual in (-residual_limit, residual_limit))
    backward_velocity = velocity-residual_limit
    turn = Polynomial([center, 1.0])-root_factor**2*backward_velocity**2/point.state.field1_v_per_mm
    turn_y = np.asarray([-half, half]+_real_interior_roots(turn.deriv(), half)+_real_interior_roots(backward_velocity, half))
    backward = backward_velocity(turn_y) < 0
    turn_clearance = min(float(np.min(turn(turn_y[backward]))) if np.any(backward) else float("inf"), center-half)
    if turn_clearance <= 0:
        raise DesignDomainError("finite source envelope collides with repeller")
    return {"energy_min_v": float(minimum), "energy_max_v": float(maximum),
            "source_clearance_mm": clearance, "minimum_repeller_turn_mm": turn_clearance}
