"""Create a standard artifact run for one ideal multipole L1 project."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from common.multipole.ideal_transport import evaluate_contract, write_results
from common.multipole._transport_run_artifacts import transport_run


def execute(project_root: Path, run_id: str) -> Path:
    with transport_run(
        project_root, run_id, mode="transport_no_collision",
        run_config_role="ideal_multipole_l1_run_config", summary_role="ideal_multipole_l1_summary",
        parameters={
            "model_level": "L1",
            "collision_model": "disabled",
            "space_charge_model": "disabled",
            "magnetic_field_model": "disabled",
            "solver_field_used": False,
        },
        identity_inputs={"shared_implementation": Path(__file__).with_name("ideal_transport.py")},
        output_names=("ideal_transport_metrics.json", "particle_events.csv", "transport_comparison.png"),
    ) as run:
        metrics, rows = evaluate_contract(run.contract)
        write_results(metrics, rows, run.result_dir)
        if metrics["status"] != "PASS":
            raise RuntimeError("ideal multipole functional gate failed")
        summary = {
            "project_id": run.contract["project_id"],
            "rf_transmission": metrics["cases"]["rf_on"]["transmission_fraction"],
            "zero_rf_transmission": metrics["cases"]["zero_rf_control"]["transmission_fraction"],
            "result": "results/ideal_transport_metrics.json",
        }
        run.complete(summary)
    print(
        f"IDEAL_MULTIPOLE_L1=PASS PROJECT={run.contract['project_id']} "
        f"RF={summary['rf_transmission']:.6g} ZERO={summary['zero_rf_transmission']:.6g} RUN_ID={run_id}"
    )
    return run.run_dir


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
