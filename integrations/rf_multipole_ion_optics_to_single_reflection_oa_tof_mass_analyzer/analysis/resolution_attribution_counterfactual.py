"""Prepare and analyze paired pre-pulse oaTOF counterfactual SIMION arms."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.rf_handoff_adapter import (
    encode_simion_accelerator_velocity,
)

from .analyze_single_flight import analyze


CHECKPOINT_COLUMNS = [
    "particle_id",
    "event",
    "instrument_time_us",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_mm_per_us",
    "vy_mm_per_us",
    "vz_mm_per_us",
]
ARM_STATE_COLUMNS = [
    "simulation_particle_id",
    "source_particle_id",
    "arm_id",
    "instrument_time_us",
    "mass_amu",
    "charge_state",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "kinetic_energy_eV",
]
RESULT_COLUMNS = [
    "arm_id",
    "simulation_particle_id",
    "source_particle_id",
    "event",
    "instrument_time_us",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_mm_per_us",
    "vy_mm_per_us",
    "vz_mm_per_us",
]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _validate_profile(profile: dict[str, Any]) -> list[str]:
    expected_keys = {
        "schema_version",
        "role",
        "profile_id",
        "source_event",
        "cohort_policy",
        "acceleration_axis",
        "transverse_axes",
        "random_seed",
        "peak_metric",
        "claim_limit",
        "arms",
    }
    if (
        set(profile) != expected_keys
        or
        profile.get("schema_version") != 1
        or profile.get("role")
        != "rf_oatof_resolution_attribution_counterfactual_profile"
        or profile.get("source_event") != "pre_pulse_state"
        or profile.get("cohort_policy")
        != "source_event_and_baseline_detector_intersection"
        or profile.get("acceleration_axis") != "global_z"
        or profile.get("transverse_axes") != ["global_x", "global_y"]
        or profile.get("random_seed") != 20260804
        or profile.get("peak_metric")
        != "canonical_direct_gaussian_kde_fwhm"
    ):
        raise ValueError("resolution-attribution profile identity differs")
    arms = profile.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ValueError("resolution-attribution profile has no arms")
    expected = {
        "observed_restart_control": "none",
        "ideal_acceleration_position": "quantile_match_global_z_to_ideal_source",
        "ideal_transverse_positions": "quantile_match_global_x_and_y_to_ideal_source",
        "remove_acceleration_covariance": "remove_linear_global_z_global_vz_covariance_preserve_vz_mean_and_sample_sigma",
        "monoenergetic": "scale_each_velocity_vector_to_cohort_mean_kinetic_energy",
        "ideal_acceleration_position_remove_covariance": "quantile_match_global_z_then_remove_linear_global_z_global_vz_covariance",
        "collapsed_acceleration_phase_space_upper_bound": "set_global_z_and_global_vz_to_cohort_means",
    }
    arm_ids = [str(item.get("arm_id", "")) for item in arms]
    if (
        arm_ids != list(expected)
        or len(set(arm_ids)) != len(arm_ids)
        or any(
            not isinstance(item, dict)
            or set(item) != {"arm_id", "intervention"}
            or item.get("intervention") != expected[item["arm_id"]]
            for item in arms
        )
    ):
        raise ValueError("resolution-attribution arm registry differs")
    return arm_ids


def _quantile_match(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    if values.size < 2 or reference.size < 2:
        raise ValueError("quantile matching requires at least two values")
    order = np.argsort(values, kind="stable")
    probabilities = (np.arange(values.size, dtype=float) + 0.5) / values.size
    matched = np.empty_like(values, dtype=float)
    matched[order] = np.quantile(reference, probabilities, method="linear")
    return matched


def _remove_linear_covariance(z: np.ndarray, vz: np.ndarray) -> np.ndarray:
    centered_z = z - np.mean(z)
    denominator = float(np.dot(centered_z, centered_z))
    if denominator <= 0:
        raise ValueError("acceleration-position variance must be positive")
    original_mean = float(np.mean(vz))
    original_sigma = float(np.std(vz, ddof=1))
    beta = float(np.dot(centered_z, vz - original_mean) / denominator)
    residual = vz - original_mean - beta * centered_z
    residual_sigma = float(np.std(residual, ddof=1))
    if original_sigma <= 0 or residual_sigma <= 0:
        raise ValueError("acceleration-velocity variance must be positive")
    adjusted = original_mean + residual * (original_sigma / residual_sigma)
    covariance = float(np.cov(z, adjusted, ddof=1)[0, 1])
    tolerance = max(1e-12, original_sigma * float(np.std(z, ddof=1)) * 1e-12)
    if abs(covariance) > tolerance:
        raise ValueError("failed to remove acceleration position-velocity covariance")
    return adjusted


def _cohort(
    checkpoints_path: Path, mass_amu: float, charge_state: int
) -> tuple[np.ndarray, np.ndarray]:
    columns, rows = _load_csv(checkpoints_path)
    if columns != CHECKPOINT_COLUMNS:
        raise ValueError("baseline checkpoint columns differ")
    pre = {int(row["particle_id"]): row for row in rows if row["event"] == "pre_pulse_state"}
    detector_ids = {
        int(row["particle_id"]) for row in rows if row["event"] == "detector_crossing"
    }
    ids = np.asarray(sorted(set(pre) & detector_ids), dtype=int)
    if ids.size < 3:
        raise ValueError("paired pre-pulse/detector cohort is too small")
    state = np.asarray(
        [
            [
                float(pre[int(pid)]["instrument_time_us"]),
                float(pre[int(pid)]["x_mm"]),
                float(pre[int(pid)]["y_mm"]),
                float(pre[int(pid)]["z_mm"]),
                float(pre[int(pid)]["vx_mm_per_us"]) * 1000.0,
                float(pre[int(pid)]["vy_mm_per_us"]) * 1000.0,
                float(pre[int(pid)]["vz_mm_per_us"]) * 1000.0,
                mass_amu,
                float(charge_state),
            ]
            for pid in ids
        ],
        dtype=float,
    )
    if not np.all(np.isfinite(state)) or not np.allclose(state[:, 0], state[0, 0]):
        raise ValueError("pre-pulse cohort must be finite and share one absolute pulse time")
    return ids, state


def _ideal_coordinates(path: Path) -> dict[str, np.ndarray]:
    columns, rows = _load_csv(path)
    required = {"initial_x_mm", "initial_y_mm", "initial_z_mm"}
    if not required.issubset(columns) or len(rows) < 3:
        raise ValueError("ideal source mapping lacks required spatial columns")
    return {
        axis: np.asarray([float(row[f"initial_{axis}_mm"]) for row in rows], dtype=float)
        for axis in "xyz"
    }


def _apply_arm(
    arm_id: str, observed: np.ndarray, ideal: dict[str, np.ndarray]
) -> np.ndarray:
    result = observed.copy()
    if arm_id == "observed_restart_control":
        return result
    if arm_id in {
        "ideal_acceleration_position",
        "ideal_acceleration_position_remove_covariance",
    }:
        result[:, 3] = _quantile_match(result[:, 3], ideal["z"])
    if arm_id == "ideal_transverse_positions":
        result[:, 1] = _quantile_match(result[:, 1], ideal["x"])
        result[:, 2] = _quantile_match(result[:, 2], ideal["y"])
    if arm_id in {
        "remove_acceleration_covariance",
        "ideal_acceleration_position_remove_covariance",
    }:
        result[:, 6] = _remove_linear_covariance(result[:, 3], result[:, 6])
    if arm_id == "monoenergetic":
        energies = np.asarray(
            [kinetic_energy_ev(row[7], row[4], row[5], row[6]) for row in result]
        )
        target = float(np.mean(energies))
        if np.any(energies <= 0):
            raise ValueError("monoenergetic intervention requires positive energy")
        result[:, 4:7] *= np.sqrt(target / energies)[:, None]
    if arm_id == "collapsed_acceleration_phase_space_upper_bound":
        result[:, 3] = float(np.mean(result[:, 3]))
        result[:, 6] = float(np.mean(result[:, 6]))
    return result


def prepare(
    profile_path: Path,
    checkpoints_path: Path,
    ideal_source_path: Path,
    output_dir: Path,
    mass_amu: float,
    charge_state: int,
) -> dict[str, Any]:
    profile = _load_json(profile_path)
    arm_ids = _validate_profile(profile)
    source_ids, observed = _cohort(checkpoints_path, mass_amu, charge_state)
    ideal = _ideal_coordinates(ideal_source_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    arm_records: list[dict[str, Any]] = []
    for arm_id in arm_ids:
        state = _apply_arm(arm_id, observed, ideal)
        state_path = output_dir / f"{arm_id}__source_state.csv"
        ion_path = output_dir / f"{arm_id}.ion"
        state_rows: list[dict[str, str]] = []
        ion_rows: list[list[str]] = []
        for simulation_id, (source_id, row) in enumerate(zip(source_ids, state), start=1):
            time_us, x, y, z, vx, vy, vz, mass, charge = row
            energy = kinetic_energy_ev(mass, vx, vy, vz)
            azimuth, elevation = encode_simion_accelerator_velocity((vx, vy, vz))
            state_rows.append(
                {
                    "simulation_particle_id": str(simulation_id),
                    "source_particle_id": str(int(source_id)),
                    "arm_id": arm_id,
                    "instrument_time_us": format(time_us, ".17g"),
                    "mass_amu": format(mass, ".17g"),
                    "charge_state": str(int(charge)),
                    "x_mm": format(x, ".17g"),
                    "y_mm": format(y, ".17g"),
                    "z_mm": format(z, ".17g"),
                    "vx_m_s": format(vx, ".17g"),
                    "vy_m_s": format(vy, ".17g"),
                    "vz_m_s": format(vz, ".17g"),
                    "kinetic_energy_eV": format(energy, ".17g"),
                }
            )
            ion_rows.append(
                [
                    format(time_us, ".17g"),
                    format(mass, ".17g"),
                    str(int(charge)),
                    format(x, ".17g"),
                    format(y, ".17g"),
                    format(z, ".17g"),
                    format(azimuth, ".17g"),
                    format(elevation, ".17g"),
                    format(energy, ".17g"),
                    "1",
                    "3",
                ]
            )
        with state_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ARM_STATE_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(state_rows)
        with ion_path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(ion_rows)
        arm_records.append(
            {
                "arm_id": arm_id,
                "particles": len(state_rows),
                "state_file": state_path.name,
                "state_sha256": file_sha256(state_path),
                "ion_file": ion_path.name,
                "ion_sha256": file_sha256(ion_path),
            }
        )
    manifest = {
        "schema_version": 1,
        "role": "rf_oatof_resolution_attribution_prepared_arms",
        "profile_id": profile["profile_id"],
        "profile_sha256": file_sha256(profile_path),
        "baseline_checkpoints_sha256": file_sha256(checkpoints_path),
        "ideal_source_sha256": file_sha256(ideal_source_path),
        "mother_sample_particle_count": 1000,
        "paired_cohort_particles": int(source_ids.size),
        "pulse_time_us": float(observed[0, 0]),
        "mass_amu": mass_amu,
        "charge_state": charge_state,
        "arms": arm_records,
    }
    manifest_path = output_dir / "prepared_arms.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def _state_summary(rows: list[dict[str, str]]) -> dict[str, float | None]:
    arrays = {
        name: np.asarray([float(row[name]) for row in rows], dtype=float)
        for name in ("x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "kinetic_energy_eV")
    }
    z_sigma = float(np.std(arrays["z_mm"], ddof=1))
    vz_sigma = float(np.std(arrays["vz_m_s"], ddof=1))
    z_vz_pearson = (
        float(np.corrcoef(arrays["z_mm"], arrays["vz_m_s"])[0, 1])
        if z_sigma > 0 and vz_sigma > 0
        else None
    )
    return {
        **{f"{name}_mean": float(np.mean(values)) for name, values in arrays.items()},
        **{f"{name}_sample_sigma": float(np.std(values, ddof=1)) for name, values in arrays.items()},
        "z_vz_pearson": z_vz_pearson,
    }


def summarize(
    profile_path: Path,
    prepared_path: Path,
    baseline_checkpoints_path: Path,
    logs_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    profile = _load_json(profile_path)
    arm_ids = _validate_profile(profile)
    prepared = _load_json(prepared_path)
    if prepared.get("role") != "rf_oatof_resolution_attribution_prepared_arms":
        raise ValueError("prepared counterfactual identity differs")
    particles = int(prepared["paired_cohort_particles"])
    mass_amu = float(prepared["mass_amu"])
    source_dir = prepared_path.parent
    baseline_columns, baseline_rows = _load_csv(baseline_checkpoints_path)
    if baseline_columns != CHECKPOINT_COLUMNS:
        raise ValueError("baseline checkpoint columns differ")
    baseline_detector = {
        int(row["particle_id"]): float(row["instrument_time_us"])
        for row in baseline_rows
        if row["event"] == "detector_crossing"
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_rows: list[dict[str, object]] = []
    metrics: list[dict[str, Any]] = []
    detector_by_arm: dict[str, dict[int, float]] = {}
    for arm_id in arm_ids:
        state_columns, state_rows = _load_csv(source_dir / f"{arm_id}__source_state.csv")
        if state_columns != ARM_STATE_COLUMNS or len(state_rows) != particles:
            raise ValueError(f"counterfactual source-state identity differs: {arm_id}")
        source_map = {
            int(row["simulation_particle_id"]): int(row["source_particle_id"])
            for row in state_rows
        }
        rows, arm_summary = analyze(logs_dir / f"{arm_id}.stdout.log", particles, mass_amu)
        detector: dict[int, float] = {}
        for row in rows:
            simulation_id = int(row["particle_id"])
            source_id = source_map[simulation_id]
            checkpoint_rows.append(
                {
                    "arm_id": arm_id,
                    "simulation_particle_id": simulation_id,
                    "source_particle_id": source_id,
                    **{key: row[key] for key in RESULT_COLUMNS[3:]},
                }
            )
            if row["event"] == "detector_crossing":
                detector[source_id] = float(row["instrument_time_us"])
        detector_by_arm[arm_id] = detector
        peak = arm_summary["instrument_clock_peak"]
        if peak is None:
            raise ValueError(f"counterfactual arm has no measurable peak: {arm_id}")
        metrics.append(
            {
                "arm_id": arm_id,
                "source_particles": particles,
                "detector_particles": len(detector),
                "source_state": _state_summary(state_rows),
                "peak": peak,
            }
        )
    with (output_dir / "counterfactual_particle_checkpoints.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(checkpoint_rows)
    metric_by_id = {item["arm_id"]: item for item in metrics}
    control = metric_by_id["observed_restart_control"]
    control_detector = detector_by_arm["observed_restart_control"]
    comparisons: list[dict[str, Any]] = []
    for arm_id in arm_ids:
        item = metric_by_id[arm_id]
        common_ids = sorted(set(control_detector) & set(detector_by_arm[arm_id]))
        paired_delta = np.asarray(
            [detector_by_arm[arm_id][pid] - control_detector[pid] for pid in common_ids]
        )
        comparisons.append(
            {
                "arm_id": arm_id,
                "common_detector_particles_vs_restart_control": len(common_ids),
                "detector_particle_delta_vs_restart_control": item["detector_particles"]
                - control["detector_particles"],
                "direct_fwhm_change_pct_vs_restart_control": 100.0
                * (
                    item["peak"]["direct_fwhm_tof_ns"]
                    / control["peak"]["direct_fwhm_tof_ns"]
                    - 1.0
                ),
                "resolution_change_pct_vs_restart_control": 100.0
                * (
                    item["peak"]["mass_resolution"]
                    / control["peak"]["mass_resolution"]
                    - 1.0
                ),
                "paired_detector_time_mean_delta_ns": float(np.mean(paired_delta) * 1000.0)
                if paired_delta.size
                else None,
                "paired_detector_time_rms_delta_ns": float(
                    math.sqrt(float(np.mean(np.square(paired_delta)))) * 1000.0
                )
                if paired_delta.size
                else None,
            }
        )
    baseline_common = sorted(set(control_detector) & set(baseline_detector))
    baseline_times = np.asarray([baseline_detector[pid] for pid in baseline_common])
    baseline_peak, _ = compute_peak_metrics(baseline_times, mass_amu)
    restart_delta = np.asarray(
        [control_detector[pid] - baseline_detector[pid] for pid in baseline_common]
    )
    summary = {
        "schema_version": 1,
        "role": "rf_oatof_resolution_attribution_counterfactual_summary",
        "status": "success",
        "claim_class": "CONTROLLED_COUNTERFACTUAL_DIAGNOSTIC_ONLY",
        "claim_limit": profile["claim_limit"],
        "profile_id": profile["profile_id"],
        "paired_cohort_particles": particles,
        "baseline_continuous_peak": baseline_peak,
        "restart_control": {
            "common_detector_particles": len(baseline_common),
            "paired_detector_time_mean_delta_ns": float(np.mean(restart_delta) * 1000.0),
            "paired_detector_time_rms_delta_ns": float(
                math.sqrt(float(np.mean(np.square(restart_delta)))) * 1000.0
            ),
            "direct_fwhm_change_pct": 100.0
            * (
                control["peak"]["direct_fwhm_tof_ns"]
                / baseline_peak["direct_fwhm_tof_ns"]
                - 1.0
            ),
        },
        "arms": metrics,
        "comparisons": comparisons,
        "formal_gate_passed": False,
    }
    (output_dir / "resolution_attribution.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--profile", required=True, type=Path)
    prepare_parser.add_argument("--checkpoints", required=True, type=Path)
    prepare_parser.add_argument("--ideal-source", required=True, type=Path)
    prepare_parser.add_argument("--output-dir", required=True, type=Path)
    prepare_parser.add_argument("--mass-amu", required=True, type=float)
    prepare_parser.add_argument("--charge-state", required=True, type=int)
    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("--profile", required=True, type=Path)
    summarize_parser.add_argument("--prepared", required=True, type=Path)
    summarize_parser.add_argument("--baseline-checkpoints", required=True, type=Path)
    summarize_parser.add_argument("--logs-dir", required=True, type=Path)
    summarize_parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(
            args.profile,
            args.checkpoints,
            args.ideal_source,
            args.output_dir,
            args.mass_amu,
            args.charge_state,
        )
        print(
            "RESOLUTION_ATTRIBUTION_PREPARE=PASS "
            f"ARMS={len(result['arms'])} PARTICLES={result['paired_cohort_particles']}"
        )
    else:
        result = summarize(
            args.profile,
            args.prepared,
            args.baseline_checkpoints,
            args.logs_dir,
            args.output_dir,
        )
        print(
            "RESOLUTION_ATTRIBUTION_SUMMARY=PASS "
            f"ARMS={len(result['arms'])} PARTICLES={result['paired_cohort_particles']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
