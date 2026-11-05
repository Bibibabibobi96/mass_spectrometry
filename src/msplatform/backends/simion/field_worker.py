"""One real field-member worker under the caller's existing process/capacity owner.

The canonical PA transaction owns build/verify/publication. This worker only
executes its requested native work and reports those actual child observations;
it never creates a RunSession, capacity lease, scheduler or recovery journal.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from msplatform.execution.context import ExecutionContext
from msplatform.execution.capacity_protection import load_capacity_protection_leases
from msplatform.execution.file_identity import guarded_file_identity
from msplatform.execution.manifest_records import file_record, verify_record
from msplatform.execution.processes import ProcessExecutionError, run_observed_process, inherited_host_token
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.io.file_identity import file_sha256
from . import pa_family_cache as cache
from .field_audit import audit_input_identity, reusable_audit
from .field_identity import render_audit_spec
from .native_plans import operating_member_identity, plan_operating_member
from .native_io import apply_native_io_mode


def _member_paths(run_directory: Path, cache_root: Path, log_directory: Path,
                  receipt_path: Path, producer_run_config: Path) -> tuple[Path, Path, Path, Path]:
    """Validate owned destinations before permitting any failure-receipt write."""
    paths = [Path(value) for value in (run_directory, cache_root, log_directory, receipt_path, producer_run_config)]
    if any(not value.is_absolute() for value in paths):
        raise ValueError('Member paths must be absolute and belong to the original run')
    root, cache_root, logs, receipt, config = (value.resolve() for value in paths)
    if (not root.is_dir() or not logs.is_relative_to(root/'logs')
            or not receipt.is_relative_to(root/'results') or receipt.suffix.lower() != '.json'
            or config != root/'run_config.json' or receipt.exists() or paths[3].is_symlink()):
        raise ValueError('Member paths must belong to its explicit original run; receipt must be new')
    return root, cache_root, logs, receipt


def _require_published_parent(cache_root: Path, parent: dict, member_id: str, *,
                              lease_id: str, lease_owner: str) -> None:
    """Require the same member's real published generation and original protection."""
    key = parent["cache_key"]
    transaction = cache.load_pa_family_cache_transaction(cache_root, key)
    if transaction["status"] != "published":
        raise ValueError("Fine member requires its actually published parent")
    generation = cache_root / key / "generations" / transaction["generation_sha256"]
    filename = "frontend." + member_id + ".pa"
    manifest = cache._validate_sealed_generation_metadata(generation,
        expected_cache_key=key, expected_filenames=[filename])
    cache._require_managed_pa_consumer_binding(cache_root, manifest,
        capacity_lease_id=lease_id, capacity_lease_owner=lease_owner)
    expected = next(row for row in manifest["files"] if row["name"] == filename)
    record = parent["record"]
    if (Path(record["path"]).resolve() != (generation / filename).resolve()
            or record["bytes"] != expected["bytes"] or record["sha256"] != expected["sha256"]):
        raise ValueError("Fine member parent record differs from its published generation")


def _audit_plan(field_plan: dict, domain_id: str, member_id: str, identity: dict,
                native_plan) -> dict:
    """Project audit protocol from the same checked native member plan, no formulas."""
    domain = next(row for row in field_plan["field_design"]["domains"] if row["domain_id"] == domain_id)
    point = copy.deepcopy(next(row for row in field_plan["field_design"]["working_points"]
        if (row.get("working_point_id") or row["kind"]) == member_id))
    refine, export, _audit = native_plan.operations
    labels = sorted(int(key) for key in point["electrode_voltages_v"])
    point.update(path=export["outputs"][0], filename=Path(export["outputs"][0]).name,
                 voltage_argument=refine["arguments"][-2])
    result = dict(domain_id=domain_id, identity=identity,
        boundary_policy=domain["boundary_policy"],
        grid=[domain["dimensions"]["n"+axis] for axis in "xyz"] +
             [domain["cell_mm_xyz"][axis] for axis in "xyz"],
        physical_electrode_ids=labels, physical_samples=domain["physical_samples"], working_points=[point])
    raw = Path(refine["arguments"][4])
    expected = next(iter(native_plan.materializations.values()))
    if render_audit_spec(result, raw, Path(export["outputs"][0]).parent) != expected:
        raise ValueError("Member audit projection differs from the canonical native plan")
    return result


