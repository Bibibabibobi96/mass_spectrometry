"""Coupled one-dimensional oa-accelerator / dual-stage-reflectron reference.

The upstream field-free length ``L_up`` is measured from the orthogonal accelerator's
first-order time-focus plane to the reflectron entrance.  This module retains the
accelerator time-to-focus term when solving the global first- and second-order energy
conditions; therefore it is not equivalent to solving the reflectron in isolation.

Lengths are millimetres, potentials and energy per charge are volts, and fields are
volts per millimetre.  Formal FWHM remains the responsibility of the repository's
shared particle-distribution post-processor.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from projects.oa_tof.analysis.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
    AcceleratorState,
    PhysicsContractError,
    accelerator_state,
    compact_exit_focus_bound,
    normalized_time_to_plane_mm_sqrt_v,
)
from projects.oa_tof.analysis.reflectron_dual_stage_solver import (
    normalized_derivatives as reflectron_normalized_derivatives,
    normalized_flight_time_mm_sqrt_v as reflectron_normalized_time,
    normalized_third_derivative as reflectron_normalized_third_derivative,
    solve_reflectron_fields,
)


@dataclass(frozen=True)
class CoupledReflectronSolution:
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
    accelerator_first_derivative_at_focus: float
    accelerator_second_derivative_at_focus: float
    accelerator_third_derivative_at_focus: float
    total_first_derivative_residual: float
    total_second_derivative_residual: float
    total_third_derivative: float
    root_iterations: int


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise PhysicsContractError(f"{name} must be finite")
    return result


def _positive(value: float, name: str) -> None:
    if value <= 0.0:
        raise PhysicsContractError(f"{name} must be > 0")


def _as_int(value: Any, name: str, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise PhysicsContractError(f"{name} must be an integer >= {minimum}")
    numeric = _finite_float(value, name)
    if not numeric.is_integer() or numeric < minimum:
        raise PhysicsContractError(f"{name} must be an integer >= {minimum}")
    return int(numeric)


def accelerator_normalized_time_to_focus(
    energy_per_charge_v: float,
    accelerator: AcceleratorState,
) -> float:
    """Return accelerator release-to-focus time with m/q factored out."""

    return normalized_time_to_plane_mm_sqrt_v(
        energy_per_charge_v,
        accelerator.intermediate_relative_v,
        accelerator.field1_v_per_mm,
        accelerator.field2_v_per_mm,
        accelerator.first_order_focus_drift_mm,
    )


def accelerator_normalized_derivatives_at_focus(
    nominal_energy_per_charge_v: float,
    accelerator: AcceleratorState,
) -> tuple[float, float, float]:
    """Return first through third derivatives of accelerator time to its focus."""

    w = _finite_float(
        nominal_energy_per_charge_v, "nominal_energy_per_charge_v"
    )
    vg = accelerator.intermediate_relative_v
    if w <= vg:
        raise PhysicsContractError(
            "nominal energy must exceed the intermediate electrode potential"
        )
    e1 = accelerator.field1_v_per_mm
    e2 = accelerator.field2_v_per_mm
    drift = accelerator.first_order_focus_drift_mm
    remaining = w - vg

    first = (
        1.0 / (e1 * math.sqrt(remaining))
        + 1.0 / e2 * (1.0 / math.sqrt(w) - 1.0 / math.sqrt(remaining))
        - drift / (2.0 * w**1.5)
    )
    second = (
        -1.0 / (2.0 * e1 * remaining**1.5)
        + 1.0 / e2 * (-1.0 / (2.0 * w**1.5) + 1.0 / (2.0 * remaining**1.5))
        + 3.0 * drift / (4.0 * w**2.5)
    )
    third = (
        3.0 / (4.0 * e1 * remaining**2.5)
        + 1.0 / e2 * (3.0 / (4.0 * w**2.5) - 3.0 / (4.0 * remaining**2.5))
        - 15.0 * drift / (8.0 * w**3.5)
    )
    return first, second, third


def coupled_normalized_flight_time_mm_sqrt_v(
    energy_per_charge_v: float,
    accelerator: AcceleratorState,
    upstream_from_accelerator_focus_mm: float,
    downstream_to_detector_mm: float,
    stage1_voltage_drop_v: float,
    stage1_field_v_per_mm: float,
    stage2_field_v_per_mm: float,
) -> float:
    """Return total release-to-detector time with m/q factored out."""

    upstream = _finite_float(
        upstream_from_accelerator_focus_mm,
        "upstream_from_accelerator_focus_mm",
    )
    downstream = _finite_float(
        downstream_to_detector_mm, "downstream_to_detector_mm"
    )
    if upstream < 0.0 or downstream < 0.0:
        raise PhysicsContractError("field-free path lengths must be >= 0")
    return accelerator_normalized_time_to_focus(energy_per_charge_v, accelerator) + (
        reflectron_normalized_time(
            energy_per_charge_v,
            upstream + downstream,
            stage1_voltage_drop_v,
            stage1_field_v_per_mm,
            stage2_field_v_per_mm,
        )
    )


def coupled_flight_time_s(
    energy_per_charge_v: float,
    mass_to_charge_th: float,
    accelerator: AcceleratorState,
    upstream_from_accelerator_focus_mm: float,
    downstream_to_detector_mm: float,
    stage1_voltage_drop_v: float,
    stage1_field_v_per_mm: float,
    stage2_field_v_per_mm: float,
) -> float:
    """Return physical release-to-detector time for a mass-to-charge ratio in Th."""

    mu = _finite_float(mass_to_charge_th, "mass_to_charge_th")
    _positive(mu, "mass_to_charge_th")
    tau = coupled_normalized_flight_time_mm_sqrt_v(
        energy_per_charge_v,
        accelerator,
        upstream_from_accelerator_focus_mm,
        downstream_to_detector_mm,
        stage1_voltage_drop_v,
        stage1_field_v_per_mm,
        stage2_field_v_per_mm,
    )
    mass_over_charge_si = mu * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
    return 1.0e-3 * math.sqrt(mass_over_charge_si / 2.0) * tau


def _candidate_from_stage1_drop(
    stage1_drop_v: float,
    nominal_energy_v: float,
    stage1_length_mm: float,
    total_field_free_length_mm: float,
    accelerator_first: float,
    accelerator_second: float,
) -> tuple[float, float] | None:
    """Return (second-order residual, stage2 field) for a trial stage-1 drop."""

    u1 = stage1_drop_v
    w0 = nominal_energy_v
    if not 0.0 < u1 < w0:
        return None
    field1 = u1 / stage1_length_mm
    root_w = math.sqrt(w0)
    root_remaining = math.sqrt(w0 - u1)
    inverse_field1 = 1.0 / field1

    inverse_field2 = 0.5 * root_remaining * (
        total_field_free_length_mm / (2.0 * root_w**3)
        - accelerator_first
        - 2.0
        * inverse_field1
        * (1.0 / root_w - 1.0 / root_remaining)
    )
    if not math.isfinite(inverse_field2) or inverse_field2 <= 0.0:
        return None

    residual = (
        accelerator_second
        + 3.0 * total_field_free_length_mm / (4.0 * root_w**5)
        + inverse_field1
        * (-1.0 / root_w**3 + 1.0 / root_remaining**3)
        - inverse_field2 / root_remaining**3
    )
    return residual, 1.0 / inverse_field2


def _find_coupled_root(
    nominal_energy_v: float,
    stage1_length_mm: float,
    total_field_free_length_mm: float,
    energy_min_v: float,
    accelerator_first: float,
    accelerator_second: float,
    *,
    scan_points: int = 4096,
    bisection_iterations: int = 100,
) -> tuple[float, float, int]:
    """Find a physically valid stage-1 drop by scan plus bisection."""

    if scan_points < 32:
        raise ValueError("scan_points must be >= 32")
    lower = max(nominal_energy_v * 1.0e-8, 1.0e-9)
    upper = min(nominal_energy_v, energy_min_v) * (1.0 - 1.0e-10)
    if not lower < upper:
        raise PhysicsContractError("empty stage-1 voltage search interval")

    uncoupled_guess = 2.0 * nominal_energy_v * (
        total_field_free_length_mm + 2.0 * stage1_length_mm
    ) / (3.0 * total_field_free_length_mm)

    valid: list[tuple[float, float, float]] = []
    for index in range(scan_points + 1):
        fraction = index / scan_points
        u1 = lower + (upper - lower) * fraction
        candidate = _candidate_from_stage1_drop(
            u1,
            nominal_energy_v,
            stage1_length_mm,
            total_field_free_length_mm,
            accelerator_first,
            accelerator_second,
        )
        if candidate is not None:
            residual, field2 = candidate
            valid.append((u1, residual, field2))

    brackets: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    exact: list[tuple[float, float, float]] = []
    for point in valid:
        if point[1] == 0.0:
            exact.append(point)
    for left, right in zip(valid, valid[1:], strict=False):
        if left[1] * right[1] < 0.0:
            brackets.append((left, right))

    if exact:
        chosen = min(exact, key=lambda point: abs(point[0] - uncoupled_guess))
        return chosen[0], chosen[2], 0
    if not brackets:
        if not valid:
            raise PhysicsContractError(
                "no positive stage-2 field exists in the coupled search interval"
            )
        closest = min(valid, key=lambda point: abs(point[1]))
        raise PhysicsContractError(
            "no coupled second-order root was bracketed; closest residual="
            f"{closest[1]:.6e} at stage1_drop={closest[0]:.9g} V"
        )

    left, right = min(
        brackets,
        key=lambda pair: abs(0.5 * (pair[0][0] + pair[1][0]) - uncoupled_guess),
    )
    lo, f_lo = left[0], left[1]
    hi = right[0]
    field2 = left[2]
    for iteration in range(1, bisection_iterations + 1):
        mid = 0.5 * (lo + hi)
        candidate = _candidate_from_stage1_drop(
            mid,
            nominal_energy_v,
            stage1_length_mm,
            total_field_free_length_mm,
            accelerator_first,
            accelerator_second,
        )
        if candidate is None:
            raise ArithmeticError("valid root bracket produced an invalid midpoint")
        f_mid, field2 = candidate
        if abs(hi - lo) <= 1.0e-12 * nominal_energy_v:
            return mid, field2, iteration
        if f_lo * f_mid <= 0.0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    root = 0.5 * (lo + hi)
    final_candidate = _candidate_from_stage1_drop(
        root,
        nominal_energy_v,
        stage1_length_mm,
        total_field_free_length_mm,
        accelerator_first,
        accelerator_second,
    )
    if final_candidate is None:
        raise ArithmeticError("final coupled root is not physically valid")
    return root, final_candidate[1], bisection_iterations


def solve_coupled_reflectron_fields(
    accelerator: AcceleratorState,
    stage1_length_mm: float,
    upstream_from_accelerator_focus_mm: float,
    downstream_to_detector_mm: float,
    *,
    energy_min_v: float | None = None,
    energy_max_v: float | None = None,
    stage2_margin_fraction: float = 0.0,
    stage2_margin_mm: float = 0.0,
    require_accelerator_focus: bool = True,
) -> CoupledReflectronSolution:
    """Solve global first- and second-order conditions for the coupled 1D system."""

    d1 = _finite_float(stage1_length_mm, "stage1_length_mm")
    upstream = _finite_float(
        upstream_from_accelerator_focus_mm,
        "upstream_from_accelerator_focus_mm",
    )
    downstream = _finite_float(
        downstream_to_detector_mm, "downstream_to_detector_mm"
    )
    _positive(d1, "stage1_length_mm")
    if upstream < 0.0 or downstream < 0.0:
        raise PhysicsContractError("field-free path lengths must be >= 0")
    total_length = upstream + downstream
    _positive(total_length, "total_field_free_length_mm")

    w0 = accelerator.nominal_energy_per_charge_v
    w_min = w0 if energy_min_v is None else _finite_float(energy_min_v, "energy_min_v")
    w_max = w0 if energy_max_v is None else _finite_float(energy_max_v, "energy_max_v")
    if not accelerator.intermediate_relative_v < w_min <= w0 <= w_max:
        raise PhysicsContractError(
            "energy envelope must remain above the accelerator intermediate potential"
        )

    acc_first, acc_second, acc_third = accelerator_normalized_derivatives_at_focus(
        w0, accelerator
    )
    focus_scale = max(
        1.0,
        abs(1.0 / (accelerator.field1_v_per_mm * math.sqrt(w0 - accelerator.intermediate_relative_v))),
    )
    if require_accelerator_focus and abs(acc_first) > 1.0e-10 * focus_scale:
        raise PhysicsContractError(
            "accelerator plane is not its first-order time focus; L_up cannot use the "
            "focus-plane semantic"
        )

    u1, field2, iterations = _find_coupled_root(
        w0,
        d1,
        total_length,
        w_min,
        acc_first,
        acc_second,
    )
    field1 = u1 / d1
    low_reaches = w_min > u1
    if not low_reaches:
        raise PhysicsContractError(
            "low-energy tail turns in reflectron stage 1; two-stage coupled model invalid"
        )

    margin_fraction = _finite_float(
        stage2_margin_fraction, "stage2_margin_fraction"
    )
    margin_mm = _finite_float(stage2_margin_mm, "stage2_margin_mm")
    if margin_fraction < 0.0 or margin_mm < 0.0:
        raise PhysicsContractError("stage-2 margins must be >= 0")
    nominal_penetration = (w0 - u1) / field2
    required_depth = (w_max - u1) / field2 * (1.0 + margin_fraction) + margin_mm

    ref_first, ref_second = reflectron_normalized_derivatives(
        w0, total_length, u1, field1, field2
    )
    total_first = acc_first + ref_first
    total_second = acc_second + ref_second
    total_third = acc_third + reflectron_normalized_third_derivative(
        w0, total_length, u1, field1, field2
    )
    remaining = w0 - u1
    second_scale = max(
        abs(acc_second),
        abs(3.0 * total_length / (4.0 * w0**2.5)),
        abs((-1.0 / w0**1.5 + 1.0 / remaining**1.5) / field1),
        abs(1.0 / (field2 * remaining**1.5)),
        1.0e-30,
    )
    if abs(total_second) > 1.0e-9 * second_scale:
        raise ArithmeticError(
            "coupled root failed the scale-aware second-order residual check"
        )

    return CoupledReflectronSolution(
        nominal_energy_per_charge_v=w0,
        upstream_from_accelerator_focus_mm=upstream,
        downstream_to_detector_mm=downstream,
        total_field_free_length_mm=total_length,
        stage1_length_mm=d1,
        stage1_voltage_drop_v=u1,
        stage1_field_v_per_mm=field1,
        stage2_field_v_per_mm=field2,
        nominal_stage2_penetration_mm=nominal_penetration,
        required_stage2_depth_mm=required_depth,
        energy_min_v=w_min,
        energy_max_v=w_max,
        low_energy_reaches_stage2=low_reaches,
        accelerator_first_derivative_at_focus=acc_first,
        accelerator_second_derivative_at_focus=acc_second,
        accelerator_third_derivative_at_focus=acc_third,
        total_first_derivative_residual=total_first,
        total_second_derivative_residual=total_second,
        total_third_derivative=total_third,
        root_iterations=iterations,
    )


def source_position_samples(
    accelerator: AcceleratorState,
    coupled: CoupledReflectronSolution,
    mass_to_charge_th: float,
    source_full_width_mm: float,
    sample_count: int,
) -> list[dict[str, float | int]]:
    """Sample the source-position family and return release-to-detector times."""

    mu = _finite_float(mass_to_charge_th, "mass_to_charge_th")
    _positive(mu, "mass_to_charge_th")
    width = _finite_float(source_full_width_mm, "source_full_width_mm")
    if width < 0.0:
        raise PhysicsContractError("source_full_width_mm must be >= 0")
    sample_count = _as_int(sample_count, "sample_count", minimum=1)
    x_center = accelerator.release_position_mm
    x_min = x_center - width / 2.0
    x_max = x_center + width / 2.0
    if not 0.0 < x_min <= x_max < accelerator.gap1_mm:
        raise PhysicsContractError("source distribution does not fit inside gap 1")

    rows: list[dict[str, float | int]] = []
    for index in range(sample_count):
        fraction = 0.5 if sample_count == 1 else index / (sample_count - 1)
        x = x_min + fraction * (x_max - x_min)
        energy = accelerator.repeller_relative_v - accelerator.field1_v_per_mm * x
        tau_acc = accelerator_normalized_time_to_focus(energy, accelerator)
        tau_total = coupled_normalized_flight_time_mm_sqrt_v(
            energy,
            accelerator,
            coupled.upstream_from_accelerator_focus_mm,
            coupled.downstream_to_detector_mm,
            coupled.stage1_voltage_drop_v,
            coupled.stage1_field_v_per_mm,
            coupled.stage2_field_v_per_mm,
        )
        mass_over_charge_si = (
            mu * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C
        )
        factor = 1.0e-3 * math.sqrt(mass_over_charge_si / 2.0)
        rows.append(
            {
                "sample_index": index,
                "release_position_mm": x,
                "energy_per_charge_V": energy,
                "accelerator_focus_time_s": factor * tau_acc,
                "detector_arrival_time_s": factor * tau_total,
            }
        )
    return rows


def _sample_summary(
    rows: Sequence[Mapping[str, float | int]],
) -> dict[str, float | int | bool]:
    times = [float(row["detector_arrival_time_s"]) for row in rows]
    mean = sum(times) / len(times)
    variance = sum((value - mean) ** 2 for value in times) / len(times)
    return {
        "sample_count": len(times),
        "arrival_time_min_s": min(times),
        "arrival_time_max_s": max(times),
        "arrival_time_span_s": max(times) - min(times),
        "arrival_time_mean_s": mean,
        "arrival_time_rms_about_mean_s": math.sqrt(variance),
        "formal_FWHM_eligible": False,
    }


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    raise PhysicsContractError(f"missing required key; expected one of {keys}")


def derive(
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, float | int]]]:
    """Derive a coupled design and optional deterministic source samples."""

    design = contract["design"]
    acc = design["oa_accelerator"]
    acc_geometry = acc["local_geometry_mm"]
    acc_voltage = acc["electrodes_V"]
    gap1 = float(_first(acc_geometry, "gap1", "d1"))
    gap2 = float(_first(acc_geometry, "gap2", "d2"))
    release_position = acc_geometry.get("release_position")
    if release_position is None:
        release_position = float(acc.get("release_center_fraction", 0.5)) * gap1
    accelerator = accelerator_state(
        float(_first(acc_voltage, "repeller", "u1")),
        float(_first(acc_voltage, "grid1", "intermediate", "u2")),
        gap1,
        gap2,
        exit_v=float(acc_voltage.get("exit", acc_voltage.get("grid2", 0.0))),
        release_position_mm=float(release_position),
        require_downstream_focus=True,
        zero_tolerance_mm=(
            None
            if "focus_zero_tolerance_mm" not in acc
            else float(acc["focus_zero_tolerance_mm"])
        ),
    )

    layout = design["layout_mm"]
    upstream = float(
        _first(
            layout,
            "upstream_from_accelerator_focus",
            "L_up_from_accelerator_focus",
        )
    )
    downstream = float(
        _first(layout, "downstream_to_detector", "L_down_to_detector")
    )

    reflectron = design["reflectron"]
    stage1_length = float(
        _first(reflectron, "stage1_length", "stage1_length_mm", "d1")
    )
    source = design.get("source", {})
    source_width = float(source.get("release_full_width_mm", 0.0))
    intrinsic_half_range = float(
        source.get("intrinsic_energy_per_charge_half_range_V", 0.0)
    )
    spatial_half_range = accelerator.field1_v_per_mm * source_width / 2.0
    energy_min = (
        accelerator.nominal_energy_per_charge_v
        - spatial_half_range
        - intrinsic_half_range
    )
    energy_max = (
        accelerator.nominal_energy_per_charge_v
        + spatial_half_range
        + intrinsic_half_range
    )
    margin = reflectron.get("stage2_margin", {})
    coupled = solve_coupled_reflectron_fields(
        accelerator,
        stage1_length,
        upstream,
        downstream,
        energy_min_v=energy_min,
        energy_max_v=energy_max,
        stage2_margin_fraction=float(margin.get("fraction", 0.0)),
        stage2_margin_mm=float(margin.get("absolute_mm", 0.0)),
    )

    translation = float(acc.get("assembly_translation_z_mm", 0.0))
    exit_local = gap1 + gap2
    focus_local = exit_local + accelerator.first_order_focus_drift_mm
    focus_global = translation + focus_local
    result: dict[str, Any] = {
        "model_id": "oatof.oaaccelerator_reflectron_coupled.ideal_1d.v1",
        "length_unit": "mm",
        "potential_unit": "V",
        "energy_per_charge_unit": "V",
        "L_up_definition": (
            "oaaccelerator first-order time-focus plane to reflectron entrance"
        ),
        "accelerator": {
            **asdict(accelerator),
            "accelerator_exit_local_z_mm": exit_local,
            "accelerator_focus_local_z_mm": focus_local,
            "accelerator_focus_global_z_mm": focus_global,
        },
        "source_energy_envelope": {
            "release_full_width_mm": source_width,
            "spatial_energy_half_range_V": spatial_half_range,
            "intrinsic_energy_per_charge_half_range_V": intrinsic_half_range,
            "energy_min_V": energy_min,
            "energy_max_V": energy_max,
            "timing_model_covers_intrinsic_energy_spread": False,
        },
        "coupled_reflectron": asdict(coupled),
        "formal_FWHM_eligible": False,
        "formal_use_requires": [
            "frozen particle table including independent energy and time spread",
            "shared repository FWHM post-processor",
            "COMSOL/SIMION cross-solver validation",
            "3D field, fringe-field, grid-transparency and detector-plane checks",
        ],
    }

    stage2_length = reflectron.get(
        "stage2_length", reflectron.get("stage2_length_mm")
    )
    if stage2_length is not None:
        actual = float(stage2_length)
        result["coupled_reflectron"]["stage2_length_mm"] = actual
        result["coupled_reflectron"]["stage2_depth_margin_mm"] = (
            actual - coupled.required_stage2_depth_mm
        )
        result["coupled_reflectron"]["stage2_depth_pass"] = (
            actual >= coupled.required_stage2_depth_mm
        )
        if bool(design.get("enforce_stage2_depth", True)) and not result[
            "coupled_reflectron"
        ]["stage2_depth_pass"]:
            raise PhysicsContractError(
                "configured reflectron stage2 length is below the required envelope depth"
            )

    rows: list[dict[str, float | int]] = []
    particle = contract.get("particle", {})
    sample_count = _as_int(source.get("sample_count", 0), "sample_count", minimum=0)
    if "mass_to_charge_Th" in particle:
        mu = float(particle["mass_to_charge_Th"])
        result["nominal_release_to_detector_time_s"] = coupled_flight_time_s(
            accelerator.nominal_energy_per_charge_v,
            mu,
            accelerator,
            upstream,
            downstream,
            coupled.stage1_voltage_drop_v,
            coupled.stage1_field_v_per_mm,
            coupled.stage2_field_v_per_mm,
        )
        if sample_count > 0:
            rows = source_position_samples(
                accelerator, coupled, mu, source_width, sample_count
            )
            result["source_position_sample_summary"] = _sample_summary(rows)
    return result, rows


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
                actual[key], value, f"{path}.{key}", abs_tol=abs_tol, rel_tol=rel_tol
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


def _write_csv(path: Path, rows: Sequence[Mapping[str, float | int]]) -> None:
    if not rows:
        raise PhysicsContractError("no sample rows were generated")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run_self_test() -> None:
    bound = compact_exit_focus_bound(4000.0, 20.0, 1.0, 3.0)
    accelerator = accelerator_state(
        bound["repeller_relative_V"],
        bound["intermediate_relative_V"],
        bound["gap1_mm"],
        bound["gap2_mm"],
        require_downstream_focus=True,
    )
    coupled = solve_coupled_reflectron_fields(
        accelerator,
        50.0,
        600.0,
        400.0,
        energy_min_v=3980.0,
        energy_max_v=4020.0,
        stage2_margin_fraction=0.2,
    )
    if abs(coupled.total_first_derivative_residual) > 1.0e-12:
        raise AssertionError("coupled first-order condition failed")
    if abs(coupled.total_second_derivative_residual) > 1.0e-12:
        raise AssertionError("coupled second-order condition failed")
    if not coupled.stage1_voltage_drop_v < coupled.energy_min_v:
        raise AssertionError("coupled low-energy envelope is invalid")

    uncoupled = solve_reflectron_fields(
        accelerator.nominal_energy_per_charge_v,
        50.0,
        upstream_from_accelerator_focus_mm=600.0,
        downstream_to_detector_mm=400.0,
        energy_min_v=3980.0,
        energy_max_v=4020.0,
    )
    _, accelerator_second, _ = accelerator_normalized_derivatives_at_focus(
        accelerator.nominal_energy_per_charge_v, accelerator
    )
    _, uncoupled_ref_second = reflectron_normalized_derivatives(
        accelerator.nominal_energy_per_charge_v,
        uncoupled.total_field_free_length_mm,
        uncoupled.stage1_voltage_drop_v,
        uncoupled.stage1_field_v_per_mm,
        uncoupled.stage2_field_v_per_mm,
    )
    if not math.isclose(
        accelerator_second + uncoupled_ref_second,
        accelerator_second,
        rel_tol=1.0e-12,
        abs_tol=1.0e-15,
    ):
        raise AssertionError("uncoupled second-order comparison failed")
    if math.isclose(
        coupled.stage1_voltage_drop_v,
        uncoupled.stage1_voltage_drop_v,
        rel_tol=1.0e-6,
        abs_tol=1.0e-6,
    ):
        raise AssertionError("coupled solver did not respond to accelerator curvature")

    rows = source_position_samples(accelerator, coupled, 100.0, 1.0, 11)
    if len(rows) != 11:
        raise AssertionError("source sampling failed")
    t100 = coupled_flight_time_s(
        accelerator.nominal_energy_per_charge_v,
        100.0,
        accelerator,
        600.0,
        400.0,
        coupled.stage1_voltage_drop_v,
        coupled.stage1_field_v_per_mm,
        coupled.stage2_field_v_per_mm,
    )
    t400 = coupled_flight_time_s(
        accelerator.nominal_energy_per_charge_v,
        400.0,
        accelerator,
        600.0,
        400.0,
        coupled.stage1_voltage_drop_v,
        coupled.stage1_field_v_per_mm,
        coupled.stage2_field_v_per_mm,
    )
    if not math.isclose(t400 / t100, 2.0, rel_tol=1.0e-12):
        raise AssertionError("coupled mass-to-charge scaling failed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Solve the coupled oa-accelerator / dual-stage-reflectron model."
    )
    parser.add_argument("contract", type=Path, nargs="?")
    parser.add_argument("--write-derived", type=Path)
    parser.add_argument("--write-samples", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print("OATOF_OAACCELERATOR_COUPLING_SELF_TEST=PASS")
        if args.contract is None:
            return 0
    if args.contract is None:
        parser.error("contract is required unless --self-test is used")

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result, rows = derive(contract)
    tolerance = contract.get("expected_tolerance", {})
    _assert_expected(
        result,
        contract.get("expected_derived", {}),
        "expected_derived",
        abs_tol=float(tolerance.get("absolute", 1.0e-10)),
        rel_tol=float(tolerance.get("relative", 1.0e-12)),
    )

    if args.write_samples:
        _write_csv(args.write_samples, rows)
        result["source_position_samples_csv"] = str(args.write_samples)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.write_derived:
        args.write_derived.parent.mkdir(parents=True, exist_ok=True)
        args.write_derived.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("OATOF_OAACCELERATOR_COUPLING_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
