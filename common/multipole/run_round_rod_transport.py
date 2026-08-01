"""Create an L2 transport run from one successful circular-rod field screen."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from common.contracts.artifact_naming import validate_run_id
from common.multipole.analyze_round_rod_screen import analyze
from common.multipole._transport_run_artifacts import ARTIFACT_PROJECTS_ROOT, transport_run
from common.multipole.ideal_transport import evaluate_round_rod_contract, write_results


def _load_source(project_id: str, source_run_id: str) -> tuple[Path, dict, list[dict[str, str]]]:
    validate_run_id(source_run_id)
    source_dir = ARTIFACT_PROJECTS_ROOT / project_id / "runs" / source_run_id
    manifest = json.loads((source_dir / "run_manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "success" or manifest.get("project") != project_id:
        raise ValueError("field-screen source manifest is not a successful run for this project")
    screen_contract = json.loads(
        (source_dir / "inputs" / "round_rod_field_screen.json").read_text(encoding="utf-8-sig")
    )
    with (source_dir / "results/round_rod_potential_samples.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return source_dir, screen_contract, rows


def execute(project_root: Path, source_run_id: str, run_id: str) -> Path:
    validate_run_id(run_id)
    project_id = json.loads((project_root / "config/project.json").read_text(encoding="utf-8"))["project_id"]
    source_dir, screen_contract, screen_rows = _load_source(project_id, source_run_id)
    screen_metrics = analyze(screen_rows, screen_contract)
    with transport_run(
        project_root, run_id, mode="round_rod_no_collision",
        run_config_role="multipole_round_rod_l2_transport_run_config",
        summary_role="multipole_round_rod_l2_transport_summary",
        parameters={"model_level": "L2", "field_dimension": 2, "fringe_field": False},
        identity_inputs={
            "field_screen_manifest": source_dir / "run_manifest.json",
            "field_screen_contract": source_dir / "inputs" / "round_rod_field_screen.json",
            "field_screen_samples": source_dir / "results" / "round_rod_potential_samples.csv",
            "shared_implementation": Path(__file__).with_name("ideal_transport.py"),
            "field_screen_analysis": Path(__file__).with_name("analyze_round_rod_screen.py"),
        },
        output_names=("round_rod_transport_metrics.json", "particle_events.csv", "transport_comparison.png"),
    ) as run:
        metrics, rows = evaluate_round_rod_contract(run.contract, screen_metrics)
        write_results(metrics, rows, run.result_dir, run.outputs[0].name)
        if metrics["status"] != "PASS":
            raise RuntimeError("round-rod L2 functional transport gate failed")
        summary = {
            "project_id": project_id,
            "source_field_screen_run_id": source_run_id,
            "selected_rod_radius_ratio": metrics["selected_geometry"]["rod_radius_ratio"],
            "rf_transmission": metrics["cases"]["round_rod_rf_on"]["transmission_fraction"],
            "zero_rf_transmission": metrics["cases"]["zero_rf_control"]["transmission_fraction"],
        }
        run.complete(summary)
    print(
        f"ROUND_ROD_TRANSPORT=PASS PROJECT={project_id} "
        f"RF={summary['rf_transmission']:.6g} ZERO={summary['zero_rf_transmission']:.6g} RUN_ID={run_id}"
    )
    return run.run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--field-screen-run-id", required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    project_label = project_root.name.replace("_", "-")
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + f"__sim__python__{project_label}-round-rod__l2-n100"
    execute(project_root, args.field_screen_run_id, run_id)


if __name__ == "__main__":
    main()