def _native_operation(context: ExecutionContext, operation: dict, *, executable: Path,
                      run_directory: Path, directory: Path, logs: Path,
                      limits: Mapping[str, Any], observations: list[dict],
                      allow_asynchronous_io: bool | None = None) -> None:
    name = operation["operation_id"]
    stdout, stderr, usage = (logs / (name + suffix) for suffix in (".stdout.log", ".stderr.log", ".usage.json"))
    receipt = None
    primary = None
    try:
        receipt = run_observed_process(context, executable=executable,
            arguments=apply_native_io_mode([str(executable), *operation["arguments"]],
                allow_asynchronous_io=allow_asynchronous_io)[1:],
            working_directory=directory, run_directory=run_directory,
            stdout_path=stdout, stderr_path=stderr, usage_path=usage, role="SIMION",
            stage=operation["stage"], run_id=run_directory.name, limits=limits)
        release = receipt["host_release"]
        if release["inherited"] is not True or release["token"] != inherited_host_token(context, required=True):
            raise ValueError("Member child did not use its actual inherited host lease")
        if operation["success_marker"] not in stdout.read_text(encoding="utf-8-sig"):
            raise ValueError("Native member success marker is absent: " + name)
        if any(not Path(path).is_file() for path in operation["outputs"]):
            raise ValueError("Native member required output is absent: " + name)
    except BaseException as failure:
        primary = failure
        if isinstance(failure, ProcessExecutionError):
            receipt = failure.receipt
        raise
    finally:
        if receipt is not None:
            row = dict(operation_id=name, role="SIMION", stage=operation["stage"], receipt=receipt)
            observations.append(row)
            try:
                write_json_atomic(logs / (name + ".process.json"), row)
            except BaseException as secondary:
                if primary is None:
                    raise
                primary.add_note(f"Member child evidence preservation failed: {secondary!r}")


