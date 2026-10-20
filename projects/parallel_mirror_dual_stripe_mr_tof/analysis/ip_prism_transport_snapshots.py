"""Full-lifecycle census snapshots within canonical saved-state support.

These complement the existing fixed all-active cohort diagnostics. Ended
particles retain a status only, never an extrapolated or frozen position.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics as local


STATUSES = ("upstream_not_transferred", "not_born", "active", "reached_exit", "lost", "numerical_unsupported")
LABELS = ("Upstream not transferred", "Not born", "Active supported", "Reached exit", "Lost", "Numerically unsupported")
COLORS = ("#999999", "#A6CEE3", "#009E73", "#0072B2", "#D55E00", "#CC79A7")


def _supported_state(track: list[dict], time_us: float, maximum_gap_us: float) -> tuple[dict | None, dict]:
    """Use an exact saved state or one adjacent, bounded canonical bracket."""
    times = np.asarray([r["t_us"] for r in track], dtype=float)
    if not len(times) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        return None, dict(support_reason="missing_or_nonmonotone_canonical_track")
    index = int(np.searchsorted(times, time_us))
    if index < len(times) and times[index] == time_us:
        state = track[index]
        if not all(math.isfinite(float(state[key])) for key in local.STATE_FIELDS):
            return None, dict(support_reason="nonfinite_saved_state")
        return {key: float(state[key]) for key in local.STATE_FIELDS[1:]}, dict(
            support_reason="exact_saved_state", lower_t_us=time_us, upper_t_us=time_us, bracket_gap_us=0.)
    if index == 0 or index == len(times):
        return None, dict(support_reason="no_canonical_bracket")
    first, second = track[index-1], track[index]
    gap = float(times[index]-times[index-1])
    serial = 8*np.finfo(float).eps*max(abs(times[index-1]), abs(times[index]))
    evidence = dict(lower_t_us=float(times[index-1]), upper_t_us=float(times[index]),
                    bracket_gap_us=gap, maximum_gap_us=maximum_gap_us, serialization_bound_us=serial)
    if gap > maximum_gap_us+serial:
        return None, dict(evidence, support_reason="canonical_bracket_gap_exceeds_bound")
    if not all(math.isfinite(float(row[key])) for row in (first, second) for key in local.STATE_FIELDS):
        return None, dict(evidence, support_reason="nonfinite_bracket_state")
    fraction = (time_us-times[index-1])/gap
    state = {key: float(first[key]+fraction*(second[key]-first[key])) for key in local.STATE_FIELDS[1:]}
    return state, dict(evidence, support_reason="bounded_canonical_interpolation", interpolation_fraction=float(fraction))


def prepare_transport_snapshots(cases: list[dict]) -> dict:
    """Prepare shared absolute times, every mother ID and supported active states.

    Times are five points from first birth to last terminal plus the earliest
    and median actual exit crossing. Active lifetime is [birth, terminal).
    Exact saved states need no inferred bracket; other states require adjacent
    canonical observations within sample cadence + maximum step + serialization.
    """
    if not cases or len({c["case"]["case_id"] for c in cases}) != len(cases):
        raise ValueError("Nonempty unique cases required")
    births = [r["t_us"] for c in cases for r in c["births"].values()]
    terminals = [r["t_us"] for c in cases for r in c["terminals"].values()]
    if not births or not terminals or not np.isfinite([*births, *terminals]).all():
        raise ValueError("Finite actual birth and terminal support required")
    exits = [r["t_us"] for c in cases for r in c["planes"].get("p1_exit", {}).values()]
    if not np.isfinite(exits).all():
        raise ValueError("Finite actual exit times required")
    anchors = [float(min(exits)), float(np.median(exits))] if exits else []
    times = sorted(set([*map(float, np.linspace(min(births), max(terminals), 5)), *anchors]))
    rows, counts = [], []
    for case in cases:
        spec = case["case"]
        if case["births"].keys() != case["terminals"].keys() or not case["births"].keys() <= case["census"].keys():
            raise ValueError("Birth/terminal/mother identity mismatch")
        if any(case["terminals"][pid]["t_us"] < birth["t_us"] for pid, birth in case["births"].items()):
            raise ValueError("Terminal before birth")
        maximum_gap = float(spec["sample_interval_us"])+float(spec["maximum_step_us"])
        if not math.isfinite(maximum_gap) or maximum_gap <= 0:
            raise ValueError("Positive finite canonical interpolation bound required")
        for index, time_us in enumerate(times):
            number = dict.fromkeys(STATUSES, 0)
            for pid in sorted(case["census"]):
                birth, terminal = case["births"].get(pid), case["terminals"].get(pid)
                row = dict(case_id=spec["case_id"], snapshot_index=index, particle_id=pid,
                           t_us=time_us, mother_count=len(case["census"]), input_count=len(case["births"]),
                           birth_t_us=birth["t_us"] if birth else None,
                           terminal_t_us=terminal["t_us"] if terminal else None,
                           terminal_reason=terminal["reason"] if terminal else None,
                           **dict.fromkeys(local.STATE_FIELDS[1:]))
                if birth is None:
                    status = "upstream_not_transferred"
                elif time_us < birth["t_us"]:
                    status = "not_born"
                elif time_us >= terminal["t_us"]:
                    status = "reached_exit" if terminal["reason"] == "reached_exit" else "lost"
                else:
                    # Never admit raw post-terminal halo as a canonical bracket.
                    track = [r for r in case["tracks"].get(pid, []) if birth["t_us"] <= r["t_us"] <= terminal["t_us"]]
                    state, evidence = _supported_state(track, time_us, maximum_gap)
                    row.update(evidence)
                    status = "active" if state is not None else "numerical_unsupported"
                    if state is not None:
                        row.update(state)
                row["status"] = status
                number[status] += 1
                rows.append(row)
            counts.append(dict(case_id=spec["case_id"], snapshot_index=index, t_us=time_us,
                               mother_count=len(case["census"]), input_count=len(case["births"]), **number))
    return dict(times_us=times, rows=rows, counts=counts, exit_anchor_times_us=anchors,
                status_definitions=dict(zip(STATUSES, LABELS)))


def prepare_display_zoom_centers(prepared: dict) -> list[dict]:
    """Describe display-only means of the identical supported active groups."""
    result = []
    for count in prepared["counts"]:
        active = [r for r in prepared["rows"] if r["case_id"] == count["case_id"]
                  and r["snapshot_index"] == count["snapshot_index"] and r["status"] == "active"]
        result.append(dict(case_id=count["case_id"], snapshot_index=count["snapshot_index"],
                           t_us=count["t_us"], active_count=len(active),
                           active_ids=[r["particle_id"] for r in active],
                           **{f"mean_{axis}_mm": float(np.mean([r[f"{axis}_mm"] for r in active]))
                              if active else None for axis in "xyz"}))
    return result


def build_transport_positions_figure(prepared: dict, cases: list[dict], epoch_us: float, transverse_axis: str,
                                     display_centers: list[dict] | None = None):
    """Display supported active positions only; every panel includes census counts."""
    from matplotlib import pyplot as plt

    if transverse_axis not in ("x", "y"):
        raise ValueError("Transverse axis must be x or y")
    times = prepared["times_us"]
    fig, axes = plt.subplots(len(cases), len(times), figsize=(3.2*len(times), 2.7*len(cases)),
                             squeeze=False, sharex=True, sharey=True, layout="constrained")
    for i, case in enumerate(cases):
        case_id = case["case"]["case_id"]
        for j, time_us in enumerate(times):
            ax = axes[i, j]
            active = [r for r in prepared["rows"] if r["case_id"] == case_id and r["snapshot_index"] == j and r["status"] == "active"]
            count = next(r for r in prepared["counts"] if r["case_id"] == case_id and r["snapshot_index"] == j)
            center = (next(r for r in display_centers if r["case_id"] == case_id and r["snapshot_index"] == j)
                      if display_centers is not None else None)
            z_offset = center["mean_z_mm"] if center is not None and active else 0.
            transverse_offset = center[f"mean_{transverse_axis}_mm"] if center is not None and active else 0.
            ax.scatter([r["z_mm"]-z_offset for r in active],
                       [r[f"{transverse_axis}_mm"]-transverse_offset for r in active], s=10, color=COLORS[2])
            if not active:
                ax.text(.5, .5, "No supported active ions", transform=ax.transAxes, ha="center", fontsize=8)
            if center is None:
                ax.set_title(f"{(time_us-epoch_us)*1000:.3f} ns from display epoch\n"
                             f"Active {count['active']}; unborn {count['not_born']}; exit {count['reached_exit']}; lost {count['lost']}\n"
                             f"Upstream {count['upstream_not_transferred']}; unsupported {count['numerical_unsupported']}", fontsize=8)
            else:
                means = (f"mean z={center['mean_z_mm']:.5f} mm\n"
                         f"mean {transverse_axis}={center[f'mean_{transverse_axis}_mm']:.5f} mm"
                         if active else "No active-position mean")
                ax.set_title(f"{(time_us-epoch_us)*1000:.3f} ns; active {len(active)}\n{means}", fontsize=8)
            ax.set(xlabel="Display delta z from panel mean (mm)" if center is not None else "Global z (mm)",
                   ylabel=f"Display delta {transverse_axis} (mm)" if center is not None else f"{transverse_axis} (mm)")
        label = f"Display delta {transverse_axis}" if display_centers is not None else transverse_axis
        axes[i, 0].set_ylabel(f"{case_id}\n{label} (mm); mother {len(case['census'])}, input {len(case['births'])}")
    title = ("Active-cloud zoom | identical active IDs and states as absolute-position panels\n"
             "Panel means subtracted for display only. Membership changes; these panels do not establish focusing or cooling."
             if display_centers is not None else
             "Full-transport simultaneous positions | shared absolute instrument times\n"
             "Only active ions with saved-state support are plotted; ended ions have status only, never extrapolated positions.")
    fig.suptitle(title)
    return fig


def build_transport_status_figure(prepared: dict, cases: list[dict], epoch_us: float):
    """Show every mother's lifecycle category, including unsupported observations."""
    from matplotlib import pyplot as plt

    fig, axes = plt.subplots(len(cases), 1, figsize=(12, 2.8*len(cases)), squeeze=False, layout="constrained")
    for ax, case in zip(axes[:, 0], cases):
        group = [r for r in prepared["counts"] if r["case_id"] == case["case"]["case_id"]]
        bottom = np.zeros(len(group))
        for status, label, color in zip(STATUSES, LABELS, COLORS):
            values = np.asarray([r[status] for r in group])
            ax.bar(range(len(group)), values, bottom=bottom, label=label, color=color, edgecolor="white", linewidth=.4)
            bottom += values
        ax.set_xticks(range(len(group)), [f"{(r['t_us']-epoch_us)*1000:.3f}" for r in group])
        ax.set(xlabel="Shared time from display epoch (ns)", ylabel="Mother-ion count",
               ylim=(0, len(case["census"])), title=f"{case['case']['case_id']} | mothers {len(case['census'])}, inputs {len(case['births'])}")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, fontsize=9)
    fig.suptitle("Full-transport lifecycle census | all categories sum to the complete mother population")
    return fig


