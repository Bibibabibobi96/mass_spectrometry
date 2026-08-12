"""Build and analyze detector-blind, dense pre-pulse SIMION observations.

The generated Lua wrapper holds the oaTOF accelerator at its pre-pulse
potential, preserves the upstream time-varying RF field, samples exact global
instrument times, and terminates before downstream oaTOF transport.  Candidate
times are ranked only from pulse eligibility and the Arm 8 analytic map.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
    accelerator_state,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import (
    solve_coupled_reflectron_fields,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_peak_metrics,
)


STATE_PATTERN = re.compile(
    r"TRACE: pulse_window_state particle_id=(?P<particle_id>\d+) "
    r"sample_index=(?P<sample_index>\d+) instrument_time_us=(?P<time>[-+\d.eE]+) "
    r"x_mm=(?P<x>[-+\d.eE]+) y_mm=(?P<y>[-+\d.eE]+) "
    r"z_mm=(?P<z>[-+\d.eE]+) vx_mm_per_us=(?P<vx>[-+\d.eE]+) "
    r"vy_mm_per_us=(?P<vy>[-+\d.eE]+) vz_mm_per_us=(?P<vz>[-+\d.eE]+) "
    r"alive=(?P<alive>[01]) instance=(?P<instance>-?\d+)"
)
TERMINAL_PATTERN = re.compile(
    r"TRACE: pulse_window_terminal particle_id=(?P<particle_id>\d+) "
    r"instrument_time_us=(?P<time>[-+\d.eE]+) reason=(?P<reason>[a-z_]+) "
    r"instance=(?P<instance>-?\d+)"
)


@dataclass(frozen=True)
class ObservationState:
    """One exact alive-state record in canonical SIMION mm/us units."""

    particle_id: int
    sample_index: int
    instrument_time_us: float
    x_mm: float
    y_mm: float
    z_mm: float
    vx_mm_per_us: float
    vy_mm_per_us: float
    vz_mm_per_us: float
    alive: int
    instance: int


def predeclared_times_us(
    pulse_effective_time_us: float,
    *,
    half_width_us: float = 0.5,
    interval_count: int = 180,
) -> tuple[float, ...]:
    """Return a symmetric schedule containing both endpoints and the centre."""

    if not math.isfinite(pulse_effective_time_us):
        raise ValueError("pulse_effective_time_us must be finite")
    if half_width_us <= 0 or interval_count <= 0 or interval_count % 2:
        raise ValueError("half width must be positive and interval_count positive/even")
    step = 2.0 * half_width_us / interval_count
    if step * 1.0e3 > 5.68 + 1.0e-12:
        raise ValueError("pulse-window sample spacing exceeds 5.68 ns")
    start = pulse_effective_time_us - half_width_us
    return tuple(start + index * step for index in range(interval_count + 1))


def build_lua_extension(times_us: Sequence[float]) -> str:
    """Return a Lua wrapper for exact upstream observations and early stop."""

    times = tuple(float(value) for value in times_us)
    if len(times) < 3 or any(not math.isfinite(value) for value in times):
        raise ValueError("at least three finite observation times are required")
    if any(right <= left for left, right in zip(times, times[1:], strict=False)):
        raise ValueError("observation times must be strictly increasing")
    table = ",\n".join(f"  [{index + 1}]={value:.15g}" for index, value in enumerate(times))
    return f"""
-- BEGIN DETECTOR-BLIND PULSE-WINDOW OBSERVABILITY
local pulse_window_times_us={{
{table}
}}
local pulse_window_next={{}}
local pulse_window_complete={{}}
local pulse_window_base_initialize_run=segment.initialize_run
local pulse_window_base_initialize=segment.initialize
local pulse_window_base_tstep_adjust=segment.tstep_adjust
local pulse_window_base_other_actions=segment.other_actions
local pulse_window_base_terminate=segment.terminate
function segment.initialize_run()
  handoff_pulse_mode=2
  single_flight_terminate_after_pulse=0
  pulse_window_base_initialize_run()
  pulse_window_next={{}}; pulse_window_complete={{}}
  print(string.format('TRACE: pulse_window_contract detector_blind=1 accelerator_held_off=1 sample_count=%d start_us=%.12g center_us=%.12g end_us=%.12g maximum_spacing_ns=%.12g',
    #pulse_window_times_us,pulse_window_times_us[1],pulse_window_times_us[(#pulse_window_times_us+1)/2],pulse_window_times_us[#pulse_window_times_us],
    (pulse_window_times_us[2]-pulse_window_times_us[1])*1000))
end
function segment.initialize()
  pulse_window_base_initialize()
  pulse_window_next[ion_number]=1
