"""Verify the frozen B/C method-comparator contract and write its receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.contracts.file_identity import file_sha256

ALLOWED_DIFFERENCES = {
    "sequence", "experiment_id", "run_id", "single_flight_accelerator_field_profile_id"
}


def verify(campaign_path: Path, output: Path) -> dict[str, object]:
    campaign = json.loads(campaign_path.read_text(encoding="utf-8-sig"))
    real, ideal = campaign["experiments"]
    differences = sorted(key for key in set(real) | set(ideal) if real.get(key) != ideal.get(key))
    if set(differences) != ALLOWED_DIFFERENCES:
        raise ValueError(f"B/C frozen fields differ: {differences}")
    if real["single_flight_accelerator_field_profile_id"] != "accelerator_real_pa":
        raise ValueError("B is not the real-field arm")
    if ideal["single_flight_accelerator_field_profile_id"] != "accelerator_ideal_piecewise_uniform":
        raise ValueError("C is not the ideal-piecewise arm")
    source = real["pre_pulse_source_state"]
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_long_focus_native_method_comparator_receipt",
        "campaign_sha256": file_sha256(campaign_path),
        "historical_arm_a": {
            "status": "read_only",
            "run_id": "20260812_210000__sim__simion__rf-oatof-terminal-analytic-ideal-boundary-step__n1000__r01",
            "pulse_time_us": 45.5585544411,
            "source_sha256": source["sha256"],
            "particle_count": source["particle_count"],
        },
        "b_c_allowed_differences": differences,
        "b_c_frozen_identity_assertion": "pass",
        "physical_contract_same_long_focus": True,
        "pa_discretization_identical_to_historical": False,
        "field_identical_to_historical_claim": False,
        "historical_to_b_intervention": "official_native_grid_implementation_bundle",
        "b_to_c_intervention": "real_vs_ideal_piecewise_accelerator_field",
        "required_rebuild": ["accelerator", "reflectron", "iob"],
        "reusable": ["flight_tube", "detector"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def verify_field_region_matrix(
    campaign_path: Path,
    profile_registry_path: Path,
    real_summary_path: Path,
    output: Path,
) -> dict[str, object]:
    """Verify the RR/IR/RI/II controlled matrix and extra global oracle."""
    campaign = json.loads(campaign_path.read_text(encoding="utf-8-sig"))
    rows = campaign["experiments"]
    if len(rows) != 4:
        raise ValueError("field-region campaign must contain IR, RI, II and oracle")
    controlled, oracle = rows[:3], rows[3]
    for left, right in zip(controlled, controlled[1:]):
        differences = {
            key for key in set(left) | set(right) if left.get(key) != right.get(key)
        }
        if differences != ALLOWED_DIFFERENCES:
            raise ValueError(f"controlled arm frozen fields differ: {sorted(differences)}")

    registry = json.loads(profile_registry_path.read_text(encoding="utf-8-sig"))
    profiles = {row["profile_id"]: row for row in registry["accelerator_field_profiles"]}
    expected = {
        "RR": ("accelerator_real_pa", 0, 0, 0),
        "IR": ("accelerator_ideal_stage1_real_stage2", 0, 1, 0),
        "RI": ("accelerator_real_stage1_ideal_stage2", 0, 0, 1),
        "II": ("accelerator_ideal_stage1_stage2_real_reflectron", 0, 1, 1),
    }
    row_by_arm = dict(zip(("IR", "RI", "II"), controlled))
    matrix = {}
    for arm, (profile_id, global_flag, stage1, stage2) in expected.items():
        profile = profiles[profile_id]
        actual = (
            profile["single_flight_ideal_accel_enable"],
            profile["single_flight_ideal_accel_stage1_enable"],
            profile["single_flight_ideal_accel_stage2_enable"],
        )
        if actual != (global_flag, stage1, stage2):
            raise ValueError(f"{arm} governed flags differ: {actual}")
        if arm in row_by_arm and row_by_arm[arm]["single_flight_accelerator_field_profile_id"] != profile_id:
            raise ValueError(f"{arm} campaign profile differs")
        matrix[arm] = {
            "profile_id": profile_id,
            "global_piecewise_enable": global_flag,
            "stage1_ideal_enable": stage1,
            "stage2_ideal_enable": stage2,
            "run_id": row_by_arm.get(arm, {}).get("run_id"),
        }

    oracle_profile_id = "accelerator_ideal_piecewise_uniform"
    if oracle["single_flight_accelerator_field_profile_id"] != oracle_profile_id:
        raise ValueError("global piecewise row is not the extra oracle")
    if profiles[oracle_profile_id]["single_flight_ideal_accel_enable"] != 1:
        raise ValueError("global piecewise oracle flag is disabled")

    real_summary = json.loads(real_summary_path.read_text(encoding="utf-8-sig"))
    provenance = real_summary.get("reanalysis_provenance", {})
    if provenance.get("role") != "manifest_bound_single_flight_spatial_reanalysis":
        raise ValueError("RR reuse is not manifest-bound")
    matrix["RR"]["run_id"] = provenance["source_run_id"]
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_short_focus_field_region_2x2_identity_receipt",
        "campaign_sha256": file_sha256(campaign_path),
        "profile_registry_sha256": file_sha256(profile_registry_path),
        "real_reanalysis_summary_sha256": file_sha256(real_summary_path),
        "real_baseline_provenance": provenance,
        "controlled_matrix": matrix,
        "controlled_new_arm_allowed_differences": sorted(ALLOWED_DIFFERENCES),
        "only_governed_stage_flags_and_run_identities_differ": True,
        "global_piecewise": {
            "classification": "extra_oracle_not_2x2_causal_arm",
            "profile_id": oracle_profile_id,
            "run_id": oracle["run_id"],
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile-registry", type=Path)
    parser.add_argument("--real-summary", type=Path)
    args = parser.parse_args()
    if args.profile_registry or args.real_summary:
        if not args.profile_registry or not args.real_summary:
            parser.error("field-region verification requires both registry and summary")
        verify_field_region_matrix(
            args.campaign, args.profile_registry, args.real_summary, args.output
        )
    else:
        verify(args.campaign, args.output)


if __name__ == "__main__":
    main()
