"""Inventory legacy artifacts before the trusted capacity ledger is initialized.

The inventory is deliberately metadata-only: it reads small manifests and
pointers and compares recorded byte counts, but never hashes payload files.
Nothing is deleted.  Ambiguous objects remain explicit review items and block
ledger initialization.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common.contracts import capacity_ledger, capacity_protection
from common.contracts.artifact_retention import (
    classify_file,
    validate_retention,
)
from common.contracts.recorded_file_removal import write_json_atomic
from common.contracts.verify_artifact_layout import INTEGRATION_CACHE_ROLES


SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objects: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for child in sorted(project.iterdir()):
        if child.name == "runs" and child.is_dir():
            for run in sorted(item for item in child.iterdir() if item.is_dir()):
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


def _workspace_external_scopes(artifact_root: Path, workspace_root: Path) -> list[dict[str, Any]]:
    """Measure the two declared source-tree working roots during calibration only."""

    workspace = workspace_root.resolve(strict=False)
    root = artifact_root.resolve(strict=False)
    if workspace == root or workspace in root.parents or root in workspace.parents:
        raise CalibrationError("workspace_root must be distinct from artifact_root to avoid double counting")
    scopes: list[dict[str, Any]] = []
    for role, name in (("repository_scratch", "scratch"), ("repository_generated", "generated")):
        target = (workspace / name).resolve(strict=False)
        if target.exists() and not target.is_dir():
            raise CalibrationError(f"declared workspace scope is not a directory: {target}")
        scopes.append({"role": role, "path": str(target), "bytes": 0 if not target.exists() else _bytes(target)})
    return scopes


def build_calibration_inventory(
    artifact_root: Path, *, review_deadline: str, workspace_root: Path | None = None,
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
        _workspace_external_scopes(root, workspace_root)
        if workspace_root is not None else []
    )
    objects: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
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
                    found, pending = _classify_project(root, project, review_deadline)
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
        if item["status"] != "writing":
            continue
        item["owner"] = item["owner_hint"]
        item["recovery_reason"] = item.get(
            "recovery_reason", item.get("active_protection", "legacy_writing_object"),
        )
        item["review_deadline"] = review_deadline
        if item.get("active_consumers"):
            item["consumers"] = sorted(set(item["active_consumers"]))
    objects.sort(key=lambda item: item["path"])
    unresolved.sort(key=lambda item: item["path"])
    writing_objects = [item for item in objects if item["status"] == "writing"]
    today = datetime.now(timezone.utc).date()
    initialization_blockers: list[dict[str, Any]] = []
    for item in writing_objects:
        missing = [
            field for field in ("owner", "recovery_reason", "review_deadline")
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


def initialize_from_inventory(
    inventory: dict[str, Any], *, ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Initialize the ledger only from a complete, zero-unresolved inventory."""

    writing_invalid = 0
    for item in inventory.get("objects", []):
        if not isinstance(item, dict) or item.get("status") != "writing":
            continue
        fields_valid = all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in ("owner", "recovery_reason", "review_deadline")
        )
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
        inventory.get("role") != "legacy_capacity_calibration_inventory"
        or inventory.get("complete") is not True
        or inventory.get("unresolved_count") != 0
        or inventory.get("unresolved") != []
        or inventory.get("initialization_blocker_count", 0) != 0
        or inventory.get("initialization_blockers", []) != []
        or writing_invalid != 0
    ):
        expired = int(inventory.get("expired_unresolved_count", 0) or 0)
        blockers = int(inventory.get("initialization_blocker_count", 0) or 0)
        expired_blockers = int(
            inventory.get("expired_initialization_blocker_count", 0) or 0
        )
        raise CalibrationError(
            "capacity ledger initialization requires zero unresolved objects and "
            "complete writing recovery responsibility; "
            f"initialization_blocker_count={blockers}; "
            f"expired_unresolved_count={expired}; "
            f"expired_initialization_blocker_count={expired_blockers}; "
            f"invalid_or_overdue_writing_count={writing_invalid}"
        )
    root = Path(str(inventory["artifact_root"]))
    ledger_objects = [
        {
            key: value for key, value in item.items()
            if key not in {
                "owner_hint", "evidence_paths", "active_protection",
                "active_consumers",
            }
        }
        for item in inventory["objects"]
    ]
    return capacity_ledger.initialize_capacity_ledger(
        root, objects=ledger_objects, external_scopes=inventory.get("external_scopes", ()), path=ledger_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--review-deadline", required=True)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--initialize-ledger", action="store_true")
    parser.add_argument("--ledger-path", type=Path)
    args = parser.parse_args()
    root = args.artifact_root.resolve()
    report = args.report.resolve(strict=False)
    try:
        report_relative = report.relative_to(root)
    except ValueError:
        report_relative = None
    if report_relative is not None and (
        args.initialize_ledger
        or report_relative.parts[:2] != ("common", "capacity_calibration")
    ):
        raise CalibrationError(
            "in-root pending reports must be below common/capacity_calibration; "
            "ledger initialization requires an external report"
        )
    inventory = build_calibration_inventory(
        root, review_deadline=args.review_deadline, workspace_root=args.workspace_root,
    )
    write_json_atomic(report, inventory)
    if args.initialize_ledger:
        initialize_from_inventory(inventory, ledger_path=args.ledger_path)
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
