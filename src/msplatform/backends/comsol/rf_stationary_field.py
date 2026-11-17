"""Native COMSOL orchestration for RF stationary differential/static fields."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from msplatform.backends.comsol.native_execution import (
    declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion,
)
from msplatform.components.rf_multipole.source_validation import validate_source
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.run_paths import project_run_path
from msplatform.io.manifest_records import file_record


def _owned_file(session: Any, name: str, source: Path, relative: str) -> tuple[Path, dict[str, Any]]:
    from msplatform.execution.inputs import freeze_file
    target = session.declare_file(session.input_dir / relative, "required_evidence")
    target.parent.mkdir(parents=True, exist_ok=True)
    freeze_file(source, target)
    record = file_record(session.canonical_path(target), "required_evidence")
    session.add_input(name, record)
    return target, record


def _science_sources(session: Any, science_task: Path) -> list[dict[str, Any]]:
    from msplatform.backends.comsol.resources import native_resource_directory

    science_task = science_task.resolve()
    resource_directory = native_resource_directory().resolve()
    if science_task != resource_directory / "solve_finite_3d_transport.m":
        raise ValueError("RF science resource must be the installed finite3D implementation")
    records = []
    for index, source in enumerate(sorted(resource_directory.glob("*.m"))):
        record = file_record(source, "required_evidence")
        session.add_input(f"science_resource_{index:03d}", record)
        records.append(record)
    return records


def _task_environment(session: Any, values: Mapping[str, Path | str]) -> str:
    native = lambda value: project_run_path(value, session.artifact_run_dir, session.run_dir)
    return "".join("setenv(" + matlab_text(name) + "," + matlab_text(native(value) if isinstance(value, Path) else value) + ");\n"
                   for name, value in values.items())


def _write_task(session: Any, operation: str, body: str) -> tuple[Path, Path, Path, Path, Path]:
    task = session.declare_file(session.input_dir / f"{operation}.m", "required_evidence")
    bootstrap = session.declare_file(session.log_dir / f"{operation}.bootstrap.log", "required_evidence")
    completion = session.declare_file(session.log_dir / f"{operation}.launcher.json", "required_evidence")
    runtime = session.run_dir / "comsol_runtime" / operation
    runtime.mkdir(parents=True)
    task.write_text(body, encoding="utf-8", newline="\n")
    return task, bootstrap, completion, runtime, session.log_dir / f"{operation}.json"


def _launcher_arguments(session: Any, launcher: Path, task: Path, bootstrap: Path,
                        completion: Path, runtime: Path) -> list[str]:
    native = lambda value: project_run_path(value, session.artifact_run_dir, session.run_dir)
    host = json.dumps({name: str(getattr(session.context, name))
                       for name in ("workspace", "python_executable", "host_state_path", "policy_path")})
    return ["-NoProfile", "-File", str(launcher), "-HostContextJson", host,
        "-WorkingDirectory", str(session.run_dir),
        "-ComsolLauncherPath", str(session.context.tools["comsol_launcher"]),
        "-MatlabRootPath", str(session.context.tools["matlab_root"]),
        "-TaskScript", native(task), "-ReportPath", native(bootstrap), "-StartupAttempts", "1",
        "-RunId", session.run_id, "-RunDir", str(runtime), "-CompletionPath", native(completion)]


def _solve_task(session: Any, *, science_task: Path, matlab: Path, resolved: Path, numerics: Path,
                source: Path, metadata: Path, model: Path) -> str:
    runtime = session.run_dir / "particle_runtime"
    progress = session.log_dir / "solver_progress"
    progress.mkdir(parents=True, exist_ok=True)
    values: dict[str, Path | str] = {
        "MULTIPOLE_RESOLVED_DESIGN": resolved, "MULTIPOLE_SOLVER_NUMERICS": numerics,
        "MULTIPOLE_L3_PARTICLE_SOURCE": source, "MULTIPOLE_L3_PARTICLE_SOURCE_METADATA": metadata,
        "MULTIPOLE_L3_RUNTIME_DIR": runtime, "MULTIPOLE_L3_SOLVER_PROGRESS_DIR": progress,
        "MULTIPOLE_L3_EVENTS": session.result_dir / "particle_events.csv",
        "MULTIPOLE_L3_TRAJECTORIES": session.result_dir / "trajectory_samples.csv",
        "MULTIPOLE_L3_MODEL": model, "MULTIPOLE_L3_STOP_STAGE": "field_solve",
        "MULTIPOLE_L3_MAXIMUM_MESH_CELLS": "",
        "MULTIPOLE_L3_CANONICAL_STATE": session.result_dir / "particle_state.csv",
        "MULTIPOLE_L3_PRIMARY_CANONICAL_STATE": session.result_dir / "particle_state__primary.csv",
        "MULTIPOLE_L3_CONTROL_CANONICAL_STATE": session.result_dir / "particle_state__control.csv",
        "MULTIPOLE_L3_PRIMARY_TRAJECTORIES": session.result_dir / "trajectory_samples__primary.csv",
        "MULTIPOLE_L3_CONTROL_TRAJECTORIES": session.result_dir / "trajectory_samples__control.csv",
    }
    return ("addpath(" + matlab_text(matlab) + ");\n" + _task_environment(session, values)
        + "run(" + matlab_text(science_task) + ");\n"
        + "assert(isfile(" + matlab_text(project_run_path(model, session.artifact_run_dir, session.run_dir)) + "));\n")


def _verify_task(session: Any, *, matlab: Path, model: Path, points: Path,
                 samples: Path, report: Path) -> str:
    native = lambda value: project_run_path(value, session.artifact_run_dir, session.run_dir)
    return f"""addpath({matlab_text(matlab)});
