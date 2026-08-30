"""Publish one immutable canonical restart from a successful time-series run."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.verify_run_manifest import verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    materialize_manifest_bound_restart,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
SCHEMA = (
    Path(__file__).resolve().parents[2] / "config" / "schemas" /
    "rf_oatof_manifest_bound_time_series_restart_materialization_receipt.schema.json"
)
MODE = "rf_oatof_time_series_restart_materialization"


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def materialize_run(
    *, repo_root: Path, producer_manifest_path: Path, run_dir: Path,
    sample_index: int = 1,
) -> Path:
    """Create one analysis run without mutating its successful producer."""

    repo_root = repo_root.resolve()
    workspace_root = repo_root.parent
    producer_manifest_path = producer_manifest_path.resolve()
    run_dir = run_dir.resolve()
    validate_run_id(run_dir.name)
    if run_dir.exists():
        raise ContractError("time-series restart run directory already exists")
    producer = _load(producer_manifest_path, "time-series producer manifest")
    if (
        producer.get("role") != "simulation_run_manifest"
        or producer.get("project") != INTEGRATION_ID
        or producer.get("mode") not in {
            "rf_to_oatof_simion_single_flight",
            "rf_oatof_pre_pulse_time_series_analysis_recovery",
        }
        or producer.get("status") != "success"
    ):
        raise ContractError("time-series producer manifest is not a successful screening run")
    try:
        verify_record(
            "time-series producer run_config", producer["run_config"],
            base_dir=producer_manifest_path.parent,
        )
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("time-series producer run_config identity differs") from exc
    producer_config_path = Path(producer["run_config"]["path"]).resolve()
    producer_config = _load(producer_config_path, "time-series producer config")
    if producer_config.get("parameters", {}).get("execution_mode") != (
        "real_pa_rf_pre_pulse_time_series"
    ):
        raise ContractError("producer is not a pulse-disabled time-series run")

    run_dir.mkdir(parents=True)
    results = run_dir / "results"
    results.mkdir()
    state_path = results / "canonical_pre_pulse_restart_state.csv"
    receipt_path = results / "time_series_restart_materialization_receipt.json"
    summary_path = run_dir / "summary.json"
    config_path = run_dir / "run_config.json"
    config = {
        "schema_version": 2,
        "run_id": run_dir.name,
        "project": INTEGRATION_ID,
        "mode": MODE,
        "project_root": str(workspace_root),
        "inputs": {
            "producer_manifest": str(producer_manifest_path),
            "producer_run_config": str(producer_config_path),
        },
        "parameters": {
            "sample_index": sample_index,
            "producer_execution_mode": "real_pa_rf_pre_pulse_time_series",
            "detector_results_used": False,
        },
        "artifact_retention": {
            "policy_version": 1, "class": "compact", "reason": None,
        },
        "formal_gate_passed": False,
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    try:
        receipt = materialize_manifest_bound_restart(
            child_manifest_path=producer_manifest_path,
            workspace_root=workspace_root,
            state_output_path=state_path,
            receipt_output_path=receipt_path,
            sample_index=sample_index,
        )
        validate_schema(receipt, SCHEMA)
    except Exception:
        # A partial analysis run cannot look like evidence.  Its directory is
        # retained only after the manifest-writing success path below.
        for path in (state_path, receipt_path, summary_path, config_path):
            path.unlink(missing_ok=True)
        results.rmdir()
        run_dir.rmdir()
        raise
    summary = {
        "schema_version": 1,
        "role": "rf_oatof_time_series_restart_materialization_summary",
        "status": "success",
        "producer_run_id": receipt["producer"]["run_id"],
        "sample_index": sample_index,
        "mother_population_count": receipt["selection"]["producer_population_denominator_count"],
        "conditional_restart_particle_count": receipt["pulse_target_state"]["particle_count"],
        "detector_results_used": False,
        "claim_status": "DEVELOPMENT_ONLY",
        "formal_gate_passed": False,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable, "-m", "common.contracts.write_run_manifest",
            "--run-config", str(config_path), "--manifest", str(run_dir / "run_manifest.json"),
            "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
            "--output", str(summary_path), "--output", str(state_path), "--output", str(receipt_path),
        ],
        cwd=repo_root, text=True, capture_output=True, encoding="utf-8",
        errors="replace", timeout=60, check=False,
    )
    if completed.returncode:
        raise ContractError(
            "time-series restart manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )
    return run_dir / "run_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--producer-manifest", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--sample-index", type=int, default=1)
    arguments = parser.parse_args()
    manifest = materialize_run(
        repo_root=arguments.repo_root, producer_manifest_path=arguments.producer_manifest,
        run_dir=arguments.run_dir, sample_index=arguments.sample_index,
    )
    print(f"TIME_SERIES_RESTART_MATERIALIZATION=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
