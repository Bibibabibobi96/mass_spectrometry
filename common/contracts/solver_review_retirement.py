"""Governed retirement of solver-review and explicitly stopped runtime payloads.

The original run manifest remains immutable historical evidence.  A completed
retirement receipt becomes the only valid verifier for the reduced run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common.contracts.recorded_file_removal import remove_recorded_files, write_json_atomic as _atomic_json
from common.contracts.file_identity import file_sha256, file_sha256_unbuffered
from common.contracts.artifact_retention import classify_file, validate_retention
from common.contracts import capacity_protection as protection
from common.contracts.verify_run_manifest import record_path, verify_record

RECEIPT_NAME = "solver_review_retirement_receipt.json"
HEAVY_ROLES = {"solver_native_binary", "dense_trajectory"}
TERMINAL_STATUSES = {
    "success", "completed", "failed", "interrupted", "cancelled", "aborted",
}
LEGACY_INITIALIZATION_SUMMARY = {
    "schema_version": 1,
    "role": "run_package_initialization_summary",
    "status": "checkpoint",
    "reason": "Run package initialized; task-specific inputs are not frozen yet.",
}


class RetirementError(ValueError):
    """One retirement precondition or verification condition failed."""


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetirementError(f"unreadable JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RetirementError(f"JSON document must be an object: {path}")
    return value


def _under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RetirementError(f"path escapes governed root: {path}") from exc
    return resolved


def _load_run(
    run: Path, *, allowed_statuses: Iterable[str] = ("success",), label: str = "run",
    allow_legacy_initialization_summary: bool = False,
    expected_run_id: str | None = None,
    stopped_checkpoint_runtime: bool = False,
    prepared_gui_checkpoint: bool = False,
) -> dict[str, Any]:
    required = {name: _json(run / name) for name in ("run_config.json", "summary.json", "run_manifest.json")}
    config, summary, manifest = required.values()
    run_id = expected_run_id or run.name
    if config.get("run_id") != run_id or manifest.get("run_id") != run_id:
        raise RetirementError(f"run identity mismatch: {run}")
    if summary.get("run_id") not in {None, run_id}:
        raise RetirementError(f"summary run identity mismatch: {run}")
    allowed = set(allowed_statuses)
    manifest_status = manifest.get("status")
    summary_status = summary.get("status")
    legacy_initialization_summary = (
        allow_legacy_initialization_summary
        and manifest_status == "success"
        and summary == LEGACY_INITIALIZATION_SUMMARY
    )
    prepared_gui_summary = prepared_gui_checkpoint and manifest_status == "checkpoint" and summary_status == "gui_replay_prepared"
    if manifest_status not in allowed or (
        summary_status != manifest_status and not legacy_initialization_summary and not prepared_gui_summary
    ):
        expected = "/".join(sorted(allowed))
        raise RetirementError(
            f"{label} is not a complete {expected} run: {run_id} "
            f"(manifest={manifest_status!r}, summary={summary_status!r})"
        )
    if config.get("formal_gate_passed") is not False or manifest.get("formal_eligible") is not False:
        raise RetirementError(f"Formal or ambiguously non-Formal run cannot be retired: {run_id}")
    try:
        retention = validate_retention(config.get("artifact_retention"))
        manifest_retention = validate_retention(manifest.get("artifact_retention"))
    except ValueError as exc:
        raise RetirementError(f"invalid solver_review retention: {run_id}: {exc}") from exc
    required_class = "compact" if stopped_checkpoint_runtime else "solver_review"
    if stopped_checkpoint_runtime and (manifest_status != "checkpoint" or summary_status != "checkpoint"):
        raise RetirementError("stopped runtime retirement requires matching checkpoint states")
    if retention.class_id != required_class:
        raise RetirementError(f"run is not solver_review: {run_id}")
    if manifest_retention.class_id != required_class:
        raise RetirementError(f"manifest retention differs: {run_id}")
    if prepared_gui_checkpoint:
        parameters = config.get("parameters", {})
        if (not prepared_gui_summary or parameters.get("workflow") != "native_gui_replay"
                or parameters.get("manual_gui_confirmed") is not False
                or parameters.get("native_field_construction") != "private_refine_and_native_IOB_prepared_not_flown"
                or summary.get("gui_fly_completed") is not False
                or summary.get("trajectory_equivalence_verified") is not False
                or summary.get("field_construction") != "new_private_refine_from_frozen_GEM"):
            raise RetirementError("prepared GUI retirement requires explicit unflown native preparation evidence")
    return {
        "dir": run,
        "config": config,
        "summary": summary,
        "manifest": manifest,
        "legacy_initialization_summary": legacy_initialization_summary,
    }


def _recorded_at(run: dict[str, Any]) -> datetime:
    text = run["manifest"].get("recorded_at_utc")
    try:
        value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetirementError("manifest recorded_at_utc is invalid") from exc
    if value.tzinfo is None:
        raise RetirementError("manifest recorded_at_utc must be timezone-aware")
    return value.astimezone(timezone.utc)


def _prepared_gui_inventory(run: dict[str, Any], records: dict[Path, dict[str, Any]]) -> None:
    """Require a sealed local GEM/IOB and numbered native family; no Fly outputs."""
    local = {path: item for path, item in records.items() if path.is_relative_to(run["dir"])}
    controllers = [path for path in local if path.suffix.lower() == ".pa#"]
    if not controllers:
        raise RetirementError("prepared GUI lacks a sealed native field family")
    for controller in controllers:
        stem = controller.with_suffix("")
        if not all(stem.with_suffix(suffix) in local for suffix in (".gem", ".iob", ".pa0", ".pa1")):
            raise RetirementError("prepared GUI native family lacks sealed GEM/IOB/controller/responses")
        indices = sorted(int(path.suffix[3:]) for path in local
                         if path.parent == controller.parent and path.stem == controller.stem
                         and path.suffix.startswith(".pa") and path.suffix[3:].isdigit())
        if indices != list(range(len(indices))):
            raise RetirementError("prepared GUI native response inventory is not contiguous")
    if any(classify_file(path, bytes_count=item["bytes"]) == "dense_trajectory"
           and "inputs" not in path.relative_to(run["dir"]).parts for path, item in local.items()):
        raise RetirementError("prepared GUI contains trajectory outputs; unflown state is uncertain")
    parameters = run["config"]["parameters"]
    baseline = [path for path in local if path.name == "baseline_manifest.json"]
    if len(baseline) != 1:
        raise RetirementError("prepared GUI lacks its unique frozen scientific source manifest")
    source = _json(baseline[0])
    if (file_sha256(baseline[0]) != str(parameters.get("baseline_manifest_sha256", "")).upper()
            or source.get("run_id") != Path(str(parameters.get("baseline_run", ""))).name
            or source.get("project") != run["config"].get("project")
            or source.get("status") not in {"success", "failed"}):
        raise RetirementError("prepared GUI frozen scientific source identity differs")


def _prepared_gui_scope(document: dict[str, Any]) -> bool:
    value = document.get("prepared_gui_checkpoint")
    if value is None:
        return False
    if value != {"writing_stopped": True} or document.get("retirement_mode") not in {None, "completed_experiment"}:
        raise RetirementError("invalid prepared GUI checkpoint retirement scope")
    return True


def _git_document_references(repository: Path, run_id: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repository), "grep", "-l", "-F", "--", run_id, "--", "*.md"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        cwd=repository,
        timeout=30,
    )
    if result.returncode not in {0, 1}:
        raise RetirementError(f"git document reference scan failed: {result.stderr.strip()}")
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def structured_target_references(value: Any, target: Path, run_id: str) -> set[str]:
    """Return exact structured references below ``target``.

    The empty string denotes the target run as a whole.  Other values are
    normalized target-relative paths.  Arbitrary prose and substring matches
    are deliberately ignored; callers decide whether a referenced file is in
    the payload they propose to remove or in the light evidence they retain.
    """

    normalized_run_id = run_id.casefold()
    target_path = target.resolve().as_posix().rstrip("/").casefold()
    prefixes = (f"{target_path}/", f"/runs/{normalized_run_id}/")
    return _structured_target_references(value, normalized_run_id, target_path, prefixes)


def _structured_target_references(
    value: Any, normalized_run_id: str, target_path: str, prefixes: tuple[str, str],
) -> set[str]:
    """Match one document against a target already resolved by this scan."""

    def references(member: Any) -> set[str]:
        if isinstance(member, dict):
            return set().union(*(references(item) for item in member.values())) if member else set()
        if isinstance(member, (list, tuple)):
            return set().union(*(references(item) for item in member)) if member else set()
        if not isinstance(member, str):
            return set()
        raw = member.strip().replace("\\", "/")
        if not raw:
            return set()
        normalized = posixpath.normpath(raw).rstrip("/").casefold()
        if normalized in {normalized_run_id, target_path} or normalized.endswith(
            f"/runs/{normalized_run_id}"
        ):
            return {""}
        for prefix in prefixes:
            if prefix == prefixes[1]:
                marker = normalized.rfind(prefix)
                if marker < 0:
                    continue
                relative = normalized[marker + len(prefix):]
            elif normalized.startswith(prefix):
                relative = normalized[len(prefix):]
            else:
                continue
            if relative and relative != "." and not relative.startswith("../"):
                return {relative}
        return set()

    return references(value)


def _downstream_references(
    artifact_root: Path, target: Path, run_id: str, *,
    removable_paths: Iterable[str] = (), preserved_paths: Iterable[str] = (),
    approved_stopped_consumers: Iterable[dict[str, Any]] = (),
) -> dict[str, list[dict[str, str]]]:
    references: dict[str, list[dict[str, str]]] = {
        "active": [],
        "active_preserved": [],
        "historical": [],
        "corrupt_run_config_reference_unavailable": [],
    }
    removable = {posixpath.normpath(item).casefold() for item in removable_paths}
    preserved = {posixpath.normpath(item).casefold() for item in preserved_paths}
    stopped = {Path(item["run_path"]).resolve() for item in approved_stopped_consumers}
    resolved_target = target.resolve()
    target_path = resolved_target.as_posix().rstrip("/").casefold()
    normalized_run_id = run_id.casefold()
    prefixes = (f"{target_path}/", f"/runs/{normalized_run_id}/")
    for run_dir in artifact_root.glob("projects/*/runs/*"):
        if not run_dir.is_dir():
            continue
        resolved_run = run_dir.resolve()
        if resolved_run == resolved_target:
            continue
        path = run_dir / "run_config.json"
        manifest_path = run_dir / "run_manifest.json"
        manifest: dict[str, Any] | None = None
        try:
            manifest = _json(manifest_path)
            manifest_status = str(manifest.get("status", "")).lower()
            if manifest.get("run_id") not in {None, run_dir.name}:
                manifest_status = "invalid_or_unreadable"
        except RetirementError:
            manifest_status = "missing_or_unreadable"
        category = (
            "historical" if manifest_status in TERMINAL_STATUSES else "active"
        )
        explicitly_stopped = resolved_run in stopped
        if explicitly_stopped:
            category = "historical"
        config: dict[str, Any] | None = None
        if path.exists():
            try:
                config = _json(path)
            except RetirementError:
                # A non-terminal run with a damaged run_config must not pin
                # every retirement target merely because its path exists.
                # First use the valid manifest's local run_config record to
                # distinguish content corruption from an unreadable parser.
                manifest_record = manifest.get("run_config") if manifest else None
                identity_matches = False
                identity_checkable = False
                if isinstance(manifest_record, dict):
                    try:
                        recorded_path = record_path(manifest_record, base_dir=run_dir)
                        identity_checkable = recorded_path == path
                        if identity_checkable:
                            verify_record(
                                "downstream run_config",
                                manifest_record,
                                base_dir=run_dir,
                            )
                            identity_matches = True
                    except (AssertionError, KeyError, OSError, TypeError, ValueError):
                        identity_matches = False
                if category == "active" and identity_checkable and not identity_matches:
                    references["corrupt_run_config_reference_unavailable"].append(
                        {
                            "run_config_path": str(path),
                            "manifest_status": manifest_status,
                            "reason": "corrupt_run_config_reference_unavailable",
                        }
                    )
                else:
                    references[category].append(
                        {
                            "run_config_path": str(path),
                            "manifest_status": manifest_status,
                            "reason": "run_config_unreadable_reference_uncertain",
                        }
                    )
        configured = set()
        if config is not None:
            configured.update(_structured_target_references(config, normalized_run_id, target_path, prefixes))
        if manifest is not None:
            configured.update(_structured_target_references(manifest, normalized_run_id, target_path, prefixes))
        for relative in sorted(configured):
            item = {
                "run_config_path": str(path),
                "manifest_status": manifest_status,
                "reason": "configured_target_run_dependency" if not relative else "configured_target_file_dependency",
            }
            if relative:
                item["path"] = relative
            if explicitly_stopped:
                item["classification_basis"] = "owner_explicit_consumer_abandonment_for_this_runtime"
            if category == "historical":
                references[category].append(item)
            elif not relative or relative in removable:
                references["active"].append(item)
            elif relative in preserved:
                references["active_preserved"].append(item)
    for category in references:
        references[category].sort(key=lambda item: (item["run_config_path"], item.get("path", "")))
    return references


def _manifest_records(
    run: dict[str, Any], *, retired_paths: Iterable[Path] = (),
    inherit_heavy_identity: bool = False,
) -> dict[Path, dict[str, Any]]:
    """Verify every recorded identity, except receipt-bound partial removals."""
    result: dict[Path, dict[str, Any]] = {}
    retired = set(retired_paths)
    manifest = run["manifest"]
    entries: list[tuple[str, dict[str, Any]]] = [("run_config", manifest.get("run_config", {}))]
    entries.extend((f"input:{name}", record) for name, record in manifest.get("inputs", {}).items())
    entries.extend((f"output:{index}", record) for index, record in enumerate(manifest.get("outputs", [])))
    for role, record in entries:
        if not isinstance(record, dict) or record.get("exists") is not True:
            raise RetirementError(f"invalid manifest record: {role}")
        try:
            path = record_path(record, base_dir=run["dir"])
            if path not in retired:
                local_heavy = (
                    inherit_heavy_identity and path.is_relative_to(run["dir"])
                    and classify_file(path, bytes_count=record.get("bytes", 0)) in HEAVY_ROLES
                )
                if local_heavy:
                    if (not path.is_file() or path.is_symlink()
                            or path.stat().st_size != record.get("bytes")
                            or len(str(record.get("sha256", ""))) != 64):
                        raise RetirementError(f"sealed heavy record differs: {path}")
                else:
                    verify_record(role, record, base_dir=run["dir"])
        except (AssertionError, KeyError, OSError) as exc:
            raise RetirementError(f"run evidence identity differs: {role}: {exc}") from exc
        identity = {"manifest_role": role, "bytes": record.get("bytes"), "sha256": record.get("sha256")}
        if path in result and any(result[path][key] != identity[key] for key in ("bytes", "sha256")):
            raise RetirementError(f"conflicting sealed records: {path}")
        result[path] = identity
    if record_path(manifest["run_config"], base_dir=run["dir"]) != run["dir"] / "run_config.json":
        raise RetirementError("manifest does not bind the local run config")
    if (
        run["dir"] / "summary.json" not in result
        and not run.get("legacy_initialization_summary")
    ):
        raise RetirementError("manifest does not bind the local summary")
    def configured_paths(value: Any, *, name: str) -> list[Path]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [record_path({"path": value}, base_dir=run["dir"])]
        if isinstance(value, (list, tuple)):
            return [
                path for index, member in enumerate(value)
                for path in configured_paths(member, name=f"{name}[{index}]")
            ]
        if isinstance(value, dict):
            return [
                path for key, member in value.items()
                for path in configured_paths(member, name=f"{name}.{key}")
            ]
        raise RetirementError(f"configured input has an invalid shape: {name}")

    def is_bound_path(configured: Path, recorded: Path) -> bool:
        if configured == recorded:
            return True
        try:
            relative = recorded.relative_to(run["dir"])
        except ValueError:
            return False
        # Short execution aliases can disappear after publication.  Accept
        # their durable artifact copy only when the role record is inside this
        # run and the complete multi-component relative suffix agrees.  An
        # existing divergent source remains ambiguous and fails closed.
        return (
            not configured.exists()
            and len(relative.parts) >= 2
            and tuple(part.lower() for part in configured.parts[-len(relative.parts):])
            == tuple(part.lower() for part in relative.parts)
        )

    for name, configured_value in run["config"].get("inputs", {}).items():
        paths = configured_paths(configured_value, name=name)
        if isinstance(configured_value, str) and configured_value:
            record = manifest.get("inputs", {}).get(name)
            if (
                not isinstance(record, dict)
                or not is_bound_path(
                    paths[0], record_path(record, base_dir=run["dir"])
                )
            ):
                raise RetirementError(f"manifest does not bind configured input: {name}")
        elif any(
            not any(is_bound_path(path, recorded) for recorded in result)
            for path in paths
        ):
            raise RetirementError(f"manifest does not bind configured input collection: {name}")
    if inherit_heavy_identity:
        # Only a verified parent record can introduce a nested manifest; never
        # discover arbitrary manifests from the filesystem.
        for path in tuple(result):
            if path.name != "run_manifest.json":
                continue
            if (not path.parent.is_relative_to(run["dir"])
                    and result[path]["manifest_role"].startswith("input:")):
                # An external input was fully verified above. It is provenance,
                # not a local child whose payload this owner may inherit/retire.
                continue
            if not path.parent.is_relative_to(run["dir"]) or path.parent == run["dir"]:
                raise RetirementError(f"child manifest is not a strict local descendant: {path}")
            child = _load_run(path.parent, expected_run_id=run["config"]["run_id"])
            if (child["config"].get("project") != run["config"].get("project")
                    or child["manifest"].get("project") != run["manifest"].get("project")):
                raise RetirementError(f"child manifest owner differs: {path}")
            for member, identity in _manifest_records(
                child, retired_paths=retired, inherit_heavy_identity=True,
            ).items():
                if member in result and any(result[member][key] != identity[key] for key in ("bytes", "sha256")):
                    raise RetirementError(f"conflicting sealed records: {member}")
                result[member] = identity
    return result


def _runtime_checkpoint_members(
    run: dict[str, Any], checkpoint_path: Path, records: dict[Path, dict[str, Any]],
    retired_paths: Iterable[Path] = (),
) -> dict[Path, dict[str, Any]]:
    """Inherit only a sealed private native family's direct numbered members.

    The checkpoint remains evidence, not a new PA publication.  No payload is
    hashed; paths, sizes and the existing checkpoint identities govern removal.
    """
    checkpoint_path = _under(checkpoint_path, run["dir"])
    record = records.get(checkpoint_path)
    if not record or not str(record["manifest_role"]).startswith("output:"):
        raise RetirementError("runtime checkpoint must be a manifest-bound local output")
    checkpoint = _json(checkpoint_path)
    receipt = checkpoint.get("runtime_receipt")
    members = checkpoint.get("members")
    if (checkpoint.get("schema_version") != 1 or checkpoint.get("status") != "prepared"
            or not isinstance(receipt, dict) or receipt.get("status") != "prepared"
            or receipt.get("run_id") != run["dir"].name
            or not isinstance(members, list) or not members):
        raise RetirementError("runtime checkpoint owner or prepared inventory differs")
    raw_directory = Path(str(checkpoint.get("directory", "")))
    directory = _under(raw_directory, run["dir"] / "runtime")
    if (directory.parent != run["dir"] / "runtime" or raw_directory.is_symlink()
            or directory.parent.is_symlink() or not directory.is_dir()):
        raise RetirementError("runtime checkpoint directory must be a direct private runtime")
    controller = _under(Path(str(receipt.get("controller_path", ""))), directory)
    responses = receipt.get("source_responses")
    if (controller.parent != directory or controller.suffix.lower() != ".pa0"
            or not isinstance(responses, list) or not responses
            or [item.get("response_id") if isinstance(item, dict) else None for item in responses]
            != list(range(1, len(responses) + 1))):
        raise RetirementError("runtime checkpoint controller or response inventory differs")
    expected_names = [controller.stem + ".pa" + str(index) for index in range(len(responses) + 1)]
    if [item.get("name") if isinstance(item, dict) else None for item in members] != expected_names:
        raise RetirementError("runtime checkpoint must enumerate exactly its numbered family")
    retired = set(retired_paths)
    inherited = {}
    for item in members:
        path = directory / item["name"]
        size, sha = item.get("bytes"), item.get("sha256")
        if (isinstance(size, bool) or not isinstance(size, int) or size <= 0
                or not isinstance(sha, str) or len(sha) != 64
                or any(char not in "0123456789abcdef" for char in sha.lower())
                or path.is_symlink() or (path not in retired and (
                    not path.is_file() or path.stat().st_size != size))):
            raise RetirementError(f"sealed runtime member differs: {path}")
        identity = {"manifest_role": "runtime_checkpoint_member", "bytes": size, "sha256": sha}
        if path in records and any(records[path][key] != identity[key] for key in ("bytes", "sha256")):
            raise RetirementError(f"conflicting sealed runtime member: {path}")
        inherited[path] = identity
    return inherited


def _assert_runtime_retirement_unprotected(artifact_root: Path, target: Path) -> None:
    """Reuse the current-GUI owner's explicit source protection projection."""
    from common.contracts.reconcile_artifact_capacity import (
        _current_gui_source_paths, _current_gui_source_retention,
    )

    _current_gui_source_paths.cache_clear()
    if _current_gui_source_retention(artifact_root, target):
        raise RetirementError("stopped runtime remains a current GUI source")


