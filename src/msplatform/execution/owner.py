"""Normal installed run owner composed from the existing lifecycle mechanisms.

Scientific materialization is an explicit callable. This module owns no provider,
solver formula, cache, secondary ledger, or alternative recovery state machine.
"""
from __future__ import annotations

from functools import partial
import copy
import inspect
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from msplatform.execution import artifact_retention as retention_policy
from msplatform.execution import capacity_ledger, capacity_protection, run_capacity_lifecycle as lifecycle
from msplatform.execution.artifact_naming import validate_run_id
from msplatform.execution.capacity_admission import capture_capacity_policy
from msplatform.execution.capacity_session import enter_capacity_session, exit_capacity_session, renew_capacity_session, selected_capacity_policy
from msplatform.execution.context import ExecutionContext
from msplatform.execution.manifest_publication import build_run_manifest
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.run_paths import create_execution_alias, path_capacity, remove_execution_alias
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import TERMINAL_JOURNAL_NAME
from msplatform.execution.terminal_publication import TERMINAL_LOCK_NAME
from msplatform.execution.workflow_publication import publish_workflow_terminal


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Owner record is not an object: {path}")
    return value


def _retention_api(session: RunSession, completion_api: Callable[[], Any] | None):
    return (session.classify_file,
        partial(retention_policy.load_failed_recovery_exemptions,
                classifier=session.classify_file, completion_api=completion_api),
        partial(retention_policy.validate_retained_files, classifier=session.classify_file),
        retention_policy.validate_retention)


def _writer_completion(session: RunSession) -> dict[str, Any]:
    """Validate actual exit/release facts before allowing retention or publication."""
    if not session.writers_stopped:
        raise ValueError("Native writer completion is unknown; retain all protection")
    releases = {}
    tokens = set()
    for row in session.resource_releases:
        if set(row) != {"release_id", "completion_receipt"} or row["release_id"] in releases:
            raise ValueError("Resource release identity is missing or duplicated")
        release = row["completion_receipt"]["host_release"]
        if (set(release) != {"inherited", "token", "result", "error"}
                or release["inherited"] is not False or release["error"] is not None
                or not isinstance(release["token"], str) or not release["token"]
                or release["token"] in tokens or release["result"] != {
                    "status": "released", "token": release["token"]}):
            raise ValueError("Resource owner release is unconfirmed or inherited")
        tokens.add(release["token"])
        releases[row["release_id"]] = False
    operation_ids = set()
    for row in session.operations:
        observation = row["observation"]
        if (row["operation_id"] in operation_ids or row["operation_id"] not in session.expected_operation_ids
                or observation.get("exit_confirmed") is not True
                or any(type(observation.get(name)) is not int for name in (
                    "returncode", "process_id", "process_started_at_utc_ticks"))
                or observation["process_id"] <= 0 or observation["process_started_at_utc_ticks"] <= 0
                or row["resource_release_id"] not in releases):
            raise ValueError("Native writer observation lacks its actual process or bound release")
        operation_ids.add(row["operation_id"])
        releases[row["resource_release_id"]] = True
    if any(not used for used in releases.values()):
        raise ValueError("Resource release has no corresponding started operation")
    return dict(operations=session.operations, resource_releases=session.resource_releases)


def _result(session: RunSession, **fields: Any) -> dict[str, Any]:
    value = dict(schema_version=1, role="run_artifact_workflow_result",
        run_directory=str(session.artifact_run_dir), execution_request=str(session.execution_request),
        **fields)
    write_json_atomic(session.result_path, value)
    return value


class CapacityAccountingDeferredError(RuntimeError):
    """Stopped writers still belong to their unresolved capacity accounting owner."""


def _require_capacity_accounted(session: RunSession) -> None:
    # Result is recovery transport, not authority to erase the original hold.
    original = _json(session.artifact_run_dir / "logs/capacity_session.json")
    for name in ("owner", "artifact_root", "lease_id"):
        if original[name] != session.capacity_session[name]:
            raise ValueError("Original finalization capacity session differs")
    if "capacity_policy" in original:
        request = _json(session.execution_request)
        if (request["capacity"].get("policy") != original["capacity_policy"]
                or session.capacity_session.get("capacity_policy") != original["capacity_policy"]):
            raise ValueError("Original finalization capacity policy differs")
        selected_capacity_policy(original)
    for capacity in (original, session.capacity_session):
        if "defer_capacity_finalization" in capacity:
            reason = capacity["defer_capacity_finalization"]
            raise CapacityAccountingDeferredError(f"Capacity accounting is deferred: {reason!r}")


