"""Common-clock OA triggering from actual-field reference rays, without detector selection.

Reference rays are a separate calibration experiment, never replacements for
the original mother population. Both pressure arms consume the same decision.
"""
from __future__ import annotations

import math
from typing import Any


POLICY_ID = "actual_field_reference_exit_centering_v1"


def propose_common_pulse(
    trials: list[dict[str, Any]], *, target_y_mm: float, release_start_us: float,
) -> dict[str, Any]:
    """Bracket an exit-centering time using native reference exits.

    Input records carry ``pulse_time_us``, ``exit_y_mm``, ``exit_time_us`` and
    ``evidence``. A proposal between two trials requires a new native check;
    interpolation is not presented as a verified flight or a population focus.
    No losses or detector results from either N=100 arm participate.
    """
    if not math.isfinite(target_y_mm) or not math.isfinite(release_start_us):
        raise ValueError("finite target position and release clock required")
    if not trials:
        raise ValueError("native reference trials required")
    for row in trials:
        if row.get("status") == "no_unique_exit" or not {"pulse_time_us", "exit_y_mm", "exit_time_us"}.issubset(row):
            raise ValueError("native reference trial has no unique measured exit; calibration cannot propose a pulse")
    ordered = sorted(trials, key=lambda r: r["pulse_time_us"])
    clocks = []
    for row in ordered:
        values = [float(row[k]) for k in ("pulse_time_us", "exit_y_mm", "exit_time_us")]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("nonfinite native reference state")
        pulse, _, exit_time = values
        if pulse < release_start_us or exit_time <= pulse:
            raise ValueError("reference clocks must preserve release < pulse < exit")
        if not row.get("evidence"):
            raise ValueError("reference trial lacks frozen native evidence")
        clocks.append(pulse)
    if len(set(clocks)) != len(clocks):
        raise ValueError("duplicate reference pulse clock")
    exact = next((r for r in ordered if float(r["exit_y_mm"]) == target_y_mm), None)
    base = dict(policy_id=POLICY_ID, target_y_mm=target_y_mm,
                release_start_us=release_start_us,
                pressure_arms_share_clock=True,
                selection_uses_mother_terminal_outcome=False,
                scope="Reference-ray centering only; not population time/space-focus qualification")
    if exact is not None:
        return dict(base, proposal_time_us=float(exact["pulse_time_us"]),
                    proposal_basis="recorded_reference_exit_at_target",
                    native_check_required=False, reference_trials=[exact])
    brackets = [(a, b) for a, b in zip(ordered, ordered[1:])
                if (float(a["exit_y_mm"])-target_y_mm)*(float(b["exit_y_mm"])-target_y_mm) < 0]
    if not brackets:
        raise ValueError("native reference exits do not bracket the target; extrapolation is forbidden")
    # A narrower observed bracket limits interpolation; it does not establish
    # a field or trajectory error bound. RF can make the response nonmonotonic.
    a, b = min(brackets, key=lambda pair: pair[1]["pulse_time_us"]-pair[0]["pulse_time_us"])
    fraction = (target_y_mm-a["exit_y_mm"])/(b["exit_y_mm"]-a["exit_y_mm"])
    proposal = a["pulse_time_us"] + fraction*(b["pulse_time_us"]-a["pulse_time_us"])
    return dict(base, proposal_time_us=proposal,
                proposal_basis="bracketed_native_reference_secant",
                native_check_required=True, reference_trials=[a, b])


def freeze_common_pulse_decision(
    verified_trial: dict[str, Any], *, target_y_mm: float, release_start_us: float,
    field_identity: dict[str, Any],
    voltage_calibration: dict[str, float],
) -> dict[str, Any]:
    """Bind the measured reference residual and one common physical flight clock.

    A finite residual is reported, never silently accepted against a new
    performance threshold. Solver and field evidence are caller-owned.
    """
    propose_common_pulse([verified_trial], target_y_mm=float(verified_trial["exit_y_mm"]),
                         release_start_us=release_start_us)
    if not field_identity or not math.isfinite(target_y_mm):
        raise ValueError("frozen field identity and finite target required")
    if set(voltage_calibration) != {"inner_correction_v", "release_hp_common_correction_v"} or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in voltage_calibration.values()
    ):
        raise ValueError("explicit finite actual-field voltage controls required")
    return dict(schema_version=1, role="actual_field_reference_exit_centering",
                policy_id=POLICY_ID,
                actual_pulse_time_us=float(verified_trial["pulse_time_us"]),
                release_start_us=release_start_us, target_y_mm=target_y_mm,
                reference_exit_y_mm=float(verified_trial["exit_y_mm"]),
                reference_centering_residual_mm=float(verified_trial["exit_y_mm"])-target_y_mm,
                reference_evidence=verified_trial["evidence"], field_identity=field_identity,
                voltage_calibration=dict(voltage_calibration),
                pressure_arms_share_clock=True,
                selection_uses_mother_terminal_outcome=False,
                qualification="Reference centering diagnostic; population widths and losses remain to be measured")
