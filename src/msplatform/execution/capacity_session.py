"""Normal workflow capacity sessions using the existing ledger and TTL leases."""
from __future__ import annotations

import copy
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from msplatform.execution import capacity_admission, capacity_protection as protection
from msplatform.execution.file_lock import shared_process_file_lock
from msplatform.execution.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
from msplatform.execution.terminal_publication import TERMINAL_LOCK_NAME


class CapacityAdmissionError(RuntimeError):
    """The original startup decision did not admit this exact lease."""

    def __init__(self, receipt: dict[str, Any]) -> None:
        self.receipt = receipt
        super().__init__(f"Capacity admission denied: {receipt['blocking_reason']}")


def _source_protection(session: dict[str, Any], references: Iterable[Mapping[str, Any]],
                       guards: ExitStack) -> set[str]:
    groups: dict[str, dict[str, list[Any]]] = {}
    touched = set()
    guarded_paths = set()
    for reference in references:
        if not isinstance(reference, Mapping) or "manifest_record" not in reference:
            raise ValueError("Source protection requires an explicit manifest_record")
        record = reference["manifest_record"]
        lock_path = Path(record["path"]).resolve().parent / TERMINAL_LOCK_NAME
        if lock_path not in guarded_paths:
            guards.enter_context(shared_process_file_lock(lock_path))
            guarded_paths.add(lock_path)
        source = resolve_consumed_run_capacity_owner(dict(record),
            consumer_artifact_root=Path(session["artifact_root"]),
            stopped_receipt_record=reference.get("stopped_receipt_record"))
        group = groups.setdefault(source["artifact_root"], {"paths": [], "keys": []})
        group["paths"].extend(str(Path(value).resolve()) for value in
                              [source["run_directory"], *reference.get("protected_paths", ())])
        group["keys"].extend(reference.get("protected_cache_keys", ()))
    for root_name, group in sorted(groups.items()):
        root = Path(root_name)
        if root == Path(session["artifact_root"]):
            session["protected_paths"] = sorted(set(session["protected_paths"]) | set(map(str, group["paths"])))
            session["protected_cache_keys"] = sorted(set(session["protected_cache_keys"]) | set(group["keys"]))
            continue
        existing = next((row for row in session["source_protection_leases"]
                         if row["artifact_root"] == root_name and row["status"] == "active"), None)
        if existing is None:
            existing = dict(artifact_root=root_name, lease_id=session["lease_id"] + "-source-" +
                str(len(session["source_protection_leases"])), status="active",
                protected_paths=[], protected_cache_keys=[])
            session["source_protection_leases"].append(existing)
            operation = protection.create_capacity_protection_lease
        else:
            operation = protection.renew_capacity_protection_lease
        lease = operation(root, lease_id=existing["lease_id"], owner=session["owner"],
            ttl_seconds=session["lease_ttl_seconds"], committed_new_bytes=0,
            protected_paths=map(Path, group["paths"]), protected_cache_keys=group["keys"])
        existing["protected_paths"] = [str(root / path) for path in lease["protected_paths"]]
        existing["protected_cache_keys"] = lease["protected_cache_keys"]
        touched.add(existing["lease_id"])
    return touched


def selected_capacity_policy(session: Mapping[str, Any]) -> dict[str, Any]:
    """Use only the new owner's captured policy; never reread its deployment file."""
    selection = session.get("capacity_policy")
    if selection is None:
        raise ValueError("Capacity admission requires explicit current-phase policy authority for a legacy session")
    policy = copy.deepcopy(selection["snapshot"])
    capacity_admission.validate_capacity_policy(policy)
    payload = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(payload).hexdigest() != selection["snapshot_sha256"]:
        raise ValueError("Captured capacity policy snapshot differs")
    if "frozen_record" in selection:
        from msplatform.io.manifest_records import verify_record
        verify_record("frozen capacity policy", selection["frozen_record"])
        frozen = json.loads(Path(selection["frozen_record"]["path"]).read_text(encoding="utf-8-sig"))
        if frozen != policy:
            raise ValueError("Frozen capacity policy differs from captured snapshot")
    return policy


