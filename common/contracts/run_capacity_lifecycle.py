"""Incrementally register opted-in run directories in the capacity ledger.

This adapter is deliberately small: it neither discovers historical runs nor
deletes files.  The PowerShell run lifecycle calls it after package creation
and after retention has completed for a terminal run.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common.contracts import capacity_ledger
from common.contracts import capacity_protection
from common.contracts.artifact_retention import classify_file
from common.contracts.recorded_file_removal import write_json_atomic


TERMINAL_STATUSES = {"success", "failed", "interrupted"}
HEAVY_RETENTION_ROLES = {
    "solver_native_binary", "dense_trajectory", "large_optional",
}
WRITING_REVIEW_DAYS = 7
READY_REVIEW_DAYS = 30
LEGACY_LIGHT_EVIDENCE_BUDGET_BYTES = 26_214_400


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


def register_writing(artifact_root: Path, run_config: Path) -> dict[str, Any]:
    run_dir, _, budget = _run_context(artifact_root, run_config)
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


def assert_retention_complete(artifact_root: Path, run_config: Path) -> dict[str, Any]:
    run_dir, config, budget = _run_context(artifact_root, run_config)
    receipt_path = run_dir / "retention_actions.json"
    receipt = _load_json(receipt_path, "retention receipt")
    if receipt.get("role") != "artifact_retention_actions" or receipt.get("status") != "complete":
        raise ValueError("terminal capacity-ledger transition requires completed retention first")
    retention = config.get("artifact_retention")
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


def finalize_ready(artifact_root: Path, run_config: Path) -> dict[str, Any]:
    run_dir, _, budget = _run_context(artifact_root, run_config)
    assert_retention_complete(artifact_root, run_config)
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


def _legacy_terminal_run_entries(
    root: Path, ledger: dict[str, Any], run_dir: Path,
) -> tuple[list[dict[str, Any]], str] | None:
    """Return one safely consolidatable historical compact run, if any.

    Old manifests already seal terminal outputs and retention decisions, but
    predate the lifecycle opt-in field.  This bridge accepts only a complete
    file-for-file ledger representation of a compact terminal run.  It uses
    sizes and retention roles, never re-hashes payloads and never deletes.
    """

    try:
        manifest = _load_json(run_dir / "run_manifest.json", "run manifest")
    except ValueError:
        return None
    try:
        config = _load_json(run_dir / "run_config.json", "run config")
    except ValueError:
        config = {}
    try:
        retention = _load_json(run_dir / "retention_actions.json", "retention receipt")
    except ValueError:
        retention = {}
    retention_class = config.get("artifact_retention", {}).get("class")
    if retention_class is None:
        # Older run configs predate the retention contract, while their v2
        # terminal manifests still freeze the chosen class.  Consume that
        # sealed record instead of asking the user to reconstruct it.
        retention_class = manifest.get("artifact_retention", {}).get("class")
    if manifest.get("status") not in TERMINAL_STATUSES:
        return None
    sealed_compact = (
        retention_class == "compact"
        and retention.get("role") == "artifact_retention_actions"
        and retention.get("status") == "complete"
        and retention.get("retention_class") == "compact"
    )
    # A historical terminal manifest may predate both retention documents.
    # It can become ready *only* when the entire range is already light
    # evidence; this is a ledger reconciliation, never an authorization to
    # discard payloads or to terminalize a checkpoint.
    terminal_light_only = retention_class is None and not retention
    if not sealed_compact and not terminal_light_only:
        return None
    _, records = _inventory(run_dir)
    if sum(int(record["bytes"]) for record in records) > LEGACY_LIGHT_EVIDENCE_BUDGET_BYTES:
        return None
    if any(
        classify_file(run_dir / record["path"], bytes_count=int(record["bytes"]))
        in HEAVY_RETENTION_ROLES
        for record in records
    ):
        return None
    prefix = capacity_ledger.capacity_object_path(root, run_dir)[1] + "/"
    entries = [
        item for item in ledger["objects"]
        if item.get("path", "").startswith(prefix) and item.get("status") != "retired"
    ]
    expected = {
        prefix + record["path"]: int(record["bytes"])
        for record in records
    }
    actual = {str(item["path"]): int(item["bytes"]) for item in entries}
    if actual != expected or any(
        item.get("class") != "light_evidence"
        or item.get("status") != "writing"
        or item.get("recovery_reason") != "run_contract_missing_or_invalid"
        or item.get("owner") != run_dir.parent.parent.name
        or item.get("consumers")
        for item in entries
    ):
        return None
    reason = (
        "legacy terminal compact run reconciled from sealed manifest and retention receipt"
        if sealed_compact else
        "legacy terminal light-evidence run reconciled from terminal manifest"
    )
    return entries, reason


def _consolidate_legacy_terminal_runs(root: Path) -> dict[str, int]:
    """Atomically replace legacy per-file light evidence with its run range."""

    migrated = migrated_bytes = 0
    with capacity_protection.capacity_decision_lock(root):
        ledger = capacity_ledger.load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("run lifecycle maintenance requires a valid capacity ledger")
        run_dirs = sorted({
            root / Path(*Path(item["path"]).parts[:4])
            for item in ledger["objects"]
            if item.get("status") == "writing"
            and item.get("recovery_reason") == "run_contract_missing_or_invalid"
            and len(Path(item["path"]).parts) >= 5
            and Path(item["path"]).parts[:3] == ("projects", Path(item["path"]).parts[1], "runs")
        })
        replacements: list[tuple[Path, list[dict[str, Any]], dict[str, Any]]] = []
        for run_dir in run_dirs:
            candidate = _legacy_terminal_run_entries(root, ledger, run_dir)
            if candidate is None:
                continue
            entries, reason = candidate
            total = sum(int(item["bytes"]) for item in entries)
            replacements.append((run_dir, entries, {
                "path": capacity_ledger.capacity_object_path(root, run_dir)[1],
                "class": "light_evidence", "bytes": total, "status": "ready", "pin": False,
                **_run_lifecycle_duties(
                    run_dir, review_days=READY_REVIEW_DAYS,
                    reason=reason,
                ),
            }))
        if not replacements:
            return {"migrated_count": 0, "migrated_bytes": 0}
        retired_paths = {entry["path"] for _, entries, _ in replacements for entry in entries}
        ledger["objects"] = [
            entry for entry in ledger["objects"] if entry.get("path") not in retired_paths
        ] + [replacement for _, _, replacement in replacements]
        if not capacity_ledger._is_valid_capacity_ledger(root, ledger):
            raise ValueError("legacy terminal run consolidation would invalidate ledger")
        write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
        migrated = len(replacements)
        migrated_bytes = sum(replacement["bytes"] for _, _, replacement in replacements)
    return {"migrated_count": migrated, "migrated_bytes": migrated_bytes}


def resume_terminal_runs(artifact_root: Path) -> dict[str, int]:
    """Close already-terminal opted-in runs without resuming a computation.

    Maintenance is allowed to make only the ledger transition that the run has
    already earned: a terminal manifest plus a completed retention receipt.
    Checkpoints, incomplete retention, legacy runs, and runs with consumers
    remain writing and are counted as blocked.  This keeps recovery decisions
    with the original workflow while making an interrupted ledger handoff
    idempotently recoverable through the existing run owner.
    """

    root = Path(artifact_root).resolve(strict=False)
    ledger = capacity_ledger.load_capacity_ledger(root)
    if ledger is None:
        raise ValueError("run lifecycle maintenance requires a valid capacity ledger")
    checked = finalized = blocked = 0
    for entry in ledger["objects"]:
        if not (
            entry.get("class") == "rebuildable_payload"
            and entry.get("status") == "writing"
            and entry.get("recovery_reason") == "run_manifest_not_terminal"
        ):
            continue
        run_dir = root / entry["path"]
        if run_dir.parent.name != "runs" or entry.get("consumers"):
            blocked += 1
            continue
        if entry.get("owner") != run_dir.parent.parent.name:
            blocked += 1
            continue
        checked += 1
        try:
            manifest = _load_json(run_dir / "run_manifest.json", "run manifest")
            if manifest.get("status") not in TERMINAL_STATUSES:
                blocked += 1
                continue
            finalize_ready(root, run_dir / "run_config.json")
        except (OSError, ValueError):
            blocked += 1
        else:
            finalized += 1
    legacy = _consolidate_legacy_terminal_runs(root)
    return {
        "checked_count": checked, "finalized_count": finalized, "blocked_count": blocked,
        **legacy,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("register-writing", "assert-retention", "finalize-ready"), required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-config", type=Path, required=True)
    args = parser.parse_args()
    action = {
        "register-writing": register_writing,
        "assert-retention": assert_retention_complete,
        "finalize-ready": finalize_ready,
    }[args.action]
    try:
        result = action(args.artifact_root, args.run_config)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
