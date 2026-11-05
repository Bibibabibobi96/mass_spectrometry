"""Narrow native result data; only the existing execution owner publishes these."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class CompiledPreparedModel:
    """Pure unsolved-model snapshot; each public view is an independent copy.

    This is not a published artifact or permission to execute a solver. The
    canonical serialized document contains no live source/particle/runtime state.
    """

    _document_json: str

    @property
    def document(self) -> dict[str, Any]:
        return json.loads(self._document_json)


@dataclass(frozen=True)
class GeometryArtifact:
    compiled_input_record: dict[str, Any]
    gem_records: tuple[dict[str, Any], ...]
    raw_geometry_records: tuple[dict[str, Any], ...]
    instance_rows: tuple[dict[str, Any], ...]
    iob_record: dict[str, Any]
    reopen_record: dict[str, Any]
    owner_manifest_record: dict[str, Any]


@dataclass(frozen=True)
class FieldBundle:
    geometry_artifact_record: dict[str, Any]
    drive_identity: dict[str, Any]
    frontend_members: tuple[dict[str, Any], ...]
    downstream_assets: tuple[dict[str, Any], ...]
    owner_manifest_record: dict[str, Any]


@dataclass(frozen=True)
class PreparedModelArtifact:
    """Manifest-bound unsolved model; never interchangeable with a FieldBundle."""

    model_record: dict[str, Any]
    geometry_records: tuple[dict[str, Any], ...]
    native_configuration_record: dict[str, Any]
    iob_record: dict[str, Any]
    readback_record: dict[str, Any]
    owner_manifest_record: dict[str, Any]


@dataclass(frozen=True)
class NativeStagePlan:
    """Materialization declarations and ordered commands, never an execution receipt."""

    materializations: dict[str, str]
    input_copies: tuple[dict[str, Any], ...]
    operations: tuple[dict[str, Any], ...]
    declared_outputs: tuple[str, ...]
