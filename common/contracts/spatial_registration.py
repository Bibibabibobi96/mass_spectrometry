"""Resolve authoritative, solver-independent spatial-registration releases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.rigid_transform import (
    PlaneSurface,
    RigidTransform,
    relative_transform,
)

SCHEMA_VERSION = 1


def _source_record(path: Path, repository_root: Path) -> dict[str, str]:
    resolved = path.resolve()
    root = repository_root.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"spatial-registration source is outside repository: {path}") from error
    if not resolved.is_file():
        raise ValueError(f"spatial-registration source is missing: {relative}")
    return {"path": relative, "sha256": file_sha256(resolved)}


def resolve_spatial_registration(
    *,
    registration_id: str,
    instrument_frame_id: str,
    component_poses: Mapping[str, RigidTransform],
    source_component_id: str,
    target_component_id: str,
    surfaces: Mapping[str, PlaneSurface],
    source_files: Sequence[Path],
    repository_root: Path,
    scalar_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one resolved release with exactly one source-to-target transform."""
    if not registration_id.strip() or registration_id != registration_id.strip():
        raise ValueError("registration_id must be a nonempty trimmed string")
    if set(component_poses) != {source_component_id, target_component_id}:
        raise ValueError("component poses must contain exactly source and target")
    for component_id, pose in component_poses.items():
        if pose.from_frame_id != component_id:
            raise ValueError(f"component pose key/frame mismatch: {component_id}")
        if pose.to_frame_id != instrument_frame_id:
            raise ValueError("all component poses must target the instrument frame")
    if not surfaces:
        raise ValueError("at least one oriented surface is required")
    relative = relative_transform(
        component_poses[source_component_id],
        component_poses[target_component_id],
    )
    resolved_surfaces: dict[str, Any] = {}
    for surface_id, surface in sorted(surfaces.items()):
        matching = [
            pose for pose in component_poses.values()
            if pose.from_frame_id == surface.frame_id
        ]
        if surface.frame_id == instrument_frame_id:
            in_instrument = surface
        elif len(matching) == 1:
            in_instrument = matching[0].transform_plane(surface)
        else:
            raise ValueError(
                f"surface {surface_id} frame has no unique component pose"
            )
        resolved_surfaces[surface_id] = {
            "declared": surface.to_contract(),
            "in_instrument_frame": in_instrument.to_contract(),
        }
    source_records = [
        _source_record(path, repository_root)
        for path in sorted(source_files, key=lambda item: item.resolve().as_posix())
    ]
    if len({record["path"] for record in source_records}) != len(source_records):
        raise ValueError("spatial-registration source paths must be unique")
    source_by_resolved_path = {
        path.resolve(): record for path, record in zip(
            sorted(source_files, key=lambda item: item.resolve().as_posix()),
            source_records,
            strict=True,
        )
    }
    resolved_bindings: dict[str, Any] = {}
    for binding_id, binding in sorted((scalar_bindings or {}).items()):
        value = float(binding["value"])
        unit = binding["unit"]
        pointer = binding["json_pointer"]
        electrodes = binding["electrode_bindings"]
        source_path = Path(binding["source_file"]).resolve()
        if not math.isfinite(value):
            raise ValueError(f"scalar binding {binding_id} must be finite")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError(f"scalar binding {binding_id} requires a unit")
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError(f"scalar binding {binding_id} requires a JSON pointer")
        if (
            isinstance(electrodes, (str, bytes))
            or not electrodes
            or not all(isinstance(item, str) and item.strip() for item in electrodes)
        ):
            raise ValueError(
                f"scalar binding {binding_id} requires electrode bindings"
            )
        if source_path not in source_by_resolved_path:
            raise ValueError(
                f"scalar binding {binding_id} source is not a release source"
            )
        resolved_bindings[binding_id] = {
            "value": value,
            "unit": unit,
            "source": source_by_resolved_path[source_path],
            "json_pointer": pointer,
            "electrode_bindings": list(electrodes),
            "coordinate_transform_policy": "unchanged_no_unit_conversion",
        }
    release = {
        "schema_version": SCHEMA_VERSION,
        "role": "resolved_spatial_registration_do_not_edit",
        "registration_id": registration_id,
        "instrument_frame_id": instrument_frame_id,
        "sources": source_records,
        "component_poses": {
            component_id: component_poses[component_id].to_contract()
            for component_id in sorted(component_poses)
        },
        "derived_relative_transform": {
            "derivation": "source_pose.then(target_pose.inverse())",
            "source_component_id": source_component_id,
            "target_component_id": target_component_id,
            "transform": relative.to_contract(),
        },
        "resolved_surfaces": resolved_surfaces,
    }
    if resolved_bindings:
        release["authoritative_scalar_bindings"] = resolved_bindings
    return release


def serialized_release(release: Mapping[str, Any]) -> str:
    """Return the canonical repository serialization."""
    return json.dumps(release, indent=2, ensure_ascii=False) + "\n"


def write_or_check_release(
    output: Path,
    release: Mapping[str, Any],
    *,
    check: bool,
) -> None:
    """Write a release or fail when the checked output is missing or stale."""
    expected = serialized_release(release)
    current = output.read_text(encoding="utf-8") if output.is_file() else ""
    if current == expected:
        return
    if check:
        raise ValueError(f"spatial registration is stale or missing: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8", newline="\n")
