"""Strict loading for integration-owned execution mappings and budgets."""

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
