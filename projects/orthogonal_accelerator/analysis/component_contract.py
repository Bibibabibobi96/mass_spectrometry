"""Versioned consumer/provider boundary for independent accelerator reuse."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import repository_text_sha256


def _source_path(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a repository-relative path")
    relative = Path(value)
    target = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or root not in target.parents:
        raise ValueError(f"{label} escapes its source root")
    if not target.is_file():
        raise ValueError(f"{label} source is missing: {value}")
    return target


def _load_object(path: Path, fields: set[str], label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError(f"{label} schema_version is unsupported")
    if type(value["api_version"]) is not int or value["api_version"] != 1:
        raise ValueError(f"{label} api_version is unsupported")
    return value


def _provider_variants(provider: dict[str, Any]) -> set[str]:
    variants = provider["structural_variants"]
    if not isinstance(variants, list) or not variants:
        raise ValueError("provider structural_variants must be nonempty")
    expected_roles = {
        "two_zone": ["repeller", "grid1", "exit_grid"],
        "three_zone": ["repeller", "grid1", "grid2", "exit_grid"],
    }
    names: set[str] = set()
    for row in variants:
        if not isinstance(row, dict) or set(row) != {
            "variant_id", "field_region_count", "primary_electrode_roles",
        }:
            raise ValueError("provider variant has missing or unknown fields")
        name = row["variant_id"]
        if not isinstance(name, str) or name not in expected_roles or name in names:
            raise ValueError("provider variant identity is invalid or duplicate")
        if (row["primary_electrode_roles"] != expected_roles[name]
                or type(row["field_region_count"]) is not int
                or row["field_region_count"] != len(expected_roles[name])-1):
            raise ValueError("provider field-region and electrode-role topology differs")
        names.add(name)
    return names


def load_accelerator_dependency(
    repository_root: Path, dependency_path: Path, *,
    consumer_project_id: str, required_variant: str,
) -> dict[str, Any]:
    """Validate API identity/topology and return sources for run-local freezing.

    All source paths are resolved inside the supplied repository. This function
    performs no copying, updates, solver work or qualification. Consumers keep
    their existing run publication mechanism and freeze these checked inputs.
    """
    root = repository_root.resolve()
    dependency_path = dependency_path.resolve()
    if root not in dependency_path.parents:
        raise ValueError("consumer dependency is outside the repository")
    dependency = _load_object(dependency_path, {
        "schema_version", "role", "consumer_project_id", "provider_project_id",
        "api_version", "provider_contract", "structural_variants", "ownership",
    }, "consumer dependency")
    if (dependency["role"] != "accelerator_component_dependency"
            or dependency["consumer_project_id"] != consumer_project_id
            or dependency["provider_project_id"] != "orthogonal_accelerator"):
        raise ValueError("accelerator dependency project/role identity differs")
    expected_provider = "projects/orthogonal_accelerator/config/component_contract.json"
    if dependency["provider_contract"] != expected_provider:
        raise ValueError("accelerator provider contract identity differs")
    provider_path = _source_path(root, expected_provider, "provider contract")
    provider = _load_object(provider_path, {
        "schema_version", "role", "project_id", "api_version", "structural_variants",
        "units", "coordinate_policy", "qualification_policy", "implementation_modules",
    }, "accelerator provider")
    if (provider["role"] != "orthogonal_accelerator_component_api"
            or provider["project_id"] != dependency["provider_project_id"]
            or provider["api_version"] != dependency["api_version"]):
        raise ValueError("accelerator provider project/role/API identity differs")
    if provider["units"] != {"length": "mm", "voltage": "V", "mass": "Da", "time": "us"}:
        raise ValueError("accelerator provider units differ")
    variants = dependency["structural_variants"]
    if (not isinstance(variants, list) or not variants
            or any(not isinstance(value, str) for value in variants)
            or len(set(variants)) != len(variants)
            or not set(variants) <= _provider_variants(provider)
            or required_variant not in variants):
        raise ValueError("consumer does not declare the required accelerator variant")
    modules = provider["implementation_modules"]
    if not isinstance(modules, list) or not modules or any(not isinstance(value, str) for value in modules):
        raise ValueError("provider implementation_modules must be nonempty paths")
    if len(set(modules)) != len(modules):
        raise ValueError("provider implementation_modules contain duplicates")
    provider_root = provider_path.parents[1]
    sources = tuple(_source_path(provider_root, value, "provider implementation") for value in modules)
    return {
        "dependency": dependency, "provider": provider,
        "api_version": provider["api_version"],
        "dependency_path": dependency_path, "provider_contract_path": provider_path,
        "dependency_sha256": repository_text_sha256(dependency_path),
        "provider_contract_sha256": repository_text_sha256(provider_path),
        "implementation_sources": sources,
    }
