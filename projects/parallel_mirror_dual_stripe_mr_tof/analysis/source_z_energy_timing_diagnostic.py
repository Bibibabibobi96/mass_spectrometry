"""Diagnose source-z transfer through one complete MR-TOF flight run.

The analysis is read-only and descriptive.  Safe-exit metrics use the complete
frozen cohort.  Downstream stage metrics use every detector hit with a complete
event chain; terminal losses remain in the accounting and are never filtered
from the source cohort or reclassified as detector hits.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable

import numpy as np

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    derive_mirror_l0_slope_tolerance_per_v,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    FLY_COMPLETED,
    _fwhm,
    peak_time_metrics,
    collision_diagnostics,
    parse_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    _collision_geometry_projection,
    _resolve_trial_geometry,
)


_PROJECT = "parallel_mirror_dual_stripe_mr_tof"
_MODE = "finite_3d_two_prism_voltage_trial"
_CHAIN = (
    ("target_k", "target_k_phase_sample"),
    ("return_p2_entry", "return_p2_entry"),
    ("return_p2_pass", "return_p2_pass"),
    ("return_positive_mirror_turn", "return_positive_mirror_turn"),
    ("detector", "detector"),
)
_SELECTED_EVENT_KINDS = {
    "accelerator_safe_exit", "terminal", "detector_plane",
    "central_plane_directional", "prism_entry", "prism_pass",
    "p2_low_field_crossing",
    *(kind for _, kind in _CHAIN),
}
_FIRST_BATCH_ABERRATION_STAGES = (
    ("accelerator_safe_exit", "accelerator_safe_exit", None),
    ("p1_target_pass", "prism_pass", 1),
    ("p2_entry", "prism_entry", 2),
    ("p2_pass", "prism_pass", 2),
    ("p2_low_field_crossing", "p2_low_field_crossing", None),
    ("target_k", "target_k_phase_sample", None),
    ("return_p2_entry", "return_p2_entry", None),
    ("return_p2_pass", "return_p2_pass", None),
    ("return_positive_mirror_turn", "return_positive_mirror_turn", None),
    ("detector", "detector", None),
)


def _finite_vector(value: Any, length: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise CandidateContractError(f"{label} must contain {length} values")
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must contain numeric values") from error
    if not all(math.isfinite(item) for item in result):
        raise CandidateContractError(f"{label} must be finite")
    return result

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object: {path}")
    return value


def _collision_loss_diagnostic(
    run_dir: Path, observation: dict[str, Any], selected_events: dict[tuple[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    cohort = observation["cohort_analysis"]
    keys = (
        "collision_component_histogram", "electrode_id_histogram",
        "collision_particles", "dominant_collision_component",
    )
    if all(key in cohort for key in keys):
        result = {key: cohort[key] for key in keys}
    else:
        trial_path = run_dir / "results" / "two_prism_trial_materialization.json"
        if not trial_path.is_file():
            return {
                "status": "unavailable__collision_geometry_not_frozen",
                "collision_component_histogram": {}, "electrode_id_histogram": {},
                "collision_particles": [], "dominant_collision_component": None,
                "p2_collision_surface_histogram": {},
            }
        trial = _load_object(
            trial_path,
            "trial materialization",
        )
        geometry = trial.get("collision_geometry")
        if not isinstance(geometry, dict):
            reviewed = _load_object(
                run_dir / "simion" / "simion_prototype_contract.json",
                "reviewed geometry contract",
            )
            trajectory = _load_object(
                run_dir / "simion" / "trajectory_contract.json",
                "trajectory contract",
            )
            accelerator = _load_object(
                run_dir / "simion" / "accelerator_geometry_contract.json",
                "accelerator geometry contract",
            )
            reviewed["accelerator"]["detector_return_path"] = trajectory["accelerator"][
                "detector_return_path"
            ]
            resolved = _resolve_trial_geometry(reviewed, trajectory, accelerator)
            geometry = _collision_geometry_projection(resolved)
        result = collision_diagnostics(
            [event for matches in selected_events.values() for event in matches], geometry,
        )
    p2_surfaces = Counter()
    tolerance = 0.250000001
    for particle in result["collision_particles"]:
        if particle["component"] != "p2_central_prism_ground_shield":
            continue
        if abs(abs(float(particle["z_mm"])) - 97.0) <= tolerance:
            p2_surfaces["stripe_side_y_end_lip"] += 1
        elif abs(abs(float(particle["x_mm"])) - 2.0) <= tolerance:
            p2_surfaces["beam_channel_x_sidewall"] += 1
        else:
            p2_surfaces["other"] += 1
    result["p2_collision_surface_histogram"] = dict(sorted(p2_surfaces.items()))
    return result


def _detector_plane_initial_z_slope(path: Path) -> float:
    """Read detector-plane arrival-time dt/dz in us/mm from one diagnostic."""
    value = _load_object(path, "source-z timing diagnostic")
    controlled = value.get("controlled_detector_focus")
    if isinstance(controlled, dict):
        if controlled.get("status") != "observed":
            raise CandidateContractError(
                "controlled detector-plane focus pair did not both reach the detector"
            )
        try:
            slope = float(controlled["dt_d_initial_z_us_per_mm"])
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError(
                "controlled detector-plane focus response is incomplete"
            ) from error
        if not math.isfinite(slope):
            raise CandidateContractError(
                "controlled detector-plane focus response must be finite"
            )
        return slope
    try:
        hit_count = int(value["cohort"]["detector_hit_count"])
        association = value["terminal_plane_diagnostic"]["detector_plane"][
            "absolute_time"
        ]["initial_z_association"]
        slope = float(association["slope"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(
            "source-z timing diagnostic lacks detector-plane dt/dz evidence"
        ) from error
    if (
        value.get("schema_version") != 1
        or value.get("role") != "mrtof_source_z_energy_timing_diagnostic"
        or value.get("status") != "candidate_diagnostic"
    ):
        raise CandidateContractError("source-z timing diagnostic identity is invalid")
    if hit_count < 2:
        raise CandidateContractError(
            "source-z timing diagnostic requires at least two detector hits"
        )
    if association.get("status") != "descriptive_linear_association":
        raise CandidateContractError("detector-plane initial-z association is unavailable")
    if association.get("slope_unit") != "us/mm" or not math.isfinite(slope):
        raise CandidateContractError("detector-plane dt/dz must be finite and use us/mm")
    return slope


def _te1_reference(path: Path) -> tuple[dict[str, Any], float, list[float], list[float]]:
    reference = _load_object(path, "reference TE1 variation")
    if (
        reference.get("schema_version") != 1
        or reference.get("role") != "mrtof_terminal_time_mirror_voltage_variation"
        or reference.get("status") != "screening_candidate_materialized"
        or reference.get("qualification")
        != "diagnostic_only__complete_3d_detector_response_pending"
        or reference.get("mode") != "TE1"
    ):
        raise CandidateContractError("reference must be one schema-1 TE1 variation")
    try:
        coordinate = float(reference["coordinate"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("reference TE1 coordinate is invalid") from error
    if not math.isfinite(coordinate) or coordinate == 0.0:
        raise CandidateContractError("reference TE1 coordinate must be finite and nonzero")
    base = _finite_vector(reference.get("base_mirror_voltages_v"), 5, "base voltages")
    target = _finite_vector(reference.get("target_mirror_voltages_v"), 5, "target voltages")
    delta = _finite_vector(reference.get("voltage_delta_v"), 4, "voltage delta")
    if base[0] != 0.0 or target[0] != 0.0:
        raise CandidateContractError("mirror ground voltage must remain zero")
    if any(
        not math.isclose(
            target[index + 1] - base[index + 1], delta[index],
            rel_tol=0.0, abs_tol=1e-9,
        )
        for index in range(4)
    ):
        raise CandidateContractError("reference TE1 variation delta is inconsistent")
    return reference, coordinate, base, delta


def build_te1_reference_from_mirror_jacobian(
    *, mirror_point_path: Path, mirror_correction_path: Path,
    contract_path: Path, output_path: Path,
) -> dict[str, Any]:
    """Derive the current mirror's TE1 direction from its existing Jacobian."""
    point = _load_object(mirror_point_path, "fixed-grid mirror point")
    correction = _load_object(mirror_correction_path, "mirror correction result")
    contract = _load_object(contract_path, "MR-TOF contract")
    base = _finite_vector(point.get("mirror_voltages_v"), 5, "mirror voltages")
    jacobian = correction.get("updated_local_slope_jacobian_per_v2")
    if not isinstance(jacobian, list) or len(jacobian) != 3:
        raise CandidateContractError("mirror correction lacks a 3-by-4 Jacobian")
    rows = [_finite_vector(row, 4, "mirror slope Jacobian row") for row in jacobian]
    gamma = _finite_vector(
        correction.get("updated_fine_gamma_gradient_per_v"), 4,
        "mirror gamma gradient",
    )
    try:
        fine_fraction = float(
            contract["downstream_fixed_grid_workpoint_profile"]
            ["jacobian_relative_step_tiers"]["fine"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("fine relative voltage step is invalid") from error
    if not math.isfinite(fine_fraction) or not 0.0 < fine_fraction < 1.0:
        raise CandidateContractError("fine relative voltage step must be between zero and one")
    system = np.asarray([*rows, gamma], dtype=float)
    if np.linalg.matrix_rank(system) != 4:
        raise CandidateContractError("mirror TE1 Jacobian is not full rank")
    direction = np.linalg.solve(system, np.asarray([1.0, 1.0, 1.0, 0.0]))
    relative = np.abs(direction / np.asarray(base[1:], dtype=float))
    scale = fine_fraction / float(np.max(relative))
    delta = direction * scale
    if delta[int(np.argmax(np.abs(delta / np.asarray(base[1:]))))] > 0.0:
        delta *= -1.0
    target = [0.0, *(base[index + 1] + float(delta[index]) for index in range(4))]
    result = {
        "schema_version": 1,
        "role": "mrtof_terminal_time_mirror_voltage_variation",
        "status": "screening_candidate_materialized",
        "qualification": "diagnostic_only__complete_3d_detector_response_pending",
        "mode": "TE1",
        "coordinate": 1.0,
        "base_mirror_voltages_v": base,
        "target_mirror_voltages_v": target,
        "voltage_delta_v": delta.tolist(),
        "derivation": {
            "method": "current_mirror_l0_common_slope__gamma_orthogonal_jacobian_solve",
            "relative_voltage_step": fine_fraction,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def materialize_scaled_te1_variation(
    *, reference_path: Path, coordinate: float, output_path: Path,
    detector_plane_root_fit: dict[str, Any] | None = None,
    mirror_period_path: Path | None = None,
    mirror_correction_path: Path | None = None,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    """Scale one measured TE1 direction continuously without quantizing voltage."""
    _, reference_coordinate, base, reference_delta = _te1_reference(reference_path)
    coordinate = float(coordinate)
    if not math.isfinite(coordinate):
        raise CandidateContractError("TE1 coordinate must be finite")
    scale = coordinate / reference_coordinate
    delta = [scale * value for value in reference_delta]
    target = [0.0, *(base[index + 1] + delta[index] for index in range(4))]
    result: dict[str, Any] = {
        "schema_version": 1,
        "role": "mrtof_terminal_time_mirror_voltage_variation",
        "status": "screening_candidate_materialized",
        "qualification": "diagnostic_only__complete_3d_detector_response_pending",
        "mode": "TE1",
        "coordinate": coordinate,
        "base_mirror_voltages_v": base,
        "target_mirror_voltages_v": target,
        "voltage_delta_v": delta,
    }
    if detector_plane_root_fit is not None:
        result["detector_plane_root_fit"] = detector_plane_root_fit
    gate_paths = (mirror_period_path, mirror_correction_path, contract_path)
    if any(path is not None for path in gate_paths):
        if not all(path is not None for path in gate_paths):
            raise CandidateContractError(
                "mirror period, correction, and contract are required together"
            )
        period = _load_object(mirror_period_path, "mirror period result")
        correction = _load_object(mirror_correction_path, "mirror correction result")
        contract = _load_object(contract_path, "MR-TOF contract")
        slopes = _finite_vector(
            period.get("simion_normalized_period_slopes_per_v"), 3,
            "mirror period slopes",
        )
        energies = _finite_vector(
            period.get("energy_centers_ev"), 3, "mirror energy nodes"
        )
        jacobian = correction.get("updated_local_slope_jacobian_per_v2")
        if not isinstance(jacobian, list) or len(jacobian) != 3:
            raise CandidateContractError("mirror correction lacks a 3-by-4 Jacobian")
        rows = [
            _finite_vector(row, 4, "mirror slope Jacobian row") for row in jacobian
        ]
        try:
            budget = contract["mirror"]["theory_requirements"]["l0_acceptance_budget"]
            tolerance = derive_mirror_l0_slope_tolerance_per_v(
                float(budget["minimum_mass_resolution"]),
                float(budget["mirror_time_width_fraction"]),
                tuple(energies),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError("mirror L0 acceptance budget is invalid") from error
        projected_change = [
            sum(row[index] * delta[index] for index in range(4)) for row in rows
        ]
        predicted = [
            slopes[index] + projected_change[index] for index in range(3)
        ]
        accepted = all(abs(value) <= tolerance for value in predicted)
        result["mirror_l0_gate_prediction"] = {
            "method": "current_fixed_grid_local_jacobian_linear_prediction",
            "accepted": accepted,
            "acceptance_tolerance_per_v": tolerance,
            "base_normalized_period_slopes_per_v": slopes,
            "projected_slope_change_per_v": projected_change,
            "predicted_normalized_period_slopes_per_v": predicted,
            "authority": "advisory_local_bare_mirror_prediction__not_a_terminal_system_gate",
        }
        if not accepted:
            result["qualification"] = (
                "bare_mirror_prediction_outside_old_zero_slope_budget__"
                "complete_system_response_required"
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def materialize_te1_variation_from_diagnostics(
    *, reference_path: Path, first_diagnostic_path: Path, first_coordinate: float,
    second_diagnostic_path: Path, second_coordinate: float, output_path: Path,
    mirror_period_path: Path | None = None,
    mirror_correction_path: Path | None = None,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    """Fit detector-plane dt/dz=0 and write one continuous schema-1 TE1 variation."""
    coordinates = (float(first_coordinate), float(second_coordinate))
    if not all(math.isfinite(value) for value in coordinates):
        raise CandidateContractError("TE1 diagnostic coordinates must be finite")
    if coordinates[0] == coordinates[1]:
        raise CandidateContractError("TE1 diagnostic coordinates must differ")
    slopes = (
        _detector_plane_initial_z_slope(first_diagnostic_path),
        _detector_plane_initial_z_slope(second_diagnostic_path),
    )
    slope_delta = slopes[1] - slopes[0]
    if slope_delta == 0.0:
        raise CandidateContractError("detector-plane dt/dz slopes must differ")
    unconstrained_root_coordinate = coordinates[0] - slopes[0] * (
        coordinates[1] - coordinates[0]
    ) / slope_delta
    if not math.isfinite(unconstrained_root_coordinate):
        raise CandidateContractError("TE1 detector-plane root coordinate is not finite")
    if contract_path is None:
        raise CandidateContractError(
            "TE1 detector-plane root requires the relative voltage trust-region contract"
        )
    contract = _load_object(contract_path, "MR-TOF contract")
    try:
        maximum_relative_step = float(
            contract["downstream_fixed_grid_workpoint_profile"]
            ["jacobian_relative_step_tiers"]["coarse"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("coarse relative voltage step is invalid") from error
    if not math.isfinite(maximum_relative_step) or not 0.0 < maximum_relative_step < 1.0:
        raise CandidateContractError(
            "coarse relative voltage step must be between zero and one"
        )
    _, reference_coordinate, base, reference_delta = _te1_reference(reference_path)
    voltage_direction = [delta / reference_coordinate for delta in reference_delta]
    if not any(direction != 0.0 for direction in voltage_direction):
        raise CandidateContractError("TE1 reference direction has no voltage response")
    current_voltages = [
        voltage + coordinates[1] * direction
        for voltage, direction in zip(base[1:], voltage_direction, strict=True)
    ]
    active_coordinate_limits = [
        maximum_relative_step * abs(voltage) / abs(direction)
        for voltage, direction in zip(current_voltages, voltage_direction, strict=True)
        if direction != 0.0
    ]
    maximum_coordinate_step = min(active_coordinate_limits)
    if maximum_coordinate_step <= 0.0:
        raise CandidateContractError(
            "TE1 trust region cannot step from a zero active mirror voltage"
        )
    requested_step = unconstrained_root_coordinate - coordinates[1]
    applied_step = max(-maximum_coordinate_step, min(maximum_coordinate_step, requested_step))
    root_coordinate = coordinates[1] + applied_step

    return materialize_scaled_te1_variation(
        reference_path=reference_path,
        coordinate=root_coordinate,
        output_path=output_path,
        mirror_period_path=mirror_period_path,
        mirror_correction_path=mirror_correction_path,
        contract_path=contract_path,
        detector_plane_root_fit={
            "method": "two_point_continuous_secant_with_relative_voltage_trust_region",
            "target_detector_dt_d_initial_z_us_per_mm": 0.0,
            "unconstrained_coordinate": unconstrained_root_coordinate,
            "anchor_coordinate": coordinates[1],
            "applied_coordinate": root_coordinate,
            "requested_coordinate_step": requested_step,
            "applied_coordinate_step": applied_step,
            "maximum_coordinate_step": maximum_coordinate_step,
            "maximum_relative_voltage_step": maximum_relative_step,
            "trust_region_clipped": not math.isclose(
                applied_step, requested_step, rel_tol=0.0, abs_tol=1e-15
            ),
            "samples": [
                {
                    "coordinate": coordinate,
                    "detector_dt_d_initial_z_us_per_mm": slope,
                    "diagnostic_path": str(path.resolve()),
                }
                for coordinate, slope, path in zip(
                    coordinates, slopes,
                    (first_diagnostic_path, second_diagnostic_path), strict=True,
                )
            ],
        },
    )


def compare_te1_diagnostics(
    *, baseline_path: Path, probe_path: Path, root_path: Path,
    probe_coordinate: float, root_coordinate: float, baseline_coordinate: float = 0.0,
    baseline_focus_path: Path | None = None,
    probe_focus_path: Path | None = None,
    root_focus_path: Path | None = None,
) -> dict[str, Any]:
    """Compare formal baseline/root metrics and keep the probe focus-only."""
    focus_paths = {
        "baseline": baseline_focus_path or baseline_path,
        "probe": probe_focus_path or probe_path,
        "root": root_focus_path or root_path,
    }
    focus_response_samples = []
    for label, coordinate in (
        ("baseline", float(baseline_coordinate)),
        ("probe", float(probe_coordinate)),
        ("root", float(root_coordinate)),
    ):
        focus_path = focus_paths[label]
        focus_value = _load_object(focus_path, f"{label} focus diagnostic")
        try:
            focus_particle_count = int(focus_value["cohort"]["particle_count"])
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError(
                f"{label} focus diagnostic lacks its particle count"
            ) from error
        if focus_particle_count <= 0:
            raise CandidateContractError(
                f"{label} focus diagnostic particle count is invalid"
            )
        focus_response_samples.append({
            "label": label,
            "te1_coordinate": coordinate,
            "particle_count": focus_particle_count,
            "detector_dt_d_initial_z_us_per_mm": (
                _detector_plane_initial_z_slope(focus_path)
            ),
            "controlled_detector_focus": (
                focus_value.get("controlled_detector_focus")
                if isinstance(focus_value.get("controlled_detector_focus"), dict)
                else None
            ),
            "diagnostic_path": str(focus_path.resolve()),
        })
    focus_by_label = {sample["label"]: sample for sample in focus_response_samples}

    samples: list[dict[str, Any]] = []
    for label, coordinate, path in (
        ("baseline", float(baseline_coordinate), baseline_path),
        ("root", float(root_coordinate), root_path),
    ):
        value = _load_object(path, f"{label} source-z timing diagnostic")
        if (
            value.get("schema_version") != 1
            or value.get("role") != "mrtof_source_z_energy_timing_diagnostic"
            or value.get("status") != "candidate_diagnostic"
        ):
            raise CandidateContractError(f"{label} diagnostic identity is invalid")
        try:
            count = int(value["cohort"]["particle_count"])
            hits = int(value["cohort"]["detector_hit_count"])
            source_identity = str(value["evidence"]["source_state_table"]["sha256"]).lower()
            timing = value["terminal_plane_diagnostic"]["detector_plane"]["absolute_time"]
            median = float(timing["median"])
            method = timing.get("method_id", "legacy_histogram_unversioned")
            if method != "common_gaussian_kde_time_v1":
                raise CandidateContractError("TE1 comparison requires current frozen KDE metrics")
            raw_fwhm = timing["fwhm"]
            fwhm = None if raw_fwhm is None else float(raw_fwhm)
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError(f"{label} diagnostic lacks detector metrics") from error
        if count <= 0 or hits < 2 or hits > count:
            raise CandidateContractError(f"{label} diagnostic cohort counts are invalid")
        if len(source_identity) != 64:
            raise CandidateContractError(f"{label} diagnostic source identity is invalid")
        if not all(math.isfinite(item) for item in (coordinate, median)):
            raise CandidateContractError(f"{label} detector timing metrics are invalid")
        if fwhm is not None and (not math.isfinite(fwhm) or fwhm <= 0.0):
            raise CandidateContractError(f"{label} detector FWHM is invalid")
        z0 = value.get("central_plane_focus_history", {}).get("target_return_crossing", {})
        z0_metrics = {
            "z0_reached_particle_count": None,
            "z0_reached_fraction": None,
            "z0_dt_d_initial_z_us_per_mm": None,
            "z0_tof_median_us": None,
            "z0_tof_fwhm_us": None,
            "z0_mass_resolution_t_over_2fwhm": None,
        }
        if isinstance(z0, dict) and z0.get("status") == "observed":
            try:
                z0_timing = z0["absolute_time"]
                z0_reached = int(z0["reached_particle_count"])
                z0_median = float(z0_timing["median"])
                z0_fwhm_raw = z0_timing["fwhm"]
                z0_fwhm = None if z0_fwhm_raw is None else float(z0_fwhm_raw)
                z0_slope = float(z0["focus_residual_us_per_mm"])
            except (KeyError, TypeError, ValueError) as error:
                raise CandidateContractError(f"{label} diagnostic has invalid z=0 metrics") from error
            if not 2 <= z0_reached <= count or not all(
                math.isfinite(item) for item in (z0_median, z0_slope)
            ):
                raise CandidateContractError(f"{label} diagnostic z=0 metrics are invalid")
            if z0_fwhm is not None and (not math.isfinite(z0_fwhm) or z0_fwhm <= 0.0):
                raise CandidateContractError(f"{label} diagnostic z=0 FWHM is invalid")
            z0_metrics = {
                "z0_reached_particle_count": z0_reached,
                "z0_reached_fraction": z0_reached / count,
                "z0_dt_d_initial_z_us_per_mm": z0_slope,
                "z0_tof_median_us": z0_median,
                "z0_tof_fwhm_us": z0_fwhm,
                "z0_mass_resolution_t_over_2fwhm": (
                    z0_timing.get("time_equivalent_resolution")
                ),
            }
        samples.append({
            "label": label,
            "te1_coordinate": coordinate,
            "particle_count": count,
            "detector_hit_count": hits,
            "collection_rate": hits / count,
            "detector_dt_d_initial_z_us_per_mm": (
                focus_by_label[label]["detector_dt_d_initial_z_us_per_mm"]
            ),
            "detector_tof_median_us": median,
            "detector_tof_mean_us": timing.get("mean"),
            "peak_method_id": method,
            "peak_analysis_contract": timing.get("analysis_contract"),
            "detector_tof_fwhm_us": fwhm,
            "mass_resolution_t_over_2fwhm": (
                timing.get("time_equivalent_resolution")
            ),
            "focus_particle_count": focus_by_label[label]["particle_count"],
            "focus_diagnostic_path": focus_by_label[label]["diagnostic_path"],
            **z0_metrics,
            "diagnostic_path": str(path.resolve()),
            "_source_identity": source_identity,
        })
    if len({sample["particle_count"] for sample in samples}) != 1:
        raise CandidateContractError(
            "formal TE1 baseline/root diagnostics must use equal particle counts"
        )
    if len({sample["_source_identity"] for sample in samples}) != 1:
        raise CandidateContractError("TE1 comparison diagnostics must use the same source states")
    for sample in samples:
        del sample["_source_identity"]
    baseline, root = samples
    if baseline["peak_analysis_contract"] is None or baseline["peak_analysis_contract"] != root["peak_analysis_contract"]:
        raise CandidateContractError("formal TE1 comparison requires identical frozen peak analysis contracts")
    particle_count = int(baseline["particle_count"])
    baseline_fwhm = baseline["detector_tof_fwhm_us"]
    root_fwhm = root["detector_tof_fwhm_us"]
    baseline_resolution = baseline["mass_resolution_t_over_2fwhm"]
    root_resolution = root["mass_resolution_t_over_2fwhm"]
    baseline_z0_resolution = baseline["z0_mass_resolution_t_over_2fwhm"]
    root_z0_resolution = root["z0_mass_resolution_t_over_2fwhm"]
    return {
        "schema_version": 1,
        "role": "mrtof_detector_plane_te1_comparison",
        "status": "candidate_comparison",
        "qualification": f"paired_n{particle_count}_candidate_diagnostic__not_formal",
        "paired_source_states_verified": True,
        "formal_metric_scope": "baseline_and_root_only",
        "probe_scope": "controlled_focus_response_only__excluded_from_collection_and_fwhm",
        "samples": samples,
        "focus_response_samples": focus_response_samples,
        "root_vs_baseline": {
            "detector_hit_count_delta": root["detector_hit_count"] - baseline["detector_hit_count"],
            "collection_rate_delta": root["collection_rate"] - baseline["collection_rate"],
            "absolute_dt_dz_ratio": (
                abs(root["detector_dt_d_initial_z_us_per_mm"])
                / abs(baseline["detector_dt_d_initial_z_us_per_mm"])
                if baseline["detector_dt_d_initial_z_us_per_mm"] != 0.0 else None
            ),
            "fwhm_ratio": (
                root_fwhm / baseline_fwhm
                if root_fwhm is not None and baseline_fwhm is not None else None
            ),
            "mass_resolution_ratio": (
                root_resolution / baseline_resolution
                if root_resolution is not None and baseline_resolution is not None else None
            ),
            "z0_reached_particle_count_delta": (
                root["z0_reached_particle_count"] - baseline["z0_reached_particle_count"]
                if root["z0_reached_particle_count"] is not None
                and baseline["z0_reached_particle_count"] is not None else None
            ),
            "z0_absolute_dt_dz_ratio": (
                abs(root["z0_dt_d_initial_z_us_per_mm"])
                / abs(baseline["z0_dt_d_initial_z_us_per_mm"])
                if root["z0_dt_d_initial_z_us_per_mm"] is not None
                and baseline["z0_dt_d_initial_z_us_per_mm"] not in (None, 0.0) else None
            ),
            "z0_mass_resolution_ratio": (
                root_z0_resolution / baseline_z0_resolution
                if root_z0_resolution is not None and baseline_z0_resolution is not None else None
            ),
        },
    }


def _verify_manifest(manifest: dict[str, Any], manifest_path: Path) -> None:
    """Verify the manifest structure and run config; consumers verify used records."""
    try:
        verify_record("run_config", manifest["run_config"], base_dir=manifest_path.parent)
        inputs, outputs = manifest.get("inputs"), manifest.get("outputs")
        if not isinstance(inputs, dict) or not isinstance(outputs, list):
            raise AssertionError("manifest inputs/outputs have invalid containers")
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError(f"manifest record verification failed: {error}") from error


def _unique_output(manifest: dict[str, Any], path: Path, label: str) -> dict[str, Any]:
    target = path.resolve()
    matches = [
        record for record in manifest.get("outputs", [])
        if isinstance(record, dict) and isinstance(record.get("path"), str)
        and Path(record["path"]).resolve() == target
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"{label} is not a unique manifest output")
    try:
        verify_record(label, matches[0], base_dir=target.parent)
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError(f"{label} record verification failed: {error}") from error
    return matches[0]


def _load_source_rows(
    *, run_dir: Path, manifest: dict[str, Any], expected_count: int,
) -> tuple[
    dict[int, dict[str, float]],
    dict[str, Any],
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[dict[str, Any]],
]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("flight manifest inputs are missing")
    try:
        verify_record("bunch-source receipt", inputs["bunch_source_receipt"], base_dir=run_dir)
        verify_record(
            "bunch-source run manifest", inputs["bunch_source_run_manifest"],
            base_dir=run_dir,
        )
        receipt_path = record_path(inputs["bunch_source_receipt"], base_dir=run_dir)
        source_manifest_path = record_path(inputs["bunch_source_run_manifest"], base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError("flight manifest lacks frozen bunch-source inputs") from error
    receipt = _load_object(receipt_path, "bunch-source receipt")
    expected_ids = list(range(1, expected_count + 1))
    expected_ids_sha256 = hashlib.sha256(
        json.dumps(expected_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (
        receipt.get("role") != "mrtof_deterministic_ideal_bunch_source"
        or receipt.get("status") != "materialized"
    ):
        raise CandidateContractError("source receipt identity differs from the flight run")
    source_manifest = _load_object(source_manifest_path, "bunch-source run manifest")
    if (
        source_manifest.get("project") != _PROJECT
        or source_manifest.get("mode") != "deterministic_bunch_source_materialization"
        or source_manifest.get("status") != "success"
    ):
        raise CandidateContractError("bunch-source run manifest is not successful")
    _verify_manifest(source_manifest, source_manifest_path)
    receipt_matches = [
        record for record in source_manifest.get("outputs", [])
        if isinstance(record, dict)
        and str(record.get("sha256", "")).lower() == _sha256(receipt_path).lower()
        and Path(str(record.get("path", ""))).name == "bunch_source_receipt.json"
    ]
    if len(receipt_matches) != 1:
        raise CandidateContractError("copied source receipt is not uniquely bound to its source run")
    try:
        verify_record("source state table receipt", receipt["state_table"])
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError("bunch-source receipt records failed verification") from error
    state_path = Path(str(receipt["state_table"]["path"])).resolve()
    _unique_output(source_manifest, state_path, "source state table")
    with state_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [int(row["particle_id"]) for row in rows]
    run_config_path = record_path(manifest["run_config"], base_dir=run_dir)
    run_config = _load_object(run_config_path, "flight run config")
    parameters = run_config.get("parameters")
    selection = parameters.get("source_selection") if isinstance(parameters, dict) else None
    selected_parent_min = 1
    selected_parent_max = expected_count
    if selection is None:
        if (
            receipt.get("particle_count") != expected_count
            or receipt.get("expected_particle_ids") != expected_ids
            or str(receipt.get("expected_particle_ids_sha256", "")).lower()
            != expected_ids_sha256
            or ids != expected_ids
        ):
            raise CandidateContractError(
                "source receipt identity or particle cohort differs from the flight run"
            )
        selected_rows = rows
    else:
        if not isinstance(selection, dict):
            raise CandidateContractError("source selection must be an object")
        try:
            particle_id_min = int(selection["particle_id_min"])
            particle_id_max = int(selection["particle_id_max"])
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError("source selection interval is incomplete") from error
        resolved = resolve_bunch_source_interval(
            receipt_path=receipt_path,
            particle_id_min=particle_id_min,
            particle_id_max=particle_id_max,
        )
        resolved_selection = resolved["source_cohort"]["selection"]
        if (
            len(resolved["particle_ids"]) != expected_count
            or selection != resolved_selection
            or parameters.get("source_cohort") != resolved["source_cohort"]
        ):
            raise CandidateContractError(
                "source selection identity or particle cohort differs from the flight run"
            )
        selected_rows = rows[particle_id_min - 1:particle_id_max]
        selected_parent_min = particle_id_min
        selected_parent_max = particle_id_max
    parsed: dict[int, dict[str, float]] = {}
    for ion, row in zip(expected_ids, selected_rows, strict=True):
        try:
            values = {
                name: float(row[name]) for name in (
                    "tob_us", "mass_th", "kinetic_energy_ev", "x_mm", "y_mm", "z_mm",
                    "direction_x", "direction_y", "direction_z",
                )
            }
            values["charge_e"] = float(int(row["charge_e"]))
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError(f"source state for ion {ion} is incomplete") from error
        if not all(math.isfinite(value) for value in values.values()) or values["mass_th"] <= 0.0:
            raise CandidateContractError(f"source state for ion {ion} is nonphysical")
        parsed[ion] = values
    def selected_pair(name: str) -> dict[str, Any] | None:
        pair = receipt.get(name)
        if not isinstance(pair, dict):
            return pair
        try:
            negative = int(pair["negative_particle_id"])
            positive = int(pair["positive_particle_id"])
        except (KeyError, TypeError, ValueError):
            return pair
        if not (
            selected_parent_min <= negative <= selected_parent_max
            and selected_parent_min <= positive <= selected_parent_max
        ):
            return None
        active = dict(pair)
        active["negative_particle_id"] = negative - selected_parent_min + 1
        active["positive_particle_id"] = positive - selected_parent_min + 1
        return active

    selected_position_pairs = []
    for pair in receipt.get("controlled_position_pairs", []):
        if not isinstance(pair, dict):
            continue
        try:
            negative = int(pair["negative_particle_id"])
            positive = int(pair["positive_particle_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            selected_parent_min <= negative <= selected_parent_max
            and selected_parent_min <= positive <= selected_parent_max
        ):
            active = dict(pair)
            active["negative_particle_id"] = negative - selected_parent_min + 1
            active["positive_particle_id"] = positive - selected_parent_min + 1
            selected_position_pairs.append(active)

    return parsed, {
        "source_run_manifest": {"path": str(source_manifest_path), "sha256": _sha256(source_manifest_path)},
        "source_state_table": receipt["state_table"],
    }, selected_pair("controlled_focus_pair"), selected_pair(
        "controlled_slow_energy_pair"
    ), selected_pair("controlled_transverse_x_pair"), selected_position_pairs


def _manifest_output_matches(manifest: dict[str, Any], path: Path, sha256: str, label: str) -> None:
    record = _unique_output(manifest, path, label)
    if str(record.get("sha256", "")).lower() != sha256.lower():
        raise CandidateContractError(f"{label} receipt identity differs from the flight manifest")


def _event_batches(
    *, run_dir: Path, manifest: dict[str, Any], particle_count: int,
) -> list[tuple[Path, int, int]]:
    inputs = manifest.get("inputs")
    if isinstance(inputs, dict) and "batch_log_merge_receipt" in inputs:
        try:
            verify_record(
                "batch-log merge receipt", inputs["batch_log_merge_receipt"],
                base_dir=run_dir,
            )
        except (AssertionError, KeyError, TypeError) as error:
            raise CandidateContractError(
                f"batch-log merge receipt verification failed: {error}"
            ) from error
        receipt_path = record_path(inputs["batch_log_merge_receipt"], base_dir=run_dir)
        receipt = _load_object(receipt_path, "batch-log merge receipt")
        if (
            receipt.get("role") != "mrtof_rebased_batch_log_merge"
            or receipt.get("status") != "success"
            or receipt.get("particle_count") != particle_count
            or receipt.get("global_particle_ids") != [1, particle_count]
            or receipt.get("all_batch_losses_retained") is not True
        ):
            raise CandidateContractError("batch-log merge receipt does not cover the complete cohort")
        batches = receipt.get("batches")
        if not isinstance(batches, list) or not batches:
            raise CandidateContractError("batch-log merge receipt has no batches")
        result: list[tuple[Path, int, int]] = []
        covered: list[int] = []
        for index, batch in enumerate(batches, start=1):
            if not isinstance(batch, dict):
                raise CandidateContractError("batch-log merge receipt has an invalid batch")
            try:
                path = Path(str(batch["path"])).resolve()
                offset, count = int(batch["offset"]), int(batch["count"])
                sha256 = str(batch["sha256"])
            except (KeyError, TypeError, ValueError) as error:
                raise CandidateContractError("batch-log merge receipt has an incomplete batch") from error
            if offset < 0 or count < 1:
                raise CandidateContractError("batch-log offset/count is invalid")
            _manifest_output_matches(manifest, path, sha256, f"native batch log {index}")
            covered.extend(range(offset + 1, offset + count + 1))
            result.append((path, offset, count))
        if covered != list(range(1, particle_count + 1)):
            raise CandidateContractError("batch logs do not cover the cohort exactly once")
        return result
    path = run_dir / "logs" / "native_two_prism_flight.log"
    _unique_output(manifest, path, "merged native flight log")
    return [(path, 0, particle_count)]


def _load_selected_events(
    batches: Iterable[tuple[Path, int, int]],
) -> tuple[dict[tuple[str, int], list[dict[str, Any]]], list[dict[str, Any]]]:
    selected: dict[tuple[str, int], list[dict[str, Any]]] = {}
    evidence: list[dict[str, Any]] = []
    for path, offset, count in batches:
        text = path.read_text(encoding="utf-8-sig")
        completions = list(FLY_COMPLETED.finditer(text))
        if len(completions) != 1 or int(completions[0].group("splats")) != count:
            raise CandidateContractError(f"native log completion differs from its batch plan: {path}")
        for event in parse_events(text):
            local_id = int(event.get("ion", -1))
            if not 1 <= local_id <= count:
                raise CandidateContractError(f"native log event ID is outside its batch: {path}")
            if event["kind"] not in _SELECTED_EVENT_KINDS:
                continue
            event = dict(event)
            event["ion"] = local_id + offset
            selected.setdefault((event["kind"], int(event["ion"])), []).append(event)
        evidence.append({"path": str(path), "sha256": _sha256(path), "offset": offset, "count": count})
    return selected, evidence


def _one(
    events: dict[tuple[str, int], list[dict[str, Any]]], kind: str, ion: int,
) -> dict[str, Any]:
    matches = events.get((kind, ion), [])
    if len(matches) != 1:
        raise CandidateContractError(f"ion {ion} does not have exactly one {kind} event")
    return matches[0]


def _association(xs: list[float], ys: list[float], slope_unit: str) -> dict[str, Any]:
    if len(xs) != len(ys) or len(xs) < 2:
        raise CandidateContractError("diagnostic vectors must contain at least two paired values")
    if not all(math.isfinite(value) for value in (*xs, *ys)):
        raise CandidateContractError("diagnostic vectors contain a non-finite value")
    if min(xs) == max(xs):
        return {
            "status": "invariant_initial_z__association_not_defined",
            "slope": None,
            "slope_unit": slope_unit,
            "pearson_r": None,
            "r_squared": None,
        }
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    variance = sum((value - mx) ** 2 for value in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / variance
    correlation = _pearson(xs, ys) if len(xs) >= 3 else None
    return {
        "status": "descriptive_linear_association",
        "slope": slope,
        "slope_unit": slope_unit,
        "pearson_r": correlation,
        "r_squared": None if correlation is None else correlation * correlation,
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Return the descriptive Pearson coefficient for finite paired values."""
    if len(xs) != len(ys) or len(xs) < 3:
        raise CandidateContractError("correlation vectors are incomplete")
    if min(xs) == max(xs) or min(ys) == max(ys):
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    covariance = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)
    )
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    if variance_x == 0.0 or variance_y == 0.0:
        return None
    return covariance / math.sqrt(variance_x * variance_y)


def _distribution(
    xs: list[float], ys: list[float], *, value_unit: str, slope_unit: str,
    include_histogram_width: bool = True,
) -> dict[str, Any]:
    return {
        "sample_count": len(ys),
        "median": statistics.median(ys),
        "value_unit": value_unit,
        "fwhm": _fwhm(ys) if include_histogram_width else None,
        "range": [min(ys), max(ys)],
        "initial_z_association": _association(xs, ys, slope_unit),
    }


def _time_plane_distribution(
    xs: list[float], times_us: list[float], *, peak_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _distribution(xs, times_us, value_unit="us", slope_unit="us/mm", include_histogram_width=False)
    result.update(peak_time_metrics(times_us, **(peak_context or {
        "mass_th": None, "analysis_contract": None, "cohort_role": None,
    })))
    return result


def _event_values(
    events: dict[tuple[str, int], list[dict[str, Any]]],
    kind: str,
    ids: list[int],
    field: str,
) -> list[float]:
    try:
        values = [float(_one(events, kind, ion)[field]) for ion in ids]
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(f"{kind} lacks finite numeric field {field}") from error
    if not all(math.isfinite(value) for value in values):
        raise CandidateContractError(f"{kind}.{field} contains a non-finite value")
    return values


def _one_terminal_plane_event(
    events: dict[tuple[str, int], list[dict[str, Any]]],
    *,
    ion: int,
    kind: str,
    after_time_us: float,
) -> dict[str, Any]:
    matches = []
    for event in events.get((kind, ion), []):
        if float(event["t_us"]) <= after_time_us:
            continue
        if kind == "detector_plane" and event.get("direction_z") != -1:
            continue
        matches.append(event)
    if len(matches) != 1:
        raise CandidateContractError(
            f"ion {ion} does not have exactly one terminal {kind} event after the positive mirror turn"
        )
    return matches[0]


def _terminal_plane_diagnostic(
    *,
    events: dict[tuple[str, int], list[dict[str, Any]]],
    hit_ids: list[int],
    hit_source_z: list[float],
    peak_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    turns = [_one(events, "return_positive_mirror_turn", ion) for ion in hit_ids]
    detector_plane = [
        _one_terminal_plane_event(
            events,
            ion=ion,
            kind="detector_plane",
            after_time_us=float(turn["t_us"]),
        )
        for ion, turn in zip(hit_ids, turns, strict=True)
    ]
    turn_times = [float(event["t_us"]) for event in turns]
    detector_times = [float(event["t_us"]) for event in detector_plane]
    detector_z = [float(event["z_mm"]) for event in detector_plane]
    if max(detector_z) - min(detector_z) > 1e-3:
        raise CandidateContractError("detector diagnostic plane is not a fixed physical z plane")
    actual_detector_z = statistics.median(detector_z)
    detector_timing = _time_plane_distribution(hit_source_z, detector_times, peak_context=peak_context)
    return {
        "qualification": (
            "observed_positive_mirror_turn_and_detector_plane__"
            "diagnostic_only__not_detector_relocation_authority"
        ),
        "positive_mirror_turn": {
            "z": _distribution(
                hit_source_z,
                [float(event["z_mm"]) for event in turns],
                value_unit="mm",
                slope_unit="mm/mm",
            ),
            "absolute_time": _distribution(
                hit_source_z, turn_times, value_unit="us", slope_unit="us/mm",
            ),
        },
        "detector_plane": {
            "z_mm": actual_detector_z,
            "absolute_time": detector_timing,
            "increment_from_positive_mirror_turn": _distribution(
                hit_source_z,
                [value - start for value, start in zip(detector_times, turn_times, strict=True)],
                value_unit="us",
                slope_unit="us/mm",
            ),
        },
    }


def _central_plane_focus_history(
    *,
    events: dict[tuple[str, int], list[dict[str, Any]]],
    expected_ids: list[int],
    source_rows: dict[int, dict[str, float]],
    controlled_pair: dict[str, Any] | None,
    source_z_by_ion: dict[int, float],
    target_crossing_index: int,
    hit_ids: list[int],
    hit_source_z: list[float],
    peak_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    groups: dict[tuple[int, int], dict[int, dict[str, Any]]] = {}
    for ion in expected_ids:
        for event in events.get(("central_plane_directional", ion), []):
            identity = (int(event["n"]), int(event["direction_z"]))
            if ion in groups.setdefault(identity, {}):
                raise CandidateContractError(
                    f"ion {ion} has duplicate central-plane identity {identity}"
                )
            groups[identity][ion] = event
    complete = []
    if len(hit_ids) >= 2:
        for (index, direction), group in sorted(groups.items()):
            if any(ion not in group for ion in hit_ids):
                continue
            times = [float(group[ion]["t_us"]) for ion in hit_ids]
            complete.append({
                "crossing_index": index,
                "direction_z": direction,
                "absolute_time": _distribution(
                    hit_source_z, times, value_unit="us", slope_unit="us/mm",
                ),
            })
    target_groups = [
        (direction, group)
        for (index, direction), group in groups.items()
        if index == target_crossing_index
    ]
    if len(target_groups) > 1:
        raise CandidateContractError(
            "target central-plane crossing has more than one direction identity"
        )
    target_return: dict[str, Any]
    if target_groups:
        direction, group = target_groups[0]
        ids = [ion for ion in expected_ids if ion in group]
        if len(ids) >= 2:
            timing = _time_plane_distribution(
                [source_z_by_ion[ion] for ion in ids],
                [float(group[ion]["t_us"]) for ion in ids],
                peak_context=peak_context,
            )
            target_return = {
                "status": "observed",
                "crossing_index": target_crossing_index,
                "direction_z": direction,
                "reached_particle_count": len(ids),
                "fraction_of_source_cohort": len(ids) / len(expected_ids),
                "absolute_time": timing,
                "focus_residual_us_per_mm": timing["initial_z_association"]["slope"],
                "scope": (
                    "all_source_cohort_particles_reaching_this_z0_crossing__"
                    "no_detector_hit_filter"
                ),
            }
        else:
            target_return = {
                "status": "unavailable",
                "reason": "fewer_than_two_particles_reach_target_z0_crossing",
                "reached_particle_count": len(ids),
            }
    else:
        target_return = {
            "status": "unavailable",
            "reason": "target_z0_crossing_not_observed",
            "reached_particle_count": 0,
        }
    if controlled_pair is None:
        controlled_z_only = {
            "status": "unavailable",
            "reason": "controlled_focus_pair_not_declared",
            "qualification": "diagnostic_only__not_a_focus_gate",
        }
    else:
        negative = int(controlled_pair["negative_particle_id"])
        positive = int(controlled_pair["positive_particle_id"])
        controlled_ids = [negative, 1, positive]
        controlled_z_only = {
            "status": "unavailable",
            "reason": "controlled_triplet_not_observed_at_same_target_crossing",
            "particle_ids": controlled_ids,
            "crossing_index": target_crossing_index,
            "direction_z": target_return.get("direction_z"),
            "coordinate_unit": "mm",
            "time_unit": "us",
            "qualification": "controlled_z_only_three_point_diagnostic_only__not_a_focus_gate",
        }
        if target_groups and all(ion in target_groups[0][1] for ion in controlled_ids):
            direction, group = target_groups[0]
            z_negative = source_rows[negative]["z_mm"]
            z_center = source_rows[1]["z_mm"]
            z_positive = source_rows[positive]["z_mm"]
            t_negative = float(group[negative]["t_us"])
            t_center = float(group[1]["t_us"])
            t_positive = float(group[positive]["t_us"])
            controlled_z_only = {
                "status": "observed",
                "particle_ids": controlled_ids,
                "crossing_index": target_crossing_index,
                "direction_z": direction,
                "initial_z_mm": [z_negative, z_center, z_positive],
                "crossing_time_us": [t_negative, t_center, t_positive],
                "dt_d_initial_z_us_per_mm": (
                    (t_positive - t_negative) / (z_positive - z_negative)
                ),
                "second_order_center_deviation_us": (
                    (t_positive + t_negative) / 2.0 - t_center
                ),
                "coordinate_unit": "mm",
                "time_unit": "us",
                "scope": (
                    "same_energy_direction_x_y_mass_charge_birth_time__z_only_triplet__"
                    "same_target_return_crossing"
                ),
                "qualification": (
                    "controlled_z_only_three_point_diagnostic_only__not_a_focus_gate"
                ),
            }
    target_return["controlled_z_only_focus"] = controlled_z_only
    result = {
        "status": "observed" if complete or target_return["status"] == "observed" else "unavailable",
        "plane_z_mm": 0.0,
        "target_return_crossing": target_return,
        "complete_crossing_count": len(complete),
        "last_complete_crossing": complete[-1] if complete else None,
        "last_ten_complete_crossings": complete[-10:],
        "qualification": (
            "target_return_uses_all_particles_reaching_z0__history_is_detector_hit_conditioned__"
            "diagnostic_resolution_not_formal_qualification"
        ),
    }
    if not complete:
        result["history_reason"] = (
            "no_central_plane_directional_identity_covers_every_detector_hit"
        )
    return result


def _controlled_detector_focus(
    *,
    pair: dict[str, Any] | None,
    source_rows: dict[int, dict[str, float]],
    events: dict[tuple[str, int], list[dict[str, Any]]],
    terminal_codes: dict[int, int],
) -> dict[str, Any] | None:
    """Measure detector dt/dz from the frozen centre-state -z/+z pair."""
    if pair is None:
        return None
    try:
        negative = int(pair["negative_particle_id"])
        positive = int(pair["positive_particle_id"])
        declared_span = float(pair["coordinate_span_mm"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("controlled focus pair metadata is incomplete") from error
    if (
        pair.get("coordinate") != "z_mm"
        or negative == positive
        or negative not in source_rows
        or positive not in source_rows
        or not math.isfinite(declared_span)
        or declared_span <= 0.0
    ):
        raise CandidateContractError("controlled focus pair metadata is invalid")
    negative_state, positive_state = source_rows[negative], source_rows[positive]
    center_state = source_rows.get(1)
    fixed = (
        "tob_us", "mass_th", "charge_e", "kinetic_energy_ev", "x_mm", "y_mm",
        "direction_x", "direction_y", "direction_z",
    )
    actual_span = positive_state["z_mm"] - negative_state["z_mm"]
    if (
        any(negative_state[name] != positive_state[name] for name in fixed)
        or center_state is None
        or any(negative_state[name] != center_state[name] for name in fixed)
        or not math.isclose(actual_span, declared_span, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(
            (positive_state["z_mm"] + negative_state["z_mm"]) / 2.0,
            center_state["z_mm"], rel_tol=0.0, abs_tol=1e-12,
        )
    ):
        raise CandidateContractError(
            "controlled focus pair changes variables other than initial z"
        )
    triplet_ids = [negative, 1, positive]
    triplet_initial_z = [
        negative_state["z_mm"], center_state["z_mm"], positive_state["z_mm"],
    ]
    triplet_terminal_codes = [terminal_codes[ion] for ion in triplet_ids]
    common = {
        # Keep the original endpoint-only fields for existing focus consumers.
        "particle_ids": [negative, positive],
        "initial_z_mm": [negative_state["z_mm"], positive_state["z_mm"]],
        "initial_z_span_mm": actual_span,
        "terminal_codes": [terminal_codes[negative], terminal_codes[positive]],
        "three_point_particle_ids": triplet_ids,
        "three_point_initial_z_mm": triplet_initial_z,
        "three_point_terminal_codes": triplet_terminal_codes,
        "three_point_scope": (
            "same_energy_direction_x_y_mass_charge_birth_time__z_only_triplet"
        ),
        "three_point_qualification": (
            "controlled_z_only_three_point_detector_diagnostic_only__not_a_focus_gate"
        ),
        "scope": "same_energy_direction_x_y_mass_charge_birth_time__z_only_pair",
        "qualification": "controlled_first_order_detector_focus_diagnostic_only",
    }
    if any(code != 1 for code in triplet_terminal_codes):
        return {
            "status": "unavailable",
            "reason": "one_or_both_controlled_z_particles_did_not_reach_detector",
            **common,
        }
    triplet_times = [
        float(_one(events, "detector", ion)["t_us"]) for ion in triplet_ids
    ]
    endpoint_times = [triplet_times[0], triplet_times[2]]
    return {
        "status": "observed",
        **common,
        "detector_time_us": endpoint_times,
        "center_detector_time_us": triplet_times[1],
        "three_point_detector_time_us": triplet_times,
        "dt_d_initial_z_us_per_mm": (
            (triplet_times[2] - triplet_times[0]) / actual_span
        ),
        "second_order_center_deviation_us": (
            (triplet_times[2] + triplet_times[0]) / 2.0 - triplet_times[1]
        ),
    }


def _controlled_slow_energy_response(
    *,
    pair: dict[str, Any] | None,
    source_rows: dict[int, dict[str, float]],
    events: dict[tuple[str, int], list[dict[str, Any]]],
    terminal_codes: dict[int, int],
) -> dict[str, Any] | None:
    """Measure stage timing versus release slow-energy with one N=3 triplet."""
    if pair is None:
        return None
    try:
        negative = int(pair["negative_particle_id"])
        positive = int(pair["positive_particle_id"])
        declared_span = float(pair["coordinate_span_ev"])
        half_span_per_charge = float(pair["half_span_ev_per_charge"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(
            "controlled slow-energy pair metadata is incomplete"
        ) from error
    if (
        pair.get("coordinate") != "release_slow_y_kinetic_energy_ev"
        or negative == positive
        or negative not in source_rows
        or positive not in source_rows
        or 1 not in source_rows
        or not math.isfinite(declared_span)
        or not math.isfinite(half_span_per_charge)
        or declared_span <= 0.0
        or half_span_per_charge <= 0.0
    ):
        raise CandidateContractError("controlled slow-energy pair metadata is invalid")
    negative_state = source_rows[negative]
    center_state = source_rows[1]
    positive_state = source_rows[positive]
    fixed = (
        "tob_us", "mass_th", "charge_e", "x_mm", "y_mm", "z_mm",
        "direction_x", "direction_y", "direction_z",
    )
    energies = [
        negative_state["kinetic_energy_ev"],
        center_state["kinetic_energy_ev"],
        positive_state["kinetic_energy_ev"],
    ]
    actual_span = energies[2] - energies[0]
    expected_span = 2.0 * half_span_per_charge * abs(center_state["charge_e"])
    if (
        any(
            negative_state[name] != center_state[name]
            or positive_state[name] != center_state[name]
            for name in fixed
        )
        or not math.isclose(actual_span, declared_span, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(actual_span, expected_span, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(
            (energies[2] + energies[0]) / 2.0,
            energies[1], rel_tol=0.0, abs_tol=1e-12,
        )
    ):
        raise CandidateContractError(
            "controlled slow-energy pair changes variables other than kinetic energy"
        )
    if (
        center_state["direction_x"] != 0.0
        or center_state["direction_z"] != 0.0
        or not math.isclose(
            abs(center_state["direction_y"]), 1.0, rel_tol=0.0, abs_tol=1e-12,
        )
    ):
        raise CandidateContractError(
            "controlled slow-y energy response requires a y-aligned centre direction"
        )
    particle_ids = [negative, 1, positive]
    stage_time_response: dict[str, Any] = {}
    for label, kind in (("accelerator_safe_exit", "accelerator_safe_exit"), *_CHAIN):
        matches = [events.get((kind, ion), []) for ion in particle_ids]
        if any(len(values) != 1 for values in matches):
            stage_time_response[label] = {
                "status": "unavailable",
                "reason": "controlled_triplet_event_not_observed_exactly_once",
                "event_counts": [len(values) for values in matches],
            }
            continue
        times = [float(values[0]["t_us"]) for values in matches]
        stage_time_response[label] = {
            "status": "observed",
            "times_us": times,
            "dt_d_release_slow_energy_us_per_ev": (
                (times[2] - times[0]) / actual_span
            ),
            "second_order_center_deviation_us": (
                (times[2] + times[0]) / 2.0 - times[1]
            ),
        }
    return {
        "status": "observed",
        "particle_ids": particle_ids,
        "release_slow_energy_ev": energies,
        "release_slow_energy_span_ev": actual_span,
        "half_span_ev_per_charge": half_span_per_charge,
        "terminal_codes": [terminal_codes[ion] for ion in particle_ids],
        "coordinate_unit": "eV",
        "time_unit": "us",
        "stage_time_response": stage_time_response,
        "scope": (
            "same_position_direction_mass_charge_birth_time__"
            "release_slow_y_energy_only_triplet"
        ),
        "qualification": (
            "controlled_slow_energy_three_point_diagnostic_only__"
            "not_a_resolution_gate"
        ),
    }


def _controlled_transverse_x_response(
    *,
    pair: dict[str, Any] | None,
    source_rows: dict[int, dict[str, float]],
    events: dict[tuple[str, int], list[dict[str, Any]]],
    terminal_codes: dict[int, int],
) -> dict[str, Any] | None:
    """Measure odd and even timing response from the centre-state -x/0/+x triplet."""
    if pair is None:
        return None
    try:
        negative = int(pair["negative_particle_id"])
        positive = int(pair["positive_particle_id"])
        declared_span = float(pair["coordinate_span_mm"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(
            "controlled transverse-x pair metadata is incomplete"
        ) from error
    if (
        pair.get("coordinate") != "x_mm"
        or negative == positive
        or negative not in source_rows
        or positive not in source_rows
        or 1 not in source_rows
        or not math.isfinite(declared_span)
        or declared_span <= 0.0
    ):
        raise CandidateContractError("controlled transverse-x pair metadata is invalid")
    negative_state = source_rows[negative]
    center_state = source_rows[1]
    positive_state = source_rows[positive]
    fixed = (
        "tob_us", "mass_th", "charge_e", "kinetic_energy_ev", "y_mm", "z_mm",
        "direction_x", "direction_y", "direction_z",
    )
    positions = [negative_state["x_mm"], center_state["x_mm"], positive_state["x_mm"]]
    actual_span = positions[2] - positions[0]
    if (
        any(
            negative_state[name] != center_state[name]
            or positive_state[name] != center_state[name]
            for name in fixed
        )
        or not math.isclose(actual_span, declared_span, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(
            (positions[2] + positions[0]) / 2.0,
            positions[1], rel_tol=0.0, abs_tol=1e-12,
        )
    ):
        raise CandidateContractError(
            "controlled transverse-x pair changes variables other than initial x"
        )
    particle_ids = [negative, 1, positive]
    stage_time_response: dict[str, Any] = {}
    for label, kind in (("accelerator_safe_exit", "accelerator_safe_exit"), *_CHAIN):
        matches = [events.get((kind, ion), []) for ion in particle_ids]
        if any(len(values) != 1 for values in matches):
            stage_time_response[label] = {
                "status": "unavailable",
                "reason": "controlled_triplet_event_not_observed_exactly_once",
                "event_counts": [len(values) for values in matches],
            }
            continue
        times = [float(values[0]["t_us"]) for values in matches]
        stage_time_response[label] = {
            "status": "observed",
            "times_us": times,
            "odd_dt_d_initial_x_us_per_mm": (
                (times[2] - times[0]) / actual_span
            ),
            "even_center_deviation_us": (
                (times[2] + times[0]) / 2.0 - times[1]
            ),
        }
    return {
        "status": "observed",
        "particle_ids": particle_ids,
        "initial_x_mm": positions,
        "initial_x_span_mm": actual_span,
        "terminal_codes": [terminal_codes[ion] for ion in particle_ids],
        "coordinate_unit": "mm",
        "time_unit": "us",
        "stage_time_response": stage_time_response,
        "scope": (
            "same_y_z_energy_direction_mass_charge_birth_time__initial_x_only_triplet"
        ),
        "qualification": (
            "controlled_transverse_x_three_point_diagnostic_only__"
            "not_a_resolution_gate"
        ),
    }


def _source_rows_from_receipt(
    receipt_path: Path, particle_ids: list[int],
) -> tuple[dict[int, dict[str, float]], dict[str, Any]]:
    """Read only the declared source states needed by an already completed batch."""
    receipt = _load_object(receipt_path, "bunch-source receipt")
    if (
        receipt.get("role") != "mrtof_deterministic_ideal_bunch_source"
        or receipt.get("status") != "materialized"
    ):
        raise CandidateContractError("source receipt identity is invalid")
    try:
        state_path = record_path(receipt["state_table"], base_dir=receipt_path.parent)
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError("source receipt lacks its state table") from error
    with state_path.open("r", encoding="utf-8", newline="") as stream:
        rows = {int(row["particle_id"]): row for row in csv.DictReader(stream)}
    parsed: dict[int, dict[str, float]] = {}
    for ion in particle_ids:
        try:
            row = rows[ion]
            values = {
                name: float(row[name]) for name in (
                    "tob_us", "mass_th", "kinetic_energy_ev", "x_mm", "y_mm", "z_mm",
                    "direction_x", "direction_y", "direction_z",
                )
            }
            values["charge_e"] = float(int(row["charge_e"]))
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError(
                f"source state for first-batch ion {ion} is incomplete"
            ) from error
        if not all(math.isfinite(value) for value in values.values()):
            raise CandidateContractError(
                f"source state for first-batch ion {ion} is non-finite"
            )
        parsed[ion] = values
    return parsed, receipt


def _controlled_first_batch_stage_response(
    *,
    coordinate: str,
    coordinate_unit: str,
    particle_ids: list[int],
    coordinate_values: list[float],
    events: dict[tuple[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Report the same real-event timing response for one controlled triplet."""
    span = coordinate_values[2] - coordinate_values[0]
    if len(particle_ids) != 3 or len(coordinate_values) != 3 or span <= 0.0:
        raise CandidateContractError("controlled first-batch triplet is invalid")
    response_unit = f"us/{coordinate_unit}"
    stages: dict[str, Any] = {}
    previous_label: str | None = None
    previous_response: tuple[float, float] | None = None
    for label, kind, prism_number in _FIRST_BATCH_ABERRATION_STAGES:
        matches = []
        for ion in particle_ids:
            candidates = events.get((kind, ion), [])
            if prism_number is not None:
                candidates = [
                    event for event in candidates
                    if int(event.get("n", 0)) == prism_number
                ]
            matches.append(candidates)
        counts = [len(values) for values in matches]
        if any(count != 1 for count in counts):
            stages[label] = {
                "status": "unavailable",
                "reason": "controlled_triplet_event_not_observed_exactly_once",
                "event_counts": counts,
                "increment_from_previous_stage": {
                    "status": "unavailable",
                    "previous_stage": previous_label,
                    "reason": "one_or_both_adjacent_stage_responses_are_unavailable",
                },
            }
            previous_label, previous_response = label, None
            continue
        times = [float(values[0]["t_us"]) for values in matches]
        first_order = (times[2] - times[0]) / span
        even = (times[2] + times[0]) / 2.0 - times[1]
        if previous_label is None:
            increment: dict[str, Any] = {
                "status": "not_applicable", "previous_stage": None,
            }
        elif previous_response is None:
            increment = {
                "status": "unavailable",
                "previous_stage": previous_label,
                "reason": "previous_stage_response_is_unavailable",
            }
        else:
            increment = {
                "status": "observed",
                "previous_stage": previous_label,
                "first_order_time_response_delta": first_order - previous_response[0],
                "first_order_time_response_delta_unit": response_unit,
                "even_center_deviation_delta_us": even - previous_response[1],
                "definition": "current_stage_time_response_minus_previous_stage_time_response",
            }
        stages[label] = {
            "status": "observed",
            "times_us": times,
            "first_order_time_response": first_order,
            "first_order_time_response_unit": response_unit,
            "even_center_deviation_us": even,
            "increment_from_previous_stage": increment,
        }
        previous_label, previous_response = label, (first_order, even)
    return {
        "coordinate": coordinate,
        "coordinate_values": coordinate_values,
        "coordinate_unit": coordinate_unit,
        "particle_ids": particle_ids,
        "stages": stages,
    }


def _controlled_position_stage_responses(
    *,
    pairs: list[dict[str, Any]],
    source_rows: dict[int, dict[str, float]],
    events: dict[tuple[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Report every receipt-declared position pair fully present in this cohort."""
    responses: dict[str, Any] = {}
    for pair in pairs:
        try:
            name = str(pair["name"])
            coordinate = str(pair["coordinate"])
            negative = int(pair["negative_particle_id"])
            positive = int(pair["positive_particle_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError(
                "controlled position-pair metadata is incomplete"
            ) from error
        if coordinate not in {"x_mm", "y_mm", "z_mm"} or not name:
            raise CandidateContractError(
                "controlled position-pair coordinate is invalid"
            )
        if not {1, negative, positive}.issubset(source_rows):
            continue
        particle_ids = [negative, 1, positive]
        coordinate_values = [
            source_rows[ion][coordinate] for ion in particle_ids
        ]
        responses[name] = {
            "scope": pair.get("scope"),
            **_controlled_first_batch_stage_response(
                coordinate=coordinate.removesuffix("_mm"),
                coordinate_unit="mm",
                particle_ids=particle_ids,
                coordinate_values=coordinate_values,
                events=events,
            ),
        }
    return responses


def analyze_controlled_aberration_first_batch(
    *, first_batch_log: Path, source_receipt_path: Path,
) -> dict[str, Any]:
    """Analyze the frozen centre and controlled pairs as soon as batch 1 completes."""
    text = first_batch_log.read_text(encoding="utf-8-sig")
    completions = list(FLY_COMPLETED.finditer(text))
    if len(completions) != 1 or int(completions[0].group("splats")) != 10:
        raise CandidateContractError(
            "controlled aberration early report requires one completed 10-particle first batch"
        )
    expected_ids = list(range(1, 11))
    source_rows, receipt = _source_rows_from_receipt(
        source_receipt_path, expected_ids,
    )
    events, _ = _load_selected_events([(first_batch_log, 0, 10)])
    observed_ids = sorted(
        ion for (kind, ion), matches in events.items()
        if kind == "terminal" and len(matches) == 1
    )
    if observed_ids != expected_ids:
        raise CandidateContractError(
            "completed first batch does not contain terminal events for IDs 1..10"
        )
    terminal_codes = {
        ion: int(_one(events, "terminal", ion).get("splat", 0))
        for ion in expected_ids
    }
    controlled_z = _controlled_detector_focus(
        pair=receipt.get("controlled_focus_pair"),
        source_rows=source_rows,
        events=events,
        terminal_codes=terminal_codes,
    )
    controlled_slow_energy = _controlled_slow_energy_response(
        pair=receipt.get("controlled_slow_energy_pair"),
        source_rows=source_rows,
        events=events,
        terminal_codes=terminal_codes,
    )
    controlled_x = _controlled_transverse_x_response(
        pair=receipt.get("controlled_transverse_x_pair"),
        source_rows=source_rows,
        events=events,
        terminal_codes=terminal_codes,
    )
    if controlled_z is None or controlled_slow_energy is None or controlled_x is None:
        raise CandidateContractError(
            "first-batch report requires controlled z, slow-energy, and x triplets"
        )
    controlled_stage_responses = {
        "initial_z": _controlled_first_batch_stage_response(
            coordinate="initial_z",
            coordinate_unit="mm",
            particle_ids=controlled_z["three_point_particle_ids"],
            coordinate_values=controlled_z["three_point_initial_z_mm"],
            events=events,
        ),
        "release_slow_energy": _controlled_first_batch_stage_response(
            coordinate="release_slow_energy",
            coordinate_unit="eV",
            particle_ids=controlled_slow_energy["particle_ids"],
            coordinate_values=controlled_slow_energy["release_slow_energy_ev"],
            events=events,
        ),
        "initial_x": _controlled_first_batch_stage_response(
            coordinate="initial_x",
            coordinate_unit="mm",
            particle_ids=controlled_x["particle_ids"],
            coordinate_values=controlled_x["initial_x_mm"],
            events=events,
        ),
    }
    controlled_position_responses = _controlled_position_stage_responses(
        pairs=[
            pair for pair in receipt.get("controlled_position_pairs", [])
            if isinstance(pair, dict)
        ],
        source_rows=source_rows,
        events=events,
    )
    return {
        "schema_version": 1,
        "role": "mrtof_controlled_aberration_first_batch",
        "status": "candidate_diagnostic",
        "partial_first_batch": True,
        "qualification": (
            "partial_first_batch_controlled_rays_only__"
            "formal_collection_fwhm_and_resolution_unavailable"
        ),
        "cohort": {
            "particle_ids": expected_ids,
            "particle_count": 10,
            "detector_hit_count": sum(code == 1 for code in terminal_codes.values()),
            "terminal_codes": terminal_codes,
        },
        "formal_metrics": {
            "status": "unavailable_until_complete_n100",
            "collection_rate": None,
            "detector_fwhm_us": None,
            "mass_resolution_t_over_2fwhm": None,
        },
        "event_stage_semantics": {
            "p1_entry": {
                "status": "not_available",
                "reason": "no_independent_p1_entry_event_is_logged",
            },
            "p1_target_pass": "prism_pass_with_n_equal_1",
            "p2_entry": "prism_entry_with_n_equal_2",
            "p2_pass": "prism_pass_with_n_equal_2",
            "p2_low_field_crossing": "raw_unfiltered_crossing_event",
            "stripe": {
                "status": "not_reported",
                "reason": "no_dedicated_stripe_event_is_logged",
            },
        },
        "controlled_z_response": controlled_z,
        "controlled_slow_energy_response": controlled_slow_energy,
        "controlled_transverse_x_response": controlled_x,
        "controlled_stage_responses": controlled_stage_responses,
        "controlled_position_responses": controlled_position_responses,
        "evidence": {
            "first_batch_log": str(first_batch_log.resolve()),
            "source_receipt": str(source_receipt_path.resolve()),
        },
    }


def analyze_source_z_energy_timing(run_dir: Path) -> dict[str, Any]:
    """Validate and analyze one complete N>1 MR-TOF flight run."""
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load_object(manifest_path, "flight run manifest")
    if (
        manifest.get("project") != _PROJECT or manifest.get("mode") != _MODE
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("input is not a successful complete MR-TOF flight run")
    _verify_manifest(manifest, manifest_path)
    observation_path = run_dir / "results" / "two_prism_trial_observation.json"
    _unique_output(manifest, observation_path, "flight observation")
    observation = _load_object(observation_path, "flight observation")
    cohort = observation.get("cohort_analysis")
    if not isinstance(cohort, dict) or cohort.get("event_integrity_passed") is not True:
        raise CandidateContractError("flight observation did not pass event integrity")
    peak_context = {
        "mass_th": cohort.get("particle_mass_th"),
        "analysis_contract": cohort.get("peak_analysis_contract"),
        "cohort_role": cohort.get("cohort_role"),
    }
    try:
        particle_count = int(cohort["expected_particle_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("flight observation lacks the expected particle count") from error
    expected_ids = list(range(1, particle_count + 1))
    if particle_count <= 1 or cohort.get("observed_particle_ids") != expected_ids:
        raise CandidateContractError("diagnostic requires one complete ordered N>1 cohort")
    (
        source_rows,
        source_evidence,
        controlled_pair,
        controlled_slow_energy_pair,
        controlled_transverse_x_pair,
        controlled_position_pairs,
    ) = (
        _load_source_rows(
        run_dir=run_dir, manifest=manifest, expected_count=particle_count,
        )
    )
    batches = _event_batches(run_dir=run_dir, manifest=manifest, particle_count=particle_count)
    events, log_evidence = _load_selected_events(batches)

    terminal_codes: dict[int, int] = {}
    for ion in expected_ids:
        terminal = _one(events, "terminal", ion)
        code = int(terminal.get("splat", 0))
        if code not in (-1, 1, 2, 4, 5):
            raise CandidateContractError(f"ion {ion} has unsupported terminal class {code}")
        terminal_codes[ion] = code
        _one(events, "accelerator_safe_exit", ion)
    hit_ids = [ion for ion in expected_ids if terminal_codes[ion] == 1]
    loss_ids = [ion for ion in expected_ids if terminal_codes[ion] != 1]
    electrode_collision_ids = [ion for ion in expected_ids if terminal_codes[ion] == -1]
    if (
        len(electrode_collision_ids) != cohort.get("electrode_collision_count")
        or len(hit_ids) != cohort.get("detector_hit_count")
    ):
        raise CandidateContractError("raw terminal classes disagree with the flight observation")
    controlled_detector_focus = _controlled_detector_focus(
        pair=controlled_pair,
        source_rows=source_rows,
        events=events,
        terminal_codes=terminal_codes,
    )
    controlled_slow_energy_response = _controlled_slow_energy_response(
        pair=controlled_slow_energy_pair,
        source_rows=source_rows,
        events=events,
        terminal_codes=terminal_codes,
    )
    controlled_transverse_x_response = _controlled_transverse_x_response(
        pair=controlled_transverse_x_pair,
        source_rows=source_rows,
        events=events,
        terminal_codes=terminal_codes,
    )
    controlled_position_responses = _controlled_position_stage_responses(
        pairs=controlled_position_pairs,
        source_rows=source_rows,
        events=events,
    )
    for ion in hit_ids:
        for _, kind in _CHAIN:
            _one(events, kind, ion)
    for ion in loss_ids:
        for _, kind in _CHAIN:
            if len(events.get((kind, ion), [])) > 1:
                raise CandidateContractError(f"loss ion {ion} has duplicate {kind} events")

    all_source_z = [source_rows[ion]["z_mm"] for ion in expected_ids]
    hit_source_z = [source_rows[ion]["z_mm"] for ion in hit_ids]
    safe_exit_time_all = _event_values(events, "accelerator_safe_exit", expected_ids, "t_us")
    safe_exit_axial_energy_all = [
        kinetic_energy_ev(
            source_rows[ion]["mass_th"], 0.0, 0.0,
            float(_one(events, "accelerator_safe_exit", ion)["vz_mm_us"]) * 1000.0,
        )
        for ion in expected_ids
    ]
    enough_detector_hits = len(hit_ids) >= 2
    safe_exit_time_hits = _event_values(events, "accelerator_safe_exit", hit_ids, "t_us")

    detector_slope: float | None = None
    stages: dict[str, Any] = {}
    if enough_detector_hits:
        previous_label = "accelerator_safe_exit"
        previous_times = safe_exit_time_hits
        for label, kind in _CHAIN:
            times = _event_values(events, kind, hit_ids, "t_us")
            absolute = _distribution(
                hit_source_z, times, value_unit="us", slope_unit="us/mm",
            )
            increments = [value - previous for value, previous in zip(times, previous_times, strict=True)]
            increment = _distribution(
                hit_source_z, increments, value_unit="us", slope_unit="us/mm",
            )
            stages[label] = {
                "absolute_time": absolute,
                "increment_from_previous_event": {
                    "previous_event": previous_label,
                    **increment,
                },
            }
            previous_label, previous_times = label, times
            if label == "detector":
                detector_slope = absolute["initial_z_association"]["slope"]
        for stage in stages.values():
            incremental_slope = stage["increment_from_previous_event"]["initial_z_association"]["slope"]
            stage["increment_from_previous_event"]["signed_fraction_of_detector_dt_dz"] = (
                None if detector_slope in (None, 0.0) or incremental_slope is None
                else incremental_slope / detector_slope
            )
    else:
        stages = {
            label: {"status": "unavailable", "reason": "fewer_than_two_detector_hits"}
            for label, _ in _CHAIN
        }

    p2_y = _event_values(events, "return_p2_pass", hit_ids, "y_mm")
    p2_vy = _event_values(events, "return_p2_pass", hit_ids, "vy_mm_us")
    p2_vz = _event_values(events, "return_p2_pass", hit_ids, "vz_mm_us")
    p2_angle = [math.degrees(math.atan2(vy, vz)) for vy, vz in zip(p2_vy, p2_vz, strict=True)]
    positive_turn_z = _event_values(events, "return_positive_mirror_turn", hit_ids, "z_mm")
    event_coverage = {
        kind: sum(len(events.get((kind, ion), [])) for ion in expected_ids)
        for kind in sorted(_SELECTED_EVENT_KINDS)
    }
    terminal_code_histogram = {
        str(code): sum(value == code for value in terminal_codes.values())
        for code in (-1, 1, 2, 4, 5)
        if any(value == code for value in terminal_codes.values())
    }
    target_slope = (
        stages["target_k"]["absolute_time"]["initial_z_association"]["slope"]
        if enough_detector_hits else None
    )
    downstream_fraction = (
        None if detector_slope in (None, 0.0) or target_slope is None
        else (detector_slope - target_slope) / detector_slope
    )
    terminal_plane_diagnostic = (
        _terminal_plane_diagnostic(
            events=events,
            hit_ids=hit_ids,
            hit_source_z=hit_source_z,
            peak_context=peak_context,
        )
        if enough_detector_hits else {
            "status": "unavailable", "reason": "fewer_than_two_detector_hits",
        }
    )
    target_crossing_indices = {
        int(event["half_cycles"])
        for ion in expected_ids
        for event in events.get(("target_k_phase_sample", ion), [])
    }
    if len(target_crossing_indices) != 1:
        raise CandidateContractError(
            "target-K events do not define one central-plane crossing index"
        )
    central_plane_focus_history = _central_plane_focus_history(
        events=events,
        expected_ids=expected_ids,
        source_rows=source_rows,
        controlled_pair=controlled_pair,
        source_z_by_ion={ion: source_rows[ion]["z_mm"] for ion in expected_ids},
        target_crossing_index=next(iter(target_crossing_indices)),
        hit_ids=hit_ids,
        hit_source_z=hit_source_z,
        peak_context=peak_context,
    )
    collision_loss_diagnostic = _collision_loss_diagnostic(run_dir, observation, events)
    return {
        "schema_version": 1,
        "role": "mrtof_source_z_energy_timing_diagnostic",
        "status": "candidate_diagnostic",
        "qualification": "descriptive_transfer_diagnostic_only__not_causal__not_resolution_qualification",
        "cohort": {
            "particle_count": particle_count,
            "detector_hit_count": len(hit_ids),
            "electrode_collision_count": len(electrode_collision_ids),
            "programmatic_timeout_count": terminal_code_histogram.get("2", 0),
            "programmatic_topology_rejection_count": terminal_code_histogram.get("4", 0),
            "programmatic_diagnostic_stop_count": terminal_code_histogram.get("5", 0),
            "terminal_code_histogram": terminal_code_histogram,
            "all_terminal_particles_retained": True,
            "safe_exit_metric_scope": "all_expected_particles",
            "downstream_metric_scope": "all_detector_hits_with_complete_event_chain",
            "source_or_peak_filtering": "none",
        },
        "safe_exit": {
            "time": _distribution(
                all_source_z, safe_exit_time_all, value_unit="us", slope_unit="us/mm",
            ),
            "axial_kinetic_energy": _distribution(
                all_source_z, safe_exit_axial_energy_all,
                value_unit="eV", slope_unit="eV/mm",
            ),
        },
        "stages": stages,
        "derived_transfer": {
            "fraction_of_detector_dt_dz_accumulated_after_target_k": downstream_fraction,
            "fraction_definition": "(detector absolute dt/dz - target-K absolute dt/dz) / detector absolute dt/dz",
        },
        "terminal_plane_diagnostic": terminal_plane_diagnostic,
        "collision_loss_diagnostic": collision_loss_diagnostic,
        "controlled_detector_focus": controlled_detector_focus,
        "controlled_slow_energy_response": controlled_slow_energy_response,
        "controlled_transverse_x_response": controlled_transverse_x_response,
        "controlled_position_responses": controlled_position_responses,
        "central_plane_focus_history": central_plane_focus_history,
        "state_dispersion": ({
            "return_p2_pass_y": _distribution(
                hit_source_z, p2_y, value_unit="mm", slope_unit="mm/mm",
            ),
            "return_p2_pass_angle": _distribution(
                hit_source_z, p2_angle, value_unit="deg", slope_unit="deg/mm",
            ),
            "return_p2_pass_vz": _distribution(
                hit_source_z, p2_vz, value_unit="mm/us", slope_unit="(mm/us)/mm",
            ),
            "return_positive_mirror_turn_depth": _distribution(
                hit_source_z, positive_turn_z, value_unit="mm", slope_unit="mm/mm",
            ),
        } if enough_detector_hits else {
            "status": "unavailable", "reason": "fewer_than_two_detector_hits",
        }),
        "event_coverage": event_coverage,
        "evidence": {
            "flight_run_manifest": {"path": str(manifest_path), "sha256": _sha256(manifest_path)},
            "flight_observation": {"path": str(observation_path), "sha256": _sha256(observation_path)},
            "native_logs": log_evidence,
            **source_evidence,
        },
        "interpretation": (
            "Slopes, correlations, FWHM values, plane-resolution diagnostics, and signed incremental fractions "
            "describe the frozen run only. The z=0 target-return diagnostic includes every source-cohort particle "
            "that reaches that crossing and therefore remains distinct from detector collection. These diagnostics "
            "do not identify a unique electrode or authorize source filtering, detrending, or Formal qualification."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--first-batch-log", type=Path)
    parser.add_argument("--source-receipt", type=Path)
    parser.add_argument("--te1-reference", type=Path)
    parser.add_argument("--build-te1-reference", action="store_true")
    parser.add_argument("--mirror-point", type=Path)
    parser.add_argument("--first-diagnostic", type=Path)
    parser.add_argument("--first-coordinate", type=float)
    parser.add_argument("--second-diagnostic", type=Path)
    parser.add_argument("--second-coordinate", type=float)
    parser.add_argument("--te1-coordinate", type=float)
    parser.add_argument("--mirror-period", type=Path)
    parser.add_argument("--mirror-correction", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--compare-baseline", type=Path)
    parser.add_argument("--compare-probe", type=Path)
    parser.add_argument("--compare-root", type=Path)
    parser.add_argument("--baseline-focus-diagnostic", type=Path)
    parser.add_argument("--probe-focus-diagnostic", type=Path)
    parser.add_argument("--root-focus-diagnostic", type=Path)
    parser.add_argument("--baseline-coordinate", type=float)
    parser.add_argument("--probe-coordinate", type=float)
    parser.add_argument("--root-coordinate", type=float)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    first_batch_arguments = (args.first_batch_log, args.source_receipt)
    if any(value is not None for value in first_batch_arguments) and not all(
        value is not None for value in first_batch_arguments
    ):
        parser.error("first-batch log and source receipt are required together")
    gate_paths = (args.mirror_period, args.mirror_correction, args.contract)
    if not args.build_te1_reference and any(value is not None for value in gate_paths) and not all(
        value is not None for value in gate_paths
    ):
        parser.error("mirror period, correction, and contract are required together")
    root_arguments = (
        args.te1_reference, args.first_diagnostic, args.first_coordinate,
        args.second_diagnostic, args.second_coordinate,
    )
    comparison_arguments = (
        args.compare_baseline, args.compare_probe, args.compare_root,
        args.probe_coordinate, args.root_coordinate,
    )
    focus_comparison_arguments = (
        args.baseline_focus_diagnostic, args.probe_focus_diagnostic,
        args.root_focus_diagnostic,
    )
    if all(value is not None for value in first_batch_arguments):
        if (
            args.build_te1_reference
            or args.run_dir is not None
            or any(value is not None for value in (
                *root_arguments, *comparison_arguments, *focus_comparison_arguments,
                args.te1_coordinate, args.mirror_period, args.mirror_correction,
                args.contract, args.mirror_point,
            ))
        ):
            parser.error("first-batch analysis cannot be combined with another mode")
        result = analyze_controlled_aberration_first_batch(
            first_batch_log=args.first_batch_log,
            source_receipt_path=args.source_receipt,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    elif args.build_te1_reference:
        if (
            args.mirror_point is None
            or args.mirror_correction is None
            or args.contract is None
            or any(value is not None for value in (
                args.run_dir, *root_arguments, *comparison_arguments,
                *focus_comparison_arguments,
                args.te1_coordinate, args.mirror_period,
            ))
        ):
            parser.error("TE1 reference derivation requires only mirror point, correction, and contract")
        build_te1_reference_from_mirror_jacobian(
            mirror_point_path=args.mirror_point,
            mirror_correction_path=args.mirror_correction,
            contract_path=args.contract,
            output_path=args.output,
        )
    elif args.run_dir is not None:
        if any(value is not None for value in (
            *root_arguments, *comparison_arguments, *focus_comparison_arguments,
        )):
            parser.error("--run-dir cannot be combined with TE1 calibration inputs")
        result = analyze_source_z_energy_timing(args.run_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    elif all(value is not None for value in comparison_arguments):
        if any(value is not None for value in (
            *root_arguments, args.te1_coordinate,
        )):
            parser.error("TE1 comparison cannot be combined with variation inputs")
        result = compare_te1_diagnostics(
            baseline_path=args.compare_baseline,
            probe_path=args.compare_probe,
            root_path=args.compare_root,
            probe_coordinate=args.probe_coordinate,
            root_coordinate=args.root_coordinate,
            baseline_coordinate=(0.0 if args.baseline_coordinate is None else args.baseline_coordinate),
            baseline_focus_path=args.baseline_focus_diagnostic,
            probe_focus_path=args.probe_focus_diagnostic,
            root_focus_path=args.root_focus_diagnostic,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    elif all(value is not None for value in root_arguments) and args.te1_coordinate is None:
        if any(value is not None for value in focus_comparison_arguments):
            parser.error("focus diagnostic overrides are valid only for TE1 comparison")
        materialize_te1_variation_from_diagnostics(
            reference_path=args.te1_reference,
            first_diagnostic_path=args.first_diagnostic,
            first_coordinate=args.first_coordinate,
            second_diagnostic_path=args.second_diagnostic,
            second_coordinate=args.second_coordinate,
            output_path=args.output,
            mirror_period_path=args.mirror_period,
            mirror_correction_path=args.mirror_correction,
            contract_path=args.contract,
        )
    elif (
        args.te1_reference is not None
        and args.te1_coordinate is not None
        and all(value is None for value in root_arguments[1:])
        and all(value is None for value in comparison_arguments)
        and all(value is None for value in focus_comparison_arguments)
    ):
        materialize_scaled_te1_variation(
            reference_path=args.te1_reference,
            coordinate=args.te1_coordinate,
            output_path=args.output,
            mirror_period_path=args.mirror_period,
            mirror_correction_path=args.mirror_correction,
            contract_path=args.contract,
        )
    else:
        parser.error("supply exactly one complete analysis, TE1 variation, root, or comparison mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
