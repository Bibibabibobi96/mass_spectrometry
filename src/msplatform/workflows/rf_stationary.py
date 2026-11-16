"""Installed RF stationary sample recipes over the public execution owner."""
from __future__ import annotations

import argparse
import csv
import json
import math
from functools import partial
from pathlib import Path
from typing import Any, Mapping, Sequence

from msplatform.components.rf_multipole import stationary_field_sampling as sampling
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import resume_finalization, run_managed_stage
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.run_paths import project_run_path
from msplatform.io.manifest_records import (
    file_record, require_completed_terminal_publication, verify_record,
)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise sampling.StationaryFieldContractError(f"JSON object required: {path}")
    return value


def _budget(path: Path, *, solver: str) -> tuple[dict[str, Any], dict[str, Any]]:
    document = _json(path)
    if (document.get("schema_version") != 1
            or document.get("role") != "multipole_resolved_resource_budget"
            or document.get("project_id") != "rf_multipole_ion_optics"
            or document.get("solver") != solver
            or document.get("stop_stage") not in {"transport", "field_solve"}
            or not isinstance(document.get("limits"), Mapping)):
        raise ValueError("Explicit resolved RF stationary resource budget required")
    limits = document["limits"]
    for name in ("transient_run_directory_bytes", "process_tree_working_set_bytes",
                 "minimum_system_available_memory_bytes"):
        if type(limits.get(name)) is not int or limits[name] < 0:
            raise ValueError("RF stationary resource limits differ")
    return document, file_record(path, "required_evidence")


