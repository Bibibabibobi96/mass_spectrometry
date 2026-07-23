"""Audit and plot the cumulative RF-to-oaTOF S3 functional chain."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle


PULSE_CONTRACT = re.compile(
    r"handoff_pulse_contract mode=(\d+) time_us=([-+0-9.eE]+) width_us=([-+0-9.eE]+)"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def analyze(source_summary_path: Path, canonical_path: Path, ion_path: Path,
            row_map_path: Path, downstream_path: Path, stdout_path: Path,
            pulse_time_us: float, pulse_width_us: float) -> dict[str, object]:
    source = json.loads(source_summary_path.read_text(encoding="utf-8"))
    canonical = _read_csv(canonical_path)
    mapping = _read_csv(row_map_path)
    downstream = _read_csv(downstream_path)
    ion_rows = [line for line in ion_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not canonical or len({len(canonical), len(mapping), len(downstream), len(ion_rows)}) != 1:
        raise ValueError("S3 downstream state and adapter censuses are inconsistent")
    identities = {(row["frame_id"], row["clock_epoch_id"]) for row in canonical}
    if len(identities) != 1 or any(not value for value in next(iter(identities))):
        raise ValueError("S3 canonical state must bind one non-empty frame and clock epoch")
    frame_id, clock_epoch_id = next(iter(identities))

    solver_ids = {int(row["solver_row_index"]): int(row["particle_id"]) for row in mapping}
    canonical_ids = {int(row["particle_id"]) for row in canonical}
    mapped_ids = set(solver_ids.values())
    detector_rows = [row for row in downstream if math.isfinite(float(row["InstrumentTimeUs"]))]
    hits = [row for row in detector_rows if row["Hit"].strip().lower() == "true"]
    initial_residual = max(
        max(abs(float(result[f"{axis.upper()}0Mm"]) - float(state[f"position_{axis}_mm"])) for axis in "xyz")
        for state, result in zip(canonical, downstream)
    )
    clock_residual = max(
        abs(float(row["InstrumentTimeUs"]) -
            (float(mapping[int(row["Ion"]) - 1]["solver_birth_time_us"]) + float(row["TofUs"])))
        for row in detector_rows
    ) if detector_rows else 0.0
    matches = PULSE_CONTRACT.findall(stdout_path.read_text(encoding="utf-8-sig"))
    pulse_match = len(matches) == 1 and int(matches[0][0]) == 1 and (
        math.isclose(float(matches[0][1]), pulse_time_us, abs_tol=1e-9)
        and math.isclose(float(matches[0][2]), pulse_width_us, abs_tol=1e-12)
    )
    checks = {
        "source_s3_run_succeeded": source["status"] == "success",
        "identity_preserved": canonical_ids == mapped_ids,
        "canonical_position_reaches_simion_exactly": initial_residual <= 1e-12,
        "global_detector_clock_continues": clock_residual <= 1e-9,
        "same_pulse_contract_continues": pulse_match,
        "at_least_one_detector_crossing": len(detector_rows) > 0,
    }
    return {
        "schema_version": 1,
        "role": "rf_to_oatof_s3_end_to_end_function_audit",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "scope": "functional chain only; no convergence, resolution or Formal claim",
        "census": {
            "rf_exit": int(source["source_particles"]),
            "oatof_entry": int(source["oatof_entry_crossings"]),
            "active_at_pulse": int(source["active_at_pulse"]),
            "local_accelerator_exit": len(canonical),
            "detector_crossing": len(detector_rows),
            "detector_hit": len(hits),
        },
        "maximum_simion_initial_position_residual_mm": initial_residual,
        "maximum_detector_clock_residual_us": clock_residual,
        "pulse": {"start_us": pulse_time_us, "width_us": pulse_width_us},
        "frame_id": frame_id,
        "clock_epoch_id": clock_epoch_id,
        "checks": checks,
        "s3_stage_passed": False,
        "resolution_claim_allowed": False,
    }


def plot(result: dict[str, object], downstream_path: Path, output: Path,
         detector_center_x_mm: float, detector_center_y_mm: float,
         detector_radius_mm: float) -> None:
    downstream = _read_csv(downstream_path)
    census = result["census"]
    labels = ["RF exit", "oa entry", "pulse active", "local exit", "detector hit"]
    values = [census[key] for key in (
        "rf_exit", "oatof_entry", "active_at_pulse", "local_accelerator_exit", "detector_hit"
    )]
    figure, axes = plt.subplots(1, 2, figsize=(12.0, 4.8))
    bars = axes[0].bar(labels, values, color=["#2166ac", "#67a9cf", "#fdae61", "#fd8d3c", "#238b45"])
    axes[0].bar_label(bars, padding=3)
    axes[0].set(ylabel="Particles", title="A  Cumulative functional-chain census", ylim=(0, 108))
    axes[0].tick_params(axis="x", rotation=18)
    axes[0].grid(axis="y", alpha=0.22)
    crossings = [row for row in downstream if math.isfinite(float(row["InstrumentTimeUs"]))]
    hits = [row for row in crossings if row["Hit"].strip().lower() == "true"]
    misses = [row for row in crossings if row["Hit"].strip().lower() != "true"]
    if hits:
        axes[1].scatter([float(row["XMm"]) - detector_center_x_mm for row in hits],
                        [float(row["YMm"]) - detector_center_y_mm for row in hits],
                        s=12, color="#238b45", label="hit")
    if misses:
        axes[1].scatter([float(row["XMm"]) - detector_center_x_mm for row in misses],
                        [float(row["YMm"]) - detector_center_y_mm for row in misses],
                        s=16, marker="x", color="#cb181d", label="outside active radius")
    axes[1].add_patch(Circle((0, 0), detector_radius_mm, fill=False, linestyle="--", color="#756bb1"))
    axes[1].set(xlabel="Detector x (mm)", ylabel="Detector y (mm)",
                title=f"B  Detector plane: {len(hits)}/{len(downstream)} hits")
    axes[1].set_aspect("equal", adjustable="box")
    axes[1].grid(alpha=0.22)
    if crossings:
        axes[1].legend(fontsize=8)
    figure.suptitle(
        "RF quadrupole to oaTOF S3 functional connection\n"
        f"frame={result['frame_id']}; clock epoch={result['clock_epoch_id']}"
    )
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, format="png", dpi=190)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-summary", "canonical", "ion", "row-map", "downstream", "stdout", "output", "figure"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--pulse-time-us", type=float, required=True)
    parser.add_argument("--pulse-width-us", type=float, required=True)
    parser.add_argument("--geometry-contract", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.source_summary, args.canonical, args.ion, args.row_map,
                     args.downstream, args.stdout, args.pulse_time_us, args.pulse_width_us)
    geometry = json.loads(args.geometry_contract.read_text(encoding="utf-8"))
    coordinates = geometry["coordinate_convention"]
    plot(result, args.downstream, args.figure, float(coordinates["detector_x"]),
         float(coordinates.get("detector_y", 0.0)), float(geometry["geometry_mm"]["detector_radius"]))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"S3_END_TO_END={result['status']} HITS={result['census']['detector_hit']}")
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
