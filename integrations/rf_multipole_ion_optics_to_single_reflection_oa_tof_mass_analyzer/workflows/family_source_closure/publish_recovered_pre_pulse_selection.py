"""Publish detector-blind pulse selection from a recovered natural TRACE run.

The original SIMION child may have completed every batch but failed before its
family parent wrote an execution receipt.  A successful recovery manifest is
still a complete, immutable authority for the materialized state table.  This
publisher intentionally needs no historical parent receipt and never reruns a
solver; it binds the recovery output to the original child's frozen inputs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.select_real_field_pulse_time import (
    select_and_write,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
RECOVERY_MODE = "rf_oatof_pre_pulse_time_series_analysis_recovery"
SELECTION_MODE = "rf_oatof_recovered_pre_pulse_selection"


def _load(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{role} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{role} must be an object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def _manifest_output(manifest: dict[str, Any], name: str, run_dir: Path) -> Path:
    records = [
        record for record in manifest.get("outputs", [])
        if isinstance(record, dict) and Path(str(record.get("path", ""))).name == name
    ]
    if len(records) != 1:
        raise ContractError(f"recovered screening output {name} is missing")
    try:
        verify_record(f"recovered screening output {name}", records[0], base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError(f"recovered screening output {name} differs") from exc
    return (run_dir / records[0]["path"]).resolve()


def publish(*, repo_root: Path, recovery_run_dir: Path, selection_run_dir: Path) -> Path:
    """Select and publish one detector-blind pulse from immutable recovery evidence."""

    recovery_run_dir = recovery_run_dir.resolve()
    selection_run_dir = selection_run_dir.resolve()
    identity = validate_run_id(selection_run_dir.name)
    if identity["activity"] != "analysis" or identity["scope"] != "python":
        raise ContractError("selection run ID must be analysis/python")
    if selection_run_dir.exists():
        raise ContractError("selection run directory already exists")
    recovery_manifest_path = recovery_run_dir / "run_manifest.json"
    recovery_manifest = _load(recovery_manifest_path, "recovery manifest")
    recovery_config = _load(recovery_run_dir / "run_config.json", "recovery configuration")
    if (
        recovery_manifest.get("status") != "success"
        or recovery_manifest.get("mode") != RECOVERY_MODE
        or recovery_config.get("mode") != RECOVERY_MODE
    ):
        raise ContractError("recovery run is not a successful natural TRACE recovery")
    failed_child_manifest = Path(
        str(recovery_config.get("inputs", {}).get("failed_child_manifest", ""))
    ).resolve()
    child_dir = failed_child_manifest.parent
    child_config = _load(child_dir / "run_config.json", "original screening configuration")
    if child_config.get("parameters", {}).get("execution_mode") != "real_pa_rf_pre_pulse_time_series":
        raise ContractError("recovery source is not pre-pulse screening")
    inputs = child_config.get("inputs")
    if not isinstance(inputs, dict):
        raise ContractError("original screening inputs are missing")
    configuration = Path(str(inputs.get("configuration", ""))).resolve()
    if not configuration.is_file():
        raise ContractError("original single-flight configuration is missing")
    source_inputs = child_dir / "inputs"
    required = {
        "resolved_population_contract": recovery_run_dir / "inputs" / "resolved_population_contract.json",
        "mother_particle_source": recovery_run_dir / "inputs" / "mother_particle_source.csv",
        "resolved_source_contract": recovery_run_dir / "inputs" / "resolved_source_contract.json",
        "pulse_schedule": recovery_run_dir / "inputs" / "resolved_single_flight_pulse_schedule.json",
        "oatof_resolved_geometry": recovery_run_dir / "inputs" / "oatof_resolved_geometry.json",
        "resolved_connection": source_inputs / "resolved_connection.json",
    }
    if any(not path.is_file() for path in required.values()):
        raise ContractError("recovered selection inputs are incomplete")
    state_table = _manifest_output(
        recovery_manifest, "pre_pulse_time_series_states.csv.gz", recovery_run_dir
    )
    screening_receipt = _manifest_output(
        recovery_manifest, "pre_pulse_time_series_screening_receipt.json", recovery_run_dir
    )
    screening_contract = Path(
        str(recovery_config.get("inputs", {}).get("pre_pulse_time_series_contract", ""))
    ).resolve()
    if not screening_contract.is_file():
        raise ContractError("recovered screening contract is missing")
    selection_run_dir.mkdir(parents=True)
    results = selection_run_dir / "results"
    try:
        receipt = select_and_write(
            state_table_path=state_table,
            screening_contract_path=screening_contract,
            screening_receipt_path=screening_receipt,
            resolved_population_path=required["resolved_population_contract"],
            population_table_path=required["mother_particle_source"],
            resolved_source_path=required["resolved_source_contract"],
            resolved_connection_path=required["resolved_connection"],
            screening_manifest_path=recovery_manifest_path,
            selector_source_path=repo_root / "integrations" / INTEGRATION_ID / "analysis" / "select_real_field_pulse_time.py",
            geometry_path=required["oatof_resolved_geometry"],
            single_flight_configuration_path=configuration,
            ballistic_schedule_path=required["pulse_schedule"],
            candidate_table_path=results / "detector_blind_pulse_timing_candidates.csv",
            receipt_path=results / "detector_blind_pulse_timing_candidate_receipt.json",
        )
        config_path = selection_run_dir / "run_config.json"
        _write(config_path, {
            "schema_version": 2, "run_id": selection_run_dir.name,
            "project": INTEGRATION_ID, "mode": SELECTION_MODE,
            "project_root": str(repo_root.parent),
            "inputs": {
                "recovery_manifest": str(recovery_manifest_path),
                "failed_child_manifest": str(failed_child_manifest),
                "screening_contract": str(screening_contract),
                **{name: str(path) for name, path in required.items()},
            },
            "parameters": {"selected_time_us": receipt["selected_time_us"], "solver_rerun": False},
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
            "formal_gate_passed": False,
        })
        summary_path = selection_run_dir / "summary.json"
        _write(summary_path, {
            "schema_version": 1, "role": "rf_oatof_recovered_pre_pulse_selection_summary",
            "status": "success", "claim_status": "FUNCTIONAL_SCREEN_ONLY",
            "solver_rerun": False, "selected_time_us": receipt["selected_time_us"],
            "claims_prohibited": ["detector", "resolution", "optimization", "Candidate", "Formal"],
        })
        manifest_path = selection_run_dir / "run_manifest.json"
        completed = subprocess.run([
            sys.executable, "-m", "common.contracts.write_run_manifest",
            "--run-config", str(config_path), "--manifest", str(manifest_path),
            "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
            "--output", str(summary_path),
            "--output", str(results / "detector_blind_pulse_timing_candidates.csv"),
            "--output", str(results / "detector_blind_pulse_timing_candidate_receipt.json"),
        ], cwd=repo_root, capture_output=True, text=True, timeout=300)
        if completed.returncode:
            raise ContractError("recovered pulse-selection manifest publication failed")
        return manifest_path
    except Exception:
        if selection_run_dir.exists() and not (selection_run_dir / "run_manifest.json").exists():
            import shutil
            shutil.rmtree(selection_run_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--recovery-run-dir", required=True, type=Path)
    parser.add_argument("--selection-run-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = publish(repo_root=args.repo_root.resolve(), recovery_run_dir=args.recovery_run_dir,
                       selection_run_dir=args.selection_run_dir.resolve())
    print(f"RECOVERED_PRE_PULSE_SELECTION=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
