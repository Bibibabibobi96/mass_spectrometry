"""Publish a paired comparison of two continuous-flight entrance apertures."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel import (
    build_figure as build_spatial_figure,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    freeze_repository_inputs,
    portable_path,
    publish_manifest,
    write_pending_json,
)
from common.analysis.peak_metrics import (
    compute_peak_metrics,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
CAPABILITY_ID = "rf_oatof_single_flight_aperture_comparison_v1"
MODE = "single-flight-aperture-comparison"
EVENTS = (
    "source_release",
    "multipole_handoff",
    "pre_pulse_state",
    "local_accelerator_exit",
    "detector_crossing",
)
COLORS = {"wide": "#0072B2", "small": "#D55E00", "common": "#009E73"}
PRE_PULSE_APERTURE_HEIGHTS_MM = frozenset((1.0, 1.5, 2.0, 2.5))
PRE_PULSE_ACCELERATOR_SHAPES = frozenset(("square", "cylindrical"))
PRE_PULSE_GAP_MM = 102.4


def _pre_pulse_axial_full_width_acceptance_mm(
    configuration: dict[str, Any], *, case_id: str
) -> float:
    """Return the run-resolved source-width acceptance criterion in mm."""

    parameters = configuration.get("parameters")
    if not isinstance(parameters, dict):
        raise ContractError(f"{case_id} resolved run parameters are missing")
    value = parameters.get("source_release_full_width_mm")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{case_id} source-release full-width acceptance is missing")
    acceptance_mm = float(value)
    if not np.isfinite(acceptance_mm) or acceptance_mm <= 0:
        raise ContractError(f"{case_id} source-release full-width acceptance is invalid")
    return acceptance_mm


def _polynomial_fit_diagnostics(
    z_mm: np.ndarray, vz_mm_per_us: np.ndarray, *, degree: int
) -> dict[str, Any]:
    """Return an explicitly model-conditioned residual diagnostic.

    A linear residual contains both stochastic scatter and deterministic field
    curvature.  Reporting the residual after degree two and three fits makes
    that distinction visible instead of labelling all linear-model residual as
    random noise.
    """

    coefficients = np.polyfit(z_mm, vz_mm_per_us, degree)
    residual = vz_mm_per_us - np.polyval(coefficients, z_mm)
    result: dict[str, Any] = {
        "degree": degree,
        "coefficients_descending_power": [float(value) for value in coefficients],
        "coefficient_units_descending_power": [
            "mm_per_us_per_mm" if power == 1 else (
                "mm_per_us" if power == 0 else f"mm_per_us_per_mm{power}"
            )
            for power in range(degree, -1, -1)
        ],
        "residual_sample_sigma_mm_per_us": float(np.std(residual, ddof=1)),
        "residual_rms_mm_per_us": float(np.sqrt(np.mean(np.square(residual)))),
        "residual_max_abs_mm_per_us": float(np.max(np.abs(residual))),
        "residual_abs_p95_mm_per_us": float(np.quantile(np.abs(residual), .95)),
    }
    # These named terms use exactly the position/velocity unit convention of
    # the campaign's default affine diagnostic: z in mm and vz in mm/us.
    result["intercept_mm_per_us"] = float(coefficients[-1])
    result["k_per_us"] = float(coefficients[-2])
    if degree >= 2:
        result["quadratic_coefficient_per_mm_us"] = float(coefficients[-3])
    if degree >= 3:
        result["cubic_coefficient_per_mm2_us"] = float(coefficients[-4])
    return result


def _selected_detector_blind_sample(
    receipt: dict[str, Any], *, case_id: str
) -> tuple[int, float]:
    """Return the detector-blind winner's native state-table sample.

    The natural archive deliberately continues after the selected pulse time so
    that another pulse policy can be evaluated without re-running SIMION.  Its
    final sample therefore has no special comparison meaning.
    """

    if (
        receipt.get("role")
        != "rf_oatof_detector_blind_real_field_pulse_timing_selection_receipt"
        or receipt.get("status") != "success"
        or receipt.get("qualification") != "candidate_selection"
        or receipt.get("selection_uses_detector_outcome") is not False
        or receipt.get("detector_results_used") is not False
    ):
        raise ContractError(f"{case_id} detector-blind pulse timing receipt is invalid")
    candidates = receipt.get("candidates_ranked")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ContractError(f"{case_id} detector-blind pulse timing winner is missing")
    winner = candidates[0]
    sample_index = winner.get("sample_index")
    candidate_time_us = winner.get("candidate_time_us")
    selected_time_us = receipt.get("selected_time_us")
    if (
        isinstance(sample_index, bool)
        or not isinstance(sample_index, int)
        or sample_index < 1
        or isinstance(candidate_time_us, bool)
        or not isinstance(candidate_time_us, (int, float))
        or isinstance(selected_time_us, bool)
        or not isinstance(selected_time_us, (int, float))
        or not math.isfinite(float(candidate_time_us))
        or not math.isfinite(float(selected_time_us))
        or not math.isclose(float(candidate_time_us), float(selected_time_us), rel_tol=0.0, abs_tol=1e-9)
    ):
        raise ContractError(f"{case_id} detector-blind pulse timing winner differs")
    return sample_index, float(selected_time_us)


def _pre_pulse_matrix_arm(
    configuration: dict[str, Any], connection: dict[str, Any], *, case_id: str
) -> tuple[str, float]:
    """Return the resolved realization and aperture height for one screening arm."""

    parameters = configuration.get("parameters")
    if not isinstance(parameters, dict):
        raise ContractError(f"{case_id} resolved run parameters are missing")
    layout_profile_id = parameters.get("layout_profile_id")
    if not isinstance(layout_profile_id, str):
        raise ContractError(f"{case_id} layout profile is missing")
    matching_shapes = [
        shape for shape in PRE_PULSE_ACCELERATOR_SHAPES
        if f"_{shape}_" in layout_profile_id
    ]
    if len(matching_shapes) != 1:
        raise ContractError(f"{case_id} accelerator realization is not square or cylindrical")
    aperture = parameters.get("accelerator_entrance_local_aperture_mm")
    if not isinstance(aperture, dict):
        raise ContractError(f"{case_id} accelerator local aperture is missing")
    width, height = aperture.get("width"), aperture.get("height")
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, (int, float))
        or not isinstance(height, (int, float))
        or not math.isclose(float(width), 1.0, rel_tol=0.0, abs_tol=1e-12)
        or float(height) not in PRE_PULSE_APERTURE_HEIGHTS_MM
    ):
        raise ContractError(f"{case_id} is outside the 1.0 mm wide aperture scan")
    registration = connection.get("spatial_registration")
    connector = connection.get("connector")
    if not isinstance(registration, dict) or not isinstance(connector, dict):
        raise ContractError(f"{case_id} resolved connection is missing")
    expected_gap_mm = registration.get("expected_gap_mm")
    connector_length_mm = connector.get("length_mm")
    if (
        isinstance(expected_gap_mm, bool)
        or isinstance(connector_length_mm, bool)
        or not isinstance(expected_gap_mm, (int, float))
        or not isinstance(connector_length_mm, (int, float))
        or not math.isclose(float(expected_gap_mm), PRE_PULSE_GAP_MM, rel_tol=0.0, abs_tol=1e-9)
        or not math.isclose(float(connector_length_mm), PRE_PULSE_GAP_MM, rel_tol=0.0, abs_tol=1e-9)
    ):
        raise ContractError(f"{case_id} does not use the 102.4 mm connector gap")
    return matching_shapes[0], float(height)


def analyze_pre_pulse_source_only_apertures(
    cases: dict[str, Path],
) -> dict[str, Any]:
    """Compare frozen pre-pulse source-only runs without downstream observables."""

    if len(cases) != len(PRE_PULSE_ACCELERATOR_SHAPES) * len(PRE_PULSE_APERTURE_HEIGHTS_MM):
        raise ContractError("pre-pulse aperture comparison requires the complete eight-arm matrix")
    mother_initial: pd.DataFrame | None = None
    matrix_arms: set[tuple[str, float]] = set()
    metrics: dict[str, Any] = {}
    for case_id, run in sorted(cases.items()):
        _validate_source_run(run)
        config = _load_json(run / "run_config.json")
        if config.get("parameters", {}).get("execution_mode") != "real_pa_rf_pre_pulse_time_series":
            raise ContractError(f"{case_id} is not a pre-pulse source-only run")
        full_width_acceptance_mm = _pre_pulse_axial_full_width_acceptance_mm(
            config, case_id=case_id
        )
        archive = run / "results" / "pre_pulse_time_series_states.csv.gz"
        states = pd.read_csv(
            archive if archive.is_file() else run / "results" / "pre_pulse_time_series_states.csv"
        )
        required = {"particle_id", "sample_index", "z_mm", "vz_mm_per_us"}
        if missing := sorted(required - set(states.columns)):
            raise ContractError(f"{case_id} states are missing: {', '.join(missing)}")
        selection_receipt = _load_json(
            run / "results" / "detector_blind_pulse_timing_candidate_receipt.json"
        )
        selected_sample_index, selected_time_us = _selected_detector_blind_sample(
            selection_receipt, case_id=case_id
        )
        shape, aperture_height_mm = _pre_pulse_matrix_arm(
            config,
            _load_json(run / "inputs" / "resolved_connection.json"),
            case_id=case_id,
        )
        if (shape, aperture_height_mm) in matrix_arms:
            raise ContractError("pre-pulse aperture comparison contains a duplicate matrix arm")
        matrix_arms.add((shape, aperture_height_mm))
        initial = pd.read_csv(run / "inputs" / "single_flight_initial_global_state.csv")
        if "particle_id" not in initial or initial["particle_id"].duplicated().any():
            raise ContractError(f"{case_id} mother cohort is invalid")
        if len(initial) != 5000:
            raise ContractError(f"{case_id} does not use the common N=5000 mother cohort")
        if mother_initial is None:
            mother_initial = initial
        elif not initial.equals(mother_initial):
            raise ContractError("pre-pulse cases must share the same frozen N=5000 mother cohort")
        ids = {int(value) for value in initial["particle_id"]}
        selected = states.loc[states["sample_index"].eq(selected_sample_index)].copy()
        if selected.empty:
            raise ContractError(f"{case_id} selected detector-blind sample is absent")
        if selected["particle_id"].duplicated().any() or not set(selected["particle_id"]).issubset(ids):
            raise ContractError(f"{case_id} selected pre-pulse state identities are invalid")
        z, vz = selected["z_mm"].to_numpy(float), selected["vz_mm_per_us"].to_numpy(float)
        if len(z) < 2 or not (np.isfinite(z).all() and np.isfinite(vz).all()):
            raise ContractError(f"{case_id} needs two finite selected pre-pulse states")
        linear = _polynomial_fit_diagnostics(z, vz, degree=1)
        quadratic = _polynomial_fit_diagnostics(z, vz, degree=2) if len(z) >= 3 else None
        cubic = _polynomial_fit_diagnostics(z, vz, degree=3) if len(z) >= 4 else None
        random_residual_model = cubic or quadratic or linear
        receipt = _load_json(run / "results" / "pre_pulse_time_series_screening_receipt.json")
        census = receipt.get("terminal_census")
        if not isinstance(census, dict):
            raise ContractError(f"{case_id} terminal loss census is missing")
        full_width_mm = float(np.max(z) - np.min(z))
        metrics[case_id] = {
            "matrix_arm": {"accelerator_shape": shape, "aperture_height_mm": aperture_height_mm, "connector_gap_mm": PRE_PULSE_GAP_MM},
            "detector_blind_pulse_timing": {
                "selected_sample_index": selected_sample_index,
                "selected_time_us": selected_time_us,
                "selection_uses_detector_outcome": False,
                "detector_results_used": False,
            },
            "mother_cohort_count": len(ids),
            "accelerator_entry_count": len(selected),
            "transmission_fraction_of_mother": len(selected) / len(ids),
            "accelerator_entry_axial_width_mm": {
                "full_width": full_width_mm,
                "quantile_width_05_to_95": float(np.quantile(z, .95) - np.quantile(z, .05)),
            },
            "accelerator_entry_axial_full_width_acceptance": {
                "threshold_full_width_mm": full_width_acceptance_mm,
                "observed_full_width_mm": full_width_mm,
                "passed": full_width_mm <= full_width_acceptance_mm,
            },
            "z_vz_linear_fit": {
                "k_per_us": linear["k_per_us"],
                "slope_per_us": linear["k_per_us"],
                "slope_vz_mm_per_us_per_mm": linear["k_per_us"],
                "intercept_mm_per_us": linear["intercept_mm_per_us"],
                "linear_residual_sample_sigma_mm_per_us": linear["residual_sample_sigma_mm_per_us"],
                "linear_residual_rms_mm_per_us": linear["residual_rms_mm_per_us"],
                "random_residual_sample_sigma_mm_per_us": random_residual_model["residual_sample_sigma_mm_per_us"],
                "random_residual_rms_mm_per_us": random_residual_model["residual_rms_mm_per_us"],
                "random_residual_model_degree": random_residual_model["degree"],
                "quadratic_coefficient_per_mm_us": None if quadratic is None else quadratic["quadratic_coefficient_per_mm_us"],
                "interpretation": (
                    "k_per_us, intercept_mm_per_us, and residual_*_mm_per_us follow the "
                    "default affine diagnostic units. Random residual is the residual after "
                    "the highest reported polynomial degree, not the linear-model residual."
                ),
            },
            "z_vz_polynomial_diagnostics": {
                "model_definition": "vz_mm_per_us = sum(coefficients_descending_power[i] * z_mm**(degree-i)); z_mm is in mm",
                "linear": linear,
                "quadratic": quadratic,
                "cubic": cubic,
                "higher_order_residual_sigma_reduction_vs_linear_mm_per_us": {
                    "quadratic": None if quadratic is None else (
                        linear["residual_sample_sigma_mm_per_us"]
                        - quadratic["residual_sample_sigma_mm_per_us"]
                    ),
                    "cubic": None if cubic is None else (
                        linear["residual_sample_sigma_mm_per_us"]
                        - cubic["residual_sample_sigma_mm_per_us"]
                    ),
                },
                "random_residual_interpretation": (
                    "Residual scatter after the highest reported polynomial degree is the "
                    "available random-residual estimate; degree-to-degree reduction is "
                    "deterministic higher-order z-vz structure."
                ),
            },
            "loss_classification": census,
        }
    expected_matrix = {
        (shape, height)
        for shape in PRE_PULSE_ACCELERATOR_SHAPES
        for height in PRE_PULSE_APERTURE_HEIGHTS_MM
    }
    if matrix_arms != expected_matrix:
        raise ContractError("pre-pulse aperture comparison matrix differs from the current eight-arm scan")
    return {"schema_version": 1, "role": "rf_oatof_pre_pulse_aperture_comparison", "status": "DETECTOR_BLIND_SOURCE_ONLY", "controlled_variables": {"mother_cohort_identical": True, "mother_cohort_count": 5000, "connector_gap_mm": PRE_PULSE_GAP_MM, "comparison_denominator": "full_mother_cohort", "detector_blind_pulse_timing_receipt_bound_per_arm": True}, "cases": metrics}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"{path.name} must contain one JSON object")
    return value


def _validate_source_run(run: Path) -> None:
    manifest = _load_json(run / "run_manifest.json")
    summary = _load_json(run / "summary.json")
    if (
        manifest.get("status") != "success"
        or manifest.get("run_id") != run.name
        or summary.get("status") != "success"
        or summary.get("role") != "rf_oatof_simion_single_flight_summary"
    ):
        raise ContractError(f"source is not a successful continuous-flight run: {run}")


def _event_maps(checkpoints: pd.DataFrame) -> dict[str, dict[int, dict[str, float]]]:
    required = {
        "particle_id",
        "event",
        "instrument_time_us",
        "x_mm",
        "y_mm",
        "z_mm",
        "vx_mm_per_us",
        "vy_mm_per_us",
        "vz_mm_per_us",
    }
    if missing := sorted(required - set(checkpoints.columns)):
        raise ContractError(f"checkpoint columns are missing: {', '.join(missing)}")
    result: dict[str, dict[int, dict[str, float]]] = {}
    for event in EVENTS:
        rows = checkpoints.loc[checkpoints["event"].eq(event)]
        if rows["particle_id"].duplicated().any():
            raise ContractError(f"duplicate particle identity at event {event}")
        result[event] = {
            int(row.particle_id): {
                "time_us": float(row.instrument_time_us),
                "x_mm": float(row.x_mm),
                "y_mm": float(row.y_mm),
                "z_mm": float(row.z_mm),
                "vx_mm_per_us": float(row.vx_mm_per_us),
                "vy_mm_per_us": float(row.vy_mm_per_us),
                "vz_mm_per_us": float(row.vz_mm_per_us),
            }
            for row in rows.itertuples(index=False)
        }
    return result


def _rms(values: Iterable[float]) -> float:
    array = np.asarray(list(values), dtype=float)
    if array.size == 0:
        raise ContractError("RMS requires at least one value")
    return float(np.sqrt(np.mean(array**2)))


def _cloud_stats(rows: dict[int, dict[str, float]]) -> dict[str, Any]:
    if len(rows) < 2:
        raise ContractError("spatial statistics require at least two particles")
    result: dict[str, Any] = {"particles": len(rows)}
    for axis in "xyz":
        values = np.asarray([row[f"{axis}_mm"] for row in rows.values()])
        result[f"mean_{axis}_mm"] = float(np.mean(values))
        result[f"sample_sigma_{axis}_mm"] = float(np.std(values, ddof=1))
    return result


def _pair_event(
    wide: dict[int, dict[str, float]], small: dict[int, dict[str, float]]
) -> tuple[dict[str, Any], list[dict[str, float | int]]]:
    wide_ids, small_ids = set(wide), set(small)
    common = sorted(wide_ids & small_ids)
    residuals: list[dict[str, float | int]] = []
    for particle_id in common:
        left, right = wide[particle_id], small[particle_id]
        row: dict[str, float | int] = {
            "particle_id": particle_id,
            "delta_time_small_minus_wide_ns": (right["time_us"] - left["time_us"]) * 1e3,
        }
        for axis in "xyz":
            row[f"delta_{axis}_mm"] = right[f"{axis}_mm"] - left[f"{axis}_mm"]
            if np.isfinite(left[f"v{axis}_mm_per_us"]) and np.isfinite(
                right[f"v{axis}_mm_per_us"]
            ):
                row[f"delta_v{axis}_m_s"] = (
                    right[f"v{axis}_mm_per_us"] - left[f"v{axis}_mm_per_us"]
                ) * 1e3
            else:
                row[f"delta_v{axis}_m_s"] = float("nan")
        residuals.append(row)
    position_norm = [
        np.sqrt(sum(float(row[f"delta_{axis}_mm"]) ** 2 for axis in "xyz"))
        for row in residuals
    ]
    velocity_norm = [
        np.sqrt(sum(float(row[f"delta_v{axis}_m_s"]) ** 2 for axis in "xyz"))
        for row in residuals
        if all(np.isfinite(float(row[f"delta_v{axis}_m_s"])) for axis in "xyz")
    ]
    metrics: dict[str, Any] = {
        "wide_particles": len(wide_ids),
        "small_particles": len(small_ids),
        "common_particles": len(common),
        "wide_only_particles": len(wide_ids - small_ids),
        "small_only_particles": len(small_ids - wide_ids),
        "jaccard_identity": len(common) / len(wide_ids | small_ids),
    }
    if residuals:
        delta_time = [float(row["delta_time_small_minus_wide_ns"]) for row in residuals]
        metrics.update(
            {
                "mean_delta_time_small_minus_wide_ns": float(np.mean(delta_time)),
                "rms_delta_time_ns": _rms(delta_time),
                "position_vector_rms_mm": _rms(position_norm),
                "velocity_vector_rms_m_s": _rms(velocity_norm) if velocity_norm else None,
            }
        )
    return metrics, residuals


def analyze_runs(wide_run: Path, small_run: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate two immutable runs and compute paired transport/peak diagnostics."""

    for run in (wide_run, small_run):
        _validate_source_run(run)
    wide_initial = pd.read_csv(wide_run / "inputs" / "single_flight_initial_global_state.csv")
    small_initial = pd.read_csv(small_run / "inputs" / "single_flight_initial_global_state.csv")
    if not wide_initial.equals(small_initial):
        raise ContractError("continuous-flight branches do not use the same N=1000 mother sample")
    if len(wide_initial) != 1000:
        raise ContractError("aperture comparison requires the standard N=1000 mother sample")

    frontend = {
        "wide": _load_json(wide_run / "inputs" / "single_flight_frontend_contract.json"),
        "small": _load_json(small_run / "inputs" / "single_flight_frontend_contract.json"),
    }
    apertures = {
        name: [float(contract["aperture"][key]) for key in ("width_mm", "height_mm")]
        for name, contract in frontend.items()
    }
    if apertures["wide"] != [1.0, 0.9] or apertures["small"] != [0.5, 0.5]:
        raise ContractError(f"unexpected aperture pair: {apertures}")
    for name, contract in frontend.items():
        if float(contract["junction_enclosure"]["shield_potential_V"]) != 0.0:
            raise ContractError(f"{name} branch shield is not grounded")

    frames = {
        "wide": pd.read_csv(wide_run / "results" / "single_flight_particle_checkpoints.csv"),
        "small": pd.read_csv(small_run / "results" / "single_flight_particle_checkpoints.csv"),
    }
    events = {name: _event_maps(frame) for name, frame in frames.items()}
    event_metrics: dict[str, Any] = {}
    residuals_by_event: dict[str, list[dict[str, float | int]]] = {}
    for event in EVENTS:
        event_metrics[event], residuals_by_event[event] = _pair_event(
            events["wide"][event], events["small"][event]
        )

    detector_common = sorted(
        set(events["wide"]["detector_crossing"])
        & set(events["small"]["detector_crossing"])
    )
    peak_metrics: dict[str, Any] = {}
    spectra: dict[str, Any] = {}
    for name in ("wide", "small"):
        all_tof = np.asarray(
            [row["time_us"] for row in events[name]["detector_crossing"].values()]
        )
        common_tof = np.asarray(
            [events[name]["detector_crossing"][particle_id]["time_us"] for particle_id in detector_common]
        )
        peak_metrics[f"{name}_all"], spectra[f"{name}_all"] = compute_peak_metrics(all_tof, 100.0)
        peak_metrics[f"{name}_common_detector_cohort"], spectra[
            f"{name}_common_detector_cohort"
        ] = compute_peak_metrics(common_tof, 100.0)

    wide_resolution = peak_metrics["wide_all"]["mass_resolution"]
    small_resolution = peak_metrics["small_all"]["mass_resolution"]
    selection_resolution = peak_metrics["wide_common_detector_cohort"]["mass_resolution"]
    common_small_resolution = peak_metrics["small_common_detector_cohort"]["mass_resolution"]
    result = {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_aperture_comparison",
        "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "capability_id": CAPABILITY_ID,
        "source_runs": {"wide": wide_run.name, "small": small_run.name},
        "controlled_variables": {
            "mother_sample_identical": True,
            "particle_count": 1000,
            "solver": "SIMION 2020",
            "execution_strategy": "simion_single_flight",
            "shield_potential_V": 0.0,
            "aperture_mm": apertures,
            "only_declared_change": "grounded physical aperture reducer geometry",
        },
        "event_identity_and_paired_residuals": event_metrics,
        "spatial": {
            name: {
                event: _cloud_stats(events[name][event])
                for event in ("multipole_handoff", "pre_pulse_state", "detector_crossing")
            }
            for name in ("wide", "small")
        },
        "peak_metrics": peak_metrics,
        "effect_decomposition": {
            "all_particle_resolution_change_pct": 100.0
            * (small_resolution - wide_resolution)
            / wide_resolution,
            "all_particle_fwhm_change_pct": 100.0
            * (
                peak_metrics["small_all"]["direct_fwhm_tof_ns"]
                - peak_metrics["wide_all"]["direct_fwhm_tof_ns"]
            )
            / peak_metrics["wide_all"]["direct_fwhm_tof_ns"],
            "small_detector_count_relative_to_wide": peak_metrics["small_all"]["particles"]
            / peak_metrics["wide_all"]["particles"],
            "wide_geometry_selection_effect_pct": 100.0
            * (selection_resolution - wide_resolution)
            / wide_resolution,
            "common_cohort_field_effect_pct": 100.0
            * (common_small_resolution - selection_resolution)
            / selection_resolution,
            "interpretation": (
                "wide-all to wide-common isolates particle-identity selection; "
                "wide-common to small-common isolates geometry/field perturbation for identical survivors"
            ),
        },
        "limits": [
            "single N=1000 mother sample and one SIMION spatial/time discretization",
            "both all-particle peaks remain asymmetric and have two significant KDE modes",
            "no aperture, mesh, RF-step or repeated-seed convergence was performed",
            "results are diagnostic and do not qualify Candidate or Formal resolution",
        ],
    }
    data = {
        "initial": wide_initial,
        "events": events,
        "frames": frames,
        "frontend": frontend,
        "spectra": spectra,
        "residuals": residuals_by_event,
        "detector_common": detector_common,
    }
    return result, data


