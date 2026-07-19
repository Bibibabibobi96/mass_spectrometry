"""Synthesize edge localization, interface uncertainty, and integration readiness.

This tool consumes existing solver outputs.  It does not rerun either solver and
does not treat local field convergence percentages as additive corrections to
particle-space discrepancies.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def pct(value: float) -> float:
    return 100.0 * value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", required=True, type=Path)
    parser.add_argument("--field-convergence", required=True, type=Path)
    parser.add_argument("--phase-diagnostics", required=True, type=Path)
    parser.add_argument("--internal-release", required=True, type=Path)
    parser.add_argument("--mode", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    interface = load(args.interface)
    convergence = load(args.field_convergence)
    phase = load(args.phase_diagnostics)
    internal = load(args.internal_release)
    mode = load(args.mode)
    targets = mode["candidate_acceptance_targets"]
    if int(interface["particles"]) < int(mode["numerics"]["minimum_diagnostic_particles"]):
        raise ValueError("Interface sample is below the configured diagnostic minimum.")

    simion = convergence["SIMION_0p2_to_0p1"]
    comsol = convergence["COMSOL_mesh1_to_hmax0p5"]
    region_rows: list[dict[str, Any]] = []
    for region in ("entrance_fringe", "rod_region", "exit_fringe_and_detector"):
        region_rows.append({
            "region": region,
            "simion_self_change_pct": pct(simion[region]["vector_relative_rms"]),
            "comsol_self_change_pct": pct(comsol[region]["vector_relative_rms"]),
        })

    edge = {
        "schema_version": 1,
        "status": "PASS",
        "purpose": "evidence synthesis and localization, not model acceptance",
        "field_spatial_convergence": region_rows,
        "baseline_trajectory": {
            "difference_onset_z_mm": phase["transverse_difference_onset"]["mean_distance_ge_0.01_mm_z_mm"],
            "rod_entry_mean_distance_mm": phase["plane_metrics"]["rod_entry"]["mean_transverse_distance_mm"],
            "rod_exit_mean_distance_mm": phase["plane_metrics"]["rod_exit"]["mean_transverse_distance_mm"],
            "handoff_mean_distance_mm": phase["plane_metrics"]["exit_enclosure_front"]["mean_transverse_distance_mm"],
        },
        "entrance_bypassed_control": {
            "internal_window_end_mean_distance_mm": internal["plane_metrics"]["internal_window_end"]["mean_transverse_distance_mm"],
            "rod_exit_mean_distance_mm": internal["plane_metrics"]["rod_exit"]["mean_transverse_distance_mm"],
            "handoff_onset_0p2_mm_z_mm": internal["transverse_difference_onset"]["mean_distance_ge_0.2_mm_z_mm"],
        },
        "interpretation": {
            "entrance": "Baseline difference begins in the entrance transition; both solvers are spatially sensitive there.",
            "rod_interior": "The entrance-bypassed control remains nearly coincident through the internal window.",
            "exit": "The remaining difference grows again near the rod exit and handoff enclosure.",
            "scope": "This identifies the causal path at engineering resolution; it does not assign a closed-source interpolation defect or demand pointwise equality.",
        },
    }

    observed = interface["comparison"]
    target_checks = {
        "transmission": observed["transmission_absolute_difference"] <= targets["cross_solver_transmission_absolute_difference"],
        "mean_tof": observed["mean_tof_relative_difference"] <= targets["cross_solver_relative_mean_tof_difference"],
        "rms_radius": observed["rms_radius_relative_difference"] <= targets["cross_solver_relative_rms_output_radius_difference"],
        "rms_divergence": observed["rms_divergence_relative_difference"] <= targets["cross_solver_relative_rms_divergence_difference"],
        "mean_energy": observed["mean_energy_relative_difference"] <= targets["cross_solver_relative_mean_energy_difference"],
    }
    budget = {
        "schema_version": 1,
        "status": "PASS" if all(target_checks.values()) else "FAIL",
        "particles": interface["particles"],
        "observed_interface_differences": {
            "transmission_absolute": observed["transmission_absolute_difference"],
            "mean_tof_pct": pct(observed["mean_tof_relative_difference"]),
            "rms_radius_pct": pct(observed["rms_radius_relative_difference"]),
            "rms_divergence_pct": pct(observed["rms_divergence_relative_difference"]),
            "mean_energy_pct": pct(observed["mean_energy_relative_difference"]),
        },
        "configured_target_checks": target_checks,
        "numerical_evidence": {
            "field_convergence_by_region": region_rows,
            "time_integration": "Previously refined independently in both solvers and excluded as the dominant cause.",
            "sampling": "N=100 satisfies the diagnostic contract but does not establish a universal high-precision uncertainty interval.",
        },
        "budget_policy": {
            "additive_correction_allowed": False,
            "reason": "Local field RMS changes, phase accumulation, and output phase-space metrics are different observables and are nonlinearly coupled.",
            "usable_conclusion": "The present discrepancy is larger than the configured interface targets and remains edge-sensitive; it cannot be waived by subtracting mesh percentages.",
        },
        "alternative_functional_criterion": {
            "status": "NOT_EVALUATED",
            "required_test": "Propagate both exported handoff phase-space ensembles through the same frozen downstream oa-TOF acceptance model and compare downstream transmission and performance against predeclared tolerances.",
            "why_not_available": "No frozen RF-to-oa-TOF transform and downstream acceptance contract currently exists.",
        },
    }

    strict_pass = all(target_checks.values())
    functional_pass = budget["alternative_functional_criterion"]["status"] == "PASS"
    verdict = "PASS" if strict_pass else ("CONDITIONAL_PASS" if functional_pass else "FAIL")
    gate = {
        "schema_version": 1,
        "status": verdict,
        "gate": "rf_quadrupole_to_oa_tof_integration_candidate",
        "regression_status": "PASS" if all(interface["regression_gates"].values()) else "FAIL",
        "strict_interface_status": "PASS" if strict_pass else "FAIL",
        "functional_alternative_status": budget["alternative_functional_criterion"]["status"],
        "package_generation_allowed": verdict in {"PASS", "CONDITIONAL_PASS"},
        "decision": "Do not generate or connect an oa-TOF integration package yet." if verdict == "FAIL" else "Candidate packaging may proceed within the stated scope.",
        "closure_path": [
            "Keep the existing component regression unchanged.",
            "If strict phase-space agreement is required, refine or redesign the entrance/exit edge representation and rerun the same N=100 gate.",
            "If downstream function is the real requirement, first freeze the transform and oa-TOF acceptance contract, then evaluate the alternative criterion without tuning either solver to match.",
        ],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write(args.output_dir / "edge_localization.json", edge)
    write(args.output_dir / "interface_error_budget.json", budget)
    write(args.output_dir / "oatof_integration_gate.json", gate)
    print(f"EDGE_LOCALIZATION={edge['status']}")
    print(f"INTERFACE_ERROR_BUDGET={budget['status']}")
    print(f"OATOF_INTEGRATION_GATE={gate['status']}")


if __name__ == "__main__":
    main()
