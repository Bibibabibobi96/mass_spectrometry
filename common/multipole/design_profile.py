"""Resolve a governed multipole design profile from the canonical project registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.multipole.compile_design_request import (
    apply_typed_operating_mode,
    compile_governed_design_request_file,
)


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if path.parent != root.resolve() and root.resolve() not in path.parents:
        raise ContractError(f"design profile path escapes canonical project: {relative}")
    if not path.is_file():
        raise ContractError(f"design profile file is missing: {path}")
    return path


def resolve_design_profile(
    repo_root: Path,
    project_id: str,
    design_profile_id: str,
) -> dict[str, Any]:
    """Resolve and verify a profile without trusting a caller-supplied project root."""
    repo_root = Path(repo_root).resolve()
    registry_path = repo_root / "config" / "project_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    matches = [item for item in registry["projects"] if item["project_id"] == project_id]
    if len(matches) != 1:
        raise ContractError(f"project registry does not contain one project_id={project_id!r}")
    registered = matches[0]
    project_root = (repo_root / "projects" / project_id).resolve()
    descriptor_path = project_root / "config" / "project.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8-sig"))
    validate_schema(descriptor, "project.schema.json")
    if descriptor["project_id"] != project_id or registered["family_id"] != descriptor["family_id"]:
        raise ContractError("canonical project descriptor differs from project registry")
    profiles_relative = descriptor["contracts"]["design_profiles"]
    if not profiles_relative:
        raise ContractError("project does not register governed design profiles")
    profiles_path = _inside(project_root, profiles_relative)
    profiles = json.loads(profiles_path.read_text(encoding="utf-8-sig"))
    validate_schema(profiles, "design_profiles.schema.json")
    if profiles["project_id"] != project_id or profiles["family_id"] != descriptor["family_id"]:
        raise ContractError("design profile registry identity differs")
    selected = [item for item in profiles["profiles"] if item["design_profile_id"] == design_profile_id]
    if len(selected) != 1:
        raise ContractError(f"design profile is not unique: {design_profile_id!r}")
    profile = selected[0]
    paths = {
        "design_request": _inside(project_root, profile["design_request"]),
        "design_variables": _inside(project_root, profile["design_variables"]),
        "optimization_envelope": _inside(project_root, profile["optimization_envelope"]),
    }
    for label, path in paths.items():
        if repository_text_sha256(path) != profile["sha256"][label]:
            raise ContractError(f"design profile hash is stale: {label}")
    request = json.loads(paths["design_request"].read_text(encoding="utf-8-sig"))
    resolved_design = None
    mode_id = profile.get("mode_id")
    if mode_id is not None:
        try:
            modes_relative = profiles["operating_mode_registry"]
            expected_modes_sha256 = profiles["operating_mode_registry_sha256"]
        except KeyError as error:
            raise ContractError(
                "typed design profile is missing its operating mode registry"
            ) from error
        modes_path = _inside(project_root, modes_relative)
        if repository_text_sha256(modes_path) != expected_modes_sha256:
            raise ContractError("operating mode registry hash is stale")
        modes = json.loads(modes_path.read_text(encoding="utf-8-sig"))
        request = apply_typed_operating_mode(request, modes, mode_id)
        paths["operating_mode_registry"] = modes_path
        resolved_design = compile_governed_design_request_file(
            paths["design_request"],
            paths["design_variables"],
            paths["optimization_envelope"],
            expected_identity=profile["identity"],
            provenance_root=repo_root,
            operating_mode_registry_path=modes_path,
            mode_id=mode_id,
            repository_text_sources=True,
        )
    if request["identity"] != profile["identity"]:
        raise ContractError("design request identity differs from design profile")
    if request["geometry_mm"]["enclosure"]["role"] != profile["topology"]["enclosure_role"]:
        raise ContractError("design request enclosure role differs from design profile")
    if request["segmentation"]["strategy"] != profile["topology"]["segmentation_strategy"]:
        raise ContractError("design request segmentation differs from design profile")
    if request["axial_drive"]["topology"] != profile["topology"]["axial_drive_topology"]:
        raise ContractError("design request axial-drive topology differs from design profile")
    result = {
        "project_root": project_root,
        "descriptor_path": descriptor_path,
        "registry_path": registry_path,
        "profiles_path": profiles_path,
        "profile": profile,
        "paths": paths,
    }
    if resolved_design is not None:
        result["resolved_design"] = resolved_design
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--design-profile-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = resolve_design_profile(
        args.repo_root, args.project_id, args.design_profile_id
    )
    serializable = {
        **result,
        "project_root": str(result["project_root"]),
        "descriptor_path": str(result["descriptor_path"]),
        "registry_path": str(result["registry_path"]),
        "profiles_path": str(result["profiles_path"]),
        "paths": {key: str(value) for key, value in result["paths"].items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
