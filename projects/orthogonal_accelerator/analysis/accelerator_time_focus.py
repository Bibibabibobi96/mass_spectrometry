"""Solver-independent reference for a two-region orthogonal space-focusing accelerator.

This module owns the ideal one-dimensional Wiley--McLaren-type accelerator
reference used by instrument consumers. Lengths are millimetres and electrode
potentials are volts. The default release position is the centre of gap 1.

The reference quantity is the first-order time-focus plane.  Its distance ``D`` is
measured from the grounded accelerator exit plane; it is not required to coincide
with that plane.  Mass-to-charge cancels from the focus-position equation.

The command-line interface remains compatible with the historical project contract
shape while adding explicit units, focus feasibility, and provenance-friendly output.
"""

from __future__ import annotations

from msplatform.components.orthogonal_accelerator.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG as ATOMIC_MASS_CONSTANT_KG,
    PhysicsContractError as PhysicsContractError,
    AcceleratorState as AcceleratorState,
    FixedEnergyGap1FocusSensitivity as FixedEnergyGap1FocusSensitivity,
    PhaseSpaceMatchedVoltagePair as PhaseSpaceMatchedVoltagePair,
    FiniteIntervalMatchedVoltagePair as FiniteIntervalMatchedVoltagePair,
    FixedPlaneFiniteIntervalTiming as FixedPlaneFiniteIntervalTiming,
    LinearPhaseSpaceTimingCoefficients as LinearPhaseSpaceTimingCoefficients,
    _as_finite_float as _as_finite_float,
    _require_positive as _require_positive,
    _as_nonnegative_int as _as_nonnegative_int,
    _relative_potentials as _relative_potentials,
    accelerator_state as accelerator_state,
    focus_drift_mm as focus_drift_mm,
    fixed_energy_gap1_focus_sensitivity as fixed_energy_gap1_focus_sensitivity,
    normalized_time_to_plane_mm_sqrt_v as normalized_time_to_plane_mm_sqrt_v,
    time_to_plane_s as time_to_plane_s,
    time_to_fixed_plane_s as time_to_fixed_plane_s,
    fixed_plane_finite_interval_timing as fixed_plane_finite_interval_timing,
    match_finite_phase_space_interval as match_finite_phase_space_interval,
    linear_phase_space_timing_coefficients as linear_phase_space_timing_coefficients,
    match_phase_space_voltage_pair as match_phase_space_voltage_pair,
    compact_exit_focus_bound as compact_exit_focus_bound,
    _first_present as _first_present,
    _derive_reference_focus as _derive_reference_focus,
    derive as derive,
)

import argparse
import json
import math
from pathlib import Path
from typing import Any

from msplatform.contracts.particle_physics import (
    ELEMENTARY_CHARGE_C as _ELEMENTARY_CHARGE_C,
)

# Retained as a public module constant for the three-zone ideal-theory API.
ELEMENTARY_CHARGE_C = _ELEMENTARY_CHARGE_C


def _assert_expected(
    actual: Any, expected: Any, path: str, *, abs_tol: float, rel_tol: float
) -> None:
    from common.contracts.expected_values import assert_expected_values

    assert_expected_values(
        actual, expected, path, abs_tol=abs_tol, rel_tol=rel_tol,
        sequence_length_message="actual length={actual} expected={expected}",
    )


def run_self_test() -> None:
    """Run deterministic algebra and compatibility checks."""

    # Historical centred-source expression.
    u1, u2, d1, d2 = 4060.0, 3940.0, 3.0, 112.247459
    e1 = (u1 - u2) / d1
    e2 = u2 / d2
    v2 = math.sqrt(u1 - u2)
    v3 = math.sqrt(u1 + u2)
    historical = (v3**3 / e1) * (
        1.0 / v2 + (e1 / e2) * (1.0 / v3 - 1.0 / v2)
    )
    current = focus_drift_mm(u1, u2, d1, d2, require_downstream_focus=False)
    if not math.isclose(current, historical, rel_tol=0.0, abs_tol=1.0e-12):
        raise AssertionError("historical centred-source formula changed")

    # Equal fields reduce to D = 2 * (distance from release point to exit).
    equal_state = accelerator_state(30.0, 20.0, 10.0, 20.0)
    expected_equal = 2.0 * (10.0 + 20.0 - 5.0)
    if not math.isclose(
        equal_state.first_order_focus_drift_mm,
        expected_equal,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise AssertionError("equal-field degeneration failed")

    # Closed-form D=0 bound, including an active mechanical lower gap.
    bound = compact_exit_focus_bound(4000.0, 20.0, 1.0, 3.0)
    state = accelerator_state(
        bound["repeller_relative_V"],
        bound["intermediate_relative_V"],
        bound["gap1_mm"],
        bound["gap2_mm"],
        require_downstream_focus=False,
    )
    if abs(state.first_order_focus_drift_mm) > 1.0e-9:
        raise AssertionError("compact D=0 bound does not focus at exit")
    expected_total = 0.5 * (200.0 + 6.0 + math.sqrt(600.0))
    if not math.isclose(
        bound["compact_accelerator_length_mm"],
        expected_total,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise AssertionError("general closed-form compactness bound failed")

    # Physical time must scale as sqrt(m/z).
    tau_args = (
        state.nominal_energy_per_charge_v,
        state.intermediate_relative_v,
        state.field1_v_per_mm,
        state.field2_v_per_mm,
        state.first_order_focus_drift_mm,
    )
    t100 = time_to_plane_s(tau_args[0], 100.0, *tau_args[1:])
    t400 = time_to_plane_s(tau_args[0], 400.0, *tau_args[1:])
    if not math.isclose(t400 / t100, 2.0, rel_tol=1.0e-12):
        raise AssertionError("mass-to-charge time scaling failed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive an ideal two-region orthogonal accelerator time focus."
    )
    parser.add_argument("contract", type=Path, nargs="?")
    parser.add_argument("--write-derived", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print("ACCELERATOR_TIME_FOCUS_SELF_TEST=PASS")
        if args.contract is None:
            return 0
    if args.contract is None:
        parser.error("contract is required unless --self-test is used")

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = derive(contract)
    tolerance = contract.get("expected_tolerance", {})
    abs_tol = float(tolerance.get("absolute", 1.0e-10))
    rel_tol = float(tolerance.get("relative", 1.0e-12))
    expected = contract.get("expected_derived", {})
    _assert_expected(
        result,
        expected,
        "expected_derived",
        abs_tol=abs_tol,
        rel_tol=rel_tol,
    )

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.write_derived:
        args.write_derived.parent.mkdir(parents=True, exist_ok=True)
        args.write_derived.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("ACCELERATOR_TIME_FOCUS_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
