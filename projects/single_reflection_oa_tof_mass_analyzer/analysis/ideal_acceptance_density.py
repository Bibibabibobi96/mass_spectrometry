"""Population pushforward density for uniform-position, Gaussian-residual sources.

This is a deterministic integral, not a finite-particle KDE and not a replacement
for canonical particle metrics. The Gaussian is retained only inside an explicit
finite residual envelope. Each position quadrature node must have a certified
monotone residual-to-time map; unsupported folds fail explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt
from typing import Any

import numpy as np
from numpy.typing import NDArray

from common.analysis.peak_metrics import half_height_width
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_design import (
    DesignDomainError, finite_source_envelope,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    IdealWorkingPoint, NumericalSourceSpec,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    exact_total_normalized_time_from_state,
)


@dataclass(frozen=True)
class PopulationDensityResult:
    """Equal-unit density curves and JSON-safe, bandwidth-free peak diagnostics."""

    time_grid_us: NDArray[np.float64]
    time_density_per_us: NDArray[np.float64]
    mass_grid_da: NDArray[np.float64]
    mass_density_per_da: NDArray[np.float64]
    summary: dict[str, Any]


def _velocity(spec: NumericalSourceSpec, offset: NDArray[np.float64]) -> NDArray[np.float64]:
    return (spec.center_velocity_m_per_s + spec.velocity_slope_m_per_s_per_mm * offset
            + spec.velocity_quadratic_m_per_s_per_mm2 * offset**2)


def _time(spec: NumericalSourceSpec, point: IdealWorkingPoint,
          offset: NDArray[np.float64], residual: NDArray[np.float64]) -> NDArray[np.float64]:
    scale = point.design_source.time_scale_s_per_mm_sqrt_v
    chi = (_velocity(spec, offset) + residual) * scale * 1e3
    return np.asarray(exact_total_normalized_time_from_state(
        point.state, point.reflectron, point.inner, spec.center_x_mm + offset,
        chi, point.focus_drift_mm,
    )) * scale * 1e6


def _energy_derivative_terms(point: IdealWorkingPoint) -> tuple[tuple[float, float, float], ...]:
    """Coefficients, energy offsets and powers in d(normalized TOF)/dE."""

    state, mirror, inner = point.state, point.reflectron, point.inner
    mirror_field1 = inner.stage1_voltage_drop_v / mirror.stage1_length_mm
    drift = point.focus_drift_mm + mirror.upstream_drift_mm + mirror.downstream_drift_mm
    return (
        (1 / state.field1_v_per_mm - 1 / state.field2_v_per_mm, state.grid1_v, -.5),
        (1 / state.field2_v_per_mm - 1 / state.field3_v_per_mm, state.grid2_v, -.5),
        (1 / state.field3_v_per_mm + 2 / mirror_field1, 0., -.5),
        (2 / inner.stage2_field_v_per_mm - 2 / mirror_field1, inner.stage1_voltage_drop_v, -.5),
        (-drift / 2, 0., -1.5),
    )


def compute_residual_time_derivative(
    spec: NumericalSourceSpec, point: IdealWorkingPoint,
    position_offset_mm: NDArray[np.float64], residual_m_per_s: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Return analytic dt/d(residual velocity), in microseconds per m/s.

The exact oracle is T=s[F(E)-2 chi/E1], E=V(x)+chi**2 and
chi=1000*s*v. This derivative holds position and all fields fixed.
"""

    offset, residual = np.broadcast_arrays(np.asarray(position_offset_mm, dtype=float),
                                           np.asarray(residual_m_per_s, dtype=float))
    if spec.affine() != point.design_source:
        raise ValueError("source specification and design source must match")
    if not np.all(np.isfinite(offset)) or not np.all(np.isfinite(residual)):
        raise ValueError("positions and residual velocities must be finite")
    scale = point.design_source.time_scale_s_per_mm_sqrt_v
    chi = (_velocity(spec, offset) + residual) * scale * 1e3
    energy = point.state.repeller_v - point.state.field1_v_per_mm * (spec.center_x_mm + offset) + chi**2
    derivative = np.zeros_like(energy)
    for coefficient, voltage, power in _energy_derivative_terms(point):
        if np.any(energy <= voltage):
            raise DesignDomainError("residual derivative lies outside exact crossing domain")
        derivative += coefficient * (energy - voltage)**power
    return (2 * chi * derivative - 2 / point.state.field1_v_per_mm) * scale**2 * 1e9


