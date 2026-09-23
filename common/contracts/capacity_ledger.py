"""Maintain the small, trusted artifact-capacity ledger.

This module never discovers artifacts or hashes payloads.  A ledger may be
created only through :func:`initialize_capacity_ledger`; normal incremental
recording fails closed when that calibrated baseline is absent or invalid.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from common.contracts import capacity_protection as protection
from common.contracts.recorded_file_removal import write_json_atomic

CAPACITY_LEDGER_RELATIVE_PATH = Path("common") / "capacity_ledger.json"
STALE_ATOMIC_TEMP_PREFIX = ".capacity_ledger.json."
STALE_ATOMIC_TEMP_MINIMUM_AGE_SECONDS = 1.0
PA_RUNTIME_STATE_RELATIVE_PATHS = {
    "common/simion/pa_family_cache/.build-locks",
    "common/simion/pa_family_cache/.locks",
    "common/simion/pa_family_cache/.staging",
}
LEDGER_CLASSES = {"light_evidence", "published_cache", "rebuildable_payload"}
LEDGER_STATUSES = {"writing", "ready", "retirement_pending", "retired"}
EXTERNAL_SCOPE_ROLES = {
    "repository_scratch", "repository_generated", "repository_workspace_scratch",
}
RECORDABLE_STATUSES = {"writing", "ready"}
SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
"""The ledger records *managed ranges*, not duties for individual files.

Each record is an exact directory or generation below the artifact root.  Its
``owner`` covers every file in that range; its class and state select the
existing retention or PA-manager exit path.  ``writing`` is the only resident
state that needs a deadline because it represents an unfinished operation.

The four former lifecycle fields are accepted while reading historical v3
ledgers so an interrupted migration remains inspectable, but new records do
not write them.  They duplicated facts already held by run manifests, PA
transactions, and the retention/retirement entry points.
"""
LEGACY_LIFECYCLE_FIELDS = {
    "owner", "retention_reason", "review_deadline", "retirement_route",
}
RECOVERY_FIELDS = {"recovery_reason", "recovery_task", "recovery_evidence_paths"}
BASE_OBJECT_FIELDS = {"path", "class", "bytes", "status"}
OPTIONAL_OBJECT_FIELDS = {
    "pin", "identity", "pin_reason", "last_used_epoch", "retired_at_utc",
    "retirement_error", "consumers", "disposition", "manager", *LEGACY_LIFECYCLE_FIELDS,
    *RECOVERY_FIELDS,
}
V2_RECOVERY_FIELDS = {"owner", "recovery_reason", "review_deadline"}
V2_OPTIONAL_OBJECT_FIELDS = {
    "pin", "identity", "pin_reason", "last_used_epoch", "retired_at_utc",
    "retirement_error", "consumers", "disposition", "manager", *V2_RECOVERY_FIELDS,
    "recovery_task", "recovery_evidence_paths",
}
PA_CACHE_MANAGER = "common.simion.pa_family_cache"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_ledger_path(root: Path, path: Path | None = None) -> Path:
    """Return the configured ledger path without creating it."""

    return (path or (root / CAPACITY_LEDGER_RELATIVE_PATH)).absolute()


def capacity_object_path(root: Path, value: Path | str) -> tuple[Path, str]:
    """Resolve one object path and reject symlink/junction escapes."""

    root = root.resolve(strict=False)
    target = Path(value)
    target = (target if target.is_absolute() else root / target).resolve(strict=False)
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("ledger object must remain below artifact root") from exc
    if not relative.parts:
        raise ValueError("ledger object cannot be the artifact root")
    return target, relative.as_posix()


def _ledger_relative_path(value: object) -> str | None:
    """Validate one already-recorded relative path without touching payloads.

    External paths still pass through :func:`capacity_object_path` when they
    enter the ledger or are acted upon.  Loading the trusted ledger must not
    resolve every recorded payload through the filesystem on each startup.
    """

    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or candidate.drive or not candidate.parts:
        return None
    if any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    canonical = candidate.as_posix()
    return canonical if canonical == value else None


def _valid_disposition(value: object, *, expected_bytes: int) -> bool:
    if not isinstance(value, dict) or set(value) not in ({
        "id", "generation", "manifest_sha256", "files",
    }, {
        "id", "generation", "manifest_path", "files",
    }):
        return False
    if any(
        not isinstance(value.get(key), str) or SHA256.fullmatch(value[key]) is None
        for key in ("id", "generation")
    ) or not isinstance(value.get("files"), list) or not value["files"]:
        return False
    legacy_hash_inventory = "manifest_sha256" in value
    if legacy_hash_inventory:
        if not isinstance(value["manifest_sha256"], str) or SHA256.fullmatch(value["manifest_sha256"]) is None:
            return False
    elif _ledger_relative_path(value.get("manifest_path")) is None:
        return False
    seen: set[str] = set()
    total = 0
    for record in value["files"]:
        required = {"path", "bytes", "sha256"} if legacy_hash_inventory else {"path", "bytes"}
        if not isinstance(record, dict) or set(record) != required:
            return False
        path = _ledger_relative_path(record.get("path"))
        size = record.get("bytes")
        if (
            path is None or path in seen or isinstance(size, bool)
            or not isinstance(size, int) or size < 0
        ):
            return False
        if legacy_hash_inventory and (
            not isinstance(record.get("sha256"), str)
            or SHA256.fullmatch(record["sha256"]) is None
        ):
            return False
        seen.add(path)
        total += size
    return total == expected_bytes


def _valid_range_owner(item: dict[str, Any]) -> bool:
    """Validate the one owner carried by a resident managed range."""

    if item["status"] == "retired":
        return "owner" not in item or (
            isinstance(item["owner"], str) and bool(item["owner"].strip())
        )
    return isinstance(item.get("owner"), str) and bool(item["owner"].strip())


def load_capacity_ledger(root: Path, path: Path | None = None) -> dict[str, Any] | None:
    """Load a calibrated complete ledger without scanning artifact payloads."""

    root = root.resolve(strict=False)
    try:
        document = json.loads(resolve_ledger_path(root, path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if _is_valid_capacity_ledger(root, document) else None


def migrate_v2_ledger_document(
    root: Path, document: object, *, lifecycle_by_path: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a range-managed v3 ledger from an explicit owner assignment.

    ``lifecycle_by_path`` keeps its public name for the narrow historical
    migration API.  Ready ranges provide only ``{"owner": "..."}``; a
    writing range additionally carries its bounded recovery evidence.  The
    helper never infers ownership from a path.
    """

    root = root.resolve(strict=False)
    if not isinstance(document, dict) or document.get("schema_version") != 2:
        raise ValueError("v2 capacity ledger migration requires a valid v2 document")
    if not _is_valid_capacity_ledger(root, document):
        raise ValueError("v2 capacity ledger migration source is invalid")
    if not isinstance(lifecycle_by_path, dict):
        raise ValueError("v2 capacity ledger lifecycle assignments must be a mapping")
    resident_paths = {
        item["path"] for item in document["objects"] if item["status"] != "retired"
    }
    if set(lifecycle_by_path) != resident_paths:
        raise ValueError("v2 capacity ledger migration duties must cover exactly every resident object")
    migrated = json.loads(json.dumps(document))
    migrated["schema_version"] = 3
    for item in migrated["objects"]:
        if item["status"] == "retired":
            continue
        duties = lifecycle_by_path[item["path"]]
        expected = {"owner"}
        allowed = set(expected)
        if item["status"] == "writing":
            expected |= {"recovery_reason", "review_deadline"}
            allowed |= {"recovery_reason", "review_deadline", "recovery_task", "recovery_evidence_paths"}
        if not isinstance(duties, dict) or not expected.issubset(duties) or set(duties) - allowed:
            raise ValueError("v2 capacity ledger migration requires complete range management")
        owner = duties["owner"]
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("v2 capacity ledger range owner must be nonempty")
        item.update(duties)
        item["owner"] = owner.strip()
        if item["class"] == "published_cache":
            item["manager"] = PA_CACHE_MANAGER
    if not _is_valid_capacity_ledger(root, migrated):
        raise ValueError("v2 capacity ledger migration result is invalid")
    return migrated


