"""Recover completed pre-pulse-screening logs into a new immutable analysis run.

The failed solver run is never changed.  This command is only for a completed
SIMION dispatch whose governed TRACE materialization failed after the solver
exited; it binds the original manifest, configuration and every raw batch log.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    materialize,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
RECOVERY_MODE = "rf_oatof_pre_pulse_time_series_analysis_recovery"


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _is_recoverable_stale_config(
    *, manifest: dict[str, Any], config: dict[str, Any], run_dir: Path
) -> bool:
    """Accept only the known post-dispatch input-index enrichment mismatch.

    A failed runner can append discovery-only input records while assembling its
    failure manifest.  If that final manifest publication itself fails, its
    earlier run-config record becomes stale.  The raw logs are still usable
    only when their governing frozen contract remains manifest-bound.
    """
    inputs = manifest.get("inputs")
    parameters = config.get("parameters")
    if not isinstance(inputs, dict) or not isinstance(parameters, dict):
        return False
    contract_record = inputs.get("pre_pulse_time_series_contract")
    if not isinstance(contract_record, dict):
        return False
    contract_sha256 = contract_record.get("sha256")
    return (
        config.get("run_id") == run_dir.name
        and config.get("project") == INTEGRATION_ID
        and config.get("mode") == "rf_to_oatof_simion_single_flight"
        and parameters.get("execution_mode") == "real_pa_rf_pre_pulse_time_series"
        and isinstance(contract_sha256, str)
        and parameters.get("pre_pulse_time_series_contract_sha256") == contract_sha256
    )


def _verify_failed_run(run_dir: Path) -> tuple[Path, dict[str, Any], list[Path]]:
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load(manifest_path, "failed screening manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") not in {"failed", "interrupted"}
        or manifest.get("mode") != "rf_to_oatof_simion_single_flight"
    ):
        raise ContractError("failed screening manifest identity differs")
    config_path = run_dir / "run_config.json"
    config = _load(config_path, "failed screening run configuration")
    config_matches_manifest = True
    try:
        verify_record("failed screening run_config", manifest["run_config"], base_dir=run_dir)
    except (AssertionError, KeyError, TypeError):
        config_matches_manifest = False
    try:
        # The complete set of frozen input records is the recovery authority,
        # including the time-series contract that governs every TRACE row.
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"failed screening input {name}", record, base_dir=run_dir)
        # A recovery may have already materialized the completed logs before
        # the parent is marked failed/interrupted.  The mutable summary is not
        # recovery evidence; all raw SIMION logs are independently verified
        # below.  Other recorded outputs remain immutable and are checked.
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            if Path(str(record.get("path", ""))).name == "summary.json":
                continue
            verify_record(f"failed screening output {index}", record, base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("failed screening manifest records differ") from exc
    if not config_matches_manifest and not _is_recoverable_stale_config(
        manifest=manifest, config=config, run_dir=run_dir
    ):
        raise ContractError("failed screening run configuration differs outside the recoverable input-index case")
    parameters = config.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("execution_mode") != "real_pa_rf_pre_pulse_time_series":
        raise ContractError("failed run is not a pre-pulse screening")
    # A continuation keeps a completed prefix as an immutable input and writes
    # only the unfinished suffix under logs/.  Recover both automatically from
    # the manifest-bound continuation plan; never ask callers to concatenate
    # logs or state tables by hand.
    logs = sorted((run_dir / "logs").glob("simion__batch*.stdout.log"))
    continuation_plan = (
        run_dir / "inputs" / "pre_pulse_batch_continuation"
        / "simion_batch_continuation_plan.json"
    )
    if continuation_plan.is_file():
        plan = _load(continuation_plan, "pre-pulse batch continuation plan")
        batches = plan.get("batches")
        if not isinstance(batches, list):
            raise ContractError("pre-pulse continuation batch plan is incomplete")
        imported: list[Path] = []
        for batch in batches:
            trace = batch.get("imported_completed_trace") if isinstance(batch, dict) else None
            if trace is None:
                continue
            if not isinstance(trace, dict) or not isinstance(trace.get("path"), str):
                raise ContractError("pre-pulse continuation imported trace is invalid")
            path = Path(trace["path"]).resolve()
            if not path.is_file() or file_sha256(path) != trace.get("sha256"):
                raise ContractError("pre-pulse continuation imported trace identity differs")
            imported.append(path)
        logs = imported + logs
    if not logs or any("Fly completed." not in path.read_text(encoding="utf-8", errors="replace") for path in logs):
        raise ContractError("failed screening has incomplete SIMION batch logs")
    return config_path, config, logs


def build_recovery_config(
    *, failed_run_dir: Path, failed_config: dict[str, Any], recovery_dir: Path
) -> dict[str, Any]:
    """Make a new run-local materializer configuration without changing source files."""
    inputs = failed_config.get("inputs")
    parameters = failed_config.get("parameters")
    if not isinstance(inputs, dict) or not isinstance(parameters, dict):
        raise ContractError("failed screening configuration is incomplete")
    contract = failed_run_dir / "inputs" / "pre_pulse_time_series_screening_contract.json"
    row_map = failed_run_dir / "inputs" / "single_flight_particle_row_map.csv"
    initial_state = failed_run_dir / "inputs" / "single_flight_initial_global_state.csv"
    population = failed_run_dir / "inputs" / "resolved_population_contract.json"
    mother_source = failed_run_dir / "inputs" / "mother_particle_source.csv"
    source_contract = failed_run_dir / "inputs" / "resolved_source_contract.json"
    pulse_schedule = failed_run_dir / "inputs" / "resolved_single_flight_pulse_schedule.json"
    geometry = failed_run_dir / "inputs" / "oatof_resolved_geometry.json"
    if not all(path.is_file() for path in (
        contract, row_map, initial_state, population, mother_source,
        source_contract, pulse_schedule, geometry,
    )):
        raise ContractError("failed screening run-local frozen inputs are missing")
    population_value = _load(population, "failed screening population contract")
    experiment_id = population_value.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ContractError("failed screening population experiment identity is missing")
    recovery_inputs = recovery_dir / "inputs"
    recovery_inputs.mkdir(parents=True, exist_ok=True)
    recovered_paths: dict[str, Path] = {}
    for key, source_path in {
        "initial_global_state": initial_state,
        "resolved_population_contract": population,
        "mother_particle_source": mother_source,
        "resolved_source_contract": source_contract,
        "pulse_schedule": pulse_schedule,
        "oatof_resolved_geometry": geometry,
    }.items():
        destination = recovery_inputs / source_path.name
        shutil.copy2(source_path, destination)
        recovered_paths[key] = destination
    return {
        "schema_version": 2,
        "run_id": recovery_dir.name,
        "project": INTEGRATION_ID,
        "mode": RECOVERY_MODE,
        "project_root": failed_config.get("project_root"),
        "experiment_id": experiment_id,
        "inputs": {
            "failed_child_manifest": str(failed_run_dir / "run_manifest.json"),
            "failed_run_config": str(failed_run_dir / "run_config.json"),
            "pre_pulse_time_series_contract": str(contract),
            "particle_row_map": str(row_map),
            **{key: str(path) for key, path in recovered_paths.items()},
        },
        "parameters": copy.deepcopy(parameters),
        "artifact_retention": {
            "policy_version": 1,
            "class": "compact",
            "reason": None,
        },
        "formal_gate_passed": False,
    }


def recover(*, repo_root: Path, failed_run_dir: Path, recovery_dir: Path) -> Path:
    failed_run_dir = failed_run_dir.resolve()
    recovery_dir = recovery_dir.resolve()
    if recovery_dir.exists():
        raise ContractError("recovery directory already exists and may not be overwritten")
    config_path, failed_config, logs = _verify_failed_run(failed_run_dir)
    recovery_dir.mkdir(parents=True)
    results = recovery_dir / "results"
    results.mkdir()
    recovery_config = build_recovery_config(
        failed_run_dir=failed_run_dir, failed_config=failed_config, recovery_dir=recovery_dir
    )
    recovery_config_path = recovery_dir / "run_config.json"
    _write(recovery_config_path, recovery_config)
    parameters = recovery_config["parameters"]
    expected_sha = parameters.get("pre_pulse_time_series_contract_sha256")
    if not isinstance(expected_sha, str):
        raise ContractError("failed screening contract hash is missing")
    result = materialize(
        stdout_paths=logs,
        run_config_path=recovery_config_path,
        expected_contract_sha256=expected_sha,
        states_path=results / "pre_pulse_time_series_states.csv.gz",
        receipt_path=results / "pre_pulse_time_series_screening_receipt.json",
        summary_path=recovery_dir / "summary.json",
    )
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_pre_pulse_time_series_analysis_recovery_receipt",
        "status": "success",
        "solver_reexecuted": False,
        "failed_run": {
            "manifest": str(failed_run_dir / "run_manifest.json"),
            "manifest_sha256": file_sha256(failed_run_dir / "run_manifest.json"),
            "run_config": str(config_path),
            "run_config_sha256": file_sha256(config_path),
        },
        "raw_stdout_logs": [
            {"path": str(path), "sha256": file_sha256(path)} for path in logs
        ],
        "materialized_outputs": {
            "state_row_count": result.state_row_count,
            "states": result.states_record,
            "screening_receipt": result.receipt_record,
        },
    }
    receipt_path = results / "pre_pulse_time_series_analysis_recovery_receipt.json"
    _write(receipt_path, receipt)
    command = [
        sys.executable, "-m", "common.contracts.write_run_manifest",
        "--run-config", str(recovery_config_path),
        "--manifest", str(recovery_dir / "run_manifest.json"),
        "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
        "--output", str(recovery_dir / "summary.json"),
        "--output", str(results / "pre_pulse_time_series_states.csv.gz"),
        "--output", str(results / "pre_pulse_time_series_screening_receipt.json"),
        "--output", str(receipt_path),
    ]
    completed = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, timeout=300)
    if completed.returncode:
        raise ContractError(f"recovery manifest publication failed: {(completed.stdout + completed.stderr).strip()}")
    return recovery_dir / "run_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--failed-run-dir", required=True, type=Path)
    parser.add_argument("--recovery-run-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = recover(repo_root=args.repo_root.resolve(), failed_run_dir=args.failed_run_dir, recovery_dir=args.recovery_run_dir)
    print(f"PRE_PULSE_SCREENING_RECOVERY=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
