"""Managed geometry-only COMSOL build of a complete Assembly."""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import datetime
from functools import partial
import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

from msplatform.assembly.model import Assembly
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.native_execution import (
    declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion,
)
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.context import ExecutionContext
from msplatform.execution.run_session import RunSession
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact

_NATIVE_SOURCES = (
    'comsolstartup.m', 'assembly_geometry_stage.m', 'build_assembly_reference_geometry.m',
    'validate_assembly_reference_selections.m', 'classify_assembly_reference_faces.m',
)


def _validation(value: Mapping[str, float], box: Mapping[str, Sequence[float]]) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != {'position_mm', 'normal_abs'}:
        raise ValueError('geometry validation requires explicit position_mm and normal_abs')
    result = dict(value)
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in result.values()):
        raise ValueError('geometry validation values must be finite numbers')
    width = min(b - a for a, b in zip(box['min'], box['max'], strict=True))
    if result['position_mm'] < 0 or 2 * result['position_mm'] >= width or not 0 <= result['normal_abs'] < 1:
        raise ValueError('invalid geometry sanity validation values')
    return result


def build_geometry(assembly: Assembly, *, outer_box_mm: Mapping[str, Sequence[float]],
                   geometry_validation: Mapping[str, float], context: ExecutionContext) -> OpenedArtifact:
    """Build and cold-reopen native geometry without physics or mesh.

    Outer-box coordinates and position sanity are in mm; normal sanity is
    dimensionless. Sanity samples do not establish whole-face accuracy.
    """
    if not isinstance(assembly, Assembly):
        raise ContractError('COMSOL build_geometry requires a complete Assembly')
    selected = Assembly(assembly.composition_plan, assembly.components)
    snapshot = dict(composition_plan=selected.composition_plan,
                    components_resolved=selected.components_resolved, components_source=selected.components_source)
    projection = project_assembly_geometry(snapshot, outer_box_mm=copy.deepcopy(outer_box_mm))
    validation = _validation(geometry_validation, projection['outer_box_mm'])
    for name in ('comsol_launcher', 'matlab_root'):
        path = context.tools.get(name)
        if path is None or not (path.is_dir() if name == 'matlab_root' else path.is_file()):
            raise ContractError('COMSOL geometry requires explicit available tool: ' + name)
    stage, authority = read_stage_policy(context, 'build_comsol_geometry', required_roles=('solver_native_binary',))
    if stage.get('runtime'):
        raise ContractError('COMSOL geometry has no additional runtime overrides')
    result = run_managed_stage(context,
        descriptor=dict(project='instrument_assembly', mode='geometry_only', software=['COMSOL', 'MATLAB']),
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__build__comsol__geometry-' + uuid4().hex[:12],
        payload=dict(action='build_comsol_geometry', assembly=snapshot, projection=projection,
                     geometry_validation=validation, stage_policy=stage),
        committed_new_bytes=stage['limits']['transient_run_directory_bytes'], commitment_inputs=[authority],
        retention=stage['artifact_retention'], expected_operation_ids=('build_geometry', 'reopen_geometry'),
        operation_dependencies={'reopen_geometry': ['build_geometry']},
        action=partial(execute_geometry, projection=projection, validation=validation, limits=stage['limits']),
        action_record=file_record(Path(__file__).resolve(), 'required_evidence'), use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api)
    return open_artifact({'manifest': result['manifest'], 'product_id': 'geometry'}, expected_kind='geometry_artifact')


def _check_report(row: Mapping[str, Any], operation: str, projection: Mapping[str, Any], model: Path) -> None:
    keys = [group['instance_id'] + '/' + group['electrode_group_id'] for group in projection['electrode_groups']]
    if (not isinstance(row, dict) or row.get('scope') != 'geometry_only' or row.get('operation') != operation
            or row.get('member_count') != len(projection['members']) or row.get('group_count') != len(keys)
            or row.get('group_keys') != keys or Path(row.get('model_path', '')).resolve() != model.resolve()
            or type(row.get('geometry_domains')) is not int or row['geometry_domains'] <= 0
            or any(type(row.get(name)) is not int or row[name] != 0
                   for name in ('physics_count', 'mesh_count', 'study_count', 'solver_count'))):
        raise ValueError('COMSOL geometry report differs from explicit projection')
    if (not isinstance(row.get('group_faces'), list) or len(row['group_faces']) != len(keys)
            or not all(row['group_faces']) or not row.get('vacuum_domains') or not row.get('outer_faces')):
        raise ValueError('COMSOL geometry report lacks native selections')


