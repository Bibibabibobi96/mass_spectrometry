"""Construct ideal three-zone designs by linear third-order focus equations.

No particle peak or resolution is optimized. The first field, source-to-grid1
distance, two intermediate potentials, and external flight path are inputs.
Three inverse fields follow from a 3-by-3 system; positive lengths follow from
their voltage drops. Local closure still needs finite-source verification.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from scipy.optimize import brentq

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_theory import (
    _quadratic_power,
    axial_time_coefficients,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    IdealWorkingPoint,
    NumericalSourceSpec,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    derive_three_zone_state,
)


class LinearDesignError(ValueError):
    """A design equation failed, with a machine-readable reason and receipt."""

    def __init__(self, reason: str, report: dict[str, Any] | None = None):
        self.reason = reason
        self.report = {} if report is None else report
        super().__init__(reason)


@dataclass(frozen=True)
class LinearDesignResult:
    """A positive-field local solution, not a finite-width acceptance result."""

    point: IdealWorkingPoint
    outer: OuterGeometry
    report: dict[str, Any]


def solve_linear_third_order_design(
    spec: NumericalSourceSpec,
    reflectron: ReflectronGeometry,
    *,
    field1_v_per_mm: float,
    center_to_grid1_mm: float,
    grid2_voltage_fraction: float,
    reflectron_stage1_voltage_v: float,
    nominal_energy_per_charge_v: float,
    focus_drift_mm: float,
    characteristic_half_width_mm: float,
    condition_limit: float,
    coefficient_tolerance_ns: float,
    order: int = 6,
) -> LinearDesignResult:
    """Solve a1=a2=a3=0 for 1/E2, 1/E3, and 1/Fmirror2.

