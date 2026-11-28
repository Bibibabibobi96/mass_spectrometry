"""Compose standalone IP science with the existing managed Store lifecycle."""
from __future__ import annotations

from contextlib import ExitStack
from functools import partial
import json
from pathlib import Path
from typing import Any, Mapping

from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import (
    recover_managed_native_store_stage,
    run_managed_stage,
    standalone_native_store,
)
from msplatform.execution.retention import classify_file
from msplatform.execution.run_session import RunSession
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import (
    file_record,
    record_path,
    require_completed_terminal_publication,
)

MODE = "native_electrode_functional"
OPERATION_ID = "native_functional"


def _completion_policy():
    from msplatform.backends.simion import native_completion
    return native_completion


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"IP JSON input must be an object: {path}")
    return value


def _runtime_profile(project: Path) -> tuple[Path, dict[str, Any]]:
    path = project / "config/runtime_profiles.json"
    registry = _read(path)
    if (registry.get("schema_version") != 1
            or registry.get("role") != "ion_processor_runtime_profiles"
            or registry.get("project_id") != "ion_processor"):
        raise ValueError("Runtime profile identity differs")
    matches = [row for row in registry.get("profiles", [])
               if row.get("profile_id") == "native_functional"]
    if len(matches) != 1:
        raise ValueError("Exactly one native_functional runtime profile is required")
    profile = matches[0]
    if type(profile.get("retain_batch_trajectories")) is not bool:
        raise ValueError("Runtime profile retain_batch_trajectories must be boolean")
    memory = profile.get("native_field_query_memory_bytes")
    if type(memory) is not int or memory <= 0:
        raise ValueError("Native query memory declaration must be positive integer bytes")
    budget = profile.get("committed_new_bytes")
    if type(budget) is not int or budget <= 0:
        raise ValueError("Native Store reservation must be positive integer bytes")
    return path, profile


def _guard_terminal_manifest(stack: ExitStack, manifest: Path) -> dict[str, Any]:
    record = file_record(manifest.resolve(strict=True), "required_evidence")
    stack.enter_context(guarded_file_identity(
        manifest, expected_bytes=record["bytes"], expected_sha256=record["sha256"]))
    require_completed_terminal_publication(manifest)
    document = _read(manifest)
    if (document.get("project") != "ion_processor" or document.get("mode") != MODE
            or document.get("run_id") != manifest.parent.name
            or document.get("status") not in {"success", "failed"}):
        raise ValueError("IP source must be an explicit terminal native functional run")
    return record


def _guard_injected_source(stack: ExitStack, source: Path) -> list[dict[str, Any]]:
    source = source.resolve(strict=True)
    contract = _read(source)
    selected = {"contract": (source, None)}
    for name in ("clock_authority", "source_states", "mother_census", "mother_fates",
                 "producer_manifest", "preparation_manifest", "preparation_source"):
        value = contract.get(name)
        if value is not None:
            selected[name] = (record_path(value, base_dir=source.parent), value)
    records = []
    for name, (path, expected) in selected.items():
        record = dict(expected) if expected is not None else file_record(path, "required_evidence")
        record["path"] = str(path.resolve())
        stack.enter_context(guarded_file_identity(path, expected_bytes=record["bytes"],
                                                  expected_sha256=record["sha256"]))
        if name in {"producer_manifest", "preparation_manifest"}:
            require_completed_terminal_publication(path)
        records.append(dict(record, retention_role="required_evidence"))
    return records


def _source_records(stack: ExitStack, *, native_field_run: Path | None,
                    continuation_manifest: Path | None,
                    injected_source: Path | None) -> list[dict[str, Any]]:
    records = []
    if injected_source is not None:
        records.extend(_guard_injected_source(stack, injected_source))
    if native_field_run is not None:
        records.append(_guard_terminal_manifest(
            stack, native_field_run.resolve(strict=True) / "run_manifest.json"))
    if continuation_manifest is not None:
        manifest = continuation_manifest.resolve(strict=True)
        if manifest.name != "run_manifest.json":
            raise ValueError("Continuation requires an explicit predecessor manifest")
        from msplatform.results.ip_continuation import continuation_protection_paths
        for predecessor in continuation_protection_paths(manifest.parent):
            records.append(_guard_terminal_manifest(
                stack, predecessor / "run_manifest.json"))
    return records


