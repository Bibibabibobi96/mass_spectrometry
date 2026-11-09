"""Resolve explicit component ports and a connection profile into frozen contracts."""

from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from msplatform.contracts.machine_contracts import (
    ContractError,
    load_json,
    sha256,
    validate_schema,
)
from msplatform.io.file_identity import canonical_json_sha256 as _canonical_sha256
from msplatform.io.file_identity import repository_text_sha256
from msplatform.io.file_identity import file_sha256
from msplatform.assembly.port_mating import (
    _dot as _dot, _norm as _norm, _subtract as _subtract,
    _matrix_vector as _matrix_vector, _determinant as _determinant,
    _validate_rotation as _validate_rotation,
    derive_direct_mating_translation as derive_direct_mating_translation,
    derive_mating_translation_with_gap as derive_mating_translation_with_gap,
)
















@dataclass(frozen=True)
class _ManagedFile:
    path: Path
    portable_path: str
    repository_text: bool


def _managed_file(source_root: str | Path | None, reference: str | Path, *, artifact_root: str | Path | None = None) -> _ManagedFile:
    """Resolve explicit source or legacy artifact bases; never discover a checkout."""
    if source_root is None:
        raise ContractError("connection file references require an explicit source_root")
    root = Path(source_root).resolve()
    artifacts = Path(artifact_root).resolve() if artifact_root is not None else None
    raw = Path(reference)
    if ".." in raw.parts:
        raise ContractError(f"connection source contains parent traversal: {reference}")
    if raw.is_absolute():
        candidate = raw.resolve()
    elif raw.as_posix().startswith("artifacts/projects/"):
        if artifacts is None:
            raise ContractError("legacy artifact references require an explicit artifact_root")
        candidate = (artifacts / Path(*raw.parts[2:])).resolve()
    else:
        candidate = (root / raw).resolve()
    # Explicit artifact ownership takes precedence inside a nested source base.
    relative_artifact = None
    if artifacts is not None:
        try:
            relative_artifact = candidate.relative_to(artifacts)
        except ValueError:
            pass
    if relative_artifact is not None:
        managed = _ManagedFile(candidate, "artifacts/projects/" + relative_artifact.as_posix(), False)
    else:
        if not raw.is_absolute() and raw.as_posix().startswith("artifacts/projects/"):
            raise ContractError(f"connection source is outside explicit artifact root: {reference}")
        try:
            relative_source = candidate.relative_to(root)
        except ValueError as exc:
            raise ContractError(f"connection source is outside repository and artifacts/projects (explicit source and artifact roots): {reference}") from exc
        managed = _ManagedFile(candidate, relative_source.as_posix(), True)
    if not candidate.is_file():
        raise ContractError(f"connection source is missing: {reference}")
    return managed


def _managed_sha256(source: _ManagedFile) -> str:
    if source.repository_text:
        return repository_text_sha256(source.path)
    return file_sha256(source.path)


def _pointer_value(document: Any, pointer: str) -> Any:
    value = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, list):
                value = value[int(token)]
            else:
                value = value[token]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ContractError(f"authority binding pointer is missing: {pointer}") from exc
    return value


def _validate_port_authority(
    port: dict[str, Any], port_path: Path, source_root: Path, *, artifact_root: str | Path | None = None
) -> tuple[str, str]:
    authority = port["authority"]
    source = _managed_file(source_root, authority["source_contract"], artifact_root=artifact_root)
    if source.path == port_path.resolve():
        raise ContractError("component port cannot cite itself as physical authority")
    source_hash = _managed_sha256(source)
    if source_hash != authority["source_sha256"]:
        raise ContractError("component port authority source SHA-256 is stale")
    source_document = load_json(source.path)
    for binding in authority["bindings"]:
        port_value = _pointer_value(port, binding["port_json_pointer"])
        source_value = _pointer_value(
            source_document, binding["source_json_pointer"]
        )
        if port_value != source_value:
            raise ContractError(
                "component port authority binding value differs: "
                f"{binding['port_json_pointer']}"
            )
    return source_hash, source.portable_path


