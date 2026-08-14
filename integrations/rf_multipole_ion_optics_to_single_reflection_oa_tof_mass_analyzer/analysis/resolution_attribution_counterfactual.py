"""Prepare and analyze paired pre-pulse oaTOF counterfactual SIMION arms."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C,
    kinetic_energy_ev,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.finite_interval_design_compiler import (
    FINITE_INTERVAL_COMPILER_POLICY,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    accelerator_state,
    linear_phase_space_timing_coefficients,
    match_finite_phase_space_interval,
    match_phase_space_voltage_pair,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import (
    solve_coupled_reflectron_from_accelerator_derivatives,
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
        {"arm_id": "current_layout_ideal_1mm_vz0", "intervention": "analytic_1mm_global_z_line_monoenergetic_10ev_zero_global_vz"},
        {"arm_id": "current_layout_ideal_1mm_linear_z_vz", "intervention": "analytic_1mm_global_z_line_monoenergetic_10ev_theory_linear_global_z_vz"},
        {"arm_id": "current_layout_ideal_finite_interval_linear_z_vz", "intervention": "analytic_run_local_finite_interval_xyz_monoenergetic_10ev_theory_linear_global_z_vz"},
        {"arm_id": "current_layout_ideal_finite_interval_axis_linear_z_vz", "intervention": "analytic_run_local_finite_interval_axis_monoenergetic_10ev_theory_linear_global_z_vz"},
        {"arm_id": "current_layout_ideal_axis_2p2mm_linear_z_vz", "intervention": "analytic_axis_2p2mm_monoenergetic_10ev_run_local_theory_linear_global_z_vz"},
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


def _validate_accelerator_match_profile(profile: dict[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "role",
        "profile_id",
        "source_event",
        "cohort_policy",
        "matching_method",
        "fixed_constraints",
        "solver",
        "probes",
        "ring_shape_probes",
        "coupled_reflectron_probes",
        "actual_slope_probes",
        "finite_interval_design",
        "finite_interval_coupled_probes",
        "frozen_phase_space_input",
        "claim_limit",
    }
    if (
        set(profile) != expected_keys
        or profile.get("schema_version") != 1
        or profile.get("role") != "rf_oatof_accelerator_phase_space_match_profile"
        or profile.get("source_event") != "pre_pulse_state"
        or profile.get("cohort_policy") != "source_event_and_pulse_eligibility"
        or profile.get("matching_method")
        != "measured_linear_z_vz_fixed_geometry_fixed_nominal_energy_v1"
        or profile.get("fixed_constraints")
        != [
            "accelerator_geometry",
            "accelerator_exit_voltage",
            "mean_final_energy_per_charge",
            "focus_plane",
            "reflectron_geometry",
        ]
    ):
        raise ValueError("accelerator phase-space match profile identity differs")
    solver = profile.get("solver")
    if not isinstance(solver, dict) or set(solver) != {
        "derivative_step_mm",
        "derivative_tolerance_s_per_mm",
    }:
        raise ValueError("accelerator phase-space match solver contract differs")
    if (
        float(solver["derivative_step_mm"]) <= 0.0
        or float(solver["derivative_tolerance_s_per_mm"]) <= 0.0
    ):
        raise ValueError("accelerator phase-space match solver values differ")
    probes = profile.get("probes")
    if not isinstance(probes, list) or not probes:
        raise ValueError("accelerator phase-space match probes are empty")
    expected_probe_keys = {"arm_id", "voltage_drop_offset_V"}
    ids = []
    offsets = []
    for probe in probes:
        if not isinstance(probe, dict) or set(probe) != expected_probe_keys:
            raise ValueError("accelerator phase-space match probe contract differs")
        ids.append(str(probe["arm_id"]))
        offsets.append(float(probe["voltage_drop_offset_V"]))
    if (
        len(ids) != len(set(ids))
        or any(not arm_id.startswith("accelerator_phase_match_") for arm_id in ids)
        or len(offsets) != len(set(offsets))
        or 0.0 not in offsets
    ):
        raise ValueError("accelerator phase-space match probe registry differs")
    ring_probes = profile.get("ring_shape_probes")
    if not isinstance(ring_probes, list) or not ring_probes:
        raise ValueError("accelerator ring-shape probes are empty")
    ring_ids = []
    ring_pairs = []
    for probe in ring_probes:
        if not isinstance(probe, dict) or set(probe) != {
            "arm_id", "quadratic_V", "cubic_V"
        }:
            raise ValueError("accelerator ring-shape probe contract differs")
        ring_ids.append(str(probe["arm_id"]))
        ring_pairs.append((float(probe["quadratic_V"]), float(probe["cubic_V"])))
    if (
        len(ring_ids) != len(set(ring_ids))
        or len(ring_pairs) != len(set(ring_pairs))
        or any(not arm_id.startswith("accelerator_ring_shape_") for arm_id in ring_ids)
    ):
        raise ValueError("accelerator ring-shape probe registry differs")
    coupled_probes = profile.get("coupled_reflectron_probes")
    if not isinstance(coupled_probes, list) or not coupled_probes:
        raise ValueError("coupled reflectron probes are empty")
    coupled_ids = []
    for probe in coupled_probes:
        if not isinstance(probe, dict) or set(probe) != {
            "arm_id", "quadratic_V", "cubic_V"
        }:
            raise ValueError("coupled reflectron probe contract differs")
        coupled_ids.append(str(probe["arm_id"]))
    if (
        len(coupled_ids) != len(set(coupled_ids))
        or any(not arm_id.startswith("accelerator_reflectron_coupled_") for arm_id in coupled_ids)
    ):
        raise ValueError("coupled reflectron probe registry differs")
    slope_probes = profile.get("actual_slope_probes")
    if not isinstance(slope_probes, list) or not slope_probes:
        raise ValueError("actual 3D slope probes are empty")
    slope_ids = []
    slope_tuples = []
    for probe in slope_probes:
        if not isinstance(probe, dict) or set(probe) != {
            "arm_id", "voltage_drop_offset_V", "quadratic_V", "cubic_V"
        }:
            raise ValueError("actual 3D slope probe contract differs")
        slope_ids.append(str(probe["arm_id"]))
        slope_tuples.append(
            (
                float(probe["voltage_drop_offset_V"]),
                float(probe["quadratic_V"]),
                float(probe["cubic_V"]),
            )
        )
    if (
        len(slope_ids) != len(set(slope_ids))
        or len(slope_tuples) != len(set(slope_tuples))
        or any(not arm_id.startswith("accelerator_actual_slope_") for arm_id in slope_ids)
        or not all(np.all(np.isfinite(values)) for values in slope_tuples)
    ):
        raise ValueError("actual 3D slope probe registry differs")
    finite_design = profile.get("finite_interval_design")
    if (
        not isinstance(finite_design, dict)
        or set(finite_design) != {
            "arm_id", "source_full_width_mm",
            "focus_policy", "stage2_field_policy", "geometry_policy",
        }
        or finite_design["arm_id"]
        != "accelerator_finite_interval_uniform_field_limit"
        or float(finite_design["source_full_width_mm"]) <= 0.0
        or finite_design["focus_policy"]
        != "derive_linear_phase_space_first_order_drift_then_translate_to_global_zero"
        or finite_design["stage2_field_policy"] != "single_uniform_field"
        or finite_design["geometry_policy"]
        != "retain_stage1_stage2_and_ring_count_unless_theory_is_infeasible"
    ):
        raise ValueError("finite-interval accelerator design contract differs")
    coupled_finite = profile.get("finite_interval_coupled_probes")
    if (
        not isinstance(coupled_finite, list)
        or len(coupled_finite) != 2
        or {item.get("coupled_reflectron_enabled") for item in coupled_finite}
        != {False, True}
        or any(
            set(item) != {
                "arm_id", "source_intervention_arm_id",
                "coupled_reflectron_enabled",
            }
            or item["source_intervention_arm_id"]
            != "current_layout_ideal_finite_interval_axis_linear_z_vz"
            for item in coupled_finite
        )
    ):
        raise ValueError("finite-interval coupled probe contract differs")
    frozen = profile.get("frozen_phase_space_input")
    if not isinstance(frozen, dict) or set(frozen) != {
        "run_id", "checkpoint_sha256", "cohort", "particle_count",
        "mass_to_charge_Th", "release_position_mm",
        "mean_initial_velocity_m_per_s", "velocity_slope_m_per_s_per_mm",
    } or frozen["cohort"] != (
        "pre_pulse_state_and_pulse_eligibility_equals_eligible"
    ) or int(frozen["particle_count"]) < 3:
        raise ValueError("frozen accelerator phase-space input differs")


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
    checkpoints_path: Path,
    mass_amu: float,
    charge_state: int,
    cohort_policy: str = "source_event_and_baseline_detector_intersection",
) -> tuple[np.ndarray, np.ndarray, int]:
    columns, rows = _load_csv(checkpoints_path)
    if not set(CHECKPOINT_COLUMNS).issubset(columns):
        raise ValueError("baseline checkpoint columns differ")
    pre = {int(row["particle_id"]): row for row in rows if row["event"] == "pre_pulse_state"}
    if cohort_policy == "source_event_and_baseline_detector_intersection":
        detector_ids = {
            int(row["particle_id"])
            for row in rows
            if row["event"] == "detector_crossing"
        }
        selected_ids = set(pre) & detector_ids
    elif cohort_policy == "source_event_and_pulse_eligibility":
        if "pulse_eligibility" not in columns:
            raise ValueError("pulse-eligibility cohort requires its checkpoint column")
        selected_ids = {
            particle_id
            for particle_id, row in pre.items()
            if row["pulse_eligibility"] == "eligible"
        }
    else:
        raise ValueError("unsupported counterfactual cohort policy")
    ids = np.asarray(sorted(selected_ids), dtype=int)
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
    theory_linear_z_vz: tuple[float, float] | None = None,
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
        "current_layout_ideal_1mm_vz0",
        "current_layout_ideal_1mm_linear_z_vz",
    }:
        # A formula-validation source, not a filtered or rescaled random beam:
        # deterministic z coverage, zero transverse extent, exactly 10 eV.
        result[:, 1] = target_center[0]
        result[:, 2] = target_center[1]
        result[:, 3] = target_center[2] + np.linspace(-0.5, 0.5, len(result))
        speeds = _speed_for_energy(
            np.full(len(result), 10.0, dtype=float), float(observed[0, 7])
        )
        result[:, 4:7] = 0.0
        if arm_id == "current_layout_ideal_1mm_linear_z_vz":
            if theory_linear_z_vz is None:
                raise ValueError("analytic linear source requires frozen theory z-vz")
            mean_vz, slope = theory_linear_z_vz
            result[:, 6] = (
                mean_vz
                + slope * (result[:, 3] - target_center[2])
            )
        if np.any(np.abs(result[:, 6]) >= speeds):
            raise ValueError("prescribed ideal-source vz exceeds total speed")
        result[:, 4] = np.sqrt(speeds * speeds - result[:, 6] * result[:, 6])
    if arm_id in {
        "current_layout_ideal_finite_interval_linear_z_vz",
        "current_layout_ideal_finite_interval_axis_linear_z_vz",
        "current_layout_ideal_axis_2p2mm_linear_z_vz",
    }:
        if theory_linear_z_vz is None:
            raise ValueError("finite-interval ideal source requires run-local theory z-vz")
        if arm_id != "current_layout_ideal_axis_2p2mm_linear_z_vz" and not math.isclose(
            float(target_size[2]), 2.2, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("finite-interval ideal source requires run-local z width 2.2 mm")
        # Preserve the governed ideal-source x/y distribution while replacing
        # the acceleration coordinate by deterministic full-interval coverage.
        scaled = _scaled_formal_positions(
            formal_samples, formal_center, formal_size, target_center, target_size
        )
        if arm_id == "current_layout_ideal_finite_interval_linear_z_vz":
            result[:, 1:3] = scaled[:, 0:2]
        else:
            result[:, 1] = target_center[0]
            result[:, 2] = target_center[1]
        source_width_mm = (
            2.2
            if arm_id == "current_layout_ideal_axis_2p2mm_linear_z_vz"
            else target_size[2]
        )
        result[:, 3] = target_center[2] + np.linspace(
            -0.5 * source_width_mm, 0.5 * source_width_mm, len(result)
        )
        mean_vz, slope = theory_linear_z_vz
        result[:, 6] = mean_vz + slope * (result[:, 3] - target_center[2])
        speeds = _speed_for_energy(
            np.full(len(result), 10.0, dtype=float), float(observed[0, 7])
        )
        result[:, 4:6] = 0.0
        if np.any(np.abs(result[:, 6]) >= speeds):
            raise ValueError("finite-interval ideal-source vz exceeds total speed")
        result[:, 4] = np.sqrt(speeds * speeds - result[:, 6] * result[:, 6])
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
    accelerator_match_profile_path: Path | None = None,
    accelerator_match_stage: str = "voltage",
    diagnostic_particle_limit: int | None = None,
) -> dict[str, Any]:
    profile = _load_json(profile_path)
    profile_arm_ids = _validate_profile(profile)
    match_profile = (
        _load_json(accelerator_match_profile_path)
        if accelerator_match_profile_path is not None
        else None
    )
    if match_profile is not None:
        _validate_accelerator_match_profile(match_profile)
        if accelerator_match_stage not in {
            "voltage", "ring_shape", "coupled_reflectron", "actual_slope",
            "finite_interval", "finite_interval_coupled",
        }:
            raise ValueError("accelerator match stage differs")
    arm_ids = (
        (["observed_restart_control"] if match_profile is not None else profile_arm_ids)
        if selected_arm_ids is None
        else list(selected_arm_ids)
    )
    if not arm_ids:
        raise ValueError("selected resolution-attribution arms cannot be empty")
    if len(arm_ids) != len(set(arm_ids)):
        raise ValueError("selected resolution-attribution arms must be unique")
    generated_match_arm_ids = {
        str(probe["arm_id"])
        for key in (
            "probes", "ring_shape_probes", "coupled_reflectron_probes",
            "actual_slope_probes", "finite_interval_coupled_probes",
        )
        for probe in ((match_profile or {}).get(key) or [])
    }
    if match_profile is not None and match_profile.get("finite_interval_design"):
        generated_match_arm_ids.add(
            str(match_profile["finite_interval_design"]["arm_id"])
        )
    if any(
        arm_id not in profile_arm_ids and arm_id not in generated_match_arm_ids
        for arm_id in arm_ids
    ):
        raise ValueError("selected resolution-attribution arm is unknown")
    cohort_policy = (
        str(match_profile["cohort_policy"])
        if match_profile is not None
        else str(profile["cohort_policy"])
    )
    source_ids, observed, mother_sample_count = _cohort(
        checkpoints_path, mass_amu, charge_state, cohort_policy
    )
    if diagnostic_particle_limit is not None:
        if diagnostic_particle_limit < 3 or diagnostic_particle_limit > source_ids.size:
            raise ValueError("diagnostic particle limit must retain 3..cohort particles")
        source_ids = source_ids[:diagnostic_particle_limit]
        observed = observed[:diagnostic_particle_limit]
    ideal = _ideal_source(ideal_source_path)
    formal_samples = _formal_samples(ideal, source_ids)
    formal_center, formal_size = _source_geometry(formal_geometry_path)
    target_center, target_size = _source_geometry(target_geometry_path)
    target_geometry = _load_json(target_geometry_path)
    finite_theory = (
        target_geometry.get("geometry_derivation", {})
        .get("accelerator", {})
        .get("finite_interval_theory")
    )
    theory_linear_z_vz = (
        (
            float(finite_theory["mean_initial_velocity_m_per_s"]),
            float(finite_theory["velocity_slope_m_per_s_per_mm"]),
        )
        if isinstance(finite_theory, dict)
        else None
    )
    generated_arms: dict[str, dict[str, Any]] = {}
    accelerator_match: dict[str, Any] | None = None
    if match_profile is not None:
        acceleration = target_geometry["geometry_derivation"]["accelerator"]
        electrodes = target_geometry["electrodes_V"]
        repeller_z = float(acceleration["canonical_repeller_z_mm"])
        release_position = float(np.mean(observed[:, 3])) - repeller_z
        centered_z = observed[:, 3] - np.mean(observed[:, 3])
        denominator = float(np.dot(centered_z, centered_z))
        if denominator <= 0.0:
            raise ValueError("phase-space matching requires nonzero z variance")
        mean_vz = float(np.mean(observed[:, 6]))
        velocity_slope = float(
            np.dot(centered_z, observed[:, 6] - mean_vz) / denominator
        )
        nominal_energy = float(
            target_geometry["geometry_derivation"]["reflectron"]
            ["nominal_energy_per_charge_V"]
        )
        solver = match_profile["solver"]
        match = match_phase_space_voltage_pair(
            float(acceleration["d1_mm"]),
            float(acceleration["d2_mm"]),
            release_position,
            mean_vz,
            velocity_slope,
            float(acceleration["focus_drift_after_grid2_mm"]),
            mass_amu / abs(charge_state),
            nominal_energy,
            exit_v=float(electrodes["grid2"]),
            voltage_drop_bounds_v=FINITE_INTERVAL_COMPILER_POLICY[
                "voltage_drop_bounds_V"
            ],
            derivative_step_mm=float(solver["derivative_step_mm"]),
            derivative_tolerance_s_per_mm=float(
                solver["derivative_tolerance_s_per_mm"]
            ),
        )
        accelerator_match = asdict(match)
        accelerator_match["profile_id"] = match_profile["profile_id"]
        accelerator_match["profile_sha256"] = file_sha256(
            accelerator_match_profile_path
        )
        accelerator_match["cohort_policy"] = cohort_policy
        accelerator_match["arms"] = []
        local_z = observed[:, 3] - repeller_z
        gap1_width = float(acceleration["d1_mm"])
        nominal_width = float(target_size[2])
        nominal_center = float(target_center[2]) - repeller_z
        physical_mask = (local_z > 0.0) & (local_z < gap1_width)
        nominal_mask = (
            np.abs(local_z - nominal_center) <= 0.5 * nominal_width
        )
        minimum_centered_width = 2.0 * float(
            np.max(np.abs(local_z - nominal_center))
        )
        accelerator_match["source_acceptance"] = {
            "coordinate": "local_z_from_repeller_mm",
            "physical_gap": {
                "minimum_mm": 0.0,
                "maximum_mm": gap1_width,
                "width_mm": gap1_width,
                "inside_particles": int(np.count_nonzero(physical_mask)),
                "inside_fraction": float(np.mean(physical_mask)),
                "all_particles_inside": bool(np.all(physical_mask)),
            },
            "nominal_reference_source_window": {
                "center_mm": nominal_center,
                "full_width_mm": nominal_width,
                "minimum_mm": nominal_center - 0.5 * nominal_width,
                "maximum_mm": nominal_center + 0.5 * nominal_width,
                "inside_particles": int(np.count_nonzero(nominal_mask)),
                "inside_fraction": float(np.mean(nominal_mask)),
                "all_particles_inside": bool(np.all(nominal_mask)),
            },
            "observed_cohort": {
                "particles": int(local_z.size),
                "minimum_mm": float(np.min(local_z)),
                "maximum_mm": float(np.max(local_z)),
                "full_span_mm": float(np.ptp(local_z)),
                "sigma_mm": float(np.std(local_z, ddof=1)),
                "minimum_centered_full_width_mm": minimum_centered_width,
            },
            "geometry_change_required": not bool(np.all(physical_mask)),
        }
        coupled_solution = None
        finite_solution = None
        if accelerator_match_stage == "finite_interval":
            finite_design = match_profile["finite_interval_design"]
            finite_solution = match_finite_phase_space_interval(
                float(acceleration["d1_mm"]),
                float(acceleration["d2_mm"]),
                release_position,
                float(finite_design["source_full_width_mm"]),
                mean_vz,
                velocity_slope,
                mass_amu / abs(charge_state),
                nominal_energy,
                exit_v=float(electrodes["grid2"]),
                voltage_drop_bounds_v=FINITE_INTERVAL_COMPILER_POLICY[
                    "voltage_drop_bounds_V"
                ],
                sample_count=int(FINITE_INTERVAL_COMPILER_POLICY["sample_count"]),
                voltage_tolerance_v=float(
                    FINITE_INTERVAL_COMPILER_POLICY["voltage_tolerance_V"]
                ),
            )
            accelerator_match["finite_interval_solution"] = asdict(finite_solution)
        if accelerator_match_stage == "finite_interval_coupled":
            if theory_linear_z_vz is None:
                raise ValueError("finite-interval coupled stage requires frozen theory z-vz")
            finite_design = match_profile["finite_interval_design"]
            theory_mean_vz, theory_velocity_slope = theory_linear_z_vz
            theory_release_position = target_center[2] - repeller_z
            finite_solution = match_finite_phase_space_interval(
                float(acceleration["d1_mm"]),
                float(acceleration["d2_mm"]),
                theory_release_position,
                float(finite_design["source_full_width_mm"]),
                theory_mean_vz,
                theory_velocity_slope,
                mass_amu / abs(charge_state),
                nominal_energy,
                exit_v=float(electrodes["grid2"]),
                voltage_drop_bounds_v=FINITE_INTERVAL_COMPILER_POLICY[
                    "voltage_drop_bounds_V"
                ],
                sample_count=int(FINITE_INTERVAL_COMPILER_POLICY["sample_count"]),
                voltage_tolerance_v=float(
                    FINITE_INTERVAL_COMPILER_POLICY["voltage_tolerance_V"]
                ),
            )
            fixed_focus_match = match_phase_space_voltage_pair(
                float(acceleration["d1_mm"]),
                float(acceleration["d2_mm"]),
                theory_release_position,
                theory_mean_vz,
                theory_velocity_slope,
                float(acceleration["focus_drift_after_grid2_mm"]),
                mass_amu / abs(charge_state),
                nominal_energy,
                exit_v=float(electrodes["grid2"]),
                voltage_drop_bounds_v=FINITE_INTERVAL_COMPILER_POLICY[
                    "voltage_drop_bounds_V"
                ],
                derivative_step_mm=float(solver["derivative_step_mm"]),
                derivative_tolerance_s_per_mm=float(
                    solver["derivative_tolerance_s_per_mm"]
                ),
            )
            matched_state = accelerator_state(
                fixed_focus_match.repeller_v,
                fixed_focus_match.intermediate_v,
                float(acceleration["d1_mm"]),
                float(acceleration["d2_mm"]),
                exit_v=fixed_focus_match.exit_v,
                release_position_mm=theory_release_position,
                require_downstream_focus=False,
            )
            coefficients = linear_phase_space_timing_coefficients(
                matched_state,
                mass_amu / abs(charge_state),
                theory_mean_vz,
                theory_velocity_slope,
                float(acceleration["focus_drift_after_grid2_mm"]),
            )
            source_positions = target_center[2] + np.linspace(
                -0.5 * finite_solution.source_full_width_mm,
                0.5 * finite_solution.source_full_width_mm,
                int(FINITE_INTERVAL_COMPILER_POLICY["sample_count"]),
            )
            source_velocities = (
                finite_solution.mean_initial_velocity_m_per_s
                + finite_solution.velocity_slope_m_per_s_per_mm
                * (source_positions - target_center[2])
            )
            local_release = source_positions - repeller_z
            electrostatic_energy = (
                matched_state.repeller_relative_v
                - matched_state.field1_v_per_mm * local_release
            )
            mass_over_charge_si = (
                mass_amu / abs(charge_state) * AMU_KG / ELEMENTARY_CHARGE_C
            )
            actual_energy = (
                electrostatic_energy
                + 0.5 * mass_over_charge_si * source_velocities ** 2
            )
            geometry = target_geometry["geometry_mm"]
            coupled_solution = solve_coupled_reflectron_from_accelerator_derivatives(
                coefficients.actual_energy_per_charge_v,
                float(geometry["L_stage1"]),
                float(geometry["L_flight"]),
                float(geometry["L_flight"]),
                coefficients.first_derivative_at_focus,
                coefficients.second_derivative_at_focus,
                energy_min_v=float(np.min(actual_energy)),
                energy_max_v=float(np.max(actual_energy)),
            )
            if coupled_solution.required_stage2_depth_mm > float(geometry["L_stage2"]):
                raise ValueError("finite-interval coupled reflectron exceeds fixed stage-2 length")
            match = fixed_focus_match
            accelerator_match["finite_interval_solution"] = asdict(finite_solution)
            accelerator_match["fixed_focus_match"] = asdict(fixed_focus_match)
            accelerator_match["linear_phase_space_coefficients"] = asdict(coefficients)
            accelerator_match["actual_energy_envelope_V"] = {
                "minimum": float(np.min(actual_energy)),
                "nominal": coefficients.actual_energy_per_charge_v,
                "maximum": float(np.max(actual_energy)),
            }
            accelerator_match["coupled_reflectron"] = asdict(coupled_solution)
        if accelerator_match_stage == "coupled_reflectron":
            matched_state = accelerator_state(
                match.repeller_v,
                match.intermediate_v,
                float(acceleration["d1_mm"]),
                float(acceleration["d2_mm"]),
                exit_v=match.exit_v,
                release_position_mm=release_position,
                require_downstream_focus=False,
            )
            coefficients = linear_phase_space_timing_coefficients(
                matched_state,
                mass_amu / abs(charge_state),
                mean_vz,
                velocity_slope,
                float(acceleration["focus_drift_after_grid2_mm"]),
            )
            local_release = observed[:, 3] - repeller_z
            electrostatic_energy = (
                matched_state.repeller_relative_v
                - matched_state.field1_v_per_mm * local_release
            )
            mass_over_charge_si = (
                mass_amu / abs(charge_state) * AMU_KG / ELEMENTARY_CHARGE_C
            )
            actual_energy = electrostatic_energy + 0.5 * mass_over_charge_si * observed[:, 6] ** 2
            geometry = target_geometry["geometry_mm"]
            coupled_solution = solve_coupled_reflectron_from_accelerator_derivatives(
                coefficients.actual_energy_per_charge_v,
                float(geometry["L_stage1"]),
                float(geometry["L_flight"]),
                float(geometry["L_flight"]),
                coefficients.first_derivative_at_focus,
                coefficients.second_derivative_at_focus,
                energy_min_v=float(np.min(actual_energy)),
                energy_max_v=float(np.max(actual_energy)),
            )
            if coupled_solution.required_stage2_depth_mm > float(geometry["L_stage2"]):
                raise ValueError("coupled reflectron solution exceeds fixed stage-2 length")
            accelerator_match["linear_phase_space_coefficients"] = asdict(coefficients)
            accelerator_match["actual_energy_envelope_V"] = {
                "minimum": float(np.min(actual_energy)),
                "nominal": coefficients.actual_energy_per_charge_v,
                "maximum": float(np.max(actual_energy)),
            }
            accelerator_match["coupled_reflectron"] = asdict(coupled_solution)
        probes = {
            "voltage": match_profile["probes"],
            "ring_shape": match_profile["ring_shape_probes"],
            "coupled_reflectron": match_profile["coupled_reflectron_probes"],
            "actual_slope": match_profile["actual_slope_probes"],
            "finite_interval": [match_profile["finite_interval_design"]],
            "finite_interval_coupled": match_profile["finite_interval_coupled_probes"],
        }[accelerator_match_stage]
        for probe in probes:
            arm_id = str(probe["arm_id"])
            voltage_drop_offset = float(probe.get("voltage_drop_offset_V", 0.0))
            voltage_drop = (
                finite_solution.gap1_voltage_drop_v
                if finite_solution is not None
                and accelerator_match_stage == "finite_interval"
                else match.gap1_voltage_drop_v + voltage_drop_offset
            )
            repeller_v = (
                match.exit_v
                + nominal_energy
                + voltage_drop * match.release_position_mm
                / float(acceleration["d1_mm"])
            )
            intermediate_v = repeller_v - voltage_drop
            if not repeller_v > intermediate_v > match.exit_v:
                raise ValueError("accelerator match probe violates voltage ordering")
            generated_arms[arm_id] = {
                "arm_id": arm_id,
                "intervention": "none",
                "source_intervention_arm_id": probe.get("source_intervention_arm_id"),
            }
            accelerator_match["arms"].append(generated_arms[arm_id])
        if selected_arm_ids is None:
            arm_ids.extend(generated_arms)
        else:
            missing = [
                arm_id for arm_id in arm_ids
                if arm_id not in generated_arms and arm_id not in profile_arm_ids
            ]
            if missing:
                raise ValueError("selected generated accelerator arm is unavailable")
            generated_arms = {
                arm_id: generated_arms[arm_id]
                for arm_id in arm_ids if arm_id in generated_arms
            }
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
    arm_profile.update(generated_arms)
    for arm_id in arm_ids:
        source_arm_id = arm_profile[arm_id].get(
            "source_intervention_arm_id", arm_id
        )
        state = _apply_arm(
                source_arm_id,
                observed,
                ideal,
                formal_samples,
                formal_center,
                formal_size,
                target_center,
                target_size,
                theory_linear_z_vz,
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
            }
        )
    manifest = {
        "schema_version": 1,
        "role": "rf_oatof_resolution_attribution_prepared_arms",
        "profile_id": profile["profile_id"],
        "profile_sha256": file_sha256(profile_path),
        "cohort_policy": cohort_policy,
        "accelerator_match": accelerator_match,
        "accelerator_match_stage": (
            accelerator_match_stage if match_profile is not None else None
        ),
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


def _write_phase_space_diagnostic(
    rows: list[dict[str, str]],
    output_dir: Path,
    prepared_path: Path,
    cohort_policy: str,
) -> dict[str, Any]:
    z = np.asarray([float(row["z_mm"]) for row in rows], dtype=float)
    vz = np.asarray([float(row["vz_m_s"]) for row in rows], dtype=float)
    if z.size < 3 or not np.all(np.isfinite(z)) or not np.all(np.isfinite(vz)):
        raise ValueError("phase-space diagnostic requires three finite z-vz states")
    centered_z = z - np.mean(z)
    denominator = float(np.dot(centered_z, centered_z))
    if denominator <= 0.0:
        raise ValueError("phase-space diagnostic requires nonzero z variance")
    mean_vz = float(np.mean(vz))
    slope = float(np.dot(centered_z, vz - mean_vz) / denominator)
    fitted = mean_vz + slope * centered_z
    residual = vz - fitted
    pearson = float(np.corrcoef(z, vz)[0, 1])

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2), constrained_layout=True)
    axes[0].scatter(
        centered_z, vz, s=14, alpha=0.62, color="#0072B2", marker="o",
        linewidths=0.25, edgecolors="white", label=f"eligible (N={z.size})",
    )
    order = np.argsort(centered_z, kind="stable")
    axes[0].plot(
        centered_z[order], fitted[order], color="#D55E00", linewidth=1.4,
        label=f"linear fit: slope={slope:.1f} m s⁻¹ mm⁻¹",
    )
    axes[0].axvline(0.0, color="#777777", linewidth=0.7, linestyle="--")
    axes[0].set(
        xlabel="Centered z (mm)",
        ylabel="Pre-pulse vz (m/s)",
        title=f"A  z–vz phase space (r={pearson:.3f})",
    )
    axes[0].legend(frameon=False, fontsize=8)

    axes[1].scatter(
        centered_z, residual, s=14, alpha=0.62, color="#009E73", marker="s",
        linewidths=0.25, edgecolors="white",
    )
    axes[1].axhline(0.0, color="#777777", linewidth=0.8, linestyle="--")
    axes[1].set(
        xlabel="Centered z (mm)",
        ylabel="Linear-fit vz residual (m/s)",
        title=f"B  Residual thickness (σ={np.std(residual, ddof=1):.1f} m/s)",
    )
    for axis in axes:
        axis.grid(alpha=0.18)
    figure_path = output_dir / "pre_pulse_z_vz_phase_space.png"
    pending_figure = figure_path.with_name(f".{figure_path.name}.pending.png")
    fig.savefig(pending_figure, dpi=220, format="png", facecolor="white")
    plt.close(fig)
    os.replace(pending_figure, figure_path)
    metadata = {
        "schema_version": 1,
        "role": "rf_oatof_pre_pulse_z_vz_phase_space_diagnostic",
        "capability_id": "rf_oatof_pre_pulse_z_vz_phase_space_v1",
        "source_prepared_arms_sha256": file_sha256(prepared_path),
        "cohort_policy": cohort_policy,
        "particle_count": int(z.size),
        "frame_id": "oatof_global_centered_at_pulse_cohort_mean_z",
        "position_unit": "mm",
        "velocity_unit": "m/s",
        "filter": "pre_pulse_state and pulse_eligibility=eligible; no detector filter",
        "linear_fit": {
            "mean_global_z_mm": float(np.mean(z)),
            "mean_vz_m_per_s": mean_vz,
            "slope_m_per_s_per_mm": slope,
            "pearson_r": pearson,
            "residual_sample_sigma_m_per_s": float(np.std(residual, ddof=1)),
        },
        "figure": figure_path.name,
        "figure_sha256": file_sha256(figure_path),
        "style": "publication_double_183x81mm_220dpi",
    }
    metadata_path = output_dir / "pre_pulse_z_vz_phase_space_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return {**metadata, "metadata": metadata_path.name}


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


def _phase_space_time_transfer(
    state_rows: list[dict[str, str]], detector: dict[int, float]
) -> dict[str, Any] | None:
    """Fit detector time against the detected source cohort's actual z-vz plane."""
    selected = [
        row for row in state_rows
        if int(row["source_particle_id"]) in detector
    ]
    if len(selected) < 3:
        return None
    z = np.asarray([float(row["z_mm"]) for row in selected], dtype=float)
    vz = np.asarray([float(row["vz_m_s"]) for row in selected], dtype=float)
    time_ns = np.asarray(
        [detector[int(row["source_particle_id"])] * 1000.0 for row in selected],
        dtype=float,
    )
    z_centered = z - np.mean(z)
    vz_centered = vz - np.mean(vz)
    z_variance = float(np.dot(z_centered, z_centered))
    if z_variance <= 0.0:
        return None
    velocity_slope = float(np.dot(z_centered, vz_centered) / z_variance)
    design = np.column_stack((np.ones(z.size), z_centered, vz_centered))
    coefficients, _, rank, _ = np.linalg.lstsq(design, time_ns, rcond=None)
    if rank < 3:
        return None
    fitted = design @ coefficients
    residual = time_ns - fitted
    total = time_ns - np.mean(time_ns)
    total_ss = float(np.dot(total, total))
    r_squared = (
        1.0 - float(np.dot(residual, residual)) / total_ss
        if total_ss > 0.0 else None
    )
    partial_z = float(coefficients[1])
    partial_vz = float(coefficients[2])
    return {
        "detected_particles": len(selected),
        "velocity_slope_m_per_s_per_mm": velocity_slope,
        "partial_time_z_ns_per_mm": partial_z,
        "partial_time_vz_ns_per_m_per_s": partial_vz,
        "actual_linear_z_vz_time_slope_ns_per_mm": (
            partial_z + velocity_slope * partial_vz
        ),
        "linear_model_r_squared": r_squared,
    }


