"""Author an identity-bound continuous-cohort full-flight campaign.

This is a configuration authoring boundary only.  It promotes no result and
never materializes a restart: every generated row replays the original
continuous-front-end population while binding its own detector-blind pulse
candidate transition.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.verify_run_manifest import record_path, verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    INTEGRATION_SCHEMA_DIR,
    _resolve_pulse_transition,
    _workspace_relative,
    expand_flat_experiment_authoring,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
TRANSITION_NAME = "pulse_timing_transition.json"
REQUIRED_CACHE_MISS_MODE = "auto_detector_blind_discovery_and_confirmation_v1"


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _load_mapping(path: Path, label: str) -> dict[str, str]:
    value = _load_object(path, label)
    if not value or any(not isinstance(key, str) or not isinstance(item, str)
                        or not key or not item for key, item in value.items()):
        raise ContractError(f"{label} must be a non-empty experiment-id mapping")
    return value


def _require_continuous_full_population(shared: dict[str, Any]) -> None:
    if shared.get("source_release_mode") != "continuous_frontend":
        raise ContractError("pre-pulse source_release_mode is not continuous_frontend")
    population = shared.get("single_flight_population")
    if not isinstance(population, dict) or population.get("population_mode") != (
        "continuous_injection_full_population"
    ):
        raise ContractError("pre-pulse population is not a continuous full population")
    execution = population.get("execution_population")
    if not isinstance(execution, dict) or int(execution.get("particle_count", 0)) < 1:
        raise ContractError("pre-pulse continuous population is incomplete")
    if population.get("postselection_policy") != "prohibited":
        raise ContractError("pre-pulse population permits postselection")


def _transition_record(
    *, workspace: Path, run_directory: Path, experiment_id: str,
) -> dict[str, Any]:
    run_dir = run_directory.resolve()
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load_object(manifest_path, "pre-pulse parent manifest")
    if (
        manifest.get("status") != "success"
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("run_id") != run_dir.name
    ):
        raise ContractError("pre-pulse parent manifest is not a successful matching run")
    try:
        verify_record("pre-pulse parent run_config", manifest["run_config"], base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("pre-pulse parent run_config identity differs") from exc
    run_config_path = record_path(manifest["run_config"], base_dir=run_dir)
    run_config = _load_object(run_config_path, "pre-pulse parent run config")
    if run_config.get("experiment_id") != experiment_id:
        raise ContractError("pre-pulse parent experiment mapping differs")
    transition_path = run_dir / "results" / TRANSITION_NAME
    # The shared resolver verifies the schema, parent manifest output binding,
    # and candidate-receipt identity before a generated campaign can reference it.
    _resolve_pulse_transition(workspace, transition_path)
    return {
        "path": _workspace_relative(transition_path, workspace),
        "sha256": file_sha256(transition_path),
    }


def author_campaign(
    *, source_campaign_path: Path, producer_mapping_path: Path,
    run_id_mapping_path: Path, output_path: Path, campaign_id: str,
    workspace: Path,
) -> dict[str, Any]:
    """Create a flat pulse-on campaign for the explicitly supplied producers."""

    output = output_path.resolve()
    if output.exists():
        raise ContractError("full-flight campaign output already exists")
    if not campaign_id:
        raise ContractError("full-flight campaign_id is required")
    campaign = _load_object(source_campaign_path, "pre-pulse campaign")
    if campaign.get("role") != "rf_multipole_oatof_experiment_campaign" or (
        campaign.get("integration_id") != INTEGRATION_ID
    ):
        raise ContractError("pre-pulse campaign identity differs")
    experiments = campaign.get("experiments")
    if not isinstance(experiments, dict) or set(experiments) != {
        "shared", "variation_axes", "rows"
    }:
        raise ContractError("pre-pulse campaign must use flat experiment authoring")
    shared = experiments["shared"]
    rows = experiments["rows"]
    if not isinstance(shared, dict) or not isinstance(rows, list):
        raise ContractError("pre-pulse flat authoring is incomplete")
    _require_continuous_full_population(shared)
    screening = campaign.get("pre_pulse_time_series_screening")
    if not isinstance(screening, dict):
        raise ContractError("pre-pulse time-series screening is missing")
    time_grid = screening.get("time_grid_profile_id")
    spatial_window = screening.get("spatial_window_profile_id")
    if not isinstance(time_grid, str) or not isinstance(spatial_window, str):
        raise ContractError("pre-pulse screening timing identities are incomplete")
    producer_mapping = _load_mapping(producer_mapping_path, "producer mapping")
    run_id_mapping = _load_mapping(run_id_mapping_path, "run-id mapping")
    if set(producer_mapping) != set(run_id_mapping):
        raise ContractError("producer and run-id experiment mappings differ")
    rows_by_id = {
        row.get("experiment_id"): row for row in rows if isinstance(row, dict)
    }
    if len(rows_by_id) != len(rows) or set(producer_mapping).difference(rows_by_id):
        raise ContractError("producer mapping contains an unknown or duplicate experiment")

    authored_rows: list[dict[str, Any]] = []
    seen_transitions: set[str] = set()
    for row in rows:
        experiment_id = row["experiment_id"]
        if experiment_id not in producer_mapping:
            continue
        transition = _transition_record(
            workspace=workspace.resolve(),
            run_directory=Path(producer_mapping[experiment_id]),
            experiment_id=experiment_id,
        )
        if transition["sha256"] in seen_transitions:
            raise ContractError("duplicate pre-pulse transition authority")
        seen_transitions.add(transition["sha256"])
        overrides = copy.deepcopy(row.get("overrides"))
        if not isinstance(overrides, dict):
            raise ContractError("pre-pulse row overrides are incomplete")
        overrides["pulse_timing_transition_authority"] = transition
        authored_rows.append({
            "sequence": len(authored_rows) + 1,
            "experiment_id": experiment_id.replace("_pre_pulse_", "_full_flight_"),
            "run_id": run_id_mapping[experiment_id],
            "overrides": overrides,
        })
    if not authored_rows:
        raise ContractError("no producer-aligned pre-pulse rows were selected")

    result = copy.deepcopy(campaign)
    result["campaign_id"] = campaign_id
    result["status"] = "exploration"
    result.pop("pre_pulse_time_series_screening", None)
    result["claim_limit"] = (
        "REAL_FIELD_EXPLORATORY_COMPARISON_ONLY. Each row replays the complete "
        "ordered continuous-frontend mother cohort with its own manifest-bound "
        "detector-blind pulse candidate; no survivor restart or common-hit "
        "postselection is permitted."
    )
    result["experiments"] = {
        "shared": copy.deepcopy(shared),
        "variation_axes": list(experiments["variation_axes"])
        + ([] if "pulse_timing_transition_authority" in experiments["variation_axes"]
           else ["pulse_timing_transition_authority"]),
        "rows": authored_rows,
    }
    policy = result["experiments"]["shared"].get("single_flight_pulse_schedule_policy")
    if not isinstance(policy, dict):
        raise ContractError("pre-pulse pulse schedule policy is missing")
    policy["cache_miss_policy"] = {
        "mode": REQUIRED_CACHE_MISS_MODE,
        "time_grid_profile_id": time_grid,
        "spatial_window_profile_id": spatial_window,
    }
    validate_schema(
        expand_flat_experiment_authoring(result),
        INTEGRATION_SCHEMA_DIR / "rf_multipole_oatof_experiment_campaign.schema.json",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-campaign", required=True, type=Path)
    parser.add_argument("--producer-map", required=True, type=Path,
                        help="JSON object: pre-pulse experiment id -> parent run directory")
    parser.add_argument("--run-id-map", required=True, type=Path,
                        help="JSON object: pre-pulse experiment id -> new full-flight run id")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    result = author_campaign(
        source_campaign_path=args.source_campaign, producer_mapping_path=args.producer_map,
        run_id_mapping_path=args.run_id_map, output_path=args.output,
        campaign_id=args.campaign_id, workspace=args.workspace,
    )
    print("FULL_FLIGHT_CAMPAIGN_AUTHORED=PASS " + json.dumps({
        "campaign_id": result["campaign_id"],
        "row_count": len(result["experiments"]["rows"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
