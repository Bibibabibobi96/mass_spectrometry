"""Fit physically ordered reflectron voltages to a sampled axis response."""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import LinearConstraint, minimize


def compile_fit_parameters(contract: dict, regularization: float) -> dict:
    """Resolve the fit solely from the supplied geometry and study parameter."""
    counts = (contract["rings"]["stage1_count"], contract["rings"]["stage2_count"])
    if any(type(count) is not int or count < 1 for count in counts):
        raise ValueError("reflectron stage ring counts must be positive integers")
    if type(regularization) not in (int, float) or not math.isfinite(regularization) or regularization < 0:
        raise ValueError("regularization must be finite and nonnegative")
    parameters = {
        "stage1_count": int(contract["rings"]["stage1_count"]),
        "stage2_count": int(contract["rings"]["stage2_count"]),
        "stage1_length_mm": float(contract["geometry_mm"]["L_stage1"]),
        "stage2_length_mm": float(contract["geometry_mm"]["L_stage2"]),
        "midgrid_voltage_v": float(contract["electrodes_V"]["midgrid"]),
        "backplate_voltage_v": float(contract["electrodes_V"]["backplate"]),
        "regularization": regularization,
    }
    for name in ("stage1_length_mm", "stage2_length_mm"):
        if not math.isfinite(parameters[name]) or parameters[name] <= 0:
            raise ValueError(f"{name} must be finite and positive")
    for name in ("midgrid_voltage_v", "backplate_voltage_v"):
        if not math.isfinite(parameters[name]):
            raise ValueError(f"{name} must be finite")
    return parameters


def optimize(
    x: np.ndarray,
    basis: np.ndarray,
    *,
    stage1_count: int,
    stage2_count: int,
    stage1_length_mm: float,
    stage2_length_mm: float,
    midgrid_voltage_v: float,
    backplate_voltage_v: float,
    regularization: float,
) -> dict:
    maximum_electrode = 4 + stage1_count + stage2_count
    if basis.shape[1] != maximum_electrode:
        raise ValueError("basis electrode count does not match ring counts")
    midgrid_electrode = 2 + stage1_count
    backplate_electrode = 3 + stage1_count + stage2_count
    variable_electrodes = [
        *range(2, midgrid_electrode),
        *range(midgrid_electrode + 1, backplate_electrode),
    ]
    fixed = (
        basis[:, midgrid_electrode - 1] * midgrid_voltage_v
        + basis[:, backplate_electrode - 1] * backplate_voltage_v
    )
    target = np.where(
        x <= stage1_length_mm,
        midgrid_voltage_v * x / stage1_length_mm,
        midgrid_voltage_v
        + (backplate_voltage_v - midgrid_voltage_v)
        * (x - stage1_length_mm)
        / stage2_length_mm,
    )
    # Exclude exact grid/backplate planes while retaining their neighboring fringe fields.
    mask = (
        (x > 0.0)
        & (x < stage1_length_mm + stage2_length_mm)
        & (np.abs(x - stage1_length_mm) > 1e-9)
    )
    matrix = basis[mask][:, np.asarray(variable_electrodes) - 1]
    rhs = target[mask] - fixed[mask]
    stage1_initial = midgrid_voltage_v * np.arange(1, stage1_count + 1) / (stage1_count + 1)
    stage2_initial = midgrid_voltage_v + (
        (backplate_voltage_v - midgrid_voltage_v)
        * np.arange(1, stage2_count + 1)
        / (stage2_count + 1)
    )
    initial = np.concatenate((stage1_initial, stage2_initial))
    # Normalize by the error that is actually being optimized.  Using the
    # approximately kilovolt target-potential scale makes the initial
    # objective and gradient so small that SLSQP can accept the linear divider
    # without taking a step, even when a useful monotone correction exists.
    initial_residual = matrix @ initial - rhs
    scale = max(float(np.sqrt(np.mean(initial_residual * initial_residual))), 1e-9)

    difference = np.zeros((stage1_count - 1 + stage2_count - 1, initial.size))
    row = 0
    for start, count in ((0, stage1_count), (stage1_count, stage2_count)):
        for index in range(count - 1):
            difference[row, start + index] = -1.0
            difference[row, start + index + 1] = 1.0
            row += 1

    def objective(values: np.ndarray) -> float:
        residual = matrix @ values - rhs
        penalty = values - initial
        return float(
            np.mean(residual * residual) / (scale * scale)
            + regularization * np.mean(penalty * penalty) / (backplate_voltage_v**2)
        )

    def gradient(values: np.ndarray) -> np.ndarray:
        residual = matrix @ values - rhs
        return (
            2.0 * matrix.T @ residual / (residual.size * scale * scale)
            + 2.0
            * regularization
            * (values - initial)
            / (values.size * backplate_voltage_v**2)
        )

    result = minimize(
        objective,
        initial,
        jac=gradient,
        method="SLSQP",
        bounds=[(0.0, midgrid_voltage_v)] * stage1_count
        + [(midgrid_voltage_v, backplate_voltage_v)] * stage2_count,
        constraints=[LinearConstraint(difference, 0.0, np.inf)],
        options={"ftol": 1e-12, "maxiter": 2000},
    )
    if not result.success:
        raise RuntimeError(f"monotone voltage optimization failed: {result.message}")
    optimized = result.x
    baseline_residual = initial_residual
    optimized_residual = matrix @ optimized - rhs
    return {
        "schema_version": 1,
        "role": "oatof_reflectron_monotone_axis_field_voltage_fit",
        "status": "success",
        "stage1_count": stage1_count,
        "stage2_count": stage2_count,
        "fixed_endpoints_V": {
            "entrance": 0.0,
            "midgrid": midgrid_voltage_v,
            "backplate": backplate_voltage_v,
            "shield": 0.0,
        },
        "stage1_ring_voltages_V": optimized[:stage1_count].tolist(),
        "stage2_ring_voltages_V": optimized[stage1_count:].tolist(),
        "baseline_stage1_ring_voltages_V": stage1_initial.tolist(),
        "baseline_stage2_ring_voltages_V": stage2_initial.tolist(),
        "fit": {
            "sample_count": int(mask.sum()),
            "regularization": regularization,
            "baseline_axis_potential_rms_error_V": float(np.sqrt(np.mean(baseline_residual**2))),
            "optimized_axis_potential_rms_error_V": float(np.sqrt(np.mean(optimized_residual**2))),
            "maximum_voltage_change_V": float(np.max(np.abs(optimized - initial))),
        },
    }