def _checkpoint_time_transfer(
    state_rows: list[dict[str, str]],
    checkpoint_rows: list[dict[str, object]],
    event: str,
) -> dict[str, Any] | None:
    """Measure one checkpoint's time spread and source-z transfer slope."""
    source_z = {
        int(row["simulation_particle_id"]): float(row["z_mm"])
        for row in state_rows
    }
    selected = [row for row in checkpoint_rows if row["event"] == event]
    if len(selected) < 3:
        return None
    z = np.asarray([source_z[int(row["particle_id"])] for row in selected])
    time_ns = np.asarray(
        [float(row["instrument_time_us"]) * 1000.0 for row in selected]
    )
    z_centered = z - np.mean(z)
    variance = float(np.dot(z_centered, z_centered))
    slope = (
        float(np.dot(z_centered, time_ns - np.mean(time_ns)) / variance)
        if variance > 0.0 else None
    )
    return {
        "particles": len(selected),
        "time_sigma_ns": float(np.std(time_ns)),
        "source_z_time_slope_ns_per_mm": slope,
    }


def _pulse_relative_peak(
    detector_times_us: np.ndarray, pulse_time_us: float, mass_amu: float
) -> dict[str, Any] | None:
    """Compute the resolution peak from detector time minus effective pulse time."""
    return (
        compute_peak_metrics(detector_times_us - pulse_time_us, mass_amu)[0]
        if detector_times_us.size >= 3
        else None
    )


