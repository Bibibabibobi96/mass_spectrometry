"""Recover completed pre-pulse-screening logs into a new immutable analysis run.

The failed solver run is never changed.  This command is only for a completed
SIMION dispatch whose governed TRACE materialization failed after the solver
exited; it binds the original manifest, configuration and every raw batch log.
"""

from __future__ import annotations

import argparse
import copy
import json
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


def _verify_failed_run(run_dir: Path) -> tuple[Path, dict[str, Any], list[Path]]:
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load(manifest_path, "failed screening manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "failed"
        or manifest.get("mode") != "rf_to_oatof_simion_single_flight"
    ):
        raise ContractError("failed screening manifest identity differs")
    try:
        verify_record("failed screening run_config", manifest["run_config"], base_dir=run_dir)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"failed screening input {name}", record, base_dir=run_dir)
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            verify_record(f"failed screening output {index}", record, base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("failed screening manifest records differ") from exc
    config_path = run_dir / "run_config.json"
    config = _load(config_path, "failed screening run configuration")
    parameters = config.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("execution_mode") != "real_pa_rf_pre_pulse_time_series":
        raise ContractError("failed run is not a pre-pulse screening")
    logs = sorted((run_dir / "logs").glob("simion__batch*.stdout.log"))
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
    if not contract.is_file() or not row_map.is_file():
        raise ContractError("failed screening run-local frozen inputs are missing")
    return {
        "schema_version": 2,
        "run_id": recovery_dir.name,
        "project": INTEGRATION_ID,
        "mode": RECOVERY_MODE,
        "project_root": failed_config.get("project_root"),
        "inputs": {
            "failed_child_manifest": str(failed_run_dir / "run_manifest.json"),
            "failed_run_config": str(failed_run_dir / "run_config.json"),
            "pre_pulse_time_series_contract": str(contract),
            "particle_row_map": str(row_map),
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
        states_path=results / "pre_pulse_time_series_states.csv",
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
        "--output", str(results / "pre_pulse_time_series_states.csv"),
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
