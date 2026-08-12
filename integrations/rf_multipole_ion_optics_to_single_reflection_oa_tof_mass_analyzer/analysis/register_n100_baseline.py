"""Write one explicitly identified N=100 pulse-resolution result receipt."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.screening_promotion_gate import (
    evaluate_campaign_n100_paired_promotion,
)


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def _screening_arm(rows: list[dict[str, str]], arm_id: str) -> dict[str, Any]:
    ids = sorted(int(row["particle_id"]) for row in rows if row["event"] == "source_release")
    eligible_ids = {
        int(row["particle_id"])
        for row in rows
        if row["event"] == "pre_pulse_state" and row["pulse_eligibility"] == "eligible"
    }
    detector = {
        int(row["particle_id"]): float(row["tof_since_pulse_us"]) * 1000.0
        for row in rows
        if row["event"] == "detector_crossing"
    }
    return {
        "arm_id": arm_id,
        "particle_ids": ids,
        "hit_status": [particle_id in detector for particle_id in ids],
        "pulse_effective_tof_ns": [detector.get(particle_id, float("nan")) for particle_id in ids],
        "pulse_eligible_status": [particle_id in eligible_ids for particle_id in ids],
    }


def build_receipt(
    campaign: dict[str, Any],
    summary: dict[str, Any],
    checkpoints: list[dict[str, str]],
    *,
    campaign_sha256: str,
    experiment_row_sha256: str,
    source_identity: dict[str, Any],
    prefix_path: str,
    prefix_sha256: str,
    registration_authority_sha256: str,
    experiment_id: str,
    arm_id: str,
    execution_mode: str,
) -> dict[str, Any]:
    experiments = [row for row in campaign["experiments"] if row["experiment_id"] == experiment_id]
    if len(experiments) != 1:
        raise ValueError("result experiment must resolve uniquely")
    experiment = experiments[0]
    contract = campaign["pulse_resolution_optimization"]
    arms = [row for row in contract["attribution_arms"] if row["arm_id"] == arm_id]
    if len(arms) != 1 or experiment["pulse_resolution_attribution_arm_id"] != arm_id:
        raise ValueError("result arm must resolve uniquely")
    arm = arms[0]
    source_ids = [int(row["particle_id"]) for row in checkpoints if row["event"] == "source_release"]
    ids = sorted(source_ids)
    if len(source_ids) != 100 or len(set(source_ids)) != 100:
        raise ValueError("result requires exactly one source-release row per particle")
    if ids != list(range(1, 101)) or summary["census"]["launched"] != 100:
        raise ValueError("baseline registration requires the complete ordered N=100 prefix")
    if summary["resolution_time_basis"] != "detector_time_minus_pulse_effective_time":
        raise ValueError("baseline registration requires the pulse-effective clock")
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "role": (
            "rf_oatof_pulse_resolution_baseline_result"
            if arm_id == "real_beam_all_real"
            else "rf_oatof_pulse_resolution_candidate_result"
        ),
        "registration_authority_sha256": registration_authority_sha256,
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": campaign_sha256,
        "experiment_id": experiment["experiment_id"],
        "experiment_row_sha256": experiment_row_sha256,
        "arm": {
            "sequence": arm["sequence"],
            "arm_id": arm["arm_id"],
            "mode": execution_mode,
            "source_model": arm["source_model"],
            "accelerator_field": arm["accelerator_field"],
            "reflectron_field": arm["reflectron_field"],
            "analysis_bootstrap_seed": contract["bootstrap"]["seed"],
        },
        "source_identity": source_identity,
        "prefix": {
            "path": prefix_path,
            "sha256": prefix_sha256,
            "count": 100,
            "selection_algorithm": "first_100_rows_in_frozen_file_order",
            "selection_seed": None,
            "ordered_particle_ids": ids,
            "particle_id_sha256_ordered": _canonical_sha(ids),
        },
        "clock": {
            "basis": summary["clock_basis"],
            "resolution_time_basis": summary["resolution_time_basis"],
            "pulse_effective_time_us": summary["pulse_effective_time_us"],
        },
        "census": summary["census"],
        "metrics": {
            "transmission": summary["transmission"],
            "pulse_effective_peak": summary["pulse_effective_peak"],
        },
        "execution_status": (
            "baseline_registered_not_candidate"
            if arm_id == "real_beam_all_real"
            else "candidate_screening_complete_not_qualified"
        ),
        "solver_execution_performed": True,
        "promotion_gate_invoked": False,
        "promotion_status": "not_evaluated",
        "claim_status": "REGISTRATION_ONLY",
        "formal_gate_passed": False,
    }
    receipt["receipt_sha256"] = _canonical_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--campaign-sha256", required=True)
    parser.add_argument("--experiment-row-sha256", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--arm-id", required=True)
    parser.add_argument("--execution-mode", required=True)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--source-identity", required=True, type=Path)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--prefix-plan-path", required=True)
    parser.add_argument("--prefix-sha256", required=True)
    parser.add_argument("--registration-authority", required=True, type=Path)
    parser.add_argument("--registration-authority-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline-checkpoints", type=Path)
    parser.add_argument("--promotion-receipt", type=Path)
    args = parser.parse_args()
    if file_sha256(args.campaign) != args.campaign_sha256:
        raise ValueError("campaign SHA differs")
    if file_sha256(args.prefix) != args.prefix_sha256:
        raise ValueError("prefix SHA differs")
    if file_sha256(args.registration_authority) != args.registration_authority_sha256:
        raise ValueError("registration authority SHA differs")
    campaign = json.loads(args.campaign.read_text(encoding="utf-8-sig"))
    summary = json.loads(args.summary.read_text(encoding="utf-8-sig"))
    source_identity = json.loads(args.source_identity.read_text(encoding="utf-8-sig"))
    with args.checkpoints.open(encoding="utf-8-sig", newline="") as handle:
        checkpoints = list(csv.DictReader(handle))
    receipt = build_receipt(
        campaign,
        summary,
        checkpoints,
        campaign_sha256=args.campaign_sha256,
        experiment_row_sha256=args.experiment_row_sha256,
        source_identity=source_identity,
        prefix_path=args.prefix_plan_path,
        prefix_sha256=args.prefix_sha256,
        registration_authority_sha256=args.registration_authority_sha256,
        experiment_id=args.experiment_id,
        arm_id=args.arm_id,
        execution_mode=args.execution_mode,
    )
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if args.baseline_checkpoints is not None or args.promotion_receipt is not None:
        if args.baseline_checkpoints is None or args.promotion_receipt is None:
            raise ValueError("paired screening requires both baseline checkpoints and promotion receipt")
        with args.baseline_checkpoints.open(encoding="utf-8-sig", newline="") as handle:
            baseline_rows = list(csv.DictReader(handle))
        promotion = evaluate_campaign_n100_paired_promotion(
            campaign,
            _screening_arm(baseline_rows, "real_beam_all_real"),
            _screening_arm(checkpoints, args.arm_id),
        )
        promotion["baseline_result_sha256"] = args.registration_authority_sha256
        promotion["candidate_result_sha256"] = file_sha256(args.output)
        args.promotion_receipt.write_text(json.dumps(promotion, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