def _runtime_scope_path(document: dict[str, Any], target: Path) -> Path | None:
    """Validate the explicit stopped scope in a plan or completed receipt."""
    if "stopped_checkpoint_runtime" not in document:
        return None
    scope = document["stopped_checkpoint_runtime"]
    if (document.get("retirement_mode") != "completed_experiment"
            or not isinstance(scope, dict) or set(scope) != {"writing_stopped", "checkpoint"}
            or scope["writing_stopped"] is not True or not isinstance(scope["checkpoint"], dict)):
        raise RetirementError("invalid stopped checkpoint runtime scope")
    record = scope["checkpoint"]
    if set(record) != {"path", "bytes", "sha256"} or not isinstance(record["path"], str):
        raise RetirementError("invalid stopped runtime checkpoint record")
    path = _under(target / record["path"], target)
    if record["path"] != path.relative_to(target).as_posix():
        raise RetirementError("runtime checkpoint scope path must be canonical run-relative")
    try:
        verify_record("stopped runtime checkpoint", {**record, "exists": True}, base_dir=target)
    except (AssertionError, KeyError, OSError, TypeError, ValueError) as exc:
        raise RetirementError("stopped runtime checkpoint identity differs") from exc
    return path


def _freeze_stopped_consumers(
    paths: Iterable[Path], artifact_root: Path, target: Path, owner: str,
) -> list[dict[str, Any]]:
    """Bind stopped consumers to this owner decision without changing their state.

    Writer/child-process cessation is the owner's explicit confirmation at the
    existing entry point.  Leases, current GUI use and sealed small identities
    are independently rechecked here; missing manifests never imply cessation.
    """
    result = []
    paths = tuple(paths)
    if not paths:
        return result
    seen = set()
    leases = protection.load_capacity_protection_leases(artifact_root)
    for path in paths:
        run = _under(path, artifact_root)
        if (run in seen or run == target or path.is_symlink() or not run.is_dir()
                or run.parent != artifact_root / "projects" / owner / "runs"):
            raise RetirementError("approved stopped consumer must be a unique same-owner project run")
        seen.add(run)
        config, summary, manifest = (_json(run / name) for name in (
            "run_config.json", "summary.json", "run_manifest.json"))
        if (config.get("run_id") != run.name or manifest.get("run_id") != run.name
                or summary.get("run_id") not in {None, run.name}
                or config.get("project") != owner or manifest.get("project") != owner
                or manifest.get("status") != "checkpoint" or summary.get("status") != "checkpoint"):
            raise RetirementError("approved stopped consumer identity or checkpoint state differs")
        if protection.path_is_protected(run, leases["protected_paths"]):
            raise RetirementError("approved stopped consumer has an active protection lease")
        _assert_runtime_retirement_unprotected(artifact_root, run)
        config_record = manifest.get("run_config")
        summary_records = [record for record in manifest.get("outputs", [])
                           if isinstance(record, dict)
                           and record_path(record, base_dir=run) == run / "summary.json"]
        if (not isinstance(config_record, dict) or record_path(config_record, base_dir=run) != run / "run_config.json"
                or len(summary_records) != 1):
            raise RetirementError("approved stopped consumer must seal its local config and summary")
        records = {}
        for name, record in (("run_config", config_record), ("summary", summary_records[0])):
            try:
                verify_record("approved stopped consumer " + name, record, base_dir=run)
            except (AssertionError, KeyError, OSError, TypeError, ValueError) as exc:
                raise RetirementError("approved stopped consumer sealed evidence differs") from exc
            records[name] = {"path": str(run / (name + ".json")), "bytes": record["bytes"],
                             "sha256": str(record["sha256"]).upper()}
        if not (structured_target_references(config, target, target.name)
                | structured_target_references(manifest, target, target.name)):
            raise RetirementError("approved stopped consumer does not reference this retirement target")
        manifest_path = run / "run_manifest.json"
        result.append({"run_path": str(run), "run_id": run.name, "owner": owner, **records,
                       "manifest": {"path": str(manifest_path), "bytes": manifest_path.stat().st_size,
                                    "sha256": file_sha256(manifest_path)}})
    return sorted(result, key=lambda item: item["run_path"])


