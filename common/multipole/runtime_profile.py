"""Resolve one governed multipole transport profile and verify its file identities."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256 as _sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.build_project_registry import pointer_value
from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    apply_typed_operating_mode,
    canonical_sha256,
    compile_design_request,
    operating_mode_source_label,
)
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
    if not isinstance(source_profile, dict) or set(source_profile) not in (
        {"path", "sha256"}, {"path", "sha256", "volume_snapshot_receipt"}
    ):
        raise ValueError("particle-source profile keys differ")
    source_path = (repo_root / source_profile["path"]).resolve()
    if not source_path.is_relative_to(repo_root.resolve()):
        raise ValueError("particle-source profile escapes the repository")
    if _sha256(source_path) != str(source_profile["sha256"]).upper():
        raise ValueError("particle-source SHA-256 differs from its profile")
    source_snapshot_receipt: dict[str, str] | None = None
    if "volume_snapshot_receipt" in source_profile:
        receipt_profile = source_profile["volume_snapshot_receipt"]
        if not isinstance(receipt_profile, dict) or set(receipt_profile) != {"path", "sha256"}:
            raise ValueError("volume-source receipt profile is invalid")
        receipt_path = (repo_root / receipt_profile["path"]).resolve()
        if not receipt_path.is_relative_to(repo_root.resolve()) or not receipt_path.is_file():
            raise ValueError("volume-source receipt profile escapes the repository")
        receipt_sha256 = _sha256(receipt_path)
        if receipt_sha256 != str(receipt_profile["sha256"]).upper():
            raise ValueError("volume-source receipt SHA-256 differs from its profile")
        source_snapshot_receipt = {"path": str(receipt_path), "sha256": receipt_sha256}

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
            **({"volume_snapshot_receipt": source_snapshot_receipt}
               if source_snapshot_receipt is not None else {}),
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


def _set_pointer(document: dict[str, Any], pointer: str, value: int | float) -> None:
    """Replace one existing scalar selected by a catalog JSON Pointer."""

    tokens = [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]
    parent: Any = document
    for token in tokens[:-1]:
        if not isinstance(parent, dict) or token not in parent:
            raise ValueError(f"catalog pointer is missing from the base request: {pointer}")
        parent = parent[token]
    leaf = tokens[-1]
    if not isinstance(parent, dict) or leaf not in parent:
        raise ValueError(f"catalog pointer is missing from the base request: {pointer}")
    parent[leaf] = value


def _resolve_execution_profile(
    project_root: Path, project_id: str, execution_profile_id: str
) -> dict[str, Any]:
    path = project_root / "config" / "execution_profiles.json"
    registry = _load(path)
    try:
        validate_schema(registry, "execution_profiles.schema.json")
    except ContractError as error:
        raise ValueError(f"invalid execution-profile registry: {error}") from error
    if registry["project_id"] != project_id:
        raise ValueError("execution-profile registry project identity differs")
    selected = [
        item for item in registry["profiles"] if item["profile_id"] == execution_profile_id
    ]
    if len(selected) != 1:
        raise ValueError(f"execution profile is not unique: {execution_profile_id}")
    profile = selected[0]
    run_steps = [item for item in profile["steps"] if item["kind"] == "run"]
    if (
        profile["mode"] != "finite_3d_no_collision"
        or profile["evidence_levels"] != ["plan"]
        or set(profile["required_bindings"]) != {"campaign_path", "experiment_id"}
        or not {"simulation_results", "simion_model", "interface_state"}.issubset(
            profile["deliverable_outputs"]
        )
        or len(run_steps) != 1
        or not run_steps[0]["entrypoint"].replace("\\", "/").endswith(
            "common/multipole/run_simion_transport_campaign.ps1"
        )
    ):
        raise ValueError(
            "execution profile is not the governed SIMION campaign engineering workflow"
        )
    return {
        "profile_id": execution_profile_id,
        "path": path.resolve(),
        "sha256": _sha256(path),
        "profile": profile,
    }


def _resolve_phase_policy(
    repo_root: Path,
    project_root: Path,
    project_id: str,
    campaign: dict[str, Any],
    experiment: dict[str, Any],
    design: dict[str, Any],
) -> dict[str, Any]:
    """Bind phase-matched source derivation without materializing run artifacts."""

    policy = campaign["particle_source_phase_policy"]
    baseline_frequency = float(policy["baseline_frequency_Hz"])
    candidate_frequency = float(design["resolved_design"]["drive"]["frequency_Hz"])
    declared_frequency = float(
        experiment["design_variable_values"][policy["frequency_variable_id"]]
    )
    if not math.isclose(candidate_frequency, declared_frequency, rel_tol=0, abs_tol=0):
        raise ValueError("candidate RF frequency differs from the campaign row")
    authority = _resolve_particle_source(
        repo_root,
        project_root,
        project_id,
        experiment["particle_source_profile_id"],
    )
    reference = _resolve_particle_source(
        repo_root,
        project_root,
        project_id,
        policy["n1000_reference_profile_id"],
    )
    authority_count = _particle_count(Path(authority["path"]))
    if authority_count not in (100, 1000, 5000):
        raise ValueError("phase-matched source must contain N=100, N=1000, or N=5000 particles")
    if _particle_count(Path(reference["path"])) != 1000:
        raise ValueError("phase-matched reference source must contain N=1000 particles")
    if authority_count == 1000 and authority["sha256"] != reference["sha256"]:
        raise ValueError("N=1000 phase-matched authority differs from its reference")
    if authority_count == 5000:
        authority_lines = Path(authority["path"]).read_text(encoding="utf-8-sig").splitlines()
        reference_lines = Path(reference["path"]).read_text(encoding="utf-8-sig").splitlines()
        if authority_lines[: len(reference_lines)] != reference_lines:
            raise ValueError("N=5000 phase-matched authority does not preserve the N=1000 reference prefix")
    return {
        "kind": policy["kind"],
        "baseline_frequency_Hz": baseline_frequency,
        "candidate_frequency_Hz": candidate_frequency,
        "frequency_variable_id": policy["frequency_variable_id"],
        "authority_source": authority,
        "authority_particle_count": authority_count,
        "n1000_reference_source": reference,
        "formula": "t_new = t_old * baseline_frequency_Hz / candidate_frequency_Hz",
    }


def _resolve_source_transform_policy(
    repo_root: Path,
    project_root: Path,
    project_id: str,
    campaign: dict[str, Any],
    experiment: dict[str, Any],
    design: dict[str, Any],
) -> dict[str, Any]:
    """Bind the governed v5 initial-energy transform without materializing it."""

    policy = campaign["particle_source_transform_policy"]
    frequency = float(policy["rf_frequency_Hz"])
    design_frequency = float(design["resolved_design"]["drive"]["frequency_Hz"])
    if not math.isclose(frequency, design_frequency, rel_tol=0, abs_tol=0):
        raise ValueError("source-transform RF frequency differs from the resolved design")
    target_energy = float(experiment["source_kinetic_energy_eV"])
    authority = _resolve_particle_source(
        repo_root, project_root, project_id, experiment["particle_source_profile_id"]
    )
    reference = _resolve_particle_source(
        repo_root,
        project_root,
        project_id,
        policy["n1000_reference_profile_id"],
    )
    authority_count = _particle_count(Path(authority["path"]))
    if authority_count not in (100, 1000, 5000):
        raise ValueError("source transform requires a standard N=100, N=1000, or N=5000 authority")
    if _particle_count(Path(reference["path"])) != 1000:
        raise ValueError("source-transform reference must contain N=1000 particles")
    if authority_count == 1000 and authority["sha256"] != reference["sha256"]:
        raise ValueError("N=1000 source-transform authority differs from its reference")
    if authority_count == 5000:
        authority_lines = Path(authority["path"]).read_text(encoding="utf-8-sig").splitlines()
        reference_lines = Path(reference["path"]).read_text(encoding="utf-8-sig").splitlines()
        if authority_lines[: len(reference_lines)] != reference_lines:
            raise ValueError("N=5000 source-transform authority does not preserve the N=1000 reference prefix")
    return {
        "kind": policy["kind"],
        "baseline_frequency_Hz": frequency,
        "candidate_frequency_Hz": frequency,
        "target_kinetic_energy_eV": target_energy,
        "authority_source": authority,
        "authority_particle_count": authority_count,
        "n1000_reference_source": reference,
        "formula": (
            "preserve birth_time, position and velocity direction; scale velocity "
            "to source_kinetic_energy_eV"
        ),
    }


def _typed_base_request(design: dict[str, Any]) -> dict[str, Any]:
    request = _load(design["paths"]["design_request"])
    mode_id = design["profile"].get("mode_id")
    if mode_id is None:
        return request
    mode_path = design["paths"].get("operating_mode_registry")
    if mode_path is None:
        raise ValueError("typed design profile omits its operating-mode registry")
    try:
        return apply_typed_operating_mode(request, _load(mode_path), mode_id)
    except MultipoleDesignCompileError as error:
        raise ValueError(f"typed base design is invalid: {error}") from error


def _compile_campaign_design_candidate(
    repo_root: Path,
    project_id: str,
    campaign: dict[str, Any],
    experiment: dict[str, Any],
    design: dict[str, Any],
) -> dict[str, Any]:
    """Compile one v3 row through catalog, profile and envelope authorities."""

    authorization = campaign["design_variable_authorization"]
    allowed_ids = authorization["allowed_variable_ids"]
    limits = authorization["variable_limits"]
    limit_ids = [item["variable_id"] for item in limits]
    if len(limit_ids) != len(set(limit_ids)) or set(limit_ids) != set(allowed_ids):
        raise ValueError(
            "campaign variable limits must identify every allowed variable exactly once"
        )
    limit_by_id = {item["variable_id"]: item for item in limits}
    for item in limits:
        if not math.isfinite(float(item["minimum"])) or not math.isfinite(
            float(item["maximum"])
        ):
            raise ValueError("campaign design-variable limits must be finite")
        if float(item["minimum"]) > float(item["maximum"]):
            raise ValueError("campaign design-variable minimum exceeds maximum")

    execution = _resolve_execution_profile(
        repo_root / "projects" / project_id,
        project_id,
        experiment["execution_profile_id"],
    )
    catalog = _load(design["paths"]["design_variables"])
    envelope = _load(design["paths"]["optimization_envelope"])
    try:
        validate_schema(catalog, "design_variable_catalog.schema.json")
        validate_schema(envelope, "optimization_envelope.schema.json")
    except ContractError as error:
        raise ValueError(f"invalid design-variable authority: {error}") from error
    if (
        catalog["project_id"] != project_id
        or envelope["project_id"] != project_id
        or catalog["family_id"] != campaign["family_id"]
        or envelope["family_id"] != campaign["family_id"]
    ):
        raise ValueError("design-variable authority identity differs")
    if envelope["status"] == "retired":
        raise ValueError("retired optimization envelope cannot authorize a campaign")
    if envelope["reference"]["design_request_sha256"] != _sha256(
        design["paths"]["design_request"]
    ):
        raise ValueError("optimization envelope base request SHA-256 differs")

    catalog_items = {item["variable_id"]: item for item in catalog["variables"]}
    if len(catalog_items) != len(catalog["variables"]):
        raise ValueError("design-variable catalog identifiers must be unique")
    bounded_pointers = {
        pointer
        for constraint in envelope["constraints"]
        if constraint["kind"] == "bounded_variable"
        for pointer in constraint["request_json_pointers"]
    }
    supported = set(execution["profile"]["supported_design_variables"])
    for variable_id in allowed_ids:
        item = catalog_items.get(variable_id)
        if item is None:
            raise ValueError(f"campaign authorizes unknown design variable: {variable_id}")
        if item["json_pointer"] not in bounded_pointers:
            raise ValueError(
                f"campaign design variable is outside the optimization envelope: {variable_id}"
            )
        if variable_id not in supported:
            raise ValueError(
                f"execution profile does not support design variable: {variable_id}"
            )
        campaign_limit = limit_by_id[variable_id]
        if campaign_limit["unit"] != item["unit"]:
            raise ValueError(f"campaign design-variable unit differs: {variable_id}")
        if (
            float(campaign_limit["minimum"]) < float(item["minimum"])
            or float(campaign_limit["maximum"]) > float(item["maximum"])
        ):
            raise ValueError(
                f"campaign design-variable range exceeds catalog bounds: {variable_id}"
            )

    values = experiment["design_variable_values"]
    missing = set(allowed_ids) - set(values)
    unknown = set(values) - set(allowed_ids)
    if missing or unknown:
        raise ValueError(
            "campaign row design-variable keys differ from its authorization: "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    request = _typed_base_request(design)
    applied: dict[str, dict[str, Any]] = {}
    for variable_id, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(
            float(value)
        ):
            raise ValueError(f"campaign design-variable value must be finite: {variable_id}")
        catalog_item = catalog_items[variable_id]
        if catalog_item["kind"] == "integer" and not isinstance(value, int):
            raise ValueError(f"campaign integer design variable is not integer: {variable_id}")
        campaign_limit = limit_by_id[variable_id]
        if not float(campaign_limit["minimum"]) <= float(value) <= float(
            campaign_limit["maximum"]
        ):
            raise ValueError(f"campaign design-variable value is outside its narrow range: {variable_id}")
        if not float(catalog_item["minimum"]) <= float(value) <= float(
            catalog_item["maximum"]
        ):
            raise ValueError(f"campaign design-variable value is outside catalog bounds: {variable_id}")
        _set_pointer(request, catalog_item["json_pointer"], value)
        applied[variable_id] = {
            "value": value,
            "unit": catalog_item["unit"],
            "json_pointer": catalog_item["json_pointer"],
        }
    if request["identity"] != design["profile"]["identity"]:
        raise ValueError("campaign candidate base design identity differs")
    for item in applied.values():
        if pointer_value(request, item["json_pointer"]) != item["value"]:
            raise ValueError("campaign design-variable application did not round-trip")

    candidate_request_sha256 = canonical_sha256(request)
    source_files = {
        "base_design_request": design["paths"]["design_request"],
        "design_variables": design["paths"]["design_variables"],
        "optimization_envelope": design["paths"]["optimization_envelope"],
        "execution_profiles": execution["path"],
    }
    mode_id = design["profile"].get("mode_id")
    if mode_id is not None:
        source_files[operating_mode_source_label(mode_id)] = design["paths"][
            "operating_mode_registry"
        ]
    try:
        resolved = compile_design_request(
            request,
            expected_identity=design["profile"]["identity"],
            source_files=source_files,
            source_root=repo_root,
        )
    except MultipoleDesignCompileError as error:
        raise ValueError(f"campaign design candidate does not compile: {error}") from error
    if resolved["request"]["sha256"] != candidate_request_sha256:
        raise ValueError("compiled candidate request SHA-256 differs")
    design["resolved_design"] = resolved
    design["candidate_request"] = request
    design["candidate_request_sha256"] = candidate_request_sha256
    design["campaign_design_variables"] = {
        "execution_profile_id": execution["profile_id"],
        "execution_profile_registry_path": str(execution["path"]),
        "execution_profile_registry_sha256": execution["sha256"],
        "catalog_sha256": _sha256(design["paths"]["design_variables"]),
        "optimization_envelope_sha256": _sha256(
            design["paths"]["optimization_envelope"]
        ),
        "allowed_variable_ids": copy.deepcopy(allowed_ids),
        "variable_limits": copy.deepcopy(limits),
        "applied_values": applied,
    }
    return design


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
    if campaign["schema_version"] in (2, 3, 4, 5, 6):
        downstream_terminal = _resolve_downstream_terminal_profile(
            repo_root, campaign["downstream_terminal_profile"]
        )

    design = resolve_design_profile(
        repo_root, project_id, experiment["design_profile_id"]
    )
    if campaign["schema_version"] in (3, 4, 6):
        design = _compile_campaign_design_candidate(
            repo_root,
            project_id,
            campaign,
            experiment,
            design,
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
    phase_derivation = None
    if campaign["schema_version"] in (3, 4):
        phase_derivation = _resolve_phase_policy(
            repo_root,
            project_root,
            project_id,
            campaign,
            experiment,
            design,
        )
        if phase_derivation["authority_source"]["sha256"] != source["sha256"]:
            raise ValueError("phase-policy authority source differs from the selected source")
    source_derivation = None
    if campaign["schema_version"] in (5, 6):
        source_derivation = _resolve_source_transform_policy(
            repo_root,
            project_root,
            project_id,
            campaign,
            experiment,
            design,
        )
        if source_derivation["authority_source"]["sha256"] != source["sha256"]:
            raise ValueError("source-transform authority differs from the selected source")
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
        "case_set": experiment.get("case_set"),
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
            "experiment_row_sha256": canonical_sha256(experiment),
            "path": str(path),
            "sha256": _sha256(path),
            "runtime_profile_registry_path": str(runtime_registry_path.resolve()),
            "runtime_profile_registry_sha256": _sha256(runtime_registry_path),
        },
    }
    if "simion_dispatch" in experiment:
        result["simion_dispatch"] = copy.deepcopy(experiment["simion_dispatch"])
    if campaign["schema_version"] in (3, 4, 6):
        result["campaign"]["design_variable_authorization_sha256"] = canonical_sha256(
            campaign["design_variable_authorization"]
        )
    if campaign["schema_version"] in (3, 4):
        result["campaign"]["particle_source_phase_policy_sha256"] = canonical_sha256(
            campaign["particle_source_phase_policy"]
        )
        result["particle_source_phase_derivation"] = phase_derivation
        if "simion_pa_basis_policy" in campaign:
            result["simion_pa_basis_policy"] = copy.deepcopy(
                campaign["simion_pa_basis_policy"]
            )
            result["campaign"]["simion_pa_basis_policy_sha256"] = canonical_sha256(
                campaign["simion_pa_basis_policy"]
            )
    if campaign["schema_version"] in (5, 6):
        result["campaign"]["particle_source_transform_policy_sha256"] = canonical_sha256(
            campaign["particle_source_transform_policy"]
        )
        result["particle_source_derivation"] = source_derivation
        result["simion_pa_basis_policy"] = copy.deepcopy(
            campaign["simion_pa_basis_policy"]
        )
        result["campaign"]["simion_pa_basis_policy_sha256"] = canonical_sha256(
            campaign["simion_pa_basis_policy"]
        )
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


def _semantic_diff_category(path: tuple[str, ...]) -> str:
    """Classify resolved-plan fields for review without creating execution policy."""

    top_level = path[0] if path else ""
    if top_level in {"runtime_profile_id", "stop_stage", "engineering_budget"}:
        return "run_control_or_budget"
    if top_level == "particle_source":
        return "source_cohort_or_sampling"
    if top_level == "solver_numerics":
        return "solver_numerics"
    if top_level in {"design_profile_id", "design_profile_resolution"}:
        return "physical_design_or_field"
    if top_level == "downstream_terminal_profile":
        return "handoff_or_downstream_design"
    if top_level in {"campaign", "runtime_profile_registry_path", "runtime_profile_registry_sha256"} or any(
        part.endswith("sha256") for part in path
    ):
        return "evidence_or_provenance"
    return "declared_configuration"


def _semantic_diff_values(
    before: object, after: object, path: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            changes.extend(
                _semantic_diff_values(before.get(key), after.get(key), path + (key,))
            )
        return changes
    if before == after:
        return []
    return [{
        "path": ".".join(path),
        "category": _semantic_diff_category(path),
        "before": before,
        "after": after,
    }]


def semantic_diff_campaign_experiments(
    repo_root: Path, campaign_path: Path, before_experiment_id: str, after_experiment_id: str
) -> dict[str, Any]:
    """Resolve two campaign rows and return their deterministic review-only diff."""

    campaign = _load(_campaign_file(repo_root.resolve(), campaign_path))
    rows_by_id = {item["experiment_id"]: item for item in campaign.get("experiments", [])}
    if len(rows_by_id) != len(campaign.get("experiments", [])):
        raise ValueError("campaign experiment_id values must be unique")
    try:
        before_row = rows_by_id[before_experiment_id]
        after_row = rows_by_id[after_experiment_id]
    except KeyError as error:
        raise ValueError(f"unknown campaign experiment: {error.args[0]}") from error
    before = resolve_campaign_experiment(
        repo_root, before_row["project_id"], campaign_path, before_experiment_id
    )
    after = resolve_campaign_experiment(
        repo_root, after_row["project_id"], campaign_path, after_experiment_id
    )
    changes = _semantic_diff_values(before, after)
    return {
        "role": "multipole_campaign_resolved_semantic_diff",
        "classification_scope": "review_only_not_execution_policy",
        "campaign_id": campaign["campaign_id"],
        "before_experiment_id": before_experiment_id,
        "after_experiment_id": after_experiment_id,
        "changed_field_count": len(changes),
        "changes": changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--runtime-profile-id")
    parser.add_argument("--campaign-path", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument(
        "--semantic-diff-experiment-ids", nargs=2, metavar=("BEFORE", "AFTER")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.semantic_diff_experiment_ids:
        if args.runtime_profile_id or not args.campaign_path or args.experiment_id:
            parser.error(
                "--semantic-diff-experiment-ids requires --campaign-path only"
            )
        before_id, after_id = args.semantic_diff_experiment_ids
        result = semantic_diff_campaign_experiments(
            args.repo_root.resolve(), args.campaign_path, before_id, after_id
        )
        print(json.dumps(result, indent=2))
        return 0
    if not args.project_id or args.output is None:
        parser.error("normal profile resolution requires --project-id and --output")
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