The coefficient convention is t(y)=sum(a_n*y**n), with ns and mm. Matrix
conditioning is measured after row scaling by half-width**n and unit column
norms; the caller supplies the admissible condition number and closure error.
No local energy-inversion monotonicity or engineering-size bound is imposed.
"""
    controls = {
        "field1_v_per_mm": float(field1_v_per_mm),
        "center_to_grid1_mm": float(center_to_grid1_mm),
        "grid2_voltage_fraction": float(grid2_voltage_fraction),
        "reflectron_stage1_voltage_v": float(reflectron_stage1_voltage_v),
        "nominal_energy_per_charge_v": float(nominal_energy_per_charge_v),
        "focus_drift_mm": float(focus_drift_mm),
        "characteristic_half_width_mm": float(characteristic_half_width_mm),
        "condition_limit": float(condition_limit),
        "coefficient_tolerance_ns": float(coefficient_tolerance_ns),
    }
    if not all(np.isfinite(value) for value in controls.values()):
        raise LinearDesignError("NONFINITE_CONTROL")
    positive = (field1_v_per_mm, center_to_grid1_mm,
                reflectron_stage1_voltage_v, nominal_energy_per_charge_v,
                characteristic_half_width_mm, coefficient_tolerance_ns)
    if any(value <= 0 for value in positive):
        raise LinearDesignError("NONPOSITIVE_CONTROL")
    if not 0 < grid2_voltage_fraction < 1 or condition_limit < 1:
        raise LinearDesignError("INVALID_FRACTION_OR_CONDITION_LIMIT")
    if focus_drift_mm < 0 or spec.center_x_mm <= 0:
        raise LinearDesignError("INVALID_SOURCE_OR_DRIFT_GEOMETRY")
    if spec.velocity_quadratic_m_per_s_per_mm2 != 0:
        raise LinearDesignError("AFFINE_SOURCE_REQUIRED")
    if isinstance(order, bool) or not isinstance(order, int) or order < 4:
        raise LinearDesignError("ORDER_MUST_BE_INTEGER_AT_LEAST_FOUR")

    source = spec.affine()
    w = nominal_energy_per_charge_v + source.chi_center_sqrt_v**2
    v1 = nominal_energy_per_charge_v - field1_v_per_mm * center_to_grid1_mm
    v2 = grid2_voltage_fraction * v1
    u1 = reflectron_stage1_voltage_v
    if v1 <= 0 or u1 >= w:
        raise LinearDesignError("CENTER_EVENT_DOMAIN_INVALID", {"grid1_v": v1, "energy_v": w})
    beta = source.chi_slope_sqrt_v_per_mm
    p = -field1_v_per_mm + 2 * source.chi_center_sqrt_v * beta
    q = beta**2
    sqrt_series = lambda voltage: _quadratic_power(w - voltage, p, q, .5, order)
    s0, s1, s2, sm = (sqrt_series(voltage) for voltage in (0., v1, v2, u1))
    drift = focus_drift_mm + reflectron.upstream_drift_mm + reflectron.downstream_drift_mm
    base = (2 / field1_v_per_mm * s1
            + 4 * reflectron.stage1_length_mm / u1 * (s0 - sm)
            + drift * _quadratic_power(w, p, q, -.5, order))
    base[0] -= 2 * source.chi_center_sqrt_v / field1_v_per_mm
    base[1] -= 2 * beta / field1_v_per_mm
    basis = np.column_stack((2 * (s2 - s1), 2 * (s0 - s2), 4 * sm))
    row_scale = characteristic_half_width_mm ** np.arange(1, 4)
    matrix = basis[1:4] * row_scale[:, None]
    right = -base[1:4] * row_scale
    column_scale = np.linalg.norm(matrix, axis=0)
    if np.any(column_scale == 0) or not np.all(np.isfinite(matrix)):
        raise LinearDesignError("SINGULAR_EQUATION_MATRIX")
    normalized = matrix / column_scale
    condition = float(np.linalg.cond(normalized))
    receipt: dict[str, Any] = {
        "controls": controls,
        "equations": "a1=a2=a3=0; linear in 1/E2, 1/E3, 1/Fmirror2",
        "normalized_matrix_condition_number": condition if np.isfinite(condition) else None,
        "normalized_matrix_determinant_sign": float(np.linalg.slogdet(normalized)[0]),
        "condition_normalization": "rows times half_width**order; columns unit Euclidean norm",
        "nominal_source_energy_v": w,
        "grid1_v": v1,
        "grid2_v": v2,
    }
    if not np.isfinite(condition) or condition > condition_limit:
        raise LinearDesignError("SINGULAR_OR_ILL_CONDITIONED_EQUATION_MATRIX", receipt)
    try:
        inverse_fields = np.linalg.solve(normalized, right) / column_scale
    except np.linalg.LinAlgError as error:
        raise LinearDesignError("SINGULAR_EQUATION_MATRIX", receipt) from error
    receipt["inverse_fields_mm_per_v"] = inverse_fields.tolist()
    if not np.all(np.isfinite(inverse_fields)) or np.any(inverse_fields <= 0):
        raise LinearDesignError("NO_POSITIVE_FIELD_SOLUTION", receipt)
    b, c, d = map(float, inverse_fields)
    l2, l3 = (v1 - v2) * b, v2 * c
    d1 = spec.center_x_mm + center_to_grid1_mm
    outer = OuterGeometry(d1, l2 + l3, l2 / (l2 + l3),
                          field1_v_per_mm * d1, nominal_energy_per_charge_v)
    eta = float(np.log(c / b))
    state = derive_three_zone_state(source, outer, eta)
    inner = InnerSolution(u1, 1 / d, eta)
    point = IdealWorkingPoint(source, state, reflectron, inner, focus_drift_mm, None)
    coefficients = axial_time_coefficients(point, order=order)
    scaled_error = coefficients[1:4] * row_scale
    receipt.update({
        "coefficients_ns_per_mm_power": coefficients.tolist(),
        "coefficient_convention": "Taylor coefficient a_n = derivative / factorial",
        "scaled_equation_residual_ns": scaled_error.tolist(),
        "equation_closed": bool(np.max(np.abs(scaled_error)) <= coefficient_tolerance_ns),
        "zone_lengths_mm": [d1, l2, l3],
        "fields_v_per_mm": [field1_v_per_mm, 1 / b, 1 / c, 1 / d],
        "source_geometric_full_width_limit_mm": 2 * min(spec.center_x_mm, center_to_grid1_mm),
        "fourth_order_coefficient_ns_per_mm4": float(coefficients[4]),
        "scope": "local third-order ideal focus from equations; no finite-width acceptance or global-maximum claim",
        "particle_peak_optimization_performed": False,
    })
    if not receipt["equation_closed"]:
        raise LinearDesignError("EQUATION_RESIDUAL_EXCEEDS_TOLERANCE", receipt)
    return LinearDesignResult(point, outer, receipt)


def find_fixed_length_designs(
    spec: NumericalSourceSpec,
    reflectron: ReflectronGeometry,
    *,
    field1_v_per_mm: float,
    center_to_grid1_mm: float,
    grid2_voltage_fraction: float,
    nominal_energy_per_charge_v: float,
    focus_drift_mm: float,
    total_accel_length_mm: float,
    stage1_voltage_grid_v: list[float],
    length_tolerance_mm: float,
    root_xtol_v: float,
    condition_limit: float,
    coefficient_tolerance_ns: float,
    characteristic_half_width_mm: float,
    order: int = 6,
) -> list[LinearDesignResult]:
    """Find fixed-length roots on positive-field branches sampled by a grid.

