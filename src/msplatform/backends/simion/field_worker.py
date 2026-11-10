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
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.processes import ProcessExecutionError, run_observed_process, inherited_host_token
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.io.file_identity import file_sha256
from . import pa_family_cache as cache
from .field_audit import audit_input_identity, reusable_audit
from .field_identity import render_audit_spec, working_point_member_id, _member_projection
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




def _selected_cache_probe(cache_root, identity, filename, selection):
    """Revalidate one actual manager selection; never discover another generation."""
    if selection is None:
        return cache.probe_pa_family_cache(cache_root, identity, expected_filenames=[filename])
    key = cache.canonical_pa_family_cache_key(identity)
    probe = selection["probe"]
    if probe.get("cache_key") != key or probe.get("disposition") not in {"hit", "miss"}:
        raise ValueError("selected field cache result differs from its actual identity")
    expected = dict(pointer=Path(cache_root) / key / cache.POINTER_NAME,
                    transaction=Path(cache_root) / cache.TRANSACTION_DIRECTORY / key / cache.TRANSACTION_NAME)
    if probe["disposition"] == "hit":
        generation = Path(probe["generation_directory"])
        if (generation.parent.name != "generations" or generation.parent.parent != Path(cache_root) / key):
            raise ValueError("selected cache generation escapes the actual member key")
        expected["generation"] = generation / cache.MANIFEST_NAME
    else:
        generation = None
    if set(selection["metadata"]) != set(expected):
        raise ValueError("selected field cache metadata closure differs")
    for name, path in expected.items():
        record = selection["metadata"][name]
        if Path(record["path"]).resolve() != path.resolve():
            raise ValueError("selected cache metadata is not the actual manager path")
        if record.get("exists") is True:
            try:
                verify_record("selected cache " + name, record)
            except (AssertionError, OSError, ValueError) as failure:
                raise ValueError("cache generation changed after selection; original owner must replan") from failure
        elif path.exists():
            raise ValueError("cache generation changed after selection; original owner must replan")
    if generation is not None:
        pointer = json.loads(expected["pointer"].read_text(encoding="utf-8-sig"))
        manifest = cache._validate_sealed_generation_metadata(generation,
            expected_cache_key=key, expected_filenames=[filename])
        if pointer != dict(cache_key=key, generation_sha256=generation.name) or manifest["identity"] != identity:
            raise ValueError("cache generation changed after selection; original owner must replan")
    elif expected["pointer"].exists():
        transaction = cache.load_pa_family_cache_transaction(cache_root, key)
        if transaction["status"] != "retired":
            raise ValueError("selected cache miss does not match actual manager metadata")
    return cache.CacheProbe(cache.CacheDisposition(probe["disposition"]), key, generation, probe.get("detail"))