def _monotonic_direction(spec: NumericalSourceSpec, point: IdealWorkingPoint,
                         offset: NDArray[np.float64], limit: float,
                         subdivisions: int) -> tuple[NDArray[np.float64], float]:
    """Bound the derivative on residual intervals; reject uncertified inversions."""

    scale = point.design_source.time_scale_s_per_mm_sqrt_v
    edges = np.linspace(-limit, limit, subdivisions + 1)
    chi = (_velocity(spec, offset[:, None]) + edges[None, :]) * scale * 1e3
    lo, hi = chi[:, :-1], chi[:, 1:]
    potential = point.state.repeller_v - point.state.field1_v_per_mm * (spec.center_x_mm + offset[:, None])
    energy_lo = potential + np.where((lo <= 0) & (hi >= 0), 0., np.minimum(lo**2, hi**2))
    energy_hi = potential + np.maximum(lo**2, hi**2)
    f_lo, f_hi = np.zeros_like(lo), np.zeros_like(hi)
    for coefficient, voltage, power in _energy_derivative_terms(point):
        if np.any(energy_lo <= voltage):
            raise DesignDomainError("finite residual envelope leaves exact crossing domain")
        values_lo, values_hi = coefficient * (energy_hi - voltage)**power, coefficient * (energy_lo - voltage)**power
        f_lo += np.minimum(values_lo, values_hi)
        f_hi += np.maximum(values_lo, values_hi)
    products = np.stack((lo * f_lo, lo * f_hi, hi * f_lo, hi * f_hi))
    d_lo = 2 * np.min(products, axis=0) - 2 / point.state.field1_v_per_mm
    d_hi = 2 * np.max(products, axis=0) - 2 / point.state.field1_v_per_mm
    decreasing = np.all(d_hi < 0, axis=1)
    increasing = np.all(d_lo > 0, axis=1)
    if not np.all(decreasing | increasing):
        raise DesignDomainError("residual-to-time monotonicity not certified; increase subdivisions or handle folds separately")
    direction = np.where(increasing, 1., -1.)
    margin = np.min(np.where(increasing[:, None], d_lo, -d_hi)) * scale**2 * 1e9
    return direction, float(margin)


