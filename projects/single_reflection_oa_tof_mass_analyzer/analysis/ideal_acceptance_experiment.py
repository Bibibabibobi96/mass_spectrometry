"""Population calculations and deterministic source construction for acceptance.

Theory selects candidates without particle-seed feedback. Equal-probability
midpoint samples, unlike unequal-weight Gauss nodes, may use the canonical KDE.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
from scipy.special import ndtri

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_design import (
    SourceQuadrature, finite_source_envelope,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    AxialParticleSource, IdealWorkingPoint, NumericalSourceSpec, _classify_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    exact_total_normalized_time_from_state,
)


def source_at_point(spec: NumericalSourceSpec, point: IdealWorkingPoint) -> NumericalSourceSpec:
    """Move the field boundaries relative to an unchanged centered source law."""
    return replace(spec, center_x_mm=point.design_source.center_x_mm)


def _from_latent(spec: NumericalSourceSpec, position: np.ndarray, residual: np.ndarray) -> AxialParticleSource:
    velocity = (spec.center_velocity_m_per_s+spec.velocity_slope_m_per_s_per_mm*position
                +spec.velocity_quadratic_m_per_s_per_mm2*position**2+residual)
    return AxialParticleSource(np.arange(1, len(position)+1, dtype=np.int64), spec.center_x_mm+position,
                               velocity, residual, spec.mass_to_charge_th)


def midpoint_population(spec: NumericalSourceSpec, *, full_width_mm: float, residual_sigma_m_per_s: float,
                         position_order: int, residual_order: int) -> AxialParticleSource:
    """Equal-probability tensor midpoints approximate the prescribed population."""
    for order in (position_order, residual_order):
        if isinstance(order, bool) or not isinstance(order, int) or order < 2:
            raise ValueError("population orders must be integers >=2")
    if not np.isfinite(full_width_mm) or full_width_mm <= 0:
        raise ValueError("population source width must be positive and finite")
    if not np.isfinite(residual_sigma_m_per_s) or residual_sigma_m_per_s < 0:
        raise ValueError("population residual must be nonnegative and finite")
    position = ((np.arange(position_order)+.5)/position_order-.5)*full_width_mm
    residual = ndtri((np.arange(residual_order)+.5)/residual_order)*residual_sigma_m_per_s
    return _from_latent(spec, np.repeat(position, residual_order), np.tile(residual, position_order))


def exact_population_moments(spec: NumericalSourceSpec, point: IdealWorkingPoint,
                              quadrature: SourceQuadrature, *, envelope_sigma: float) -> dict[str, Any]:
    """Exact TOF at weighted nodes plus analytic finite-box reachability check.

Conditional variance decomposition uses the residual nodes at each position.
Gaussian tails outside the stated envelope are not guaranteed loss-free.
"""
    spec = source_at_point(spec, point)
    envelope = finite_source_envelope(spec, point, quadrature.full_width_mm,
                                      quadrature.residual_sigma_m_per_s*envelope_sigma)
    if envelope["energy_min_v"] <= max(point.state.grid1_v, point.inner.stage1_voltage_drop_v):
        raise ValueError("finite source envelope cannot reach the required field regions")
    if (envelope["energy_max_v"]-point.inner.stage1_voltage_drop_v)/point.inner.stage2_field_v_per_mm >= point.reflectron.stage2_length_mm:
        raise ValueError("finite source envelope reaches the mirror backplate")
    source = _from_latent(spec, quadrature.position_offset_mm, quadrature.residual_m_per_s)
    classes, chi = _classify_source(source, point)
    if np.any(classes != "detector_arrival"):
        raise ValueError("quadrature includes non-arriving/model-unsupported particles")
    times = np.asarray(exact_total_normalized_time_from_state(point.state, point.reflectron, point.inner,
                       source.source_x_mm, chi, point.focus_drift_mm))*point.design_source.time_scale_s_per_mm_sqrt_v*1e9
    weights = quadrature.weights
    mean = float(weights @ times)
    variance = float(weights @ (times-mean)**2)
    shape = (quadrature.position_order, quadrature.residual_order)
    joint = weights.reshape(shape)
    wx = np.sum(joint, axis=1)
    conditional = joint/wx[:, None]
    mean_x = np.sum(conditional*times.reshape(shape), axis=1)
    mean_variance = float(wx @ (mean_x-mean)**2)
    thickness = float(np.sum(joint*(times.reshape(shape)-mean_x[:, None])**2))
    return {"mean_tof_ns": mean, "variance_ns2": variance, "relative_variance": variance/mean**2,
            "conditional_mean_variance_ns2": mean_variance, "conditional_thickness_variance_ns2": thickness,
            "variance_decomposition_residual_ns2": variance-mean_variance-thickness,
            "finite_envelope": envelope, "envelope_sigma": envelope_sigma,
            "node_count": int(times.size), "fwhm_claim": False}


def accepted(summary: dict[str, Any], minimum_resolution: float) -> bool:
    """Accept only defined canonical FWHM with every mother particle retained."""
    metrics = summary.get("peak_metrics") or {}
    resolution = metrics.get("mass_resolution")
    return bool(summary.get("full_cohort_reachable") and resolution is not None
                and np.isfinite(resolution) and resolution >= minimum_resolution)
