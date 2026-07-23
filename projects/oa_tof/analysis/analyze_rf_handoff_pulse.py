"""Evaluate and visualize the shared-clock oaTOF extraction-pulse test."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from statistics import fmean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from rf_handoff_adapter import ordered_solver_identity_map


NUMBER = r"[-+0-9.eE]+"
PULSE_CONTRACT_RE = re.compile(
    rf"TRACE: handoff_pulse_contract mode=1 time_us=(?P<time>{NUMBER}) "
    rf"width_us=(?P<width>{NUMBER})"
)
PULSE_RE = re.compile(
    rf"TRACE: handoff_pulse_on ion=(?P<ion>\d+) instrument_time_us=(?P<time>{NUMBER}) "
    rf"x_mm=(?P<x>{NUMBER}) y_mm=(?P<y>{NUMBER}) z_mm=(?P<z>{NUMBER}) "
    rf"vx_mm_per_us=(?P<vx>{NUMBER}) vy_mm_per_us=(?P<vy>{NUMBER}) "
    rf"vz_mm_per_us=(?P<vz>{NUMBER})"
)
TERMINAL_RE = re.compile(
    rf"TRACE: handoff_terminal_raw ion=(?P<ion>\d+) instance=(?P<instance>\d+) "
    rf"instrument_time_us=(?P<time>{NUMBER}) x_mm=(?P<x>{NUMBER}) "
    rf"y_mm=(?P<y>{NUMBER}) z_mm=(?P<z>{NUMBER}) "
    rf"vx_mm_per_us=(?P<vx>{NUMBER}) vy_mm_per_us=(?P<vy>{NUMBER}) "
    rf"vz_mm_per_us=(?P<vz>{NUMBER})"
)
EVENT_FIELDS = [
    "particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm",
    "vx_m_s", "vy_m_s", "vz_m_s", "status",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict[str, str]]) -> dict[str, float | int | None]:
    hits = [row for row in rows if row["Hit"].lower() == "true"]
    tofs = [float(row["TofUs"]) for row in hits]
    return {
        "emitted": len(rows),
        "hits": len(hits),
        "transmission": len(hits) / len(rows) if rows else 0.0,
        "mean_local_tof_us": fmean(tofs) if tofs else None,
        "tof_standard_deviation_us": (
            math.sqrt(sum((value - fmean(tofs)) ** 2 for value in tofs) / (len(tofs) - 1))
            if len(tofs) > 1 else None
        ),
    }


def parse_log(path: Path) -> tuple[float, float, dict[int, dict[str, float]], dict[int, dict[str, float]]]:
    pulse_time = pulse_width = None
    pulse_states: dict[int, dict[str, float]] = {}
    terminal_states: dict[int, dict[str, float]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = PULSE_CONTRACT_RE.search(line)
        if match:
            pulse_time, pulse_width = float(match["time"]), float(match["width"])
        match = PULSE_RE.search(line)
        if match:
            pulse_states[int(match["ion"])] = {key: float(match[key]) for key in (
                "time", "x", "y", "z", "vx", "vy", "vz"
            )}
        match = TERMINAL_RE.search(line)
        if match:
            terminal_states[int(match["ion"])] = {
                **{key: float(match[key]) for key in ("time", "x", "y", "z", "vx", "vy", "vz")},
                "instance": int(match["instance"]),
            }
    if pulse_time is None or pulse_width is None:
        raise ValueError("Timed log does not contain the pulse contract")
    return pulse_time, pulse_width, pulse_states, terminal_states


def build_events(
    canonical_rows: list[dict[str, str]], row_map_rows: list[dict[str, str]],
    timed_rows: list[dict[str, str]],
    pulse_states: dict[int, dict[str, float]], terminal_states: dict[int, dict[str, float]],
) -> tuple[list[dict[str, object]], dict[int, str]]:
    solver_to_particle = ordered_solver_identity_map(canonical_rows, row_map_rows)
    outcomes: dict[int, str] = {}
    for row in timed_rows:
        solver_row = int(row["Ion"])
        if solver_row not in solver_to_particle:
            raise ValueError("timed result contains a solver row absent from row_map")
        particle_id = solver_to_particle[solver_row]
        if particle_id in outcomes:
            raise ValueError("timed result contains a duplicate solver particle")
        outcomes[particle_id] = (
            "detector_hit" if row["Hit"].lower() == "true" else "lost"
        )
    if len(outcomes) != len(canonical_rows):
        raise ValueError("timed result does not contain a complete particle census")
    pulse_by_particle = {
        solver_to_particle[solver_row]: state
        for solver_row, state in pulse_states.items()
        if solver_row in solver_to_particle
    }
    terminal_by_particle = {
        solver_to_particle[solver_row]: state
        for solver_row, state in terminal_states.items()
        if solver_row in solver_to_particle
    }
    unknown_log_rows = (
        set(pulse_states) | set(terminal_states)
    ).difference(solver_to_particle)
    if unknown_log_rows:
        raise ValueError("pulse log contains a solver row absent from row_map")
    events: list[dict[str, object]] = []
    for row in canonical_rows:
        particle_id = int(row["particle_id"])
        events.append({
            "particle_id": particle_id, "event": "effective_entry",
            "instrument_time_us": float(row["instrument_time_us"]),
            "x_mm": float(row["position_x_mm"]), "y_mm": float(row["position_y_mm"]),
            "z_mm": float(row["position_z_mm"]), "vx_m_s": float(row["velocity_x_m_s"]),
            "vy_m_s": float(row["velocity_y_m_s"]), "vz_m_s": float(row["velocity_z_m_s"]),
            "status": "entered",
        })
        pulse = pulse_by_particle.get(particle_id)
        if pulse:
            events.append({
                "particle_id": particle_id, "event": "pulse_on",
                "instrument_time_us": pulse["time"], "x_mm": pulse["x"],
                "y_mm": pulse["y"], "z_mm": pulse["z"],
                "vx_m_s": pulse["vx"] * 1000.0, "vy_m_s": pulse["vy"] * 1000.0,
                "vz_m_s": pulse["vz"] * 1000.0, "status": "exposed_to_pulse",
            })
        terminal = terminal_by_particle.get(particle_id)
        if terminal:
            events.append({
                "particle_id": particle_id, "event": "terminal",
                "instrument_time_us": terminal["time"], "x_mm": terminal["x"],
                "y_mm": terminal["y"], "z_mm": terminal["z"],
                "vx_m_s": terminal["vx"] * 1000.0, "vy_m_s": terminal["vy"] * 1000.0,
                "vz_m_s": terminal["vz"] * 1000.0, "status": outcomes[particle_id],
            })
    return events, outcomes


def plot_timeline(
    events: list[dict[str, object]], outcomes: dict[int, str], pulse_time: float,
    pulse_width: float, output: Path,
) -> None:
    by_particle: dict[int, dict[str, dict[str, object]]] = {}
    for row in events:
        by_particle.setdefault(int(row["particle_id"]), {})[str(row["event"])] = row
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = {"detector_hit": "#238b45", "lost": "#d95f0e"}
    for particle_id, particle_events in sorted(by_particle.items()):
        entry = particle_events["effective_entry"]
        terminal = particle_events.get("terminal")
        color = colors[outcomes[particle_id]]
        if terminal:
            ax.plot([entry["instrument_time_us"], terminal["instrument_time_us"]],
                    [particle_id, particle_id], color=color, alpha=0.22, linewidth=0.8)
            marker = "o" if outcomes[particle_id] == "detector_hit" else "x"
            ax.scatter(terminal["instrument_time_us"], particle_id, color=color, marker=marker, s=14)
        ax.scatter(entry["instrument_time_us"], particle_id, color="#2166ac", marker="|", s=22)
    ax.axvspan(pulse_time, pulse_time + pulse_width, color="#756bb1", alpha=0.25)
    ax.set(xlabel="Instrument time (us)", ylabel="Particle ID",
           title="RF handoff arrival, shared extraction pulse, and terminal outcome")
    ax.grid(alpha=0.2)
    ax.legend(handles=[
        Line2D([], [], color="#2166ac", marker="|", linestyle="None", markersize=9,
               label="effective entry"),
        Line2D([], [], color=colors["detector_hit"], marker="o", linestyle="None",
               label="detector hit"),
        Line2D([], [], color=colors["lost"], marker="x", linestyle="None", label="lost"),
        Patch(facecolor="#756bb1", alpha=0.25, label=f"extraction pulse ({pulse_width:g} us)"),
    ], loc="upper right")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_snapshot(
    events: list[dict[str, object]], outcomes: dict[int, str], pulse_time: float, output: Path,
) -> None:
    pulse_rows = [row for row in events if row["event"] == "pulse_on"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    for outcome, label, color, marker in (
        ("detector_hit", "detector hit", "#238b45", "o"),
        ("lost", "lost", "#d95f0e", "x"),
    ):
        rows = [row for row in pulse_rows if outcomes[int(row["particle_id"])] == outcome]
        axes[0].scatter([row["x_mm"] for row in rows], [row["z_mm"] for row in rows],
                        label=label, color=color, marker=marker, s=22, alpha=0.8)
        axes[1].scatter([row["y_mm"] for row in rows], [row["z_mm"] for row in rows],
                        label=label, color=color, marker=marker, s=22, alpha=0.8)
    axes[0].set(xlabel="x (mm)", ylabel="z (mm)", title="Extraction plane view (x-z)")
    axes[1].set(xlabel="y (mm)", ylabel="z (mm)", title="Transverse view (y-z)")
    for ax in axes:
        ax.grid(alpha=0.2)
    axes[1].legend(loc="best")
    fig.suptitle(f"Particle distribution at pulse onset, t = {pulse_time:.6f} us")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def analyze(
    timed_path: Path, control_path: Path, canonical_path: Path, row_map_path: Path,
    mode_path: Path,
    pulse_log: Path, events_output: Path, timeline_output: Path, snapshot_output: Path,
) -> dict:
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    timed_rows, control_rows = read_csv(timed_path), read_csv(control_path)
    timed, control = summarize(timed_rows), summarize(control_rows)
    pulse_time, pulse_width, pulse_states, terminal_states = parse_log(pulse_log)
    events, outcomes = build_events(
        read_csv(canonical_path), read_csv(row_map_path), timed_rows,
        pulse_states, terminal_states,
    )
    write_csv(events_output, events)
    plot_timeline(events, outcomes, pulse_time, pulse_width, timeline_output)
    plot_snapshot(events, outcomes, pulse_time, snapshot_output)
    acceptance = mode["acceptance"]
    checks = {
        "minimum_particles": timed["emitted"] >= int(acceptance["minimum_particles"]),
        "timed_pulse_transmission": timed["transmission"] >= float(
            acceptance["minimum_timed_pulse_detector_transmission"]
        ),
        "gain_over_held_off_control": timed["transmission"] - control["transmission"] >= float(
            acceptance["minimum_transmission_gain_over_held_off_control"]
        ),
        "minimum_pulse_event_fraction": len(pulse_states) / timed["emitted"] >= float(
            acceptance["minimum_pulse_event_fraction"]
        ),
        "complete_terminal_census": len(terminal_states) == timed["emitted"],
        "pulse_states_include_velocity": len(pulse_states) > 0,
    }
    return {
        "schema_version": 2,
        "role": "oa_tof_rf_handoff_shared_clock_pulse_test",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "timed_pulse": timed,
        "held_off_control": control,
        "transmission_gain": timed["transmission"] - control["transmission"],
        "pulse": {"instrument_time_us": pulse_time, "width_us": pulse_width},
        "pulse_event_count": len(pulse_states),
        "sparse_event_table": {
            "rows": len(events), "particles": timed["emitted"],
            "events": ["effective_entry", "pulse_on", "terminal"],
            "dense_trajectories_saved": False,
        },
        "checks": checks,
        "functional_link_scope": "time-ordered projected RF-COMSOL entry with continuous pre/post trajectories through one shared-clock finite oaTOF extraction pulse",
        "physical_link_claim_allowed": False,
        "resolution_claim_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timed", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--row-map", type=Path, required=True)
    parser.add_argument("--mode", type=Path, required=True)
    parser.add_argument("--pulse-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--events-output", type=Path, required=True)
    parser.add_argument("--timeline-output", type=Path, required=True)
    parser.add_argument("--snapshot-output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(
        args.timed, args.control, args.canonical, args.row_map, args.mode, args.pulse_log,
        args.events_output, args.timeline_output, args.snapshot_output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"RF_HANDOFF_PULSE={result['status']} "
        f"TIMED={result['timed_pulse']['hits']}/{result['timed_pulse']['emitted']} "
        f"CONTROL={result['held_off_control']['hits']}/{result['held_off_control']['emitted']}"
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
