
"""Register one directly contracted N=100 pulse-resolution result."""

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


REPO_ROOT = Path(__file__).resolve().parents[3]


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
        int(row["particle_id"]): float(row["pulse_effective_elapsed_us"]) * 1000.0
        for row in rows
        if row["event"] == "detector_crossing"
    }
    return {
        "arm_id": arm_id,
        "particle_ids": ids,
        "hit_status": [particle_id in detector for particle_id in ids],
        "pulse_effective_tof_ns": [
            detector.get(particle_id, float("nan")) for particle_id in ids
        ],
        "pulse_eligible_status": [particle_id in eligible_ids for particle_id in ids],
    }


def _experiment_and_mode(
    campaign: dict[str, Any], experiment_id: str
) -> tuple[dict[str, Any], str]:
    experiments = [
        row for row in campaign["experiments"]
        if row["experiment_id"] == experiment_id
    ]
    if len(experiments) != 1:
        raise ValueError("result experiment must resolve uniquely")
    experiment = experiments[0]
    mode = experiment["pulse_resolution_execution_mode"]
    matrix_rows = [
        row for row in campaign["pulse_resolution_optimization"]["comparison_matrix"]
        if row["experiment_id"] == experiment_id
    ]
    if len(matrix_rows) != 1:
        raise ValueError("result experiment must resolve in the comparison matrix")
    matrix = matrix_rows[0]
    if matrix["authority_status"] != "direct_executable_contract":
        raise ValueError("pending comparison must not publish a registered result")
    if (
        matrix["sequence"] != experiment["sequence"]
        or matrix["source_profile_id"] != experiment["source_profile_id"]
        or matrix["field_profile_id"]
        != experiment["single_flight_accelerator_field_profile_id"]
    ):
        raise ValueError("result experiment differs from its comparison identity")
    baseline = mode == "screening_prefix_n100_baseline_registration"
    if baseline != (
        experiment["single_flight_accelerator_field_profile_id"]
        == "accelerator_real_pa"
    ):
        raise ValueError("baseline role differs from the direct field identity")
    return experiment, mode


def _analysis_identity(experiment: dict[str, Any]) -> dict[str, int]:
    analysis = experiment["single_flight_population"]["analysis_randomness"]
    return {
        "bootstrap_resample_count": int(analysis["bootstrap_resample_count"]),
        "bootstrap_seed": int(analysis["bootstrap_seed"]),
    }


def _pulse_clock_authority(experiment: dict[str, Any]) -> tuple[float, float]:
    planned = float(
        experiment["single_flight_pulse_schedule_policy"]
        ["fixed_execution_authority"]["pulse_effective_time_us"]
    )
    record = experiment["source"]["handoff_publication_contract"]
    contract_path = REPO_ROOT / record["path"]
    if (
        not contract_path.is_file()
        or file_sha256(contract_path).upper() != record["sha256"].upper()
    ):
        raise ValueError("pulse clock tolerance contract identity differs")
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    tolerance = float(contract["canonical_state"]["clock_tolerance_us"])
    if tolerance <= 0.0:
        raise ValueError("pulse clock tolerance must be positive")
    return planned, tolerance


def _observed_id_set(ids: list[int]) -> dict[str, Any]:
    ordered_ids = sorted(set(ids))
    return {
        "ordered_particle_ids": ordered_ids,
        "count": len(ordered_ids),
        "ordered_particle_id_sha256": _canonical_sha(ordered_ids).upper(),
    }