def load_connection_profile_registry(path: str | Path) -> dict[str, Any]:
    """Load and schema-validate one integration family's profile registry."""
    registry = load_json(Path(path))
    validate_schema(registry, "connection_profile_registry.schema.json")
    integration_id = registry["integration_id"]
    seen: set[str] = set()
    for profile in registry["profiles"]:
        if profile["integration_id"] != integration_id:
            raise ContractError(
                f"profile {profile['connection_profile_id']}: integration_id differs from registry"
            )
        profile_id = profile["connection_profile_id"]
        if profile_id in seen:
            raise ContractError(f"duplicate connection_profile_id: {profile_id}")
        seen.add(profile_id)
    return registry




def _validate_transition_aperture(
    aperture: dict[str, Any],
    downstream_normal: list[float],
    angular_tolerance: float,
) -> float:
    width_axis = aperture["width_axis_downstream_frame"]
    height_axis = aperture["height_axis_downstream_frame"]
    for label, axis in (("width", width_axis), ("height", height_axis)):
        if abs(_norm(axis) - 1.0) > angular_tolerance:
            raise ContractError(f"transition aperture {label} axis is not a unit vector")
        if abs(_dot(axis, downstream_normal)) > angular_tolerance:
            raise ContractError(
                f"transition aperture {label} axis is not in the downstream mating plane"
            )
    if abs(_dot(width_axis, height_axis)) > angular_tolerance:
        raise ContractError("transition aperture in-plane axes are not orthogonal")
    return 0.5 * min(aperture["full_width_mm"], aperture["full_height_mm"])


def _validate_field_ownership(
    segments: list[dict[str, Any]], length_mm: float, tolerance_mm: float, mode: str
) -> None:
    if length_mm <= tolerance_mm:
        if segments:
            raise ContractError("zero-length connection cannot own a finite field segment")
        return
    if not segments:
        raise ContractError("field responsibility leaves the connection undefined")
    cursor = 0.0
    for segment in segments:
        start = segment["start_mm"]
        end = segment["end_mm"]
        if end <= start:
            raise ContractError("field ownership segment must have positive length")
        if abs(start - cursor) > tolerance_mm:
            relation = "overlap" if start < cursor else "gap"
            raise ContractError(f"field responsibility has a {relation}")
        cursor = end
    if abs(cursor - length_mm) > tolerance_mm:
        raise ContractError("field responsibility does not cover connector length")
    if mode in {"field_overlap", "monolithic_joint_solve"} and not any(
        segment["owner"] == "integration" for segment in segments
    ):
        raise ContractError(f"{mode} requires integration-owned field region")


