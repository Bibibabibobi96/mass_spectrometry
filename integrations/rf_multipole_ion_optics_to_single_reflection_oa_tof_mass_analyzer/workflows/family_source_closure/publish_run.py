"""Publish one lightweight parent run for a family source-closure chain."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
STAGES = {
    "pre_pulse_interface_transport": {
        "run_suffix": "__sim__comsol__rf-oatof-pre-pulse-interface-gap0__n100",
        "mode": "rf_to_oatof_pre_pulse_interface_transport_n100",
    },
    "pulse_capture": {
        "run_suffix": "__sim__comsol__rf-oatof-pulse-capture-gap0__n100",
        "mode": "rf_to_oatof_pulse_capture_n100",
    },
    "analyzer_transport": {
        "run_suffix": "__sim__cross__rf-oatof-analyzer-transport-gap0__n100",
        "mode": "rf_to_oatof_analyzer_transport_n100",
    },
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _portable(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"path is outside the workspace: {path}") from exc


def _verify_stage(
    *,
    run_path: Path,
    run_id: str,
    project_id: str,
    mode: str,
    workspace_root: Path,
) -> dict[str, str]:
    manifest_path = run_path / "run_manifest.json"
    manifest = _load(manifest_path)
    expected = {
        "role": "simulation_run_manifest",
        "run_id": run_id,
        "project": project_id,
        "mode": mode,
        "status": "success",
    }
    if any(manifest.get(name) != value for name, value in expected.items()):
        raise ContractError(f"family stage identity/status differs: {run_id}")
    try:
        verify_record("run_config", manifest["run_config"])
    except (AssertionError, KeyError) as exc:
        raise ContractError(f"family stage run_config is invalid: {run_id}") from exc
    if Path(manifest["run_config"]["path"]).resolve().parent != run_path:
        raise ContractError(f"family stage run_config is nonlocal: {run_id}")
    return {
        "phase": next(
            phase
            for phase, contract in STAGES.items()
            if contract["mode"] == mode
        ),
        "run_id": run_id,
        "path": _portable(run_path, workspace_root),
        "manifest_sha256": file_sha256(manifest_path),
    }


def _verify_stage_chain_identity(
    *,
    stage: dict[str, str],
    workspace_root: Path,
    receipt: dict[str, Any],
    expected_source_field: str,
    expected_runtime_binding_sha256: str,
) -> None:
    run_config = _load(workspace_root / stage["path"] / "run_config.json")
    profile_id = receipt["connection_profile_id"]
    source_branch_id = receipt["source_branch_id"]
    source_identity = receipt["source_identity"]
    stage_source_identity = run_config.get(expected_source_field)
    if (
        not isinstance(stage_source_identity, dict)
        or any(
            stage_source_identity.get(key) != value
            for key, value in source_identity.items()
        )
        or run_config.get("parameters", {}).get("connection_profile_id")
        != profile_id
        or run_config.get("parameters", {}).get("source_branch_id")
        != source_branch_id
    ):
        raise ContractError(
            f"family stage source/profile identity differs: {stage['phase']}"
        )
    inputs = run_config.get("inputs", {})
    runtime_path = Path(inputs.get("runtime_binding", ""))
    resolved_path = Path(inputs.get("resolved_connection", ""))
    if (
        not runtime_path.is_file()
        or file_sha256(runtime_path)
        != expected_runtime_binding_sha256
        or not resolved_path.is_file()
        or file_sha256(resolved_path)
        != receipt["resolved_connection_sha256"]
    ):
        raise ContractError(
            f"family stage runtime/resolved identity differs: {stage['phase']}"
        )


def publish_family_source_closure_run(
    *,
    repo_root: Path,
    workspace_root: Path,
    integration_run_dir: Path,
    receipt_path: Path,
    resolved_path: Path,
    plan_path: Path,
    budget_path: Path,
) -> Path:
    run_dir = integration_run_dir.resolve()
    run_id = run_dir.name
    validate_run_id(run_id)
    if not run_id.startswith(run_id[:15] + "__"):
        raise ContractError("family parent run ID has no canonical timestamp")
    receipt = _load(receipt_path)
    resolved = _load(resolved_path)
    plan = _load(plan_path)
    budget = _load(budget_path)
    if (
        receipt.get("role")
        != "integration_family_source_closure_execution_receipt"
        or receipt.get("integration_run_id") != run_id
        or receipt.get("execution_status")
        != "completed_pending_paired_analysis"
        or plan.get("integration_id") != INTEGRATION_ID
        or resolved.get("integration_id") != INTEGRATION_ID
    ):
        raise ContractError("family parent receipt or integration identity differs")
    profile_id = receipt["connection_profile_id"]
    source_branch_id = receipt["source_branch_id"]
    if (
        plan["selection"]["connection_profile_id"] != profile_id
        or resolved["selection"]["connection_profile_id"] != profile_id
        or budget["connection_profile_id"] != profile_id
        or budget["source_identity"] != receipt["source_identity"]
        or budget["source_identity"]["source_branch_id"] != source_branch_id
    ):
        raise ContractError("family parent profile or source identity differs")
    upstream_project_id = resolved["selection"]["upstream_project_id"]
    stage_run_ids = receipt.get("stage_run_ids")
    stage_runtime_binding_sha256s = receipt.get(
        "stage_runtime_binding_sha256s"
    )
    if (
        not isinstance(stage_run_ids, dict)
        or set(stage_run_ids) != set(STAGES)
        or not isinstance(stage_runtime_binding_sha256s, dict)
        or set(stage_runtime_binding_sha256s) != set(STAGES)
    ):
        raise ContractError("family receipt stage identities are incomplete")
    for phase in STAGES:
        validate_run_id(stage_run_ids[phase])
        binding_hash = stage_runtime_binding_sha256s[phase]
        if (
            not isinstance(binding_hash, str)
            or len(binding_hash) != 64
            or any(character not in "0123456789ABCDEF" for character in binding_hash)
        ):
            raise ContractError(
                f"family receipt stage runtime-binding SHA is invalid: {phase}"
            )
    stage_root = (
        workspace_root
        / "artifacts"
        / "projects"
        / upstream_project_id
        / "runs"
    )
    stages = []
    for phase, contract in STAGES.items():
        stage_run_id = stage_run_ids[phase]
        stages.append(
            _verify_stage(
                run_path=stage_root / stage_run_id,
                run_id=stage_run_id,
                project_id=upstream_project_id,
                mode=contract["mode"],
                workspace_root=workspace_root,
            )
        )

    pre_pulse_config = _load(
        workspace_root / stages[0]["path"] / "run_config.json"
    )
    pre_pulse_source = pre_pulse_config.get("source_particle_identity")
    required_source_keys = (
        "source_branch_id",
        "solver_id",
        "run_id",
        "project_id",
        "manifest_sha256",
        "event_sha256",
        "particle_source_sha256",
        "metadata_sha256",
    )
    if (
        not isinstance(pre_pulse_source, dict)
        or any(
            pre_pulse_source.get(key) != receipt["source_identity"][key]
            for key in required_source_keys
        )
    ):
        raise ContractError(
            "family pre-pulse and parent source identities differ"
        )
    _verify_stage_chain_identity(
        stage=stages[0],
        workspace_root=workspace_root,
        receipt=receipt,
        expected_source_field="source_particle_identity",
        expected_runtime_binding_sha256=stage_runtime_binding_sha256s[
            "pre_pulse_interface_transport"
        ],
    )
    for stage in stages[1:]:
        _verify_stage_chain_identity(
            stage=stage,
            workspace_root=workspace_root,
            receipt=receipt,
            expected_source_field="upstream_source_identity",
            expected_runtime_binding_sha256=stage_runtime_binding_sha256s[
                stage["phase"]
            ],
        )

    analyzer_summary = _load(
        workspace_root / stages[2]["path"] / "summary.json"
    )
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": "multipole_family_source_closure_n100",
        "project_root": str(workspace_root),
        "inputs": {
            "execution_receipt": _portable(receipt_path, workspace_root),
            "resolved_connection": _portable(resolved_path, workspace_root),
            "composition_plan": _portable(plan_path, workspace_root),
            "resolved_engineering_budget": _portable(
                budget_path, workspace_root
            ),
            **{
                f"{stage['phase']}_manifest": (
                    stage["path"] + "/run_manifest.json"
                )
                for stage in stages
            },
        },
        "connection_profile_id": profile_id,
        "source_branch_id": source_branch_id,
        "source_particle_identity": receipt["source_identity"],
        "stage_runtime_binding_sha256s": stage_runtime_binding_sha256s,
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
        "role": "integration_family_source_closure_summary",
        "status": "success",
        "connection_profile_id": profile_id,
        "source_branch_id": source_branch_id,
        "stage_runs_verified": 3,
        "census": analyzer_summary.get("census"),
        "claim_status": "FUNCTIONAL_SCREEN_ONLY",
        "paired_analysis_status": "NOT_RUN",
        "formal_gate_passed": False,
    }
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    run_config_path.write_text(
        json.dumps(run_config, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_path = run_dir / "run_manifest.json"
    completed = subprocess.run(
        [
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
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ContractError(
            "family parent manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--integration-run-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--resolved-connection", required=True, type=Path)
    parser.add_argument("--composition-plan", required=True, type=Path)
    parser.add_argument(
        "--resolved-engineering-budget",
        required=True,
        type=Path,
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    manifest = publish_family_source_closure_run(
        repo_root=repo_root,
        workspace_root=repo_root.parent,
        integration_run_dir=args.integration_run_dir.resolve(),
        receipt_path=args.receipt.resolve(),
        resolved_path=args.resolved_connection.resolve(),
        plan_path=args.composition_plan.resolve(),
        budget_path=args.resolved_engineering_budget.resolve(),
    )
    print(f"FAMILY_SOURCE_CLOSURE_PUBLICATION=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
