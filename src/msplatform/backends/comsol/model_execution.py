"""Shared COMSOL unsolved-model execution, with one existing managed owner."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from functools import partial
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.context import ExecutionContext
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact
from .native_execution import (
    declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion,
)

@dataclass(frozen=True)
class UnsolvedModelSpec:
    """Actual native resources and filenames of one implemented model workflow."""
    run_label: str
    matlab_resources: tuple[str, ...]
    build_function: str
    verify_function: str
    model_relative_paths: tuple[str, ...]
    build_extra_arguments: tuple[str, ...] = ()


def build_unsolved_model(resolved: dict, baseline: Mapping[str, Any], modes: Mapping[str, Any], *,
                         action_name: str, spec: UnsolvedModelSpec,
                         context: ExecutionContext) -> OpenedArtifact:
    """Use the existing owner for actual model creation and separate cold verification."""
    for name in ("comsol_launcher", "matlab_root"):
        path = context.tools.get(name)
        if path is None or not (path.is_dir() if name == "matlab_root" else path.is_file()):
            raise ContractError(action_name + " requires explicit available tool: " + name)
    stage, authority = read_stage_policy(context, action_name, required_roles=("solver_native_binary",))
    if stage.get("runtime", {}):
        raise ContractError(action_name + " has no additional runtime overrides")
    result = run_managed_stage(context,
        descriptor=dict(project=resolved["project_id"], mode="prepared_model", software=["COMSOL", "MATLAB"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__build__comsol__" + spec.run_label + "-" + uuid4().hex[:12],
        payload=dict(action=action_name, baseline=copy.deepcopy(dict(baseline)),
                     modes=copy.deepcopy(dict(modes)), resolved=resolved, stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[authority], retention=stage["artifact_retention"],
        expected_operation_ids=("build_model", "verify_model"),
        operation_dependencies={"verify_model": ["build_model"]},
        action=partial(execute_unsolved_model, resolved=resolved, limits=stage["limits"], spec=spec),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
        use_short_execution_path=True, completion_api=no_particle_batch_completion_api)
    return open_artifact({"manifest": result["manifest"], "product_id": "model"}, expected_kind="prepared_model")










def _report(path: Path, contract: dict, contract_path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if (value.get("status") != "PASS" or value.get("execution_mode") != "build_only"
            or value.get("selected_mode_id") != contract["selected_mode_id"]
            or value.get("contract_project_id") != contract["project_id"]
            or value.get("contract_model_id") != contract["model_id"]
            or Path(value.get("contract_path", "")).resolve() != contract_path.resolve()
            or value.get("parameter_bindings_verified") is not True
            or value.get("candidate_evidence_allowed") is not False):
        raise ValueError("COMSOL report differs from the frozen unsolved contract")
    return value


def execute_unsolved_model(session, *, resolved: dict, limits: Mapping[str, Any], spec: UnsolvedModelSpec) -> dict:
    """Bind sources, call the same launcher twice, and publish real verified bytes."""
    if session.expected_operation_ids != ("build_model", "verify_model"):
        raise ValueError("COMSOL model requires build_model followed by verify_model")
    if resolved["numerical"]["execution_mode"] != "build_only":
        raise ValueError("COMSOL execution requires the resolved build_only mode")
    launcher, sources = freeze_native_sources(session, spec.matlab_resources)
    contract = session.declare_file(session.input_dir / "resolved_model.json", "required_evidence")
    write_json_atomic(contract, resolved)
    contract_record = file_record(contract, "required_evidence")
    session.add_input("resolved_contract", contract_record)
    for name in ("comsol_launcher",):
        session.add_input(name, file_record(session.context.tools[name], "required_evidence"))
    matlab = launcher.parent.parent / "matlab"
    models = [session.declare_file(session.run_dir / relative, "solver_native_binary")
              for relative in spec.model_relative_paths]
    model = models[-1]
    host = json.dumps({name: str(getattr(session.context, name)) for name in
                      ("workspace", "python_executable", "host_state_path", "policy_path")})
    reports = {}
    original_models = []
    for operation in session.expected_operation_ids:
        verify = operation == "verify_model"
        report = session.declare_file(session.result_dir / (operation + ".json"), "required_evidence")
        bootstrap = session.declare_file(session.log_dir / (operation + ".bootstrap.log"), "required_evidence")
        completion = session.declare_file(session.log_dir / (operation + ".launcher.json"), "required_evidence")
        task = session.declare_file(session.input_dir / (operation + ".m"), "required_evidence")
        runtime = session.run_dir / "comsol_runtime" / operation
        runtime.mkdir(parents=True)
        function = spec.verify_function if verify else spec.build_function
        values = [model, contract] if verify else [contract, session.run_dir, *spec.build_extra_arguments]
        call = function + "(" + ",".join(matlab_text(value) for value in values) + ")"
        script = ("addpath(" + matlab_text(matlab) + ");\nresult=" + call + ";\n"
                  "fid=fopen(" + matlab_text(report) + ",'w','n','UTF-8');\n"
                  "assert(fid>=0,'COMSOL:ReportWrite','Cannot write COMSOL report');\n"
                  "cleanup=onCleanup(@()fclose(fid));\nfprintf(fid,'%s',jsonencode(result));\n")
        task.write_text(script, encoding="utf-8", newline="\n")
        task_record = file_record(task, "required_evidence")
        arguments = ["-NoProfile", "-File", str(launcher), "-HostContextJson", host,
                     "-WorkingDirectory", str(session.run_dir), "-ComsolLauncherPath",
                     str(session.context.tools["comsol_launcher"]), "-MatlabRootPath",
                     str(session.context.tools["matlab_root"]), "-TaskScript", str(task),
                     "-ReportPath", str(bootstrap), "-StartupAttempts", "1", "-RunId", session.run_id,
                     "-RunDir", str(runtime), "-CompletionPath", str(completion)]
        guards = [*sources, contract_record, task_record]
        guards.extend(original_models)
        primary = None
        try:
            session.run_process(operation, executable=session.context.powershell_executable,
                arguments=arguments, role="COMSOL", stage="solver", limits=limits,
                immutable_input_records=guards)
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                declare_runtime_files(session, runtime, bootstrap=bootstrap)
            except BaseException as secondary:
                if primary is None:
                    raise
                primary.add_note(f"COMSOL runtime diagnostic preservation failed: {secondary!r}")
        for record in guards:
            verify_record("COMSOL immutable input", record)
        require_launcher_completion(completion, session.run_id)
        if "STATUS=PASS" not in bootstrap.read_text(encoding="utf-8-sig"):
            raise ValueError("COMSOL bootstrap did not complete its task")
        value = _report(report, resolved, contract)
        if Path(value.get("model_path", "")).resolve() != model.resolve() or not model.is_file():
            raise ValueError("COMSOL report does not identify the expected saved model")
        if verify:
            if (value.get("solution_data_empty") != [True, True] or value.get("compute_calls") != 0
                    or value.get("model_rewritten") is not False or value.get("mesh_complete") is not True
                    or type(value.get("geometry_domains")) is not int or value["geometry_domains"] <= 0
                    or set(value.get("physics_tags", [])) != {"es", "cpt"}
                    or set(value.get("study_tags", [])) != {"std1", "std2"}
                    or set(value.get("solver_tags", [])) != {"sol1", "sol2"}):
                raise ValueError("COMSOL cold verifier lacks unsolved geometry/mesh/physics/solver evidence")
            for record in original_models:
                verify_record("COMSOL model unchanged by cold verification", record)
        else:
            if (value.get("geometry_built") is not True or value.get("mesh_built") is not True
                    or value.get("electrostatics_solved") is not False
                    or value.get("particle_tracing_solved") is not False):
                raise ValueError("COMSOL builder did not produce the declared unsolved model")
            original_models = [file_record(path, "solver_native_binary") for path in models]
        reports[operation] = report
    metadata = dict(backend="comsol", model_id=resolved["model_id"], selected_mode_id=resolved["selected_mode_id"],
                    field_status="not_solved", source_status="not_requested", scientific_qualification="not_granted",
                    native_reopen_verified=True, compute_calls_requested=0)
    records = {name: file_record(path, "required_evidence") for name, path in reports.items()}
    records.update(model=file_record(model, "solver_native_binary"), resolved_contract=contract_record)
    records.update({"model_stage_" + str(index): file_record(path, "solver_native_binary")
                    for index, path in enumerate(models[:-1], 1)})
    return dict(status="success", summary=metadata, output_paths=[*map(str, models), *map(str, reports.values())],
        required_output_paths=[*map(str, models), *map(str, reports.values())], retention_preserve_paths=[],
        manifest_extra_fields=dict(products=dict(model=dict(schema_version=1, kind="prepared_model", status="complete",
                                                           metadata=metadata, data=records))))