Each voltage sample first solves a1=a2=a3=0. Adjacent valid samples on the
same determinant-sign branch bracket the length equation; invalid interior
evaluations reject that bracket. Every root must satisfy the final length and
coefficient tolerances. All detected roots are returned without peak ranking.
The finite grid is not a completeness proof: an unsampled branch or a tangent
length root without a sign change can be missed.
"""
    grid = np.asarray(stage1_voltage_grid_v, dtype=float)
    if (grid.ndim != 1 or len(grid) < 2 or not np.all(np.isfinite(grid))
            or np.any(grid <= 0) or np.any(np.diff(grid) <= 0)):
        raise ValueError("stage1 voltage grid must have at least two increasing positive values")
    for name, value in (("total_accel_length_mm", total_accel_length_mm),
                        ("length_tolerance_mm", length_tolerance_mm),
                        ("root_xtol_v", root_xtol_v)):
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    cache: dict[float, LinearDesignResult] = {}

    def evaluate(voltage: float) -> LinearDesignResult:
        voltage = float(voltage)
        if voltage not in cache:
            cache[voltage] = solve_linear_third_order_design(
                spec, reflectron, field1_v_per_mm=field1_v_per_mm,
                center_to_grid1_mm=center_to_grid1_mm,
                grid2_voltage_fraction=grid2_voltage_fraction,
                reflectron_stage1_voltage_v=voltage,
                nominal_energy_per_charge_v=nominal_energy_per_charge_v,
                focus_drift_mm=focus_drift_mm,
                characteristic_half_width_mm=characteristic_half_width_mm,
                condition_limit=condition_limit,
                coefficient_tolerance_ns=coefficient_tolerance_ns, order=order)
        return cache[voltage]

    def length_error(result: LinearDesignResult) -> float:
        return float(sum(result.report["zone_lengths_mm"]) - total_accel_length_mm)

    def branch_sign(result: LinearDesignResult) -> float:
        return result.report["normalized_matrix_determinant_sign"]

    results: list[LinearDesignResult] = []

    def retain(result: LinearDesignResult, bracket: list[float]) -> None:
        error = length_error(result)
        if abs(error) > length_tolerance_mm:
            return
        voltage = result.point.inner.stage1_voltage_drop_v
        if any(abs(item.point.inner.stage1_voltage_drop_v - voltage) <= root_xtol_v
               for item in results):
            return
        receipt = {**result.report, "fixed_length_equation": {
            "target_accelerator_length_mm": float(total_accel_length_mm),
            "length_residual_mm": error,
            "length_tolerance_mm": float(length_tolerance_mm),
            "root_xtol_v": float(root_xtol_v),
            "voltage_bracket_v": bracket,
            "method": "bracketed scalar root after linear third-order closure",
            "all_roots_in_continuous_domain_proved": False,
            "particle_peak_optimization_performed": False,
        }}
        results.append(replace(result, report=receipt))

    previous: tuple[float, LinearDesignResult] | None = None
    invalid_controls = {"NONFINITE_CONTROL", "NONPOSITIVE_CONTROL",
        "INVALID_FRACTION_OR_CONDITION_LIMIT", "INVALID_SOURCE_OR_DRIFT_GEOMETRY",
        "AFFINE_SOURCE_REQUIRED", "ORDER_MUST_BE_INTEGER_AT_LEAST_FOUR"}
    for voltage in map(float, grid):
        try:
            result = evaluate(voltage)
        except LinearDesignError as error:
            if error.reason in invalid_controls:
                raise
            previous = None
            continue
        retain(result, [voltage, voltage])
        if previous is not None:
            old_voltage, old_result = previous
            sign = branch_sign(result)
            if branch_sign(old_result) == sign and length_error(old_result)*length_error(result) < 0:
                def residual(value: float) -> float:
                    candidate = evaluate(value)
                    if branch_sign(candidate) != sign:
                        raise LinearDesignError("BRACKET_CROSSES_EQUATION_POLE")
                    return length_error(candidate)
                try:
                    # A midpoint catches a hidden invalid branch before Brent's
                    # interpolation can approach a pole from only one side.
                    residual((old_voltage+voltage)/2)
                    root_voltage = brentq(residual, old_voltage, voltage, xtol=root_xtol_v)
                    retain(evaluate(root_voltage), [old_voltage, voltage])
                except (LinearDesignError, ValueError, RuntimeError):
                    pass  # no valid fixed-length root from this sampled bracket
        previous = (voltage, result)
    return sorted(results, key=lambda item: item.point.inner.stage1_voltage_drop_v)