def _parent_model(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_record = file_record(manifest_path, "required_evidence")
    verify_record("RF stationary parent manifest", manifest_record)
    require_completed_terminal_publication(manifest_path)
    manifest = _json(manifest_path)
    if manifest.get("project") != "rf_multipole_ion_optics" or manifest.get("status") != "success":
        raise ValueError("Successful RF finite3D parent required")
    config_record = manifest.get("run_config")
    verify_record("RF stationary parent config", config_record)
    config = _json(Path(config_record["path"]))
    models = [row for row in manifest.get("outputs", [])
              if Path(row.get("path", "")).name == "finite_3d_transport.mph"]
    if len(models) != 1:
        raise ValueError("RF stationary parent must bind one saved finite3D model")
    verify_record("RF stationary parent model", models[0])
    resolved_record = manifest.get("inputs", {}).get("multipole_resolved_design")
    verify_record("RF stationary parent resolved design", resolved_record)
    return manifest_record, config, models[0], resolved_record


def _owned_input(session: Any, name: str, source: Path, relative: str) -> dict[str, Any]:
    target = session.declare_file(session.input_dir / relative, "required_evidence")
    target.parent.mkdir(parents=True, exist_ok=True)
    freeze_file(source, target)
    record = file_record(session.canonical_path(target), "required_evidence")
    session.add_input(name, record)
    return record


def _points(session: Any, resolved_record: Mapping[str, Any], plan_record: Mapping[str, Any], source_id: str):
    resolved = _json(Path(resolved_record["path"]))
    plan = _json(Path(plan_record["path"]))
    rows = sampling.generate_stationary_field_sample_rows(resolved, plan)
    points = session.declare_file(session.input_dir / "stationary_field_sample_points.csv", "required_evidence")
    sampling.write_stationary_field_sample_csv(rows, points)
    authority = session.declare_file(session.input_dir / "stationary_field_sampling_authority.json", "required_evidence")
    write_json_atomic(authority, sampling.build_stationary_sampling_authority(
        resolved, plan, rows, points_path=points, source_id=source_id))
    for name, path in (("stationary_field_sample_points", points),
                       ("stationary_field_sampling_authority", authority)):
        session.add_input(name, file_record(session.canonical_path(path), "required_evidence"))
    return points, authority


def _validation_document(authority_path: Path, samples_path: Path, output_path: Path) -> None:
    sampling.validate_stationary_output_authority(_json(authority_path), samples_path)
    records = sampling.load_stationary_field_output_csv(samples_path)
    write_json_atomic(output_path, dict(schema_version=1,
        role="multipole_stationary_field_sample_validation", status="PASS",
        field_cases=list(sampling.FIELD_CASES),
        point_count=len({row.sample_id for row in records}), row_count=len(records)))


def execute_saved_comsol(session: Any, *, parent_manifest: Mapping[str, Any], model_record: Mapping[str, Any],
                         resolved_source: Path, plan_source: Path, limits: Mapping[str, Any],
                         source_id: str) -> dict[str, Any]:
    """Export an owned child from a protected saved model without Compute/save."""
    from msplatform.backends.comsol.native_execution import (
        declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion,
    )
    if session.expected_operation_ids != ("export_saved_stationary",):
        raise ValueError("Saved stationary owner operation graph differs")
    session.add_input("parent_manifest", dict(parent_manifest))
    session.add_input("parent_model", dict(model_record))
    launcher, sources = freeze_native_sources(session, (
        "comsolstartup.m", "export_comsol_stationary_field_samples.m",
        "read_rf_saved_stationary_solution.m"))
    resolved = _owned_input(session, "resolved_design", resolved_source, "resolved_geometry.json")
    plan = _owned_input(session, "stationary_sampling_plan", plan_source, "stationary_field_sampling_plan.json")
    points, authority = _points(session, resolved, plan, source_id)
    samples = session.declare_file(session.result_dir / "stationary_field_samples.csv", "required_evidence")
    validation = session.declare_file(session.result_dir / "stationary_field_sample_validation.json", "required_evidence")
    report = session.declare_file(session.result_dir / "saved_stationary_export.json", "required_evidence")
    bootstrap = session.declare_file(session.log_dir / "saved_stationary.bootstrap.log", "required_evidence")
    completion = session.declare_file(session.log_dir / "saved_stationary.launcher.json", "required_evidence")
    task = session.declare_file(session.input_dir / "saved_stationary_export.m", "required_evidence")
    runtime = session.run_dir / "comsol_runtime" / "saved_stationary"
    runtime.mkdir(parents=True)
    matlab = launcher.parent.parent / "matlab"
    native = lambda value: project_run_path(value, session.artifact_run_dir, session.run_dir)
    task.write_text("addpath(" + matlab_text(matlab) + ");\n"
        "request=struct('model_path'," + matlab_text(model_record["path"])
        + ",'points_path'," + matlab_text(native(points)) + ",'output_path'," + matlab_text(native(samples)) + ");\n"
        "receipt=read_rf_saved_stationary_solution(request);\n"
        "fid=fopen(" + matlab_text(native(report)) + ",'w','n','UTF-8');\n"
        "assert(fid>=0);cleanup=onCleanup(@() fclose(fid));fprintf(fid,'%s',jsonencode(receipt));\n",
        encoding="utf-8", newline="\n")
    host = json.dumps({name: str(getattr(session.context, name))
                       for name in ("workspace", "python_executable", "host_state_path", "policy_path")})
    arguments = ["-NoProfile", "-File", str(launcher), "-HostContextJson", host,
        "-WorkingDirectory", str(session.run_dir),
        "-ComsolLauncherPath", str(session.context.tools["comsol_launcher"]),
        "-MatlabRootPath", str(session.context.tools["matlab_root"]),
        "-TaskScript", native(task), "-ReportPath", native(bootstrap), "-StartupAttempts", "1",
        "-RunId", session.run_id, "-RunDir", str(runtime), "-CompletionPath", native(completion)]
    guards = [*sources, dict(model_record), resolved, plan,
              file_record(task, "required_evidence"),
              file_record(session.canonical_path(points), "required_evidence"),
              file_record(session.canonical_path(authority), "required_evidence")]
    try:
        session.run_process("export_saved_stationary", executable=session.context.powershell_executable,
            arguments=arguments, role="COMSOL", stage="solver", limits=limits,
            immutable_input_records=guards)
        require_launcher_completion(completion, session.run_id)
        if "STATUS=PASS" not in bootstrap.read_text(encoding="utf-8-sig"):
            raise ValueError("Saved stationary export bootstrap failed")
        receipt = _json(report)
        if (receipt.get("native_solves") != 0 or receipt.get("parent_model_saved") is not False
                or receipt.get("stationary_field_row_count") != 2 * len(sampling.load_stationary_field_output_csv(samples)) // 2):
            raise ValueError("Saved stationary export receipt differs")
        _validation_document(authority, samples, validation)
    finally:
        declare_runtime_files(session, runtime, bootstrap=bootstrap)
    outputs = [samples, validation, report]
    return dict(status="success", summary=dict(role="rf_saved_stationary_samples",
        native_solves=0, parent_model_saved=False, fly_calls=0,
        scientific_qualification="not_granted"), output_paths=list(map(str, outputs)),
        required_output_paths=list(map(str, outputs)), retention_preserve_paths=[], manifest_extra_fields={})


def saved_comsol(*, parent_manifest: Path, sampling_plan: Path, budget: Path, run_id: str,
                 source_id: str, context: ExecutionContext) -> dict[str, Any]:
    parent, _, model, resolved = _parent_model(parent_manifest)
    resolved_budget, budget_record = _budget(budget, solver="comsol")
    plan_record = file_record(sampling_plan, "required_evidence")
    resolved_record = file_record(Path(resolved["path"]), "required_evidence")
    result = run_managed_stage(context,
        descriptor=dict(project="rf_multipole_ion_optics", mode="rf_stationary_saved_export",
                        software=["COMSOL 6.4", "MATLAB R2025b", "Python 3.11"]),
        run_id=run_id, payload=dict(action="saved_comsol_stationary", source_id=source_id,
                                    budget=resolved_budget),
        committed_new_bytes=resolved_budget["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[budget_record, plan_record, resolved_record,
                           file_record(Path(sampling.__file__).resolve(), "required_evidence")],
        retention={"policy_version": 1, "class": "solver_review",
                   "reason": "RF saved stationary samples; parent read-only; no Compute or qualification"},
        source_references=[dict(manifest_record=parent)],
        expected_operation_ids=("export_saved_stationary",), operation_dependencies={},
        action=partial(execute_saved_comsol, parent_manifest=parent, model_record=model,
                       resolved_source=Path(resolved["path"]), plan_source=sampling_plan,
                       limits=resolved_budget["limits"], source_id=source_id),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
        expected_relative_paths=("inputs/saved_stationary_export.m",), use_short_execution_path=True)
    return result


def _simion_request(path: Path) -> dict[str, Any]:
    request = _json(path)
    required = {"schema_version", "role", "resolved_design", "sampling_plan", "controller_pa",
                "producer_manifest", "origin_mm", "cell_mm", "electrode_ids_by_group"}
    if set(request) != required or request["schema_version"] != 1 or request["role"] != "multipole_stationary_simion_sampling_request":
        raise ValueError("Explicit SIMION stationary sampling request differs")
    for name in ("origin_mm", "cell_mm"):
        values = request[name]
        if (not isinstance(values, list) or len(values) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                or (name == "cell_mm" and any(value <= 0 for value in values))):
            raise ValueError("SIMION stationary origin/cell requires three finite values")
    groups = request["electrode_ids_by_group"]
    if (not isinstance(groups, Mapping) or set(groups) != {"1", "2"}
            or any(not isinstance(ids, list) or not ids or any(type(value) is not int or value <= 0 for value in ids)
                   for ids in groups.values())):
        raise ValueError("SIMION stationary electrode mapping differs")
    return request


def execute_simion_samples(session: Any, *, request: Mapping[str, Any], limits: Mapping[str, Any], source_id: str):
    """Sample two frozen voltage vectors in memory; never save PA or build IOB/Fly."""
    from msplatform.backends.simion.resources import native_resource_path
    if session.expected_operation_ids != ("sample_differential", "sample_static"):
        raise ValueError("SIMION stationary operation graph differs")
    resolved = _owned_input(session, "resolved_design", Path(request["resolved_design"]), "resolved_geometry.json")
    plan = _owned_input(session, "stationary_sampling_plan", Path(request["sampling_plan"]), "stationary_field_sampling_plan.json")
    controller_record = file_record(Path(request["controller_pa"]), "solver_native_binary")
    session.add_input("controller_pa", controller_record)
    points, authority = _points(session, resolved, plan, source_id)
    sampler = _owned_input(session, "stationary_sampler", native_resource_path("export_stationary_field_samples.lua"),
                           "native_sources/export_stationary_field_samples.lua")
    case_outputs = {}
    for field_case in sampling.FIELD_CASES:
        output = session.declare_file(session.result_dir / f"stationary_field_samples__{field_case}.csv", "required_evidence")
        voltages = []
        for group, ids in request["electrode_ids_by_group"].items():
            value = 100 * (3 - 2 * int(group)) if field_case == "differential" else 0
            voltages.extend(f"{electrode_id}={value}" for electrode_id in sorted(ids))
        arguments = ["--nogui", "--noprompt", "lua",
            project_run_path(sampler["path"], session.artifact_run_dir, session.run_dir), controller_record["path"],
            project_run_path(points, session.artifact_run_dir, session.run_dir),
            project_run_path(output, session.artifact_run_dir, session.run_dir), field_case,
            ",".join(format(value, ".17g") for value in request["origin_mm"]),
            ",".join(format(value, ".17g") for value in request["cell_mm"]), *voltages]
        session.run_process("sample_" + field_case, executable=session.context.tools["simion"],
            arguments=arguments, role="SIMION", stage="inspect", limits=limits,
            immutable_input_records=[controller_record, sampler,
                file_record(session.canonical_path(points), "required_evidence")])
        case_outputs[field_case] = output
    samples = session.declare_file(session.result_dir / "stationary_field_samples.csv", "required_evidence")
    with samples.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=sampling.FIELD_OUTPUT_COLUMNS)
        writer.writeheader()
        for field_case in sampling.FIELD_CASES:
            with case_outputs[field_case].open(encoding="utf-8-sig", newline="") as source:
                writer.writerows(csv.DictReader(source))
    validation = session.declare_file(session.result_dir / "stationary_field_sample_validation.json", "required_evidence")
    _validation_document(authority, samples, validation)
    outputs = [samples, validation, *case_outputs.values()]
    return dict(status="success", summary=dict(role="rf_simion_stationary_samples",
        refine_calls=0, fly_calls=0, iob_calls=0, scientific_qualification="not_granted"),
        output_paths=list(map(str, outputs)), required_output_paths=list(map(str, outputs)),
        retention_preserve_paths=[], manifest_extra_fields={})


def simion_samples(*, request_path: Path, budget: Path, run_id: str, source_id: str,
                   context: ExecutionContext) -> dict[str, Any]:
    request = _simion_request(request_path)
    resolved_budget, budget_record = _budget(budget, solver="simion")
    producer = file_record(Path(request["producer_manifest"]), "required_evidence")
    verify_record("SIMION stationary producer manifest", producer)
    require_completed_terminal_publication(Path(request["producer_manifest"]))
    authorities = [budget_record, file_record(request_path, "required_evidence"),
                   file_record(Path(sampling.__file__).resolve(), "required_evidence")]
    return run_managed_stage(context,
        descriptor=dict(project="rf_multipole_ion_optics", mode="rf_stationary_simion_samples",
                        software=["SIMION 2020", "Python 3.11"]),
        run_id=run_id, payload=dict(action="simion_stationary_samples", source_id=source_id,
                                    budget=resolved_budget),
        committed_new_bytes=resolved_budget["limits"]["transient_run_directory_bytes"],
        commitment_inputs=authorities,
        retention={"policy_version": 1, "class": "solver_review",
                   "reason": "RF stationary PA samples; no PA save, IOB, Fly or qualification"},
        source_references=[dict(manifest_record=producer)],
        expected_operation_ids=("sample_differential", "sample_static"), operation_dependencies={},
        action=partial(execute_simion_samples, request=request, limits=resolved_budget["limits"], source_id=source_id),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"), use_short_execution_path=True)


def validate_preregistration(document: Mapping[str, Any], *, solver: str, run_id: str,
        runtime_profile_id: str, design_profile_id: str, particle_source_profile_id: str,
        solver_numerics_profile_id: str, retention_class: str, expected_resolved_sha256: str,
        authority_paths: Mapping[str, Path], implementation_paths: Sequence[Path]) -> dict[str, Any]:
    """Validate explicit field preregistration against installed source identities."""
    expected = dict(maximum_commercial_run_count=1, automatic_retry_count=0, planned_run_id=run_id,
        runtime_profile_id=runtime_profile_id, design_profile_id=design_profile_id,
        particle_source_profile_id=particle_source_profile_id, stop_stage="field_solve",
        retention_class=retention_class)
    expected[solver + "_solver_numerics_profile_id"] = solver_numerics_profile_id
    if (document.get("schema_version") != 2
            or document.get("role") != f"multipole_{solver}_field_solver_isolation_preregistration"
            or document.get("status") != "authorized_not_run"
            or document.get("project_id") != "rf_multipole_ion_optics"
            or document.get("preregistered_before_run") is not True
            or document.get("authorization") != expected):
        raise ValueError("Field-solve preregistration identity or authorization differs")
    frozen = document.get("frozen_identity")
    if not isinstance(frozen, Mapping) or frozen.get("expected_run_parent_resolved_design_sha256") != expected_resolved_sha256:
        raise ValueError("Field-solve preregistration resolved-design identity differs")
    for name, path in authority_paths.items():
        if frozen.get(name) != file_record(path, "required_evidence")["sha256"]:
            raise ValueError("Field-solve preregistration authority hash differs: " + name)
    declared = document.get("frozen_implementation", {}).get("files")
    expected_files = [dict(path=str(path.resolve()),
                           sha256=file_record(path, "required_evidence")["sha256"])
                      for path in implementation_paths]
    if declared != expected_files:
        raise ValueError("Field-solve preregistration implementation inventory differs")
    field = document.get("field_sampling")
    if (not isinstance(field, Mapping) or field.get("role") != "multipole_stationary_field_sampling"
            or type(field.get("expected_point_count")) is not int or field["expected_point_count"] < 1
            or field.get("expected_row_count") != 2 * field["expected_point_count"]
            or field.get("field_cases") != list(sampling.FIELD_CASES)):
        raise ValueError("Field-solve preregistration sampling contract differs")
    plan_path = Path(field["plan_path"])
    if field["plan_sha256"] != file_record(plan_path, "required_evidence")["sha256"]:
        raise ValueError("Field-solve preregistration sampling-plan identity differs")
    report = document.get("required_report", {})
    required_tokens = {"CHECKPOINT=MESH_COMPLETE", "CHECKPOINT=STATIONARY_FIELDS_COMPLETE",
        "CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE", "STOP_STAGE=field_solve",
        "PARTICLE_PHYSICS_CREATED=0", "PARTICLE_STUDIES_CREATED=0",
        "FIELD_SOLVE_DIAGNOSTIC=PASS", "STATUS=PASS"}
    forbidden = {"PRIMARY_PARTICLE_CASE_COMPLETE", "CONTROL_PARTICLE_CASE_COMPLETE"}
    if (not required_tokens <= set(report.get("tokens", ()))
            or not forbidden <= set(report.get("forbidden_checkpoints", ()))):
        raise ValueError("Field-solve preregistration required report differs")
    return dict(document)


def _context(arguments: argparse.Namespace, *, tools: Mapping[str, Path]) -> ExecutionContext:
    return ExecutionContext(workspace=Path(arguments.workspace).absolute(),
        python_executable=Path(arguments.python).absolute(),
        powershell_executable=Path(arguments.powershell).absolute(), tools=tools,
        host_state_path=Path(arguments.host_state).absolute(), policy_path=Path(arguments.policy).absolute())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--resolved-design", type=Path, required=True)
    generate.add_argument("--sampling-plan", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    validate.add_argument("--authority", type=Path)
    authorize = commands.add_parser("authorize")
    authorize.add_argument("--resolved-design", type=Path, required=True)
    authorize.add_argument("--sampling-plan", type=Path, required=True)
    authorize.add_argument("--points", type=Path, required=True)
    authorize.add_argument("--source-id", required=True)
    authorize.add_argument("--output", type=Path, required=True)
    comparison = commands.add_parser("comparison-authority")
    comparison.add_argument("--reference-authority", type=Path, required=True)
    comparison.add_argument("--candidate-authority", type=Path, required=True)
    comparison.add_argument("--coordinate-tolerance-mm", type=float, required=True)
    comparison.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--reference", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--comparison-authority", type=Path)
    for name in ("saved-comsol", "simion-sample"):
        command = commands.add_parser(name)
        command.add_argument("--budget", type=Path, required=True)
        command.add_argument("--run-id", required=True)
        command.add_argument("--source-id", required=True)
        command.add_argument("--workspace", type=Path, required=True)
        command.add_argument("--python", type=Path, required=True)
        command.add_argument("--powershell", type=Path, required=True)
        command.add_argument("--host-state", type=Path, required=True)
        command.add_argument("--policy", type=Path, required=True)
        if name == "saved-comsol":
            command.add_argument("--parent-manifest", type=Path, required=True)
            command.add_argument("--sampling-plan", type=Path, required=True)
            command.add_argument("--comsol-launcher", type=Path, required=True)
            command.add_argument("--matlab-root", type=Path, required=True)
        else:
            command.add_argument("--request", type=Path, required=True)
            command.add_argument("--simion", type=Path, required=True)
    resume = commands.add_parser("resume-finalization")
    resume.add_argument("--result-path", type=Path, required=True)
    resume.add_argument("--workspace", type=Path, required=True)
    resume.add_argument("--python", type=Path, required=True)
    resume.add_argument("--powershell", type=Path, required=True)
    resume.add_argument("--host-state", type=Path, required=True)
    resume.add_argument("--policy", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "generate":
        rows = sampling.generate_stationary_field_sample_rows(
            _json(arguments.resolved_design), _json(arguments.sampling_plan))
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        sampling.write_stationary_field_sample_csv(rows, arguments.output)
        return 0
    if arguments.command == "validate":
        if arguments.authority is not None:
            sampling.validate_stationary_output_authority(_json(arguments.authority), arguments.input)
        _validation_document(arguments.authority, arguments.input, arguments.output) if arguments.authority else None
        if arguments.authority is None:
            records = sampling.load_stationary_field_output_csv(arguments.input)
            write_json_atomic(arguments.output, dict(schema_version=1,
                role="multipole_stationary_field_sample_validation", status="PASS",
                field_cases=list(sampling.FIELD_CASES),
                point_count=len({row.sample_id for row in records}), row_count=len(records)))
        return 0
    if arguments.command == "authorize":
        with arguments.points.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != sampling.SAMPLE_COLUMNS:
                raise sampling.StationaryFieldContractError("stationary point columns differ")
            points = list(reader)
        authority = sampling.build_stationary_sampling_authority(
            _json(arguments.resolved_design), _json(arguments.sampling_plan), points,
            points_path=arguments.points, source_id=arguments.source_id)
        write_json_atomic(arguments.output, authority)
        return 0
    if arguments.command == "comparison-authority":
        authority = sampling.build_multipole_comparison_authority(
            _json(arguments.reference_authority), _json(arguments.candidate_authority),
            coordinate_tolerance_mm=arguments.coordinate_tolerance_mm)
        write_json_atomic(arguments.output, authority)
        return 0
    if arguments.command == "compare":
        if arguments.comparison_authority is not None:
            _compare_generic(arguments)
        else:
            comparison = sampling.compare_stationary_field_outputs(
                sampling.load_stationary_field_output_csv(arguments.reference),
                sampling.load_stationary_field_output_csv(arguments.candidate))
            write_json_atomic(arguments.output, comparison)
        return 0
    if arguments.command == "resume-finalization":
        resume_finalization(_context(arguments, tools={}), arguments.result_path)
        return 0
    if arguments.command == "saved-comsol":
        context = _context(arguments, tools=dict(comsol_launcher=arguments.comsol_launcher.absolute(),
                                                 matlab_root=arguments.matlab_root.absolute()))
        saved_comsol(parent_manifest=arguments.parent_manifest, sampling_plan=arguments.sampling_plan,
            budget=arguments.budget, run_id=arguments.run_id, source_id=arguments.source_id, context=context)
        return 0
    if arguments.command == "simion-sample":
        context = _context(arguments, tools=dict(simion=arguments.simion.absolute()))
        simion_samples(request_path=arguments.request, budget=arguments.budget,
            run_id=arguments.run_id, source_id=arguments.source_id, context=context)
        return 0
    raise AssertionError(arguments.command)


def _compare_generic(arguments: argparse.Namespace) -> None:
    import pandas as pd
    from types import SimpleNamespace
    from msplatform.analysis.field_comparison import compare_static_field_samples, validate_static_comparison_authority
    from msplatform.contracts.rigid_transform import RigidTransform
    from msplatform.io.strict_json import load_json_object
    authority = load_json_object(arguments.comparison_authority)
    if set(authority) != {"schema_version", "role", "coordinate_tolerance_mm", *sampling.FIELD_CASES}:
        raise sampling.StationaryFieldContractError("multipole comparison authority fields differ")
    if (type(authority["schema_version"]) is not int or authority["schema_version"] != 1
            or authority["role"] != "multipole_static_field_comparison_authority"):
        raise sampling.StationaryFieldContractError("multipole comparison authority version or role differs")
    for field_case in sampling.FIELD_CASES:
        case = authority[field_case]
        validate_static_comparison_authority(dict(schema_version=authority["schema_version"],
            role="static_field_comparison_authority", coordinate_tolerance_mm=authority["coordinate_tolerance_mm"], **case))
    tables = [pd.read_csv(path, float_precision="round_trip", dtype={"sample_id": str, "region": str, "field_case": str},
                          keep_default_na=False) for path in (arguments.reference, arguments.candidate)]
    for table in tables:
        identities = [SimpleNamespace(sample_id=row["sample_id"], region=row["region"], field_case=row["field_case"],
            x_mm=float(row["x_mm"]), y_mm=float(row["y_mm"]), z_mm=float(row["z_mm"]))
            for row in table.to_dict("records")]
        sampling._validate_paired_field_cases(identities)
    generic = {}
    for field_case in sampling.FIELD_CASES:
        frames = []
        for label, table in zip(("reference", "candidate"), tables, strict=True):
            frame = table[table["field_case"] == field_case].copy().rename(columns={"sample_id": "point_id"})
            states = authority[field_case][label]["status_by_point_id"]
            frame["status"] = [states[str(point)] for point in frame["point_id"]]
            frames.append(frame)
        values = authority[field_case]
        generic[field_case] = compare_static_field_samples(*frames,
            reference_metadata=values["reference"]["metadata"], candidate_metadata=values["candidate"]["metadata"],
            reference_transform=RigidTransform.from_contract(values["reference"]["transform"]),
            candidate_transform=RigidTransform.from_contract(values["candidate"]["transform"]),
            coordinate_tolerance_mm=authority["coordinate_tolerance_mm"])
    write_json_atomic(arguments.output, dict(schema_version=1, role="multipole_static_field_comparison",
        status="DESCRIPTIVE_ONLY", field_cases=generic))


if __name__ == "__main__":
    raise SystemExit(main())
