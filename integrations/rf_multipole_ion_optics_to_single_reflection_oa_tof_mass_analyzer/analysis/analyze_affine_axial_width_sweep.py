"""Analyze finite-width nonlinear timing with the existing all-ideal physics APIs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json, validate_schema
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from common.multipole.compile_design_request import canonical_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.affine_axial_ideal_report import (
    ENERGY_ENVELOPE_ABS_TOL_V,
    INTEGRATION_ROOT,
    WORKSPACE_ROOT,
    compute_analytic_report,
    resolve_bound_input_path,
    select_bound_source_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    resolve_source_materialization_profile,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    PhysicsContractError,
    accelerator_state,
    linear_phase_space_timing_coefficients,
    time_to_fixed_plane_s,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import (
    solve_coupled_reflectron_from_accelerator_derivatives,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.reflectron_dual_stage_solver import (
    flight_time_s,
)


CHECKPOINTS = ("accelerator_focus", "reflectron_entrance", "detector")


def _finite_positive_sequence(values: object, label: str) -> tuple[float, ...]:
    if not isinstance(values, list) or not values:
        raise PhysicsContractError(f"{label} must be a nonempty list")
    result = tuple(float(value) for value in values)
    if not all(np.isfinite(result)) or any(value <= 0.0 for value in result):
        raise PhysicsContractError(f"{label} must contain finite positive values")
    if tuple(sorted(set(result))) != result:
        raise PhysicsContractError(f"{label} must be strictly increasing and unique")
    return result


def _summary(times_us: np.ndarray, mass_amu: float) -> dict[str, float | int]:
    peak, _ = compute_peak_metrics(times_us, mass_amu)
    return {
        "mean_tof_us": float(np.mean(times_us)),
        "population_sigma_tof_ns": float(np.std(times_us, ddof=0) * 1.0e3),
        "central_80_percent_width_ns": float(
            (np.quantile(times_us, 0.9) - np.quantile(times_us, 0.1)) * 1.0e3
        ),
        "full_span_tof_ns": float(np.ptp(times_us) * 1.0e3),
        "significant_kde_modes": int(peak["significant_kde_modes"]),
    }


def _modulo_fold_masks(count: int, modulus: int, offset: int) -> tuple[np.ndarray, np.ndarray]:
    if count < 15 or count % 2 == 0:
        raise PhysicsContractError("sample_count must be an odd integer >= 15")
    if modulus < 3 or not 0 <= offset < modulus:
        raise PhysicsContractError("cross-validation modulus/offset are invalid")
    particle_ids = np.arange(1, count + 1)
    validation = particle_ids % modulus == offset
    train = ~validation
    if np.count_nonzero(train) < 7 or np.count_nonzero(validation) < 3:
        raise PhysicsContractError("particle-ID fold leaves too few rows")
    return train, validation


def _r_squared(observed: np.ndarray, predicted: np.ndarray) -> float:
    residual = float(np.sum((observed - predicted) ** 2))
    total = float(np.sum((observed - np.mean(observed)) ** 2))
    if total <= 0.0:
        raise PhysicsContractError("timing target has zero validation variance")
    return 1.0 - residual / total


def _nested_models(
    normalized_coordinate: np.ndarray,
    times_us: np.ndarray,
    train: np.ndarray,
    validation: np.ndarray,
) -> list[dict[str, Any]]:
    target_ns = (times_us - np.mean(times_us[train])) * 1.0e3
    validation_sigma = float(np.std(target_ns[validation], ddof=0))
    if validation_sigma <= 0.0:
        raise PhysicsContractError("validation timing sigma must be positive")
    models = []
    for degree in range(1, 7):
        design = np.polynomial.polynomial.polyvander(normalized_coordinate, degree)
        coefficients = np.linalg.lstsq(design[train], target_ns[train], rcond=None)[0]
        predicted = design[validation] @ coefficients
        residual = predicted - target_ns[validation]
        rmse = float(np.sqrt(np.mean(residual**2)))
        models.append(
            {
                "degree": degree,
                "coefficient_ns_per_normalized_coordinate_power": coefficients.tolist(),
                "validation_r_squared": _r_squared(target_ns[validation], predicted),
                "validation_rmse_ns": rmse,
                "validation_mae_ns": float(np.mean(np.abs(residual))),
                "validation_rmse_fraction_of_observed_sigma": rmse / validation_sigma,
            }
        )
    return models


def _legendre_variance(times_us: np.ndarray, normalized_coordinate: np.ndarray) -> dict[str, Any]:
    target_ns = (times_us - np.mean(times_us)) * 1.0e3
    design = np.polynomial.legendre.legvander(normalized_coordinate, 6)
    orthogonal, _ = np.linalg.qr(design, mode="reduced")
    projection = orthogonal.T @ target_ns
    contributions = projection[1:] ** 2
    explained = float(np.sum(contributions))
    if explained <= 0.0:
        raise PhysicsContractError("Legendre timing variance must be positive")
    return {
        "basis": "discrete_qr_orthogonalized_legendre_degree_order_on_1001_point_grid",
        "interpretation_limit": (
            "exact_discrete_global_shape_variance_not_taylor_derivative_order; "
            "higher_raw_powers_can_project_onto_lower_legendre_degrees"
        ),
        "maximum_degree": 6,
        "orthogonal_projection_ns_sqrt_count": projection.tolist(),
        "variance_contribution_ns2_by_degree_1_to_6": contributions.tolist(),
        "linear_variance_share": float(contributions[0] / explained),
        "nonlinear_degree_2_to_6_variance_share": float(np.sum(contributions[1:]) / explained),
        "quadratic_variance_share": float(contributions[1] / explained),
        "degree_3_to_6_variance_share": float(np.sum(contributions[2:]) / explained),
        "fit_r_squared_full_population": _r_squared(
            target_ns, orthogonal @ projection
        ),
    }


def _exact_quadratic_energy_extrema(
    coefficients: Any, full_width_mm: float
) -> dict[str, Any]:
    """Return endpoint-plus-stationary-point extrema of the affine energy quadratic."""

    half_width = full_width_mm / 2.0
    candidates = [-half_width, half_width]
    second = float(coefficients.energy_position_second_v_per_mm2)
    first = float(coefficients.energy_position_first_v_per_mm)
    if second != 0.0:
        stationary = -first / second
        if -half_width <= stationary <= half_width:
            candidates.append(stationary)
    energies = [
        float(coefficients.actual_energy_per_charge_v)
        + first * offset
        + 0.5 * second * offset * offset
        for offset in candidates
    ]
    minimum_index = int(np.argmin(energies))
    maximum_index = int(np.argmax(energies))
    return {
        "method": "exact_quadratic_endpoints_plus_interval_stationary_point",
        "candidate_offsets_mm": candidates,
        "candidate_energies_V": energies,
        "minimum_offset_mm": candidates[minimum_index],
        "minimum_energy_V": energies[minimum_index],
        "maximum_offset_mm": candidates[maximum_index],
        "maximum_energy_V": energies[maximum_index],
    }


def _log_width_scaling(widths: Sequence[float], values: Sequence[float]) -> dict[str, float]:
    x = np.log(np.asarray(widths, dtype=float))
    y = np.log(np.asarray(values, dtype=float))
    if np.any(~np.isfinite(y)):
        raise PhysicsContractError("width-scaling metric must be finite and positive")
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    return {
        "log_log_exponent": float(slope),
        "log_intercept": float(intercept),
        "r_squared": _r_squared(y, predicted),
    }


def _load_base_case(
    sweep: Mapping[str, Any], workspace_root: Path
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    campaign_record = sweep["base_analytic_campaign"]
    campaign_path = resolve_bound_input_path(
        workspace_root, campaign_record, "base analytic campaign"
    )
    base_report = compute_analytic_report(
        campaign_path, str(sweep["base_case_id"]), workspace_root=workspace_root
    )
    campaign = load_json(campaign_path)
    cases = [case for case in campaign["cases"] if case.get("case_id") == sweep["base_case_id"]]
    if len(cases) != 1:
        raise PhysicsContractError("base_case_id must select exactly one analytic case")
    case = cases[0]
    if (
        base_report["architecture_id"] != sweep["fixed_architecture_id"]
        or case["source_profile_id"] != sweep["source_family_profile_id"]
    ):
        raise PhysicsContractError("fixed architecture or source-line identity differs")
    geometry = load_json(
        resolve_bound_input_path(workspace_root, case["resolved_geometry"], "geometry")
    )
    receipt = load_json(
        resolve_bound_input_path(
            workspace_root, case["source_materialization_receipt"], "source receipt"
        )
    )
    registry_path = (workspace_root / campaign["source_profile_registry_path"]).resolve()
    profile = resolve_source_materialization_profile(
        dict(select_bound_source_profile(load_json(registry_path), case)), INTEGRATION_ROOT
    )
    return case, geometry, receipt, profile


def compute_width_sweep_report(
    campaign_path: Path,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Return the explicitly exploratory all-ideal affine width-sweep analysis."""

    campaign_path = campaign_path.resolve()
    sweep = load_json(campaign_path)
    validate_schema(
        sweep, "rf_oatof_affine_axial_all_ideal_width_sweep_campaign.schema.json"
    )
    if not isinstance(sweep, dict) or (
        sweep.get("role") != "rf_oatof_affine_axial_all_ideal_width_sweep_campaign"
        or sweep.get("evidence_level") != "EXPLORATORY_PROVISIONAL"
        or sweep.get("solver_execution_allowed") is not False
        or sweep.get("threshold_status")
        != "declared_after_initial_observation_not_preregistered"
    ):
        raise PhysicsContractError("width-sweep campaign identity is invalid")
    widths = _finite_positive_sequence(sweep.get("full_widths_mm"), "full_widths_mm")
    sample_count = int(sweep.get("sample_count", 0))
    cross_validation = sweep.get("cross_validation", {})
    modulus = int(cross_validation.get("particle_id_modulus", 0))
    offsets = tuple(int(value) for value in cross_validation.get("validation_offsets", ()))
    if (
        cross_validation.get("method") != "five_fold_particle_id_modulo"
        or modulus != 5
        or offsets != tuple(range(modulus))
        or cross_validation.get("selection_uses_detector_outcome") is not False
    ):
        raise PhysicsContractError("cross-validation must enumerate every particle-ID modulo fold")
    folds = [
        (offset, *_modulo_fold_masks(sample_count, modulus, offset)) for offset in offsets
    ]
    case, geometry, receipt, profile = _load_base_case(sweep, workspace_root)
    accelerator = geometry["geometry_derivation"]["accelerator"]
    theory = accelerator["finite_interval_theory"]
    reflectron = theory["coupled_reflectron"]
    electrodes = geometry["electrodes_V"]
    mass_amu = float(case["source_contract"]["mass_amu"])
    charge = int(case["source_contract"]["charge_state"])
    mz = mass_to_charge_th(mass_amu, charge)
    center_z = float(receipt["resolved_target_center_mm"][2])
    repeller_z = float(accelerator["canonical_repeller_z_mm"])
    mean_vz = float(profile["mean_velocity_z_m_per_s"])
    slope_vz = float(profile["velocity_z_slope_m_per_s_per_mm"])
    upstream = float(reflectron["upstream_from_accelerator_focus_mm"])
    downstream = float(reflectron["downstream_to_detector_mm"])
    total_free = upstream + downstream
    if not 0.0 < upstream < total_free:
        raise PhysicsContractError("reflectron entrance distance is invalid")
    normalized = np.linspace(-1.0, 1.0, sample_count)
    widest = max(widths)
    center_state = accelerator_state(
        float(electrodes["repeller"]),
        float(electrodes["grid1"]),
        float(accelerator["d1_mm"]),
        float(accelerator["d2_mm"]),
        exit_v=float(electrodes["grid2"]),
        release_position_mm=center_z - repeller_z,
        require_downstream_focus=False,
    )
    accelerator_coefficients = linear_phase_space_timing_coefficients(
        center_state,
        mz,
        mean_vz,
        slope_vz,
        float(theory["focus_drift_mm"]),
    )
    exact_energy_extrema = _exact_quadratic_energy_extrema(
        accelerator_coefficients, widest
    )
    coupled = solve_coupled_reflectron_from_accelerator_derivatives(
        accelerator_coefficients.actual_energy_per_charge_v,
        float(geometry["geometry_mm"]["L_stage1"]),
        upstream,
        downstream,
        accelerator_coefficients.first_derivative_at_focus,
        accelerator_coefficients.second_derivative_at_focus,
        energy_min_v=float(exact_energy_extrema["minimum_energy_V"]),
        energy_max_v=float(exact_energy_extrema["maximum_energy_V"]),
    )
    if coupled.required_stage2_depth_mm > float(geometry["geometry_mm"]["L_stage2"]):
        raise PhysicsContractError("rederived widest-source envelope exceeds fixed stage-2 length")

    def timing_at_offset(offset_mm: float) -> tuple[float, float, dict[str, float]]:
        z = center_z + offset_mm
        vz = mean_vz + slope_vz * offset_mm
        release_z = z - repeller_z
        state = accelerator_state(
            float(electrodes["repeller"]),
            float(electrodes["grid1"]),
            float(accelerator["d1_mm"]),
            float(accelerator["d2_mm"]),
            exit_v=float(electrodes["grid2"]),
            release_position_mm=release_z,
            require_downstream_focus=False,
        )
        energy = state.nominal_energy_per_charge_v + kinetic_energy_ev(
            mass_amu, 0.0, 0.0, vz
        ) / charge
        focus_s = time_to_fixed_plane_s(
            float(electrodes["repeller"]),
            float(electrodes["grid1"]),
            float(accelerator["d1_mm"]),
            float(accelerator["d2_mm"]),
            release_z,
            vz,
            float(theory["focus_drift_mm"]),
            mz,
            exit_v=float(electrodes["grid2"]),
        )
        reflectron_arguments = (
            energy,
            mz,
            coupled.stage1_voltage_drop_v,
            coupled.stage1_field_v_per_mm,
            coupled.stage2_field_v_per_mm,
        )
        total_reflectron_s = flight_time_s(
            reflectron_arguments[0],
            reflectron_arguments[1],
            total_free,
            *reflectron_arguments[2:],
        )
        without_upstream_s = flight_time_s(
            reflectron_arguments[0],
            reflectron_arguments[1],
            total_free - upstream,
            *reflectron_arguments[2:],
        )
        return z, vz, {
            "axial_energy_per_charge_V": energy,
            "accelerator_focus": focus_s * 1.0e6,
            "reflectron_entrance": (focus_s + total_reflectron_s - without_upstream_s)
            * 1.0e6,
            "detector": (focus_s + total_reflectron_s) * 1.0e6,
        }

    closure = sweep["local_taylor_closure"]
    if closure.get("coefficient_source") != "linear_phase_space_timing_coefficients":
        raise PhysicsContractError("local Taylor coefficient authority is invalid")
    if closure.get("require_resolved_accelerator_coefficient_match") is True:
        first_difference = abs(
            accelerator_coefficients.first_derivative_at_focus
            - float(reflectron["accelerator_first_derivative_at_focus"])
        )
        second_difference = abs(
            accelerator_coefficients.second_derivative_at_focus
            - float(reflectron["accelerator_second_derivative_at_focus"])
        )
        if first_difference > float(
            closure["maximum_accelerator_first_coefficient_difference_mm_per_v_pow_3_over_2"]
        ) or second_difference > float(
            closure["maximum_accelerator_second_coefficient_difference_mm_per_v_pow_5_over_2"]
        ):
            raise PhysicsContractError("recomputed accelerator timing coefficients differ from resolved")
    else:
        first_difference = None
        second_difference = None
    step = float(closure["detector_central_difference_step_mm"])
    if not np.isfinite(step) or step <= 0.0 or step >= widest / 2.0:
        raise PhysicsContractError("detector central-difference step is invalid")
    _, _, minus = timing_at_offset(-step)
    _, _, center = timing_at_offset(0.0)
    _, _, plus = timing_at_offset(step)
    detector_first_ns_per_mm = (
        plus["detector"] - minus["detector"]
    ) * 1.0e3 / (2.0 * step)
    detector_second_ns_per_mm2 = (
        plus["detector"] - 2.0 * center["detector"] + minus["detector"]
    ) * 1.0e3 / (step * step)
    closure_checks = {
        "coupled_first_residual": abs(coupled.total_first_derivative_residual)
        <= float(closure["maximum_abs_coupled_first_residual_mm_per_v_pow_3_over_2"]),
        "coupled_second_residual": abs(coupled.total_second_derivative_residual)
        <= float(closure["maximum_abs_coupled_second_residual_mm_per_v_pow_5_over_2"]),
        "detector_time_path_first_derivative": abs(detector_first_ns_per_mm)
        <= float(closure["maximum_abs_detector_first_derivative_ns_per_mm"]),
        "detector_time_path_second_derivative": abs(detector_second_ns_per_mm2)
        <= float(closure["maximum_abs_detector_second_derivative_ns_per_mm2"]),
    }
    if not all(closure_checks.values()):
        raise PhysicsContractError("local detector Taylor first/second-order closure failed")
    width_results = []
    timing_arrays: dict[float, dict[str, np.ndarray]] = {}
    for width in widths:
        records = []
        checkpoint_values = {checkpoint: [] for checkpoint in CHECKPOINTS}
        energies = []
        for index, coordinate in enumerate(normalized):
            xi = width * coordinate / 2.0
            z, vz, timing = timing_at_offset(float(xi))
            energy = timing["axial_energy_per_charge_V"]
            times_us = {checkpoint: timing[checkpoint] for checkpoint in CHECKPOINTS}
            for checkpoint in CHECKPOINTS:
                checkpoint_values[checkpoint].append(times_us[checkpoint])
            energies.append(energy)
            records.append(
                {
                    "particle_id": index + 1,
                    "normalized_coordinate": float(coordinate),
                    "affine_offset_mm": float(xi),
                    "initial_z_mm": float(z),
                    "initial_vz_m_per_s": float(vz),
                    "axial_energy_per_charge_V": float(energy),
                    **{f"{name}_tof_us": value for name, value in times_us.items()},
                }
            )
        timing_arrays[width] = {
            name: np.asarray(values, dtype=float) for name, values in checkpoint_values.items()
        }
        energy_values = np.asarray(energies)
        outside = (energy_values < coupled.energy_min_v - ENERGY_ENVELOPE_ABS_TOL_V) | (
            energy_values > coupled.energy_max_v + ENERGY_ENVELOPE_ABS_TOL_V
        )
        width_results.append(
            {
                "full_width_mm": width,
                "checkpoint_summaries": {
                    name: _summary(values, mass_amu)
                    for name, values in timing_arrays[width].items()
                },
                "energy_envelope_outside_count": int(np.count_nonzero(outside)),
                "particle_timing_records_sha256": canonical_sha256(records),
                "particle_timing_records": records,
            }
        )

    model_width = float(sweep["model_full_width_mm"])
    if model_width not in timing_arrays:
        raise PhysicsContractError("model_full_width_mm is not a registered sweep width")
    models = {}
    for checkpoint, values in timing_arrays[model_width].items():
        fold_results = []
        for offset, train, validation in folds:
            fold_results.append(
                {
                    "validation_offset": offset,
                    "train_count": int(np.count_nonzero(train)),
                    "validation_count": int(np.count_nonzero(validation)),
                    "train_particle_ids_sha256": canonical_sha256(
                        (np.flatnonzero(train) + 1).tolist()
                    ),
                    "validation_particle_ids_sha256": canonical_sha256(
                        (np.flatnonzero(validation) + 1).tolist()
                    ),
                    "nested_polynomial_models": _nested_models(
                        normalized, values, train, validation
                    ),
                }
            )
        degree_metrics = {
            degree: [fold["nested_polynomial_models"][degree - 1] for fold in fold_results]
            for degree in range(1, 7)
        }
        models[checkpoint] = {
            "five_fold_particle_id_modulo": fold_results,
            "worst_case_validation": {
                f"degree_{degree}": {
                    "minimum_r_squared": min(
                        metric["validation_r_squared"] for metric in metrics
                    ),
                    "maximum_r_squared": max(
                        metric["validation_r_squared"] for metric in metrics
                    ),
                    "maximum_rmse_fraction_of_observed_sigma": max(
                        metric["validation_rmse_fraction_of_observed_sigma"]
                        for metric in metrics
                    ),
                }
                for degree, metrics in degree_metrics.items()
            },
            "legendre_variance": _legendre_variance(values, normalized),
        }
    scaling = {}
    for checkpoint in CHECKPOINTS:
        scaling[checkpoint] = {}
        for metric in (
            "population_sigma_tof_ns",
            "central_80_percent_width_ns",
            "full_span_tof_ns",
        ):
            scaling[checkpoint][metric] = _log_width_scaling(
                widths,
                [result["checkpoint_summaries"][checkpoint][metric] for result in width_results],
            )

    target_checkpoint = str(sweep["exploratory_target_checkpoint"])
    target = models[target_checkpoint]
    worst = target["worst_case_validation"]
    full_model = worst["degree_6"]
    quadratic_model = worst["degree_2"]
    cubic_model = worst["degree_3"]
    sigma_scaling = scaling[target_checkpoint]["population_sigma_tof_ns"]
    thresholds = sweep["exploratory_declared_thresholds"]
    reconstruction_checks = {
        "full_model_validation_r_squared_all_folds": full_model["minimum_r_squared"]
        >= float(thresholds["minimum_full_model_validation_r_squared"]),
        "full_model_validation_rmse_fraction_all_folds": full_model[
            "maximum_rmse_fraction_of_observed_sigma"
        ]
        <= float(thresholds["maximum_full_model_validation_rmse_fraction_of_sigma"]),
        "quadratic_model_is_insufficient_in_every_fold": quadratic_model[
            "maximum_r_squared"
        ]
        < float(thresholds["minimum_full_model_validation_r_squared"]),
        "cubic_model_meets_common_adequacy_boundary_in_every_fold": (
            cubic_model["minimum_r_squared"]
            >= float(thresholds["minimum_full_model_validation_r_squared"])
            and cubic_model["maximum_rmse_fraction_of_observed_sigma"]
            <= float(thresholds["maximum_full_model_validation_rmse_fraction_of_sigma"])
        ),
    }
    width_scaling_checks = {
        "sigma_width_exponent_lower_bound": sigma_scaling["log_log_exponent"]
        >= float(thresholds["minimum_sigma_log_width_exponent"]),
        "sigma_width_exponent_upper_bound": sigma_scaling["log_log_exponent"]
        <= float(thresholds["maximum_sigma_log_width_exponent"]),
        "sigma_width_scaling_r_squared": sigma_scaling["r_squared"]
        >= float(thresholds["minimum_sigma_log_width_fit_r_squared"]),
        "energy_envelope_outside_count": max(
            result["energy_envelope_outside_count"] for result in width_results
        )
        <= int(thresholds["maximum_energy_envelope_outside_count"]),
    }
    local_taylor_supported = all(closure_checks.values())
    reconstruction_supported = all(reconstruction_checks.values())
    width_scaling_supported = all(width_scaling_checks.values())
    return {
        "schema_version": 1,
        "report_role": "rf_oatof_affine_axial_all_ideal_width_sweep_report",
        "status": "EXPLORATORY_PROVISIONAL",
        "evidence_level": "EXPLORATORY_PROVISIONAL",
        "claim_scope": f"affine_all_ideal_axial_n{sample_count}_exploratory_diagnostic_only",
        "threshold_status": "declared_after_initial_observation_not_preregistered",
        "exclusion_limitations": [
            "does_not_exclude_real_field_or_grid_effects",
            "does_not_exclude_transverse_coupling",
            "does_not_validate_solver_source_release",
            "does_not_exclude_solver_numerical_discretization",
            "does_not_apply_to_true_zero_vz_source_family",
        ],
        "campaign": {"path": campaign_path.as_posix(), "sha256": file_sha256(campaign_path)},
        "fixed_architecture_id": sweep["fixed_architecture_id"],
        "source_family": {
            "profile_id": sweep["source_family_profile_id"],
            "identity_semantics": "affine_line_parameter_authority_not_analysis_particle_cohort",
            "reused_parameters": [
                "mass_amu",
                "charge_state",
                "mean_velocity_z_m_per_s",
                "velocity_z_slope_m_per_s_per_mm",
            ],
        },
        "rederived_widest_source_coupled_reflectron": {
            "derivation": "solve_coupled_reflectron_from_accelerator_derivatives_with_actual_affine_energy_min_max",
            "energy_extrema": exact_energy_extrema,
            "energy_min_V": coupled.energy_min_v,
            "energy_max_V": coupled.energy_max_v,
            "stage1_voltage_drop_V": coupled.stage1_voltage_drop_v,
            "stage1_field_V_per_mm": coupled.stage1_field_v_per_mm,
            "stage2_field_V_per_mm": coupled.stage2_field_v_per_mm,
            "required_stage2_depth_mm": coupled.required_stage2_depth_mm,
            "fixed_stage2_length_mm": float(geometry["geometry_mm"]["L_stage2"]),
            "total_first_derivative_residual": coupled.total_first_derivative_residual,
            "total_second_derivative_residual": coupled.total_second_derivative_residual,
            "outside_count_interpretation": "constructive_self_consistency_against_rederived_envelope",
            "stage2_depth_interpretation": "independent_fixed_geometry_containment_check",
            "closure_semantics": {
                "first_order": "stage2_field_is_algebraically_constructed_from_the_first_order_equation",
                "second_order": "existing_coupled_solver_applies_a_scale_aware_second_order_residual_guard",
                "independent_time_path_check": "central_difference_of_the_same_exact_detector_time_path",
            },
        },
        "local_taylor_closure": {
            "authority": "linear_phase_space_timing_coefficients_plus_coupled_solver_plus_detector_time_path",
            "recomputed_accelerator_first_coefficient": accelerator_coefficients.first_derivative_at_focus,
            "recomputed_accelerator_second_coefficient": accelerator_coefficients.second_derivative_at_focus,
            "resolved_accelerator_first_coefficient_difference": first_difference,
            "resolved_accelerator_second_coefficient_difference": second_difference,
            "coupled_total_first_residual": coupled.total_first_derivative_residual,
            "coupled_total_second_residual": coupled.total_second_derivative_residual,
            "detector_central_difference_step_mm": step,
            "detector_first_derivative_ns_per_mm": detector_first_ns_per_mm,
            "detector_second_derivative_ns_per_mm2": detector_second_ns_per_mm2,
            "declared_thresholds": dict(closure),
            "checks": closure_checks,
            "local_taylor_degree_3_or_higher_start_supported": local_taylor_supported,
            "interpretation_limit": "local_starting_order_only_not_global_variance_dominance",
        },
        "third_and_higher_derivative_authority": {
            "existing_coupled_total_third_derivative": coupled.total_third_derivative,
            "published_nonnull_total_third_derivative_available": (
                coupled.total_third_derivative is not None
            ),
            "current_report_uses_total_third_derivative_as_authority": False,
            "next_stage_supported_method": (
                "reuse_the_same_existing_exact_accelerator_and_reflectron_time_APIs_at_"
                "symmetric_offsets_minus2h_minush_zero_plush_plus2h_and_require_h_to_half_h_"
                "convergence_for_detector_D3_and_D4"
            ),
            "next_stage_claim_limit": (
                "symmetric_time_differences_may_estimate_D3_D4_but_cannot_become_an_"
                "authoritative_unique_order_claim_without_step_convergence"
            ),
        },
        "sample_count_per_width": sample_count,
        "deterministic_quadrature_cohort": {
            "cohort_role": "symmetric_affine_axial_quadrature_not_materialized_source_release",
            "particle_id_start": 1,
            "particle_id_end": sample_count,
            "particle_count": sample_count,
            "normalized_coordinate_minimum": -1.0,
            "normalized_coordinate_maximum": 1.0,
        },
        "full_widths_mm": list(widths),
        "cross_validation": dict(cross_validation),
        "width_results": width_results,
        "model_full_width_mm": model_width,
        "checkpoint_models": models,
        "log_width_scaling": scaling,
        "exploratory_assessment": {
            "target_checkpoint": target_checkpoint,
            "thresholds": dict(thresholds),
            "global_polynomial_reconstruction": {
                "checks": reconstruction_checks,
                "cubic_or_higher_terms_required_for_declared_global_adequacy": reconstruction_supported,
                "interpretation_limit": "global_reconstruction_adequacy_does_not_set_local_taylor_starting_order",
            },
            "width_scaling": {
                "checks": width_scaling_checks,
                "approximately_cubic_width_response_supported": width_scaling_supported,
                "interpretation_limit": "effective_width_exponent_does_not_identify_a_unique_taylor_order",
            },
            "combined_affine_all_ideal_n1001_pattern_supported": (
                local_taylor_supported
                and reconstruction_supported
                and width_scaling_supported
            ),
            "specific_dominant_order_claim": "withheld_no_unique_order_identification",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = compute_width_sweep_report(arguments.campaign)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PROVISIONAL_WIDTH_SWEEP_REPORT={arguments.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
