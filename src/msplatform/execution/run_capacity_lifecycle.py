"""Normal run capacity transitions; historical retirement policy stays with its owner."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from msplatform.execution import capacity_ledger, capacity_protection
from msplatform.execution.manifest_records import file_record, verify_record
from msplatform.execution.recorded_file_removal import write_json_atomic

TERMINAL_STATUSES = {"success", "failed", "interrupted"}
HEAVY_RETENTION_ROLES = {"solver_native_binary", "dense_trajectory", "large_optional"}
WRITING_REVIEW_DAYS = 7
READY_REVIEW_DAYS = 30
SEALED_CHECKPOINT_REASON = "owner sealed checkpoint; continuation requires a new run"
SEALED_PAYLOAD_REASON_PREFIX = "owner sealed stopped payload; "


def _run_lifecycle_duties(run_dir: Path, *, review_days: int, reason: str) -> dict[str, str]:
    """Assign the run owner a finite review and owner-managed retirement route."""

    return {
        "owner": run_dir.parent.parent.name,
        "retention_reason": reason,
        "review_deadline": (
            datetime.now(timezone.utc).date() + timedelta(days=review_days)
        ).isoformat(),
        "retirement_route": "owner_managed_disposition",
    }


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is missing or invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be one JSON object: {path}")
    return value


def _run_context(artifact_root: Path, run_config: Path) -> tuple[Path, dict[str, Any], int]:
    root = artifact_root.resolve(strict=True)
    config_path = run_config.resolve(strict=True)
    run_dir = config_path.parent
    if config_path.name != "run_config.json" or run_dir.parent.name != "runs":
        raise ValueError("capacity-ledger run_config must be a direct runs/<run-id>/run_config.json")
    capacity_ledger.capacity_object_path(root, run_dir)
    config = _load_json(config_path, "run config")
    lifecycle = config.get("capacity_ledger_lifecycle")
    if not isinstance(lifecycle, dict) or lifecycle.get("schema_version") != 1 or lifecycle.get("enabled") is not True:
        raise ValueError("run config has not opted into capacity-ledger lifecycle")
    try:
        declared_root = Path(str(lifecycle.get("artifact_root", ""))).resolve(strict=True)
    except OSError as exc:
        raise ValueError("run capacity-ledger artifact_root is invalid") from exc
    if declared_root != root:
        raise ValueError("run capacity-ledger artifact_root differs from the invoked root")
    budget = lifecycle.get("light_evidence_budget_bytes")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise ValueError("run light-evidence budget must be a positive integer")
    return run_dir, config, budget


def _inventory(run_dir: Path) -> tuple[int, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    for path in run_dir.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"run capacity inventory refuses a symlink: {path}")
        if not path.is_file():
            continue
        size = path.stat().st_size
        records.append({"path": path.relative_to(run_dir).as_posix(), "bytes": size})
    records.sort(key=lambda item: (-int(item["bytes"]), str(item["path"])))
    return sum(int(item["bytes"]) for item in records), records


def register_writing_range(artifact_root: Path, run_directory: Path) -> dict[str, Any]:
    """Register an empty run range before its first managed file is written."""

    root = artifact_root.resolve(strict=True)
    try:
        run_dir = run_directory.resolve(strict=True)
    except OSError as exc:
        raise ValueError("pre-write run range is missing") from exc
    if run_dir.is_symlink() or not run_dir.is_dir() or run_dir.parent.name != "runs":
        raise ValueError("pre-write run range must be a direct runs/<run-id> directory")
    capacity_ledger.capacity_object_path(root, run_dir)
    total, records = _inventory(run_dir)
    if records:
        raise ValueError("pre-write run range must not contain files")
    entry = capacity_ledger.record_capacity_object(
        root, path=run_dir, object_class="rebuildable_payload", bytes_count=total,
        status="writing",
        **_run_lifecycle_duties(
            run_dir, review_days=WRITING_REVIEW_DAYS,
            reason="registered run range awaiting initialization",
        ),
        recovery_reason="run_package_initialization_incomplete",
        recovery_task="run owner must initialize or retire the registered range",
    )
    return {
        "schema_version": 1,
        "role": "run_capacity_lifecycle_receipt",
        "action": "register_writing_range",
        "status": "writing",
        "run_directory": str(run_dir),
        "bytes": total,
        "file_count": 0,
        "ledger_entry": entry,
    }


def register_writing(artifact_root: Path, run_config: Path) -> dict[str, Any]:
    run_dir, _, budget = _run_context(artifact_root, run_config)
    ledger = capacity_ledger.load_capacity_ledger(artifact_root)
    relative = run_dir.relative_to(artifact_root.resolve()).as_posix()
    if ledger and any(
        item["path"] == relative and (
            item.get("retention_reason") == SEALED_CHECKPOINT_REASON
            or str(item.get("retention_reason", "")).startswith(SEALED_PAYLOAD_REASON_PREFIX)
        )
        for item in ledger["objects"]
    ):
        raise ValueError("sealed run is read-only; continuation requires a new run")
    total, records = _inventory(run_dir)
    entry = capacity_ledger.record_capacity_object(
        artifact_root,
        path=run_dir,
        object_class="rebuildable_payload",
        bytes_count=total,
        status="writing",
        **_run_lifecycle_duties(
            run_dir, review_days=WRITING_REVIEW_DAYS,
            reason="active run awaiting terminal retention",
        ),
        recovery_reason="run_manifest_not_terminal",
        recovery_task="run owner must complete terminal retention or explicit recovery",
        recovery_evidence_paths=[run_dir / "run_config.json"],
    )
    return {
        "schema_version": 1,
        "role": "run_capacity_lifecycle_receipt",
        "action": "register_writing",
        "status": "writing",
        "run_directory": str(run_dir),
        "bytes": total,
        "file_count": len(records),
        "light_evidence_budget_bytes": budget,
        "ledger_entry": entry,
    }


def assert_retention_complete(artifact_root: Path, run_config: Path, *,
                              retirement_receipt_name: str | None = None,
                              retirement_receipt_validator: Callable[[Path], Path] | None = None) -> dict[str, Any]:
    run_dir, config, budget = _run_context(artifact_root, run_config)
    receipt_path = run_dir / "retention_actions.json"
    retention = config.get("artifact_retention")
    if not receipt_path.exists() and not receipt_path.is_symlink() and (retirement_receipt_name is not None and (run_dir / retirement_receipt_name).exists()):
        if not isinstance(retention, dict) or retention.get("class") != "solver_review":
            raise ValueError("retirement receipt requires the frozen solver_review contract")
        if retirement_receipt_validator is None:
            raise ValueError("retirement receipt requires its explicit owner validator")
        receipt_path = retirement_receipt_validator(run_dir)
    else:
        receipt = _load_json(receipt_path, "retention receipt")
        if receipt.get("role") != "artifact_retention_actions" or receipt.get("status") != "complete":
            raise ValueError("terminal capacity-ledger transition requires completed retention first")
        if not isinstance(retention, dict) or receipt.get("retention_class") != retention.get("class"):
            raise ValueError("retention receipt class differs from the frozen run contract")
    return {
        "schema_version": 1,
        "role": "run_capacity_lifecycle_receipt",
        "action": "assert_retention_complete",
        "status": "ready_for_terminal_manifest",
        "run_directory": str(run_dir),
        "retention_receipt": str(receipt_path),
        "light_evidence_budget_bytes": budget,
    }


def finalize_ready(artifact_root: Path, run_config: Path, *,
                   classify_file: Callable[..., str],
                   retention_complete: Callable[[Path, Path], dict[str, Any]] = assert_retention_complete) -> dict[str, Any]:
    run_dir, _, budget = _run_context(artifact_root, run_config)
    retention_complete(artifact_root, run_config)
    manifest = _load_json(run_dir / "run_manifest.json", "run manifest")
    if manifest.get("status") not in TERMINAL_STATUSES:
        raise ValueError("run manifest is not success, failed, or interrupted")
    total, records = _inventory(run_dir)
    forbidden = []
    for record in records:
        role = classify_file(
            run_dir / record["path"], bytes_count=int(record["bytes"]),
        )
        if role in HEAVY_RETENTION_ROLES:
            forbidden.append({**record, "retention_role": role})
    if total > budget or forbidden:
        largest = json.dumps(records[:10], ensure_ascii=False, separators=(",", ":"))
        forbidden_json = json.dumps(
            forbidden, ensure_ascii=False, separators=(",", ":"),
        )
        raise ValueError(
            "terminal run cannot become light_evidence; keep it writing and move "
            "heavy payloads to governed storage first; "
            f"forbidden_files={forbidden_json}; largest_files={largest}"
        )
    entry = capacity_ledger.record_capacity_object(
        artifact_root,
        path=run_dir,
        object_class="light_evidence",
        bytes_count=total,
        status="ready",
        **_run_lifecycle_duties(
            run_dir, review_days=READY_REVIEW_DAYS,
            reason="terminal compact run retained as light evidence",
        ),
    )
    return {
        "schema_version": 1,
        "role": "run_capacity_lifecycle_receipt",
        "action": "finalize_ready",
        "status": "ready",
        "terminal_status": manifest["status"],
        "run_directory": str(run_dir),
        "bytes": total,
        "file_count": len(records),
        "light_evidence_budget_bytes": budget,
        "light_evidence_budget_exceeded": False,
        "largest_files": [],
        "ledger_entry": entry,
    }


def _retirement_call(callback: Callable[..., Any] | None, name: str, *args: Any) -> Any:
    if callback is None:
        raise ValueError(f"retired payload requires its explicit owner {name} callback")
    return callback(*args)


def seal_checkpoint(
    artifact_root: Path, run_config: Path, *, owner: str,
    classify_file: Callable[..., str],
    retirement_receipt_name: str | None = None,
    verify_retirement: Callable[..., Any] | None = None,
    assert_retirement_unprotected: Callable[..., Any] | None = None,
    verify_retired_payload_remainder: Callable[..., Any] | None = None,
    retention_complete: Callable[..., Any] = assert_retention_complete,
    writing_stopped: bool = False,
    retain_payload: bool = False, retention_reason: str | None = None,
) -> dict[str, Any]:
    """Retain a stopped, light checkpoint without changing its scientific state.

    The owner must establish that its writer and children have exited. Leases
    do not distinguish readers from writers, so any overlap postpones sealing.
    No run file is written or removed; continuation must use a new run identity.
    The explicit payload action retains heavy files pinned, preserves the original
    manifest status, and requires a named owner retention decision.
    """
    root = artifact_root.resolve(strict=True)
    run_dir, config, budget = _run_context(root, run_config)
    if not writing_stopped or owner != run_dir.parent.parent.name:
        raise ValueError("checkpoint sealing requires its owner and confirmed stopped writing")
    if retain_payload:
        if not isinstance(retention_reason, str) or not retention_reason.strip():
            raise ValueError("stopped payload sealing requires an explicit owner retention reason")
        reason = SEALED_PAYLOAD_REASON_PREFIX + retention_reason.strip()
    else:
        if retention_reason is not None:
            raise ValueError("payload retention reason is not valid for light checkpoint sealing")
        reason = SEALED_CHECKPOINT_REASON
    retirement_receipt_path = None
    if retirement_receipt_name is not None:
        retirement_receipt_path = run_dir / retirement_receipt_name
        if retirement_receipt_path.parent != run_dir or not retirement_receipt_name:
            raise ValueError("retirement receipt must be one explicit run-local name")
    relative = run_dir.relative_to(root).as_posix()
    accounting_reconciliation = None
    with capacity_protection.capacity_decision_lock(root):
        ledger = capacity_ledger.load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("checkpoint sealing requires a valid capacity ledger")
        entry = next((item for item in ledger["objects"] if item["path"] == relative), None)
        if entry is None or entry.get("owner") != owner or "disposition" in entry:
            raise ValueError("checkpoint sealing requires its exact registered owner range")
        if retain_payload and entry.get("class") != "rebuildable_payload":
            raise ValueError("stopped payload must already belong to its rebuildable run owner")
        if entry.get("consumers"):
            raise ValueError("checkpoint consumers require owner handoff before sealing")
        retired_runtime = False
        if (not retain_payload and entry["status"] == "ready"
                and entry.get("class") == "rebuildable_payload"
                and str(entry.get("retention_reason", "")).startswith(SEALED_PAYLOAD_REASON_PREFIX)
                and retirement_receipt_path is not None and retirement_receipt_path.is_file()):
            if (run_dir / "retention_actions.json").exists():
                retention_complete(root, run_config)
            verified = _retirement_call(verify_retirement, "verify_retirement", run_dir)
            receipt = _load_json(retirement_receipt_path, "runtime retirement receipt")
            if (verified["target_terminal_status"] != "checkpoint"
                    or not isinstance(receipt.get("stopped_checkpoint_runtime"), dict)):
                raise ValueError("checkpoint closure requires its verified stopped runtime retirement")
            _retirement_call(assert_retirement_unprotected, "assert_retirement_unprotected", root, run_dir)
            retired_runtime = True
        if entry["status"] != "writing" and not retired_runtime and not (
            entry["status"] == "ready" and entry.get("retention_reason") == reason
        ):
            raise ValueError("checkpoint range is not writing or already sealed")
        leases = capacity_protection._load_capacity_protection_leases_unlocked(root)
        if capacity_protection.path_is_protected(run_dir, leases["protected_paths"]):
            raise ValueError("checkpoint has an active protection lease; defer sealing")
        manifest = _load_json(run_dir / "run_manifest.json", "run manifest")
        if retain_payload and (
            manifest.get("status") not in TERMINAL_STATUSES | {"checkpoint"}
            or manifest.get("run_id") != run_dir.name or manifest.get("project") != owner
            or config.get("run_id") != run_dir.name or config.get("project") != owner
        ):
            raise ValueError("stopped payload requires exact run/project identity and a stopped manifest state")
        if not retain_payload and manifest.get("status") != "checkpoint":
            raise ValueError("checkpoint sealing requires a checkpoint manifest")
        stopped_run_config = file_record(run_dir / "run_config.json", retention_classifier=classify_file) if retain_payload else None
        total, records = _inventory(run_dir)
        if retain_payload and entry["status"] == "ready":
            size_changed = total != int(entry["bytes"])
            if (retirement_receipt_path is None or not retirement_receipt_path.is_file()) and size_changed:
                raise ValueError("sealed stopped payload resident bytes changed; owner must investigate")
            if retirement_receipt_path is not None and retirement_receipt_path.is_file():
                reconciliation = _retirement_call(verify_retired_payload_remainder, "verify_retired_payload_remainder", run_dir, config, owner, entry, records)
                if size_changed:
                    accounting_reconciliation = reconciliation
        if not retain_payload and (total > budget or any(
            classify_file(run_dir / item["path"], bytes_count=item["bytes"]) in HEAVY_RETENTION_ROLES
            for item in records
        )):
            raise ValueError("checkpoint is not light evidence; preserve it for its payload owner")
        preserve_payload_duties = retain_payload and entry["status"] == "ready"
        ledger["resident_bytes"] += total - int(entry["bytes"])
        entry.update(
            {"class": "rebuildable_payload" if retain_payload else "light_evidence", "bytes": total, "status": "ready"},
        )
        if not preserve_payload_duties:
            entry.update(_run_lifecycle_duties(
                run_dir, review_days=READY_REVIEW_DAYS, reason=reason,
            ))
        if retain_payload:
            entry.update(pin=True, pin_reason=entry.get("pin_reason", retention_reason.strip()))
        elif retired_runtime:
            entry.update(pin=False)
            entry.pop("pin_reason", None)
        for field in ("recovery_reason", "recovery_task", "recovery_evidence_paths", "consumers"):
            entry.pop(field, None)
        if not capacity_ledger._is_valid_capacity_ledger(root, ledger):
            raise ValueError("checkpoint sealing would invalidate ledger")
        write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
    return {
        "schema_version": 1, "role": "run_capacity_lifecycle_receipt",
        "action": "seal_stopped_payload" if retain_payload else "seal_checkpoint",
        "status": "ready", "run_status": manifest["status"],
        "run_directory": str(run_dir), "bytes": total, "file_count": len(records),
        "continuation": "new_run_required", "ledger_entry": entry,
        **({"run_config": stopped_run_config} if retain_payload else {}),
        **({"accounting_reconciliation": accounting_reconciliation} if accounting_reconciliation is not None else {}),
    }


def resolve_consumed_run_capacity_owner(manifest_record: dict[str, Any], *,
                                       consumer_artifact_root: Path | None = None,
                                       stopped_receipt_record: dict[str, Any] | None = None) -> dict[str, str]:
    """Resolve an explicitly bound source owner without inspecting its payload.

    The caller holds the existing shared terminal-consumption guard until its
    source protection lease has been acquired. Scientific applicability and PA
    byte protection remain the consuming project's responsibility.
    """
    from msplatform.execution.manifest_records import record_path
    from msplatform.execution.terminal_publication import require_completed_terminal_publication

    manifest_path = record_path(manifest_record)
    if manifest_path.name != "run_manifest.json":
        raise ValueError("source protection requires an explicit run manifest record")
    require_completed_terminal_publication(manifest_path)
    verify_record("source protection manifest", manifest_record)
    manifest = _load_json(manifest_path, "source manifest")
    if (manifest.get("schema_version") not in (1, 2) or manifest.get("role") != "simulation_run_manifest"
            or manifest.get("status") not in TERMINAL_STATUSES | {"superseded", "checkpoint"}
            or manifest.get("lifecycle_state") == "provisional"):
        raise ValueError("source protection requires a completed terminal run")
    stopped = None
    config_record = manifest.get("run_config")
    if manifest["status"] == "checkpoint":
        if stopped_receipt_record is None:
            raise ValueError("checkpoint source requires its explicit stopped payload receipt")
        verify_record("source stopped payload receipt", stopped_receipt_record)
        stopped = _load_json(record_path(stopped_receipt_record), "source stopped payload receipt")
        if (stopped.get("schema_version") != 1 or stopped.get("role") != "run_capacity_lifecycle_receipt"
                or stopped.get("action") != "seal_stopped_payload" or stopped.get("status") != "ready"
                or stopped.get("run_status") != "checkpoint"
                or Path(stopped.get("run_directory", "")).resolve() != manifest_path.parent
                or stopped.get("continuation") != "new_run_required"):
            raise ValueError("checkpoint source stopped payload receipt differs")
        config_record = stopped.get("run_config")
    if not isinstance(config_record, dict):
        raise ValueError("source manifest must bind its run config")
    config_path = record_path(config_record, base_dir=manifest_path.parent)
    if config_path != manifest_path.parent / "run_config.json":
        raise ValueError("source manifest run config is outside its owning run")
    verify_record("source protection run config", config_record, base_dir=manifest_path.parent)
    config = _load_json(config_path, "source run config")
    lifecycle = config.get("capacity_ledger_lifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("artifact_root"):
        run_dir, config, _ = _run_context(Path(lifecycle["artifact_root"]), config_path)
        root = Path(lifecycle["artifact_root"]).resolve(strict=True)
    else:
        # Legacy consumption within the one already-known root does not need
        # a fabricated historical owner. Never infer a different source root.
        if consumer_artifact_root is None:
            raise ValueError("source has no frozen capacity owner; provide sufficient source evidence")
        root = consumer_artifact_root.resolve(strict=True)
        run_dir = config_path.parent
        expected = root / "projects" / str(config.get("project", "")) / "runs" / str(config.get("run_id", ""))
        if run_dir != expected.resolve() or run_dir.parent.name != "runs":
            raise ValueError("cross-root source has no frozen capacity owner; provide sufficient source evidence")
        capacity_ledger.capacity_object_path(root, run_dir)
    for name in ("run_id", "project", "mode"):
        if not isinstance(config.get(name), str) or manifest.get(name) != config[name]:
            raise ValueError(f"source manifest and run config {name} differ")
    if config["run_id"] != run_dir.name:
        raise ValueError("source run identity differs from its owning directory")
    if "paths" in config and Path(config["paths"]["artifact_root"]).resolve(strict=True) != root:
        raise ValueError("source frozen path context and capacity owner differ")
    if stopped is not None:
        # This source-only check consumes the existing owner's stopped receipt;
        # it neither seals a checkpoint nor re-inventories its native payload.
        ledger = capacity_ledger.load_capacity_ledger(root)
        relative = run_dir.relative_to(root).as_posix()
        entries = [] if ledger is None else [item for item in ledger["objects"] if item.get("path") == relative]
        if (len(entries) != 1 or entries[0] != stopped.get("ledger_entry")
                or entries[0].get("status") != "ready" or entries[0].get("class") != "rebuildable_payload"
                or entries[0].get("pin") is not True
                or not str(entries[0].get("retention_reason", "")).startswith(SEALED_PAYLOAD_REASON_PREFIX)):
            raise ValueError("checkpoint source lacks its actual ready pinned owner range")
    return {"artifact_root": str(root), "run_directory": str(run_dir)}
