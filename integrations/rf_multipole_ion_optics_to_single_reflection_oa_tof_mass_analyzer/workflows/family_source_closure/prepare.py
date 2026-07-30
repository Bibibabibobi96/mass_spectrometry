"""Prepare one preregistered multipole-family source-closure execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.integration.adapter_contract import (
    load_execution_adapter_registry,
    resolve_execution_mapping,
)
from common.integration.resolve_connection import (
    load_connection_profile_registry,
    verify_composition_plan,
    write_resolved_and_plan,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _repo_record(root: Path, record: dict[str, str], label: str) -> Path:
    path = (root / record["path"]).resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or file_sha256(path) != record["sha256"]
    ):
        raise ContractError(f"{label} is missing, stale or escapes the repository")
    return path


def _unique_profile(
    document: dict[str, Any],
    profile_id: str,
    *,
    role: str,
) -> dict[str, Any]:
    records = [
        record
        for record in document["profiles"]
        if record["connection_profile_id"] == profile_id
    ]
    if len(records) != 1:
        raise ContractError(f"{role} profile is not unique: {profile_id}")
    return records[0]


def prepare_family_source_closure(
    *,
    repo_root: Path,
    profile_registry_path: Path,
    adapter_registry_path: Path,
    preregistration_path: Path,
    profile_id: str,
    source_branch_id: str,
    resolved_output: Path,
    plan_output: Path,
) -> tuple[Path, Path]:
    root = repo_root.resolve()
    if source_branch_id not in {"comsol", "simion"}:
        raise ContractError("source_branch_id must be comsol or simion")

    profile_registry = load_connection_profile_registry(profile_registry_path)
    registered_ids = {
        profile["connection_profile_id"]
        for profile in profile_registry["profiles"]
    }
    preregistration = _load(preregistration_path)
    validate_schema(
        preregistration,
        "integration_family_source_closure_preregistration.schema.json",
    )
    if preregistration["integration_id"] != profile_registry["integration_id"]:
        raise ContractError("family preregistration integration identity differs")
    preregistered_ids = {
        profile["connection_profile_id"]
        for profile in preregistration["profiles"]
    }
    if len(preregistered_ids) != 3 or not preregistered_ids.issubset(
        registered_ids
    ):
        raise ContractError("family preregistration profile set differs")
    preregistered_profile = _unique_profile(
        preregistration,
        profile_id,
        role="family preregistration",
    )
    if source_branch_id not in preregistered_profile["source_branch_ids"]:
        raise ContractError("source branch is not preregistered for this profile")

    adapter_registry = load_execution_adapter_registry(adapter_registry_path)
    if adapter_registry["integration_id"] != profile_registry["integration_id"]:
        raise ContractError("execution adapter integration identity differs")
    mapping = resolve_execution_mapping(
        adapter_registry,
        profile_id,
        repo_root=root,
    )
    runtime_binding_path = _repo_record(
        root,
        {
            "path": mapping["runtime_binding_path"],
            "sha256": mapping["runtime_binding_sha256"],
        },
        "family runtime binding",
    )
    runtime_binding = _load(runtime_binding_path)
    validate_schema(
        runtime_binding,
        "rf_multipole_oatof_runtime_binding.schema.json",
    )
    if (
        runtime_binding["connection_profile_id"] != profile_id
        or runtime_binding["upstream_project_id"]
        != next(
            profile["upstream"]["project_id"]
            for profile in profile_registry["profiles"]
            if profile["connection_profile_id"] == profile_id
        )
    ):
        raise ContractError("family runtime binding identity differs")

    source_contract_record = runtime_binding["contracts"]["source_contract"]
    source_contract_path = _repo_record(
        root,
        source_contract_record,
        "family source contract",
    )
    if source_contract_record != preregistered_profile["source_contract"]:
        raise ContractError(
            "runtime and preregistration source contracts differ"
        )
    source_contract = _load(source_contract_path)
    validate_schema(
        source_contract,
        "rf_multipole_oatof_source_contract.schema.json",
    )
    if source_contract["schema_version"] != 2:
        raise ContractError("family workflow requires source contract schema v2")
    source_branch = source_contract["source_branches"][source_branch_id]
    source = source_branch["source"]

    budget_path = _repo_record(
        root,
        preregistration["engineering_budget"],
        "family engineering budget",
    )
    budget = _load(budget_path)
    validate_schema(
        budget,
        "integration_family_source_closure_budget.schema.json",
    )
    budget_profiles = {
        item["connection_profile_id"]: item["source_contract"]
        for item in budget["authorization"]["scope"][
            "profile_source_contracts"
        ]
    }
    scope = budget["authorization"]["scope"]
    if (
        budget_profiles.get(profile_id) != source_contract_record
        or source_branch_id not in scope["source_branch_ids"]
        or scope["particle_count"] != source["particle_count"]
    ):
        raise ContractError("family budget profile or source scope differs")

    source_identity = {
        "source_branch_id": source_branch_id,
        "solver_id": source_branch["solver_id"],
        "run_id": source["run_id"],
        "project_id": source_branch["recorded_project_id"],
        "manifest_sha256": source["manifest"]["sha256"],
        "event_sha256": source["state"]["sha256"],
        "particle_source_sha256": source["particle_source"]["sha256"],
        "metadata_sha256": source["metadata"]["sha256"],
    }
    resolved_budget = {
        "schema_version": 1,
        "role": "integration_resolved_engineering_budget",
        "integration_id": profile_registry["integration_id"],
        "connection_profile_id": profile_id,
        "source_identity": source_identity,
        "particle_count": source["particle_count"],
        "retention_class": scope["retention_class"],
        "stage_limits": budget["authorization"]["stage_limits"],
        "budget_path": str(budget_path),
    }
    resolved_budget_path = plan_output.with_name(
        "resolved_engineering_budget.json"
    )
    resolved_budget_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_budget_path.write_text(
        json.dumps(resolved_budget, indent=2) + "\n",
        encoding="utf-8",
    )

    resolved_path, plan_path = write_resolved_and_plan(
        profile_registry_path,
        profile_id,
        resolved_output,
        plan_output,
        repo_root=root,
    )
    plan = _load(plan_path)
    plan["execution_steps"] = [
        {
            "step_id": "rf_to_oatof_transfer",
            "adapter": "powershell",
            "entrypoint": mapping["adapter_entrypoint"],
            "arguments": [
                f"adapter_registry_sha256={file_sha256(adapter_registry_path)}",
                f"preregistration_sha256={file_sha256(preregistration_path)}",
                f"runtime_binding_path={mapping['runtime_binding_path']}",
                f"runtime_binding_sha256={mapping['runtime_binding_sha256']}",
                f"source_branch_id={source_branch_id}",
                "resolved_budget_filename=resolved_engineering_budget.json",
                f"resolved_budget_sha256={file_sha256(resolved_budget_path)}",
            ],
        }
    ]
    validate_schema(plan, "composition_plan.schema.json")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    verify_composition_plan(plan_path, resolved_path, repo_root=root)
    return resolved_path, plan_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--profile-registry", required=True, type=Path)
    parser.add_argument("--adapter-registry", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument(
        "--source-branch-id",
        required=True,
        choices=("comsol", "simion"),
    )
    parser.add_argument("--resolved-output", required=True, type=Path)
    parser.add_argument("--plan-output", required=True, type=Path)
    args = parser.parse_args()
    resolved, plan = prepare_family_source_closure(
        repo_root=args.repo_root,
        profile_registry_path=args.profile_registry,
        adapter_registry_path=args.adapter_registry,
        preregistration_path=args.preregistration,
        profile_id=args.profile_id,
        source_branch_id=args.source_branch_id,
        resolved_output=args.resolved_output,
        plan_output=args.plan_output,
    )
    print(
        "FAMILY_SOURCE_CLOSURE_PREPARE=PASS "
        f"PROFILE={args.profile_id} SOURCE_BRANCH={args.source_branch_id} "
        f"RESOLVED={resolved} PLAN={plan}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