def _admit(session: dict[str, Any], maintenance: Callable[[dict[str, Any]], Any] | None) -> dict[str, Any]:
    policy = selected_capacity_policy(session)

    def decision() -> dict[str, Any]:
        receipt = capacity_admission.plan_startup(Path(session["artifact_root"]),
            target_bytes=int(policy["target_gib"] * 1024**3),
            minimum_free_bytes=int(policy["minimum_free_gib"] * 1024**3),
            required_paths=map(Path, session["protected_paths"]),
            required_cache_keys=session["protected_cache_keys"],
            capacity_protection_lease_id=session["lease_id"], policy=policy)
        receipt.update(applied=bool(receipt["satisfied"]), removed=[], removed_bytes=0,
            free_bytes_after=receipt["free_bytes_before"], satisfied_after_apply=bool(receipt["satisfied"]))
        return receipt

    receipt = decision()
    if receipt["satisfied"]:
        return receipt
    if maintenance is None or receipt["blocking_reason"] not in {
            "TARGET_CAPACITY_EXCEEDED", "MINIMUM_FREE_CAPACITY_UNAVAILABLE"}:
        raise CapacityAdmissionError(receipt)
    # One explicit outer maintenance pass, then fresh admission under the same lease.
    attempt = dict(trigger_reason=receipt["blocking_reason"], initial_admission=receipt,
                   stage="renew_before_maintenance", maintenance=None)
    try:
        renew_capacity_session(session)
        attempt["stage"] = "maintenance"
        attempt["maintenance"] = maintenance(session)
        attempt["stage"] = "renew_before_readmission"
        renew_capacity_session(session)
        attempt["stage"] = "readmission"
        receipt = decision()
        receipt["pressure_maintenance"] = attempt
        if not receipt["satisfied"]:
            raise CapacityAdmissionError(receipt)
        attempt["stage"] = "admitted"
        return receipt
    except BaseException as failure:
        failure.add_note(f"Capacity pressure relief failed at {attempt['stage']}")
        failure.pressure_maintenance = attempt
        raise


