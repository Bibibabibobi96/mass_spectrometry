"""Create a standard artifact run for one ideal multipole L1 project."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common.contracts.artifact_naming import validate_run_id
from common.contracts.artifact_project import ensure_artifact_project
from common.multipole.family_contract import from_high_order_baseline, operating_contract_document
from common.multipole.ideal_transport import evaluate_contract, write_results


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parent
CONTRACT_TOOLS = REPO_ROOT / "common" / "contracts"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _manifest(run_config: Path, status: str, outputs: list[Path]) -> None:
    command = [
        sys.executable, str(CONTRACT_TOOLS / "write_run_manifest.py"),
        "--run-config", str(run_config), "--status", status,
        "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    subprocess.run(command, check=True, cwd=REPO_ROOT, timeout=60)


def execute(project_root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    baseline_source = project_root / "config" / "baseline.json"
    mode_source = project_root / "config" / "modes" / "transport_no_collision.json"
    contract = json.loads(baseline_source.read_text(encoding="utf-8"))
    project_id = contract["project_id"]
    artifact_project = ensure_artifact_project(WORKSPACE_ROOT / "artifacts" / "projects", project_id)
    run_dir = artifact_project / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    input_dir, result_dir, log_dir = (run_dir / name for name in ("inputs", "results", "logs"))
    for directory in (input_dir, result_dir, log_dir):
        directory.mkdir(parents=True)
    frozen_baseline = input_dir / "baseline.json"
    frozen_mode = input_dir / "transport_no_collision.json"
    family_operating = input_dir / "family_operating_contract.json"
    shutil.copy2(baseline_source, frozen_baseline)
    shutil.copy2(mode_source, frozen_mode)
    _write_json(family_operating, operating_contract_document(from_high_order_baseline(contract)))
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    run_config = {
        "schema_version": 1,
        "role": "ideal_multipole_l1_run_config",
        "run_id": run_id,
        "project": project_id,
        "mode": "transport_no_collision",
        "project_root": str(project_root),
        "inputs": {
            "baseline": str(frozen_baseline),
            "mode": str(frozen_mode),
            "family_operating_contract": str(family_operating),
            "shared_implementation": str(Path(__file__).with_name("ideal_transport.py")),
        },
        "parameters": {
            "model_level": "L1",
            "collision_model": "disabled",
            "space_charge_model": "disabled",
            "magnetic_field_model": "disabled",
            "solver_field_used": False,
        },
        "formal_gate_passed": False,
    }
    _write_json(run_config_path, run_config)
    _write_json(summary_path, {"schema_version": 1, "role": "ideal_multipole_l1_summary", "status": "interrupted"})
    _manifest(run_config_path, "interrupted", [summary_path])
    outputs = [result_dir / name for name in ("ideal_transport_metrics.json", "particle_events.csv", "transport_comparison.png")]
    try:
        metrics, rows = evaluate_contract(json.loads(frozen_baseline.read_text(encoding="utf-8")))
        write_results(metrics, rows, result_dir)
        if metrics["status"] != "PASS":
            raise RuntimeError("ideal multipole functional gate failed")
        summary = {
            "schema_version": 1,
            "role": "ideal_multipole_l1_summary",
            "status": "success",
            "project_id": project_id,
            "rf_transmission": metrics["cases"]["rf_on"]["transmission_fraction"],
            "zero_rf_transmission": metrics["cases"]["zero_rf_control"]["transmission_fraction"],
            "result": "results/ideal_transport_metrics.json",
        }
        _write_json(summary_path, summary)
        _manifest(run_config_path, "success", outputs + [summary_path])
    except Exception as exception:
        _write_json(summary_path, {
            "schema_version": 1, "role": "ideal_multipole_l1_summary",
            "status": "failed", "reason": str(exception),
        })
        _manifest(run_config_path, "failed", [summary_path] + [path for path in outputs if path.is_file()])
        raise
    print(
        f"IDEAL_MULTIPOLE_L1=PASS PROJECT={project_id} "
        f"RF={summary['rf_transmission']:.6g} ZERO={summary['zero_rf_transmission']:.6g} RUN_ID={run_id}"
    )
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    project_id = project_root.name.replace("_", "-")
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + f"__sim__python__{project_id}-l1__n100"
    execute(project_root, run_id)


if __name__ == "__main__":
    main()
