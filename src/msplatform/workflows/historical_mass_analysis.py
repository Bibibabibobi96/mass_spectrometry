"""Store-owned analysis of authenticated historical mass-spectrum runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
from functools import partial
from msplatform.execution.owner import standalone_native_store
from msplatform.execution.run_session import RunSession
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.results.historical_mass_spectrum import OUTPUT_NAMES, read_historical_mass_selection

PROJECT = "single_reflection_oa_tof_mass_analyzer"
MODE = "mass_spectrum_candidate"
ACTION = "oa_tof_mass_spectrum"

def _json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def _completion_api():
    from msplatform.backends.simion import native_completion
    return native_completion

def _freeze_code(session: RunSession, task_script: Path | None, resolved: Path) -> tuple[dict[str, Any], Path | None, Path]:
    """Freeze installed origins and the selected backend retrace task."""
    from importlib.resources import files
    from msplatform.execution.inputs import enumerate_python_sources, freeze_file, freeze_python_package

    provider = Path(str(files("msplatform"))).resolve()
    source_root = provider.parent
    selected = enumerate_python_sources(
        source_root, package_roots=("msplatform",),
        resource_suffixes=(".json", ".ps1", ".lua", ".m", ".gem", ".iob"),
        require_python_source=True,
    )
    code_root = session.input_dir / "code"
    # Declare before materialization so even an interrupted copy remains classifiable.
    for relative in selected:
        session.declare_file(code_root / relative, "required_evidence")
    package = freeze_python_package(source_root, code_root, relative_paths=selected)
    def code_inputs():
        for index, entry in enumerate(package["files"]):
            path = session.declare_file(Path(entry["path"]), "required_evidence")
            yield f"study_code_{index:04d}", dict(
                path=str(path), exists=True, bytes=path.stat().st_size,
                sha256=str(entry["sha256"]).upper(), retention_role="required_evidence")
    session.add_inputs(code_inputs())
    task_target = None
    geometry_target = session.declare_file(
        code_root / "src/msplatform/components/single_reflection_oa_tof/config/resolved_geometry.json", "required_evidence")
    geometry_target.parent.mkdir(parents=True, exist_ok=True)
    freeze_file(resolved, geometry_target)
    geometry_record = file_record(geometry_target, "required_evidence")
    package["files"].append(dict(
        relative_path="src/msplatform/components/single_reflection_oa_tof/config/resolved_geometry.json",
        path=str(geometry_target), sha256=geometry_record["sha256"]))
    session.add_input("frozen_geometry", geometry_record)
    inventory_path = session.declare_file(session.input_dir / "code_inventory.json", "required_evidence")
    write_json_atomic(inventory_path, package)
    session.add_input("code_inventory", file_record(inventory_path, "required_evidence"))
    return package, task_target, geometry_target


def _frozen_guards(package: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Bind current files to their original inventory, never to altered bytes."""
    guards = []
    for row in package["files"]:
        path = Path(row["path"])
        if not path.is_file():
            raise RuntimeError(f"Frozen Python dependency is missing: {path}")
        record = file_record(path, "required_evidence")
        if record["sha256"] != str(row["sha256"]).upper():
            raise RuntimeError(f"Frozen Python dependency hash differs: {path}")
        guards.append(record)
    return guards