def _declare_payload(session: RunSession) -> list[Path]:
    for path in session.artifact_run_dir.rglob("*"):
        if path.is_file() and path.name != "run_manifest.json" and str(path) not in session.file_roles:
            session.declare_file(path, classify_file(path))
    config = _read(session.run_config)
    for value in config.get("inputs", {}).values():
        if isinstance(value, str):
            path = Path(value)
            if not path.is_absolute():
                path = session.artifact_run_dir / path
            if path.is_file() and str(path) not in session.file_roles:
                session.declare_file(path, classify_file(path))
    inputs = {record_path(record, base_dir=session.artifact_run_dir)
              for record in config.get("inputs", {}).values()
              if isinstance(record, Mapping) and "path" in record}
    inputs.update(Path(value).resolve() if Path(value).is_absolute()
                  else (session.artifact_run_dir / value).resolve()
                  for value in config.get("inputs", {}).values() if isinstance(value, str))
    return [path for path in session.artifact_run_dir.rglob("*")
            if path.is_file() and path.name not in {"run_config.json", "run_manifest.json"}
            and path.resolve() not in inputs]


def _execute(session: RunSession, *, request: Mapping[str, Any],
             profile: Mapping[str, Any], launcher_record: Mapping[str, Any]) -> dict[str, Any]:
    try:
        frozen_budget = freeze_file(Path(profile["source_path"]),
            session.input_dir / "runtime_profiles.json", retention_role="required_evidence")
        session.add_input("runtime_profiles", frozen_budget)
        frozen_launcher = freeze_file(Path(launcher_record["path"]),
            session.input_dir / "native_functional.ps1", retention_role="required_evidence")
        if any(frozen_launcher[name] != launcher_record[name] for name in ("bytes", "sha256")):
            raise ValueError("Frozen IP native launcher differs from its admitted source")
        session.add_input("native_launcher", frozen_launcher)
        arguments = [
            "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(launcher_record["path"]),
            "-RunId", session.run_id, "-PythonExe", str(session.context.python_executable),
            "-SimionExe", str(session.context.tools["simion"]),
            "-SourceProfile", str(request["source_profile"]),
            "-ResourceProfileRunsRoot", str(request["resource_profile_runs_root"]),
        ]
        options = (
            ("configuration_directory", "-ConfigurationDirectory"),
            ("native_field_run", "-NativeFieldRun"),
            ("continuation_manifest", "-ContinuationPredecessorManifestPath"),
            ("injected_source", "-InjectedSource"),
        )
        for name, option in options:
            if request.get(name) is not None:
                arguments.extend((option, str(request[name])))
        receipt = session.run_process(OPERATION_ID,
            executable=session.context.powershell_executable, arguments=arguments,
            role="SIMION", stage="workflow", limits=profile["limits"],
            immutable_input_records=(frozen_budget, launcher_record, frozen_launcher))
        if receipt["observation"]["exit_code"] != 0:
            raise RuntimeError("Standalone IP native workflow failed; see its frozen summary and logs")
        summary_path = session.artifact_run_dir / "summary.json"
        summary = _read(summary_path)
        if summary.get("role") != "ion_processor_functional_summary":
            raise ValueError("Missing physical summary")
        outputs = _declare_payload(session)
        return dict(status="success", summary=summary,
            output_paths=outputs, required_output_paths=[summary_path],
            retention_preserve_paths=[], manifest_extra_fields={})
    except BaseException as failure:
        try:
            failure.failure_output_paths = _declare_payload(session)
        except BaseException as secondary:
            failure.add_note(f"IP failure evidence selection failed: {secondary!r}")
        raise


def _annotate_failure(failure: BaseException, scope: Mapping[str, Any] | None) -> None:
    if scope is None:
        return
    failure.add_note("IP Store run_id: " + str(scope["parent_run_id"]))
    for asset_id in scope["produced"]:
        failure.add_note("IP native stage asset_id: " + str(asset_id))


