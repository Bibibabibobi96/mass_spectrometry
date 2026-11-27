"""Numerical trust-region directions for measured two-coordinate control."""
from __future__ import annotations

import math

import numpy as np


def accepted_secant_update(jacobian: np.ndarray, delta_v: np.ndarray, delta_r: np.ndarray) -> np.ndarray:
    """Retain the base Jacobian when the accepted voltage displacement is zero."""
    squared = float(delta_v @ delta_v)
    if squared <= np.finfo(float).tiny:
        return jacobian
    return jacobian + np.outer(delta_r - jacobian @ delta_v, delta_v) / squared


def scaled_two_coordinate_step(
    subsystem: np.ndarray, residuals: np.ndarray,
    parameter_scales: np.ndarray, tolerances: np.ndarray,
) -> tuple[np.ndarray, str, float]:
    """Shared scaled correction; rectangular S1 uses measured least squares."""
    scaled = (subsystem / tolerances[:, None]) * parameter_scales[None, :]
    condition = float(np.linalg.cond(scaled))
    rhs = residuals / tolerances
    if not math.isfinite(condition):
        raise np.linalg.LinAlgError("selected scaled two-coordinate Jacobian is singular")
    if scaled.shape[0] != scaled.shape[1]:
        normalized, _remaining, rank, _singular = np.linalg.lstsq(scaled, -rhs, rcond=None)
        if rank != scaled.shape[1]:
            raise np.linalg.LinAlgError("selected rectangular Jacobian lacks an active voltage direction")
        method = "scaled_rectangular_least_squares"
    elif condition > 100.0:
        normalized = np.linalg.solve(
            scaled.T @ scaled + 1.0e-4 * np.eye(2), -scaled.T @ rhs,
        )
        method = "ridge_regularized_scaled_least_squares"
    else:
        normalized = np.linalg.solve(scaled, -rhs)
        method = "scaled_direct_solve"
    return normalized * parameter_scales, method, condition


def bounded_coordinate_step(
    voltages: np.ndarray, raw: np.ndarray, maximum: np.ndarray,
    lower: np.ndarray, upper: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Scale a continuous direction once, preserving its two-axis direction."""
    alpha = 1.0
    for offset, component in enumerate(raw):
        if component != 0.0:
            alpha = min(alpha, maximum[offset] / abs(component))
        if component > 0.0:
            alpha = min(alpha, (upper[offset] - voltages[offset]) / component)
        elif component < 0.0:
            alpha = min(alpha, (lower[offset] - voltages[offset]) / component)
    alpha = max(0.0, min(1.0, float(alpha)))
    return alpha * raw, alpha
