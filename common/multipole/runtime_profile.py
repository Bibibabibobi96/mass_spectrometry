"""Resolve one governed multipole transport profile and verify its file identities."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import ContractError, validate_schema
from common.multipole.design_profile import resolve_design_profile
from common.multipole.downstream_terminal import (
    compose_downstream_terminal,
    select_downstream_terminal_profile,
)
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


def _project_file(project_root: Path, path: Path | str, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(project_root.resolve()):
        raise ValueError(f"{label} escapes the project")
    if not candidate.is_file():
        raise ValueError(f"{label} is missing: {candidate}")
    return candidate


def _campaign_file(repo_root: Path, path: Path) -> Path:
    campaign_root = (repo_root / "common" / "multipole" / "campaigns").resolve()
    candidate = path if path.is_absolute() else campaign_root / path
    candidate = candidate.resolve()
    if not candidate.is_relative_to(campaign_root):
        raise ValueError("campaign path escapes common/multipole/campaigns")
    if not candidate.is_file():
        raise ValueError(f"campaign path is missing: {candidate}")
    return candidate


def _resolve_downstream_terminal_profile(
    repo_root: Path, binding: dict[str, Any]
) -> dict[str, Any]:
    """Resolve one integration-owned terminal profile without project copies."""

    _require_keys(
        binding,
        {"integration_id", "terminal_profile_id", "registry_sha256"},
        "downstream-terminal campaign binding",
    )
    discovery_path = repo_root / "integrations" / "registry.json"
    discovery = _load(discovery_path)
    validate_schema(discovery, "integration_registry.schema.json")
    matches = [
        item
        for item in discovery["integrations"]
        if item["integration_id"] == binding["integration_id"]
    ]
    if len(matches) != 1:
        raise ValueError("downstream-terminal integration identity is not unique")
    relative = matches[0].get("downstream_terminal_profile_registry")
    if not isinstance(relative, str) or not relative:
        raise ValueError("integration omits its downstream-terminal profile registry")
    registry_path = (repo_root / relative).resolve()
    if not registry_path.is_relative_to(repo_root) or not registry_path.is_file():
        raise ValueError("downstream-terminal profile registry is missing or escapes the repository")
    registry_sha256 = _sha256(registry_path)
    if registry_sha256 != binding["registry_sha256"]:
        raise ValueError("downstream-terminal profile registry SHA-256 differs")
    registry = _load(registry_path)
    validate_schema(registry, "multipole_downstream_terminal_profiles.schema.json")
    if (
        registry["integration_id"] != binding["integration_id"]
        or registry["compatible_upstream_family_id"] != "rf_multipole_ion_optics"
    ):
        raise ValueError("downstream-terminal profile registry identity differs")
    selected = [
        item
        for item in registry["profiles"]
        if item["terminal_profile_id"] == binding["terminal_profile_id"]
    ]
    if len(selected) != 1:
        raise ValueError("downstream-terminal profile identity is not unique")
    return {
        "integration_id": binding["integration_id"],
        "terminal_profile_id": binding["terminal_profile_id"],
        "registry_path": str(registry_path),
        "registry_sha256": registry_sha256,
        "profile": selected[0],
        "discovery_path": str(discovery_path.resolve()),
        "discovery_sha256": _sha256(discovery_path),
    }


def _serializable_design(design: dict[str, Any]) -> dict[str, Any]:
    return {
        **design,
        "project_root": str(design["project_root"]),
        "descriptor_path": str(design["descriptor_path"]),
        "registry_path": str(design["registry_path"]),
        "profiles_path": str(design["profiles_path"]),
        "paths": {key: str(value) for key, value in design["paths"].items()},
    }


def _resolve_particle_source(
    repo_root: Path,
    project_root: Path,
    project_id: str,
    source_id: str,
) -> dict[str, str]:
    registry_path = project_root / "config" / "particle_source_profiles.json"
    registry = _load(registry_path)
    _require_keys(
        registry,
        {"schema_version", "role", "project_id", "profiles"},
        "particle-source registry",
    )
    if (
        registry["schema_version"] != 1
        or registry["role"] != "multipole_particle_source_profiles"
        or registry["project_id"] != project_id
    ):
        raise ValueError("particle-source registry identity differs")
    selected = registry["profiles"].get(source_id)
    if not isinstance(selected, dict):
        raise ValueError(f"unknown particle-source profile: {source_id}")
    _require_keys(selected, {"path", "sha256"}, "particle-source profile")
    source_path = (repo_root / selected["path"]).resolve()
    if not source_path.is_relative_to(repo_root.resolve()):
        raise ValueError("particle-source profile escapes the repository")
    if _sha256(source_path) != str(selected["sha256"]).upper():
        raise ValueError("particle-source SHA-256 differs from its profile")
    return {
        "profile_id": source_id,
        "path": str(source_path),
        "sha256": _sha256(source_path),
        "registry_path": str(registry_path.resolve()),
        "registry_sha256": _sha256(registry_path),
    }


def _solver_registry_paths(
    project_root: Path, project_id: str
) -> tuple[dict[str, Path], dict[str, Any], Path]:
    runtime_registry_path = project_root / "config" / "runtime_profiles.json"
    runtime_registry = _load(runtime_registry_path)
    if (
        runtime_registry.get("schema_version") != 2
        or runtime_registry.get("role") != "multipole_transport_runtime_profiles"
        or runtime_registry.get("project_id") != project_id
    ):
        raise ValueError("runtime profile registry identity differs")
    configured = runtime_registry.get("solver_numerics_registry_paths", {})
    if not isinstance(configured, dict) or set(configured) - {"comsol", "simion"}:
        raise ValueError("solver-numerics registry paths are invalid")
    paths = {
        solver: _project_file(
            project_root,
            configured.get(solver, f"config/{solver}_solver_numerics.json"),
            f"{solver} solver-numerics registry",
        )
        for solver in ("comsol", "simion")
    }
    return paths, runtime_registry, runtime_registry_path


def _resolve_solver_profile(
    path: Path, project_id: str, solver: str, profile_id: str
) -> dict[str, Any]:
    registry = _load(path)
    _require_keys(
        registry,
        {"schema_version", "role", "project_id", "profiles"},
        f"{solver} solver-numerics registry",
    )
    if (
        registry["schema_version"] != 1
        or registry["role"] != f"multipole_{solver}_solver_numerics_profiles"
        or registry["project_id"] != project_id
    ):
        raise ValueError(f"{solver} solver-numerics registry identity differs")
    selected = registry["profiles"].get(profile_id)
    if not isinstance(selected, dict):
        raise ValueError(f"unknown {solver} solver-numerics profile: {profile_id}")
    if solver == "simion":
        selected = normalize_simion_solver_numerics(selected)
    return {
        "profile_id": profile_id,
        "values": selected,
        "registry_sha256": _sha256(path),
    }


def _particle_count(path: Path) -> int:
    with path.open(encoding="utf-8-sig") as stream:
        return max(sum(1 for line in stream if line.strip()) - 1, 0)


def resolve_campaign_experiment(
    repo_root: Path,
    project_id: str,
    campaign_path: Path,
    experiment_id: str,
) -> dict[str, Any]:
    """Resolve one preregistered SIMION experiment through existing authorities."""

    repo_root = repo_root.resolve()
    project_root = repo_root / "projects" / project_id
    path = _campaign_file(repo_root, campaign_path)
    campaign = _load(path)
    try:
        json.dumps(campaign, allow_nan=False)
        validate_schema(
            campaign, "multipole_transport_experiment_campaign.schema.json"
        )
    except (ContractError, TypeError, ValueError) as error:
        raise ValueError(f"invalid multipole transport campaign: {error}") from error
    if campaign["family_id"] != "rf_multipole_ion_optics":
        raise ValueError("campaign family identity differs")
    identifiers = [item["experiment_id"] for item in campaign["experiments"]]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("campaign experiment_id values must be unique")
    matches = [
        item for item in campaign["experiments"] if item["experiment_id"] == experiment_id
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown campaign experiment: {experiment_id}")
    experiment = matches[0]
    if experiment["project_id"] != project_id:
        raise ValueError("campaign experiment project identity differs")

    downstream_terminal = None
    if campaign["schema_version"] == 2:
        downstream_terminal = _resolve_downstream_terminal_profile(
            repo_root, campaign["downstream_terminal_profile"]
        )

    design = resolve_design_profile(
        repo_root, project_id, experiment["design_profile_id"]
    )
    if downstream_terminal is not None:
        terminal_profile = select_downstream_terminal_profile(
            _load(Path(downstream_terminal["registry_path"])),
            downstream_terminal["terminal_profile_id"],
            upstream_project_id=project_id,
        )
        design["resolved_design"] = compose_downstream_terminal(
            design["resolved_design"], terminal_profile
        )
    source = _resolve_particle_source(
        repo_root,
        project_root,
        project_id,
        experiment["particle_source_profile_id"],
    )
    registry_paths, _, runtime_registry_path = _solver_registry_paths(
        project_root, project_id
    )
    comsol = _resolve_solver_profile(
        registry_paths["comsol"],
        project_id,
        "comsol",
        experiment["comsol_solver_numerics_profile_id"],
    )
    simion_binding = experiment["simion_solver_numerics"]
    if simion_binding["kind"] == "profile":
        simion = _resolve_solver_profile(
            registry_paths["simion"],
            project_id,
            "simion",
            simion_binding["profile_id"],
        )
        simion_authority_path = registry_paths["simion"]
    else:
        simion = {
            "profile_id": simion_binding["numerics_id"],
            "values": normalize_simion_solver_numerics(simion_binding["values"]),
            "registry_sha256": _sha256(path),
        }
        simion_authority_path = path

    authorization = experiment["resource_authorization"]
    scope = {
        "project_id": project_id,
        "runtime_profile_id": experiment_id,
        "stop_stage": experiment["stop_stage"],
        "design_profile_id": experiment["design_profile_id"],
        "particle_source_profile_id": source["profile_id"],
        "particle_count": _particle_count(Path(source["path"])),
        "solver_numerics_profile_ids": {
            "comsol": comsol["profile_id"],
            "simion": simion["profile_id"],
        },
        "allowed_solvers": ["simion"],
        "retention_class": experiment["retention_class"],
        "authorized_run_id": experiment["authorized_run_id"],
    }
    budget = {
        "schema_version": 1,
        "role": "multipole_engineering_budget_contract",
        "project_id": project_id,
        "contract_id": f"{campaign['campaign_id']}__{experiment_id}",
        "preregistered_before_run": campaign["preregistered_before_run"],
        "pilot_authorization": {
            "authorized": authorization["authorized"],
            "scope": scope,
            "limits": authorization["limits"],
        },
        "full_matrix_authorization": authorization["full_matrix_authorization"],
        "budget_exhaustion_result": authorization["budget_exhaustion_result"],
        "claim_limit": experiment["claim_limit"],
    }
    result = {
        "schema_version": 1,
        "role": "multipole_resolved_runtime_profile",
        "project_id": project_id,
        "runtime_profile_id": experiment_id,
        "runtime_profile_registry_path": str(path),
        "runtime_profile_registry_sha256": _sha256(path),
        "stop_stage": experiment["stop_stage"],
        "design_profile_id": experiment["design_profile_id"],
        "design_profile_resolution": _serializable_design(design),
        "particle_source": source,
        "solver_numerics": {"comsol": comsol, "simion": simion},
        "solver_numerics_registry_paths": {
            "comsol": str(registry_paths["comsol"]),
            "simion": str(simion_authority_path),
        },
        "engineering_budget": {
            "path": str(path),
            "sha256": _sha256(path),
            "inline_contract": budget,
        },
        "campaign": {
            "campaign_id": campaign["campaign_id"],
            "experiment_id": experiment_id,
            "path": str(path),
            "sha256": _sha256(path),
            "runtime_profile_registry_path": str(runtime_registry_path.resolve()),
            "runtime_profile_registry_sha256": _sha256(runtime_registry_path),
        },
    }
    if downstream_terminal is not None:
        result["downstream_terminal_profile"] = downstream_terminal
    return result


def resolve_runtime_selection(
    repo_root: Path,
    project_id: str,
    *,
    runtime_profile_id: str | None = None,
    campaign_path: Path | None = None,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    """Resolve exactly one legacy profile or declarative campaign experiment."""

    legacy = runtime_profile_id is not None
    campaign = campaign_path is not None or experiment_id is not None
    if legacy == campaign:
        raise ValueError(
            "select exactly one runtime_profile_id or campaign_path + experiment_id"
        )
    if legacy:
        return resolve_runtime_profile(repo_root, project_id, runtime_profile_id)
    if campaign_path is None or experiment_id is None:
        raise ValueError("campaign_path and experiment_id must be provided together")
    return resolve_campaign_experiment(
        repo_root, project_id, campaign_path, experiment_id
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--runtime-profile-id")
    parser.add_argument("--campaign-path", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = resolve_runtime_selection(
        args.repo_root.resolve(),
        args.project_id,
        runtime_profile_id=args.runtime_profile_id,
        campaign_path=args.campaign_path,
        experiment_id=args.experiment_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "MULTIPOLE_RUNTIME_PROFILE=PASS "
        f"PROJECT={args.project_id} PROFILE={result['runtime_profile_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
