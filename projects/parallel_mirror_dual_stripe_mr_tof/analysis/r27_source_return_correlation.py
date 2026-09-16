"""Correlate the frozen r27 source with return-plane and terminal observations.

This is a descriptive Candidate diagnostic.  Correlation and leave-one-out
scores are not causal estimates, acceptance criteria, or permission to filter
the frozen cohort.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    load_verified_bunch_source_receipt,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    FLY_COMPLETED,
    parse_events,
)

_PROJECT = "parallel_mirror_dual_stripe_mr_tof"
_MODE = "finite_3d_two_prism_voltage_trial"
_EXPECTED_COUNT = 100
_CONTINUOUS_SOURCE_FIELDS = (
    "kinetic_energy_ev", "x_mm", "y_mm", "z_mm",
    "direction_x", "direction_y", "direction_z",
)
_CONSTANT_SOURCE_FIELDS = ("tob_us", "mass_th", "charge_e")


def _sha256(path: Path) -> str:
    return file_sha256(path).lower()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object: {path}")
    return value


def _verify_full_manifest_records(manifest: dict[str, Any], manifest_path: Path) -> None:
    """Apply the common byte-identity verifier to every declared file record."""
    base_dir = manifest_path.parent
    try:
        verify_record("run_config", manifest["run_config"], base_dir=base_dir)
        inputs = manifest.get("inputs")
        outputs = manifest.get("outputs")
        if not isinstance(inputs, dict) or not isinstance(outputs, list):
            raise AssertionError("manifest inputs/outputs have invalid containers")
        for name, record in inputs.items():
            verify_record(f"input {name}", record, base_dir=base_dir)
        for index, record in enumerate(outputs, start=1):
            verify_record(f"output {index}", record, base_dir=base_dir)
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError(f"manifest record verification failed: {error}") from error


def _unique_output(manifest: dict[str, Any], path: Path, label: str) -> None:
    target = path.resolve()
    matches = [
        record for record in manifest.get("outputs", [])
        if isinstance(record, dict)
        and isinstance(record.get("path"), str)
        and Path(record["path"]).resolve() == target
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"{label} is not a unique manifest output")


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        raise CandidateContractError("correlation vectors are incomplete")
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    sx, sy = sum(x * x for x in dx), sum(y * y for y in dy)
    if sx == 0.0 or sy == 0.0:
        return None
    return sum(x * y for x, y in zip(dx, dy, strict=True)) / math.sqrt(sx * sy)


def _loo_linear(xs: list[float], ys: list[float]) -> dict[str, Any]:
    predictions: list[float] = []
    baselines: list[float] = []
    correlations: list[float] = []
    for omitted in range(len(xs)):
        tx = xs[:omitted] + xs[omitted + 1:]
        ty = ys[:omitted] + ys[omitted + 1:]
        mx, my = sum(tx) / len(tx), sum(ty) / len(ty)
        variance = sum((x - mx) ** 2 for x in tx)
        if variance == 0.0:
            raise CandidateContractError("leave-one-out predictor is invariant")
        slope = sum((x - mx) * (y - my) for x, y in zip(tx, ty, strict=True)) / variance
        predictions.append(my + slope * (xs[omitted] - mx))
        baselines.append(my)
        value = _pearson(tx, ty)
        if value is not None:
            correlations.append(value)
    squared = [(actual - predicted) ** 2 for actual, predicted in zip(ys, predictions, strict=True)]
    baseline_squared = [
        (actual - predicted) ** 2 for actual, predicted in zip(ys, baselines, strict=True)
    ]
    denominator = sum(baseline_squared)
    return {
        "prediction_rmse": math.sqrt(sum(squared) / len(squared)),
        "mean_only_rmse": math.sqrt(denominator / len(squared)),
        "skill_vs_training_mean": None if denominator == 0.0 else 1.0 - sum(squared) / denominator,
        "jackknife_correlation_min": min(correlations),
        "jackknife_correlation_max": max(correlations),
        "jackknife_sign_stable": min(correlations) * max(correlations) > 0.0,
    }


def _best_threshold(xs: list[float], labels: list[int]) -> tuple[float, int]:
    candidates = sorted(set(xs))
    if len(candidates) < 2:
        raise CandidateContractError("terminal classifier variable is invariant")
    thresholds = [(a + b) / 2.0 for a, b in zip(candidates, candidates[1:])]
    best: tuple[float, float, int] | None = None
    for threshold in thresholds:
        for direction in (-1, 1):
            predictions = [int(direction * (x - threshold) >= 0.0) for x in xs]
            sensitivity = sum(p == y == 1 for p, y in zip(predictions, labels, strict=True)) / sum(labels)
            specificity = sum(p == y == 0 for p, y in zip(predictions, labels, strict=True)) / (len(labels) - sum(labels))
            candidate = ((sensitivity + specificity) / 2.0, -abs(threshold), direction)
            if best is None or candidate > best:
                best = candidate
                selected = threshold
    assert best is not None
    return selected, best[2]


def _loo_threshold(xs: list[float], labels: list[int]) -> dict[str, Any]:
    predictions: list[int] = []
    for omitted in range(len(xs)):
        tx = xs[:omitted] + xs[omitted + 1:]
        ty = labels[:omitted] + labels[omitted + 1:]
        if not 0 < sum(ty) < len(ty):
            raise CandidateContractError("leave-one-out terminal classes are incomplete")
        threshold, direction = _best_threshold(tx, ty)
        predictions.append(int(direction * (xs[omitted] - threshold) >= 0.0))
    tp = sum(p == y == 1 for p, y in zip(predictions, labels, strict=True))
    tn = sum(p == y == 0 for p, y in zip(predictions, labels, strict=True))
    fp = sum(p == 1 and y == 0 for p, y in zip(predictions, labels, strict=True))
    fn = sum(p == 0 and y == 1 for p, y in zip(predictions, labels, strict=True))
    return {
        "method": "univariate_training_threshold_maximizing_balanced_accuracy",
        "true_collision": tp, "true_detector": tn,
        "false_collision": fp, "false_detector": fn,
        "accuracy": (tp + tn) / len(labels),
        "balanced_accuracy": 0.5 * (tp / (tp + fn) + tn / (tn + fp)),
    }


def _one(events: Iterable[dict[str, Any]], kind: str, ion: int) -> dict[str, Any]:
    matches = [event for event in events if event["kind"] == kind and int(event.get("ion", -1)) == ion]
    if len(matches) != 1:
        raise CandidateContractError(f"ion {ion} does not have exactly one {kind} event")
    return matches[0]


def _return_lip_event(events: list[dict[str, Any]], ion: int, phase_time: float) -> dict[str, Any]:
    matches = [
        event for event in events
        if int(event.get("ion", -1)) == ion
        and float(event.get("t_us", -math.inf)) > phase_time
        and abs(float(event.get("z_mm", math.inf)) + 97.0) <= 1e-5
        and (
            (event["kind"] == "patch_interface" and event.get("name") == "mirror_turn_negative__z_max")
            or (event["kind"] == "terminal" and int(event.get("splat", 0)) == -1)
        )
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"ion {ion} lacks one exact post-K z=-97 return-lip state")
    return matches[0]


def analyze_r27_source_return_correlation(run_dir: Path) -> dict[str, Any]:
    """Validate and analyze one complete r27-style N=100 static pilot."""
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load_object(manifest_path, "r27 run manifest")
    if (
        manifest.get("project") != _PROJECT or manifest.get("mode") != _MODE
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("input is not a successful MR-TOF full-flight manifest")
    _verify_full_manifest_records(manifest, manifest_path)
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("r27 manifest inputs are missing")
    receipt_path = record_path(inputs["bunch_source_receipt"], base_dir=run_dir)
    source_manifest_path = record_path(inputs["bunch_source_run_manifest"], base_dir=run_dir)
    receipt = load_verified_bunch_source_receipt(receipt_path)
    if receipt.get("particle_count") != _EXPECTED_COUNT:
        raise CandidateContractError("diagnostic requires the complete frozen N=100 cohort")
    source_manifest = _load_object(source_manifest_path, "bunch source run manifest")
    if (
        source_manifest.get("project") != _PROJECT
        or source_manifest.get("mode") != "deterministic_bunch_source_materialization"
        or source_manifest.get("status") != "success"
    ):
        raise CandidateContractError("bunch source run manifest is not successful")
    _verify_full_manifest_records(source_manifest, source_manifest_path)
    state_path = Path(receipt["state_table"]["path"])
    fly2_path = Path(receipt["fly2"]["path"])
    _unique_output(source_manifest, state_path, "source state table")
    _unique_output(source_manifest, fly2_path, "source Fly2")
    receipt_matches = [
        record for record in source_manifest.get("outputs", [])
        if isinstance(record, dict)
        and str(record.get("sha256", "")).lower() == _sha256(receipt_path).lower()
        and Path(str(record.get("path", ""))).name == "bunch_source_receipt.json"
    ]
    if len(receipt_matches) != 1:
        raise CandidateContractError("copied source receipt is not uniquely bound to its source run")

    raw_path = run_dir / "logs" / "native_two_prism_flight.log"
    observation_path = run_dir / "results" / "two_prism_trial_observation.json"
    _unique_output(manifest, raw_path, "merged native flight log")
    _unique_output(manifest, observation_path, "flight observation")
    observation = _load_object(observation_path, "flight observation")
    cohort = observation.get("cohort_analysis")
    if (
        not isinstance(cohort, dict) or cohort.get("event_integrity_passed") is not True
        or cohort.get("expected_particle_count") != _EXPECTED_COUNT
        or cohort.get("observed_particle_ids") != list(range(1, _EXPECTED_COUNT + 1))
    ):
        raise CandidateContractError("flight observation does not bind one complete N=100 cohort")

    with state_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [int(row["particle_id"]) for row in rows]
    if ids != list(range(1, _EXPECTED_COUNT + 1)):
        raise CandidateContractError("source table does not preserve all ordered particle IDs")
    text = raw_path.read_text(encoding="utf-8")
    completions = list(FLY_COMPLETED.finditer(text))
    if len(completions) != 1 or int(completions[0].group("splats")) != _EXPECTED_COUNT:
        raise CandidateContractError("merged log lacks one complete 100-particle Fly completion")
    events = parse_events(text)

    target_y: list[float] = []
    lip_y: list[float] = []
    collision: list[int] = []
    particle_records: list[dict[str, Any]] = []
    for row in rows:
        ion = int(row["particle_id"])
        phase = _one(events, "target_k_phase_sample", ion)
        terminal = _one(events, "terminal", ion)
        code = int(terminal["splat"])
        if code not in (-1, 1):
            raise CandidateContractError(f"ion {ion} has unsupported terminal class {code}")
        lip = _return_lip_event(events, ion, float(phase["t_us"]))
        target_y.append(float(phase["y_mm"]))
        lip_y.append(float(lip["y_mm"]))
        collision.append(int(code == -1))
        particle_records.append({
            "particle_id": ion,
            "initial": {name: float(row[name]) for name in _CONSTANT_SOURCE_FIELDS + _CONTINUOUS_SOURCE_FIELDS},
            "target_k_y_mm": target_y[-1],
            "return_lip_y_mm_at_z_minus_97": lip_y[-1],
            "return_lip_event_kind": lip["kind"],
            "terminal_class": "electrode_collision" if code == -1 else "detector_hit",
            "terminal_splat": code,
        })
    if sum(collision) != cohort.get("electrode_collision_count") or sum(1 - x for x in collision) != cohort.get("detector_hit_count"):
        raise CandidateContractError("raw terminal classes disagree with the frozen observation")
    if len(collision) < 30 or min(sum(collision), len(collision) - sum(collision)) < 10:
        raise CandidateContractError("cohort is too small for the declared simple leave-one-out diagnostic")

    associations: dict[str, Any] = {}
    for name in _CONSTANT_SOURCE_FIELDS + _CONTINUOUS_SOURCE_FIELDS:
        xs = [record["initial"][name] for record in particle_records]
        invariant = min(xs) == max(xs)
        if invariant:
            associations[name] = {
                "status": "invariant__association_not_defined", "value": xs[0],
            }
            continue
        associations[name] = {
            "status": "descriptive_diagnostic",
            "target_k_y": {
                "pearson_r": _pearson(xs, target_y),
                "leave_one_out_linear": _loo_linear(xs, target_y),
            },
            "return_lip_y": {
                "pearson_r": _pearson(xs, lip_y),
                "leave_one_out_linear": _loo_linear(xs, lip_y),
            },
            "terminal_collision": {
                "point_biserial_r": _pearson(xs, collision),
                "leave_one_out_threshold": _loo_threshold(xs, collision),
            },
        }
    return {
        "schema_version": 1,
        "role": "mrtof_r27_source_return_terminal_correlation_diagnostic",
        "status": "candidate_diagnostic",
        "qualification": "descriptive_association_only__not_causal__no_acceptance_threshold",
        "acceptance_threshold": None,
        "warnings": [
            "Correlations and leave-one-out scores are descriptive associations, not causal effects.",
            "All 100 frozen particles, including every loss, are retained; no source filtering is authorized.",
            "The minority terminal class contains only 12 particles, so classification scores are limited diagnostics.",
        ],
        "evidence": {
            "run_manifest": {"path": str(manifest_path), "sha256": _sha256(manifest_path)},
            "source_run_manifest": {"path": str(source_manifest_path), "sha256": _sha256(source_manifest_path)},
            "source_state_table": receipt["state_table"],
            "native_log": {"path": str(raw_path), "sha256": _sha256(raw_path)},
            "observation": {"path": str(observation_path), "sha256": _sha256(observation_path)},
        },
        "cohort": {
            "particle_count": len(particle_records),
            "particle_ids": ids,
            "detector_hit_count": len(collision) - sum(collision),
            "electrode_collision_count": sum(collision),
            "return_plane": "project z=-97 mm after target-K negative-mirror turn",
        },
        "associations": associations,
        "particles": particle_records,
        "interpretation": (
            "Use these associations only to identify follow-up variables and envelope diagnostics. "
            "They do not prove a physical cause or qualify a changed source, aperture, voltage, or resolution."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_r27_source_return_correlation(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