def _verify_stopped_consumers(document: dict[str, Any], target: Path) -> list[dict[str, Any]]:
    """Recheck the same frozen list for apply, pending replay and verification."""
    approved = document.get("approved_stopped_consumers", [])
    if not isinstance(approved, list):
        raise RetirementError("approved stopped consumers must be a frozen list")
    if not approved:
        return []
    if _runtime_scope_path(document, target) is None:
        raise RetirementError("stopped consumer approval is limited to stopped runtime retirement")
    if any(not isinstance(item, dict) or not isinstance(item.get("run_path"), str) for item in approved):
        raise RetirementError("approved stopped consumer record is invalid")
    refreshed = _freeze_stopped_consumers(
        [Path(item["run_path"]) for item in approved], Path(document["artifact_root"]), target, document["owner"])
    if refreshed != approved:
        raise RetirementError("approved stopped consumer evidence changed")
    return refreshed


def _file_inventory(
    run: dict[str, Any], *, retired_paths: Iterable[Path] = (),
    inherit_heavy_identity: bool = False,
    runtime_checkpoint_path: Path | None = None,
) -> list[dict[str, Any]]:
    root: Path = run["dir"]
    records = _manifest_records(
        run, retired_paths=retired_paths, inherit_heavy_identity=inherit_heavy_identity,
    )
    if runtime_checkpoint_path is not None:
        records.update(_runtime_checkpoint_members(run, runtime_checkpoint_path, records, retired_paths))
    inventory: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        if path.name == RECEIPT_NAME:
            continue
        record = records.get(path.resolve())
        bytes_count = path.stat().st_size
        manifest_sha = str(record.get("sha256")).upper() if record and record.get("sha256") else None
        inherited = inherit_heavy_identity and classify_file(path, bytes_count=bytes_count) in HEAVY_ROLES
        if inherited and not record:
            raise RetirementError(f"heavy payload lacks sealed identity: {path}")
        actual_sha = manifest_sha if inherited else file_sha256(path)
        if record and (record["bytes"] != bytes_count or manifest_sha != actual_sha):
            raise RetirementError(f"manifest identity changed: {path}")
        inventory.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": bytes_count,
            "sha256": actual_sha,
            "manifest_sha256": manifest_sha,
            "manifest_identity_matches": manifest_sha is None or manifest_sha == actual_sha,
            "identity_source": "sealed_manifest" if inherited else "computed_before_retirement",
            "manifest_role": record.get("manifest_role") if record else None,
            "retention_role": classify_file(path, bytes_count=bytes_count),
        })
    return inventory


