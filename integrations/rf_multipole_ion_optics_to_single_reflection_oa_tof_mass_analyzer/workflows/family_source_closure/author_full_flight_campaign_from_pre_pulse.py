"""Author an identity-bound continuous-cohort full-flight campaign.

This is a configuration authoring boundary only.  It promotes no result and
never materializes a restart: every generated row replays the original
continuous-front-end population while binding its own detector-blind pulse
candidate transition.
"""

from __future__ import annotations

import argparse
import copy
import csv
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


def _manifest_record(
    manifest: dict[str, Any], *, run_dir: Path, name: str,
) -> tuple[Path, dict[str, Any]]:
    """Return one verified manifest record whose basename is *name*."""

    matches: list[tuple[Path, dict[str, Any]]] = []
    for record in manifest.get("inputs", {}).values():
        if not isinstance(record, dict):
            continue
        path = record_path(record, base_dir=run_dir)
        if path.name == name:
            matches.append((path, record))
    for record in manifest.get("outputs", []):
        if not isinstance(record, dict):
            continue
        path = record_path(record, base_dir=run_dir)
        if path.name == name:
            matches.append((path, record))
    if len(matches) != 1:
        raise ContractError(f"pre-pulse producer manifest lacks unique {name}")
    path, record = matches[0]
    try:
        verify_record(f"pre-pulse producer {name}", record, base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError(f"pre-pulse producer {name} identity differs") from exc
    return path, record


def _require_complete_mother_source(source_path: Path, expected_count: int) -> None:
    """Require one manifest-bound CSV row and unique particle ID per mother ion."""

    try:
        with source_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "particle_id" not in reader.fieldnames:
                raise ContractError("pre-pulse producer mother source lacks particle_id")
            particle_ids = [row.get("particle_id") for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ContractError("pre-pulse producer mother source is unreadable") from exc
    if (
        len(particle_ids) != expected_count
        or any(not isinstance(value, str) or not value for value in particle_ids)
        or len(set(particle_ids)) != expected_count
    ):
        raise ContractError("pre-pulse producer mother source is not the complete cohort")


def _validate_screening_producer(
    *, run_directory: Path, experiment_id: str,
    shared_population: dict[str, Any],
) -> None:
    """Require a successful detector-blind screen of the full mother cohort.

    The full-flight campaign deliberately does not carry a survivor restart or
    a preselected timing transition.  This verification is an authoring gate:
    it proves that the supplied producer is the corresponding detector-blind
    screen and that its frozen population is the same full continuous cohort.
    """

    run_dir = run_directory.resolve()
    manifest = _load_object(run_dir / "run_manifest.json", "pre-pulse producer manifest")
    if (
        manifest.get("status") != "success"
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("run_id") != run_dir.name
    ):
        raise ContractError("pre-pulse producer manifest is not a successful matching run")
    try:
        verify_record("pre-pulse producer run_config", manifest["run_config"], base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("pre-pulse producer run_config identity differs") from exc

    population_path, population_record = _manifest_record(
        manifest, run_dir=run_dir, name="resolved_population_contract.json"
    )
    mother_source_path, mother_source_record = _manifest_record(
        manifest, run_dir=run_dir, name="mother_particle_source.csv"
    )
    receipt_path, receipt_record = _manifest_record(
        manifest, run_dir=run_dir,
        name="pre_pulse_time_series_screening_receipt.json",
    )
    population = _load_object(population_path, "pre-pulse producer population")
    receipt = _load_object(receipt_path, "pre-pulse screening receipt")
    execution = population.get("execution_population")
    authority = population.get("source_authority")
    denominators = population.get("denominators")
    expected_execution = shared_population["execution_population"]
    expected_denominators = shared_population.get("denominators")
    expected_source = shared_population.get("source_authority")
    if not all(isinstance(value, dict) for value in (
        execution, authority, denominators, expected_execution,
        expected_denominators, expected_source,
    )) or not isinstance(population.get("single_flight_execution"), dict) or not isinstance(
        authority.get("table"), dict
    ):
        raise ContractError("pre-pulse producer population contract is incomplete")
    expected_count = expected_execution.get("particle_count")
    if (
        population.get("role") != "rf_oatof_resolved_population_contract"
        or population.get("experiment_id") != experiment_id
        or population.get("population_mode") != "continuous_injection_full_population"
        or population.get("source_release_mode") != "continuous_frontend"
        or population.get("postselection_policy") != "prohibited"
        or population.get("single_flight_execution", {}).get("is_pre_pulse_restart") is not False
        or execution.get("selection_algorithm") != "all_rows_in_frozen_file_order"
        or execution.get("particle_count") != expected_count
        or execution.get("ordered_particle_id_sha256")
        != expected_execution.get("ordered_particle_id_sha256")
        or denominators.get("population_count") != expected_denominators.get("population_count")
        or denominators.get("eligible_population_count")
        != expected_denominators.get("eligible_population_count")
        or authority.get("table_binding") != expected_source.get("table_binding")
        or authority.get("particle_count") != expected_count
        or authority.get("table", {}).get("sha256") != mother_source_record.get("sha256")
        or file_sha256(population_path) != population_record.get("sha256")
    ):
        raise ContractError("pre-pulse producer full mother population identity differs")
    identities = receipt.get("identities")
    if (
        receipt.get("role") != "rf_oatof_pre_pulse_time_series_screening_receipt"
        or receipt.get("status") != "success"
        or receipt.get("qualification") != "FUNCTIONAL_ONLY"
        or receipt.get("execution_mode") != "real_pa_rf_pre_pulse_time_series"
        or receipt.get("pulse_disabled") is not True
        or receipt.get("resolution_claim_allowed") is not False
        or receipt.get("particle_count") != expected_count
        or not isinstance(identities, dict)
        or identities.get("experiment_id") != experiment_id
        or identities.get("resolved_population_contract_sha256") != population_record.get("sha256")
        or identities.get("mother_particle_source_sha256") != mother_source_record.get("sha256")
        or identities.get("ordered_particle_id_sha256")
        != expected_execution.get("ordered_particle_id_sha256")
        or not isinstance(receipt.get("sample_census"), list)
        or not receipt["sample_census"]
        or not isinstance(receipt.get("terminal_census"), dict)
        or receipt_record.get("sha256") != file_sha256(receipt_path)
    ):
        raise ContractError("pre-pulse screening receipt full-cohort identity differs")
    # The source is verified via its manifest record above.  Keeping this
    # content check makes malformed but correctly addressed records fail before
    # authoring a supposedly complete-cohort full flight.
    _require_complete_mother_source(mother_source_path, expected_count)


def _producer_transition_or_screening(
    *, workspace: Path, run_directory: Path, experiment_id: str,
    shared_population: dict[str, Any],
) -> dict[str, Any] | None:
    """Use legacy transition authority when present, otherwise validate screen."""

    transition_path = run_directory.resolve() / "results" / TRANSITION_NAME
    if transition_path.is_file():
        return _transition_record(
            workspace=workspace, run_directory=run_directory,
            experiment_id=experiment_id,
        )
    _validate_screening_producer(
        run_directory=run_directory, experiment_id=experiment_id,
        shared_population=shared_population,
    )
    return None


def author_campaign(
    *, source_campaign_path: Path, producer_mapping_path: Path,
    output_path: Path, campaign_id: str,
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
    rows_by_id = {
        row.get("experiment_id"): row for row in rows if isinstance(row, dict)
    }
    if len(rows_by_id) != len(rows) or set(producer_mapping).difference(rows_by_id):
        raise ContractError("producer mapping contains an unknown or duplicate experiment")

    authored_rows: list[dict[str, Any]] = []
    seen_transitions: set[str] = set()
    has_transition_authority = False
    for row in rows:
        experiment_id = row["experiment_id"]
        if experiment_id not in producer_mapping:
            continue
        producer_directory = Path(producer_mapping[experiment_id])
        if not producer_directory.is_absolute():
            producer_directory = workspace / producer_directory
        transition = _producer_transition_or_screening(
            workspace=workspace.resolve(),
            run_directory=producer_directory,
            experiment_id=experiment_id,
            shared_population=shared["single_flight_population"],
        )
        if transition is not None:
            if transition["sha256"] in seen_transitions:
                raise ContractError("duplicate pre-pulse transition authority")
            seen_transitions.add(transition["sha256"])
            has_transition_authority = True
        values = copy.deepcopy(row.get("values"))
        if not isinstance(values, dict):
            raise ContractError("pre-pulse row values are incomplete")
        if transition is not None:
            values["pulse_timing_transition_authority"] = transition
        authored_rows.append({
            "experiment_id": experiment_id.replace("_pre_pulse_", "_full_flight_"),
            "values": values,
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
        + ([] if not has_transition_authority
           or "pulse_timing_transition_authority" in experiments["variation_axes"]
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
                        help="Path to a JSON object mapping pre-pulse experiment ID to parent run directory")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    result = author_campaign(
        source_campaign_path=args.source_campaign, producer_mapping_path=args.producer_map,
        output_path=args.output,
        campaign_id=args.campaign_id, workspace=args.workspace,
    )
    print("FULL_FLIGHT_CAMPAIGN_AUTHORED=PASS " + json.dumps({
        "campaign_id": result["campaign_id"],
        "row_count": len(result["experiments"]["rows"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
