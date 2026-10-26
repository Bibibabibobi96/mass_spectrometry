"""Reconstruct bounded canonical extraction crossings without file or solver I/O."""
from __future__ import annotations

from collections.abc import Iterable
import math

from common.contracts.particle_physics import kinetic_energy_ev

VALUES = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")


def prepare_spatial_crossings_from_samples(
    case: dict, planes: list[float], samples: Iterable[tuple[int, dict]],
) -> list[dict]:
    """Reconstruct first bounded -z crossings from caller-verified canonical rows.

    Each item is (source row number, state), with mm/us values and t_us. The
    caller owns source identity verification and coordinate/clock projection;
    source row numbers remain in both interpolation anchors. No files are
    created, no terminal is extrapolated, and every mother ID remains explicit.
    """
    if not planes or len(set(planes)) != len(planes) or any(not math.isfinite(z) or z < 0 for z in planes) or planes != sorted(planes, reverse=True):
        raise ValueError("spatial planes must be unique finite nonnegative descending z")
    config = case["config"]
    pulse = config["native_timing"]["pulse_start_us"]
    limit = config["diagnostics"]["max_extraction_bracket_us"]
    mass = config["source"]["species"]["mass_amu"]
    previous, crossed = {}, {}
    for line, raw in samples:
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ValueError("sample source row number must be a positive integer")
        t = float(raw["t_us"])
        if t < pulse:
            continue
        pid = int(raw["particle_id"])
        if pid not in case["sources"]:
            raise ValueError("spatial sample contains unknown particle")
        current = dict(t_us=t, **{key:float(raw[key]) for key in VALUES}, line=line)
        if any(not math.isfinite(current[key]) for key in ("t_us", *VALUES)):
            raise ValueError("nonfinite spatial sample")
        before = previous.get(pid)
        previous[pid] = current
        if before is None:
            continue
        gap = t-before["t_us"]
        if gap <= 0:
            raise ValueError("spatial sample time not increasing for particle")
        if gap > limit+1e-12 or before["vz_mm_us"] >= 0 or current["vz_mm_us"] >= 0:
            continue
        for z in planes:
            if z == 0 or (pid,z) in crossed or not before["z_mm"] >= z >= current["z_mm"] or before["z_mm"] == current["z_mm"]:
                continue
            alpha = (z-before["z_mm"])/(current["z_mm"]-before["z_mm"])
            state = {key:before[key]+alpha*(current[key]-before[key]) for key in ("t_us", *VALUES)}
            state["z_mm"] = z
            crossed[pid,z] = dict(**state, bracket_start_us=before["t_us"], bracket_end_us=t, bracket_gap_us=gap,
                                  lower_sample_line=before["line"], upper_sample_line=line, interpolation_alpha=alpha, method="bounded_linear_sample_crossing")
    for pid, raw in case["exits"].items():
        state = {key:float(raw[key]) for key in ("t_us", *VALUES)}
        if any(not math.isfinite(value) for value in state.values()) or state["t_us"] < pulse or state["vz_mm_us"] >= 0 or abs(state["z_mm"]) > 1e-10:
            raise ValueError("recorded exit violates spatial crossing contract")
        before = previous.get(pid)
        # The actual exit is a measured upper anchor when sampling stops at z>0.
        # Preserve the same temporal bound; never extrapolate or invent a CSV line.
        if before is not None:
            gap = state["t_us"]-before["t_us"]
            if 0 < gap <= limit+1e-12 and before["vz_mm_us"] < 0 and before["z_mm"] > 0:
                for z in planes:
                    if z == 0 or (pid,z) in crossed or not before["z_mm"] >= z > 0:
                        continue
                    alpha = (z-before["z_mm"])/(state["z_mm"]-before["z_mm"])
                    interpolated = {key:before[key]+alpha*(state[key]-before[key]) for key in ("t_us", *VALUES)}
                    interpolated["z_mm"] = z
                    crossed[pid,z] = dict(**interpolated, bracket_start_us=before["t_us"], bracket_end_us=state["t_us"], bracket_gap_us=gap,
                                          lower_sample_line=before["line"], upper_sample_line=None, interpolation_alpha=alpha,
                                          method="bounded_sample_to_exit_event_crossing")
        if 0 in planes:
            crossed[pid,0] = dict(**state, bracket_start_us=None, bracket_end_us=None, bracket_gap_us=None,
                                  lower_sample_line=None, upper_sample_line=None, interpolation_alpha=None, method="recorded_extraction_exit_event")
    rows = []
    for z in planes:
        for pid in sorted(case["sources"]):
            state = crossed.get((pid,z))
            row = dict(case=case["label"], stage=f"z_{z:g}_mm", plane_z_mm=z, particle_id=pid, status="alive" if state else "unknown",
                       reason="first_negative_z_crossing" if state else "no_valid_recorded_crossing", terminal_reason=case["terminals"][pid]["reason"])
            columns = ("t_us", *VALUES, "bracket_start_us", "bracket_end_us", "bracket_gap_us", "lower_sample_line", "upper_sample_line", "interpolation_alpha", "method")
            row.update({key:state[key] if state else None for key in columns})
            row["time_after_pulse_us"] = state["t_us"]-pulse if state else None
            row["Ex_eV"] = kinetic_energy_ev(mass,state["vx_mm_us"]*1000,0,0) if state else None
            row["Ez_eV"] = kinetic_energy_ev(mass,0,0,state["vz_mm_us"]*1000) if state else None
            row["total_energy_eV"] = kinetic_energy_ev(mass,*(state[f"v{axis}_mm_us"]*1000 for axis in "xyz")) if state else None
            for axis in "xy":
                row[f"theta_{axis}_deg"] = math.degrees(math.atan2(state[f"v{axis}_mm_us"],abs(state["vz_mm_us"]))) if state else None
            rows.append(row)
    return rows
