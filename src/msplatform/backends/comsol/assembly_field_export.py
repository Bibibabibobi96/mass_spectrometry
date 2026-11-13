"""Export a saved Assembly stationary solution as masked world scalar samples."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

from msplatform.backends.comsol.assembly_field_solution import validate_solution_readback
from msplatform.backends.comsol.native_execution import (
    declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion,
)
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import (
    file_record, require_completed_terminal_publication, validate_file_record, verify_record,
)
from msplatform.results.artifacts import open_artifact

_REVIEWED_ADAPTED_WRITER_SHA256 = '2B5F211548D22F8D06B4BAAB88E85FF292A271E7E217877D96C1734A25C89A5B'

_NATIVE_SOURCES = ('comsolstartup.m', 'export_assembly_world_scalar_field.m',
                   'sample_scalar_grid_blocks.m', 'read_assembly_stationary_solution.m')


def validate_grid(grid: Mapping[str, Any], projection: Mapping[str, Any], solution: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an explicit full-world grid against the selected saved solution."""
    required = {'frame_id', 'origin_mm', 'pitch_mm', 'dimensions', 'block_points',
                'study_tag', 'solution_tag', 'dataset_tag'}
    if not isinstance(grid, Mapping) or set(grid) != required:
        raise ValueError('explicit frame, grid, block size and stored solution tags required')
    if not isinstance(grid['frame_id'], str) or not grid['frame_id'] or grid['frame_id'] != projection['assembly_frame_id']:
        raise ValueError('scalar grid frame differs from Assembly frame')
    for name in ('study_tag', 'solution_tag', 'dataset_tag'):
        if not isinstance(grid[name], str) or not grid[name] or grid[name] != solution.get(name):
            raise ValueError('scalar grid stored solution identity differs: ' + name)
    origin, pitch, dimensions = grid['origin_mm'], grid['pitch_mm'], grid['dimensions']
    if any(not isinstance(value, (list, tuple)) or len(value) != 3 for value in (origin, pitch, dimensions)):
        raise ValueError('scalar grid requires three coordinates, pitches and dimensions')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in origin):
        raise ValueError('scalar grid origin must be finite')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in pitch):
        raise ValueError('scalar grid pitches must be finite and positive')
    if any(type(v) is not int or v < 2 or v > 90000 for v in dimensions) or dimensions[0] < 3 or dimensions[1] < 3:
        raise ValueError('scalar grid dimensions exceed the PA writer minimum')
    if type(grid['block_points']) is not int or grid['block_points'] < 1:
        raise ValueError('scalar sampling block size must be a positive integer')
    maximum = [origin[i] + (dimensions[i] - 1) * pitch[i] for i in range(3)]
    box = projection['outer_box_mm']
    if any(not math.isfinite(maximum[i]) or origin[i] < box['min'][i] or maximum[i] > box['max'][i] for i in range(3)):
        raise ValueError('scalar grid extends outside the explicitly selected solution geometry')
    return dict(grid, origin_mm=list(origin), pitch_mm=list(pitch), dimensions=list(dimensions),
                maximum_mm=maximum, point_count=math.prod(dimensions))


