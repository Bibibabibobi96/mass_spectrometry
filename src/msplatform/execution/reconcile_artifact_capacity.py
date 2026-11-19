"""Installed startup admission; repository maintenance remains in common."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

from msplatform.execution import capacity_admission as _admission
from msplatform.execution import capacity_protection as protection
from msplatform.execution.resources import resource_path

GIB = 1024**3
POLICY_PATH = resource_path("artifact_capacity_policy.json")
_capacity_policy = _admission._capacity_policy
_timings = _admission._timings
_startup_capacity_gate = _admission._startup_capacity_gate


def plan(
    root: Path, *, target_bytes: int, minimum_free_bytes: int,
    protected_paths: Iterable[Path] = (), protected_cache_keys: Iterable[str] = (),
    capacity_ledger: Path | None = None,
    capacity_protection_lease_id: str | None = None,
) -> dict[str, Any]:
    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    return _startup_capacity_gate(
        root, target_bytes=target_bytes, minimum_free_bytes=minimum_free_bytes,
        required_paths=protected_paths, required_cache_keys=protected_cache_keys,
        capacity_ledger_path=capacity_ledger,
        capacity_protection_lease_id=capacity_protection_lease_id,
    )


def _complete_startup_decision(receipt: dict[str, Any]) -> dict[str, Any]:
    receipt.update(
        applied=bool(receipt["satisfied"]), removed=[], removed_bytes=0,
        free_bytes_after=receipt["free_bytes_before"],
        satisfied_after_apply=bool(receipt["satisfied"]),
    )
    return receipt


def main() -> None:
    started = time.perf_counter()
    policy = _capacity_policy()
    timings = _timings(policy)
    timings.started = started
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--execution-mode", choices=("startup",), default="startup")
    parser.add_argument("--capacity-ledger", type=Path)
    parser.add_argument("--capacity-protection-lease-id")
    parser.add_argument("--protect-path", action="append", type=Path, default=[])
    parser.add_argument("--protect-cache-key", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--detailed-output", action="store_true")
    args = parser.parse_args()
    if args.apply and not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
        parser.error("--apply requires the shared HostExecutionLease")
    try:
        with timings.phase("plan"):
            receipt = plan(
                args.artifact_root,
                target_bytes=int(policy["target_gib"] * GIB),
                minimum_free_bytes=int(policy["minimum_free_gib"] * GIB),
                protected_paths=args.protect_path,
                protected_cache_keys=args.protect_cache_key,
                capacity_ledger=args.capacity_ledger,
                capacity_protection_lease_id=args.capacity_protection_lease_id,
            )
        for name, seconds in receipt.get("timing", {}).get("phases_seconds", {}).items():
            timings.phases[f"plan.{name}"] = seconds
        if args.apply:
            receipt = _complete_startup_decision(receipt)
        if not args.detailed_output:
            receipt = {
                key: value for key, value in receipt.items() if key not in {"planned", "removed"}
            } | {
                "planned_count": len(receipt.get("planned", [])),
                "removed_count": len(receipt.get("removed", [])),
            }
        receipt["owner_actions"] = {}
        receipt["timing"] = timings.finish()
        print(json.dumps(receipt, indent=2))
    except (ValueError, RuntimeError, protection.CapacityProtectionLeaseError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
