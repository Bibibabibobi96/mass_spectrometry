"""Audit a finite-3-D two-prism shooting sequence and publish its result.

The calculation consumes immutable SIMION trial manifests rather than typed
voltages.  One seed and two single-axis perturbations define the local 2x2
Jacobian; subsequent observations document the converged shooting sequence.
The result is a single-centre hand-off candidate, not K=25 or resolution
evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    classify_constraint_system,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)


RESIDUAL_NAMES = (
    "P1_P2_phase_origin_turn_y_mm",
    "P1_P2_slow_kinetic_energy_per_charge_v",
)
UNKNOWN_NAMES = ("prism_1_voltage_v", "prism_2_voltage_v")


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise CandidateContractError(f"expected a JSON object in {path}")
    return value


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _manifest_output(manifest_path: Path, filename: str) -> Path:
    manifest = _load_object(manifest_path)
    manifest_dir = manifest_path.resolve().parent
    if (
        manifest.get("status") != "success"
        or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") != "finite_3d_two_prism_voltage_trial"
    ):
        raise CandidateContractError(f"not a successful finite-3-D P1/P2 trial: {manifest_path}")
    verify_record("run_config", manifest["run_config"], base_dir=manifest_dir)
    for name, record in manifest.get("inputs", {}).items():
        verify_record(f"input {name}", record, base_dir=manifest_dir)
    matches: list[Path] = []
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        verify_record(f"output {index}", record, base_dir=manifest_dir)
        path = record_path(record, base_dir=manifest_dir)
        if path.name == filename:
            matches.append(path)
    if len(matches) != 1:
        raise CandidateContractError(
            f"trial manifest must bind exactly one {filename}: {manifest_path}"
        )
    return matches[0]


def _trial(manifest_path: Path) -> dict[str, Any]:
    observation_path = _manifest_output(manifest_path, "two_prism_trial_observation.json")
    materialization_path = _manifest_output(manifest_path, "two_prism_trial_materialization.json")
    observation = _load_object(observation_path)
    materialization = _load_object(materialization_path)
    if observation.get("status") != "phase_origin_observed":
        raise CandidateContractError(f"P1/P2 trial did not reach its phase origin: {manifest_path}")
    voltages = observation.get("prism_voltages_v")
    residuals = observation.get("residuals")
    if not isinstance(voltages, list) or len(voltages) != 2 or not isinstance(residuals, dict):
        raise CandidateContractError("P1/P2 observation lacks its voltage or residual vector")
    phase = observation.get("drift_phase_origin_state")
    if not isinstance(phase, dict):
        raise CandidateContractError("P1/P2 observation lacks its phase-origin state")
    position = phase.get("position_mm")
    velocity = phase.get("velocity_mm_per_us")
    if not isinstance(position, list) or len(position) != 3 or not isinstance(velocity, list) or len(velocity) != 3:
        raise CandidateContractError("P1/P2 phase-origin state must be three-dimensional")
    return {
        "run_id": _load_object(manifest_path).get("run_id"),
        "run_manifest_path": str(manifest_path.resolve()),
        "run_manifest_sha256": file_sha256(manifest_path),
        "observation_path": str(observation_path),
        "observation_sha256": file_sha256(observation_path),
        "materialization_sha256": file_sha256(materialization_path),
        "prism_voltages_v": [_finite(value, "prism voltage") for value in voltages],
        "residual_vector": [_finite(residuals.get(name), name) for name in RESIDUAL_NAMES],
        "phase_origin_position_mm": [_finite(value, "phase-origin position") for value in position],
        "phase_origin_velocity_mm_per_us": [_finite(value, "phase-origin velocity") for value in velocity],
        "source_identity": {
            key: materialization.get("inputs", {}).get(key)
            for key in (
                "contract_sha256",
                "reviewed_contract_sha256",
                "mirror_summary_sha256",
                "stripe_summary_sha256",
                "accelerator_receipt_sha256",
            )
        },
        "target_turn_y_mm": materialization.get("target_turn_y_mm"),
        "target_slow_kinetic_energy_per_charge_v": materialization.get(
            "target_slow_kinetic_energy_per_charge_v"
        ),
        "phase_origin_mirror_side": materialization.get("phase_origin_mirror_side"),
    }


def _same_frozen_problem(trials: Sequence[dict[str, Any]]) -> None:
    fields = (
        "source_identity",
        "target_turn_y_mm",
        "target_slow_kinetic_energy_per_charge_v",
        "phase_origin_mirror_side",
    )
    for field in fields:
        if any(trial[field] != trials[0][field] for trial in trials[1:]):
            raise CandidateContractError(f"P1/P2 trials do not share the same frozen {field}")
    if trials[0]["phase_origin_mirror_side"] != 1:
        raise CandidateContractError("manufactured P1/P2 path must use the positive-z post-P2 mirror turn")


def _natural_scales(contract: dict[str, Any]) -> tuple[list[float], list[float]]:
    try:
        energy = contract["prism_transport"]["energy_partition"]
        slow_energy = _finite(energy["drift_kinetic_energy_ev"], "drift energy")
        fast_energy = _finite(energy["fast_reflection_kinetic_energy_ev"], "fast energy")
        drift_length = _finite(
            contract["dual_stripe_l0"]["manufactured_design_abs_drift_length_L_mm"],
            "manufactured drift length",
        )
    except KeyError as error:
        raise CandidateContractError("contract lacks natural P1/P2 scaling inputs") from error
    if slow_energy <= 0.0 or fast_energy <= 0.0 or drift_length <= 0.0:
        raise CandidateContractError("natural P1/P2 scaling inputs must be positive")
    voltage_scale = math.sqrt(slow_energy * fast_energy)
    return [voltage_scale, voltage_scale], [drift_length, slow_energy]


def audit_operating_point(
    *,
    contract_path: Path,
    seed_manifest: Path,
    prism_1_perturbation_manifest: Path,
    prism_2_perturbation_manifest: Path,
    iteration_manifests: Sequence[Path],
) -> dict[str, Any]:
    """Return a rank-audited P1/P2 single-centre hand-off receipt."""
    if not iteration_manifests:
        raise CandidateContractError("P1/P2 audit needs at least one post-Jacobian iteration")
    contract = load_contract(contract_path)
    seed = _trial(seed_manifest)
    p1_trial = _trial(prism_1_perturbation_manifest)
    p2_trial = _trial(prism_2_perturbation_manifest)
    iterations = [_trial(path) for path in iteration_manifests]
    all_trials = [seed, p1_trial, p2_trial, *iterations]
    _same_frozen_problem(all_trials)

    seed_v = np.asarray(seed["prism_voltages_v"], dtype=float)
    p1_delta = np.asarray(p1_trial["prism_voltages_v"], dtype=float) - seed_v
    p2_delta = np.asarray(p2_trial["prism_voltages_v"], dtype=float) - seed_v
    if not (p1_delta[0] > 0.0 and p1_delta[1] == 0.0):
        raise CandidateContractError("P1 Jacobian trial must perturb only P1 by a positive step")
    if not (p2_delta[1] > 0.0 and p2_delta[0] == 0.0):
        raise CandidateContractError("P2 Jacobian trial must perturb only P2 by a positive step")
    if not math.isclose(float(p1_delta[0]), float(p2_delta[1]), rel_tol=0.0, abs_tol=1e-12):
        raise CandidateContractError("P1 and P2 Jacobian steps must be equal")

    seed_r = np.asarray(seed["residual_vector"], dtype=float)
    jacobian = np.column_stack((
        (np.asarray(p1_trial["residual_vector"]) - seed_r) / p1_delta[0],
        (np.asarray(p2_trial["residual_vector"]) - seed_r) / p2_delta[1],
    ))
    parameter_scales, residual_scales = _natural_scales(contract)
    rank_tolerance = _finite(
        contract["dual_stripe_l0"]["determination_numerics"]["relative_singular_value_rank_tolerance"],
        "relative singular-value rank tolerance",
    )
    classification = classify_constraint_system(
        UNKNOWN_NAMES,
        RESIDUAL_NAMES,
        jacobian_rows=jacobian.tolist(),
        residuals=seed_r.tolist(),
        parameter_scales=parameter_scales,
        residual_scales=residual_scales,
        relative_rank_tolerance=rank_tolerance,
    )
    if classification.status != "square_exact":
        raise CandidateContractError(f"P1/P2 finite-3-D Jacobian is not square exact: {classification.status}")

    predicted_first_step = -np.linalg.solve(jacobian, seed_r)
    final = iterations[-1]
    final_r = np.asarray(final["residual_vector"], dtype=float)
    if np.linalg.norm(final_r / np.asarray(residual_scales)) >= np.linalg.norm(seed_r / np.asarray(residual_scales)):
        raise CandidateContractError("P1/P2 iteration sequence did not reduce the scaled residual")

    return {
        "schema_version": 1,
        "role": "mrtof_finite_3d_two_prism_operating_point_audit",
        "status": "success",
        "qualification": "single_center_phase_space_handoff_candidate__K25_pending",
        "contract_sha256": file_sha256(contract_path),
        "unknown_names": list(UNKNOWN_NAMES),
        "residual_names": list(RESIDUAL_NAMES),
        "seed": seed,
        "jacobian_trials": [p1_trial, p2_trial],
        "finite_difference_scheme": "forward_about_solver_neutral_hard_boundary_seed",
        "finite_difference_step_v": float(p1_delta[0]),
        "physical_jacobian_rows": jacobian.tolist(),
        "parameter_scales_v": parameter_scales,
        "residual_scales": {
            RESIDUAL_NAMES[0]: residual_scales[0],
            RESIDUAL_NAMES[1]: residual_scales[1],
        },
        "scale_derivation": {
            "prism_voltage": "sqrt(drift_kinetic_energy_ev*fast_reflection_kinetic_energy_ev)",
            "phase_origin_y": "dual_stripe_l0.manufactured_design_abs_drift_length_L_mm",
            "slow_energy": "prism_transport.energy_partition.drift_kinetic_energy_ev",
        },
        "classification": asdict(classification),
        "first_linear_correction_v": predicted_first_step.tolist(),
        "iterations": iterations,
        "selected_prism_voltages_v": final["prism_voltages_v"],
        "selected_phase_origin_position_mm": final["phase_origin_position_mm"],
        "selected_phase_origin_velocity_mm_per_us": final["phase_origin_velocity_mm_per_us"],
        "selected_residuals": dict(zip(RESIDUAL_NAMES, final["residual_vector"])),
        "residual_acceptance_status": "not_declared__numeric_values_reported_without_inventing_a_tolerance",
        "next_gate": "run_the_same_single_center_source_through_the_complete_K25_event_chain",
        "limits": [
            "one center ion only",
            "finite-three-dimensional SIMION field at one mesh and time-step setting",
            "does not qualify K=25 return, detector hit, bundle transmission, TOF, FWHM, or mass resolution",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--seed-manifest", required=True, type=Path)
    parser.add_argument("--prism-1-perturbation-manifest", required=True, type=Path)
    parser.add_argument("--prism-2-perturbation-manifest", required=True, type=Path)
    parser.add_argument("--iteration-manifest", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit_operating_point(
        contract_path=args.contract,
        seed_manifest=args.seed_manifest,
        prism_1_perturbation_manifest=args.prism_1_perturbation_manifest,
        prism_2_perturbation_manifest=args.prism_2_perturbation_manifest,
        iteration_manifests=args.iteration_manifest,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "MRTOF_TWO_PRISM_OPERATING_POINT_AUDIT=PASS "
        f"P1={result['selected_prism_voltages_v'][0]:.12g} "
        f"P2={result['selected_prism_voltages_v'][1]:.12g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
