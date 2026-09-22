"""Reconcile externally interrupted compact runs without discarding evidence.

An external stop or failed runner can prevent the normal compact-retention
step.  This tool deliberately accepts only a verified, terminal ``failed`` or
``interrupted`` run whose frozen retention class is ``compact``.  It removes
only files forbidden by that class (for example PA arrays and dense
trajectories), retains the input/summary/log/manifest evidence, and records
every removal.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from common.contracts import capacity_protection as protection
from common.contracts.artifact_retention import (
    _execute_removals,
    _publish_removal_preflight,
    classify_file,
    load_run_retention,
)
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.solver_review_retirement import _downstream_references


TERMINAL_RECONCILABLE_STATUSES = frozenset({"failed", "interrupted"})
HOST_LEASE_OWNER_ENV = "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _artifact_root_for_run(run_dir: Path) -> Path:
    """Validate and return the artifact root for one top-level project run."""

    if (
        not run_dir.is_dir()
        or len(run_dir.parents) < 4
        or run_dir.parent.name != "runs"
        or run_dir.parents[2].name != "projects"
    ):
        raise ValueError(
            "run directory must be an existing top-level "
            "projects/<project>/runs/<run_id> directory"
        )
    return run_dir.parents[3]


def inspect_run(
    run_dir: Path, *, permit_manifest_drift: bool = False,
    verify_manifest_records: bool = True,
    permit_preflight_marker: bool = False,
) -> dict[str, Any]:
    """Return a fail-closed reconciliation plan for one terminal compact run."""

    run_dir = run_dir.resolve()
    artifact_root = _artifact_root_for_run(run_dir)
    leases = protection.load_capacity_protection_leases(artifact_root)
    if protection.path_is_protected(run_dir, leases["protected_paths"]):
        raise ValueError("run is covered by an active capacity protection lease")
    config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    if not config_path.is_file() or not summary_path.is_file() or not manifest_path.is_file():
        raise ValueError("run requires run_config.json, summary.json, and run_manifest.json")
    manifest = _load(manifest_path)
    manifest_status = manifest.get("status")
    if manifest_status not in TERMINAL_RECONCILABLE_STATUSES:
        raise ValueError(
            "run_manifest status must be terminal failed or interrupted; "
            "checkpoint runs require normal terminalization first"
        )
    summary = _load(summary_path)
    if summary.get("status") != manifest_status:
        raise ValueError(
            "summary status must match the terminal failed/interrupted manifest status"
        )
    integrity = "verified" if verify_manifest_records else "structural_precheck"
    if verify_manifest_records:
        try:
            verify_record("run_config", manifest["run_config"], base_dir=run_dir)
        except (AssertionError, KeyError, TypeError) as error:
            if not permit_manifest_drift:
                raise ValueError(f"manifest integrity must verify before reconciliation: {error}") from error
            integrity = "degraded_manifest_drift"
    config_record = record_path(manifest["run_config"], base_dir=run_dir)
    if config_record != config_path:
        raise ValueError("manifest run_config must be the local run_config.json")
    if _load(config_path).get("run_id") != run_dir.name:
        raise ValueError("run_config run_id must match the run directory")
    _, retention = load_run_retention(config_path)
    if retention.class_id != "compact":
        raise ValueError("only compact runs may be reconciled")
    action_path = run_dir / "retention_actions.json"
    if action_path.exists():
        action = _load(action_path)
        if not (
            permit_preflight_marker
            and action.get("status") == "preflight_pending"
            and action.get("retention_class") == "compact"
        ):
            raise ValueError("run already has a retention reconciliation receipt")

    recorded: set[Path] = {config_path, manifest_path}
    summary_recorded = False
    for section in ("inputs", "outputs"):
        values = manifest.get(section, {} if section == "inputs" else [])
        records = values.values() if isinstance(values, dict) else values
        if not isinstance(records, (list, tuple, type({}.values()))):
            raise ValueError(f"manifest {section} has an invalid shape")
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(f"manifest {section} record {index} is invalid")
            candidate = record_path(record, base_dir=run_dir)
            local_candidate = candidate == run_dir or run_dir in candidate.parents
            if section == "outputs" and not local_candidate:
                raise ValueError(f"manifest {section} record escapes run directory")
            if verify_manifest_records:
                try:
                    verify_record(f"{section} {index}", record, base_dir=run_dir)
                except AssertionError as error:
                    if not permit_manifest_drift:
                        raise ValueError(f"manifest integrity must verify before reconciliation: {error}") from error
                    integrity = "degraded_manifest_drift"
            if local_candidate:
                recorded.add(candidate)
                summary_recorded = summary_recorded or candidate == summary_path

    if not summary_recorded:
        raise ValueError("manifest must record the local summary.json")

    forbidden: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path in {manifest_path, action_path}:
            continue
        role = classify_file(path)
        if role in {"solver_native_binary", "dense_trajectory", "large_optional"}:
            if path.resolve() in recorded:
                raise ValueError(f"manifest-recorded file is forbidden in compact run: {path}")
            forbidden.append({"path": path.relative_to(run_dir).as_posix(), "bytes": path.stat().st_size, "retention_role": role})
    all_files = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*") if path.is_file() and not path.is_symlink()
    }
    removable_paths = {item["path"] for item in forbidden}
    references = _downstream_references(
        artifact_root,
        run_dir,
        run_dir.name,
        removable_paths=removable_paths,
        preserved_paths=all_files - removable_paths,
    )
    occupied_all = any(not item.get("path") for item in references["active"])
    occupied_paths = {
        item.get("path") for item in references["active"] if item.get("path")
    }
    occupied = [
        {**item, "consumers": [
            reference["run_config_path"] for reference in references["active"]
            if not reference.get("path") or reference.get("path") == item["path"]
        ]}
        for item in forbidden
        if occupied_all or item["path"].casefold() in {str(path).casefold() for path in occupied_paths}
    ]
    occupied_relative_paths = {item["path"].casefold() for item in occupied}
    removable = [
        item for item in forbidden
        if item["path"].casefold() not in occupied_relative_paths
    ]
    return {
        "run_dir": str(run_dir), "run_id": config_path.parent.name,
        "eligible": True, "terminal_status": manifest_status,
        "manifest_integrity": integrity,
        "manifest_records_verified": verify_manifest_records,
        "removable_file_count": len(removable),
        "removable_bytes": sum(int(item["bytes"]) for item in removable),
        "removable": removable,
        "occupied_file_count": len(occupied),
        "occupied_bytes": sum(int(item["bytes"]) for item in occupied),
        "occupied": occupied,
        "active_preserved_file_references": references["active_preserved"],
        "historical_references": references["historical"],
    }


def apply_run(run_dir: Path, *, permit_manifest_drift: bool = False) -> Path:
    """Recheck one terminal run and remove only unrecorded heavy files."""

    if not os.environ.get(HOST_LEASE_OWNER_ENV):
        raise RuntimeError("apply requires the shared HostExecutionLease")
    artifact_root = _artifact_root_for_run(run_dir.resolve())
    with protection.capacity_decision_lock(artifact_root):
        report = inspect_run(
            run_dir,
            permit_manifest_drift=permit_manifest_drift,
            verify_manifest_records=False,
            permit_preflight_marker=True,
        )
        directory, retention = load_run_retention(run_dir / "run_config.json")
        removed = [
            {**item, "action": "removed_unrecorded_interrupted_payload"}
            for item in report["removable"]
        ]
        action_path = directory / "retention_actions.json"
        if not action_path.exists():
            _publish_removal_preflight(directory, retention, removed)
    verified = inspect_run(
        run_dir,
        permit_manifest_drift=permit_manifest_drift,
        verify_manifest_records=True,
        permit_preflight_marker=True,
    )
    verified_removed = [
        {**item, "action": "removed_unrecorded_interrupted_payload"}
        for item in verified["removable"]
    ]
    if verified_removed != removed:
        raise ValueError("compact removable payload changed after pending marker")
    return _execute_removals(directory, retention, removed, [])


def reconcile(run_root: Path, *, apply: bool, permit_manifest_drift: bool = False, max_apply_runs: int | None = None) -> list[dict[str, Any]]:
    """Inspect every direct run child; optionally apply only safe plans."""

    root = run_root.resolve()
    if not root.is_dir() or root.name != "runs":
        raise ValueError("run_root must be an existing runs directory")
    reports: list[dict[str, Any]] = []
    applied_count = 0
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            report = inspect_run(child, permit_manifest_drift=permit_manifest_drift)
        except (AssertionError, KeyError, ValueError) as error:
            reports.append({"run_dir": str(child), "eligible": False, "reason": str(error)})
            continue
        if apply and report["removable_file_count"] and (max_apply_runs is None or applied_count < max_apply_runs):
            action_path = apply_run(child, permit_manifest_drift=permit_manifest_drift)
            action = _load(action_path)
            report["applied"] = True
            report["retention_actions"] = str(action_path)
            report["removed_file_count"] = action["removed_file_count"]
            report["removed_bytes"] = action["removed_bytes"]
            applied_count += 1
        else:
            report["applied"] = False
        reports.append(report)
    return reports


def summarize(reports: list[dict[str, Any]], *, apply: bool) -> dict[str, Any]:
    """Build the small startup receipt without serializing every run plan."""

    eligible = [item for item in reports if item.get("eligible")]
    applied = [item for item in reports if item.get("applied")]
    return {
        "schema_version": 1,
        "role": "interrupted_compact_reconciliation",
        "apply": apply,
        "scanned_run_count": len(reports),
        "eligible_runs": len(eligible),
        "removable_bytes": sum(int(item.get("removable_bytes", 0)) for item in eligible),
        "occupied_file_count": sum(
            int(item.get("occupied_file_count", 0)) for item in eligible
        ),
        "occupied_bytes": sum(int(item.get("occupied_bytes", 0)) for item in eligible),
        "applied_runs": len(applied),
        "removed_file_count": sum(int(item.get("removed_file_count", 0)) for item in applied),
        "removed_bytes": sum(int(item.get("removed_bytes", 0)) for item in applied),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-root", type=Path)
    target.add_argument(
        "--run-dir", type=Path,
        help="inspect or apply only this projects/<project>/runs/<run_id>",
    )
    parser.add_argument("--apply", action="store_true", help="perform the preflighted removals")
    parser.add_argument("--permit-manifest-drift", action="store_true", help="allow a terminal compact run whose manifest hashes drifted; still refuses manifest-recorded heavy files")
    parser.add_argument("--max-apply-runs", type=int, help="apply at most this many eligible runs in one invocation")
    parser.add_argument("--summary-only", action="store_true", help="emit only aggregate scan/removal counts; suitable for every solver startup")
    args = parser.parse_args()
    if args.max_apply_runs is not None and (not args.apply or args.max_apply_runs < 1):
        parser.error("--max-apply-runs requires --apply and a positive value")
    if args.run_dir is not None and args.max_apply_runs is not None:
        parser.error("--max-apply-runs is only valid with --run-root")
    if args.run_dir is not None:
        try:
            report = inspect_run(
                args.run_dir, permit_manifest_drift=args.permit_manifest_drift
            )
            if args.apply and report["removable_file_count"]:
                action_path = apply_run(
                    args.run_dir, permit_manifest_drift=args.permit_manifest_drift
                )
                action = _load(action_path)
                report.update({
                    "applied": True,
                    "retention_actions": str(action_path),
                    "removed_file_count": action["removed_file_count"],
                    "removed_bytes": action["removed_bytes"],
                })
            else:
                report["applied"] = False
        except (AssertionError, KeyError, ValueError) as error:
            if args.apply:
                raise
            report = {
                "run_dir": str(args.run_dir.resolve()),
                "eligible": False,
                "reason": str(error),
                "applied": False,
            }
        reports = [report]
    else:
        reports = reconcile(
            args.run_root, apply=args.apply,
            permit_manifest_drift=args.permit_manifest_drift,
            max_apply_runs=args.max_apply_runs,
        )
    receipt = summarize(reports, apply=args.apply)
    receipt["permit_manifest_drift"] = args.permit_manifest_drift
    if not args.summary_only:
        receipt["runs"] = reports
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