def create_capacity_session(root: Path, run_directory: Path, *, owner: str,
        committed_new_bytes: int, protected_paths: Iterable[Path] = (),
        protected_cache_keys: Iterable[str] = (), source_references: Iterable[Mapping[str, Any]] = (),
        lease_ttl_seconds: int = 21600, capacity_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Acquire original source/own protection before the explicit admission policy."""
    session = dict(schema_version=1, role="artifact_workflow_capacity_session", status="active",
        artifact_root=str(root.resolve(strict=True)), lease_id="workflow-" + uuid4().hex,
        owner=owner, lease_ttl_seconds=lease_ttl_seconds, committed_new_bytes=committed_new_bytes,
        protected_paths=sorted({str(run_directory.resolve()), *map(lambda p: str(p.resolve()), protected_paths)}),
        protected_cache_keys=sorted(set(protected_cache_keys)), source_protection_leases=[],
        lease=None, startup_gate=None)
    if capacity_policy is not None:
        session["capacity_policy"] = copy.deepcopy(dict(capacity_policy))
        selected_capacity_policy(session)
    with ExitStack() as guards:
        try:
            _source_protection(session, source_references, guards)
            session["lease"] = protection.create_capacity_protection_lease(root,
                lease_id=session["lease_id"], owner=owner, ttl_seconds=lease_ttl_seconds,
                committed_new_bytes=committed_new_bytes, protected_paths=map(Path, session["protected_paths"]),
                protected_cache_keys=session["protected_cache_keys"])
            session["protected_paths"] = [str(root / path) for path in session["lease"]["protected_paths"]]
            session["protected_cache_keys"] = session["lease"]["protected_cache_keys"]
            return session
        except BaseException as primary:
            try:
                exit_capacity_session(session)
            except BaseException as secondary:
                primary.add_note(f"Capacity lease cleanup failed: {secondary!r}")
                primary.capacity_session = session
                primary.capacity_lease_cleanup = dict(lease_id=session["lease_id"], status="failed", error=str(secondary))
            else:
                primary.capacity_lease_cleanup = dict(lease_id=session["lease_id"], status="released")
            raise


def enter_capacity_session(root: Path, run_directory: Path, *, owner: str,
        committed_new_bytes: int, protected_paths: Iterable[Path] = (),
        protected_cache_keys: Iterable[str] = (), source_references: Iterable[Mapping[str, Any]] = (),
        lease_ttl_seconds: int = 21600,
        pressure_maintenance: Callable[[dict[str, Any]], Any] | None = None,
        capacity_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create the one protected session and evaluate its actual startup budget."""
    if capacity_policy is None:
        capacity_policy = capacity_admission.capture_capacity_policy()
    session = create_capacity_session(root, run_directory, owner=owner,
        committed_new_bytes=committed_new_bytes, protected_paths=protected_paths,
        protected_cache_keys=protected_cache_keys, source_references=source_references,
        lease_ttl_seconds=lease_ttl_seconds, capacity_policy=capacity_policy)
    try:
        session["startup_gate"] = _admit(session, pressure_maintenance)
        return session
    except BaseException as primary:
        try:
            exit_capacity_session(session)
        except BaseException as secondary:
            primary.add_note(f"Capacity lease cleanup failed: {secondary!r}")
            primary.capacity_session = session
            primary.capacity_lease_cleanup = dict(lease_id=session["lease_id"], status="failed", error=str(secondary))
        else:
            primary.capacity_lease_cleanup = dict(lease_id=session["lease_id"], status="released")
        raise


def renew_capacity_session(session: dict[str, Any], *, remaining_committed_new_bytes: int | None = None,
        protected_paths: Iterable[Path] = (), protected_cache_keys: Iterable[str] = (),
        source_references: Iterable[Mapping[str, Any]] = (),
        pressure_maintenance: Callable[[dict[str, Any]], Any] | None = None,
        admission: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, Any]:
    if session["status"] != "active":
        raise ValueError("Workflow capacity session is not active")
    prior = session["committed_new_bytes"]
    if "capacity_policy" in session:
        selected_capacity_policy(session)
    elif remaining_committed_new_bytes is not None and remaining_committed_new_bytes > prior and admission is None:
        raise ValueError("Capacity admission requires explicit current-phase policy authority for a legacy session")
    with ExitStack() as guards:
        touched = _source_protection(session, source_references, guards)
        for source in session["source_protection_leases"]:
            if source["status"] == "active" and source["lease_id"] not in touched:
                protection.renew_capacity_protection_lease(Path(source["artifact_root"]),
                    lease_id=source["lease_id"], owner=session["owner"],
                    ttl_seconds=session["lease_ttl_seconds"], committed_new_bytes=0)
        renewal = protection.renew_capacity_protection_lease(Path(session["artifact_root"]),
            lease_id=session["lease_id"], owner=session["owner"], ttl_seconds=session["lease_ttl_seconds"],
            committed_new_bytes=remaining_committed_new_bytes,
            protected_paths=map(Path, [*session["protected_paths"], *protected_paths]),
            protected_cache_keys=[*session["protected_cache_keys"], *protected_cache_keys])
        session["lease"] = renewal
        session["protected_paths"] = [str(Path(session["artifact_root"]) / path) for path in renewal["protected_paths"]]
        session["protected_cache_keys"] = renewal["protected_cache_keys"]
        if remaining_committed_new_bytes is not None:
            session["committed_new_bytes"] = remaining_committed_new_bytes
        if session["committed_new_bytes"] > prior:
            session["startup_gate"] = admission(session) if admission is not None else _admit(session, pressure_maintenance)
        return renewal


def exit_capacity_session(session: dict[str, Any]) -> dict[str, Any]:
    """Release all original source leases and own lease; preserve the first error."""
    if session["status"] != "active":
        return dict(deleted=False, status=session["status"])
    errors = []
    result = None
    for source in session["source_protection_leases"]:
        if source["status"] == "active":
            try:
                protection.delete_capacity_protection_lease(Path(source["artifact_root"]), lease_id=source["lease_id"])
                source["status"] = "released"
            except BaseException as failure:
                errors.append(failure)
    try:
        result = protection.delete_capacity_protection_lease(Path(session["artifact_root"]), lease_id=session["lease_id"])
    except BaseException as failure:
        errors.append(failure)
    if errors:
        for secondary in errors[1:]:
            errors[0].add_note(f"Capacity release failed: {secondary!r}")
        errors[0].capacity_session = session
        raise errors[0]
    session["status"] = "released"
    return result