def _check_cold_report(first: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    for key in ('group_keys', 'group_faces', 'vacuum_domains', 'outer_faces', 'geometry_domains'):
        if row[key] != first[key]:
            raise ValueError('COMSOL geometry cold reopen differs: ' + key)


def execute_geometry(session: RunSession, *, projection: Mapping[str, Any],
                     validation: Mapping[str, float], limits: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze sources and execute geometry creation and independent cold read."""
    if session.expected_operation_ids != ('build_geometry', 'reopen_geometry'):
        raise ValueError('COMSOL geometry requires build followed by cold reopen')
    launcher, sources = freeze_native_sources(session, _NATIVE_SOURCES)
    scene = session.declare_file(session.input_dir / 'projection.json', 'required_evidence')
    sanity = session.declare_file(session.input_dir / 'geometry-validation.json', 'required_evidence')
    for name, path, value in (('projection', scene, projection), ('geometry_validation', sanity, validation)):
        write_json_atomic(path, value)
        session.add_input(name, file_record(path, 'required_evidence'))
    scene_record = file_record(scene, 'required_evidence')
    sanity_record = file_record(sanity, 'required_evidence')
    session.add_input('comsol_launcher', file_record(session.context.tools['comsol_launcher'], 'required_evidence'))
    model = session.declare_file(session.run_dir / 'geometry-only.mph', 'solver_native_binary')
    descriptor = session.declare_file(session.result_dir / 'geometry-descriptor.json', 'required_evidence')
    matlab = launcher.parent.parent / 'matlab'
    host = json.dumps({name: str(getattr(session.context, name)) for name in
                       ('workspace', 'python_executable', 'host_state_path', 'policy_path')})
    reports, first, persisted = {}, None, []
    for operation, mode in (('build_geometry', 'build'), ('reopen_geometry', 'reopen')):
        report = session.declare_file(session.result_dir / (operation + '.json'), 'required_evidence')
        bootstrap = session.declare_file(session.log_dir / (operation + '.bootstrap.log'), 'required_evidence')
        completion = session.declare_file(session.log_dir / (operation + '.launcher.json'), 'required_evidence')
        task = session.declare_file(session.input_dir / (operation + '.m'), 'required_evidence')
        runtime = session.run_dir / 'comsol_runtime' / operation
        runtime.mkdir(parents=True)
        call = 'assembly_geometry_stage(' + ','.join(map(matlab_text, (scene, model, descriptor, sanity, mode))) + ')'
        task.write_text('addpath(' + matlab_text(matlab) + ');\nresult=' + call + ';\n'
                        'fid=fopen(' + matlab_text(report) + ",'w','n','UTF-8');\n"
                        "assert(fid>=0); cleanup=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result));\n",
                        encoding='utf-8', newline='\n')
        guards = [*sources, scene_record, sanity_record, file_record(task, 'required_evidence'), *persisted]
        args = ['-NoProfile', '-File', str(launcher), '-HostContextJson', host, '-WorkingDirectory', str(session.run_dir),
                '-ComsolLauncherPath', str(session.context.tools['comsol_launcher']), '-MatlabRootPath',
                str(session.context.tools['matlab_root']), '-TaskScript', str(task), '-ReportPath', str(bootstrap),
                '-StartupAttempts', '1', '-RunId', session.run_id, '-RunDir', str(runtime), '-CompletionPath', str(completion)]
        primary = None
        try:
            session.run_process(operation, executable=session.context.powershell_executable, arguments=args,
                                role='COMSOL', stage='solver', limits=limits, immutable_input_records=guards)
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                declare_runtime_files(session, runtime, bootstrap=bootstrap)
            except BaseException as error:
                if primary is None:
                    raise
                primary.add_note('COMSOL runtime diagnostic preservation failed: ' + repr(error))
        for record in guards:
            verify_record('COMSOL geometry immutable input', record)
        require_launcher_completion(completion, session.run_id)
        if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'):
            raise ValueError('COMSOL geometry bootstrap failed')
        row = json.loads(report.read_text(encoding='utf-8-sig'))
        _check_report(row, mode, projection, model)
        if mode == 'build':
            first = row
            persisted = [file_record(model, 'solver_native_binary'), file_record(descriptor, 'required_evidence')]
        else:
            _check_cold_report(first, row)
        reports[operation] = report
    metadata = dict(backend='comsol', geometry_materialized=True, native_reopen_verified=True,
                    field_status='not_solved', source_status='not_requested', scientific_qualification='not_granted',
                    scope='geometry_only', geometry_validation=validation,
                    assembly_frame_id=projection['assembly_frame_id'], electrode_groups=projection['electrode_groups'])
    records = dict(projection=scene_record, geometry_validation=sanity_record,
                   model=persisted[0], descriptor=persisted[1],
                   **{name: file_record(path, 'required_evidence') for name, path in reports.items()})
    outputs = [model, descriptor, *reports.values()]
    return dict(status='success', summary=metadata, output_paths=[str(path) for path in outputs],
                required_output_paths=[str(path) for path in outputs], retention_preserve_paths=[],
                manifest_extra_fields=dict(products=dict(geometry=dict(schema_version=1, kind='geometry_artifact',
                    status='complete', metadata=metadata, data=records))))
