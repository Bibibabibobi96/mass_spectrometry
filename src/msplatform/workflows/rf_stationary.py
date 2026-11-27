"""Installed RF stationary sample recipes over the public execution owner."""
from __future__ import annotations

import csv
import json
import math
from functools import partial
from pathlib import Path
from typing import Any, Mapping, Sequence

from msplatform.components.rf_multipole import stationary_field_sampling as sampling
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import run_managed_stage
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
                 source_id: str, context: ExecutionContext, artifact_store=None) -> dict[str, Any]:
    from contextlib import ExitStack, nullcontext
    from msplatform.execution.native_source_guard import guard_historical_run
    from msplatform.execution.owner import current_managed_native_store, standalone_native_store
    from msplatform.io.file_identity import guarded_file_identity
    parent_scope = current_managed_native_store()
    if artifact_store is None and parent_scope is None:
        raise ValueError('RF saved export requires an explicit ArtifactStore or protected parent scope')
    store = artifact_store if artifact_store is not None else parent_scope['store']
    if parent_scope is not None and parent_scope['store'] is not store:
        raise ValueError('RF saved export must use the parent Store')
    resolved_budget, budget_record = _budget(budget, solver="comsol")
    plan_record = file_record(sampling_plan, "required_evidence")
    manifest_record = file_record(parent_manifest, 'required_evidence')
    with ExitStack() as guards:
        for record in (budget_record, plan_record):
            guards.enter_context(guarded_file_identity(Path(record['path']), expected_bytes=record['bytes'],
                                                        expected_sha256=record['sha256']))
        if _budget(budget, solver='comsol')[0] != resolved_budget:
            raise ValueError('RF saved export budget changed during admission')
        manifest_path = Path(manifest_record['path']).resolve(strict=True)
        assets = set()
        if manifest_path.is_relative_to(store.root / 'assets'):
            parts = manifest_path.relative_to(store.root).parts
            if len(parts) < 6 or parts[:2] != ('assets', 'native_stage'):
                raise ValueError('RF saved source Store identity differs')
            asset = parts[3]
            asset_path = guards.enter_context(store.claim_verified(asset))
            if asset_path != store.root.joinpath(*parts[:4]):
                raise ValueError('RF saved source Store owner differs')
            assets.add(asset)
        source = guards.enter_context(guard_historical_run(manifest_record,
            expected_project='rf_multipole_ion_optics', expected_mode='resolved_design_transport'))
        parent, _, model, resolved = _parent_model(parent_manifest)
        if source.output('results/finite_3d_transport.mph') != model:
            raise ValueError('RF saved model identity differs')
        if source.input('multipole_resolved_design') != resolved:
            raise ValueError('RF saved resolved design identity differs')
        if parent_scope is not None and parent_scope['retain_source_assets']:
            parent_scope['required_source_assets'].update(assets)
        scope = (standalone_native_store(store, task_key='rf-saved:' + run_id,
            budget=resolved_budget['limits']['transient_run_directory_bytes'], required_assets=tuple(assets))
            if parent_scope is None else nullcontext())
        with scope:
            return _saved_comsol_guarded(context=context, parent=parent, model=model, resolved=resolved,
                resolved_budget=resolved_budget, budget_record=budget_record, plan_record=plan_record,
                sampling_plan=sampling_plan, run_id=run_id, source_id=source_id)


def _saved_comsol_guarded(*, context, parent, model, resolved, resolved_budget, budget_record,
                           plan_record, sampling_plan, run_id, source_id):
    resolved_record = file_record(Path(resolved["path"]), "required_evidence")
    return run_managed_stage(context,
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
        expected_relative_paths=("inputs/saved_stationary_export.m",), use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api)


