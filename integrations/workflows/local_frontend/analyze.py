"""Analyze recorded one-carrier local-frontend flights; never launches a solver."""
from __future__ import annotations

import csv
import itertools
import json
import math
from pathlib import Path
import re
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from integrations.runtime.single_flight_source import binary64_serialization_close as _close

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.rigid_transform import FramedPosition, PhaseSpaceState, RigidTransform
from common.contracts.write_run_manifest import file_record
from integrations.analysis.plot_single_flight_spatial_six_panel import (
    _checkpoint_distribution_summary,
    build_local_shared_time_figure,
    write_checkpoint_evolution_outputs,
)
from integrations.runtime.pulse_selection import (
    select_actual_occupancy_pulse,
)

from integrations.workflows.local_frontend.focus import (
    export_local_focus, prepare_local_focus,
)

_APERTURE_EVENTS = ("local_aperture_pre", "local_aperture_post")
_APERTURE_ENDPOINTS = {name + suffix for name in _APERTURE_EVENTS
                       for suffix in ("_step_before", "_step_after")}
_EVENTS = {"source_release", "local_shared_time", "local_trajectory",
           *_APERTURE_EVENTS, *_APERTURE_ENDPOINTS,
           "accelerator_grid1_forward", "accelerator_intermediate2_forward", "local_accelerator_exit",
           "local_accelerator_exit_step_before", "local_accelerator_exit_step_after",
           "accelerator_exit_stop", "local_timeout", "local_native_stop"}
