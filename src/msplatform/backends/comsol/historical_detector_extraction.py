"""Managed read-only extraction from a sealed historical COMSOL particle solution."""
from __future__ import annotations

from datetime import datetime
from functools import partial
import csv
import json
import math
from pathlib import Path
import re
from uuid import uuid4

from msplatform.backends.comsol.native_execution import (
    declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion,
)
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.execution.owner import run_managed_stage, standalone_native_store
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.results.artifacts import open_artifact
from msplatform.results.historical_comsol_request import validate_detector_cohort

PROJECT = "single_reflection_oa_tof_mass_analyzer"
RESOURCES = ("comsolstartup.m", "load_oatof_contract.m", "reextract_oatof_saved_solution.m",
    "oatof_postprocess_saved_solution.m", "oatof_detector_arrival_reducer.m",
    "oatof_export_detector_events.m", "oatof_particle_plot_view.m",
    "oatof_create_result_nodes.m", "oatof_validate_candidate_solution.m")


def extract_historical_detector(manifest_record, *, model_output, context_output, geometry_input,
                                analysis_contract_input, context, store, source_status="success"):
    """Cold-read one sealed successful model under its original source guard and Store owner."""
    stage, authority = read_stage_policy(context, "reextract_oatof_saved_solution",
                                         required_roles=("required_evidence", "solver_native_binary"))
    if source_status == "success":
        guard = guard_historical_run(manifest_record, expected_project=PROJECT, expected_mode="design_candidate")
    elif source_status == "failed":
        from msplatform.execution.native_source_guard import guard_oa_failed_historical_run
        guard = guard_oa_failed_historical_run(manifest_record)
    else:
        raise ValueError("explicit historical source status must be success or failed")
    with guard as source:
        if source.manifest.get("mode") != "design_candidate":
            raise ValueError("saved model must belong to its original design producer")
        model = source.output(model_output)
        saved_context = source.output(context_output)
        geometry = source.input(geometry_input)
        analysis_contract = source.input(analysis_contract_input)
        document = json.loads(Path(saved_context["path"]).read_text(encoding="utf-8-sig"))
        if (document.get("schema_version") != 1 or document.get("role") != "oatof_saved_particle_solution"
                or type(document.get("particle_count")) not in (int, float) or document["particle_count"] != 100
                or document.get("solution_tag") != "sol2" or document.get("dataset_tag") != "pdset1"
                or type(document.get("saved_model_bytes")) not in (int, float)
                or not math.isfinite(document["saved_model_bytes"]) or document["saved_model_bytes"] != model["bytes"]):
            raise ValueError("saved COMSOL particle solution is not explicitly complete")
        if "model_save_state" in document and document["model_save_state"] not in ("raw_complete", "gui_update_complete"):
            raise ValueError("saved COMSOL model completion is unknown")
        if source_status == "success":
            _validate_legacy_save_completion(source, require_final_pass="model_save_state" not in document)
        label = document.get("label")
        if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_ -]+", label):
            raise ValueError("saved COMSOL label is not a safe output name")
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "__analysis__comsol__cold-" + uuid4().hex[:12]
        budget = stage["limits"]["transient_run_directory_bytes"]
        with standalone_native_store(store, task_key="historical-comsol:" + run_id, budget=budget) as scope:
            result = run_managed_stage(context, descriptor={"project": PROJECT, "mode": "saved_detector_extraction",
                "software": ["COMSOL", "MATLAB"]}, run_id=run_id,
                payload={"action": "reextract_oatof_saved_solution", "stage_policy": stage},
                committed_new_bytes=budget, commitment_inputs=[authority], retention=stage["artifact_retention"],
                source_references=[{"manifest_record": dict(manifest_record)}],
                expected_operation_ids=("reextract_saved_detector",), operation_dependencies={},
                action=partial(_extract_action, model=model, saved_context=saved_context, geometry=geometry,
                    analysis_contract=analysis_contract, manifest_record=dict(manifest_record),
                    source_root=source.root, source_status=source_status, label=label,
                    limits=stage["limits"]), action_record=file_record(Path(__file__), "required_evidence"),
                use_short_execution_path=False, completion_api=no_particle_batch_completion_api)
            scope["reported_status"] = result["status"]
        product = open_artifact({"manifest": result["manifest"], "product_id": "detector_export"},
                                expected_kind="historical_detector_export")
        return product, scope["parent_run_id"]


