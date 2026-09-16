"""TTL artifact protection shared by cleanup and layout verification.

This module owns lease schema and path coverage; the capacity CLI owns commands.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CACHE_KEY = re.compile(r"\b[a-f0-9]{64}\b", re.IGNORECASE)
LEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PROTECTION_LEASE_DIRECTORY = Path("common") / "capacity_protection_leases"


class CapacityProtectionLeaseError(RuntimeError):
    """A protection lease is unreadable or cannot be trusted safely."""

    def __init__(self, path: Path, reason: str) -> None:
        self.audit = {
            "schema_version": 1,
            "role": "artifact_capacity_protection_lease_audit",
            "status": "invalid",
            "path": str(path),
            "reason": reason,
        }
        super().__init__(f"invalid artifact-capacity protection lease {path}: {reason}")


def parse_utc_timestamp(value: object) -> tuple[float, str] | None:
    """Parse a manifest UTC time without accepting an ambiguous local time."""

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    normalized = parsed.astimezone(timezone.utc)
    return normalized.timestamp(), normalized.isoformat().replace("+00:00", "Z")


def _validated_lease_id(value: object) -> str:
    if not isinstance(value, str) or LEASE_ID.fullmatch(value) is None:
        raise ValueError("lease_id must be a safe 1-128 character identifier")
    return value


def _lease_path(root: Path, lease_id: str) -> Path:
    return root / PROTECTION_LEASE_DIRECTORY / f"{_validated_lease_id(lease_id)}.json"


def _relative_protected_path(root: Path, value: Path) -> str:
    root_resolved = root.resolve()
    candidate = value if value.is_absolute() else root_resolved / value
    candidate = candidate.resolve(strict=False)
    try:
        relative = candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("protected path must remain below the artifact root") from exc
    if not relative.parts:
        raise ValueError("the artifact root itself cannot be protected by a lease")
    return relative.as_posix()


def create_capacity_protection_lease(
    root: Path, *, lease_id: str, owner: str, ttl_seconds: int,
    protected_cache_keys: Iterable[str] = (), protected_paths: Iterable[Path] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create one immutable TTL protection lease below ``artifacts/common``."""

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    lease_id = _validated_lease_id(lease_id)
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("lease owner must be nonempty")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise ValueError("lease TTL seconds must be a positive integer")
    keys = sorted({str(key).lower() for key in protected_cache_keys})
    if any(CACHE_KEY.fullmatch(key) is None for key in keys):
        raise ValueError("every protected cache key must be one SHA-256 key")
    paths = sorted({_relative_protected_path(root, Path(path)) for path in protected_paths})
    if not keys and not paths:
        raise ValueError("a protection lease must protect at least one cache key or path")
    created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires = datetime.fromtimestamp(created.timestamp() + ttl_seconds, timezone.utc)
    document = {
        "schema_version": 1,
        "role": "artifact_capacity_protection_lease",
        "lease_id": lease_id,
        "owner": owner.strip(),
        "created_at_utc": created.isoformat().replace("+00:00", "Z"),
        "expires_at_utc": expires.isoformat().replace("+00:00", "Z"),
        "protected_cache_keys": keys,
        "protected_paths": paths,
    }
    path = _lease_path(root, lease_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise ValueError(f"protection lease already exists: {lease_id}") from exc
    return {**document, "path": str(path)}


def delete_capacity_protection_lease(root: Path, *, lease_id: str) -> dict[str, Any]:
    """Delete exactly one named protection lease; missing leases are a no-op."""

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    path = _lease_path(root, lease_id)
    try:
        path.unlink()
        deleted = True
    except FileNotFoundError:
        deleted = False
    return {
        "schema_version": 1,
        "role": "artifact_capacity_protection_lease_deletion",
        "lease_id": lease_id,
        "path": str(path),
        "deleted": deleted,
    }


def load_capacity_protection_leases(
    root: Path, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Load and union active leases, failing closed on an ambiguous document."""

    lease_root = root / PROTECTION_LEASE_DIRECTORY
    result: dict[str, Any] = {
        "protected_cache_keys": set(),
        "protected_paths": set(),
        "audit": [],
    }
    if not lease_root.exists():
        return result
    if not lease_root.is_dir() or lease_root.is_symlink():
        raise CapacityProtectionLeaseError(lease_root, "lease root is not a real directory")
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).timestamp()
    for path in sorted(lease_root.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.is_symlink() or path.suffix != ".json":
            raise CapacityProtectionLeaseError(path, "lease directory contains a non-JSON file")
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CapacityProtectionLeaseError(path, f"lease JSON is unreadable: {exc}") from exc
        if not isinstance(document, dict):
            raise CapacityProtectionLeaseError(path, "lease JSON must be an object")
        expiry = parse_utc_timestamp(document.get("expires_at_utc"))
        if expiry is None:
            raise CapacityProtectionLeaseError(path, "expires_at_utc must be timezone-aware")
        audit = {
            "path": str(path),
            "lease_id": document.get("lease_id", path.stem),
            "owner": document.get("owner"),
            "expires_at_utc": expiry[1],
        }
        if expiry[0] <= observed:
            result["audit"].append({**audit, "status": "expired_ignored"})
            continue
        expected_fields = {
            "schema_version", "role", "lease_id", "owner", "created_at_utc",
            "expires_at_utc", "protected_cache_keys", "protected_paths",
        }
        try:
            lease_id = _validated_lease_id(document.get("lease_id"))
        except ValueError as exc:
            raise CapacityProtectionLeaseError(path, str(exc)) from exc
        created = parse_utc_timestamp(document.get("created_at_utc"))
        keys = document.get("protected_cache_keys")
        paths = document.get("protected_paths")
        malformed = (
            set(document) != expected_fields
            or document.get("schema_version") != 1
            or document.get("role") != "artifact_capacity_protection_lease"
            or path.name != f"{lease_id}.json"
            or not isinstance(document.get("owner"), str)
            or not document["owner"].strip()
            or created is None
            or created[0] >= expiry[0]
            or not isinstance(keys, list)
            or not isinstance(paths, list)
            or any(not isinstance(key, str) or CACHE_KEY.fullmatch(key) is None for key in keys or ())
            or any(not isinstance(item, str) or not item for item in paths or ())
            or (not keys and not paths)
        )
        if malformed:
            raise CapacityProtectionLeaseError(path, "active lease fields differ from schema version 1")
        resolved_paths: set[Path] = set()
        try:
            for item in paths:
                if Path(item).is_absolute() or Path(item).as_posix() != item:
                    raise ValueError("protected paths must be canonical artifact-root-relative paths")
                relative = _relative_protected_path(root, Path(item))
                if relative != item:
                    raise ValueError("protected path is not canonical")
                # Preserve the artifact root's accepted spelling (including a
                # Windows 8.3 temporary path) after the resolved containment
                # check, so comparisons match candidates from the same root.
                resolved_paths.add((root / Path(item)).absolute())
        except ValueError as exc:
            raise CapacityProtectionLeaseError(path, str(exc)) from exc
        normalized_keys = {key.lower() for key in keys}
        result["protected_cache_keys"].update(normalized_keys)
        result["protected_paths"].update(resolved_paths)
        result["audit"].append({
            **audit,
            "status": "active",
            "protected_cache_key_count": len(normalized_keys),
            "protected_path_count": len(resolved_paths),
        })
    return result


def path_is_protected(path: Path, protected_paths: Iterable[Path]) -> bool:
    return any(path == item or item in path.parents or path in item.parents for item in protected_paths)
