"""Exact manifest file records and verification, independent of tools and workflow policy."""
from __future__ import annotations
import copy
from collections.abc import Mapping
import hashlib
import re
import json
import os
from pathlib import Path
from typing import Any
from msplatform.io.file_identity import file_sha256
from msplatform.io.file_identity import file_sha256_unbuffered

# Original closed solver-native payload I/O tier, not a scientific threshold.
_UNBUFFERED_SOLVER_PAYLOAD_BYTES = 8 * 1024 * 1024


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def file_record(
    path: Path,
    retention_role: str | None = None,
    *,
    recorded_path: Path | None = None,
    document: dict[str, Any] | None = None,
    retention_classifier: Any = None,
    _identity_cache: dict[tuple[Any, ...], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """Record exact bytes with the shared read policy for closed payloads.

    Large Windows solver-native files use the existing unbuffered reader;
    producers must already have stopped writing. Read failures never retry or
    fall back to another view. Virtual documents retain their exact JSON hash.
    The optional private cache belongs to one closed-payload build/verify call;
    default calls always read fresh bytes and never retain record metadata.
    """
    payload = _json_bytes(document) if document is not None else None
    exists = payload is not None or path.is_file()
    record: dict[str, Any] = {"path": str(recorded_path or path), "exists": exists}
    if payload is not None:
        record.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest().upper())
    elif path.is_file():
        metadata = path.stat()
        size = metadata.st_size
        large_windows_file = os.name == "nt" and size >= _UNBUFFERED_SOLVER_PAYLOAD_BYTES
        read_role = retention_role
        if large_windows_file and read_role is None:
            if retention_classifier is None:
                raise ValueError("large unclassified record requires an explicit retention classifier")
            read_role = retention_classifier(path, bytes_count=size)
        hash_file = file_sha256_unbuffered if (
            large_windows_file and read_role == "solver_native_binary"
        ) else file_sha256
        key = (path.resolve(), hash_file, size, metadata.st_mtime_ns) if _identity_cache is not None else None
        identity = _identity_cache.get(key) if _identity_cache is not None else None
        if identity is None:
            identity = (size, hash_file(path))
            if _identity_cache is not None:
                _identity_cache[key] = identity
        record.update(bytes=identity[0], sha256=identity[1])
    if retention_role is not None:
        record["retention_role"] = retention_role
    return record


def record_path(record: dict, *, base_dir: Path | None = None) -> Path:
    """Resolve an absolute record or a historical run-relative record."""

    path = Path(record["path"])
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def verify_record(
    name: str, record: dict, *, base_dir: Path | None = None,
    retention_classifier: Any = None,
    _identity_cache: dict[tuple[Any, ...], tuple[int, str]] | None = None,
) -> None:
    path = record_path(record, base_dir=base_dir)
    if not path.is_file():
        raise AssertionError(f"manifest {name} is missing: {path}")
    if path.stat().st_size != record.get("bytes"):
        raise AssertionError(f"manifest {name} byte count changed: {path}")
    actual = file_record(path, record.get("retention_role"), retention_classifier=retention_classifier, _identity_cache=_identity_cache)
    if actual["bytes"] != record.get("bytes"):
        raise AssertionError(f"manifest {name} byte count changed: {path}")
    if actual["sha256"] != str(record.get("sha256", "")).upper():
        raise AssertionError(f"manifest {name} SHA-256 changed: {path}")


TERMINAL_JOURNAL_NAME = ".run_terminal_publication.json"


def require_completed_terminal_publication(manifest_path: Path) -> None:
    """Reject a manifest while its sibling journal still owns completion."""

    if (manifest_path.resolve().parent / TERMINAL_JOURNAL_NAME).is_file():
        raise ValueError("run terminal publication is incomplete; replay its journal")


def validate_file_record(value: Any, label: str) -> dict[str, Any]:
    if (not isinstance(value, Mapping) or value.get("exists") is not True
            or not isinstance(value.get("path"), str) or not value["path"]
            or type(value.get("bytes")) is not int or value["bytes"] < 0
            or not re.fullmatch(r"[0-9a-fA-F]{64}", str(value.get("sha256", "")))):
        raise ValueError(f"{label} requires a complete existing file record")
    return copy.deepcopy(dict(value))
