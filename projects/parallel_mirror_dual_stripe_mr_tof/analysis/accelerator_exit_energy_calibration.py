"""Derive a finite-3D accelerator gain correction from one verified exit state."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.host_resource_python import ensure_heavy_entry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_exact_k_operating_point import (
    load_managed_exact_k_operating_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    axial_potential_v,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CandidateContractError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def derive_unity_response_correction(
    observation: dict[str, Any],
    *,
    mirror_design: MirrorL0Design,
    target_axial_energy_per_charge_v: float,
    previous_cumulative_correction_v: float = 0.0,
) -> dict[str, Any]:
    """Return one Newton-like correction using the first-pass unit gain response.

    The proposal is deliberately not an acceptance result.  A second real
    SIMION exit observation determines the actual finite-field response and
    either closes the residual or supplies a measured secant slope.
    """
    if (
        not isinstance(observation, dict)
        or observation.get("schema_version") != 1
        or observation.get("role") != "mrtof_accelerator_exit_observation"
        or observation.get("status") != "observed"
        or observation.get("coordinate_frame") != "project"
    ):
        raise CandidateContractError("accelerator-exit observation identity is invalid")
    state = observation.get("safe_exit_state")
    components = observation.get("recorded_kinetic_energy_components_ev")
    if not isinstance(state, dict) or not isinstance(components, dict):
        raise CandidateContractError("accelerator-exit observation lacks energy state")
    position = state.get("position_mm")
    charge = state.get("charge_state")
    if not isinstance(position, list) or len(position) != 3:
        raise CandidateContractError("accelerator-exit position must have three components")
    if type(charge) is not int or charge == 0:
        raise CandidateContractError("accelerator-exit charge state must be a nonzero integer")
    z_mm = _finite(position[2], "accelerator-exit z")
    axial_kinetic_v = _finite(components.get("z"), "accelerator-exit axial kinetic energy") / abs(charge)
    target_v = _finite(target_axial_energy_per_charge_v, "target axial energy")
    previous_v = _finite(previous_cumulative_correction_v, "previous cumulative correction")
    if target_v <= 0.0:
        raise CandidateContractError("target axial energy must be positive")
    mirror_potential_v = axial_potential_v(z_mm, mirror_design)
    measured_hamiltonian_v = axial_kinetic_v + (1.0 if charge > 0 else -1.0) * mirror_potential_v
    residual_v = measured_hamiltonian_v - target_v
    correction_increment_v = -residual_v
    proposed_v = previous_v + correction_increment_v
    return {
        "schema_version": 1,
        "role": "mrtof_accelerator_finite_3d_energy_correction_proposal",
        "status": "derived",
        "qualification": "unity_response_first_correction_only__real_simion_exit_required",
        "target_axial_energy_per_charge_v": target_v,
        "measured_axial_kinetic_energy_per_charge_v": axial_kinetic_v,
        "mirror_potential_at_source_v": mirror_potential_v,
        "measured_axial_hamiltonian_per_charge_v": measured_hamiltonian_v,
        "measured_minus_target_axial_energy_v": residual_v,
        "previous_cumulative_correction_v": previous_v,
        "assumed_response_d_measured_energy_d_command": 1.0,
        "correction_increment_v": correction_increment_v,
        "proposed_cumulative_correction_v": proposed_v,
        "required_next_action": (
            "apply the proposed voltage-command correction without changing the exact-K target, "
            "then measure one new real accelerator exit"
        ),
    }


def main() -> int:
    ensure_heavy_entry(
        "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
        "accelerator_exit_energy_calibration",
        role="GATE",
        stage="theory_compute",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--exact-k-manifest", type=Path, required=True)
    parser.add_argument("--accelerator-exit-observation", type=Path, required=True)
    parser.add_argument("--previous-cumulative-correction-v", type=float, default=0.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    managed = load_managed_exact_k_operating_point(args.exact_k_manifest, args.contract)
    try:
        observation = json.loads(args.accelerator_exit_observation.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateContractError("accelerator-exit observation is not readable JSON") from error
    result = derive_unity_response_correction(
        observation,
        mirror_design=managed.design,
        target_axial_energy_per_charge_v=managed.axial_energy_per_charge_v,
        previous_cumulative_correction_v=args.previous_cumulative_correction_v,
    )
    result["inputs"] = {
        "contract_sha256": file_sha256(args.contract).lower(),
        "exact_k_manifest_sha256": file_sha256(args.exact_k_manifest).lower(),
        "accelerator_exit_observation_sha256": file_sha256(
            args.accelerator_exit_observation
        ).lower(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "MRTOF_ACCELERATOR_EXIT_ENERGY_CALIBRATION=PASS "
        f"correction_v={result['proposed_cumulative_correction_v']:.12g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
