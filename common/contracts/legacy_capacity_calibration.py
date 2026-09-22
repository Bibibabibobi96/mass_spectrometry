"""Inventory legacy artifacts before the trusted capacity ledger is initialized.

The inventory is deliberately metadata-only: it reads small manifests and
pointers and compares recorded byte counts, but never hashes payload files.
Nothing is deleted.  Ambiguous objects remain explicit review items and block
ledger initialization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from common.contracts import capacity_ledger, capacity_protection
from common.contracts.artifact_retention import (
    classify_file,
    validate_retention,
)
from common.contracts.recorded_file_removal import write_json_atomic
from common.contracts.verify_artifact_layout import INTEGRATION_CACHE_ROLES


SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
LEGACY_LEDGER_KEYS = {
    "schema_version", "role", "status", "complete", "artifact_root",
    "resident_bytes", "objects",
}
LEDGER_MIGRATION_DIRECTORY = Path("common") / "capacity_calibration" / "ledger_migrations"
COMMON_CAPACITY_LIFECYCLE_ROOTS = {
    "capacity_disposal_receipts",
    "capacity_calibration",
    "capacity_protection_leases",
}
COMMON_GOVERNANCE_OWNERS = {
    "execution_aliases": "common.run_artifact_support",
    "host_resources.sqlite3": "common.host_resources",
}
TERMINAL_RUN_STATUSES = {
    "success", "completed", "failed", "interrupted", "cancelled", "aborted",
}
HEAVY_RETENTION_ROLES = {
    "solver_native_binary", "dense_trajectory", "large_optional",
}
FROZEN_INPUT_CACHE_ROLES = {
    "native_corridor_frozen_inputs": (
        "native_corridor_freeze_manifest.json",
        "mrtof_native_corridor_frozen_inputs",
    ),
}
LEGACY_PROJECT_EVIDENCE_DIRECTORIES = {
    "paper1_stage_evidence",
    "resolution_matrix_20260820",
    "resolution_matrix_20260822",
}
LEGACY_SCRATCH_ENGINEERING_SOURCE_DIRECTORIES = {
    (
        "parallel_mirror_dual_stripe_mr_tof",
        "20260902__ion-foil-recovery",
    ),
    (
        "dual_cone_tandem_quadrupole_ion_interface",
        "20260914_084035__dual-cone__gas-field",
    ),
}
SCRATCH_LIGHT_EVIDENCE_MAX_BYTES = 1024 * 1024
SCRATCH_LIGHT_ROLE_SUFFIXES = (
    "_report",
    "_receipt",
    "_summary",
    "_metrics",
    "_root_cause",
)


class CalibrationError(ValueError):
    """Raised when a calibration request or trusted metadata is invalid."""


CalibrationProgress = Callable[[str, Path], None]


def _report_progress(
    progress: CalibrationProgress | None, event: str, path: Path,
) -> None:
    """Emit an optional coarse-grained scan checkpoint.

    Calibration deliberately measures every declared scope once.  On a large
    PA repository that metadata walk can take long enough that a caller needs
    proof it is still scanning rather than waiting on ledger initialization.
    The callback never reports individual files or reads payload contents.
    """

    if progress is not None:
        progress(event, path)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*") if item.is_file())


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for member in value.values():
            yield from _strings(member)
    elif isinstance(value, (list, tuple)):
        for member in value:
            yield from _strings(member)
    elif isinstance(value, str):
        yield value


def _bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in _files(path))


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise CalibrationError(f"inventory path escapes artifact root: {path}") from exc


def _owner_hint(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root)
    parts = relative.parts
    if len(parts) >= 2 and parts[0] == "projects":
        return parts[1]
    if parts and parts[0] == "common":
        return "common"
    return "artifact_root_maintainer"


def _candidate(
    root: Path, path: Path, object_class: str, *, identity: str | None = None,
    status: str = "ready", pin: bool = False, pin_reason: str | None = None,
    evidence: Iterable[Path] = (), recovery_reason: str | None = None,
    owner_hint: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": _relative(root, path),
        "class": object_class,
        "bytes": _bytes(path),
        "status": status,
        "pin": pin,
        "owner_hint": _owner_hint(root, path) if owner_hint is None else owner_hint,
        "evidence_paths": [_relative(root, item) for item in evidence],
    }
    if identity is not None:
        item["identity"] = identity.upper()
    if pin:
        item["pin_reason"] = pin_reason or "legacy scientific evidence"
    if recovery_reason is not None:
        item["recovery_reason"] = recovery_reason
    return item


def _unresolved(
    root: Path, path: Path, reason: str, review_deadline: str,
    *, evidence: Iterable[Path] = (), owner_hint: str | None = None,
    recovery_task: str | None = None,
) -> dict[str, Any]:
    return {
        "path": _relative(root, path),
        "bytes": _bytes(path),
        "reason": reason,
        "owner_hint": _owner_hint(root, path) if owner_hint is None else owner_hint,
        "review_deadline": review_deadline,
        "evidence_paths": [_relative(root, item) for item in evidence],
        **({"recovery_task": recovery_task} if recovery_task is not None else {}),
    }


def _recorded_members_match(directory: Path, manifest: dict[str, Any]) -> bool:
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        return False
    for record in records:
        if not isinstance(record, dict):
            return False
        name, count = record.get("name"), record.get("bytes")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            return False
        member = directory / name
        if not member.is_file() or member.stat().st_size != count:
            return False
    return True


def _scratch_is_small_named_evidence(path: Path) -> bool:
    """Recognize only bounded, explicitly role-labelled scratch evidence."""

    if path.suffix.casefold() != ".json":
        return False
    if path.stat().st_size > SCRATCH_LIGHT_EVIDENCE_MAX_BYTES:
        return False
    document = _load_json(path)
    role = None if document is None else document.get("role")
    return (
        isinstance(role, str)
        and role.casefold().endswith(SCRATCH_LIGHT_ROLE_SUFFIXES)
    )


def _common_pa_runtime_state(
    root: Path, path: Path, *, reason: str,
) -> dict[str, Any]:
    """Account PA transaction/lock state without treating it as a cache key."""

    return _candidate(
        root, path, "rebuildable_payload", status="writing",
        recovery_reason=reason, owner_hint="common.simion.pa_family_cache",
    )


def _execution_alias_root(root: Path, path: Path, review_deadline: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate disposable junction aliases without double-counting targets."""

    root_resolved = root.resolve(strict=False)
    for alias in sorted(path.iterdir()):
        try:
            target = alias.resolve(strict=True)
            target.relative_to(root_resolved)
        except (OSError, RuntimeError, ValueError):
            return None, _unresolved(
                root, path, "execution_alias_target_missing_or_escapes_artifact_root",
                review_deadline,
            )
        attributes = getattr(alias.lstat(), "st_file_attributes", 0)
        if not alias.is_dir() or not (attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return None, _unresolved(
                root, path, "execution_alias_root_contains_non_junction_entry",
                review_deadline,
            )
    # Junction payload is already represented by its target object.  Recording
    # this zero-byte administrative root makes the declared scope explicit
    # while preserving the physical resident-byte invariant.
    return _candidate(root, path, "light_evidence", owner_hint="common.run_artifact_support"), None


def _common_pa_cache(
    root: Path, key: Path, review_deadline: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    pointer_path = key / "current_generation.json"
    pointer = _load_json(pointer_path)
    generation = "" if pointer is None else str(pointer.get("generation_sha256", ""))
    selected = key / "generations" / generation
    manifest_path = selected / "cache_manifest.json"
    manifest = _load_json(manifest_path)
    valid = (
        SHA256.fullmatch(key.name) is not None
        and pointer is not None
        and pointer.get("cache_key", "").casefold() == key.name.casefold()
        and SHA256.fullmatch(generation) is not None
        and pointer.get("generation_relative_path", f"generations/{generation}")
        == f"generations/{generation}"
        and manifest is not None
        and manifest.get("role") == "simion_pa_family_cache"
        and str(manifest.get("cache_key", "")).casefold() == key.name.casefold()
        and str(manifest.get("generation_sha256", "")).casefold() == generation.casefold()
        and selected.is_dir()
        and _recorded_members_match(selected, manifest)
    )
    evidence = (pointer_path, manifest_path)
    if valid:
        transaction_path = key.parent / ".transactions" / key.name / "transaction.json"
        transaction = _load_json(transaction_path)
        transaction_bound = (
            transaction is not None
            and transaction.get("schema_version") == 1
            and transaction.get("role") == "simion_pa_family_cache_transaction"
            and transaction.get("status") == "published"
            and str(transaction.get("cache_key", "")).casefold() == key.name.casefold()
            and str(transaction.get("generation_sha256", "")).casefold() == generation.casefold()
            and isinstance(transaction.get("owner"), str)
            and bool(transaction["owner"].strip())
            and isinstance(transaction.get("verification"), dict)
        )
        if transaction_bound:
            candidate = _candidate(
                root, key, "published_cache", identity=generation,
                evidence=(*evidence, transaction_path),
            )
            candidate["manager"] = capacity_ledger.PA_CACHE_MANAGER
            return candidate, None
        # A pointer and manifest establish byte identity, but never establish
        # who may recover, consume, or retire it.  Preserve the exact object
        # as governed writing state until its real owner restores a transaction
        # or creates an authorized disposition; do not invent either record.
        return _candidate(
            root, key, "published_cache", identity=generation,
            status="writing", evidence=(*evidence, transaction_path),
            recovery_reason="legacy_pa_cache_missing_owner_transaction",
            owner_hint="common.simion.pa_family_cache",
        ), None
    return None, _unresolved(
        root, key, "common_pa_cache_identity_chain_incomplete",
        review_deadline, evidence=evidence,
    )


def _multipole_basis_cache(
    root: Path, key: Path, review_deadline: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    manifest_path = key / "manifest.json"
    manifest = _load_json(manifest_path)
    valid = (
        SHA256.fullmatch(key.name) is not None
        and manifest is not None
        and manifest.get("role") == "multipole_simion_pa_basis_cache"
        and str(manifest.get("fingerprint_sha256", "")).casefold()
        == key.name.casefold()
        and _recorded_members_match(key, manifest)
    )
    if valid:
        return _candidate(
            root, key, "published_cache", identity=key.name,
            evidence=(manifest_path,),
        ), None
    return None, _unresolved(
        root, key, "multipole_basis_cache_manifest_or_member_metadata_differs",
        review_deadline, evidence=(manifest_path,),
    )


def _integration_cache(
    root: Path, cache_role_root: Path, key: Path, review_deadline: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    pointer_path = key / "current_generation.json"
    pointer = _load_json(pointer_path)
    allowed = INTEGRATION_CACHE_ROLES.get(cache_role_root.name, set())
    if pointer is None:
        if cache_role_root.name == "verified_pulse":
            receipt_path = key / "verified_pulse_timing_receipt.json"
            receipt = _load_json(receipt_path)
            valid_receipt = (
                SHA256.fullmatch(key.name) is not None
                and receipt is not None
                and receipt.get("role") in allowed
                and receipt.get("status") == "success"
                and receipt.get("reusable_verified_pulse") is True
                and str(receipt.get("content_key", "")).casefold()
                == key.name.casefold()
                and {item.name for item in key.iterdir()}
                == {"verified_pulse_timing_receipt.json"}
            )
            if valid_receipt:
                return _candidate(
                    root, key, "published_cache", identity=key.name,
                    evidence=(receipt_path,),
                ), None
        manifest_path = key / "cache_manifest.json"
        manifest = _load_json(manifest_path)
        valid_legacy = (
            SHA256.fullmatch(key.name) is not None
            and manifest is not None
            and manifest.get("role") in allowed
            and str(manifest.get("cache_key", key.name)).casefold()
            == key.name.casefold()
            and _recorded_members_match(key, manifest)
        )
        if valid_legacy:
            return _candidate(
                root, key, "published_cache", identity=key.name,
                evidence=(manifest_path,),
            ), None
        return None, _unresolved(
            root, key, "project_cache_identity_chain_incomplete",
            review_deadline, evidence=(manifest_path,),
        )
    generation = "" if pointer is None else str(pointer.get("generation_sha256", ""))
    selected = key / "generations" / generation
    manifest_path = selected / "cache_manifest.json"
    manifest = _load_json(manifest_path)
    valid = (
        SHA256.fullmatch(key.name) is not None
        and pointer is not None
        and pointer.get("cache_key", "").casefold() == key.name.casefold()
        and SHA256.fullmatch(generation) is not None
        and pointer.get("generation_relative_path") == f"generations/{generation}"
        and manifest is not None
        and manifest.get("role") in allowed
        and str(manifest.get("cache_key", "")).casefold() == key.name.casefold()
        and str(manifest.get("generation_sha256", "")).casefold() == generation.casefold()
        and selected.is_dir()
        and _recorded_members_match(selected, manifest)
    )
    evidence = (pointer_path, manifest_path)
    if valid:
        return _candidate(
            root, key, "published_cache", identity=generation, evidence=evidence,
        ), None
    return None, _unresolved(
        root, key, "project_cache_identity_chain_incomplete",
        review_deadline, evidence=evidence,
    )


def _frozen_input_cache(
    root: Path, role_root: Path, key: Path, review_deadline: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    manifest_name, expected_role = FROZEN_INPUT_CACHE_ROLES[role_root.name]
    manifest_path = key / manifest_name
    manifest = _load_json(manifest_path)
    valid = (
        SHA256.fullmatch(key.name) is not None
        and manifest is not None
        and manifest.get("role") == expected_role
        and manifest.get("status") == "frozen"
        and str(manifest.get("pa_family_cache_key", "")).casefold()
        == key.name.casefold()
        and _recorded_members_match(key, manifest)
    )
    if valid:
        return _candidate(
            root, key, "published_cache", identity=key.name,
            evidence=(manifest_path,),
        ), None
    return None, _unresolved(
        root, key, "frozen_input_cache_manifest_or_member_metadata_differs",
        review_deadline, evidence=(manifest_path,),
        recovery_task=(
            "project cache owner must restore the frozen-input manifest and its "
            "member inventory, or retire this exact cache key through its owner"
        ),
    )


def _review_package_unresolved(
    root: Path, project: Path, reviews: Path, review_deadline: str,
) -> dict[str, Any]:
    """Keep review copies out of the ledger until a sealed lifecycle receipt exists."""

    evidence = tuple(sorted(
        path for path in reviews.rglob("*.json")
        if path.name.casefold().endswith(("receipt.json", "manifest.json"))
    ))
    return _unresolved(
        root, reviews, "review_package_lacks_sealed_owner_disposition_manifest",
        review_deadline, evidence=evidence, owner_hint=project.name,
        recovery_task=(
            "project owner must publish a sealed review-package manifest with "
            "content inventory, source identity, consumer protection and owner "
            "retirement/disposition semantics; otherwise remove it through an "
            "owner-authorized recorded-file disposition"
        ),
    )


def _run_objects(
    root: Path, run: Path, review_deadline: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config_path = run / "run_config.json"
    manifest_path = run / "run_manifest.json"
    summary_path = run / "summary.json"
    config = _load_json(config_path)
    summary = _load_json(summary_path)
    manifest = _load_json(manifest_path)
    evidence = (config_path, summary_path, manifest_path)
    if config is None or summary is None or manifest is None:
        return [
            _candidate(
                root, path,
                (
                    "rebuildable_payload"
                    if classify_file(path) in HEAVY_RETENTION_ROLES
                    else "light_evidence"
                ),
                status="writing", evidence=evidence,
                recovery_reason="run_contract_missing_or_invalid",
            )
            for path in _files(run)
        ], []
    if manifest.get("status") not in TERMINAL_RUN_STATUSES:
        return [_candidate(
            root, run, "rebuildable_payload", status="writing", evidence=evidence,
            recovery_reason="run_manifest_not_terminal",
        )], []
    retention_value = config.get("artifact_retention")
    if manifest.get("schema_version") == 2:
        try:
            retention = validate_retention(retention_value)
        except ValueError:
            return [], [_unresolved(
                root, run, "run_retention_contract_invalid", review_deadline,
                evidence=evidence,
            )]
        if manifest.get("artifact_retention") != retention_value:
            return [], [_unresolved(
                root, run, "run_retention_identity_differs", review_deadline,
                evidence=evidence,
            )]
    else:
        retention = None

    if retention is not None and retention.class_id == "qualification":
        return [_candidate(
            root, run, "light_evidence", pin=True,
            pin_reason=f"qualification run: {retention.reason}", evidence=evidence,
        )], []

    heavy = [path for path in _files(run) if classify_file(path) in HEAVY_RETENTION_ROLES]
    if heavy:
        if retention is None:
            heavy_set = set(heavy)
            return [
                _candidate(
                    root, path,
                    "rebuildable_payload" if path in heavy_set else "light_evidence",
                    evidence=evidence,
                )
                for path in _files(run)
            ], []
        heavy_set = set(heavy)
        split = [
            _candidate(
                root, path,
                "rebuildable_payload" if path in heavy_set else "light_evidence",
                evidence=evidence,
            )
            for path in _files(run)
        ]
        return split, []
    return [_candidate(root, run, "light_evidence", evidence=evidence)], []


def _classify_project(
    root: Path, project: Path, review_deadline: str,
    *, progress: CalibrationProgress | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objects: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for child in sorted(project.iterdir()):
        if child.name == "runs" and child.is_dir():
            runs = sorted(item for item in child.iterdir() if item.is_dir())
            for index, run in enumerate(runs, start=1):
                if index == 1 or index == len(runs) or index % 25 == 0:
                    _report_progress(progress, "scan_project_runs", run)
                found, pending = _run_objects(root, run, review_deadline)
                objects.extend(found)
                unresolved.extend(pending)
        elif child.name == "formal" and child.is_dir():
            manifest = child / "asset_manifest.json"
            document = _load_json(manifest)
            if document is not None and document.get("role") == "formal_asset_manifest":
                objects.append(_candidate(
                    root, child, "light_evidence", pin=True,
                    pin_reason="formal project assets", evidence=(manifest,),
                ))
            else:
                unresolved.append(_unresolved(
                    root, child, "formal_asset_manifest_missing_or_invalid",
                    review_deadline, evidence=(manifest,),
                ))
        elif child.name == "archive" and child.is_dir():
            for archive in sorted(item for item in child.iterdir() if item.is_dir()):
                manifest = archive / "archive_manifest.json"
                document = _load_json(manifest)
                if (
                    document is not None
                    and document.get("role") == "artifact_identity_archive_manifest"
                ):
                    objects.append(_candidate(
                        root, archive, "light_evidence", pin=True,
                        pin_reason="immutable project archive", evidence=(manifest,),
                    ))
                else:
                    objects.append(_candidate(
                        root, archive, "light_evidence", pin=True,
                        pin_reason=(
                            "legacy archive preservation intent; archive manifest "
                            f"repair required by {review_deadline}"
                        ),
                        evidence=(manifest,),
                    ))
        elif child.name == "reviews" and child.is_dir():
            # A GUI review package can contain copied PA payloads.  Existing
            # lightweight receipts identify observations but do not prove a
            # complete owner/disposition chain, so it remains explicit pending
            # work instead of being silently treated as evidence or cache.
            unresolved.append(_review_package_unresolved(
                root, project, child, review_deadline,
            ))
        elif child.name == "scratch" and child.is_dir():
            for task in sorted(child.iterdir()):
                preserve_engineering_source = (
                    project.name, task.name
                ) in LEGACY_SCRATCH_ENGINEERING_SOURCE_DIRECTORIES
                for path in _files(task):
                    if preserve_engineering_source:
                        objects.append(_candidate(
                            root, path, "light_evidence", pin=True,
                            pin_reason=(
                                "legacy engineering source pending promotion by "
                                f"{review_deadline}"
                            ),
                        ))
                        continue
                    light_evidence = _scratch_is_small_named_evidence(path)
                    objects.append(_candidate(
                        root, path,
                        (
                            "light_evidence"
                            if light_evidence else "rebuildable_payload"
                        ),
                    ))
        elif child.name == "cache" and child.is_dir():
            for role_root in sorted(child.iterdir()):
                if not role_root.is_dir():
                    unresolved.append(_unresolved(
                        root, role_root, "project_cache_entry_is_not_a_provider_directory",
                        review_deadline,
                    ))
                    continue
                for key in sorted(role_root.iterdir()):
                    if key.name in {".locks", ".staging"} and _bytes(key) == 0:
                        continue
                    if role_root.name == "simion_pa_basis" and key.is_dir():
                        candidate, pending = _multipole_basis_cache(root, key, review_deadline)
                    elif role_root.name in INTEGRATION_CACHE_ROLES and key.is_dir():
                        candidate, pending = _integration_cache(
                            root, role_root, key, review_deadline,
                        )
                    elif role_root.name in FROZEN_INPUT_CACHE_ROLES and key.is_dir():
                        candidate, pending = _frozen_input_cache(
                            root, role_root, key, review_deadline,
                        )
                    else:
                        candidate, pending = None, _unresolved(
                            root, key, "project_cache_provider_or_layout_unrecognized",
                            review_deadline,
                        )
                    (objects if candidate else unresolved).append(candidate or pending)
        elif child.is_file() and child.name == "00_README.txt":
            objects.append(_candidate(root, child, "light_evidence"))
        elif child.is_dir() and child.name in LEGACY_PROJECT_EVIDENCE_DIRECTORIES:
            objects.append(_candidate(
                root, child, "light_evidence", pin=True,
                pin_reason=(
                    "legacy report or resolution-matrix evidence pending migration "
                    f"by {review_deadline}"
                ),
            ))
        else:
            unresolved.append(_unresolved(
                root, child, "project_artifact_role_unrecognized", review_deadline,
            ))
    return objects, unresolved


def _active_structured_references(root: Path) -> dict[str, set[str]]:
    run_paths = {
        run.name.casefold(): _relative(root, run)
        for run in root.glob("projects/*/runs/*")
        if run.is_dir()
    }
    references: dict[str, set[str]] = {}
    root_text = root.as_posix().rstrip("/").casefold()
    for run in root.glob("projects/*/runs/*"):
        if not run.is_dir():
            continue
        manifest = _load_json(run / "run_manifest.json")
        if manifest is not None and manifest.get("status") in TERMINAL_RUN_STATUSES:
            continue
        consumer = _relative(root, run)
        for document in (_load_json(run / "run_config.json"), manifest):
            if document is None:
                continue
            for value in _strings(document):
                normalized = value.strip().replace("\\", "/").rstrip("/")
                lowered = normalized.casefold()
                relative: str | None = None
                if lowered.startswith(root_text + "/"):
                    relative = normalized[len(root_text) + 1:]
                else:
                    marker = lowered.rfind("/artifacts/")
                    if marker >= 0:
                        relative = normalized[marker + len("/artifacts/"):]
                    elif lowered.startswith(("projects/", "common/")):
                        relative = normalized
                    elif lowered in run_paths:
                        relative = run_paths[lowered]
                if relative:
                    key = relative.replace("\\", "/").casefold()
                    references.setdefault(key, set()).add(consumer)
    return references


def _protect_active_dependencies(
    root: Path, objects: list[dict[str, Any]],
) -> tuple[int, int, dict[str, Any]]:
    references = _active_structured_references(root)
    leases = capacity_protection.load_capacity_protection_leases(root)
    count = 0
    bytes_count = 0
    for item in objects:
        if item["class"] != "rebuildable_payload" or item["status"] != "ready":
            continue
        identity = item["path"].casefold()
        consumers: set[str] = set()
        for reference, reference_consumers in references.items():
            if (
                identity == reference
                or identity.startswith(reference + "/")
                or reference.startswith(identity + "/")
            ):
                consumers.update(reference_consumers)
        referenced = bool(consumers)
        target = root / item["path"]
        leased = capacity_protection.path_is_protected(
            target, leases["protected_paths"],
        )
        if referenced or leased:
            item["status"] = "writing"
            item["active_protection"] = (
                "structured_nonterminal_run_reference" if referenced
                else "capacity_protection_lease"
            )
            if consumers:
                item["active_consumers"] = sorted(consumers)
            count += 1
            bytes_count += int(item["bytes"])
    return count, bytes_count, leases


def _workspace_external_scopes(
    artifact_root: Path, workspace_root: Path, *, progress: CalibrationProgress | None = None,
) -> list[dict[str, Any]]:
    """Measure the two declared source-tree working roots during calibration only."""

    declared = _declared_workspace_scope_paths(artifact_root, workspace_root)
    scopes: list[dict[str, Any]] = []
    for role, target in declared:
        _report_progress(progress, "scan_workspace_scope", target)
        if target.exists() and not target.is_dir():
            raise CalibrationError(f"declared workspace scope is not a directory: {target}")
        scopes.append({"role": role, "path": str(target), "bytes": 0 if not target.exists() else _bytes(target)})
    return scopes


def _declared_workspace_scope_paths(
    artifact_root: Path, workspace_root: Path,
) -> list[tuple[str, Path]]:
    """Return the two fixed source-tree scope paths without touching contents."""

    workspace = workspace_root.resolve(strict=False)
    root = artifact_root.resolve(strict=False)
    if workspace == root or workspace in root.parents or root in workspace.parents:
        raise CalibrationError(
            "workspace_root must be distinct from artifact_root to avoid double counting"
        )
    return [
        ("repository_scratch", (workspace / "scratch").resolve(strict=False)),
        ("repository_generated", (workspace / "generated").resolve(strict=False)),
    ]


def build_calibration_inventory(
    artifact_root: Path, *, review_deadline: str, workspace_root: Path | None = None,
    progress: CalibrationProgress | None = None,
) -> dict[str, Any]:
    """Return a metadata-only inventory; never hash or remove payload files."""

    root = artifact_root.resolve()
    try:
        date.fromisoformat(review_deadline)
    except ValueError as exc:
        raise CalibrationError("review_deadline must be YYYY-MM-DD") from exc
    if not root.is_dir():
        raise CalibrationError("artifact_root must be an existing directory")
    external_scopes = (
        _workspace_external_scopes(root, workspace_root, progress=progress)
        if workspace_root is not None else []
    )
    objects: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        _report_progress(progress, "scan_artifact_root_entry", child)
        if child.name == "common" and child.is_dir():
            for common_child in sorted(child.iterdir()):
                if common_child.name == "simion" and common_child.is_dir():
                    cache = common_child / "pa_family_cache"
                    for entry in sorted(common_child.iterdir()):
                        if entry != cache:
                            unresolved.append(_unresolved(
                                root, entry, "common_simion_role_unrecognized",
                                review_deadline,
                            ))
                    if cache.is_dir():
                        for key in sorted(cache.iterdir()):
                            if key.name == ".transactions":
                                objects.append(_common_pa_runtime_state(
                                    root, key, reason="pa_transaction_recovery_required",
                                ))
                                continue
                            if key.name in {".locks", ".staging", ".build-locks"}:
                                objects.append(_common_pa_runtime_state(
                                    root, key, reason="pa_runtime_state_recovery_required",
                                ))
                                continue
                            candidate, pending = _common_pa_cache(root, key, review_deadline)
                            (objects if candidate else unresolved).append(candidate or pending)
                elif common_child.name == "execution_aliases" and common_child.is_dir():
                    candidate, pending = _execution_alias_root(root, common_child, review_deadline)
                    (objects if candidate else unresolved).append(candidate or pending)
                elif common_child.name in {
                    "capacity_protection_leases", "capacity_disposal_receipts", "host_resources.sqlite3",
                }:
                    objects.append(_candidate(root, common_child, "light_evidence"))
                elif common_child.name == "capacity_calibration" and common_child.is_dir():
                    # Calibration receipts describe the governed snapshot and cannot
                    # recursively account for their own bytes.
                    continue
                elif common_child.name.startswith(".capacity_ledger.json.") and common_child.is_file():
                    current = common_child.with_name("capacity_ledger.json")
                    unresolved.append(_unresolved(
                        root, common_child, "stale_capacity_ledger_atomic_temp_requires_recovery",
                        review_deadline, evidence=((current,) if current.is_file() else ()),
                        owner_hint="common.capacity_ledger",
                        recovery_task=(
                            "capacity ledger owner must validate the atomic publication lineage "
                            "against the current ledger, then remove this exact temporary file "
                            "through the recorded recovery/disposition path"
                        ),
                    ))
                elif common_child.name != "capacity_ledger.json":
                    unresolved.append(_unresolved(
                        root, common_child, "common_artifact_role_unrecognized",
                        review_deadline,
                    ))
        elif child.name in {"scratch", "generated"} and child.is_dir():
            # These top-level working areas are outside project run layouts but
            # occupy the same governed volume.  A calibration accounts for them
            # as recoverable writing state; startup later reads the ledger and
            # never repeats this walk.
            objects.append(_candidate(
                root, child, "rebuildable_payload", status="writing",
                recovery_reason="top_level_runtime_payload_requires_owner_review",
            ))
        elif child.name == "projects" and child.is_dir():
            for project in sorted(child.iterdir()):
                if project.is_dir():
                    _report_progress(progress, "scan_project", project)
                    found, pending = _classify_project(
                        root, project, review_deadline, progress=progress,
                    )
                    objects.extend(found)
                    unresolved.extend(pending)
                else:
                    unresolved.append(_unresolved(
                        root, project, "projects_root_entry_is_not_a_project_directory",
                        review_deadline,
                    ))
        else:
            unresolved.append(_unresolved(
                root, child, "artifact_root_role_unrecognized", review_deadline,
            ))
    protected_count, protected_bytes, leases = _protect_active_dependencies(root, objects)
    for item in objects:
        # The calibrated item is the managed range.  Its single owner covers
        # the files beneath it; class/status select the existing retention or
        # manager exit path.  Do not copy run/PA lifecycle prose into the
        # accounting ledger.
        item["owner"] = item["owner_hint"]
        if item["status"] == "writing":
            item["review_deadline"] = review_deadline
            item["recovery_reason"] = item.get(
                "recovery_reason", item.get("active_protection", "legacy_writing_object"),
            )
            item["recovery_task"] = item.get(
                "recovery_task", "legacy calibrated recovery requires explicit owner action",
            )
            item["recovery_evidence_paths"] = sorted(set(
                item.get("evidence_paths", []) or [item["path"]]
            ))
            if item.get("active_consumers"):
                item["consumers"] = sorted(set(item["active_consumers"]))
    objects.sort(key=lambda item: item["path"])
    unresolved.sort(key=lambda item: item["path"])
    writing_objects = [item for item in objects if item["status"] == "writing"]
    today = datetime.now(timezone.utc).date()
    initialization_blockers: list[dict[str, Any]] = []
    for item in writing_objects:
        missing = [
            field for field in (
                "owner", "review_deadline", "recovery_reason", "recovery_task",
            )
            if not isinstance(item.get(field), str) or not item[field].strip()
        ]
        try:
            item_deadline = date.fromisoformat(str(item.get("review_deadline", "")))
        except ValueError:
            item_deadline = None
        reason: str | None = None
        if missing or item_deadline is None:
            reason = "writing_recovery_contract_incomplete"
        elif today > item_deadline:
            reason = "writing_recovery_deadline_expired"
        if reason is not None:
            initialization_blockers.append({
                "path": item["path"],
                "bytes": int(item["bytes"]),
                "reason": reason,
                "owner_hint": item["owner_hint"],
                "review_deadline": str(item.get("review_deadline", review_deadline)),
                **(
                    {"active_consumers": item["active_consumers"]}
                    if item.get("active_consumers") else {}
                ),
            })
    classified_bytes = sum(item["bytes"] for item in objects)
    unresolved_bytes = sum(item["bytes"] for item in unresolved)
    blocker_bytes = sum(item["bytes"] for item in initialization_blockers)
    unresolved_overdue = (
        bool(unresolved) and today > date.fromisoformat(review_deadline)
    )
    overdue = unresolved_overdue or any(
        item["reason"] == "writing_recovery_deadline_expired"
        for item in initialization_blockers
    )
    recovery_required = [
        {
            "path": item["path"],
            "bytes": int(item["bytes"]),
            "reason": item["recovery_reason"],
            "owner_hint": item["owner_hint"],
            "review_deadline": item["review_deadline"],
            "status": "writing",
            **(
                {"active_consumers": item["active_consumers"]}
                if item.get("active_consumers") else {}
            ),
        }
        for item in writing_objects
    ]
    return {
        "schema_version": 1,
        "role": "legacy_capacity_calibration_inventory",
        "status": (
            "calibration_review_overdue"
            if overdue
            else (
                "calibration_pending"
                if unresolved or initialization_blockers
                else "ready_to_initialize"
            )
        ),
        "complete": not unresolved and not initialization_blockers,
        "artifact_root": str(root),
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "review_deadline": review_deadline,
        "metadata_only": True,
        "payload_hashes_computed": False,
        "excluded_governance_paths": ["common/capacity_calibration"],
        "classified_bytes": classified_bytes,
        "unresolved_bytes": unresolved_bytes,
        "external_scope_bytes": sum(int(item["bytes"]) for item in external_scopes),
        "resident_bytes": classified_bytes + unresolved_bytes + sum(int(item["bytes"]) for item in external_scopes),
        "object_count": len(objects),
        "unresolved_count": len(unresolved),
        "expired_unresolved_count": len(unresolved) if unresolved_overdue else 0,
        "writing_object_count": len(writing_objects),
        "writing_object_bytes": sum(int(item["bytes"]) for item in writing_objects),
        "initialization_blocker_count": len(initialization_blockers),
        "initialization_blocker_bytes": blocker_bytes,
        "expired_initialization_blocker_count": (
            sum(
                item["reason"] == "writing_recovery_deadline_expired"
                for item in initialization_blockers
            )
        ),
        "active_reference_protected_object_count": protected_count,
        "active_reference_protected_bytes": protected_bytes,
        "active_capacity_lease_ids": sorted(
            item["lease_id"] for item in leases.get("audit", [])
            if item.get("status") == "active" and isinstance(item.get("lease_id"), str)
        ),
        "recovery_required_count": len(recovery_required),
        "recovery_required": recovery_required,
        "initialization_blockers": initialization_blockers,
        "objects": objects,
        "external_scopes": external_scopes,
        "unresolved": unresolved,
    }


def _validate_existing_report_scope(
    inventory: dict[str, Any], *, artifact_root: Path, workspace_root: Path,
    review_deadline: str,
) -> None:
    """Validate a frozen report against this invocation without reading payloads."""

    root = artifact_root.resolve(strict=False)
    try:
        report_root = Path(str(inventory.get("artifact_root", ""))).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise CalibrationError("existing calibration report has an invalid artifact_root") from exc
    if report_root != root:
        raise CalibrationError("existing calibration report artifact_root does not match this invocation")
    if inventory.get("review_deadline") != review_deadline:
        raise CalibrationError("existing calibration report review_deadline does not match this invocation")
    expected = _declared_workspace_scope_paths(root, workspace_root)
    scopes = inventory.get("external_scopes")
    if not isinstance(scopes, list) or len(scopes) != len(expected):
        raise CalibrationError("existing calibration report external scopes are incomplete")
    expected_by_role = {role: path for role, path in expected}
    seen_roles: set[str] = set()
    for scope in scopes:
        if not isinstance(scope, dict) or set(scope) != {"role", "path", "bytes"}:
            raise CalibrationError("existing calibration report external scope schema is invalid")
        role, value, bytes_count = scope.get("role"), scope.get("path"), scope.get("bytes")
        if role not in expected_by_role or role in seen_roles:
            raise CalibrationError("existing calibration report external scopes do not match workspace")
        try:
            path = Path(str(value)).resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise CalibrationError("existing calibration report external scope path is invalid") from exc
        if path != expected_by_role[role]:
            raise CalibrationError("existing calibration report external scopes do not match workspace")
        if isinstance(bytes_count, bool) or not isinstance(bytes_count, int) or bytes_count < 0:
            raise CalibrationError("existing calibration report external scope bytes are invalid")
        seen_roles.add(role)
    if seen_roles != set(expected_by_role):
        raise CalibrationError("existing calibration report external scopes do not match workspace")


def _validate_existing_report_accounting(inventory: dict[str, Any]) -> None:
    """Reject a truncated or internally inconsistent frozen inventory report."""

    groups = (
        ("objects", "object_count", "classified_bytes"),
        ("unresolved", "unresolved_count", "unresolved_bytes"),
        ("initialization_blockers", "initialization_blocker_count", None),
    )
    totals: dict[str, int] = {}
    for name, count_name, bytes_name in groups:
        records = inventory.get(name)
        if not isinstance(records, list):
            raise CalibrationError(f"existing calibration report {name} is invalid")
        if inventory.get(count_name) != len(records):
            raise CalibrationError(f"existing calibration report {count_name} does not match records")
        if bytes_name is None:
            continue
        total = 0
        for record in records:
            bytes_count = record.get("bytes") if isinstance(record, dict) else None
            if isinstance(bytes_count, bool) or not isinstance(bytes_count, int) or bytes_count < 0:
                raise CalibrationError(f"existing calibration report {name} bytes are invalid")
            total += bytes_count
        if inventory.get(bytes_name) != total:
            raise CalibrationError(f"existing calibration report {bytes_name} does not match records")
        totals[bytes_name] = total
    scopes = inventory["external_scopes"]
    external_bytes = sum(int(scope["bytes"]) for scope in scopes)
    if inventory.get("external_scope_bytes") != external_bytes:
        raise CalibrationError("existing calibration report external_scope_bytes does not match scopes")
    expected_resident = (
        totals["classified_bytes"] + totals["unresolved_bytes"] + external_bytes
    )
    if inventory.get("resident_bytes") != expected_resident:
        raise CalibrationError("existing calibration report resident_bytes does not match records")


def _recovery_writing_entries(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert only explicit, still-actionable unresolved records to writing.

    A calibration report is deliberately retained unchanged as the immutable
    discovery record.  This conversion is the narrow bridge into the v2
    ledger: it keeps the exact path, bytes, owner, recovery obligation and
    evidence, but never upgrades an unknown object to a consumable cache.
    """

    unresolved = inventory.get("unresolved")
    if not isinstance(unresolved, list):
        raise CalibrationError("existing calibration report unresolved records are invalid")
    deadline = inventory.get("review_deadline")
    if not isinstance(deadline, str):
        raise CalibrationError("existing calibration report review_deadline is invalid")
    try:
        date.fromisoformat(deadline)
    except ValueError as exc:
        raise CalibrationError("existing calibration report review_deadline is invalid") from exc

    allowed = {
        "path", "bytes", "reason", "owner_hint", "review_deadline",
        "evidence_paths", "recovery_task",
    }
    entries: list[dict[str, Any]] = []
    for item in unresolved:
        if not isinstance(item, dict) or set(item) - allowed:
            raise CalibrationError("unresolved recovery record schema is invalid")
        required = ("path", "bytes", "reason", "owner_hint", "review_deadline", "evidence_paths", "recovery_task")
        if any(field not in item for field in required):
            raise CalibrationError("unresolved record lacks explicit recovery responsibility")
        path, owner, reason, item_deadline, task = (
            item["path"], item["owner_hint"], item["reason"],
            item["review_deadline"], item["recovery_task"],
        )
        size = item["bytes"]
        evidence = item["evidence_paths"]
        if (
            not all(isinstance(value, str) and value.strip() for value in (
                path, owner, reason, item_deadline, task,
            ))
            or isinstance(size, bool) or not isinstance(size, int) or size < 0
            or not isinstance(evidence, list)
            or any(not isinstance(value, str) or not value for value in evidence)
        ):
            raise CalibrationError("unresolved record lacks explicit recovery responsibility")
        try:
            parsed_deadline = date.fromisoformat(item_deadline)
        except ValueError as exc:
            raise CalibrationError("unresolved record review_deadline is invalid") from exc
        if item_deadline != deadline or datetime.now(timezone.utc).date() > parsed_deadline:
            raise CalibrationError("unresolved recovery responsibility is overdue or inconsistent")
        try:
            canonical_path = capacity_ledger.capacity_object_path(
                Path(str(inventory["artifact_root"])), path,
            )[1]
            canonical_evidence = sorted({
                capacity_ledger.capacity_object_path(
                    Path(str(inventory["artifact_root"])), value,
                )[1]
                for value in evidence
            })
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            raise CalibrationError("unresolved recovery paths escape artifact root") from exc
        if canonical_path != path or canonical_evidence != evidence:
            raise CalibrationError("unresolved recovery paths are not canonical")
        entries.append({
            "path": canonical_path,
            "class": "rebuildable_payload",
            "bytes": size,
            "status": "writing",
            "pin": False,
            "owner": owner.strip(),
            "recovery_reason": reason.strip(),
            "review_deadline": item_deadline,
            "recovery_task": task.strip(),
            "recovery_evidence_paths": canonical_evidence or [canonical_path],
        })
    return entries


def _inventory_is_initializable(inventory: dict[str, Any]) -> bool:
    """Accept complete inventories or unexpired, explicitly recoverable ones."""

    unresolved = inventory.get("unresolved")
    if not isinstance(unresolved, list):
        return False
    if inventory.get("initialization_blocker_count", 0) != 0 or inventory.get("initialization_blockers", []) != []:
        return False
    if not unresolved:
        return inventory.get("status") == "ready_to_initialize" and inventory.get("complete") is True
    if inventory.get("status") != "calibration_pending" or inventory.get("complete") is not False:
        return False
    try:
        _recovery_writing_entries(inventory)
    except CalibrationError:
        return False
    return True


def _report_has_supported_lifecycle(inventory: dict[str, Any]) -> bool:
    """Accept a report for later rejection diagnostics without weakening init."""

    if inventory.get("status") == "ready_to_initialize" and inventory.get("complete") is True:
        return True
    return _inventory_is_initializable(inventory)


def load_existing_calibration_report(
    report_path: Path, *, artifact_root: Path, workspace_root: Path,
    review_deadline: str,
) -> dict[str, Any]:
    """Load one external, completed metadata-only report for ledger initialization.

    This deliberately does not rediscover any artifact or workspace path.  The
    caller supplies every scope identity again, so a stale report cannot be
    replayed for another repository or a different review responsibility.
    """

    root = artifact_root.resolve(strict=False)
    report = report_path.resolve(strict=False)
    try:
        report.relative_to(root)
    except ValueError:
        pass
    else:
        raise CalibrationError("ledger initialization requires an external calibration report")
    inventory = _load_json(report)
    if inventory is None:
        raise CalibrationError("existing calibration report is not a JSON object")
    if inventory.get("schema_version") != 1:
        raise CalibrationError("existing calibration report schema_version is unsupported")
    if inventory.get("role") != "legacy_capacity_calibration_inventory":
        raise CalibrationError("existing calibration report role is invalid")
    if not _report_has_supported_lifecycle(inventory):
        raise CalibrationError(
            "existing calibration report is neither complete nor an explicit, "
            "unexpired recovery-only inventory"
        )
    if inventory.get("metadata_only") is not True or inventory.get("payload_hashes_computed") is not False:
        raise CalibrationError("existing calibration report must be metadata-only with no payload hashes")
    _validate_existing_report_scope(
        inventory, artifact_root=root, workspace_root=workspace_root,
        review_deadline=review_deadline,
    )
    _validate_existing_report_accounting(inventory)
    return inventory


def initialize_from_inventory(
    inventory: dict[str, Any], *, ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Initialize v3 from a complete or explicit recovery-only inventory."""

    try:
        _validate_existing_report_accounting(inventory)
    except (KeyError, TypeError) as exc:
        raise CalibrationError("capacity ledger initialization inventory accounting is invalid") from exc
    writing_invalid = 0
    for item in inventory.get("objects", []):
        if not isinstance(item, dict) or item.get("status") != "writing":
            continue
        fields_valid = all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in (
                "owner", "review_deadline", "recovery_reason", "recovery_task",
            )
        ) and isinstance(item.get("recovery_evidence_paths"), list) and bool(item["recovery_evidence_paths"])
        try:
            deadline = date.fromisoformat(str(item.get("review_deadline", "")))
        except ValueError:
            deadline = None
        if (
            not fields_valid
            or deadline is None
            or datetime.now(timezone.utc).date() > deadline
        ):
            writing_invalid += 1
    if (
        inventory.get("schema_version") != 1
        or inventory.get("role") != "legacy_capacity_calibration_inventory"
        or inventory.get("metadata_only") is not True
        or inventory.get("payload_hashes_computed") is not False
        or not _inventory_is_initializable(inventory)
        or writing_invalid != 0
    ):
        expired = int(inventory.get("expired_unresolved_count", 0) or 0)
        blockers = int(inventory.get("initialization_blocker_count", 0) or 0)
        expired_blockers = int(
            inventory.get("expired_initialization_blocker_count", 0) or 0
        )
        raise CalibrationError(
            "capacity ledger initialization requires complete inventory or "
            "explicit unexpired recovery responsibility; "
            f"initialization_blocker_count={blockers}; "
            f"expired_unresolved_count={expired}; "
            f"expired_initialization_blocker_count={expired_blockers}; "
            f"invalid_or_overdue_writing_count={writing_invalid}"
        )
    root = Path(str(inventory["artifact_root"]))
    recovery_entries = _recovery_writing_entries(inventory)
    ledger_objects = [
        {
            key: value for key, value in item.items()
            if key not in {
                "owner_hint", "evidence_paths", "active_protection",
                "active_consumers",
            }
        }
        for item in inventory["objects"]
    ] + recovery_entries
    return _initialize_or_migrate_capacity_ledger(
        root,
        objects=ledger_objects,
        external_scopes=inventory.get("external_scopes", ()),
        inventory=inventory,
        ledger_path=ledger_path,
    )


def _canonical_json_sha256(value: object) -> str:
    """Return a stable identity for small governance records only."""

    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _load_json_bytes(path: Path) -> tuple[dict[str, Any] | None, bytes | None]:
    """Read one small governance JSON record without inspecting artifacts."""

    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    return (value if isinstance(value, dict) else None), raw


def _valid_legacy_v1_ledger(root: Path, document: object) -> bool:
    """Recognize only the calibrated v1 ledger shape that v2 supersedes."""

    if not isinstance(document, dict) or set(document) != LEGACY_LEDGER_KEYS:
        return False
    if (
        document.get("schema_version") != 1
        or document.get("role") != "artifact_capacity_ledger"
        or document.get("status") != "calibrated"
        or document.get("complete") is not True
    ):
        return False
    try:
        document_root = Path(str(document.get("artifact_root", ""))).resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    if document_root != root:
        return False
    resident = document.get("resident_bytes")
    objects = document.get("objects")
    if (
        isinstance(resident, bool) or not isinstance(resident, int) or resident < 0
        or not isinstance(objects, list)
    ):
        return False
    total = 0
    for item in objects:
        if not isinstance(item, dict):
            return False
        if (
            not isinstance(item.get("path"), str) or not item["path"]
            or item.get("class") not in capacity_ledger.LEDGER_CLASSES
            or item.get("status") not in capacity_ledger.LEDGER_STATUSES
            or isinstance(item.get("bytes"), bool)
            or not isinstance(item.get("bytes"), int)
            or item["bytes"] < 0
            or not isinstance(item.get("pin", False), bool)
        ):
            return False
        if item["status"] != "retired":
            total += item["bytes"]
    if total != resident:
        return False
    # v1 differed only by the absence of external-scope accounting.  Reuse
    # the v2 validator with that one known structural addition so malformed
    # historical fields never become an overwrite authorization.
    return capacity_ledger._is_valid_capacity_ledger(root, {
        **document,
        "schema_version": 2,
        "external_scopes": [],
    })


def _build_v3_ledger_document(
    root: Path, *, objects: Iterable[dict[str, Any]],
    external_scopes: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build the same complete v3 document as normal baseline publication."""

    normalized: list[dict[str, Any]] = []
    for source in objects:
        if not isinstance(source, dict):
            raise CalibrationError("capacity ledger objects must be mappings")
        _, relative = capacity_ledger.capacity_object_path(root, str(source.get("path", "")))
        normalized.append({**source, "path": relative})
    scopes = [dict(scope) for scope in external_scopes]
    document = {
        "schema_version": 3,
        "role": "artifact_capacity_ledger",
        "status": "calibrated",
        "complete": True,
        "artifact_root": str(root),
        "resident_bytes": (
            sum(int(item.get("bytes", 0)) for item in normalized if item.get("status") != "retired")
            + sum(int(item.get("bytes", 0)) for item in scopes)
        ),
        "objects": normalized,
        "external_scopes": scopes,
    }
    if not capacity_ledger._is_valid_capacity_ledger(root, document):
        raise CalibrationError("explicit capacity ledger baseline is invalid")
    return document


def _write_immutable_json(path: Path, document: dict[str, Any]) -> None:
    """Publish a small receipt once; an existing differing receipt is unsafe."""

    encoded = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        existing, raw = _load_json_bytes(path)
        if existing != document or raw is None:
            raise CalibrationError(f"immutable ledger migration receipt conflicts: {path}")
        return
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _migration_receipt(
    *, migration_id: str, status: str, root: Path, destination: Path,
    legacy_sha256: str, inventory_sha256: str, target_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "role": "capacity_ledger_v1_to_v3_migration",
        "status": status,
        "migration_id": migration_id,
        "artifact_root": str(root),
        "ledger_path": str(destination),
        "legacy_ledger_sha256": legacy_sha256,
        "calibration_inventory_sha256": inventory_sha256,
        "target_ledger_sha256": target_sha256,
    }


def _initialize_or_migrate_capacity_ledger(
    root: Path, *, objects: Iterable[dict[str, Any]],
    external_scopes: Iterable[dict[str, Any]], inventory: dict[str, Any],
    ledger_path: Path | None,
) -> dict[str, Any]:
    """Initialize an empty destination or recover one exact v1→v3 migration.

    A v1 ledger is never treated as an overwrite permission.  The exact old
    ledger, frozen calibration inventory and target v2 document are bound into
    an immutable pending receipt before the atomic replacement.  A retry can
    only finish that exact pending migration after validating the landed v3
    ledger; arbitrary valid ledgers remain untouchable.
    """

    root = root.resolve(strict=False)
    destination = capacity_ledger.resolve_ledger_path(root, ledger_path)
    canonical = capacity_ledger.resolve_ledger_path(root)
    if destination != canonical:
        return capacity_ledger.initialize_capacity_ledger(
            root, objects=objects, external_scopes=external_scopes, path=destination,
        )
    target = _build_v3_ledger_document(
        root, objects=objects, external_scopes=external_scopes,
    )
    inventory_sha256 = _canonical_json_sha256(inventory)
    target_sha256 = _canonical_json_sha256(target)

    with capacity_protection.capacity_decision_lock(root):
        existing, raw = _load_json_bytes(destination)
        if raw is None:
            if destination.exists():
                raise CalibrationError(
                    "existing capacity ledger is unreadable and will not be overwritten"
                )
            write_json_atomic(destination, target)
            initialized = capacity_ledger.load_capacity_ledger(root, destination)
            if initialized != target:
                raise CalibrationError("capacity ledger publication could not be read back")
            return initialized
        receipt_directory = root / LEDGER_MIGRATION_DIRECTORY
        if _valid_legacy_v1_ledger(root, existing):
            legacy_sha256 = hashlib.sha256(raw).hexdigest().upper()
            migration_id = hashlib.sha256(
                f"capacity-ledger-v1-to-v3:{legacy_sha256}:{inventory_sha256}:{target_sha256}".encode("ascii")
            ).hexdigest().upper()
            pending_path = receipt_directory / f"{migration_id}.pending.json"
            complete_path = receipt_directory / f"{migration_id}.complete.json"
            pending = _migration_receipt(
                migration_id=migration_id, status="pending", root=root,
                destination=destination, legacy_sha256=legacy_sha256,
                inventory_sha256=inventory_sha256, target_sha256=target_sha256,
            )
            complete = {**pending, "status": "complete"}
            _write_immutable_json(pending_path, pending)
            write_json_atomic(destination, target)
            landed = capacity_ledger.load_capacity_ledger(root, destination)
            if landed != target:
                raise CalibrationError("v1 to v3 capacity ledger replacement could not be read back")
            _write_immutable_json(complete_path, complete)
            return landed

        landed = capacity_ledger.load_capacity_ledger(root, destination)
        if landed is None:
            raise CalibrationError(
                "existing capacity ledger is neither an exact calibrated v1 ledger nor a valid v2 ledger"
            )
        matches: list[tuple[Path, dict[str, Any]]] = []
        if receipt_directory.is_dir():
            for candidate_path in receipt_directory.glob("*.pending.json"):
                candidate, _ = _load_json_bytes(candidate_path)
                if not isinstance(candidate, dict):
                    continue
                legacy_sha256 = candidate.get("legacy_ledger_sha256")
                migration_id = candidate.get("migration_id")
                expected_id = (
                    hashlib.sha256(
                    f"capacity-ledger-v1-to-v3:{legacy_sha256}:{inventory_sha256}:{target_sha256}".encode("ascii")
                    ).hexdigest().upper()
                    if isinstance(legacy_sha256, str) else None
                )
                if (
                    candidate.get("schema_version") == 1
                    and candidate.get("role") == "capacity_ledger_v1_to_v3_migration"
                    and candidate.get("status") == "pending"
                    and candidate.get("artifact_root") == str(root)
                    and candidate.get("ledger_path") == str(destination)
                    and candidate.get("calibration_inventory_sha256") == inventory_sha256
                    and candidate.get("target_ledger_sha256") == target_sha256
                    and migration_id == expected_id
                ):
                    matches.append((candidate_path, candidate))
        if len(matches) != 1:
            raise CalibrationError("valid capacity ledger will not be overwritten by migration")
        if landed != target:
            raise CalibrationError("pending capacity ledger migration target differs from landed v3 ledger")
        pending_path, pending = matches[0]
        complete_path = pending_path.with_name(
            pending_path.name.removesuffix(".pending.json") + ".complete.json"
        )
        complete = {**pending, "status": "complete"}
        _write_immutable_json(complete_path, complete)
        return landed


def _v2_to_v3_migration_id(source_sha256: str, review_deadline: str) -> str:
    return hashlib.sha256(
        f"capacity-ledger-v2-to-v3:{source_sha256}:{review_deadline}".encode("ascii")
    ).hexdigest().upper()


def _legacy_v3_duties(
    document: dict[str, Any], *, review_deadline: str, pending_receipt_path: str,
) -> dict[str, dict[str, Any]]:
    """Assign one range owner where canonical paths establish it.

    The historical function name remains because it labels immutable
    migration receipts.  New v3 records no longer duplicate retention prose
    and retirement routes; classes and the owner manager already select them.
    """

    duties_by_path: dict[str, dict[str, Any]] = {}
    for item in document["objects"]:
        if item["status"] == "retired":
            continue
        path = item["path"]
        parts = Path(path).parts
        governance_root = (
            len(parts) >= 2
            and parts[0] == "common"
            and (
                parts[1] in COMMON_CAPACITY_LIFECYCLE_ROOTS
                or parts[1].startswith(".capacity_ledger.json.")
            )
        )
        common_owner = (
            COMMON_GOVERNANCE_OWNERS.get(parts[1])
            if len(parts) >= 2 and parts[0] == "common" else None
        )
        if len(parts) >= 4 and parts[:3] == ("common", "simion", "pa_family_cache"):
            owner = capacity_ledger.PA_CACHE_MANAGER
        elif governance_root:
            owner = "common.capacity_lifecycle"
        elif common_owner is not None:
            owner = common_owner
        elif len(parts) >= 2 and parts[0] == "projects" and parts[1]:
            owner = parts[1]
        else:
            raise CalibrationError(
                f"v2 to v3 migration cannot establish owner from canonical path: {path}"
            )
        existing_owner = item.get("owner")
        allowed_legacy_governance_owners = {
            "common", "common.capacity_ledger", "common.run_artifact_support",
        }
        if existing_owner is not None and existing_owner != owner and not (
            (governance_root or common_owner is not None)
            and existing_owner in allowed_legacy_governance_owners
        ):
            raise CalibrationError(
                f"v2 to v3 migration owner conflicts with canonical path: {path}"
            )
        duties: dict[str, Any] = {"owner": owner}
        if item["status"] == "writing":
            recovery_reason = item.get("recovery_reason")
            if not isinstance(recovery_reason, str) or not recovery_reason.strip():
                raise CalibrationError(f"v2 writing object has no recovery reason: {path}")
            existing_evidence = item.get("recovery_evidence_paths", [])
            if (
                not isinstance(existing_evidence, list)
                or any(not isinstance(value, str) or not value for value in existing_evidence)
            ):
                raise CalibrationError(f"v2 writing recovery evidence is invalid: {path}")
            recovery_task = item.get("recovery_task")
            if not isinstance(recovery_task, str) or not recovery_task.strip():
                recovery_task = "legacy calibrated recovery requires explicit owner action"
            duties.update({
                "recovery_reason": recovery_reason,
                "review_deadline": review_deadline,
                "recovery_task": recovery_task,
                "recovery_evidence_paths": sorted(set([
                    *existing_evidence, pending_receipt_path,
                ])),
            })
        duties_by_path[path] = duties
    return duties_by_path


def _v2_to_v3_migration_receipt(
    *, migration_id: str, status: str, root: Path, destination: Path,
    source_sha256: str, target_sha256: str, review_deadline: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "role": "capacity_ledger_v2_to_v3_migration",
        "status": status,
        "migration_id": migration_id,
        "artifact_root": str(root),
        "ledger_path": str(destination),
        "source_v2_ledger_sha256": source_sha256,
        "target_v3_ledger_sha256": target_sha256,
        "review_deadline": review_deadline,
    }


def migrate_canonical_v2_ledger_to_v3(
    root: Path, *, review_deadline: str,
) -> dict[str, Any]:
    """Atomically replace only the canonical v2 ledger with its bound v3 form."""

    try:
        date.fromisoformat(review_deadline)
    except ValueError as exc:
        raise CalibrationError("v2 to v3 migration review_deadline must be YYYY-MM-DD") from exc
    root = root.resolve(strict=False)
    destination = capacity_ledger.resolve_ledger_path(root)
    receipt_directory = root / LEDGER_MIGRATION_DIRECTORY
    with capacity_protection.capacity_decision_lock(root):
        existing, raw = _load_json_bytes(destination)
        if existing is None or raw is None:
            raise CalibrationError("canonical capacity ledger is unreadable and cannot be migrated")
        if existing.get("schema_version") == 2:
            if not capacity_ledger._is_valid_capacity_ledger(root, existing):
                raise CalibrationError("canonical capacity ledger is not a valid v2 ledger")
            source_sha256 = hashlib.sha256(raw).hexdigest().upper()
            migration_id = _v2_to_v3_migration_id(source_sha256, review_deadline)
            pending_path = receipt_directory / f"{migration_id}.v2-to-v3.pending.json"
            pending_relative = pending_path.relative_to(root).as_posix()
            duties = _legacy_v3_duties(
                existing, review_deadline=review_deadline,
                pending_receipt_path=pending_relative,
            )
            target = capacity_ledger.migrate_v2_ledger_document(
                root, existing, lifecycle_by_path=duties,
            )
            target_sha256 = _canonical_json_sha256(target)
            pending = _v2_to_v3_migration_receipt(
                migration_id=migration_id, status="pending", root=root,
                destination=destination, source_sha256=source_sha256,
                target_sha256=target_sha256, review_deadline=review_deadline,
            )
            complete = {**pending, "status": "complete"}
            complete_path = pending_path.with_name(
                pending_path.name.removesuffix(".pending.json") + ".complete.json"
            )
            _write_immutable_json(pending_path, pending)
            write_json_atomic(destination, target)
            landed = capacity_ledger.load_capacity_ledger(root, destination)
            if landed != target:
                raise CalibrationError("v2 to v3 capacity ledger replacement could not be read back")
            _write_immutable_json(complete_path, complete)
            return landed
        if existing.get("schema_version") != 3:
            raise CalibrationError("canonical capacity ledger is neither a valid v2 ledger nor a valid v3 ledger")
        landed = capacity_ledger.load_capacity_ledger(root, destination)
        if landed is None:
            raise CalibrationError("canonical capacity ledger is invalid and cannot be migrated")
        matches: list[tuple[Path, dict[str, Any]]] = []
        if receipt_directory.is_dir():
            for pending_path in receipt_directory.glob("*.v2-to-v3.pending.json"):
                pending, _ = _load_json_bytes(pending_path)
                if not isinstance(pending, dict):
                    continue
                source_sha256 = pending.get("source_v2_ledger_sha256")
                target_sha256 = pending.get("target_v3_ledger_sha256")
                if (
                    isinstance(source_sha256, str)
                    and pending == _v2_to_v3_migration_receipt(
                        migration_id=_v2_to_v3_migration_id(source_sha256, review_deadline),
                        status="pending", root=root, destination=destination,
                        source_sha256=source_sha256, target_sha256=target_sha256,
                        review_deadline=review_deadline,
                    )
                    and _canonical_json_sha256(landed) == target_sha256
                ):
                    matches.append((pending_path, pending))
        if len(matches) != 1:
            raise CalibrationError("valid v3 capacity ledger will not be overwritten by migration")
        pending_path, pending = matches[0]
        complete_path = pending_path.with_name(
            pending_path.name.removesuffix(".pending.json") + ".complete.json"
        )
        _write_immutable_json(complete_path, {**pending, "status": "complete"})
        return landed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--review-deadline", required=True)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--initialize-ledger", action="store_true")
    parser.add_argument("--initialize-from-report", type=Path)
    parser.add_argument("--migrate-v2-to-v3", action="store_true")
    parser.add_argument("--ledger-path", type=Path)
    args = parser.parse_args()
    root = args.artifact_root.resolve()
    if sum(value is not None for value in (args.report, args.initialize_from_report)) + int(args.migrate_v2_to_v3) != 1:
        parser.error("provide exactly one of --report, --initialize-from-report, or --migrate-v2-to-v3")
    if not args.migrate_v2_to_v3 and args.workspace_root is None:
        parser.error("--workspace-root is required for calibration operations")
    if args.migrate_v2_to_v3 and (args.initialize_ledger or args.ledger_path is not None):
        parser.error("--migrate-v2-to-v3 only operates on the canonical ledger")
    if args.initialize_from_report is not None and args.initialize_ledger:
        parser.error("--initialize-ledger cannot be combined with --initialize-from-report")
    if args.migrate_v2_to_v3:
        try:
            migrated = migrate_canonical_v2_ledger_to_v3(
                root, review_deadline=args.review_deadline,
            )
        except (CalibrationError, ValueError, OSError) as exc:
            print(json.dumps({
                "event": "v2_to_v3_ledger_migration_rejected",
                "artifact_root": str(root), "reason": str(exc),
            }, ensure_ascii=False), file=sys.stderr, flush=True)
            raise SystemExit(2) from exc
        print(json.dumps({
            "event": "v2_to_v3_ledger_migrated",
            "ledger_path": str(capacity_ledger.resolve_ledger_path(root)),
            "schema_version": migrated["schema_version"],
        }, ensure_ascii=False))
        return
    report = (args.report or args.initialize_from_report).resolve(strict=False)
    try:
        report_relative = report.relative_to(root)
    except ValueError:
        report_relative = None
    if args.initialize_from_report is not None and report_relative is not None:
        raise CalibrationError("ledger initialization requires an external calibration report")
    if args.report is not None and report_relative is not None and (
        args.initialize_ledger or report_relative.parts[:2] != ("common", "capacity_calibration")
    ):
        raise CalibrationError(
            "in-root pending reports must be below common/capacity_calibration; "
            "ledger initialization requires an external report"
        )

    def progress(event: str, path: Path) -> None:
        print(json.dumps({
            "event": event,
            "path": str(path),
        }, ensure_ascii=False), file=sys.stderr, flush=True)

    if args.initialize_from_report is not None:
        print(json.dumps({
            "event": "existing_calibration_report_initialization_started",
            "artifact_root": str(root),
            "workspace_root": str(args.workspace_root.resolve()),
            "report": str(report),
        }, ensure_ascii=False), file=sys.stderr, flush=True)
        try:
            inventory = load_existing_calibration_report(
                report, artifact_root=root, workspace_root=args.workspace_root,
                review_deadline=args.review_deadline,
            )
            initialize_from_inventory(inventory, ledger_path=args.ledger_path)
        except (CalibrationError, ValueError, OSError) as exc:
            print(json.dumps({
                "event": "existing_calibration_report_initialization_rejected",
                "report": str(report),
                "reason": str(exc),
            }, ensure_ascii=False), file=sys.stderr, flush=True)
            raise SystemExit(2) from exc
        print(json.dumps({
            "event": "ledger_initialized_from_existing_report",
            "ledger_path": str(
                args.ledger_path.resolve(strict=False)
                if args.ledger_path is not None
                else capacity_ledger.resolve_ledger_path(root)
            ),
        }, ensure_ascii=False), file=sys.stderr, flush=True)
        print(json.dumps({
            "status": inventory["status"],
            "classified_bytes": inventory["classified_bytes"],
            "unresolved_bytes": inventory["unresolved_bytes"],
            "unresolved_count": inventory["unresolved_count"],
            "external_scope_bytes": inventory["external_scope_bytes"],
            "report": str(report),
        }, ensure_ascii=False))
        return

    print(json.dumps({
        "event": "calibration_started",
        "artifact_root": str(root),
            "workspace_root": str(args.workspace_root.resolve()),
        "report": str(report),
        "initialize_ledger": args.initialize_ledger,
    }, ensure_ascii=False), file=sys.stderr, flush=True)
    try:
        inventory = build_calibration_inventory(
            root, review_deadline=args.review_deadline,
            workspace_root=args.workspace_root, progress=progress,
        )
    except (CalibrationError, OSError) as exc:
        print(json.dumps({
            "event": "calibration_failed_before_report",
            "report": str(report),
            "error_type": type(exc).__name__,
            "reason": str(exc),
        }, ensure_ascii=False), file=sys.stderr, flush=True)
        raise
    write_json_atomic(report, inventory)
    print(json.dumps({
        "event": "calibration_report_written",
        "report": str(report),
        "status": inventory["status"],
        "unresolved_count": inventory["unresolved_count"],
        "initialization_blocker_count": inventory["initialization_blocker_count"],
    }, ensure_ascii=False), file=sys.stderr, flush=True)
    if args.initialize_ledger:
        try:
            initialize_from_inventory(inventory, ledger_path=args.ledger_path)
        except CalibrationError as exc:
            print(json.dumps({
                "event": "ledger_initialization_rejected",
                "report": str(report),
                "reason": str(exc),
            }, ensure_ascii=False), file=sys.stderr, flush=True)
            raise SystemExit(2) from exc
        print(json.dumps({
            "event": "ledger_initialized",
            "ledger_path": str(
                args.ledger_path.resolve(strict=False)
                if args.ledger_path is not None
                else capacity_ledger.resolve_ledger_path(root)
            ),
        }, ensure_ascii=False), file=sys.stderr, flush=True)
    print(json.dumps({
        "status": inventory["status"],
        "classified_bytes": inventory["classified_bytes"],
        "unresolved_bytes": inventory["unresolved_bytes"],
        "unresolved_count": inventory["unresolved_count"],
        "external_scope_bytes": inventory["external_scope_bytes"],
        "report": str(report),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