def _resolve_profile(
    profile: dict[str, Any],
    upstream_port: dict[str, Any],
    downstream_port: dict[str, Any],
    upstream_path: Path,
    downstream_path: Path,
    source_root: Path,
    *, artifact_root: str | Path | None = None,
) -> dict[str, Any]:
    validate_schema(upstream_port, "component_port.schema.json")
    validate_schema(downstream_port, "component_port.schema.json")
    upstream_authority_hash, upstream_authority_path = _validate_port_authority(
        upstream_port, upstream_path, source_root, artifact_root=artifact_root
    )
    downstream_authority_hash, downstream_authority_path = _validate_port_authority(
        downstream_port, downstream_path, source_root, artifact_root=artifact_root
    )
    upstream_port_source = _managed_file(source_root, upstream_path, artifact_root=artifact_root)
    downstream_port_source = _managed_file(source_root, downstream_path, artifact_root=artifact_root)

    upstream_ref = profile["upstream"]
    downstream_ref = profile["downstream"]
    for port, reference, direction, label in (
        (upstream_port, upstream_ref, "provided", "upstream"),
        (downstream_port, downstream_ref, "required", "downstream"),
    ):
        if port["direction"] != direction:
            raise ContractError(f"{label} port direction must be {direction}")
        if (
            port["project_id"] != reference["project_id"]
            or port["port_id"] != reference["port_id"]
        ):
            raise ContractError(f"{label} port identity differs from explicit selection")

    if upstream_port["state_contract"] != downstream_port["state_contract"]:
        raise ContractError("component particle-state contracts are incompatible")
    if (
        upstream_port["coordinate_frame"]["length_unit"]
        != downstream_port["coordinate_frame"]["length_unit"]
    ):
        raise ContractError("component port length units are incompatible")
    if upstream_port["clock"]["time_unit"] != downstream_port["clock"]["time_unit"]:
        raise ContractError("component port time units are incompatible")

    registration = profile["spatial_registration"]
    rotation = registration["rotation_upstream_to_downstream"]
    position_tolerance = registration["position_tolerance_mm"]
    angular_tolerance = registration["angular_tolerance_rad"]
    _validate_rotation(rotation, angular_tolerance)

    upstream_surface = upstream_port["mating_surface"]
    downstream_surface = downstream_port["mating_surface"]
    upstream_normal = upstream_surface["outward_normal"]
    downstream_normal = downstream_surface["outward_normal"]
    if abs(_norm(upstream_normal) - 1.0) > angular_tolerance:
        raise ContractError("upstream port normal is not a unit vector")
    if abs(_norm(downstream_normal) - 1.0) > angular_tolerance:
        raise ContractError("downstream port normal is not a unit vector")

    transformed_center = _matrix_vector(rotation, upstream_surface["center_mm"])
    transformed_center = [
        value + offset
        for value, offset in zip(
            transformed_center, registration["translation_mm"], strict=True
        )
    ]
    transformed_normal = _matrix_vector(rotation, upstream_normal)
    if _dot(transformed_normal, downstream_normal) > -math.cos(angular_tolerance):
        raise ContractError("mating surface normals are not opposed")

    separation = _subtract(downstream_surface["center_mm"], transformed_center)
    measured_gap = _dot(separation, transformed_normal)
    transverse = _subtract(
        separation, [measured_gap * component for component in transformed_normal]
    )
    if measured_gap < -position_tolerance:
        raise ContractError("downstream mating surface lies behind upstream port")
    if abs(measured_gap - registration["expected_gap_mm"]) > position_tolerance:
        raise ContractError("mating surface gap differs from connection profile")
    if _norm(transverse) > position_tolerance:
        raise ContractError("mating surface centers have transverse misalignment")
    if (
        abs(profile["connector"]["length_mm"] - measured_gap)
        > position_tolerance
    ):
        raise ContractError("connector length differs from mating surface gap")
    direct_mating = (
        registration["expected_gap_mm"] == 0.0
        and profile["connector"]["length_mm"] == 0.0
    )
    actual_gap = 0.0 if direct_mating else measured_gap

    transition_aperture = profile["transition_aperture"]
    transition_clear_radius = _validate_transition_aperture(
        transition_aperture,
        downstream_normal,
        angular_tolerance,
    )
    effective_radius = min(
        upstream_surface["aperture_radius_mm"],
        downstream_surface["aperture_radius_mm"],
        transition_clear_radius,
    )
    if effective_radius + position_tolerance < profile["minimum_clear_radius_mm"]:
        raise ContractError("connection aperture is below the required clear radius")

    potential = profile["potential_alignment"]
    actual_step = downstream_surface["potential_V"] - upstream_surface["potential_V"]
    if potential["mode"] == "continuous":
        if abs(actual_step) > potential["tolerance_V"]:
            raise ContractError("undeclared potential step between component ports")
    elif abs(actual_step - potential["declared_step_V"]) > potential["tolerance_V"]:
        raise ContractError("actual potential step differs from declared step")

    clock = profile["clock_alignment"]
    same_origin = upstream_port["clock"]["origin_id"] == downstream_port["clock"]["origin_id"]
    if clock["mode"] == "same_origin":
        if not same_origin or abs(clock["offset_s"]) > 0:
            raise ContractError("same_origin clock alignment is inconsistent")
    elif same_origin and abs(clock["offset_s"]) > 0:
        raise ContractError("declared clock offset conflicts with identical origins")

    _validate_field_ownership(
        profile["field_ownership_segments"],
        profile["connector"]["length_mm"],
        position_tolerance,
        profile["coupling_mode"],
    )
    segments = profile["field_ownership_segments"]
    if segments:
        if (
            upstream_port["field_boundary"]["field_reaches_surface"]
            and segments[0]["owner"] not in {"upstream", "integration"}
        ):
            raise ContractError("upstream field responsibility is missing at its port")
        if (
            downstream_port["field_boundary"]["field_reaches_surface"]
            and segments[-1]["owner"] not in {"downstream", "integration"}
        ):
            raise ContractError("downstream field responsibility is missing at its port")

    resolved = {
        "schema_version": 1,
        "role": "resolved_connection_do_not_edit",
        "integration_id": profile["integration_id"],
        "selection": {
            "upstream_project_id": upstream_ref["project_id"],
            "upstream_port_id": upstream_ref["port_id"],
            "downstream_project_id": downstream_ref["project_id"],
            "downstream_port_id": downstream_ref["port_id"],
            "connection_profile_id": profile["connection_profile_id"],
        },
        "sources": {
            "profile_sha256": _canonical_sha256(profile),
            "upstream_port": {
                "path": upstream_port_source.portable_path,
                "sha256": _managed_sha256(upstream_port_source),
            },
            "downstream_port": {
                "path": downstream_port_source.portable_path,
                "sha256": _managed_sha256(downstream_port_source),
            },
            "upstream_authority": {
                "path": upstream_authority_path,
                "sha256": upstream_authority_hash,
            },
            "downstream_authority": {
                "path": downstream_authority_path,
                "sha256": downstream_authority_hash,
            },
        },
        "coupling_mode": profile["coupling_mode"],
        "spatial_registration": {
            **copy.deepcopy(registration),
            "actual_gap_mm": actual_gap,
            "transformed_upstream_normal": transformed_normal,
        },
        "connector": copy.deepcopy(profile["connector"]),
        "port_geometry": {
            "upstream": {
                "coordinate_frame": copy.deepcopy(upstream_port["coordinate_frame"]),
                "mating_surface": copy.deepcopy(upstream_surface),
                "clock": copy.deepcopy(upstream_port["clock"]),
            },
            "downstream": {
                "coordinate_frame": copy.deepcopy(downstream_port["coordinate_frame"]),
                "mating_surface": copy.deepcopy(downstream_surface),
                "clock": copy.deepcopy(downstream_port["clock"]),
            },
        },
        "transition_aperture": {
            "shape": transition_aperture["shape"],
            "coordinate_frame_id": downstream_port["coordinate_frame"]["frame_id"],
            "center_mm": copy.deepcopy(downstream_surface["center_mm"]),
            "surface_normal": copy.deepcopy(downstream_normal),
            "full_width_mm": transition_aperture["full_width_mm"],
            "full_height_mm": transition_aperture["full_height_mm"],
            "width_axis": copy.deepcopy(
                transition_aperture["width_axis_downstream_frame"]
            ),
            "height_axis": copy.deepcopy(
                transition_aperture["height_axis_downstream_frame"]
            ),
        },
        "effective_clear_radius_mm": effective_radius,
        "potential_alignment": {
            **copy.deepcopy(potential),
            "actual_step_V": actual_step,
        },
        "clock_alignment": copy.deepcopy(clock),
        "field_ownership_segments": copy.deepcopy(profile["field_ownership_segments"]),
        "compatibility": {
            "status": "pass",
            "checks": [
                "explicit_selection",
                "state_contract",
                "coordinate_units",
                "mating_normals",
                "surface_gap",
                "transition_aperture_geometry",
                "clear_aperture",
                "potential_alignment",
                "clock_alignment",
                "field_responsibility",
            ],
        },
    }
    validate_schema(resolved, "resolved_connection.schema.json")
    return resolved


