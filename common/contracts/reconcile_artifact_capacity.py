"""Keep an artifact scope below a governed capacity watermark.

The gate is deliberately conservative.  It only ever removes reconstructible
material.  Candidates receive a deletion priority from the checked-in policy:
lower-priority material is evicted first, then the oldest item within that
same priority. Reusable cache age means its last recorded successful
consumption, falling back to its generation publication time when no such
record exists. Formal evidence, active runs, and explicitly protected paths
are never candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common.contracts import reconcile_interrupted_compact_runs as compact
from common.contracts.artifact_retention import apply_retention, classify_file
from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import verify_record

GIB = 1024**3
# Run manifests in this repository publish successful solver work as
# ``success``. Terminal runs cannot keep a reconstructible cache active.
TERMINAL = {"success", "completed", "failed", "interrupted", "cancelled", "aborted"}
DISPOSABLE_TERMINAL_RUNS = {"failed", "interrupted", "cancelled", "aborted"}
CACHE_KEY = re.compile(r"\b[a-f0-9]{64}\b", re.IGNORECASE)
LEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
POLICY_PATH = Path(__file__).with_name("artifact_capacity_policy.json")
PROTECTION_LEASE_DIRECTORY = Path("common") / "capacity_protection_leases"
DISPOSAL_RECEIPT_DIRECTORY = Path("common") / "capacity_disposal_receipts"
HEAVY_RETENTION_ROLES = {"solver_native_binary", "dense_trajectory", "large_optional"}


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


def _published_pa_cache_key(pointer_path: Path) -> str | None:
    """Return one valid current PA-family key without hashing its large payload.

    The repository has two published PA-family pointer schemas: the shared
    device-neutral cache and the older integration adapter.  Both publish the
    pointer last.  A key is therefore protected only when that pointer selects
    an existing generation manifest with matching key and generation identity.
    Unpublished staging directories and damaged/failed publications have no
    such closed chain and are deliberately excluded.
    """

    key = pointer_path.parent.name.lower()
    if not CACHE_KEY.fullmatch(key):
        return None
    pointer = _load_object(pointer_path)
    if pointer is None:
        return None
    declared_key = pointer.get("cache_key")
    if declared_key is not None and str(declared_key).lower() != key:
        return None
    relative = pointer.get("generation_relative_path")
    if isinstance(relative, str):
        relative_path = Path(relative)
        generation = relative_path.name
        manifest_path = pointer_path.parent / relative_path / "cache_manifest.json"
    else:
        generation = pointer.get("generation_sha256")
        if not isinstance(generation, str):
            return None
        manifest_path = (
            pointer_path.parent / "generations" / generation / "cache_manifest.json"
        )
    manifest = _load_object(manifest_path)
    if manifest is None:
        return None
    role = str(manifest.get("role", ""))
    schema_version = manifest.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version < 1
        or (role != "simion_pa_family_cache" and not role.endswith("_pa_cache"))
    ):
        return None
    if (
        str(manifest.get("cache_key", "")).lower() != key
        or str(manifest.get("generation_sha256", "")) != generation
    ):
        return None
    return key


def _current_generation_pointers(root: Path) -> list[Path]:
    """Enumerate pointer files while tolerating concurrently removed children."""

    pointers: list[Path] = []

    def visit(directory: Path) -> None:
        try:
            entries = os.scandir(directory)
        except FileNotFoundError:
            return
        with entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        visit(Path(entry.path))
                    elif (
                        entry.is_file(follow_symlinks=False)
                        and entry.name == "current_generation.json"
                    ):
                        pointers.append(Path(entry.path))
                except FileNotFoundError:
                    # Capacity preflights and failed-run cleanup may remove a
                    # temporary sibling after its directory entry was read.
                    # A disappeared node cannot be a retained publication.
                    continue

    visit(root)
    return pointers


def snapshot_published_pa_cache_keys(root: Path) -> dict[str, Any]:
    """Freeze all valid PA-family publications visible at run startup."""

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    keys = sorted({
        key
        for pointer in _current_generation_pointers(root)
        if (key := _published_pa_cache_key(pointer)) is not None
    })
    return {
        "schema_version": 1,
        "role": "artifact_capacity_published_pa_cache_protection_snapshot",
        "artifact_root": str(root),
        "captured_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "protected_cache_keys": keys,
        "protected_cache_key_count": len(keys),
    }


def _capacity_policy() -> dict[str, Any]:
    """Load and minimally validate the versioned repository eviction policy."""

    policy = _load_object(POLICY_PATH)
    if policy is None or int(policy.get("schema_version", 0)) != 1:
        raise RuntimeError(f"invalid artifact-capacity policy: {POLICY_PATH}")
    roles = policy.get("l2_role_deletion_priorities")
    if not isinstance(roles, dict):
        raise RuntimeError(f"invalid L2 role priorities in {POLICY_PATH}")
    for field in (
        "unmanaged_run_deletion_priority",
        "terminal_nonformal_run_deletion_priority",
        "explicit_success_build_payload_deletion_priority",
        "default_l2_deletion_priority",
        "l1_deletion_priority",
        "l3_deletion_priority",
    ):
        if not isinstance(policy.get(field), int) or int(policy[field]) < 0:
            raise RuntimeError(f"invalid {field} in {POLICY_PATH}")
    grace = policy.get("unmanaged_run_grace_seconds")
    if isinstance(grace, bool) or not isinstance(grace, int) or grace < 0:
        raise RuntimeError(f"invalid unmanaged_run_grace_seconds in {POLICY_PATH}")
    if any(not isinstance(value, int) or value < 0 for value in roles.values()):
        raise RuntimeError(f"invalid L2 role priority in {POLICY_PATH}")
    return policy


def _deletion_priority(*, level: str, cache_role: str | None, policy: dict[str, Any]) -> int:
    """Return a policy-owned priority; unknown published roles stay conservative."""

    if level == "RUN":
        return int(policy["terminal_nonformal_run_deletion_priority"])
    if level == "L1":
        return int(policy["l1_deletion_priority"])
    if level == "L3":
        return int(policy["l3_deletion_priority"])
    if level != "L2":
        raise ValueError(f"unknown artifact cleanup level: {level}")
    role_priorities = policy["l2_role_deletion_priorities"]
    return int(role_priorities.get(cache_role, policy["default_l2_deletion_priority"]))


def _directory_bytes(root: Path) -> dict[Path, int]:
    """Return inclusive byte counts for every real directory in one walk.

    Capacity planning needs both the whole artifact footprint and individual
    cache footprints.  Re-walking each cache made a dry-run scale with the
    number of cache keys.  A bottom-up walk preserves the exact file and
    symlink rules while sharing that I/O across all candidates.
    """
    sizes: dict[Path, int] = {}

    def measure(directory: Path) -> int:
        """Measure once with DirEntry's cached type/stat information.

        This is the bounded slow path: no valid conservative upper bound is
        available, so the gate must inspect the artifact tree before it may
        remove anything.  ``os.walk`` reconstructs paths and performs fresh
        metadata lookups for every file; on the large PA cache that makes an
        otherwise single walk unnecessarily slow.  ``scandir`` retains the
        same no-symlink accounting rule while avoiding those extra lookups.
        """
        total = 0
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        total += measure(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except FileNotFoundError:
                    # A concurrent preflight may remove its temporary child
                    # after enumeration. Missing children consume no bytes;
                    # permission and other I/O failures must still propagate.
                    continue
        sizes[directory] = total
        return total

    measure(root)
    return sizes


def _load_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _active_cache_keys(root: Path) -> set[str]:
    """Keys mentioned by a non-terminal run are protected from L2 cleanup."""

    protected: set[str] = set()
    for manifest in root.rglob("run_manifest.json"):
        document = _load_object(manifest)
        if document is None or str(document.get("status", "")).lower() in TERMINAL:
            continue
        try:
            protected.update(CACHE_KEY.findall(manifest.read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeDecodeError):
            continue
    return {key.lower() for key in protected}


def _utc_timestamp(value: object) -> tuple[float, str] | None:
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


def _load_capacity_protection_leases(
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
        expiry = _utc_timestamp(document.get("expires_at_utc"))
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
        created = _utc_timestamp(document.get("created_at_utc"))
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


def _last_successful_cache_uses(root: Path) -> dict[str, tuple[float, str]]:
    """Return each cache key's latest successful, manifest-recorded consumer.

    Filesystem atime is frequently disabled or changed by backup/indexing, so
    it is not evidence that a simulation consumed a cache. A terminal
    ``success``/``completed`` run manifest is durable, auditable evidence.
    The scan runs only after the fast capacity paths establish that cleanup is
    necessary.
    """

    latest: dict[str, tuple[float, str]] = {}
    for manifest in root.rglob("run_manifest.json"):
        document = _load_object(manifest)
        if document is None or str(document.get("status", "")).lower() not in {"success", "completed"}:
            continue
        observed = _utc_timestamp(document.get("recorded_at_utc"))
        if observed is None:
            continue
        try:
            keys = {key.lower() for key in CACHE_KEY.findall(manifest.read_text(encoding="utf-8-sig"))}
        except (OSError, UnicodeDecodeError):
            continue
        for key in keys:
            if key not in latest or observed[0] > latest[key][0]:
                latest[key] = observed
    return latest


def _is_immutable_lifecycle_path(path: Path) -> bool:
    """Formal releases and archived evidence are never cleanup candidates."""

    return any(part.lower() in {"formal", "archive"} for part in path.parts)


def _protected(path: Path, protected_paths: Iterable[Path]) -> bool:
    return any(path == item or item in path.parents or path in item.parents for item in protected_paths)


def _active_run_reference_texts(root: Path) -> tuple[tuple[Path, str], ...]:
    """Load the frozen identity text of every non-terminal run once."""

    values: list[tuple[Path, str]] = []
    for manifest_path in root.rglob("run_manifest.json"):
        manifest = _load_object(manifest_path)
        if manifest is None or str(manifest.get("status", "")).lower() in TERMINAL:
            continue
        run_dir = manifest_path.parent.absolute()
        text_parts: list[str] = []
        for path in (manifest_path, run_dir / "run_config.json"):
            try:
                text_parts.append(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError):
                # An unreadable active identity is ambiguous.  Its own run is
                # still protected by status; unrelated candidates are not
                # inferred from bytes that cannot be inspected.
                continue
        values.append((run_dir, "\n".join(text_parts)))
    return tuple(values)


def _has_active_run_reference(
    candidate: Path, active_references: Iterable[tuple[Path, str]]
) -> bool:
    candidate = candidate.absolute()
    path_spellings = {str(candidate), candidate.as_posix()}
    for active_dir, text in active_references:
        if active_dir == candidate:
            continue
        if candidate.name in text or any(value in text for value in path_spellings):
            return True
    return False


def _cache_candidate(cache_key_dir: Path, protected_keys: set[str], last_successful_uses: dict[str, tuple[float, str]],
                     now: float, staging_grace_seconds: int,
                     protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
                     policy: dict[str, Any]) -> dict[str, Any] | None:
    if _is_immutable_lifecycle_path(cache_key_dir) or _protected(cache_key_dir, protected_paths):
        return None
    name = cache_key_dir.name.lower()
    mtime = cache_key_dir.stat().st_mtime
    payload = {"path": str(cache_key_dir), "bytes": directory_bytes.get(cache_key_dir, 0), "timestamp": mtime}
    if name.startswith("b-") and not (cache_key_dir / "cache_manifest.json").exists():
        if now - mtime >= staging_grace_seconds:
            payload.update(level="L1", reason="old_unpublished_cache_staging",
                           deletion_priority=_deletion_priority(level="L1", cache_role=None, policy=policy))
            return payload
        return None
    if not CACHE_KEY.fullmatch(name) or name in protected_keys:
        return None
    pointer = cache_key_dir / "current_generation.json"
    if not pointer.is_file():
        return None
    selected = _load_object(pointer)
    relative = selected.get("generation_relative_path") if selected else None
    if isinstance(relative, str):
        generation = Path(relative).name
        published = cache_key_dir / relative / "cache_manifest.json"
    else:
        generation_value = selected.get("generation_sha256") if selected else None
        generation = generation_value if isinstance(generation_value, str) else ""
        published = (
            cache_key_dir / "generations" / generation / "cache_manifest.json"
            if generation
            else None
        )
    manifest = _load_object(published) if published and published.is_file() else None
    role = str(manifest.get("role", "")) if manifest else ""
    schema_version = int(manifest.get("schema_version", 0)) if manifest else 0
    verified = bool(
        manifest
        and (
            schema_version >= 3
            or (schema_version >= 1 and role == "simion_pa_family_cache")
        )
        and str(manifest.get("cache_key", "")).lower() == name
        and str(manifest.get("generation_sha256", "")).lower() == generation.lower()
    )
    if not verified:
        # A malformed pointer or selected generation is an incomplete cache,
        # not a published L2 object.  It is only eligible as L1 and never if
        # a caller explicitly pins the key.
        payload.update(level="L1", reason="damaged_or_incomplete_cache_generation",
                       deletion_priority=_deletion_priority(level="L1", cache_role=None, policy=policy))
        return payload
    last_use = last_successful_uses.get(name)
    if last_use is None:
        payload.update(
            timestamp=published.stat().st_mtime,
            eviction_time_basis="generation_publication_time",
        )
    else:
        payload.update(
            timestamp=last_use[0],
            last_successful_use_at_utc=last_use[1],
            eviction_time_basis="last_successful_cache_consumption",
        )
    cache_role = str(manifest.get("role", cache_key_dir.parent.name))
    payload.update(level="L2", reason="inactive_reconstructible_published_cache", cache_role=cache_role,
                   deletion_priority=_deletion_priority(level="L2", cache_role=cache_role, policy=policy))
    return payload


def _cache_candidates(root: Path, protected_keys: set[str], last_successful_uses: dict[str, tuple[float, str]],
                      now: float, staging_grace_seconds: int,
                      protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
                      policy: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for cache_root in root.rglob("cache"):
        if not cache_root.is_dir() or _is_immutable_lifecycle_path(cache_root):
            continue
        for role_dir in cache_root.iterdir():
            if not role_dir.is_dir() or _is_immutable_lifecycle_path(role_dir):
                continue
            for child in role_dir.iterdir():
                if child.is_dir():
                    candidate = _cache_candidate(child, protected_keys, last_successful_uses, now, staging_grace_seconds, protected_paths, directory_bytes, policy)
                    if candidate:
                        candidates.append(candidate)
    common_pa_family_cache = root / "common" / "simion" / "pa_family_cache"
    if common_pa_family_cache.is_dir() and not _is_immutable_lifecycle_path(
        common_pa_family_cache
    ):
        for child in common_pa_family_cache.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                candidate = _cache_candidate(
                    child,
                    protected_keys,
                    last_successful_uses,
                    now,
                    staging_grace_seconds,
                    protected_paths,
                    directory_bytes,
                    policy,
                )
                if candidate:
                    candidates.append(candidate)
    return candidates


def _compact_candidates(root: Path, protected_paths: Iterable[Path], policy: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for run_root in root.rglob("runs"):
        if not run_root.is_dir() or _is_immutable_lifecycle_path(run_root):
            continue
        for run_dir in run_root.iterdir():
            if not run_dir.is_dir() or _protected(run_dir, protected_paths):
                continue
            try:
                report = compact.inspect_run(run_dir)
            except (AssertionError, KeyError, TypeError, ValueError):
                continue
            if report["removable_bytes"]:
                candidates.append({"level": "L3", "reason": "verified_interrupted_compact_payload",
                                   "path": str(run_dir), "bytes": int(report["removable_bytes"]),
                                   "timestamp": run_dir.stat().st_mtime, "compact_report": report,
                                   "deletion_priority": _deletion_priority(level="L3", cache_role=None, policy=policy)})
    return candidates


def _unmanaged_run_candidates(
    root: Path, protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
    active_references: Iterable[tuple[Path, str]], now: float,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return old run-shaped trees that never published identity evidence."""

    candidates: list[dict[str, Any]] = []
    grace = int(policy["unmanaged_run_grace_seconds"])
    for run_root in root.rglob("runs"):
        if not run_root.is_dir() or _is_immutable_lifecycle_path(run_root):
            continue
        for run_dir in run_root.iterdir():
            if (
                not run_dir.is_dir()
                or _protected(run_dir, protected_paths)
                or (run_dir / "run_manifest.json").exists()
                or (run_dir / "summary.json").exists()
                or _has_active_run_reference(run_dir, active_references)
                or _unmanaged_run_receipt_path(root, run_dir).exists()
            ):
                continue
            created = run_dir.stat().st_ctime
            if now - created < grace:
                continue
            candidates.append({
                "level": "L1",
                "operation": "remove_unmanaged_run_with_receipt",
                "reason": "old_unmanaged_unreferenced_run",
                "path": str(run_dir),
                "bytes": directory_bytes.get(run_dir, 0),
                "timestamp": created,
                "eviction_time_basis": "run_directory_creation_time",
                "deletion_priority": int(policy["unmanaged_run_deletion_priority"]),
            })
    return candidates


