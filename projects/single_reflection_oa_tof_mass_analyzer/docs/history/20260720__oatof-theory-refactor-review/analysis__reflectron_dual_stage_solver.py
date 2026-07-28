"""Solver-independent ideal dual-stage reflectron reference.

The model is one-dimensional, piecewise uniform, and uses energy per charge in volts,
lengths in millimetres, and fields in volts per millimetre.  The effective upstream
field-free length starts at the oa-accelerator first-order time-focus plane.

This module deliberately does not promote a cubic endpoint estimate to a formal FWHM.
It can emit deterministic arrival-time samples for the repository's shared FWHM
post-processor.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ELEMENTARY_CHARGE_C = 1.602176634e-19
ATOMIC_MASS_CONSTANT_KG = 1.66053906892e-27


class PhysicsContractError(ValueError):
    """Raised when an input violates the ideal reflectron model."""


@dataclass(frozen=True)
class ReflectronSolution:
    nominal_energy_per_charge_v: float
    upstream_from_accelerator_focus_mm: float
    downstream_to_detector_mm: float
    total_field_free_length_mm: float
    stage1_length_mm: float
    stage1_voltage_drop_v: float
    stage1_field_v_per_mm: float
    stage2_field_v_per_mm: float
    nominal_stage2_penetration_mm: float
    required_stage2_depth_mm: float
    energy_min_v: float
    energy_max_v: float
    low_energy_reaches_stage2: bool
    first_derivative_residual: float
    second_derivative_residual: float


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise PhysicsContractError(f"{name} must be finite")
    return result


def _positive(value: float, name: str) -> None:
    if value <= 0.0:
        raise PhysicsContractError(f"{name} must be > 0")


def normalized_flight_time_mm_sqrt_v(
    energy_per_charge_v: float,
    total_field_free_length_mm: float,
    stage1_voltage_drop_v: float,
    stage1_field_v_per_mm: float,
    stage2_field_v_per_mm: float,
) -> float:
    """Return ideal reflectron time in mm/sqrt(V), with m/q factored out."""

    w = _finite_float(energy_per_charge_v, "energy_per_charge_v")
    length = _finite_float(total_field_free_length_mm, "total_field_free_length_mm")
    u1 = _finite_float(stage1_voltage_drop_v, "stage1_voltage_drop_v")
    field1 = _finite_float(stage1_field_v_per_mm, "stage1_field_v_per_mm")
    field2 = _finite_float(stage2_field_v_per_mm, "stage2_field_v_per_mm")
    for value, name in (
        (w, "energy_per_charge_v"),
        (length, "total_field_free_length_mm"),
        (u1, "stage1_voltage_drop_v"),
        (field1, "stage1_field_v_per_mm"),
        (field2, "stage2_field_v_per_mm"),
    ):
        _positive(value, name)
    if w <= u1:
        raise PhysicsContractError(
            "energy_per_charge_v must exceed the stage-1 voltage drop; otherwise "
            "the ion turns before entering stage 2"
        )

    root_w = math.sqrt(w)
    root_stage2_entry = math.sqrt(w - u1)
    return (
        length / root_w
        + 4.0 * (root_w - root_stage2_entry) / field1
        + 4.0 * root_stage2_entry / field2
    )


def flight_time_s(
    energy_per_charge_v: float,
    mass_to_charge_th: float,
    total_field_free_length_mm: float,
    stage1_voltage_drop_v: float,
    stage1_field_v_per_mm: float,
    stage2_field_v_per_mm: float,
) -> float:
    """Return physical flight time for ``mass_to_charge_th`` in Th."""

    mu = _finite_float(mass_to_charge_th, "mass_to_charge_th")
    _positive(mu, "mass_to_charge_th")
    tau = normalized_flight_time_mm_sqrt_v(
        energy_per_charge_v,
        total_field_free_length_mm,
        stage1_voltage_drop_v,
        stage1_field_v_per_mm,
        stage2_field_v_per_mm,
    )
    mass_over_charge_si = mu * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
    return 1.0e-3 * math.sqrt(mass_over_charge_si / 2.0) * tau


def normalized_derivatives(
    nominal_energy_per_charge_v: float,
    total_field_free_length_mm: float,
    stage1_voltage_drop_v: float,
    stage1_field_v_per_mm: float,
    stage2_field_v_per_mm: float,
) -> tuple[float, float]:
    """Return analytic first and second derivatives of normalized flight time."""

    w = nominal_energy_per_charge_v
    length = total_field_free_length_mm
    u1 = stage1_voltage_drop_v
    field1 = stage1_field_v_per_mm
    field2 = stage2_field_v_per_mm
    if not w > u1 > 0.0:
        raise PhysicsContractError("require nominal energy > stage-1 drop > 0")
    root_w = math.sqrt(w)
    root_remaining = math.sqrt(w - u1)
    first = (
        -length / (2.0 * root_w**3)
        + 2.0 / field1 * (1.0 / root_w - 1.0 / root_remaining)
        + 2.0 / (field2 * root_remaining)
    )
    second = (
        3.0 * length / (4.0 * root_w**5)
        + 1.0
        / field1
        * (-1.0 / root_w**3 + 1.0 / root_remaining**3)
        - 1.0 / (field2 * root_remaining**3)
    )
    return first, second


def normalized_third_derivative(
    nominal_energy_per_charge_v: float,
    total_field_free_length_mm: float,
    stage1_voltage_drop_v: float,
    stage1_field_v_per_mm: float,
    stage2_field_v_per_mm: float,
) -> float:
    """Return the analytic third derivative of normalized flight time."""

    w = nominal_energy_per_charge_v
    length = total_field_free_length_mm
    u1 = stage1_voltage_drop_v
    field1 = stage1_field_v_per_mm
    field2 = stage2_field_v_per_mm
    if not w > u1 > 0.0:
        raise PhysicsContractError("require nominal energy > stage-1 drop > 0")
    remaining = w - u1
    return (
        -15.0 * length / (8.0 * w ** 3.5)
        + 3.0 / (2.0 * field1) * (w ** -2.5 - remaining ** -2.5)
        + 3.0 / (2.0 * field2) * remaining ** -2.5
    )


def solve_reflectron_fields(
    nominal_energy_per_charge_v: float,
    stage1_length_mm: float,
    *,
    upstream_from_accelerator_focus_mm: float | None = None,
    downstream_to_detector_mm: float | None = None,
    total_field_free_length_mm: float | None = None,
    energy_min_v: float | None = None,
    energy_max_v: float | None = None,
    stage2_margin_fraction: float = 0.0,
    stage2_margin_mm: float = 0.0,
    enforce_energy_envelope: bool = True,
) -> ReflectronSolution:
    """Solve the ideal uncoupled dual-stage reflectron field conditions.

    The solution enforces first- and second-order energy focusing for the reflectron
    segment beginning at the accelerator first-order focus plane.  For global oa-TOF
    second-order focusing, use ``oatof_oaaccelerator_coupling.py`` because the
    accelerator contributes its own second derivative.
    """

    w0 = _finite_float(
        nominal_energy_per_charge_v, "nominal_energy_per_charge_v"
    )
    d1 = _finite_float(stage1_length_mm, "stage1_length_mm")
    _positive(w0, "nominal_energy_per_charge_v")
    _positive(d1, "stage1_length_mm")

    if total_field_free_length_mm is None:
        if upstream_from_accelerator_focus_mm is None or downstream_to_detector_mm is None:
            raise PhysicsContractError(
                "provide both upstream_from_accelerator_focus_mm and "
                "downstream_to_detector_mm, or provide total_field_free_length_mm"
            )
        upstream = _finite_float(
            upstream_from_accelerator_focus_mm,
            "upstream_from_accelerator_focus_mm",
        )
        downstream = _finite_float(
            downstream_to_detector_mm, "downstream_to_detector_mm"
        )
        if upstream < 0.0 or downstream < 0.0:
            raise PhysicsContractError("field-free path lengths must be >= 0")
        length = upstream + downstream
    else:
        length = _finite_float(
            total_field_free_length_mm, "total_field_free_length_mm"
        )
        _positive(length, "total_field_free_length_mm")
        if upstream_from_accelerator_focus_mm is None:
            upstream = length / 2.0
        else:
            upstream = _finite_float(
                upstream_from_accelerator_focus_mm,
                "upstream_from_accelerator_focus_mm",
            )
        if downstream_to_detector_mm is None:
            downstream = length - upstream
        else:
            downstream = _finite_float(
                downstream_to_detector_mm, "downstream_to_detector_mm"
            )
        if upstream < 0.0 or downstream < 0.0:
            raise PhysicsContractError("field-free path lengths must be >= 0")
        if not math.isclose(
            upstream + downstream,
            length,
            rel_tol=1.0e-12,
            abs_tol=1.0e-10,
        ):
            raise PhysicsContractError(
                "upstream + downstream must equal total_field_free_length_mm"
            )

    if not d1 < length / 4.0:
        raise PhysicsContractError(
            "require 0 < stage1_length_mm < total_field_free_length_mm / 4"
        )

    u1 = 2.0 * w0 * (length + 2.0 * d1) / (3.0 * length)
    field1 = u1 / d1
    root_w = math.sqrt(w0)
    root_remaining = math.sqrt(w0 - u1)
    inverse_field2 = 0.5 * root_remaining * (
        length / (2.0 * root_w**3)
        - 2.0 / field1 * (1.0 / root_w - 1.0 / root_remaining)
    )
    if inverse_field2 <= 0.0:
        raise PhysicsContractError("derived stage-2 field is not positive")
    field2 = 1.0 / inverse_field2

    w_min = w0 if energy_min_v is None else _finite_float(energy_min_v, "energy_min_v")
    w_max = w0 if energy_max_v is None else _finite_float(energy_max_v, "energy_max_v")
    if not 0.0 < w_min <= w0 <= w_max:
        raise PhysicsContractError("require 0 < energy_min <= nominal_energy <= energy_max")
    low_reaches_stage2 = w_min > u1
    if enforce_energy_envelope and not low_reaches_stage2:
        raise PhysicsContractError(
            "energy envelope violates the two-stage model: the low-energy tail turns "
            "inside stage 1"
        )

    nominal_penetration = (w0 - u1) / field2
    high_energy_penetration = (w_max - u1) / field2
    margin_fraction = _finite_float(
        stage2_margin_fraction, "stage2_margin_fraction"
    )
    margin_mm = _finite_float(stage2_margin_mm, "stage2_margin_mm")
    if margin_fraction < 0.0 or margin_mm < 0.0:
        raise PhysicsContractError("stage-2 margins must be >= 0")
    required_depth = high_energy_penetration * (1.0 + margin_fraction) + margin_mm

    first, second = normalized_derivatives(w0, length, u1, field1, field2)
    return ReflectronSolution(
        nominal_energy_per_charge_v=w0,
        upstream_from_accelerator_focus_mm=upstream,
        downstream_to_detector_mm=downstream,
        total_field_free_length_mm=length,
        stage1_length_mm=d1,
        stage1_voltage_drop_v=u1,
        stage1_field_v_per_mm=field1,
        stage2_field_v_per_mm=field2,
        nominal_stage2_penetration_mm=nominal_penetration,
        required_stage2_depth_mm=required_depth,
        energy_min_v=w_min,
        energy_max_v=w_max,
        low_energy_reaches_stage2=low_reaches_stage2,
        first_derivative_residual=first,
        second_derivative_residual=second,
    )


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Solve a small dense system with partial-pivot Gaussian elimination."""

    n = len(rhs)
    a = [row[:] + [rhs_value] for row, rhs_value in zip(matrix, rhs, strict=True)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1.0e-30:
            raise ArithmeticError("singular finite-difference system")
        a[col], a[pivot] = a[pivot], a[col]
        pivot_value = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= pivot_value
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                a[row][j] -= factor * a[col][j]
    return [a[row][n] for row in range(n)]


def finite_difference_derivative(
    function: Callable[[float], float],
    x: float,
    order: int,
    *,
    relative_step: float = 1.0e-4,
    radius: int = 3,
) -> float:
    """Return a centred finite-difference derivative using generated weights."""

    if order < 0 or order > 2 * radius:
        raise ValueError("order must satisfy 0 <= order <= 2 * radius")
    if relative_step <= 0.0:
        raise ValueError("relative_step must be > 0")
    h = max(abs(x) * relative_step, 1.0e-8)
    offsets = list(range(-radius, radius + 1))
    n = len(offsets)
    matrix = [[float(offset) ** power for offset in offsets] for power in range(n)]
    rhs = [0.0] * n
    rhs[order] = float(math.factorial(order))
    weights = _solve_linear_system(matrix, rhs)
    return sum(
        weight * function(x + offset * h)
        for weight, offset in zip(weights, offsets, strict=True)
    ) / h**order


def energy_aberration_diagnostics(
    solution: ReflectronSolution,
    mass_to_charge_th: float,
    energy_half_range_v: float,
) -> dict[str, Any]:
    """Return cubic endpoint diagnostics without claiming a formal FWHM."""

    mu = _finite_float(mass_to_charge_th, "mass_to_charge_th")
    half_range = _finite_float(energy_half_range_v, "energy_half_range_v")
    _positive(mu, "mass_to_charge_th")
    _positive(half_range, "energy_half_range_v")
    def normalized(w: float) -> float:
        return normalized_flight_time_mm_sqrt_v(
            w,
            solution.total_field_free_length_mm,
            solution.stage1_voltage_drop_v,
            solution.stage1_field_v_per_mm,
            solution.stage2_field_v_per_mm,
        )

    tau0 = normalized(solution.nominal_energy_per_charge_v)
    tau3 = normalized_third_derivative(
        solution.nominal_energy_per_charge_v,
        solution.total_field_free_length_mm,
        solution.stage1_voltage_drop_v,
        solution.stage1_field_v_per_mm,
        solution.stage2_field_v_per_mm,
    )
    mass_over_charge_si = mu * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
    factor = 1.0e-3 * math.sqrt(mass_over_charge_si / 2.0)
    t0 = factor * tau0
    delta_t_endpoint = factor * abs(tau3) * half_range**3 / 6.0
    proxy = math.inf if delta_t_endpoint == 0.0 else t0 / (2.0 * delta_t_endpoint)
    return {
        "mass_to_charge_Th": mu,
        "energy_half_range_V": half_range,
        "nominal_time_s": t0,
        "normalized_third_derivative_mm_per_V_power_3p5": tau3,
        "cubic_endpoint_time_offset_s": delta_t_endpoint,
        "endpoint_resolution_proxy_not_FWHM": proxy,
        "formal_FWHM_eligible": False,
        "required_formal_method": (
            "sample the frozen input distribution, build the arrival-time peak, and "
            "use the repository shared FWHM post-processor"
        ),
    }


def arrival_time_samples(
    solution: ReflectronSolution,
    mass_to_charge_th: float,
    energies_per_charge_v: Sequence[float],
) -> list[dict[str, float]]:
    """Return deterministic particle-level times for external FWHM processing."""

    rows: list[dict[str, float]] = []
    for index, energy in enumerate(energies_per_charge_v):
        w = float(energy)
        rows.append(
            {
                "sample_index": float(index),
                "energy_per_charge_V": w,
                "arrival_time_s": flight_time_s(
                    w,
                    mass_to_charge_th,
                    solution.total_field_free_length_mm,
                    solution.stage1_voltage_drop_v,
                    solution.stage1_field_v_per_mm,
                    solution.stage2_field_v_per_mm,
                ),
            }
        )
    return rows


def _mapping_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    raise PhysicsContractError(f"missing required key; expected one of {keys}")


def derive(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Solve a reflectron design from a machine-readable project contract."""

    design = contract["design"]
    w0 = float(
        _mapping_value(
            design,
            "nominal_energy_per_charge_V",
            "U0_V",
            "U0",
        )
    )
    reflectron = design.get("reflectron", design)
    stage1_length = float(
        _mapping_value(reflectron, "stage1_length_mm", "d1_mm", "d1")
    )

    lengths = design.get("field_free_lengths_mm", {})
    total = lengths.get("total")
    upstream = lengths.get(
        "upstream_from_accelerator_focus",
        lengths.get("L1", design.get("L1_mm")),
    )
    downstream = lengths.get(
        "downstream_to_detector",
        lengths.get("L2", design.get("L2_mm")),
    )
    if total is None and upstream is None and downstream is None:
        total = _mapping_value(design, "total_field_free_length_mm", "L_mm", "L")

    envelope = design.get("energy_envelope_V", {})
    half_range = envelope.get("half_range")
    if half_range is not None:
        energy_min = w0 - float(half_range)
        energy_max = w0 + float(half_range)
    else:
        energy_min = envelope.get("min", envelope.get("minimum", w0))
        energy_max = envelope.get("max", envelope.get("maximum", w0))

    margin = reflectron.get("stage2_margin", {})
    solution = solve_reflectron_fields(
        w0,
        stage1_length,
        upstream_from_accelerator_focus_mm=(None if upstream is None else float(upstream)),
        downstream_to_detector_mm=(None if downstream is None else float(downstream)),
        total_field_free_length_mm=(None if total is None else float(total)),
        energy_min_v=float(energy_min),
        energy_max_v=float(energy_max),
        stage2_margin_fraction=float(margin.get("fraction", 0.0)),
        stage2_margin_mm=float(margin.get("absolute_mm", 0.0)),
        enforce_energy_envelope=bool(
            design.get("enforce_energy_envelope", True)
        ),
    )
    result: dict[str, Any] = {
        "model_id": "reflectron.dual_stage.ideal_1d.v2",
        "length_unit": "mm",
        "potential_unit": "V",
        "energy_per_charge_unit": "V",
        **asdict(solution),
        "formal_FWHM_eligible": False,
        "field_free_origin": "oaaccelerator_first_order_time_focus_plane",
    }

    actual_stage2_length = reflectron.get("stage2_length_mm")
    if actual_stage2_length is not None:
        actual = float(actual_stage2_length)
        result["stage2_length_mm"] = actual
        result["stage2_depth_margin_mm"] = (
            actual - solution.required_stage2_depth_mm
        )
        result["stage2_depth_pass"] = actual >= solution.required_stage2_depth_mm
        if bool(design.get("enforce_stage2_depth", True)) and not result[
            "stage2_depth_pass"
        ]:
            raise PhysicsContractError(
                "configured stage2_length_mm is shorter than the required high-energy "
                "penetration depth plus margin"
            )

    particle = contract.get("particle", {})
    if "mass_to_charge_Th" in particle:
        mu = float(particle["mass_to_charge_Th"])
        result["nominal_flight_time_s"] = flight_time_s(
            solution.nominal_energy_per_charge_v,
            mu,
            solution.total_field_free_length_mm,
            solution.stage1_voltage_drop_v,
            solution.stage1_field_v_per_mm,
            solution.stage2_field_v_per_mm,
        )
        if half_range is not None and float(half_range) > 0.0:
            result["energy_aberration_diagnostics"] = energy_aberration_diagnostics(
                solution,
                mu,
                float(half_range),
            )
    return result


def _assert_expected(
    actual: Any,
    expected: Any,
    path: str,
    *,
    abs_tol: float,
    rel_tol: float,
) -> None:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            raise SystemExit(f"MISMATCH {path}: actual is not a mapping")
        for key, value in expected.items():
            if key not in actual:
                raise SystemExit(f"MISMATCH {path}.{key}: missing actual key")
            _assert_expected(
                actual[key],
                value,
                f"{path}.{key}",
                abs_tol=abs_tol,
                rel_tol=rel_tol,
            )
        return
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes)):
            raise SystemExit(f"MISMATCH {path}: actual is not a sequence")
        if len(actual) != len(expected):
            raise SystemExit(f"MISMATCH {path}: sequence length differs")
        for index, (a_value, e_value) in enumerate(zip(actual, expected, strict=True)):
            _assert_expected(
                a_value,
                e_value,
                f"{path}[{index}]",
                abs_tol=abs_tol,
                rel_tol=rel_tol,
            )
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not math.isclose(
            float(actual), float(expected), rel_tol=rel_tol, abs_tol=abs_tol
        ):
            raise SystemExit(
                f"MISMATCH {path}: actual={actual!r} expected={expected!r}"
            )
        return
    if actual != expected:
        raise SystemExit(f"MISMATCH {path}: actual={actual!r} expected={expected!r}")


def _write_samples_csv(path: Path, rows: Sequence[Mapping[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("cannot write empty sample set")
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_self_test() -> None:
    solution = solve_reflectron_fields(
        4000.0,
        50.0,
        upstream_from_accelerator_focus_mm=600.0,
        downstream_to_detector_mm=400.0,
        energy_min_v=3980.0,
        energy_max_v=4020.0,
        stage2_margin_fraction=0.2,
    )
    if abs(solution.first_derivative_residual) > 1.0e-14:
        raise AssertionError("first-order reflectron condition failed")
    if abs(solution.second_derivative_residual) > 1.0e-16:
        raise AssertionError("second-order reflectron condition failed")

    split = solve_reflectron_fields(
        4000.0,
        50.0,
        upstream_from_accelerator_focus_mm=100.0,
        downstream_to_detector_mm=900.0,
        energy_min_v=3980.0,
        energy_max_v=4020.0,
        stage2_margin_fraction=0.2,
    )
    for name in (
        "stage1_voltage_drop_v",
        "stage1_field_v_per_mm",
        "stage2_field_v_per_mm",
    ):
        if not math.isclose(
            getattr(solution, name),
            getattr(split, name),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise AssertionError("L_up/L_down split invariance failed")

    if solution.required_stage2_depth_mm <= solution.nominal_stage2_penetration_mm:
        raise AssertionError("high-energy envelope did not increase stage-2 depth")

    t100 = flight_time_s(
        4000.0,
        100.0,
        solution.total_field_free_length_mm,
        solution.stage1_voltage_drop_v,
        solution.stage1_field_v_per_mm,
        solution.stage2_field_v_per_mm,
    )
    t400 = flight_time_s(
        4000.0,
        400.0,
        solution.total_field_free_length_mm,
        solution.stage1_voltage_drop_v,
        solution.stage1_field_v_per_mm,
        solution.stage2_field_v_per_mm,
    )
    if not math.isclose(t400 / t100, 2.0, rel_tol=1.0e-12):
        raise AssertionError("reflectron time mass-to-charge scaling failed")

    def polynomial(x: float) -> float:
        return 2.0 + 3.0 * x - 4.0 * x**2 + 5.0 * x**3

    if not math.isclose(
        finite_difference_derivative(polynomial, 1.2, 3, relative_step=1.0e-2),
        30.0,
        rel_tol=1.0e-6,
        abs_tol=1.0e-6,
    ):
        raise AssertionError("finite-difference third derivative failed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Solve the ideal dual-stage reflectron reference model."
    )
    parser.add_argument("contract", type=Path, nargs="?")
    parser.add_argument("--write-derived", type=Path)
    parser.add_argument("--write-samples", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print("REFLECTRON_DUAL_STAGE_SELF_TEST=PASS")
        if args.contract is None:
            return 0
    if args.contract is None:
        parser.error("contract is required unless --self-test is used")

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = derive(contract)
    tolerance = contract.get("expected_tolerance", {})
    _assert_expected(
        result,
        contract.get("expected_derived", {}),
        "expected_derived",
        abs_tol=float(tolerance.get("absolute", 1.0e-10)),
        rel_tol=float(tolerance.get("relative", 1.0e-12)),
    )

    if args.write_samples:
        particle = contract.get("particle", {})
        if "mass_to_charge_Th" not in particle:
            raise PhysicsContractError(
                "particle.mass_to_charge_Th is required for --write-samples"
            )
        energies = contract.get("energy_samples_per_charge_V")
        if not energies:
            raise PhysicsContractError(
                "energy_samples_per_charge_V is required for --write-samples"
            )
        solution_keys = ReflectronSolution.__dataclass_fields__.keys()
        solution = ReflectronSolution(
            **{key: result[key] for key in solution_keys}
        )
        rows = arrival_time_samples(
            solution, float(particle["mass_to_charge_Th"]), [float(v) for v in energies]
        )
        _write_samples_csv(args.write_samples, rows)
        result["arrival_time_samples_csv"] = str(args.write_samples)

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.write_derived:
        args.write_derived.parent.mkdir(parents=True, exist_ok=True)
        args.write_derived.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("REFLECTRON_DUAL_STAGE_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
