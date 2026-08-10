"""Aggregate exact-union SIMION particle batches using global particle IDs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import compute_peak_metrics


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def aggregate(
    run_roots: list[Path],
    selection_receipt_path: Path,
    checkpoints_output: Path,
    summary_output: Path,
    mass_amu: float = 100.0,
) -> dict[str, Any]:
    receipt = _load(selection_receipt_path)
    expected_batches = receipt["execution_batches"]
    if len(run_roots) != receipt["execution_batch_count"] or len(run_roots) != 5:
        raise ValueError("N=1000 aggregation requires the governed five batches")
    if receipt["physics_scope"]["collisions_enabled"] or receipt["physics_scope"]["space_charge_enabled"]:
        raise ValueError("independent-batch equivalence requires collisions and space charge disabled")
    combined: list[dict[str, str]] = []
    summaries: list[dict[str, Any]] = []
    fieldnames: list[str] | None = None
    geometry_hashes: set[str] = set()
    pulse_times: set[float] = set()
    for run_root, expected in zip(run_roots, expected_batches, strict=True):
        source_path = run_root / "inputs/mother_particle_source.csv"
        if file_sha256(source_path) != expected["sha256"]:
            raise ValueError("batch mother source differs from selection receipt")
        summary = _load(run_root / "summary.json")
        if summary["status"] != "success" or summary["census"]["launched"] != expected["particle_count"]:
            raise ValueError("batch summary status or count differs")
        summaries.append(summary)
        run_config = _load(run_root / "run_config.json")
        clock_basis = run_config["parameters"].get(
            "clock_basis", "legacy_relative_time"
        )
        if clock_basis not in {"legacy_relative_time", "absolute_birth_time"}:
            raise ValueError("batch clock basis differs")
        geometry_hashes.add(file_sha256(run_root / "inputs/oatof_resolved_geometry.json"))
        pulse_times.add(round(float(summary["pulse_first_observed_us"]), 9))
        offset = int(expected["global_particle_id_offset"])
        batch_rows: list[dict[str, str]] = []
        with (run_root / "results/single_flight_particle_checkpoints.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            if fieldnames is None:
                fieldnames = list(reader.fieldnames or [])
            elif reader.fieldnames != fieldnames:
                raise ValueError("batch checkpoint columns differ")
            for row in reader:
                batch_rows.append(row)
        if (
            clock_basis == "absolute_birth_time"
            and summary.get("detector_time_basis") != "instrument_time_us"
        ):
            birth_times = {
                int(row["particle_id"]): float(row["instrument_time_us"])
                for row in batch_rows
                if row["event"] == "source_release"
            }
            for row in batch_rows:
                if row["event"] == "detector_crossing":
                    particle_id = int(row["particle_id"])
                    if particle_id not in birth_times:
                        raise ValueError(
                            "absolute detector clock correction lacks source release"
                        )
                    row["instrument_time_us"] = format(
                        float(row["instrument_time_us"])
                        + birth_times[particle_id],
                        ".17g",
                    )
        for row in batch_rows:
            row["particle_id"] = str(int(row["particle_id"]) + offset)
            combined.append(row)
    if len(geometry_hashes) != 1 or len(pulse_times) != 1:
        raise ValueError("batch geometry or fixed pulse phase differs")
    combined.sort(key=lambda row: (int(row["particle_id"]), row["event"]))
    checkpoints_output.parent.mkdir(parents=True, exist_ok=True)
    with checkpoints_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(combined)
    census_keys = summaries[0]["census"].keys()
    census = {key: sum(int(summary["census"][key]) for summary in summaries) for key in census_keys}
    capture_keys = summaries[0]["pulse_capture"]["counts"].keys()
    capture_counts = {
        key: sum(int(summary["pulse_capture"]["counts"][key]) for summary in summaries)
        for key in capture_keys
    }
    detector_times = np.asarray([
        float(row["instrument_time_us"])
        for row in combined if row["event"] == "detector_crossing"
    ])
    peak = compute_peak_metrics(detector_times, mass_amu)[0] if len(detector_times) >= 3 else None
    eligible = capture_counts["eligible"]
    detected_eligible = sum(int(summary["pulse_capture"]["detected_eligible_count"]) for summary in summaries)
    result = {
        "schema_version": 1,
        "role": "rf_oatof_batched_single_flight_aggregate",
        "status": "success",
        "batching": {
            "batch_count": 5,
            "particles_per_batch": 200,
            "global_particle_ids_contiguous": sorted({int(row["particle_id"]) for row in combined if row["event"] == "source_release"}) == list(range(1, 1001)),
            "same_geometry_sha256": next(iter(geometry_hashes)),
            "same_fixed_pulse_time_us": next(iter(pulse_times)),
            "pa_reuse_policy": "content_addressed_warm_once_then_read_only",
            "equivalent_to_single_fly_under_declared_physics": True,
        },
        "selection_receipt_sha256": file_sha256(selection_receipt_path),
        "census": census,
        "transmission": {
            "multipole_handoff_fraction": census["multipole_handoff"] / census["launched"],
            "detector_fraction": census["detector_crossing"] / census["launched"],
        },
        "pulse_capture": {
            "counts": capture_counts,
            "capture_fraction_of_launched": eligible / census["launched"],
            "detected_eligible_count": detected_eligible,
            "conditional_detector_efficiency": detected_eligible / eligible if eligible else None,
            "selection_uses_detector_outcome": False,
        },
        "instrument_clock_peak": peak,
        "detector_time_basis": "instrument_time_us",
        "instrument_clock_peak_is_resolution_claim": False,
        "checkpoints_sha256": file_sha256(checkpoints_output),
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", action="append", required=True, type=Path)
    parser.add_argument("--selection-receipt", required=True, type=Path)
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--mass-amu", type=float, default=100.0)
    args = parser.parse_args()
    summary = aggregate(args.run_root, args.selection_receipt, args.checkpoints, args.summary, args.mass_amu)
    print(
        "BATCHED_SINGLE_FLIGHT_AGGREGATE=PASS "
        f"DETECTOR={summary['census']['detector_crossing']}/{summary['census']['launched']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
