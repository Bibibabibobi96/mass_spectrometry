"""Compose the independent OA–MR study with the existing native Store owner."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from functools import partial
from importlib.resources import files
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from msplatform.contracts.trajectory_recording import resolve_trajectory_recording
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
from msplatform.io.manifest_records import file_record
from msplatform.results.mr_batch_continuation import continuation_protection_projection

MODE = "oa_mr"
OPERATION_ID = "oa_mr"

_REQUIRED = (
    "run_id", "repository_root", "legacy_artifact_root",
    "accelerator_component_contract_path", "accelerator_geometry_profile_id",
    "geometry_review_run_path", "mirror_run_path", "stripe_run_path",
    "accelerator_provider_receipt_path", "composition_plan_path",
    "prism1_voltage_v", "prism2_voltage_v",
)
_PATH_OPTIONS = {
    "local_scope_path": "LocalScopePath",
    "native_corridor_bank_run_path": "NativeCorridorBankRunPath",
    "native_system_runtime_bundle_path": "NativeSystemRuntimeBundlePath",
    "field_binding_path": "FieldBindingPath",
    "accelerator_pulse_schedule_path": "AcceleratorPulseSchedulePath",
    "mirror_voltage_variation_path": "MirrorVoltageVariationPath",
    "contract_path": "ContractPath",
    "bunch_source_receipt_path": "BunchSourceReceiptPath",
    "batch_continuation_run_path": "BatchContinuationRunPath",
    "native_runtime_checkpoint": "NativeRuntimeCheckpoint",
}
_VALUE_OPTIONS = {
    "accelerator_component_contract_path": "AcceleratorComponentContractPath",
    "accelerator_geometry_profile_id": "AcceleratorGeometryProfileId",
    "geometry_review_run_path": "GeometryReviewRunPath",
    "mirror_run_path": "MirrorRunPath",
    "stripe_run_path": "StripeRunPath",
    "accelerator_provider_receipt_path": "AcceleratorProviderReceiptPath",
    "composition_plan_path": "CompositionPlanPath",
    "prism1_voltage_v": "Prism1VoltageV",
    "prism2_voltage_v": "Prism2VoltageV",
    "trajectory_profile_id": "TrajectoryProfileId",
    "trajectory_step_scale": "TrajectoryStepScale",
    "accelerator_source_y_offset_mm": "AcceleratorSourceYOffsetMm",
    "accelerator_y_anchor_mm": "AcceleratorYAnchorMm",
    "bunch_particle_id_min": "BunchParticleIdMin",
    "bunch_particle_id_max": "BunchParticleIdMax",
}
_SWITCH_OPTIONS = {
    "pulse_accelerator_until_initial_exit": "PulseAcceleratorUntilInitialExit",
    "accelerator_safe_exit_only": "AcceleratorSafeExitOnly",
    "retain_gui_workbench": "RetainGuiWorkbench",
}
_OPTIONAL = {*_PATH_OPTIONS, *_VALUE_OPTIONS, *_SWITCH_OPTIONS, "inherited_host_resource_lease"}


def _completion_policy():
    from msplatform.backends.simion import native_completion
    return native_completion


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"OA–MR request must be a JSON object: {path}")
    return value


def _request(path: Path) -> dict[str, Any]:
    request = _read(path)
    missing = [name for name in _REQUIRED if name not in request]
    unknown = sorted(set(request) - set(_REQUIRED) - _OPTIONAL)
    if missing or unknown:
        raise ValueError(f"OA–MR request fields differ; missing={missing}, unknown={unknown}")
    for name in _REQUIRED:
        if name not in {"prism1_voltage_v", "prism2_voltage_v"} and (
                not isinstance(request[name], str) or not request[name].strip()):
            raise ValueError(f"OA–MR request requires nonempty {name}")
    for name in _SWITCH_OPTIONS:
        if name in request and type(request[name]) is not bool:
            raise ValueError(f"OA–MR switch must be boolean: {name}")
    lease = request.get("inherited_host_resource_lease")
    if lease is not None and not isinstance(lease, Mapping):
        raise ValueError("inherited_host_resource_lease must be an object")
    return request


def _controller_path() -> Path:
    return (Path(str(files("msplatform.workflows"))) / "resources/oa_mr.ps1").resolve(strict=True)


def _controller_arguments(request: Mapping[str, Any]) -> list[str]:
    arguments = []
    for name, option in _VALUE_OPTIONS.items():
        if name in request and request[name] is not None:
            arguments.extend((f"-{option}", str(request[name])))
    for name, option in _PATH_OPTIONS.items():
        if name in request and request[name]:
            arguments.extend((f"-{option}", str(request[name])))
    for name, option in _SWITCH_OPTIONS.items():
        if request.get(name) is True:
            arguments.append(f"-{option}")
    if "inherited_host_resource_lease" in request:
        arguments.extend(("-InheritedHostResourceLeaseJson", json.dumps(
            request["inherited_host_resource_lease"], separators=(",", ":"), allow_nan=False)))
    return arguments


def _native_peak(request: Mapping[str, Any], contract: Mapping[str, Any]) -> int:
    required = 0
    package = Path(str(files("msplatform"))).resolve(strict=True)
    selected_contract = request.get("contract_path") or str(
        package / "components/multi_reflection_tof/simion_candidate_two_zone.json")
    names = [
        selected_contract, selected_contract, selected_contract, selected_contract,
        request["mirror_run_path"] + "/summary.json",
        request["stripe_run_path"] + "/summary.json",
        request["accelerator_provider_receipt_path"],
    ]
    provider = _read(Path(request["accelerator_provider_receipt_path"]).resolve(strict=True))
    for key in ("provider_plan", "resolved_campaign"):
        names.append(provider[key]["path"])
    names.extend(str(package / relative) for relative in (
        "components/multi_reflection_tof/fixed_mirror_stripe_operating_point.py",
        "workflows/oa_mr/prism_trial.py", "backends/simion/mrtof_batch_flight.py",
        "backends/simion/resources/mrtof_candidate.lua",
        "backends/simion/resources/voltage_waveforms.lua",
        "backends/simion/resources/mirror_cycle_counter.lua",
        "backends/simion/resources/candidate_voltage_map.lua",
        "backends/simion/resources/run_iob_flight.lua",
    ))
    for name in ("mirror_voltage_variation_path", "bunch_source_receipt_path"):
        if request.get(name):
            names.append(request[name])
    for name in names:
        if name:
            required += Path(name).resolve(strict=True).stat().st_size
    peak = max(required, 25 * 1024**2)
    peak += int(contract.get("output_budget_bytes", 0))
    if not request.get("field_binding_path") and not request.get("native_runtime_checkpoint"):
        publication = _read(Path(request["native_corridor_bank_run_path"]).resolve(strict=True)
                            / "results/pa_family_cache_publication.json")
        cache = _read(Path(publication["generation_directory"]).resolve(strict=True) / "cache_manifest.json")
        raw = [row for row in cache["files"] if row.get("name") == "mrtof_analyzer_corridor.pa#"]
        if len(raw) != 1:
            raise ValueError("Native corridor bank lacks its unique raw geometry record")
        peak += 10 * int(raw[0]["bytes"])
    return peak


def _guard_request_sources(stack: ExitStack, request: Mapping[str, Any]) -> None:
    """Bind small scientific authorities for the whole native controller lifetime."""
    def hold(path):
        target = Path(path).resolve(strict=True)
        record = file_record(target, "required_evidence")
        stack.enter_context(guarded_file_identity(target, expected_bytes=record["bytes"],
                                                  expected_sha256=record["sha256"]))
    for name in (
        "accelerator_provider_receipt_path", "composition_plan_path", "contract_path",
        "accelerator_pulse_schedule_path", "mirror_voltage_variation_path",
        "bunch_source_receipt_path", "local_scope_path", "native_system_runtime_bundle_path",
    ):
        if request.get(name):
            hold(request[name])
    for name in ("mirror_run_path", "stripe_run_path"):
        hold(Path(request[name]) / "summary.json")
        hold(Path(request[name]) / "run_manifest.json")
    receipt = Path(request["accelerator_provider_receipt_path"]).resolve(strict=True)
    provider = _read(receipt)
    hold(receipt.parent.parent / "run_manifest.json")
    for name in ("provider_plan", "resolved_campaign"):
        hold(provider[name]["path"])
    if request.get("bunch_source_receipt_path"):
        bunch = _read(Path(request["bunch_source_receipt_path"]))
        for name in ("state_table", "fly2"):
            if bunch.get(name, {}).get("path"):
                hold(bunch[name]["path"])
    if not request.get("field_binding_path"):
        bank_run = Path(request["native_corridor_bank_run_path"])
        hold(bank_run / "run_manifest.json")
        publication_path = bank_run / "results/pa_family_cache_publication.json"
        publication = _read(publication_path.resolve(strict=True))
        hold(publication_path)
        hold(Path(publication["generation_directory"]) / "cache_manifest.json")


def _guard_static_sources(stack: ExitStack, binding_path: Path) -> None:
    """Hold the same sealed static field and response layers used by the controller."""
    from msplatform.backends.comsol.static_field_binding import load_binding
    binding = load_binding(binding_path.resolve(strict=True))
    mode = binding.get("mode", "comsol_static_scalar_v")
    paths = {binding_path.resolve()}

    def add(value):
        if value:
            paths.add(Path(value).resolve(strict=True))

    def add_component(component):
        for value in component.get("sources", {}).values():
            if value is not None:
                add(value)
        if mode == "native_static_pa":
            add(component.get("manifest"))
        else:
            add(component.get("export_manifest"))
        for window in component.get("refinement_windows", []):
            for value in window.get("sources", {}).values():
                if value is not None:
                    add(value)
            add(window.get("manifest") if mode == "native_static_pa" else window.get("export_manifest"))

    add_component(binding)
    add(binding.get("collision_geometry"))
    for instance in binding.get("instances", []):
        add(instance.get("pa_path"))
        add(instance.get("manifest"))
    for term in binding.get("response_terms", []):
        add(term.get("binding_path"))
        add_component(term["binding"])
    for path in sorted(paths, key=str):
        stack.enter_context(guarded_file_identity(path))


def _guard_continuation(stack: ExitStack, parent: Path) -> None:
    before = continuation_protection_projection(parent.resolve(strict=True))
    manifests = before["manifests"]
    for name, expected in manifests.items():
        path = Path(name).resolve(strict=True)
        record = file_record(path, "required_evidence")
        if record["sha256"].lower() != expected.lower():
            raise ValueError("Continuation manifest identity differs before Store admission")
        stack.enter_context(guarded_file_identity(path, expected_bytes=record["bytes"],
                                                  expected_sha256=record["sha256"]))
    for name in before["files"]:
        stack.enter_context(guarded_file_identity(Path(name).resolve(strict=True)))
    after = continuation_protection_projection(parent.resolve(strict=True))
    if before != after:
        raise ValueError("Continuation protection projection changed during Store admission")


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
    inputs = set()
    from msplatform.io.manifest_records import record_path
    for value in config.get("inputs", {}).values():
        if isinstance(value, Mapping) and "path" in value:
            inputs.add(record_path(value, base_dir=session.artifact_run_dir))
        elif isinstance(value, str):
            path = Path(value)
            inputs.add(path.resolve() if path.is_absolute() else (session.artifact_run_dir / value).resolve())
    return [path for path in session.artifact_run_dir.rglob("*")
            if path.is_file() and path.name not in {"run_config.json", "run_manifest.json"}
            and path.resolve() not in inputs]


def _execute(session: RunSession, *, request: Mapping[str, Any], request_record: Mapping[str, Any],
             controller_record: Mapping[str, Any], retention: Mapping[str, Any],
             committed_new_bytes: int) -> dict[str, Any]:
    try:
        frozen_request = freeze_file(Path(request_record["path"]),
            session.input_dir / "oa_mr_request.json", retention_role="required_evidence")
        session.add_input("oa_mr_request", frozen_request)
        frozen_controller = freeze_file(Path(controller_record["path"]),
            session.input_dir / "oa_mr_controller.ps1", retention_role="required_evidence")
        if any(frozen_controller[name] != controller_record[name] for name in ("bytes", "sha256")):
            raise ValueError("Frozen OA–MR controller differs from its admitted source")
        session.add_input("oa_mr_controller", frozen_controller)
        arguments = ["-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(controller_record["path"]),
                     "-RunId", session.run_id, "-PythonExe", str(session.context.python_executable),
                     "-RepoRoot", request["repository_root"]]
        arguments.extend(_controller_arguments(request))
        environment = {
            "MASS_SPECTROMETRY_OA_MR_CAPACITY_JSON": json.dumps(session.capacity_session, default=str),
            "MASS_SPECTROMETRY_OA_MR_LEGACY_ARTIFACT_ROOT": request["legacy_artifact_root"],
            "MASS_SPECTROMETRY_OA_MR_RETENTION_JSON": json.dumps(retention),
        }
        receipt = session.run_process(OPERATION_ID,
            executable=session.context.powershell_executable, arguments=arguments,
            role="SIMION", stage="mrtof_flight",
            limits={"transient_run_directory_bytes": committed_new_bytes},
            environment=environment,
            immutable_input_records=(request_record, controller_record, frozen_request, frozen_controller))
        if receipt["observation"]["exit_code"] != 0:
            raise RuntimeError("OA–MR scientific controller failed; see its frozen summary and logs")
        summary_path = session.artifact_run_dir / "summary.json"
        summary = _read(summary_path)
        if summary.get("role") != "mrtof_finite_3d_two_prism_voltage_trial" or summary.get("status") != "success":
            raise ValueError("OA–MR controller did not publish its scientific success summary")
        outputs = _declare_payload(session)
        return dict(status="success", summary=summary,
            output_paths=outputs, required_output_paths=[summary_path],
            retention_preserve_paths=[], manifest_extra_fields={})
    except BaseException as failure:
        try:
            failure.failure_output_paths = _declare_payload(session)
        except BaseException as secondary:
            failure.add_note(f"OA–MR failure evidence selection failed: {secondary!r}")
        raise


def _annotate_failure(failure: BaseException, scope: Mapping[str, Any] | None) -> None:
    if scope is None:
        return
    failure.add_note("OA–MR Store run_id: " + str(scope["parent_run_id"]))
    for asset_id in scope["produced"]:
        failure.add_note("OA–MR native stage asset_id: " + str(asset_id))


def run_oa_mr(*, context: ExecutionContext, artifact_store: Any, request_path: Path) -> dict[str, Any]:
    """Run one independent OA–MR native study under an explicit ArtifactStore."""
    request_path = Path(request_path).resolve(strict=True)
    request_record = file_record(request_path, "required_evidence")
    with ExitStack() as guards:
        guards.enter_context(guarded_file_identity(request_path,
            expected_bytes=request_record["bytes"], expected_sha256=request_record["sha256"]))
        request = _request(request_path)
        _guard_request_sources(guards, request)
        if request.get("field_binding_path"):
            _guard_static_sources(guards, Path(request["field_binding_path"]))
        if request.get("batch_continuation_run_path"):
            _guard_continuation(guards, Path(request["batch_continuation_run_path"]))
        checkpoint = request.get("native_runtime_checkpoint")
        if checkpoint:
            guards.enter_context(guarded_file_identity(Path(checkpoint).resolve(strict=True)))
        contract_path = Path(request.get("contract_path") or
            Path(str(files("msplatform.components.multi_reflection_tof"))) / "simion_candidate_two_zone.json")
        contract_document = _read(contract_path.resolve(strict=True))
        recording = resolve_trajectory_recording(contract_document) or {
            "retention_class": "compact", "reason": "", "output_budget_bytes": 0}
        retention = {"policy_version": 1, "class": recording["retention_class"],
                     "reason": recording.get("reason") or None}
        committed = _native_peak(request, recording)
        controller = _controller_path()
        controller_record = file_record(controller, "required_evidence")
        commitment = [request_record, file_record(contract_path, "required_evidence"), controller_record]
        if request.get("field_binding_path"):
            commitment.append(file_record(Path(request["field_binding_path"]).resolve(strict=True), "required_evidence"))
        scope = None
        try:
            with standalone_native_store(artifact_store, task_key="oa-mr:" + request["run_id"],
                                         budget=committed) as scope:
                try:
                    result = run_managed_stage(context, artifact_store=artifact_store,
                        descriptor=dict(project="instrument_assembly", mode=MODE,
                                        software=["SIMION 2020", "Python 3.11"]),
                        run_id=request["run_id"],
                        payload=dict(workflow=MODE, request=_request_locator(request_path)),
                        committed_new_bytes=committed, commitment_inputs=commitment,
                        retention=retention, expected_operation_ids=(OPERATION_ID,),
                        operation_dependencies={},
                        action=partial(_execute, request=request, request_record=request_record,
                            controller_record=controller_record, retention=retention,
                            committed_new_bytes=committed),
                        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
                        completion_api=_completion_policy, use_short_execution_path=True)
                    scope["reported_status"] = result["status"]
                except BaseException as failure:
                    scope["reported_status"] = "failed"
                    _annotate_failure(failure, scope)
                    raise
        except BaseException as failure:
            _annotate_failure(failure, scope)
            raise
        return dict(result, run_id=request["run_id"], store_run_id=scope["parent_run_id"],
                    store_run_path=str(scope["published_path"]),
                    native_stage_asset_ids=list(scope["produced"]))


def _request_locator(path: Path) -> str:
    """Return the admitted original request locator for run metadata."""
    return str(path.resolve())


def recover_oa_mr_stage(*, artifact_store: Any, native_stage_asset_id: str,
                        context: ExecutionContext) -> dict[str, Any]:
    """Recover exactly one terminal OA–MR Store stage without invoking science."""
    if not isinstance(native_stage_asset_id, str) or not native_stage_asset_id.strip():
        raise ValueError("OA–MR recovery requires an exact native stage asset ID")
    recovered = recover_managed_native_store_stage(artifact_store, native_stage_asset_id, context=context)
    return dict(role="oa_mr_native_stage_recovery", native_stage_asset_id=native_stage_asset_id,
                recovered=recovered)


def recover_oa_mr_publication(*, artifact_store: Any, store_run_id: str) -> dict[str, Any]:
    """Replay exactly one stopped OA–MR Store parent publication."""
    if not isinstance(store_run_id, str) or not store_run_id.strip():
        raise ValueError("OA–MR publication recovery requires an exact Store run ID")
    recovered = artifact_store.recover_run_publication(store_run_id)
    return dict(role="oa_mr_store_publication_recovery", store_run_id=store_run_id,
                recovered=recovered, run_path=str(artifact_store.inspect_run(store_run_id)))


def _context(args: argparse.Namespace) -> ExecutionContext:
    from msplatform.execution.resources import resource_path
    return ExecutionContext(workspace=Path(args.workspace).absolute(),
        python_executable=Path(args.python_exe).absolute(),
        powershell_executable=Path(args.powershell_exe).absolute(),
        tools={"simion": Path(args.simion_exe).absolute()},
        host_state_path=Path(args.host_state_path).absolute(),
        policy_path=Path(args.policy_path).absolute() if args.policy_path else resource_path("host_resource_policy.json"),
        execution_root=Path(args.execution_root).absolute())


def _write_result(path: Path | None, result: Mapping[str, Any]) -> None:
    rendered = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2, default=str) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")


def main(argv: Sequence[str] | None = None) -> int:
    """Run or recover OA–MR without selecting the generic continuous tracer."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path)
    for command in (run, commands.add_parser("recover-stage")):
        command.add_argument("--workspace", required=True)
        command.add_argument("--python-exe", required=True)
        command.add_argument("--powershell-exe", required=True)
        command.add_argument("--simion-exe", required=True)
        command.add_argument("--host-state-path", required=True)
        command.add_argument("--policy-path")
        command.add_argument("--execution-root", required=True)
        command.add_argument("--artifact-root", type=Path, required=True)
    recover_stage = commands.choices["recover-stage"]
    recover_stage.add_argument("--native-stage-asset-id", required=True)
    recover_stage.add_argument("--output", type=Path)
    recover_publication = commands.add_parser("recover-publication")
    recover_publication.add_argument("--artifact-root", type=Path, required=True)
    recover_publication.add_argument("--store-run-id", required=True)
    recover_publication.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    from msplatform.storage import ArtifactStore
    store = ArtifactStore(args.artifact_root.absolute())
    try:
        if args.action == "run":
            result = run_oa_mr(context=_context(args), artifact_store=store, request_path=args.request)
        elif args.action == "recover-stage":
            result = recover_oa_mr_stage(artifact_store=store,
                native_stage_asset_id=args.native_stage_asset_id, context=_context(args))
        else:
            result = recover_oa_mr_publication(artifact_store=store, store_run_id=args.store_run_id)
    except BaseException as failure:
        if args.output is not None:
            notes = list(getattr(failure, "__notes__", ()))
            error_result = dict(status="failed", error=dict(type=type(failure).__name__,
                message=str(failure), notes=notes))
            if args.action == "run":
                error_result["run_id"] = _read(args.request)["run_id"]
                store_note = next((note for note in notes if note.startswith("OA–MR Store run_id: ")), None)
                assets = [note.rsplit(": ", 1)[1] for note in notes
                          if note.startswith("OA–MR native stage asset_id: ")]
                if store_note is not None:
                    error_result["store_run_id"] = store_note.rsplit(": ", 1)[1]
                if assets:
                    error_result["native_stage_asset_ids"] = assets
                    stage = store.asset_status(assets[0])
                    run_directory = Path(stage["path"]) / "runs" / error_result["run_id"]
                    error_result["run_directory"] = str(run_directory)
                    manifest = run_directory / "run_manifest.json"
                    if manifest.is_file():
                        error_result["manifest"] = {"path": str(manifest)}
            _write_result(args.output, error_result)
        raise
    _write_result(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