def _validate_legacy_save_completion(source, *, require_final_pass=True):
    """Verify original public and native stop evidence when the old sidecar lacks a save state."""
    from msplatform.backends.simion.native_stage_completion import append_native_stage_completion
    from msplatform.execution.owner import validate_writer_completion
    from msplatform.io.manifest_records import record_path
    native = source.output("logs/comsol_build_completion.json")
    matches = [record_path(record, base_dir=source.root) for record in source.manifest.get("outputs", [])
               if isinstance(record, dict) and record_path(record, base_dir=source.root).name == "execution_completion.json"]
    if len(matches) != 1:
        raise ValueError("legacy COMSOL public completion is missing or ambiguous")
    completion_record = source.output(matches[0].relative_to(source.root).as_posix())
    completion = json.loads(Path(completion_record["path"]).read_text(encoding="utf-8-sig"))
    if (completion.get("schema_version") != 1 or completion.get("role") != "run_artifact_workflow_completion"
            or completion.get("run_id") != source.root.name or completion.get("project") != PROJECT
            or completion.get("status") != source.manifest["status"]
            or completion.get("run_config", {}).get("sha256") != source.manifest["run_config"]["sha256"]):
        raise ValueError("legacy COMSOL public completion differs")
    original_request = source.input("execution_request")
    completion_request = completion.get("execution_request")
    if (not isinstance(completion_request, dict) or completion_request.get("exists") is not True
            or Path(completion_request.get("path", "")).resolve() != Path(original_request["path"]).resolve()
            or completion_request.get("bytes") != original_request["bytes"]
            or completion_request.get("sha256", "").lower() != original_request["sha256"].lower()):
        raise ValueError("legacy COMSOL completion request identity differs")
    request = json.loads(Path(original_request["path"]).read_text(encoding="utf-8-sig"))
    package = request.get("package", {})
    if (request.get("schema_version") != 1 or request.get("role") != "run_artifact_workflow_request"
            or package.get("run_id") != source.root.name or package.get("project") != PROJECT
            or package.get("mode") != source.manifest.get("mode")):
        raise ValueError("legacy COMSOL execution request differs")
    writer = {"operations": [], "resource_releases": []}
    append_native_stage_completion(writer, Path(native["path"]), role="comsol_launcher_completion",
                                   run_id=source.root.name)
    if not writer["operations"] or any(op["observation"].get("exit_confirmed") is not True for op in writer["operations"]):
        raise ValueError("legacy COMSOL native writer is not stopped")
    if require_final_pass:
        report = source.output("logs/comsol_build.txt")
        if ("STATUS=PASS" not in Path(report["path"]).read_text(encoding="utf-8-sig").splitlines()
                or any(op["observation"].get("returncode") != 0 for op in writer["operations"])):
            raise ValueError("legacy COMSOL native save lacks successful stopped completion")
    public = completion.get("writer_completion", {})
    if (any(op not in public.get("operations", []) for op in writer["operations"])
            or any(item not in public.get("resource_releases", []) for item in writer["resource_releases"])):
        raise ValueError("legacy COMSOL native completion is not bound by the public owner")
    try:
        validate_writer_completion(writers_stopped=True,
            expected_operation_ids=tuple(row["operation_id"] for row in public["operations"]),
            operations=public["operations"], resource_releases=public["resource_releases"],
            powershell_owner=True, require_process_identity=False)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("legacy COMSOL public writer is not stopped") from error


