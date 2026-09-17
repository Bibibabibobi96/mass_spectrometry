"""Refine gamma=90 roots continuously along the real-3-D mirror L0 family."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import least_squares

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_screen import (
    CombinedField,
    RealFieldL1Error,
    ResponseBasis,
    l1_probe_at_energy,
    load_response_basis_csv,
    rank_screened_members,
    screen_feasible_family,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family import (
    GROUPS,
    AxisFieldResponseBasis,
    AxisResponseBasis,
    load_axis_response_basis_csv,
    normalized_slopes,
    reduced_period_from_basis,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealFieldL1Error(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RealFieldL1Error(f"{label} must be an object")
    return value


def load_axis_basis(
    path: Path, normalization_v: float,
) -> tuple[AxisResponseBasis, AxisFieldResponseBasis]:
    try:
        return load_axis_response_basis_csv(path, normalization_v=normalization_v)
    except CandidateContractError as exc:
        raise RealFieldL1Error(str(exc)) from exc


_FIXED_GRID_DEFERRED_FAILURE_PREFIXES = (
    "gamma_probe_not_converged:",
    "tbar_probe_not_converged:",
)


def rank_fixed_grid_validation_candidates(
    full_screen: Mapping[str, Any],
    *,
    metric_tolerances: Sequence[float],
) -> dict[str, Any]:
    """Rank roots whose only unresolved gates require a finer fixed grid.

    This does not convert a failed 0.5-mm probe-convergence gate into a pass.
    It only identifies which otherwise physical root may proceed to the
    required fixed 0.25-mm native validation, where those gates remain open.
    """

    raw_members = full_screen.get("members")
    if not isinstance(raw_members, list):
        raise RealFieldL1Error("full root screen lacks its member list")
    provisional_reports = copy.deepcopy(raw_members)
    candidate_indices: list[int] = []
    deferred_failures: dict[str, list[str]] = {}
    for index, report in enumerate(provisional_reports):
        if not isinstance(report, dict):
            raise RealFieldL1Error("full root screen member is not an object")
        failures = report.get("hard_gate_failures", [])
        if not isinstance(failures, list) or not all(isinstance(item, str) for item in failures):
            raise RealFieldL1Error("full root screen member has invalid gate failures")
        eligible = report.get("status") == "screen_pass_diagnostic_only" or (
            bool(failures)
            and all(item.startswith(_FIXED_GRID_DEFERRED_FAILURE_PREFIXES) for item in failures)
        )
        if eligible:
            candidate_indices.append(index)
            deferred_failures[str(index)] = list(failures)
            report["status"] = "screen_pass_diagnostic_only"
    ranking = rank_screened_members(
        provisional_reports,
        metric_tolerances=metric_tolerances,
    )
    selected = list(ranking["selected_member_indices"])
    return {
        "status": (
            "selected_for_fixed_0p25mm_native_validation"
            if selected else "no_fixed_grid_validation_candidate"
        ),
        "qualification": "stage_handoff_only__all_deferred_gates_remain_unpassed",
        "eligible_root_indices": candidate_indices,
        "selected_root_indices": selected,
        "primary_root_index": ranking["primary_member_index"],
        "deferred_hard_gate_failures_by_root": deferred_failures,
        "ranking": ranking,
    }


def build_fixed_grid_selection_receipt(
    refinement_path: Path,
    contract_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Publish a manifest-bindable handoff without rerunning expensive roots."""

    refinement = _object(refinement_path, "continuous L1 refinement")
    contract = _object(contract_path, "MR-TOF contract")
    if (
        refinement.get("role")
        != "mrtof_real_3d_mirror_l1_continuous_family_refinement"
        or not isinstance(refinement.get("roots"), list)
        or not isinstance(refinement.get("full_root_screen"), dict)
    ):
        raise RealFieldL1Error("continuous L1 refinement cannot supply a fixed-grid handoff")
    try:
        tolerances = contract["mirror"]["theory_requirements"][
            "real_3d_l1_screen_profile"
        ]["ranking_metric_tolerances"]
    except (KeyError, TypeError) as exc:
        raise RealFieldL1Error("contract lacks fixed-grid ranking tolerances") from exc
    selection = rank_fixed_grid_validation_candidates(
        refinement["full_root_screen"],
        metric_tolerances=(
            float(tolerances["absolute_Tbar_xx_us_per_mm2"]),
            float(tolerances["minimum_stability_margin"]),
            float(tolerances["sampled_peak_field_v_per_mm"]),
            float(tolerances["maximum_absolute_mirror_voltage_v"]),
        ),
    )
    selected_roots = []
    for index in selection["selected_root_indices"]:
        root = refinement["roots"][index]
        screen = refinement["full_root_screen"]["members"][index]
        selected_roots.append({
            "root_index": int(index),
            "mirror_voltages_v": list(root["mirror_voltages_v"]),
            "normalized_period_slopes_per_v": list(root["normalized_period_slopes_per_v"]),
            "gamma_root": root["gamma_root"],
            "coarse_screen_selection_metrics": screen["selection_metrics"],
            "deferred_hard_gate_failures": list(screen["hard_gate_failures"]),
        })
    receipt = {
        "schema_version": 1,
        "role": "mrtof_real_3d_mirror_fixed_grid_validation_selection",
        "status": selection["status"],
        "qualification": selection["qualification"],
        "source_refinement_sha256": file_sha256(refinement_path),
        "source_contract_sha256": file_sha256(contract_path),
        "selection": selection,
        "selected_roots": selected_roots,
        "limitations": [
            "Deferred 0.5-mm probe-convergence failures remain unpassed.",
            "This receipt authorizes only fixed 0.25-mm native validation, not a Candidate operating point.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def _fixed_e_l0_solution(
    axis_basis: AxisFieldResponseBasis,
    *,
    e_voltage_v: float,
    start_bcd_v: Sequence[float],
    energies_v: Sequence[float],
    derivative_step_v: float,
    bounds: Mapping[str, Sequence[float]],
    slope_gate_per_v: float,
    jacobian_relative_step: float,
    least_squares_relative_tolerance: float,
    maximum_function_evaluations: int,
) -> dict[str, Any]:
    lower = np.asarray([float(bounds[group][0]) for group in GROUPS[:3]])
    upper = np.asarray([float(bounds[group][1]) for group in GROUPS[:3]])

    def residual(values: np.ndarray) -> np.ndarray:
        try:
            return 1.0e7 * np.asarray(normalized_slopes(
                axis_basis, (*values, e_voltage_v), energies_v, derivative_step_v,
            ))
        except CandidateContractError:
            return np.full(3, 1.0e6)

    solution = least_squares(
        residual, np.clip(np.asarray(start_bcd_v, dtype=float), lower, upper),
        bounds=(lower, upper), x_scale=np.maximum(upper - lower, 1.0),
        jac="3-point", diff_step=jacobian_relative_step,
        ftol=least_squares_relative_tolerance,
        xtol=least_squares_relative_tolerance,
        gtol=least_squares_relative_tolerance,
        max_nfev=maximum_function_evaluations,
    )
    voltages = [*map(float, solution.x), float(e_voltage_v)]
    slopes = normalized_slopes(axis_basis, voltages, energies_v, derivative_step_v)
    periods_and_turns = [
        reduced_period_from_basis(axis_basis, energy, voltages) for energy in energies_v
    ]
    feasible = bool(solution.success and max(abs(value) for value in slopes) <= slope_gate_per_v)
    return {
        "mirror_voltages_v": [0.0, *voltages],
        "normalized_period_slopes_per_v": list(slopes),
        "reduced_periods_mm_per_sqrt_v": [item[0] for item in periods_and_turns],
        "turning_points_mm": [list(item[1]) for item in periods_and_turns],
        "optimizer_success": bool(solution.success),
        "optimizer_message": str(solution.message),
        "function_evaluations": int(solution.nfev),
        "l0_feasible": feasible,
    }


def _gamma_sample(
    response_basis: ResponseBasis,
    voltages: Sequence[float],
    *,
    nominal_energy_v: float,
    position_probe_mm: float,
    angle_probe_rad: float,
    largest_scale: float,
    trace_controls: Mapping[str, float],
) -> dict[str, Any]:
    field = CombinedField(response_basis, tuple(float(value) for value in voltages[1:]))
    records = [
        l1_probe_at_energy(
            field, energy_per_charge_v=nominal_energy_v, launch_direction=direction,
            position_probe_mm=position_probe_mm * largest_scale,
            angle_probe_rad=angle_probe_rad * largest_scale,
            trace_controls=trace_controls,
        )
        for direction in (-1, 1)
    ]
    if any(not record["stable"] or record["gamma_degrees"] is None for record in records):
        raise RealFieldL1Error("continuous gamma trial left the stable transverse branch")
    trace_halves = [float(record["trace_half"]) for record in records]
    return {
        "objective_mean_trace_half": sum(trace_halves) / len(trace_halves),
        "directional_trace_half": trace_halves,
        "directional_gamma_degrees": [float(record["gamma_degrees"]) for record in records],
        "directional_stability_margin": [float(record["stability_margin"]) for record in records],
    }


def _endpoint_job(payload: tuple[Any, ...]) -> dict[str, Any]:
    (
        source_index, source_member, response_basis, energies, position_probe,
        angle_probe, largest_scale, trace_controls,
    ) = payload
    member = dict(source_member)
    member["source_index"] = int(source_index)
    if not member["l0_feasible"]:
        member["field_consistent_endpoint_status"] = "l0_not_feasible"
        return member
    try:
        gamma = _gamma_sample(
            response_basis,
            member["mirror_voltages_v"],
            nominal_energy_v=energies[1],
            position_probe_mm=position_probe,
            angle_probe_rad=angle_probe,
            largest_scale=largest_scale,
            trace_controls=trace_controls,
        )
    except RealFieldL1Error as exc:
        member["field_consistent_endpoint_status"] = "gamma_preflight_failed"
        member["gamma_preflight_error"] = str(exc)
        return member
    member["field_consistent_endpoint_status"] = "stable_gamma_preflight_complete"
    member["gamma_objective"] = float(gamma["objective_mean_trace_half"])
    member["gamma_preflight"] = gamma
    return member


def _root_job(payload: tuple[Any, ...]) -> dict[str, Any]:
    (
        bracket, axis_basis, response_basis, energies, derivative_step, bounds, slope_gate,
        jacobian_step, solver_tolerance, maximum_evaluations, position_probe, angle_probe, largest_scale,
        trace_controls, trace_tolerance, e_voltage_tolerance, maximum_iterations,
        checkpoint_path, checkpoint_identity,
    ) = payload
    left, right = bracket
    left_e = float(left["mirror_voltages_v"][-1])
    right_e = float(right["mirror_voltages_v"][-1])
    source_bracket_member_indices = [
        int(left["source_index"]), int(right["source_index"]),
    ]
    left_value = float(left["gamma_objective"])
    right_value = float(right["gamma_objective"])
    if not left_e < right_e or left_value * right_value >= 0.0:
        raise RealFieldL1Error("gamma root bracket is invalid")
    history = []
    best_member = None
    best_gamma = None
    best_abs_value = math.inf
    previous_updated_side = None
    consecutive_same_side_updates = 0
    for iteration in range(maximum_iterations):
        trial_e = (left_e * right_value - right_e * left_value) / (right_value - left_value)
        if (
            not left_e < trial_e < right_e
            or consecutive_same_side_updates >= 2
        ):
            trial_e = 0.5 * (left_e + right_e)
        fraction = (trial_e - left_e) / (right_e - left_e)
        start = [
            (1.0 - fraction) * float(left["mirror_voltages_v"][index])
            + fraction * float(right["mirror_voltages_v"][index])
            for index in range(1, 4)
        ]
        member = _fixed_e_l0_solution(
            axis_basis, e_voltage_v=trial_e, start_bcd_v=start,
            energies_v=energies, derivative_step_v=derivative_step,
            bounds=bounds, slope_gate_per_v=slope_gate,
            jacobian_relative_step=jacobian_step,
            least_squares_relative_tolerance=solver_tolerance,
            maximum_function_evaluations=maximum_evaluations,
        )
        if not member["l0_feasible"]:
            raise RealFieldL1Error("gamma continuation trial left the L0 family")
        gamma = _gamma_sample(
            response_basis, member["mirror_voltages_v"], nominal_energy_v=energies[1],
            position_probe_mm=position_probe, angle_probe_rad=angle_probe,
            largest_scale=largest_scale, trace_controls=trace_controls,
        )
        value = float(gamma["objective_mean_trace_half"])
        history.append({
            "iteration": iteration,
            "mirror_E_v": trial_e,
            "objective_mean_trace_half": value,
            "directional_gamma_degrees": gamma["directional_gamma_degrees"],
            "maximum_abs_l0_slope_per_v": max(
                abs(float(item)) for item in member["normalized_period_slopes_per_v"]
            ),
        })
        if abs(value) < best_abs_value:
            best_abs_value = abs(value)
            best_member, best_gamma = member, gamma
        converged = abs(value) <= trace_tolerance
        if left_value * value < 0.0:
            right_e, right_value, right = trial_e, value, member
            updated_side = "right"
        else:
            left_e, left_value, left = trial_e, value, member
            updated_side = "left"
        if updated_side == previous_updated_side:
            consecutive_same_side_updates += 1
        else:
            previous_updated_side = updated_side
            consecutive_same_side_updates = 1
        checkpoint = {
            "schema_version": 1,
            "role": "mrtof_real_3d_mirror_l1_gamma_root_checkpoint",
            "status": "converged" if converged else "in_progress",
            "input_identity": checkpoint_identity,
            "source_bracket_member_indices": source_bracket_member_indices,
            "iteration": iteration,
            "left_mirror_E_v": left_e,
            "left_objective_mean_trace_half": left_value,
            "right_mirror_E_v": right_e,
            "right_objective_mean_trace_half": right_value,
            "best_abs_objective_mean_trace_half": best_abs_value,
            "best_member": best_member,
            "best_gamma_root": best_gamma,
            "root_history": history,
        }
        destination = Path(checkpoint_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(checkpoint, indent=2, allow_nan=False) + "\n")
        os.replace(temporary, destination)
        if converged or right_e - left_e <= e_voltage_tolerance:
            break
    if best_member is None or best_gamma is None:
        raise RealFieldL1Error("gamma root refinement produced no trial")
    converged = abs(float(best_gamma["objective_mean_trace_half"])) <= trace_tolerance
    return {
        "status": "coarse_gamma_root_found" if converged else "coarse_gamma_root_not_converged",
        "l0_feasible": bool(best_member["l0_feasible"] and converged),
        "mirror_voltages_v": best_member["mirror_voltages_v"],
        "normalized_period_slopes_per_v": best_member["normalized_period_slopes_per_v"],
        "reduced_periods_mm_per_sqrt_v": best_member["reduced_periods_mm_per_sqrt_v"],
        "turning_points_mm": best_member["turning_points_mm"],
        "gamma_root": best_gamma,
        "root_history": history,
        "source_bracket_member_indices": source_bracket_member_indices,
        "terminal_e_voltage_bracket_width_v": right_e - left_e,
    }


def refine_roots(
    *, family_path: Path, discrete_screen_path: Path, axis_basis_path: Path,
    response_basis_path: Path, sampling_plan_path: Path, contract_path: Path,
    output_path: Path, checkpoint_directory: Path | None = None,
) -> dict[str, Any]:
    family = _object(family_path, "L0 family")
    screen = _object(discrete_screen_path, "discrete L1 screen")
    plan = _object(sampling_plan_path, "L1 sampling plan")
    contract = _object(contract_path, "MR-TOF contract")
    normalization = float(plan["basis_normalization_v"])
    sampled_potential_axis, sampled_field_axis = load_axis_basis(
        axis_basis_path, normalization,
    )
    response_basis = load_response_basis_csv(
        response_basis_path, normalization_v=normalization,
        probe_y_mm=float(plan["slice_y_mm"]),
    )
    requirements = contract["mirror"]["theory_requirements"]
    l1 = requirements["l1_screen_profile"]
    real = requirements["real_3d_l1_screen_profile"]
    trajectory = contract["simion"]["trajectory_profiles"][real["screen_trajectory_profile_id"]]
    species = contract["particle_source"]["species"]
    authority_source = (
        "mirror.theory_requirements.real_3d_l0_voltage_family_profile.axis_period_authority"
    )
    if (
        real["axis_period_authority_source"] != authority_source
        or family.get("axis_period_authority") != "integrated_piecewise_linear_sampled_Ez"
        or int(family.get("axis_basis_schema_version", 0)) != 2
    ):
        raise RealFieldL1Error("real-field L0/L1 axis propagation authority is unsupported")
    zero_x_indices = np.flatnonzero(response_basis.x_mm == 0.0)
    if len(zero_x_indices) != 1 or not np.array_equal(
        sampled_potential_axis.z_mm, response_basis.z_mm,
    ):
        raise RealFieldL1Error("axis and transverse response grids do not share x=0,z nodes")
    zero_x_index = int(zero_x_indices[0])
    maximum_node_mismatch = float(np.max(np.abs(
        sampled_potential_axis.response_v - response_basis.potential_v[zero_x_index]
    )))
    if maximum_node_mismatch > float(real["maximum_axis_potential_node_mismatch_v"]):
        raise RealFieldL1Error("axis and transverse response potentials differ at native nodes")
    maximum_ez_node_mismatch = float(np.max(np.abs(
        sampled_field_axis.ez_response_v_per_mm
        - response_basis.field_v_per_mm[zero_x_index, :, :, 2]
    )))
    if maximum_ez_node_mismatch > float(real["maximum_axis_field_node_mismatch_v_per_mm"]):
        raise RealFieldL1Error("axis and transverse Ez responses differ at native nodes")
    axis_basis = sampled_field_axis
    energies = tuple(float(value) for value in family["energy_centers_ev"])
    trace_controls = {
        "particle_mass_th": float(species["mass_th"]),
        "particle_charge_e": float(species["charge_e"]),
        "relative_tolerance": float(real["surrogate_relative_tolerance"]),
        "absolute_tolerance": float(real["surrogate_absolute_tolerance"]),
        "maximum_step_us": float(trajectory["maximum_step_us"]),
        "maximum_leg_time_us": float(real["maximum_leg_time_us"]),
        "central_plane_offset_mm": float(real["central_plane_offset_mm"]),
    }
    if (
        not isinstance(screen.get("members"), list)
        or screen.get("inputs", {}).get("l0_family_sha256") != file_sha256(family_path)
    ):
        raise RealFieldL1Error("discrete L1 screen members are missing")
    feasible_indices = [
        index for index, member in enumerate(family["members"]) if member.get("l0_feasible") is True
    ]
    numerics = family["numerics"]
    endpoint_payloads = [(
        index, family["members"][index], response_basis, energies,
        float(l1["position_probe_mm"]), float(l1["angle_probe_rad"]),
        max(float(value) for value in l1["probe_convergence_scale_factors"]), trace_controls,
    ) for index in feasible_indices]
    with ProcessPoolExecutor(
        max_workers=min(len(endpoint_payloads), int(l1["maximum_parallel_workers"])),
    ) as executor:
        reprojected_endpoints = list(executor.map(_endpoint_job, endpoint_payloads))
    endpoints = [
        member for member in reprojected_endpoints
        if member.get("field_consistent_endpoint_status") == "stable_gamma_preflight_complete"
    ]
    endpoints.sort(key=lambda item: float(item["mirror_voltages_v"][-1]))
    brackets = [
        (left, right) for left, right in zip(endpoints, endpoints[1:], strict=False)
        if float(left["gamma_objective"]) * float(right["gamma_objective"]) < 0.0
    ]
    if not brackets:
        raise RealFieldL1Error("field-consistent real-field family contains no stable gamma root bracket")
    target_gamma_tolerance = float(l1["maximum_gamma_target_residual_degrees"])
    trace_tolerance = math.sin(math.radians(target_gamma_tolerance))
    input_identity = {
        "family_sha256": file_sha256(family_path),
        "discrete_screen_sha256": file_sha256(discrete_screen_path),
        "axis_basis_sha256": file_sha256(axis_basis_path),
        "response_basis_sha256": file_sha256(response_basis_path),
        "sampling_plan_sha256": file_sha256(sampling_plan_path),
        "contract_sha256": file_sha256(contract_path),
    }
    checkpoint_root = checkpoint_directory or output_path.parent
    payloads = [(
        bracket, axis_basis, response_basis, energies,
        float(family["period_slope_derivative_step_ev"]), family["voltage_bounds_v"],
        float(family["maximum_abs_normalized_period_slope_per_v"]),
        float(numerics["voltage_jacobian_relative_step"]),
        float(numerics["least_squares_relative_tolerance"]),
        int(numerics["maximum_function_evaluations_per_e_slice"]),
        float(l1["position_probe_mm"]), float(l1["angle_probe_rad"]),
        max(float(value) for value in l1["probe_convergence_scale_factors"]),
        trace_controls, trace_tolerance, float(l1["e_voltage_root_tolerance_v"]),
        int(l1["maximum_root_iterations"]),
        checkpoint_root / (
            f"root_{int(bracket[0]['source_index'])}_{int(bracket[1]['source_index'])}.checkpoint.json"
        ),
        input_identity,
    ) for bracket in brackets]
    with ProcessPoolExecutor(max_workers=min(len(payloads), os.cpu_count() or 1)) as executor:
        roots = list(executor.map(_root_job, payloads))
    root_family = {
        "role": "mrtof_real_3d_mirror_l0_voltage_family",
        "feasible_member_count": sum(item["l0_feasible"] for item in roots),
        "members": roots,
    }
    tolerances = real["ranking_metric_tolerances"]
    full_screen = screen_feasible_family(
        root_family, response_basis,
        evaluation_arguments={
            "energy_points_v": energies,
            "period_slope_derivative_step_v": float(family["period_slope_derivative_step_ev"]),
            "probe_scale_factors": tuple(float(value) for value in l1["probe_convergence_scale_factors"]),
            "position_probe_mm": float(l1["position_probe_mm"]),
            "angle_probe_rad": float(l1["angle_probe_rad"]),
            "trace_controls": trace_controls,
            "target_gamma_degrees": float(l1["target_gamma_degrees"]),
            "maximum_gamma_target_residual_degrees": target_gamma_tolerance,
            "maximum_adjacent_gamma_change_degrees": float(l1["maximum_adjacent_gamma_change_degrees"]),
            "maximum_adjacent_relative_tbar_change": float(l1["maximum_adjacent_relative_Tbar_change"]),
            "tbar_relative_change_absolute_floor_us_per_mm2": float(
                real["tbar_relative_change_absolute_floor_us_per_mm2"]
            ),
            "minimum_stability_margin": float(real["minimum_stability_margin"]),
            "maximum_abs_normalized_period_slope_per_v": float(
                family["maximum_abs_normalized_period_slope_per_v"]
            ),
            "gamma_target_is_acceptance_gate": True,
        },
        ranking_metric_tolerances=(
            float(tolerances["absolute_Tbar_xx_us_per_mm2"]),
            float(tolerances["minimum_stability_margin"]),
            float(tolerances["sampled_peak_field_v_per_mm"]),
            float(tolerances["maximum_absolute_mirror_voltage_v"]),
        ),
        maximum_parallel_workers=min(len(roots), int(l1["maximum_parallel_workers"])),
    )
    metric_tolerances = (
        float(tolerances["absolute_Tbar_xx_us_per_mm2"]),
        float(tolerances["minimum_stability_margin"]),
        float(tolerances["sampled_peak_field_v_per_mm"]),
        float(tolerances["maximum_absolute_mirror_voltage_v"]),
    )
    fixed_grid_candidates = rank_fixed_grid_validation_candidates(
        full_screen,
        metric_tolerances=metric_tolerances,
    )
    result = {
        "schema_version": 1,
        "role": "mrtof_real_3d_mirror_l1_continuous_family_refinement",
        "status": "coarse_0p5mm_roots_screened__fixed_candidate_0p25mm_validation_pending",
        "qualification": "coarse_family_selection_only__not_native_simion_or_candidate_qualification",
        "gamma_root_coordinate": "mean directional trace_half = 0 at nominal energy",
        "axis_period_authority": family["axis_period_authority"],
        "maximum_axis_potential_node_mismatch_v": maximum_node_mismatch,
        "maximum_axis_field_node_mismatch_v_per_mm": maximum_ez_node_mismatch,
        "directional_gamma_acceptance_gate_degrees": target_gamma_tolerance,
        "adjacent_scale_gamma_convergence_gate_degrees": float(
            l1["maximum_adjacent_gamma_change_degrees"]
        ),
        "trace_half_root_tolerance": trace_tolerance,
        "bracket_count": len(brackets),
        "field_consistent_endpoints": reprojected_endpoints,
        "roots": roots,
        "full_root_screen": full_screen,
        "fixed_0p25mm_validation_candidates": fixed_grid_candidates,
        "inputs": input_identity,
    }
    output_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments and arguments[0] == "select-fixed-grid":
        parser = argparse.ArgumentParser()
        parser.add_argument("select-fixed-grid")
        parser.add_argument("--refinement", type=Path, required=True)
        parser.add_argument("--contract", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args(arguments)
        result = build_fixed_grid_selection_receipt(
            args.refinement, args.contract, args.output,
        )
        print(f"MRTOF_REAL_FIELD_L1_FIXED_GRID_SELECTION={result['status']}")
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", type=Path, required=True)
    parser.add_argument("--discrete-screen", type=Path, required=True)
    parser.add_argument("--axis-basis", type=Path, required=True)
    parser.add_argument("--response-basis", type=Path, required=True)
    parser.add_argument("--sampling-plan", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-directory", type=Path)
    args = parser.parse_args(arguments)
    result = refine_roots(
        family_path=args.family, discrete_screen_path=args.discrete_screen,
        axis_basis_path=args.axis_basis, response_basis_path=args.response_basis,
        sampling_plan_path=args.sampling_plan, contract_path=args.contract,
        output_path=args.output, checkpoint_directory=args.checkpoint_directory,
    )
    print(
        "MRTOF_REAL_FIELD_MIRROR_L1_CONTINUOUS="
        f"{result['status']} ROOTS={len(result['roots'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
