"""Derive an instance-specific two-Stripe seed with the paper's theory.

The two seed equations are the nominal oscillation count and spatial-return
condition.  A polynomial/linear fit is used only to find starting roots; every
published number is re-evaluated and Newton-refined against the native frozen
B-spline geometry.  Energy and time-platform residuals remain reported raw and
therefore this module cannot publish a complete downstream operating point.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from scipy.optimize import least_squares

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    analyze_dual_stripe_l0,
    identify_fixed_cad_component_shapes,
    paper_dimensionless_condition_residuals,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    JointL0Trial,
    StripeHardBoundary,
    coupled_normalized_period_slope_at_energy,
    coupled_reduced_period_mm_per_sqrt_v,
    derive_coupled_drift_state,
    derive_turning_y_from_entry_direction,
    evaluate_joint_l0_trial,
    finite_difference_joint_jacobian,
    fit_dimensionless_psi_g_profiles,
    spatial_return_kappa_derivative_residual,
    time_platform_derivative_residuals,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_candidate_receipt import (
    ManagedMirrorCandidate,
    load_managed_mirror_candidate,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    derive_mirror_l0_slope_tolerance_per_v,
    reduced_period,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_path_length_evaluator,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    audit_two_prism_voltage_definition,
)


WidthFunction = Callable[[float], float]

_PUBLISHABLE_DETERMINATION_STATES = {"square_exact", "overdetermined_consistent"}
_PROJECT_ID = "parallel_mirror_dual_stripe_mr_tof"
_OPERATING_SEED_MODE = "dual_stripe_paper_theory_instance_seed"


def audit_exact_paper_component_emulation_by_static_stripes(
    dimensionless_target: dict[str, Any],
) -> dict[str, Any]:
    """Test exact emulation of the paper's original two component responses.

    The paper target decomposes ``psi=p_s+p_m`` and ``g=p_s-p_m``.  If the
    fixed hardware roles are exactly one high-order component and one linear
    component, their required response ratios are therefore +1 and -1.  A
    transmitted hard-boundary electrostatic Stripe instead has
    ``h=sqrt(w0/(w0-v)) > 0``.  This is an algebraic realizability check, not a
    bounded optimizer result.  It is deliberately *not* a realizability test
    for the active fixed curves against the governing integral conditions:
    those curves generate their own ``psi`` and ``g`` and must be classified
    by the complete residual Jacobian instead.
    """
    selected = dimensionless_target.get("selected_root")
    if not isinstance(selected, dict):
        raise CandidateContractError("dimensionless target lacks its selected root")
    try:
        coefficients = tuple(float(value) for value in selected["coefficients_c0_to_c5"])
        psi = tuple(float(value) for value in selected["psi_coefficients_by_power"])
        g = tuple(float(value) for value in selected["g_coefficients_by_power"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("dimensionless target coefficients are incomplete") from error
    if len(coefficients) != 6 or len(psi) != 5 or len(g) != 5:
        raise CandidateContractError("dimensionless paper target must retain c0..c5 and powers one through five")
    scale = max(1.0, *(abs(value) for value in coefficients + psi + g))
    tolerance = 64.0 * np.finfo(float).eps * scale
    expected_psi = (coefficients[0] + coefficients[1], *coefficients[2:])
    expected_g = (coefficients[1] - coefficients[0], *coefficients[2:])
    if max(abs(left - right) for left, right in zip(psi, expected_psi)) > tolerance:
        raise CandidateContractError("paper target psi coefficients violate the declared component decomposition")
    if max(abs(left - right) for left, right in zip(g, expected_g)) > tolerance:
        raise CandidateContractError("paper target g coefficients violate the declared component decomposition")
    if abs(coefficients[0]) <= tolerance or max(abs(value) for value in coefficients[2:]) <= tolerance:
        raise CandidateContractError("paper target must retain nonzero linear and high-order components")
    return {
        "status": "not_equivalent_to_exact_original_paper_component_decomposition",
        "scope": "reference_component_emulation_only__not_active_fixed_hardware_realizability",
        "optimizer_independent": True,
        "gates_active_fixed_hardware_operating_state": False,
        "static_stripe_response_relation": "g_i=h_i*p_i; h_i=sqrt(w0/(w0-v_i))>0 for w0-v_i>0",
        "paper_target_component_relations": ["psi=p_s+p_m", "g=p_s-p_m"],
        "required_response_factors": {"set_1_high_order_h": 1.0, "set_2_linear_h": -1.0},
        "contradictions": [
            "set_2 requires h=-1 but every transmitted static electrostatic Stripe has h>0",
            "set_1 requires h=1, which implies v=0 and therefore zero finite-width hard-boundary action perturbation",
        ],
        "resolution_options": [
            "redesign both fixed curves from the exact dual-Stripe inverse for a chosen positive distinct h1,h2",
            "retain the paper high-order-plus-linear shapes but restore a non-static or geometric source of the negative linear time response",
            "define and qualify a new achievable psi/g target rather than claiming the original paper target",
        ],
    }


def _fixed_geometry_drift_length_bound(contract: dict[str, Any]) -> dict[str, Any]:
    """Derive the largest admissible nominal ``|L|`` from the active span."""
    stripe_l0 = contract.get("dual_stripe_l0")
    dual_stripe = contract.get("dual_stripe")
    if not isinstance(stripe_l0, dict) or not isinstance(dual_stripe, dict):
        raise CandidateContractError("Stripe contract blocks are incomplete")
    entry = _finite(
        stripe_l0.get("theory_stripe_entrance", {}).get("project_y_mm"),
        "Stripe entry y",
    )
    y_span = tuple(
        _finite(value, "Stripe active span")
        for value in dual_stripe.get("theory_profile", {}).get("active_y_span_mm", [])
    )
    nodes = tuple(
        _finite(value, "time-platform node")
        for value in stripe_l0.get("time_platform_constraint", {}).get("eta_turn_nodes", [])
    )
    if len(y_span) != 2 or y_span[0] >= y_span[1] or entry != y_span[1]:
        raise CandidateContractError("Stripe active span must end at the theory entrance")
    if not nodes or min(nodes) <= 0.0:
        raise CandidateContractError("Stripe time-platform nodes must be positive")
    usable_length = entry - y_span[0]
    maximum_node = max(nodes)
    return {
        "active_span_y_mm": list(y_span),
        "active_length_mm": usable_length,
        "maximum_eta_turn_node": maximum_node,
        "maximum_abs_drift_length_L_mm": usable_length / maximum_node,
        "nominal_turn_y_relation": "y_turn=y_entry-|L|",
        "derivation": "|L| <= active_length/max(eta_turn_nodes)",
    }


def attach_fixed_geometry_parameter_authority(
    report: dict[str, Any], contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """State what fixed Stripe geometry can and cannot determine.

    Angle and energy-partition values at an incompatible least-squares iterate
    are useful diagnostics, but they are not an operating point.  Keep that
    distinction machine-readable so a later prism or SIMION stage cannot
    silently consume them.
    """
    family = report.get("complete_fixed_hardware_root_family")
    if not isinstance(family, list):
        raise CandidateContractError("Stripe report lacks the fixed-hardware mirror-root family")
    reference_emulation = report.get("exact_paper_component_emulation_audit")
    branch_states: list[dict[str, Any]] = []
    publishable_indices: list[int] = []
    for branch in family:
        if not isinstance(branch, dict):
            raise CandidateContractError("fixed-hardware branch must be an object")
        index = branch.get("mirror_root_index")
        search = branch.get("complete_fixed_hardware_search")
        best = search.get("best_iterate") if isinstance(search, dict) else None
        determination = best.get("determination") if isinstance(best, dict) else None
        status = determination.get("status") if isinstance(determination, dict) else "no_physical_iterate"
        publishable = status in _PUBLISHABLE_DETERMINATION_STATES
        if publishable:
            publishable_indices.append(index)
        branch_states.append({
            "mirror_root_index": index,
            "determination_status": status,
            "operating_state_publishable": publishable,
            "diagnostic_only_outputs": [] if publishable else [
                "nominal_injection_angle_degrees",
                "derived_drift_kinetic_energy_per_charge_v",
                "derived_fast_reflection_energy_per_charge_v",
            ],
        })
    gate_passed = bool(publishable_indices)
    report["fixed_geometry_parameter_authority"] = {
        "geometry_alone": {
            "status": "underdetermined",
            "fixed_quantities": [
                "physical_width_functions_S1_y_and_S2_y",
                "Stripe_entry_coordinate_and_usable_interval",
                "two_response_function_space",
            ],
            "not_fixed_quantities": [
                "drift_length_L",
                "Stripe_biases_v1_and_v2",
                "nominal_injection_angle_theta0",
                "drift_energy_per_charge_wy",
                "fast_reflection_energy_per_charge_wz",
            ],
            "reason": "the physical turn depends on the voltage response and energy partition, not on curve coordinates alone",
            "derived_feasibility_bound": (
                _fixed_geometry_drift_length_bound(contract) if contract is not None else None
            ),
        },
        "coupled_problem": {
            "external_or_upstream_authorities": [
                "mirror_receipt_axial_width_W",
                "nominal_total_energy_per_charge_w0",
                "target_oscillation_count_K",
            ],
            "solve_coordinates": [
                "stripe_set_1_bias_v",
                "stripe_set_2_bias_v",
                "drift_length_L_mm",
            ],
            "conditionally_derived_outputs": [
                "theta0_from_sin_theta0_equals_kappa_1_L_over_K_W",
                "wy_equals_w0_sin_squared_theta0",
                "wz_equals_w0_minus_wy",
            ],
            "publication_condition": "at least one branch must be locally compatible and full-column-rank",
        },
        "reference_component_emulation": reference_emulation,
        "branch_states": branch_states,
        "operating_state_publication_gate": {
            "passed": gate_passed,
            "publishable_mirror_root_indices": publishable_indices,
            "status": (
                "passed" if gate_passed else "failed_no_compatible_full_rank_branch"
            ),
            "published_operating_state": "available_in_publishable_branch" if gate_passed else None,
        },
    }
    return report


def _manifest_record_named(records: object, filename: str) -> dict[str, Any]:
    candidates = records.values() if isinstance(records, dict) else records if isinstance(records, list) else []
    matches = [
        record for record in candidates
        if isinstance(record, dict) and Path(str(record.get("path", ""))).name == filename
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"managed Stripe manifest must contain exactly one {filename} record")
    return matches[0]


def build_parameter_authority_from_managed_seed(manifest_path: Path) -> dict[str, Any]:
    """Derive parameter authority from an integrity-checked managed seed run."""
    path = manifest_path.resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"managed Stripe manifest is not readable JSON: {path}") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        raise CandidateContractError("managed Stripe authority input requires a schema-v2 manifest")
    if (
        manifest.get("status") != "success"
        or manifest.get("project") != _PROJECT_ID
        or manifest.get("mode") != _OPERATING_SEED_MODE
    ):
        raise CandidateContractError("managed Stripe manifest has the wrong terminal status, project, or mode")
    try:
        verify_record("run_config", manifest["run_config"], base_dir=path.parent)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"input {name}", record, base_dir=path.parent)
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            verify_record(f"output {index}", record, base_dir=path.parent)
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(f"managed Stripe manifest integrity failed: {error}") from error
    summary_record = _manifest_record_named(manifest.get("outputs"), "summary.json")
    contract_record = _manifest_record_named(manifest.get("inputs"), "simion_candidate_two_zone.json")
    summary_path = record_path(summary_record, base_dir=path.parent)
    contract_path = record_path(contract_record, base_dir=path.parent)
    try:
        source_summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError("managed Stripe summary is not readable JSON") from error
    try:
        source_contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError("managed Stripe input contract is not readable JSON") from error
    if (
        not isinstance(source_summary, dict)
        or source_summary.get("role") != "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family"
    ):
        raise CandidateContractError("managed Stripe summary has the wrong role")
    updated = copy.deepcopy(source_summary)
    target = updated.get("dimensionless_paper_target")
    if not isinstance(target, dict):
        raise CandidateContractError("managed Stripe summary omits its dimensionless paper target")
    updated["exact_paper_component_emulation_audit"] = (
        audit_exact_paper_component_emulation_by_static_stripes(target)
    )
    attach_fixed_geometry_parameter_authority(updated, source_contract)
    return {
        "schema_version": 1,
        "role": "mrtof_fixed_stripe_geometry_parameter_authority",
        "status": "success",
        "qualification": "solver_neutral_parameter_authority__not_an_operating_point",
        "source_operating_seed_run_id": manifest.get("run_id"),
        "source_operating_seed_manifest_sha256": file_sha256(path),
        "source_operating_seed_summary_sha256": str(summary_record.get("sha256", "")).upper(),
        "fixed_geometry_parameter_authority": updated["fixed_geometry_parameter_authority"],
        "two_prism_voltage_definition": audit_two_prism_voltage_definition(source_contract),
        "limitations": [
            "This report classifies parameter authority only; it does not rerun or improve the bounded search.",
            "A failed publication gate withholds Stripe, prism, SIMION-flight, and performance operating values.",
        ],
    }


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


def _solve_dimensionless_paper_target(contract: dict[str, Any]) -> dict[str, Any]:
    """Solve the six paper conditions for the project-selected four nodes."""
    l0 = contract.get("dual_stripe_l0")
    settings = l0.get("dimensionless_paper_target") if isinstance(l0, dict) else None
    if not isinstance(settings, dict) or settings.get("status") != "solve_from_six_paper_conditions":
        raise CandidateContractError("dimensionless paper-target solver contract is incomplete")
    reference = np.asarray([
        _finite(value, "published target reference coefficient")
        for value in settings.get("published_printed_reference_c0_to_c5", [])
    ])
    if reference.shape != (6,):
        raise CandidateContractError("dimensionless paper-target reference must contain c0..c5")
    nodes = tuple(
        _finite(value, "time-platform node")
        for value in l0["time_platform_constraint"]["eta_turn_nodes"]
    )
    profile = _seed_profile(contract)
    kappa_step = _finite(profile["kappa_derivative_step"], "target kappa derivative step")
    tau_step = _finite(profile["time_platform_derivative_step"], "target tau derivative step")
    start_count = _positive_integer(settings["deterministic_multistart_count"], "target multistart count")
    maximum_evaluations = _positive_integer(settings["maximum_function_evaluations"], "target evaluation count")
    perturbation = _finite(settings["relative_reference_perturbation"], "target perturbation")
    difference_step = _finite(settings["relative_finite_difference_step"], "target finite-difference step")
    root_tolerance = _finite(settings["residual_norm_tolerance"], "target residual tolerance")
    distinct_tolerance = _finite(settings["distinct_root_scaled_distance"], "target distinct-root tolerance")
    if not 0.0 < perturbation < 1.0 or not 0.0 < difference_step < 1.0:
        raise CandidateContractError("dimensionless paper-target perturbation and difference step must lie in (0,1)")
    if root_tolerance <= 0.0 or distinct_tolerance <= 0.0:
        raise CandidateContractError("dimensionless paper-target root tolerances must be positive")
    scales = np.maximum(np.abs(reference), 1.0)
    seed_material = json.dumps(
        {"reference": reference.tolist(), "nodes": nodes},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    random_seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    generator = np.random.default_rng(random_seed)
    starts = [reference]
    starts.extend(
        reference + generator.normal(size=6) * scales * perturbation
        for _ in range(start_count - 1)
    )

    def residual_vector(coefficients: np.ndarray) -> np.ndarray:
        try:
            return np.asarray([
                value for _name, value in paper_dimensionless_condition_residuals(
                    coefficients,
                    eta_turn_nodes=nodes,
                    kappa_derivative_step=kappa_step,
                    tau_derivative_step=tau_step,
                )
            ])
        except CandidateContractError:
            distance = float(np.linalg.norm((coefficients - reference) / scales))
            return np.full(6, 1.0e3 + distance)

    roots: list[dict[str, Any]] = []
    for start in starts:
        result = least_squares(
            residual_vector,
            start,
            diff_step=difference_step,
            max_nfev=maximum_evaluations,
            xtol=1.0e-12,
            ftol=1.0e-12,
            gtol=1.0e-12,
        )
        residual = residual_vector(result.x)
        norm = float(np.linalg.norm(residual))
        if norm > root_tolerance:
            continue
        scaled_distance = float(np.linalg.norm((result.x - reference) / scales))
        duplicate = next((
            root for root in roots
            if np.linalg.norm((result.x - np.asarray(root["coefficients_c0_to_c5"])) / scales)
            <= distinct_tolerance
        ), None)
        candidate = {
            "coefficients_c0_to_c5": [float(value) for value in result.x],
            "residual_norm_2": norm,
            "scaled_distance_from_published_reference": scaled_distance,
            "function_evaluations": int(result.nfev),
        }
        if duplicate is not None:
            if norm < duplicate["residual_norm_2"]:
                duplicate.clear()
                duplicate.update(candidate)
            continue
        roots.append(candidate)
    if not roots:
        raise CandidateContractError("no dimensionless coefficient root passed the declared six-condition gate")
    roots.sort(key=lambda root: (
        root["scaled_distance_from_published_reference"], root["residual_norm_2"]
    ))
    selected = roots[0]
    coefficients = np.asarray(selected["coefficients_c0_to_c5"])
    residuals = paper_dimensionless_condition_residuals(
        coefficients,
        eta_turn_nodes=nodes,
        kappa_derivative_step=kappa_step,
        tau_derivative_step=tau_step,
    )
    selected.update({
        "residuals": dict(residuals),
        "psi_coefficients_by_power": [
            float(coefficients[0] + coefficients[1]),
            *(float(value) for value in coefficients[2:]),
        ],
        "g_coefficients_by_power": [
            float(coefficients[1] - coefficients[0]),
            *(float(value) for value in coefficients[2:]),
        ],
    })
    return {
        "status": "six_paper_conditions_solved_for_project_nodes",
        "qualification": "dimensionless_target_branch_only__not_active_hardware_coefficients",
        "eta_turn_nodes": list(nodes),
        "start_count": len(starts),
        "distinct_root_count": len(roots),
        "reproducible_seed_sha256": hashlib.sha256(seed_material).hexdigest(),
        "selection_rule": "minimum scaled distance from the published rounded branch, then residual norm",
        "selected_root": selected,
        "other_root_summaries": roots[1:],
    }


def _compare_fixed_profile_to_dimensionless_target(
    consistency: dict[str, Any], target: dict[str, Any],
) -> None:
    best = consistency.get("best_iterate")
    if not isinstance(best, dict):
        return
    fitted = best.get("dimensionless_psi_g_polynomial_fit")
    selected = target["selected_root"]
    if not isinstance(fitted, dict):
        return
    psi = np.asarray(fitted["psi_coefficients_by_power"], dtype=float)
    g = np.asarray(fitted["g_coefficients_by_power"], dtype=float)
    target_psi = np.asarray(selected["psi_coefficients_by_power"], dtype=float)
    target_g = np.asarray(selected["g_coefficients_by_power"], dtype=float)
    coefficient_scales = np.maximum(np.maximum(np.abs(target_psi), np.abs(target_g)), 1.0)
    difference = np.concatenate(((psi - target_psi) / coefficient_scales, (g - target_g) / coefficient_scales))
    best["dimensionless_target_comparison"] = {
        "qualification": "diagnostic_polynomial_projection__integral_residuals_remain_authoritative",
        "actual_equivalent_c0_from_linear_psi_g": float((psi[0] - g[0]) / 2.0),
        "actual_equivalent_c1_from_linear_psi_g": float((psi[0] + g[0]) / 2.0),
        "target_c0": float(selected["coefficients_c0_to_c5"][0]),
        "target_c1": float(selected["coefficients_c0_to_c5"][1]),
        "maximum_abs_high_order_psi_minus_g": float(np.max(np.abs(psi[1:] - g[1:]))),
        "scaled_psi_g_coefficient_difference_norm_2": float(np.linalg.norm(difference)),
    }


def _seed_profile(contract: dict[str, Any]) -> dict[str, Any]:
    block = contract.get("dual_stripe_l0")
    profile = block.get("operating_seed_search") if isinstance(block, dict) else None
    if not isinstance(profile, dict) or profile.get("status") != "paper_theory__instance_specific_K_and_spatial_return_seed":
        raise CandidateContractError("dual_stripe_l0.operating_seed_search is incomplete")
    if profile.get("seed_equations") != ["target_oscillation_count", "spatial_return_kappa_prime"]:
        raise CandidateContractError("Stripe operating seed must retain the declared two paper equations")
    return profile


def _entry_direction_and_search_end(
    contract: dict[str, Any], profile: dict[str, Any],
) -> tuple[tuple[float, float, float], float, int]:
    energy = contract.get("prism_transport", {}).get("energy_partition", {})
    if energy.get("semantics") != "total_kinetic_energy_at_first_prism_ev":
        raise CandidateContractError("Stripe seed requires the declared prism energy partition")
    total = _finite(energy.get("total_kinetic_energy_ev"), "total kinetic energy")
    drift = _finite(energy.get("drift_kinetic_energy_ev"), "drift kinetic energy")
    nominal = _finite(contract.get("nominal", {}).get("energy_per_charge_v"), "nominal energy")
    if total != nominal or not 0.0 < drift < total:
        raise CandidateContractError("Stripe seed energy partition must match the positive nominal energy")
    direction = (0.0, -math.sqrt(drift / total), -math.sqrt(1.0 - drift / total))
    stripe_l0 = contract["dual_stripe_l0"]
    entry = _finite(stripe_l0["theory_stripe_entrance"]["project_y_mm"], "Stripe entry y")
    y_span = tuple(_finite(value, "Stripe active span") for value in contract["dual_stripe"]["theory_profile"]["active_y_span_mm"])
    nodes = tuple(_finite(value, "time-platform node") for value in stripe_l0["time_platform_constraint"]["eta_turn_nodes"])
    if len(y_span) != 2 or entry != y_span[1] or not nodes or min(nodes) <= 0.0:
        raise CandidateContractError("Stripe active span, entry, or time-platform nodes are inconsistent")
    usable_length = (entry - y_span[0]) / max(nodes)
    search_end = entry - usable_length
    theory = contract["dual_stripe"]["theory_profile"]
    samples_per_span = _positive_integer(
        theory.get("sampling_per_nonzero_knot_span"),
        "native Stripe samples per nonzero knot span",
    )
    span_counts = []
    for set_name in ("set_1", "set_2"):
        definition = theory.get(set_name, {})
        for edge_name in ("lower_edge", "upper_edge"):
            edge = definition.get(edge_name, {})
            if edge.get("basis") != "cubic_bspline":
                continue
            order = _positive_integer(edge.get("order"), f"{set_name} {edge_name} order")
            knots = tuple(_finite(value, f"{set_name} {edge_name} knot") for value in edge.get("knots", []))
            if len(knots) <= 2 * order:
                raise CandidateContractError("native Stripe knot vector cannot derive turning-search sampling")
            span_counts.append(sum(right > left for left, right in zip(knots[order - 1:-order], knots[order:1 - order])))
    if not span_counts or min(span_counts) <= 0:
        raise CandidateContractError("native Stripe profiles have no nonzero B-spline spans")
    multiplier = _positive_integer(
        profile.get("turning_search_sampling_multiplier"),
        "turning-search sampling multiplier",
    )
    sample_count = max(span_counts) * samples_per_span * multiplier
    return direction, search_end, sample_count


def _surrogate_widths(contract: dict[str, Any]) -> tuple[WidthFunction, WidthFunction]:
    shape = identify_fixed_cad_component_shapes(contract)
    fit = shape["selected_fit"]
    baselines = shape["width_baselines_at_entry_mm"]
    coefficients = tuple(float(value) for value in fit["set_1_coefficients_per_physical_mm_power"])
    linear = float(fit["set_2_coefficient_per_physical_mm"])
    first_baseline = float(baselines["set_1"])
    second_baseline = float(baselines["set_2"])
    multiplier = _finite(
        contract["dual_stripe"]["theory_profile"]["path_length_mapping"]["profile_width_to_total_S_multiplier"],
        "Stripe surrogate path-length multiplier",
    )
    if multiplier <= 0.0:
        raise CandidateContractError("Stripe surrogate path-length multiplier must be positive")

    def first(y_mm: float) -> float:
        distance = -float(y_mm)
        return multiplier * (
            first_baseline + sum(value * distance**power for power, value in enumerate(coefficients, 1))
        )

    def second(y_mm: float) -> float:
        return multiplier * (second_baseline + linear * -float(y_mm))

    return first, second


def _evaluate_seed_equations(
    mirror: ManagedMirrorCandidate,
    widths: Sequence[WidthFunction],
    biases_v: Sequence[float],
    direction: Sequence[float],
    search_end_y_mm: float,
    sample_count: int,
    kappa_derivative_step: float,
) -> tuple[np.ndarray, tuple[StripeHardBoundary, StripeHardBoundary], float, Any]:
    if len(widths) != 2 or len(biases_v) != 2:
        raise CandidateContractError("Stripe seed evaluation needs two widths and two biases")
    stripes = tuple(
        StripeHardBoundary(_finite(bias, "Stripe seed bias"), width)
        for bias, width in zip(biases_v, widths)
    )
    entry = _finite(mirror.contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"], "Stripe entry")
    target_k = _positive_integer(mirror.contract["nominal"]["target_oscillation_count"], "target K")
    energy = mirror.nominal_energy_per_charge_v
    turn = derive_turning_y_from_entry_direction(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy,
        stripes=stripes,
        entry_y_mm=entry,
        entry_unit_direction_project=direction,
        search_end_y_mm=search_end_y_mm,
        sample_count=sample_count,
    )
    state = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy,
        target_oscillation_count=target_k,
        stripes=stripes,
        entry_y_mm=entry,
        turning_y_mm=turn,
    )
    kappa_prime = spatial_return_kappa_derivative_residual(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy,
        stripes=stripes,
        entry_y_mm=entry,
        nominal_turning_y_mm=turn,
        derivative_step=kappa_derivative_step,
    )
    return np.asarray([state.target_oscillation_count_residual, kappa_prime]), stripes, turn, state


def _central_jacobian(
    evaluator: Callable[[np.ndarray], np.ndarray], values: np.ndarray, step_v: float,
) -> np.ndarray:
    result = np.empty((2, 2), dtype=float)
    for column in range(2):
        lower = values.copy()
        upper = values.copy()
        lower[column] -= step_v
        upper[column] += step_v
        result[:, column] = (evaluator(upper) - evaluator(lower)) / (2.0 * step_v)
    return result


def _bias_pair_is_nondegenerate(values: np.ndarray, profile: dict[str, Any], energy: float) -> bool:
    minimum_abs_fraction = _finite(
        profile.get("minimum_abs_bias_fraction_of_nominal_energy"),
        "minimum bias fraction",
    )
    minimum_ratio = _finite(
        profile.get("minimum_bias_magnitude_ratio"),
        "minimum bias magnitude ratio",
    )
    minimum_separation_fraction = _finite(
        profile.get("minimum_bias_separation_fraction_of_nominal_energy"),
        "minimum separation fraction",
    )
    magnitudes = tuple(abs(float(value)) for value in values)
    if not 0.0 < minimum_ratio < 1.0:
        raise CandidateContractError("minimum bias magnitude ratio must lie strictly between zero and one")
    return (
        min(magnitudes) > minimum_abs_fraction * energy
        and min(magnitudes) / max(magnitudes) >= minimum_ratio
        and abs(float(values[0] - values[1])) > minimum_separation_fraction * energy
    )


def _fixed_hardware_joint_trial(
    mirror: ManagedMirrorCandidate,
    widths: Sequence[WidthFunction],
    biases_v: Sequence[float],
    direction: Sequence[float],
    search_end_y_mm: float,
    sample_count: int,
    kappa_derivative_step: float,
    time_platform_derivative_step: float,
    energy_derivative_step_v: float,
) -> JointL0Trial:
    """Construct one complete fixed-hardware Stripe trial from two biases."""
    contract = mirror.contract
    entry = _finite(contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"], "Stripe entry")
    stripes = tuple(
        StripeHardBoundary(_finite(bias, "Stripe consistency bias"), width)
        for bias, width in zip(biases_v, widths)
    )
    if len(stripes) != 2:
        raise CandidateContractError("fixed-hardware consistency trial requires two Stripe biases")
    turn = derive_turning_y_from_entry_direction(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=mirror.nominal_energy_per_charge_v,
        stripes=stripes,
        entry_y_mm=entry,
        entry_unit_direction_project=direction,
        search_end_y_mm=search_end_y_mm,
        sample_count=sample_count,
    )
    return _fixed_hardware_joint_trial_at_turn(
        mirror,
        widths,
        biases_v,
        turn,
        kappa_derivative_step,
        time_platform_derivative_step,
        energy_derivative_step_v,
    )


def _fixed_hardware_joint_trial_at_turn(
    mirror: ManagedMirrorCandidate,
    widths: Sequence[WidthFunction],
    biases_v: Sequence[float],
    turning_y_mm: float,
    kappa_derivative_step: float,
    time_platform_derivative_step: float,
    energy_derivative_step_v: float,
) -> JointL0Trial:
    """Construct a fixed-geometry trial with ``L`` as a solve coordinate."""
    contract = mirror.contract
    entry = _finite(contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"], "Stripe entry")
    stripes = tuple(
        StripeHardBoundary(_finite(bias, "Stripe consistency bias"), width)
        for bias, width in zip(biases_v, widths)
    )
    if len(stripes) != 2:
        raise CandidateContractError("fixed-hardware consistency trial requires two Stripe biases")
    return JointL0Trial(
        mirror_design=mirror.design,
        energy_points_v=mirror.energy_points_v,
        stripes=stripes,
        stripe_entry_y_mm=entry,
        nominal_turning_y_mm=_finite(turning_y_mm, "Stripe physical turning y"),
        target_oscillation_count=_positive_integer(
            contract["nominal"]["target_oscillation_count"], "target K"
        ),
        time_platform_eta_nodes=tuple(
            _finite(value, "time-platform node")
            for value in contract["dual_stripe_l0"]["time_platform_constraint"]["eta_turn_nodes"]
        ),
        kappa_derivative_step=kappa_derivative_step,
        time_platform_derivative_step=time_platform_derivative_step,
        energy_derivative_step_v=energy_derivative_step_v,
    )


def _complete_residual_scales(
    contract: dict[str, Any], names: Sequence[str], energies_v: Sequence[float],
) -> tuple[float, ...]:
    budget = contract["mirror"]["theory_requirements"]["l0_acceptance_budget"]
    period_scale = derive_mirror_l0_slope_tolerance_per_v(
        float(budget["minimum_mass_resolution"]),
        float(budget["mirror_time_width_fraction"]),
        tuple(float(value) for value in energies_v),
    )
    return tuple(
        period_scale if name.startswith("full_analyser_period_slope_at_") else 1.0
        for name in names
    )


def _dimensionless_profile_fit(
    mirror: ManagedMirrorCandidate,
    stripes: Sequence[StripeHardBoundary],
    turning_y_mm: float,
    sample_count: int,
) -> dict[str, Any]:
    contract = mirror.contract
    nodes = tuple(
        _finite(value, "time-platform node")
        for value in contract["dual_stripe_l0"]["time_platform_constraint"]["eta_turn_nodes"]
    )
    degree = _positive_integer(
        contract["dual_stripe_l0"]["fixed_cad_shape_identification"]["set_1_polynomial_degree"],
        "dimensionless profile polynomial degree",
    )
    return asdict(fit_dimensionless_psi_g_profiles(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=mirror.nominal_energy_per_charge_v,
        stripes=stripes,
        entry_y_mm=_finite(
            contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"],
            "Stripe entry",
        ),
        nominal_turning_y_mm=turning_y_mm,
        eta_max=max(1.0, *nodes),
        polynomial_degree=degree,
        sample_count=sample_count,
    ))


def _search_complete_fixed_hardware_consistency(mirror: ManagedMirrorCandidate) -> dict[str, Any]:
    """Run a bounded multi-start search over every remaining paper residual.

    The residual scales only condition this diagnostic search.  They are not
    physical acceptance tolerances, so the best iterate is never promoted by
    optimizer success alone.
    """
    contract = mirror.contract
    profile = _seed_profile(contract)
    direction, search_end, sample_count = _entry_direction_and_search_end(contract, profile)
    widths = tuple(compile_dual_stripe_path_length_evaluator(contract, name) for name in ("set_1", "set_2"))
    eta_step = _finite(profile["kappa_derivative_step"], "kappa derivative step")
    time_step = _finite(profile["time_platform_derivative_step"], "time-platform derivative step")
    energy_step = _finite(
        contract["mirror"]["theory_requirements"]["global_l0_search_profile"]["period_slope_derivative_step_v"],
        "full-analyser energy derivative step",
    )
    voltage_step = _finite(profile["native_newton_voltage_step_v"], "Stripe voltage step")
    maximum_evaluations = _positive_integer(
        profile["maximum_surrogate_function_evaluations"], "complete consistency evaluation count"
    )
    refinement_start_count = _positive_integer(
        profile["complete_consistency_refinement_start_count"],
        "complete consistency refinement start count",
    )
    fractions = tuple(_finite(value, "complete consistency start fraction") for value in profile["normalized_start_fractions"])
    energy = mirror.nominal_energy_per_charge_v
    lower = -energy
    upper = math.nextafter(min(mirror.energy_points_v), -math.inf)
    bias_starts = [
        energy * np.asarray((first, second), dtype=float)
        for first in fractions
        for second in fractions
        if first != second
    ]
    entry = _finite(contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"], "Stripe entry")
    drift_sign = 1.0 if search_end > entry else -1.0
    usable_length = abs(search_end - entry)
    length_step = usable_length / sample_count
    starts: list[np.ndarray] = []
    for biases in bias_starts:
        try:
            initialization_trial = _fixed_hardware_joint_trial(
                mirror, widths, biases, direction, search_end, sample_count,
                eta_step, time_step, energy_step,
            )
        except CandidateContractError:
            continue
        starts.append(np.asarray([
            float(biases[0]),
            float(biases[1]),
            abs(initialization_trial.nominal_turning_y_mm - entry),
        ]))
    feasible_starts = 0
    candidates: list[dict[str, Any]] = []
    screened_starts: list[tuple[float, np.ndarray]] = []
    residual_names: tuple[str, ...] | None = None
    residual_scales: tuple[float, ...] | None = None

    def report_at(values: Sequence[float]):
        if len(values) != 3:
            raise CandidateContractError("complete fixed-hardware search needs v1, v2, and L")
        length = _finite(values[2], "Stripe drift length solve coordinate")
        if not 0.0 < length < usable_length:
            raise CandidateContractError("Stripe drift length solve coordinate left the active profile")
        trial = _fixed_hardware_joint_trial_at_turn(
            mirror,
            widths,
            values[:2],
            entry + drift_sign * length,
            eta_step,
            time_step,
            energy_step,
        )
        return evaluate_joint_l0_trial(trial)

    for start in starts:
        try:
            initial = report_at(start)
        except CandidateContractError:
            continue
        feasible_starts += 1
        if residual_names is None:
            residual_names = initial.residual_names()
            residual_scales = _complete_residual_scales(contract, residual_names, mirror.energy_points_v)
        assert residual_scales is not None
        initial_scaled = np.asarray(initial.residual_vector()) / np.asarray(residual_scales)
        screened_starts.append((float(np.linalg.norm(initial_scaled)), start))

    screened_starts.sort(key=lambda item: item[0])
    refined_starts = screened_starts[:min(refinement_start_count, len(screened_starts))]
    for _initial_norm, start in refined_starts:
        assert residual_scales is not None

        def objective(values: np.ndarray) -> np.ndarray:
            try:
                report = report_at(values)
                if report.residual_names() != residual_names:
                    raise CandidateContractError("complete residual identity changed during search")
                return np.asarray(report.residual_vector()) / np.asarray(residual_scales)
            except CandidateContractError:
                distance = float(np.linalg.norm(
                    (values - start) / np.asarray([energy, energy, usable_length])
                ))
                return np.full(len(residual_scales), 1.0e3 + distance)

        def objective_jacobian(values: np.ndarray) -> np.ndarray:
            """Differentiate the nested integral residuals on an absolute voltage scale.

            SciPy's default relative perturbation becomes microscopic for this
            kilovolt-scale solve and samples quadrature noise instead of the
            physical voltage response.  The same contract-owned absolute step
            used by the publication rank audit keeps search and classification
            on one numerical scale.
            """
            columns: list[np.ndarray] = []
            for index in range(len(values)):
                low = values.copy()
                high = values.copy()
                coordinate_step = voltage_step if index < 2 else length_step
                coordinate_lower = lower if index < 2 else math.nextafter(0.0, math.inf)
                coordinate_upper = upper if index < 2 else math.nextafter(usable_length, -math.inf)
                low[index] = max(coordinate_lower, float(values[index]) - coordinate_step)
                high[index] = min(coordinate_upper, float(values[index]) + coordinate_step)
                denominator = high[index] - low[index]
                if denominator <= 0.0:
                    raise CandidateContractError("Stripe voltage Jacobian step collapsed at its bound")
                columns.append((objective(high) - objective(low)) / denominator)
            return np.column_stack(columns)

        result = least_squares(
            objective,
            start,
            bounds=(
                [lower, lower, math.nextafter(0.0, math.inf)],
                [upper, upper, math.nextafter(usable_length, -math.inf)],
            ),
            jac=objective_jacobian,
            x_scale=np.asarray([energy, energy, usable_length]),
            max_nfev=maximum_evaluations,
        )
        try:
            final_report = report_at(result.x)
        except CandidateContractError:
            continue
        scaled = np.asarray(final_report.residual_vector()) / np.asarray(residual_scales)
        candidates.append({
            "biases_v": [float(value) for value in result.x[:2]],
            "drift_length_solve_coordinate_mm": float(result.x[2]),
            "scaled_residual_norm_2": float(np.linalg.norm(scaled)),
            "optimizer_success": bool(result.success),
            "optimizer_message": str(result.message),
            "function_evaluations": int(result.nfev),
        })
    if not candidates or residual_names is None or residual_scales is None:
        return {
            "status": "no_feasible_complete_consistency_iterate",
            "attempted_start_count": len(bias_starts),
            "legacy_5eV_initializable_start_count": len(starts),
            "feasible_start_count": feasible_starts,
            "refined_start_count": 0,
            "limitations": ["No physical first-turn trial survived the declared bounded multi-start search."],
        }
    candidates.sort(key=lambda item: (item["scaled_residual_norm_2"], max(abs(v) for v in item["biases_v"])))
    best = candidates[0]

    def trial_from_values(values: tuple[float, ...]) -> JointL0Trial:
        length = _finite(values[2], "Stripe drift length solve coordinate")
        return _fixed_hardware_joint_trial_at_turn(
            mirror, widths, values[:2], entry + drift_sign * length,
            eta_step, time_step, energy_step,
        )

    best_parameters = (*best["biases_v"], best["drift_length_solve_coordinate_mm"])
    best_trial = trial_from_values(tuple(best_parameters))
    numerics = contract["dual_stripe_l0"]["determination_numerics"]
    report, classification = finite_difference_joint_jacobian(
        ("stripe_set_1_bias_v", "stripe_set_2_bias_v", "drift_length_L_mm"),
        tuple(best_parameters),
        (voltage_step, voltage_step, length_step),
        trial_from_values,
        parameter_scales=(energy, energy, usable_length),
        residual_scales=residual_scales,
        relative_rank_tolerance=_finite(
            numerics["relative_singular_value_rank_tolerance"], "rank tolerance"
        ),
        compatibility_tolerance=_finite(
            numerics["scaled_irreducible_residual_norm_tolerance"], "compatibility tolerance"
        ),
    )
    best.update({
        "raw_residuals": dict(report.residuals),
        "residual_scales": dict(zip(report.residual_names(), residual_scales)),
        "determination": asdict(classification),
        "drift_length_L_mm": report.drift_state.drift_length_l_mm,
        "derived_drift_kinetic_energy_per_charge_v": report.drift_state.turning_pseudopotential_v,
        "derived_fast_reflection_energy_per_charge_v": (
            mirror.nominal_energy_per_charge_v - report.drift_state.turning_pseudopotential_v
        ),
        "mirror_owned_axial_width_W_mm": report.drift_state.axial_width_w_mm,
        "nominal_kappa_1": report.drift_state.nominal_kappa_1,
        "nominal_injection_angle_degrees": math.degrees(report.drift_state.nominal_injection_angle_rad),
        "dimensionless_psi_g_polynomial_fit": _dimensionless_profile_fit(
            mirror, best_trial.stripes, best_trial.nominal_turning_y_mm, sample_count,
        ),
    })
    return {
        "status": "bounded_multistart_complete__not_a_global_proof",
        "attempted_start_count": len(bias_starts),
        "legacy_5eV_initializable_start_count": len(starts),
        "feasible_start_count": feasible_starts,
        "refined_start_count": len(refined_starts),
        "distinct_final_iterate_count": len(candidates),
        "best_iterate": best,
        "paper_turning_normalization": {
            "constraint": "psi(1)-1=0",
            "status": "identically_satisfied_by_normalizing_at_the_solved_physical_turn",
        },
        "energy_partition_semantics": "theta0, drift energy, and fast reflection energy are derived from the solved L and turning pseudopotential; 5 eV initializes starts only",
        "limitations": [
            "Optimizer convergence is a search diagnostic, not an acceptance condition.",
            "The bounded deterministic start grid is not a mathematical proof of global existence or nonexistence.",
        ],
    }


def _build_operating_seed_report_for_mirror(mirror: ManagedMirrorCandidate) -> dict[str, Any]:
    """Search one qualified mirror root and publish native-geometry seed diagnostics."""
    contract = mirror.contract
    profile = _seed_profile(contract)
    direction, search_end, sample_count = _entry_direction_and_search_end(contract, profile)
    kappa_step = _finite(profile.get("kappa_derivative_step"), "kappa derivative step")
    voltage_step = _finite(profile.get("native_newton_voltage_step_v"), "Newton voltage step")
    maximum_newton = _positive_integer(profile.get("maximum_native_newton_iterations"), "Newton iteration count")
    maximum_evaluations = _positive_integer(profile.get("maximum_surrogate_function_evaluations"), "surrogate evaluation count")
    residual_tolerances = tuple(_finite(value, "seed residual tolerance") for value in profile.get("residual_tolerances", []))
    if len(residual_tolerances) != 2 or min(residual_tolerances) <= 0.0 or kappa_step <= 0.0 or voltage_step <= 0.0:
        raise CandidateContractError("Stripe seed numerical controls are incomplete")
    fractions = tuple(_finite(value, "start fraction") for value in profile.get("normalized_start_fractions", []))
    if len(fractions) < 2 or any(value == 0.0 or not -1.0 < value < 1.0 for value in fractions):
        raise CandidateContractError("Stripe seed requires nonzero normalized starts inside the energy envelope")
    energy = mirror.nominal_energy_per_charge_v
    energy_nodes = mirror.energy_points_v
    lower_bound = -energy
    upper_bound = math.nextafter(min(energy_nodes), -math.inf)
    surrogate_widths = _surrogate_widths(contract)

    def evaluate(widths: Sequence[WidthFunction], values: np.ndarray) -> np.ndarray:
        return _evaluate_seed_equations(
            mirror, widths, values, direction, search_end, sample_count, kappa_step,
        )[0]

    surrogate_roots: list[np.ndarray] = []
    starts_attempted = 0
    starts_feasible = 0
    for first_fraction in fractions:
        for second_fraction in fractions:
            if first_fraction == second_fraction:
                continue
            start = energy * np.asarray([first_fraction, second_fraction])
            starts_attempted += 1
            try:
                evaluate(surrogate_widths, start)
            except CandidateContractError:
                continue
            starts_feasible += 1

            def surrogate_objective(values: np.ndarray) -> np.ndarray:
                trial = np.asarray(values, dtype=float)
                try:
                    return evaluate(surrogate_widths, trial)
                except CandidateContractError:
                    distance = float(np.linalg.norm((trial - start) / energy))
                    return np.asarray([1000.0 + distance, 1000.0 + distance])

            result = least_squares(
                surrogate_objective,
                start,
                bounds=([lower_bound, lower_bound], [upper_bound, upper_bound]),
                x_scale="jac",
                max_nfev=maximum_evaluations,
            )
            if not result.success:
                continue
            root = np.asarray(result.x, dtype=float)
            residual = evaluate(surrogate_widths, root)
            if any(abs(value) > 100.0 * tolerance for value, tolerance in zip(residual, residual_tolerances)):
                continue
            if not any(np.linalg.norm(root - known, ord=np.inf) <= voltage_step for known in surrogate_roots):
                surrogate_roots.append(root)
    if not surrogate_roots:
        raise CandidateContractError("no surrogate K/spatial-return root was found in the declared voltage envelope")

    native_widths = tuple(
        compile_dual_stripe_path_length_evaluator(contract, name) for name in ("set_1", "set_2")
    )
    native_roots: list[dict[str, Any]] = []
    for surrogate_root in surrogate_roots:
        values = surrogate_root.copy()
        history: list[dict[str, Any]] = []

        def native_evaluator(trial: np.ndarray) -> np.ndarray:
            return evaluate(native_widths, trial)

        try:
            for iteration in range(maximum_newton):
                residual = native_evaluator(values)
                jacobian = _central_jacobian(native_evaluator, values, voltage_step)
                rank = int(np.linalg.matrix_rank(jacobian))
                history.append({
                    "iteration": iteration,
                    "biases_v": values.tolist(),
                    "residuals": residual.tolist(),
                    "jacobian": jacobian.tolist(),
                    "jacobian_rank": rank,
                })
                if rank != 2:
                    raise CandidateContractError("native Stripe seed Jacobian is rank deficient")
                if all(abs(value) <= tolerance for value, tolerance in zip(residual, residual_tolerances)):
                    break
                values += np.linalg.solve(jacobian, -residual)
                if np.any(values <= lower_bound) or np.any(values >= upper_bound):
                    raise CandidateContractError("native Stripe Newton refinement left its declared envelope")
            residual, stripes, turn, state = _evaluate_seed_equations(
                mirror, native_widths, values, direction, search_end, sample_count, kappa_step,
            )
        except (CandidateContractError, np.linalg.LinAlgError):
            continue
        if any(abs(value) > tolerance for value, tolerance in zip(residual, residual_tolerances)):
            continue
        if not _bias_pair_is_nondegenerate(values, profile, energy):
            continue
        response = analyze_dual_stripe_l0(contract, values)
        entry_y_mm = _finite(
            contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"],
            "Stripe entry y",
        )
        periods = [
            coupled_reduced_period_mm_per_sqrt_v(
                reduced_period(node, mirror.design),
                node,
                tuple(width(entry_y_mm) for width in native_widths),
                values,
            )
            for node in energy_nodes
        ]
        central_period = periods[1]
        energy_step = _finite(
            contract["mirror"]["theory_requirements"]["global_l0_search_profile"]["period_slope_derivative_step_v"],
            "full-analyser period derivative step",
        )
        full_analyser_slopes = [
            coupled_normalized_period_slope_at_energy(
                mirror.design,
                node,
                tuple(width(entry_y_mm) for width in native_widths),
                values,
                energy_step,
            )
            for node in energy_nodes
        ]
        nodes = tuple(float(value) for value in contract["dual_stripe_l0"]["time_platform_constraint"]["eta_turn_nodes"])
        time_residuals = time_platform_derivative_residuals(
            mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
            energy_per_charge_v=energy,
            stripes=stripes,
            entry_y_mm=entry_y_mm,
            nominal_turning_y_mm=turn,
            eta_turn_nodes=nodes,
            derivative_step=_finite(profile.get("time_platform_derivative_step"), "time derivative step"),
        )

        def trial_from_biases(biases: tuple[float, ...]) -> JointL0Trial:
            trial_stripes = tuple(
                StripeHardBoundary(bias, width)
                for bias, width in zip(biases, native_widths)
            )
            trial_turn = derive_turning_y_from_entry_direction(
                mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
                energy_per_charge_v=energy,
                stripes=trial_stripes,
                entry_y_mm=entry_y_mm,
                entry_unit_direction_project=direction,
                search_end_y_mm=search_end,
                sample_count=sample_count,
            )
            return JointL0Trial(
                mirror_design=mirror.design,
                energy_points_v=tuple(energy_nodes),
                stripes=trial_stripes,
                stripe_entry_y_mm=entry_y_mm,
                nominal_turning_y_mm=trial_turn,
                target_oscillation_count=int(contract["nominal"]["target_oscillation_count"]),
                time_platform_eta_nodes=nodes,
                kappa_derivative_step=kappa_step,
                time_platform_derivative_step=_finite(
                    profile["time_platform_derivative_step"], "time-platform derivative step"
                ),
                energy_derivative_step_v=energy_step,
            )

        seed_trial = trial_from_biases(tuple(float(value) for value in values))
        initial_full_report = evaluate_joint_l0_trial(seed_trial)
        l0_budget = contract["mirror"]["theory_requirements"]["l0_acceptance_budget"]
        period_slope_scale = derive_mirror_l0_slope_tolerance_per_v(
            float(l0_budget["minimum_mass_resolution"]),
            float(l0_budget["mirror_time_width_fraction"]),
            tuple(energy_nodes),
        )
        full_residual_scales = tuple(
            period_slope_scale if name.startswith("full_analyser_period_slope_at_") else 1.0
            for name in initial_full_report.residual_names()
        )
        numerics = contract["dual_stripe_l0"]["determination_numerics"]
        full_report, full_classification = finite_difference_joint_jacobian(
            ("stripe_set_1_bias_v", "stripe_set_2_bias_v"),
            tuple(float(value) for value in values),
            (voltage_step, voltage_step),
            trial_from_biases,
            parameter_scales=(energy, energy),
            residual_scales=full_residual_scales,
            relative_rank_tolerance=_finite(
                numerics["relative_singular_value_rank_tolerance"], "rank tolerance"
            ),
            compatibility_tolerance=_finite(
                numerics["scaled_irreducible_residual_norm_tolerance"],
                "compatibility tolerance",
            ),
        )
        record = {
            "stripe_biases_v": values.tolist(),
            "native_seed_residuals": {
                "target_oscillation_count": float(residual[0]),
                "spatial_return_kappa_prime": float(residual[1]),
            },
            "jacobian_rank": history[-1]["jacobian_rank"],
            "native_newton_history": history,
            "drift_length_L_mm": state.drift_length_l_mm,
            "initialization_drift_kinetic_energy_per_charge_v": state.turning_pseudopotential_v,
            "initialization_fast_reflection_energy_per_charge_v": (
                energy - state.turning_pseudopotential_v
            ),
            "mirror_owned_axial_width_W_mm": state.axial_width_w_mm,
            "nominal_kappa_1": state.nominal_kappa_1,
            "nominal_injection_angle_degrees": math.degrees(state.nominal_injection_angle_rad),
            "response_matrix_condition_number_2": response["response_matrix_condition_number_2"],
            "full_analyser_reduced_periods_mm_per_sqrt_v": periods,
            "full_analyser_relative_period_residuals": [
                (periods[0] - central_period) / central_period,
                (periods[2] - central_period) / central_period,
            ],
            "full_analyser_normalized_period_slopes_per_v": dict(
                zip((str(value) for value in energy_nodes), full_analyser_slopes)
            ),
            "time_platform_tau_g_derivatives": dict(zip((str(value) for value in nodes), time_residuals)),
            "complete_fixed_hardware_residuals": dict(full_report.residuals),
            "paper_turning_normalization": {
                "constraint": "psi(1)-1=0",
                "residual": 0.0,
                "status": "eliminated_by_deriving_L_from_the_first_physical_5eV_turn",
                "semantics": "This paper relation determines L for each voltage trial; it is not counted again as an independent optimizer residual.",
            },
            "complete_fixed_hardware_residual_scales": dict(
                zip(full_report.residual_names(), full_residual_scales)
            ),
            "complete_fixed_hardware_determination": asdict(full_classification),
            "dimensionless_psi_g_polynomial_fit": _dimensionless_profile_fit(
                mirror, seed_trial.stripes, seed_trial.nominal_turning_y_mm, sample_count,
            ),
        }
        if not any(
            np.linalg.norm(values - np.asarray(known["stripe_biases_v"]), ord=np.inf) <= voltage_step
            for known in native_roots
        ):
            native_roots.append(record)
    if not native_roots:
        raise CandidateContractError("no nondegenerate native-geometry Stripe seed passed the numerical root gate")
    native_roots.sort(key=lambda item: (
        max(abs(value) for value in item["stripe_biases_v"]),
        item["response_matrix_condition_number_2"],
    ))
    selected = native_roots[0]
    return {
        "schema_version": 1,
        "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed",
        "status": "success",
        "qualification": "analytic_seed__complete_fixed_hardware_consistency_diagnostic__P1_P2_pending",
        "managed_mirror_run_id": mirror.run_id,
        "managed_mirror_manifest_sha256": mirror.manifest_sha256,
        "paper_relation_identity": "same equations and dimensionless structure; instance coefficients, L, W, and voltages may differ",
        "seed_equations": profile["seed_equations"],
        "entry_direction_project": list(direction),
        "search_envelope_v": [lower_bound, upper_bound],
        "turning_search_end_y_mm": search_end,
        "turning_search_sample_count": sample_count,
        "start_audit": {
            "attempted": starts_attempted,
            "feasible": starts_feasible,
            "surrogate_root_count": len(surrogate_roots),
            "native_nondegenerate_root_count": len(native_roots),
        },
        "selection_rule": "minimum maximum absolute Stripe voltage, then minimum response-matrix condition number",
        "selected_seed": selected,
        "native_root_family": native_roots,
        "limitations": [
            "The polynomial/linear fit is used only for root discovery; every published seed quantity is native-B-spline evaluated.",
            "Only the contract target K and kappa-prime=0 determine this two-voltage seed; the four time-platform and three local full-analyser energy-slope residuals are classified together but are not acceptance-tested.",
            "P1/P2 transport, finite three-dimensional fields, and SIMION flight remain pending.",
        ],
    }


def build_operating_seed_report(mirror_manifest: Path, downstream_contract: Path) -> dict[str, Any]:
    """Search every managed gamma-target mirror root before downstream selection."""
    mirror = load_managed_mirror_candidate(mirror_manifest, downstream_contract)
    dimensionless_target = _solve_dimensionless_paper_target(mirror.contract)
    reference_emulation_audit = audit_exact_paper_component_emulation_by_static_stripes(
        dimensionless_target
    )
    prism_definition = audit_two_prism_voltage_definition(mirror.contract)
    reports: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    consistency_family: list[dict[str, Any]] = []
    branches = [
        replace(
            mirror,
            design=root.design,
            nominal_reduced_period_mm_per_sqrt_v=root.nominal_reduced_period_mm_per_sqrt_v,
            nominal_axial_width_w_mm=root.nominal_axial_width_w_mm,
        )
        for root in mirror.root_family
    ]
    maximum_workers = _positive_integer(
        _seed_profile(mirror.contract)["complete_consistency_maximum_parallel_workers"],
        "complete consistency maximum parallel workers",
    )
    actual_workers = min(maximum_workers, len(branches))
    with ProcessPoolExecutor(max_workers=actual_workers) as executor:
        consistency_results = list(executor.map(_search_complete_fixed_hardware_consistency, branches))
    for consistency in consistency_results:
        _compare_fixed_profile_to_dimensionless_target(consistency, dimensionless_target)
    for index, (root, branch, consistency) in enumerate(
        zip(mirror.root_family, branches, consistency_results)
    ):
        consistency_family.append({
            "mirror_root_index": index,
            "source_l0_restart_index": root.source_l0_restart_index,
            "mirror_owned_axial_width_W_mm": root.nominal_axial_width_w_mm,
            "complete_fixed_hardware_search": consistency,
        })
        try:
            report = _build_operating_seed_report_for_mirror(branch)
        except CandidateContractError as error:
            rejected.append({
                "mirror_root_index": index,
                "source_l0_restart_index": root.source_l0_restart_index,
                "mirror_owned_axial_width_W_mm": root.nominal_axial_width_w_mm,
                "reason": str(error),
            })
            continue
        report["mirror_root_index"] = index
        report["source_l0_restart_index"] = root.source_l0_restart_index
        report["mirror_root_gamma_degrees"] = root.gamma_degrees
        reports.append(report)
    if not reports:
        return attach_fixed_geometry_parameter_authority({
            "schema_version": 2,
            "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family",
            "status": "no_two_equation_seed_found",
            "qualification": "negative_analytic_seed_diagnostic__not_an_operating_point",
            "managed_mirror_run_id": mirror.run_id,
            "managed_mirror_manifest_sha256": mirror.manifest_sha256,
            "paper_relation_identity": "same equations and dimensionless structure; instance coefficients, L, W, and voltages may differ",
            "dimensionless_paper_target": dimensionless_target,
            "exact_paper_component_emulation_audit": reference_emulation_audit,
            "two_prism_voltage_definition": prism_definition,
            "mirror_root_count": len(mirror.root_family),
            "complete_consistency_actual_parallel_workers": actual_workers,
            "successful_mirror_root_count": 0,
            "complete_fixed_hardware_root_family": consistency_family,
            "rejected_mirror_roots": rejected,
            "limitations": [
                "No qualified mirror root produced a native fixed-geometry K/spatial-return seed inside the declared search envelope.",
                "This is a bounded numerical diagnostic, not a proof that no mathematical root exists outside that envelope.",
                "No Stripe voltage, L, prism voltage, SIMION flight, or performance value is published.",
            ],
        }, mirror.contract)
    reports.sort(key=lambda item: (
        max(abs(value) for value in item["selected_seed"]["stripe_biases_v"]),
        item["selected_seed"]["response_matrix_condition_number_2"],
    ))
    selected = reports[0]
    return attach_fixed_geometry_parameter_authority({
        **selected,
        "schema_version": 2,
        "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family",
        "dimensionless_paper_target": dimensionless_target,
        "exact_paper_component_emulation_audit": reference_emulation_audit,
        "two_prism_voltage_definition": prism_definition,
        "mirror_root_count": len(mirror.root_family),
        "complete_consistency_actual_parallel_workers": actual_workers,
        "successful_mirror_root_count": len(reports),
        "selected_mirror_root_index": selected["mirror_root_index"],
        "per_mirror_root_reports": reports,
        "complete_fixed_hardware_root_family": consistency_family,
        "rejected_mirror_roots": rejected,
    }, mirror.contract)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-manifest", type=Path)
    parser.add_argument("--downstream-contract", type=Path)
    parser.add_argument("--source-operating-seed-manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.source_operating_seed_manifest is not None:
        if arguments.mirror_manifest is not None or arguments.downstream_contract is not None:
            parser.error("authority-only mode cannot also accept mirror or downstream inputs")
        report = build_parameter_authority_from_managed_seed(arguments.source_operating_seed_manifest)
        marker = "MRTOF_FIXED_STRIPE_PARAMETER_AUTHORITY"
    else:
        if arguments.mirror_manifest is None or arguments.downstream_contract is None:
            parser.error("search mode requires --mirror-manifest and --downstream-contract")
        report = build_operating_seed_report(arguments.mirror_manifest, arguments.downstream_contract)
        marker = "MRTOF_DUAL_STRIPE_OPERATING_SEED"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{marker}=PASS OUTPUT={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
