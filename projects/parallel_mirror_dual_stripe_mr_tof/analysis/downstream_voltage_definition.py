"""Audit the finite-3-D Stripe/P1/P2 four-coordinate local definition.

The mirror voltages remain frozen by their independent mirror-theory receipt.
This module consumes one baseline and four single-axis SIMION trials, constructs
the scaled 4x4 Jacobian, and reports rank and the undamped linear correction.
It never launches SIMION or promotes the extrapolated correction to a voltage
working point.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    classify_constraint_system,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)


UNKNOWN_NAMES = (
    "stripe_1_voltage_v",
    "stripe_2_voltage_v",
    "prism_1_voltage_v",
    "prism_2_voltage_v",
)
RESIDUAL_NAMES = (
    "P1_P2_phase_origin_turn_y_mm",
    "P1_P2_slow_kinetic_energy_per_charge_v",
    "Stripe_slow_turn_y_minus_L_mm",
    "Stripe_fractional_K_minus_target",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise CandidateContractError(f"expected an object in {path}")
    return value


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _manifest_output(manifest_path: Path, filename: str) -> Path:
    manifest = _load(manifest_path)
    base = manifest_path.resolve().parent
    if (
        manifest.get("status") != "success"
        or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") != "finite_3d_two_prism_voltage_trial"
    ):
        raise CandidateContractError(f"not a successful downstream SIMION trial: {manifest_path}")
    verify_record("run_config", manifest["run_config"], base_dir=base)
    matches: list[Path] = []
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        verify_record(f"output {index}", record, base_dir=base)
        path = record_path(record, base_dir=base)
        if path.name == filename:
            matches.append(path)
    if len(matches) != 1:
        raise CandidateContractError(f"manifest must bind exactly one {filename}: {manifest_path}")
    return matches[0]


def _trial(manifest_path: Path) -> dict[str, Any]:
    summary = _load(_manifest_output(manifest_path, "summary.json"))
    materialization = _load(
        _manifest_output(manifest_path, "two_prism_trial_materialization.json")
    )
    if summary.get("transport_status") != "full_drift_observed":
        raise CandidateContractError(f"trial lacks all four downstream residuals: {manifest_path}")
    stripes = summary.get("stripe_biases_v")
    prisms = summary.get("prism_voltages_v")
    residuals = summary.get("residuals")
    if not isinstance(stripes, list) or len(stripes) != 2:
        raise CandidateContractError("trial must contain two Stripe voltages")
    if not isinstance(prisms, list) or len(prisms) != 2:
        raise CandidateContractError("trial must contain two prism voltages")
    if not isinstance(residuals, dict):
        raise CandidateContractError("trial must contain its residual object")
    return {
        "run_id": _load(manifest_path).get("run_id"),
        "parameters": [_finite(value, "downstream voltage") for value in stripes + prisms],
        "residuals": [_finite(residuals.get(name), name) for name in RESIDUAL_NAMES],
        "frozen_problem": {
            "inputs": materialization.get("inputs"),
            "mirror_voltages_v": materialization.get("mirror_voltages_v"),
            "target_slow_turn_y_mm": materialization.get("target_slow_turn_y_mm"),
            "target_oscillation_count": materialization.get("target_oscillation_count"),
            "target_turn_y_mm": materialization.get("target_turn_y_mm"),
            "target_slow_kinetic_energy_per_charge_v": materialization.get(
                "target_slow_kinetic_energy_per_charge_v"
            ),
            "particle_mass_th": materialization.get("particle_mass_th"),
            "charge_state": materialization.get("charge_state"),
        },
    }


def audit_downstream_definition(
    *, contract_path: Path, baseline_manifest: Path, axis_manifests: Sequence[Path]
) -> dict[str, Any]:
    """Return a rank-audited local definition without accepting a Newton step."""
    if len(axis_manifests) != len(UNKNOWN_NAMES):
        raise CandidateContractError("exactly four ordered single-axis trials are required")
    contract = load_contract(contract_path)
    baseline = _trial(baseline_manifest)
    axes = [_trial(path) for path in axis_manifests]
    if any(trial["frozen_problem"] != baseline["frozen_problem"] for trial in axes):
        raise CandidateContractError("downstream trials do not share one frozen physical problem")
    p0 = np.asarray(baseline["parameters"], dtype=float)
    r0 = np.asarray(baseline["residuals"], dtype=float)
    columns: list[np.ndarray] = []
    steps: list[float] = []
    for index, trial in enumerate(axes):
        delta = np.asarray(trial["parameters"], dtype=float) - p0
        serialization_tolerance = np.maximum(1e-12, 1e-12 * np.maximum(np.abs(p0), 1.0))
        changed = np.flatnonzero(np.abs(delta) > serialization_tolerance)
        if changed.tolist() != [index] or delta[index] <= 0.0:
            raise CandidateContractError(
                f"axis trial {index + 1} must positively perturb only {UNKNOWN_NAMES[index]}"
            )
        step = float(delta[index])
        steps.append(step)
        columns.append((np.asarray(trial["residuals"], dtype=float) - r0) / step)
    jacobian = np.column_stack(columns)
    frozen = baseline["frozen_problem"]
    length_scale = _finite(frozen["target_slow_turn_y_mm"], "drift-length scale")
    energy_scale = _finite(
        frozen["target_slow_kinetic_energy_per_charge_v"], "slow-energy scale"
    )
    k_scale = _finite(frozen["target_oscillation_count"], "target-K scale")
    parameter_scales = [max(abs(value), 1.0) for value in p0]
    residual_scales = [length_scale, energy_scale, length_scale, k_scale]
    rank_tolerance = _finite(
        contract["dual_stripe_l0"]["determination_numerics"][
            "relative_singular_value_rank_tolerance"
        ],
        "relative singular-value rank tolerance",
    )
    classification = classify_constraint_system(
        UNKNOWN_NAMES,
        RESIDUAL_NAMES,
        jacobian_rows=jacobian.tolist(),
        residuals=r0.tolist(),
        parameter_scales=parameter_scales,
        residual_scales=residual_scales,
        relative_rank_tolerance=rank_tolerance,
    )
    correction = None
    extrapolation = None
    if classification.status == "square_exact":
        correction_array = np.linalg.solve(jacobian, -r0)
        correction = correction_array.tolist()
        extrapolation = [abs(float(value)) / steps[index] for index, value in enumerate(correction_array)]
    return {
        "schema_version": 1,
        "role": "mrtof_finite_3d_downstream_voltage_definition_audit",
        "status": "success",
        "qualification": "local_definition_only__iteration_not_authorized",
        "unknown_names": list(UNKNOWN_NAMES),
        "residual_names": list(RESIDUAL_NAMES),
        "baseline": baseline,
        "axis_trials": axes,
        "finite_difference_steps_v": steps,
        "physical_jacobian_rows": jacobian.tolist(),
        "parameter_scales_v": parameter_scales,
        "residual_scales": residual_scales,
        "classification": asdict(classification),
        "undamped_linear_correction_v": correction,
        "correction_to_finite_difference_step_ratios": extrapolation,
        "iteration_status": (
            "not_executed__rank_does_not_establish_a_valid_extrapolation_radius"
        ),
        "limits": [
            "one center ion at one analyzer mesh and time-step setting",
            "forward finite differences only",
            "the linear correction is diagnostic and is not an accepted voltage point",
            "mirror and accelerator voltages remain frozen",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--baseline-manifest", required=True, type=Path)
    parser.add_argument("--axis-manifest", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit_downstream_definition(
        contract_path=args.contract,
        baseline_manifest=args.baseline_manifest,
        axis_manifests=args.axis_manifest,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "MRTOF_DOWNSTREAM_VOLTAGE_DEFINITION=PASS "
        f"CLASS={result['classification']['status']} "
        f"COND={result['classification']['condition_number_2']:.12g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