def _topology_compatible(
    target: dict[str, Any],
    replacement: dict[str, Any],
    required_input_roles: Iterable[str],
    input_role_mappings: Iterable[tuple[str, str]],
    *, prepared_gui_checkpoint: bool = False,
) -> dict[str, Any]:
    for field in ("project", "mode"):
        if target["config"].get(field) != replacement["config"].get(field):
            raise RetirementError(f"replacement {field} differs")
    required_roles = {role.strip() for role in required_input_roles if role.strip()}
    mappings = [(target_role.strip(), replacement_role.strip())
                for target_role, replacement_role in input_role_mappings]
    if not required_roles and not mappings:
        raise RetirementError(
            "at least one compatibility input role or role mapping is required"
        )
    if any(not target_role or not replacement_role for target_role, replacement_role in mappings):
        raise RetirementError("compatibility input role mappings must name both roles")
    if (
        len({target_role for target_role, _ in mappings}) != len(mappings)
        or len({replacement_role for _, replacement_role in mappings}) != len(mappings)
    ):
        raise RetirementError("compatibility input role mappings must be one-to-one")
    target_roles = set(target["config"].get("inputs", {}))
    replacement_roles = set(replacement["config"].get("inputs", {}))
    missing_target = required_roles - target_roles
    missing_replacement = required_roles - replacement_roles
    if missing_target or missing_replacement:
        raise RetirementError(
            f"three-component geometry identity roles missing: target={sorted(missing_target)}, "
            f"replacement={sorted(missing_replacement)}"
        )
    verified_mappings: list[dict[str, Any]] = []
    for target_role, replacement_role in mappings:
        if target_role not in target_roles or replacement_role not in replacement_roles:
            raise RetirementError(
                "compatibility input mapping roles missing: "
                f"target={target_role!r}, replacement={replacement_role!r}"
            )
        target_record = target["manifest"].get("inputs", {}).get(target_role)
        replacement_record = replacement["manifest"].get("inputs", {}).get(replacement_role)
        if not isinstance(target_record, dict) or not isinstance(replacement_record, dict):
            raise RetirementError(
                "compatibility input mapping lacks manifest records: "
                f"target={target_role!r}, replacement={replacement_role!r}"
            )
        target_identity = (target_record.get("bytes"), str(target_record.get("sha256", "")).upper())
        replacement_identity = (
            replacement_record.get("bytes"),
            str(replacement_record.get("sha256", "")).upper(),
        )
        if target_identity != replacement_identity or not target_identity[1]:
            raise RetirementError(
                "compatibility input mapping identity differs: "
                f"target={target_role!r}, replacement={replacement_role!r}"
            )
        verified_mappings.append({
            "target_role": target_role,
            "replacement_role": replacement_role,
            "bytes": target_identity[0],
            "sha256": target_identity[1],
        })
    return {
        "project": target["config"]["project"],
        "mode": target["config"]["mode"],
        "required_input_roles": sorted(required_roles),
        "replacement_role_superset": required_roles.issubset(replacement_roles),
        "verified_input_role_mappings": verified_mappings,
        "semantics": (
            "same project/mode and caller-declared preparation roles; independently validated newer "
            "unflown GUI replaces the obsolete preparation; scientific inputs and geometry may differ"
            if prepared_gui_checkpoint else
            "same project/mode, caller-declared compatibility input roles, and "
            "identity-equal explicitly mapped legacy roles; "
            "domain-specific topology semantics remain outside the common retirement layer"
        ),
    }


def _selected_heavy_paths(value: Iterable[str] | None) -> list[str] | None:
    """Validate an explicit owner selection without inferring scientific roles."""
    if value is None:
        return None
    if isinstance(value, str):
        raise RetirementError("selected heavy paths must be a collection")
    paths = list(value)
    if (not paths or any(not isinstance(p, str) or not p or "\\" in p
            or Path(p).is_absolute() or ":" in p or p != posixpath.normpath(p)
            or any(part in {"", ".", ".."} for part in p.split("/")) for p in paths)
            or len({p.casefold() for p in paths}) != len(paths)):
        raise RetirementError("selected heavy paths must be nonempty unique canonical run-relative paths")
    return sorted(paths)


def _selected_heavy_records(inventory: list[dict[str, Any]], selected: list[str] | None) -> list[dict[str, Any]]:
    heavy = [item for item in inventory if item["retention_role"] in HEAVY_ROLES]
    if selected is None:
        return heavy
    chosen = [item for item in heavy if item["path"] in selected]
    if ({item["path"] for item in chosen} != set(selected)
            or any(not item.get("manifest_sha256") or not item.get("manifest_role") for item in chosen)):
        raise RetirementError("selected paths must identify sealed governed heavy payload only")
    return chosen


