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

from msplatform.components.single_reflection_oa_tof.oatof_oaaccelerator_coupling import (
    CoupledReflectronSolution as CoupledReflectronSolution,
    _finite_float as _finite_float,
    _positive as _positive,
    _as_int as _as_int,
    accelerator_normalized_time_to_focus as accelerator_normalized_time_to_focus,
    accelerator_normalized_derivatives_at_focus as accelerator_normalized_derivatives_at_focus,
    coupled_normalized_flight_time_mm_sqrt_v as coupled_normalized_flight_time_mm_sqrt_v,
    coupled_flight_time_s as coupled_flight_time_s,
    _candidate_from_stage1_drop as _candidate_from_stage1_drop,
    _find_coupled_root as _find_coupled_root,
    solve_coupled_reflectron_from_accelerator_derivatives as solve_coupled_reflectron_from_accelerator_derivatives,
    solve_coupled_reflectron_fields as solve_coupled_reflectron_fields,
    source_position_samples as source_position_samples,
    _sample_summary as _sample_summary,
    _first as _first,
    derive as derive,
)

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    PhysicsContractError,
    accelerator_state,
    compact_exit_focus_bound,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.reflectron_dual_stage_solver import (
    normalized_derivatives as reflectron_normalized_derivatives,
    solve_reflectron_fields,
)


def _assert_expected(
    actual: Any, expected: Any, path: str, *, abs_tol: float, rel_tol: float
) -> None:
    from common.contracts.expected_values import assert_expected_values

    assert_expected_values(
        actual, expected, path, abs_tol=abs_tol, rel_tol=rel_tol,
    )


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
