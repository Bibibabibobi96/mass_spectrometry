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

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    materialize,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.scan_pre_pulse_trace_pulse_time import (
    _trace_completed,
    scan,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
RECOVERY_MODE = "rf_oatof_pre_pulse_time_series_analysis_recovery"
RECOVERABLE_SOURCE_STATUSES = frozenset({"failed", "interrupted", "checkpoint"})
PRE_PULSE_INAPPLICABLE_PA_ROLES = (
    "frontend",
    "full_coarse_bridge",
    "connector_collision",
    "accelerator_main",
    "accelerator_entrance_local",
    "accelerator_overlay",
    "accelerator_entrance_overlay",
    "accelerator_intermediate_overlay",
    "accelerator_intermediate2_overlay",
    "flight_tube",
    "reflectron",
)


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


def _completed_trace_logs(run_dir: Path) -> list[Path]:
    """Return the authoritative batch streams for pre-pulse materialization.

    Current SIMION programs write governed TRACE records to their dedicated
    ``.trace.log`` files.  Older failed runs kept the same records in stdout,
    so retain that format only as a backward-compatible fallback.  Do not mix
    the two: a partial current trace set must fail the terminal census rather
    than silently combine unrelated streams.
    """

    logs_dir = run_dir / "logs"
    trace_logs = sorted(logs_dir.glob("simion__batch*.trace.log"))
    if trace_logs:
        return trace_logs
    return sorted(logs_dir.glob("simion__batch*.stdout.log"))


def _recoverable_source_status(status: object) -> bool:
    """Return whether a source terminal record can enter log-based recovery.

    A ``checkpoint`` is admissible only after the caller verifies every native
    TRACE stream completed.  This is the normal durable state when SIMION
    batches finish but post-processing stops before the terminal manifest.
    """

    return isinstance(status, str) and status in RECOVERABLE_SOURCE_STATUSES


def _validate_recovery_run_id(recovery_dir: Path) -> None:
    """Reject an invalid recovery identifier before materializing large logs."""

    try:
        validate_run_id(recovery_dir.name)
    except ValueError as exc:
        raise ContractError("recovery run_id is invalid") from exc


def _verify_failed_run(run_dir: Path) -> tuple[Path, dict[str, Any], list[Path]]:
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load(manifest_path, "failed screening manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or not _recoverable_source_status(manifest.get("status"))
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
    logs = _completed_trace_logs(run_dir)
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
    if not logs or any(not _trace_completed(path) for path in logs):
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
    simion_configuration = failed_run_dir / "inputs" / "simion_single_flight.json"
    if not all(path.is_file() for path in (
        contract, row_map, initial_state, population, mother_source,
        source_contract, pulse_schedule, geometry, simion_configuration,
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
        "pre_pulse_time_series_contract": contract,
        "particle_row_map": row_map,
        "initial_global_state": initial_state,
        "resolved_population_contract": population,
        "mother_particle_source": mother_source,
        "resolved_source_contract": source_contract,
        "pulse_schedule": pulse_schedule,
        "oatof_resolved_geometry": geometry,
        "simion_single_flight": simion_configuration,
    }.items():
        destination = recovery_inputs / source_path.name
        shutil.copy2(source_path, destination)
        recovered_paths[key] = destination
    recovery_parameters = copy.deepcopy(parameters)
    dispositions = recovery_parameters.get("pa_cache_dispositions")
    if isinstance(dispositions, dict):
        # A recovery runs only Python materialization.  Carrying historical
        # ``formal`` labels for omitted PA roles falsely asserts a dependency
        # and conflicts with the current four-instance pre-pulse contract.
        for role in PRE_PULSE_INAPPLICABLE_PA_ROLES:
            disposition = dispositions.get(role)
            if isinstance(disposition, dict):
                disposition["key"] = None
                disposition["disposition"] = "not_applicable"
    contract_value = _load(contract, "failed screening contract")
    trace_policy = contract_value.get("trace_policy")
    compact_handoff = (
        isinstance(trace_policy, dict)
        and trace_policy.get("mode") == "natural_trajectory_compact_handoff_v1"
    )
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
            **{key: str(path) for key, path in recovered_paths.items()},
        },
        "parameters": recovery_parameters,
        "artifact_retention": {
            "policy_version": 1,
            # A natural TRACE recovery retains its complete per-sample census
            # both in the materializer receipt and in the summary.  Those
            # auditable records can exceed the compact policy's 100 MiB
            # optional-file limit, even though the state table itself is
            # mandatory evidence for the detector-blind selector.
            "class": "compact" if compact_handoff else "qualification",
            "reason": (
                None
                if compact_handoff
                else "materialized natural pre-pulse trace required for detector-blind pulse selection"
            ),
        },
        "formal_gate_passed": False,
    }


def recover(*, repo_root: Path, failed_run_dir: Path, recovery_dir: Path) -> Path:
    failed_run_dir = failed_run_dir.resolve()
    recovery_dir = recovery_dir.resolve()
    _validate_recovery_run_id(recovery_dir)
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
    contract = _load(
        recovery_dir / "inputs" / "pre_pulse_time_series_screening_contract.json",
        "recovery screening contract",
    )
    trace_policy = contract.get("trace_policy")
    compact_handoff = (
        isinstance(trace_policy, dict)
        and trace_policy.get("mode") == "natural_trajectory_compact_handoff_v1"
    )
    output_paths: list[Path]
    materialized_outputs: dict[str, Any]
    if compact_handoff:
        handoff_path = results / "pre_pulse_compact_handoff.csv"
        handoff_receipt_path = results / "pre_pulse_compact_handoff_receipt.json"
        selection_path = results / "pre_pulse_compact_handoff_selection.json"
        result = scan(
            recovery_dir,
            handoff_output=handoff_path,
            receipt_output=handoff_receipt_path,
            trace_paths=logs,
        )
        _write(selection_path, result)
        _write(recovery_dir / "summary.json", {
            "schema_version": 1,
            "role": "rf_oatof_pre_pulse_time_series_analysis_recovery_summary",
            "status": "success",
            "execution_mode": "compact_detector_blind_handoff_recovery",
            "solver_reexecuted": False,
            "selected_time_us": result["selected_time_us"],
            "pulse_eligible_particle_count": result["pulse_eligible_count"],
        })
        output_paths = [
            recovery_dir / "summary.json",
            handoff_path,
            handoff_receipt_path,
            selection_path,
            results / "pre_pulse_particle_terminal_states.csv",
        ]
        materialized_outputs = {
            "mode": "selected_pulse_handoff_only_v1",
            "selected_time_us": result["selected_time_us"],
            "pulse_eligible_particle_count": result["pulse_eligible_count"],
            "handoff": {
                "path": str(handoff_path),
                "sha256": file_sha256(handoff_path),
            },
            "handoff_receipt": {
                "path": str(handoff_receipt_path),
                "sha256": file_sha256(handoff_receipt_path),
            },
        }
    else:
        result = materialize(
            stdout_paths=logs,
            run_config_path=recovery_config_path,
            expected_contract_sha256=expected_sha,
            states_path=results / "pre_pulse_time_series_states.csv.gz",
            receipt_path=results / "pre_pulse_time_series_screening_receipt.json",
            summary_path=recovery_dir / "summary.json",
        )
        output_paths = [
            recovery_dir / "summary.json",
            results / "pre_pulse_time_series_states.csv.gz",
            results / "pre_pulse_time_series_screening_receipt.json",
        ]
        materialized_outputs = {
            "mode": "complete_time_series_archive_v1",
            "state_row_count": result.state_row_count,
            "states": result.states_record,
            "screening_receipt": result.receipt_record,
        }
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
        "materialized_outputs": materialized_outputs,
    }
    receipt_path = results / "pre_pulse_time_series_analysis_recovery_receipt.json"
    _write(receipt_path, receipt)
    command = [
        sys.executable, "-m", "common.contracts.write_run_manifest",
        "--run-config", str(recovery_config_path),
        "--manifest", str(recovery_dir / "run_manifest.json"),
        "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
        *[
            argument
            for path in (*output_paths, receipt_path)
            for argument in ("--output", str(path))
        ],
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
