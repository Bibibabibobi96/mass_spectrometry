"""Resolve one governed multipole transport profile and verify its file identities."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common.multipole.design_profile import resolve_design_profile
from common.multipole.simion_numerics import normalize_simion_solver_numerics


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys differ: {sorted(value)}")


def resolve_runtime_profile(
    repo_root: Path, project_id: str, runtime_profile_id: str
) -> dict[str, Any]:
    project_root = repo_root / "projects" / project_id
    registry_path = project_root / "config" / "runtime_profiles.json"
    registry = _load(registry_path)
    registry_keys = {"schema_version", "role", "project_id", "profiles"}
    optional_registry_keys = {
        "solver_numerics_registry_paths",
        "engineering_budget_path",
    }
    if not registry_keys.issubset(registry) or set(registry) - (
        registry_keys | optional_registry_keys
    ):
        raise ValueError(f"runtime profile registry keys differ: {sorted(registry)}")
    if (
        registry["schema_version"] != 2
        or registry["role"] != "multipole_transport_runtime_profiles"
        or registry["project_id"] != project_id
    ):
        raise ValueError("runtime profile registry identity differs")
    profiles = registry["profiles"]
    if not isinstance(profiles, dict) or runtime_profile_id not in profiles:
        raise ValueError(f"unknown runtime profile: {runtime_profile_id}")
    profile = profiles[runtime_profile_id]
    required_profile_keys = {
        "design_profile_id",
        "particle_source_profile_id",
        "comsol_solver_numerics_profile_id",
        "simion_solver_numerics_profile_id",
    }
    allowed_profile_keys = required_profile_keys | {
        "stop_stage",
        "engineering_budget_path",
    }
    if not required_profile_keys.issubset(profile) or set(profile) - allowed_profile_keys:
        raise ValueError(f"runtime profile keys differ: {sorted(profile)}")
    stop_stage = profile.get("stop_stage", "transport")
    if stop_stage not in {"transport", "mesh_build", "field_solve"}:
        raise ValueError(f"unsupported runtime stop stage: {stop_stage}")
    design = resolve_design_profile(repo_root, project_id, profile["design_profile_id"])
    design_serializable = {
        **design,
        "project_root": str(design["project_root"]),
        "descriptor_path": str(design["descriptor_path"]),
        "registry_path": str(design["registry_path"]),
        "profiles_path": str(design["profiles_path"]),
        "paths": {key: str(value) for key, value in design["paths"].items()},
    }

    source_registry_path = project_root / "config" / "particle_source_profiles.json"
    source_registry = _load(source_registry_path)
    _require_keys(
        source_registry,
        {"schema_version", "role", "project_id", "profiles"},
        "particle-source registry",
    )
    if (
        source_registry["schema_version"] != 1
        or source_registry["role"] != "multipole_particle_source_profiles"
        or source_registry["project_id"] != project_id
    ):
        raise ValueError("particle-source registry identity differs")
    source_id = profile["particle_source_profile_id"]
    source_profile = source_registry["profiles"].get(source_id)
    if not isinstance(source_profile, dict):
        raise ValueError(f"unknown particle-source profile: {source_id}")
    _require_keys(source_profile, {"path", "sha256"}, "particle-source profile")
    source_path = (repo_root / source_profile["path"]).resolve()
    if not source_path.is_relative_to(repo_root.resolve()):
        raise ValueError("particle-source profile escapes the repository")
    if _sha256(source_path) != str(source_profile["sha256"]).upper():
        raise ValueError("particle-source SHA-256 differs from its profile")

    numerics: dict[str, Any] = {}
    numerics_paths: dict[str, str] = {}
    configured_paths = registry.get("solver_numerics_registry_paths", {})
    if not isinstance(configured_paths, dict) or set(configured_paths) - {
        "comsol",
        "simion",
    }:
        raise ValueError("solver-numerics registry paths are invalid")
    for solver in ("comsol", "simion"):
        relative_path = configured_paths.get(
            solver, f"config/{solver}_solver_numerics.json"
        )
        if not isinstance(relative_path, str):
            raise ValueError(f"{solver} solver-numerics registry path is invalid")
        path = (project_root / relative_path).resolve()
        if not path.is_relative_to(project_root.resolve()):
            raise ValueError(f"{solver} solver-numerics registry escapes the project")
        contract = _load(path)
        _require_keys(
            contract,
            {"schema_version", "role", "project_id", "profiles"},
            f"{solver} solver-numerics registry",
        )
        expected_role = f"multipole_{solver}_solver_numerics_profiles"
        if (
            contract["schema_version"] != 1
            or contract["role"] != expected_role
            or contract["project_id"] != project_id
        ):
            raise ValueError(f"{solver} solver-numerics registry identity differs")
        profile_id = profile[f"{solver}_solver_numerics_profile_id"]
        selected = contract["profiles"].get(profile_id)
        if not isinstance(selected, dict):
            raise ValueError(f"unknown {solver} solver-numerics profile: {profile_id}")
        if solver == "simion":
            selected = normalize_simion_solver_numerics(selected)
        numerics[solver] = {
            "profile_id": profile_id,
            "values": selected,
            "registry_sha256": _sha256(path),
        }
        numerics_paths[solver] = str(path.resolve())

    budget_relative_path = profile.get(
        "engineering_budget_path",
        registry.get("engineering_budget_path"),
    )
    if not isinstance(budget_relative_path, str) or not budget_relative_path:
        raise ValueError("runtime profile registry engineering_budget_path is missing")
    budget_path = (project_root / budget_relative_path).resolve()
    if not budget_path.is_relative_to(project_root.resolve()):
        raise ValueError("engineering-budget path escapes the project")
    if not budget_path.is_file():
        raise ValueError(f"engineering-budget contract is missing: {budget_path}")

    return {
        "schema_version": 1,
        "role": "multipole_resolved_runtime_profile",
        "project_id": project_id,
        "runtime_profile_id": runtime_profile_id,
        "runtime_profile_registry_path": str(registry_path.resolve()),
        "runtime_profile_registry_sha256": _sha256(registry_path),
        "stop_stage": stop_stage,
        "design_profile_id": profile["design_profile_id"],
        "design_profile_resolution": design_serializable,
        "particle_source": {
            "profile_id": source_id,
            "path": str(source_path),
            "sha256": _sha256(source_path),
            "registry_path": str(source_registry_path.resolve()),
            "registry_sha256": _sha256(source_registry_path),
        },
        "solver_numerics": numerics,
        "solver_numerics_registry_paths": numerics_paths,
        "engineering_budget": {
            "path": str(budget_path),
            "sha256": _sha256(budget_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--runtime-profile-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = resolve_runtime_profile(
        args.repo_root.resolve(), args.project_id, args.runtime_profile_id
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "MULTIPOLE_RUNTIME_PROFILE=PASS "
        f"PROJECT={args.project_id} PROFILE={args.runtime_profile_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