def _manifest_recorded_paths(run_dir: Path, manifest: dict[str, Any]) -> set[Path]:
    """Resolve manifest records conservatively without trusting escaping paths."""

    recorded = {
        (run_dir / "run_manifest.json").resolve(),
        (run_dir / "run_config.json").resolve(),
        (run_dir / "summary.json").resolve(),
    }
    verify_record("run_config", manifest["run_config"], base_dir=run_dir)
    for section in ("inputs", "outputs"):
        values = manifest.get(section, {} if section == "inputs" else [])
        records = values.values() if isinstance(values, dict) else values
        if not isinstance(records, (list, tuple, type({}.values()))):
            raise ValueError(f"manifest {section} records differ")
        for index, record in enumerate(records):
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise ValueError(f"manifest {section} record differs")
            verify_record(f"{section} {index}", record, base_dir=run_dir)
            path = (run_dir / record["path"]).resolve()
            try:
                path.relative_to(run_dir.resolve())
            except ValueError as exc:
                raise ValueError("manifest record escapes its run") from exc
            recorded.add(path)
    return recorded


def _success_build_payload_candidate(
    run_dir: Path, protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
    active_references: Iterable[tuple[Path, str]], policy: dict[str, Any],
) -> dict[str, Any] | None:
    """Inspect one explicitly authorized success build without weakening success runs."""

    run_dir = run_dir.absolute()
    if (
        run_dir.parent.name != "runs"
        or not run_dir.is_dir()
        or _is_immutable_lifecycle_path(run_dir)
        or _protected(run_dir, protected_paths)
        or _has_active_run_reference(run_dir, active_references)
        or (run_dir / "capacity_retirement_actions.json").exists()
    ):
        return None
    manifest = _load_object(run_dir / "run_manifest.json")
    summary = _load_object(run_dir / "summary.json")
    config = _load_object(run_dir / "run_config.json")
    if manifest is None or summary is None or config is None:
        return None
    if (
        manifest.get("status") != "success"
        or summary.get("status") != "success"
        or bool(manifest.get("formal_eligible"))
        or bool(summary.get("formal_eligible"))
        or bool(config.get("formal_gate_passed"))
        or config.get("run_id") != run_dir.name
        or len(run_dir.name.split("__")) < 2
        or run_dir.name.split("__")[1] != "build"
    ):
        return None
    try:
        recorded = _manifest_recorded_paths(run_dir, manifest)
    except (AssertionError, KeyError, TypeError, ValueError):
        return None
    removable: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.resolve() in recorded:
            continue
        role = classify_file(path)
        if role in HEAVY_RETENTION_ROLES:
            removable.append({
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": path.stat().st_size,
                "retention_role": role,
            })
    removable_bytes = sum(int(item["bytes"]) for item in removable)
    if not removable_bytes:
        return None
    recorded_at = _utc_timestamp(manifest.get("recorded_at_utc"))
    timestamp = recorded_at[0] if recorded_at is not None else run_dir.stat().st_mtime
    return {
        "level": "RUN_PAYLOAD",
        "operation": "retire_explicit_success_build_payload",
        "reason": "explicit_rebuildable_unreferenced_success_build_payload",
        "path": str(run_dir),
        "bytes": removable_bytes,
        "timestamp": timestamp,
        "eviction_time_basis": (
            "success_manifest_recorded_at_utc" if recorded_at is not None
            else "run_directory_modification_time"
        ),
        "removable": removable,
        "deletion_priority": int(policy["explicit_success_build_payload_deletion_priority"]),
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _unmanaged_run_receipt_path(root: Path, run_dir: Path) -> Path:
    identity = hashlib.sha256(str(run_dir.absolute()).encode("utf-8")).hexdigest()[:16]
    return root / DISPOSAL_RECEIPT_DIRECTORY / f"unmanaged_run_{identity}.json"


def _file_disposal_records(run_dir: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("capacity disposal path escapes its run") from exc
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"capacity disposal file is missing or not regular: {path}")
        records.append({
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        })
    return records


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        path.chmod(path.stat().st_mode | stat.S_IWRITE)
        path.unlink()


def _remove_unmanaged_run_with_receipt(root: Path, run_dir: Path) -> tuple[Path, int]:
    files = sorted(
        path for path in run_dir.rglob("*") if path.is_file() and not path.is_symlink()
    )
    records = _file_disposal_records(run_dir, files)
    receipt_path = _unmanaged_run_receipt_path(root, run_dir)
    receipt = {
        "schema_version": 1,
        "role": "artifact_capacity_disposal_receipt",
        "status": "pending",
        "reason": "old_unmanaged_unreferenced_run",
        "target_path": str(run_dir),
        "files": records,
        "removed_bytes": sum(int(item["bytes"]) for item in records),
    }
    _write_json_atomic(receipt_path, receipt)
    _remove_tree(run_dir)
    receipt["status"] = "complete"
    _write_json_atomic(receipt_path, receipt)
    return receipt_path, int(receipt["removed_bytes"])


def _retire_success_build_payload(run_dir: Path, removable: Iterable[dict[str, Any]]) -> tuple[Path, int]:
    paths = [run_dir / str(item["path"]) for item in removable]
    records = _file_disposal_records(run_dir, paths)
    receipt_path = run_dir / "capacity_retirement_actions.json"
    manifest_path = run_dir / "run_manifest.json"
    receipt = {
        "schema_version": 1,
        "role": "artifact_capacity_success_build_payload_retirement",
        "status": "pending",
        "reason": "explicit_rebuildable_unreferenced_success_build_payload",
        "run_id": run_dir.name,
        "source_manifest_sha256": file_sha256(manifest_path),
        "removed": records,
        "removed_bytes": sum(int(item["bytes"]) for item in records),
    }
    _write_json_atomic(receipt_path, receipt)
    for path in paths:
        _remove_file(path)
    receipt["status"] = "complete"
    _write_json_atomic(receipt_path, receipt)
    return receipt_path, int(receipt["removed_bytes"])


def _terminal_run_candidate(run_dir: Path, protected_paths: Iterable[Path],
                            directory_bytes: dict[Path, int], policy: dict[str, Any]) -> dict[str, Any] | None:
    """Return a whole-run eviction candidate only for failed, non-formal work.

    A completed run can still be useful evidence, so it is never removed here.
    Historical interrupted runs sometimes predate a manifest; in that case a
    terminal ``summary.json`` is sufficient.  When both records exist, any
    success/completed or formal marker wins conservatively.
    """

    if _is_immutable_lifecycle_path(run_dir) or _protected(run_dir, protected_paths):
        return None
    manifest = _load_object(run_dir / "run_manifest.json")
    summary = _load_object(run_dir / "summary.json")
    documents = tuple(document for document in (manifest, summary) if document is not None)
    if not documents:
        return None
    if any(bool(document.get("formal_eligible")) for document in documents):
        return None
    statuses = {str(document.get("status", "")).lower() for document in documents}
    nonterminal_statuses = statuses - TERMINAL
    # A checkpoint manifest is an intermediate durability record, not a final
    # outcome.  Some older governed runs published that checkpoint after their
    # child had already written a terminal failed/interrupted summary.  Treat
    # that specific combination as disposable; genuinely live states such as
    # ``running`` still protect the entire run.
    if (
        nonterminal_statuses - {"checkpoint"}
        or statuses & {"success", "completed"}
        or not (statuses & DISPOSABLE_TERMINAL_RUNS)
    ):
        return None
    return {
        "level": "RUN",
        "operation": "remove_tree",
        "reason": "terminal_nonformal_failed_or_interrupted_run",
        "path": str(run_dir),
        "bytes": directory_bytes.get(run_dir, 0),
        "timestamp": run_dir.stat().st_mtime,
        "run_statuses": sorted(statuses),
        "deletion_priority": _deletion_priority(level="RUN", cache_role=None, policy=policy),
    }


def _terminal_run_candidates(root: Path, protected_paths: Iterable[Path],
                             directory_bytes: dict[Path, int], policy: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for run_root in root.rglob("runs"):
        if not run_root.is_dir() or _is_immutable_lifecycle_path(run_root):
            continue
        for run_dir in run_root.iterdir():
            if run_dir.is_dir():
                candidate = _terminal_run_candidate(run_dir, protected_paths, directory_bytes, policy)
                if candidate:
                    candidates.append(candidate)
    return candidates


def plan(root: Path, *, target_bytes: int, required_headroom_bytes: int = 0,
         minimum_free_bytes: int = 0,
         staging_grace_seconds: int = 900, protected_paths: Iterable[Path] = (),
         protected_cache_keys: Iterable[str] = (),
         rebuildable_success_build_runs: Iterable[Path] = (),
         known_measured_bytes: int | None = None,
         maximum_new_artifact_bytes: int | None = None) -> dict[str, Any]:
    # Keep the caller's absolute spelling.  On Windows, resolve() can rewrite
    # an 8.3 temporary-root path to its long form, making the receipt disagree
    # with the paths accepted by the caller despite denoting the same cache.
    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    if (known_measured_bytes is None) != (maximum_new_artifact_bytes is None):
        raise ValueError("known capacity fast path requires both byte values")
    if known_measured_bytes is not None and (
        known_measured_bytes < 0 or maximum_new_artifact_bytes is None
        or maximum_new_artifact_bytes < 0
    ):
        raise ValueError("known capacity fast-path bytes must be nonnegative")
    explicit_protected = tuple(path.absolute() for path in protected_paths)
    explicit_keys = {
        str(key).lower() for key in protected_cache_keys
        if CACHE_KEY.fullmatch(str(key))
    }
    explicit_success_build_runs: list[Path] = []
    for value in rebuildable_success_build_runs:
        candidate = Path(value).absolute()
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("rebuildable success build run must remain below artifact root") from exc
        explicit_success_build_runs.append(candidate)
    explicit_success_build_runs = sorted(set(explicit_success_build_runs), key=str)
    leases = _load_capacity_protection_leases(root)
    protected = tuple(sorted(
        {*explicit_protected, *leases["protected_paths"]}, key=str
    ))
    leased_and_explicit_keys = explicit_keys | leases["protected_cache_keys"]
    protection_fields = {
        "explicit_protected_paths": [str(path) for path in explicit_protected],
        "explicit_protected_cache_keys": sorted(explicit_keys),
        "explicit_rebuildable_success_build_runs": [
            str(path) for path in explicit_success_build_runs
        ],
        "protected_paths": [str(path) for path in protected],
        "protected_cache_keys": sorted(leased_and_explicit_keys),
        "protection_lease_audit": leases["audit"],
    }
    # A launch receipt plus its governed maximum transient footprint supplies
    # a conservative upper bound while the shared solver lease excludes a
    # second concurrent SIMION publication.  Avoid a full artifact walk when
    # that upper bound is already safely below the watermark and the physical
    # disk floor is met.  This is an optimization only: uncertainty falls back
    # to the existing exhaustive, level-then-age planner.
    free_bytes = shutil.disk_usage(root).free
    if (
        known_measured_bytes is not None
        and known_measured_bytes + maximum_new_artifact_bytes + required_headroom_bytes
        <= target_bytes
        and free_bytes >= minimum_free_bytes
    ):
        upper_bound = known_measured_bytes + maximum_new_artifact_bytes
        return {
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "free_bytes_before": free_bytes, "staging_grace_seconds": staging_grace_seconds,
            **protection_fields,
            "measurement_mode": "SAFE_NO_RECONCILIATION",
            "known_measured_bytes": known_measured_bytes,
            "maximum_new_artifact_bytes": maximum_new_artifact_bytes,
            "estimated_upper_bound_bytes": upper_bound,
            "free_deficit_bytes": 0, "measured_bytes": known_measured_bytes,
            "limit_bytes": target_bytes - required_headroom_bytes,
            "active_cache_key_count": None, "candidate_count": 0,
            "planned": [], "projected_bytes": upper_bound, "satisfied": True,
        }
    directory_bytes = _directory_bytes(root)
    measured = directory_bytes[root]
    if minimum_free_bytes < 0:
        raise ValueError("minimum free bytes must be nonnegative")
    free_bytes = shutil.disk_usage(root).free
    # A current full measurement can close the ordinary no-cleanup case without
    # enumerating cache manifests or interrupted runs.  apply() repeats this
    # measurement immediately before publication; if the state changed, it
    # falls through to the established L1/L2/L3 planner below.
    if (
        measured + required_headroom_bytes <= target_bytes
        and free_bytes >= minimum_free_bytes
    ):
        return {
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "free_bytes_before": free_bytes, "staging_grace_seconds": staging_grace_seconds,
            **protection_fields,
            "measurement_mode": "FULL_NO_RECONCILIATION",
            "free_deficit_bytes": 0, "measured_bytes": measured,
            "limit_bytes": target_bytes - required_headroom_bytes,
            "active_cache_key_count": None, "candidate_count": 0,
            "planned": [], "projected_bytes": measured, "satisfied": True,
        }
    now = time.time()
    policy = _capacity_policy()
    active_keys = _active_cache_keys(root)
    last_successful_uses = _last_successful_cache_uses(root)
    active_references = _active_run_reference_texts(root)
    active_keys.update(leased_and_explicit_keys)
    candidates = _terminal_run_candidates(root, protected, directory_bytes, policy)
    candidates.extend(_unmanaged_run_candidates(
        root, protected, directory_bytes, active_references, now, policy
    ))
    candidates.extend(_cache_candidates(root, active_keys, last_successful_uses, now, staging_grace_seconds, protected, directory_bytes, policy))
    candidates.extend(_compact_candidates(root, protected, policy))
    for run_dir in explicit_success_build_runs:
        candidate = _success_build_payload_candidate(
            run_dir, protected, directory_bytes, active_references, policy
        )
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda item: (item["deletion_priority"], item["timestamp"], item["path"]))
    free_deficit = max(0, minimum_free_bytes - free_bytes)
    # Every byte removed from this artifact root returns one byte to the same
    # volume.  Intersect the repository watermark with the physical-free-space
    # requirement so the repository policy's priority-then-age ordering remains the sole deletion
    # policy.
    limit = min(target_bytes - required_headroom_bytes, measured - free_deficit)
    planned: list[dict[str, Any]] = []
    projected = measured
    for candidate in candidates:
        if projected <= limit:
            break
        planned.append(candidate)
        projected -= candidate["bytes"]
    return {"schema_version": 1, "role": "artifact_capacity_gate", "artifact_root": str(root),
            "target_bytes": target_bytes, "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes, "free_bytes_before": free_bytes,
            "staging_grace_seconds": staging_grace_seconds,
            "explicit_protected_paths": protection_fields["explicit_protected_paths"],
            "explicit_protected_cache_keys": protection_fields["explicit_protected_cache_keys"],
            "explicit_rebuildable_success_build_runs": protection_fields[
                "explicit_rebuildable_success_build_runs"
            ],
            "protected_paths": [str(path) for path in protected],
            "protected_cache_keys": sorted(active_keys),
            "protection_lease_audit": leases["audit"],
            "free_deficit_bytes": free_deficit,
            "measured_bytes": measured, "limit_bytes": limit, "active_cache_key_count": len(active_keys),
            "candidate_count": len(candidates), "planned": planned, "projected_bytes": projected,
            "satisfied": projected <= limit}


def _remove_tree(path: Path) -> bool:
    """Remove one planned tree, tolerating another gate winning the race.

    Capacity reconciliation deliberately refreshes its plan immediately before
    applying it, but independent solver launches may still choose the same
    rebuildable candidate.  An already-absent path is therefore a successful
    no-op, not evidence that the surviving artifact set is inconsistent.
    """

    missing = False

    def onerror(function: Any, value: str, error: Any) -> None:
        nonlocal missing
        if isinstance(error[1], FileNotFoundError):
            missing = True
            return
        try:
            os.chmod(value, stat.S_IWRITE)
            function(value)
        except FileNotFoundError:
            missing = True

    try:
        shutil.rmtree(path, onerror=onerror)
    except FileNotFoundError:
        missing = True
    return not missing


def apply(receipt: dict[str, Any]) -> dict[str, Any]:
    # Active SIMION does not prohibit cleanup: plan() excludes every cache key
    # mentioned by a non-terminal manifest, and the plan is refreshed here to
    # close the interval between a capacity decision and deletion.  This keeps
    # the disk floor enforceable while another independent channel is solving.
    root = Path(receipt["artifact_root"])
    if receipt.get("measurement_mode") == "FULL_NO_RECONCILIATION":
        sizes = _directory_bytes(root)
        measured_after = sizes[root]
        free_after = shutil.disk_usage(root).free
        if (
            measured_after + int(receipt["required_headroom_bytes"])
            <= int(receipt["target_bytes"])
            and free_after >= int(receipt["minimum_free_bytes"])
        ):
            outcome = dict(receipt)
            outcome.update(
                applied=True, removed=[], removed_bytes=0,
                measured_after_bytes=measured_after,
                free_bytes_after=free_after,
                satisfied_after_apply=True,
            )
            return outcome
    if receipt.get("measurement_mode") == "SAFE_NO_RECONCILIATION":
        outcome = dict(receipt)
        outcome.update(
            applied=True, removed=[], removed_bytes=0,
            measured_after_bytes=receipt["known_measured_bytes"],
            estimated_upper_bound_after_bytes=receipt["estimated_upper_bound_bytes"],
            free_bytes_after=shutil.disk_usage(root).free,
            satisfied_after_apply=True,
        )
        return outcome
    receipt = plan(
        root,
        target_bytes=int(receipt["target_bytes"]),
        required_headroom_bytes=int(receipt["required_headroom_bytes"]),
        minimum_free_bytes=int(receipt["minimum_free_bytes"]),
        staging_grace_seconds=int(receipt.get("staging_grace_seconds", 900)),
        protected_paths=(
            Path(path) for path in receipt.get(
                "explicit_protected_paths", receipt.get("protected_paths", ())
            )
        ),
        protected_cache_keys=receipt.get(
            "explicit_protected_cache_keys", receipt.get("protected_cache_keys", ())
        ),
        rebuildable_success_build_runs=(
            Path(path) for path in receipt.get(
                "explicit_rebuildable_success_build_runs", ()
            )
        ),
    )
    removed: list[dict[str, Any]] = []
    for item in receipt["planned"]:
        path = Path(item["path"])
        if item.get("operation") == "remove_unmanaged_run_with_receipt":
            receipt_path, removed_bytes = _remove_unmanaged_run_with_receipt(root, path)
            removed.append({
                "path": str(path), "level": item["level"], "bytes": removed_bytes,
                "disposal_receipt": str(receipt_path),
            })
            continue
        if item.get("operation") == "retire_explicit_success_build_payload":
            receipt_path, removed_bytes = _retire_success_build_payload(
                path, item["removable"]
            )
            removed.append({
                "path": str(path), "level": item["level"], "bytes": removed_bytes,
                "retirement_receipt": str(receipt_path),
            })
            continue
        if item.get("operation") == "remove_tree" or item["level"] in {"L1", "L2"}:
            if not _remove_tree(path):
                continue
        else:
            actions = apply_retention(path / "run_config.json")
            removed.append({"path": str(path), "level": item["level"], "bytes": item["bytes"],
                            "retention_actions": str(actions)})
            continue
        removed.append({"path": str(path), "level": item["level"], "bytes": item["bytes"]})
    receipt = dict(receipt)
    receipt["applied"] = True
    receipt["removed"] = removed
    receipt["removed_bytes"] = sum(item["bytes"] for item in removed)
    receipt["measured_after_bytes"] = _directory_bytes(Path(receipt["artifact_root"]))[
        Path(receipt["artifact_root"])
    ]
    receipt["free_bytes_after"] = shutil.disk_usage(Path(receipt["artifact_root"])).free
    receipt["satisfied_after_apply"] = (
        receipt["measured_after_bytes"] + receipt["required_headroom_bytes"] <= receipt["target_bytes"]
        and receipt["free_bytes_after"] >= receipt["minimum_free_bytes"]
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--snapshot-published-pa-cache-keys", action="store_true")
    lease_actions = parser.add_mutually_exclusive_group()
    lease_actions.add_argument("--create-protection-lease")
    lease_actions.add_argument("--delete-protection-lease")
    parser.add_argument("--lease-owner")
    parser.add_argument("--lease-ttl-seconds", type=int)
    parser.add_argument("--target-gib", type=float, default=500.0)
    parser.add_argument("--required-headroom-bytes", type=int, default=0)
    parser.add_argument("--minimum-free-gib", type=float, default=500.0)
    parser.add_argument("--staging-grace-seconds", type=int, default=900)
    parser.add_argument("--protect-path", action="append", type=Path, default=[])
    parser.add_argument("--protect-cache-key", action="append", default=[])
    parser.add_argument(
        "--rebuildable-success-build-run", action="append", type=Path, default=[]
    )
    parser.add_argument("--known-measured-bytes", type=int)
    parser.add_argument("--maximum-new-artifact-bytes", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.snapshot_published_pa_cache_keys:
        if args.apply:
            parser.error("published PA cache protection snapshot is read-only")
        print(json.dumps(snapshot_published_pa_cache_keys(args.artifact_root), indent=2))
        return
    if args.create_protection_lease:
        if args.apply or not args.lease_owner or args.lease_ttl_seconds is None:
            parser.error("lease creation requires owner and TTL, and cannot use --apply")
        try:
            lease = create_capacity_protection_lease(
                args.artifact_root,
                lease_id=args.create_protection_lease,
                owner=args.lease_owner,
                ttl_seconds=args.lease_ttl_seconds,
                protected_cache_keys=args.protect_cache_key,
                protected_paths=args.protect_path,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(lease, indent=2))
        return
    if args.delete_protection_lease:
        if args.apply:
            parser.error("lease deletion cannot use --apply")
        try:
            deleted = delete_capacity_protection_lease(
                args.artifact_root, lease_id=args.delete_protection_lease
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(deleted, indent=2))
        return
    if (args.target_gib <= 0 or args.required_headroom_bytes < 0 or
            args.minimum_free_gib < 0 or args.staging_grace_seconds < 0):
        parser.error("capacity values must be nonnegative and target positive")
    if args.apply and not os.environ.get(
        "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"
    ):
        parser.error(
            "--apply requires the shared HostExecutionLease; use "
            "Invoke-ArtifactCapacityGate from PowerShell 7"
        )
    try:
        receipt = plan(args.artifact_root, target_bytes=int(args.target_gib * GIB),
                       required_headroom_bytes=args.required_headroom_bytes,
                       minimum_free_bytes=int(args.minimum_free_gib * GIB),
                       staging_grace_seconds=args.staging_grace_seconds, protected_paths=args.protect_path,
                       protected_cache_keys=args.protect_cache_key,
                       rebuildable_success_build_runs=args.rebuildable_success_build_run,
                       known_measured_bytes=args.known_measured_bytes,
                       maximum_new_artifact_bytes=args.maximum_new_artifact_bytes)
        if args.apply:
            receipt = apply(receipt)
    except CapacityProtectionLeaseError as exc:
        print(json.dumps(exc.audit, indent=2), file=sys.stderr)
        sys.exit(2)
    if args.apply:
        satisfied = receipt["satisfied_after_apply"]
    else:
        satisfied = receipt["satisfied"]
    print(json.dumps(receipt, indent=2))
    if not satisfied:
        sys.exit(2)


if __name__ == "__main__":
    main()