def _field_runtime(path: Path, budget: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _json(path)
    if (runtime.get("schema_version") != 1
            or runtime.get("role") != "multipole_resolved_runtime_profile"
            or runtime.get("project_id") != "rf_multipole_ion_optics"
            or runtime.get("stop_stage") != "field_solve"):
        raise ValueError("Explicit RF field_solve resolved runtime required")
    design = runtime.get("design_profile_resolution", {}).get("resolved_design", {})
    particle = runtime.get("particle_source", {})
    numerics = runtime.get("solver_numerics", {}).get("comsol", {})
    expected = dict(runtime_profile_id=runtime.get("runtime_profile_id"),
                    design_profile_id=runtime.get("design_profile_id"),
                    particle_source_profile_id=particle.get("profile_id"),
                    solver_numerics_profile_id=numerics.get("profile_id"),
                    authorized_run_id=budget.get("authorized_run_id"),
                    expected_run_parent_resolved_design_sha256=design.get("resolved_sha256"))
    if (design.get("role") != "multipole_resolved_design_do_not_edit"
            or not isinstance(design.get("resolved_sha256"), str)
            or not isinstance(particle.get("path"), str) or not isinstance(numerics.get("values"), Mapping)
            or any(budget.get(name) != value for name, value in expected.items())):
        raise ValueError("RF field runtime, design, numerics and budget identities differ")
    return runtime


def execute_comsol_fields(session: Any, *, runtime: Mapping[str, Any], science_task: Path,
                          plan_source: Path, limits: Mapping[str, Any], source_id: str) -> dict[str, Any]:
    from msplatform.backends.comsol.rf_stationary_field import run_field_operations
    resolved_source = session.declare_file(session.input_dir / "stationary_resolved_design.json", "required_evidence")
    write_json_atomic(resolved_source, runtime["design_profile_resolution"]["resolved_design"])
    _owned_input(session, "stationary_sampling_plan", plan_source, "stationary_field_sampling_plan.json")
    points, _ = _points(session, file_record(resolved_source, "required_evidence"),
                        file_record(plan_source, "required_evidence"), source_id)
    samples = session.declare_file(session.result_dir / "stationary_field_samples.csv", "required_evidence")
    validation = session.declare_file(session.result_dir / "stationary_field_sample_validation.json", "required_evidence")
    model = session.declare_file(session.result_dir / "finite_3d_transport.mph", "solver_native_binary")
    try:
        native = run_field_operations(session, runtime=runtime, science_task=science_task,
                                      points=points, samples=samples, limits=limits)
        _validation_document(session.input_dir / "stationary_field_sampling_authority.json", samples, validation)
    except BaseException as failure:
        failure.failure_output_paths = [path for path in (model, samples)
                                        if session.canonical_path(path).is_file()]
        raise
    outputs = [model, samples, validation, native["verification"]]
    return dict(status="success", summary=dict(role="rf_stationary_field_parent",
        native_solves=1, native_operations=2, verification_compute_calls=0,
        fly_calls=0, solution_tags=native["solution_tags"], scientific_qualification="not_granted"),
        output_paths=list(map(str, outputs)), required_output_paths=list(map(str, outputs)),
        retention_preserve_paths=[], manifest_extra_fields={})


def solve_comsol(*, resolved_runtime: Path, preregistration: Path, science_task: Path,
                 sampling_plan: Path, budget: Path, run_id: str, source_id: str,
                 context: ExecutionContext, artifact_store=None) -> dict[str, Any]:
    from msplatform.backends.comsol import rf_stationary_field
    from msplatform.backends.comsol.resources import native_resource_path
    from msplatform.execution.owner import current_managed_native_store
    parent = current_managed_native_store()
    if artifact_store is None and parent is None:
        raise ValueError('RF stationary solve requires an explicit ArtifactStore or protected parent scope')
    if parent is not None and artifact_store is not None and parent['store'] is not artifact_store:
        raise ValueError('RF stationary solve must use the parent Store')
    resolved_budget, budget_record = _budget(budget, solver="comsol")
    runtime = _field_runtime(resolved_runtime, resolved_budget)
    design = runtime["design_profile_resolution"]["resolved_design"]
    particle = runtime["particle_source"]
    profile = runtime["design_profile_resolution"]
    authorities = {
        "runtime_profiles_sha256": Path(runtime["runtime_profile_registry_path"]),
        "engineering_budget_sha256": Path(runtime["engineering_budget"]["path"]),
        "particle_source_profiles_sha256": Path(particle["registry_path"]),
        "design_profiles_sha256": Path(profile["profiles_path"]),
        "comsol_solver_numerics_sha256": Path(runtime["solver_numerics_registry_paths"]["comsol"]),
    }
    implementation = [Path(rf_stationary_field.__file__).resolve(), Path(__file__).resolve(),
        science_task.resolve(), native_resource_path("read_rf_saved_stationary_solution.m"),
        native_resource_path("export_comsol_stationary_field_samples.m")]
    rows = sampling.generate_stationary_field_sample_rows(design, _json(sampling_plan))
    registration = validate_preregistration(_json(preregistration), solver="comsol", run_id=run_id,
        runtime_profile_id=runtime["runtime_profile_id"], design_profile_id=runtime["design_profile_id"],
        particle_source_profile_id=particle["profile_id"],
        solver_numerics_profile_id=runtime["solver_numerics"]["comsol"]["profile_id"],
        retention_class="solver_review", expected_resolved_sha256=design["resolved_sha256"],
        authority_paths=authorities, implementation_paths=implementation)
    if registration["field_sampling"]["expected_point_count"] != len(rows):
        raise ValueError("RF field preregistration sample count differs")
    prereg_record = file_record(preregistration, "required_evidence")
    plan_record = file_record(sampling_plan, "required_evidence")
    runtime_record = file_record(resolved_runtime, "required_evidence")
    result = run_managed_stage(context, artifact_store=artifact_store,
        descriptor=dict(project="rf_multipole_ion_optics", mode="rf_stationary_field_solve",
                        software=["COMSOL 6.4", "MATLAB R2025b", "Python 3.11"]),
        run_id=run_id, payload=dict(action="solve_comsol_stationary_fields", source_id=source_id,
                                    preregistration=registration, budget=resolved_budget),
        committed_new_bytes=resolved_budget["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[budget_record, prereg_record, plan_record, runtime_record],
        retention={"policy_version": 1, "class": "solver_review",
                   "reason": "RF stationary differential/static parent and cold verification; no Fly or qualification"},
        source_references=[], expected_operation_ids=("solve_stationary_fields", "verify_stationary_fields"),
        operation_dependencies={"verify_stationary_fields": ["solve_stationary_fields"]},
        action=partial(execute_comsol_fields, runtime=runtime, science_task=science_task,
                       plan_source=sampling_plan, limits=resolved_budget["limits"], source_id=source_id),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
        expected_relative_paths=("inputs/solve_stationary_fields.m", "inputs/verify_stationary_fields.m"),
        use_short_execution_path=True, completion_api=no_particle_batch_completion_api)
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
                   context: ExecutionContext, artifact_store=None) -> dict[str, Any]:
    from contextlib import ExitStack, nullcontext
    from msplatform.execution.native_source_guard import guard_historical_run
    from msplatform.execution.owner import current_managed_native_store, standalone_native_store
    from msplatform.io.file_identity import guarded_file_identity
    parent_scope = current_managed_native_store()
    if artifact_store is None and parent_scope is None:
        raise ValueError('RF SIMION sampling requires an explicit ArtifactStore or protected parent scope')
    store = artifact_store if artifact_store is not None else parent_scope['store']
    if parent_scope is not None and parent_scope['store'] is not store:
        raise ValueError('RF SIMION sampling must use the parent Store')
    request = _simion_request(request_path)
    resolved_budget, budget_record = _budget(budget, solver="simion")
    producer = file_record(Path(request["producer_manifest"]), "required_evidence")
    with ExitStack() as guards:
        manifest_path = Path(producer['path']).resolve(strict=True)
        assets = set()
        if manifest_path.is_relative_to(store.root / 'assets'):
            parts = manifest_path.relative_to(store.root).parts
            if len(parts) < 6 or parts[:2] != ('assets', 'native_stage'):
                raise ValueError('RF SIMION source Store identity differs')
            asset = parts[3]
            asset_path = guards.enter_context(store.claim_verified(asset))
            if asset_path != store.root.joinpath(*parts[:4]):
                raise ValueError('RF SIMION source Store owner differs')
            assets.add(asset)
        source = guards.enter_context(guard_historical_run(producer,
            expected_project='rf_multipole_ion_optics', expected_mode='resolved_design_transport'))
        controller = Path(request['controller_pa']).resolve(strict=True)
        if not controller.is_relative_to(source.root):
            raise ValueError('RF SIMION controller is outside its producer')
        source.output(controller.relative_to(source.root).as_posix())
        for path in (request_path, budget, Path(request['resolved_design']), Path(request['sampling_plan'])):
            record = file_record(path, 'required_evidence')
            guards.enter_context(guarded_file_identity(Path(record['path']), expected_bytes=record['bytes'],
                                                        expected_sha256=record['sha256']))
        if _simion_request(request_path) != request or _budget(budget, solver='simion')[0] != resolved_budget:
            raise ValueError('RF SIMION author inputs changed during admission')
        if parent_scope is not None and parent_scope['retain_source_assets']:
            parent_scope['required_source_assets'].update(assets)
        scope = (standalone_native_store(store, task_key='rf-simion-samples:' + run_id,
            budget=resolved_budget['limits']['transient_run_directory_bytes'], required_assets=tuple(assets))
            if parent_scope is None else nullcontext())
        with scope:
            return _simion_samples_guarded(context=context, request=request, request_path=request_path,
                producer=producer, resolved_budget=resolved_budget, budget_record=budget_record,
                run_id=run_id, source_id=source_id)


def _simion_samples_guarded(*, context, request, request_path, producer, resolved_budget,
                             budget_record, run_id, source_id):
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
        action_record=file_record(Path(__file__).resolve(), "required_evidence"), use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api)


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


def _context(arguments: Any, *, tools: Mapping[str, Path]) -> ExecutionContext:
    return ExecutionContext(workspace=Path(arguments.workspace).absolute(),
        python_executable=Path(arguments.python).absolute(),
        powershell_executable=Path(arguments.powershell).absolute(), tools=tools,
        host_state_path=Path(arguments.host_state).absolute(), policy_path=Path(arguments.policy).absolute())






def _compare_generic(arguments: Any) -> None:
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
