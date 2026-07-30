"""Strict loading for integration-owned execution mappings and migration preregistration."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _repo_file(repo_root: Path, relative: str) -> Path:
    root = Path(repo_root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ContractError(f"integration adapter path is missing or escapes repo: {relative}")
    return path


def load_execution_adapter_registry(path: Path) -> dict[str, Any]:
    registry = _load(path)
    validate_schema(registry, "execution_adapter_registry.schema.json")
    identifiers = [item["connection_profile_id"] for item in registry["mappings"]]
    if len(identifiers) != len(set(identifiers)):
        raise ContractError("duplicate execution adapter connection_profile_id")
    return registry


def resolve_execution_mapping(
    registry: dict[str, Any],
    profile_id: str,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    validate_schema(registry, "execution_adapter_registry.schema.json")
    matches = [
        item
        for item in registry["mappings"]
        if item["connection_profile_id"] == profile_id
    ]
    if len(matches) != 1:
        raise ContractError(f"execution adapter mapping is not unique: {profile_id}")
    mapping = copy.deepcopy(matches[0])
    adapter = _repo_file(repo_root, mapping["adapter_entrypoint"])
    if file_sha256(adapter) != mapping["adapter_sha256"]:
        raise ContractError("execution adapter SHA-256 is stale")
    runtime_binding = _repo_file(repo_root, mapping["runtime_binding_path"])
    if file_sha256(runtime_binding) != mapping["runtime_binding_sha256"]:
        raise ContractError("execution runtime binding SHA-256 is stale")
    return mapping


def validate_migration_preregistration(
    path: Path,
    *,
    repo_root: Path,
    expected_profile_ids: set[str],
) -> dict[str, Any]:
    document = _load(path)
    validate_schema(document, "migration_equivalence_preregistration.schema.json")
    oracle = _repo_file(repo_root, document["legacy_oracle"]["path"])
    if file_sha256(oracle) != document["legacy_oracle"]["sha256"]:
        raise ContractError("migration oracle SHA-256 is stale")
    actual_ids = {item["connection_profile_id"] for item in document["profiles"]}
    if actual_ids != expected_profile_ids or len(actual_ids) != len(document["profiles"]):
        raise ContractError("migration preregistration profile set differs")
    return document


def resolve_integration_engineering_budget(
    path: Path,
    *,
    repo_root: Path,
    integration_id: str,
    profile_id: str,
    source_identity: dict[str, Any],
) -> dict[str, Any]:
    """Validate and resolve the exact zero-retry budget for one integration profile."""

    root = Path(repo_root).resolve()
    budget_path = Path(path).resolve()
    if not budget_path.is_relative_to(root) or not budget_path.is_file():
        raise ContractError("integration engineering-budget path is missing or escapes repo")
    budget = _load(path)
    validate_schema(budget, "integration_engineering_budget.schema.json")
    if budget["integration_id"] != integration_id:
        raise ContractError("integration engineering-budget identity differs")
    pilot = budget["pilot_authorization"]
    if pilot["authorized"] is not True:
        raise ContractError("integration commercial-solver pilot is not authorized")
    scope = pilot["scope"]
    if profile_id not in scope["connection_profile_ids"]:
        raise ContractError("connection profile is not authorized by integration budget")
    expected_source = {
        "project_id": source_identity["project_id"],
        "run_id": source_identity["run_id"],
        "manifest_sha256": source_identity["manifest"]["sha256"],
        "event_sha256": source_identity["events"]["sha256"],
        "metadata_sha256": source_identity["metadata"]["sha256"],
    }
    if (
        scope["source_identity"] != expected_source
        or scope["particle_count"] != source_identity["particle_count"]
        or scope["retention_class"] != "compact"
    ):
        raise ContractError("integration budget source or retention scope differs")
    return {
        "schema_version": 1,
        "role": "integration_resolved_engineering_budget",
        "integration_id": integration_id,
        "connection_profile_id": profile_id,
        "source_identity": copy.deepcopy(expected_source),
        "particle_count": scope["particle_count"],
        "retention_class": scope["retention_class"],
        "stage_limits": copy.deepcopy(pilot["stage_limits"]),
        "budget_path": str(budget_path),
    }