def _invert_density(spec: NumericalSourceSpec, point: IdealWorkingPoint,
                    offset: NDArray[np.float64], weights: NDArray[np.float64],
                    direction: NDArray[np.float64], grid: NDArray[np.float64],
                    sigma: float, limit: float, iterations: int, tolerance: float) -> NDArray[np.float64]:
    """Vectorized bounded bisection, integrating the change-of-variable Jacobian."""

    lower_time = _time(spec, point, offset, np.full(offset.shape, -limit))
    upper_time = _time(spec, point, offset, np.full(offset.shape, limit))
    density = np.zeros_like(grid)
    # Only storage is chunked; all nodes and the same root tolerance are retained.
    chunk_size = max(1, 262144 // offset.size)
    for start in range(0, grid.size, chunk_size):
        targets = grid[None, start:start + chunk_size]
        active = ((targets >= np.minimum(lower_time, upper_time)[:, None])
                  & (targets <= np.maximum(lower_time, upper_time)[:, None]))
        lo = np.full(active.shape, -limit)
        hi = np.full(active.shape, limit)
        for _ in range(iterations):
            midpoint = (lo + hi) / 2
            times = _time(spec, point, offset[:, None], midpoint)
            move_lower = (times - targets) * direction[:, None] < 0
            lo = np.where(move_lower, midpoint, lo)
            hi = np.where(move_lower, hi, midpoint)
            if float(np.max(hi - lo)) <= tolerance:
                break
        if float(np.max(hi - lo)) > tolerance:
            raise ArithmeticError("residual inversion exhausted root_iterations before residual tolerance")
        residual = (lo + hi) / 2
        jacobian = np.abs(compute_residual_time_derivative(spec, point, offset[:, None], residual))
        conditional = np.exp(-.5 * (residual / sigma)**2) / (sigma * np.sqrt(2 * np.pi) * jacobian)
        density[start:start + chunk_size] = weights @ np.where(active, conditional, 0.)
    return density


def compute_population_density(
    spec: NumericalSourceSpec, point: IdealWorkingPoint, *, full_width_mm: float,
    residual_sigma_m_per_s: float, grid_points: int, position_order: int,
    envelope_sigma: float, root_iterations: int, residual_tolerance_m_per_s: float,
    monotonicity_subdivisions: int,
) -> PopulationDensityResult:
    """Integrate the exact TOF probability density without sample-size bandwidth.

Raises ValueError for invalid settings, DesignDomainError for event-domain or
uncertified monotonicity, and ArithmeticError for unresolved inversion. The
caller must compare position-order and time-grid refinements before interpreting
the result as converged. Gaussian probability outside the envelope is reported,
not silently claimed to arrive at the detector.
"""

    for name, value in (("grid_points", grid_points), ("position_order", position_order),
                        ("root_iterations", root_iterations), ("monotonicity_subdivisions", monotonicity_subdivisions)):
        if isinstance(value, bool) or not isinstance(value, int) or value < (3 if name == "grid_points" else 2):
            raise ValueError(f"{name} must be an integer >= {3 if name == 'grid_points' else 2}")
    for name, value in (("residual_sigma_m_per_s", residual_sigma_m_per_s),
                        ("envelope_sigma", envelope_sigma), ("residual_tolerance_m_per_s", residual_tolerance_m_per_s)):
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    limit = envelope_sigma * residual_sigma_m_per_s
    envelope = finite_source_envelope(spec, point, full_width_mm, limit)
    if envelope["energy_min_v"] <= max(point.state.grid1_v, point.inner.stage1_voltage_drop_v):
        raise DesignDomainError("finite source envelope cannot traverse both mirror stages")
    backplate = point.inner.stage1_voltage_drop_v + point.inner.stage2_field_v_per_mm * point.reflectron.stage2_length_mm
    if envelope["energy_max_v"] >= backplate:
        raise DesignDomainError("finite source envelope reaches reflectron backplate")
    nodes, weights = np.polynomial.legendre.leggauss(position_order)
    offset, weights = nodes * full_width_mm / 2, weights / 2
    direction, margin = _monotonic_direction(spec, point, offset, limit, monotonicity_subdivisions)
    endpoints = np.concatenate((_time(spec, point, offset, np.full(offset.shape, -limit)),
                                _time(spec, point, offset, np.full(offset.shape, limit))))
    if not np.all(np.isfinite(endpoints)) or np.min(endpoints) <= 0:
        raise DesignDomainError("finite source envelope has invalid pulse-relative times")
    grid = np.linspace(float(np.min(endpoints)), float(np.max(endpoints)), grid_points)
    density = _invert_density(spec, point, offset, weights, direction, grid,
                             residual_sigma_m_per_s, limit, root_iterations, residual_tolerance_m_per_s)
    # NumPy 1.x calls this `trapz`; current NumPy calls it `trapezoid`.
    # Both are the same numerical operation.
    integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    probability = float(integrate(density, grid))
    expected_probability = erf(envelope_sigma / sqrt(2))
    if not np.isfinite(probability) or probability <= 0:
        raise ArithmeticError("population density has no finite integrated probability")
    mean = float(np.trapezoid(grid * density, grid) / probability)
    time_width, time_left, time_right, _ = half_height_width(grid, density)
    mass = spec.mass_to_charge_th * (grid / mean)**2
    mass_density = density * mean**2 / (2 * spec.mass_to_charge_th * grid)
    mass_width, mass_left, mass_right, _ = half_height_width(mass, mass_density)
    summary = {
        "status": "SUCCESS", "metric_kind": "population_pushforward_density_not_finite_particle_kde",
        "source_envelope": "finite_gaussian_residual_box_not_infinite_population_guarantee",
        "finite_envelope_reachable": True,
        "time_basis": "elapsed_since_ideal_instantaneous_extraction_pulse_us",
        "full_width_mm": float(full_width_mm), "residual_sigma_m_per_s": float(residual_sigma_m_per_s),
        "envelope_sigma": float(envelope_sigma), "position_order": position_order, "grid_points": grid_points,
        "root_iterations": root_iterations, "residual_tolerance_m_per_s": float(residual_tolerance_m_per_s),
        "monotonicity_subdivisions": monotonicity_subdivisions,
        "monotonicity_scope": "interval_certified_at_all_position_quadrature_nodes",
        "minimum_absolute_residual_derivative_bound_us_per_m_per_s": margin,
        "integrated_probability": probability, "expected_finite_envelope_probability": expected_probability,
        "omitted_gaussian_probability": 1 - expected_probability,
        "probability_integration_error": probability - expected_probability,
        "mean_tof_us": mean, "fwhm_tof_ns": float(time_width * 1e3),
        "fwhm_mass_da": float(mass_width), "resolution_mass": float(spec.mass_to_charge_th / mass_width),
        "time_half_height_left_us": float(time_left), "time_half_height_right_us": float(time_right),
        "mass_half_height_left_da": float(mass_left), "mass_half_height_right_da": float(mass_right),
        "finite_source_envelope": envelope,
    }
    return PopulationDensityResult(grid, density, mass, mass_density, summary)
