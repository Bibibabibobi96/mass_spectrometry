"""Reconcile externally interrupted compact runs without discarding evidence.

An external stop can prevent a solver runner's normal compact-retention step.
This tool deliberately accepts only a verified, terminal ``interrupted`` run
whose frozen retention class is ``compact``.  It removes only files forbidden
by that class (for example PA arrays and dense trajectories), retains the
input/summary/log/manifest evidence, and records every removal.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from common.contracts.artifact_retention import (
    apply_retention,
    classify_file,
    load_run_retention,
)
from common.contracts.verify_run_manifest import record_path, verify_record


def assert_no_active_simion() -> None:
    """Refuse reconciliation while any local SIMION process is active."""

    if __import__("os").name != "nt":
        return
    listing = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"], cwd=Path.cwd(), text=True, capture_output=True,
        encoding="utf-8", errors="replace", check=False, timeout=15,
    )
    if listing.returncode != 0:
        raise RuntimeError("cannot establish that SIMION is inactive")
    active = [line for line in listing.stdout.splitlines() if line.lower().startswith('"simion')]
    if active:
        raise RuntimeError("refusing compact reconciliation while SIMION is active")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def inspect_run(run_dir: Path, *, permit_manifest_drift: bool = False) -> dict[str, Any]:
    """Return a fail-closed reconciliation plan for one interrupted run."""

    run_dir = run_dir.resolve()
    if run_dir.parent.name != "runs":
        raise ValueError("run directory must be a direct child of runs/")
    config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    if not config_path.is_file() or not summary_path.is_file() or not manifest_path.is_file():
        raise ValueError("run requires run_config.json, summary.json, and run_manifest.json")
    manifest = _load(manifest_path)
    if manifest.get("status") != "interrupted":
        raise ValueError("only terminal interrupted runs may be reconciled")
    summary = _load(summary_path)
    if summary.get("status") != "interrupted":
        raise ValueError("summary status must be interrupted before reconciliation")
    integrity = "verified"
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
            if candidate != run_dir and run_dir not in candidate.parents:
                raise ValueError(f"manifest {section} record escapes run directory")
            try:
                verify_record(f"{section} {index}", record, base_dir=run_dir)
            except AssertionError as error:
                if not permit_manifest_drift:
                    raise ValueError(f"manifest integrity must verify before reconciliation: {error}") from error
                integrity = "degraded_manifest_drift"
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
    return {
        "run_dir": str(run_dir), "run_id": config_path.parent.name,
        "eligible": True, "manifest_integrity": integrity, "removable_file_count": len(forbidden),
        "removable_bytes": sum(int(item["bytes"]) for item in forbidden), "removable": forbidden,
    }


def reconcile(run_root: Path, *, apply: bool, permit_manifest_drift: bool = False, max_apply_runs: int | None = None) -> list[dict[str, Any]]:
    """Inspect every direct run child; optionally apply only safe plans."""

    root = run_root.resolve()
    if not root.is_dir() or root.name != "runs":
        raise ValueError("run_root must be an existing runs directory")
    if apply:
        assert_no_active_simion()
    reports: list[dict[str, Any]] = []
    applied_count = 0
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            report = inspect_run(child, permit_manifest_drift=permit_manifest_drift)
        except (AssertionError, KeyError, ValueError) as error:
            reports.append({"run_dir": str(child), "eligible": False, "reason": str(error)})
            continue
        if apply and report["removable_file_count"] and (max_apply_runs is None or applied_count < max_apply_runs):
            action_path = apply_retention(child / "run_config.json")
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
        "applied_runs": len(applied),
        "removed_file_count": sum(int(item.get("removed_file_count", 0)) for item in applied),
        "removed_bytes": sum(int(item.get("removed_bytes", 0)) for item in applied),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="perform the preflighted removals")
    parser.add_argument("--permit-manifest-drift", action="store_true", help="allow an interrupted compact run whose manifest hashes drifted; still refuses manifest-recorded heavy files")
    parser.add_argument("--max-apply-runs", type=int, help="apply at most this many eligible runs in one invocation")
    parser.add_argument("--summary-only", action="store_true", help="emit only aggregate scan/removal counts; suitable for every solver startup")
    args = parser.parse_args()
    if args.max_apply_runs is not None and (not args.apply or args.max_apply_runs < 1):
        parser.error("--max-apply-runs requires --apply and a positive value")
    reports = reconcile(args.run_root, apply=args.apply, permit_manifest_drift=args.permit_manifest_drift, max_apply_runs=args.max_apply_runs)
    receipt = summarize(reports, apply=args.apply)
    receipt["permit_manifest_drift"] = args.permit_manifest_drift
    if not args.summary_only:
        receipt["runs"] = reports
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
