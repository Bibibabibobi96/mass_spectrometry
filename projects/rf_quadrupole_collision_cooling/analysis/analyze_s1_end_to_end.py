"""Summarize the sparse RF -> physical S1 joint -> oaTOF detector chain."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


FIELDS = ["particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm", "status"]


def read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def analyze(entry_path: Path, local_path: Path, downstream_path: Path, row_map_path: Path,
            events_output: Path) -> dict[str, object]:
    entries, local, downstream, mapping = map(read, (entry_path, local_path, downstream_path, row_map_path))
    if len(entries) != 100 or len(local) != 100:
        raise ValueError("S1 end-to-end analysis requires the complete N=100 upstream census")
    solver_to_particle = {int(row["solver_row_index"]): int(row["particle_id"]) for row in mapping}
    if len(downstream) != len(mapping):
        raise ValueError("SIMION downstream census differs from its row map")
    sparse: list[dict[str, object]] = []
    for row in entries:
        sparse.append({
            "particle_id": int(row["particle_id"]), "event": "rf_exit_entry",
            "instrument_time_us": row["instrument_time_us"], "x_mm": row["position_x_mm"],
            "y_mm": row["position_y_mm"], "z_mm": row["position_z_mm"], "status": "entered_s1",
        })
    for row in local:
        sparse.append({
            "particle_id": int(row["particle_id"]), "event": row["event"],
            "instrument_time_us": row["instrument_time_us"], "x_mm": row["x_mm"],
            "y_mm": row["y_mm"], "z_mm": row["z_mm"], "status": row["status"],
        })
    hits = 0
    for row in downstream:
        solver_index = int(row["Ion"])
        particle_id = solver_to_particle[solver_index]
        hit = row["Hit"].strip().lower() == "true"
        hits += int(hit)
        sparse.append({
            "particle_id": particle_id, "event": "detector_outcome",
            "instrument_time_us": row["InstrumentTimeUs"], "x_mm": row["XMm"],
            "y_mm": row["YMm"], "z_mm": "0", "status": "detector_hit" if hit else "lost",
        })
    events_output.parent.mkdir(parents=True, exist_ok=True)
    with events_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader(); writer.writerows(sparse)
    geometric = sum(row["event"] != "geometric_reject" for row in local)
    exits = sum(row["event"] == "local_joint_exit" for row in local)
    finite_detector_times = sum(math.isfinite(float(row["InstrumentTimeUs"])) for row in downstream)
    checks = {
        "complete_upstream_census": len(entries) == 100 and len(local) == 100,
        "local_exit_census_matches_downstream_input": exits == len(mapping),
        "complete_downstream_census": len(downstream) == len(mapping),
        "minimum_detector_hit": hits >= 1,
    }
    return {
        "schema_version": 1,
        "role": "rf_to_oatof_s1_physical_end_to_end_function_gate",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "rf_exit_particles": 100,
        "physical_port_accepted": geometric,
        "local_joint_exit": exits,
        "simion_downstream_emitted": len(downstream),
        "detector_plane_crossings": finite_detector_times,
        "detector_hits": hits,
        "end_to_end_detector_transmission": hits / 100,
        "downstream_detector_transmission": hits / len(downstream) if downstream else 0.0,
        "sparse_event_rows": len(sparse),
        "dense_trajectories_saved": False,
        "checks": checks,
        "physical_link_claim_allowed": False,
        "resolution_claim_allowed": False,
    }


def plot_funnel(result: dict[str, object], output: Path) -> None:
    labels = ["RF exit", "inside port", "local exit", "detector hit"]
    values = [int(result[key]) for key in (
        "rf_exit_particles", "physical_port_accepted", "local_joint_exit", "detector_hits"
    )]
    colors = ["#2166ac", "#67a9cf", "#fdae61", "#238b45"]
    figure, axis = plt.subplots(figsize=(7.2, 4.6))
    bars = axis.bar(labels, values, color=colors)
    axis.bar_label(bars, labels=[f"{value}/100" for value in values], padding=3)
    axis.set(ylabel="Particles", ylim=(0, 108), title="RF to oaTOF S1 functional-chain census")
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--downstream", type=Path, required=True)
    parser.add_argument("--row-map", type=Path, required=True)
    parser.add_argument("--events-output", type=Path, required=True)
    parser.add_argument("--figure", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.entry, args.local, args.downstream, args.row_map, args.events_output)
    if args.figure is not None:
        plot_funnel(result, args.figure)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"S1_END_TO_END={result['status']} HITS={result['detector_hits']}/100")
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
