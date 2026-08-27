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

from projects.single_reflection_oa_tof_mass_analyzer.analysis.exported_axis_field_integrator import (
    integrate_axis_to_plane_us,
    load_total_axis_field,
)


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


def _local_axis_initial_states(checkpoints: Path) -> tuple[dict[int, tuple[float, float]], float]:
    """Read the exact C3 pre-pulse z/vz states and common local-exit plane."""
    initial: dict[int, tuple[float, float]] = {}
    exit_planes: dict[int, float] = {}
    with checkpoints.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            particle_id = int(row["particle_id"])
            if row.get("event") == "pre_pulse_state":
                if particle_id in initial:
                    raise ValueError(f"duplicate pre_pulse_state for particle {particle_id}")
                initial[particle_id] = (float(row["z_mm"]), float(row["vz_mm_per_us"]))
            elif row.get("event") == "local_accelerator_exit":
                if particle_id in exit_planes:
                    raise ValueError(f"duplicate local_accelerator_exit for particle {particle_id}")
                exit_planes[particle_id] = float(row["z_mm"])
    common = set(initial).intersection(exit_planes)
    if not common:
        raise ValueError("checkpoint table has no local axis paths")
    if set(initial) != common or set(exit_planes) != common:
        raise ValueError("local axis reference may not discard incomplete checkpoint paths")
    values = np.asarray([exit_planes[item] for item in sorted(common)], dtype=float)
    if not np.all(np.isfinite(values)) or np.ptp(values) > 1.0e-9:
        raise ValueError("local_accelerator_exit is not one common axial plane")
    return initial, float(values[0])


def _candidate_species(candidate: Mapping[str, Any]) -> tuple[float, int]:
    source = candidate.get("source_identity", {}).get("frozen_source", {})
    mass_to_charge = float(source.get("mass_to_charge_th", math.nan))
    charge_sign = source.get("charge_sign")
    if not math.isfinite(mass_to_charge) or mass_to_charge <= 0 or charge_sign not in (-1, 1):
        raise ValueError("C3 Candidate lacks a finite signed mass-to-charge identity")
    return mass_to_charge, int(charge_sign)


def _axis_export_field_path(
    scale: float, *, field_run_directory: Path, expected_candidate_bytes: bytes,
    expected_pulse_time_us: float,
) -> Path:
    """Validate one governed field-only run and return its canonical CSV."""
    summary = _load_json(field_run_directory / "summary.json")
    manifest = _load_json(field_run_directory / "run_manifest.json")
    if summary.get("status") != "success" or manifest.get("status") != "success":
        raise ValueError(f"{_scale_key(scale)} axis export is not a successful immutable record")
    if summary.get("execution_mode") != "program_axis_field_export":
        raise ValueError(f"{_scale_key(scale)} run is not a top-level total-axis-field export")
    configuration = _load_json(field_run_directory / "run_config.json")
    actual_pulse = float(configuration.get("parameters", {}).get("pulse_time_us", math.nan))
    if not math.isfinite(actual_pulse) or not math.isclose(
        actual_pulse, expected_pulse_time_us, rel_tol=0.0, abs_tol=1.0e-10
    ):
        raise ValueError(f"{_scale_key(scale)} axis export uses a different effective pulse")
    candidate_path = field_run_directory / "inputs" / "three_zone_t5_candidate_resolved.json"
    if not candidate_path.is_file() or candidate_path.read_bytes() != expected_candidate_bytes:
        raise ValueError(f"{_scale_key(scale)} axis export is not bound to its real-PA Candidate")
    path = field_run_directory / "results" / "total_axis_field.csv"
    if not path.is_file():
        raise ValueError(f"{_scale_key(scale)} axis export lacks total_axis_field.csv")
    return path


