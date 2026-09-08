"""Select an exact-K operating energy on a mirror-theory-qualified branch.

The fixed manufactured mirror has four non-ground voltage coordinates and
three axial L0 equations.  L1 gamma selects one member at each trial energy.
This module then varies only the accelerator net-gain centre within its
declared range and applies ``T_D(theta_0)/T_0=K`` as a system-level selector.
Stripe voltages never participate in the mirror solve.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import brentq, least_squares

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    endpoint_regularized_kappa,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_operating_seed import (
    solve_dimensionless_paper_target,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    classify_constraint_system,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_candidate_receipt import (
    ManagedMirrorRoot,
    load_managed_mirror_candidate,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    derive_mirror_l0_slope_tolerance_per_v,
    effective_axial_width_mm,
    reduced_period,
    three_point_report,
    three_point_normalized_period_slopes_per_v,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l1 import (
    map_at_energy,
    refine_l0_gamma_intersection,
    screen_l1_fixed_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_mirror_voltage_bounds,
    derive_operating_energy_envelope,
    load_contract,
)


@dataclass(frozen=True)
class ExactKPoint:
    """One gamma-qualified mirror point evaluated at a selected energy."""

    branch_index: int
    energy_per_charge_v: float
    mirror_voltages_v: tuple[float, ...]
    mirror_reduced_period_mm_per_sqrt_v: float
    mirror_axial_width_w_mm: float
    calculated_td_over_t0: float
    exact_k_residual: float
    gamma_degrees: float
    gamma_residual_degrees: float
    normalized_period_slopes_per_v: tuple[float, ...]


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be numeric") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CandidateContractError(f"{label} must be a positive integer")
    return value


def _paper_kappa(contract: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    target = solve_dimensionless_paper_target(contract)
    selected = target["selected_root"]
    coefficients = tuple(
        _finite(value, "paper psi coefficient")
        for value in selected["psi_coefficients_by_power"]
    )

    def psi(eta: float) -> float:
        return sum(value * eta**power for power, value in enumerate(coefficients, start=1))

    return endpoint_regularized_kappa(psi), target


def _drift_inputs(contract: dict[str, Any]) -> tuple[float, float, int]:
    length = _finite(
        contract["dual_stripe_l0"]["manufactured_design_abs_drift_length_L_mm"],
        "manufactured drift length L",
    )
    partition = contract["prism_transport"]["energy_partition"]
    drift_energy = _finite(partition["drift_kinetic_energy_ev"], "drift kinetic energy")
    target_k = _positive_integer(contract["nominal"]["target_oscillation_count"], "target K")
    if length <= 0.0 or drift_energy <= 0.0:
        raise CandidateContractError("exact-K drift inputs must be positive")
    return length, drift_energy, target_k


def _td_over_t0(
    energy_per_charge_v: float,
    width_mm: float,
    kappa_1: float,
    length_mm: float,
    drift_energy_per_charge_v: float,
) -> float:
    total_energy = energy_per_charge_v + drift_energy_per_charge_v
    sin_theta = math.sqrt(drift_energy_per_charge_v / total_energy)
    return kappa_1 * length_mm / (width_mm * sin_theta)


def _slope_tolerance(contract: dict[str, Any], energies: tuple[float, float, float]) -> float:
    budget = contract["mirror"]["theory_requirements"]["l0_acceptance_budget"]
    return derive_mirror_l0_slope_tolerance_per_v(
        _finite(budget["minimum_mass_resolution"], "minimum mass resolution"),
        _finite(budget["mirror_time_width_fraction"], "mirror time-width fraction"),
        energies,
    )


def _joint_refine_exact_k(
    contract: dict[str, Any],
    seed: ManagedMirrorRoot,
    approximate: ExactKPoint,
    kappa_1: float,
) -> tuple[ExactKPoint, dict[str, object]]:
    """Close the three L0, gamma, and exact-K equations in one solve."""
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    global_profile = contract["mirror"]["theory_requirements"]["global_l0_search_profile"]
    selector = contract["mirror"]["theory_requirements"]["exact_k_operating_point_selection"]
    reference_envelope = derive_operating_energy_envelope(contract)
    target_gamma = _finite(profile["target_gamma_degrees"], "target gamma")
    gamma_tolerance = _finite(
        profile["maximum_gamma_target_residual_degrees"], "gamma tolerance"
    )
    k_tolerance = _finite(
        selector["maximum_abs_numerical_k_residual"], "K residual tolerance"
    )
    derivative_step = _finite(
        global_profile["period_slope_derivative_step_v"], "period slope derivative step"
    )
    length, drift_energy, target_k = _drift_inputs(contract)

    def evaluate(parameters: np.ndarray) -> tuple[
        MirrorL0Design, tuple[float, float, float], tuple[float, ...], float, float, float,
    ]:
        voltages = tuple(float(value) for value in parameters[:4])
        selected_energy = float(parameters[4])
        local_energy = derive_operating_energy_envelope(
            contract, selected_center_v=selected_energy,
        )
        design = MirrorL0Design(
            seed.design.transverse_half_gap_mm,
            seed.design.transition_z_mm,
            (0.0, *voltages),
            seed.design.terminal_electrode_plane_z_mm,
            voltages[-1],
        )
        slopes = three_point_normalized_period_slopes_per_v(
            design, local_energy.mirror_energy_nodes_v, derivative_step,
        )
        mapping = map_at_energy(
            selected_energy,
            design,
            _finite(profile["position_probe_mm"], "position probe"),
            _finite(profile["angle_probe_rad"], "angle probe"),
        )
        if not mapping.stable or mapping.gamma_degrees is None:
            raise CandidateContractError("joint exact-K solve encountered an unstable mirror map")
        reduced = reduced_period(selected_energy, design)
        width = effective_axial_width_mm(selected_energy, reduced)
        ratio = _td_over_t0(selected_energy, width, kappa_1, length, drift_energy)
        return design, local_energy.mirror_energy_nodes_v, slopes, mapping.gamma_degrees, width, ratio

    center = np.asarray([
        *approximate.mirror_voltages_v[1:], approximate.energy_per_charge_v,
    ])
    voltage_envelope = contract["mirror"]["theory_requirements"]["voltage_envelope_v"]
    particle_half_range = reference_envelope.particle_net_gain_half_range_v
    lower = np.asarray([
        *(_finite(voltage_envelope[key]["minimum_inclusive_v"], f"mirror {key} minimum")
          for key in ("B", "C", "D")),
        math.nextafter(
            reference_envelope.net_gain_center_minimum_v + particle_half_range, math.inf,
        ),
        reference_envelope.net_gain_center_minimum_v,
    ])
    upper = np.asarray([
        *((reference_envelope.net_gain_center_maximum_v - particle_half_range,) * 3),
        _finite(voltage_envelope["E"]["maximum_inclusive_v"], "mirror E maximum"),
        reference_envelope.net_gain_center_maximum_v,
    ])
    nominal_energy = derive_operating_energy_envelope(
        contract, selected_center_v=approximate.energy_per_charge_v,
    )
    slope_tolerance = _slope_tolerance(contract, nominal_energy.mirror_energy_nodes_v)

    def scaled_residual(parameters: np.ndarray) -> np.ndarray:
        try:
            _design, _energies, slopes, gamma, _width, ratio = evaluate(parameters)
        except CandidateContractError:
            return np.full(5, 1e9)
        return np.asarray([
            *(value / slope_tolerance for value in slopes),
            (gamma - target_gamma) / gamma_tolerance,
            (ratio - target_k) / k_tolerance,
        ])

    solution = least_squares(
        scaled_residual,
        center,
        bounds=(lower, upper),
        max_nfev=_positive_integer(
            profile["maximum_local_function_evaluations"], "joint evaluations"
        ),
        x_scale="jac",
        ftol=1e-13,
        xtol=1e-13,
        gtol=1e-13,
    )
    design, energies, slopes, gamma, width, ratio = evaluate(solution.x)
    selected_energy = float(solution.x[4])
    local_lower, local_upper = derive_mirror_voltage_bounds(
        contract, selected_center_v=selected_energy,
    )
    if any(
        not low <= value <= high
        for value, low, high in zip(
            design.electrode_voltages_v[1:], local_lower, local_upper, strict=True,
        )
    ):
        raise CandidateContractError("joint exact-K root violates its energy-dependent voltage envelope")
    gamma_residual = gamma - target_gamma
    if (
        not solution.success
        or any(abs(value) > slope_tolerance for value in slopes)
        or abs(gamma_residual) > gamma_tolerance
        or abs(ratio - target_k) > k_tolerance
    ):
        raise CandidateContractError(
            "joint exact-K solve did not close all five declared residual gates: "
            f"success={solution.success}, max_slope={max(abs(value) for value in slopes):.12g}, "
            f"gamma_residual={gamma_residual:.12g}, K_residual={ratio - target_k:.12g}"
        )
    reduced = reduced_period(selected_energy, design)
    point = ExactKPoint(
        branch_index=approximate.branch_index,
        energy_per_charge_v=selected_energy,
        mirror_voltages_v=design.electrode_voltages_v,
        mirror_reduced_period_mm_per_sqrt_v=reduced,
        mirror_axial_width_w_mm=width,
        calculated_td_over_t0=ratio,
        exact_k_residual=ratio - target_k,
        gamma_degrees=gamma,
        gamma_residual_degrees=gamma_residual,
        normalized_period_slopes_per_v=slopes,
    )
    screen = screen_l1_fixed_geometry(
        design,
        energies,
        _finite(profile["position_probe_mm"], "position probe"),
        _finite(profile["angle_probe_rad"], "angle probe"),
    )
    receipt = {
        "status": "joint_l0_gamma_exact_k_root__probe_and_3d_validation_pending",
        "target_gamma_degrees": target_gamma,
        "gamma_residual_degrees": gamma_residual,
        "optimizer": {
            "success": bool(solution.success),
            "message": str(solution.message),
            "cost": float(solution.cost),
            "function_evaluations": int(solution.nfev),
            "selection_stage": "joint three-L0 plus gamma plus exact-K solve",
        },
        "l0_receipt": {
            "status": "l0_voltage_slice_member_not_l1_or_3d_validated",
            "geometry_fixed": True,
            "transition_z_mm": list(design.transition_z_mm),
            "transverse_half_gap_mm": design.transverse_half_gap_mm,
            "terminal_electrode_plane_z_mm": design.terminal_electrode_plane_z_mm,
            "electrode_voltages_v": list(design.electrode_voltages_v),
            "three_point": three_point_report(design, energies),
            "normalized_period_slopes_per_v": list(slopes),
            "period_slope_derivative_step_v": derivative_step,
            "maximum_abs_normalized_period_slope_per_v": slope_tolerance,
            "not_evaluated": ["three_dimensional_fields", "simion_pa"],
        },
        "l1_screen": screen,
    }
    return point, receipt


def evaluate_branch_at_energy(
    contract: dict[str, Any],
    seed: ManagedMirrorRoot,
    branch_index: int,
    energy_per_charge_v: float,
    kappa_1: float,
    continuation_point: ExactKPoint | None = None,
) -> tuple[ExactKPoint, dict[str, object]]:
    """Continue one frozen gamma branch to one admissible operating energy."""
    energy = derive_operating_energy_envelope(contract, selected_center_v=energy_per_charge_v)
    energies = energy.mirror_energy_nodes_v
    lower, upper = derive_mirror_voltage_bounds(contract, selected_center_v=energy_per_charge_v)
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    if continuation_point is None:
        reference_energy = derive_operating_energy_envelope(contract).net_gain_reference_center_v
        reference_voltages = seed.design.electrode_voltages_v
    else:
        reference_energy = continuation_point.energy_per_charge_v
        reference_voltages = continuation_point.mirror_voltages_v
    scale = energy_per_charge_v / reference_energy
    scaled_voltages = (0.0, *(value * scale for value in reference_voltages[1:]))
    initial = MirrorL0Design(
        seed.design.transverse_half_gap_mm,
        seed.design.transition_z_mm,
        scaled_voltages,
        seed.design.terminal_electrode_plane_z_mm,
        scaled_voltages[-1],
    )
    refined = refine_l0_gamma_intersection(
        initial,
        lower,
        upper,
        energies,
        _finite(profile["target_gamma_degrees"], "target gamma"),
        _finite(
            contract["mirror"]["theory_requirements"]["global_l0_search_profile"]
            ["period_slope_derivative_step_v"],
            "period slope derivative step",
        ),
        _slope_tolerance(contract, energies),
        _finite(profile["position_probe_mm"], "position probe"),
        _finite(profile["angle_probe_rad"], "angle probe"),
        _finite(profile["maximum_gamma_target_residual_degrees"], "gamma tolerance"),
        _positive_integer(profile["maximum_local_function_evaluations"], "L1 evaluations"),
    )
    l0 = refined["l0_receipt"]
    reduced = _finite(l0["three_point"]["reduced_periods"][1], "mirror reduced period")
    width = effective_axial_width_mm(energy_per_charge_v, reduced)
    length, drift_energy, target_k = _drift_inputs(contract)
    ratio = _td_over_t0(energy_per_charge_v, width, kappa_1, length, drift_energy)
    point = ExactKPoint(
        branch_index=branch_index,
        energy_per_charge_v=energy_per_charge_v,
        mirror_voltages_v=tuple(_finite(value, "mirror voltage") for value in l0["electrode_voltages_v"]),
        mirror_reduced_period_mm_per_sqrt_v=reduced,
        mirror_axial_width_w_mm=width,
        calculated_td_over_t0=ratio,
        exact_k_residual=ratio - target_k,
        gamma_degrees=_finite(refined["l1_screen"]["nominal_mapping"]["gamma_degrees"], "gamma"),
        gamma_residual_degrees=_finite(refined["gamma_residual_degrees"], "gamma residual"),
        normalized_period_slopes_per_v=tuple(
            _finite(value, "normalized period slope")
            for value in l0["normalized_period_slopes_per_v"]
        ),
    )
    return point, refined


def _probe_convergence(
    contract: dict[str, Any], point: ExactKPoint, seed: ManagedMirrorRoot,
) -> dict[str, Any]:
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    energy = derive_operating_energy_envelope(
        contract, selected_center_v=point.energy_per_charge_v,
    )
    design = MirrorL0Design(
        seed.design.transverse_half_gap_mm,
        seed.design.transition_z_mm,
        point.mirror_voltages_v,
        seed.design.terminal_electrode_plane_z_mm,
        point.mirror_voltages_v[-1],
    )
    nominal_key = str(float(point.energy_per_charge_v))
    records = []
    for scale_value in profile["probe_convergence_scale_factors"]:
        scale = _finite(scale_value, "probe scale")
        screen = screen_l1_fixed_geometry(
            design,
            energy.mirror_energy_nodes_v,
            _finite(profile["position_probe_mm"], "position probe") * scale,
            _finite(profile["angle_probe_rad"], "angle probe") * scale,
        )
        records.append({
            "scale_factor": scale,
            "gamma_degrees": screen["maps_by_energy_v"][nominal_key]["gamma_degrees"],
            "Tbar_xx": screen["phase_averaged_time_aberration_by_energy_v"][nominal_key]["Tbar_xx"],
        })
    previous, last = records[-2:]
    gamma_change = abs(float(last["gamma_degrees"]) - float(previous["gamma_degrees"]))
    tbar_scale = max(abs(float(last["Tbar_xx"])), abs(float(previous["Tbar_xx"])))
    relative_tbar_change = abs(float(last["Tbar_xx"]) - float(previous["Tbar_xx"])) / tbar_scale
    passed = (
        gamma_change <= _finite(profile["maximum_adjacent_gamma_change_degrees"], "gamma convergence")
        and relative_tbar_change <= _finite(
            profile["maximum_adjacent_relative_Tbar_change"], "Tbar convergence"
        )
    )
    return {
        "status": "pass" if passed else "fail",
        "records": records,
        "last_adjacent_gamma_change_degrees": gamma_change,
        "last_adjacent_relative_Tbar_change": relative_tbar_change,
    }


def _definition_receipt(
    contract: dict[str, Any], point: ExactKPoint, seed: ManagedMirrorRoot, kappa_1: float,
) -> dict[str, Any]:
    selector = contract["mirror"]["theory_requirements"]["exact_k_operating_point_selection"]
    energy = derive_operating_energy_envelope(contract, selected_center_v=point.energy_per_charge_v)
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    global_profile = contract["mirror"]["theory_requirements"]["global_l0_search_profile"]
    target_gamma_degrees = _finite(profile["target_gamma_degrees"], "target gamma")
    length, drift_energy, target_k = _drift_inputs(contract)
    names = ("mirror_B_v", "mirror_C_v", "mirror_D_v", "mirror_E_v", "net_gain_center_v")
    residual_names = (
        "mirror_period_slope_low",
        "mirror_period_slope_center",
        "mirror_period_slope_high",
        "mirror_gamma_target_residual_degrees",
        "T_D_over_T_0_minus_target_K",
    )

    def residual(parameters: np.ndarray) -> np.ndarray:
        voltage_values = tuple(float(value) for value in parameters[:4])
        selected_energy = float(parameters[4])
        local_energy = derive_operating_energy_envelope(contract, selected_center_v=selected_energy)
        design = MirrorL0Design(
            seed.design.transverse_half_gap_mm,
            seed.design.transition_z_mm,
            (0.0, *voltage_values),
            seed.design.terminal_electrode_plane_z_mm,
            voltage_values[-1],
        )
        slopes = three_point_normalized_period_slopes_per_v(
            design,
            local_energy.mirror_energy_nodes_v,
            _finite(global_profile["period_slope_derivative_step_v"], "period derivative step"),
        )
        mapping = map_at_energy(
            selected_energy,
            design,
            _finite(profile["position_probe_mm"], "position probe"),
            _finite(profile["angle_probe_rad"], "angle probe"),
        )
        if not mapping.stable or mapping.gamma_degrees is None:
            raise CandidateContractError("definition Jacobian encountered an unstable mirror map")
        width = effective_axial_width_mm(selected_energy, reduced_period(selected_energy, design))
        ratio = _td_over_t0(selected_energy, width, kappa_1, length, drift_energy)
        return np.asarray([
            *slopes,
            mapping.gamma_degrees - target_gamma_degrees,
            ratio - target_k,
        ])

    center = np.asarray([*point.mirror_voltages_v[1:], point.energy_per_charge_v])
    steps = np.asarray([
        *([_finite(selector["finite_difference_voltage_step_v"], "voltage Jacobian step")] * 4),
        _finite(selector["finite_difference_energy_step_v"], "energy Jacobian step"),
    ])
    columns = []
    for index, step in enumerate(steps):
        upper = center.copy()
        lower = center.copy()
        upper[index] += step
        lower[index] -= step
        columns.append((residual(upper) - residual(lower)) / (2.0 * step))
    jacobian = np.column_stack(columns)
    lower_bounds, upper_bounds = derive_mirror_voltage_bounds(
        contract, selected_center_v=point.energy_per_charge_v,
    )
    parameter_scales = tuple(
        upper - lower for lower, upper in zip(lower_bounds, upper_bounds, strict=True)
    ) + (energy.net_gain_center_maximum_v - energy.net_gain_center_minimum_v,)
    slope_scale = _slope_tolerance(contract, energy.mirror_energy_nodes_v)
    residual_scales = (
        slope_scale,
        slope_scale,
        slope_scale,
        _finite(profile["maximum_gamma_target_residual_degrees"], "gamma tolerance"),
        1.0,
    )
    numerics = contract["dual_stripe_l0"]["determination_numerics"]
    center_residual = residual(center)
    classification = classify_constraint_system(
        names,
        residual_names,
        jacobian_rows=jacobian.tolist(),
        residuals=center_residual.tolist(),
        parameter_scales=parameter_scales,
        residual_scales=residual_scales,
        relative_rank_tolerance=_finite(
            numerics["relative_singular_value_rank_tolerance"], "rank tolerance"
        ),
        compatibility_tolerance=_finite(
            numerics["scaled_irreducible_residual_norm_tolerance"], "compatibility tolerance"
        ),
    )
    return {
        "unknown_names": list(names),
        "residual_names": list(residual_names),
        "raw_residuals": center_residual.tolist(),
        "parameter_scales": list(parameter_scales),
        "residual_scales": list(residual_scales),
        "finite_difference_steps": steps.tolist(),
        "jacobian_rows": jacobian.tolist(),
        "classification": asdict(classification),
    }


def solve_exact_k_operating_point(
    mirror_manifest_path: Path, contract_path: Path,
) -> dict[str, Any]:
    """Find and validate all exact-K roots on the managed gamma branches."""
    contract = load_contract(contract_path)
    managed = load_managed_mirror_candidate(mirror_manifest_path, contract_path)
    kappa_1, dimensionless_target = _paper_kappa(contract)
    envelope = derive_operating_energy_envelope(contract)
    selector = contract["mirror"]["theory_requirements"].get("exact_k_operating_point_selection")
    if not isinstance(selector, dict) or selector.get("status") != (
        "system_level_selection_over_mirror_qualified_energy_family"
    ):
        raise CandidateContractError("exact-K operating-point selection contract is incomplete")
    node_count = _positive_integer(selector["energy_bracket_node_count"], "energy bracket nodes")
    if node_count < 2:
        raise CandidateContractError("exact-K energy bracket requires at least two nodes")
    energy_nodes = np.linspace(
        envelope.net_gain_center_minimum_v,
        envelope.net_gain_center_maximum_v,
        node_count,
    )
    roots: list[dict[str, Any]] = []
    branch_audits: list[dict[str, Any]] = []
    for branch_index, seed in enumerate(managed.root_family):
        cache: dict[float, tuple[ExactKPoint, dict[str, object]]] = {}

        def evaluate(value: float) -> tuple[ExactKPoint, dict[str, object]]:
            key = float(value)
            if key not in cache:
                continuation = min(
                    (cached[0] for cached in cache.values()),
                    key=lambda point: abs(point.energy_per_charge_v - key),
                    default=None,
                )
                cache[key] = evaluate_branch_at_energy(
                    contract, seed, branch_index, key, kappa_1, continuation,
                )
            return cache[key]

        sampled = [evaluate(float(value))[0] for value in energy_nodes]
        brackets = []
        for lower, upper in zip(sampled[:-1], sampled[1:], strict=True):
            if lower.exact_k_residual == 0.0:
                brackets.append((lower.energy_per_charge_v, lower.energy_per_charge_v))
            elif lower.exact_k_residual * upper.exact_k_residual < 0.0:
                brackets.append((lower.energy_per_charge_v, upper.energy_per_charge_v))
        if sampled[-1].exact_k_residual == 0.0:
            brackets.append((sampled[-1].energy_per_charge_v, sampled[-1].energy_per_charge_v))
        branch_audits.append({
            "branch_index": branch_index,
            "source_l0_restart_index": seed.source_l0_restart_index,
            "sampled_points": [asdict(point) for point in sampled],
            "sign_change_brackets_v": [list(bracket) for bracket in brackets],
        })
        for lower, upper in brackets:
            if lower == upper:
                selected_energy = lower
            else:
                selected_energy = brentq(
                    lambda value: evaluate(value)[0].exact_k_residual,
                    lower,
                    upper,
                    xtol=_finite(selector["energy_root_absolute_tolerance_v"], "energy root tolerance"),
                    maxiter=_positive_integer(selector["maximum_root_iterations"], "energy root iterations"),
                )
            approximate, _nested_refined = evaluate(selected_energy)
            point, refined = _joint_refine_exact_k(
                contract, seed, approximate, kappa_1,
            )
            k_residual_tolerance = _finite(
                selector["maximum_abs_numerical_k_residual"], "K residual tolerance"
            )
            if abs(point.exact_k_residual) > k_residual_tolerance:
                raise CandidateContractError(
                    "exact-K root residual "
                    f"{point.exact_k_residual:.12g} exceeds tolerance {k_residual_tolerance:.12g}"
                )
            convergence = _probe_convergence(contract, point, seed)
            definition = _definition_receipt(contract, point, seed, kappa_1)
            roots.append({
                "point": asdict(point),
                "probe_convergence": convergence,
                "definition": definition,
                "refined_mirror_receipt": refined,
            })
    if not roots:
        raise CandidateContractError("no managed mirror branch brackets the target integer K")
    roots.sort(key=lambda item: (
        abs(float(item["point"]["energy_per_charge_v"]) - envelope.net_gain_reference_center_v),
        max(abs(float(value)) for value in item["point"]["mirror_voltages_v"]),
    ))
    selected = roots[0]
    if selected["probe_convergence"]["status"] != "pass":
        raise CandidateContractError("selected exact-K root failed the declared L1 probe convergence")
    if selected["definition"]["classification"]["status"] != "square_exact":
        raise CandidateContractError("selected exact-K system is not locally square and full rank")
    point = selected["point"]
    mass_th = _finite(contract["particle_source"]["species"]["mass_th"], "ion mass")
    energy_j = float(point["energy_per_charge_v"]) * 1.602176634e-19
    mass_kg = mass_th * 1.66053906660e-27
    period_us = (
        float(point["mirror_axial_width_w_mm"]) * 1.0e-3
        * math.sqrt(2.0 * mass_kg / energy_j) * 1.0e6
    )
    return {
        "schema_version": 1,
        "role": "mrtof_exact_k_mirror_energy_operating_point",
        "status": "exact_k_system_point_found__peak_field_and_3d_validation_pending",
        "qualification": "solver_neutral_2d_system_selection__not_simion_voltage_authority",
        "input": {
            "mirror_manifest": {
                "path": str(mirror_manifest_path.resolve()),
                "sha256": file_sha256(mirror_manifest_path),
                "run_id": managed.run_id,
            },
            "contract": {"path": str(contract_path.resolve()), "sha256": file_sha256(contract_path)},
        },
        "governing_equation": "T_D(theta_0)/T_0=K",
        "paper_dimensionless_target": dimensionless_target,
        "nominal_kappa_1": kappa_1,
        "energy_search_interval_per_charge_v": [
            envelope.net_gain_center_minimum_v,
            envelope.net_gain_center_maximum_v,
        ],
        "branch_audits": branch_audits,
        "root_count": len(roots),
        "roots": roots,
        "selected_root_index": 0,
        "selected_operating_point": {
            **point,
            "mirror_full_two_mirror_period_T0_us_for_declared_mass": period_us,
            "post_acceleration_total_energy_ev": (
                float(point["energy_per_charge_v"]) + _drift_inputs(contract)[1]
            ),
        },
        "limitations": [
            "The exact-K equation selects among independently mirror-qualified energy points; it is not an extra axial mirror equation.",
            "This is an ideal two-dimensional analytic result. Peak field, finite slots and covers, PA fields, P1/P2 transport, and SIMION flight remain pending.",
            "No baseline voltage or solver file is modified by this receipt.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-manifest", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = solve_exact_k_operating_point(arguments.mirror_manifest, arguments.contract)
    except (CandidateContractError, KeyError, TypeError, ValueError) as error:
        print(f"MRTOF_EXACT_K_OPERATING_POINT=FAIL ERROR={error}")
        return 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    point = result["selected_operating_point"]
    print(
        "MRTOF_EXACT_K_OPERATING_POINT=PASS "
        f"ENERGY_V={point['energy_per_charge_v']:.12g} "
        f"K_RESIDUAL={point['exact_k_residual']:.12g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