def _analysis_action(session: RunSession, *, selection: dict[str, Any],
                     stage: dict[str, Any]) -> dict[str, Any]:
    from msplatform.execution.inputs import freeze_file
    mode = session.declare_file(session.input_dir / "mass_spectrum.json", "required_evidence")
    geometry = session.declare_file(session.input_dir / "resolved_geometry.json", "required_evidence")
    try:
        input_guards = []
        for name, target in (("mode_config", mode), ("resolved_geometry", geometry)):
            record = dict(freeze_file(Path(selection["inputs"][name]["path"]), target),
                          retention_role="required_evidence")
            if record["sha256"] != selection["inputs"][name]["sha256"]:
                raise ValueError(f"Parent {name} changed before analysis")
            session.add_input(name, record)
            input_guards.append(record)
        package, _, _ = _freeze_code(session, None, geometry)
        worker_selection = dict(selection, frozen_mode=str(mode), frozen_geometry=str(geometry))
        selection_path = session.declare_file(session.input_dir / "source_selection.json", "required_evidence")
        write_json_atomic(selection_path, worker_selection)
        selection_record = file_record(selection_path, "required_evidence")
        session.add_input("source_selection", selection_record)
        guards = _frozen_guards(package)
        guards += [selection_record, *input_guards, *selection["exports"].values()]
        outputs = [session.declare_file(session.result_dir / name, "required_evidence")
                   for name in OUTPUT_NAMES]
        bootstrap = ("import runpy,sys;from pathlib import Path;root=Path(sys.argv[1]);"
                     "worker=root/'msplatform/execution/historical_mass_spectrum_worker.py';"
                     "worker.is_file() or (_ for _ in ()).throw(FileNotFoundError(f'Frozen worker is absent: {worker}'));"
                     "sys.path.insert(0,str(root));sys.argv=sys.argv[2:];"
                     "runpy.run_module('msplatform.execution.historical_mass_spectrum_worker',"
                     "run_name='__main__')")
        for record in guards:
            try:
                verify_record("Frozen Python dependency", dict(record))
            except AssertionError as error:
                if not Path(record["path"]).is_file():
                    raise RuntimeError(f"Frozen Python dependency is missing: {record['path']}") from error
                raise RuntimeError(f"Frozen Python dependency hash differs: {record['path']}") from error
        from msplatform.execution.processes import ProcessExecutionError
        try:
            receipt = session.run_process("python-analysis", executable=session.context.python_executable,
                arguments=["-I", "-B", "-c", bootstrap, str(session.input_dir / "code"),
                           "mass-spectrum-analysis", "--selection", str(selection_path),
                           "--output", str(session.result_dir), "--code-root", str(session.input_dir / "code")],
                role="GATE", stage="postprocess", limits=stage["limits"],
                immutable_input_records=guards)
        except ProcessExecutionError as error:
            if error.observed_process_exit_confirmed:
                stderr = session.log_dir / "operation_0001.stderr.log"
                detail = stderr.read_text(encoding="utf-8", errors="replace")[-4000:] if stderr.is_file() else str(error)
                raise RuntimeError("Mass-spectrum reanalysis failed: " + detail) from error
            raise
        if receipt["observation"]["exit_code"] != 0:
            raise RuntimeError("Mass-spectrum reanalysis failed; see analysis stderr")
        config = _json(session.run_config)
        config["parameters"].update(lifecycle_stage="complete", simulation_calls=0,
            solver_native_calls=0, pa_materializations=0, parent_run_id=selection["run_id"])
        write_json_atomic(session.run_config, config)
        return dict(status="success", summary=dict(role="oa_tof_candidate_mass_spectrum_analysis",
            analysis_only=True, parent_run_id=selection["run_id"], solver_native_calls=0,
            pa_materializations=0, formal_gate_passed=False, resolution_claim_allowed=False,
            native_path_preparation={"calls": 1 if session.package.get("execution_alias") else 0}),
            output_paths=outputs, required_output_paths=outputs,
            retention_preserve_paths=[], manifest_extra_fields={})
    except Exception as primary:
        primary.failure_output_paths = [Path(path) for path in session.file_roles
            if Path(path).is_file() and Path(path).is_relative_to(session.artifact_run_dir)]
        raise


def analyze_recorded_mass_spectrum(context, *, source_manifest: Path, run_id: str,
                                   artifact_store, committed_new_bytes: int) -> dict[str, Any]:
    """Analyze a sealed v1 run using Store and the managed process owner.

    The historical source is held read-only until its worker and Store publication
    finish. Failed and incomplete historical runs are rejected.
    """
    if type(committed_new_bytes) is not int or committed_new_bytes <= 0:
        raise ValueError("committed_new_bytes must be a positive integer")
    manifest_record = file_record(Path(source_manifest).resolve(strict=True), "required_evidence")
    stage, policy_record = read_stage_policy(context, ACTION)
    with guard_historical_run(manifest_record, expected_project=PROJECT, expected_mode=MODE) as source:
        selection = read_historical_mass_selection(source, manifest_record)
        protected = [Path(row["path"]) for row in selection["exports"].values()]
        # The historical source remains guarded until stage and Store publication finish.
        with standalone_native_store(artifact_store, task_key='historical-analysis:' + run_id,
                                     budget=committed_new_bytes) as scope:
            result = run_managed_stage(context,
                descriptor=dict(project=PROJECT, mode="mass_spectrum_analysis", software=["Python 3.11"]),
                run_id=run_id, payload=dict(lifecycle_stage="prepared", analysis_only=True,
                    parent_run_id=selection["run_id"], formal_gate_passed=False),
                committed_new_bytes=committed_new_bytes,
                commitment_inputs=[policy_record, manifest_record],
                retention=stage["artifact_retention"], expected_operation_ids=["python-analysis"],
                operation_dependencies={}, action=partial(_analysis_action, selection=selection, stage=stage),
                action_record=file_record(Path(__file__).resolve(), "required_evidence"),
                protected_paths=protected, use_short_execution_path=True,
                completion_api=_completion_api, artifact_store=artifact_store)
            if result.get('status') != 'success':
                raise RuntimeError('historical mass analysis stage failed: ' + str(result.get('status')))
        return dict(result, store_run_id=scope['parent_run_id'], store_run_path=str(scope['published_path']))