_TERMINALS = {"accelerator_exit_stop", "local_timeout", "local_native_stop"}
_FLOATS = ("instrument_time_us", "x_mm", "y_mm", "z_mm",
           "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "requested_time_us")
_STATE = ("x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us")
SHARED_TIME_DISPLAY_SELECTION = (
    "At most five declared times: evenly indexed recorded-active times plus the first "
    "complete-mother terminal time after the last active/unsupported time, if available; "
    "all declared times and IDs remain in CSV."
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    keys = columns or list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def parse_local_logs(log_paths: list[Path], source: dict[int, dict]) -> tuple[list[dict], dict]:
    """Keep each original trace line and bind its log identity exactly once."""
    events, identities = [], {}
    for path in log_paths:
        path = path.resolve()
        before = file_record(path)
        identities[str(path)] = before
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            match = re.search(r"TRACE: (\w+) (.*)", line)
            if match is None:
                continue
            event, fields = match.groups()
            if event not in _EVENTS:
                raise ValueError(f"unexpected local Program event {event}")
            pairs = re.findall(r"(\w+)=([^\s]+)", fields)
            raw = dict(pairs)
            if len(raw) != len(pairs):
                raise ValueError("duplicate native trace field")
            required = {*_FLOATS, "particle_id", "ion", "source_instance"}
            if set(raw) != required:
                raise ValueError("local native trace fields differ from Program contract")
            row = {key: float(raw[key]) for key in _FLOATS}
            if not all(math.isfinite(value) for value in row.values()):
                raise ValueError("non-finite local native state")
            row.update({key: int(raw[key]) for key in ("particle_id", "ion", "source_instance")})
            pid = row["particle_id"]
            if pid not in source:
                raise ValueError("native particle ID is outside the complete source")
            row.update(event=event, raw_line=line, raw_line_number=line_number, raw_log_path=str(path))
            row["kinetic_energy_eV"] = kinetic_energy_ev(
                float(source[pid]["mass_amu"]), *(1000. * row[f"v{a}_mm_per_us"] for a in "xyz"))
            events.append(row)
        if before != file_record(path):
            raise ValueError("native log changed while being consumed")
    return events, identities


def _source_rows(path: Path) -> dict[int, dict]:
    with path.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    ids = [int(row["particle_id"]) for row in rows]
    if not rows or len(set(ids)) != len(ids):
        raise ValueError("complete source IDs must be nonempty and unique")
    return dict(zip(ids, rows))


def _validate_lifetimes(events: list[dict], source: dict[int, dict]) -> dict[int, dict]:
    lifetimes = {}
    by_id = {pid: [] for pid in source}
    for row in events:
        by_id[row["particle_id"]].append(row)
    for pid, original in source.items():
        rows = by_id[pid]
        births = [row for row in rows if row["event"] == "source_release"]
        ends = [row for row in rows if row["event"] in _TERMINALS]
        if len(births) != 1 or len(ends) != 1:
            raise ValueError(f"particle {pid} lacks a unique birth/terminal")
        birth, end = births[0], ends[0]
        expected = {"instrument_time_us": float(original["instrument_time_us"])}
        expected.update({f"{a}_mm": float(original[f"position_{a}_mm"]) for a in "xyz"})
        expected.update({f"v{a}_mm_per_us": float(original[f"velocity_{a}_m_s"]) / 1000. for a in "xyz"})
        if any(not _close(birth[key], value) for key, value in expected.items()):
            raise ValueError(f"particle {pid} birth differs from frozen source/clock")
        if end["instrument_time_us"] < birth["instrument_time_us"]:
            raise ValueError("terminal precedes birth")
        for row in rows:
            t = row["instrument_time_us"]
            if t < birth["instrument_time_us"] and not _close(t, birth["instrument_time_us"]):
                raise ValueError("native state precedes birth")
            if t > end["instrument_time_us"] and not _close(t, end["instrument_time_us"]):
                raise ValueError(
                    f"particle {pid} native state follows terminal: "
                    f"{row['event']} at {row['raw_log_path']}:{row['raw_line_number']} "
                    f"time_us={t:.17g}; {end['event']} at "
                    f"{end['raw_log_path']}:{end['raw_line_number']} "
                    f"time_us={end['instrument_time_us']:.17g}"
                )
        exits = [row for row in rows if row["event"] == "local_accelerator_exit"]
        if len(exits) > 1 or bool(exits) != (end["event"] == "accelerator_exit_stop"):
            raise ValueError("exit checkpoint and terminal classification disagree")
        lifetimes[pid] = {"birth": birth, "terminal": end, "exit": exits[0] if exits else None}
    return lifetimes


def _validate_aperture_crossings(events: list[dict], port: dict) -> list[dict]:
    """Verify each recorded checkpoint against its consecutive native endpoint events."""
    crossings, consumed = [], set()
    for index, before in enumerate(events):
        if before["event"] not in {*_APERTURE_EVENTS, *_APERTURE_ENDPOINTS} or index in consumed:
            continue
        name = before["event"].removesuffix("_step_before")
        if name not in _APERTURE_EVENTS or before["event"] != name + "_step_before" or index + 2 >= len(events):
            raise ValueError("aperture checkpoint lacks its native endpoint triplet")
        after, crossing = events[index + 1:index + 3]
        if after["event"] != name + "_step_after" or crossing["event"] != name:
            raise ValueError("aperture endpoint event order differs from Program contract")
        rows = (before, after, crossing)
        for key in ("particle_id", "ion", "source_instance", "raw_log_path"):
            if any(row[key] != before[key] for row in rows):
                raise ValueError("aperture endpoint identity or native source differs")
        if before["source_instance"] != 1 or not (before["raw_line_number"] < after["raw_line_number"] < crossing["raw_line_number"]):
            raise ValueError("aperture endpoint source or native event order is invalid")
        if any(not _close(row["requested_time_us"], row["instrument_time_us"]) for row in rows):
            raise ValueError("aperture event clock differs from its recorded state")
        plane = float(port["flange_min_mm" if name == "local_aperture_pre" else "flange_max_mm"])
        t0, t1 = before["instrument_time_us"], after["instrument_time_us"]
        y0, y1 = before["y_mm"], after["y_mm"]
        if after["vy_mm_per_us"] <= 0 or crossing["vy_mm_per_us"] <= 0:
            raise ValueError("aperture checkpoint is not a forward passage")
        if t1 > t0 and y0 < plane <= y1:
            fraction = (plane - y0) / (y1 - y0)
            expected = {key: before[key] + fraction * (after[key] - before[key])
                        for key in (*_STATE, "instrument_time_us")}
            expected["y_mm"] = plane
            basis = "same_native_step_linear_6d_plane_interpolation"
        elif t1 == t0 and all(before[key] == after[key] for key in _STATE) and _close(y1, plane):
            fraction = None
            expected = {key: after[key] for key in (*_STATE, "instrument_time_us")}
            basis = "native_zero_step_actual_state_within_32_ulp"
        else:
            raise ValueError("aperture checkpoint lacks a forward bracket or a zero-step state within 32 ULP")
        if not t0 <= crossing["instrument_time_us"] <= t1 or any(
            not _close(crossing[key], value) for key, value in expected.items()
        ):
            raise ValueError("aperture checkpoint differs from its recorded native-step interpolation")
        crossing.update(plane_landing_basis=basis, interpolation_fraction=fraction,
                        step_before_raw_line_number=before["raw_line_number"],
                        step_after_raw_line_number=after["raw_line_number"])
        crossings.append(crossing)
        consumed.update((index, index + 1, index + 2))
    return crossings


def _aperture_passages(events: list[dict], source: dict[int, dict], lives: dict[int, dict],
                       frontend: dict) -> tuple[list[dict], dict]:
    """Summarize recorded face passages, without inferring a metal stop cause."""
    port = frontend["accelerator_local_region"]["port"]
    if port["normal_axis"] != "y" or port["flange_min_mm"] >= port["flange_max_mm"]:
        raise ValueError("aperture diagnostics require increasing physical +y wall faces")
    first = {name: {} for name in _APERTURE_EVENTS}
    for row in sorted(_validate_aperture_crossings(events, port), key=lambda r: r["instrument_time_us"]):
        plane = port["flange_min_mm" if row["event"] == "local_aperture_pre" else "flange_max_mm"]
        if not _close(row["y_mm"], float(plane)) or row["vy_mm_per_us"] <= 0:
            raise ValueError("aperture checkpoint differs from the forward wall face")
        first[row["event"]].setdefault(row["particle_id"], row)
    pre, post = first.values()
    if not set(post) <= set(pre) or any(post[pid]["instrument_time_us"] < pre[pid]["instrument_time_us"] for pid in post):
        raise ValueError("aperture post passage lacks its earlier pre passage")
    census = []
    for pid in source:
        stage = "after_post" if pid in post else "between_faces" if pid in pre else "before_pre"
        census.append(dict(particle_id=pid, recorded_passage_stage=stage,
                           pre_time_us=pre[pid]["instrument_time_us"] if pid in pre else None,
                           post_time_us=post[pid]["instrument_time_us"] if pid in post else None,
                           terminal_event=lives[pid]["terminal"]["event"],
                           terminal_raw_log_path=lives[pid]["terminal"]["raw_log_path"],
                           terminal_raw_line_number=lives[pid]["terminal"]["raw_line_number"]))
    paired = sorted(set(pre) & set(post))
    cohorts = {}
    for label, ids, name in (("pre_own", sorted(pre), "local_aperture_pre"),
                             ("post_own", sorted(post), "local_aperture_post"),
                             ("paired_pre", paired, "local_aperture_pre"),
                             ("paired_post", paired, "local_aperture_post")):
        rows = [first[name][pid] for pid in ids]
        cohorts[label] = dict(particle_ids=ids, count=len(ids), statistics=(
            _checkpoint_distribution_summary(pd.DataFrame(rows), name, frame_id=frontend["native_frame_id"],
                                             propagation_axis="y") if rows else None))
    return census, dict(mother_count=len(source), pre_count=len(pre), post_count=len(post),
                        paired_ids=paired, cohorts=cohorts,
                        recorded_passage_stage_counts={stage: sum(r["recorded_passage_stage"] == stage for r in census)
                            for stage in ("before_pre", "between_faces", "after_post")},
                        classification_basis="First forward physical-face observations; passage history, not proof of terminal metal contact",
                        plane_landing_basis="Same-native-step linear 6D plane interpolation; zero-step actual states only within 32 ULP; native endpoint triplets retained",
                        terminal_causes="Native stops remain unresolved; no aperture-metal classification inferred")


def _observe(row: dict, observer: RigidTransform) -> dict:
    state = observer.transform_state(PhaseSpaceState(
        observer.from_frame_id, tuple(row[f"{a}_mm"] for a in "xyz"),
        tuple(1000. * row[f"v{a}_mm_per_us"] for a in "xyz"), row["instrument_time_us"]))
    return {**row, **dict(zip(("x_mm", "y_mm", "z_mm"), state.position_mm)),
            **{f"v{a}_mm_per_us": state.velocity_m_s[i] / 1000. for i, a in enumerate("xyz")},
            "frame_id": observer.to_frame_id}


def _snapshot_census(events: list[dict], source: dict[int, dict], lives: dict[int, dict],
                     times: list[float], observer: RigidTransform) -> tuple[list[dict], list[dict], list[dict]]:
    snapshots = {}
    for row in events:
        if row["event"] == "local_shared_time":
            requested = row["requested_time_us"]
            key = (row["particle_id"], requested)
            if requested not in times or key in snapshots:
                raise ValueError("unknown or duplicate native shared-time observation")
            snapshots[key] = row
    census, active, counts = [], [], []
    for time in times:
        tally = dict(instrument_time_us=time, mother_count=len(source),
                     not_born=0, active=0, already_exit=0, already_loss=0, numerical_unsupported=0)
        for pid in source:
            life = lives[pid]
            birth, end = life["birth"]["instrument_time_us"], life["terminal"]["instrument_time_us"]
            row = snapshots.get((pid, time))
            if time < birth and not _close(time, birth):
                status = "not_born"
            elif time >= end or _close(time, end):
                status = "already_exit" if life["exit"] else "already_loss"
            elif row is None or not _close(row["instrument_time_us"], time):
                status = "numerical_unsupported"
            else:
                status = "active"
                active.append(_observe(row, observer))
            tally[status] += 1
            census.append(dict(particle_id=pid, instrument_time_us=time, status=status))
        counts.append(tally)
    return census, active, counts


def select_shared_time_display_counts(counts: list[dict]) -> list[dict]:
    """Select useful display panels from a validated, chronological mother census.

    Keep first/last recorded-active times and evenly indexed intermediate ones.
    Reserve one panel for the first complete terminal census after all active or
    unsupported lifetimes; not-born/unsupported populations are never terminal.
    This display-only subset does not modify counts, times, particles or CSVs.
    """
    if not counts:
        return []
    active = [row for row in counts if row["active"] > 0]
    last_alive = max((i for i, row in enumerate(counts)
                      if row["active"] > 0 or row["numerical_unsupported"] > 0), default=-1)
    terminal = next((row for i, row in enumerate(counts) if i > last_alive and
                     row["mother_count"] > 0 and row["not_born"] == row["active"] == row["numerical_unsupported"] == 0 and
                     row["already_exit"] + row["already_loss"] == row["mother_count"]), None)
    slots = 4 if terminal is not None else 5
    selected = active if len(active) <= slots else [
        active[round(i * (len(active) - 1) / (slots - 1))] for i in range(slots)]
    if terminal is not None:
        selected = [*selected, terminal]
    return selected or [counts[0]]


def _capture_bounds(frontend: dict) -> dict:
    """Transform the actual provider rectangle; never substitute a square bore."""
    local = frontend["accelerator_local_region"]
    if "first_gap_bounds_mm" in local:
        box = local["first_gap_bounds_mm"]
        bounds = {a: {"minimum_mm": float(box[f"{a}_min"]), "maximum_mm": float(box[f"{a}_max"])}
                  for a in "xyz"}
        for item in bounds.values():
            if not math.isfinite(item["minimum_mm"]) or not math.isfinite(item["maximum_mm"]) or item["minimum_mm"] >= item["maximum_mm"]:
                raise ValueError("actual provider first-gap bounds are invalid")
            item["center_mm"] = (item["minimum_mm"] + item["maximum_mm"]) / 2.
            item["full_width_mm"] = item["maximum_mm"] - item["minimum_mm"]
        return bounds
    component = local["accelerator_component"]
    transform = RigidTransform("accelerator_component", frontend["native_frame_id"],
                               component["transform"]["rotation"], component["transform"]["translation_mm"])
    box = local["canonical_electrodes"]["grid_supports"][0]["aperture_box_mm"]
    corners = [transform.transform_position(FramedPosition(
        transform.from_frame_id, tuple(point))).coordinates_mm
        for point in itertools.product(*[(box[f"{a}_min_mm"], box[f"{a}_max_mm"]) for a in "xyz"])]
    bounds = {a: {"minimum_mm": min(p[i] for p in corners), "maximum_mm": max(p[i] for p in corners)}
              for i, a in enumerate("xy")}
    bounds["z"] = {"minimum_mm": min(local["planes"]["repeller"], local["planes"]["grid1"]), "maximum_mm": max(local["planes"]["repeller"], local["planes"]["grid1"])}
    for item in bounds.values():
        item["center_mm"] = (item["minimum_mm"] + item["maximum_mm"]) / 2.
        item["full_width_mm"] = item["maximum_mm"] - item["minimum_mm"]
    return bounds


def _select_pulse(events: list[dict], census: list[dict], times: list[float], frontend: dict) -> dict:
    bounds = _capture_bounds(frontend)
    by_time = {t: [] for t in times}
    observations = {t: [] for t in times}
    for row in census:
        by_time[row["instrument_time_us"]].append(row)
    for row in events:
        if row["event"] == "local_shared_time":
            observations[row["requested_time_us"]].append(row)
    return select_actual_occupancy_pulse(observations, by_time, times, bounds,
                                         frame_id=frontend["native_frame_id"])


def analyze_local_frontend(
    run_directory: Path, log_paths: list[Path], *, phase: str,
    shared_times_us: list[float], pulse_time_us: float | None = None,
) -> dict:
    """Publish loss-complete local evidence from frozen source and native logs."""
    run = Path(run_directory).resolve()
    if phase not in {"discovery", "extraction"}:
        raise ValueError("unknown local analysis phase")
    if not shared_times_us or shared_times_us != sorted(set(shared_times_us)) or any(
        not math.isfinite(t) or t < 0 for t in shared_times_us):
        raise ValueError("declared shared times are invalid")
    if phase == "extraction" and (pulse_time_us is None or not math.isfinite(pulse_time_us)):
        raise ValueError("extraction analysis requires the actual selected pulse time")
    inputs = run / "inputs"
    source = _source_rows(inputs / "release_global.csv")
    frontend = _read(inputs / "frontend_contract.json")
    observer = RigidTransform.from_contract(_read(inputs / "registration.json")["observer_to_mr"])
    if frontend.get("native_frame_id") != "mrtof_global_cartesian" or frontend.get("slow_axis") != "y" or frontend.get("acceleration_direction") != -1:
        raise ValueError("local diagnostics require actual native MR coordinates with acceleration -z")
    if observer.from_frame_id != "mrtof_global_cartesian" or observer.to_frame_id != "mrtof_global_cartesian" or observer.rotation != ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)) or any(observer.translation_mm):
        raise ValueError("native MR records require an identity observer; post-flight rotation is forbidden")
    output = run / "results/local_frontend" / phase
    if output.exists():
        raise ValueError("refuse to overwrite an existing analysis phase")
    events, log_identity = parse_local_logs(log_paths, source)
    lives = _validate_lifetimes(events, source)
    for life in lives.values():
        row = life["exit"]
        if row is not None and (not _close(row["z_mm"], float(frontend["accelerator_local_region"]["planes"]["exit"])) or row["vz_mm_per_us"] >= 0.):
            raise ValueError("exit checkpoint is not the actual forward OA exit plane")
    aperture_census, aperture_summary = _aperture_passages(events, source, lives, frontend)
    census, active, counts = _snapshot_census(events, source, lives, shared_times_us, observer)
    output.mkdir(parents=True)
    _csv(output / "all_native_events.csv", events)
    _csv(output / "aperture_mother_census.csv", aperture_census)
    _write(output / "aperture_passage_summary.json", aperture_summary)
    terminals = [dict(life["terminal"], terminal_class=("exit" if life["exit"] else "timeout" if life["terminal"]["event"] == "local_timeout" else "native_stop_unresolved"))
                 for life in lives.values()]
    _csv(output / "all_mother_terminal_census.csv", terminals)
    _csv(output / "all_losses.csv", [r for r in terminals if r["terminal_class"] != "exit"], list(terminals[0]))
    _csv(output / "all_shared_time_census.csv", census)
    _csv(output / "all_shared_time_status_counts.csv", counts)
    _csv(output / "active_shared_states_mr.csv", active, list(events[0]) + ["frame_id"])
    # Each diagnostic checkpoint describes first forward passage per ID.
    # Recrossings remain verbatim in all_native_events.csv, never extra ions.
    first_checkpoints = {}
    for row in sorted(events, key=lambda r: r["instrument_time_us"]):
        if row["event"] in {"source_release", "local_aperture_pre", "local_aperture_post", "accelerator_grid1_forward", "accelerator_intermediate2_forward", "local_accelerator_exit"}:
            first_checkpoints.setdefault((row["particle_id"], row["event"]), row)
    checkpoints = list(first_checkpoints.values())
    _csv(output / "checkpoints.csv", checkpoints)
    write_checkpoint_evolution_outputs(output / "checkpoints.csv", output / "checkpoint_evolution.png",
                                       output / "checkpoint_evolution_metadata.json", output / "checkpoint_evolution.csv",
                                       frame_id=frontend["native_frame_id"], checkpoint_axes={
                                           "source_release": "y", "local_aperture_pre": "y", "local_aperture_post": "y",
                                           "accelerator_grid1_forward": "z", "accelerator_intermediate2_forward": "z",
                                           "local_accelerator_exit": "z",
                                       })
    exits = [life["exit"] for life in lives.values() if life["exit"]]
    mr_exits = [_observe(row, observer) for row in exits]
    _csv(output / "exit_states_mr.csv", mr_exits, list(events[0]) + ["frame_id"])
    display_counts = select_shared_time_display_counts(counts)
    frame = pd.DataFrame(active, columns=list(events[0]) + ["frame_id"])
    figure, _ = build_local_shared_time_figure(
        frame, display_counts, frame_id=observer.to_frame_id, frontend_contract=frontend,
        terminal_rows=pd.DataFrame(terminals),
    )
    for ext in ("png", "svg"):
        figure.savefig(output / f"shared_time_distributions.{ext}", dpi=190)
    plt.close(figure)
    pulse = _select_pulse(events, census, shared_times_us, frontend) if phase == "discovery" else None
    if pulse is not None:
        _write(output / "pulse_selection.json", pulse)
    mr_stats = _checkpoint_distribution_summary(pd.DataFrame(mr_exits), "local_accelerator_exit", frame_id=frontend["native_frame_id"]) if mr_exits else None
    if mr_stats is not None:
        components = mr_stats.pop("integration_frame_components")
        components.update(frame=observer.to_frame_id, mr_frame_mapping="native_mr_frame")
        mr_stats.update(frame_id=observer.to_frame_id, observer_frame_components=components)
    focus_summary = None
    if phase == "extraction":
        prepared_focus = prepare_local_focus(
            events, source, lives, frontend, _read(inputs / "numerics.json"),
            pulse_time_us=pulse_time_us, source_events_path=output / "all_native_events.csv",
        )
        focus_summary = export_local_focus(prepared_focus, output)
    summary = dict(role="local_frontend_recorded_analysis", phase=phase, mother_count=len(source),
                   exit_count=len(exits), loss_count=len(source)-len(exits),
                   exit_fraction_of_mother=len(exits)/len(source),
                   exit_conditional_population_count=len(exits), actual_pulse_time_us=pulse_time_us,
                   terminal_counts={kind: sum(r["terminal_class"] == kind for r in terminals) for kind in ("exit", "timeout", "native_stop_unresolved")},
                   mr_exit_statistics=mr_stats, aperture_passages=aperture_summary,
                   focus_diagnostics=focus_summary,
                   shared_unsupported_count=sum(r["numerical_unsupported"] for r in counts),
                   selected_pulse_time_us=pulse["selected_time_us"] if pulse else None,
                   scope="Local OA exit only; no detector, MR acceptance or resolving-power qualification")
    _write(output / "summary.json", summary)
    _write(output / "metadata.json", dict(logs=log_identity,
           source=file_record(inputs / "release_global.csv"), frontend=file_record(inputs / "frontend_contract.json"),
           registration=file_record(inputs / "registration.json"), observer=observer.to_contract(),
           shared_times_us=shared_times_us, display_times_us=[r["instrument_time_us"] for r in display_counts],
           display_selection=SHARED_TIME_DISPLAY_SELECTION,
           census_interval="birth inclusive, terminal exclusive; terminal positions never propagated",
           checkpoint_rule="first forward passage per ID; every recrossing retained in all_native_events.csv",
           shared_figure_scaling="common z limits and common transverse limits per row; display aspect ratio only",
           shared_figure_geometry="Frozen canonical electrodes and guide rods in the native MR frame; labelled sections and projections",
           shared_figure_terminals="Cumulative actual terminal anchors; exited, unresolved native stop/splat and timeout use distinct markers; never propagated",
           mother_particle_ids=list(source), mr_exit_ids=[r["particle_id"] for r in mr_exits]))
    return {**summary, "output_paths": [str(p) for p in sorted(output.iterdir()) if p.is_file()]}