def _require_frozen_parent(parent, member_id, source, session):
    """Consume only the selected legacy inventory under this original session."""
    from msplatform.execution.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
    if (source.get("source_schema_version") not in (2, 3)
            or source.get("cache_key") != parent.get("cache_key")
            or working_point_member_id(parent["record"]) != member_id):
        raise ValueError("frozen parent must bind its selected schema2/3 member")
    producer_record = source["producer_manifest_record"]
    verify_record("selected parent producer manifest", producer_record)
    original_record = dict(producer_record, path=producer_record.get("source_path", producer_record["path"]))
    owner = resolve_consumed_run_capacity_owner(original_record,
        consumer_artifact_root=Path(session["artifact_root"]))
    producer = Path(owner["run_directory"]).resolve()
    manifest = json.loads(Path(producer_record["path"]).read_text(encoding="utf-8-sig"))
    identity_record = file_record(Path(source["identity_path"]), "required_evidence")
    if not any(row.get("bytes") == identity_record["bytes"] and
               str(row.get("sha256", "")).upper() == identity_record["sha256"]
               for row in [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]):
        raise ValueError("frozen parent identity is not bound by its selected producer")
    generation = Path(source["generation_directory"]).resolve()
    source_cache = generation.parents[2]
    sealed = cache.validate_pa_family_cache_generation(generation,
        expected_cache_key=source["cache_key"], expected_filenames=source["cache_filenames"], verify_payload=False)
    if sealed["identity"] != source["identity"]:
        raise ValueError("frozen parent producer inventory identity differs")
    filename = Path(parent["record"]["path"]).name
    matches = [row for row in sealed["files"] if row["name"] == filename]
    if (len(matches) != 1 or Path(parent["record"]["path"]).resolve() != generation / filename
            or matches[0]["bytes"] != parent["record"]["bytes"]
            or matches[0]["sha256"].upper() != parent["record"]["sha256"].upper()):
        raise ValueError("frozen parent member differs from the actual selected inventory")
    roots = [(Path(session["artifact_root"]), session["lease_id"])]
    roots.extend((Path(row["artifact_root"]), row["lease_id"])
                 for row in session.get("source_protection_leases", []) if row.get("status") == "active")
    protected_producer, protected_key = False, False
    for root, lease_id in roots:
        leases = load_capacity_protection_leases(root)
        for lease in leases["audit"]:
            if (lease.get("status") != "active" or lease.get("lease_id") != lease_id
                    or lease.get("owner") != session["owner"]):
                continue
            protected_producer |= any(producer.is_relative_to((root / name).resolve())
                                      for name in lease.get("protected_paths", []))
            if cache._artifact_root_for_cache(source_cache) == root.resolve():
                protected_key |= source["cache_key"].lower() in lease.get("protected_cache_keys", [])
    if not protected_producer or not protected_key:
        raise ValueError("selected frozen parent lacks its original-session source protection binding")