def resolve_connection_profile(
    registry: dict[str, Any], profile_id: str, source_root: str | Path, *, artifact_root: str | Path | None = None
) -> dict[str, Any]:
    """Resolve one explicitly selected profile and both referenced component ports."""
    validate_schema(registry, "connection_profile_registry.schema.json")
    matches = [
        profile
        for profile in registry["profiles"]
        if profile["connection_profile_id"] == profile_id
    ]
    if len(matches) != 1:
        raise ContractError(
            f"connection_profile_id must resolve exactly once: {profile_id}"
        )
    profile = matches[0]
    if profile["integration_id"] != registry["integration_id"]:
        raise ContractError("connection profile integration_id differs from registry")
    if "port_contract" not in profile["upstream"]:
        raise ContractError(
            "upstream port binding is unresolved: "
            f"{profile['upstream']['port_binding']}"
        )
    root = Path(source_root)
    upstream_path = _managed_file(root, profile["upstream"]["port_contract"], artifact_root=artifact_root).path
    downstream_path = _managed_file(root, profile["downstream"]["port_contract"], artifact_root=artifact_root).path
    return _resolve_profile(
        profile,
        load_json(upstream_path),
        load_json(downstream_path),
        upstream_path,
        downstream_path,
        root, artifact_root=artifact_root,
    )