def execute_member(context: ExecutionContext, *, field_plan: dict, domain_id: str, member_id: str,
                   tool_identity: dict, raw_geometry_record: dict, resources: Mapping[str, Path],
                   cache_root: Path, producer_run_config: Path, capacity_lease_id: str,
                   capacity_lease_owner: str, run_directory: Path, log_directory: Path,
                   limits: Mapping[str, Any], receipt_path: Path,
                   published_parent: dict | None = None, producer_handoff: dict | None = None,
                   allow_asynchronous_io: bool | None = None) -> dict:
    """Advance one complete scientific member; HIT records zero native children.

    Caller must already protect the exact cache key with its original capacity
    lease and own a SIMION/pa_refine envelope. Missing geometry is never rebuilt.
    Failure retains the primary error and reports stopped-stage accounting as a
    separate fact for the original owner; this function cannot clear a hold.
    """
    run_directory, cache_root, logs, receipt_path = _member_paths(
        run_directory, cache_root, log_directory, receipt_path, producer_run_config)
    key = None
    transaction = None
    begin_attempted = False
    observations: list[dict] = []
    primary = None
    report = dict(schema_version=1, role="simion_field_member_worker", status="failed", domain_id=domain_id,
        member_id=member_id, cache_key=None, native_operations=observations, native_count=0,
        accounting_deferred=False, stopped_stage_accounting=None, preflight_completed=False,
        cache_mutation_attempted=False, cache_transaction_attempted=False)
    try:
        logs.mkdir(parents=True, exist_ok=False)
        inherited_host_token(context, required=True)
        executable = context.tools["simion"]
        native = tool_identity["simion_identity"]
        verify_record("member executable", dict(path=str(executable), exists=True,
            bytes=native["executable_bytes"], sha256=native["executable_sha256"], retention_role="required_evidence"))
        for name in ("operating_builder", "exporter"):
            if file_sha256(resources[name]) != tool_identity["builder_identity"][name]:
                raise ValueError("Member builder source identity differs: " + name)
        identity = operating_member_identity(field_plan, domain_id=domain_id, member_id=member_id,
            tool_identity=tool_identity, published_parent=published_parent)
        key = cache.canonical_pa_family_cache_key(identity)
        artifact_root = cache._artifact_root_for_cache(cache_root)
        if artifact_root is None:
            raise ValueError("Field member requires its original governed capacity root")
        if cache_root.resolve() != (artifact_root / "common/simion/pa_family_cache").resolve():
            raise ValueError("Field member cache must use the original PA manager's governed range")
        protections = load_capacity_protection_leases(artifact_root)
        if not any(row.get("status") == "active" and row.get("lease_id") == capacity_lease_id
                and row.get("owner") == capacity_lease_owner and key.lower() in row.get("protected_cache_keys", [])
                for row in protections["audit"]):
            raise ValueError("Original capacity lease does not protect this exact field member")
        if published_parent is not None:
            _require_published_parent(cache_root, published_parent, member_id,
                lease_id=capacity_lease_id, lease_owner=capacity_lease_owner)
        filename = ("frontend" if domain_id == "parent" else "frontend_entrance_refinement") + "." + member_id + ".pa"
        arguments = dict(owner=run_directory.name, producer_run_config=producer_run_config,
            recovery_policy="none", published_pin_reason="Retain standalone fields required by published field products.")
        report['cache_key'] = key
        report['key_bytes_before'] = cache._key_root_bytes(cache_root / key)
        report['preflight_completed'] = True
        # Canonical probe may update the governed HIT's last-used ledger entry.
        report['cache_mutation_attempted'] = True
        probe = cache.probe_pa_family_cache(cache_root, identity, expected_filenames=[filename])
        if probe.disposition not in {cache.CacheDisposition.HIT, cache.CacheDisposition.MISS}:
            raise cache.PAFamilyCacheError("Member cache is not reusable: " + str(probe.detail))
        if probe.disposition is cache.CacheDisposition.HIT:
            generation = probe.generation_directory
            cache.load_pa_family_cache_transaction(cache_root, key)
            manifest = json.loads((generation / "cache_manifest.json").read_text(encoding="utf-8-sig"))
            cache._require_managed_pa_consumer_binding(cache_root, manifest,
                capacity_lease_id=capacity_lease_id, capacity_lease_owner=capacity_lease_owner)
            scratch, payload = logs / "audit", generation
        else:
            begin_attempted = True
            report["cache_transaction_attempted"] = True
            transaction = cache.advance_pa_family_cache_transaction(cache_root, identity, [filename],
                **arguments, producer_handoff=producer_handoff)
            generation = transaction.generation_directory
            scratch = transaction.scratch_directory
            payload = generation if generation is not None else transaction.build_directory
            if generation is not None:
                manifest = json.loads((generation / "cache_manifest.json").read_text(encoding="utf-8-sig"))
        plan, actual_identity = plan_operating_member(field_plan, domain_id=domain_id, member_id=member_id,
            tool_identity=tool_identity, raw_geometry_record=raw_geometry_record,
            working_directory=scratch, payload_directory=payload, resource_paths=resources,
            published_parent=published_parent)
        if actual_identity != identity:
            raise ValueError("Native member identity changed after transaction selection")
        audit_plan = _audit_plan(field_plan, domain_id, member_id, identity, plan)
        audit_plan["cache_key"] = key
        audit_record = reusable_audit(audit_plan, generation, resources["verifier"]) if generation else None
        if audit_record is None:
            scratch.mkdir(parents=True, exist_ok=True)
            with ExitStack() as guards:
                for record in [raw_geometry_record, *([published_parent["record"]] if published_parent else [])]:
                    guards.enter_context(guarded_file_identity(record["path"],
                        expected_bytes=record["bytes"], expected_sha256=record["sha256"]))
                for path, text in plan.materializations.items():
                    Path(path).write_text(text, encoding="utf-8", newline="\n")
                if transaction is not None and transaction.action_required == "build":
                    for operation in plan.operations[:2]:
                        _native_operation(context, operation, executable=executable, run_directory=run_directory,
                            directory=scratch, logs=logs, limits=limits, observations=observations,
                            allow_asynchronous_io=allow_asynchronous_io)
                    transaction = cache.advance_pa_family_cache_transaction(cache_root, identity, [filename], **arguments)
                if generation:
                    member = next(row for row in manifest["files"] if row["name"] == filename)
                    guards.enter_context(guarded_file_identity(generation / filename,
                        expected_bytes=member["bytes"], expected_sha256=member["sha256"]))
                _native_operation(context, plan.operations[2], executable=executable, run_directory=run_directory,
                    directory=scratch, logs=logs, limits=limits, observations=observations,
                    allow_asynchronous_io=allow_asynchronous_io)
            audit_path = Path(plan.operations[2]["outputs"][0])
            audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
            if audit.get("status") != "pass":
                raise ValueError("Native member audit did not pass")
            audit.update(audit_input_sha256=audit_input_identity(audit_plan),
                         audit_verifier_sha256=file_sha256(resources["verifier"]))
            write_json_atomic(audit_path, audit)
            # The cache can retire transaction scratch; its verification must
            # bind the owning run's durable small audit, as the original stage did.
            durable_audit = logs / "audit.json"
            write_json_atomic(durable_audit, audit)
            audit_record = file_record(durable_audit, "required_evidence")
        if transaction is not None and transaction.action_required == "verify":
            evidence = dict(schema_version=1, role="simion_pa_family_verification", status="pass", cache_key=key,
                inventory_sha256=transaction.inventory_sha256, solver_release="SIMION 2020",
                verifier_path=str(resources["verifier"]), verifier_sha256=file_sha256(resources["verifier"]),
                verification_output_path=audit_record["path"], verification_output_sha256=audit_record["sha256"])
            transaction = cache.advance_pa_family_cache_transaction(cache_root, identity, [filename],
                **arguments, verification_evidence=evidence)
            generation = transaction.generation_directory
        if transaction is not None and transaction.action_required != "complete":
            raise ValueError("Member transaction did not complete")
        manifest = json.loads((generation / "cache_manifest.json").read_text(encoding="utf-8-sig"))
        cache._require_managed_pa_consumer_binding(cache_root, manifest,
            capacity_lease_id=capacity_lease_id, capacity_lease_owner=capacity_lease_owner)
        member = next(row for row in manifest["files"] if row["name"] == filename)
        report.update(status="success", cache_disposition=probe.disposition.value,
            generation_directory=str(generation), audit_record=audit_record,
            record=dict(path=str(generation / filename), exists=True, bytes=member["bytes"],
                sha256=member["sha256"], retention_role="solver_native_binary"))
        report['key_bytes_after'] = cache._key_root_bytes(cache_root / key)
        report['newly_accounted_cache_bytes'] = max(0, report['key_bytes_after'] - report['key_bytes_before'])
        return report
    except BaseException as failure:
        primary = failure
        report["exception"] = dict(type=type(failure).__name__, message=str(failure))
        if begin_attempted:
            try:
                original = cache.load_pa_family_cache_transaction(cache_root, key)
                # The caller's pre-advance transaction can still be building
                # when publication has landed but failed its ledger handoff.
                # Preserve the original stage's conservative accounting rule;
                # a published journal alone does not prove accounting complete.
                needs_accounting = (original["owner"] == run_directory.name and
                    (original["status"] == "building" or
                     (transaction is not None and transaction.status in {"building", "prepared"})))
                if needs_accounting:
                    accounted = cache.advance_pa_family_cache_transaction(cache_root, identity, [filename],
                        **arguments, record_stage_only=True)
                    report["stopped_stage_accounting"] = dict(status=accounted.status, cache_key=accounted.cache_key)
            except BaseException as secondary:
                report.update(accounting_deferred=True, accounting_error=str(secondary))
                failure.add_note(f"Stopped member accounting failed: {secondary!r}")
        raise
    finally:
        report["native_count"] = len(observations)
        try:
            write_json_atomic(receipt_path, report)
        except BaseException as secondary:
            if primary is None:
                raise
            primary.add_note(f"Member receipt preservation failed: {secondary!r}")