def run_native_functional(*, context: ExecutionContext, artifact_store: Any,
        run_id: str, source_profile: str = "functional",
        configuration_directory: Path | None = None, native_field_run: Path | None = None,
        continuation_manifest: Path | None = None, injected_source: Path | None = None) -> dict[str, Any]:
    """Run the unchanged standalone IP science under an explicit ArtifactStore."""
    if source_profile not in {"functional", "exploration"}:
        raise ValueError("source_profile must be functional or exploration")
    if native_field_run is not None and continuation_manifest is not None:
        raise ValueError("Completed-population continuation obtains its field from its predecessor")
    simion = context.tools.get("simion")
    if simion is None or not simion.is_file() or simion.name.lower() != "simion.exe":
        raise ValueError("Standalone IP requires the explicit available SIMION 2020 executable")
    from importlib.resources import files
    project = Path(str(files("msplatform.components.ion_processor"))).resolve(strict=True)
    budget_path, profile = _runtime_profile(project)
    configuration = (configuration_directory or project / "config").resolve(strict=True)
    committed = profile["committed_new_bytes"]
    if native_field_run is not None:
        source_name = "source_exploration.json" if source_profile == "exploration" else "source.json"
        count = _read(configuration / source_name)["particle_count"]
        if type(count) is not int or count < 0:
            raise ValueError("IP source particle_count must be a nonnegative integer")
        committed = max(2 * 1024**3, count * 50 * 1024**2 + 256 * 1024**2)
    request = dict(source_profile=source_profile, configuration_directory=configuration,
        native_field_run=native_field_run, continuation_manifest=continuation_manifest,
        injected_source=injected_source,
        resource_profile_runs_root=context.workspace / "artifacts/components/ion_processor/runs")
    launcher = Path(str(files("msplatform.workflows"))) / "resources/ip_functional.ps1"
    launcher_record = file_record(launcher.resolve(strict=True), "required_evidence")
    with ExitStack() as guards:
        sources = _source_records(guards, native_field_run=native_field_run,
                                  continuation_manifest=continuation_manifest,
                                  injected_source=injected_source)
        budget_record = file_record(budget_path, "required_evidence")
        scope = None
        try:
            with standalone_native_store(artifact_store, task_key="ion-processor:" + run_id,
                                         budget=committed) as scope:
                try:
                    result = run_managed_stage(context, artifact_store=artifact_store,
                        descriptor=dict(project="ion_processor", mode=MODE,
                                        software=["SIMION 2020", "Python 3.11"]),
                        run_id=run_id,
                        payload=dict(workflow=MODE, source_profile=source_profile,
                            configuration_directory=str(configuration),
                            native_field_run=str(native_field_run) if native_field_run else None,
                            continuation_predecessor_manifest=str(continuation_manifest) if continuation_manifest else None,
                            injected_source=str(injected_source) if injected_source else None),
                        committed_new_bytes=committed,
                        commitment_inputs=[budget_record, launcher_record, *sources],
                        retention=dict(policy_version=1, **{"class": profile["retention_class"]},
                                       reason=profile["retention_reason"]),
                        expected_operation_ids=(OPERATION_ID,), operation_dependencies={},
                        action=partial(_execute, request=request,
                            profile=dict(profile, source_path=str(budget_path)),
                            launcher_record=launcher_record),
                        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
                        completion_api=_completion_policy,
                        use_short_execution_path=True)
                    scope["reported_status"] = result["status"]
                except BaseException as failure:
                    scope["reported_status"] = "failed"
                    _annotate_failure(failure, scope)
                    raise
        except BaseException as failure:
            _annotate_failure(failure, scope)
            raise
        return dict(result, store_run_id=scope["parent_run_id"],
                    store_run_path=str(scope["published_path"]),
                    native_stage_asset_ids=list(scope["produced"]))


def recover_native_stage(*, artifact_store: Any, native_stage_asset_id: str,
                         context: ExecutionContext) -> dict[str, Any]:
    """Recover exactly one terminal IP Store stage without invoking science."""
    if not isinstance(native_stage_asset_id, str) or not native_stage_asset_id.strip():
        raise ValueError("IP recovery requires an exact native stage asset ID")
    recovered = recover_managed_native_store_stage(
        artifact_store, native_stage_asset_id, context=context)
    return dict(role="ion_processor_native_stage_recovery",
                native_stage_asset_id=native_stage_asset_id, recovered=recovered)


def recover_native_publication(*, artifact_store: Any, store_run_id: str) -> dict[str, Any]:
    """Replay exactly one stopped IP Store parent publication."""
    if not isinstance(store_run_id, str) or not store_run_id.strip():
        raise ValueError("IP publication recovery requires an exact Store run ID")
    recovered = artifact_store.recover_run_publication(store_run_id)
    return dict(role="ion_processor_store_publication_recovery",
                store_run_id=store_run_id, recovered=recovered,
                run_path=str(artifact_store.inspect_run(store_run_id)))
