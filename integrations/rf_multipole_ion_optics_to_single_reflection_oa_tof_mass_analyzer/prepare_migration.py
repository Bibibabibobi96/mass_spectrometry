"""Prepare one frozen RF-to-oaTOF migration composition without running solvers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.integration.adapter_contract import (
    load_execution_adapter_registry,
    resolve_integration_engineering_budget,
    resolve_execution_mapping,
    validate_migration_preregistration,
)
from common.integration.resolve_connection import (
    load_connection_profile_registry,
    verify_composition_plan,
    write_resolved_and_plan,
)


def prepare_migration(
    *,
    repo_root: Path,
    profile_registry_path: Path,
    adapter_registry_path: Path,
    preregistration_path: Path,
    profile_id: str,
    resolved_output: Path,
    plan_output: Path,
) -> tuple[Path, Path]:
    root = Path(repo_root).resolve()
    profile_registry = load_connection_profile_registry(profile_registry_path)
    profile_ids = {
        profile["connection_profile_id"] for profile in profile_registry["profiles"]
    }
    adapter_registry = load_execution_adapter_registry(adapter_registry_path)
    if adapter_registry["integration_id"] != profile_registry["integration_id"]:
        raise ContractError("execution adapter integration identity differs")
    mapping = resolve_execution_mapping(
        adapter_registry,
        profile_id,
        repo_root=root,
    )
    preregistration = validate_migration_preregistration(
        preregistration_path,
        repo_root=root,
        expected_profile_ids=profile_ids,
    )
    oracle_path = root / preregistration["legacy_oracle"]["path"]
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    budget_path = root / preregistration["engineering_budget"]["path"]
    resolved_budget = resolve_integration_engineering_budget(
        budget_path,
        repo_root=root,
        integration_id=profile_registry["integration_id"],
        profile_id=profile_id,
        source_identity=oracle["source_identity"],
    )
    resolved_budget_path = plan_output.with_name("resolved_engineering_budget.json")
    resolved_budget_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_budget_path.write_text(
        json.dumps(resolved_budget, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    resolved_path, plan_path = write_resolved_and_plan(
        profile_registry_path,
        profile_id,
        resolved_output,
        plan_output,
        repo_root=root,
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["execution_steps"] = [
        {
            "step_id": "rf_to_oatof_transfer",
            "adapter": "powershell",
            "entrypoint": mapping["adapter_entrypoint"],
            "arguments": [
                f"workflow_entrypoint={mapping['workflow_entrypoint']}",
                f"adapter_registry_sha256={file_sha256(adapter_registry_path)}",
                "resolved_budget_filename=resolved_engineering_budget.json",
                f"resolved_budget_sha256={file_sha256(resolved_budget_path)}",
            ],
        }
    ]
    validate_schema(plan, "composition_plan.schema.json")
    plan_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    verify_composition_plan(plan_path, resolved_path, repo_root=root)
    return resolved_path, plan_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--profile-registry", required=True, type=Path)
    parser.add_argument("--adapter-registry", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--resolved-output", required=True, type=Path)
    parser.add_argument("--plan-output", required=True, type=Path)
    args = parser.parse_args()
    resolved, plan = prepare_migration(
        repo_root=args.repo_root,
        profile_registry_path=args.profile_registry,
        adapter_registry_path=args.adapter_registry,
        preregistration_path=args.preregistration,
        profile_id=args.profile_id,
        resolved_output=args.resolved_output,
        plan_output=args.plan_output,
    )
    print(
        "INTEGRATION_MIGRATION_PREPARE=PASS "
        f"PROFILE={args.profile_id} RESOLVED={resolved} PLAN={plan}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
