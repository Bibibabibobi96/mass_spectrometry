"""Publish a new immutable analysis package from a failed frozen analysis input.

This deliberately never changes the failed package.  It is for a post-solver
analysis failure where every source manifest/state was frozen successfully but
the analysis implementation subsequently received a correctness fix.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record


ROLE = "multipole_campaign_analysis_recovery"


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _verified_failed_analysis(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _load(path / "run_manifest.json", "failed analysis manifest")
    if (manifest.get("role"), manifest.get("status")) != ("simulation_run_manifest", "failed"):
        raise ContractError("analysis recovery requires a failed immutable analysis manifest")
    if not str(manifest.get("mode", "")).startswith("multipole_campaign_"):
        raise ContractError("failed manifest is not a multipole campaign analysis")
    try:
        verify_record("failed analysis run_config", manifest["run_config"], base_dir=path)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"failed analysis input {name}", record, base_dir=path)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("failed analysis frozen inputs differ") from exc
    config = _load(path / "run_config.json", "failed analysis run_config")
    inputs = config.get("inputs")
    if not isinstance(inputs, dict) or not all(
        isinstance(inputs.get(key), str)
        for key in ("source_001_run_manifest", "source_002_run_manifest", "source_001_state", "source_002_state")
    ):
        raise ContractError("failed analysis source bindings are incomplete")
    return manifest, config


def recover(*, repo_root: Path, failed_analysis_dir: Path, recovery_dir: Path) -> Path:
    failed_analysis_dir, recovery_dir = failed_analysis_dir.resolve(), recovery_dir.resolve()
    if recovery_dir.exists():
        raise ContractError("analysis recovery directory already exists and may not be overwritten")
    failed_manifest, failed_config = _verified_failed_analysis(failed_analysis_dir)
    parameters = failed_config.get("parameters")
    if not isinstance(parameters, dict):
        raise ContractError("failed analysis parameters are incomplete")
    analysis_parameters = parameters.get("analysis_parameters")
    if not isinstance(analysis_parameters, dict):
        raise ContractError("failed analysis fixed parameters are incomplete")
    recovery_dir.mkdir(parents=True)
    inputs_dir, results_dir = recovery_dir / "inputs", recovery_dir / "results"
    inputs_dir.mkdir(); results_dir.mkdir()
    copied: dict[str, str] = {}
    for name, source in failed_config["inputs"].items():
        source_path = Path(source)
        if not source_path.is_file():
            raise ContractError(f"failed analysis input is missing: {name}")
        destination = inputs_dir / source_path.name
        shutil.copy2(source_path, destination)
        copied[name] = str(destination)
    current_analysis = repo_root / "common/multipole/analyze_source_model_comparison.py"
    current_plot = repo_root / "common/multipole/exit_state_plot.py"
    if not current_analysis.is_file() or not current_plot.is_file():
        raise ContractError("current campaign analysis consumers are missing")
    current_analysis_copy = inputs_dir / "recovered_analysis_module.py"
    current_plot_copy = inputs_dir / "recovered_plot_module.py"
    shutil.copy2(current_analysis, current_analysis_copy)
    shutil.copy2(current_plot, current_plot_copy)
    metrics, report = results_dir / "metrics.json", results_dir / "report.md"
    figure, figure_manifest = results_dir / "figure.png", results_dir / "figure_manifest.json"
    baseline = str(parameters.get("baseline_experiment_id", ""))
    experiments = parameters.get("experiment_ids")
    if not baseline or not isinstance(experiments, list) or len(experiments) != 2:
        raise ContractError("failed analysis series identity is incomplete")
    labels = [str(item) for item in experiments]
    if baseline not in labels:
        raise ContractError("failed analysis baseline is not in its frozen series")
    analysis_command = [
        sys.executable, "-m", "common.multipole.analyze_source_model_comparison",
        "--series", labels[0], copied["source_001_run_manifest"],
        "--series", labels[1], copied["source_002_run_manifest"],
        "--baseline-label", baseline, "--output", str(metrics), "--markdown", str(report),
    ]
    plot_command = [
        sys.executable, "-m", "common.multipole.exit_state_plot",
        "--series", f"{labels[0]}={copied['source_001_state']}={failed_manifest['run_id']}",
        "--series", f"{labels[1]}={copied['source_002_state']}={failed_manifest['run_id']}",
        "--output", str(figure), "--manifest", str(figure_manifest),
        "--title", "RF octupole planar versus independent axial-volume source comparison",
        "--purpose", "Frozen-input analysis recovery after consumer correctness fix",
        "--bin-count", str(analysis_parameters["bin_count"]), "--dpi", str(analysis_parameters["dpi"]),
        "--repo-root", str(repo_root),
    ]
    for command, label in ((analysis_command, "metrics"), (plot_command, "figure")):
        completed = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, timeout=600)
        if completed.returncode:
            raise ContractError(f"analysis recovery {label} failed: {(completed.stdout + completed.stderr).strip()}")
    config = {
        "schema_version": 2, "run_id": recovery_dir.name, "project": failed_config["project"],
        "mode": ROLE, "project_root": str(repo_root), "inputs": {
            "failed_analysis_manifest": str(failed_analysis_dir / "run_manifest.json"),
            **copied, "recovered_analysis_module": str(current_analysis_copy),
            "recovered_plot_module": str(current_plot_copy),
        }, "parameters": {**parameters, "recovery_of_run_id": failed_manifest["run_id"],
            "solver_reexecuted": False}, "formal_gate_passed": False,
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
    }
    config_path = recovery_dir / "run_config.json"
    _write(config_path, config)
    summary = recovery_dir / "summary.json"
    _write(summary, {"schema_version": 1, "role": ROLE, "status": "success", "solver_reexecuted": False,
        "failed_analysis_run_id": failed_manifest["run_id"], "failed_analysis_manifest_sha256": file_sha256(failed_analysis_dir / "run_manifest.json")})
    command = [sys.executable, "-m", "common.contracts.write_run_manifest", "--run-config", str(config_path),
        "--manifest", str(recovery_dir / "run_manifest.json"), "--status", "success", "--software",
        f"Python {sys.version_info.major}.{sys.version_info.minor}", "--output", str(summary), "--output", str(metrics),
        "--output", str(report), "--output", str(figure), "--output", str(figure_manifest)]
    completed = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, timeout=300)
    if completed.returncode:
        raise ContractError(f"analysis recovery manifest publication failed: {(completed.stdout + completed.stderr).strip()}")
    return recovery_dir / "run_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--failed-analysis-dir", required=True, type=Path)
    parser.add_argument("--recovery-run-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = recover(repo_root=args.repo_root.resolve(), failed_analysis_dir=args.failed_analysis_dir,
        recovery_dir=args.recovery_run_dir)
    print(f"MULTIPOLE_CAMPAIGN_ANALYSIS_RECOVERY=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
