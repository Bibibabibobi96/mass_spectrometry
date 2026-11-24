"""Create a standard artifact run for one ideal multipole L1 project."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from msplatform.components.rf_multipole import ideal_transport
from msplatform.workflows.rf_transport_artifacts import transport_run


def execute(
    component_root: Path, run_id: str, *, design_profile_id: str,
    workspace_root: Path, artifact_root: Path,
) -> Path:
    """Run ideal L1 transport and publish a run beneath the explicit artifact root."""
    with transport_run(
        component_root, run_id, design_profile_id=design_profile_id, mode="transport_no_collision",
        run_config_role="ideal_multipole_l1_run_config", summary_role="ideal_multipole_l1_summary",
        parameters={
            "model_level": "L1",
            "collision_model": "disabled",
            "space_charge_model": "disabled",
            "magnetic_field_model": "disabled",
            "solver_field_used": False,
        },
        identity_inputs={"shared_implementation": Path(ideal_transport.__file__)},
        output_names=("ideal_transport_metrics.json", "particle_events.csv", "transport_comparison.png"),
        repository_root=workspace_root, artifact_root=artifact_root,
    ) as run:
        metrics, rows = ideal_transport.evaluate_contract(run.contract)
        ideal_transport.write_results(metrics, rows, run.result_dir)
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
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--component-root", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--design-profile-id", required=True)
    args = parser.parse_args()
    from msplatform.execution.host_resource_python import ensure_heavy_entry

    ensure_heavy_entry("msplatform.workflows.rf_ideal_transport")
    component_root = args.component_root.resolve()
    project_id = component_root.name.replace("_", "-")
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + f"__sim__python__{project_id}-l1__n100"
    execute(
        component_root, run_id, design_profile_id=args.design_profile_id,
        workspace_root=args.workspace_root.resolve(), artifact_root=args.artifact_root.resolve(),
    )


if __name__ == "__main__":
    main()