def analyze_multi_arm_runs(
    cases: dict[str, Path], *, baseline_case: str, bootstrap_samples: int = 500
) -> dict[str, Any]:
    """Compare any number of complete continuous-flight arms against one baseline.

    Peak metrics are deliberately computed from each arm's complete detector
    cohort.  Common detector IDs are reserved for paired state/time effects.
    """

    if len(cases) < 2 or baseline_case not in cases or bootstrap_samples < 1:
        raise ContractError("multi-arm comparison requires a baseline, two arms, and bootstrap samples")
    mother_ids: set[int] | None = None
    event_maps: dict[str, dict[str, dict[int, dict[str, float]]]] = {}
    arms: dict[str, Any] = {}
    for case_id, run in sorted(cases.items()):
        _validate_source_run(run)
        initial = pd.read_csv(run / "inputs" / "single_flight_initial_global_state.csv")
        if "particle_id" not in initial or initial["particle_id"].duplicated().any():
            raise ContractError(f"{case_id} mother cohort is invalid")
        ids = set(initial["particle_id"].astype(int))
        if mother_ids is None:
            mother_ids = ids
        elif ids != mother_ids:
            raise ContractError("multi-arm branches do not use identical mother particle IDs")
        events = _event_maps(pd.read_csv(run / "results" / "single_flight_particle_checkpoints.csv"))
        if set(events["source_release"]) != ids:
            raise ContractError(f"{case_id} source-release IDs do not close the mother denominator")
        detector_times = np.asarray(
            [row["time_us"] for row in events["detector_crossing"].values()], dtype=float
        )
        if detector_times.size < 2:
            raise ContractError(f"{case_id} has too few detector arrivals for peak metrics")
        peak, _ = compute_peak_metrics(detector_times, 100.0)
        counts = {event: len(rows) for event, rows in events.items()}
        arms[case_id] = {
            "source_run_id": run.name,
            "mother_cohort_count": len(ids),
            "event_counts": counts,
            "event_transmission_fraction_of_mother": {event: count / len(ids) for event, count in counts.items()},
            "loss_classification": {event: {"not_reaching_event_count": len(ids) - count} for event, count in counts.items()},
            "all_detector_peak_metrics": peak,
        }
        event_maps[case_id] = events
    comparisons: dict[str, Any] = {}
    baseline_peak = arms[baseline_case]["all_detector_peak_metrics"]
    rng = np.random.default_rng(0)
    for case_id, events in event_maps.items():
        if case_id == baseline_case:
            continue
        paired_events: dict[str, Any] = {}
        for event in EVENTS:
            paired, _ = _pair_event(event_maps[baseline_case][event], events[event])
            paired_events[event] = paired
        common_ids = sorted(set(event_maps[baseline_case]["detector_crossing"]) & set(events["detector_crossing"]))
        delta_ns = np.asarray([
            (events["detector_crossing"][particle_id]["time_us"] - event_maps[baseline_case]["detector_crossing"][particle_id]["time_us"]) * 1e3
            for particle_id in common_ids
        ])
        bootstrap = rng.choice(delta_ns, size=(bootstrap_samples, len(delta_ns)), replace=True).mean(axis=1) if len(delta_ns) else np.asarray([])
        peak = arms[case_id]["all_detector_peak_metrics"]
        comparisons[case_id] = {
            "baseline_case": baseline_case,
            "all_detector_peak_delta": {
                "mass_resolution": peak["mass_resolution"] - baseline_peak["mass_resolution"],
                "direct_fwhm_tof_ns": peak["direct_fwhm_tof_ns"] - baseline_peak["direct_fwhm_tof_ns"],
                "population_definition": "each arm's complete detector cohort; never the common-ID intersection",
            },
            "paired_common_detector_time_difference_ns": {
                "common_particle_count": len(common_ids),
                "mean": None if not len(delta_ns) else float(np.mean(delta_ns)),
                "bootstrap_mean_95pct_interval": None if not len(bootstrap) else [float(np.quantile(bootstrap, .025)), float(np.quantile(bootstrap, .975))],
                "bootstrap_samples": bootstrap_samples,
            },
            "paired_event_state_differences": paired_events,
        }
    return {"schema_version": 1, "role": "rf_oatof_multi_arm_aperture_comparison", "status": "INCONCLUSIVE_DIAGNOSTIC_ONLY", "baseline_case": baseline_case, "controlled_variables": {"mother_particle_ids_identical": True, "paired_ids_are_not_peak_population": True}, "arms": arms, "comparisons": comparisons}


