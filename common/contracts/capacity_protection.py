"""TTL artifact protection shared by cleanup and layout verification.

This module owns lease schema and path coverage; the capacity CLI owns commands.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CACHE_KEY = re.compile(r"\b[a-f0-9]{64}\b", re.IGNORECASE)
LEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PROTECTION_LEASE_DIRECTORY = Path("common") / "capacity_protection_leases"
CAPACITY_DECISION_LOCK_NAME = ".capacity_decision.lock"
DISPOSAL_RECEIPT_DIRECTORY = Path("common") / "capacity_disposal_receipts"


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


@contextmanager
def capacity_decision_lock(root: Path, *, timeout_seconds: float = 30.0):
    """Serialize only protection registration and cleanup decisions.

    The retained lock file is harmless; the kernel lock, not file existence,
    owns exclusion and is released automatically if a process exits.
    """

    if timeout_seconds < 0:
        raise ValueError("capacity decision lock timeout must be nonnegative")
    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    path = root / PROTECTION_LEASE_DIRECTORY / CAPACITY_DECISION_LOCK_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + timeout_seconds
    try:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"capacity decision lock is held: {path}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"capacity decision lock is held: {path}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


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


def _pending_disposal_targets_from_receipts(root: Path) -> set[Path]:
    """Read explicit pending capacity-disposal receipts without discovery.

    A protection lease can be needed precisely while a historical capacity
    ledger is missing or fails schema validation.  Such registration must not
    initialize, repair, or otherwise mutate that ledger.  Pending disposal
    receipts remain independent, durable deletion authority, so inspect them
    directly before accepting a new lease in that bootstrap state.
    """

    receipt_root = root / DISPOSAL_RECEIPT_DIRECTORY
    if not receipt_root.exists():
        return set()
    if not receipt_root.is_dir() or receipt_root.is_symlink():
        raise ValueError("capacity disposal receipt directory is not a real directory")
    pending: set[Path] = set()
    for receipt_path in sorted(receipt_root.glob("*.json"), key=lambda item: item.name):
        # A zero-byte historical plan placeholder cannot be a valid receipt:
        # every receipt is a JSON object with role and status.  Ignoring this
        # exact shape permits protective registration during ledger migration;
        # nonempty unreadable files remain fail-closed below.
        if receipt_path.stat().st_size == 0:
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"capacity disposal receipt is unreadable: {receipt_path}"
            ) from exc
        if not isinstance(receipt, dict) or receipt.get("status") != "pending":
            continue
        if receipt.get("role") != "artifact_capacity_disposal_receipt":
            continue
        target_value = receipt.get("target_path")
        if not isinstance(target_value, str) or not target_value:
            raise ValueError(
                f"pending capacity disposal receipt target is invalid: {receipt_path}"
            )
        target = Path(target_value).resolve(strict=False)
        try:
            target.relative_to(root.resolve(strict=False))
        except ValueError as exc:
            raise ValueError(
                f"pending capacity disposal target escapes artifact root: {receipt_path}"
            ) from exc
        if target == root.resolve(strict=False):
            raise ValueError(
                f"pending capacity disposal target is artifact root: {receipt_path}"
            )
        pending.add(target)
    return pending


def _pending_disposal_targets(root: Path) -> set[Path] | None:
    """Query the calibrated ledger when available without legacy discovery."""

    # Local import avoids a module-initialization cycle: capacity_ledger uses
    # this module's decision lock for its own atomic state transitions.
    from common.contracts.capacity_ledger import pending_disposal_targets

    from common.contracts.capacity_ledger import load_capacity_ledger

    if load_capacity_ledger(root) is None:
        return None
    return pending_disposal_targets(root)


def _assert_not_pending_disposal(
    root: Path, *, keys: Iterable[str], paths: Iterable[str],
    allow_unavailable_ledger: bool = False,
) -> None:
    # Receipt inspection is required even when the ledger is healthy: a
    # deletion receipt is durable authority during the ledger/apply gap.
    pending = _pending_disposal_targets_from_receipts(root)
    ledger_pending = _pending_disposal_targets(root)
    if ledger_pending is None:
        if not allow_unavailable_ledger:
            raise ValueError("capacity ledger is missing or invalid; pending state is unknown")
    else:
        pending.update(ledger_pending)
    normalized_keys = {key.lower() for key in keys}
    if any(target.name.lower() in normalized_keys for target in pending):
        raise ValueError("cannot protect a cache key after its disposal became pending")
    resolved_paths = {(root / Path(path)).resolve(strict=False) for path in paths}
    if any(path_is_protected(target, resolved_paths) for target in pending):
        raise ValueError("cannot protect a path after its disposal became pending")


def _validated_commitment(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("committed_new_bytes must be a nonnegative integer")
    return value


def _create_capacity_protection_lease_unlocked(
    root: Path, *, lease_id: str, owner: str, ttl_seconds: int,
    protected_cache_keys: Iterable[str] = (), protected_paths: Iterable[Path] = (),
    committed_new_bytes: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create one TTL protection lease below ``artifacts/common``."""

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    lease_id = _validated_lease_id(lease_id)
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("lease owner must be nonempty")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise ValueError("lease TTL seconds must be a positive integer")
    committed_new_bytes = _validated_commitment(committed_new_bytes)
    keys = sorted({str(key).lower() for key in protected_cache_keys})
    if any(CACHE_KEY.fullmatch(key) is None for key in keys):
        raise ValueError("every protected cache key must be one SHA-256 key")
    paths = sorted({_relative_protected_path(root, Path(path)) for path in protected_paths})
    if not keys and not paths:
        raise ValueError("a protection lease must protect at least one cache key or path")
    _assert_not_pending_disposal(
        root, keys=keys, paths=paths, allow_unavailable_ledger=True,
    )
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
        "committed_new_bytes": committed_new_bytes,
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


