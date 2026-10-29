"""Select one pulse from actual execution-cohort OFF snapshots; no I/O or solver."""
from __future__ import annotations

import math
from typing import Any

from integrations.runtime.pulse_selection import select_actual_occupancy_pulse
from integrations.runtime.single_flight_source import binary64_serialization_close as _close

ROLE = "single_reflection_actual_occupancy_pulse_decision"
_STATE = ("x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us")


def resolve_phase_flight(author_flight: dict, *, phase: str, decision: dict | None = None,
                         requires_rf: bool = True) -> dict[str, Any]:
    """Derive the one actual native control from the frozen author's explicit plan."""
    from integrations.runtime.build_single_flight_program import validate_native_flight

    author = validate_native_flight(author_flight, requires_rf=requires_rf, allow_discovery=True)
    if phase not in {"discovery", "full_instrument"}:
        raise ValueError("native flight phase must be discovery or full_instrument")
    if author["pulse"]["mode"] != "discover":
        if phase != "full_instrument" or decision is not None:
            raise ValueError("only an author discovery plan can derive flight phases or a decision")
        return validate_native_flight(author, requires_rf=requires_rf)
    actual = {key: value for key, value in author.items() if key != "pulse"}
    if phase == "discovery":
        if decision is not None:
            raise ValueError("discovery cannot consume a pulse decision")
        actual.update(pulse={"mode": "held_off"}, observation_times_us=list(author["pulse"]["candidate_times_us"]))
    else:
        if (not isinstance(decision, dict) or decision.get("schema_version") != 2
                or decision.get("role") != "single_reflection_actual_occupancy_pulse_decision"
                or decision.get("status") != "success"
                or decision.get("selection_uses_future_terminal_outcome") is not False
                or decision.get("candidate_times_us") != author["pulse"]["candidate_times_us"]
                or decision.get("pulse_width_us") != author["pulse"]["width_us"]):
            raise ValueError("timed discovery successor requires a successful matching actual-occupancy decision")
        time = decision.get("actual_pulse_time_us")
        selection = decision.get("selection", {})
        if (isinstance(time, bool) or not isinstance(time, (int, float))
                or time not in author["pulse"]["candidate_times_us"]
                or selection.get("status") != "selected" or selection.get("selected_time_us") != time):
            raise ValueError("pulse decision must select one declared actual candidate")
        actual["pulse"] = {"mode": "timed", "time_us": time, "width_us": author["pulse"]["width_us"]}
    return validate_native_flight(actual, requires_rf=requires_rf)


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _capture_bounds(geometry: dict) -> dict:
    """Use the actual square OA bore and repeller/grid1 planes in assembly axes."""
    g = geometry["accelerator_projection"]
    width = g["bore_width_mm"]
    planes = (g["repeller_front_z_mm"], g["grid1_z_mm"])
    if (not _finite(width) or width <= 0 or any(not _finite(v) for v in planes)
            or planes[0] >= planes[1]):
        raise ValueError("actual OA first-gap geometry is invalid")
    bounds = {}
    for axis, low, high in (
        ("x", g["axis_x_mm"]-width/2, g["axis_x_mm"]+width/2),
        ("y", g["axis_y_mm"]-width/2, g["axis_y_mm"]+width/2),
        ("z", *planes),
    ):
        if not all(_finite(value) for value in (low, high)):
            raise ValueError("actual OA first-gap bounds are nonfinite")
        bounds[axis] = dict(minimum_mm=low, maximum_mm=high, center_mm=(low+high)/2,
                            full_width_mm=high-low)
    return bounds


def select_discovery_pulse(
    *, births_us: dict[int, float], snapshots: list[dict],
    terminal_times_us: dict[int, float], candidate_times_us: list[float],
    frontend_geometry: dict, pulse_width_us: float, input_records: dict,
) -> dict:
    """Use only actual births, snapshots, lifetime endpoints and first-gap geometry.

    Terminal times establish whether each original particle is alive at a
    candidate; causes, detector results and later positions are not inputs.
    No supported candidate is a retained negative decision, never a fake pulse.
    The managed caller verifies the three small input records before this API.
    """
    if set(input_records) != {"collection", "request", "frontend_geometry"}:
        raise ValueError("decision requires collection/request/frontend_geometry records")
    if not _finite(pulse_width_us) or pulse_width_us <= 0:
        raise ValueError("positive finite pulse width required")
    if (not candidate_times_us or any(not _finite(t) for t in candidate_times_us)
            or candidate_times_us != sorted(set(candidate_times_us))):
        raise ValueError("candidate times must be finite and strictly increasing")
    if (not births_us or any(type(pid) is not int or pid <= 0 for pid in births_us)
            or set(terminal_times_us) != set(births_us)):
        raise ValueError("actual birth/terminal lifetimes must cover the complete execution cohort")
    for pid, birth in births_us.items():
        end = terminal_times_us[pid]
        if (not _finite(birth) or not _finite(end)
                or (end < birth and not _close(end, birth))):
            raise ValueError(f"particle {pid}: invalid actual lifetime")
    observations = {time: [] for time in candidate_times_us}
    by_id_time = {}
    for row in snapshots:
        pid, target, actual = row["particle_id"], row["candidate_time_us"], row["instrument_time_us"]
        if type(pid) is not int or pid not in births_us or not _finite(target) or target not in observations:
            raise ValueError("snapshot ID or candidate is outside frozen execution cohort/plan")
        if ((pid, target) in by_id_time or not _finite(actual)
                or any(not _finite(row[field]) for field in _STATE)):
            raise ValueError("duplicate or nonfinite actual snapshot")
        if not _close(actual, target):
            raise ValueError("candidate snapshot lacks actual native time support; interpolation is forbidden")
        birth, end = births_us[pid], terminal_times_us[pid]
        if ((actual < birth and not _close(actual, birth))
                or (actual > end and not _close(actual, end))):
            raise ValueError(f"particle {pid}: snapshot outside actual lifetime")
        by_id_time[pid, target] = row
        observations[target].append(row)
    census, counts = {}, []
    for time in candidate_times_us:
        rows = []
        tally = dict(candidate_time_us=time, execution_cohort_count=len(births_us), not_born=0,
                     active=0, already_terminal=0, numerical_unsupported=0)
        for pid, birth in births_us.items():
            end = terminal_times_us[pid]
            if time < birth and not _close(time, birth):
                status = "not_born"
            elif time >= end or _close(time, end):
                status = "already_terminal"
            elif (pid, time) not in by_id_time:
                status = "numerical_unsupported"
            else:
                status = "active"
            tally[status] += 1
            rows.append(dict(particle_id=pid, instrument_time_us=time, status=status))
        census[time] = rows
        counts.append(tally)
    selection = select_actual_occupancy_pulse(
        observations, census, candidate_times_us, _capture_bounds(frontend_geometry),
        frame_id=frontend_geometry["composition_plan"]["assembly_frame_id"])
    selection["execution_cohort_count"] = len(births_us)
    selection["candidate_status_counts"] = counts
    success = selection["status"] == "selected"
    decision = dict(schema_version=2, role=ROLE,
        status="success" if success else "no_supported_candidate",
        input_records=dict(input_records), candidate_times_us=list(candidate_times_us),
        pulse_width_us=pulse_width_us, selection=selection,
        selection_uses_future_terminal_outcome=False)
    if success:
        decision["actual_pulse_time_us"] = selection["selected_time_us"]
    return decision
