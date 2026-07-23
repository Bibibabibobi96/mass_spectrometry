"""Validate project capability descriptors and build their deterministic registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

if __package__:
    from .machine_contracts import ContractError, REPO_ROOT, load_json, sha256, validate_schema
else:
    from machine_contracts import ContractError, REPO_ROOT, load_json, sha256, validate_schema


MATURITY = {"prototype": 0, "static": 1, "candidate": 2, "formal": 3}
EVIDENCE = {"plan": -1, **MATURITY}
DEFAULT_OUTPUT = REPO_ROOT / "config" / "project_registry.json"


def descriptor_paths(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "projects").glob("*/config/project.json"))


def pointer_value(document: dict[str, Any], pointer: str) -> Any:
    value: Any = document
    for token in pointer.lstrip("/").split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


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

    profiles_relative = descriptor["contracts"].get("design_profiles")
    if profiles_relative is not None:
        profiles_path = project_root / profiles_relative
        profiles = load_json(profiles_path)
        validate_schema(profiles, "design_profiles.schema.json")
        if (
            profiles["project_id"] != descriptor["project_id"]
            or profiles["family_id"] != descriptor["family_id"]
        ):
            raise ContractError(f"{profiles_path}: design profile identity differs")
        profile_ids: set[str] = set()
        for profile in profiles["profiles"]:
            profile_id = profile["design_profile_id"]
            if profile_id in profile_ids:
                raise ContractError(f"{profiles_path}: duplicate design profile {profile_id!r}")
            profile_ids.add(profile_id)
            for label in ("design_request", "design_variables", "optimization_envelope"):
                source = project_root / profile[label]
                if not source.is_file() or sha256(source) != profile["sha256"][label]:
                    raise ContractError(f"{profiles_path}: stale design profile source {label!r}")
            request = load_json(project_root / profile["design_request"])
            validate_schema(request, "multipole_design_request.schema.json")
            variables = load_json(project_root / profile["design_variables"])
            envelope = load_json(project_root / profile["optimization_envelope"])
            validate_schema(variables, "design_variable_catalog.schema.json")
            validate_schema(envelope, "optimization_envelope.schema.json")
            if (
                variables["project_id"] != descriptor["project_id"]
                or variables["family_id"] != descriptor["family_id"]
                or envelope["project_id"] != descriptor["project_id"]
                or envelope["family_id"] != descriptor["family_id"]
            ):
                raise ContractError(f"{profiles_path}: profile governance identity differs")
            if envelope["reference"]["design_request_sha256"] != sha256(
                project_root / profile["design_request"]
            ):
                raise ContractError(f"{profiles_path}: profile envelope request hash is stale")
            for variable in variables["variables"]:
                try:
                    current = pointer_value(request, variable["json_pointer"])
                except (KeyError, TypeError) as exc:
                    raise ContractError(
                        f"{profiles_path}: profile catalog pointer is missing"
                    ) from exc
                if not isinstance(current, (int, float)) or isinstance(current, bool):
                    raise ContractError(f"{profiles_path}: profile variable is not numeric")
                if not variable["minimum"] <= current <= variable["maximum"]:
                    raise ContractError(f"{profiles_path}: profile variable is outside bounds")
            if request["identity"] != profile["identity"]:
                raise ContractError(f"{profiles_path}: profile request identity differs")
            if request["geometry_mm"]["enclosure"]["role"] != profile["topology"]["enclosure_role"]:
                raise ContractError(f"{profiles_path}: profile enclosure topology differs")
            if request["segmentation"]["strategy"] != profile["topology"]["segmentation_strategy"]:
                raise ContractError(f"{profiles_path}: profile segmentation topology differs")

    execution_relative = descriptor["contracts"]["execution"]
    if execution_relative is not None:
        execution_path = project_root / execution_relative
        execution = load_json(execution_path)
        validate_schema(execution, "execution_profiles.schema.json")
        if execution["project_id"] != descriptor["project_id"]:
            raise ContractError(f"{execution_path}: project_id differs from project descriptor")
        capabilities = {item["capability_id"]: item for item in descriptor["capabilities"]}
        profile_ids: set[str] = set()
        profile_keys: set[tuple[str, str]] = set()
        for profile in execution["profiles"]:
            profile_id = profile["profile_id"]
            if profile_id in profile_ids:
                raise ContractError(f"{execution_path}: duplicate profile_id {profile_id!r}")
            profile_ids.add(profile_id)
            capability = capabilities.get(profile["capability_id"])
            if capability is None:
                raise ContractError(f"{execution_path}: unknown capability {profile['capability_id']!r}")
            if profile["mode"] not in capability["modes"]:
                raise ContractError(f"{execution_path}: profile mode {profile['mode']!r} is not declared by capability")
            key = (profile["capability_id"], profile["mode"])
            if key in profile_keys:
                raise ContractError(f"{execution_path}: duplicate capability/mode profile {key!r}")
            profile_keys.add(key)
            if any(EVIDENCE[level] > MATURITY[capability["status"]] for level in profile["evidence_levels"]):
                raise ContractError(f"{execution_path}: profile evidence exceeds capability maturity")
            for step in profile["steps"]:
                entrypoint = project_root / step["entrypoint"]
                if not entrypoint.is_file():
                    raise ContractError(f"{execution_path}: step entrypoint is missing: {step['entrypoint']}")

    variables_relative = descriptor["contracts"]["design_variables"]
    if variables_relative is not None:
        variables_path = project_root / variables_relative
        catalog = load_json(variables_path)
        validate_schema(catalog, "design_variable_catalog.schema.json")
        if catalog["project_id"] != descriptor["project_id"]:
            raise ContractError(f"{variables_path}: project_id differs from project descriptor")
        strategy = catalog["optimization_strategy"]
        if strategy == "expandable_reference_envelope_compaction":
            reference_relative = descriptor["contracts"]["baseline"]
            if reference_relative is None:
                raise ContractError(f"{variables_path}: design variables require a baseline contract")
            reference = load_json(project_root / reference_relative)
        elif strategy == "multipole_design_request_compilation":
            if catalog["family_id"] != descriptor["family_id"]:
                raise ContractError(f"{variables_path}: family_id differs from project descriptor")
            reference = None
            baseline_relative = descriptor["contracts"]["baseline"]
            if baseline_relative is None:
                raise ContractError(f"{variables_path}: multipole design variables require a baseline contract")
            baseline = load_json(project_root / baseline_relative)
            baseline_identity = baseline["multipole"]
            expected_identity = {
                "project_id": descriptor["project_id"],
                "family_id": descriptor["family_id"],
                "radial_order_n": baseline_identity["radial_order_n"],
                "electrode_count": baseline_identity["electrode_count"],
            }
            if expected_identity["electrode_count"] != 2 * expected_identity["radial_order_n"]:
                raise ContractError(f"{variables_path}: electrode_count must equal twice radial_order_n")
        else:
            raise ContractError(f"{variables_path}: unsupported optimization strategy")
        catalog_ids: set[str] = set()
        for variable in catalog["variables"]:
            variable_id = variable["variable_id"]
            if variable_id in catalog_ids:
                raise ContractError(f"{variables_path}: duplicate variable_id {variable_id!r}")
            catalog_ids.add(variable_id)
            if variable["minimum"] >= variable["maximum"]:
                raise ContractError(f"{variables_path}: invalid bounds for {variable_id!r}")
            if reference is not None:
                try:
                    current = pointer_value(reference, variable["json_pointer"])
                except (KeyError, TypeError) as exc:
                    raise ContractError(f"{variables_path}: invalid JSON pointer for {variable_id!r}") from exc
                if not isinstance(current, (int, float)) or isinstance(current, bool):
                    raise ContractError(f"{variables_path}: variable target is not numeric: {variable_id!r}")
                if not variable["minimum"] <= current <= variable["maximum"]:
                    raise ContractError(f"{variables_path}: baseline value is outside bounds: {variable_id!r}")
                if variable["kind"] == "integer" and not isinstance(current, int):
                    raise ContractError(f"{variables_path}: integer variable targets non-integer baseline: {variable_id!r}")
        declared_ids = {item for capability in descriptor["capabilities"] for item in capability["design_variables"]}
        if catalog_ids != declared_ids:
            missing = sorted(declared_ids - catalog_ids)
            extra = sorted(catalog_ids - declared_ids)
            raise ContractError(f"{variables_path}: catalog/capability mismatch missing={missing} extra={extra}")

        envelope_relative = descriptor["contracts"]["optimization_envelope"]
        if strategy == "multipole_design_request_compilation":
            envelope_relative = None
        elif envelope_relative is None or catalog["envelope_contract"] != envelope_relative:
            raise ContractError(f"{variables_path}: catalog must reference the project optimization envelope")
        if envelope_relative is None:
            envelope = None
        else:
            envelope_path = project_root / envelope_relative
            envelope = load_json(envelope_path)
            validate_schema(envelope, "optimization_envelope.schema.json")
        if envelope is not None and envelope["project_id"] != descriptor["project_id"]:
            raise ContractError(f"{envelope_path}: project_id differs from project descriptor")
        reference_path = project_root / reference_relative if reference is not None else None
        if strategy == "expandable_reference_envelope_compaction":
            if envelope["reference"]["baseline"] != reference_relative:
                raise ContractError(f"{envelope_path}: reference baseline differs from project descriptor")
            if envelope["reference"]["baseline_sha256"] != sha256(reference_path):
                raise ContractError(f"{envelope_path}: reference baseline hash is stale")
            geometry = reference["geometry_mm"]
            rings = reference["rings"]
            limits = envelope["tof_limits"]
            current_values = {
                "max_flight_length_mm": geometry["L_flight"],
                "max_positive_axial_extent_mm": geometry["shield_outer_z_max"] - geometry["detector_z"],
                "max_outer_radius_mm": geometry["flight_tube_r"] + geometry["flight_tube_wall"],
                "max_stage1_electrode_count": rings["stage1_count"],
                "max_stage2_electrode_count": rings["stage2_count"],
            }
            for limit, current in current_values.items():
                if current > limits[limit] + 1e-10:
                    raise ContractError(f"{envelope_path}: formal baseline exceeds {limit}")
        elif envelope is not None:
            if envelope["family_id"] != descriptor["family_id"]:
                raise ContractError(f"{envelope_path}: family_id differs from project descriptor")
            if envelope["reference"]["design_request"] != reference_relative:
                raise ContractError(f"{envelope_path}: reference design request differs from catalog")
            if envelope["reference"]["design_request_sha256"] != sha256(reference_path):
                raise ContractError(f"{envelope_path}: reference design request hash is stale")
            constraint_ids: set[str] = set()
            for constraint in envelope["constraints"]:
                constraint_id = constraint["constraint_id"]
                if constraint_id in constraint_ids:
                    raise ContractError(f"{envelope_path}: duplicate constraint_id {constraint_id!r}")
                constraint_ids.add(constraint_id)
                for pointer in constraint["request_json_pointers"]:
                    try:
                        pointer_value(reference, pointer)
                    except (KeyError, TypeError) as exc:
                        raise ContractError(
                            f"{envelope_path}: invalid request JSON pointer in {constraint_id!r}"
                        ) from exc
    elif descriptor["contracts"]["optimization_envelope"] is not None:
        raise ContractError(f"{path}: optimization envelope requires a design-variable catalog")

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
