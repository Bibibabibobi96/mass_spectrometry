"""Create an L2 transport run from one successful circular-rod field screen."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common.contracts.artifact_naming import validate_run_id
from common.multipole.analyze_round_rod_screen import analyze
from common.multipole.ensure_artifact_project import ensure_artifact_project
from common.multipole.family_contract import from_high_order_baseline, operating_contract_document
from common.multipole.ideal_transport import evaluate_round_rod_contract, write_results


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parent
CONTRACT_TOOLS = REPO_ROOT / "common" / "contracts"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_manifest(run_config: Path, status: str, outputs: list[Path]) -> None:
    command = [
        sys.executable, str(CONTRACT_TOOLS / "write_run_manifest.py"),
        "--run-config", str(run_config), "--status", status,
        "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    subprocess.run(command, check=True, cwd=REPO_ROOT, timeout=60)


def _load_source(project_id: str, source_run_id: str) -> tuple[Path, dict, list[dict[str, str]]]:
    validate_run_id(source_run_id)
    source_dir = WORKSPACE_ROOT / "artifacts" / "projects" / project_id / "runs" / source_run_id
    manifest_path = source_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "success" or manifest.get("project") != project_id:
        raise ValueError("field-screen source manifest is not a successful run for this project")
    screen_contract = json.loads(
        (source_dir / "inputs" / "round_rod_field_screen.json").read_text(encoding="utf-8-sig")
    )
    with (source_dir / "results" / "round_rod_potential_samples.csv").open(
        newline="", encoding="utf-8-sig"
    ) as stream:
        rows = list(csv.DictReader(stream))
    return source_dir, screen_contract, rows


def execute(project_root: Path, source_run_id: str, run_id: str) -> Path:
    validate_run_id(run_id)
    baseline_source = project_root / "config" / "baseline.json"
    contract = json.loads(baseline_source.read_text(encoding="utf-8"))
    project_id = contract["project_id"]
    source_dir, screen_contract, screen_rows = _load_source(project_id, source_run_id)
    screen_metrics = analyze(screen_rows, screen_contract)
    artifact_project = ensure_artifact_project(WORKSPACE_ROOT / "artifacts" / "projects", project_id)
    run_dir = artifact_project / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    input_dir, result_dir, log_dir = (run_dir / name for name in ("inputs", "results", "logs"))
    for directory in (input_dir, result_dir, log_dir):
        directory.mkdir(parents=True)
    frozen_baseline = input_dir / "baseline.json"
    frozen_mode = input_dir / "round_rod_no_collision.json"
    family_operating = input_dir / "family_operating_contract.json"
    shutil.copy2(baseline_source, frozen_baseline)
    shutil.copy2(project_root / "config" / "modes" / "round_rod_no_collision.json", frozen_mode)
    _write_json(family_operating, operating_contract_document(from_high_order_baseline(contract)))
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    run_config = {
        "schema_version": 1,
        "role": "multipole_round_rod_l2_transport_run_config",
        "run_id": run_id,
        "project": project_id,
        "mode": "round_rod_no_collision",
        "project_root": str(project_root),
        "inputs": {
            "baseline": str(frozen_baseline),
            "mode": str(frozen_mode),
            "family_operating_contract": str(family_operating),
            "field_screen_manifest": str(source_dir / "run_manifest.json"),
            "field_screen_contract": str(source_dir / "inputs" / "round_rod_field_screen.json"),
            "field_screen_samples": str(source_dir / "results" / "round_rod_potential_samples.csv"),
            "shared_implementation": str(Path(__file__).with_name("ideal_transport.py")),
            "field_screen_analysis": str(Path(__file__).with_name("analyze_round_rod_screen.py")),
        },
        "parameters": {"model_level": "L2", "field_dimension": 2, "fringe_field": False},
        "formal_gate_passed": False,
    }
    _write_json(run_config_path, run_config)
    _write_json(summary_path, {"schema_version": 1, "role": "multipole_round_rod_l2_transport_summary", "status": "interrupted"})
    _write_manifest(run_config_path, "interrupted", [summary_path])
    metrics_path = result_dir / "round_rod_transport_metrics.json"
    outputs = [metrics_path, result_dir / "particle_events.csv", result_dir / "transport_comparison.png"]
    try:
        metrics, rows = evaluate_round_rod_contract(contract, screen_metrics)
        write_results(metrics, rows, result_dir, metrics_path.name)
        if metrics["status"] != "PASS":
            raise RuntimeError("round-rod L2 functional transport gate failed")
        summary = {
            "schema_version": 1,
            "role": "multipole_round_rod_l2_transport_summary",
            "status": "success",
            "project_id": project_id,
            "source_field_screen_run_id": source_run_id,
            "selected_rod_radius_ratio": metrics["selected_geometry"]["rod_radius_ratio"],
            "rf_transmission": metrics["cases"]["round_rod_rf_on"]["transmission_fraction"],
            "zero_rf_transmission": metrics["cases"]["zero_rf_control"]["transmission_fraction"],
        }
        _write_json(summary_path, summary)
        _write_manifest(run_config_path, "success", outputs + [summary_path])
    except Exception as exception:
        _write_json(summary_path, {"schema_version": 1, "role": "multipole_round_rod_l2_transport_summary", "status": "failed", "reason": str(exception)})
        _write_manifest(run_config_path, "failed", [summary_path] + [path for path in outputs if path.is_file()])
        raise
    print(
        f"ROUND_ROD_TRANSPORT=PASS PROJECT={project_id} "
        f"RF={summary['rf_transmission']:.6g} ZERO={summary['zero_rf_transmission']:.6g} RUN_ID={run_id}"
    )
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--field-screen-run-id", required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    project_label = project_root.name.replace("_", "-")
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + f"__sim__python__{project_label}-round-rod__l2-n25"
    execute(project_root, args.field_screen_run_id, run_id)


if __name__ == "__main__":
    main()