def build_composition_plan(
    resolved: dict[str, Any], resolved_path: str | Path
) -> dict[str, Any]:
    validate_schema(resolved, "resolved_connection.schema.json")
    path = Path(resolved_path)
    plan = {
        "schema_version": 1,
        "role": "integration_composition_plan_do_not_edit",
        "integration_id": resolved["integration_id"],
        "selection": copy.deepcopy(resolved["selection"]),
        "resolved_connection": {"path": str(path), "sha256": sha256(path)},
        "coupling_mode": resolved["coupling_mode"],
        "execution_steps": [],
    }
    validate_schema(plan, "composition_plan.schema.json")
    return plan


def write_resolved_and_plan(
    registry_path: str | Path,
    profile_id: str,
    resolved_output: str | Path,
    plan_output: str | Path,
    source_root: str | Path,
    *, artifact_root: str | Path | None = None,
) -> tuple[Path, Path]:
    root = Path(source_root).resolve()
    registry_source = _managed_file(root, registry_path, artifact_root=artifact_root)
    registry_file = registry_source.path
    registry = load_connection_profile_registry(registry_file)
    resolved = resolve_connection_profile(registry, profile_id, source_root=root, artifact_root=artifact_root)
    resolved["sources"]["profile_registry"] = {
        "path": registry_source.portable_path,
        "sha256": _managed_sha256(registry_source),
    }
    validate_schema(resolved, "resolved_connection.schema.json")
    resolved_path = Path(resolved_output)
    plan_path = Path(plan_output)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    plan = build_composition_plan(resolved, resolved_path)
    plan_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return resolved_path, plan_path