def run_member(session, *, operation_id: str, parameters: Mapping[str, Any],
               limits: Mapping[str, Any]) -> dict:
    """Launch the actual member worker once, including on cache HIT.

    The original RunSession records only this outer PID/release. Child native
    observations remain in the bound backend receipt. An absent accounting
    receipt after launch is not evidence that an external cache write completed.
    """
    if operation_id not in session.expected_operation_ids or not operation_id.replace("_", "").isalnum():
        raise ValueError("Field worker requires its declared simple operation identity")
    parameters = copy.deepcopy(dict(parameters))
    parameters["cache_root"] = str(parameters["cache_root"])
    parameters["resources"] = {name: str(path) for name, path in parameters["resources"].items()}
    forbidden = {"run_directory", "producer_run_config", "capacity_lease_id", "capacity_lease_owner",
                 "receipt_path", "log_directory", "limits"}
    if set(parameters) & forbidden:
        raise ValueError("Field worker caller cannot replace original owner paths or lease")
    receipt = session.declare_file(session.result_dir / (operation_id + ".json"), "required_evidence")
    logs = session.log_dir / operation_id
    request_path = session.declare_file(session.input_dir / (operation_id + ".json"), "required_evidence")
    parameters.update(run_directory=str(session.artifact_run_dir),
        producer_run_config=str(session.run_config), capacity_lease_id=session.capacity_session["lease_id"],
        capacity_lease_owner=session.capacity_session["owner"], receipt_path=str(session.canonical_path(receipt)),
        log_directory=str(session.canonical_path(logs)), limits=dict(limits))
    context = {name: str(getattr(session.context, name)) for name in (
        "workspace", "python_executable", "powershell_executable", "host_state_path", "policy_path", "execution_root")}
    context["tools"] = {name: str(path) for name, path in session.context.tools.items()}
    write_json_atomic(request_path, dict(schema_version=1, context=context, parameters=parameters))
    request_record = file_record(session.canonical_path(request_path), "required_evidence")
    session.add_input(operation_id + "_request", request_record)
    primary = None
    try:
        session.run_process(operation_id, executable=session.context.python_executable,
            arguments=["-I", "-B", "-X", "utf8", "-m", __name__, str(request_path)],
            role="SIMION", stage="pa_refine", limits=limits)
    except BaseException as failure:
        primary = failure
        raise
    finally:
        try:
            for path in session.canonical_path(logs).rglob("*"):
                if path.is_file():
                    session.declare_file(path, "required_evidence")
            report = json.loads(Path(receipt).read_text(encoding="utf-8-sig"))
            if report.get("request") != request_record:
                raise ValueError("Field member receipt is not bound to the frozen worker request")
            if report.get("accounting_deferred") is True:
                session.defer_capacity_finalization(report["accounting_error"])
        except BaseException as secondary:
            try:
                session.defer_capacity_finalization("Member accounting receipt is unavailable: " + str(secondary))
            except BaseException as preservation:
                secondary.add_note(f"Original accounting hold preservation failed: {preservation!r}")
            if primary is None:
                raise
            primary.add_note(f"Member accounting receipt failed: {secondary!r}")
    if report.get("status") != "success":
        raise ValueError("Field member worker returned no successful result")
    return report


