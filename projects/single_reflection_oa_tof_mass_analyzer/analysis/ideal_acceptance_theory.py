"""Finite-width design equations derived from the existing ideal TOF formula.

This maintained analysis capability computes Taylor coefficients analytically,
not by differentiating noisy particle peaks. Lengths are mm, velocities m/s,
and returned time coefficients ns/mm**order. No voltage/peak optimization occurs.
"""

from __future__ import annotations

from math import comb
from typing import Any

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    IdealWorkingPoint,
)


def _quadratic_power(constant: float, linear: float, quadratic: float,
                     exponent: float, order: int) -> np.ndarray:
    """Coefficients of (constant+linear*y+quadratic*y**2)**exponent.

The generalized binomial series is algebraically truncated at the requested
order. Its finite-width accuracy still requires an independent exact-time check.
"""
    if constant <= 0 or not np.isfinite(constant + linear + quadratic):
        raise ValueError("Taylor expansion requires a positive finite center argument")
    coefficients = np.zeros(order + 1)
    binomial = 1.0
    for power in range(order + 1):
        if power:
            binomial *= (exponent - power + 1) / power
        for quadratics in range(min(power, order - power) + 1):
            degree = power + quadratics
            coefficients[degree] += (binomial * comb(power, quadratics)
                                     * (linear / constant)**(power - quadratics)
                                     * (quadratic / constant)**quadratics)
    return constant**exponent * coefficients


def axial_time_coefficients(point: IdealWorkingPoint, *, order: int) -> np.ndarray:
    """Return exact Taylor coefficients t(y)=sum(a_n*y**n), including factorials.

The source is the point's affine conditional mean. This direct position-domain
expansion remains defined when the energy-position slope passes through zero.
"""
    if isinstance(order, bool) or not isinstance(order, int) or order < 1:
        raise ValueError("order must be a positive integer")
    state, mirror, inner, source = point.state, point.reflectron, point.inner, point.design_source
    w = state.center_energy_per_charge_v
    p = state.energy_position_first_v_per_mm
    beta = source.chi_slope_sqrt_v_per_mm
    mirror_field1 = inner.stage1_voltage_drop_v / mirror.stage1_length_mm
    terms = (
        (2 / state.field1_v_per_mm - 2 / state.field2_v_per_mm, state.grid1_v),
        (2 / state.field2_v_per_mm - 2 / state.field3_v_per_mm, state.grid2_v),
        (2 / state.field3_v_per_mm + 4 / mirror_field1, 0.0),
        (4 / inner.stage2_field_v_per_mm - 4 / mirror_field1, inner.stage1_voltage_drop_v),
    )
    result = sum((factor * _quadratic_power(w - voltage, p, beta**2, .5, order)
                  for factor, voltage in terms), start=np.zeros(order + 1))
    drift = point.focus_drift_mm + mirror.upstream_drift_mm + mirror.downstream_drift_mm
    result += drift * _quadratic_power(w, p, beta**2, -.5, order)
    result[0] -= 2 * source.chi_center_sqrt_v / state.field1_v_per_mm
    result[1] -= 2 * beta / state.field1_v_per_mm
    return result * source.time_scale_s_per_mm_sqrt_v * 1e9


def residual_time_sensitivity(point: IdealWorkingPoint, offset_mm: np.ndarray) -> np.ndarray:
    """Analytic dt/dv at fixed position along the affine mean, ns/(m/s).

This is a downstream timing projection of a fixed source residual, not a change
of the source covariance. It includes its variation across the entire width.
"""
    y = np.asarray(offset_mm, dtype=float)
    state, inner, mirror, source = point.state, point.inner, point.reflectron, point.design_source
    chi = source.chi_center_sqrt_v + source.chi_slope_sqrt_v_per_mm * y
    energy = state.center_energy_per_charge_v + state.energy_position_first_v_per_mm*y + source.chi_slope_sqrt_v_per_mm**2*y**2
    if np.any(energy <= max(state.grid1_v, inner.stage1_voltage_drop_v)):
        raise ValueError("source interval is outside the two-stage timing domain")
    field = inner.stage1_voltage_drop_v / mirror.stage1_length_mm
    derivative = ((1/state.field1_v_per_mm - 1/state.field2_v_per_mm)/np.sqrt(energy-state.grid1_v)
                  + (1/state.field2_v_per_mm - 1/state.field3_v_per_mm)/np.sqrt(energy-state.grid2_v)
                  + (1/state.field3_v_per_mm + 2/field)/np.sqrt(energy)
                  + (2/inner.stage2_field_v_per_mm - 2/field)/np.sqrt(energy-inner.stage1_voltage_drop_v)
                  - .5*(point.focus_drift_mm+mirror.upstream_drift_mm+mirror.downstream_drift_mm)/energy**1.5)
    return (2*chi*derivative - 2/state.field1_v_per_mm) * source.time_scale_s_per_mm_sqrt_v**2 * 1e12


def uniform_polynomial_variance(coefficients: np.ndarray, full_width_mm: float) -> float:
    """Exact variance of a polynomial over a centered uniform source interval."""
    if not np.isfinite(full_width_mm) or full_width_mm <= 0:
        raise ValueError("full width must be finite and positive")
    coefficients = np.asarray(coefficients, dtype=float).copy()
    coefficients[0] = 0.0  # remove the large common flight time before moments
    half = full_width_mm/2
    moment = lambda n: 0.0 if n % 2 else half**n/(n+1)
    mean = sum(c*moment(i) for i, c in enumerate(coefficients))
    squared = np.polynomial.polynomial.polymul(coefficients, coefficients)
    return float(sum(c*moment(i) for i, c in enumerate(squared))-mean**2)


def coefficient_report(point: IdealWorkingPoint, *, full_width_mm: float,
                       residual_sigma_m_per_s: float, order: int, position_order: int) -> dict[str, Any]:
    """Report high-order deterministic spread and first-order residual projection."""
    coefficients = axial_time_coefficients(point, order=order)
    nodes, weights = np.polynomial.legendre.leggauss(position_order)
    sensitivities = residual_time_sensitivity(point, nodes*full_width_mm/2)
    variance = uniform_polynomial_variance(coefficients, full_width_mm)
    residual_variance = float(weights @ sensitivities**2 / 2 * residual_sigma_m_per_s**2)
    return {"coefficients_ns_per_mm_power": coefficients.tolist(),
            "coefficient_convention": "Taylor coefficients = derivatives / factorial; a0 is center TOF",
            "full_width_mm": full_width_mm, "residual_sigma_m_per_s": residual_sigma_m_per_s,
            "polynomial_conditional_mean_variance_ns2": variance,
            "linearized_conditional_thickness_variance_ns2": residual_variance,
            "linearized_total_sigma_ns": float(np.sqrt(max(0., variance+residual_variance))),
            "residual_sensitivity_center_ns_per_m_per_s": float(residual_time_sensitivity(point, np.array([0.]))[0]),
            "scope": "local series and first-order residual projection; exact finite-width propagation must verify remainder"}
