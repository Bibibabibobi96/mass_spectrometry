"""Resolve explicit component ports and a connection profile into frozen contracts."""

from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import (
    ContractError,
    REPO_ROOT,
    load_json,
    sha256,
    validate_schema,
)
from common.contracts.file_identity import (
    canonical_json_sha256 as _canonical_sha256,
    file_sha256,
    repository_text_sha256,
)


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _norm(vector: list[float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _subtract(left: list[float], right: list[float]) -> list[float]:
    return [a - b for a, b in zip(left, right, strict=True)]


def _matrix_vector(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [_dot(row, vector) for row in matrix]


def derive_direct_mating_translation(
    rotation_upstream_to_downstream: list[list[float]],
    upstream_center_mm: list[float],
    downstream_center_mm: list[float],
) -> list[float]:
    """Return the rigid translation that makes two port centers coincide."""
    if (
        len(rotation_upstream_to_downstream) != 3
        or any(len(row) != 3 for row in rotation_upstream_to_downstream)
        or len(upstream_center_mm) != 3
        or len(downstream_center_mm) != 3
    ):
        raise ContractError("direct-mating translation requires 3D rotation and centers")
    values = [
        float(value)
        for row in rotation_upstream_to_downstream
        for value in row
    ] + [float(value) for value in upstream_center_mm + downstream_center_mm]
    if not all(math.isfinite(value) for value in values):
        raise ContractError("direct-mating translation inputs must be finite")
    transformed = _matrix_vector(
        rotation_upstream_to_downstream, list(map(float, upstream_center_mm))
    )
    return _subtract(list(map(float, downstream_center_mm)), transformed)


def derive_mating_translation_with_gap(
    rotation_upstream_to_downstream: list[list[float]],
    upstream_center_mm: list[float],
    upstream_outward_normal: list[float],
    downstream_center_mm: list[float],
    gap_mm: float,
) -> list[float]:
    """Return a rigid translation with a nonnegative normal gap in millimetres."""
    direct_translation = derive_direct_mating_translation(
        rotation_upstream_to_downstream,
        upstream_center_mm,
        downstream_center_mm,
    )
    if len(upstream_outward_normal) != 3:
        raise ContractError("gap-mating translation requires a 3D upstream normal")
    normal = list(map(float, upstream_outward_normal))
    gap = float(gap_mm)
    if not all(math.isfinite(value) for value in [*normal, gap]):
        raise ContractError("gap-mating translation inputs must be finite")
    if gap < 0.0:
        raise ContractError("gap-mating translation gap must be nonnegative")
    if not math.isclose(_norm(normal), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ContractError("gap-mating translation upstream normal must be a unit vector")
    _validate_rotation(rotation_upstream_to_downstream, 1e-12)
    transformed_normal = _matrix_vector(rotation_upstream_to_downstream, normal)
    return [
        value - gap * component
        for value, component in zip(
            direct_translation, transformed_normal, strict=True
        )
    ]


def _determinant(matrix: list[list[float]]) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


@dataclass(frozen=True)
class _ManagedFile:
    path: Path
    portable_path: str
    repository_text: bool


def _managed_file(repo_root: Path, reference: str | Path) -> _ManagedFile:
    """Resolve one explicit repository or workspace artifact file reference."""
    root = repo_root.resolve()
    workspace_root = root.parent
    artifacts_root = (workspace_root / "artifacts" / "projects").resolve()
    raw = Path(reference)
    if ".." in raw.parts:
        raise ContractError(f"connection source contains parent traversal: {reference}")

    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        normalized = raw.as_posix()
        base = workspace_root if normalized.startswith("artifacts/projects/") else root
        candidate = (base / raw).resolve()

    try:
        relative_repo = candidate.relative_to(root)
    except ValueError:
        relative_repo = None
    if relative_repo is not None:
        managed = _ManagedFile(
            path=candidate,
            portable_path=relative_repo.as_posix(),
            repository_text=True,
        )
    else:
        try:
            candidate.relative_to(artifacts_root)
        except ValueError as exc:
            raise ContractError(
                f"connection source is outside repository and artifacts/projects: {reference}"
            ) from exc
        managed = _ManagedFile(
            path=candidate,
            portable_path=candidate.relative_to(workspace_root).as_posix(),
            repository_text=False,
        )
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
    port: dict[str, Any], port_path: Path, repo_root: Path
) -> tuple[str, str]:
    authority = port["authority"]
    source = _managed_file(repo_root, authority["source_contract"])
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
        validate_schema(profile, "connection_profile.schema.json")
        if profile["integration_id"] != integration_id:
            raise ContractError(
                f"profile {profile['connection_profile_id']}: integration_id differs from registry"
            )
        profile_id = profile["connection_profile_id"]
        if profile_id in seen:
            raise ContractError(f"duplicate connection_profile_id: {profile_id}")
        seen.add(profile_id)
    return registry


def _validate_rotation(matrix: list[list[float]], tolerance: float) -> None:
    for row in matrix:
        if abs(_norm(row) - 1.0) > tolerance:
            raise ContractError("spatial registration rotation is not orthonormal")
    for left in range(3):
        for right in range(left + 1, 3):
            if abs(_dot(matrix[left], matrix[right])) > tolerance:
                raise ContractError("spatial registration rotation is not orthonormal")
    if abs(_determinant(matrix) - 1.0) > tolerance:
        raise ContractError("spatial registration rotation must be right-handed")


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
    repo_root: Path,
) -> dict[str, Any]:
    validate_schema(profile, "connection_profile.schema.json")
    validate_schema(upstream_port, "component_port.schema.json")
    validate_schema(downstream_port, "component_port.schema.json")
    upstream_authority_hash, upstream_authority_path = _validate_port_authority(
        upstream_port, upstream_path, repo_root
    )
    downstream_authority_hash, downstream_authority_path = _validate_port_authority(
        downstream_port, downstream_path, repo_root
    )
    upstream_port_source = _managed_file(repo_root, upstream_path)
    downstream_port_source = _managed_file(repo_root, downstream_path)

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
    registry: dict[str, Any], profile_id: str, repo_root: str | Path = REPO_ROOT
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
    validate_schema(profile, "connection_profile.schema.json")
    if profile["integration_id"] != registry["integration_id"]:
        raise ContractError("connection profile integration_id differs from registry")
    if "port_contract" not in profile["upstream"]:
        raise ContractError(
            "upstream port binding is unresolved: "
            f"{profile['upstream']['port_binding']}"
        )
    root = Path(repo_root)
    upstream_path = _managed_file(root, profile["upstream"]["port_contract"]).path
    downstream_path = _managed_file(root, profile["downstream"]["port_contract"]).path
    return _resolve_profile(
        profile,
        load_json(upstream_path),
        load_json(downstream_path),
        upstream_path,
        downstream_path,
        root,
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
    repo_root: str | Path = REPO_ROOT,
) -> tuple[Path, Path]:
    root = Path(repo_root).resolve()
    registry_source = _managed_file(root, registry_path)
    registry_file = registry_source.path
    registry = load_connection_profile_registry(registry_file)
    resolved = resolve_connection_profile(registry, profile_id, repo_root=root)
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


def verify_composition_plan(
    plan_path: str | Path,
    resolved_path: str | Path,
    repo_root: str | Path = REPO_ROOT,
) -> None:
    plan = load_json(Path(plan_path))
    resolved_file = Path(resolved_path)
    resolved = load_json(resolved_file)
    validate_schema(plan, "composition_plan.schema.json")
    validate_schema(resolved, "resolved_connection.schema.json")
    if plan["resolved_connection"]["sha256"] != sha256(resolved_file):
        raise ContractError("composition plan resolved_connection SHA-256 is stale")
    if (
        plan["integration_id"] != resolved["integration_id"]
        or plan["selection"] != resolved["selection"]
        or plan["coupling_mode"] != resolved["coupling_mode"]
    ):
        raise ContractError("composition plan identity differs from resolved connection")
    root = Path(repo_root)
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
        source_file = _managed_file(root, source["path"])
        if source["sha256"] != _managed_sha256(source_file):
            raise ContractError(f"resolved connection source SHA-256 is stale: {source_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--profile-id")
    parser.add_argument("--resolved-output", type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--verify-plan", type=Path)
    parser.add_argument("--resolved", type=Path)
    parser.add_argument("--verify-repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    if args.verify_plan is not None:
        if args.resolved is None:
            parser.error("--verify-plan requires --resolved")
        verify_composition_plan(
            args.verify_plan, args.resolved, repo_root=args.verify_repo_root
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
    resolved_path, plan_path = write_resolved_and_plan(
        args.registry,
        args.profile_id,
        args.resolved_output,
        args.plan_output,
        repo_root=args.repo_root,
    )
    print(f"CONNECTION_RESOLUTION=PASS RESOLVED={resolved_path} PLAN={plan_path}")


if __name__ == "__main__":
    main()
