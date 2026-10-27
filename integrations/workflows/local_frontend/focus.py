"""Prepare and export bounded local OA focus diagnostics from verified records.

The caller owns native parsing, complete lifetime validation and source identity.
This adapter preserves the original all_native_events.csv and raw-log anchors;
it never launches a solver or substitutes a projected state for a real crossing.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

from common.analysis.figure_export import export_figures
from common.analysis.population_moments import population_moments
from common.analysis.plane_crossings import (
    METHOD as CROSSING_METHOD,
    SCHEMA_VERSION as CROSSING_SCHEMA_VERSION,
    CrossingSample,
    iter_bounded_plane_crossings,
)
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.rigid_transform import PhaseSpaceState, PlaneSurface

from common.analysis.beam_focus_diagnostics import (
    build_focus_figure,
    build_time_focus_figure,
    prepare_focus_diagnostics,
    prepare_time_focus_diagnostics,
)

_STATE = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
_NATIVE_SAMPLES = {"source_release", "local_trajectory", "local_shared_time",
                   "accelerator_grid1_forward", "accelerator_intermediate2_forward"}
_NATIVE_SAMPLES.update(name+suffix for name in ("local_aperture_pre", "local_aperture_post", "local_accelerator_exit")
                       for suffix in ("_step_before", "_step_after"))
_COHORT_NAMES = {
    "all_available_alive": "Available crossings of the complete birth cohort",
    "own_extracted_ids": "All own exit IDs; missing upstream crossings retained",
    "common_extracted_ids": "Fixed exit IDs with valid crossings at every declared plane",
}


def _planes(frontend: dict) -> list[float]:
    start = float(frontend["accelerator_local_region"]["planes"]["grid1"])
    stop = float(frontend["accelerator_local_region"]["planes"]["exit"])
    cell = float(frontend["cell_mm_xyz"]["z"])
    origin = float(frontend["instance_origin_mm"]["z"])
    if not all(math.isfinite(v) for v in (start, stop, cell, origin)) or not start > stop == 0 or cell <= 0:
        raise ValueError("focus diagnostics require positive grid1-to-z0 span and native z cell")
    indices = []
    for coordinate in (start, stop):
        index = (coordinate-origin)/cell
        # Same binary64 serialization allowance as the verified native parser;
        # this is a lattice-identity check, not a physical mesh tolerance.
        if abs(index-round(index)) > 32*math.ulp(max(1., abs(index))):
            raise ValueError("actual focus endpoint is not on the declared native z lattice")
        indices.append(round(index))
    planes = [origin+i*cell for i in range(indices[0], indices[1]-1, -1)]
    planes[0], planes[-1] = start, stop
    return planes


def _canonical(row: dict) -> dict:
    return dict(particle_id=row["particle_id"], t_us=row["instrument_time_us"],
                **{f"{a}_mm": row[f"{a}_mm"] for a in "xyz"},
                **{f"v{a}_mm_us": row[f"v{a}_mm_per_us"] for a in "xyz"})


def _samples(events: list[dict], lives: dict[int, dict]) -> tuple[list, list, dict]:
    """Deduplicate identical accepted states, retaining both source-row anchors."""
    grouped = {pid: [] for pid in lives}
    anchors = {}
    for line, event in enumerate(events, start=2):
        anchors[line] = event
        pid = event["particle_id"]
        if pid not in grouped:
            raise ValueError("focus sample is outside the complete lifetime census")
        # Terminal callbacks may run outside every PA instance. Their real
        # terminal state is retained by the caller, but is not an in-field path
        # anchor. Interpolated checkpoints are also separate from native steps.
        if event["event"] not in _NATIVE_SAMPLES or event["source_instance"] != 1:
            continue
        end = lives[pid]["exit"] or lives[pid]["terminal"]
        if event["instrument_time_us"] <= end["instrument_time_us"]:
            grouped[pid].append((line, _canonical(event)))
    samples, duplicates = [], []
    for pid, group in grouped.items():
        previous = None
        for line, row in sorted(group, key=lambda item: (item[1]["t_us"], item[0])):
            if previous is not None and row["t_us"] == previous[1]["t_us"]:
                if any(row[key] != previous[1][key] for key in _STATE):
                    raise ValueError(f"conflicting native states at the same time for particle {pid}")
                duplicates.append(dict(particle_id=pid, t_us=row["t_us"],
                                       retained_sample_line=previous[0], duplicate_sample_line=line,
                                       state_comparison="exact_6d_equality"))
                continue
            samples.append((line, row))
            previous = line, row
    return samples, duplicates, anchors


def _provenance(rows: list[dict], anchors: dict, lives: dict, log_indices: dict) -> None:
    event_lines = {(row["raw_log_path"], row["raw_line_number"]): line for line, row in anchors.items()}
    for row in rows:
        for side in ("lower", "upper"):
            line = row[f"{side}_sample_line"]
            anchor = anchors[line] if line is not None else None
            row[f"{side}_raw_log_index"] = log_indices[anchor["raw_log_path"]] if anchor else None
            row[f"{side}_raw_line_number"] = anchor["raw_line_number"] if anchor else None
        event = lives[row["particle_id"]]["exit"] if row["method"] in {
            "recorded_extraction_exit_event", "bounded_sample_to_exit_event_crossing"} else None
        row["exit_event_sample_line"] = event_lines[event["raw_log_path"], event["raw_line_number"]] if event else None
        row["exit_event_raw_log_index"] = log_indices[event["raw_log_path"]] if event else None
        row["exit_event_raw_line_number"] = event["raw_line_number"] if event else None


def _local_crossings(samples, source, exits, terminals, planes, *, frame, pulse, limit, mass):
    """Select native OA brackets; interpolate raw mm/us fields before advancing."""
    latest, crossed = {}, {}
    active_pair = None
    plane_z = {repr(z): z for z in planes}

    def recorded_states():
        nonlocal active_pair
        for line, raw in samples:
            time = float(raw["t_us"])
            if time < pulse:
                continue
            pid = raw["particle_id"]
            current = dict(t_us=time, **{key: float(raw[key]) for key in _STATE}, line=line)
            active_pair = latest.get(pid), current
            latest[pid] = current
            yield CrossingSample(pid, line, PhaseSpaceState(
                frame, tuple(current[f"{axis}_mm"] for axis in "xyz"),
                tuple(current[f"v{axis}_mm_us"]*1000 for axis in "xyz"), time))
        for pid, raw in exits.items():
            state = {key: float(raw[key]) for key in ("t_us", *_STATE)}
            if (any(not math.isfinite(value) for value in state.values()) or
                    state["t_us"] < pulse or state["vz_mm_us"] >= 0 or abs(state["z_mm"]) > 1e-10):
                raise ValueError("recorded exit violates local focus crossing contract")
            crossed[pid, 0.] = dict(**state, bracket_start_us=None, bracket_end_us=None, bracket_gap_us=None,
                                   lower_sample_line=None, upper_sample_line=None, interpolation_alpha=None,
                                   method="recorded_extraction_exit_event")
            before = latest.get(pid)
            gap = state["t_us"]-before["t_us"] if before is not None else None
            if (before is not None and 0 < gap <= limit+1e-12 and
                    before["vz_mm_us"] < 0 and before["z_mm"] > 0):
                current = dict(**state, line=None)
                active_pair = before, current
                yield CrossingSample(pid, "extraction_exit", PhaseSpaceState(
                    frame, tuple(state[f"{axis}_mm"] for axis in "xyz"),
                    tuple(state[f"v{axis}_mm_us"]*1000 for axis in "xyz"), state["t_us"]))

    for bracket in iter_bounded_plane_crossings(
        recorded_states(), particle_ids=source,
        planes={key: PlaneSurface(frame, (0., 0., z), (0., 0., -1.)) for key, z in plane_z.items()},
        minimum_time_us=pulse, maximum_gap_us=limit, gap_tolerance_us=1e-12,
    ):
        z = plane_z[bracket.plane_id]
        if z == 0:
            continue  # z=0 is supplied exclusively by the measured exit event.
        before, current = active_pair
        alpha = bracket.interpolation_alpha
        state = {key: before[key]+alpha*(current[key]-before[key]) for key in ("t_us", *_STATE)}
        state["z_mm"] = z
        crossed[bracket.particle_id, z] = dict(
            **state, bracket_start_us=before["t_us"], bracket_end_us=current["t_us"],
            bracket_gap_us=current["t_us"]-before["t_us"], lower_sample_line=before["line"],
            upper_sample_line=current["line"], interpolation_alpha=alpha,
            method="bounded_linear_sample_crossing" if current["line"] is not None else "bounded_sample_to_exit_event_crossing")
    rows = []
    for z in planes:
        for pid in sorted(source):
            state = crossed.get((pid, z))
            row = dict(case="Local OA", stage=f"z_{z:g}_mm", plane_z_mm=z, particle_id=pid,
                       status="alive" if state else "unknown",
                       reason="first_negative_z_crossing" if state else "no_valid_recorded_crossing",
                       terminal_reason=terminals[pid]["reason"])
            fields = ("t_us", *_STATE, "bracket_start_us", "bracket_end_us", "bracket_gap_us",
                      "lower_sample_line", "upper_sample_line", "interpolation_alpha", "method")
            row.update({key: state[key] if state else None for key in fields})
            row["time_after_pulse_us"] = state["t_us"]-pulse if state else None
            row["Ex_eV"] = kinetic_energy_ev(mass, state["vx_mm_us"]*1000, 0, 0) if state else None
            row["Ez_eV"] = kinetic_energy_ev(mass, 0, 0, state["vz_mm_us"]*1000) if state else None
            row["total_energy_eV"] = kinetic_energy_ev(mass, *(state[f"v{a}_mm_us"]*1000 for a in "xyz")) if state else None
            for axis in "xy":
                row[f"theta_{axis}_deg"] = math.degrees(math.atan2(state[f"v{axis}_mm_us"], abs(state["vz_mm_us"]))) if state else None
            rows.append(row)
    return rows


def prepare_exit_portrait(rows: list[dict], mass_amu: float) -> dict:
    """Retain every actual exit and its coupled time/space/angle/energy moments."""
    exits = [dict(row) for row in rows if row["plane_z_mm"] == 0 and row["status"] == "alive"]
    fields = ("arrival_minus_mean_ns", "x_mm", "y_mm", "theta_x_deg", "theta_y_deg",
              "Ex_eV", "Ey_eV", "Ez_eV", "total_energy_eV")
    mean_time = float(np.mean([row["t_us"] for row in exits])) if exits else None
    for row in exits:
        row["Ey_eV"] = kinetic_energy_ev(mass_amu, 0., row["vy_mm_us"]*1000., 0.)
        row["arrival_minus_mean_ns"] = (row["t_us"]-mean_time)*1000.
    values = np.asarray([[row[field] for field in fields] for row in exits], dtype=float).reshape(len(exits), len(fields))
    population = population_moments(values)
    return dict(states=exits, fields=list(fields), count=len(exits), mean_t_us=mean_time,
                moments={field: dict(mean=float(population.mean[i]), population_sd=float(np.sqrt(population.covariance[i, i])))
                         for i, field in enumerate(fields)} if exits else {},
                covariance_matrix=population.covariance.tolist() if exits else None,
                covariance_definition="Population covariance; field order and units in fields; all own exit IDs, no clipping")


def prepare_local_focus(
    events: list[dict], source: dict[int, dict], lives: dict[int, dict],
    frontend: dict, numerics: dict, *, pulse_time_us: float, source_events_path: Path,
) -> dict:
    """Adapt already-verified native MR records without rereading or re-timing them.

    ``source_events_path`` names the caller's CSV of ``events`` in exactly this
    order. CSV line 1 is its header. Raw log text remains in that source table.
    Unknown spatial crossings are diagnostic gaps, never new physical losses.
    """
    if (frontend.get("native_frame_id") != "mrtof_global_cartesian" or
            frontend.get("slow_axis") != "y" or frontend.get("acceleration_direction") != -1):
        raise ValueError("focus adapter requires native MR coordinates and negative-z extraction")
    if not source or set(source) != set(lives) or not math.isfinite(pulse_time_us):
        raise ValueError("focus adapter requires the complete source/lifetime census and pulse time")
    masses = {float(row["mass_amu"]) for row in source.values()}
    if len(masses) != 1 or not math.isfinite(next(iter(masses))) or next(iter(masses)) <= 0:
        raise ValueError("focus moments require one finite positive source mass")
    sample_interval = float(numerics["trajectory_sample_interval_us"])
    maximum_step = float(numerics["maximum_step_us"])
    if any(not math.isfinite(v) or v <= 0 for v in (sample_interval, maximum_step)):
        raise ValueError("focus bracket requires positive frozen sampling and step limits")
    planes = _planes(frontend)
    samples, duplicates, anchors = _samples(events, lives)
    exits = {pid: _canonical(life["exit"]) for pid, life in lives.items() if life["exit"]}
    terminals = {pid: dict(reason=life["terminal"]["event"]) for pid, life in lives.items()}
    case = dict(label="Local OA", sources=source, exits=exits, terminals=terminals,
                particle_weights={pid: 1. for pid in source})
    rows = _local_crossings(samples, source, exits, terminals, planes, frame=frontend["native_frame_id"],
                            pulse=pulse_time_us, limit=sample_interval+maximum_step, mass=next(iter(masses)))
    log_indices = {path: index for index, path in enumerate(dict.fromkeys(r["raw_log_path"] for r in events))}
    _provenance(rows, anchors, lives, log_indices)
    valid = {z: {r["particle_id"] for r in rows if r["plane_z_mm"] == z and r["status"] == "alive"} for z in planes}
    fixed = sorted(set(exits).intersection(*(valid[z] for z in planes)))
    case["states"] = rows
    focus = prepare_focus_diagnostics([case], planes, fixed)
    if not fixed:
        focus["display_cohort"] = "own_extracted_ids"
    # Along-field tables contain only recorded crossings. Dense hypothetical
    # drift curves are calculated once at the real exit, not at every plane.
    time = prepare_time_focus_diagnostics([case], planes, fixed, {"drift_lengths_mm": [0.]})
    exit_case = {**case, "states": [r for r in rows if r["plane_z_mm"] == planes[-1]]}
    drift_lengths = [z-planes[-1] for z in reversed(planes)]
    exit_time = prepare_time_focus_diagnostics([exit_case], [planes[-1]], fixed,
                                               {"drift_lengths_mm": drift_lengths})
    metadata = dict(schema_version=1, role="local_frontend_recorded_focus", frame_id=frontend["native_frame_id"],
                    source_events_path=str(Path(source_events_path).resolve()),
                    raw_logs=[dict(index=index, path=path) for path, index in log_indices.items()],
                    clock="Original absolute instrument time in us; no epoch reset",
                    pulse_time_us=pulse_time_us, plane_rule="Every native z lattice plane from actual grid1 to actual z=0 exit",
                    planes_mm=planes, maximum_bracket_us=sample_interval+maximum_step,
                    mother_ids=sorted(source), own_exit_ids=sorted(exits), fixed_all_plane_exit_ids=fixed,
                    terminal_loss_ids=sorted(set(source)-set(exits)), cohorts=_COHORT_NAMES,
                    duplicate_count=len(duplicates), canonical_sample_count=len(samples),
                    interpolation="First post-pulse negative-z bounded linear crossing; exit from verified native checkpoint",
                    crossing_reconstruction=dict(schema_version=CROSSING_SCHEMA_VERSION, method=CROSSING_METHOD,
                                                 occurrence=1, observation="adjacent_native_sample_reconstruction"),
                    provenance="Sample lines refer to all_native_events.csv including its header; log indices map to raw_logs; raw text stays in source CSV",
                    unknown_policy="No valid bracket means unknown crossing, not loss; no extrapolation or tail rejection",
                    drift_scope="Exit-only zero-field straight-path counterfactual, not actual downstream focus",
                    drift_lengths_mm=drift_lengths, focus_metrics=focus["metadata"], time_metrics=time["metadata"])
    return dict(metadata=metadata, crossings=rows, duplicates=duplicates, focus=focus,
                time=time, exit_time=exit_time, exit_portrait=prepare_exit_portrait(rows, next(iter(masses))))


def build_local_focus_figures(prepared: dict) -> dict:
    """Render existing focus figures and the actual angular/emittance evolution."""
    from matplotlib import pyplot as plt

    focus, time, exit_time = prepared["focus"], prepared["time"], prepared["exit_time"]
    figure = build_focus_figure(focus)
    figures = {"recorded_focus": figure}
    for cohort, name in (("own_extracted_ids", "time_focus_own_exits"),
                         ("common_extracted_ids", "time_focus_fixed_ids")):
        if cohort == "common_extracted_ids" and not focus["common_ids"]:
            continue
        render = {**time, "display_cohort": cohort,
                  "reference_plane_predictions": exit_time["reference_plane_predictions"]}
        figures[name] = build_time_focus_figure(render)
        figures[name].legends[0].set_title(_COHORT_NAMES[cohort] + "\nRecorded crossings and separately declared zero-field prediction")
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    metrics = (("sigma_theta_x_deg", "SD xz angle (deg)"), ("sigma_theta_y_deg", "SD yz angle (deg)"),
               ("epsilon_x_mm_mrad", "RMS x emittance (mm mrad)"), ("epsilon_y_mm_mrad", "RMS y emittance (mm mrad)"))
    for cohort, color, line in zip(_COHORT_NAMES, ("#0072B2", "#E69F00", "#009E73"), ("-", "--", ":"), strict=True):
        if cohort == "common_extracted_ids" and not focus["common_ids"]:
            continue
        rows = [r for r in focus["plane_statistics"] if r["cohort"] == cohort]
        counts = [r["observed_count"] for r in rows]
        label = f"{_COHORT_NAMES[cohort]} | N={min(counts)} to {max(counts)}"
        for ax, (key, ylabel) in zip(axes.flat, metrics, strict=True):
            ax.plot([r["plane_z_mm"] for r in rows], [math.nan if r[key] is None else r[key] for r in rows],
                    color=color, linestyle=line, linewidth=1.2, label=label)
            ax.set(xlabel="Recorded plane z (mm); flight toward -z", ylabel=ylabel,
                   xlim=(max(focus["planes_mm"]), min(focus["planes_mm"])))
            ax.grid(alpha=.2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside upper center", frameon=False, fontsize=8,
                  title="Actual bounded crossings | Population moments; missing crossings remain unknown")
    figures["recorded_angle_emittance"] = figure
    portrait = prepared["exit_portrait"]
    rows = portrait["states"]
    figure, axes = plt.subplots(3, 3, figsize=(13, 11), constrained_layout=True)
    for ax, (abscissa, ordinate, xlabel, ylabel) in zip(axes[0], (
        ("x_mm", "theta_x_deg", "Native x (mm)", "Signed xz angle (deg)"),
        ("y_mm", "theta_y_deg", "Native y (mm)", "Signed yz angle (deg)"),
        ("x_mm", "y_mm", "Native x (mm)", "Native y (mm)")), strict=True):
        ax.scatter([r[abscissa] for r in rows], [r[ordinate] for r in rows], s=12, color="#0072B2")
        ax.set(xlabel=xlabel, ylabel=ylabel)
    for ax, field in zip(axes[1], ("Ex_eV", "Ey_eV", "Ez_eV"), strict=True):
        values = np.sort([r[field] for r in rows])
        ax.step(values, np.arange(1, len(values)+1)/len(values) if len(values) else [], where="post", color="#0072B2")
        ax.set(xlabel=field.replace("_eV", " (eV)"), ylabel="Cumulative fraction of all exits", ylim=(0., 1.02))
    for ax, field, xlabel in zip(axes[2, :2], ("total_energy_eV", "arrival_minus_mean_ns"),
                                  ("Total kinetic energy (eV)", "Arrival time minus own exit mean (ns)"), strict=True):
        values = np.sort([r[field] for r in rows])
        ax.step(values, np.arange(1, len(values)+1)/len(values) if len(values) else [], where="post", color="#0072B2")
        ax.set(xlabel=xlabel, ylabel="Cumulative fraction of all exits", ylim=(0., 1.02))
    axes[2, 2].scatter([r["arrival_minus_mean_ns"] for r in rows], [r["total_energy_eV"] for r in rows], s=12, color="#D55E00")
    axes[2, 2].set(xlabel="Arrival time minus own exit mean (ns)", ylabel="Total kinetic energy (eV)")
    for ax in axes.flat:
        ax.grid(alpha=.2)
        if not rows:
            ax.text(.5, .5, "No recorded exits", transform=ax.transAxes, ha="center")
    figure.suptitle(f"Actual OA exit at z=0 mm | All {len(rows)} exits of {len(prepared['metadata']['mother_ids'])} births\n"
                   "Each ion at its own crossing time; full tails retained; directional energies include bulk drift", fontsize=11)
    figures["exit_phase_energy"] = figure
    return figures


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    columns = fields or list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, allow_nan=False) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def export_local_focus(prepared: dict, output_directory: Path) -> dict:
    """Write compact summaries, complete CSV evidence and English PNG/SVG figures."""
    from matplotlib import pyplot as plt

    out = Path(output_directory)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.glob("focus_*")):
        raise FileExistsError("local focus export refuses to overwrite existing focus outputs")
    focus, time, exit_time = prepared["focus"], prepared["time"], prepared["exit_time"]
    tables = {"spatial_crossings": prepared["crossings"], "plane_statistics": focus["plane_statistics"],
              "exit_angle_decomposition": focus["exit_angle_decomposition"], "exit_free_drift_waists": focus["field_free_predictions"],
              "plane_time_statistics": time["plane_time_statistics"], "time_interval_variances": time["time_interval_variance_rows"],
              "exit_free_drift_time": exit_time["reference_plane_predictions"],
              "exit_phase_energy": prepared["exit_portrait"]["states"]}
    for name, rows in tables.items():
        _write_csv(out / f"focus_{name}.csv", rows)
    _write_csv(out / "focus_duplicate_sample_audit.csv", prepared["duplicates"],
               ["particle_id", "t_us", "retained_sample_line", "duplicate_sample_line", "state_comparison"])
    summary = dict(schema_version=1, role="local_frontend_recorded_focus_summary",
                   mother_count=len(prepared["metadata"]["mother_ids"]),
                   own_exit_count=len(prepared["metadata"]["own_exit_ids"]),
                   fixed_all_plane_exit_count=len(focus["common_ids"]),
                   plane_count=len(focus["planes_mm"]),
                   unknown_crossing_count=sum(r["status"] == "unknown" for r in prepared["crossings"]),
                   sampled_minima=[{k: v for k, v in r.items() if k != "available_ids"} for r in time["sampled_minima"]],
                   exit_free_drift_waists=focus["field_free_predictions"],
                   exit_phase_energy_moments={k: v for k, v in prepared["exit_portrait"].items() if k != "states"},
                   scope="Bounded recorded-plane diagnostics; no numerical convergence, MR acceptance or resolving-power claim")
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none"}):
        figures = build_local_focus_figures(prepared)
        try:
            summary["figure_exports"] = export_figures(
                {out / f"focus_{name}": figure for name,figure in figures.items()},
                formats=("png","svg"),dpi=190,facecolor="white")
        finally:
            for figure in figures.values():
                plt.close(figure)
    for name, value in (("summary", summary), ("metadata", prepared["metadata"])):
        (out / f"focus_{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return {**summary, "output_paths": [str(p) for p in sorted(out.glob("focus_*")) if p.is_file()]}