def create_capacity_protection_lease(
    root: Path, *, lease_id: str, owner: str, ttl_seconds: int,
    protected_cache_keys: Iterable[str] = (), protected_paths: Iterable[Path] = (),
    committed_new_bytes: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    with capacity_decision_lock(root):
        return _create_capacity_protection_lease_unlocked(
            root,
            lease_id=lease_id,
            owner=owner,
            ttl_seconds=ttl_seconds,
            protected_cache_keys=protected_cache_keys,
            protected_paths=protected_paths,
            committed_new_bytes=committed_new_bytes,
            now=now,
        )


def _renew_capacity_protection_lease_unlocked(
    root: Path, *, lease_id: str, owner: str, ttl_seconds: int,
    protected_cache_keys: Iterable[str] = (),
    protected_paths: Iterable[Path] = (),
    committed_new_bytes: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically extend an active lease and monotonically expand its scope.

    Renewal must happen before expiry and requires the same owner.  New keys
    and paths are unioned with the existing scope; renewal can never remove a
    protected generation.  This lets a producer publish a content-addressed
    successor and protect it before handing the same lease to its consumer.
    """

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    lease_id = _validated_lease_id(lease_id)
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("lease owner must be nonempty")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise ValueError("lease TTL seconds must be a positive integer")
    if committed_new_bytes is not None:
        committed_new_bytes = _validated_commitment(committed_new_bytes)
    additional_keys = {str(key).lower() for key in protected_cache_keys}
    if any(CACHE_KEY.fullmatch(key) is None for key in additional_keys):
        raise ValueError("every protected cache key must be one SHA-256 key")
    additional_paths = {
        _relative_protected_path(root, Path(path)) for path in protected_paths
    }
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    leases = load_capacity_protection_leases(root, now=observed)
    audit = next(
        (item for item in leases["audit"] if item.get("lease_id") == lease_id),
        None,
    )
    if audit is None:
        raise ValueError(f"protection lease does not exist: {lease_id}")
    if audit.get("status") != "active":
        raise ValueError(
            f"protection lease is expired and cannot be renewed: {lease_id}"
        )
    path = _lease_path(root, lease_id)
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if document["owner"] != owner.strip():
        raise ValueError("protection lease owner differs")
    current_commitment = _validated_commitment(document.get("committed_new_bytes", 0))
    current_keys = set(document["protected_cache_keys"])
    current_paths = set(document["protected_paths"])
    from common.contracts.capacity_ledger import CAPACITY_LEDGER_RELATIVE_PATH

    capacity_ledger_path = root / CAPACITY_LEDGER_RELATIVE_PATH
    ledger_missing = (
        not capacity_ledger_path.exists()
        and not capacity_ledger_path.is_symlink()
    )
    bootstrap_renewal = False
    if ledger_missing:
        if not additional_keys.issubset(current_keys) or not additional_paths.issubset(current_paths):
            raise ValueError("bootstrap lease renewal cannot expand protection scope")
        if committed_new_bytes is not None and committed_new_bytes != current_commitment:
            raise ValueError("bootstrap lease renewal cannot change committed_new_bytes")
        bootstrap_renewal = True
    else:
        _assert_not_pending_disposal(
            root,
            keys=current_keys | additional_keys,
            paths=current_paths | additional_paths,
        )
    current_expiry = parse_utc_timestamp(document.get("expires_at_utc"))
    if current_expiry is None:
        raise ValueError("protection lease expiry is invalid")
    expires = datetime.fromtimestamp(observed.timestamp() + ttl_seconds, timezone.utc)
    if expires.timestamp() <= current_expiry[0]:
        raise ValueError("protection lease renewal must extend its expiry")
    renewed = {
        **document,
        "expires_at_utc": expires.isoformat().replace("+00:00", "Z"),
        "protected_cache_keys": sorted(
            current_keys | additional_keys
        ),
        "protected_paths": sorted(
            current_paths | additional_paths
        ),
        "committed_new_bytes": (
            current_commitment
            if committed_new_bytes is None
            else committed_new_bytes
        ),
    }
    scope_extended = (
        renewed["protected_cache_keys"] != document["protected_cache_keys"]
        or renewed["protected_paths"] != document["protected_paths"]
    )
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.renewing"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(renewed, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        **renewed,
        "path": str(path),
        "renewed": True,
        "scope_extended": scope_extended,
        "bootstrap_renewal": bootstrap_renewal,
        "renewal_mode": (
            "bootstrap_missing_capacity_ledger"
            if bootstrap_renewal
            else "normal"
        ),
    }


def renew_capacity_protection_lease(
    root: Path, *, lease_id: str, owner: str, ttl_seconds: int,
    protected_cache_keys: Iterable[str] = (),
    protected_paths: Iterable[Path] = (),
    committed_new_bytes: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    with capacity_decision_lock(root):
        return _renew_capacity_protection_lease_unlocked(
            root,
            lease_id=lease_id,
            owner=owner,
            ttl_seconds=ttl_seconds,
            protected_cache_keys=protected_cache_keys,
            protected_paths=protected_paths,
            committed_new_bytes=committed_new_bytes,
            now=now,
        )


def _delete_capacity_protection_lease_unlocked(root: Path, *, lease_id: str) -> dict[str, Any]:
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


def delete_capacity_protection_lease(root: Path, *, lease_id: str) -> dict[str, Any]:
    with capacity_decision_lock(root):
        return _delete_capacity_protection_lease_unlocked(root, lease_id=lease_id)


def load_capacity_protection_leases(
    root: Path, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Load and union active leases, failing closed on an ambiguous document."""

    lease_root = root / PROTECTION_LEASE_DIRECTORY
    result: dict[str, Any] = {
        "protected_cache_keys": set(),
        "protected_paths": set(),
        "audit": [],
        "committed_new_bytes": 0,
        "legacy_unknown_commitment_count": 0,
    }
    if not lease_root.exists():
        return result
    if not lease_root.is_dir() or lease_root.is_symlink():
        raise CapacityProtectionLeaseError(lease_root, "lease root is not a real directory")
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).timestamp()
    for path in sorted(lease_root.iterdir(), key=lambda item: item.name):
        if path.name == CAPACITY_DECISION_LOCK_NAME and path.is_file():
            continue
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
        required_fields = {
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
            not required_fields.issubset(document)
            or set(document) - (required_fields | {"committed_new_bytes"})
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
        legacy_commitment = "committed_new_bytes" not in document
        commitment = document.get("committed_new_bytes", 0)
        try:
            commitment = _validated_commitment(commitment)
        except ValueError as exc:
            raise CapacityProtectionLeaseError(path, str(exc)) from exc
        result["protected_cache_keys"].update(normalized_keys)
        result["protected_paths"].update(resolved_paths)
        result["committed_new_bytes"] += commitment
        result["legacy_unknown_commitment_count"] += int(legacy_commitment)
        result["audit"].append({
            **audit,
            "status": "active",
            "protected_cache_key_count": len(normalized_keys),
            "protected_path_count": len(resolved_paths),
            "protected_cache_keys": sorted(normalized_keys),
            "protected_paths": sorted(str(item) for item in resolved_paths),
            "committed_new_bytes": commitment,
            "commitment_status": "legacy_unknown_treated_as_zero" if legacy_commitment else "declared",
        })
    return result


def path_is_protected(path: Path, protected_paths: Iterable[Path]) -> bool:
    return any(path == item or item in path.parents or path in item.parents for item in protected_paths)