def _preserve_accounting_hold(session: RunSession, completion: Mapping[str, Any],
                              failure: CapacityAccountingDeferredError) -> None:
    _result(session, status="failed", stage="capacity_accounting", writers_confirmed=True,
        execution_status="capacity_accounting_deferred", resume_action="return_to_capacity_accounting_owner",
        lease_released=False, capacity_finalized=False, terminal_published=False,
        exception=completion["exception"], secondary_errors=[str(failure)],
        capacity_session=session.capacity_session)


def _publish(session: RunSession, request: Mapping[str, Any], completion: Mapping[str, Any],
             completion_api: Callable[[], Any] | None) -> dict[str, Any]:
    root = session.artifact_run_dir
    completion_path = root / "results/execution_completion.json"
    verify_record("completion request", completion["execution_request"])
    verify_record("completion run config", completion["run_config"])
    _writer_completion(session)
    for index, authority in enumerate([request["prepared"]["entrypoint"], *request["capacity"]["commitment_inputs"]]):
        verify_record(f"owner authority {index}", authority)
    if completion["status"] not in {"success", "failed", "interrupted"}:
        raise ValueError("Workflow completion status differs")
    session.declare_file(root / "retention_actions.json", "required_evidence")
    session.declare_file(root / TERMINAL_LOCK_NAME, "required_evidence")
    session.declare_file(root / TERMINAL_JOURNAL_NAME, "required_evidence")
    retention_path = root / "retention_actions.json"
    if not retention_path.exists() or _json(retention_path).get("status") != "complete":
        retention_policy.apply_retention(session.run_config,
            classifier=session.classify_file, completion_api=completion_api,
            preserve_paths=map(Path, completion["retention_preserve_paths"]),
            failed_run=completion["status"] != "success",
            recovery_inputs=(session.execution_request, completion_path),
            resume=retention_path.exists())
    observed_logs = [Path(name) for name in session.file_roles
                     if Path(name).parent == root / "logs" and Path(name).is_file()]
    return publish_workflow_terminal(completion_path, root / "logs/capacity_session.json", None,
        retention_api=lambda: _retention_api(session, completion_api), additional_output_paths=observed_logs)


def _finalize(session: RunSession, request: dict[str, Any], completion: dict[str, Any], *,
              completion_api: Callable[[], Any] | None) -> dict[str, Any]:
    _writer_completion(session)
    _require_capacity_accounted(session)
    _publish(session, request, completion, completion_api)
    selection = retention_policy.validate_retention(request["retention"])
    if selection.class_id == "compact":
        capacity = lifecycle.finalize_ready(session.artifact_root, session.run_config,
                                           classify_file=session.classify_file)
        exit_capacity_session(session.capacity_session)
    else:
        # The exact current bytes remain registered before the stopped-payload seal.
        ledger = capacity_ledger.load_capacity_ledger(session.artifact_root)
        relative = session.artifact_run_dir.relative_to(session.artifact_root).as_posix()
        entry = next(row for row in ledger["objects"] if row["path"] == relative)
        if entry["status"] == "writing":
            lifecycle.register_writing(session.artifact_root, session.run_config)
        exit_capacity_session(session.capacity_session)
        capacity = lifecycle.seal_checkpoint(session.artifact_root, session.run_config,
            owner=session.project, classify_file=session.classify_file, writing_stopped=True,
            retain_payload=True, retention_reason=selection.reason)
    alias = session.package.get("execution_alias")
    if alias:
        remove_execution_alias(session.context, Path(alias), session.artifact_run_dir)
    return _result(session, status=completion["status"], stage="complete", writers_confirmed=True,
        resume_action=None, capacity=capacity, capacity_session=session.capacity_session,
        manifest=file_record(session.artifact_run_dir / "run_manifest.json", "required_evidence"),
        exception=completion["exception"])