end
function segment.tstep_adjust()
  pulse_window_base_tstep_adjust()
  local sample_index=pulse_window_next[ion_number] or 1
  local target=pulse_window_times_us[sample_index]
  if target~=nil then
    local remaining=target-single_flight_instrument_time_us()
    if remaining>1e-12 and ion_time_step>remaining then ion_time_step=remaining end
  end
end
function segment.other_actions()
  pulse_window_base_other_actions()
  local sample_index=pulse_window_next[ion_number] or 1
  local target=pulse_window_times_us[sample_index]
  local now=single_flight_instrument_time_us()
  if target~=nil and math.abs(now-target)<=1e-8 then
    local particle_id=ion_number+single_flight_particle_id_offset
    print(string.format('TRACE: pulse_window_state particle_id=%d sample_index=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g alive=1 instance=%d',
      particle_id,sample_index,now,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_instance))
    sample_index=sample_index+1; pulse_window_next[ion_number]=sample_index
    if sample_index>#pulse_window_times_us then pulse_window_complete[ion_number]=true; ion_splat=1 end
  elseif target~=nil and now>target+1e-8 then
    error('pulse-window exact sample was skipped')
  end
end
function segment.terminate()
  local particle_id=ion_number+single_flight_particle_id_offset
  local now=single_flight_instrument_time_us()
  local reason='native_splat_during_window'
  if pulse_window_complete[ion_number] then reason='window_complete'
  elseif now<pulse_window_times_us[1] then reason='native_splat_before_window' end
  print(string.format('TRACE: pulse_window_terminal particle_id=%d instrument_time_us=%.12g reason=%s instance=%d',
    particle_id,now,reason,ion_instance))
  pulse_window_base_terminate()
