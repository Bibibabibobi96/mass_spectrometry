"""Materialize and dispatch one identity-bound pulse-on time-series successor.

The consumer campaign row is deliberately supplied by the researcher.  This
workflow never writes or amends a scientific campaign: it verifies that its
pre-registered restart binding is exactly the state materialized from the
successful pulse-disabled producer, then delegates solver dispatch to the
existing governed family entry point.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.materialize_time_series_restart import (
    materialize_run,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    expand_flat_experiment_authoring,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
PRODUCER_MODE = "real_pa_rf_pre_pulse_time_series"
REQUIRED_IDENTITY_KEYS = (
    "connection_profile_id",
    "layout_profile_id",
    "architecture_generation_id",
    "source_profile_id",
    "field_overlay_id",
    "three_zone_candidate_sha256",
)


def _consumer_identity_value(consumer: dict[str, Any], key: str) -> Any:
    """Read one identity from the resolved campaign representation.

    The compact campaign intentionally retains the Candidate as a path/SHA
    record.  The prepared producer records its SHA as a scalar parameter, so
    normalize that one representation difference before identity comparison.
    """

    if key == "layout_profile_id":
        return consumer.get("single_flight_layout_profile_id")
    if key == "three_zone_candidate_sha256":
        candidate = consumer.get("single_flight_three_zone_candidate")
        if isinstance(candidate, dict):
            return candidate.get("sha256")
    return consumer.get(key)


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _consumer_row(campaign_path: Path, experiment_id: str) -> dict[str, Any]:
    campaign = _load(campaign_path, "successor consumer campaign")
    if (
        campaign.get("role") != "rf_multipole_oatof_experiment_campaign"
        or campaign.get("integration_id") != INTEGRATION_ID
    ):
        raise ContractError("successor consumer campaign identity differs")
    campaign = expand_flat_experiment_authoring(campaign)
    rows = [
        row for row in campaign.get("experiments", [])
        if isinstance(row, dict) and row.get("experiment_id") == experiment_id
    ]
    if len(rows) != 1:
        raise ContractError("successor consumer experiment must resolve exactly once")
    return rows[0]


def _restart_sample_index(
    *, campaign_path: Path, experiment_id: str, workspace_root: Path,
) -> int:
    """Recover the detector-blind sample index bound by the consumer receipt."""

    consumer = _consumer_row(campaign_path, experiment_id)
    state = consumer.get("pre_pulse_source_state")
    receipt_record = state.get("materialization_receipt") if isinstance(state, dict) else None
    if not isinstance(receipt_record, dict) or not isinstance(receipt_record.get("path"), str):
        raise ContractError("successor materialization receipt is missing")
    receipt_path = Path(receipt_record["path"])
    if not receipt_path.is_absolute():
        receipt_path = workspace_root / receipt_path
    receipt = _load(receipt_path, "successor materialization receipt")
    selection = receipt.get("selection")
    sample_index = selection.get("sample_index") if isinstance(selection, dict) else None
    if isinstance(sample_index, bool) or not isinstance(sample_index, int) or sample_index < 1:
        raise ContractError("successor materialization sample index is invalid")
    return sample_index


def _producer_identity(producer_manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _load(producer_manifest_path, "time-series producer manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("status") != "success"
    ):
        raise ContractError("time-series producer is not a successful integration run")
    config_record = manifest.get("run_config")
    if not isinstance(config_record, dict) or not isinstance(config_record.get("path"), str):
        raise ContractError("time-series producer run config record is incomplete")
    config = _load(Path(config_record["path"]), "time-series producer config")
    parameters = config.get("parameters")
    inputs = config.get("inputs")
    if not isinstance(parameters, dict) or not isinstance(inputs, dict):
        raise ContractError("time-series producer config is incomplete")
    if parameters.get("execution_mode") != PRODUCER_MODE:
        raise ContractError("producer is not a pulse-disabled time-series run")
    source_contract_path = inputs.get("resolved_source_contract")
    if not isinstance(source_contract_path, str):
        raise ContractError("time-series producer source identity is missing")
    source_contract = _load(Path(source_contract_path), "time-series producer source contract")
    branch = source_contract.get("source_branches", {}).get(parameters.get("source_branch_id"))
    if not isinstance(branch, dict) or not isinstance(branch.get("source"), dict):
        raise ContractError("time-series producer source branch identity is missing")
    return manifest, parameters, branch["source"]


def validate_successor(
    *, producer_manifest_path: Path, consumer_campaign_path: Path,
    consumer_experiment_id: str, materialization_manifest_path: Path,
) -> dict[str, Any]:
    """Reject a consumer unless it restarts the exact producer state and identity."""

    producer_manifest, producer_parameters, producer_source = _producer_identity(
        producer_manifest_path
    )
    consumer = _consumer_row(consumer_campaign_path, consumer_experiment_id)
    if consumer.get("source_release_mode") != "pre_pulse_restart":
        raise ContractError("successor consumer must use pre_pulse_restart")
    mismatches = [
        key for key in REQUIRED_IDENTITY_KEYS
        if _consumer_identity_value(consumer, key) != producer_parameters.get(key)
    ]
    if mismatches:
        raise ContractError("successor physical identity differs: " + ", ".join(mismatches))
    consumer_source = consumer.get("source")
    if not isinstance(consumer_source, dict):
        raise ContractError("successor consumer source identity is missing")
    for key in ("run_id", "launched_particle_count", "manifest", "state", "particle_source", "metadata"):
        if consumer_source.get(key) != producer_source.get(key):
            raise ContractError(f"successor source identity differs: {key}")
    restart = consumer.get("pre_pulse_source_state")
    population = consumer.get("single_flight_population", {}).get("execution_population")
    if not isinstance(restart, dict) or not isinstance(population, dict):
        raise ContractError("successor restart state or population is missing")
    materialization_manifest = _load(
        materialization_manifest_path, "time-series restart materialization manifest"
    )
    materialization_config = _load(
        Path(materialization_manifest["run_config"]["path"]), "time-series restart materialization config"
    )
    receipt_path = materialization_manifest_path.parent / "results" / "time_series_restart_materialization_receipt.json"
    receipt = _load(receipt_path, "time-series restart materialization receipt")
    target = receipt.get("pulse_target_state", {})
    if (
        materialization_config.get("inputs", {}).get("producer_manifest")
        != str(producer_manifest_path.resolve())
        or restart.get("sha256") != target.get("sha256")
        or restart.get("particle_count") != target.get("particle_count")
        or population.get("particle_count") != target.get("particle_count")
        or population.get("ordered_particle_id_sha256") != target.get("ordered_particle_id_sha256")
        or restart.get("materialization_receipt", {}).get("sha256") != file_sha256(receipt_path)
    ):
        raise ContractError("successor restart state/population differs from materialized producer")
    return {
        "status": "PASS",
        "producer_run_id": producer_manifest["run_id"],
        "consumer_experiment_id": consumer_experiment_id,
        "pulse_disabled_transition": {"producer": True, "consumer": False},
        "restart_particle_count": target["particle_count"],
        "restart_state_sha256": target["sha256"],
    }


def _run(command: list[str], *, repo_root: Path, failure: str) -> None:
    completed = subprocess.run(
        command, cwd=repo_root, check=False, text=True, encoding="utf-8", errors="replace", timeout=900
    )
    if completed.returncode:
        raise ContractError(f"{failure} (exit_code={completed.returncode})")


def orchestrate(
    *, repo_root: Path, producer_manifest_path: Path, materialization_run_dir: Path,
    consumer_campaign_path: Path, consumer_experiment_id: str, execute: bool,
    materialization_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Materialize, validate, and optionally dispatch through the governed entry point."""

    if materialization_manifest_path is None:
        sample_index = _restart_sample_index(
            campaign_path=consumer_campaign_path,
            experiment_id=consumer_experiment_id,
            workspace_root=repo_root.parent,
        )
        materialization_manifest = materialize_run(
            repo_root=repo_root, producer_manifest_path=producer_manifest_path,
            run_dir=materialization_run_dir, sample_index=sample_index,
        )
    else:
        materialization_manifest = materialization_manifest_path.resolve()
        receipt = _load(
            materialization_manifest.parent / "results" / "time_series_restart_materialization_receipt.json",
            "time-series restart materialization receipt",
        )
        sample_index = int(receipt.get("selection", {}).get("sample_index", 0))
        if sample_index < 1:
            raise ContractError("successor materialization sample index is invalid")
    result = validate_successor(
        producer_manifest_path=producer_manifest_path,
        consumer_campaign_path=consumer_campaign_path,
        consumer_experiment_id=consumer_experiment_id,
        materialization_manifest_path=materialization_manifest,
    )
    result["materialization_manifest"] = str(materialization_manifest)
    result["sample_index"] = sample_index
    if execute:
        runner = Path(__file__).with_name("execute.ps1")
        _run(
            ["pwsh", "-NoProfile", "-File", str(runner), "-Campaign", str(consumer_campaign_path),
             "-ExperimentId", consumer_experiment_id, "-Exploration", "-SolverAuthorized"],
            repo_root=repo_root, failure="governed pulse-on successor execution failed",
        )
        result["governed_execution"] = "DISPATCHED"
    else:
        result["governed_execution"] = "NOT_DISPATCHED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--producer-manifest", required=True, type=Path)
    parser.add_argument("--materialization-run-dir", type=Path)
    parser.add_argument("--materialization-manifest", type=Path)
    parser.add_argument("--consumer-campaign", required=True, type=Path)
    parser.add_argument("--consumer-experiment-id", required=True)
    parser.add_argument("--execute", action="store_true", help="dispatch the validated consumer via execute.ps1")
    args = parser.parse_args()
    if (args.materialization_run_dir is None) == (args.materialization_manifest is None):
        parser.error("supply exactly one of --materialization-run-dir or --materialization-manifest")
    result = orchestrate(
        repo_root=args.repo_root.resolve(), producer_manifest_path=args.producer_manifest.resolve(),
        materialization_run_dir=(args.materialization_run_dir or Path(".")).resolve(),
        consumer_campaign_path=args.consumer_campaign.resolve(),
        consumer_experiment_id=args.consumer_experiment_id, execute=args.execute,
        materialization_manifest_path=(
            args.materialization_manifest.resolve()
            if args.materialization_manifest is not None else None
        ),
    )
    print("TIME_SERIES_SUCCESSOR=PASS " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