def _is_valid_capacity_ledger(root: Path, document: object) -> bool:
    """Validate the complete ledger schema and its resident-byte invariant."""

    if not isinstance(document, dict) or document.get("schema_version") not in {2, 3}:
        return False
    is_v3 = document["schema_version"] == 3
    if set(document) != {
        "schema_version", "role", "status", "complete", "artifact_root",
        "resident_bytes", "objects", "external_scopes",
    }:
        return False
    if document.get("role") != "artifact_capacity_ledger":
        return False
    if document.get("status") != "calibrated" or document.get("complete") is not True:
        return False
    try:
        document_root = Path(str(document.get("artifact_root", ""))).resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    if document_root != root:
        return False
    resident = document.get("resident_bytes")
    if isinstance(resident, bool) or not isinstance(resident, int) or resident < 0:
        return False
    objects = document.get("objects", [])
    external_scopes = document.get("external_scopes", [])
    if not isinstance(objects, list) or not isinstance(external_scopes, list):
        return False
    external_bytes = 0
    external_roles: set[str] = set()
    external_paths: set[str] = set()
    for item in external_scopes:
        if not isinstance(item, dict) or set(item) != {"role", "path", "bytes"}:
            return False
        role, path, size = item.get("role"), item.get("path"), item.get("bytes")
        if role not in EXTERNAL_SCOPE_ROLES or not isinstance(path, str) or not path:
            return False
        candidate = Path(path)
        if not candidate.is_absolute() or candidate.resolve(strict=False) != candidate:
            return False
        key = str(candidate).casefold() if os.name == "nt" else str(candidate)
        if role in external_roles or key in external_paths:
            return False
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            return False
        external_roles.add(role)
        external_paths.add(key)
        external_bytes += size
    if external_scopes and not external_roles.issubset(EXTERNAL_SCOPE_ROLES):
        return False
    seen_paths: set[str] = set()
    governed_paths: list[str] = []
    governed_bytes = 0
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return False
        allowed_object_fields = OPTIONAL_OBJECT_FIELDS if is_v3 else V2_OPTIONAL_OBJECT_FIELDS
        if not BASE_OBJECT_FIELDS.issubset(item) or set(item) - (
            BASE_OBJECT_FIELDS | allowed_object_fields
        ):
            return False
        if item.get("class") not in LEDGER_CLASSES:
            return False
        if item.get("status") not in LEDGER_STATUSES or not isinstance(item.get("pin", False), bool):
            return False
        if is_v3:
            if not _valid_range_owner(item):
                return False
            recovery_present = RECOVERY_FIELDS.intersection(item)
        else:
            recovery_present = V2_RECOVERY_FIELDS.intersection(item)
        if item["status"] == "writing":
            required_recovery_fields = {"recovery_reason"} if is_v3 else V2_RECOVERY_FIELDS
            if not required_recovery_fields.issubset(recovery_present):
                return False
            writing_text_fields = (
                ("recovery_reason",) if is_v3
                else ("owner", "recovery_reason", "review_deadline")
            )
            if any(not isinstance(item[field], str) or not item[field].strip() for field in writing_text_fields):
                return False
            if "recovery_task" in item and (
                not isinstance(item["recovery_task"], str) or not item["recovery_task"].strip()
            ):
                return False
            if is_v3:
                try:
                    date.fromisoformat(str(item.get("review_deadline", "")))
                except ValueError:
                    return False
            if not is_v3:
                try:
                    date.fromisoformat(item["review_deadline"])
                except ValueError:
                    return False
            consumers = item.get("consumers", [])
            if not isinstance(consumers, list) or any(
                not isinstance(value, str) or not value for value in consumers
            ):
                return False
            canonical_consumers = [_ledger_relative_path(value) for value in consumers]
            if any(value is None for value in canonical_consumers):
                return False
            if consumers != sorted(set(canonical_consumers)):
                return False
            evidence_paths = item.get("recovery_evidence_paths", [])
            if not isinstance(evidence_paths, list) or any(
                not isinstance(value, str) or not value for value in evidence_paths
            ):
                return False
            canonical_evidence = [_ledger_relative_path(value) for value in evidence_paths]
            if any(value is None for value in canonical_evidence):
                return False
            if evidence_paths != sorted(set(canonical_evidence)):
                return False
        elif recovery_present or "consumers" in item or "recovery_task" in item or "recovery_evidence_paths" in item:
            return False
        canonical = _ledger_relative_path(item["path"])
        if canonical is None:
            return False
        identity = canonical.casefold() if os.name == "nt" else canonical
        if identity in seen_paths:
            return False
        seen_paths.add(identity)
        value = item.get("bytes", 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
        pin = item.get("pin", False)
        if pin and (
            not isinstance(item.get("pin_reason"), str)
            or not item["pin_reason"].strip()
        ):
            return False
        if not pin and "pin_reason" in item:
            return False
        if item["class"] == "published_cache" and (
            not isinstance(item.get("identity"), str)
            or SHA256.fullmatch(item["identity"]) is None
        ):
            return False
        is_pa_family_range = item["path"].startswith("common/simion/pa_family_cache/")
        if is_v3 and is_pa_family_range and item["class"] == "published_cache" and item["status"] == "ready":
            if item.get("manager") != PA_CACHE_MANAGER:
                return False
        if item["class"] != "published_cache" and (
            "identity" in item or "last_used_epoch" in item or "manager" in item
        ):
            return False
        if "manager" in item and item["manager"] != PA_CACHE_MANAGER:
            return False
        disposition = item.get("disposition")
        if disposition is not None and (
            item["class"] != "rebuildable_payload"
            or item["status"] not in {"ready", "retirement_pending", "retired"}
            or not _valid_disposition(disposition, expected_bytes=value)
        ):
            return False
        if item["status"] != "retired" and "retired_at_utc" in item:
            return False
        if item["status"] != "retirement_pending" and "retirement_error" in item:
            return False
        last_used = item.get("last_used_epoch")
        if last_used is not None and (
            isinstance(last_used, bool)
            or not isinstance(last_used, (int, float))
            or not math.isfinite(last_used)
            or last_used < 0
        ):
            return False
        if item["status"] != "retired":
            governed_paths.append(identity)
            governed_bytes += value
    # Check each lexical ancestor against a set.  This is linear in the total
    # number of path components and avoids the former pairwise Path.parents
    # walk, which made a historical calibration quadratic in object count.
    governed_path_set = set(governed_paths)
    for governed_path in governed_paths:
        parts = governed_path.split("/")
        if any("/".join(parts[:index]) in governed_path_set for index in range(1, len(parts))):
            return False
    if governed_bytes + external_bytes != resident:
        return False
    return True


def initialize_capacity_ledger(
    root: Path, *, objects: Iterable[dict[str, Any]],
    external_scopes: Iterable[dict[str, Any]] | None = None,
    path: Path | None = None, overwrite: bool = False,
) -> dict[str, Any]:
    """Explicitly publish a calibrated complete baseline from backfill output.

    ``objects`` must already be the complete, reviewed inventory.  This API
    validates and publishes it but deliberately performs no discovery.
    """

    root = root.resolve(strict=False)
    destination = resolve_ledger_path(root, path)
    normalized: list[dict[str, Any]] = []
    for source in objects:
        if not isinstance(source, dict):
            raise ValueError("capacity ledger objects must be mappings")
        _, relative = capacity_object_path(root, str(source.get("path", "")))
        # A calibrated record denotes a whole managed range.  Historical
        # callers may still supply the former duplicated duty fields; omit
        # them on publication so the ledger stays the small accounting view.
        entry = {
            key: value for key, value in source.items()
            if key not in {"retention_reason", "retirement_route"}
        }
        if entry.get("status") != "writing":
            entry.pop("review_deadline", None)
        entry["path"] = relative
        normalized.append(entry)
    document = {
        "schema_version": 3,
        "role": "artifact_capacity_ledger",
        "status": "calibrated",
        "complete": True,
        "artifact_root": str(root),
        "resident_bytes": (
            sum(int(item.get("bytes", 0)) for item in normalized if item.get("status") != "retired")
            + sum(int(item.get("bytes", 0)) for item in (external_scopes or ()))
        ),
        "objects": normalized,
        "external_scopes": list(external_scopes or ()),
    }
    if not _is_valid_capacity_ledger(root, document):
        raise ValueError("explicit capacity ledger baseline is invalid")
    with protection.capacity_decision_lock(root):
        if destination.exists() and not overwrite:
            raise FileExistsError(f"capacity ledger already exists: {destination}")
        write_json_atomic(destination, document)
        validated = load_capacity_ledger(root, destination)
        if validated is None:
            raise RuntimeError("capacity ledger publication could not be read back")
    return validated


def record_capacity_object(
    root: Path, *, path: Path | str, object_class: str, bytes_count: int,
    status: str = "ready", identity: str | None = None, pin: bool = False,
    pin_reason: str | None = None,
    owner: str | None = None, retention_reason: str | None = None,
    review_deadline: str | None = None, retirement_route: str | None = None,
    recovery_reason: str | None = None, recovery_task: str | None = None,
    recovery_evidence_paths: Iterable[Path | str] = (),
    consumers: Iterable[Path | str] = (),
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Insert or update one governed object; never create a missing ledger."""

    if object_class not in LEDGER_CLASSES or status not in RECORDABLE_STATUSES:
        raise ValueError("ledger object class/status is not governed")
    if isinstance(bytes_count, bool) or not isinstance(bytes_count, int) or bytes_count < 0:
        raise ValueError("ledger object bytes must be a nonnegative integer")
    if pin and (not isinstance(pin_reason, str) or not pin_reason.strip()):
        raise ValueError("pinned ledger objects require a nonempty pin_reason")
    if object_class == "published_cache" and (
        not isinstance(identity, str) or SHA256.fullmatch(identity) is None
    ):
        raise ValueError("published_cache requires a SHA-256 generation identity")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("resident managed ranges require a nonempty owner")
    if status == "writing":
        if not isinstance(recovery_reason, str) or not recovery_reason.strip():
            raise ValueError("writing ledger ranges require recovery_reason")
        if recovery_task is not None and (
            not isinstance(recovery_task, str) or not recovery_task.strip()
        ):
            raise ValueError("writing ledger recovery_task must be nonempty when provided")
        try:
            date.fromisoformat(str(review_deadline))
        except ValueError as exc:
            raise ValueError("writing ledger ranges require review_deadline YYYY-MM-DD") from exc
    elif any(value is not None for value in (recovery_reason, recovery_task)):
        raise ValueError("ready ledger objects cannot carry recovery responsibility fields")
    root = root.resolve(strict=False)
    _, relative = capacity_object_path(root, path)
    canonical_consumers = sorted({
        capacity_object_path(root, value)[1] for value in consumers
    })
    canonical_recovery_evidence = sorted({
        capacity_object_path(root, value)[1] for value in recovery_evidence_paths
    })
    if status != "writing" and canonical_consumers:
        raise ValueError("ready ledger objects cannot carry consumers")
    if status != "writing" and canonical_recovery_evidence:
        raise ValueError("ready ledger objects cannot carry recovery evidence")
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError(
                "capacity ledger is missing, incomplete, or uncalibrated; "
                "initialize it through the explicit initialize/backfill API"
            )
        objects = ledger["objects"]
        existing = next((item for item in objects if item.get("path") == relative), None)
        if existing is not None and "disposition" in existing:
            raise ValueError("manager-approved disposition cannot be replaced by normal recording")
        relative_identity = relative.casefold() if os.name == "nt" else relative
        for item in objects:
            if item is existing or item.get("status") == "retired":
                continue
            other = item["path"].casefold() if os.name == "nt" else item["path"]
            if (
                relative_identity == other
                or relative_identity.startswith(other + "/")
                or other.startswith(relative_identity + "/")
            ):
                raise ValueError("nonretired ledger object ranges cannot overlap")
        old_bytes = int(existing.get("bytes", 0)) if existing and existing.get("status") != "retired" else 0
        entry = {
            "path": relative, "class": object_class, "bytes": bytes_count,
            "status": status, "pin": bool(pin),
        }
        if identity is not None:
            entry["identity"] = str(identity)
        if object_class == "published_cache" and relative.startswith("common/simion/pa_family_cache/"):
            entry["manager"] = PA_CACHE_MANAGER
        if pin:
            entry["pin_reason"] = pin_reason.strip()
        entry["owner"] = owner.strip()
        if status == "writing":
            entry["review_deadline"] = str(review_deadline)
            entry["recovery_reason"] = recovery_reason.strip()
            if recovery_task is not None:
                entry["recovery_task"] = recovery_task.strip()
            if canonical_recovery_evidence:
                entry["recovery_evidence_paths"] = canonical_recovery_evidence
            if canonical_consumers:
                entry["consumers"] = canonical_consumers
        if existing is None:
            objects.append(entry)
        else:
            existing.clear()
            existing.update(entry)
        new_bytes = 0 if status == "retired" else bytes_count
        ledger["resident_bytes"] = int(ledger["resident_bytes"]) + new_bytes - old_bytes
        write_json_atomic(destination, ledger)
    return entry


def touch_capacity_object(
    root: Path, *, path: Path | str, when_epoch: int | float,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Advance only the successful-use time of one ready published cache."""

    if (
        isinstance(when_epoch, bool)
        or not isinstance(when_epoch, (int, float))
        or not math.isfinite(when_epoch)
        or when_epoch < 0
    ):
        raise ValueError("cache touch epoch must be a finite nonnegative number")
    root = root.resolve(strict=False)
    _, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if (
            entry is None
            or entry.get("class") != "published_cache"
            or entry.get("status") != "ready"
        ):
            raise ValueError("only a ready published_cache can be touched")
        previous = entry.get("last_used_epoch")
        if previous is not None and when_epoch < previous:
            raise ValueError("cache touch epoch cannot move backwards")
        entry["last_used_epoch"] = when_epoch
        write_json_atomic(destination, ledger)
        return dict(entry)


def handoff_prepared_cache_stage(
    root: Path, *, stage_path: Path | str, stage_owner: str,
    stage_bytes: int, published_path: Path | str, published_identity: str,
    published_bytes: int, published_owner: str, published_retention_reason: str,
    published_review_deadline: str, published_retirement_route: str,
    published_pin_reason: str | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically replace one prepared stage with its landed cache key.

    Payload publication happens before this call.  The caller declares the
    already-landed key identity and byte count; this function deliberately
    neither scans nor hashes it.  A competing publisher may already have
    recorded the same key, in which case only the duplicate stage is retired.
    """

    if not isinstance(stage_owner, str) or not stage_owner.strip():
        raise ValueError("prepared cache stage owner must be nonempty")
    for label, value in (("stage", stage_bytes), ("published", published_bytes)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label} cache bytes must be a nonnegative integer")
    if not isinstance(published_identity, str) or SHA256.fullmatch(published_identity) is None:
        raise ValueError("published cache handoff requires a SHA-256 generation identity")
    if not isinstance(published_owner, str) or not published_owner.strip():
        raise ValueError("published cache handoff requires a nonempty range owner")
    if published_pin_reason is not None and (
        not isinstance(published_pin_reason, str) or not published_pin_reason.strip()
    ):
        raise ValueError("published cache pin reason must be nonempty when provided")
    pin = published_pin_reason is not None
    pin_reason = published_pin_reason.strip() if published_pin_reason is not None else None

    root = root.resolve(strict=False)
    _, stage_relative = capacity_object_path(root, stage_path)
    _, published_relative = capacity_object_path(root, published_path)
    if stage_relative == published_relative:
        raise ValueError("prepared stage and published cache key must be distinct")
    destination = resolve_ledger_path(root, ledger_path)

    with protection.capacity_decision_lock(root):
        published_target, locked_published_relative = capacity_object_path(root, published_path)
        if locked_published_relative != published_relative or not published_target.is_dir():
            raise ValueError("published cache key must be landed before ledger handoff")
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        objects = ledger["objects"]
        stage = next((item for item in objects if item.get("path") == stage_relative), None)
        published = next(
            (item for item in objects if item.get("path") == published_relative), None,
        )

        published_matches = (
            published is not None
            and published.get("class") == "published_cache"
            and published.get("status") == "ready"
            and published.get("identity") == published_identity
            and published.get("bytes") == published_bytes
            and published.get("pin") is pin
            and published.get("pin_reason") == pin_reason
            and published.get("owner") == published_owner.strip()
        )
        if stage is not None and stage.get("status") == "retired":
            if (
                stage.get("class") != "rebuildable_payload"
                or stage.get("bytes") != stage_bytes
                or not published_matches
            ):
                raise ValueError("completed cache handoff does not match the retry declaration")
            return {
                "stage": dict(stage), "published": dict(published),
                "resident_bytes": int(ledger["resident_bytes"]),
            }

        if (
            stage is None
            or stage.get("class") != "rebuildable_payload"
            or stage.get("status") != "writing"
            or stage.get("owner") != stage_owner.strip()
            or stage.get("bytes") != stage_bytes
            or stage.get("consumers") != [published_relative]
        ):
            raise ValueError(
                "prepared cache stage must exactly match path, owner, bytes, and key consumer"
            )
        if published is not None and published.get("status") != "retired" and not published_matches:
            raise ValueError("published cache key conflicts with the handoff declaration")

        published_identity_path = (
            published_relative.casefold() if os.name == "nt" else published_relative
        )
        for item in objects:
            if item is stage or item is published or item.get("status") == "retired":
                continue
            other = item["path"].casefold() if os.name == "nt" else item["path"]
            if (
                published_identity_path == other
                or published_identity_path.startswith(other + "/")
                or other.startswith(published_identity_path + "/")
            ):
                raise ValueError("nonretired ledger object ranges cannot overlap")

        old_published_bytes = (
            int(published["bytes"])
            if published is not None and published.get("status") != "retired"
            else 0
        )
        stage.clear()
        stage.update({
            "path": stage_relative,
            "class": "rebuildable_payload",
            "bytes": stage_bytes,
            "status": "retired",
            "pin": False,
            "retired_at_utc": _utc_now(),
        })
        published_entry = {
            "path": published_relative,
            "class": "published_cache",
            "bytes": published_bytes,
            "status": "ready",
            "pin": pin,
            "identity": published_identity,
            "manager": PA_CACHE_MANAGER,
        }
        published_entry["owner"] = published_owner.strip()
        if pin_reason is not None:
            published_entry["pin_reason"] = pin_reason
        if published is None:
            objects.append(published_entry)
            published = objects[-1]
        elif not published_matches:
            published.clear()
            published.update(published_entry)
        ledger["resident_bytes"] = (
            int(ledger["resident_bytes"])
            - stage_bytes
            - (0 if published_matches else old_published_bytes)
            + (0 if published_matches else published_bytes)
        )
        write_json_atomic(destination, ledger)
        return {
            "stage": dict(stage), "published": dict(published),
            "resident_bytes": int(ledger["resident_bytes"]),
        }


def _assert_unleased(root: Path, target: Path) -> None:
    leases = protection.load_capacity_protection_leases(root)
    if (
        protection.path_is_protected(target, leases["protected_paths"])
        or target.name.lower() in leases["protected_cache_keys"]
    ):
        raise ValueError(f"ledger object has an active capacity protection lease: {target}")


def approve_published_cache_retirement(
    root: Path, *, path: Path | str, expected_identity: str, expected_bytes: int,
    disposition_id: str, manifest_sha256: str,
    files: Iterable[dict[str, Any]], ledger_path: Path | None = None,
    commit_owner_retirement: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Authorize one exact PA generation for manager-owned retirement.

    The PA manager supplies its sealed manifest inventory.  This function does
    no discovery or hashing and atomically removes the publication pin while
    reclassifying the exact bytes as an approved rebuildable payload.
    """

    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0:
        raise ValueError("cache retirement bytes must be a nonnegative integer")
    if any(SHA256.fullmatch(value or "") is None for value in (
        expected_identity, disposition_id, manifest_sha256,
    )):
        raise ValueError("cache retirement identities must be SHA-256 values")
    disposition = {
        "id": disposition_id.upper(), "generation": expected_identity.upper(),
        "manifest_sha256": manifest_sha256.upper(),
        "files": [dict(record) for record in files],
    }
    if not _valid_disposition(disposition, expected_bytes=expected_bytes):
        raise ValueError("cache retirement sealed file inventory is invalid")
    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        owner = entry.get("owner") if entry is not None else None
        approved = {
            "path": relative, "class": "rebuildable_payload", "bytes": expected_bytes,
            "status": "ready", "pin": False, "disposition": disposition,
            "owner": owner,
        }
        if entry == approved:
            if commit_owner_retirement is not None:
                commit_owner_retirement(disposition)
            return dict(entry)
        if (
            entry is None or entry.get("class") != "published_cache"
            or entry.get("status") != "ready" or entry.get("identity", "").upper() != expected_identity.upper()
            or entry.get("bytes") != expected_bytes or entry.get("pin") is not False
            or "pin_reason" in entry
            or entry.get("manager") != PA_CACHE_MANAGER
        ):
            raise ValueError("published cache retirement declaration conflicts with ledger")
        _assert_unleased(root, target)
        if commit_owner_retirement is None:
            raise ValueError("cache retirement requires its manager commit callback")
        commit_owner_retirement(disposition)
        entry.clear()
        entry.update(approved)
        write_json_atomic(destination, ledger)
        return dict(entry)


def _assert_abandoned_pa_transaction_allowed(
    root: Path, target: Path, relative: str, owner: str, cache_key: str,
    ledger: dict[str, Any], *, allow_transaction_container: bool = False,
) -> dict[str, Any]:
    by_path = {item["path"]: item for item in ledger["objects"]}
    entry = by_path.get(relative)
    is_transaction_container = False
    if entry is None and allow_transaction_container:
        container = "common/simion/pa_family_cache/.transactions"
        candidate = by_path.get(container)
        if (relative.startswith(container + "/") and candidate is not None
                and candidate.get("owner") == PA_CACHE_MANAGER):
            entry = candidate
            is_transaction_container = True
    if (entry is None or entry.get("pin", False) or "pin_reason" in entry
            or not ((entry.get("status") == "writing"
                     and entry.get("class") == "rebuildable_payload"
                     and (entry.get("owner") == owner or is_transaction_container))
                    or (entry.get("status") == "ready" and entry.get("class") == "light_evidence"))):
        raise ValueError("abandonment requires the unpinned writing stage owner")
    _assert_unleased(root, target)
    leases = protection.load_capacity_protection_leases(root)
    if cache_key.lower() in leases["protected_cache_keys"]:
        raise ValueError("abandonment cache key has an active protection lease")
    for consumer in entry.get("consumers", []):
        _assert_unleased(root, root / consumer)
        other = by_path.get(consumer)
        if other is not None and other["status"] != "retired":
            raise ValueError("abandonment has a resident consumer")
    for other in ledger["objects"]:
        if other is entry or other["status"] == "retired":
            continue
        if protection.path_is_protected(target, {root / value for value in other.get("consumers", [])}):
            raise ValueError("abandonment is referenced by another writing owner")
    return entry


def assert_abandoned_pa_transaction_allowed(
    root: Path, *, path: Path, owner: str, cache_key: str,
) -> dict[str, Any]:
    """Check the existing PA-owner retirement protections without mutation."""
    root = root.resolve()
    target, relative = capacity_object_path(root, path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        return dict(_assert_abandoned_pa_transaction_allowed(
            root, target, relative, owner, cache_key, ledger, allow_transaction_container=True,
        ))


def reconcile_pa_transaction_container_bytes(
    root: Path, *, path: Path, owner: str, cache_key: str, resident_bytes: int,
) -> dict[str, Any]:
    """Reconcile a legacy transaction-container range from metadata-only bytes."""
    if isinstance(resident_bytes, bool) or not isinstance(resident_bytes, int) or resident_bytes < 0:
        raise ValueError("transaction container bytes must be nonnegative")
    root = root.resolve()
    target, relative = capacity_object_path(root, path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = _assert_abandoned_pa_transaction_allowed(
            root, target, relative, owner, cache_key, ledger, allow_transaction_container=True,
        )
        if entry["path"] == relative:
            raise ValueError("exact transaction ranges are reconciled by their owner retirement")
        old_bytes = int(entry["bytes"])
        entry["bytes"] = resident_bytes
        ledger["resident_bytes"] += resident_bytes - old_bytes
        write_json_atomic(resolve_ledger_path(root), ledger)
        return dict(entry)


def reconcile_abandoned_pa_transaction(
    root: Path, *, path: Path, owner: str, cache_key: str,
    commit_owner_retirement: Callable[[], None],
) -> dict[str, Any]:
    """Close an empty failed PA stage, retaining evidence and correcting stale bytes.

    This owner operation does not delete payloads or claim physical space freed.
    The callback must verify the empty stage and durably retain its prior state.
    """
    root = root.resolve()
    target, relative = capacity_object_path(root, path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = _assert_abandoned_pa_transaction_allowed(root, target, relative, owner, cache_key, ledger)
        commit_owner_retirement()
        retained_bytes = (target / "transaction.json").stat().st_size
        old_bytes = entry["bytes"]
        owner = entry.get("owner")
        entry.clear()
        entry.update(path=relative, **{"class": "light_evidence"}, bytes=retained_bytes,
                     status="ready", pin=False, owner=owner)
        ledger["resident_bytes"] += retained_bytes - old_bytes
        write_json_atomic(resolve_ledger_path(root), ledger)
        return dict(entry)


def begin_approved_disposition(
    root: Path, *, path: Path | str, disposition_id: str,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Recheck lease and exact manager approval, then make it resumable."""

    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if (
            entry is None or entry.get("class") != "rebuildable_payload"
            or entry.get("status") not in {"ready", "retirement_pending"}
            or entry.get("pin") is not False
            or entry.get("disposition", {}).get("id") != disposition_id.upper()
        ):
            raise ValueError("manager-approved disposition differs from ledger")
        _assert_unleased(root, target)
        if entry["status"] == "ready":
            entry["status"] = "retirement_pending"
            write_json_atomic(destination, ledger)
        return dict(entry)


def retire_capacity_object(
    root: Path, *, path: Path | str, bytes_removed: int | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Record an already-completed whole-object retirement atomically."""

    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if (
            entry is None
            or entry.get("class") != "rebuildable_payload"
            or entry.get("status") != "ready"
            or entry.get("pin") is True
            or "disposition" in entry
        ):
            raise ValueError("ledger object is not eligible for retirement")
        _assert_unleased(root, target)
        amount = int(entry["bytes"] if bytes_removed is None else bytes_removed)
        if amount != int(entry["bytes"]):
            raise ValueError("ledger objects must be retired as one complete object")
        entry["status"] = "retired"
        entry["retired_at_utc"] = _utc_now()
        ledger["resident_bytes"] = int(ledger["resident_bytes"]) - amount
        write_json_atomic(destination, ledger)
    return entry


def recover_stale_atomic_ledger_temps(root: Path) -> dict[str, int]:
    """Retire crash-left ledger publication temps through the normal ledger.

    ``write_json_atomic`` has a bounded 0.75-second replacement retry.  A
    matching temp older than that interval, beside a valid current ledger, is
    therefore a failed publication residue rather than a new artifact.  This
    narrow owner recovery does not inspect its JSON payload or hash it.
    """

    root = root.resolve(strict=False)
    receipt_directory = root / "common" / "capacity_disposal_receipts"
    result = {"checked_count": 0, "retired_count": 0, "removed_bytes": 0,
              "fresh_count": 0, "invalid_count": 0, "replayed_count": 0}
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        now = time.time()
        candidates = [
            item for item in ledger["objects"]
            if item.get("status") in {"writing", "retirement_pending"}
            and item.get("owner") == "common.capacity_lifecycle"
            and Path(str(item.get("path", ""))).parent.as_posix() == "common"
            and Path(str(item.get("path", ""))).name.startswith(STALE_ATOMIC_TEMP_PREFIX)
        ]
        for entry in candidates:
            result["checked_count"] += 1
            target, relative = capacity_object_path(root, entry["path"])
            receipt = receipt_directory / f"atomic-ledger-temp-{target.name}.json"
            if entry["status"] == "retirement_pending" and not target.exists():
                try:
                    receipt_document = json.loads(receipt.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    result["invalid_count"] += 1
                    continue
                if (receipt_document.get("role") != "capacity_ledger_atomic_temp_recovery"
                        or receipt_document.get("status") not in {"retirement_pending", "retired"}
                        or receipt_document.get("target_path") != relative
                        or receipt_document.get("expected_bytes") != int(entry["bytes"])):
                    result["invalid_count"] += 1
                    continue
                entry["status"] = "retired"
                entry["retired_at_utc"] = _utc_now()
                entry.pop("retirement_error", None)
                ledger["resident_bytes"] -= int(entry["bytes"])
                receipt_document["status"] = "retired"
                receipt_document["removed_bytes"] = int(entry["bytes"])
                write_json_atomic(receipt, receipt_document)
                write_json_atomic(resolve_ledger_path(root), ledger)
                result["retired_count"] += 1
                result["removed_bytes"] += int(entry["bytes"])
                result["replayed_count"] += 1
                continue
            if target.is_symlink() or not target.is_file() or target.stat().st_size != int(entry["bytes"]):
                result["invalid_count"] += 1
                continue
            if (entry["status"] == "writing"
                    and now - target.stat().st_mtime < STALE_ATOMIC_TEMP_MINIMUM_AGE_SECONDS):
                result["fresh_count"] += 1
                continue
            _assert_unleased(root, target)
            if entry["status"] == "writing":
                entry["status"] = "retirement_pending"
                entry.pop("recovery_reason", None)
                entry.pop("recovery_task", None)
                entry.pop("recovery_evidence_paths", None)
                write_json_atomic(receipt, {
                    "schema_version": 1,
                    "role": "capacity_ledger_atomic_temp_recovery",
                    "status": "retirement_pending",
                    "target_path": relative,
                    "expected_bytes": int(entry["bytes"]),
                })
                write_json_atomic(resolve_ledger_path(root), ledger)
            try:
                target.unlink()
            except OSError as exc:
                entry["retirement_error"] = f"{type(exc).__name__}: {exc}"
                write_json_atomic(resolve_ledger_path(root), ledger)
                continue
            entry["status"] = "retired"
            entry["retired_at_utc"] = _utc_now()
            ledger["resident_bytes"] -= int(entry["bytes"])
            receipt_document = json.loads(receipt.read_text(encoding="utf-8-sig"))
            receipt_document["status"] = "retired"
            receipt_document["removed_bytes"] = int(entry["bytes"])
            write_json_atomic(receipt, receipt_document)
            write_json_atomic(resolve_ledger_path(root), ledger)
            result["retired_count"] += 1
            result["removed_bytes"] += int(entry["bytes"])
    return result


def reconcile_pa_runtime_state(root: Path) -> dict[str, int]:
    """Mark the cache's reusable lock and staging directories as ready state.

    They are small cache-runtime directories, not interrupted PA payloads.
    Reclassification preserves their owner and bytes, performs no removal, and
    prevents a durable lock file from appearing as an unbounded recovery job.
    """

    root = root.resolve(strict=False)
    result = {"checked_count": 0, "ready_count": 0, "ready_bytes": 0, "invalid_count": 0}
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        changed = False
        for entry in ledger["objects"]:
            if entry.get("path") not in PA_RUNTIME_STATE_RELATIVE_PATHS:
                continue
            result["checked_count"] += 1
            target, _ = capacity_object_path(root, entry["path"])
            if target.is_symlink() or not target.is_dir():
                result["invalid_count"] += 1
                continue
            if entry.get("status") == "ready" and entry.get("class") == "light_evidence":
                continue
            if not (
                entry.get("status") == "writing"
                and entry.get("class") == "rebuildable_payload"
                and entry.get("owner") == "common.simion.pa_family_cache"
                and entry.get("recovery_reason") == "pa_runtime_state_recovery_required"
            ):
                result["invalid_count"] += 1
                continue
            entry["status"] = "ready"
            entry["class"] = "light_evidence"
            entry.pop("recovery_reason", None)
            entry.pop("recovery_task", None)
            entry.pop("recovery_evidence_paths", None)
            result["ready_count"] += 1
            result["ready_bytes"] += int(entry["bytes"])
            changed = True
        if changed:
            write_json_atomic(resolve_ledger_path(root), ledger)
    return result


def pending_disposal_targets(root: Path, path: Path | None = None) -> set[Path]:
    """Return exact targets whose validated ledger state is retirement-pending."""

    root = root.resolve(strict=False)
    ledger = load_capacity_ledger(root, path)
    if ledger is None:
        raise ValueError("capacity ledger is missing or invalid; pending state is unknown")
    return {
        (root / Path(item["path"])).resolve(strict=False)
        for item in ledger["objects"]
        if item.get("status") == "retirement_pending"
        or (item.get("status") != "retired" and "disposition" in item)
    }


def mark_retirement_pending(
    root: Path, *, path: Path | str, ledger_path: Path | None = None,
) -> int:
    """Recheck admission and publish pending state within one short lock."""

    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        _assert_unleased(root, target)
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if entry is None or entry.get("status") not in {"ready", "retirement_pending"} or entry.get("pin") is True:
            raise ValueError(f"ledger object is no longer removable: {target}")
        if entry.get("class") != "rebuildable_payload" or "disposition" in entry:
            raise ValueError(f"ledger object class is not removable: {target}")
        if entry["status"] == "ready":
            entry["status"] = "retirement_pending"
            entry.pop("retirement_error", None)
            write_json_atomic(destination, ledger)
        return int(entry["bytes"])


def record_retirement_error(
    root: Path, *, path: Path | str, error: str, ledger_path: Path | None = None,
) -> None:
    """Persist an interrupted retirement reason while leaving it resumable."""

    root = root.resolve(strict=False)
    _, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            return
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if entry is not None and entry.get("status") == "retirement_pending":
            entry["retirement_error"] = error
            write_json_atomic(destination, ledger)


def finalize_retirement(
    root: Path, *, path: Path | str, removed_bytes: int, ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Finalize one pending retirement and debit its calibrated byte count."""

    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger became invalid while retirement was in progress")
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if entry is None or entry.get("status") != "retirement_pending":
            raise ValueError("capacity ledger retirement state changed before finalization")
        expected = int(entry["bytes"])
        if removed_bytes != expected:
            raise ValueError(f"removed byte count {removed_bytes} differs from ledger {expected}")
        entry["status"] = "retired"
        entry["retired_at_utc"] = _utc_now()
        entry.pop("retirement_error", None)
        ledger["resident_bytes"] = int(ledger["resident_bytes"]) - removed_bytes
        write_json_atomic(destination, ledger)
        return entry


def update_external_scope_bytes(
    root: Path, *, role: str, path: Path, expected_bytes: int, new_bytes: int,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically update one calibration-only external scope after exact disposal."""

    if role not in EXTERNAL_SCOPE_ROLES or min(expected_bytes, new_bytes) < 0:
        raise ValueError("external scope update values are invalid")
    root = root.resolve(strict=False)
    destination = resolve_ledger_path(root, ledger_path)
    canonical = str(path.resolve(strict=False))
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = next((item for item in ledger["external_scopes"] if item["role"] == role), None)
        if entry is None or entry["path"] != canonical or int(entry["bytes"]) != expected_bytes:
            raise ValueError("external scope record differs from approved disposition")
        entry["bytes"] = new_bytes
        ledger["resident_bytes"] += new_bytes - expected_bytes
        write_json_atomic(destination, ledger)
        return dict(entry)


def record_external_scope(
    root: Path, *, role: str, path: Path, bytes_count: int,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Register one measured workspace range without rediscovering artifacts."""

    if role not in EXTERNAL_SCOPE_ROLES or isinstance(bytes_count, bool) or bytes_count < 0:
        raise ValueError("external scope record is invalid")
    root = root.resolve(strict=False)
    destination = resolve_ledger_path(root, ledger_path)
    canonical = str(path.resolve(strict=False))
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        existing = next((item for item in ledger["external_scopes"] if item["role"] == role), None)
        if existing is not None:
            if existing["path"] != canonical or int(existing["bytes"]) != bytes_count:
                raise ValueError("external scope differs from its calibrated record")
            return dict(existing)
        if any(item["path"] == canonical for item in ledger["external_scopes"]):
            raise ValueError("external scope path is already registered")
        entry = {"role": role, "path": canonical, "bytes": bytes_count}
        ledger["external_scopes"].append(entry)
        ledger["external_scopes"].sort(key=lambda item: item["role"])
        ledger["resident_bytes"] += bytes_count
        write_json_atomic(destination, ledger)
        return dict(entry)
