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
from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C,
    kinetic_energy_ev,
)
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
        "pulse_delay_reference",
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
        or profile.get("pulse_delay_reference")
        != "upstream_resolved_design.drive.frequency_Hz"
    ):
        raise ValueError("resolution-attribution profile identity differs")
    arms = profile.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ValueError("resolution-attribution profile has no arms")
    expected = [
        {"arm_id": "observed_restart_control", "intervention": "none"},
        {"arm_id": "ideal_acceleration_position", "intervention": "quantile_match_centered_global_z_to_ideal_source_shape"},
        {"arm_id": "ideal_transverse_positions", "intervention": "quantile_match_centered_global_x_and_y_to_ideal_source_shape"},
        {"arm_id": "ideal_multipole_axis_position", "intervention": "quantile_match_centered_global_x_to_ideal_source_shape"},
        {"arm_id": "remove_acceleration_covariance", "intervention": "remove_linear_global_z_global_vz_covariance_preserve_vz_mean_and_sample_sigma"},
        {"arm_id": "monoenergetic", "intervention": "scale_each_velocity_vector_to_cohort_mean_kinetic_energy"},
        {"arm_id": "current_layout_ideal_source", "intervention": "scale_formal_positions_to_target_source_extents_and_apply_observed_energy_along_positive_global_x"},
        {"arm_id": "formal_focus_mapped_layout_source", "intervention": "translate_formal_positions_and_apply_observed_energy_along_positive_global_x", "solver_profile_id": "formal_reflectron"},
        {"arm_id": "exact_formal_field_mapped_layout_source", "intervention": "translate_formal_positions_and_apply_observed_energy_along_positive_global_x", "solver_profile_id": "formal_reflectron", "frontend_profile_id": "formal_accelerator"},
        {"arm_id": "formal_ideal_source", "intervention": "translate_formal_positions_and_apply_formal_energy_along_positive_global_x"},
        {"arm_id": "formal_positions_observed_velocities", "intervention": "translate_formal_positions_preserve_observed_velocity_vectors"},
        {"arm_id": "observed_positions_formal_kinematics", "intervention": "preserve_observed_positions_apply_formal_energy_along_positive_global_x"},
        {"arm_id": "observed_positions_axialized_velocities", "intervention": "preserve_observed_positions_and_energy_set_direction_positive_global_x"},
        {"arm_id": "observed_positions_formal_energy_observed_directions", "intervention": "preserve_observed_positions_and_directions_apply_formal_energy"},
        {"arm_id": "ideal_acceleration_position_remove_covariance", "intervention": "quantile_match_centered_global_z_then_remove_linear_global_z_global_vz_covariance"},
        {"arm_id": "collapse_acceleration_velocity_residual", "intervention": "project_global_vz_onto_observed_linear_global_z_global_vz_relation"},
        {"arm_id": "ideal_acceleration_position_preserve_observed_linear_slope", "intervention": "quantile_match_centered_global_z_then_project_global_vz_with_observed_linear_slope"},
        {"arm_id": "delay_pulse_one_eighth_rf_period", "intervention": "delay_pulse_from_frozen_pre_pulse_state", "pulse_delay_rf_periods": 0.125},
        {"arm_id": "delay_pulse_one_quarter_rf_period", "intervention": "delay_pulse_from_frozen_pre_pulse_state", "pulse_delay_rf_periods": 0.25},
        {"arm_id": "collapsed_acceleration_phase_space_upper_bound", "intervention": "set_global_z_and_global_vz_to_cohort_means"},
    ]
    arm_ids = [str(item.get("arm_id", "")) for item in arms]
    if (
        arms != expected
        or len(set(arm_ids)) != len(arm_ids)
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


def _quantile_match_centered(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    matched = _quantile_match(values, reference)
    return matched - float(np.mean(matched)) + float(np.mean(values))


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


def _collapse_linear_residual(z: np.ndarray, vz: np.ndarray) -> np.ndarray:
    centered_z = z - np.mean(z)
    denominator = float(np.dot(centered_z, centered_z))
    if denominator <= 0:
        raise ValueError("acceleration-position variance must be positive")
    mean_vz = float(np.mean(vz))
    beta = float(np.dot(centered_z, vz - mean_vz) / denominator)
    return mean_vz + beta * centered_z


def _project_observed_linear_slope(
    observed_z: np.ndarray,
    observed_vz: np.ndarray,
    target_z: np.ndarray,
) -> np.ndarray:
    centered_observed_z = observed_z - np.mean(observed_z)
    denominator = float(np.dot(centered_observed_z, centered_observed_z))
    if denominator <= 0:
        raise ValueError("acceleration-position variance must be positive")
    mean_vz = float(np.mean(observed_vz))
    beta = float(
        np.dot(centered_observed_z, observed_vz - mean_vz) / denominator
    )
    return mean_vz + beta * (target_z - np.mean(target_z))


def _cohort(
    checkpoints_path: Path, mass_amu: float, charge_state: int
) -> tuple[np.ndarray, np.ndarray, int]:
    columns, rows = _load_csv(checkpoints_path)
    if not set(CHECKPOINT_COLUMNS).issubset(columns):
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
    mother_sample_count = len({int(row["particle_id"]) for row in rows})
    return ids, state, mother_sample_count


def _ideal_source(path: Path) -> dict[str, np.ndarray]:
    columns, rows = _load_csv(path)
    mapping_columns = {
        "particle_id": "particle_id",
        "x": "initial_x_mm",
        "y": "initial_y_mm",
        "z": "initial_z_mm",
        "energy": "initial_energy_eV",
    }
    formal_columns = {
        "particle_id": "Ion",
        "x": "X0Mm",
        "y": "Y0Mm",
        "z": "Z0Mm",
        "energy": "EnergyEv",
    }
    selected = next(
        (
            candidate
            for candidate in (mapping_columns, formal_columns)
            if set(candidate.values()).issubset(columns)
        ),
        None,
    )
    if selected is None or len(rows) < 3:
        raise ValueError("ideal source mapping lacks required spatial columns")
    particle_ids = np.asarray(
        [int(row[selected["particle_id"]]) for row in rows], dtype=int
    )
    if len(set(particle_ids)) != particle_ids.size:
        raise ValueError("ideal source mapping particle identities are not unique")
    ideal = {
        "particle_id": particle_ids,
        **{
            axis: np.asarray(
                [float(row[selected[axis]]) for row in rows], dtype=float
            )
            for axis in "xyz"
        },
        "energy": np.asarray(
            [float(row[selected["energy"]]) for row in rows], dtype=float
        ),
    }
    if not all(np.all(np.isfinite(values)) for key, values in ideal.items() if key != "particle_id"):
        raise ValueError("ideal source mapping must be finite")
    return ideal


def _source_geometry(geometry_path: Path) -> tuple[np.ndarray, np.ndarray]:
    geometry = _load_json(geometry_path)
    source = geometry.get("particle_source")
    if not isinstance(source, dict):
        raise ValueError("resolved geometry lacks particle source")
    center = np.asarray(
        [source.get(f"center_{axis}_mm") for axis in "xyz"], dtype=float
    )
    size = np.asarray(
        [source.get(f"size_{axis}_mm") for axis in "xyz"], dtype=float
    )
    if not np.all(np.isfinite(center)) or not np.all(np.isfinite(size)) or np.any(size <= 0):
        raise ValueError("resolved particle-source center and size must be finite")
    return center, size


def _formal_samples(
    ideal: dict[str, np.ndarray], source_ids: np.ndarray
) -> np.ndarray:
    row_by_id = {
        int(particle_id): index
        for index, particle_id in enumerate(ideal["particle_id"])
    }
    missing = sorted(set(int(value) for value in source_ids) - set(row_by_id))
    if missing:
        raise ValueError(f"ideal source mapping lacks particle ids: {missing[:5]}")
    indices = [row_by_id[int(source_id)] for source_id in source_ids]
    return np.column_stack(
        [ideal[axis][indices] for axis in "xyz"] + [ideal["energy"][indices]]
    )


def _translated_formal_positions(
    formal_samples: np.ndarray,
    formal_center: np.ndarray,
    target_center: np.ndarray,
) -> np.ndarray:
    return formal_samples[:, :3] + target_center - formal_center


def _scaled_formal_positions(
    formal_samples: np.ndarray,
    formal_center: np.ndarray,
    formal_size: np.ndarray,
    target_center: np.ndarray,
    target_size: np.ndarray,
) -> np.ndarray:
    normalized = (formal_samples[:, :3] - formal_center) / formal_size
    return target_center + normalized * target_size


def _speed_for_energy(energy_ev: np.ndarray, mass_amu: float) -> np.ndarray:
    if mass_amu <= 0 or np.any(energy_ev <= 0):
        raise ValueError("positive mass and energy are required")
    return np.sqrt(2.0 * energy_ev * ELEMENTARY_CHARGE_C / (mass_amu * AMU_KG))


def _set_energy_preserve_direction(
    velocities: np.ndarray, energy_ev: np.ndarray, mass_amu: float
) -> np.ndarray:
    norms = np.linalg.norm(velocities, axis=1)
    if np.any(norms <= 0):
        raise ValueError("velocity direction requires positive speed")
    return velocities / norms[:, None] * _speed_for_energy(energy_ev, mass_amu)[:, None]


def _apply_arm(
    arm_id: str,
    observed: np.ndarray,
    ideal: dict[str, np.ndarray],
    formal_samples: np.ndarray,
    formal_center: np.ndarray,
    formal_size: np.ndarray,
    target_center: np.ndarray,
    target_size: np.ndarray,
) -> np.ndarray:
    result = observed.copy()
    if arm_id == "observed_restart_control":
        return result
    if arm_id in {
        "ideal_acceleration_position",
        "ideal_acceleration_position_remove_covariance",
        "ideal_acceleration_position_preserve_observed_linear_slope",
    }:
        result[:, 3] = _quantile_match_centered(result[:, 3], ideal["z"])
    if arm_id == "ideal_transverse_positions":
        result[:, 1] = _quantile_match_centered(result[:, 1], ideal["x"])
        result[:, 2] = _quantile_match_centered(result[:, 2], ideal["y"])
    if arm_id == "ideal_multipole_axis_position":
        result[:, 1] = _quantile_match_centered(result[:, 1], ideal["x"])
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
    if arm_id == "current_layout_ideal_source":
        result[:, 1:4] = _scaled_formal_positions(
            formal_samples,
            formal_center,
            formal_size,
            target_center,
            target_size,
        )
        energies = np.asarray(
            [kinetic_energy_ev(row[7], row[4], row[5], row[6]) for row in observed]
        )
        result[:, 4:7] = 0.0
        result[:, 4] = _speed_for_energy(energies, float(observed[0, 7]))
    if arm_id in {
        "formal_focus_mapped_layout_source",
        "exact_formal_field_mapped_layout_source",
    }:
        result[:, 1:4] = _translated_formal_positions(
            formal_samples, formal_center, target_center
        )
        energies = np.asarray(
            [kinetic_energy_ev(row[7], row[4], row[5], row[6]) for row in observed]
        )
        result[:, 4:7] = 0.0
        result[:, 4] = _speed_for_energy(energies, float(observed[0, 7]))
    formal_positions = {
        "formal_ideal_source",
        "formal_positions_observed_velocities",
    }
    if arm_id in formal_positions:
        result[:, 1:4] = _translated_formal_positions(
            formal_samples, formal_center, target_center
        )
    formal_energy = {
        "formal_ideal_source",
        "observed_positions_formal_kinematics",
        "observed_positions_formal_energy_observed_directions",
    }
    if arm_id in formal_energy:
        energies = formal_samples[:, 3]
        if arm_id == "observed_positions_formal_energy_observed_directions":
            result[:, 4:7] = _set_energy_preserve_direction(
                observed[:, 4:7], energies, float(observed[0, 7])
            )
        else:
            result[:, 4:7] = 0.0
            result[:, 4] = _speed_for_energy(energies, float(observed[0, 7]))
    if arm_id == "observed_positions_axialized_velocities":
        energies = np.asarray(
            [kinetic_energy_ev(row[7], row[4], row[5], row[6]) for row in observed]
        )
        result[:, 4:7] = 0.0
        result[:, 4] = _speed_for_energy(energies, float(observed[0, 7]))
    if arm_id == "collapse_acceleration_velocity_residual":
        result[:, 6] = _collapse_linear_residual(result[:, 3], result[:, 6])
    if arm_id == "ideal_acceleration_position_preserve_observed_linear_slope":
        result[:, 6] = _project_observed_linear_slope(
            observed[:, 3], observed[:, 6], result[:, 3]
        )
    if arm_id == "collapsed_acceleration_phase_space_upper_bound":
        result[:, 3] = float(np.mean(result[:, 3]))
        result[:, 6] = float(np.mean(result[:, 6]))
    return result


def prepare(
    profile_path: Path,
    checkpoints_path: Path,
    ideal_source_path: Path,
    formal_geometry_path: Path,
    target_geometry_path: Path,
    output_dir: Path,
    mass_amu: float,
    charge_state: int,
    rf_frequency_hz: float | None = None,
    execution_batch_count: int = 5,
    selected_arm_ids: list[str] | None = None,
    initial_pa_instance: int = 3,
    solver_birth_time_us: float | None = None,
) -> dict[str, Any]:
    profile = _load_json(profile_path)
    profile_arm_ids = _validate_profile(profile)
    arm_ids = profile_arm_ids if selected_arm_ids is None else selected_arm_ids
    if not arm_ids:
        raise ValueError("selected resolution-attribution arms cannot be empty")
    if len(arm_ids) != len(set(arm_ids)):
        raise ValueError("selected resolution-attribution arms must be unique")
    if any(arm_id not in profile_arm_ids for arm_id in arm_ids):
        raise ValueError("selected resolution-attribution arm is unknown")
    source_ids, observed, mother_sample_count = _cohort(
        checkpoints_path, mass_amu, charge_state
    )
    ideal = _ideal_source(ideal_source_path)
    formal_samples = _formal_samples(ideal, source_ids)
    formal_center, formal_size = _source_geometry(formal_geometry_path)
    target_center, target_size = _source_geometry(target_geometry_path)
    if any("pulse_delay_rf_periods" in arm for arm in profile["arms"]):
        if rf_frequency_hz is None or rf_frequency_hz <= 0:
            raise ValueError("pulse-delay arms require a positive RF frequency")
    if execution_batch_count < 1 or execution_batch_count > source_ids.size:
        raise ValueError("execution batch count differs")
    if initial_pa_instance not in {3, 5}:
        raise ValueError("initial PA instance must be the combined frontend or overlay")
    if solver_birth_time_us is not None and solver_birth_time_us < 0:
        raise ValueError("solver birth time must be non-negative")
    output_dir.mkdir(parents=True, exist_ok=False)
    arm_records: list[dict[str, Any]] = []
    arm_profile = {arm["arm_id"]: arm for arm in profile["arms"]}
    for arm_id in arm_ids:
        state = _apply_arm(
            arm_id,
            observed,
            ideal,
            formal_samples,
            formal_center,
            formal_size,
            target_center,
            target_size,
        )
        state_path = output_dir / f"{arm_id}__source_state.csv"
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
                    format(
                        time_us if solver_birth_time_us is None else solver_birth_time_us,
                        ".17g",
                    ),
                    format(mass, ".17g"),
                    str(int(charge)),
                    format(x, ".17g"),
                    format(y, ".17g"),
                    format(z, ".17g"),
                    format(azimuth, ".17g"),
                    format(elevation, ".17g"),
                    format(energy, ".17g"),
                    "1",
                    str(initial_pa_instance),
                ]
            )
        with state_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ARM_STATE_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(state_rows)
        batch_records: list[dict[str, Any]] = []
        quotient, remainder = divmod(len(ion_rows), execution_batch_count)
        offset = 0
        for batch_index in range(1, execution_batch_count + 1):
            count = quotient + (1 if batch_index <= remainder else 0)
            ion_path = output_dir / f"{arm_id}__batch{batch_index:02d}.ion"
            with ion_path.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerows(
                    ion_rows[offset : offset + count]
                )
            batch_records.append(
                {
                    "batch_index": batch_index,
                    "simulation_particle_id_offset": offset,
                    "particles": count,
                    "ion_file": ion_path.name,
                    "ion_sha256": file_sha256(ion_path),
                }
            )
            offset += count
        arm_records.append(
            {
                "arm_id": arm_id,
                "particles": len(state_rows),
                "state_file": state_path.name,
                "state_sha256": file_sha256(state_path),
                "execution_batches": batch_records,
                "pulse_time_us": float(observed[0, 0]) + (
                    float(arm_profile[arm_id].get("pulse_delay_rf_periods", 0.0))
                    * 1.0e6 / float(rf_frequency_hz)
                    if rf_frequency_hz is not None else 0.0
                ),
                "solver_profile_id": arm_profile[arm_id].get(
                    "solver_profile_id", "current_downstream"
                ),
                "frontend_profile_id": arm_profile[arm_id].get(
                    "frontend_profile_id", "combined_frontend"
                ),
            }
        )
    manifest = {
        "schema_version": 1,
        "role": "rf_oatof_resolution_attribution_prepared_arms",
        "profile_id": profile["profile_id"],
        "profile_sha256": file_sha256(profile_path),
        "baseline_checkpoints_sha256": file_sha256(checkpoints_path),
        "ideal_source_sha256": file_sha256(ideal_source_path),
        "formal_geometry_sha256": file_sha256(formal_geometry_path),
        "target_geometry_sha256": file_sha256(target_geometry_path),
        "mother_sample_particle_count": mother_sample_count,
        "paired_cohort_particles": int(source_ids.size),
        "initial_pa_instance": initial_pa_instance,
        "solver_birth_time_us": solver_birth_time_us,
        "pulse_time_us": float(observed[0, 0]),
        "rf_frequency_hz": rf_frequency_hz,
        "execution_batch_count": execution_batch_count,
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


def _checkpoint_detector_times(
    rows: list[dict[str, str]],
) -> dict[int, float]:
    """Return canonical instrument-clock detector times from checkpoint rows."""
    return {
        int(row["particle_id"]): float(row["instrument_time_us"])
        for row in rows
        if row["event"] == "detector_crossing"
    }


def _canonical_replay_detector_time(
    native_time_us: float,
    instrument_birth_time_us: float,
    solver_birth_time_us: float | None,
) -> float:
    """Restore the instrument epoch when solver and physical births differ."""
    if solver_birth_time_us is None:
        return native_time_us
    return native_time_us + instrument_birth_time_us - solver_birth_time_us


def summarize(
    profile_path: Path,
    prepared_path: Path,
    baseline_checkpoints_path: Path,
    logs_dir: Path,
    output_dir: Path,
    baseline_clock_basis: str = "legacy_relative_time",
    reference_arm_id: str | None = None,
) -> dict[str, Any]:
    profile = _load_json(profile_path)
    profile_arm_ids = _validate_profile(profile)
    prepared = _load_json(prepared_path)
    if prepared.get("role") != "rf_oatof_resolution_attribution_prepared_arms":
        raise ValueError("prepared counterfactual identity differs")
    arm_ids = [str(arm["arm_id"]) for arm in prepared.get("arms", [])]
    if (
        not arm_ids
        or len(arm_ids) != len(set(arm_ids))
        or any(arm_id not in profile_arm_ids for arm_id in arm_ids)
    ):
        raise ValueError("prepared counterfactual arm selection differs")
    reference_arm_id = reference_arm_id or (
        "observed_restart_control"
        if "observed_restart_control" in arm_ids
        else arm_ids[0]
    )
    if reference_arm_id not in arm_ids:
        raise ValueError("resolution-attribution reference arm is not selected")
    particles = int(prepared["paired_cohort_particles"])
    mass_amu = float(prepared["mass_amu"])
    source_dir = prepared_path.parent
    baseline_columns, baseline_rows = _load_csv(baseline_checkpoints_path)
    if not set(CHECKPOINT_COLUMNS).issubset(baseline_columns):
        raise ValueError("baseline checkpoint columns differ")
    if baseline_clock_basis not in {"legacy_relative_time", "absolute_birth_time"}:
        raise ValueError("baseline clock basis differs")
    # analyze_single_flight writes canonical instrument-clock time into every
    # checkpoint row.  clock_basis records how that value was obtained; it is
    # not an instruction to add source_release a second time here.
    baseline_detector = _checkpoint_detector_times(baseline_rows)
    output_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_rows: list[dict[str, object]] = []
    metrics: list[dict[str, Any]] = []
    detector_by_arm: dict[str, dict[int, float]] = {}
    prepared_by_id = {arm["arm_id"]: arm for arm in prepared["arms"]}
    for arm_id in arm_ids:
        state_columns, state_rows = _load_csv(source_dir / f"{arm_id}__source_state.csv")
        if state_columns != ARM_STATE_COLUMNS or len(state_rows) != particles:
            raise ValueError(f"counterfactual source-state identity differs: {arm_id}")
        source_map = {
            int(row["simulation_particle_id"]): int(row["source_particle_id"])
            for row in state_rows
        }
        instrument_birth = {
            int(row["simulation_particle_id"]): float(row["instrument_time_us"])
            for row in state_rows
        }
        solver_birth = prepared.get("solver_birth_time_us")
        solver_birth = float(solver_birth) if solver_birth is not None else None
        rows: list[dict[str, object]] = []
        for batch in prepared_by_id[arm_id]["execution_batches"]:
            batch_rows, _ = analyze(
                logs_dir / f"{arm_id}__batch{int(batch['batch_index']):02d}.stdout.log",
                int(batch["particles"]),
                mass_amu,
            )
            offset = int(batch["simulation_particle_id_offset"])
            for row in batch_rows:
                row["particle_id"] = int(row["particle_id"]) + offset
                rows.append(row)
        detector: dict[int, float] = {}
        for row in rows:
            simulation_id = int(row["particle_id"])
            source_id = source_map[simulation_id]
            canonical_time = float(row["instrument_time_us"])
            if row["event"] == "detector_crossing":
                canonical_time = _canonical_replay_detector_time(
                    canonical_time,
                    instrument_birth[simulation_id],
                    solver_birth,
                )
            checkpoint_rows.append(
                {
                    "arm_id": arm_id,
                    "simulation_particle_id": simulation_id,
                    "source_particle_id": source_id,
                    **{
                        key: canonical_time if key == "instrument_time_us" else row[key]
                        for key in RESULT_COLUMNS[3:]
                    },
                }
            )
            if row["event"] == "detector_crossing":
                detector[source_id] = canonical_time
        detector_by_arm[arm_id] = detector
        detector_times = np.asarray(list(detector.values()), dtype=float)
        peak = (
            compute_peak_metrics(detector_times, mass_amu)[0]
            if detector_times.size >= 3 else None
        )
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
    reference = metric_by_id[reference_arm_id]
    reference_detector = detector_by_arm[reference_arm_id]
    comparisons: list[dict[str, Any]] = []
    for arm_id in arm_ids:
        item = metric_by_id[arm_id]
        common_ids = sorted(set(reference_detector) & set(detector_by_arm[arm_id]))
        paired_delta = np.asarray(
            [
                detector_by_arm[arm_id][pid] - reference_detector[pid]
                for pid in common_ids
            ]
        )
        centered_delta = paired_delta - np.mean(paired_delta) if paired_delta.size else paired_delta
        item_peak = item["peak"]
        reference_peak = reference["peak"]
        comparisons.append(
            {
                "arm_id": arm_id,
                "reference_arm_id": reference_arm_id,
                "common_detector_particles_vs_reference": len(common_ids),
                "detector_particle_delta_vs_reference": item["detector_particles"]
                - reference["detector_particles"],
                "direct_fwhm_change_pct_vs_reference": 100.0
                * (
                    item_peak["direct_fwhm_tof_ns"]
                    / reference_peak["direct_fwhm_tof_ns"]
                    - 1.0
                ) if item_peak is not None else None,
                "resolution_change_pct_vs_reference": 100.0
                * (
                    item_peak["mass_resolution"]
                    / reference_peak["mass_resolution"]
                    - 1.0
                ) if item_peak is not None else None,
                "paired_detector_time_mean_delta_ns": float(np.mean(paired_delta) * 1000.0)
                if paired_delta.size
                else None,
                "paired_detector_time_rms_delta_ns": float(
                    math.sqrt(float(np.mean(np.square(paired_delta)))) * 1000.0
                )
                if paired_delta.size
                else None,
                "paired_detector_time_centered_rms_delta_ns": float(
                    math.sqrt(float(np.mean(np.square(centered_delta)))) * 1000.0
                )
                if centered_delta.size
                else None,
            }
        )
    baseline_common = sorted(set(reference_detector) & set(baseline_detector))
    baseline_times = np.asarray([baseline_detector[pid] for pid in baseline_common])
    baseline_peak, _ = compute_peak_metrics(baseline_times, mass_amu)
    restart_delta = np.asarray(
        [reference_detector[pid] - baseline_detector[pid] for pid in baseline_common]
    )
    summary = {
        "schema_version": 2,
        "role": "rf_oatof_resolution_attribution_counterfactual_summary",
        "status": "success",
        "claim_class": "CONTROLLED_COUNTERFACTUAL_DIAGNOSTIC_ONLY",
        "claim_limit": profile["claim_limit"],
        "profile_id": profile["profile_id"],
        "reference_arm_id": reference_arm_id,
        "paired_cohort_particles": particles,
        "baseline_continuous_peak": baseline_peak,
        "reference_vs_baseline": {
            "common_detector_particles": len(baseline_common),
            "paired_detector_time_mean_delta_ns": float(np.mean(restart_delta) * 1000.0),
            "paired_detector_time_rms_delta_ns": float(
                math.sqrt(float(np.mean(np.square(restart_delta)))) * 1000.0
            ),
            "direct_fwhm_change_pct": 100.0
            * (
                reference["peak"]["direct_fwhm_tof_ns"]
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
    prepare_parser.add_argument("--formal-geometry", required=True, type=Path)
    prepare_parser.add_argument("--target-geometry", required=True, type=Path)
    prepare_parser.add_argument("--output-dir", required=True, type=Path)
    prepare_parser.add_argument("--mass-amu", required=True, type=float)
    prepare_parser.add_argument("--charge-state", required=True, type=int)
    prepare_parser.add_argument("--rf-frequency-hz", required=True, type=float)
    prepare_parser.add_argument("--execution-batch-count", type=int, default=5)
    prepare_parser.add_argument("--initial-pa-instance", type=int, choices=(3, 5), default=3)
    prepare_parser.add_argument("--solver-birth-time-us", type=float)
    prepare_parser.add_argument("--arm-id", action="append", dest="selected_arm_ids")
    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("--profile", required=True, type=Path)
    summarize_parser.add_argument("--prepared", required=True, type=Path)
    summarize_parser.add_argument("--baseline-checkpoints", required=True, type=Path)
    summarize_parser.add_argument("--logs-dir", required=True, type=Path)
    summarize_parser.add_argument("--output-dir", required=True, type=Path)
    summarize_parser.add_argument("--reference-arm-id")
    summarize_parser.add_argument(
        "--baseline-clock-basis",
        choices=("legacy_relative_time", "absolute_birth_time"),
        default="legacy_relative_time",
    )
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(
            args.profile,
            args.checkpoints,
            args.ideal_source,
            args.formal_geometry,
            args.target_geometry,
            args.output_dir,
            args.mass_amu,
            args.charge_state,
            args.rf_frequency_hz,
            args.execution_batch_count,
            args.selected_arm_ids,
            args.initial_pa_instance,
            args.solver_birth_time_us,
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
            args.baseline_clock_basis,
            args.reference_arm_id,
        )
        print(
            "RESOLUTION_ATTRIBUTION_SUMMARY=PASS "
            f"ARMS={len(result['arms'])} PARTICLES={result['paired_cohort_particles']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
