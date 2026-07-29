"""Publish one lightweight RF-to-oaTOF integration run identity."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.evaluate_migration_equivalence import (
    INTEGRATION_ID,
    NEW_PROJECT_ID,
    STAGE_MODES,
    load_json,
    portable_path,
    verify_manifest,
)


RF_PROJECT_ID = NEW_PROJECT_ID
STAGE_SUBJECTS = {
    "pre_pulse_interface_transport": (
        "sim",
        "comsol",
        "rf-oatof-pre-pulse-interface",
    ),
    "pulse_capture": (
        "sim",
        "comsol",
        "rf-oatof-pulse-capture",
    ),
    "analyzer_transport": (
        "sim",
        "cross",
        "rf-oatof-analyzer-transport",
    ),
}


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def gap_label(connector_length_mm: object) -> str:
    value = float(connector_length_mm)
    if value == 0.0:
        return "0"
    if value == 1.0:
        return "1"
    raise ContractError(
        "migration publisher accepts only preregistered 0 mm or 1 mm profiles"
    )


def stage_run_id(stamp: str, phase: str, gap: str) -> str:
    activity, scope, subject = STAGE_SUBJECTS[phase]
    return (
        f"{stamp}__{activity}__{scope}__{subject}-gap{gap}__n100"
    )


def verify_stage(
    *,
    stage_root: Path,
    run_id: str,
    phase: str,
    workspace_root: Path,
) -> dict[str, str]:
    manifest_path = stage_root / run_id / "run_manifest.json"
    if not manifest_path.is_file():
        raise ContractError(f"stage manifest is missing: {manifest_path}")
    manifest = verify_manifest(
        manifest_path,
        run_id=run_id,
        project_id=RF_PROJECT_ID,
        mode=STAGE_MODES[phase],
    )
    run_path = manifest_path.parent
    try:
        verify_record("run_config", manifest["run_config"])
    except (AssertionError, KeyError) as exc:
        raise ContractError(
            f"stage manifest does not bind run_config: {phase}"
        ) from exc
    if Path(manifest["run_config"]["path"]).resolve().parent != run_path:
        raise ContractError(f"stage run_config is nonlocal: {phase}")
    return {
        "phase": phase,
        "run_id": run_id,
        "path": portable_path(run_path, workspace_root),
        "manifest_sha256": file_sha256(manifest_path),
    }


def canonical_source_identity(pre_pulse_run: Path) -> dict[str, str]:
    config = load_json(pre_pulse_run / "run_config.json")
    identity = config.get("source_particle_identity")
    if not isinstance(identity, dict):
        raise ContractError("pre-pulse run lacks source_particle_identity")
    canonical = {
        "run_id": identity.get("run_id"),
        "project_id": identity.get("recorded_project_id"),
        "manifest_sha256": identity.get("manifest_sha256"),
        "event_sha256": identity.get("event_sha256"),
        "metadata_sha256": identity.get("metadata_sha256"),
    }
    if any(not isinstance(value, str) or not value for value in canonical.values()):
        raise ContractError("pre-pulse source_particle_identity is incomplete")
    return canonical


def publish_integration_run(
    *,
    repo_root: Path,
    workspace_root: Path,
    integration_run_dir: Path,
    project_runs_root: Path,
    receipt_path: Path,
    resolved_path: Path,
    plan_path: Path,
    budget_path: Path,
) -> Path:
    """Freeze the receipt and three child runs as one compact parent run."""

    workspace_root = workspace_root.resolve()
    integration_run_dir = integration_run_dir.resolve()
    expected_parent = (
        workspace_root / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    ).resolve()
    if integration_run_dir.parent != expected_parent:
        raise ContractError(
            "integration run must be a direct child of its canonical runs root"
        )
    receipt = load_json(receipt_path)
    resolved = load_json(resolved_path)
    run_id = integration_run_dir.name
    match = re.fullmatch(r"(?P<stamp>\d{8}_\d{6})__[a-z0-9][a-z0-9._-]*", run_id)
    if not match:
        raise ContractError("integration run id does not begin with yyyyMMdd_HHmmss__")
    profile_id = resolved.get("selection", {}).get("connection_profile_id")
    expected_receipt = {
        "role": "integration_migration_execution_receipt",
        "integration_run_id": run_id,
        "connection_profile_id": profile_id,
        "execution_status": "completed_not_equivalence_evaluated",
        "equivalence_status": "BLOCKED",
    }
    if any(receipt.get(name) != value for name, value in expected_receipt.items()):
        raise ContractError("execution receipt identity/state differs")
    if receipt.get("composition_plan_sha256") != file_sha256(plan_path):
        raise ContractError("receipt does not bind the current composition plan")
    if receipt.get("resolved_connection_sha256") != file_sha256(resolved_path):
        raise ContractError("receipt does not bind the current resolved connection")
    if receipt.get("resolved_engineering_budget_sha256") != file_sha256(
        budget_path
    ):
        raise ContractError("receipt does not bind the resolved engineering budget")
    budget = load_json(budget_path)
    if (
        budget.get("role") != "integration_resolved_engineering_budget"
        or budget.get("integration_id") != INTEGRATION_ID
        or budget.get("connection_profile_id") != profile_id
        or budget.get("particle_count") != 100
        or budget.get("retention_class") != "compact"
    ):
        raise ContractError("resolved engineering-budget identity/scope differs")

    gap = gap_label(resolved.get("connector", {}).get("length_mm"))
    stamp = match.group("stamp")
    stages = [
        verify_stage(
            stage_root=project_runs_root,
            run_id=stage_run_id(stamp, phase, gap),
            phase=phase,
            workspace_root=workspace_root,
        )
        for phase in STAGE_SUBJECTS
    ]
    source_identity = canonical_source_identity(
        workspace_root / stages[0]["path"]
    )
    if budget.get("source_identity") != source_identity:
        raise ContractError(
            "resolved engineering budget and pre-pulse source identities differ"
        )
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": "migration_equivalence_execution",
        "project_root": str(workspace_root),
        "inputs": {
            "execution_receipt": portable_path(receipt_path, workspace_root),
            "resolved_connection": portable_path(resolved_path, workspace_root),
            "composition_plan": portable_path(plan_path, workspace_root),
            "resolved_engineering_budget": portable_path(
                budget_path, workspace_root
            ),
            "pre_pulse_manifest": (
                stages[0]["path"] + "/run_manifest.json"
            ),
            "pulse_capture_manifest": (
                stages[1]["path"] + "/run_manifest.json"
            ),
            "analyzer_transport_manifest": (
                stages[2]["path"] + "/run_manifest.json"
            ),
        },
        "connection_profile_id": profile_id,
        "source_particle_identity": source_identity,
        "stage_runs": stages,
        "artifact_retention": {
            "policy_version": 1,
            "class": "compact",
            "reason": None,
        },
        "formal_gate_passed": False,
    }
    summary = {
        "schema_version": 1,
        "role": "integration_migration_execution_summary",
        "status": "success",
        "connection_profile_id": profile_id,
        "equivalence_status": "BLOCKED",
        "stage_runs_verified": 3,
        "formal_gate_passed": False,
    }
    run_config_path = integration_run_dir / "run_config.json"
    summary_path = integration_run_dir / "summary.json"
    write_json(run_config_path, run_config)
    write_json(summary_path, summary)
    manifest_path = integration_run_dir / "run_manifest.json"
    command = [
        sys.executable,
        "-m",
        "common.contracts.write_run_manifest",
        "--run-config",
        str(run_config_path),
        "--manifest",
        str(manifest_path),
        "--status",
        "success",
        "--software",
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
        "--output",
        str(summary_path),
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ContractError(
            "integration manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--integration-run-dir", required=True, type=Path)
    parser.add_argument("--project-runs-root", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--resolved-connection", type=Path)
    parser.add_argument("--composition-plan", type=Path)
    parser.add_argument("--resolved-engineering-budget", type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    workspace_root = (
        args.workspace_root.resolve()
        if args.workspace_root
        else repo_root.parent.resolve()
    )
    run_dir = args.integration_run_dir.resolve()
    manifest = publish_integration_run(
        repo_root=repo_root,
        workspace_root=workspace_root,
        integration_run_dir=run_dir,
        project_runs_root=(
            args.project_runs_root.resolve()
            if args.project_runs_root
            else workspace_root
            / "artifacts"
            / "projects"
            / RF_PROJECT_ID
            / "runs"
        ),
        receipt_path=(
            args.receipt.resolve()
            if args.receipt
            else run_dir / "execution_receipt.json"
        ),
        resolved_path=(
            args.resolved_connection.resolve()
            if args.resolved_connection
            else run_dir / "resolved_connection.json"
        ),
        plan_path=(
            args.composition_plan.resolve()
            if args.composition_plan
            else run_dir / "composition_plan.json"
        ),
        budget_path=(
            args.resolved_engineering_budget.resolve()
            if args.resolved_engineering_budget
            else run_dir / "resolved_engineering_budget.json"
        ),
    )
    print(f"INTEGRATION_RUN_PUBLICATION=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
