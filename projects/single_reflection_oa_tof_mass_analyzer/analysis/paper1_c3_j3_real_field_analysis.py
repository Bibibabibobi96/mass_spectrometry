"""Analyze the frozen C3 J3 real-PA five-point derivative platform.

The analyzer is deliberately detector-blind with respect to candidate choice:
it accepts all five pre-registered points, validates their full source cohort
and event topology, and calculates only paired finite differences.  A separate
exported-axis-field integrator may provide a reference derivative later; until
then this module reports an explicit incomplete stage rather than a pass.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np


SCALES = (-2.0, -1.0, 0.0, 1.0, 2.0)
EVENTS = (
    "pre_pulse_state",
    "accelerator_grid1_forward",
    "accelerator_intermediate2_forward",
    "local_accelerator_exit",
    "accelerator_focus_forward",
    "reflectron_entrance_forward",
    "reflectron_midgrid_forward",
    "reflectron_turning_point",
    "reflectron_exit_return",
    "detector_crossing",
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _scale_key(value: float) -> str:
    return f"{value:+.0f}h"


def _local_accelerator_segment_times_ns(checkpoints: Path) -> dict[int, float]:
    """Return pre-pulse to local-exit elapsed time for particles with both events."""
    pre_pulse: dict[int, float] = {}
    local_exit: dict[int, float] = {}
    with checkpoints.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            particle_id = int(row["particle_id"])
            event = row.get("event")
            target = pre_pulse if event == "pre_pulse_state" else (
                local_exit if event == "local_accelerator_exit" else None
            )
            if target is not None:
                if particle_id in target:
                    raise ValueError(f"duplicate {event} for particle {particle_id}")
                target[particle_id] = float(row["instrument_time_us"])
    common = set(pre_pulse).intersection(local_exit)
    if not common:
        raise ValueError("checkpoint table has no complete pre-pulse to local-exit paths")
    return {particle_id: (local_exit[particle_id] - pre_pulse[particle_id]) * 1000.0 for particle_id in common}


def _event_particle_ids(checkpoints: Path) -> dict[str, set[int]]:
    result = {event: set() for event in EVENTS}
    with checkpoints.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            event = row.get("event")
            if event in result:
                result[event].add(int(row["particle_id"]))
    return result


def _run_observation(scale: float, run_directory: Path) -> dict[str, Any]:
    summary = _load_json(run_directory / "summary.json")
    manifest = _load_json(run_directory / "run_manifest.json")
    if summary.get("status") != "success" or manifest.get("status") != "success":
        raise ValueError(f"{_scale_key(scale)} run is not a successful immutable record")
    candidate = _load_json(run_directory / "inputs" / "three_zone_t5_candidate_resolved.json")
    evidence = candidate.get("c3_j3_evidence")
    if not isinstance(evidence, Mapping) or float(evidence.get("scale_h", math.nan)) != scale:
        raise ValueError(f"{_scale_key(scale)} run is not bound to its C3 candidate")
    census = summary.get("census")
    if not isinstance(census, Mapping):
        raise ValueError(f"{_scale_key(scale)} run lacks its census")
    for event in EVENTS:
        if int(census.get(event, -1)) < 0:
            raise ValueError(f"{_scale_key(scale)} census lacks {event}")
    pulse_time_us = float(summary["pulse_effective_time_us"])
    checkpoints = run_directory / "results" / "single_flight_particle_checkpoints.csv"
    event_ids = _event_particle_ids(checkpoints)
    return {
        "run_directory": str(run_directory.resolve()),
        "summary": summary,
        "census": {event: int(census[event]) for event in EVENTS},
        "pulse_time_us": pulse_time_us,
        "local_accelerator_segment_times_ns": _local_accelerator_segment_times_ns(checkpoints),
        "event_particle_ids": event_ids,
    }


def _bootstrap_mean_difference(
    first: np.ndarray, second: np.ndarray, *, seed: int, replicates: int,
) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    values = np.empty(replicates, dtype=float)
    for index in range(replicates):
        sample = generator.integers(0, first.size, first.size)
        values[index] = float(np.mean(first[sample] - second[sample]))
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def analyze_c3_real_field_platform(
    *, runs: Mapping[float, Path], bootstrap_seed: int = 20260825,
    bootstrap_replicates: int = 400, axis_reference_derivative_ns_per_h: float | None = None,
) -> dict[str, Any]:
    """Return the paired C3 five-point platform and its guarded conclusion."""

    if set(runs) != set(SCALES):
        raise ValueError("C3 requires exactly the -2h, -h, 0, +h, +2h run set")
    observations = {scale: _run_observation(scale, Path(runs[scale])) for scale in SCALES}
    pulses = {item["pulse_time_us"] for item in observations.values()}
    if len(pulses) != 1:
        raise ValueError("C3 points use different effective pulse times")
    segment_sets = {scale: set(item["local_accelerator_segment_times_ns"]) for scale, item in observations.items()}
    first = segment_sets[-2.0]
    if any(ids != first for ids in segment_sets.values()):
        raise ValueError("C3 points do not retain the same local accelerator cohort")
    topology_stable = all(
        item["event_particle_ids"] == observations[0.0]["event_particle_ids"]
        for item in observations.values()
    )
    particle_ids = np.asarray(sorted(first), dtype=int)
    arrival = {
        scale: np.asarray([observations[scale]["local_accelerator_segment_times_ns"][particle_id] for particle_id in particle_ids])
        for scale in SCALES
    }
    one_h = (arrival[1.0] - arrival[-1.0]) / 2.0
    two_h = (arrival[2.0] - arrival[-2.0]) / 4.0
    mean_one_h, mean_two_h = float(np.mean(one_h)), float(np.mean(two_h))
    platform_error = abs(mean_one_h - mean_two_h) / max(abs(mean_two_h), 1.0e-15)
    confidence_interval = _bootstrap_mean_difference(
        one_h, two_h, seed=bootstrap_seed, replicates=bootstrap_replicates,
    )
    reference_error: float | None = None
    if axis_reference_derivative_ns_per_h is not None:
        if not math.isfinite(axis_reference_derivative_ns_per_h) or axis_reference_derivative_ns_per_h == 0.0:
            raise ValueError("axis reference derivative must be finite and nonzero")
        reference_error = abs(mean_two_h - axis_reference_derivative_ns_per_h) / abs(axis_reference_derivative_ns_per_h)
    gates = {
        "same_effective_pulse": True,
        "same_local_accelerator_cohort": True,
        "event_topology_stable": topology_stable,
        "paired_step_platform_le_5_percent": platform_error <= 0.05,
        "independent_axis_reference_supplied": reference_error is not None,
        "three_dimensional_vs_axis_derivative_le_5_percent": reference_error is not None and reference_error <= 0.05,
    }
    conclusion = "PASS_CONTINUE" if all(gates.values()) else "INCONCLUSIVE_REVISE"
    failures = [name for name, passed in gates.items() if not passed]
    return {
        "stage_id": "C3_J3",
        "conclusion": conclusion,
        "claim_limit": "Real-PA local derivative platform only; no peak-width, transmission, optimization, Candidate, Formal, or multi-mass claim.",
        "inputs": {
            "runs": {_scale_key(scale): observations[scale]["run_directory"] for scale in SCALES},
            "bootstrap_seed": bootstrap_seed,
            "bootstrap_replicates": bootstrap_replicates,
            "axis_reference_derivative_ns_per_h": axis_reference_derivative_ns_per_h,
        },
        "metrics": {
            "effective_pulse_time_us": next(iter(pulses)),
            "common_local_accelerator_particle_count": int(particle_ids.size),
            "event_census_by_scale": {_scale_key(scale): observations[scale]["census"] for scale in SCALES},
            "event_topology_stable": topology_stable,
            "local_accelerator_segment_central_difference_ns_per_h": {
                "plus_minus_h_mean": mean_one_h,
                "plus_minus_2h_mean": mean_two_h,
                "plus_minus_h_sample_sigma": float(np.std(one_h, ddof=1)),
                "plus_minus_2h_sample_sigma": float(np.std(two_h, ddof=1)),
                "mean_difference_bootstrap_95pct_ns_per_h": list(confidence_interval),
                "step_platform_relative_error": platform_error,
                "axis_reference_relative_error": reference_error,
            },
            "gates": gates,
        },
        "claims_supported": [
            "The pre-registered real-PA C3 five-point family has a stable paired pre-pulse-to-local-exit derivative and unchanged observed event topology."
        ],
        "claims_prohibited": [
            "Peak-width, resolution, transmission, optimization, structure-superiority, Candidate, Formal, or multi-mass claims.",
            "Any C3 pass claim before an independent exported-axis-field derivative is supplied and compared."
        ],
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, metavar="SCALE=PATH")
    parser.add_argument("--axis-reference-derivative-ns-per-h", type=float)
    parser.add_argument("--bootstrap-seed", type=int, default=20260825)
    parser.add_argument("--bootstrap-replicates", type=int, default=400)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    runs: dict[float, Path] = {}
    for item in args.run:
        key, separator, value = item.partition("=")
        if not separator:
            parser.error("--run must be SCALE=PATH")
        scale = float(key)
        if scale in runs:
            parser.error("--run repeats a scale")
        runs[scale] = Path(value)
    result = analyze_c3_real_field_platform(
        runs=runs, bootstrap_seed=args.bootstrap_seed,
        bootstrap_replicates=args.bootstrap_replicates,
        axis_reference_derivative_ns_per_h=args.axis_reference_derivative_ns_per_h,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