def _observed_cohort_authority(
    checkpoints: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    selectors = {
        "source_release": lambda row: row["event"] == "source_release",
        "pre_pulse_state": lambda row: row["event"] == "pre_pulse_state",
        "pulse_eligible": lambda row: (
            row["event"] == "pre_pulse_state"
            and row.get("pulse_eligibility") == "eligible"
        ),
        "outside_transverse_bore": lambda row: (
            row["event"] == "pre_pulse_state"
            and row.get("pulse_eligibility") == "outside_transverse_bore"
        ),
    }
    memberships: dict[str, list[int]] = {}
    for name, selector in selectors.items():
        observed_ids = [
            int(row["particle_id"]) for row in checkpoints if selector(row)
        ]
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError(f"observed {name} cohort contains duplicate checkpoints")
        memberships[name] = sorted(observed_ids)
    if (
        not set(memberships["pulse_eligible"]).issubset(
            memberships["pre_pulse_state"]
        )
        or not set(memberships["outside_transverse_bore"]).issubset(
            memberships["pre_pulse_state"]
        )
        or set(memberships["pulse_eligible"])
        & set(memberships["outside_transverse_bore"])
    ):
        raise ValueError("observed pre-pulse cohort partition differs")
    authority = {
        "role": "rf_oatof_observed_paired_cohort_authority",
        **{
            name: _observed_id_set(ids)
            for name, ids in memberships.items()
        },
    }
    handoff_ids = [
        int(row["particle_id"])
        for row in checkpoints if row["event"] == "multipole_handoff"
    ]
    if len(handoff_ids) != len(set(handoff_ids)):
        raise ValueError("observed handoff contains duplicate checkpoints")
    handoff = _observed_id_set(handoff_ids)
    return authority, handoff


def _cohort_census(authority: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "count": int(authority[name]["count"]),
            "ordered_particle_id_sha256": authority[name][
                "ordered_particle_id_sha256"
            ],
        }
        for name in (
            "source_release", "pre_pulse_state", "pulse_eligible",
            "outside_transverse_bore",
        )
    }


def _require_same_cohort_authority(
    observed: dict[str, Any], frozen: dict[str, Any]
) -> None:
    for name in (
        "source_release", "pre_pulse_state", "pulse_eligible",
        "outside_transverse_bore",
    ):
        if observed.get(name) != frozen.get(name):
            raise ValueError(f"observed {name} cohort differs from frozen authority")


def validate_frozen_baseline_evidence(
    campaign: dict[str, Any],
    baseline_evidence: dict[str, Any],
    baseline_evidence_sha256: str,
) -> dict[str, dict[str, Any]]:
    """Validate one baseline receipt without candidate-run state or side effects."""

    descriptor = campaign.get("pulse_resolution_baseline_evidence", {})
    if set(descriptor) != {
        "authority_id",
        "path",
        "sha256",
        "baseline_campaign_id",
        "baseline_campaign_sha256",
    }:
        raise ValueError("candidate must declare one complete baseline evidence authority")
    if descriptor["sha256"].upper() != baseline_evidence_sha256.upper():
        raise ValueError("frozen baseline evidence SHA differs from the campaign authority")
    receipt_without_sha = dict(baseline_evidence)
    receipt_sha256 = receipt_without_sha.pop("receipt_sha256", "")
    if receipt_sha256.upper() != _canonical_sha(receipt_without_sha).upper():
        raise ValueError("frozen baseline evidence self-SHA differs")
    if baseline_evidence.get("solver_execution_performed") is not True:
        raise ValueError("frozen baseline evidence lacks completed solver execution")
    checkpoint_rows = baseline_evidence.get("paired_checkpoint_rows")
    if not isinstance(checkpoint_rows, list) or not checkpoint_rows:
        raise ValueError("frozen baseline evidence lacks paired checkpoint rows")
    observed_authority, observed_handoff = _observed_cohort_authority(
        checkpoint_rows
    )
    if baseline_evidence.get("cohort_authority_mode") != (
        "establish_observed_authority"
    ):
        raise ValueError("frozen baseline evidence did not establish observed authority")
    if baseline_evidence.get("observed_cohort_authority") != observed_authority:
        raise ValueError("frozen baseline observed cohort authority differs")
    if baseline_evidence.get("observed_handoff") != observed_handoff:
        raise ValueError("frozen baseline observed handoff differs")
    census = _cohort_census(observed_authority)
    if baseline_evidence.get("cohort_census") != census:
        raise ValueError("frozen baseline receipt cohort census or digest differs")
    return census


