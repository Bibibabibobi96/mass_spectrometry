#!/usr/bin/env python3
"""Screen every accepted member of a frozen analytic L0 family in L1."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
import os
import platform
from pathlib import Path

import scipy

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l1 import (
    continue_fixed_e_l0_family_to_gamma,
    refine_l0_gamma_intersection,
    screen_l1_fixed_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)


def _screen_family_member(arguments: tuple[object, ...]) -> dict[str, object]:
    index, receipt, energies, position_probe_mm, angle_probe_rad = arguments
    try:
        design = MirrorL0Design(
            float(receipt["transverse_half_gap_mm"]),
            tuple(float(value) for value in receipt["transition_z_mm"]),
            tuple(float(value) for value in receipt["electrode_voltages_v"]),
            receipt.get("terminal_electrode_plane_z_mm"),
            float(receipt["electrode_voltages_v"][-1])
            if receipt.get("terminal_electrode_plane_z_mm") is not None else None,
        )
        result = screen_l1_fixed_geometry(
            design, tuple(float(value) for value in energies),
            float(position_probe_mm), float(angle_probe_rad),
        )
    except (CandidateContractError, OverflowError, ValueError) as exc:
        result = {"status": "l1_screen_failed", "failure_reason": str(exc)}
    result["l0_restart_index"] = int(index)
    result["l0_normalized_period_slopes_per_v"] = receipt.get("normalized_period_slopes_per_v")
    return result


def _refine_gamma_family_seed(arguments: tuple[object, ...]) -> dict[str, object]:
    (
        screen,
        lower_bounds,
        upper_bounds,
        energies,
        target_gamma,
        period_step,
        slope_tolerance,
        position_probe,
        angle_probe,
        gamma_tolerance,
        maximum_evaluations,
    ) = arguments
    restart_index = int(screen["l0_restart_index"])
    try:
        result = refine_l0_gamma_intersection(
            _design_from_screen(screen),
            tuple(float(value) for value in lower_bounds),
            tuple(float(value) for value in upper_bounds),
            tuple(float(value) for value in energies),
            float(target_gamma),
            float(period_step),
            float(slope_tolerance),
            float(position_probe),
            float(angle_probe),
            float(gamma_tolerance),
            int(maximum_evaluations),
        )
    except (CandidateContractError, OverflowError, ValueError) as exc:
        return {
            "status": "gamma_target_intersection_seed_rejected",
            "source_l0_restart_index": restart_index,
            "reason": str(exc),
        }
    result["source_l0_restart_index"] = restart_index
    return result


def screen_l1_family(
    l0_receipt: dict[str, object],
    energy_points_v: tuple[float, float, float],
    position_probe_mm: float,
    angle_probe_rad: float,
    maximum_workers: int,
) -> dict[str, object]:
    """Screen all L0-accepted restarts without altering their voltages."""
    receipts = l0_receipt.get("restart_receipts", [l0_receipt])
    accepted = [
        (index, receipt) for index, receipt in enumerate(receipts)
        if receipt.get("status") == "l0_voltage_family_member_not_l1_validated"
    ]
    if not accepted:
        raise CandidateContractError("L1 family screen requires at least one accepted L0 family member")
    worker_count = min(len(accepted), int(maximum_workers), os.cpu_count() or 1)
    if worker_count <= 0:
        raise CandidateContractError("L1 family screen requires a positive worker count")
    jobs = [
        (index, receipt, energy_points_v, position_probe_mm, angle_probe_rad)
        for index, receipt in accepted
    ]
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        screens = list(executor.map(_screen_family_member, jobs))

    stable = [screen for screen in screens if screen["status"] == "l1_screened_stable_not_3d_validated"]
    nominal_key = str(float(energy_points_v[1]))

    def metrics(screen: dict[str, object]) -> tuple[float, float, float, int]:
        aberration = screen["phase_averaged_time_aberration_by_energy_v"][nominal_key]["Tbar_xx"]
        maps = screen["maps_by_energy_v"].values()
        minimum_margin = min(
            1.0 - abs((item["matrix_x_alpha"][0][0] + item["matrix_x_alpha"][1][1]) / 2.0)
            for item in maps
        )
        maximum_voltage = max(abs(float(value)) for value in screen["electrode_voltages_v"])
        return (abs(float(aberration)), -minimum_margin, maximum_voltage, int(screen["l0_restart_index"]))

    provisional = min(stable, key=metrics) if stable else None
    return {
        "status": (
            "l1_family_screened_stable__selection_incomplete_peak_field_and_probe_convergence"
            if stable else "l1_family_screened_no_stable_member"
        ),
        "l0_accepted_count": len(accepted),
        "l1_stable_count": len(stable),
        "actual_parallel_workers": worker_count,
        "energy_points_v": list(energy_points_v),
        "position_probe_mm": float(position_probe_mm),
        "angle_probe_rad": float(angle_probe_rad),
        "provisional_selected_l0_restart_index": (
            int(provisional["l0_restart_index"]) if provisional is not None else None
        ),
        "provisional_selection_metrics": (
            {
                "absolute_nominal_Tbar_xx": metrics(provisional)[0],
                "minimum_stability_margin": -metrics(provisional)[1],
                "maximum_absolute_voltage_v": metrics(provisional)[2],
            }
            if provisional is not None else None
        ),
        "family_screens": screens,
        "not_evaluated": [
            "peak_mirror_field", "probe_step_convergence", "three_dimensional_fields", "simion_pa",
        ],
    }


def _design_from_screen(screen: dict[str, object]) -> MirrorL0Design:
    return MirrorL0Design(
        float(screen["family_screens_transverse_half_gap_mm"]),
        tuple(float(value) for value in screen["transition_z_mm"]),
        tuple(float(value) for value in screen["electrode_voltages_v"]),
        screen.get("terminal_electrode_plane_z_mm"),
        float(screen["electrode_voltages_v"][-1]),
    )


def select_gamma_continuation_pair(
    family_screens: list[dict[str, object]],
    target_gamma_degrees: float,
    voltage_span_v: tuple[float, float, float, float],
) -> tuple[dict[str, object], dict[str, object]]:
    """Choose the closest stable voltage-space pair that brackets gamma."""
    stable = [item for item in family_screens if item["status"] == "l1_screened_stable_not_3d_validated"]
    pairs = []
    for first_index, first in enumerate(stable):
        first_gamma = float(first["nominal_mapping"]["gamma_degrees"])
        for second in stable[first_index + 1:]:
            second_gamma = float(second["nominal_mapping"]["gamma_degrees"])
            if (first_gamma - target_gamma_degrees) * (second_gamma - target_gamma_degrees) > 0.0:
                continue
            if first["electrode_voltages_v"][-1] == second["electrode_voltages_v"][-1]:
                continue
            distance = sum(
                ((float(first["electrode_voltages_v"][index])
                  - float(second["electrode_voltages_v"][index])) / voltage_span_v[index - 1]) ** 2
                for index in range(1, 5)
            ) ** 0.5
            pairs.append((distance, first, second))
    if not pairs:
        raise CandidateContractError("no stable L0-family screen pair brackets the target gamma")
    _distance, first, second = min(pairs, key=lambda item: item[0])
    return tuple(sorted((first, second), key=lambda item: float(item["electrode_voltages_v"][-1])))


def _probe_convergence(
    root: dict[str, object],
    energies: tuple[float, float, float],
    profile: dict[str, object],
) -> dict[str, object]:
    root_design = _design_from_screen({
        **root["l0_receipt"],
        "family_screens_transverse_half_gap_mm": root["l0_receipt"]["transverse_half_gap_mm"],
    })
    convergence_screens = [
        screen_l1_fixed_geometry(
            root_design,
            energies,
            float(profile["position_probe_mm"]) * float(scale),
            float(profile["angle_probe_rad"]) * float(scale),
        )
        for scale in profile["probe_convergence_scale_factors"]
    ]
    nominal_key = str(float(energies[1]))
    records = [
        {
            "scale_factor": float(scale),
            "gamma_degrees": screen["maps_by_energy_v"][nominal_key]["gamma_degrees"],
            "Tbar_xx": screen["phase_averaged_time_aberration_by_energy_v"][nominal_key]["Tbar_xx"],
        }
        for scale, screen in zip(profile["probe_convergence_scale_factors"], convergence_screens)
    ]
    last, previous = records[-1], records[-2]
    gamma_change = abs(float(last["gamma_degrees"]) - float(previous["gamma_degrees"]))
    tbar_scale = max(abs(float(last["Tbar_xx"])), abs(float(previous["Tbar_xx"])))
    relative_tbar_change = abs(float(last["Tbar_xx"]) - float(previous["Tbar_xx"])) / tbar_scale
    passed = (
        gamma_change <= float(profile["maximum_adjacent_gamma_change_degrees"])
        and relative_tbar_change <= float(profile["maximum_adjacent_relative_Tbar_change"])
    )
    return {
        "status": "pass" if passed else "fail",
        "records": records,
        "last_adjacent_gamma_change_degrees": gamma_change,
        "last_adjacent_relative_Tbar_change": relative_tbar_change,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--l0-receipt", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    receipt = json.loads(arguments.l0_receipt.read_text(encoding="utf-8"))
    contract = load_contract(arguments.contract)
    energies = tuple(float(value) for value in contract["mirror"]["theory_requirements"]["energies_v"])
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    result = screen_l1_family(
        receipt, energies, float(profile["position_probe_mm"]), float(profile["angle_probe_rad"]),
        int(profile["maximum_parallel_workers"]),
    )
    result["input"] = {
        "l0_receipt": {
            "filename": arguments.l0_receipt.name,
            "sha256": file_sha256(arguments.l0_receipt),
        },
        "contract": {
            "filename": arguments.contract.name,
            "sha256": file_sha256(arguments.contract),
        },
    }
    result["runtime"] = {
        "python_version": platform.python_version(),
        "scipy_version": scipy.__version__,
    }
    result["l1_screen_profile"] = profile
    envelope = contract["mirror"]["theory_requirements"]["voltage_envelope_v"]
    keys = ("B", "C", "D", "E")
    lower_bounds = tuple(
        math.nextafter(max(energies), math.inf)
        if key == "E" else float(envelope[key]["minimum_inclusive_v"])
        for key in keys
    )
    upper_bounds = tuple(float(envelope[key]["maximum_inclusive_v"]) for key in keys)
    spans = tuple(high - low for low, high in zip(lower_bounds, upper_bounds))
    stable_screens = [
        screen for screen in result["family_screens"]
        if screen["status"] == "l1_screened_stable_not_3d_validated"
    ]
    for screen in stable_screens:
        screen["family_screens_transverse_half_gap_mm"] = float(receipt["transverse_half_gap_mm"])
    lower_screen, upper_screen = select_gamma_continuation_pair(
        result["family_screens"], float(profile["target_gamma_degrees"]), spans,
    )
    bracket_root = continue_fixed_e_l0_family_to_gamma(
        _design_from_screen(lower_screen), _design_from_screen(upper_screen),
        lower_bounds, upper_bounds, energies, float(profile["target_gamma_degrees"]),
        float(receipt["period_slope_derivative_step_v"]),
        float(receipt["maximum_abs_normalized_period_slope_per_v"]),
        float(profile["position_probe_mm"]), float(profile["angle_probe_rad"]),
        int(profile["continuation_node_count"]), float(profile["e_voltage_root_tolerance_v"]),
        float(profile["maximum_gamma_target_residual_degrees"]),
        int(profile["maximum_root_iterations"]), int(profile["maximum_local_function_evaluations"]),
    )
    bracket_root["source_l0_restart_indices"] = [
        int(lower_screen["l0_restart_index"]), int(upper_screen["l0_restart_index"]),
    ]
    jobs = [
        (
            screen, lower_bounds, upper_bounds, energies,
            profile["target_gamma_degrees"], receipt["period_slope_derivative_step_v"],
            receipt["maximum_abs_normalized_period_slope_per_v"], profile["position_probe_mm"],
            profile["angle_probe_rad"], profile["maximum_gamma_target_residual_degrees"],
            profile["maximum_local_function_evaluations"],
        )
        for screen in stable_screens
    ]
    worker_count = min(len(jobs), int(profile["maximum_parallel_workers"]), os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        seed_results = list(executor.map(_refine_gamma_family_seed, jobs))
    direct_roots = [
        item for item in seed_results
        if item["status"] == "gamma_target_intersection_found__probe_and_3d_validation_pending"
    ]
    raw_roots = [bracket_root, *direct_roots]
    deduplication_tolerance = float(profile["root_family_deduplication_voltage_tolerance_v"])
    roots: list[dict[str, object]] = []
    for candidate in sorted(
        raw_roots,
        key=lambda item: tuple(float(value) for value in item["l0_receipt"]["electrode_voltages_v"]),
    ):
        voltages = candidate["l0_receipt"]["electrode_voltages_v"]
        if any(
            max(abs(float(first) - float(second)) for first, second in zip(voltages, known["l0_receipt"]["electrode_voltages_v"]))
            <= deduplication_tolerance
            for known in roots
        ):
            continue
        candidate["probe_convergence"] = _probe_convergence(candidate, energies, profile)
        roots.append(candidate)
    qualified = [item for item in roots if item["probe_convergence"]["status"] == "pass"]
    if not qualified:
        raise CandidateContractError("no distinct gamma-target root passed the declared probe convergence")

    nominal_key = str(float(energies[1]))

    def selection_metrics(root: dict[str, object]) -> tuple[float, float, tuple[float, ...]]:
        aberration = root["l1_screen"]["phase_averaged_time_aberration_by_energy_v"][nominal_key]["Tbar_xx"]
        voltages = tuple(float(value) for value in root["l0_receipt"]["electrode_voltages_v"])
        return abs(float(aberration)), max(abs(value) for value in voltages), voltages

    selected = min(qualified, key=selection_metrics)
    result["gamma_target_root_family"] = {
        "status": "complete_stable_seed_intersection_family__downstream_selection_pending",
        "stable_seed_count": len(stable_screens),
        "actual_parallel_workers": worker_count,
        "bracket_continuation_root_count": 1,
        "direct_converged_seed_count": len(direct_roots),
        "raw_converged_seed_count": len(raw_roots),
        "distinct_root_count": len(roots),
        "probe_converged_root_count": len(qualified),
        "deduplication_voltage_tolerance_v": deduplication_tolerance,
        "seed_audit": seed_results,
        "roots": roots,
        "selection_semantics": "The selected mirror-only representative minimizes absolute nominal Tbar_xx and then maximum absolute voltage. Every probe-converged root remains available for downstream Stripe compatibility selection without changing the mirror equations.",
    }
    result["gamma_target_continuation"] = {
        **selected,
        "status": "gamma_target_selected_with_probe_convergence__peak_field_and_3d_validation_pending",
    }
    result["gamma_target_probe_convergence"] = selected["probe_convergence"]
    result["status"] = "l1_family_continued_to_gamma_target__peak_field_and_3d_validation_pending"
    result["limitations"] = [
        "Analytic infinite-y 2-D screening only; it includes the ideal Berdnikov terminal-electrode plane but excludes real slots, electrode thickness, sidewalls, and three-dimensional hardware.",
        "The initial transverse screen does not alter any accepted L0 restart. Every stable seed independently refines the four-variable intersection; the first three residuals remain the mirror-only L0 equations and gamma is only the L1 family-member selector.",
        "The mirror-only representative does not erase the distinct probe-converged root family. Downstream Stripe compatibility may select among those roots but may not change the mirror equations or accept a nonconverged mirror root.",
        "Finite-difference probe convergence is reported explicitly; the representative remains provisional until the analytic peak-field ranking stage is evaluated.",
        "PA, IOB, SIMION flight, grid convergence, and hardware feasibility remain unevaluated.",
    ]
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MIRROR_L1_HARDWARE_SCREEN: status={result['status']} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