def build_c3_axis_reference(
    *, runs: Mapping[float, Path], axis_field_runs: Mapping[float, Path],
    dt_us_values: tuple[float, ...] = (1.0e-4, 5.0e-5, 2.5e-5),
) -> dict[str, Any]:
    """Build the detector-blind C3 1D reference from five governed field exports.

    Every integration begins from the recorded pre-pulse state of the same
    particle in the matching real-PA run and stops at that run's declared
    local accelerator-exit plane.  This is deliberately not a whole-flight
    surrogate.  The smallest two time steps must agree within one percent
    before their central derivative can be compared with real PA.
    """
    if set(runs) != set(SCALES) or set(axis_field_runs) != set(SCALES):
        raise ValueError("C3 axis reference requires exactly five real and five field-export scales")
    if len(dt_us_values) < 2 or any(
        not math.isfinite(value) or value <= 0 for value in dt_us_values
    ) or any(right >= left for left, right in zip(dt_us_values, dt_us_values[1:])):
        raise ValueError("axis reference time steps must be strictly decreasing positive values")
    observations = {scale: _run_observation(scale, Path(runs[scale])) for scale in SCALES}
    pulses = {item["pulse_time_us"] for item in observations.values()}
    if len(pulses) != 1:
        raise ValueError("C3 real-PA points use different effective pulse times")
    reference_times: dict[float, dict[float, np.ndarray]] = {}
    field_bindings: dict[str, str] = {}
    species: tuple[float, int] | None = None
    for scale in SCALES:
        real_directory = Path(runs[scale])
        candidate_path = real_directory / "inputs" / "three_zone_t5_candidate_resolved.json"
        candidate_bytes = candidate_path.read_bytes()
        candidate = _load_json(candidate_path)
        candidate_species = _candidate_species(candidate)
        if species is None:
            species = candidate_species
        elif candidate_species != species:
            raise ValueError("C3 field-reference candidates use different species identities")
        field_path = _axis_export_field_path(
            scale, field_run_directory=Path(axis_field_runs[scale]),
            expected_candidate_bytes=candidate_bytes,
            expected_pulse_time_us=next(iter(pulses)),
        )
        field = load_total_axis_field(field_path)
        states, exit_plane = _local_axis_initial_states(
            real_directory / "results" / "single_flight_particle_checkpoints.csv"
        )
        expected_ids = set(observations[scale]["local_accelerator_segment_times_ns"])
        if set(states) != expected_ids:
            raise ValueError(f"{_scale_key(scale)} C3 axis state cohort differs from real-PA local cohort")
        values_by_dt: dict[float, np.ndarray] = {}
        assert species is not None
        for dt_us in dt_us_values:
            values_by_dt[dt_us] = np.asarray([
                integrate_axis_to_plane_us(
                    field, z0_mm=states[particle_id][0],
                    vz0_mm_per_us=states[particle_id][1], z_stop_mm=exit_plane,
                    mass_th=species[0], charge_state=species[1], dt_us=dt_us,
                ) * 1000.0
                for particle_id in sorted(expected_ids)
            ], dtype=float)
        reference_times[scale] = values_by_dt
        field_bindings[_scale_key(scale)] = str(field_path.resolve())
    derivatives: dict[float, float] = {}
    for dt_us in dt_us_values:
        derivatives[dt_us] = float(np.mean(
            (reference_times[2.0][dt_us] - reference_times[-2.0][dt_us]) / 4.0
        ))
    finest, next_finest = dt_us_values[-1], dt_us_values[-2]
    finest_derivative = derivatives[finest]
    if finest_derivative == 0.0:
        raise ValueError("C3 axis reference derivative is zero and cannot support a relative comparison")
    convergence_error = abs(derivatives[next_finest] - finest_derivative) / abs(finest_derivative)
    return {
        "role": "paper1_c3_j3_exported_axis_field_reference",
        "claim_limit": "Local pre-pulse-to-local-exit 1D reference only; no detector, peak-width, transmission, optimization, Candidate, Formal, or multi-mass claim.",
        "axis_field_runs": {_scale_key(scale): str(Path(axis_field_runs[scale]).resolve()) for scale in SCALES},
        "axis_field_csv": field_bindings,
        "mass_to_charge_th": species[0] if species is not None else None,
        "charge_state": species[1] if species is not None else None,
        "dt_us_values": list(dt_us_values),
        "central_derivative_ns_per_h_by_dt_us": {str(dt_us): derivatives[dt_us] for dt_us in dt_us_values},
        "axis_reference_derivative_ns_per_h": finest_derivative,
        "finest_pair_relative_difference": convergence_error,
        "dt_converged_le_1_percent": convergence_error <= 0.01,
    }


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
    parser.add_argument(
        "--axis-field-run", action="append", metavar="SCALE=PATH",
        help="matching governed BuildOnly program_axis_field_export run; supply all five or none",
    )
    parser.add_argument(
        "--axis-reference-dt-us", action="append", type=float,
        help="strictly decreasing 1D RK4 steps; default is 1e-4, 5e-5, 2.5e-5 us",
    )
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
    axis_runs: dict[float, Path] = {}
    for item in args.axis_field_run or []:
        key, separator, value = item.partition("=")
        if not separator:
            parser.error("--axis-field-run must be SCALE=PATH")
        scale = float(key)
        if scale in axis_runs:
            parser.error("--axis-field-run repeats a scale")
        axis_runs[scale] = Path(value)
    if args.axis_reference_dt_us and not axis_runs:
        parser.error("--axis-reference-dt-us requires all five --axis-field-run values")
    axis_reference: dict[str, Any] | None = None
    axis_derivative = args.axis_reference_derivative_ns_per_h
    if axis_runs:
        if axis_derivative is not None:
            parser.error("provide either governed --axis-field-run values or a scalar axis reference, not both")
        axis_reference = build_c3_axis_reference(
            runs=runs, axis_field_runs=axis_runs,
            dt_us_values=tuple(args.axis_reference_dt_us or (1.0e-4, 5.0e-5, 2.5e-5)),
        )
        axis_derivative = float(axis_reference["axis_reference_derivative_ns_per_h"])
    result = analyze_c3_real_field_platform(
        runs=runs, bootstrap_seed=args.bootstrap_seed,
        bootstrap_replicates=args.bootstrap_replicates,
        axis_reference_derivative_ns_per_h=axis_derivative,
    )
    if axis_reference is not None:
        result["axis_reference"] = axis_reference
        result["metrics"]["gates"]["axis_reference_dt_converged_le_1_percent"] = bool(
            axis_reference["dt_converged_le_1_percent"]
        )
        if not axis_reference["dt_converged_le_1_percent"]:
            result["conclusion"] = "INCONCLUSIVE_REVISE"
            result["failures"].append("axis_reference_dt_converged_le_1_percent")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
