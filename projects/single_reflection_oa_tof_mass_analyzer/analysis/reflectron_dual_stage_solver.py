"""Solver-independent ideal dual-stage reflectron reference.

The model is one-dimensional, piecewise uniform, and uses energy per charge in volts,
lengths in millimetres, and fields in volts per millimetre.  The effective upstream
field-free length starts at the oa-accelerator first-order time-focus plane.

This module deliberately does not promote a cubic endpoint estimate to a formal FWHM.
It can emit deterministic arrival-time samples for the repository's shared FWHM
post-processor.
"""

from __future__ import annotations

from msplatform.components.single_reflection_oa_tof.reflectron_dual_stage_solver import (
    PhysicsContractError as PhysicsContractError,
    ReflectronSolution as ReflectronSolution,
    _finite_float as _finite_float,
    _positive as _positive,
    normalized_flight_time_mm_sqrt_v as normalized_flight_time_mm_sqrt_v,
    flight_time_s as flight_time_s,
    normalized_derivatives as normalized_derivatives,
    normalized_third_derivative as normalized_third_derivative,
    solve_reflectron_fields as solve_reflectron_fields,
    _solve_linear_system as _solve_linear_system,
    finite_difference_derivative as finite_difference_derivative,
    energy_aberration_diagnostics as energy_aberration_diagnostics,
    arrival_time_samples as arrival_time_samples,
    _mapping_value as _mapping_value,
    derive as derive,
)

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


def _assert_expected(
    actual: Any, expected: Any, path: str, *, abs_tol: float, rel_tol: float
) -> None:
    from common.contracts.expected_values import assert_expected_values

    assert_expected_values(
        actual, expected, path, abs_tol=abs_tol, rel_tol=rel_tol,
    )


def _write_samples_csv(
    path: Path, rows: Sequence[Mapping[str, float | int]]
) -> None:
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