def run_managed_stage(context: ExecutionContext, *, descriptor: Mapping[str, Any], run_id: str,
        payload: Mapping[str, Any], committed_new_bytes: int,
        commitment_inputs: Sequence[Mapping[str, Any]], retention: Mapping[str, Any],
        expected_operation_ids: Sequence[str], operation_dependencies: Mapping[str, Sequence[str]],
        action: Callable[[RunSession], Mapping[str, Any]], action_record: Mapping[str, Any],
        protected_paths: Sequence[Path] = (), protected_cache_keys: Sequence[str] = (),
        source_references: Sequence[Mapping[str, Any]] = (),
        expected_relative_paths: Sequence[str] = (), use_short_execution_path: bool = False,
        pressure_maintenance: Callable[[dict[str, Any]], Any] | None = None,
        completion_api: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Create one package, run one bound action, then finalize with the sole journal.

    The action returns status, summary, output_paths, required_output_paths,
    retention_preserve_paths, and manifest_extra_fields. A failure is re-raised
    after safe finalization; its secondary errors never replace that first error.
    An action exception may carry explicit failure_output_paths. Only actual,
    declared files inside this run are published after writer closure is proven.
    """
    validate_run_id(run_id)
    environment = context.environment
    if environment is not None:
        if "execution_environment" in payload:
            raise ValueError("Execution environment provenance is owned by the managed stage")
        payload = dict(payload, execution_environment=environment)
    if (set(descriptor) != {"project", "mode", "software"}
            or not isinstance(descriptor["project"], str)
            or re.fullmatch(r"[a-z][a-z0-9_]*", descriptor["project"]) is None
            or not isinstance(descriptor["mode"], str) or not descriptor["mode"]
            or not isinstance(descriptor["software"], (list, tuple))):
        raise ValueError("Explicit workflow descriptor differs")
    retention_policy.validate_retention(dict(retention))
    if type(committed_new_bytes) is not int or committed_new_bytes < 0:
        raise ValueError("Workflow capacity requires a nonnegative integer commitment")
    if not commitment_inputs:
        raise ValueError("Workflow capacity requires its frozen budget authority")
    if environment is not None and environment["source"] is not None:
        commitment_inputs = [*commitment_inputs, environment["source"]]
    for index, record in enumerate([action_record, *commitment_inputs]):
        verify_record(f"owner authority {index}", dict(record))
    source_callable = action.func if isinstance(action, partial) else action
    source_path = inspect.getsourcefile(inspect.unwrap(source_callable))
    if source_path is None or Path(source_path).resolve() != Path(action_record["path"]).resolve():
        raise ValueError("Prepared callable source differs from its bound action record")
    ids = tuple(expected_operation_ids)
    if (any(not isinstance(name, str) or not name for name in ids) or len(set(ids)) != len(ids)
            or any(name not in ids or any(parent not in ids or parent == name for parent in parents)
                   for name, parents in operation_dependencies.items())):
        raise ValueError("Declared operation identities or dependencies differ")
    # A genuinely new empty artifact root has an explicit empty calibrated baseline.
    # Existing content without a ledger is never discovered or silently adopted.
    context.workspace.mkdir(parents=True, exist_ok=True)
    root = context.workspace / "artifacts"
    if not root.exists():
        root.mkdir()
        capacity_ledger.initialize_capacity_ledger(root, objects=[])
    if capacity_ledger.load_capacity_ledger(root) is None:
        raise ValueError("Existing artifact root lacks its explicit calibrated capacity ledger")
    project = descriptor["project"]
    run_root = root / "projects" / project / "runs" / run_id
    if run_root.exists():
        raise FileExistsError("Run already exists; resume its original finalization")
    result_path = root / "projects" / project / "scratch/workflow_results" / run_id / "result.json"
    if result_path.exists():
        raise FileExistsError("Workflow Result already exists")
    policy_selection = capture_capacity_policy(context.capacity_policy_path)
    policy_snapshot = policy_selection["snapshot"]
    capacity = enter_capacity_session(root, run_root,
        owner=f"run-artifact-workflow:{project}:{run_id}", committed_new_bytes=committed_new_bytes,
        protected_paths=protected_paths, protected_cache_keys=protected_cache_keys,
        source_references=source_references, pressure_maintenance=pressure_maintenance,
        capacity_policy=policy_selection)
    package = dict(artifact_run_dir=str(run_root), run_dir=str(run_root), execution_alias=None)
    session = RunSession(context, root, run_id, project, descriptor["mode"], package, capacity,
        run_root / "inputs/execution_request.json", result_path, ids, dict(operation_dependencies))
    primary = None
    finalized = False
    try:
        run_root.mkdir(parents=True)
        lifecycle.register_writing_range(root, run_root)
        report = path_capacity(context, run_root, expected_relative_paths=expected_relative_paths)
        if use_short_execution_path or (expected_relative_paths and not report["legacy_windows_compatible"]):
            alias = create_execution_alias(context, run_root, expected_relative_paths=expected_relative_paths)
            package.update(run_dir=alias["execution_alias"], execution_alias=alias["execution_alias"])
        for directory in ("inputs", "results", "logs"):
            (run_root / directory).mkdir()
        paths = dict(artifact_root=str(root), execution_root=str(context.execution_root),
                     host_resource_state_path=str(context.host_state_path))
        config = dict(schema_version=2, run_id=run_id, project=project, mode=descriptor["mode"],
            project_root=str(context.workspace), inputs={"execution_request": str(session.execution_request)},
            parameters=dict(payload), formal_gate_passed=False, paths=paths, artifact_retention=dict(retention),
            capacity_ledger_lifecycle=dict(schema_version=1, enabled=True, artifact_root=str(root),
                light_evidence_budget_bytes=policy_snapshot["light_evidence_budget_bytes"]))
        request = dict(schema_version=1, role="run_artifact_workflow_request", package=dict(descriptor, run_id=run_id),
            payload=dict(payload), capacity=dict(committed_new_bytes=committed_new_bytes,
                commitment_inputs=list(commitment_inputs), protected_paths=list(map(str, protected_paths)),
                protected_cache_keys=list(protected_cache_keys), source_references=list(source_references)),
            prepared=dict(owner_kind="managed_action", entrypoint=dict(action_record)), retention=dict(retention), paths=paths,
            expected_operation_ids=list(ids), operation_dependencies=dict(operation_dependencies))
        for target in (session.run_config, session.execution_request, run_root / "run_manifest.json", run_root / "summary.json",
                       run_root / "logs/capacity_session.json", run_root / "results/execution_completion.json"):
            session.declare_file(target, "required_evidence")
        frozen_policy = session.declare_file(run_root / "inputs/capacity_policy.json", "required_evidence")
        write_json_atomic(frozen_policy, policy_snapshot)
        capacity["capacity_policy"]["frozen_record"] = file_record(frozen_policy, "required_evidence")
        request["capacity"]["policy"] = copy.deepcopy(capacity["capacity_policy"])
        write_json_atomic(session.execution_request, request)
        write_json_atomic(session.run_config, config)
        session.add_input("capacity_policy", capacity["capacity_policy"]["frozen_record"])
        # The callable authority is bound after capture, avoiding a duplicate input rebind.
        for index, authority in enumerate(commitment_inputs, start=1):
            session.add_input(f"owner_authority_{index}", dict(authority, retention_role="required_evidence"))
        write_json_atomic(run_root / "summary.json", dict(schema_version=1, status="checkpoint",
            role="run_package_initialization_summary", reason="Run package initialized; action has not executed"))
        write_json_atomic(run_root / "logs/capacity_session.json", capacity)
        checkpoint = build_run_manifest(session.run_config, "checkpoint",
            retention_api=lambda: _retention_api(session, completion_api), software=list(descriptor["software"]),
            output_paths=[run_root / "summary.json"])
        write_json_atomic(run_root / "run_manifest.json", checkpoint)
        lifecycle.register_writing(root, session.run_config)
        _result(session, status="pending", stage="prepared", resume_action="inspect_writer_completion")
        try:
            from msplatform.execution.inputs import freeze_file
            source_action_path = Path(action_record["path"]).resolve()
            frozen_action = session.declare_file(run_root / "inputs" / "owner" / ("action" + source_action_path.suffix), "required_evidence")
            frozen_action.parent.mkdir(parents=True, exist_ok=True)
            freeze_file(source_action_path, frozen_action)
            frozen_action_record = file_record(frozen_action, "required_evidence")
            if any(frozen_action_record[key] != action_record[key] for key in ("bytes", "sha256")):
                raise ValueError("Frozen action source differs from callable authority")
            verify_record("original action source after freeze", dict(action_record))
            verify_record("frozen action source after freeze", frozen_action_record)
            updated_request = copy.deepcopy(request)
            updated_request["prepared"]["source_entrypoint"] = dict(action_record)
            updated_request["prepared"]["entrypoint"] = frozen_action_record
            write_json_atomic(session.execution_request, updated_request)
            request = updated_request
            session.add_input("owner_authority_0", frozen_action_record)
            result = dict(action(session))
        except BaseException as failure:
            primary = failure
            try:
                inputs = _json(session.run_config)["inputs"]
                if "owner_authority_0" not in inputs:
                    request = _json(session.execution_request)
                    current_authority = dict(request["prepared"]["entrypoint"], retention_role="required_evidence")
                    verify_record("fallback action authority", current_authority)
                    session.add_input("owner_authority_0", current_authority)
            except BaseException as secondary:
                failure.add_note(f"Action authority preservation failed: {secondary!r}")
                raise
            result = dict(status="failed", summary=dict(failure_reason=str(failure)),
                          output_paths=[], required_output_paths=[], retention_preserve_paths=[], manifest_extra_fields={})
        if set(result) != {"status", "summary", "output_paths", "required_output_paths",
                           "retention_preserve_paths", "manifest_extra_fields"}:
            raise ValueError("Prepared action completion fields differ")
        if result["status"] == "success" and (set(session._completed) != set(ids)
                or any(code != 0 for code in session._completed.values())):
            raise ValueError("Successful action did not complete all declared operations")
        _writer_completion(session)
        verify_record("original action source after action", dict(action_record))
        verify_record("current action authority after action", request["prepared"]["entrypoint"])
        if primary is not None:
            failure_outputs = getattr(primary, "failure_output_paths", ())
            if not isinstance(failure_outputs, (list, tuple)):
                raise ValueError("Action failure_output_paths must be explicit file paths")
            result["output_paths"] = list(failure_outputs)
        for value in [*result["output_paths"], *result["required_output_paths"], *result["retention_preserve_paths"]]:
            path = session.canonical_path(value)
            if not path.is_relative_to(run_root) or not path.is_file():
                raise ValueError("Workflow output must be an actual file inside its run")
            session.classify_file(path)
        if set(result["manifest_extra_fields"]) & set(checkpoint):
            raise ValueError("Manifest extra fields cannot overwrite reserved fields")
        result["summary"] = dict(result["summary"], status=result["status"], run_id=run_id)
        completion = dict(schema_version=1, role="run_artifact_workflow_completion", run_id=run_id, project=project,
            execution_request=file_record(session.execution_request, "required_evidence"),
            run_config=file_record(session.run_config, "required_evidence"), writer_completion=_writer_completion(session),
            exception=None if primary is None else dict(type=type(primary).__name__, message=str(primary),
                                                       notes=getattr(primary, "__notes__", [])), **result)
        for name in ("output_paths", "required_output_paths", "retention_preserve_paths"):
            completion[name] = [str(session.canonical_path(path)) for path in completion[name]]
        completion["file_roles"] = session.file_roles
        completion["package"] = package
        write_json_atomic(run_root / "results/execution_completion.json", completion)
        _result(session, status="pending", stage="completion", writers_confirmed=True,
                resume_action="resume_finalization")
        outcome = _finalize(session, request, completion, completion_api=completion_api)
        finalized = True
        if primary is not None:
            raise primary
        return outcome
    except BaseException as failure:
        if finalized and primary is failure:
            raise
        accounting_failure = failure if isinstance(failure, CapacityAccountingDeferredError) else None
        if primary is not None and primary is not failure:
            primary.add_note(f"Workflow finalization failed: {failure!r}")
            failure = primary
        try:
            if accounting_failure is not None:
                _preserve_accounting_hold(session, completion, accounting_failure)
            else:
                _result(session, status="failed", stage="finalization" if session.writers_stopped else "writer_completion",
                writers_confirmed=session.writers_stopped, resume_action="resume_finalization" if
                    (run_root / "results/execution_completion.json").is_file() else "inspect_writer_completion",
                exception=dict(type=type(failure).__name__, message=str(failure), notes=getattr(failure, "__notes__", [])),
                capacity_session=capacity)
        except BaseException as secondary:
            failure.add_note(f"Workflow Result preservation failed: {secondary!r}")
        raise failure


def resume_finalization(context: ExecutionContext, result_path: Path, *,
                        completion_api: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Resume only persisted stopped completion; never import or invoke its action."""
    result = _json(result_path)
    if result.get("role") != "run_artifact_workflow_result" or result.get("writers_confirmed") is not True:
        raise ValueError("Finalization recovery requires confirmed stopped writers")
    root = Path(result["run_directory"])
    request_path = root / "inputs/execution_request.json"
    request = _json(request_path)
    completion = _json(root / "results/execution_completion.json")
    for name in ("execution_request", "run_config"):
        verify_record(name, completion[name])
    if request["paths"]["host_resource_state_path"] != str(context.host_state_path):
        raise ValueError("Finalization context shared host ledger differs")
    if request["paths"]["execution_root"] != str(context.execution_root):
        raise ValueError("Finalization execution root differs")
    artifact_root = Path(request["paths"]["artifact_root"])
    if artifact_root != context.workspace / "artifacts":
        raise ValueError("Finalization workspace differs")
    # Result is a recovery transport snapshot. Only the original owner's
    # current accounting document can authorize its normal finalization.
    capacity = _json(root / "logs/capacity_session.json")
    transported = result.get("capacity_session")
    if transported is not None and (not isinstance(transported, Mapping) or
            any(transported.get(name) != capacity[name] for name in ("owner", "artifact_root", "lease_id"))):
        raise ValueError("Finalization Result capacity identity differs from its original authority")
    expected_owner = f"run-artifact-workflow:{completion['project']}:{completion['run_id']}"
    if capacity["owner"] != expected_owner or capacity["artifact_root"] != str(artifact_root):
        raise ValueError("Finalization capacity owner differs")
    session = RunSession(context, artifact_root, completion["run_id"], completion["project"],
        request["package"]["mode"], completion["package"], capacity, request_path, result_path,
        tuple(request["expected_operation_ids"]), request["operation_dependencies"],
        file_roles=completion["file_roles"], operations=completion["writer_completion"]["operations"],
        resource_releases=completion["writer_completion"]["resource_releases"])
    _writer_completion(session)
    try:
        _require_capacity_accounted(session)
    except CapacityAccountingDeferredError as failure:
        _preserve_accounting_hold(session, completion, failure)
        raise
    if result.get("stage") == "complete":
        manifest_record = result.get("manifest")
        if (not isinstance(manifest_record, Mapping)
                or Path(manifest_record.get("path", "")).resolve() != root / "run_manifest.json"):
            raise ValueError("Completed finalization lacks its original manifest identity")
        lifecycle.resolve_consumed_run_capacity_owner(dict(manifest_record), consumer_artifact_root=artifact_root)
        manifest = _json(root / "run_manifest.json")
        if manifest["status"] != completion["status"] or result["status"] != completion["status"]:
            raise ValueError("Completed finalization differs from its original completion")
        # The original log remains manifest-bound. Do not rewrite it after
        # publication or renew the already released lease from its old snapshot.
        leases = [(artifact_root, capacity["lease_id"]), *(
            (Path(source["artifact_root"]), source["lease_id"]) for source in capacity["source_protection_leases"])]
        if any(capacity_protection._lease_path(owner_root, lease_id).exists() for owner_root, lease_id in leases):
            raise ValueError("Completed finalization still has an original capacity protection lease")
        ledger = capacity_ledger.load_capacity_ledger(artifact_root)
        relative = root.relative_to(artifact_root).as_posix()
        entries = [row for row in ledger["objects"] if row["path"] == relative] if ledger else []
        sealed = result.get("capacity")
        if not isinstance(sealed, Mapping):
            raise ValueError("Completed finalization lacks its capacity receipt")
        if (len(entries) != 1 or entries[0].get("status") != "ready"
                or entries[0].get("owner") != completion["project"] or "disposition" in entries[0]
                or entries[0]["bytes"] != sealed.get("bytes")
                or sealed.get("ledger_entry", {}).get("path") != relative):
            raise ValueError("Completed finalization lacks its actual sealed capacity range")
        selection = retention_policy.validate_retention(request["retention"])
        if selection.class_id != "compact" and (
                entries[0].get("class") != "rebuildable_payload" or entries[0].get("pin") is not True
                or not str(entries[0].get("retention_reason", "")).startswith(lifecycle.SEALED_PAYLOAD_REASON_PREFIX)):
            raise ValueError("Completed finalization lacks its retained stopped-payload seal")
        if selection.class_id == "compact" and entries[0].get("class") != "light_evidence":
            raise ValueError("Completed finalization lacks its compact evidence accounting")
        return result
    if capacity["status"] == "active":
        renew_capacity_session(capacity)
    return _finalize(session, request, completion, completion_api=completion_api)