def _validate_baseline_evidence(
    campaign: dict[str, Any],
    experiment: dict[str, Any],
    baseline_evidence: dict[str, Any],
    baseline_evidence_sha256: str,
    source_identity: dict[str, Any],
    prefix_sha256: str,
    ordered_particle_ids: list[int],
    summary: dict[str, Any],
    observed_cohort_authority: dict[str, Any],
    clock_tolerance_us: float,
) -> None:
    validate_frozen_baseline_evidence(
        campaign, baseline_evidence, baseline_evidence_sha256
    )
    descriptor = campaign.get("pulse_resolution_baseline_evidence", {})
    baseline_experiment = baseline_evidence.get("experiment_row", {})
    baseline_row_sha256 = baseline_evidence.get("experiment_row_sha256", "")
    if baseline_row_sha256.upper() != _canonical_sha(baseline_experiment).upper():
        raise ValueError("frozen baseline experiment row SHA differs")
    baseline_analysis = _analysis_identity(baseline_experiment)
    candidate_analysis = _analysis_identity(experiment)
    if candidate_analysis != baseline_analysis:
        raise ValueError("candidate analysis identity differs from the baseline")
    baseline_population = baseline_experiment["single_flight_population"]["execution_population"]
    candidate_population = experiment["single_flight_population"][
        "execution_population"
    ]
    if candidate_population != baseline_population:
        raise ValueError("candidate cohort identity differs from the baseline")
    comparison = baseline_evidence.get("comparison", {})
    evidence_source = baseline_evidence.get("source_identity", {})
    evidence_prefix = baseline_evidence.get("prefix", {})
    evidence_clock = baseline_evidence.get("clock", {})
    if (
        baseline_evidence.get("role")
        != "rf_oatof_pulse_resolution_baseline_result"
        or baseline_evidence.get("baseline_authority_id") != descriptor["authority_id"]
        or baseline_evidence.get("campaign_id") != descriptor["baseline_campaign_id"]
        or baseline_evidence.get("campaign_sha256", "").upper()
        != descriptor["baseline_campaign_sha256"].upper()
        or baseline_evidence.get("experiment_id")
        != baseline_experiment.get("experiment_id")
        or baseline_evidence.get("execution_status")
        != "baseline_registered_not_candidate"
        or baseline_evidence.get("formal_gate_passed") is not False
        or baseline_experiment.get("pulse_resolution_execution_mode")
        != "screening_prefix_n100_baseline_registration"
        or baseline_experiment.get("single_flight_accelerator_field_profile_id")
        != "accelerator_real_pa"
        or comparison.get("sequence") != baseline_experiment.get("sequence")
        or comparison.get("source_profile_id")
        != baseline_experiment.get("source_profile_id")
        or comparison.get("field_profile_id") != "accelerator_real_pa"
        or comparison.get("analysis_bootstrap_seed")
        != baseline_analysis["bootstrap_seed"]
        or comparison.get("analysis_bootstrap_resample_count")
        != baseline_analysis["bootstrap_resample_count"]
    ):
        raise ValueError("frozen baseline campaign or analysis identity differs")
    frozen_observed_authority = baseline_evidence.get(
        "observed_cohort_authority", {}
    )
    _require_same_cohort_authority(
        observed_cohort_authority, frozen_observed_authority
    )
    if baseline_evidence.get("analysis_randomness") != candidate_analysis:
        raise ValueError("frozen baseline analysis authority differs")
    for field in ("event_sha256", "particle_source_sha256"):
        if evidence_source.get(field) != source_identity.get(field):
            raise ValueError("frozen baseline source identity differs")
    if (
        evidence_prefix.get("sha256") != prefix_sha256
        or evidence_prefix.get("ordered_particle_ids") != ordered_particle_ids
        or evidence_prefix.get("particle_id_sha256_ordered", "").upper()
        != _canonical_sha(ordered_particle_ids).upper()
        or evidence_prefix.get("selection_algorithm")
        != baseline_population["selection_algorithm"]
        or evidence_prefix.get("selection_seed")
        != baseline_population["selection_seed"]
        or evidence_prefix.get("count") != baseline_population["particle_count"]
        or evidence_prefix.get("particle_id_sha256_ordered", "").upper()
        != baseline_population["ordered_particle_id_sha256"].upper()
        or evidence_clock.get("resolution_time_basis")
        != summary["resolution_time_basis"]
        or evidence_clock.get("resolution_time_basis")
        != campaign["pulse_resolution_optimization"]["clock_contract"][
            "resolution_time_basis"
        ]
        or abs(
            float(evidence_clock.get("pulse_effective_time_us"))
            - float(summary["pulse_effective_time_us"])
        ) > clock_tolerance_us
        or baseline_experiment.get("single_flight_pulse_schedule_policy")
        != experiment.get("single_flight_pulse_schedule_policy")
        or float(evidence_clock.get("pulse_effective_time_us"))
        != float(
            experiment["single_flight_pulse_schedule_policy"][
                "fixed_execution_authority"
            ]["pulse_effective_time_us"]
        )
        or comparison.get("source_run_id") != experiment["source"]["run_id"]
        or comparison.get("source_state_sha256")
        != experiment["source"]["state"]["sha256"]
        or baseline_experiment.get("source") != experiment.get("source")
        or baseline_experiment.get("source_profile_id")
        != experiment.get("source_profile_id")
    ):
        raise ValueError("frozen baseline cohort or clock identity differs")
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
    baseline_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    experiment, execution_mode = _experiment_and_mode(campaign, experiment_id)
    if experiment_row_sha256.upper() != _canonical_sha(experiment).upper():
        raise ValueError("experiment row SHA differs from the campaign identity")
    baseline = execution_mode == "screening_prefix_n100_baseline_registration"
    population = experiment["single_flight_population"]["execution_population"]
    analysis_identity = _analysis_identity(experiment)
    observed_cohort_authority, observed_handoff = _observed_cohort_authority(
        checkpoints
    )
    cohort_census = _cohort_census(observed_cohort_authority)
    if summary.get("observed_cohort_authority") != observed_cohort_authority:
        raise ValueError("analysis summary observed cohort authority differs")
    if summary.get("observed_handoff") != observed_handoff:
        raise ValueError("analysis summary observed handoff differs")
    source_ids = [int(row["particle_id"]) for row in checkpoints if row["event"] == "source_release"]
    ids = sorted(source_ids)
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("result requires exactly one source-release row per particle")
    if summary["census"]["launched"] != len(ids):
        raise ValueError("result source-release census differs")
    if (
        population["particle_count"] != len(ids)
        or population["selection_algorithm"]
        != "first_100_rows_in_frozen_file_order"
        or population["ordered_particle_id_sha256"].upper()
        != _canonical_sha(ids).upper()
    ):
        raise ValueError("result cohort differs from the campaign execution population")
    if (
        source_identity.get("event_sha256")
        != experiment["source"]["state"]["sha256"]
        or source_identity.get("particle_source_sha256")
        != experiment["source"]["particle_source"]["sha256"]
    ):
        raise ValueError("result source identity differs from the campaign source")
    if summary["resolution_time_basis"] != "detector_time_minus_pulse_effective_time":
        raise ValueError("baseline registration requires the pulse-effective clock")
    pulse_authority = experiment["single_flight_pulse_schedule_policy"][
        "fixed_execution_authority"
    ]
    planned_pulse_us, clock_tolerance_us = _pulse_clock_authority(experiment)
    observed_pulse_us = float(summary["pulse_effective_time_us"])
    if (
        summary["resolution_time_basis"]
        != campaign["pulse_resolution_optimization"]["clock_contract"][
            "resolution_time_basis"
        ]
        or abs(observed_pulse_us - planned_pulse_us) > clock_tolerance_us
        or pulse_authority["source_state_sha256"]
        != experiment["source"]["state"]["sha256"]
    ):
        raise ValueError("result pulse clock authority differs from the campaign")
    if baseline_evidence is not None:
        if baseline:
            raise ValueError("baseline result must not consume prior baseline evidence")
        _validate_baseline_evidence(
            campaign,
            experiment,
            baseline_evidence,
            registration_authority_sha256,
            source_identity,
            prefix_sha256,
            ids,
            summary,
            observed_cohort_authority,
            clock_tolerance_us,
        )
    elif not baseline:
        raise ValueError("paired candidate requires one frozen baseline evidence")
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "role": (
            "rf_oatof_pulse_resolution_baseline_result"
            if baseline
            else "rf_oatof_pulse_resolution_candidate_result"
        ),
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": campaign_sha256,
        "experiment_id": experiment["experiment_id"],
        "experiment_row_sha256": experiment_row_sha256,
        "experiment_row": experiment,
        "comparison": {
            "sequence": experiment["sequence"],
            "experiment_id": experiment["experiment_id"],
            "mode": execution_mode,
            "source_run_id": experiment["source"]["run_id"],
            "source_state_sha256": experiment["source"]["state"]["sha256"],
            "source_profile_id": experiment["source_profile_id"],
            "layout_profile_id": experiment["single_flight_layout_profile_id"],
            "frontend_grid_profile_id": experiment["single_flight_frontend_grid_profile_id"],
            "field_profile_id": experiment["single_flight_accelerator_field_profile_id"],
            "analysis_bootstrap_seed": analysis_identity["bootstrap_seed"],
            "analysis_bootstrap_resample_count": analysis_identity[
                "bootstrap_resample_count"
            ],
        },
        "source_identity": source_identity,
        "cohort_authority_mode": (
            "establish_observed_authority"
            if baseline else "require_frozen_baseline_authority"
        ),
        "observed_cohort_authority": observed_cohort_authority,
        "observed_handoff": observed_handoff,
        "analysis_randomness": analysis_identity,
        "cohort_census": cohort_census,
        "paired_checkpoint_rows": checkpoints,
        "prefix": {
            "path": prefix_path,
            "sha256": prefix_sha256,
            "count": 100,
            "selection_algorithm": population["selection_algorithm"],
            "selection_seed": population["selection_seed"],
            "ordered_particle_ids": ids,
            "particle_id_sha256_ordered": _canonical_sha(ids),
        },
        "clock": {
            "basis": summary["clock_basis"],
            "resolution_time_basis": summary["resolution_time_basis"],
            "pulse_effective_time_us": planned_pulse_us,
            "observed_serialized_pulse_effective_time_us": observed_pulse_us,
            "observed_minus_planned_us": observed_pulse_us - planned_pulse_us,
            "clock_abs_tolerance_us": clock_tolerance_us,
        },
        "census": summary["census"],
        "metrics": {
            "transmission": summary["transmission"],
            "pulse_effective_peak": summary["pulse_effective_peak"],
        },
        "execution_status": (
            "baseline_registered_not_candidate"
            if baseline
            else "candidate_screening_complete_not_qualified"
        ),
        "solver_execution_performed": True,
        "promotion_gate_invoked": False,
        "promotion_status": "not_evaluated",
        "claim_status": "REGISTRATION_ONLY",
        "formal_gate_passed": False,
    }
    if baseline:
        receipt["baseline_authority_id"] = (
            f"{campaign['campaign_id']}_{experiment_id}"
        )
        receipt["historical_migration_reference"] = {
            "status": "historical_migration_reference_only",
            "registration_authority_sha256": registration_authority_sha256,
            "campaign_cohort_reference": campaign.get(
                "pulse_resolution_cohort_authority"
            ),
        }
    else:
        receipt["frozen_baseline_evidence_sha256"] = (
            registration_authority_sha256
        )
    receipt["receipt_sha256"] = _canonical_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--campaign-sha256", required=True)
    parser.add_argument("--experiment-row-sha256", required=True)
    parser.add_argument("--experiment-id", required=True)
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
    _, derived_execution_mode = _experiment_and_mode(
        campaign, args.experiment_id
    )
    if args.execution_mode != derived_execution_mode:
        raise ValueError("transported execution mode differs from the campaign row")
    baseline_evidence = None
    if derived_execution_mode == "screening_prefix_n100_paired_candidate":
        baseline_evidence = json.loads(
            args.registration_authority.read_text(encoding="utf-8-sig")
        )
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
        baseline_evidence=baseline_evidence,
    )
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if args.promotion_receipt is not None:
        if baseline_evidence is None:
            raise ValueError("promotion receipt requires frozen baseline evidence")
        baseline_rows = baseline_evidence.get("paired_checkpoint_rows", [])
        if not isinstance(baseline_rows, list) or not baseline_rows:
            raise ValueError("frozen baseline evidence lacks paired checkpoint rows")
        promotion = evaluate_campaign_n100_paired_promotion(
            campaign,
            _screening_arm(baseline_rows, "pulse_resolution_baseline"),
            _screening_arm(checkpoints, args.experiment_id),
        )
        promotion.pop("receipt_sha256", None)
        promotion["baseline_result_sha256"] = args.registration_authority_sha256
        promotion["candidate_result_sha256"] = file_sha256(args.output)
        promotion["receipt_sha256"] = _canonical_sha(promotion)
        args.promotion_receipt.write_text(json.dumps(promotion, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