def _materialize_member_geometry(context, *, gem_record, raw_path, domain_id, run_directory,
                                 logs, limits, observations, allow_asynchronous_io=None,
                                 native_path_projection=None):
    """Materialize only an explicitly frozen GEM into its declared owned raw path."""
    from msplatform.execution.inputs import freeze_file
    raw_path, run_directory = Path(raw_path), Path(run_directory).resolve()
    if (not raw_path.is_absolute() or not raw_path.resolve().is_relative_to(run_directory / "simion")
            or raw_path.exists() or not str(raw_path).lower().endswith(".pa#")
            or not Path(gem_record["path"]).resolve().is_relative_to(run_directory / "inputs")):
        raise ValueError("explicit GEM materialization escapes original-run ownership or replaces an existing raw file")
    verify_record("frozen member GEM", gem_record)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    private_gem = raw_path.with_suffix(".gem")
    freeze_file(Path(gem_record["path"]), private_gem)
    with guarded_file_identity(private_gem, expected_bytes=gem_record["bytes"], expected_sha256=gem_record["sha256"]):
        _native_operation(context, dict(operation_id="gem2pa_" + domain_id, stage="prepare",
            arguments=["--nogui", "--noprompt", "gem2pa", str(private_gem), str(raw_path)],
            outputs=[str(raw_path)], success_marker=""), executable=context.tools["simion"],
            run_directory=run_directory, directory=raw_path.parent, logs=logs, limits=limits,
            observations=observations, allow_asynchronous_io=allow_asynchronous_io,
            native_path_projection=native_path_projection)
    actual = file_record(raw_path, "solver_native_binary")
    if actual.get("exists") is not True or actual.get("bytes", 0) <= 0:
        raise ValueError("GEM2PA did not produce actual nonempty raw geometry")
    return actual


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
                      allow_asynchronous_io: bool | None = None,
                      native_path_projection: dict | None = None) -> None:
    name = operation["operation_id"]
    stdout, stderr, usage = (logs / (name + suffix) for suffix in (".stdout.log", ".stderr.log", ".usage.json"))
    receipt = None
    primary = None
    try:
        arguments = operation["arguments"]
        environment = None
        if native_path_projection is not None:
            from msplatform.execution.run_paths import project_run_path
            persistent, execution = (native_path_projection[key] for key in ("artifact_run_dir", "run_dir"))
            arguments = [project_run_path(value, persistent, execution) for value in arguments]
            directory = Path(project_run_path(directory, persistent, execution))
            environment = dict(MASS_SPECTROMETRY_RUN_DIRECTORY=persistent,
                               MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=execution)
        receipt = run_observed_process(context, executable=executable,
            arguments=apply_native_io_mode([str(executable), *arguments],
                allow_asynchronous_io=allow_asynchronous_io)[1:],
            working_directory=directory, run_directory=run_directory,
            stdout_path=stdout, stderr_path=stderr, usage_path=usage, role="SIMION",
            stage=operation["stage"], run_id=run_directory.name, limits=limits,
            **({"environment": environment} if environment is not None else {}))
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
                   tool_identity: dict, raw_geometry_record: dict | None, resources: Mapping[str, Path],
                   cache_root: Path, producer_run_config: Path, capacity_lease_id: str,
                   capacity_lease_owner: str, run_directory: Path, log_directory: Path,
                   limits: Mapping[str, Any], receipt_path: Path,
                   published_parent: dict | None = None, producer_handoff: dict | None = None,
                   allow_asynchronous_io: bool | None = None,
                   gem_geometry_record: dict | None = None, raw_geometry_path: Path | None = None,
                   capacity_session: dict | None = None, reserved_run_payload_bytes: int | None = None,
                   native_path_projection: dict | None = None,
                   published_parent_source: dict | None = None,
                   cache_selection: dict | None = None,
                   frozen_field_source: dict | None = None, source_audit_record: dict | None = None,
                   published_pin_reason: str | None = None) -> dict:
    """Advance one complete scientific member; HIT records zero native children.

    Caller must already protect the exact cache key with its original capacity
    lease and own a SIMION/pa_refine envelope. Missing record-based geometry is
    never rebuilt. An explicit frozen GEM alternative may materialize its owned
    future raw path only after the same cache/audit decision needs native work.
    Failure retains the primary error and reports stopped-stage accounting as a
    separate fact for the original owner; this function cannot clear a hold.
    """
    run_directory, cache_root, logs, receipt_path = _member_paths(
        run_directory, cache_root, log_directory, receipt_path, producer_run_config)
    lazy_geometry = raw_geometry_record is None
    raw_path = None
    domain = next((row for row in field_plan.get("field_design", {}).get("domains", [])
                   if row.get("domain_id") == domain_id), None)

    def native_path(value):
        if native_path_projection is None:
            return Path(value)
        from msplatform.execution.run_paths import project_run_path
        return Path(project_run_path(value, native_path_projection["artifact_run_dir"], native_path_projection["run_dir"]))

    def reserve_geometry_bytes(factor):
        if not lazy_geometry:
            return
        from msplatform.execution.capacity_session import renew_capacity_session
        floor = reserved_run_payload_bytes
        for axis in "xyz":
            factor *= domain["dimensions"]["n" + axis]
        floor += factor
        if capacity_session["committed_new_bytes"] < floor:
            renew_capacity_session(capacity_session, remaining_committed_new_bytes=floor)

    key = None
    transaction = None
    begin_attempted = False
    build_entered = False
    publication_attempted = False
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
        if native_path_projection is not None:
            if (set(native_path_projection) != {"artifact_run_dir", "run_dir"}
                    or any(not Path(value).is_absolute() for value in native_path_projection.values())
                    or any(Path(value).resolve() != run_directory for value in native_path_projection.values())):
                raise ValueError("native projection must belong to the same original run")
        if lazy_geometry:
            if (gem_geometry_record is None or raw_geometry_path is None or domain is None
                    or capacity_session is None or type(reserved_run_payload_bytes) is not int
                    or reserved_run_payload_bytes < 0):
                raise ValueError("future raw path requires frozen GEM and original capacity authority")
            raw_path = Path(raw_geometry_path)
            gem_path = Path(gem_geometry_record["path"])
            if (not raw_path.is_absolute() or not raw_path.resolve().is_relative_to(run_directory / "simion")
                    or not str(raw_path).lower().endswith(".pa#") or raw_path.exists()
                    or not gem_path.resolve().is_relative_to(run_directory / "inputs")
                    or gem_path.suffix.lower() != ".gem"):
                raise ValueError("future raw and frozen GEM must have their declared original-run ownership")
            if (capacity_session.get("lease_id") != capacity_lease_id
                    or capacity_session.get("owner") != capacity_lease_owner
                    or Path(capacity_session["artifact_root"]).resolve() != cache._artifact_root_for_cache(cache_root)):
                raise ValueError("future raw requires the original governed capacity session")
            verify_record("frozen member GEM", gem_geometry_record)
            if gem_geometry_record["sha256"].upper() != domain["gem_sha256"].upper():
                raise ValueError("frozen member GEM differs from the field design")
        elif gem_geometry_record is not None or raw_geometry_path is not None:
            raise ValueError("actual raw record cannot be combined with a future GEM request")
        identity = operating_member_identity(field_plan, domain_id=domain_id, member_id=member_id,
            tool_identity=tool_identity, published_parent=published_parent)
        key = (frozen_field_source["cache_key"] if frozen_field_source else
               cache.canonical_pa_family_cache_key(identity))
        artifact_root = cache._artifact_root_for_cache(cache_root)
        if artifact_root is None:
            raise ValueError("Field member requires its original governed capacity root")
        if cache_root.resolve() != (artifact_root / "common/simion/pa_family_cache").resolve():
            raise ValueError("Field member cache must use the original PA manager's governed range")
        protections = load_capacity_protection_leases(artifact_root)
        if frozen_field_source is None and not any(row.get("status") == "active" and row.get("lease_id") == capacity_lease_id
                and row.get("owner") == capacity_lease_owner and key.lower() in row.get("protected_cache_keys", [])
                for row in protections["audit"]):
            raise ValueError("Original capacity lease does not protect this exact field member")
        if published_parent is not None:
            if published_parent_source is None:
                _require_published_parent(cache_root, published_parent, member_id,
                    lease_id=capacity_lease_id, lease_owner=capacity_lease_owner)
            else:
                if capacity_session is None:
                    raise ValueError("frozen parent requires its original capacity session")
                _require_frozen_parent(published_parent, member_id, published_parent_source, capacity_session)
        filename = ("frontend" if domain_id == "parent" else "frontend_entrance_refinement") + "." + member_id + ".pa"
        if published_pin_reason is not None and (not isinstance(published_pin_reason, str) or not published_pin_reason.strip()):
            raise ValueError("Explicit published field pin reason must be nonempty")
        arguments = dict(owner=run_directory.name, producer_run_config=producer_run_config,
            recovery_policy="none", published_pin_reason=(published_pin_reason if published_pin_reason is not None else
                "Retain standalone fields required by published field products."))
        report['cache_key'] = key
        report['key_bytes_before'] = cache._key_root_bytes(cache_root / key)
        report['preflight_completed'] = True
        if frozen_field_source is not None:
            if capacity_session is None:
                raise ValueError("frozen member requires its original capacity session")
            projected = (frozen_field_source["identity"] if frozen_field_source["source_schema_version"] == 3 else
                _member_projection(frozen_field_source["identity"], frozen_field_source["physical_point"], member_id=member_id))
            if projected != identity:
                raise ValueError("selected frozen field source physical identity differs")
            _require_frozen_parent(dict(cache_key=key, record=frozen_field_source["record"]),
                member_id, frozen_field_source, capacity_session)
            generation = Path(frozen_field_source["generation_directory"])
            manifest = json.loads((generation / "cache_manifest.json").read_text(encoding="utf-8-sig"))
            scratch, payload = logs / "audit", generation
            probe = None
        else:
            # Canonical probe may update the governed HIT's last-used ledger entry.
            report['cache_mutation_attempted'] = True
            probe = _selected_cache_probe(cache_root, identity, filename, cache_selection)
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
                reserve_geometry_bytes(24)
                begin_attempted = True
                report["cache_transaction_attempted"] = True
                transaction = cache.advance_pa_family_cache_transaction(cache_root, identity, [filename],
                    **arguments, producer_handoff=producer_handoff)
                build_entered = transaction.action_required == "build"
                generation = transaction.generation_directory
                scratch = transaction.scratch_directory
                payload = generation if generation is not None else transaction.build_directory
                if generation is not None:
                    manifest = json.loads((generation / "cache_manifest.json").read_text(encoding="utf-8-sig"))
        projected_record = (None if raw_geometry_record is None else
                            dict(raw_geometry_record, path=str(native_path(raw_geometry_record["path"]))))
        plan_parent = None if published_parent is None else dict(published_parent,
            record=dict(published_parent["record"], path=str(native_path(published_parent["record"]["path"]))))
        plan, actual_identity = plan_operating_member(field_plan, domain_id=domain_id, member_id=member_id,
            tool_identity=tool_identity, raw_geometry_record=projected_record,
            **({"raw_geometry_path": native_path(raw_path)} if lazy_geometry else {}),
            working_directory=native_path(scratch), payload_directory=native_path(payload),
            resource_paths={key: native_path(value) for key, value in resources.items()},
            published_parent=plan_parent)
        if actual_identity != identity:
            raise ValueError("Native member identity changed after transaction selection")
        audit_plan = _audit_plan(field_plan, domain_id, member_id, identity, plan)
        audit_plan["cache_key"] = key
        if frozen_field_source is not None:
            audit_plan["frozen_field_source"] = frozen_field_source
        audit_record = reusable_audit(audit_plan, generation, resources["verifier"]) if generation else None
        if frozen_field_source is not None and audit_record != source_audit_record:
            raise ValueError("source field audit changed after selection; original owner must replan")
        if cache_selection is not None:
            verifier = cache_selection["verifier_record"]
            if Path(verifier["path"]).resolve() != Path(resources["verifier"]).resolve():
                raise ValueError("selected audit verifier has another resource origin")
            verify_record("selected audit verifier", verifier)
            if cache_selection["probe"]["disposition"] == "hit" and audit_record != cache_selection["audit_record"]:
                raise ValueError("field audit changed after selection; original owner must replan")
        if audit_record is None:
            if lazy_geometry:
                reserve_geometry_bytes(8)
                raw_geometry_record = _materialize_member_geometry(context, gem_record=gem_geometry_record,
                    raw_path=raw_path, domain_id=domain_id, run_directory=run_directory, logs=logs,
                    limits=limits, observations=observations, allow_asynchronous_io=allow_asynchronous_io,
                    native_path_projection=native_path_projection)
                report["raw_geometry_record"] = raw_geometry_record
            scratch.mkdir(parents=True, exist_ok=True)
            with ExitStack() as guards:
                for record in [raw_geometry_record, *([published_parent["record"]] if published_parent else [])]:
                    guards.enter_context(guarded_file_identity(record["path"],
                        expected_bytes=record["bytes"], expected_sha256=record["sha256"]))
                for path, text in plan.materializations.items():
                    Path(path).write_text(text, encoding="utf-8", newline="\n")
                if transaction is not None and transaction.action_required == "build":
                    _native_operation(context, plan.operations[0], executable=executable, run_directory=run_directory,
                        directory=scratch, logs=logs, limits=limits, observations=observations,
                        allow_asynchronous_io=allow_asynchronous_io, native_path_projection=native_path_projection)
                    # Only a closed successful export may become a transaction
                    # payload member. Failed partial bytes stay in build scratch.
                    export = copy.deepcopy(plan.operations[1])
                    destination = Path(export["outputs"][0])
                    exported = scratch / destination.name
                    if exported.exists():
                        exported.unlink()
                    export["arguments"][-1] = str(native_path(exported))
                    export["outputs"] = [str(exported)]
                    _native_operation(context, export, executable=executable, run_directory=run_directory,
                        directory=scratch, logs=logs, limits=limits, observations=observations,
                        allow_asynchronous_io=allow_asynchronous_io, native_path_projection=native_path_projection)
                    exported.replace(destination)
                    transaction = cache.advance_pa_family_cache_transaction(cache_root, identity, [filename], **arguments)
                if generation:
                    member = next(row for row in manifest["files"] if row["name"] == filename)
                    guards.enter_context(guarded_file_identity(generation / filename,
                        expected_bytes=member["bytes"], expected_sha256=member["sha256"]))
                _native_operation(context, plan.operations[2], executable=executable, run_directory=run_directory,
                    directory=scratch, logs=logs, limits=limits, observations=observations,
                    allow_asynchronous_io=allow_asynchronous_io,
                    native_path_projection=native_path_projection)
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
            publication_attempted = True
            transaction = cache.advance_pa_family_cache_transaction(cache_root, identity, [filename],
                **arguments, verification_evidence=evidence)
            generation = transaction.generation_directory
        if transaction is not None and transaction.action_required != "complete":
            raise ValueError("Member transaction did not complete")
        manifest = json.loads((generation / "cache_manifest.json").read_text(encoding="utf-8-sig"))
        if frozen_field_source is None:
            cache._require_managed_pa_consumer_binding(cache_root, manifest,
                capacity_lease_id=capacity_lease_id, capacity_lease_owner=capacity_lease_owner)
        member = next(row for row in manifest["files"] if row["name"] == filename)
        report.update(status="success", cache_disposition=probe.disposition.value if probe else "explicit_source",
            generation_directory=str(generation), audit_record=audit_record,
            record=dict(path=str(generation / filename), exists=True, bytes=member["bytes"],
                sha256=member["sha256"], retention_role="solver_native_binary"))
        report['key_bytes_after'] = cache._key_root_bytes(cache_root / key)
        report['newly_accounted_cache_bytes'] = (max(0, report['key_bytes_after'] - report['key_bytes_before'])
                                                  if frozen_field_source is None else 0)
        return report
    except BaseException as failure:
        primary = failure
        report["exception"] = dict(type=type(failure).__name__, message=str(failure))
        if begin_attempted:
            try:
                original = cache.load_pa_family_cache_transaction(cache_root, key)
                # Audit-only entry to an already sealed inventory creates no
                # cache payload. A fresh build or publication attempt still
                # requires conservative accounting, even if its journal moved
                # ahead before a failed ledger handoff.
                needs_accounting = (original["owner"] == run_directory.name and
                    (build_entered or publication_attempted or
                     (transaction is None and original["status"] == "building")))
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
        if capacity_session is not None:
            report["capacity_session"] = capacity_session
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
        if (not {"schema_version", "context", "parameters"} <= set(request)
                or set(request) - {"schema_version", "context", "parameters", "implementation_records"}
                or request["schema_version"] != 1):
            raise ValueError("Field worker request fields differ")
        if "implementation_records" in request:
            from msplatform.backends.simion import native_plans
            modules = dict(worker=Path(__file__), native_plans=Path(native_plans.__file__))
            if set(request["implementation_records"]) != set(modules):
                raise ValueError("Field worker frozen implementation closure differs")
            for name, module_path in modules.items():
                expected = request["implementation_records"][name]
                if Path(expected["path"]).resolve() != module_path.resolve():
                    raise ValueError("Field worker is not the selected frozen implementation")
                verify_record("frozen field " + name, expected)
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