def resolve_published_writer(manifest_record: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the existing published adapted PA writer without an installed-path fallback."""
    authority = validate_file_record(manifest_record, 'PA writer source manifest')
    path = Path(authority['path'])
    if not path.is_absolute():
        raise ValueError('PA writer source manifest path must be explicit and absolute')
    verify_record('PA writer source manifest', authority)
    require_completed_terminal_publication(path)
    published = json.loads(path.read_text(encoding='utf-8-sig'))
    if (not isinstance(published, dict) or published.get('role') != 'simulation_run_manifest'
            or published.get('project') != 'parallel_mirror_dual_stripe_mr_tof'
            or published.get('status') != 'success' or not isinstance(published.get('inputs'), dict)):
        raise ValueError('PA writer requires a successful published corridor export manifest')
    matches = [value for value in published['inputs'].values() if isinstance(value, Mapping)
               and isinstance(value.get('path'), str) and Path(value['path']).name.lower() == 'simion_pa_save.m']
    if len(matches) != 1:
        raise ValueError('published corridor export must bind exactly one PA writer')
    record = validate_file_record(matches[0], 'published adapted PA writer')
    if record['sha256'].upper() != _REVIEWED_ADAPTED_WRITER_SHA256:
        raise ValueError('published PA writer is not the reviewed adapted source')
    local = path.parent / 'inputs' / 'simion_pa_save.m'
    relocated = dict(record, path=str(local.resolve()))
    verify_record('published adapted PA writer', relocated)
    return authority, relocated


def resolve_model_source_manifests(source: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve explicit owner manifests for an owned or borrowed solution model."""
    current = dict(source.reference['manifest'], path=str(source.manifest_location))
    verify_record('field solution manifest', current)
    require_completed_terminal_publication(Path(current['path']))
    published = json.loads(Path(current['path']).read_text(encoding='utf-8-sig'))
    model = source.data_records['model']
    outputs = published.get('outputs')
    inputs = published.get('inputs')
    if not isinstance(outputs, list) or not isinstance(inputs, dict):
        raise ValueError('field solution manifest inputs or outputs differ')
    count = sum(record == model for record in outputs)
    if count == 1:
        return current, None
    if count != 0 or inputs.get('borrowed_solution') != model:
        raise ValueError('field solution borrowed model binding differs')
    origin = validate_file_record(inputs.get('failed_manifest'), 'borrowed model producer manifest')
    path = Path(origin['path'])
    if not path.is_absolute():
        raise ValueError('borrowed model producer manifest must be absolute')
    verify_record('borrowed model producer manifest', origin)
    require_completed_terminal_publication(path)
    producer = json.loads(path.read_text(encoding='utf-8-sig'))
    if (producer.get('role') != 'simulation_run_manifest' or producer.get('status') != 'failed'
            or not isinstance(producer.get('outputs'), list)
            or sum(record == model for record in producer['outputs']) != 1):
        raise ValueError('borrowed model is not an exact failed producer output')
    return current, origin

def export_world_scalar(solution: Any, *, grid: Mapping[str, Any], writer_manifest: Mapping[str, Any], context: Any) -> Any:
    """Export one verified stationary workpoint; no solve or flight qualification."""
    source = open_artifact(solution, expected_kind='field_solution')
    metadata = source.metadata
    if (metadata.get('backend') != 'comsol' or metadata.get('scope') != 'single_stationary_workpoint'
            or metadata.get('field_status') != 'solved' or metadata.get('native_reopen_verified') is not True):
        raise ContractError('verified single-workpoint COMSOL field_solution required')
    observed = metadata.get('solution')
    if not isinstance(observed, Mapping):
        raise ValueError('saved solution readback required')
    validate_solution_readback(observed, study_tag=observed.get('study_tag'),
                               solution_tag=observed.get('solution_tag'), dataset_tag=observed.get('dataset_tag'))
    projection = json.loads(source.data_path('projection').read_text(encoding='utf-8-sig'))
    baseline = json.loads(source.data_path('reopen_geometry').read_text(encoding='utf-8-sig'))
    resolved = validate_grid(grid, projection, observed)
    geometry_validation = json.loads(source.data_path('geometry_validation').read_text(encoding='utf-8-sig'))
    position_sanity = geometry_validation.get('position_mm')
    if type(position_sanity) not in (int, float) or not math.isfinite(position_sanity) or position_sanity < 0:
        raise ValueError('nonnegative frozen geometry position sanity required')
    resolved['coordinate_sanity_mm'] = position_sanity
    writer_authority, writer = resolve_published_writer(writer_manifest)
    for name in ('comsol_launcher', 'matlab_root'):
        path = context.tools.get(name)
        if path is None or not (path.is_dir() if name == 'matlab_root' else path.is_file()):
            raise ContractError('COMSOL scalar export requires explicit available tool: ' + name)
    stage, authority = read_stage_policy(context, 'export_assembly_world_scalar', required_roles=('solver_native_binary',))
    if stage.get('runtime'):
        raise ContractError('COMSOL scalar export has no implicit runtime overrides')
    reference, origin = resolve_model_source_manifests(source)
    source_refs = [{'manifest_record': reference}]
    if origin is not None:
        source_refs.append({'manifest_record': origin})
    result = run_managed_stage(context, descriptor=dict(project='instrument_assembly', mode='world_scalar_export', software=['COMSOL', 'MATLAB']),
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__analysis__comsol__assembly-scalar-' + uuid4().hex[:12],
        payload=dict(action='export_assembly_world_scalar', grid=resolved, stage_policy=stage),
        committed_new_bytes=stage['limits']['transient_run_directory_bytes'], commitment_inputs=[authority],
        retention=stage['artifact_retention'], source_references=source_refs,
        expected_operation_ids=('export_world_scalar',), operation_dependencies={},
        action=partial(execute_export, source=source, manifest_record=reference, grid=resolved,
                       baseline=baseline, solution_identity=dict(observed), writer_authority=writer_authority, writer=writer, limits=stage['limits'], origin_manifest=origin),
        action_record=file_record(Path(__file__).resolve(), 'required_evidence'), use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api)
    return open_artifact({'manifest': result['manifest'], 'product_id': 'samples'}, expected_kind='scalar_field_samples')


def execute_export(session: Any, *, source: Any, manifest_record: Mapping[str, Any], grid: Mapping[str, Any],
                   baseline: Mapping[str, Any], solution_identity: Mapping[str, Any], writer_authority: Mapping[str, Any],
                   writer: Mapping[str, Any], limits: Mapping[str, Any],
                   origin_manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Freeze small authorities and guard the borrowed saved model during export."""
    if session.expected_operation_ids != ('export_world_scalar',):
        raise ValueError('scalar export requires exactly one saved-solution operation')
    launcher, sources = freeze_native_sources(session, _NATIVE_SOURCES)
    session.add_input('field_solution_manifest', dict(manifest_record, retention_role='required_evidence'))
    origin_guard = []
    if origin_manifest is not None:
        session.add_input('borrowed_model_origin_manifest', dict(origin_manifest, retention_role='required_evidence'))
        origin_path = session.declare_file(session.input_dir / 'solution' / 'borrowed-source-manifest.json', 'required_evidence')
        origin_path.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(Path(origin_manifest['path']), origin_path)
        origin_copy = file_record(origin_path, 'required_evidence')
        if any(origin_copy[key] != origin_manifest[key] for key in ('bytes', 'sha256')):
            raise ValueError('frozen borrowed model producer manifest differs')
        session.add_input('borrowed_model_origin_frozen', origin_copy)
        origin_guard = [origin_manifest, origin_copy]
    model = dict(source.data_records['model'], path=str(source.data_locations['model']))
    session.add_input('field_solution_model', model)
    frozen = {}
    for name in ('projection', 'request', 'geometry_validation', 'reopen_geometry', 'reopen_solution'):
        src = source.data_path(name)
        target = session.declare_file(session.input_dir / 'solution' / name / src.name, 'required_evidence')
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(src, target)
        record = file_record(target, 'required_evidence')
        if any(record[key] != source.data_records[name][key] for key in ('bytes', 'sha256')):
            raise ValueError('frozen solution authority differs: ' + name)
        session.add_input('solution_' + name, record)
        frozen[name] = record
    session.add_input('pa_writer_source_manifest', dict(writer_authority, retention_role='required_evidence'))
    session.add_input('pa_writer_source', dict(writer, retention_role='required_evidence'))
    manifest_copy = session.declare_file(session.input_dir / 'writer' / 'source-manifest.json', 'required_evidence')
    manifest_copy.parent.mkdir(parents=True, exist_ok=True)
    freeze_file(Path(writer_authority['path']), manifest_copy)
    manifest_frozen = file_record(manifest_copy, 'required_evidence')
    if any(manifest_frozen[key] != writer_authority[key] for key in ('bytes', 'sha256')):
        raise ValueError('frozen PA writer authority differs')
    session.add_input('pa_writer_authority', manifest_frozen)
    writer_path = session.declare_file(session.input_dir / 'writer' / 'simion_pa_save.m', 'required_evidence')
    writer_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_file(Path(writer['path']), writer_path)
    writer_copy = file_record(writer_path, 'required_evidence')
    if any(writer_copy[key] != writer[key] for key in ('bytes', 'sha256')):
        raise ValueError('frozen PA writer differs from explicit source identity')
    session.add_input('pa_writer', writer_copy)
    grid_path = session.declare_file(session.input_dir / 'world-grid.json', 'required_evidence')
    write_json_atomic(grid_path, dict(grid))
    grid_record = file_record(grid_path, 'required_evidence'); session.add_input('world_grid', grid_record)
    output_dir = session.run_dir / 'scalar'; output_dir.mkdir()
    outputs = [session.declare_file(output_dir / name, 'solver_native_binary') for name in ('field_v.pa', 'field_valid.pa')]
    report = session.declare_file(session.result_dir / 'export_world_scalar.json', 'required_evidence')
    bootstrap = session.declare_file(session.log_dir / 'export_world_scalar.bootstrap.log', 'required_evidence')
    completion = session.declare_file(session.log_dir / 'export_world_scalar.launcher.json', 'required_evidence')
    task = session.declare_file(session.input_dir / 'export_world_scalar.m', 'required_evidence')
    runtime = session.run_dir / 'comsol_runtime' / 'export_world_scalar'; runtime.mkdir(parents=True)
    matlab = launcher.parent.parent / 'matlab'
    call = 'export_assembly_world_scalar_field(' + ','.join(map(matlab_text, (source.data_locations['model'],
        frozen['projection']['path'], frozen['reopen_geometry']['path'], grid_path, writer_path, output_dir))) + ')'
    task.write_text('addpath(' + matlab_text(matlab) + ');\nresult=' + call + ';\n'
        'fid=fopen(' + matlab_text(report) + ",'w','n','UTF-8');\n"
        "assert(fid>=0); cleanup=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result));\n",
        encoding='utf-8', newline='\n')
    guards = [*sources, *frozen.values(), *origin_guard, manifest_frozen, writer_copy, grid_record, file_record(task, 'required_evidence'), model]
    host = json.dumps({name: str(getattr(session.context, name)) for name in ('workspace', 'python_executable', 'host_state_path', 'policy_path')})
    args = ['-NoProfile', '-File', str(launcher), '-HostContextJson', host, '-WorkingDirectory', str(session.run_dir),
        '-ComsolLauncherPath', str(session.context.tools['comsol_launcher']), '-MatlabRootPath', str(session.context.tools['matlab_root']),
        '-TaskScript', str(task), '-ReportPath', str(bootstrap), '-StartupAttempts', '1', '-RunId', session.run_id,
        '-RunDir', str(runtime), '-CompletionPath', str(completion)]
    primary = None
    try:
        session.run_process('export_world_scalar', executable=session.context.powershell_executable, arguments=args,
                            role='COMSOL', stage='solver', limits=limits, immutable_input_records=guards)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            declare_runtime_files(session, runtime, bootstrap=bootstrap)
        except BaseException as error:
            if primary is None: raise
            primary.add_note('COMSOL diagnostic preservation failed: ' + repr(error))
    require_launcher_completion(completion, session.run_id)
    if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'):
        raise ValueError('COMSOL scalar export bootstrap failed')
    row = json.loads(report.read_text(encoding='utf-8-sig'))
    _check_report(row, grid=grid, baseline=baseline, solution_identity=solution_identity, model=Path(source.data_locations['model']))
    for path in outputs:
        _validate_scalar_pa(path, grid)
    records = dict(field_v=file_record(outputs[0], 'solver_native_binary'), field_valid=file_record(outputs[1], 'solver_native_binary'),
                   grid=grid_record, field_solution_manifest=manifest_record, writer=writer_copy, writer_manifest=manifest_frozen,
                   projection=frozen['projection'], request=frozen['request'], geometry_validation=frozen['geometry_validation'], reopen_geometry=frozen['reopen_geometry'],
                   reopen_solution=frozen['reopen_solution'], report=file_record(report, 'required_evidence'))
    metadata = dict(backend='comsol', scope='assembly_world_scalar_samples', field_status='sampled',
                    scientific_qualification='not_granted', frame_id=grid['frame_id'], compute_calls_requested=0)
    return dict(status='success', summary=metadata, output_paths=[*map(str, outputs), str(report)],
        required_output_paths=[*map(str, outputs), str(report)], retention_preserve_paths=[],
        manifest_extra_fields=dict(products=dict(samples=dict(schema_version=1, kind='scalar_field_samples',
            status='complete', metadata=metadata, data=records))))


def _validate_scalar_pa(path: Path, grid: Mapping[str, Any]) -> None:
    """Verify an actual ordinary non-refinable planar PA against the selected grid."""
    from msplatform.backends.simion.collision_overlay import COLLISION_NOTREFINABLE_FLAG, collision_pa_header
    header = collision_pa_header(path)
    if (header.mode != -2 or header.symmetry != 1 or header.raw_mirror != COLLISION_NOTREFINABLE_FLAG
            or (header.nx, header.ny, header.nz) != tuple(grid['dimensions'])
            or (header.dx_mm, header.dy_mm, header.dz_mm) != tuple(grid['pitch_mm'])):
        raise ValueError('scalar PA header differs from the explicit world grid: ' + str(path))


def _check_report(row: Mapping[str, Any], *, grid: Mapping[str, Any], baseline: Mapping[str, Any], solution_identity: Mapping[str, Any], model: Path) -> None:
    if (not isinstance(row, Mapping) or row.get('status') != 'success' or row.get('scope') != 'assembly_world_scalar_samples'
            or row.get('field_qualification') is not False or row.get('compute_calls') != 0
            or row.get('filled_conductor_count') != 0 or row.get('coordinate_mapping') != 'world_identity'
            or Path(row.get('model_path', '')).resolve() != model.resolve()):
        raise ValueError('saved world scalar export report differs')
    for name in ('frame_id', 'origin_mm', 'pitch_mm', 'dimensions', 'point_count', 'study_tag', 'solution_tag', 'dataset_tag'):
        if row.get(name) != grid[name]: raise ValueError('world scalar grid or solution differs: ' + name)
    witness = row.get('coordinate_witness')
    if not isinstance(witness, Mapping) or not isinstance(witness.get('geometry_length_unit'), str) or not witness['geometry_length_unit']:
        raise ValueError('world coordinate witness geometry unit differs')
    sanity = grid.get('coordinate_sanity_mm')
    if type(sanity) not in (int, float) or not math.isfinite(sanity) or sanity < 0:
        raise ValueError('world coordinate sanity authority missing')
    if witness.get('status') == 'insufficient':
        if witness.get('index') != 0 or witness.get('requested_mm') != [] or witness.get('actual_mm') != []:
            raise ValueError('insufficient coordinate witness differs')
    elif witness.get('status') == 'verified':
        index = witness.get('index')
        requested, actual = witness.get('requested_mm'), witness.get('actual_mm')
        if type(index) is not int or index < 1 or index > grid['point_count'] or not isinstance(requested, list) or not isinstance(actual, list) or len(requested) != 3 or len(actual) != 3:
            raise ValueError('world coordinate witness shape differs')
        offset = index - 1
        nx, ny, _ = grid['dimensions']
        indices = (offset % nx, (offset // nx) % ny, offset // (nx * ny))
        expected = [grid['origin_mm'][i] + grid['pitch_mm'][i] * indices[i] for i in range(3)]
        if not any(value != 0 for value in expected) or any(type(value) not in (int, float) or not math.isfinite(value) for value in requested + actual) or any(abs(requested[i] - expected[i]) > sanity or abs(actual[i] - requested[i]) > sanity for i in range(3)):
            raise ValueError('world coordinate witness differs from frozen grid')
    else:
        raise ValueError('world coordinate witness status differs')
    vacuum = row.get('vacuum_domains')
    expected_vacuum = baseline.get('vacuum_domains')
    if type(vacuum) is int: vacuum = [vacuum]
    if type(expected_vacuum) is int: expected_vacuum = [expected_vacuum]
    if vacuum != expected_vacuum:
        raise ValueError('world scalar vacuum authority differs')
    finite, invalid = row.get('fem_valid'), row.get('invalid_count')
    if type(finite) is not int or type(invalid) is not int or finite < 0 or invalid < 0 or finite + invalid != grid['point_count']:
        raise ValueError('world scalar mask accounting differs')
    validate_solution_readback(row.get('solution_readback'), study_tag=grid['study_tag'],
                               solution_tag=grid['solution_tag'], dataset_tag=grid['dataset_tag'])
    for name in ('study_tag', 'solution_tag', 'dataset_tag', 'dataset_solution', 'solution_empty', 'solution_dofs', 'solution_count', 'stored_main_solutions'):
        if row['solution_readback'].get(name) != solution_identity.get(name):
            raise ValueError('world scalar stored solution readback differs: ' + name)