def summarize(
    profile_path: Path,
    prepared_path: Path,
    baseline_checkpoints_path: Path,
    logs_dir: Path,
    output_dir: Path,
    reference_arm_id: str | None = None,
) -> dict[str, Any]:
    profile = _load_json(profile_path)
    profile_arm_ids = _validate_profile(profile)
    prepared = _load_json(prepared_path)
    if prepared.get("role") != "rf_oatof_resolution_attribution_prepared_arms":
        raise ValueError("prepared counterfactual identity differs")
    arm_ids = [str(arm["arm_id"]) for arm in prepared.get("arms", [])]
    generated_arm_ids = {
        str(arm["arm_id"])
        for arm in (prepared.get("accelerator_match") or {}).get("arms", [])
    }
    allowed_arm_ids = set(profile_arm_ids) | generated_arm_ids
    if (
        not arm_ids
        or len(arm_ids) != len(set(arm_ids))
        or any(arm_id not in allowed_arm_ids for arm_id in arm_ids)
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
    pulse_time_us = float(prepared["pulse_time_us"])
    source_dir = prepared_path.parent
    baseline_columns, baseline_rows = _load_csv(baseline_checkpoints_path)
    if not set(CHECKPOINT_COLUMNS).issubset(baseline_columns):
        raise ValueError("baseline checkpoint columns differ")
    # analyze_single_flight writes the canonical instrument clock into every
    # checkpoint row.  No second time basis is accepted or reconstructed here.
    baseline_detector = _checkpoint_detector_times(baseline_rows)
    output_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_rows: list[dict[str, object]] = []
    metrics: list[dict[str, Any]] = []
    detector_by_arm: dict[str, dict[int, float]] = {}
    prepared_by_id = {arm["arm_id"]: arm for arm in prepared["arms"]}
    phase_space_diagnostic = None
    if prepared.get("accelerator_match") is not None:
        observed_state_path = source_dir / f"{arm_ids[0]}__source_state.csv"
        observed_columns, observed_rows = _load_csv(observed_state_path)
        if observed_columns != ARM_STATE_COLUMNS:
            raise ValueError("observed phase-space source-state identity differs")
        phase_space_diagnostic = _write_phase_space_diagnostic(
            observed_rows,
            output_dir,
            prepared_path,
            str(prepared["cohort_policy"]),
        )
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
        peak = _pulse_relative_peak(detector_times, pulse_time_us, mass_amu)
        metrics.append(
            {
                "arm_id": arm_id,
                "source_particles": particles,
                "detector_particles": len(detector),
                "source_state": _state_summary(state_rows),
                "phase_space_time_transfer": _phase_space_time_transfer(
                    state_rows, detector
                ),
                "checkpoint_time_transfer": {
                    event: _checkpoint_time_transfer(state_rows, rows, event)
                    for event in (
                        "accelerator_grid1_forward", "local_accelerator_exit",
                        "accelerator_focus_forward",
                    )
                },
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
    baseline_peak = _pulse_relative_peak(baseline_times, pulse_time_us, mass_amu)
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
        "cohort_policy": prepared.get("cohort_policy", profile["cohort_policy"]),
        "accelerator_match": prepared.get("accelerator_match"),
        "phase_space_diagnostic": phase_space_diagnostic,
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
    prepare_parser.add_argument("--diagnostic-particle-limit", type=int)
    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("--profile", required=True, type=Path)
    summarize_parser.add_argument("--prepared", required=True, type=Path)
    summarize_parser.add_argument("--baseline-checkpoints", required=True, type=Path)
    summarize_parser.add_argument("--logs-dir", required=True, type=Path)
    summarize_parser.add_argument("--output-dir", required=True, type=Path)
    summarize_parser.add_argument("--reference-arm-id")
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
            None,
            "voltage",
            args.diagnostic_particle_limit,
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
            args.reference_arm_id,
        )
        print(
            "RESOLUTION_ATTRIBUTION_SUMMARY=PASS "
            f"ARMS={len(result['arms'])} PARTICLES={result['paired_cohort_particles']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