def validate_stopped_cold_launcher(path: Path, run_id: str) -> None:
    """Bind the COMSOL launcher format to the shared native writer validator."""
    from msplatform.execution.owner import validate_writer_completion
    receipt = json.loads(path.read_text(encoding="utf-8-sig"))
    operations = receipt.get("operations")
    if (receipt.get("schema_version") != 1 or receipt.get("role") != "comsol_launcher_completion"
            or receipt.get("run_id") != run_id or not isinstance(operations, list) or len(operations) != 1
            or not isinstance(operations[0], dict) or not isinstance(operations[0].get("operation_id"), str)
            or not operations[0]["operation_id"].strip()
            or not isinstance(operations[0].get("observation"), dict)):
        raise ValueError("cold COMSOL launcher completion identity differs")
    operation = {"operation_id": operations[0]["operation_id"], "observation": operations[0]["observation"],
                 "resource_release_id": "comsol-launcher"}
    validate_writer_completion(writers_stopped=True, expected_operation_ids=(operation["operation_id"],),
        operations=[operation], resource_releases=[{"release_id": "comsol-launcher", "completion_receipt": receipt}],
        powershell_owner=True, require_process_identity=True)


def _extract_action(session, *, model, saved_context, geometry, analysis_contract, manifest_record, source_root, source_status, label, limits):
    from msplatform.execution.inputs import freeze_file
    launcher, frozen = freeze_native_sources(session, RESOURCES)
    model_record = dict(model, retention_role="solver_native_binary")
    session.add_input("source_model", model_record)
    session.add_input("source_manifest", dict(manifest_record, retention_role="required_evidence"))
    records = {}
    for name, record in (("saved_context", saved_context), ("geometry", geometry),
                         ("analysis_contract", analysis_contract)):
        target = session.declare_file(session.input_dir / (name + ".json"), "required_evidence")
        freeze_file(Path(record["path"]), target)
        records[name] = file_record(target, "required_evidence")
        session.add_input(name, records[name])
    safe_label = re.sub(r"[^A-Za-z0-9_-]", "_", label)
    output = session.result_dir
    events = session.declare_file(output / ("comsol_detector_events_" + safe_label + ".csv"), "required_evidence")
    request = session.declare_file(output / ("comsol_detector_events_" + safe_label + ".analysis_request.json"), "required_evidence")
    figure = session.declare_file(output / ("ms_oaTOF_ringstack_reflectron_" + label.replace(" ", "_") + ".png"), "required_evidence")
    report = session.declare_file(output / "cold_extraction.json", "required_evidence")
    task = session.declare_file(session.input_dir / "cold_extraction.m", "required_evidence")
    bootstrap = session.declare_file(session.log_dir / "cold_extraction.bootstrap.log", "required_evidence")
    completion = session.declare_file(session.log_dir / "cold_extraction.launcher.json", "required_evidence")
    runtime = session.run_dir / "comsol_runtime"
    runtime.mkdir()
    request_json = {"model_path": model["path"], "context_path": records["saved_context"]["path"],
        "output_dir": str(output), "parent_run_directory": str(source_root),
        "child_run_directory": str(session.run_dir), "candidate_contract_path": records["geometry"]["path"]}
    parameters = session.declare_file(session.input_dir / "cold_request.json", "required_evidence")
    parameters.write_text(json.dumps(request_json), encoding="utf-8")
    task.write_text("addpath(" + matlab_text(launcher.parent.parent / "matlab") + ");\n"
        "request=jsondecode(fileread(" + matlab_text(parameters) + "));\n"
        "result=reextract_oatof_saved_solution(request);\n"
        "assert(result.native_particle_solve_count==0 && result.native_field_solve_count==0 && ~result.parent_model_saved);\n"
        "fid=fopen(" + matlab_text(report) + ",'w','n','UTF-8'); assert(fid>=0);"
        " c=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result)); clear c;\n"
        "fid=fopen(getenv('COMSOL_BOOTSTRAP_REPORT'),'a'); assert(fid>=0); fprintf(fid,'STATUS=PASS\\n'); fclose(fid);\n",
        encoding="utf-8", newline="\n")
    host = json.dumps({name: str(getattr(session.context, name)) for name in
        ("workspace", "python_executable", "host_state_path", "policy_path")})
    args = ["-NoProfile", "-File", str(launcher), "-HostContextJson", host,
        "-WorkingDirectory", str(session.run_dir), "-ComsolLauncherPath", str(session.context.tools["comsol_launcher"]),
        "-MatlabRootPath", str(session.context.tools["matlab_root"]), "-TaskScript", str(task),
        "-ReportPath", str(bootstrap), "-StartupAttempts", "1", "-RunId", session.run_id,
        "-RunDir", str(runtime), "-CompletionPath", str(completion)]
    guards = [*frozen, *records.values(), model_record, file_record(parameters, "required_evidence"),
              file_record(task, "required_evidence")]
    primary = None
    try:
        session.run_process("reextract_saved_detector", executable=session.context.powershell_executable,
                            arguments=args, role="COMSOL", stage="solver", limits=limits, immutable_input_records=guards)
    except BaseException as error:
        primary = error
        from msplatform.execution.processes import ProcessExecutionError
        if isinstance(error, ProcessExecutionError) and error.observed_process_exit_confirmed:
            try:
                validate_stopped_cold_launcher(completion, session.run_id)
                validate_detector_cohort(events, request)
                error.failure_output_paths = [*getattr(error, "failure_output_paths", ()), events, request, completion]
            except Exception as export_error:
                error.add_note("Stopped cold detector export is incomplete: " + str(export_error))
        raise
    finally:
        try:
            declare_runtime_files(session, runtime, bootstrap=bootstrap)
        except BaseException as error:
            if primary is None:
                raise
            primary.add_note("COMSOL diagnostic preservation failed: " + repr(error))
    for record in guards:
        if record is not model_record:
            verify_record("historical COMSOL immutable input", record)
    require_launcher_completion(completion, session.run_id)
    if "STATUS=PASS" not in bootstrap.read_text(encoding="utf-8-sig"):
        raise ValueError("cold detector extraction did not pass")
    result = json.loads(report.read_text(encoding="utf-8-sig"))
    if (any(type(result.get(name)) is not int or result[name] != 0
            for name in ("native_particle_solve_count", "native_field_solve_count"))
            or result.get("parent_model_saved") is not False or result.get("candidate_model_validation") != "passed"
            or any(type(result.get(name)) is not int or result[name] != 100 for name in ("nP", "nDet"))):
        raise ValueError("cold detector extraction evidence differs")
    outputs = [events, request, figure, report]
    if any(not path.is_file() for path in outputs):
        raise ValueError("cold detector extraction output is incomplete")
    from msplatform.results.historical_comsol_request import load_request
    exported_request = load_request(request)
    if (Path(str(result.get("model_path", ""))).resolve() != Path(model["path"]).resolve()
            or Path(exported_request["raw_events_csv"]).resolve() != events.resolve()
            or Path(str(result.get("raw_detector_events_path", ""))).resolve() != events.resolve()
            or Path(str(result.get("analysis_request_path", ""))).resolve() != request.resolve()):
        raise ValueError("cold detector export identity differs")
    with events.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    try:
        ids = [int(row["Ion"]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("cold detector export IDs are invalid") from error
    if len(ids) != 100 or set(ids) != set(range(1, 101)):
        raise ValueError("cold detector export does not contain all original IDs")
    product = {"schema_version": 1, "kind": "historical_detector_export", "status": "complete",
        "metadata": {"backend": "comsol", "scope": "saved_solution_read_only",
            "native_particle_solve_count": 0, "native_field_solve_count": 0,
            "source_manifest": manifest_record, "source_model": model, "source_execution_status": source_status},
        "data": {"events": file_record(events, "required_evidence"),
            "request": file_record(request, "required_evidence"), "report": file_record(report, "required_evidence"),
            "geometry": records["geometry"], "analysis_contract": records["analysis_contract"],
            "saved_context": records["saved_context"]}}
    return {"status": "success", "summary": {"scope": "saved_solution_read_only", "solve_calls": 0},
        "output_paths": list(map(str, outputs)), "required_output_paths": list(map(str, outputs)),
        "retention_preserve_paths": [], "manifest_extra_fields": {"products": {"detector_export": product}}}
