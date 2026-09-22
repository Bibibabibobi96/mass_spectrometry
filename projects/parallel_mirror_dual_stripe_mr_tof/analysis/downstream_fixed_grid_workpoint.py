"""Audit one fixed-grid S1/S2/P1/P2 finite-3-D workpoint step.

The five input runs are one baseline and four positive single-axis voltage
perturbations.  They must share geometry, source, mirror, accelerator, target K,
and trajectory numerics.  This module does not launch SIMION; it turns those
immutable observations into a rank-audited, bounded linear correction.  A
previous fine-grid Jacobian may also be transported to a new baseline when the
field geometry, mesh, mirror/Stripe authority, targets, and energy are
unchanged.  That path is only a seed: it always requires one real center-flight
confirmation before the proposal can be accepted.
"""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import asdict
import json
import math
import re
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    classify_constraint_system,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
    _load_object,
)


def _trajectory_physics_identity(manifest: Mapping[str, Any], raw_sha256: str) -> str:
    """Hash trajectory settings that affect a flight, excluding acceptance only."""
    record = manifest.get("inputs", {}).get("trajectory_numerics_contract")
    if not isinstance(record, Mapping):
        raise CandidateContractError("trial manifest lacks its trajectory numerics contract")
    path = record_path(record)
    verify_record("trajectory_numerics_contract", record, base_dir=path.parent)
    if file_sha256(path).lower() != str(raw_sha256).lower():
        raise CandidateContractError("trial trajectory contract identity differs from materialization")
    contract = _load_object(path)
    try:
        automatic = contract["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]
        acceptance = automatic.pop("acceptance_tolerances")
    except (KeyError, AttributeError) as exc:
        raise CandidateContractError("trajectory contract lacks automatic-iteration acceptance tolerances") from exc
    if not isinstance(acceptance, Mapping):
        raise CandidateContractError("trajectory acceptance tolerances must be an object")
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


UNKNOWN_NAMES = (
    "stripe_1_voltage_v",
    "stripe_2_voltage_v",
    "prism_1_voltage_v",
    "prism_2_voltage_v",
)
RESIDUAL_NAMES = (
    "P1_P2_positive_mirror_turn_y_mm",
    "P1_P2_P2_shield_low_field_signed_vy_over_vz",
    "Stripe_slow_turn_y_minus_L_mm",
    "Stripe_target_phase_y_minus_origin_mm",
)


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def native_bank_identity(receipt: Mapping[str, Any]) -> dict[str, str]:
    """Return stable scientific identity, excluding private per-flight paths."""
    if (receipt.get("schema_version") != 1
            or receipt.get("role") != "mrtof_private_native_corridor_family"
            or receipt.get("status") != "prepared"
            or receipt.get("response_refine_performed") is not False
            or receipt.get("published_native_members_opened") is not False
            or receipt.get("controller_refine") != "solutions={0}"):
        raise CandidateContractError("native corridor runtime receipt is invalid")
    result = {}
    for name in ("cache_key", "generation_sha256"):
        value = receipt.get(name)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
            raise CandidateContractError(f"native corridor receipt lacks {name}")
        result[name] = value.upper()
    return result


def _trial(manifest_path: Path, freeze_dir: Path | None = None, *, require_target_phase: bool = True) -> dict[str, Any]:
    """Read the named observation projection; do not rehash unused PA payloads."""
    manifest = _load_object(manifest_path)
    if (manifest.get("status") != "success"
            or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
            or manifest.get("mode") != "finite_3d_two_prism_voltage_trial"):
        raise CandidateContractError(f"not a successful downstream trial: {manifest_path}")
    records = {"run_config": manifest["run_config"]}
    for filename in ("two_prism_trial_observation.json", "two_prism_trial_materialization.json"):
        matches = [record for record in manifest["outputs"]
                   if record_path(record, base_dir=manifest_path.parent).name == filename]
        if len(matches) != 1:
            raise CandidateContractError(f"trial must bind exactly one {filename}")
        records[filename] = matches[0]
    native_records = [record for record in manifest["outputs"]
                      if record_path(record, base_dir=manifest_path.parent).name == "native_corridor_runtime_family.json"]
    if len(native_records) > 1:
        raise CandidateContractError("trial binds duplicate native corridor receipts")
    if native_records:
        records["native_corridor_runtime_family.json"] = native_records[0]
    documents = {}
    for name, record in records.items():
        path = record_path(record, base_dir=manifest_path.parent)
        if freeze_dir is not None:
            freeze_dir.mkdir(parents=True, exist_ok=True)
            destination = freeze_dir / path.name
            shutil.copyfile(path, destination)
            record = {**record, "path": str(destination)}
            path = destination
        verify_record(name, record, base_dir=manifest_path.parent)
        documents[name] = _load_object(path)
    if freeze_dir is not None:
        shutil.copyfile(manifest_path, freeze_dir / "run_manifest.json")
    parameters = documents["run_config"].get("parameters", {})
    native_mode = parameters.get("pa_binding_mode") == "native_corridor_private_fast_adjust_family__four_instances__n1"
    if native_mode != bool(native_records):
        raise CandidateContractError("native corridor binding mode and receipt disagree")
    bank_identity = native_bank_identity(documents["native_corridor_runtime_family.json"]) if native_mode else None
    observation = documents["two_prism_trial_observation.json"]
    materialization = documents["two_prism_trial_materialization.json"]
    if require_target_phase and observation.get("status") not in {"full_drift_observed", "target_phase_observed", "detected"}:
        raise CandidateContractError("downstream workpoint trial must observe the target drift phase")
    stripes = materialization.get("stripe_biases_v")
    prisms = observation.get("prism_voltages_v")
    if prisms != materialization.get("prism_voltages_v"):
        raise CandidateContractError("observed prism voltages differ from materialization")
    residuals = observation.get("residuals")
    if not isinstance(stripes, list) or len(stripes) != 2 or not isinstance(prisms, list) or len(prisms) != 2:
        raise CandidateContractError("downstream workpoint trial lacks four electrode voltages")
    if require_target_phase and not isinstance(residuals, dict):
        raise CandidateContractError("downstream workpoint trial lacks its residual map")
    inputs = materialization.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("downstream workpoint trial lacks frozen input identities")
    inputs = dict(inputs)
    raw_trajectory_identity = inputs.pop("trajectory_contract_sha256", None)
    if raw_trajectory_identity is None:
        # Legacy non-native trial fixtures predate the trajectory contract
        # input.  Their complete input map remains the strict identity.
        pass
    elif not isinstance(raw_trajectory_identity, str) or not raw_trajectory_identity:
        raise CandidateContractError("downstream workpoint trial has an invalid trajectory contract identity")
    else:
        inputs["trajectory_physics_contract_sha256"] = _trajectory_physics_identity(
            manifest, raw_trajectory_identity
        )
    target_names = (
        "target_drift_period_ratio",
        "target_positive_mirror_turn_y_mm",
        "target_low_field_tangent_ratio_vy_over_vz",
        "target_slow_turn_y_mm",
    )
    return {
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": file_sha256(manifest_path),
        "consumer_projection": {
            "id": "mrtof_downstream_workpoint_observation",
            "records": records,
            "scope": "run_config_and_two_trial_json_outputs__not_full_PA_verification",
        },
        "voltages_v": [_finite(value, "downstream voltage") for value in (*stripes, *prisms)],
        "residual_vector": ([_finite(residuals.get(name), name) for name in RESIDUAL_NAMES]
                            if require_target_phase else []),
        "frozen_problem": {
            "native_bank_identity": bank_identity,
            "inputs": inputs,
            "targets": {name: _finite(materialization.get(name), name) for name in target_names},
            "source_position_project_mm": materialization.get("source_position_project_mm"),
            "source_direction_project": materialization.get("source_direction_project"),
            "trajectory_profile": materialization.get("trajectory_profile"),
            "accelerator_pulse": materialization.get("accelerator_pulse"),
            "mirror_voltages_v": materialization["mirror_voltages_v"],
            "selected_axial_energy_per_charge_v": materialization["selected_axial_energy_per_charge_v"],
            "source_slow_kinetic_energy_per_charge_v": materialization["source_slow_kinetic_energy_per_charge_v"],
            "fly2_sha256": materialization["fly2_sha256"],
            "drift_phase_contract": materialization["drift_phase_contract"],
            "local_region_mesh_mm_per_gu": documents["run_config"]["parameters"]["local_region_mesh_mm_per_gu"],
        },
    }


def assert_trial_matches_jacobian(proposal: Mapping[str, Any], child_manifest: Path) -> dict[str, Any]:
    """Bind each real observation to the audited baseline's physical problem."""
    baseline_name = proposal.get("baseline_manifest")
    if not isinstance(baseline_name, str) or not baseline_name:
        raise CandidateContractError("initial Jacobian lacks its baseline manifest")
    baseline_path = Path(baseline_name)
    consumed = proposal.get("consumed_trials", [])
    matches = [item for item in consumed if isinstance(item, Mapping)
               and Path(str(item.get("manifest", ""))).resolve() == baseline_path.resolve()]
    if len(matches) != 1 or str(matches[0].get("manifest_sha256", "")).lower() != file_sha256(baseline_path).lower():
        raise CandidateContractError("initial Jacobian baseline manifest identity differs")
    baseline = _trial(baseline_path)
    child = _trial(child_manifest, require_target_phase=False)
    expected, actual = baseline["frozen_problem"], child["frozen_problem"]
    if expected != actual:
        changed = sorted(key for key in set(expected) | set(actual) if expected.get(key) != actual.get(key))
        raise CandidateContractError(f"child changes initial Jacobian frozen physical problem: {changed}")
    return child


def resolve_numerics(contract: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Derive bounded local-solve controls from the baseline and frozen trial."""
    profile = contract["downstream_fixed_grid_workpoint_profile"]
    if profile["schema_version"] != 1 or profile["parameter_scale_rule"] != "absolute_baseline_voltage":
        raise CandidateContractError("unsupported downstream workpoint profile")
    if profile["voltage_bounds_rule"] != "stripe_seed_energy_envelope_with_baseline_sign__prism_initial_search_window":
        raise CandidateContractError("unsupported downstream voltage envelope rule")
    energy = _finite(baseline["frozen_problem"]["selected_axial_energy_per_charge_v"], "axial energy")
    deviation = _finite(contract["accelerator_energy_contract"]["maximum_particle_net_gain_deviation_per_charge_v"], "energy half-window")
    seed = contract["dual_stripe_l0"]["operating_seed_search"]
    floor = energy * _finite(seed["minimum_abs_bias_fraction_of_nominal_energy"], "minimum bias fraction")
    if energy <= deviation or deviation <= 0 or floor <= 0:
        raise CandidateContractError("invalid downstream energy/bias envelope")
    voltage = baseline["voltages_v"]
    if not voltage[0] < -floor or not voltage[1] > floor:
        raise CandidateContractError("downstream Stripe seed requires S1 negative and S2 positive")
    prism_window = contract["prism_transport"]["two_prism_injection_l0"]["voltage_polarity_contract"]["current_initial_search_window_v"]
    target_ratio = baseline["frozen_problem"]["targets"]["target_low_field_tangent_ratio_vy_over_vz"]
    angle_scale = math.radians(_finite(profile["angle_residual_scale_degrees"], "angle scale"))
    if not 0 < angle_scale < math.pi / 2:
        raise CandidateContractError("angle scale must be positive and below 90 degrees")
    target_angle = math.atan(target_ratio)
    ratio_scale = min(math.tan(target_angle + angle_scale) - target_ratio,
                      target_ratio - math.tan(target_angle - angle_scale))
    return {
        "lower_bounds_v": [-energy, floor, prism_window["prism_1"][0], prism_window["prism_2"][0]],
        "upper_bounds_v": [-floor, math.nextafter(energy - deviation, -math.inf), prism_window["prism_1"][1], prism_window["prism_2"][1]],
        "parameter_scales_v": [abs(value) for value in voltage],
        "residual_scales": [profile["position_residual_scale_mm"], ratio_scale,
                            profile["slow_turn_residual_scale_mm"], profile["return_phase_residual_scale_mm"]],
        "maximum_abs_step_v": profile["maximum_abs_step_v"],
        "relative_rank_tolerance": contract["dual_stripe_l0"]["determination_numerics"]["relative_singular_value_rank_tolerance"],
        "compatibility_tolerance": contract["dual_stripe_l0"]["determination_numerics"]["scaled_irreducible_residual_norm_tolerance"],
    }


def solve_linearized_step(
    baseline: Mapping[str, Any],
    perturbations: Sequence[Mapping[str, Any]],
    *,
    lower_bounds_v: Sequence[float],
    upper_bounds_v: Sequence[float],
    parameter_scales_v: Sequence[float],
    residual_scales: Sequence[float],
    maximum_abs_step_v: Sequence[float],
    relative_rank_tolerance: float,
    compatibility_tolerance: float,
) -> dict[str, Any]:
    """Return a full-rank signed one-sided Jacobian correction with one trust scale."""
    if len(perturbations) != 4:
        raise CandidateContractError("downstream workpoint needs exactly four perturbations")
    vectors = [np.asarray(item["voltages_v"], dtype=float) for item in (baseline, *perturbations)]
    residual_vectors = [np.asarray(item["residual_vector"], dtype=float) for item in (baseline, *perturbations)]
    if any(value.shape != (4,) or not np.all(np.isfinite(value)) for value in (*vectors, *residual_vectors)):
        raise CandidateContractError("downstream voltage and residual vectors must be finite four-vectors")
    if any(item["frozen_problem"] != baseline["frozen_problem"] for item in perturbations):
        raise CandidateContractError("downstream perturbations change the frozen physical problem")
    base_v, base_r = vectors[0], residual_vectors[0]
    columns: list[np.ndarray] = []
    steps: list[float] = []
    for index, trial_v in enumerate(vectors[1:]):
        delta = trial_v - base_v
        changed = np.flatnonzero(delta != 0.0)
        if changed.tolist() != [index]:
            raise CandidateContractError(
                f"perturbation {index + 1} must change only {UNKNOWN_NAMES[index]} by a nonzero step"
            )
        steps.append(float(delta[index]))
        columns.append((residual_vectors[index + 1] - base_r) / delta[index])
    jacobian = np.column_stack(columns)
    lower = np.asarray(lower_bounds_v, dtype=float)
    upper = np.asarray(upper_bounds_v, dtype=float)
    parameter_scales = np.asarray(parameter_scales_v, dtype=float)
    residual_scale_array = np.asarray(residual_scales, dtype=float)
    maximum_step = np.asarray(maximum_abs_step_v, dtype=float)
    if any(value.shape != (4,) or not np.all(np.isfinite(value)) for value in (lower, upper, parameter_scales, residual_scale_array, maximum_step)):
        raise CandidateContractError("downstream bounds, scales, and trust limits must be finite four-vectors")
    if np.any(lower >= base_v) or np.any(base_v >= upper):
        raise CandidateContractError("baseline downstream voltages must lie strictly inside their bounds")
    if np.any(parameter_scales <= 0.0) or np.any(residual_scale_array <= 0.0) or np.any(maximum_step <= 0.0):
        raise CandidateContractError("downstream scales and trust limits must be positive")
    rank_tolerance = _finite(relative_rank_tolerance, "relative rank tolerance")
    if rank_tolerance <= 0.0:
        raise CandidateContractError("relative rank tolerance must be positive")
    result = solve_with_jacobian(
        baseline,
        jacobian,
        lower_bounds_v=lower,
        upper_bounds_v=upper,
        parameter_scales_v=parameter_scales,
        residual_scales=residual_scale_array,
        maximum_abs_step_v=maximum_step,
        relative_rank_tolerance=rank_tolerance,
        compatibility_tolerance=compatibility_tolerance,
    )
    return {"stencil_steps_v": steps, **result}


def solve_with_jacobian(
    baseline: Mapping[str, Any],
    jacobian_rows: Sequence[Sequence[float]],
    *,
    lower_bounds_v: Sequence[float],
    upper_bounds_v: Sequence[float],
    parameter_scales_v: Sequence[float],
    residual_scales: Sequence[float],
    maximum_abs_step_v: Sequence[float],
    relative_rank_tolerance: float,
    compatibility_tolerance: float,
) -> dict[str, Any]:
    """Apply one bounded Newton step from an already audited local Jacobian."""
    base_v = np.asarray(baseline["voltages_v"], dtype=float)
    base_r = np.asarray(baseline["residual_vector"], dtype=float)
    jacobian = np.asarray(jacobian_rows, dtype=float)
    lower = np.asarray(lower_bounds_v, dtype=float)
    upper = np.asarray(upper_bounds_v, dtype=float)
    parameter_scales = np.asarray(parameter_scales_v, dtype=float)
    residual_scale_array = np.asarray(residual_scales, dtype=float)
    maximum_step = np.asarray(maximum_abs_step_v, dtype=float)
    if (base_v.shape != (4,) or base_r.shape != (4,) or jacobian.shape != (4, 4)
            or not np.all(np.isfinite(base_v)) or not np.all(np.isfinite(base_r))
            or not np.all(np.isfinite(jacobian))):
        raise CandidateContractError("downstream baseline and Jacobian must be finite four-dimensional arrays")
    if any(value.shape != (4,) or not np.all(np.isfinite(value))
           for value in (lower, upper, parameter_scales, residual_scale_array, maximum_step)):
        raise CandidateContractError("downstream bounds, scales, and trust limits must be finite four-vectors")
    if np.any(lower >= base_v) or np.any(base_v >= upper):
        raise CandidateContractError("baseline downstream voltages must lie strictly inside their bounds")
    if np.any(parameter_scales <= 0.0) or np.any(residual_scale_array <= 0.0) or np.any(maximum_step <= 0.0):
        raise CandidateContractError("downstream scales and trust limits must be positive")
    rank_tolerance = _finite(relative_rank_tolerance, "relative rank tolerance")
    if rank_tolerance <= 0.0:
        raise CandidateContractError("relative rank tolerance must be positive")
    classification = classify_constraint_system(
        UNKNOWN_NAMES,
        RESIDUAL_NAMES,
        jacobian_rows=jacobian.tolist(),
        residuals=base_r.tolist(),
        parameter_scales=parameter_scales.tolist(),
        residual_scales=residual_scale_array.tolist(),
        relative_rank_tolerance=rank_tolerance,
        compatibility_tolerance=compatibility_tolerance,
    )
    if classification.status != "square_exact":
        raise CandidateContractError(
            f"downstream finite-3-D Jacobian is not square exact: {classification.status}"
        )
    raw_step = np.linalg.solve(jacobian, -base_r)
    nonzero = np.abs(raw_step) > 0
    alpha = min(1.0, float(np.min(maximum_step[nonzero] / np.abs(raw_step[nonzero])))) if np.any(nonzero) else 1.0
    for index, component in enumerate(raw_step):
        if component > 0.0:
            alpha = min(alpha, float((upper[index] - base_v[index]) / component))
        elif component < 0.0:
            alpha = min(alpha, float((lower[index] - base_v[index]) / component))
    alpha = max(0.0, min(1.0, alpha))
    if alpha <= 0.0:
        raise CandidateContractError("no positive bounded trust step is available")
    applied = alpha * raw_step
    proposed = base_v + applied
    predicted = base_r + jacobian @ applied
    return {
        "unknown_names": list(UNKNOWN_NAMES),
        "residual_names": list(RESIDUAL_NAMES),
        "baseline_voltages_v": base_v.tolist(),
        "baseline_residuals": dict(zip(RESIDUAL_NAMES, base_r.tolist())),
        "physical_jacobian_rows": jacobian.tolist(),
        "classification": asdict(classification),
        "unbounded_linear_correction_v": raw_step.tolist(),
        "trust_scale": alpha,
        "applied_correction_v": applied.tolist(),
        "proposed_voltages_v": proposed.tolist(),
        "predicted_residuals": dict(zip(RESIDUAL_NAMES, predicted.tolist())),
    }


def _transport_invariants(trial: Mapping[str, Any]) -> dict[str, Any]:
    frozen = trial["frozen_problem"]
    inputs = frozen["inputs"]
    required_input_names = (
        "fixed_mirror_stripe_authority_sha256",
        "mirror_summary_sha256",
        "reviewed_contract_sha256",
        "stripe_summary_sha256",
    )
    missing = [name for name in required_input_names if name not in inputs]
    if missing:
        raise CandidateContractError(f"transport baseline lacks invariant identities: {missing}")
    return {
        "native_bank_identity": frozen.get("native_bank_identity"),
        "field_authorities": {name: inputs[name] for name in required_input_names},
        "targets": frozen["targets"],
        "mirror_voltages_v": frozen["mirror_voltages_v"],
        "selected_axial_energy_per_charge_v": frozen["selected_axial_energy_per_charge_v"],
        "source_slow_kinetic_energy_per_charge_v": frozen["source_slow_kinetic_energy_per_charge_v"],
        "drift_phase_contract": frozen["drift_phase_contract"],
        "trajectory_profile": frozen["trajectory_profile"],
        "local_region_mesh_mm_per_gu": frozen["local_region_mesh_mm_per_gu"],
    }


def audit_transported(
    definition: Mapping[str, Any],
    contract: Mapping[str, Any],
    contract_path: Path,
    freeze_dir: Path | None,
) -> dict[str, Any]:
    """Transport a prior audited fine-grid Jacobian to one compatible baseline."""
    allowed = {"schema_version", "role", "contract", "baseline_manifest", "prior_workpoint_manifest"}
    if set(definition) != allowed:
        raise CandidateContractError("transport definition only binds contract, baseline, and prior audit")
    baseline = _trial(
        Path(definition["baseline_manifest"]),
        freeze_dir / "baseline" if freeze_dir else None,
    )
    prior_manifest_path = Path(definition["prior_workpoint_manifest"])
    prior_manifest = _load_object(prior_manifest_path)
    if (prior_manifest.get("status") != "success"
            or prior_manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
            or prior_manifest.get("mode") != "downstream_fixed_grid_workpoint"):
        raise CandidateContractError("prior Jacobian must come from a successful downstream workpoint run")
    prior_records = [
        record for record in prior_manifest.get("outputs", [])
        if record_path(record, base_dir=prior_manifest_path.parent).name == "downstream_fixed_grid_workpoint.json"
    ]
    if len(prior_records) != 1:
        raise CandidateContractError("prior workpoint manifest must bind one workpoint audit")
    verify_record("prior_workpoint_audit", prior_records[0], base_dir=prior_manifest_path.parent)
    prior_path = record_path(prior_records[0], base_dir=prior_manifest_path.parent)
    prior = _load_object(prior_path)
    if (prior.get("role") != "mrtof_downstream_fixed_grid_workpoint_audit"
            or prior.get("status") != "linearized_candidate_step"
            or prior.get("unknown_names") != list(UNKNOWN_NAMES)
            or prior.get("residual_names") != list(RESIDUAL_NAMES)):
        raise CandidateContractError("prior workpoint audit is not an eligible four-variable Jacobian source")
    if freeze_dir is not None:
        freeze_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prior_path, freeze_dir / "prior_workpoint_audit.json")
        shutil.copyfile(prior_manifest_path, freeze_dir / "prior_workpoint_manifest.json")
    prior_baseline = _trial(
        Path(prior["baseline_manifest"]),
        freeze_dir / "prior_baseline" if freeze_dir else None,
    )
    prior_invariants = _transport_invariants(prior_baseline)
    current_invariants = _transport_invariants(baseline)
    if prior_invariants != current_invariants:
        changed = [name for name in prior_invariants if prior_invariants[name] != current_invariants[name]]
        raise CandidateContractError(f"prior Jacobian changes transport invariants: {changed}")
    target_k = _finite(contract["nominal"]["target_drift_period_ratio"], "target K")
    if (baseline["frozen_problem"]["targets"]["target_drift_period_ratio"] != target_k
            or prior.get("target_drift_period_ratio") != target_k):
        raise CandidateContractError("contract target K differs from transported Jacobian inputs")
    numerics = resolve_numerics(contract, baseline)
    result = solve_with_jacobian(
        baseline,
        prior["physical_jacobian_rows"],
        **numerics,
    )
    source_baseline = np.asarray(prior["baseline_voltages_v"], dtype=float)
    target_baseline = np.asarray(baseline["voltages_v"], dtype=float)
    source_trust = np.asarray(prior["resolved_numerics"]["maximum_abs_step_v"], dtype=float)
    transport_offset = target_baseline - source_baseline
    return {
        "schema_version": 1,
        "role": "mrtof_downstream_fixed_grid_workpoint_audit",
        "status": "transported_linearized_candidate_step",
        "qualification": "transported_fine_grid_jacobian_seed__requires_one_real_center_flight_confirmation",
        "target_drift_period_ratio": target_k,
        "contract_sha256": file_sha256(contract_path),
        "native_bank_identity": baseline["frozen_problem"].get("native_bank_identity"),
        "resolved_numerics": numerics,
        "baseline_manifest": baseline["manifest"],
        "prior_workpoint_manifest": str(prior_manifest_path.resolve()),
        "prior_workpoint_manifest_sha256": file_sha256(prior_manifest_path),
        "prior_workpoint_audit": str(prior_path.resolve()),
        "prior_workpoint_audit_sha256": file_sha256(prior_path),
        "prior_baseline_manifest": prior_baseline["manifest"],
        "transport_invariants": current_invariants,
        "jacobian_use": "transported_local_approximation",
        "transport_offset_from_source_baseline_v": transport_offset.tolist(),
        "source_trust_radius_v": source_trust.tolist(),
        "outside_source_trust_radius": bool(np.any(np.abs(transport_offset) > source_trust)),
        "requires_real_center_flight_confirmation": True,
        "allowed_changed_state": {
            "source_position_project_mm": {
                "prior": prior_baseline["frozen_problem"]["source_position_project_mm"],
                "current": baseline["frozen_problem"]["source_position_project_mm"],
            },
            "source_direction_project": {
                "prior": prior_baseline["frozen_problem"]["source_direction_project"],
                "current": baseline["frozen_problem"]["source_direction_project"],
            },
            "accelerator_pulse": {
                "prior": prior_baseline["frozen_problem"]["accelerator_pulse"],
                "current": baseline["frozen_problem"]["accelerator_pulse"],
            },
            "fly2_sha256": {
                "prior": prior_baseline["frozen_problem"]["fly2_sha256"],
                "current": baseline["frozen_problem"]["fly2_sha256"],
            },
        },
        "consumed_trials": [{
            key: baseline[key] for key in ("manifest", "manifest_sha256", "consumer_projection")
        }],
        **result,
    }


def audit(definition_path: Path, freeze_dir: Path | None = None) -> dict[str, Any]:
    """Audit five immutable trials under one contract-owned numerical profile."""
    definition = _load_object(definition_path)
    role = definition.get("role")
    if definition.get("schema_version") != 1 or role not in {
        "mrtof_downstream_fixed_grid_workpoint_definition",
        "mrtof_downstream_transported_jacobian_definition",
    }:
        raise CandidateContractError("invalid downstream workpoint definition role")
    contract_path = Path(definition["contract"])
    contract = _load_object(contract_path)
    if role == "mrtof_downstream_transported_jacobian_definition":
        return audit_transported(definition, contract, contract_path, freeze_dir)
    if set(definition) != {"schema_version", "role", "contract", "baseline_manifest", "perturbation_manifests"}:
        raise CandidateContractError("definition only transports contract and trial paths; numerical overrides are forbidden")
    baseline = _trial(Path(definition["baseline_manifest"]), freeze_dir / "baseline" if freeze_dir else None)
    perturbation_map = definition.get("perturbation_manifests")
    if not isinstance(perturbation_map, dict) or set(perturbation_map) != set(UNKNOWN_NAMES):
        raise CandidateContractError("definition must bind one perturbation manifest per downstream voltage")
    target_k = _finite(contract["nominal"]["target_drift_period_ratio"], "target K")
    if baseline["frozen_problem"]["targets"]["target_drift_period_ratio"] != target_k:
        raise CandidateContractError("contract target K differs from the frozen trials")
    perturbations = [_trial(Path(perturbation_map[name]), freeze_dir / name if freeze_dir else None)
                     for name in UNKNOWN_NAMES]
    numerics = resolve_numerics(contract, baseline)
    result = solve_linearized_step(baseline, perturbations, **numerics)
    stripes = result["proposed_voltages_v"][:2]
    seed = contract["dual_stripe_l0"]["operating_seed_search"]
    energy = baseline["frozen_problem"]["selected_axial_energy_per_charge_v"]
    if (min(map(abs, stripes)) / max(map(abs, stripes)) < seed["minimum_bias_magnitude_ratio"]
            or abs(stripes[0] - stripes[1]) < energy * seed["minimum_bias_separation_fraction_of_nominal_energy"]):
        raise CandidateContractError("proposed Stripe pair violates the seed nondegeneracy rules")
    return {
        "schema_version": 1,
        "role": "mrtof_downstream_fixed_grid_workpoint_audit",
        "status": "linearized_candidate_step",
        "qualification": "linearized_candidate_proposal__requires_real_flight_confirmation_on_reused_response_fields",
        "target_drift_period_ratio": target_k,
        "contract_sha256": file_sha256(contract_path),
        "native_bank_identity": baseline["frozen_problem"].get("native_bank_identity"),
        "resolved_numerics": numerics,
        "consumed_trials": [
            {key: trial[key] for key in ("manifest", "manifest_sha256", "consumer_projection")}
            for trial in (baseline, *perturbations)
        ],
        "baseline_manifest": baseline["manifest"],
        "perturbation_manifests": {
            name: str(Path(perturbation_map[name]).resolve()) for name in UNKNOWN_NAMES
        },
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--freeze-input-dir", type=Path)
    args = parser.parse_args()
    result = audit(args.definition, args.freeze_input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MRTOF_DOWNSTREAM_FIXED_GRID_WORKPOINT={result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
