"""Single-stage CLI for the solver-free oaTOF three-zone theory funnel."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common.contracts.artifact_naming import validate_run_id
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_theory_experiment import (
    REPOSITORY_ROOT,
    execute_stage,
    load_campaign,
    resolve_stage_plan,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _publish_run_artifacts(
    campaign_path: Path,
    output_dir: Path,
    report: dict[str, object],
    receipt: dict[str, object],
) -> None:
    run_config_path = output_dir / "run_config.json"
    summary_path = output_dir / "summary.json"
    run_config = {
        "schema_version": 1,
        "run_id": output_dir.name,
        "project": "single_reflection_oa_tof_mass_analyzer",
        "mode": "three_zone_ideal_theory",
        "project_root": str(PROJECT_ROOT),
        "inputs": {"campaign": str(campaign_path)},
        "formal_gate_passed": False,
    }
    summary = {
        "schema_version": 1,
        "role": "oatof_three_zone_theory_stage_summary",
        "status": receipt["status"],
        "run_id": output_dir.name,
        "stage_id": receipt["stage_id"],
        "conclusion": report["scientific_assessment"],
        "formal_gate_passed": False,
    }
    run_config_path.write_text(
        json.dumps(run_config, indent=2) + "\n", encoding="utf-8"
    )
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "common.contracts.write_run_manifest",
        "--run-config",
        str(run_config_path),
        "--manifest",
        str(output_dir / "run_manifest.json"),
        "--status",
        str(receipt["status"]),
        "--software",
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for name in (
        "resolved_plan.json",
        "stage_report.json",
        "stage_receipt.json",
        "summary.json",
    ):
        command.extend(("--output", str(output_dir / name)))
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "three-zone run manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--predecessor-receipt", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manual-conclusion")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--validate", action="store_true")
    actions.add_argument("--plan", action="store_true")
    actions.add_argument("--execute", action="store_true")
    arguments = parser.parse_args()

    campaign_path = arguments.campaign.resolve()
    if arguments.validate:
        campaign = load_campaign(campaign_path)
        if arguments.predecessor_receipt or arguments.output_dir or arguments.manual_conclusion:
            parser.error("--validate accepts no predecessor, output, or conclusion")
        print(f"THREE_ZONE_CAMPAIGN=PASS ID={campaign['campaign_id']}")
        return 0

    plan = resolve_stage_plan(
        campaign_path,
        arguments.stage,
        predecessor_receipt_path=(
            None
            if arguments.predecessor_receipt is None
            else arguments.predecessor_receipt.resolve()
        ),
    )
    if arguments.plan:
        if arguments.output_dir or arguments.manual_conclusion:
            parser.error("--plan accepts no output or manual conclusion")
        print(json.dumps(plan, indent=2))
        return 0

    if arguments.output_dir is None:
        parser.error("--execute requires --output-dir")
    output_dir = arguments.output_dir.resolve()
    try:
        validate_run_id(output_dir.name)
    except ValueError as exc:
        parser.error(f"invalid output run id: {exc}")
    report, receipt = execute_stage(
        campaign_path,
        plan,
        output_dir,
        manual_conclusion=arguments.manual_conclusion,
    )
    _publish_run_artifacts(campaign_path, output_dir, report, receipt)
    print(
        f"THREE_ZONE_STAGE={receipt['stage_id']} STATUS={receipt['status']} "
        f"CONCLUSION={report['scientific_assessment']}"
    )
    return 0 if receipt["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
