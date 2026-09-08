"""Publish the N=1 full-centre source from an audited P1/P2 hand-off.

This materializer changes exactly one execution semantic from the final
P1/P2 shooting trial: it continues past the observed drift phase origin.
All particle, geometry, field, voltage, mesh, and integration values remain
byte-bound to the selected trial and operating-point audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise CandidateContractError(f"expected a JSON object in {path}")
    return value


def _source_record(path: Path) -> dict[str, Any]:
    ids = [1]
    identity = json.dumps(ids, separators=(",", ":")).encode("utf-8")
    return {
        "filename": path.name,
        "sha256": file_sha256(path).lower(),
        "particle_count_contract_key": "center_particle_count",
        "particle_count": 1,
        "source_profile_id": "full_mrtof_center",
        "expected_particle_ids": ids,
        "expected_particle_ids_sha256": hashlib.sha256(identity).hexdigest(),
    }


def materialize_full_center_source(
    *,
    operating_point_summary_path: Path,
    selected_contract_path: Path,
    trial_materialization_path: Path,
    trial_fly2_path: Path,
    trial_sidecar_path: Path,
    output_contract_path: Path,
    output_fly2_path: Path,
    output_sidecar_path: Path,
    output_manifest_path: Path,
    output_receipt_path: Path,
) -> dict[str, Any]:
    """Materialize a continuation source without altering its physical state."""
    operating = _load(operating_point_summary_path)
    trial = _load(trial_materialization_path)
    contract = _load(selected_contract_path)
    if operating.get("qualification") != "single_center_phase_space_handoff_candidate__K25_pending":
        raise CandidateContractError("full-centre source requires the audited P1/P2 hand-off candidate")
    iterations = operating.get("iterations")
    if not isinstance(iterations, list) or not iterations or not isinstance(iterations[-1], dict):
        raise CandidateContractError("P1/P2 operating-point audit has no selected final iteration")
    selected = operating.get("selected_prism_voltages_v")
    if selected != trial.get("prism_voltages_v") or selected != iterations[-1].get("prism_voltages_v"):
        raise CandidateContractError("selected P1/P2 voltages differ from the final SIMION trial")
    if file_sha256(trial_materialization_path).upper() != str(iterations[-1].get("materialization_sha256", "")).upper():
        raise CandidateContractError("final trial materialization differs from the operating-point audit")
    if file_sha256(trial_fly2_path).lower() != str(trial.get("fly2_sha256", "")).lower():
        raise CandidateContractError("final P1/P2 trial Fly2 identity changed")
    if file_sha256(trial_sidecar_path).lower() != str(trial.get("operating_point_lua_sha256", "")).lower():
        raise CandidateContractError("final P1/P2 trial sidecar identity changed")

    sidecar = trial_sidecar_path.read_text(encoding="utf-8")
    marker = "stop_at_drift_phase_origin = true"
    if sidecar.count(marker) != 1 or "stop_at_drift_phase_origin = false" in sidecar:
        raise CandidateContractError("P1/P2 trial sidecar has an unexpected continuation setting")
    continued_sidecar = sidecar.replace(marker, "stop_at_drift_phase_origin = false")
    output_sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    output_sidecar_path.write_text(continued_sidecar, encoding="utf-8", newline="\n")
    output_fly2_path.write_bytes(trial_fly2_path.read_bytes())

    source_profile = contract.get("particle_source", {}).get("full_mrtof_center")
    if not isinstance(source_profile, dict):
        raise CandidateContractError("selected contract lacks the full_mrtof_center source profile")
    source_profile.update({
        "status": "single_center_phase_space_handoff_candidate__full_K25_flight_enabled",
        "publishable": True,
        "operating_point_receipt_sha256": file_sha256(operating_point_summary_path),
        "phase_origin_mirror_side": "positive_project_z",
        "scope": "N=1 complete-event-chain trial only; bundle and resolution remain unpublished",
    })
    source_profile["required_inputs"] = [
        "the exact-K mirror and dual-Stripe receipts consumed by the selected P1/P2 trials",
        "the full-rank finite-three-dimensional P1/P2 Jacobian audit",
        "the selected positive-z mirror-turn phase-space hand-off at registered function y=0",
    ]
    output_contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    manifest = {
        "schema_version": 3,
        "status": "joint_downstream_operating_point__center_flight_allowed",
        "derived_contract": {
            "filename": output_contract_path.name,
            "sha256": file_sha256(output_contract_path).lower(),
        },
        "operating_point": {
            "filename": output_sidecar_path.name,
            "sha256": file_sha256(output_sidecar_path).lower(),
        },
        "full_mrtof_center_fly2": _source_record(output_fly2_path),
        "source_operating_point_audit": {
            "filename": operating_point_summary_path.name,
            "sha256": file_sha256(operating_point_summary_path).lower(),
        },
    }
    output_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    receipt = {
        "schema_version": 1,
        "role": "mrtof_full_center_source_materialization",
        "status": "success",
        "qualification": "N1_complete_event_chain_input__not_bundle_or_resolution_evidence",
        "selected_prism_voltages_v": selected,
        "source_trial_run_id": iterations[-1].get("run_id"),
        "source_trial_manifest_sha256": iterations[-1].get("run_manifest_sha256"),
        "operating_point_summary_sha256": file_sha256(operating_point_summary_path),
        "input_trial_fly2_sha256": file_sha256(trial_fly2_path),
        "output_fly2_sha256": file_sha256(output_fly2_path),
        "input_trial_sidecar_sha256": file_sha256(trial_sidecar_path),
        "output_continuation_sidecar_sha256": file_sha256(output_sidecar_path),
        "only_execution_semantic_change": "stop_at_drift_phase_origin: true -> false",
    }
    output_receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operating-point-summary", required=True, type=Path)
    parser.add_argument("--selected-contract", required=True, type=Path)
    parser.add_argument("--trial-materialization", required=True, type=Path)
    parser.add_argument("--trial-fly2", required=True, type=Path)
    parser.add_argument("--trial-sidecar", required=True, type=Path)
    parser.add_argument("--output-contract", required=True, type=Path)
    parser.add_argument("--output-fly2", required=True, type=Path)
    parser.add_argument("--output-sidecar", required=True, type=Path)
    parser.add_argument("--output-manifest", required=True, type=Path)
    parser.add_argument("--output-receipt", required=True, type=Path)
    args = parser.parse_args()
    result = materialize_full_center_source(
        operating_point_summary_path=args.operating_point_summary,
        selected_contract_path=args.selected_contract,
        trial_materialization_path=args.trial_materialization,
        trial_fly2_path=args.trial_fly2,
        trial_sidecar_path=args.trial_sidecar,
        output_contract_path=args.output_contract,
        output_fly2_path=args.output_fly2,
        output_sidecar_path=args.output_sidecar,
        output_manifest_path=args.output_manifest,
        output_receipt_path=args.output_receipt,
    )
    print(
        "MRTOF_FULL_CENTER_SOURCE=PASS "
        f"P1={result['selected_prism_voltages_v'][0]:.12g} "
        f"P2={result['selected_prism_voltages_v'][1]:.12g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
