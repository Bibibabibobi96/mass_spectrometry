"""Publish one lightweight parent run for a family source-closure chain."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
STAGES = {
    "pre_pulse_interface_transport": {
        "run_stem": "__sim__comsol__rf-oatof-pre-pulse-interface-gap0__n",
        "mode": "rf_to_oatof_pre_pulse_interface_transport",
    },
    "pulse_capture": {
        "run_stem": "__sim__comsol__rf-oatof-pulse-capture-gap0__n",
        "mode": "rf_to_oatof_pulse_capture",
    },
    "analyzer_transport": {
        "run_stem": "__sim__cross__rf-oatof-analyzer-transport-gap0__n",
        "mode": "rf_to_oatof_analyzer_transport",
    },
}
SINGLE_FLIGHT_STAGES = {
    "single_flight_transport": {
        "run_stem": "__sim__simion__rf-oatof-single-flight-gap0__n",
        "mode": "rf_to_oatof_simion_single_flight",
    }
}
STAGES_BY_STRATEGY = {
    "staged_three_stage": STAGES,
    "simion_single_flight": SINGLE_FLIGHT_STAGES,
}
ALL_STAGE_CONTRACTS = {**STAGES, **SINGLE_FLIGHT_STAGES}


def _retry_suffix(run_id: str) -> str:
    match = re.search(r"(__r\d{2})$", run_id)
    return match.group(1) if match else ""


def stage_project_id(execution_strategy: str, upstream_project_id: str) -> str:
    if execution_strategy == "simion_single_flight":
        return INTEGRATION_ID
    if execution_strategy == "staged_three_stage":
        return upstream_project_id
    raise ContractError(f"unsupported family execution strategy: {execution_strategy}")


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
            for phase, contract in ALL_STAGE_CONTRACTS.items()
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
    if stage["phase"] == "single_flight_transport":
        population_path = Path(inputs.get("resolved_population_contract", ""))
        if (
            not population_path.is_file()
            or file_sha256(population_path)
            != receipt["resolved_population_contract_sha256"]
        ):
            raise ContractError("single-flight stage population authority differs")


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
    execution_strategy = receipt.get("execution_strategy")
    if execution_strategy is None:
        raise ContractError("family parent execution strategy is missing")
    if execution_strategy not in STAGES_BY_STRATEGY:
        raise ContractError("family parent execution strategy is invalid")
    stage_contracts = STAGES_BY_STRATEGY[execution_strategy]
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
    campaign_keys = (
        "campaign_id",
        "experiment_id",
        "experiment_row_sha256",
        "launched_particle_count",
        "particle_count",
        "policy_id",
        "retention_class",
    )
    if any(key not in receipt or key not in budget for key in campaign_keys):
        raise ContractError("family parent campaign identity is missing")
    profile_id = receipt["connection_profile_id"]
    source_branch_id = receipt["source_branch_id"]
    if (
        plan["selection"]["connection_profile_id"] != profile_id
        or resolved["selection"]["connection_profile_id"] != profile_id
        or budget["connection_profile_id"] != profile_id
        or budget["source_identity"] != receipt["source_identity"]
        or budget["execution_strategy"] != execution_strategy
        or budget["source_identity"]["source_branch_id"] != source_branch_id
        or any(budget[key] != receipt[key] for key in campaign_keys)
        or receipt.get("campaign_sha256") is None
        or receipt.get("campaign_path") is None
    ):
        raise ContractError("family parent campaign, profile or source identity differs")
    launched_particle_count = receipt["launched_particle_count"]
    particle_count = receipt["particle_count"]
    if (
        not isinstance(launched_particle_count, int)
        or not isinstance(particle_count, int)
        or particle_count < 1
        or launched_particle_count < particle_count
    ):
        raise ContractError("family parent particle census is invalid")
    campaign_path = (repo_root / receipt["campaign_path"]).resolve()
    resolved_source_contract_path = (
        receipt_path.parent / receipt.get("resolved_source_contract_filename", "")
    ).resolve()
    upstream_resolved_design_path = (
        receipt_path.parent / receipt.get("upstream_resolved_design_filename", "")
    ).resolve()
    resolved_population_contract_path = (
        receipt_path.parent / receipt.get("resolved_population_contract_filename", "")
    ).resolve()
    if (
        not campaign_path.is_relative_to(repo_root.resolve())
        or not campaign_path.is_file()
        or repository_text_sha256(campaign_path) != receipt["campaign_sha256"]
        or resolved_source_contract_path.parent != receipt_path.parent.resolve()
        or not resolved_source_contract_path.is_file()
        or file_sha256(resolved_source_contract_path)
        != receipt.get("resolved_source_contract_sha256")
        or upstream_resolved_design_path.parent != receipt_path.parent.resolve()
        or not upstream_resolved_design_path.is_file()
        or file_sha256(upstream_resolved_design_path)
        != receipt.get("upstream_resolved_design_sha256")
    ):
        raise ContractError("family parent frozen campaign inputs differ")
    if execution_strategy == "simion_single_flight":
        if (
            resolved_population_contract_path.parent != receipt_path.parent.resolve()
            or not resolved_population_contract_path.is_file()
            or file_sha256(resolved_population_contract_path)
            != receipt.get("resolved_population_contract_sha256")
        ):
            raise ContractError("family parent resolved population authority differs")
        population = _load(resolved_population_contract_path)
        if (
            population.get("role") != "rf_oatof_resolved_population_contract"
            or population.get("campaign_id") != receipt["campaign_id"]
            or population.get("experiment_id") != receipt["experiment_id"]
            or population.get("experiment_row_sha256")
            != receipt["experiment_row_sha256"]
            or population.get("execution_population", {}).get("particle_count")
            != launched_particle_count
        ):
            raise ContractError("family parent population contract identity differs")
    upstream_project_id = resolved["selection"]["upstream_project_id"]
    stage_run_ids = receipt.get("stage_run_ids")
    stage_runtime_binding_sha256s = receipt.get(
        "stage_runtime_binding_sha256s"
    )
    if (
        not isinstance(stage_run_ids, dict)
        or set(stage_run_ids) != set(stage_contracts)
        or not isinstance(stage_runtime_binding_sha256s, dict)
        or set(stage_runtime_binding_sha256s) != set(stage_contracts)
    ):
        raise ContractError("family receipt stage identities are incomplete")
    for phase in stage_contracts:
        validate_run_id(stage_run_ids[phase])
        expected_run_id = (
            run_id[:15]
            + stage_contracts[phase]["run_stem"]
            + str(particle_count)
            + _retry_suffix(run_id)
        )
        binding_hash = stage_runtime_binding_sha256s[phase]
        if (
            stage_run_ids[phase] != expected_run_id
            or not isinstance(binding_hash, str)
            or len(binding_hash) != 64
            or any(character not in "0123456789ABCDEF" for character in binding_hash)
        ):
            raise ContractError(
                f"family receipt stage runtime-binding SHA is invalid: {phase}"
            )
    stage_owner = stage_project_id(execution_strategy, upstream_project_id)
    stage_root = (
        workspace_root
        / "artifacts"
        / "projects"
        / stage_owner
        / "runs"
    )
    stages = []
    for phase, contract in stage_contracts.items():
        stage_run_id = stage_run_ids[phase]
        stages.append(
            _verify_stage(
                run_path=stage_root / stage_run_id,
                run_id=stage_run_id,
                project_id=stage_owner,
                mode=contract["mode"],
                workspace_root=workspace_root,
            )
        )

    first_stage_config = _load(
        workspace_root / stages[0]["path"] / "run_config.json"
    )
    pre_pulse_source = first_stage_config.get(
        "source_particle_identity" if execution_strategy == "staged_three_stage" else "upstream_source_identity"
    )
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
            "family first stage and parent source identities differ"
        )
    _verify_stage_chain_identity(
        stage=stages[0],
        workspace_root=workspace_root,
        receipt=receipt,
        expected_source_field=(
            "source_particle_identity"
            if execution_strategy == "staged_three_stage"
            else "upstream_source_identity"
        ),
        expected_runtime_binding_sha256=stage_runtime_binding_sha256s[
            stages[0]["phase"]
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
        workspace_root / stages[-1]["path"] / "summary.json"
    )
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": "multipole_family_source_closure",
        "project_root": str(workspace_root),
        "inputs": {
            "campaign": _portable(campaign_path, workspace_root),
            "execution_receipt": _portable(receipt_path, workspace_root),
            "resolved_connection": _portable(resolved_path, workspace_root),
            "composition_plan": _portable(plan_path, workspace_root),
            "resolved_source_contract": _portable(
                resolved_source_contract_path, workspace_root
            ),
            "upstream_resolved_design": _portable(
                upstream_resolved_design_path, workspace_root
            ),
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
        "campaign_path": receipt["campaign_path"],
        "campaign_sha256": receipt["campaign_sha256"],
        "campaign_id": receipt["campaign_id"],
        "experiment_id": receipt["experiment_id"],
        "experiment_row_sha256": receipt["experiment_row_sha256"],
        "source_branch_id": source_branch_id,
        "execution_strategy": execution_strategy,
        "launched_particle_count": launched_particle_count,
        "particle_count": particle_count,
        "policy_id": receipt["policy_id"],
        "source_particle_identity": receipt["source_identity"],
        "stage_runtime_binding_sha256s": stage_runtime_binding_sha256s,
        "stage_runs": stages,
        "artifact_retention": {
            "policy_version": 1,
            "class": receipt["retention_class"],
            "reason": None,
        },
        "formal_gate_passed": False,
    }
    summary = {
        "schema_version": 1,
        "role": "integration_family_source_closure_summary",
        "status": "success",
        "connection_profile_id": profile_id,
        "campaign_id": receipt["campaign_id"],
        "experiment_id": receipt["experiment_id"],
        "experiment_row_sha256": receipt["experiment_row_sha256"],
        "source_branch_id": source_branch_id,
        "launched_particle_count": launched_particle_count,
        "particle_count": particle_count,
        "policy_id": receipt["policy_id"],
        "execution_strategy": execution_strategy,
        "stage_runs_verified": len(stages),
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
    from .assess_full_domain_width_numerics import (
        is_full_domain_width_numerics_campaign,
        publish_completed_assessment,
    )

    campaign = _load(campaign_path)
    if is_full_domain_width_numerics_campaign(campaign):
        final_experiment = max(
            campaign["experiments"], key=lambda row: row["sequence"]
        )["experiment_id"]
        if receipt["experiment_id"] == final_experiment:
            publish_completed_assessment(
                repo_root=repo_root,
                workspace_root=workspace_root,
                campaign_path=campaign_path,
            )
    return manifest_path


def publish_family_source_closure_failure(
    *,
    repo_root: Path,
    workspace_root: Path,
    integration_run_dir: Path,
    resolved_path: Path,
    plan_path: Path,
    budget_path: Path,
    terminal_status: str,
    reason: str,
) -> Path:
    """Terminalize a prepared parent run when its governed child chain fails."""

    if terminal_status not in {"failed", "interrupted"}:
        raise ContractError("failure publication requires failed or interrupted")
    run_dir = integration_run_dir.resolve()
    run_id = run_dir.name
    validate_run_id(run_id)
    resolved = _load(resolved_path)
    plan = _load(plan_path)
    budget = _load(budget_path)
    profile_id = plan.get("selection", {}).get("connection_profile_id")
    if (
        resolved.get("integration_id") != INTEGRATION_ID
        or plan.get("integration_id") != INTEGRATION_ID
        or resolved.get("selection", {}).get("connection_profile_id") != profile_id
        or budget.get("connection_profile_id") != profile_id
    ):
        raise ContractError("failed parent prepared identities differ")
    frozen_names = (
        "composition_plan.json",
        "resolved_connection.json",
        "resolved_engineering_budget.json",
        "resolved_source_contract.json",
        "upstream_resolved_design.json",
        "resolved_oatof_geometry.json",
        "resolved_single_flight_pulse_schedule.json",
        "resolved_population_contract.json",
    )
    frozen_inputs = {
        name.removesuffix(".json"): _portable(run_dir / name, workspace_root)
        for name in frozen_names
        if (run_dir / name).is_file()
    }
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": "multipole_family_source_closure",
        "project_root": str(workspace_root.resolve()),
        "inputs": frozen_inputs,
        "connection_profile_id": profile_id,
        "campaign_id": budget.get("campaign_id"),
        "experiment_id": budget.get("experiment_id"),
        "experiment_row_sha256": budget.get("experiment_row_sha256"),
        "execution_strategy": budget.get("execution_strategy"),
        "launched_particle_count": budget.get("launched_particle_count"),
        "particle_count": budget.get("particle_count"),
        "artifact_retention": {
            "policy_version": 1,
            "class": budget.get("retention_class", "compact"),
            "reason": None,
        },
        "formal_gate_passed": False,
    }
    summary = {
        "schema_version": 1,
        "role": "integration_family_source_closure_summary",
        "status": terminal_status,
        "reason": reason,
        "failure_stage": "governed_child_execution_or_publication",
        "threshold_result_eligible": False,
        "connection_profile_id": profile_id,
        "campaign_id": budget.get("campaign_id"),
        "experiment_id": budget.get("experiment_id"),
        "execution_strategy": budget.get("execution_strategy"),
        "formal_gate_passed": False,
    }
    run_config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    run_config_path.write_text(
        json.dumps(run_config, indent=2) + "\n", encoding="utf-8"
    )
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
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
            terminal_status,
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
            "failed family parent manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--integration-run-dir", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--resolved-connection", required=True, type=Path)
    parser.add_argument("--composition-plan", required=True, type=Path)
    parser.add_argument(
        "--resolved-engineering-budget",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--terminal-status", choices=("failed", "interrupted")
    )
    parser.add_argument("--failure-reason")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.failure_reason is not None:
        if args.terminal_status is None or args.receipt is not None:
            parser.error("failure publication requires status and forbids receipt")
        manifest = publish_family_source_closure_failure(
            repo_root=repo_root,
            workspace_root=repo_root.parent,
            integration_run_dir=args.integration_run_dir.resolve(),
            resolved_path=args.resolved_connection.resolve(),
            plan_path=args.composition_plan.resolve(),
            budget_path=args.resolved_engineering_budget.resolve(),
            terminal_status=args.terminal_status,
            reason=args.failure_reason,
        )
    else:
        if args.receipt is None or args.terminal_status is not None:
            parser.error("success publication requires receipt only")
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