def plan_retirement(
    artifact_root: Path, repository_root: Path, target_run: Path, replacement_run: Path | None = None,
    compatibility_assertion: str = "", compatibility_input_roles: Iterable[str] = (),
    compatibility_input_role_mappings: Iterable[tuple[str, str]] = (),
    *, owner: str = "", owner_abandonment_reason: str = "",
    runtime_checkpoint_path: Path | None = None, writing_stopped: bool = False,
    approved_stopped_consumers: Iterable[Path] = (),
    prepared_gui_checkpoint: bool = False,
    selected_heavy_paths: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Plan supersession or owner-approved completion; retain all small evidence."""
    owner_mode = bool(owner or owner_abandonment_reason)
    runtime_mode = runtime_checkpoint_path is not None
    gui_mode = prepared_gui_checkpoint
    selected = _selected_heavy_paths(selected_heavy_paths)
    if selected is not None and (not owner_mode or runtime_mode or gui_mode):
        raise RetirementError("selected heavy scope requires ordinary owner completion")
    if gui_mode and (runtime_mode or not writing_stopped):
        raise RetirementError("prepared GUI retirement requires explicit scope and confirmed stopped writing")
    approved_stopped_consumers = tuple(approved_stopped_consumers)
    if approved_stopped_consumers and not (owner_mode and runtime_mode and writing_stopped):
        raise RetirementError("stopped consumer approval requires the confirmed owner runtime scope")
    if (runtime_mode and (not owner_mode or not writing_stopped)) or (writing_stopped and not (runtime_mode or gui_mode)):
        raise RetirementError("runtime retirement requires explicit owner completion and confirmed stopped writing")
    compatibility_input_roles = tuple(compatibility_input_roles)
    compatibility_input_role_mappings = tuple(compatibility_input_role_mappings)
    if owner_mode:
        if not owner.strip() or not owner_abandonment_reason.strip():
            raise RetirementError("owner completion requires owner and a nonempty abandonment reason")
        if replacement_run or compatibility_assertion or compatibility_input_roles or compatibility_input_role_mappings:
            raise RetirementError("owner completion and superseded modes are mutually exclusive")
    elif replacement_run is None or not compatibility_assertion.strip():
        raise RetirementError("superseded mode requires replacement and compatibility assertion")
    artifact_root = artifact_root.resolve()
    repository_root = repository_root.resolve()
    target_run = _under(target_run, artifact_root)
    replacement_run = _under(replacement_run, artifact_root) if replacement_run else None
    if target_run == replacement_run:
        raise RetirementError("target and replacement must differ")
    approved_consumers = _freeze_stopped_consumers(
        approved_stopped_consumers, artifact_root, target_run, owner.strip())
    prior_pending_sha: str | None = None
    prior_removed_missing: list[dict[str, Any]] = []
    if (target_run / RECEIPT_NAME).exists():
        prior = _json(target_run / RECEIPT_NAME)
        if prior.get("lifecycle_status") != "retirement_pending":
            raise RetirementError("target already has a completed retirement receipt")
        prior_removed_missing = [
            {**item, "already_removed_before_resume": True}
            for item in prior.get("removed_files", [])
            if not (target_run / item["path"]).is_file()
        ]
        prior_pending_sha = file_sha256(target_run / RECEIPT_NAME)
        prior_runtime = _runtime_scope_path(prior, target_run)
        requested_runtime = _under(runtime_checkpoint_path, target_run) if runtime_mode else None
        if prior_runtime != requested_runtime:
            raise RetirementError("pending retirement runtime scope changed")
        if _prepared_gui_scope(prior) != gui_mode:
            raise RetirementError("pending retirement prepared GUI scope changed")
        if prior.get("selected_heavy_paths") != selected:
            raise RetirementError("pending retirement selected heavy scope changed")
        if prior.get("approved_stopped_consumers", []) != approved_consumers:
            raise RetirementError("pending retirement stopped consumer list or identity changed")
    target = _load_run(
        target_run,
        allowed_statuses=("checkpoint",) if runtime_mode or gui_mode else (
            ("success", "failed", "interrupted") if owner_mode else ("success", "failed")),
        label="target",
        allow_legacy_initialization_summary=not owner_mode,
        stopped_checkpoint_runtime=runtime_mode,
        prepared_gui_checkpoint=gui_mode,
    )
    if owner_mode and target["config"].get("project") != owner.strip():
        raise RetirementError("completed experiment owner differs from target project")
    replacement = _load_run(replacement_run, label="replacement",
                            allowed_statuses=("checkpoint",) if gui_mode else ("success",),
                            prepared_gui_checkpoint=gui_mode) if replacement_run else None
    if replacement:
        replacement_records = _manifest_records(replacement)
        if gui_mode:
            _prepared_gui_inventory(replacement, replacement_records)
    if prior_pending_sha and (
        prior["target_manifest"]["sha256"] != file_sha256(target_run / "run_manifest.json")
        or prior.get("owner", "") != owner.strip()
        or prior.get("owner_abandonment_reason", "") != owner_abandonment_reason.strip()
        or prior.get("replacement_manifest") != (
            {"bytes": (replacement_run / "run_manifest.json").stat().st_size,
             "sha256": file_sha256(replacement_run / "run_manifest.json")} if replacement_run else None
        )
        or prior["replacement_run_path"] != (str(replacement_run) if replacement_run else None)
    ):
        raise RetirementError("pending retirement manifest identity changed")
    if replacement and _recorded_at(replacement) <= _recorded_at(target):
        raise RetirementError("replacement is not newer than target")
    if replacement and target["config"].get("project") != replacement["config"].get("project"):
        raise RetirementError("replacement belongs to another project")
    document_refs = _git_document_references(repository_root, target_run.name)
    leases = protection.load_capacity_protection_leases(artifact_root)
    if protection.path_is_protected(target_run, leases["protected_paths"]):
        raise RetirementError("target is covered by an active capacity protection lease")
    if runtime_mode or gui_mode:
        _assert_runtime_retirement_unprotected(artifact_root, target_run)
    if runtime_mode:
        runtime_checkpoint_path = _under(runtime_checkpoint_path, target_run)
    topology = _topology_compatible(
        target, replacement, compatibility_input_roles,
        compatibility_input_role_mappings,
        prepared_gui_checkpoint=gui_mode,
    ) if replacement else None
    inventory = _file_inventory(
        target, retired_paths=[_under(target_run / item["path"], target_run) for item in prior_removed_missing],
        inherit_heavy_identity=owner_mode or gui_mode,
        runtime_checkpoint_path=runtime_checkpoint_path,
    )
    if gui_mode:
        _prepared_gui_inventory(target, _manifest_records(target,
            retired_paths=[_under(target_run / item["path"], target_run) for item in prior_removed_missing],
            inherit_heavy_identity=True))
    _selected_heavy_records(prior_removed_missing + inventory, selected)
    removed_current = [item for item in inventory if item["retention_role"] in HEAVY_ROLES
                       and (selected is None or item["path"] in selected)]
    if runtime_mode and any(item["manifest_role"] != "runtime_checkpoint_member" for item in removed_current):
        raise RetirementError("stopped checkpoint retirement is limited to its sealed runtime members")
    removed = prior_removed_missing + removed_current
    if not removed:
        raise RetirementError("target contains no governed heavy payload")
    preserved = [item for item in inventory if item not in removed]
    downstream_refs = _downstream_references(
        artifact_root,
        target_run,
        target_run.name,
        removable_paths=[item["path"] for item in removed] + (
            [runtime_checkpoint_path.relative_to(target_run).as_posix()] if runtime_mode else []),
        preserved_paths=(item["path"] for item in preserved),
        approved_stopped_consumers=approved_consumers,
    )
    if downstream_refs["active"]:
        raise RetirementError(
            "target still has active references in downstream run_config: "
            f"{downstream_refs['active']}"
        )
    return {
        "schema_version": 1,
        "role": "solver_review_retirement_plan",
        "status": "eligible",
        "target_run_id": target_run.name,
        "target_run_path": str(target_run),
        **({"selected_heavy_paths": selected} if selected is not None else {}),
        **({"prepared_gui_checkpoint": {"writing_stopped": True}} if gui_mode else {}),
        **({"retirement_mode": "completed_experiment", "owner": owner.strip(),
            "owner_abandonment_reason": owner_abandonment_reason.strip()} if owner_mode else {}),
        **({"stopped_checkpoint_runtime": {
            "writing_stopped": True,
            "checkpoint": {"path": runtime_checkpoint_path.relative_to(target_run).as_posix(),
                           "bytes": runtime_checkpoint_path.stat().st_size,
                           "sha256": file_sha256(runtime_checkpoint_path)},
        }} if runtime_mode else {}),
        **({"approved_stopped_consumers": approved_consumers} if approved_consumers else {}),
        "replacement_run_id": replacement_run.name if replacement_run else None,
        "replacement_run_path": str(replacement_run) if replacement_run else None,
        "artifact_root": str(artifact_root),
        "repository_root": str(repository_root),
        "compatibility_assertion": compatibility_assertion.strip(),
        "compatibility_checks": topology,
        "target_terminal_status": target["manifest"]["status"],
        "target_legacy_initialization_summary": target[
            "legacy_initialization_summary"
        ],
        "target_manifest": {"bytes": (target_run / "run_manifest.json").stat().st_size, "sha256": file_sha256(target_run / "run_manifest.json")},
        "replacement_manifest": {"bytes": (replacement_run / "run_manifest.json").stat().st_size, "sha256": file_sha256(replacement_run / "run_manifest.json")} if replacement_run else None,
        "original_file_inventory": inventory,
        "removed_files": removed,
        "preserved_files": preserved,
        "bytes_to_release": sum(item["bytes"] for item in removed_current),
        "total_retired_bytes": sum(item["bytes"] for item in removed),
        "historical_document_references": document_refs,
        "historical_downstream_references": downstream_refs["historical"],
        "active_preserved_file_references": downstream_refs["active_preserved"],
        "corrupt_run_config_reference_unavailable": downstream_refs[
            "corrupt_run_config_reference_unavailable"
        ],
        "capacity_protection_audit": leases["audit"],
        "recovery_of_pending_receipt_sha256": prior_pending_sha,
    }


def apply_retirement(plan: dict[str, Any]) -> dict[str, Any]:
    if not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
        raise RetirementError("apply requires the shared HostExecutionLease")
    try:
        artifact_root = Path(plan["artifact_root"]).resolve()
    except (KeyError, TypeError, ValueError) as exc:
        raise RetirementError("retirement plan lacks governed root identity") from exc
    target = _under(Path(plan["target_run_path"]), artifact_root)
    receipt_path = target / RECEIPT_NAME
    with protection.capacity_decision_lock(artifact_root):
        runtime_checkpoint_path = _runtime_scope_path(plan, target)
        gui_mode = _prepared_gui_scope(plan)
        if (_selected_heavy_paths(plan.get("selected_heavy_paths")) is not None
                and (plan.get("retirement_mode") != "completed_experiment" or runtime_checkpoint_path is not None or gui_mode)):
            raise RetirementError("selected heavy scope requires ordinary owner completion")
        approved_consumers = _verify_stopped_consumers(plan, target)
        if runtime_checkpoint_path is not None or gui_mode:
            _assert_runtime_retirement_unprotected(artifact_root, target)
        leases = protection.load_capacity_protection_leases(artifact_root)
        if protection.path_is_protected(target, leases["protected_paths"]):
            raise RetirementError(
                "target gained an active capacity protection lease before apply"
            )
        downstream = _downstream_references(
            artifact_root,
            target,
            target.name,
            removable_paths=[item["path"] for item in plan["removed_files"]] + (
                [runtime_checkpoint_path.relative_to(target).as_posix()] if runtime_checkpoint_path is not None else []),
            preserved_paths=(item["path"] for item in plan["preserved_files"]),
            approved_stopped_consumers=approved_consumers,
        )
        if downstream["active"]:
            raise RetirementError(
                "target gained active references before retirement decision: "
                f"{downstream['active']}"
            )
        if receipt_path.exists():
            marker = _json(receipt_path)
            if not (
                marker.get("lifecycle_status") == "retirement_pending"
                and marker.get("target_manifest") == plan.get("target_manifest")
                and marker.get("replacement_manifest") == plan.get("replacement_manifest")
                and marker.get("selected_heavy_paths") == plan.get("selected_heavy_paths")
            ):
                raise RetirementError("target already has another retirement marker")
        else:
            _atomic_json(
                receipt_path,
                {
                    **plan,
                    "role": "solver_review_retirement_receipt",
                    "status": "preflight_pending",
                    "lifecycle_status": "retirement_pending",
                    "started_at_utc": datetime.now(timezone.utc).isoformat().replace(
                        "+00:00", "Z"
                    ),
                },
            )
    return _apply_retirement_locked(plan)


def _apply_retirement_locked(plan: dict[str, Any]) -> dict[str, Any]:
    owner_mode = plan.get("retirement_mode") == "completed_experiment"
    try:
        artifact_root = Path(plan["artifact_root"]).resolve()
        repository_root = Path(plan["repository_root"]).resolve()
        target = _under(Path(plan["target_run_path"]), artifact_root)
        replacement = (
            _under(Path(plan["replacement_run_path"]), artifact_root) if not owner_mode else None
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RetirementError("retirement plan lacks governed root identity") from exc
    manifest_paths = [("target", target)]
    runtime_checkpoint_path = _runtime_scope_path(plan, target)
    runtime_mode = runtime_checkpoint_path is not None
    gui_mode = _prepared_gui_scope(plan)
    approved_consumers = _verify_stopped_consumers(plan, target)
    if replacement:
        manifest_paths.append(("replacement", replacement))
    for label, path in manifest_paths:
        if file_sha256(path / "run_manifest.json") != plan[f"{label}_manifest"]["sha256"]:
            raise RetirementError(f"{label} run manifest changed before apply")
    replacement_state = _load_run(replacement, label="replacement",
                                  allowed_statuses=("checkpoint",) if gui_mode else ("success",),
                                  prepared_gui_checkpoint=gui_mode) if replacement else None
    if replacement_state:
        replacement_records = _manifest_records(replacement_state)
        if gui_mode:
            _prepared_gui_inventory(replacement_state, replacement_records)
    target_state = _load_run(
        target,
        allowed_statuses=("checkpoint",) if runtime_mode or gui_mode else (
            ("success", "failed", "interrupted") if owner_mode else ("success", "failed")),
        label="target",
        allow_legacy_initialization_summary=not owner_mode,
        stopped_checkpoint_runtime=runtime_mode,
        prepared_gui_checkpoint=gui_mode,
    )
    if plan.get("target_terminal_status") != target_state["manifest"]["status"]:
        raise RetirementError("target terminal status changed before apply")
    if bool(plan.get("target_legacy_initialization_summary")) != bool(
        target_state["legacy_initialization_summary"]
    ):
        raise RetirementError("target legacy summary state changed before apply")
    if owner_mode:
        if (plan.get("owner") != target_state["config"].get("project")
                or not str(plan.get("owner_abandonment_reason", "")).strip()
                or any(plan.get(key) for key in (
                    "replacement_run_path", "replacement_run_id", "replacement_manifest",
                    "compatibility_assertion", "compatibility_checks",
                ))):
            raise RetirementError("completed experiment owner decision is invalid")
    else:
        if _recorded_at(replacement_state) <= _recorded_at(target_state):
            raise RetirementError("replacement is not newer than target before apply")
        checks = plan.get("compatibility_checks")
        if not isinstance(checks, dict):
            raise RetirementError("retirement plan lacks compatibility checks")
        mapped = checks.get("verified_input_role_mappings", [])
        if not isinstance(mapped, list) or any(not isinstance(item, dict) for item in mapped):
            raise RetirementError("retirement plan compatibility mappings are invalid")
        refreshed_topology = _topology_compatible(
            target_state, replacement_state,
            checks.get("required_input_roles", ()),
            [
                (str(item.get("target_role", "")), str(item.get("replacement_role", "")))
                for item in mapped
            ],
            prepared_gui_checkpoint=gui_mode,
        )
        if refreshed_topology != checks:
            raise RetirementError("retirement compatibility changed before apply")
    document_refs = _git_document_references(repository_root, target.name)
    downstream_refs = _downstream_references(
        artifact_root,
        target,
        target.name,
        removable_paths=[item["path"] for item in plan["removed_files"]] + (
            [runtime_checkpoint_path.relative_to(target).as_posix()] if runtime_mode else []),
        preserved_paths=(item["path"] for item in plan["preserved_files"]),
        approved_stopped_consumers=approved_consumers,
    )
    if downstream_refs["active"]:
        raise RetirementError(
            "target gained active references in downstream run_config before apply: "
            f"{downstream_refs['active']}"
        )
    leases = protection.load_capacity_protection_leases(artifact_root)
    if protection.path_is_protected(target, leases["protected_paths"]):
        raise RetirementError(
            "target gained an active capacity protection lease before apply"
        )
    if runtime_mode or gui_mode:
        _assert_runtime_retirement_unprotected(artifact_root, target)
    inventory = _file_inventory(
        target_state, retired_paths=[
            _under(target / item["path"], target)
            for item in plan["removed_files"] if item.get("already_removed_before_resume")
        ],
        inherit_heavy_identity=owner_mode or gui_mode,
        runtime_checkpoint_path=runtime_checkpoint_path,
    )
    if owner_mode or gui_mode:
        planned_inventory = [
            item for item in plan["original_file_inventory"]
            if not any(item["path"] == removed["path"] and removed.get("already_removed_before_resume")
                       for removed in plan["removed_files"])
        ]
        if inventory != planned_inventory:
            raise RetirementError("completed experiment inventory changed before apply")
        selected = _selected_heavy_paths(plan.get("selected_heavy_paths"))
        if selected is not None and (not owner_mode or runtime_mode or gui_mode):
            raise RetirementError("selected heavy scope requires ordinary owner completion")
        old_missing = [item for item in plan["removed_files"] if item.get("already_removed_before_resume")]
        _selected_heavy_records(old_missing + inventory, selected)
        expected_removed = [item for item in inventory if item["retention_role"] in HEAVY_ROLES
                            and (selected is None or item["path"] in selected)]
        actual_removed = [item for item in plan["removed_files"] if not item.get("already_removed_before_resume")]
        if actual_removed != expected_removed or plan["preserved_files"] != [
            item for item in inventory if item not in expected_removed
        ]:
            raise RetirementError("completed experiment removal scope differs from inventory")
    receipt_path = target / RECEIPT_NAME
    pending = {
        **plan,
        "role": "solver_review_retirement_receipt",
        "lifecycle_status": "retirement_pending",
        "started_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "apply_historical_document_references": document_refs,
        "apply_historical_downstream_references": downstream_refs["historical"],
        "apply_active_preserved_file_references": downstream_refs["active_preserved"],
        "apply_corrupt_run_config_reference_unavailable": downstream_refs[
            "corrupt_run_config_reference_unavailable"
        ],
        "apply_capacity_protection_audit": leases["audit"],
    }
    _atomic_json(receipt_path, pending)
    removed_bytes = 0
    try:
        for item in plan["removed_files"]:
            path = _under(target / item["path"], target)
            if item.get("already_removed_before_resume"):
                if path.exists():
                    raise RetirementError(f"previously removed payload reappeared: {item['path']}")
                removed_bytes += item["bytes"]
                continue
            try:
                for _ in remove_recorded_files(
                    target, [item], identities_verified=True
                ):
                    pass
            except ValueError as exc:
                raise RetirementError(str(exc)) from exc
            removed_bytes += item["bytes"]
        complete = {
            **pending,
            "lifecycle_status": "completed_experiment_payload_retired" if owner_mode else "superseded_payload_retired",
            "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "removed_bytes": removed_bytes,
            "bytes_released_this_apply": plan["bytes_to_release"],
            "verification_semantics": (
                "The immutable original run manifest describes the pre-retirement run and is intentionally no "
                "longer complete on disk. Consumers must reject it and use this receipt verifier for historical "
                "provenance only."
            ),
        }
        _atomic_json(receipt_path, complete)
        return complete
    except Exception:
        # The pending receipt makes partial deletion explicit and fail-closed.
        raise


_VIEW_REPAIR_MIN_BYTES = 8 * 1024**2


@contextmanager
def _payload_owner_lock(path: Path):
    """Serialize this exact stopped-file transaction with a Windows kernel mutex.

    Unlike the capacity decision lock this target-specific owner lock may span
    copies and hashes. The kernel releases it after process exit; no run-local
    lock file or additional lifecycle state is created.
    https://learn.microsoft.com/windows/win32/sync/using-mutex-objects
    """
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    name = "Local\\MassSpectrometryPreservedPA_" + hashlib.sha256(str(path).casefold().encode()).hexdigest()
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise OSError(ctypes.get_last_error(), "cannot create payload owner mutex")
    acquired = False
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        if result not in (0, 0x80):
            raise RetirementError("preserved payload already has an active repair owner")
        acquired = True
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def _assert_payload_repair_capacity(root: Path, source: Path, audit: Path,
                                    owner: str, lease_id: str, budget: int) -> None:
    """Check only lease metadata; caller holds the short capacity decision lock."""
    leases = protection.load_capacity_protection_leases(root)
    active = [v for v in leases["audit"] if v.get("status") == "active"]
    own = [v for v in active if v["lease_id"] == lease_id]
    if len(own) != 1 or own[0]["owner"] != f"owned-payload-view-repair:{owner}:{audit.name}":
        raise RetirementError("payload repair requires its explicit active capacity lease")
    for entry in active:
        protected_paths = [Path(value) for value in entry["protected_paths"]]
        if entry["lease_id"] == lease_id:
            if (entry.get("committed_new_bytes", 0) < budget
                    or not protection.path_is_protected(source, protected_paths)
                    or not protection.path_is_protected(audit, protected_paths)):
                raise RetirementError("payload repair capacity reservation or protection is incomplete")
        elif (protection.path_is_protected(source, protected_paths)
              or protection.path_is_protected(audit, protected_paths)):
            raise RetirementError("payload repair conflicts with another active consumer lease")


@contextmanager
def _payload_read_guard(path: Path):
    """Deny source writers while allowing the owner to rename its old object.

    CreateFileW GENERIC_READ and FILE_SHARE_READ|FILE_SHARE_DELETE permit only
    reads and renames. No writable handle, FlushFileBuffers or source flush is
    used. Existing incompatible readers/writers make opening or renaming fail.
    https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
    """
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW("\\\\?\\" + str(path), 0x80000000, 1 | 4, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "preserved payload cannot be protected against writers", str(path))
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def _payload_object_identity(path: Path) -> dict[str, int]:
    stat = path.stat()
    if path.is_symlink() or getattr(stat, "st_file_attributes", 0) & 1024 or not path.is_file():
        raise RetirementError("payload repair requires a regular non-reparse file")
    return dict(bytes=stat.st_size, device=stat.st_dev, file_id=stat.st_ino,
                mtime_ns=stat.st_mtime_ns, creation_ns=stat.st_ctime_ns)


def _payload_views(path: Path) -> dict[str, Any]:
    """Record both read paths; agreement is required explicitly by the caller."""
    result = dict(path=str(path), started_at_utc=datetime.now(timezone.utc).isoformat())
    result.update(buffered_sha256=file_sha256(path), unbuffered_sha256=file_sha256_unbuffered(path),
                  object=_payload_object_identity(path), completed_at_utc=datetime.now(timezone.utc).isoformat())
    return result


def repair_preserved_native_file(
    artifact_root: Path, run_dir: Path, relative_path: str, evidence_run: Path, *,
    owner: str, expected_manifest_sha256: str, expected_retirement_sha256: str,
    writing_stopped: bool = False, capacity_lease_id: str = "", apply: bool = False,
) -> dict[str, Any]:
    """Replace one stopped preserved PA object with verified identical bytes.

    This explicit Windows owner action keeps historical manifests unchanged.
    Two private /J snapshots must each agree under both read methods. The old
    object is retained in the audit run; a pending journal supports replay at
    every rename boundary. It neither deletes data nor repairs persistent damage.
    """
    from common.contracts.artifact_naming import validate_run_id
    from common.simion.cache_generation import snapshot_immutable_file
    root, run, audit = artifact_root.resolve(), run_dir.resolve(), evidence_run.resolve()
    for selected in (run, audit):
        parts = selected.relative_to(root).parts
        if len(parts) != 4 or parts[:3] != ("projects", owner, "runs"):
            raise RetirementError("payload repair requires canonical same-owner runs")
        validate_run_id(parts[3])
    if run == audit or os.name != "nt" or not writing_stopped:
        raise RetirementError("payload repair requires Windows, a separate audit run and stopped-writing confirmation")
    selected = _selected_heavy_paths([relative_path])[0]
    source = _under(run / selected, run)
    if source != run / selected or source.suffix.lower() != ".pa":
        raise RetirementError("payload view repair only accepts ordinary standalone .pa files")
    manifest_path, retirement_path = run / "run_manifest.json", run / RECEIPT_NAME
    expected_manifest_sha256 = expected_manifest_sha256.upper()
    expected_retirement_sha256 = expected_retirement_sha256.upper()
    with _payload_owner_lock(source):
        if (file_sha256(manifest_path) != expected_manifest_sha256
                or file_sha256(retirement_path) != expected_retirement_sha256):
            raise RetirementError("payload repair manifest or retirement receipt CAS differs")
        state = _load_run(run)
        receipt = _json(retirement_path)
        if (state["config"].get("project") != owner or receipt.get("target_run_id") != run.name
                or receipt.get("target_manifest", {}).get("sha256", "").upper() != expected_manifest_sha256
                or receipt.get("role") != "solver_review_retirement_receipt"
                or (receipt.get("retirement_mode") == "completed_experiment" and receipt.get("owner") != owner)
                or receipt.get("lifecycle_status") not in {"completed_experiment_payload_retired", "superseded_payload_retired"}):
            raise RetirementError("payload repair requires original successful owned retired-run evidence")
        _manifest_records(state, retired_paths={source, *(_under(run / v["path"], run) for v in receipt["removed_files"])},
                          inherit_heavy_identity=True)
        preserved = [v for v in receipt["preserved_files"] if v["path"] == selected]
        records = [v for v in state["manifest"]["outputs"] if record_path(v, base_dir=run) == source]
        if (len(preserved) != 1 or len(records) != 1
                or records[0].get("retention_role") != "solver_native_binary"
                or records[0]["bytes"] < _VIEW_REPAIR_MIN_BYTES
                or any(preserved[0][k] != records[0][k] for k in ("bytes", "sha256"))
                or any(v["path"] == selected for v in receipt["removed_files"])):
            raise RetirementError("payload is not uniquely preserved with its original native manifest identity")
        expected = dict(name=source.name, bytes=records[0]["bytes"], sha256=records[0]["sha256"].upper())
        audit_config = _json(audit / "run_config.json")
        if (audit_config.get("project") != owner or audit_config.get("run_id") != audit.name
                or audit_config.get("mode") != "owned_payload_view_repair"
                or validate_retention(audit_config.get("artifact_retention")).class_id != "solver_review"
                or audit_config.get("capacity_ledger_lifecycle", {}).get("enabled") is not True
                or Path(audit_config["capacity_ledger_lifecycle"]["artifact_root"]).resolve() != root):
            raise RetirementError("payload repair requires a governed solver-review audit run")
        plan = dict(schema_version=1, role="solver_review_preserved_payload_view_repair",
                    owner=owner, source_run=str(run), source_path=str(source), relative_path=selected,
                    expected=expected, manifest_sha256=expected_manifest_sha256,
                    retirement_sha256=expected_retirement_sha256, evidence_run=str(audit),
                    committed_new_bytes=3 * expected["bytes"], source_write_or_flush=False)
        if not apply:
            return {**plan, "status": "plan", "mutation_performed": False}
        if not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
            raise RetirementError("payload repair apply requires the shared HostExecutionLease")
        with protection.capacity_decision_lock(root):
            _assert_payload_repair_capacity(root, source, audit, owner, capacity_lease_id, plan["committed_new_bytes"])
        directory = audit / "results" / "payload_view_repair"
        journal_path = directory / "repair_journal.json"
        old = directory / "quarantine" / source.name
        snapshots = [directory / name / source.name for name in ("snapshot_1", "snapshot_2")]
        if journal_path.exists():
            journal = _json(journal_path)
            if journal.get("plan") != plan:
                raise RetirementError("payload repair journal identity differs")
        else:
            if directory.exists():
                raise RetirementError("payload repair audit directory already contains unknown evidence")
            directory.mkdir(parents=True)
            journal = dict(plan=plan, status="preparing", observations=[])
            _atomic_json(journal_path, journal)

        def verify_views(path: Path) -> dict[str, Any]:
            view = _payload_views(path)
            if (view["object"]["bytes"] != expected["bytes"]
                    or view["buffered_sha256"] != expected["sha256"]
                    or view["unbuffered_sha256"] != expected["sha256"]):
                journal["observations"].append(view)
                _atomic_json(journal_path, journal)
                raise RetirementError("payload repair independent read views do not both match the original manifest")
            return view

        if journal["status"] == "complete":
            with _payload_read_guard(source):
                verify_views(source)
            verify_views(snapshots[1])
            if not old.is_file() or _payload_object_identity(old) != journal["original_object"]:
                raise RetirementError("payload repair quarantine evidence is missing")
            return journal
        guard_path = old if old.exists() else source
        with _payload_read_guard(guard_path):
            snapshots_fresh = False
            if journal["status"] == "preparing":
                observed = _payload_views(source)
                journal["observations"].append(observed)
                _atomic_json(journal_path, journal)
                if (observed["object"]["bytes"] != expected["bytes"]
                        or observed["unbuffered_sha256"] != expected["sha256"]):
                    raise RetirementError("payload repair cannot recover persistent missing or changed bytes")
                verified_snapshots = []
                for snapshot in snapshots:
                    if not snapshot.exists():
                        snapshot_immutable_file(source, snapshot, expected)
                    verified_snapshots.append(verify_views(snapshot))
                if _payload_object_identity(source) != observed["object"]:
                    raise RetirementError("payload repair source object changed during snapshots")
                journal.update(status="snapshots_verified", original_object=observed["object"],
                               snapshots=verified_snapshots)
                _atomic_json(journal_path, journal)
                snapshots_fresh = True
            if journal["status"] == "snapshots_verified":
                if not snapshots_fresh:
                    for snapshot in snapshots:
                        verify_views(snapshot)
                # Only small authority CAS, lease metadata and one rename are
                # inside the capacity lock. All PA copying/hashing is outside.
                with protection.capacity_decision_lock(root):
                    _assert_payload_repair_capacity(root, source, audit, owner, capacity_lease_id, plan["committed_new_bytes"])
                    if (file_sha256(manifest_path) != expected_manifest_sha256
                            or file_sha256(retirement_path) != expected_retirement_sha256):
                        raise RetirementError("payload repair original records changed before quarantine")
                    if old.exists():
                        if source.exists() or _payload_object_identity(old) != journal["original_object"]:
                            raise RetirementError("payload repair quarantine rename replay differs")
                    else:
                        if _payload_object_identity(source) != journal["original_object"]:
                            raise RetirementError("payload repair source object CAS differs")
                        old.parent.mkdir(exist_ok=True)
                        os.replace(source, old)
                journal["status"] = "quarantined"
                _atomic_json(journal_path, journal)
            if journal["status"] == "quarantined":
                if _payload_object_identity(old) != journal["original_object"]:
                    raise RetirementError("payload repair old object identity changed")
                verify_views(snapshots[1])
                if source.exists():
                    if snapshots[0].exists():
                        raise RetirementError("payload repair source unexpectedly reappeared")
                    verify_views(source)
                else:
                    verify_views(snapshots[0])
                    with protection.capacity_decision_lock(root):
                        _assert_payload_repair_capacity(root, source, audit, owner, capacity_lease_id, plan["committed_new_bytes"])
                        if (file_sha256(manifest_path) != expected_manifest_sha256
                                or file_sha256(retirement_path) != expected_retirement_sha256):
                            raise RetirementError("payload repair original records changed before replacement")
                        os.replace(snapshots[0], source)
                journal["status"] = "replaced"
                _atomic_json(journal_path, journal)
            if journal["status"] != "replaced":
                raise RetirementError("payload repair journal state is unknown")
            with _payload_read_guard(source):
                journal["post_replacement"] = verify_views(source)
            if (file_sha256(manifest_path) != expected_manifest_sha256
                    or file_sha256(retirement_path) != expected_retirement_sha256):
                raise RetirementError("payload repair original records changed before completion")
            journal.update(status="complete", mutation_performed=True, quarantine_path=str(old),
                           retained_snapshot=str(snapshots[1]), completed_at_utc=datetime.now(timezone.utc).isoformat())
            _atomic_json(journal_path, journal)
        return journal


def verify_retirement(run_dir: Path) -> dict[str, Any]:
    receipt = _json(run_dir / RECEIPT_NAME)
    owner_mode = receipt.get("retirement_mode") == "completed_experiment"
    expected_status = "completed_experiment_payload_retired" if owner_mode else "superseded_payload_retired"
    if receipt.get("role") != "solver_review_retirement_receipt" or receipt.get("lifecycle_status") != expected_status:
        raise RetirementError("retirement receipt is not complete")
    if receipt.get("target_run_id") != run_dir.name:
        raise RetirementError("retirement target identity differs")
    for name in ("run_config.json", "summary.json", "run_manifest.json"):
        if not (run_dir / name).is_file():
            raise RetirementError(f"required historical record missing: {name}")
    if file_sha256(run_dir / "run_manifest.json") != receipt["target_manifest"]["sha256"]:
        raise RetirementError("original run manifest changed")
    # Receipts written before failed-target retirement existed can only have
    # described successful targets, so preserve their verification contract.
    target_status = receipt.get("target_terminal_status", "success")
    runtime_checkpoint_path = _runtime_scope_path(receipt, run_dir)
    runtime_mode = runtime_checkpoint_path is not None
    gui_mode = _prepared_gui_scope(receipt)
    selected = _selected_heavy_paths(receipt.get("selected_heavy_paths"))
    if selected is not None and (not owner_mode or runtime_mode or gui_mode):
        raise RetirementError("selected heavy scope requires ordinary owner completion")
    allowed_statuses = {"checkpoint"} if runtime_mode or gui_mode else (
        {"success", "failed", "interrupted"} if owner_mode else {"success", "failed"})
    if target_status not in allowed_statuses:
        raise RetirementError("retirement target terminal status is invalid")
    manifest_status = _json(run_dir / "run_manifest.json").get("status")
    summary = _json(run_dir / "summary.json")
    legacy_initialization_summary = receipt.get(
        "target_legacy_initialization_summary", False
    )
    if not isinstance(legacy_initialization_summary, bool):
        raise RetirementError("retirement target legacy summary flag is invalid")
    if manifest_status != target_status or (
        summary.get("status") != target_status
        and not (
            legacy_initialization_summary
            and target_status == "success"
            and summary == LEGACY_INITIALIZATION_SUMMARY
        )
        and not (gui_mode and summary.get("status") == "gui_replay_prepared")
    ):
        raise RetirementError("retirement target terminal status differs")
    if owner_mode:
        if (receipt.get("owner") != _json(run_dir / "run_config.json").get("project")
                or not str(receipt.get("owner_abandonment_reason", "")).strip()
                or any(receipt.get(key) for key in (
                    "replacement_run_path", "replacement_run_id", "replacement_manifest",
                    "compatibility_assertion", "compatibility_checks",
                ))):
            raise RetirementError("completed experiment owner decision is invalid")
    else:
        replacement = Path(receipt["replacement_run_path"])
        replacement_state = _load_run(replacement, label="replacement",
            allowed_statuses=("checkpoint",) if gui_mode else ("success",), prepared_gui_checkpoint=gui_mode)
        replacement_records = _manifest_records(replacement_state)
        if gui_mode:
            _prepared_gui_inventory(replacement_state, replacement_records)
        if file_sha256(replacement / "run_manifest.json") != receipt["replacement_manifest"]["sha256"]:
            raise RetirementError("replacement run manifest changed")
    _verify_stopped_consumers(receipt, run_dir)
    if gui_mode:
        state = _load_run(run_dir, allowed_statuses=("checkpoint",), prepared_gui_checkpoint=True)
        records = _manifest_records(state,
            retired_paths={_under(run_dir / item["path"], run_dir) for item in receipt["removed_files"]},
            inherit_heavy_identity=True)
        _prepared_gui_inventory(state, records)
    if runtime_mode:
        state = _load_run(run_dir, allowed_statuses=("checkpoint",), stopped_checkpoint_runtime=True)
        retired_paths = {_under(run_dir / item["path"], run_dir) for item in receipt["removed_files"]}
        records = _manifest_records(state, retired_paths=retired_paths, inherit_heavy_identity=True)
        members = _runtime_checkpoint_members(state, runtime_checkpoint_path, records, retired_paths)
        if retired_paths != set(members) or any(
            item.get("bytes") != members[_under(run_dir / item["path"], run_dir)]["bytes"]
            or str(item.get("sha256", "")).upper()
            != members[_under(run_dir / item["path"], run_dir)]["sha256"].upper()
            for item in receipt["removed_files"]
        ):
            raise RetirementError("retired runtime scope differs from its sealed checkpoint inventory")
    if selected is not None:
        _selected_heavy_records(receipt["removed_files"], selected)
        if sorted(item["path"] for item in receipt["removed_files"]) != selected:
            raise RetirementError("retired payload differs from selected heavy scope")
        state = _load_run(run_dir, allowed_statuses=allowed_statuses)
        retired_paths = {_under(run_dir / path, run_dir) for path in selected}
        records = _manifest_records(state, retired_paths=retired_paths, inherit_heavy_identity=True)
        for item in receipt["removed_files"]:
            record = records.get(_under(run_dir / item["path"], run_dir))
            if not record or item["bytes"] != record["bytes"] or item["sha256"].upper() != record["sha256"].upper():
                raise RetirementError("selected retired payload differs from sealed manifest")
    for item in receipt["removed_files"]:
        if (run_dir / item["path"]).exists():
            raise RetirementError(f"retired heavy payload reappeared: {item['path']}")
    for item in receipt["preserved_files"]:
        path = run_dir / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or file_sha256(path) != item["sha256"]:
            raise RetirementError(f"preserved evidence identity differs: {item['path']}")
    return {
        "schema_version": 1,
        "role": "solver_review_retirement_verification",
        "status": "PASS",
        "run_id": run_dir.name,
        "target_terminal_status": target_status,
        "replacement_run_id": receipt["replacement_run_id"],
        "removed_bytes": receipt["removed_bytes"],
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--target-run", type=Path)
    parser.add_argument("--replacement-run", type=Path)
    parser.add_argument("--compatibility-assertion")
    parser.add_argument("--owner", default="")
    parser.add_argument("--owner-abandonment-reason", default="")
    parser.add_argument("--runtime-checkpoint", type=Path)
    parser.add_argument("--prepared-gui-checkpoint", action="store_true")
    parser.add_argument("--selected-heavy-path", action="append", default=None)
    parser.add_argument("--confirm-writing-stopped", action="store_true")
    parser.add_argument("--approved-stopped-consumer", action="append", type=Path, default=[])
    parser.add_argument("--compatibility-input-role", action="append", default=[])
    parser.add_argument(
        "--compatibility-input-role-map", action="append", default=[],
        metavar="TARGET_ROLE=REPLACEMENT_ROLE",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--repair-preserved-file")
    parser.add_argument("--repair-evidence-run", type=Path)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--expected-retirement-sha256")
    parser.add_argument("--capacity-lease-id", default="")
    args = parser.parse_args(argv)
    try:
        if args.repair_preserved_file:
            if (not all((args.artifact_root, args.target_run, args.owner, args.repair_evidence_run,
                         args.expected_manifest_sha256, args.expected_retirement_sha256))
                    or args.verify or args.replacement_run or args.compatibility_assertion
                    or args.owner_abandonment_reason or args.runtime_checkpoint or args.prepared_gui_checkpoint
                    or args.selected_heavy_path or args.approved_stopped_consumer
                    or args.compatibility_input_role or args.compatibility_input_role_map):
                parser.error("preserved payload repair requires its explicit identities and no retirement/verify action")
            result = repair_preserved_native_file(args.artifact_root, args.target_run, args.repair_preserved_file,
                args.repair_evidence_run, owner=args.owner, expected_manifest_sha256=args.expected_manifest_sha256,
                expected_retirement_sha256=args.expected_retirement_sha256,
                writing_stopped=args.confirm_writing_stopped, capacity_lease_id=args.capacity_lease_id, apply=args.apply)
        elif args.repair_evidence_run or args.expected_manifest_sha256 or args.expected_retirement_sha256 or args.capacity_lease_id:
            parser.error("repair options require --repair-preserved-file")
        elif args.verify:
            result = verify_retirement(args.verify.resolve())
        else:
            if not all((args.artifact_root, args.repository_root, args.target_run)):
                parser.error("plan/apply requires artifact root, repository root, and target")
            compatibility_roles: list[str] = []
            mapping_values = list(args.compatibility_input_role_map)
            for value in args.compatibility_input_role:
                # The PowerShell lease-owning wrapper predates the dedicated
                # map switch and forwards this repeatable option.  Accept the
                # same explicit TARGET=REPLACEMENT syntax here so mapped-only
                # retirements still use that governed apply entrypoint.
                if "=" in value:
                    mapping_values.append(value)
                else:
                    compatibility_roles.append(value)
            mappings: list[tuple[str, str]] = []
            for value in mapping_values:
                if "=" not in value:
                    raise RetirementError(
                        "compatibility input role mapping must use TARGET_ROLE=REPLACEMENT_ROLE"
                    )
                target_role, replacement_role = value.split("=", 1)
                if not target_role.strip() or not replacement_role.strip():
                    raise RetirementError(
                        "compatibility input role mapping must name both roles"
                    )
                mappings.append((target_role, replacement_role))
            result = plan_retirement(
                args.artifact_root, args.repository_root, args.target_run,
                args.replacement_run, args.compatibility_assertion or "",
                compatibility_roles,
                mappings,
                owner=args.owner, owner_abandonment_reason=args.owner_abandonment_reason,
                runtime_checkpoint_path=args.runtime_checkpoint, writing_stopped=args.confirm_writing_stopped,
                approved_stopped_consumers=args.approved_stopped_consumer,
                prepared_gui_checkpoint=args.prepared_gui_checkpoint,
                selected_heavy_paths=args.selected_heavy_path,
            )
            if args.apply:
                result = apply_retirement(result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except RetirementError as exc:
        print(json.dumps({"role": "solver_review_retirement_error", "status": "FAIL", "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
