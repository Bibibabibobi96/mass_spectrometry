"""Solver- and instrument-neutral ideal theory for a two-zone OA accelerator.

This module owns only the one-dimensional uniform-field time-focus equation.
It deliberately has no CAD frame, source placement, voltages from a particular
instrument, or SIMION/COMSOL syntax.  Each consuming project supplies those
values through its own frozen contract and applies its own rigid placement.
"""
from __future__ import annotations

from dataclasses import dataclass
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    PhysicsContractError,
    accelerator_state,
)


class TwoZoneTheoryError(ValueError):
    """Raised when an ideal two-zone accelerator state is not physical."""


@dataclass(frozen=True)
class TwoZoneTimeFocus:
    """Ideal fields, release energy, and focus distance beyond the exit plane."""

    field_1_v_per_mm: float
    field_2_v_per_mm: float
    energy_per_charge_v: float
    focus_after_exit_mm: float


def derive_two_zone_time_focus(
    *, repeller_v: float, intermediate_v: float, exit_v: float,
    gap_1_mm: float, gap_2_mm: float, release_position_in_gap_1_mm: float,
) -> TwoZoneTimeFocus:
    """Return the first-order focus of two uniform accelerating fields.

    Potentials are expressed in volts, lengths in millimetres, and the release
    coordinate is measured from the repeller into the first gap.  The returned
    focus distance is measured beyond the grounded/reference exit plane.  No
    device-coordinate placement is implied by this result.
    """
    try:
        state = accelerator_state(
            repeller_v, intermediate_v, gap_1_mm, gap_2_mm,
            exit_v=exit_v,
            release_position_mm=release_position_in_gap_1_mm,
            zero_tolerance_mm=0.0,
        )
    except PhysicsContractError as error:
        raise TwoZoneTheoryError(str(error)) from error
    return TwoZoneTimeFocus(
        state.field1_v_per_mm,
        state.field2_v_per_mm,
        state.nominal_energy_per_charge_v,
        state.first_order_focus_drift_mm,
    )
