"""Read one published product without restoring its execution environment.

The existing run manifest owns product metadata and file records. This reader
checks only the requested data closure; it never replays a journal or workflow.
Backend consumers still validate the product's scientific applicability.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from msplatform.execution.manifest_records import record_path, verify_record
from msplatform.execution.terminal_publication import require_completed_terminal_publication


ArtifactResolver = Callable[[Mapping[str, Any], Path | None], Path]
ARTIFACT_KINDS = frozenset({"cad_geometry", "geometry_artifact", "prepared_model", "field_bundle", "trajectory_result"})


def _record(value: Any, label: str) -> dict[str, Any]:
    if (not isinstance(value, Mapping) or value.get("exists") is not True
            or not isinstance(value.get("path"), str) or not value["path"]
            or type(value.get("bytes")) is not int or value["bytes"] < 0
            or not re.fullmatch(r"[0-9a-fA-F]{64}", str(value.get("sha256", "")))):
        raise ValueError(f"{label} requires a complete existing file record")
    return copy.deepcopy(dict(value))


def _verified_path(record: dict[str, Any], *, label: str, base: Path | None,
                   resolver: ArtifactResolver | None) -> Path:
    if resolver is not None:
        path = Path(resolver(copy.deepcopy(record), base))
        if not path.is_absolute():
            raise ValueError("artifact resolver must return an explicit absolute path")
    else:
        if base is None and not Path(record["path"]).is_absolute():
            raise ValueError("artifact manifest reference must be absolute or have an explicit resolver")
        path = record_path(record, base_dir=base)
    verify_record(label, dict(record, path=str(path)))
    return path


@dataclass(frozen=True, init=False)
class OpenedArtifact:
    """An independent metadata snapshot and verified, read-only file locations."""

    kind: str
    product_id: str
    _reference: dict[str, Any]
    _metadata: dict[str, Any]
    _records: dict[str, dict[str, Any]]
    _paths: dict[str, Path]
    _producer: dict[str, Any]
    _manifest_location: Path

    def __init__(self, *, kind: str, product_id: str, reference: dict[str, Any],
                 metadata: dict[str, Any], records: dict[str, dict[str, Any]],
                 paths: dict[str, Path], producer: dict[str, Any], manifest_location: Path | None = None):
        location = Path(reference['manifest']['path']) if manifest_location is None else Path(manifest_location)
        if not location.is_absolute():
            raise ValueError('opened artifact requires an explicit absolute manifest location')
        for name, value in (("kind", kind), ("product_id", product_id), ("_reference", reference),
                            ("_metadata", metadata), ("_records", records), ("_paths", paths),
                            ("_producer", producer)):
            object.__setattr__(self, name, copy.deepcopy(value))
        object.__setattr__(self, '_manifest_location', location)

    @property
    def reference(self) -> dict[str, Any]:
        return copy.deepcopy(self._reference)

    @property
    def manifest_location(self) -> Path:
        """Location verified at open, preserving the original reference identity.

        Direct manual construction does not validate these bytes. This path
        snapshot is not a second manifest authority or a later integrity check.
        """
        return self._manifest_location

    @property
    def metadata(self) -> dict[str, Any]:
        return copy.deepcopy(self._metadata)

    @property
    def data_records(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._records)

    @property
    def data_locations(self) -> dict[str, Path]:
        """Return the locations verified when this product was opened.

        This independent snapshot preserves its explicit resolver. It does not
        recheck later bytes or replace an owner's immutable input protection;
        use data_path for another read, or guard these locations by their records.
        """
        return copy.deepcopy(self._paths)

    @property
    def producer(self) -> dict[str, Any]:
        return copy.deepcopy(self._producer)

    def data_path(self, name: str) -> Path:
        """Recheck the selected bytes before another consumer reads them."""
        if name not in self._records:
            raise ValueError(f"product has no declared data member: {name}")
        path = self._paths[name]
        verify_record(name, dict(self._records[name], path=str(path)))
        return path


def open_artifact(reference: Mapping[str, Any], *, expected_kind: str,
                  resolver: ArtifactResolver | None = None) -> OpenedArtifact:
    """Verify a manifest-bound complete product; no tools, writes, locks or replay.

    Products v1 are extra_fields in the existing manifest, not a separate index:
    {schema_version, kind, status: 'complete', metadata, data: {name: file_record}}.
    Every selected data record must also be one of that manifest's input/output
    records. Missing unrelated execution code does not invalidate readable data.
    """
    if expected_kind not in ARTIFACT_KINDS:
        raise ValueError(f"unsupported artifact kind: {expected_kind}")
    if not isinstance(reference, Mapping) or set(reference) != {"manifest", "product_id"}:
        raise ValueError("artifact reference requires manifest record and product_id")
    product_id = reference["product_id"]
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("artifact product_id must be explicit")
    manifest_record = _record(reference["manifest"], "manifest")
    manifest_path = _verified_path(manifest_record, label="manifest", base=None, resolver=resolver)
    require_completed_terminal_publication(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] not in (1, 2) or manifest.get("role") != "simulation_run_manifest"
            or manifest.get("status") not in {"success", "failed", "interrupted", "superseded"}
            or manifest.get("lifecycle_state") == "provisional"):
        raise ValueError("artifact requires an explicitly published terminal run manifest")
    products = manifest.get("products")
    product = products.get(product_id) if isinstance(products, dict) else None
    if (not isinstance(product, dict) or type(product.get("schema_version")) is not int
            or product["schema_version"] != 1 or product.get("kind") != expected_kind
            or product.get("status") != "complete" or not isinstance(product.get("metadata"), dict)
            or not isinstance(product.get("data"), dict) or not product["data"]):
        raise ValueError("artifact product is missing, incomplete, unknown-version or the wrong kind")
    inputs, outputs = manifest.get("inputs"), manifest.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        raise ValueError("artifact manifest input/output records are invalid")
    bound = [*inputs.values(), *outputs]
    records, paths = {}, {}
    for name, value in product["data"].items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("artifact data member names must be explicit")
        record = _record(value, name)
        if record not in bound:
            raise ValueError(f"artifact data member is not bound by the run manifest: {name}")
        records[name] = record
        paths[name] = _verified_path(record, label=name, base=manifest_path.parent, resolver=resolver)
    producer = {name: copy.deepcopy(manifest.get(name)) for name in ("run_id", "project", "mode", "status")}
    return OpenedArtifact(kind=expected_kind, product_id=product_id,
        reference=dict(reference), metadata=product["metadata"], records=records, paths=paths, producer=producer,
        manifest_location=manifest_path)