def export_transport_snapshots(output: Path, cases: list[dict], epoch_us: float) -> dict:
    """Write full-window census, absolute/zoom positions and status figures."""
    prepared = prepare_transport_snapshots(cases)
    local._write_csv(output/"transport_time_census.csv", prepared["rows"])
    local._write_csv(output/"transport_time_counts.csv", prepared["counts"])
    names = []
    for axis in ("x", "y"):
        name = f"transport_packet_spatial_evolution_{axis}z"
        local._save_figure(build_transport_positions_figure(prepared, cases, epoch_us, axis), output/name)
        names.append(name)
    name = "transport_lifecycle_status"
    local._save_figure(build_transport_status_figure(prepared, cases, epoch_us), output/name)
    names.append(name)
    centers = prepare_display_zoom_centers(prepared)
    local._write_csv(output/"display_zoom_centers.csv", centers)
    for axis in ("x", "y"):
        name = f"transport_packet_zoom_{axis}z"
        local._save_figure(build_transport_positions_figure(prepared, cases, epoch_us, axis, centers), output/name)
        names.append(name)
    return dict(figure_names=names, times_us=prepared["times_us"],
                exit_anchor_times_us=prepared["exit_anchor_times_us"], status_definitions=prepared["status_definitions"],
                display_zoom_centers_table="display_zoom_centers.csv",
                display_zoom="Identical supported active IDs; per-panel mean xyz subtracted solely for display. Absolute positions/times unchanged in transport_time_census.csv. Active membership changes must not imply focusing or cooling; empty groups have no mean.",
                interpolation="Exact saved state, otherwise adjacent canonical bracket <= sample_interval_us + maximum_step_us + serialization; no post-terminal halo or extrapolation",
                policy="Five shared first-birth to last-terminal times plus earliest and median actual exit, exact automatic deduplication; active lifetime [birth,terminal); all mother IDs retained")