end
-- END DETECTOR-BLIND PULSE-WINDOW OBSERVABILITY
""".lstrip()


def parse_observation_log(
    text: str,
    times_us: Sequence[float],
    *,
    launched_count: int,
    time_tolerance_us: float = 1.0e-8,
) -> tuple[list[ObservationState], list[dict[str, Any]]]:
    """Parse exact states and require a complete detector-free terminal census."""

    if any(marker in text for marker in ("TRACE: detector_crossing", "TRACE: detector_hit_entity")):
        raise ValueError("detector outcome appeared in detector-blind observation log")
    states: list[ObservationState] = []
    seen: set[tuple[int, int]] = set()
    terminals: list[dict[str, Any]] = []
    terminal_ids: set[int] = set()
    schedule = tuple(times_us)
    for line in text.splitlines():
        match = STATE_PATTERN.search(line)
        if match:
            values = match.groupdict()
            particle_id = int(values["particle_id"])
            sample_index = int(values["sample_index"])
            key = (particle_id, sample_index)
            if key in seen or not 1 <= particle_id <= launched_count:
                raise ValueError("duplicate or out-of-range pulse-window state identity")
            if not 1 <= sample_index <= len(schedule):
                raise ValueError("pulse-window sample index is outside the schedule")
            actual_time = float(values["time"])
            if abs(actual_time - schedule[sample_index - 1]) > time_tolerance_us:
                raise ValueError("pulse-window state is not at its predeclared exact time")
            seen.add(key)
            states.append(
                ObservationState(
                    particle_id=particle_id,
                    sample_index=sample_index,
                    instrument_time_us=actual_time,
                    x_mm=float(values["x"]), y_mm=float(values["y"]),
                    z_mm=float(values["z"]), vx_mm_per_us=float(values["vx"]),
                    vy_mm_per_us=float(values["vy"]), vz_mm_per_us=float(values["vz"]),
                    alive=int(values["alive"]), instance=int(values["instance"]),
                )
            )
            continue
        match = TERMINAL_PATTERN.search(line)
        if match:
            values = match.groupdict()
            particle_id = int(values["particle_id"])
            if particle_id in terminal_ids:
                raise ValueError("duplicate pulse-window terminal identity")
            terminal_ids.add(particle_id)
            terminals.append(
                {"particle_id": particle_id, "instrument_time_us": float(values["time"]),
                 "reason": values["reason"], "instance": int(values["instance"])}
            )
    if terminal_ids != set(range(1, launched_count + 1)):
        raise ValueError("pulse-window terminal census does not cover every launched particle")
    return states, terminals


def _eligible(row: ObservationState, geometry: Mapping[str, Any]) -> bool:
    dimensions = geometry["geometry_mm"]
    axis_x = float(geometry["coordinate_convention"]["accelerator_axis_x"])
    return (
        float(dimensions["accelerator_repeller_z"]) < row.z_mm
        < float(dimensions["accelerator_grid1_z"])
        and abs(row.x_mm - axis_x) < float(dimensions["accelerator_bore_half"])
        and abs(row.y_mm) < float(dimensions["accelerator_bore_half"])
    )


def _arm8_tof_us(row: ObservationState, resolved: Mapping[str, Any], arm8: Mapping[str, Any]) -> float:
    geometry = resolved["geometry_mm"]
    electrodes = resolved["electrodes_V"]
    derivation = resolved["geometry_derivation"]["accelerator"]
    accelerator = accelerator_state(
        float(electrodes["repeller"]), float(electrodes["grid1"]),
        float(derivation["d1_mm"]), float(derivation["d2_mm"]),
        exit_v=float(electrodes["grid2"]),
    )
    theory = arm8["theory"]
    reflectron = solve_coupled_reflectron_fields(
        accelerator, float(geometry["L_stage1"]), float(geometry["L_flight"]),
        float(geometry["L_flight"]), energy_min_v=float(theory["energy_envelope_min_V"]),
        energy_max_v=float(theory["energy_envelope_max_V"]),
        stage2_margin_fraction=float(theory["reflectron_stage2_margin_fraction"]),
        stage2_margin_mm=float(theory["reflectron_stage2_margin_mm"]),
    )
    mass = float(arm8["source"]["mass_to_charge_Th"])
    acceleration_scale = (
        1000.0 / (mass * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C) * 1.0e-9
    )
    grid1_z = float(geometry["accelerator_grid1_z"])
    grid2_z = float(geometry["accelerator_grid2_z"])
    entrance_z = float(geometry["L_flight"])
    focus_z = 0.0
    velocity0 = row.vz_mm_per_us
    distance1 = grid1_z - row.z_mm
    acceleration1 = accelerator.field1_v_per_mm * acceleration_scale
    disc1 = velocity0 * velocity0 + 2.0 * acceleration1 * distance1
    if disc1 <= 0:
        raise ValueError("Arm8 analytic particle cannot cross accelerator stage 1")
    velocity1 = math.sqrt(disc1)
    time1 = (velocity1 - velocity0) / acceleration1
    acceleration2 = accelerator.field2_v_per_mm * acceleration_scale
    velocity2 = math.sqrt(velocity1 * velocity1 + 2.0 * acceleration2 * (grid2_z - grid1_z))
    time2 = (velocity2 - velocity1) / acceleration2
    acceleration_r1 = reflectron.stage1_field_v_per_mm * acceleration_scale
    velocity3_sq = velocity2 * velocity2 - 2.0 * acceleration_r1 * reflectron.stage1_length_mm
    if velocity3_sq <= 0:
        raise ValueError("Arm8 analytic particle turns before reflectron stage 2")
    velocity3 = math.sqrt(velocity3_sq)
    acceleration_r2 = reflectron.stage2_field_v_per_mm * acceleration_scale
    drift = (entrance_z - grid2_z + entrance_z - focus_z) / velocity2
    reflection = 2.0 * (velocity2 - velocity3) / acceleration_r1 + 2.0 * velocity3 / acceleration_r2
    return time1 + time2 + drift + reflection


def summarize_observations(
    states: Sequence[ObservationState], terminals: Sequence[Mapping[str, Any]],
    times_us: Sequence[float], geometry: Mapping[str, Any], resolved: Mapping[str, Any],
    arm8: Mapping[str, Any], *, launched_count: int, current_eligible_minimum: int,
) -> dict[str, Any]:
    """Summarize every preregistered time and select up to three blind candidates."""

    by_index: dict[int, list[ObservationState]] = {index: [] for index in range(1, len(times_us) + 1)}
    for row in states:
        by_index[row.sample_index].append(row)
    rows: list[dict[str, Any]] = []
    for index, time_us in enumerate(times_us, start=1):
        alive = by_index[index]
        eligible = [row for row in alive if _eligible(row, geometry)]
        z = np.asarray([row.z_mm for row in eligible], dtype=float)
        vz = np.asarray([row.vz_mm_per_us for row in eligible], dtype=float)
        predicted = np.asarray([_arm8_tof_us(row, resolved, arm8) for row in eligible], dtype=float)
        peak = compute_peak_metrics(predicted, float(arm8["source"]["mass_to_charge_Th"]))[0] if len(predicted) >= 3 else None
        rows.append({
            "sample_index": index, "instrument_time_us": float(time_us),
            "alive_count": len(alive), "eligible_count": len(eligible),
            "alive_coverage_fraction": len(alive) / launched_count,
            "eligible_coverage_fraction": len(eligible) / launched_count,
            "corr_z_vz": float(np.corrcoef(z, vz)[0, 1]) if len(z) >= 2 and np.std(z) and np.std(vz) else None,
            "spread": {
                "z_sigma_mm": float(np.std(z, ddof=1)) if len(z) >= 2 else None,
                "z_minimum_mm": float(np.min(z)) if len(z) else None,
                "z_maximum_mm": float(np.max(z)) if len(z) else None,
                "vz_sigma_mm_per_us": float(np.std(vz, ddof=1)) if len(vz) >= 2 else None,
                "vz_minimum_mm_per_us": float(np.min(vz)) if len(vz) else None,
                "vz_maximum_mm_per_us": float(np.max(vz)) if len(vz) else None,
            },
            "arm8_analytic_peak": None if peak is None else {
                "particles": peak["particles"], "mean_tof_us": peak["mean_tof_us"],
                "direct_fwhm_tof_ns": peak["direct_fwhm_tof_ns"],
                "mass_resolution": peak["mass_resolution"],
                "significant_kde_modes": peak["significant_kde_modes"],
            },
        })
    admissible = [row for row in rows if row["eligible_count"] >= current_eligible_minimum and row["arm8_analytic_peak"]]
    ranked = sorted(admissible, key=lambda row: (row["arm8_analytic_peak"]["direct_fwhm_tof_ns"], -row["eligible_count"], row["instrument_time_us"]))
    selected = [{"rank": rank, "sample_index": row["sample_index"], "instrument_time_us": row["instrument_time_us"],
                 "eligible_count": row["eligible_count"], "arm8_analytic_peak": row["arm8_analytic_peak"]}
                for rank, row in enumerate(ranked[:3], start=1)]
    max_alive = max(row["alive_count"] for row in rows)
    max_eligible = max(row["eligible_count"] for row in rows)
    return {
        "schema_version": 1,
        "role": "detector_blind_pulse_window_observability",
        "claim_scope": "upstream_observation_and_arm8_analytic_prediction_not_detector_candidate_solver",
        "detector_outcome_used": False,
        "schedule": {"sample_count": len(times_us), "start_us": times_us[0],
                     "center_us": times_us[len(times_us) // 2], "end_us": times_us[-1],
                     "maximum_spacing_ns": max(np.diff(times_us)) * 1.0e3},
        "census": {"launched_count": launched_count, "state_record_count": len(states),
                   "terminal_count": len(terminals), "terminal_reasons": {
                       reason: sum(row["reason"] == reason for row in terminals)
                       for reason in sorted({str(row["reason"]) for row in terminals})}},
        "coverage": {"current_eligible_minimum_count": current_eligible_minimum,
                     "maximum_alive_count": max_alive, "maximum_alive_fraction": max_alive / launched_count,
                     "maximum_eligible_count": max_eligible, "maximum_eligible_fraction": max_eligible / launched_count,
                     "seventy_percent_reachable": max_eligible >= math.ceil(0.7 * launched_count),
                     "seventy_percent_shortfall_explanation": None if max_eligible >= math.ceil(0.7 * launched_count)
                     else f"maximum observed eligible count {max_eligible}/{launched_count} is below 70%; particles lost before or outside the upstream extraction volume were not deleted"},
        "selection_rule": "minimum_Arm8_analytic_direct_FWHM_among_times_with_eligible_count_at_least_current_baseline_then_higher_coverage_then_earlier_time",
        "selected_preregistered_candidates": selected,
        "time_summaries": rows,
        "formal_qualification_claimed": False,
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-extension")
    build.add_argument("--pulse-time-us", type=float, required=True)
    build.add_argument("--base-program", type=Path)
    build.add_argument("--output", type=Path, required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--log", type=Path, required=True)
    analyze.add_argument("--geometry", type=Path, required=True)
    analyze.add_argument("--resolved", type=Path, required=True)
    analyze.add_argument("--arm8-contract", type=Path, required=True)
    analyze.add_argument("--pulse-time-us", type=float, required=True)
    analyze.add_argument("--launched-count", type=int, default=100)
    analyze.add_argument("--current-eligible-minimum", type=int, default=50)
    analyze.add_argument("--states-csv", type=Path, required=True)
    analyze.add_argument("--terminals-csv", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    times = predeclared_times_us(args.pulse_time_us)
    if args.command == "build-extension":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        base = ""
        if args.base_program is not None:
            base = args.base_program.read_text(encoding="utf-8").rstrip() + "\n\n"
        args.output.write_text(base + build_lua_extension(times), encoding="utf-8")
        return 0
    states, terminals = parse_observation_log(args.log.read_text(encoding="utf-8", errors="replace"), times, launched_count=args.launched_count)
    geometry = json.loads(args.geometry.read_text(encoding="utf-8-sig"))
    resolved = json.loads(args.resolved.read_text(encoding="utf-8-sig"))
    arm8 = json.loads(args.arm8_contract.read_text(encoding="utf-8-sig"))
    summary = summarize_observations(states, terminals, times, geometry, resolved, arm8,
                                     launched_count=args.launched_count, current_eligible_minimum=args.current_eligible_minimum)
    _write_csv(args.states_csv, [row.__dict__ for row in states]); _write_csv(args.terminals_csv, terminals)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"PULSE_WINDOW_OBSERVABILITY=PASS selected={len(summary['selected_preregistered_candidates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