def resolve_assembly_recipe(
    recipe_path: str | Path, components_path: str | Path, source_root: str | Path,
    *, local_scope_path: str | Path | None = None, artifact_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load explicit recipe/provider files and bind their content identities."""
    from msplatform.assembly.resolve_assembly import compile_assembly_layout, validate_composition_plan_contract

    root = Path(source_root).resolve()
    sources = {name: _managed_file(root, path, artifact_root=artifact_root) for name, path in (
        ("recipe", recipe_path), ("components", components_path),
    )}
    if local_scope_path is not None:
        sources["local_scope"] = _managed_file(root, local_scope_path, artifact_root=artifact_root)
    plan = compile_assembly_layout(
        load_json(sources["recipe"].path), load_json(sources["components"].path),
        local_scope=load_json(sources["local_scope"].path) if "local_scope" in sources else None,
    )
    plan["input_files"] = {
        name: {"path": source.portable_path, "sha256": _managed_sha256(source)}
        for name, source in sources.items()
    }
    validate_composition_plan_contract(plan)
    return plan


def _verify_assembly_plan(plan: dict[str, Any], source_root: str | Path | None, *, artifact_root: str | Path | None = None) -> None:
    """Rebuild the layout from frozen inputs and, when present, recheck files."""
    from msplatform.assembly.resolve_assembly import compile_assembly_layout

    expected = compile_assembly_layout(
        plan["recipe"], plan["components"], local_scope=plan.get("local_scope"),
    )
    if "input_files" in plan:
        for name, record in plan["input_files"].items():
            source = _managed_file(source_root, record["path"], artifact_root=artifact_root)
            if _managed_sha256(source) != record["sha256"] or load_json(source.path) != plan[name]:
                raise ContractError(f"assembly {name} source identity is stale")
        expected["input_files"] = plan["input_files"]
    if plan != expected:
        raise ContractError("assembly plan differs from its frozen direct inputs")

def verify_composition_plan(
    plan_path: str | Path,
    resolved_path: str | Path | None = None,
    source_root: str | Path | None = None,
    *, artifact_root: str | Path | None = None,
) -> None:
    from msplatform.assembly.resolve_assembly import validate_composition_plan_contract

    plan = load_json(Path(plan_path))
    validate_composition_plan_contract(plan)
    if plan["schema_version"] in (3, 4, 5):
        _verify_assembly_plan(plan, source_root, artifact_root=artifact_root)
        return
    if resolved_path is None:
        raise ContractError("pair composition plan verification requires resolved_path")
    resolved_file = Path(resolved_path)
    resolved = load_json(resolved_file)
    validate_schema(resolved, "resolved_connection.schema.json")
    if plan["resolved_connection"]["sha256"] != sha256(resolved_file):
        raise ContractError("composition plan resolved_connection SHA-256 is stale")
    if (
        plan["integration_id"] != resolved["integration_id"]
        or plan["selection"] != resolved["selection"]
        or plan["coupling_mode"] != resolved["coupling_mode"]
    ):
        raise ContractError("composition plan identity differs from resolved connection")
    root = source_root
    for source_name in (
        "profile_registry",
        "upstream_port",
        "downstream_port",
        "upstream_authority",
        "downstream_authority",
    ):
        source = resolved["sources"].get(source_name)
        if source is None:
            continue
        source_file = _managed_file(root, source["path"], artifact_root=artifact_root)
        if source["sha256"] != _managed_sha256(source_file):
            raise ContractError(f"resolved connection source SHA-256 is stale: {source_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--components", type=Path)
    parser.add_argument("--local-scope", type=Path)
    parser.add_argument("--profile-id")
    parser.add_argument("--resolved-output", type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--verify-plan", type=Path)
    parser.add_argument("--resolved", type=Path)
    args = parser.parse_args()
    if args.recipe is not None:
        if args.plan_output is None or args.components is None or any(
            value is not None for value in (
                args.registry, args.profile_id, args.resolved_output,
                args.verify_plan, args.resolved,
            )
        ):
            parser.error("--recipe requires --components and --plan-output and excludes pair/verification inputs")
        if args.source_root is None:
            parser.error("resolution requires an explicit --source-root")
        plan = resolve_assembly_recipe(
            args.recipe, args.components, args.source_root, local_scope_path=args.local_scope, artifact_root=args.artifact_root,
        )
        args.plan_output.parent.mkdir(parents=True, exist_ok=True)
        args.plan_output.write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n",
        )
        print(f"ASSEMBLY_LAYOUT=PASS PLAN={args.plan_output}")
        return
    if args.local_scope is not None:
        parser.error("--local-scope requires --recipe")
    if args.verify_plan is not None:
        verify_composition_plan(
            args.verify_plan, args.resolved, source_root=args.source_root, artifact_root=args.artifact_root
        )
        print("COMPOSITION_PLAN=PASS")
        return
    required = (
        args.registry,
        args.profile_id,
        args.resolved_output,
        args.plan_output,
    )
    if any(value is None for value in required):
        parser.error(
            "resolution requires --registry, --profile-id, --resolved-output and --plan-output"
        )
    if args.source_root is None:
        parser.error("resolution requires an explicit --source-root")
    resolved_path, plan_path = write_resolved_and_plan(
        args.registry,
        args.profile_id,
        args.resolved_output,
        args.plan_output,
        source_root=args.source_root, artifact_root=args.artifact_root,
    )
    print(f"CONNECTION_RESOLUTION=PASS RESOLVED={resolved_path} PLAN={plan_path}")


if __name__ == "__main__":
    main()
