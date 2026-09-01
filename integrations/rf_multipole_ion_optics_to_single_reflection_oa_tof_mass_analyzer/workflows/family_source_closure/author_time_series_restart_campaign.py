"""Author one compact pulse-on consumer from a materialized pre-pulse state."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    INTEGRATION_SCHEMA_DIR,
    RESOLVED_CAMPAIGN_SCHEMA_PATH,
    _workspace_relative,
    expand_flat_experiment_authoring,
    expand_pre_pulse_campaign_profile,
)


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(document, dict):
        raise ContractError(f"{label} must be a JSON object")
    return document


def _state_record(receipt: dict[str, Any]) -> dict[str, Any]:
    target = receipt.get("pulse_target_state")
    selection = receipt.get("selection")
    if not isinstance(target, dict) or not isinstance(selection, dict):
        raise ContractError("restart materialization receipt is incomplete")
    required = ("path", "sha256", "particle_count", "coordinate_frame", "source_state_epoch", "source_state_locus")
    if any(key not in target for key in required):
        raise ContractError("restart target state is incomplete")
    return {
        "path": target["path"], "sha256": target["sha256"],
        "particle_count": target["particle_count"],
        "coordinate_frame": target["coordinate_frame"],
        "release_event": "pre_pulse_state",
        "materialization_receipt": {
            "path": None, "sha256": None,
        },
        "source_state_epoch": target["source_state_epoch"],
        "source_state_locus": target["source_state_locus"]["kind"] if isinstance(target["source_state_locus"], dict) else target["source_state_locus"],
        "position_rowwise_abs_tolerance_mm": 1e-9,
        "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
        "clock_abs_tolerance_us": 1e-9,
        "energy_abs_tolerance_eV": 5e-9,
        "postselection_prohibited": selection.get("postselection_prohibited") is True,
    }


def author_campaign(
    *, source_campaign_path: Path, source_experiment_id: str,
    materialization_receipt_path: Path, output_path: Path,
    campaign_id: str, consumer_experiment_id: str, workspace: Path,
) -> dict[str, Any]:
    """Write a single-row compact restart campaign with full-mother denominators."""

    if output_path.exists():
        raise ContractError("restart campaign output already exists")
    source = expand_pre_pulse_campaign_profile(
        _load(source_campaign_path, "source full-flight campaign")
    )
    experiments = source.get("experiments")
    if not isinstance(experiments, dict) or set(experiments) != {"shared", "variation_axes", "rows"}:
        raise ContractError("source campaign must use compact authoring")
    rows = experiments["rows"]
    if not isinstance(rows, list):
        raise ContractError("source campaign rows are invalid")
    matches = [row for row in rows if isinstance(row, dict) and row.get("experiment_id") == source_experiment_id]
    if len(matches) != 1 or not isinstance(matches[0].get("values"), dict):
        raise ContractError("source experiment must resolve exactly once")
    receipt = _load(materialization_receipt_path, "restart materialization receipt")
    state = _state_record(receipt)
    state["materialization_receipt"] = {
        "path": _workspace_relative(materialization_receipt_path.resolve(), workspace.resolve()),
        "sha256": file_sha256(materialization_receipt_path),
    }
    count = int(state["particle_count"])
    selection = receipt["selection"]
    denominator = int(selection["producer_population_denominator_count"])
    if count < 1 or denominator < count:
        raise ContractError("restart population count is invalid")
    shared = copy.deepcopy(experiments["shared"])
    shared["source_release_mode"] = "pre_pulse_restart"
    shared["pre_pulse_source_state"] = state
    shared["single_flight_population"] = {
        "population_id": f"{consumer_experiment_id}_conditional_restart",
        "population_mode": "pre_pulse_restart",
        "source_authority": {
            "input_role": "pre_pulse_source_state",
            "table_binding": "experiment_pre_pulse_source_state",
            "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1",
        },
        "execution_population": {
            "particle_count": count,
            "ordered_particle_id_sha256": receipt["pulse_target_state"]["ordered_particle_id_sha256"],
            "selection_algorithm": "all_rows_in_frozen_file_order",
            "selection_seed": 0,
        },
        "denominators": {"population_count": denominator, "eligible_population_count": count},
        "analysis_randomness": copy.deepcopy(experiments["shared"]["single_flight_population"]["analysis_randomness"]),
        "postselection_policy": "prohibited",
    }
    shared["single_flight_pulse_schedule_policy"].pop("cache_miss_policy", None)
    result = {
        "schema_version": source["schema_version"], "role": source["role"],
        "integration_id": source["integration_id"], "campaign_id": campaign_id,
        "status": "exploration", "execution_policy": copy.deepcopy(source["execution_policy"]),
        "claim_limit": (
            "DEVELOPMENT_ONLY conditional restart transport. Detector timing "
            f"metrics condition on the {count} detector-blind pre-pulse states; "
            f"all transmission and loss rates retain the frozen {denominator}-ion "
            "mother denominator."
        ),
        "experiments": {
            "shared": shared, "variation_axes": list(experiments["variation_axes"]),
            "rows": [{"experiment_id": consumer_experiment_id, "values": copy.deepcopy(matches[0]["values"])}],
        },
    }
    validate_schema(
        result,
        INTEGRATION_SCHEMA_DIR / "rf_multipole_oatof_experiment_campaign.schema.json",
    )
    validate_schema(expand_flat_experiment_authoring(result), RESOLVED_CAMPAIGN_SCHEMA_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-campaign", required=True, type=Path)
    parser.add_argument("--source-experiment-id", required=True)
    parser.add_argument("--materialization-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--consumer-experiment-id", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    campaign = author_campaign(
        source_campaign_path=args.source_campaign,
        source_experiment_id=args.source_experiment_id,
        materialization_receipt_path=args.materialization_receipt,
        output_path=args.output,
        campaign_id=args.campaign_id,
        consumer_experiment_id=args.consumer_experiment_id,
        workspace=args.workspace,
    )
    print("TIME_SERIES_RESTART_CAMPAIGN_AUTHORED=PASS " + json.dumps({"campaign_id": campaign["campaign_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
