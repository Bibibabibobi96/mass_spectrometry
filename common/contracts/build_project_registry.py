"""Validate project capability descriptors and build their deterministic registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from machine_contracts import ContractError, REPO_ROOT, load_json, sha256, validate_schema


MATURITY = {"prototype": 0, "static": 1, "candidate": 2, "formal": 3}
DEFAULT_OUTPUT = REPO_ROOT / "config" / "project_registry.json"


def descriptor_paths(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "projects").glob("*/config/project.json"))


def validate_descriptor(descriptor: dict[str, Any], path: Path, repo_root: Path) -> None:
    validate_schema(descriptor, "project.schema.json")
    project_root = path.parents[1]
    if descriptor["project_id"] != project_root.name:
        raise ContractError(
            f"{path}: project_id {descriptor['project_id']!r} differs from directory {project_root.name!r}"
        )
    if project_root.parent != repo_root / "projects":
        raise ContractError(f"{path}: descriptor is outside projects/<project>/config")

    capability_ids: set[str] = set()
    for capability in descriptor["capabilities"]:
        capability_id = capability["capability_id"]
        if capability_id in capability_ids:
            raise ContractError(f"{path}: duplicate capability_id {capability_id!r}")
        capability_ids.add(capability_id)
        if MATURITY[capability["status"]] > MATURITY[descriptor["lifecycle_status"]]:
            raise ContractError(f"{path}: capability {capability_id!r} exceeds project maturity")
        for mode in capability["modes"]:
            mode_path = project_root / "config" / "modes" / f"{mode}.json"
            if not mode_path.is_file():
                raise ContractError(f"{path}: capability {capability_id!r} references missing mode {mode_path}")

    for role, relative in descriptor["contracts"].items():
        if relative is not None and not (project_root / relative).is_file():
            raise ContractError(f"{path}: {role} contract is missing: {relative}")

    assets = descriptor["formal_assets"]
    identity = assets["identity_contract"]
    if identity is not None and not (project_root / identity).is_file():
        raise ContractError(f"{path}: formal identity contract is missing: {identity}")
    if assets["status"] == "formal":
        if descriptor["lifecycle_status"] != "formal" or identity is None or not assets["types"]:
            raise ContractError(f"{path}: formal assets require formal maturity, types, and identity contract")
    elif any(capability["status"] == "formal" for capability in descriptor["capabilities"]):
        raise ContractError(f"{path}: formal capability declared without formal assets")


def build_registry(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    paths = descriptor_paths(repo_root)
    project_dirs = sorted(path for path in (repo_root / "projects").iterdir() if path.is_dir())
    described_roots = {path.parents[1] for path in paths}
    missing = [path.name for path in project_dirs if path not in described_roots]
    if missing:
        raise ContractError(f"projects missing config/project.json: {', '.join(missing)}")

    descriptors: list[dict[str, Any]] = []
    source_records = []
    project_ids: set[str] = set()
    for path in paths:
        descriptor = load_json(path)
        validate_descriptor(descriptor, path, repo_root)
        project_id = descriptor["project_id"]
        if project_id in project_ids:
            raise ContractError(f"duplicate project_id: {project_id}")
        project_ids.add(project_id)
        descriptors.append(descriptor)
        source_records.append(
            {
                "descriptor": path.relative_to(repo_root).as_posix(),
                "sha256": sha256(path),
            }
        )
    registry = {
        "schema_version": 1,
        "role": "generated_project_capability_registry_do_not_edit",
        "generated_from": source_records,
        "projects": descriptors,
    }
    validate_schema(registry, "project_registry.schema.json")
    return registry


def serialized(registry: dict[str, Any]) -> str:
    return json.dumps(registry, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    registry = build_registry()
    expected = serialized(registry)
    output = args.output.resolve()
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8-sig") != expected:
            raise SystemExit(f"PROJECT_REGISTRY=FAIL stale_or_missing={output}")
        print(f"PROJECT_REGISTRY=PASS PROJECTS={len(registry['projects'])} PATH={output}")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8")
    print(f"PROJECT_REGISTRY=BUILT PROJECTS={len(registry['projects'])} PATH={output}")


if __name__ == "__main__":
    main()