def main() -> None:
    """Private installed -m transport; scientific requests are frozen by the owner."""
    if len(sys.argv) != 2:
        raise ValueError("Field member requires exactly one frozen request path")
    request_path = Path(sys.argv[1]).resolve(strict=True)
    with guarded_file_identity(request_path) as identity:
        request = json.loads(request_path.read_text(encoding="utf-8-sig"))
        if set(request) != {"schema_version", "context", "parameters"} or request["schema_version"] != 1:
            raise ValueError("Field worker request fields differ")
        context = ExecutionContext(**request["context"])
        parameters = request["parameters"]
        for name in ("cache_root", "producer_run_config", "run_directory", "log_directory", "receipt_path"):
            parameters[name] = Path(parameters[name])
        parameters["resources"] = {name: Path(path) for name, path in parameters["resources"].items()}
        # Do not bind/write a receipt after rejecting an unsafe destination.
        _member_paths(parameters['run_directory'], parameters['cache_root'], parameters['log_directory'],
                      parameters['receipt_path'], parameters['producer_run_config'])
        primary = None
        try:
            execute_member(context, **parameters)
        except BaseException as failure:
            primary = failure
            raise
        finally:
            try:
                receipt = parameters["receipt_path"]
                report = json.loads(receipt.read_text(encoding="utf-8-sig"))
                report["request"] = dict(path=str(request_path), exists=True, bytes=identity.bytes_count,
                    sha256=identity.sha256, retention_role="required_evidence")
                write_json_atomic(receipt, report)
            except BaseException as secondary:
                if primary is None:
                    raise
                primary.add_note(f"Worker request binding preservation failed: {secondary!r}")


if __name__ == "__main__":
    main()
