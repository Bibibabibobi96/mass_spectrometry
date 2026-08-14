"""Audit local timing order with the governed all-ideal oaTOF theory APIs."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    select_profile,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
    accelerator_state,
    time_to_fixed_plane_s,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import (
    coupled_flight_time_s,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _bound_file(root: Path, record: Mapping[str, Any], label: str) -> Path:
    path = (root / str(record["path"])).resolve()
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{label} byte count differs: {path}")
    if file_sha256(path) != str(record["sha256"]).upper():
        raise ValueError(f"{label} SHA-256 differs: {path}")
    return path


def _bound_json(
    root: Path, record: Mapping[str, Any], label: str
) -> tuple[Path, dict[str, Any]]:
    path = _bound_file(root, record, label)
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return path, value


def _rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean((values - np.mean(values)) ** 2)))


def _relative_difference(left: float, right: float, floor: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), floor)


def _richardson(raw_large: float, raw_half: float) -> float:
    return (4.0 * raw_half - raw_large) / 3.0


def _effect_agrees(
    reference: float,
    observed: float,
    step_mm: float,
    order: int,
    relative_tolerance: float,
    absolute_effect_floor_s: float,
) -> bool:
    difference_effect = abs(reference - observed) * step_mm**order
    scale_effect = max(abs(reference), abs(observed)) * step_mm**order
    return difference_effect <= max(
        relative_tolerance * scale_effect, absolute_effect_floor_s
    )


def _numeric_order_audit(
    time_s: Callable[[float], float],
    half_width_mm: float,
    step_fractions: Sequence[float],
    c1_s_per_mm: float,
    c2_s_per_mm2: float,
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    steps = [half_width_mm * float(value) for value in step_fractions]
    if not (
        len(steps) >= 3
        and steps[0] > steps[1] > steps[2] > 0.0
        and np.allclose(np.asarray(steps[:-1]) / 2.0, steps[1:])
    ):
        raise ValueError("derivative steps must be three descending halvings")
    center = time_s(0.0)
    rows = []
    for step in steps:
        plus = time_s(step)
        minus = time_s(-step)
        odd = (plus - minus) / 2.0
        even = (plus + minus) / 2.0 - center
        rows.append(
            {
                "step_mm": step,
                "odd_time_s": odd,
                "even_time_s": even,
                "raw_c1_s_per_mm": odd / step,
                "raw_c2_s_per_mm2": even / step**2,
                "raw_c3_after_d1_s_per_mm3": (odd - c1_s_per_mm * step)
                / step**3,
                "raw_c4_after_d2_s_per_mm4": (even - c2_s_per_mm2 * step**2)
                / step**4,
            }
        )
    c1_richardson = [
        _richardson(rows[index]["raw_c1_s_per_mm"], rows[index + 1]["raw_c1_s_per_mm"])
        for index in range(len(rows) - 1)
    ]
    c2_richardson = [
        _richardson(rows[index]["raw_c2_s_per_mm2"], rows[index + 1]["raw_c2_s_per_mm2"])
        for index in range(len(rows) - 1)
    ]
    c3_richardson = [
        _richardson(
            rows[index]["raw_c3_after_d1_s_per_mm3"],
            rows[index + 1]["raw_c3_after_d1_s_per_mm3"],
        )
        for index in range(len(rows) - 1)
    ]
    c4_richardson = [
        _richardson(
            rows[index]["raw_c4_after_d2_s_per_mm4"],
            rows[index + 1]["raw_c4_after_d2_s_per_mm4"],
        )
        for index in range(len(rows) - 1)
    ]
    floor_effect = (
        float(thresholds["numeric_floor_multiplier"])
        * float(thresholds["absolute_time_floor_s"])
    )
    smallest_step = steps[-1]
    d1_agrees = _effect_agrees(
        c1_s_per_mm,
        c1_richardson[-1],
        smallest_step,
        1,
        float(thresholds["d1_d2_effect_relative_agreement"]),
        floor_effect,
    )
    d2_agrees = _effect_agrees(
        c2_s_per_mm2,
        c2_richardson[-1],
        smallest_step,
        2,
        float(thresholds["d1_d2_effect_relative_agreement"]),
        floor_effect,
    )

    def convergence(values: Sequence[float], order: int) -> dict[str, Any]:
        significant = abs(values[-1]) * smallest_step**order > floor_effect
        converged = _effect_agrees(
            values[-2],
            values[-1],
            smallest_step,
            order,
            float(thresholds["richardson_effect_relative_convergence"]),
            floor_effect,
        )
        return {
            "values": list(values),
            "small_step_value": float(values[-1]),
            "significant_above_numeric_floor": significant,
            "converged": converged,
            "status": (
                "CONVERGED_NUMERIC_TAYLOR_COEFFICIENT_AUDIT"
                if significant and converged
                else "NOT_RESOLVED_NUMERIC_FLOOR"
                if not significant
                else "NOT_CONVERGED"
            ),
        }

    return {
        "interpretation": (
            "D1_D2_are_solver_authorities; c3_equals_T3_over_3_factorial_and_"
            "c4_equals_T4_over_4_factorial_are_symmetric_multistep_Richardson_"
            "numeric_Taylor_coefficient_audits_not_analytic_authorities"
        ),
        "steps": rows,
        "solver_authority": {
            "c1_s_per_mm": c1_s_per_mm,
            "c2_s_per_mm2": c2_s_per_mm2,
        },
        "d1_numeric_audit": {
            "richardson_values_s_per_mm": c1_richardson,
            "agrees_with_solver_authority": d1_agrees,
        },
        "d2_numeric_audit": {
            "richardson_values_s_per_mm2": c2_richardson,
            "agrees_with_solver_authority": d2_agrees,
        },
        "c3_numeric_taylor_coefficient_audit": convergence(c3_richardson, 3),
        "c4_numeric_taylor_coefficient_audit": convergence(c4_richardson, 4),
    }


def _compile_width(
    width_mm: float,
    campaign: Mapping[str, Any],
    base_geometry: Mapping[str, Any],
    port: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    base_profile = select_profile(
        dict(registry), str(campaign["base_layout_profile_id"])
    )
    profile = copy.deepcopy(base_profile)
    width_token = str(width_mm).replace(".", "p")
    profile["layout_profile_id"] = f"theory_order_long_{width_token}mm"
    profile["architecture_generation_id"] = (
        f"theory_order_long_{width_token}mm_independently_matched_v1"
    )
    profile["finite_interval_source_full_width_mm"] = width_mm
    geometry, _, _ = compile_geometry_and_port(
        copy.deepcopy(dict(base_geometry)), copy.deepcopy(dict(port)), profile
    )
    accelerator_derivation = geometry["geometry_derivation"]["accelerator"]
    theory = accelerator_derivation["finite_interval_theory"]
    coupled = theory["coupled_reflectron"]
    phase = theory["solver_phase_space_input"]
    if (
        float(theory["source_full_width_mm"]) != width_mm
        or float(phase["mean_initial_velocity_m_per_s"]) != 0.0
        or float(phase["velocity_slope_m_per_s_per_mm"]) != 0.0
        or float(phase["mass_to_charge_Th"]) != float(campaign["mass_to_charge_Th"])
    ):
        raise ValueError("compiled width arm differs from true-zero theory contract")
    if (
        coupled["accelerator_third_derivative_at_focus"] is not None
        or coupled["total_third_derivative"] is not None
    ):
        raise ValueError("ZERO-MATCH unexpectedly published an analytic third derivative")
    accelerator = accelerator_state(
        float(theory["repeller_v"]),
        float(theory["intermediate_v"]),
        float(accelerator_derivation["d1_mm"]),
        float(accelerator_derivation["d2_mm"]),
        exit_v=float(theory["exit_v"]),
        release_position_mm=float(theory["source_center_mm"]),
        require_downstream_focus=False,
    )
    mass = float(campaign["mass_to_charge_Th"])
    field1 = float(theory["stage1_field_v_per_mm"])
    source_center = float(theory["source_center_mm"])

    def detector_time(offset_mm: float) -> float:
        energy = float(theory["repeller_v"]) - field1 * (source_center + offset_mm)
        return coupled_flight_time_s(
            energy,
            mass,
            accelerator,
            float(coupled["upstream_from_accelerator_focus_mm"]),
            float(coupled["downstream_to_detector_mm"]),
            float(coupled["stage1_voltage_drop_v"]),
            float(coupled["stage1_field_v_per_mm"]),
            float(coupled["stage2_field_v_per_mm"]),
        )

    def focus_time(offset_mm: float) -> float:
        return time_to_fixed_plane_s(
            float(theory["repeller_v"]),
            float(theory["intermediate_v"]),
            float(accelerator_derivation["d1_mm"]),
            float(accelerator_derivation["d2_mm"]),
            source_center + offset_mm,
            0.0,
            float(theory["focus_drift_mm"]),
            mass,
            exit_v=float(theory["exit_v"]),
        )

    factor_s_per_mm_sqrt_v = 1.0e-3 * math.sqrt(
        mass * ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C / 2.0
    )
    c1 = (
        factor_s_per_mm_sqrt_v
        * float(coupled["total_first_derivative_residual"])
        * -field1
    )
    c2 = (
        factor_s_per_mm_sqrt_v
        * 0.5
        * float(coupled["total_second_derivative_residual"])
        * field1**2
    )
    thresholds = campaign["thresholds"]
    derivative = _numeric_order_audit(
        detector_time,
        width_mm / 2.0,
        campaign["derivative_step_fractions_of_half_width"],
        c1,
        c2,
        thresholds,
    )
    sample_metrics: dict[str, Any] = {}
    for count in campaign["uniform_sample_counts"]:
        offsets = np.linspace(-width_mm / 2.0, width_mm / 2.0, int(count))
        detector_times = np.asarray([detector_time(value) for value in offsets])
        focus_times = np.asarray([focus_time(value) for value in offsets])
        sample_metrics[str(count)] = {
            "detector_population_sigma_s": _rms(detector_times),
            "detector_full_span_s": float(np.ptp(detector_times)),
            "accelerator_focus_population_sigma_s": _rms(focus_times),
            "accelerator_focus_full_span_s": float(np.ptp(focus_times)),
        }
    first_count, second_count = (str(value) for value in campaign["uniform_sample_counts"])
    sample_convergence = _relative_difference(
        sample_metrics[first_count]["detector_population_sigma_s"],
        sample_metrics[second_count]["detector_population_sigma_s"],
        float(thresholds["absolute_time_floor_s"]),
    )

    nested = []
    dense_count = int(campaign["uniform_sample_counts"][-1])
    for fraction in campaign["nested_width_fractions"]:
        nested_width = width_mm * float(fraction)
        offsets = np.linspace(-nested_width / 2.0, nested_width / 2.0, dense_count)
        times = np.asarray([detector_time(value) for value in offsets])
        nested.append(
            {
                "width_fraction": float(fraction),
                "full_width_mm": nested_width,
                "population_sigma_s": _rms(times),
                "full_span_s": float(np.ptp(times)),
            }
        )
    scaling_exponents = []
    for left, right in zip(nested[:-1], nested[1:], strict=True):
        exponent = math.log(
            right["population_sigma_s"] / left["population_sigma_s"]
        ) / math.log(right["full_width_mm"] / left["full_width_mm"])
        scaling_exponents.append(exponent)

    offsets = np.linspace(-width_mm / 2.0, width_mm / 2.0, dense_count)
    times = np.asarray([detector_time(value) for value in offsets])
    low = c1 * offsets + c2 * offsets**2
    high = times - detector_time(0.0) - low
    total_rms = _rms(times)
    low_ratio = _rms(low) / total_rms
    high_ratio = _rms(high) / total_rms
    c3 = float(
        derivative["c3_numeric_taylor_coefficient_audit"]["small_step_value"]
    )
    c4 = float(
        derivative["c4_numeric_taylor_coefficient_audit"]["small_step_value"]
    )

    def reconstruction(candidate: np.ndarray) -> dict[str, float]:
        high_centered = high - np.mean(high)
        candidate_centered = candidate - np.mean(candidate)
        residual = high_centered - candidate_centered
        denominator = float(np.sum(high_centered**2))
        return {
            "captured_fraction_of_high_order_sse": 1.0
            - float(np.sum(residual**2)) / denominator,
            "residual_rms_fraction_of_high_order": _rms(residual) / _rms(high),
        }

    third = reconstruction(c3 * offsets**3)
    fourth = reconstruction(c4 * offsets**4)
    combined = reconstruction(c3 * offsets**3 + c4 * offsets**4)
    checks = {
        "sample_rms_converged": sample_convergence
        <= float(thresholds["sample_rms_relative_convergence"]),
        "d1_agrees_with_solver": derivative["d1_numeric_audit"][
            "agrees_with_solver_authority"
        ],
        "d2_agrees_with_solver": derivative["d2_numeric_audit"][
            "agrees_with_solver_authority"
        ],
        "high_order_rms_ratio": high_ratio
        >= float(thresholds["minimum_high_order_rms_ratio"]),
        "low_order_rms_ratio": low_ratio
        <= float(thresholds["maximum_low_order_rms_ratio"]),
        "nested_sigma_exponent": min(scaling_exponents)
        >= float(thresholds["minimum_nested_sigma_exponent"]),
    }
    return {
        "source_full_width_mm": width_mm,
        "layout_profile_id": profile["layout_profile_id"],
        "independent_theory_match": {
            "repeller_v": float(theory["repeller_v"]),
            "intermediate_v": float(theory["intermediate_v"]),
            "focus_drift_mm": float(theory["focus_drift_mm"]),
            "reflectron_stage1_voltage_drop_v": float(coupled["stage1_voltage_drop_v"]),
            "reflectron_stage2_field_v_per_mm": float(coupled["stage2_field_v_per_mm"]),
            "total_first_derivative_residual": float(
                coupled["total_first_derivative_residual"]
            ),
            "total_second_derivative_residual": float(
                coupled["total_second_derivative_residual"]
            ),
            "total_third_derivative": None,
        },
        "sample_metrics": sample_metrics,
        "sample_rms_relative_difference": sample_convergence,
        "nested_width_metrics": nested,
        "nested_sigma_log_slopes": scaling_exponents,
        "local_order_audit": derivative,
        "physical_low_vs_high_order": {
            "low_order_definition": "solver_D1_times_u_plus_solver_D2_over_2_times_u_squared",
            "high_order_definition": "complete_T_of_z_minus_T0_minus_low_order",
            "low_order_rms_ratio": low_ratio,
            "third_and_higher_rms_ratio": high_ratio,
            "numeric_c3_taylor_term_reconstruction": third,
            "numeric_c4_taylor_term_reconstruction": fourth,
            "numeric_c3_plus_c4_taylor_term_reconstruction": combined,
        },
        "checks": checks,
    }


def compute_theory_order_report(
    campaign_path: Path, *, workspace_root: Path = REPOSITORY_ROOT
) -> dict[str, Any]:
    campaign = load_json(campaign_path)
    validate_schema(campaign, "rf_oatof_theory_order_stage_campaign.schema.json")
    json_inputs = {
        name: record
        for name, record in campaign["inputs"].items()
        if name != "finite_interval_compiler_policy"
    }
    bound = {
        name: _bound_json(workspace_root, record, name)
        for name, record in json_inputs.items()
    }
    policy_record = campaign["inputs"].get("finite_interval_compiler_policy")
    if policy_record is not None:
        policy_path = _bound_file(
            workspace_root, policy_record, "finite_interval_compiler_policy"
        )
        expected_policy_path = (
            workspace_root
            / "projects/single_reflection_oa_tof_mass_analyzer/analysis/"
            "finite_interval_design_compiler.py"
        ).resolve()
        if policy_path != expected_policy_path:
            raise ValueError("finite-interval compiler policy path differs")
        bound["finite_interval_compiler_policy"] = (policy_path, None)
    arms = [
        _compile_width(
            float(width),
            campaign,
            bound["base_geometry"][1],
            bound["accelerator_entry_port"][1],
            bound["layout_profile_registry"][1],
        )
        for width in campaign["source_widths_mm"]
    ]
    target = arms[-1]
    all_contract_checks = all(
        arm["checks"]["sample_rms_converged"]
        and arm["checks"]["d1_agrees_with_solver"]
        and arm["checks"]["d2_agrees_with_solver"]
        for arm in arms
    )
    target_c3 = target["local_order_audit"][
        "c3_numeric_taylor_coefficient_audit"
    ]
    target_c4 = target["local_order_audit"][
        "c4_numeric_taylor_coefficient_audit"
    ]
    coefficient_resolved = (
        target_c3["status"] == "CONVERGED_NUMERIC_TAYLOR_COEFFICIENT_AUDIT"
        or target_c4["status"] == "CONVERGED_NUMERIC_TAYLOR_COEFFICIENT_AUDIT"
    )
    terminal_coefficient_significant = (
        target_c3["significant_above_numeric_floor"]
        or target_c4["significant_above_numeric_floor"]
    )
    dominance = (
        target["checks"]["high_order_rms_ratio"]
        and target["checks"]["low_order_rms_ratio"]
        and target["checks"]["nested_sigma_exponent"]
    )
    thresholds = campaign["thresholds"]
    dense_count = str(campaign["uniform_sample_counts"][-1])
    cross_arm_scaling = []
    for left, right in zip(arms[:-1], arms[1:], strict=True):
        left_sigma = left["sample_metrics"][dense_count][
            "detector_population_sigma_s"
        ]
        right_sigma = right["sample_metrics"][dense_count][
            "detector_population_sigma_s"
        ]
        exponent = math.log(right_sigma / left_sigma) / math.log(
            right["source_full_width_mm"] / left["source_full_width_mm"]
        )
        cross_arm_scaling.append(
            {
                "left_width_mm": left["source_full_width_mm"],
                "right_width_mm": right["source_full_width_mm"],
                "sigma_log_width_exponent": exponent,
            }
        )
    cross_arm_scaling_passed = all(
        float(thresholds["minimum_cross_arm_sigma_exponent"])
        <= row["sigma_log_width_exponent"]
        <= float(thresholds["maximum_cross_arm_sigma_exponent"])
        for row in cross_arm_scaling
    )
    passed = (
        all_contract_checks
        and coefficient_resolved
        and terminal_coefficient_significant
        and dominance
        and cross_arm_scaling_passed
    )
    high = target["physical_low_vs_high_order"]
    third_supported = (
        target_c3["status"] == "CONVERGED_NUMERIC_TAYLOR_COEFFICIENT_AUDIT"
        and high["numeric_c3_taylor_term_reconstruction"]["captured_fraction_of_high_order_sse"]
        >= float(thresholds["minimum_single_order_captured_fraction"])
        and high["numeric_c3_taylor_term_reconstruction"]["residual_rms_fraction_of_high_order"]
        <= float(thresholds["maximum_single_order_residual_fraction"])
    )
    fourth_supported = (
        target_c4["status"] == "CONVERGED_NUMERIC_TAYLOR_COEFFICIENT_AUDIT"
        and high["numeric_c4_taylor_term_reconstruction"]["captured_fraction_of_high_order_sse"]
        >= float(thresholds["minimum_single_order_captured_fraction"])
        and high["numeric_c4_taylor_term_reconstruction"]["residual_rms_fraction_of_high_order"]
        <= float(thresholds["maximum_single_order_residual_fraction"])
    )
    report = {
        "schema_version": 1,
        "role": "rf_oatof_theory_order_stage_report",
        "status": (
            "PROVISIONAL_THRESHOLDS_PASSED"
            if passed
            else "PROVISIONAL_THRESHOLDS_NOT_PASSED"
        ),
        "evidence_level": "PROVISIONAL",
        "solver_execution_performed": False,
        "campaign": {
            "path": str(campaign_path.resolve()),
            "sha256": file_sha256(campaign_path.resolve()),
        },
        "input_evidence": {
            name: dict(campaign["inputs"][name]) for name in sorted(bound)
        },
        "arms": arms,
        "cross_arm_sigma_scaling": cross_arm_scaling,
        "declared_provisional_assessment": {
            "all_width_contract_checks_passed": all_contract_checks,
            "target_2p2mm_numeric_c3_or_c4_resolved": coefficient_resolved,
            "target_2p2mm_terminal_c3_or_c4_significant_above_numeric_floor":
            terminal_coefficient_significant,
            "cross_arm_sigma_exponents_within_2p7_to_3p3":
            cross_arm_scaling_passed,
            "target_2p2mm_third_and_higher_dominance_supported": dominance,
            "target_2p2mm_numeric_c3_term_dominance_supported": third_supported,
            "target_2p2mm_numeric_c4_term_dominance_supported": fourth_supported,
            "allowed_claim": (
                "SUPPORTED_NUMERIC_LOCAL_THIRD_AND_HIGHER_DOMINANCE"
                if passed
                else "THEORY_ORDER_DOMINANCE_NOT_SUPPORTED"
            ),
            "authority_limit": (
                "D1_D2_solver_authoritative; c3=T'''/3! and c4=T''''/4! are_"
                "symmetric_multistep_Richardson_numeric_Taylor_coefficient_"
                "audits_only"
            ),
        },
        "claim_limit": campaign["claim_limit"],
    }
    validate_schema(report, "rf_oatof_theory_order_stage_report.schema.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = compute_theory_order_report(arguments.campaign)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"THEORY_ORDER_STAGE={report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