def write_paired_csv(path: Path, data: dict[str, Any]) -> None:
    """Write one mother-particle row with event survival and paired residuals."""

    residual_lookup = {
        event: {int(row["particle_id"]): row for row in rows}
        for event, rows in data["residuals"].items()
    }
    fields = ["particle_id"]
    for event in EVENTS:
        fields.extend((f"wide_{event}", f"small_{event}", f"common_{event}"))
        fields.extend(
            (
                f"{event}_delta_time_small_minus_wide_ns",
                f"{event}_position_delta_vector_mm",
                f"{event}_velocity_delta_vector_m_s",
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending")
    with pending.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for particle_id in sorted(data["initial"]["particle_id"].astype(int)):
            row: dict[str, Any] = {"particle_id": particle_id}
            for event in EVENTS:
                wide = particle_id in data["events"]["wide"][event]
                small = particle_id in data["events"]["small"][event]
                row[f"wide_{event}"] = wide
                row[f"small_{event}"] = small
                row[f"common_{event}"] = wide and small
                paired = residual_lookup[event].get(particle_id)
                if paired is not None:
                    row[f"{event}_delta_time_small_minus_wide_ns"] = paired[
                        "delta_time_small_minus_wide_ns"
                    ]
                    row[f"{event}_position_delta_vector_mm"] = np.sqrt(
                        sum(float(paired[f"delta_{axis}_mm"]) ** 2 for axis in "xyz")
                    )
                    velocity = [float(paired[f"delta_v{axis}_m_s"]) for axis in "xyz"]
                    row[f"{event}_velocity_delta_vector_m_s"] = (
                        np.sqrt(sum(value**2 for value in velocity))
                        if all(np.isfinite(velocity))
                        else ""
                    )
            writer.writerow(row)
    os.replace(pending, path)


def build_comparison_figure(
    result: dict[str, Any], data: dict[str, Any]
) -> tuple[plt.Figure, np.ndarray]:
    """Build the governed six-panel aperture comparison evidence figure."""

    figure, axes = plt.subplots(2, 3, figsize=(16.0, 9.4), constrained_layout=True)
    metrics = result["event_identity_and_paired_residuals"]
    x = np.arange(len(EVENTS))
    for name, marker, linestyle in (("wide", "o", "-"), ("small", "s", "--")):
        axes[0, 0].plot(
            x,
            [metrics[event][f"{name}_particles"] for event in EVENTS],
            color=COLORS[name], marker=marker, linestyle=linestyle, label=name,
        )
    axes[0, 0].set_xticks(x, ["release", "handoff", "pre-pulse", "accel exit", "detector"], rotation=20)
    axes[0, 0].set(title="A  Continuous-flight census", ylabel="particles")

    detector_metric = metrics["detector_crossing"]
    identity_labels = ["common", "wide only", "small only"]
    identity_counts = [
        detector_metric["common_particles"], detector_metric["wide_only_particles"],
        detector_metric["small_only_particles"],
    ]
    bars = axes[0, 1].bar(identity_labels, identity_counts,
                          color=[COLORS["common"], COLORS["wide"], COLORS["small"]])
    axes[0, 1].bar_label(bars)
    axes[0, 1].set(title="B  Detector identity overlap", ylabel="particles")

    prepulse = data["events"]
    for name, marker in (("wide", "o"), ("small", "s")):
        rows = prepulse[name]["pre_pulse_state"]
        axes[0, 2].scatter(
            [row["y_mm"] for row in rows.values()], [row["z_mm"] for row in rows.values()],
            s=5, alpha=0.38, color=COLORS[name], marker=marker,
            edgecolors="none", label=f"{name} (N={len(rows)})",
        )
    center_z = float(data["frontend"]["wide"]["source_exit_center_mm"]["z"])
    for name, linestyle in (("wide", "-"), ("small", "--")):
        aperture = data["frontend"][name]["aperture"]
        width, height = float(aperture["width_mm"]), float(aperture["height_mm"])
        axes[0, 2].add_patch(Rectangle(
            (-width / 2, center_z - height / 2), width, height, fill=False,
            color=COLORS[name], linestyle=linestyle, linewidth=1.3,
        ))
    axes[0, 2].set_aspect("equal", adjustable="box")
    axes[0, 2].set(title="C  Pre-pulse y-z distribution", xlabel="global y (mm)", ylabel="global z (mm)")

    for name, marker in (("wide", "o"), ("small", "s")):
        rows = data["events"][name]["detector_crossing"]
        axes[1, 0].scatter(
            [row["x_mm"] for row in rows.values()], [row["y_mm"] for row in rows.values()],
            s=5, alpha=0.4, color=COLORS[name], marker=marker,
            edgecolors="none", label=f"{name} (N={len(rows)})",
        )
    axes[1, 0].set_aspect("equal", adjustable="box")
    axes[1, 0].set(title="D  Detector crossings", xlabel="global x (mm)", ylabel="global y (mm)")

    for name, linestyle in (("wide_all", "-"), ("small_all", "--")):
        spectrum = data["spectra"][name]
        centered = (spectrum["time_grid_us"] - np.mean(spectrum["tof_us"])) * 1e3
        case = name.split("_")[0]
        axes[1, 1].plot(centered, spectrum["time_density_normalized"],
                        color=COLORS[case], linestyle=linestyle, label=name.replace("_", " "))
    axes[1, 1].set(title="E  All-detector TOF KDE", xlabel="TOF − mean (ns)", ylabel="normalized density")

    paired_detector = data["residuals"]["detector_crossing"]
    delta = np.asarray([row["delta_time_small_minus_wide_ns"] for row in paired_detector])
    axes[1, 2].hist(delta, bins=24, density=True, histtype="stepfilled", alpha=0.35,
                    color=COLORS["common"], label=f"common N={len(delta)}")
    axes[1, 2].axvline(float(np.mean(delta)), color="#252525", linestyle="--",
                       label=f"mean={np.mean(delta):+.3f} ns")
    axes[1, 2].set(title="F  Paired detector timing residual", xlabel="small − wide TOF (ns)", ylabel="probability density")

    for ax in axes.flat:
        ax.grid(alpha=0.18)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(fontsize=7, frameon=False)
    figure.suptitle(
        "Continuous octupole → oaTOF aperture comparison, same N=1000 mother sample\n"
        "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        fontsize=12,
    )
    return figure, axes


def _save_figure(figure: plt.Figure, path: Path, dpi: int = 220) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending")
    figure.savefig(pending, format="png", dpi=dpi, facecolor="white")
    plt.close(figure)
    os.replace(pending, path)


def publish_run(repo_root: Path, run_id: str, wide_run: Path, small_run: Path) -> Path:
    """Publish one immutable analysis run from two verified solver runs."""

    validate_run_id(run_id)
    repo_root, workspace_root = repo_root.resolve(), repo_root.resolve().parent
    run_dir = workspace_root / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
    if run_dir.exists():
        raise ContractError(f"analysis run already exists: {run_dir}")
    implementation = Path(__file__).resolve()
    spatial_implementation = implementation.with_name("plot_single_flight_spatial_six_panel.py")
    capability_catalog = repo_root / "integrations" / INTEGRATION_ID / "config" / "analysis_capabilities.json"
    requirements_lock = repo_root / "requirements-lock.txt"
    run_dir.mkdir(parents=True)
    result_path = run_dir / "results" / "single_flight_aperture_comparison.json"
    paired_path = run_dir / "results" / "single_flight_aperture_particle_pairs.csv"
    figure_path = run_dir / "results" / "single_flight_aperture_comparison.png"
    figure_metadata_path = run_dir / "results" / "single_flight_aperture_comparison.figure.json"
    small_spatial_path = run_dir / "results" / "aperture050_single_flight_spatial_six_panel.png"
    small_spatial_metadata_path = run_dir / "results" / "aperture050_single_flight_spatial_six_panel.figure.json"
    summary_path = run_dir / "summary.json"
    run_config_path = run_dir / "run_config.json"
    manifest_path = run_dir / "run_manifest.json"
    inputs = {
        "wide_manifest": wide_run / "run_manifest.json",
        "wide_summary": wide_run / "summary.json",
        "wide_initial": wide_run / "inputs" / "single_flight_initial_global_state.csv",
        "wide_checkpoints": wide_run / "results" / "single_flight_particle_checkpoints.csv",
        "wide_frontend": wide_run / "inputs" / "single_flight_frontend_contract.json",
        "small_manifest": small_run / "run_manifest.json",
        "small_summary": small_run / "summary.json",
        "small_initial": small_run / "inputs" / "single_flight_initial_global_state.csv",
        "small_checkpoints": small_run / "results" / "single_flight_particle_checkpoints.csv",
        "small_frontend": small_run / "inputs" / "single_flight_frontend_contract.json",
        "small_upstream": small_run / "inputs" / "upstream_resolved_design.json",
        "small_oatof": small_run / "inputs" / "oatof_resolved_geometry.json",
        "comparison_implementation": implementation,
        "spatial_implementation": spatial_implementation,
        "analysis_capability_catalog": capability_catalog,
        "requirements_lock": requirements_lock,
    }
    if any(not path.is_file() for path in inputs.values()):
        raise ContractError("one or more aperture comparison inputs are missing")
    frozen = freeze_repository_inputs(inputs, repo_root=repo_root, run_dir=run_dir)
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": MODE,
        "project_root": str(workspace_root),
        "inputs": {name: portable_path(path, workspace_root) for name, path in sorted(frozen.items())},
        "parameters": {
            "analysis_class": "POSTHOC_PAIRED_DIAGNOSTIC",
            "capability_id": CAPABILITY_ID,
            "source_run_ids": [wide_run.name, small_run.name],
            "particle_count": 1000,
            "aperture_pair_mm": [[1.0, 0.9], [0.5, 0.5]],
            "qualification_decision_made": False,
        },
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        "formal_gate_passed": False,
    }
    write_pending_json(run_config_path, run_config)
    write_pending_json(summary_path, {
        "schema_version": 1, "role": "rf_oatof_single_flight_aperture_comparison_summary",
        "status": "interrupted", "analysis_status": "NOT_RUN", "formal_gate_passed": False,
    })
    pending_manifest = manifest_path.with_name(".run_manifest.json.pending")
    publish_manifest(
        repo_root=repo_root, run_config=run_config_path, manifest_path=pending_manifest,
        status="interrupted", outputs=(summary_path,), project=INTEGRATION_ID,
        mode=MODE, label="single-flight-aperture-comparison",
    )
    os.replace(pending_manifest, manifest_path)

    result, data = analyze_runs(wide_run, small_run)
    write_pending_json(result_path, result)
    write_paired_csv(paired_path, data)
    comparison_figure, _ = build_comparison_figure(result, data)
    _save_figure(comparison_figure, figure_path)
    write_pending_json(figure_metadata_path, {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_aperture_comparison_figure_manifest",
        "capability_id": CAPABILITY_ID,
        "source_run_ids": [wide_run.name, small_run.name],
        "dimensions_inches": [16.0, 9.4], "format": "PNG", "dpi": 220,
        "particle_filter": "none; panels identify all event rows or the explicit common detector cohort",
        "tof_estimator": "canonical direct KDE FWHM",
        "qualification_decision_made": False,
    })

    spatial_figure, spatial_counts = build_spatial_figure(
        data["initial"], data["frames"]["small"],
        _load_json(small_run / "inputs" / "upstream_resolved_design.json"),
        data["frontend"]["small"],
        _load_json(small_run / "inputs" / "oatof_resolved_geometry.json"),
        _load_json(small_run / "summary.json")["source_region_diagnostic"],
    )
    _save_figure(spatial_figure, small_spatial_path, dpi=190)
    write_pending_json(small_spatial_metadata_path, {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_spatial_six_panel_figure_manifest",
        "capability_id": "rf_oatof_single_flight_spatial_six_panel_v2",
        "source_run_id": small_run.name,
        "counts": spatial_counts,
        "aperture_mm": [0.5, 0.5],
        "republication_reason": "correct dynamic aperture legend in a new immutable analysis run",
        "format": "PNG", "dpi": 190,
    })
    summary = {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_aperture_comparison_summary",
        "status": "success",
        "analysis_status": "INCONCLUSIVE_DIAGNOSTIC_ONLY",
        "source_run_ids": [wide_run.name, small_run.name],
        "result": portable_path(result_path, run_dir),
        "paired_particles": portable_path(paired_path, run_dir),
        "comparison_figure": portable_path(figure_path, run_dir),
        "aperture050_spatial_figure": portable_path(small_spatial_path, run_dir),
        "formal_gate_passed": False,
    }
    write_pending_json(summary_path, summary)
    outputs = (
        result_path, paired_path, figure_path, figure_metadata_path,
        small_spatial_path, small_spatial_metadata_path, summary_path,
    )
    publish_manifest(
        repo_root=repo_root, run_config=run_config_path, manifest_path=pending_manifest,
        status="success", outputs=outputs, project=INTEGRATION_ID, mode=MODE,
        label="single-flight-aperture-comparison",
    )
    os.replace(pending_manifest, manifest_path)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--wide-run", type=Path, required=True)
    parser.add_argument("--small-run", type=Path, required=True)
    args = parser.parse_args()
    manifest = publish_run(args.repo_root, args.run_id, args.wide_run, args.small_run)
    print(f"SINGLE_FLIGHT_APERTURE_COMPARISON=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