import com.comsol.model.util.*
tag=char(java.util.UUID.randomUUID());tag=['RF_FIELD_VERIFY_' strrep(tag,'-','_')];
model=mphload({matlab_text(native(model))},tag);
cleanup=onCleanup(@()ModelUtil.remove(tag));
solutions=cell(model.sol.tags());
if any(strcmp(solutions,'sol_es'))
  required={{'sol_es'}};
  info=mphsolinfo(model,'soltag','sol_es');
elseif all(ismember({{'sol_es_diff','sol_es_static'}},solutions))
  required={{'sol_es_diff','sol_es_static'}};
  info=mphsolinfo(model,'soltag','sol_es_diff');
  staticInfo=mphsolinfo(model,'soltag','sol_es_static');
  assert(double(staticInfo.size)>0,'RF stationary static solution is empty.');
else
  error('rf:StationaryFieldSolve','Stored RF stationary solutions are missing.');
end
assert(double(info.size)>0,'RF stationary differential solution is empty.');
clear cleanup
request=struct('model_path',{matlab_text(native(model))},'points_path',{matlab_text(native(points))},'output_path',{matlab_text(native(samples))});
receipt=read_rf_saved_stationary_solution(request);
receipt.solution_tags=solutions;
fid=fopen({matlab_text(native(report))},'w','n','UTF-8');assert(fid>=0);
reportCleanup=onCleanup(@() fclose(fid));fprintf(fid,'%s',jsonencode(receipt));
fid=fopen(getenv('COMSOL_BOOTSTRAP_REPORT'),'a');assert(fid>=0);
logCleanup=onCleanup(@() fclose(fid));
fprintf(fid,'STORED_SOLUTIONS=%s\\n',strjoin(solutions,','));
fprintf(fid,'CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE\\n');
"""


def _prepare_inputs(session: Any, runtime: Mapping[str, Any]) -> dict[str, Any]:
    runtime_path = session.declare_file(session.input_dir / "resolved_runtime.json", "required_evidence")
    write_json_atomic(runtime_path, runtime)
    runtime_record = file_record(session.canonical_path(runtime_path), "required_evidence")
    session.add_input("resolved_runtime", runtime_record)
    design_path = session.declare_file(session.input_dir / "multipole_resolved_design.json", "required_evidence")
    design = runtime["design_profile_resolution"]["resolved_design"]
    write_json_atomic(design_path, design)
    session.add_input("multipole_resolved_design", file_record(session.canonical_path(design_path), "required_evidence"))
    numerics_path = session.declare_file(session.input_dir / "solver_numerics.json", "required_evidence")
    write_json_atomic(numerics_path, dict(schema_version=1, role="multipole_comsol_solver_numerics",
                                          **runtime["solver_numerics"]["comsol"]["values"]))
    session.add_input("solver_numerics", file_record(session.canonical_path(numerics_path), "required_evidence"))
    particle = runtime["particle_source"]
    source, _ = _owned_file(session, "particle_source", Path(particle["path"]), "particle_source.csv")
    receipt_path = None
    if particle.get("volume_snapshot_receipt") is not None:
        receipt_path, _ = _owned_file(session, "particle_source_volume_snapshot_receipt",
            Path(particle["volume_snapshot_receipt"]["path"]), "particle_source_volume_snapshot_receipt.json")
    metadata_path = session.declare_file(session.input_dir / "particle_source_metadata.json", "required_evidence")
    metadata = validate_source(source, design, solver="comsol", volume_snapshot_receipt_path=receipt_path)
    write_json_atomic(metadata_path, metadata)
    session.add_input("particle_source_metadata", file_record(session.canonical_path(metadata_path), "required_evidence"))
    return dict(resolved=design_path, numerics=numerics_path, source=source, metadata=metadata_path)


def run_field_operations(session: Any, *, runtime: Mapping[str, Any], science_task: Path,
                         points: Path, samples: Path, limits: Mapping[str, Any]) -> dict[str, Any]:
    """Solve/save RF fields, then cold-read both stored cases without another Compute."""
    if session.expected_operation_ids != ("solve_stationary_fields", "verify_stationary_fields"):
        raise ValueError("RF stationary field operation graph differs")
    launcher, native_sources = freeze_native_sources(session, (
        "comsolstartup.m", "export_comsol_stationary_field_samples.m", "read_rf_saved_stationary_solution.m",
        "configure_comsol_mesh.m", "add_comsol_size_feature.m", "read_comsol_mesh_size_controls.m"))
    science_sources = _science_sources(session, science_task)
    inputs = _prepare_inputs(session, runtime)
    model = session.declare_file(session.result_dir / "finite_3d_transport.mph", "solver_native_binary")
    verification = session.declare_file(session.result_dir / "stored_solution_verification.json", "required_evidence")
    matlab = launcher.parent.parent / "matlab"
    operations = (
        ("solve_stationary_fields", _solve_task(session, science_task=science_task, matlab=matlab, model=model, **inputs)),
        ("verify_stationary_fields", _verify_task(session, matlab=matlab, model=model, points=points,
                                                  samples=samples, report=verification)),
    )
    model_record = None
    for operation, body in operations:
        task, bootstrap, completion, runtime_dir, _ = _write_task(session, operation, body)
        guards = [*native_sources, *science_sources, file_record(task, "required_evidence")]
        if model_record is not None:
            guards.append(model_record)
        try:
            session.run_process(operation, executable=session.context.powershell_executable,
                arguments=_launcher_arguments(session, launcher, task, bootstrap, completion, runtime_dir),
                role="COMSOL", stage="solver", limits=limits,
                immutable_input_records=guards)
        finally:
            declare_runtime_files(session, runtime_dir, bootstrap=bootstrap)
            progress = session.log_dir / "solver_progress"
            if progress.is_dir():
                for path in progress.rglob("*"):
                    if path.is_file():
                        session.declare_file(path, "required_evidence")
        require_launcher_completion(completion, session.run_id)
        text = bootstrap.read_text(encoding="utf-8-sig")
        if "STATUS=PASS" not in text:
            raise ValueError("RF stationary native bootstrap failed: " + operation)
        if operation == "solve_stationary_fields":
            required = ("CHECKPOINT=MESH_COMPLETE", "CHECKPOINT=STATIONARY_FIELDS_COMPLETE",
                        "STOP_STAGE=field_solve", "PARTICLE_PHYSICS_CREATED=0",
                        "PARTICLE_STUDIES_CREATED=0", "FIELD_SOLVE_DIAGNOSTIC=PASS", "MODEL_SAVED=true")
            forbidden = ("PRIMARY_PARTICLE_CASE_COMPLETE", "CONTROL_PARTICLE_CASE_COMPLETE")
            if any(token not in text for token in required) or any(token in text for token in forbidden):
                raise ValueError("RF stationary field-solve report differs")
            model_record = file_record(model, "solver_native_binary")
        else:
            if "CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE" not in text:
                raise ValueError("RF stationary stored-field samples were not completed")
    receipt = json.loads(verification.read_text(encoding="utf-8-sig"))
    if receipt.get("native_solves") != 0 or receipt.get("parent_model_saved") is not False:
        raise ValueError("RF stationary cold verification invoked Compute or saved the parent")
    return dict(model=model, verification=verification, solution_tags=receipt["solution_tags"])
