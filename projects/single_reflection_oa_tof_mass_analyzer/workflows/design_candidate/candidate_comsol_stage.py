"""Frozen COMSOL Candidate construction and scientific completion checks."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import load_json
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import frozen_source_path, verify_candidate_source_closure

def _report_value(path: Path, key: str) -> str:
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            if value:
                return value
    raise RuntimeError(f"required {key} record is missing from {path}")


def execute_comsol_stage(stage: dict[str, Any], plan: dict[str, Any], simion_exe: str, *, runtime: Any) -> dict[str, Any]:
    """Execute the declared frozen COMSOL stage using owner-managed processes."""
    from .candidate_stage_execution import _powershell, _require_pass_report
    _run_managed_stage_command = runtime._run_managed_stage_command
    _verify_frozen_cad_python = runtime._verify_frozen_cad_python
    closure = plan.get("execution_source_closure")
    if closure is not None:
        verify_candidate_source_closure(closure)
    run_root = Path(plan["run_root"])
    logs = run_root / "logs"
    if closure is None:
        raise RuntimeError("candidate source closure is required")
    _verify_frozen_cad_python(closure, logs / "cad_python_preflight.log")
    environment = {key: str(value) for key, value in stage["environment"].items()}
    environment["OATOF_CANDIDATE_ARTIFACT_ROOT"] = str(
        Path(closure["runtime"]["candidate_artifact_root"]).resolve().parents[1]
    )
    build_report = Path(stage["report_path"])
    build_command = _powershell(
        frozen_source_path(closure, "common/comsol/run_comsol_r2025b.ps1"),
        [
            "-TaskScript",
            frozen_source_path(
                closure,
                "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m",
            ),
            "-ReportPath",
            str(build_report),
            "-RunId", plan["run_id"],
            "-CompletionPath", str(logs / "comsol_build_completion.json"),
        ],
    )
    _run_managed_stage_command(build_command, logs / "comsol_build_launcher.log", plan,
                               logs / "comsol_build_completion.json", "comsol_launcher_completion", environment)
    _require_pass_report(build_report)
    analysis_request = Path(_report_value(build_report, "PYTHON_ANALYSIS_REQUEST"))
    if not analysis_request.is_file():
        raise RuntimeError(f"COMSOL detector-event analysis request is missing: {analysis_request}")
    analysis_receipt = analyze_detector_request(analysis_request, closure, logs / "comsol_detector_event_analysis.log", runtime=runtime)
    sync_report = logs / "comsol_sync.txt"
    sync_environment = {
        "OATOF_COMSOL_MODEL_PATH": stage["model_path"],
        "OATOF_CONTRACT_PATH": stage["contract_path"],
    }
    sync_command = _powershell(
        frozen_source_path(closure, "common/comsol/run_comsol_r2025b.ps1"),
        [
            "-TaskScript",
            frozen_source_path(
                closure,
                "projects/single_reflection_oa_tof_mass_analyzer/comsol/verify_oatof_comsol_sync.m",
            ),
            "-ReportPath",
            str(sync_report),
            "-RunId", plan["run_id"],
            "-CompletionPath", str(logs / "comsol_sync_completion.json"),
        ],
    )
    _run_managed_stage_command(sync_command, logs / "comsol_sync_launcher.log", plan,
                               logs / "comsol_sync_completion.json", "comsol_launcher_completion", sync_environment)
    _require_pass_report(sync_report)
    return {
        "model": stage["model_path"], "build_report": str(build_report),
        "sync_report": str(sync_report), "analysis_request": str(analysis_request),
        "analysis_receipt": str(analysis_receipt),
        "analysis_contract": frozen_source_path(closure, "projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json"),
    }


def analyze_detector_request(request: Path, closure: dict[str, Any], log: Path, *, runtime: Any) -> Path:
    """Execute the sole existing detector analysis consumer from frozen code."""
    runtime._run_command([
        str(Path(closure["runtime"]["python_executable"]).resolve()), "-I", "-B", "-c",
        "import sys;sys.path.insert(0,sys.argv[1]);"
        "from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_comsol_detector_events import main;"
        "sys.exit(main(['--request',sys.argv[2]]))", str(closure["code_root"]), str(request),
    ], log, {"PYTHONPATH": str(closure["code_root"]), "PYTHONDONTWRITEBYTECODE": "1"})
    receipt = Path(load_json(request)["analysis_output_dir"]) / "analysis_receipt.json"
    if not receipt.is_file():
        raise RuntimeError(f"COMSOL detector-event Python analysis receipt is missing: {receipt}")
    return receipt


def execute_saved_postprocess(selection: dict, root: Path, closure: dict, plan: dict, *, runtime: Any) -> dict:
    """Postprocess one admitted parent; no parent save or solver dispatch exists."""
    import csv
    import json
    import os
    from common.paths.workspace_paths import project_run_path
    from .candidate_stage_execution import _powershell, _require_pass_report
    output = root / "results"
    output.mkdir(exist_ok=True)
    runtime._run_command([closure["runtime"]["python_executable"], "-I", "-B", "-c",
        "import sys;sys.path.insert(0,sys.argv[1]);"
        "from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_comsol_detector_events import analyze_request;"
        "from projects.single_reflection_oa_tof_mass_analyzer.analysis.reference_analysis_core import load_contract,DEFAULT_CONTRACT;load_contract(DEFAULT_CONTRACT)",
        str(closure["code_root"])], root / "logs/analysis_import_preflight.log")
    exports = selection["exports"]
    receipt_path = None
    if exports is not None:
        document = load_json(Path(exports["request"]["path"]))
        document["raw_events_csv"] = exports["events"]["path"]
        document["analysis_output_dir"] = str(output / "detector_analysis")
        analysis_request = root / "inputs/postprocess_analysis_request.json"
        analysis_request.write_text(json.dumps(document, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    else:
        execution = Path(os.environ["MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY"])
        def execution_path(value: Path) -> str:
            return project_run_path(value, root, execution)
        request = {"model_path": selection["model_record"]["path"],
                   "context_path": selection["context_record"]["path"],
                   "output_dir": str(output), "parent_run_directory": selection["parent"],
                   "child_run_directory": str(root),
                   "candidate_contract_path": frozen_source_path(closure,
                       "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json")}
        source_context = plan.get("source_execution_context")
        if (not isinstance(source_context, dict) or source_context.get("schema_version") != 1
                or source_context.get("role") != "run_source_execution_context"
                or Path(source_context.get("child_run_directory", "")).resolve() != root.resolve()
                or str(source_context.get("request_sha256", "")).lower() != str(plan.get("context_sha256", "")).lower()):
            raise ValueError("SOURCE_NATIVE_CONTEXT_MISSING: use the public owner's declared native inputs")
        expected = {str(Path(request[name]).resolve()) for name in ("model_path", "context_path")}
        sources = [value for value in source_context["sources"]
                   if Path(value["target_directory"]).resolve() == Path(selection["parent"]).resolve()
                   and expected <= {str(Path(path).resolve()) for path in value["input_paths"]}]
        if len(sources) != 1:
            raise ValueError("SOURCE_NATIVE_CONTEXT_AMBIGUOUS: one exact source owner must declare model/context")
        source = sources[0]
        native_model = project_run_path(request["model_path"], source["target_directory"], source["execution_directory"])
        native_context = project_run_path(request["context_path"], source["target_directory"], source["execution_directory"])
        request_path = root / "inputs/cold_request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False)+"\n", encoding="utf-8")
        code = execution_path(Path(closure["code_root"]))
        project = str(Path(code) / "projects/single_reflection_oa_tof_mass_analyzer")
        def quote(value: str) -> str:
            return "'"+value.replace("'", "''")+"'"
        task = root / "inputs/cold_postprocess.m"
        result_path = output / "cold_postprocess_result.json"
        task.write_text("addpath("+quote(project)+","+quote(str(Path(project)/"comsol"))+");\n"
                        "request=jsondecode(fileread("+quote(execution_path(request_path))+"));\n"
                        "request.output_dir="+quote(execution_path(output))+";request.child_run_directory="+quote(str(execution))+";\n"
                        "request.model_path="+quote(native_model)+";request.context_path="+quote(native_context)+";\n"
                        "request.parent_run_directory="+quote(source["execution_directory"])+";\n"
                        "request.candidate_contract_path="+quote(execution_path(Path(request["candidate_contract_path"])))+";\n"
                        "result=reextract_oatof_saved_solution(request);\n"
                        "assert(result.native_particle_solve_count==0 && result.native_field_solve_count==0 && ~result.parent_model_saved);\n"
                        "fid=fopen("+quote(execution_path(result_path))+",'w');assert(fid>=0);\n"
                        "cleanup=onCleanup(@() fclose(fid));fprintf(fid,'%s\\n',jsonencode(result));clear cleanup\n"
                        "fid=fopen(getenv('COMSOL_BOOTSTRAP_REPORT'),'a');assert(fid>=0);fprintf(fid,'STATUS=PASS\\n');fclose(fid);\n", encoding="utf-8", newline="\n")
        report = root / "logs/cold_postprocess.txt"
        receipt_path = root / "logs/cold_postprocess_completion.json"
        command = _powershell(execution_path(Path(frozen_source_path(closure, "common/comsol/run_comsol_r2025b.ps1"))),
            ["-TaskScript", execution_path(task), "-ReportPath", execution_path(report), "-RunId", root.name,
             "-StartupAttempts", "1", "-CompletionPath", execution_path(receipt_path)])
        runtime._run_managed_stage_command(command, root / "logs/cold_launcher.log", plan,
                                            receipt_path, "comsol_launcher_completion")
        _require_pass_report(report)
        result = load_json(result_path)
        if result.get("candidate_model_validation") != "passed":
            raise ValueError("Cold Candidate model did not complete the original read-only scientific checks")
        result["model_path"] = project_run_path(result["model_path"], source["execution_directory"], source["target_directory"])
        if Path(result["model_path"]).resolve() != Path(selection["model_record"]["path"]).resolve():
            raise ValueError("Cold model result does not match its canonical source identity")
        result["model_path"] = selection["model_record"]["path"]
        for name in ("raw_detector_events_path", "analysis_request_path", "analysis_output_dir"):
            result[name] = project_run_path(Path(result[name]), execution, root)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        analysis_request = Path(result["analysis_request_path"])
        # Persist execution-created small JSON paths in canonical child form.
        document = load_json(analysis_request)
        for name in ("raw_events_csv", "analysis_output_dir"):
            value = Path(document[name])
            if value.is_relative_to(execution):
                document[name] = str(root / value.relative_to(execution))
        analysis_request = root / analysis_request.relative_to(execution) if analysis_request.is_relative_to(execution) else analysis_request
        analysis_request.write_text(json.dumps(document, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    document = load_json(analysis_request)
    # The original normal Candidate contract requires all 100 requested IDs/hits.
    with Path(document["raw_events_csv"]).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 100 or {int(row["Ion"]) for row in rows} != set(range(1,101)) or any(
            row["Hit"].lower() not in {"1", "true"} or row["Status"] != "detector_hit" for row in rows):
        raise ValueError("Candidate detected population differs: requires 100 original IDs and detector_hit classifications")
    if exports is None and isinstance(plan.get("postprocess_evidence"), dict):
        # A completed export can survive the following Python analysis failure.
        # Reuse the public stopped-writer/release validator, not a local guess.
        import subprocess
        writer_path = root / "logs/postprocess_export_writer.json"
        writer_path.write_text(json.dumps(plan["writer_completion"]), encoding="utf-8")
        validator = frozen_source_path(closure, "common/contracts/run_artifact_workflow.ps1")
        command = ". '"+validator.replace("'", "''")+"'; Assert-WorkflowWriterCompletion (Get-Content -Raw -Encoding UTF8 '"+str(writer_path).replace("'", "''")+"'|ConvertFrom-Json -AsHashtable)"
        plan["postprocess_evidence"]["writer_completion_unconfirmed"] = True
        checked = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=os.environ.get("MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY", str(root)),
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        (root / "logs/postprocess_export_writer.log").write_text(checked.stdout+checked.stderr, encoding="utf-8")
        if checked.returncode:
            plan["postprocess_evidence"]["writer_completion_unconfirmed"] = True
            raise RuntimeError("POSTPROCESS_EXPORT_WRITER_UNCONFIRMED: "+checked.stderr.strip())
        plan["postprocess_evidence"].pop("writer_completion_unconfirmed")
        plan["postprocess_evidence"].update(analysis_request=str(analysis_request),
            raw_events_csv=str(Path(document["raw_events_csv"])), detector_exports_ready=True,
            native_launch_count=1, native_particle_solve_count=0,
            native_field_solve_count=0, parent_model_saved=False)
    analysis = analyze_detector_request(analysis_request, closure, root / "logs/detector_analysis.log", runtime=runtime)
    return {"analysis_request": str(analysis_request), "analysis_receipt": str(analysis),
            "native_launch_count": 0 if exports else 1, "native_particle_solve_count": 0,
            "native_field_solve_count": 0, "parent_model_saved": False}


def refresh_reused_comsol_analysis(evidence: dict, output_records: dict, root: Path, closure: dict, *, parent_root: Path, runtime: Any) -> tuple[dict, str]:
    """Reuse native outputs while checking the actual frozen analysis authority."""
    from common.contracts.verify_run_manifest import verify_record
    from common.contracts.write_run_manifest import file_record
    import json
    authority_id = "projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json"
    current = next((item for item in closure["sources"] if item["source_id"] == authority_id), None)
    if current is None:
        raise ValueError("Current COMSOL analysis authority was not explicitly frozen")
    previous = output_records.get("analysis_contract")
    if previous is not None and all(str(previous[key]).upper() == str(current[key]).upper() for key in ("bytes","sha256")):
        return evidence, "reused"
    verify_candidate_source_closure(closure)
    old_request = load_json(Path(evidence["analysis_request"]))
    old_receipt = load_json(Path(evidence["analysis_receipt"]))
    raw = old_receipt.get("raw_events")
    if not isinstance(raw, dict) or Path(old_request["raw_events_csv"]).resolve() != Path(raw.get("path", "")).resolve():
        raise ValueError("Native/CSV reuse lacks a sufficiently bound detector export; no implicit solve")
    from common.contracts.verify_run_manifest import record_path
    parent_manifest = load_json(parent_root / "run_manifest.json")
    matches = [record for record in parent_manifest["outputs"]
               if record_path(record, base_dir=parent_root) == Path(raw["path"]).resolve()]
    if len(matches) != 1 or matches[0]["sha256"].upper() != raw["sha256"].upper():
        raise ValueError("Reused detector CSV is not bound by the original manifest and analysis receipt")
    verify_record("reused COMSOL event export", matches[0], base_dir=parent_root)
    output = root / "results/comsol_reanalysis"
    output.mkdir(parents=True, exist_ok=True)
    request = output / "analysis_request.json"
    old_request["analysis_output_dir"] = str(output / "analysis")
    request.write_text(json.dumps(old_request, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    receipt = analyze_detector_request(request, closure, root / "logs/comsol_reanalysis.log", runtime=runtime)
    evidence = dict(evidence, analysis_request=str(request), analysis_receipt=str(receipt),
                    analysis_contract=frozen_source_path(closure, authority_id))
    for name in ("analysis_request", "analysis_receipt", "analysis_contract"):
        output_records[name] = file_record(Path(evidence[name]))
    return evidence, "executed"
