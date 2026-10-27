"""Adapt IP extraction records to the version-1 shared bounded crossing kernel."""
from __future__ import annotations

from collections.abc import Iterable
import math

from common.analysis.plane_crossings import CrossingSample, iter_bounded_plane_crossings
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.rigid_transform import PhaseSpaceState, PlaneSurface

VALUES = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")


def prepare_spatial_crossings_from_samples(
    case: dict, planes: list[float], samples: Iterable[tuple[int, dict]],
) -> list[dict]:
    """Reconstruct first bounded -z crossings from caller-verified IP records.

    Input rows retain source line numbers, project-world mm/mm-us and native
    elapsed t_us. The frozen epoch is added exactly once for the core's
    PhaseSpaceState view; original fields are interpolated in their original
    units/time basis. The caller verifies source identity and clock authority.
    Pre-pulse rows retain the previous skip policy. z=0 always comes from the
    recorded exit, never an interpolated sample crossing. Every mother ID is
    retained, and missing brackets do not imply physical loss.
    """
    if not planes or len(set(planes)) != len(planes) or any(not math.isfinite(z) or z < 0 for z in planes) or planes != sorted(planes, reverse=True):
        raise ValueError("spatial planes must be unique finite nonnegative descending z")
    config = case["config"]
    pulse = config["native_timing"]["pulse_start_us"]
    limit = config["diagnostics"]["max_extraction_bracket_us"]
    mass = config["source"]["species"]["mass_amu"]
    frame = config["coordinate_transform"]["to_frame_id"]
    epoch = float(config["baseline"]["clock"]["epoch_us"])
    if not math.isfinite(epoch):
        raise ValueError("spatial crossing epoch must be finite")
    plane_z = {repr(z): z for z in planes}
    surfaces = {key: PlaneSurface(frame, (0., 0., z), (0., 0., -1.)) for key, z in plane_z.items()}
    latest, active_pair, crossed = {}, {}, {}

    def canonical_sample(pid, anchor, state):
        return CrossingSample(pid, anchor, PhaseSpaceState(
            frame, tuple(state[f"{axis}_mm"] for axis in "xyz"),
            tuple(state[f"v{axis}_mm_us"]*1000 for axis in "xyz"), epoch+state["t_us"],
        ))

    def recorded_samples():
        for line, raw in samples:
            if isinstance(line, bool) or not isinstance(line, int) or line < 1:
                raise ValueError("sample source row number must be a positive integer")
            t = float(raw["t_us"])
            # Preserve the established input contract: neither state/ID nor
            # time-order validation applies to these pre-pulse records.
            if t < pulse:
                continue
            pid = int(raw["particle_id"])
            if pid not in case["sources"]:
                raise ValueError("spatial sample contains unknown particle")
            current = dict(t_us=t, **{key:float(raw[key]) for key in VALUES}, line=line)
            if any(not math.isfinite(current[key]) for key in ("t_us", *VALUES)):
                raise ValueError("nonfinite spatial sample")
            active_pair[pid] = latest.get(pid), current
            latest[pid] = current
            yield canonical_sample(pid, line, current)
        for pid, raw in case["exits"].items():
            state = {key:float(raw[key]) for key in ("t_us", *VALUES)}
            if any(not math.isfinite(value) for value in state.values()) or state["t_us"] < pulse or state["vz_mm_us"] >= 0 or abs(state["z_mm"]) > 1e-10:
                raise ValueError("recorded exit violates spatial crossing contract")
            if 0 in planes:
                crossed[pid,0] = dict(**state, bracket_start_us=None, bracket_end_us=None, bracket_gap_us=None,
                                      lower_sample_line=None, upper_sample_line=None, interpolation_alpha=None,
                                      method="recorded_extraction_exit_event")
            before = latest.get(pid)
            if before is not None:
                gap = state["t_us"]-before["t_us"]
                if 0 < gap <= limit+1e-12 and before["vz_mm_us"] < 0 and before["z_mm"] > 0:
                    active_pair[pid] = before, state
                    yield canonical_sample(pid, "extraction_exit", state)

    # Include requested z=0 in validation, even for a zero-only request, but
    # discard its interpolated receipts. The real exit remains authoritative.
    for bracket in iter_bounded_plane_crossings(
        recorded_samples(), particle_ids=case["sources"], planes=surfaces,
        minimum_time_us=epoch+pulse, maximum_gap_us=limit, gap_tolerance_us=1e-12, occurrence=1,
    ):
        z = plane_z[bracket.plane_id]
        if z == 0:
            continue
        before, current = active_pair[bracket.particle_id]
        alpha = bracket.interpolation_alpha
        state = {key:before[key]+alpha*(current[key]-before[key]) for key in ("t_us", *VALUES)}
        state["z_mm"] = z
        from_exit = bracket.upper_anchor == "extraction_exit"
        crossed[bracket.particle_id,z] = dict(
            **state, bracket_start_us=before["t_us"], bracket_end_us=current["t_us"],
            bracket_gap_us=current["t_us"]-before["t_us"], lower_sample_line=bracket.lower_anchor,
            upper_sample_line=None if from_exit else bracket.upper_anchor, interpolation_alpha=alpha,
            method="bounded_sample_to_exit_event_crossing" if from_exit else "bounded_linear_sample_crossing",
        )
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
