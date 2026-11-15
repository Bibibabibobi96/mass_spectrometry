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
from msplatform.backends.simion.scalar_pa_payload import finalize_scalar_pair
from msplatform.backends.simion.standalone_pa_composition import HEADER
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

def _classification_grid_identity(grid: Mapping[str, Any]) -> dict[str, Any]:
    """Return only coordinates that determine a classified grid node."""
    return {key: grid[key] for key in ('frame_id', 'origin_mm', 'pitch_mm', 'dimensions', 'point_count')}


def export_world_scalar(solution: Any, *, grid: Mapping[str, Any], context: Any,
                        fill_conductor_interiors: bool = False, publish_prepared_support: bool = False,
                        prepared_support: Any = None) -> Any:
    """Export a single verified saved workpoint on one explicit grid."""
    return _export_world_scalar(solution, grid=grid, context=context,
        fill_conductor_interiors=fill_conductor_interiors, publish_prepared_support=publish_prepared_support,
        prepared_support=prepared_support)


def export_world_scalar_grids(solution: Any, *, grids: Mapping[str, Mapping[str, Any]],
                              context: Any) -> dict[str, Any]:
    """Export named raw scalar grids with one saved-model load and no Compute."""
    import re
    if not isinstance(grids, Mapping) or not grids:
        raise ValueError('at least one explicitly named scalar grid required')
    names = list(grids)
    if any(not isinstance(name, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,39}', name) is None for name in names):
        raise ValueError('grid names must be unique lowercase identifiers')
    if len(names) != len(grids) or len(set(names)) != len(names):
        raise ValueError('grid names must be unique')
    return _export_world_scalar(solution, grid=next(iter(grids.values())), grids=grids,
                                context=context)


def _export_world_scalar(solution: Any, *, grid: Mapping[str, Any], context: Any, fill_conductor_interiors: bool = False,
                        publish_prepared_support: bool = False, prepared_support: Any = None, grids: Mapping[str, Any] | None = None) -> Any:
    """Export one verified workpoint, optionally filling strict conductor interiors.

    ``publish_prepared_support`` publishes reusable interior labels; an explicit
    ``prepared_support`` reference reuses labels only after identity checks.
    Neither option qualifies the physical field or trajectory.
    """
    if type(fill_conductor_interiors) is not bool:
        raise ValueError('fill_conductor_interiors must be an explicit boolean')
    if type(publish_prepared_support) is not bool:
        raise ValueError('publish_prepared_support must be boolean')
    if (publish_prepared_support or prepared_support is not None) and not fill_conductor_interiors:
        raise ValueError('prepared support requires explicit conductor fill')
    if publish_prepared_support and prepared_support is not None:
        raise ValueError('cannot publish and consume prepared support together')
    support_source = None
    if prepared_support is not None:
        support_source = open_artifact(prepared_support, expected_kind='scalar_field_samples')
        if support_source.producer.get('status') != 'success':
            raise ValueError('prepared support producer must be successful')
        for key in ('prepared_support_labels', 'conductor_support', 'sampled_field_valid', 'projection', 'grid'):
            support_source.data_path(key)
    support_original = None
    if support_source is not None:
        from msplatform.backends.simion.scalar_sample_binding import original_sample_source
        support_original = original_sample_source(support_source)
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
    resolved_grids = ({name: validate_grid(value, projection, observed) for name, value in grids.items()}
                      if grids is not None else None)
    if fill_conductor_interiors:
        from msplatform.backends.comsol.assembly_scalar_fill import InvalidNodeClassifier
        request = json.loads(source.data_path('request').read_text(encoding='utf-8-sig'))
        InvalidNodeClassifier(projection, request, resolved)
    geometry_validation = json.loads(source.data_path('geometry_validation').read_text(encoding='utf-8-sig'))
    position_sanity = geometry_validation.get('position_mm')
    if type(position_sanity) not in (int, float) or not math.isfinite(position_sanity) or position_sanity < 0:
        raise ValueError('nonnegative frozen geometry position sanity required')
    resolved['coordinate_sanity_mm'] = position_sanity
    if resolved_grids is not None:
        for value in resolved_grids.values(): value['coordinate_sanity_mm'] = position_sanity
    for name in ('comsol_launcher', 'matlab_root'):
        path = context.tools.get(name)
        if path is None or not (path.is_dir() if name == 'matlab_root' else path.is_file()):
            raise ContractError('COMSOL scalar export requires explicit available tool: ' + name)
    stage, authority = read_stage_policy(context, 'export_assembly_world_scalar', required_roles=('solver_native_binary',))
    if stage.get('runtime'):
        raise ContractError('COMSOL scalar export has no implicit runtime overrides')
    if resolved_grids is not None:
        minimum = sum(2 * (HEADER.size + 8 * value['point_count']) for value in resolved_grids.values())
        if any(minimum > stage['limits'][key] for key in ('transient_run_directory_bytes','compact_final_retained_bytes')):
            raise ValueError('named grid raw output minimum exceeds configured stage limits')
    reference, origin = resolve_model_source_manifests(source)
    source_refs = [{'manifest_record': reference}]
    if origin is not None:
        source_refs.append({'manifest_record': origin})
    if support_source is not None:
        source_refs.append({'manifest_record': support_source.reference['manifest']})
        if support_original is not None: source_refs.append({'manifest_record': support_original.reference['manifest']})
    payload = dict(action='export_assembly_world_scalar', grid=resolved, stage_policy=stage,
                   fill_conductor_interiors=fill_conductor_interiors,
                   publish_prepared_support=publish_prepared_support,
                   prepared_support=(support_source.reference if support_source is not None else None))
    if resolved_grids is not None: payload['grids'] = resolved_grids
    result = run_managed_stage(context, descriptor=dict(project='instrument_assembly', mode='world_scalar_export', software=['COMSOL', 'MATLAB']),
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__analysis__comsol__assembly-scalar-' + uuid4().hex[:12],
        payload=payload,
        committed_new_bytes=stage['limits']['transient_run_directory_bytes'], commitment_inputs=[authority],
        retention=stage['artifact_retention'], source_references=source_refs,
        expected_operation_ids=('export_world_scalar',), operation_dependencies={},
        action=partial(execute_export, source=source, manifest_record=reference, grid=resolved,
                       baseline=baseline, solution_identity=dict(observed), limits=stage['limits'], origin_manifest=origin, fill_conductor_interiors=fill_conductor_interiors,
                       publish_prepared_support=publish_prepared_support, support_source=support_source, support_original=support_original, grids=resolved_grids),
        action_record=file_record(Path(__file__).resolve(), 'required_evidence'), use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api)
    if resolved_grids is not None:
        return {name: open_artifact({'manifest': result['manifest'], 'product_id': 'samples_' + name},
                                    expected_kind='scalar_field_samples') for name in resolved_grids}
    return open_artifact({'manifest': result['manifest'], 'product_id': 'samples'}, expected_kind='scalar_field_samples')


def execute_export(session: Any, *, source: Any, manifest_record: Mapping[str, Any], grid: Mapping[str, Any],
                   baseline: Mapping[str, Any], solution_identity: Mapping[str, Any], limits: Mapping[str, Any],
                   origin_manifest: Mapping[str, Any] | None = None,
                   fill_conductor_interiors: bool = False,
                   publish_prepared_support: bool = False, support_source: Any = None,
                   support_original: Any = None, grids: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Freeze small authorities and guard the borrowed saved model during export."""
    if session.expected_operation_ids != ('export_world_scalar',):
        raise ValueError('scalar export requires exactly one saved-solution operation')
    if type(fill_conductor_interiors) is not bool:
        raise ValueError('fill_conductor_interiors must be an explicit boolean')
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
    support_code = []
    if fill_conductor_interiors:
        from msplatform.backends.comsol.assembly_scalar_fill import InvalidNodeClassifier
        projection = json.loads(Path(frozen['projection']['path']).read_text(encoding='utf-8-sig'))
        request = json.loads(Path(frozen['request']['path']).read_text(encoding='utf-8-sig'))
        InvalidNodeClassifier(projection, request, grid)
        support_code = _freeze_support_sources(session)
    support_guards = []
    if support_original is not None:
        session.add_input('prepared_support_original_manifest', support_original.reference['manifest'])
        support_guards.append(support_original.reference['manifest'])
    if support_source is not None:
        support_manifest = support_source.reference['manifest']
        session.add_input('prepared_support_manifest', support_manifest)
        support_guards.append(support_manifest)
        for key in ('prepared_support_labels', 'conductor_support', 'sampled_field_valid', 'projection', 'grid'):
            record = dict(support_source.data_records[key], path=str(support_source.data_locations[key]))
            session.add_input('prepared_support_' + key, record)
            support_guards.append(record)
    encoder_code = _freeze_pa_encoder_sources(session)
    output_dir = session.run_dir / 'scalar'; output_dir.mkdir()
    batch = {}
    batch_guards = []
    if grids is None:
        grid_path = session.declare_file(session.input_dir / 'world-grid.json', 'required_evidence')
        write_json_atomic(grid_path, dict(grid))
        grid_record = file_record(grid_path, 'required_evidence'); session.add_input('world_grid', grid_record)
        outputs = [session.declare_file(output_dir / name, 'solver_native_binary') for name in ('field_v.pa', 'field_valid.pa')]
        report = session.declare_file(session.result_dir / 'export_world_scalar.json', 'required_evidence')
    else:
        if fill_conductor_interiors or publish_prepared_support or support_source is not None:
            raise ValueError('named grid export emits raw samples only')
        entries = []
        for name, value in grids.items():
            subdir = output_dir / name; subdir.mkdir()
            gp = session.declare_file(session.input_dir / ('world-grid-' + name + '.json'), 'required_evidence')
            write_json_atomic(gp, dict(value)); gr = file_record(gp, 'required_evidence')
            session.add_input('world_grid_' + name, gr); batch_guards.append(gr)
            paths = [session.declare_file(subdir / n, 'solver_native_binary') for n in ('field_v.pa', 'field_valid.pa')]
            rp = session.declare_file(session.result_dir / ('export_world_scalar_' + name + '.json'), 'required_evidence')
            batch[name] = dict(grid=value, grid_record=gr, outputs=paths, report=rp)
            entries.append(dict(grid_path=str(gp), output_directory=str(subdir), report_path=str(rp)))
        grid_path = session.declare_file(session.input_dir / 'world-grid-batch.json', 'required_evidence')
        write_json_atomic(grid_path, dict(role='assembly_world_scalar_grid_batch', entries=entries))
        grid_record = file_record(grid_path, 'required_evidence'); session.add_input('world_grid_batch', grid_record)
        outputs = [p for item in batch.values() for p in item['outputs']]
        report = session.declare_file(session.result_dir / 'export_world_scalar_batch.json', 'required_evidence')
    bootstrap = session.declare_file(session.log_dir / 'export_world_scalar.bootstrap.log', 'required_evidence')
    completion = session.declare_file(session.log_dir / 'export_world_scalar.launcher.json', 'required_evidence')
    task = session.declare_file(session.input_dir / 'export_world_scalar.m', 'required_evidence')
    runtime = session.run_dir / 'comsol_runtime' / 'export_world_scalar'; runtime.mkdir(parents=True)
    matlab = launcher.parent.parent / 'matlab'
    call = 'export_assembly_world_scalar_field(' + ','.join(map(matlab_text, (source.data_locations['model'],
        frozen['projection']['path'], frozen['reopen_geometry']['path'], grid_path))) + ',' + str(HEADER.size) + ',' + matlab_text(output_dir) + ')'
    task.write_text('addpath(' + matlab_text(matlab) + ');\nresult=' + call + ';\n'
        'fid=fopen(' + matlab_text(report) + ",'w','n','UTF-8');\n"
        "assert(fid>=0); cleanup=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result));\n",
        encoding='utf-8', newline='\n')
    guards = [*sources, *frozen.values(), *origin_guard, *encoder_code, grid_record, *batch_guards, file_record(task, 'required_evidence'), model, *support_code, *support_guards]
    unique_guards = {}
    for record in guards:
        key = Path(record['path']).resolve(strict=True)
        if key in unique_guards and unique_guards[key] != record:
            raise ValueError('conflicting immutable source records: ' + record['path'])
        unique_guards[key] = record
    guards = list(unique_guards.values())
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
        prior = list(getattr(error, 'failure_output_paths', ()))
        candidates = [*outputs, report, *(item['report'] for item in batch.values())]
        error.failure_output_paths = [*prior, *(path for path in candidates if path.is_file())]
        raise
    finally:
        try:
            declare_runtime_files(session, runtime, bootstrap=bootstrap)
        except BaseException as error:
            if primary is None:
                prior = list(getattr(error, 'failure_output_paths', ()))
                candidates = [*outputs, report, *(item['report'] for item in batch.values())]
                error.failure_output_paths = [*prior, *(path for path in candidates if path.is_file())]
                raise
            primary.add_note('COMSOL diagnostic preservation failed: ' + repr(error))
    try:
        require_launcher_completion(completion, session.run_id)
        if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'):
            raise ValueError('COMSOL scalar export bootstrap failed')
    except BaseException as error:
        prior = list(getattr(error, 'failure_output_paths', ()))
        candidates = [*outputs, report, *(item['report'] for item in batch.values())]
        error.failure_output_paths = [*prior, *(path for path in candidates if path.is_file())]
        raise
    if grids is not None:
        try:
            summary = json.loads(report.read_text(encoding='utf-8-sig'))
            if (summary.get('status') != 'success' or summary.get('scope') != 'assembly_world_scalar_grid_batch'
                    or type(summary.get('grid_count')) is not int or summary['grid_count'] != len(batch)
                    or type(summary.get('compute_calls')) is not int or summary['compute_calls'] != 0):
                raise ValueError('named scalar grid batch completion differs')
            products = {}
            result_paths = [report]
            for name, item in batch.items():
                row = json.loads(item['report'].read_text(encoding='utf-8-sig'))
                _check_report(row, grid=item['grid'], baseline=baseline, solution_identity=solution_identity, model=Path(source.data_locations['model']))
                _finalize_scalar_outputs(item['outputs'], item['grid'], encoder_code)
                for path in item['outputs']: _validate_scalar_pa(path, item['grid'])
                records = dict(field_v=file_record(item['outputs'][0], 'solver_native_binary'),
                    field_valid=file_record(item['outputs'][1], 'solver_native_binary'), grid=item['grid_record'],
                    field_solution_manifest=manifest_record,
                    projection=frozen['projection'], request=frozen['request'], geometry_validation=frozen['geometry_validation'],
                    reopen_geometry=frozen['reopen_geometry'], reopen_solution=frozen['reopen_solution'],
                    report=file_record(item['report'], 'required_evidence'))
                metadata = dict(backend='comsol', scope='assembly_world_scalar_samples', field_status='sampled',
                    scientific_qualification='not_granted', frame_id=item['grid']['frame_id'], compute_calls_requested=0)
                products['samples_' + name] = dict(schema_version=1, kind='scalar_field_samples', status='complete', metadata=metadata, data=records)
                result_paths.extend([*item['outputs'], item['report']])
            return dict(status='success', summary=dict(backend='comsol', scope='assembly_world_scalar_grid_batch',
                scientific_qualification='not_granted', compute_calls_requested=0), output_paths=list(map(str, result_paths)),
                required_output_paths=list(map(str, result_paths)), retention_preserve_paths=[],
                manifest_extra_fields=dict(products=products))
        except BaseException as error:
            prior = list(getattr(error, 'failure_output_paths', ()))
            candidates = [*outputs, report, *(item['report'] for item in batch.values())]
            error.failure_output_paths = [*prior, *(path for path in candidates if path.is_file())]
            raise
    try:
        row = json.loads(report.read_text(encoding='utf-8-sig'))
        _check_report(row, grid=grid, baseline=baseline, solution_identity=solution_identity, model=Path(source.data_locations['model']))
        _finalize_scalar_outputs(outputs, grid, encoder_code)
        for path in outputs:
            _validate_scalar_pa(path, grid)
    except BaseException as error:
        prior = list(getattr(error, 'failure_output_paths', ()))
        error.failure_output_paths = [*prior, *(path for path in [*outputs, report] if path.is_file())]
        raise
    published_outputs, support_record, raw_mask_record, labels_path, support_path = _postprocess_scalar(
        session, outputs=outputs, output_dir=output_dir, grid=grid, projection=projection if fill_conductor_interiors else {},
        request=request if fill_conductor_interiors else {}, frozen=frozen, grid_record=grid_record,
        manifest_record=manifest_record, row=row, support_code=support_code, support_guards=support_guards,
        support_source=support_source, fill_conductor_interiors=fill_conductor_interiors,
        publish_prepared_support=publish_prepared_support, failure_report=report)
    records = dict(field_v=file_record(published_outputs[0], 'solver_native_binary'), field_valid=file_record(published_outputs[1], 'solver_native_binary'),
                   grid=grid_record, field_solution_manifest=manifest_record,
                   projection=frozen['projection'], request=frozen['request'], geometry_validation=frozen['geometry_validation'], reopen_geometry=frozen['reopen_geometry'],
                   reopen_solution=frozen['reopen_solution'], report=file_record(report, 'required_evidence'))
    if support_record is not None:
        records.update(sampled_field_v=file_record(outputs[0], 'solver_native_binary'),
                       sampled_field_valid=raw_mask_record, conductor_support=support_record)
        if labels_path is not None:
            records['prepared_support_labels'] = file_record(labels_path, 'required_evidence')
    metadata = dict(backend='comsol', scope='assembly_world_scalar_samples', field_status='sampled',
                    scientific_qualification='not_granted', frame_id=grid['frame_id'], compute_calls_requested=0)
    if support_record is not None:
        metadata['conductor_support_policy'] = 'unique_dirichlet_solid_interiors'
    result_paths = [*outputs, *([*published_outputs, support_path] if support_record is not None else []), report]
    if support_record is not None and labels_path is not None: result_paths.append(labels_path)
    return dict(status='success', summary=metadata, output_paths=list(map(str, result_paths)),
        required_output_paths=list(map(str, result_paths)), retention_preserve_paths=[],
        manifest_extra_fields=dict(products=dict(samples=dict(schema_version=1, kind='scalar_field_samples',
            status='complete', metadata=metadata, data=records))))


def _published_solution_readback(reopen: Mapping[str, Any], grid: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate the nested readback already emitted by the stationary owner."""
    solution = reopen.get('solution') if isinstance(reopen, Mapping) else None
    if not isinstance(solution, Mapping): raise ValueError('published nested solution readback is required')
    validate_solution_readback(solution, study_tag=grid['study_tag'],
                               solution_tag=grid['solution_tag'], dataset_tag=grid['dataset_tag'])
    return solution


def derive_world_scalar_support(samples: Any, *, context: Any,
                                publish_prepared_support: bool = False,
                                prepared_support: Any = None) -> Any:
    """Derive strict-interior fill from an existing published raw samples product.

    No solver is started and no physical field or trajectory is qualified.
    The original sampled files and report remain protected producer inputs.
    """
    if type(publish_prepared_support) is not bool:
        raise ValueError('publish_prepared_support must be boolean')
    if publish_prepared_support and prepared_support is not None:
        raise ValueError('cannot publish and consume prepared support together')
    source = open_artifact(samples, expected_kind='scalar_field_samples')
    if source.producer.get('status') != 'success':
        raise ValueError('source samples producer must be successful')
    from msplatform.backends.simion.scalar_sample_binding import original_sample_source
    original = original_sample_source(source) or source
    if (source.metadata.get('backend') != 'comsol'
            or source.metadata.get('scope') != 'assembly_world_scalar_samples'
            or source.metadata.get('field_status') != 'sampled'):
        raise ContractError('published Assembly world scalar samples required')
    raw_names = ('sampled_field_v', 'sampled_field_valid')
    if any(name in source.data_records for name in raw_names):
        if not all(name in source.data_records for name in raw_names):
            raise ValueError('incomplete published original raw sample pair')
    else:
        if source.metadata.get('conductor_support_policy') is not None:
            raise ValueError('filled samples lack the original raw pair')
        raw_names = ('field_v', 'field_valid')
    required = ('grid', 'projection', 'request', 'geometry_validation', 'reopen_geometry',
                'reopen_solution', 'report', 'field_solution_manifest')
    writer_names = ('writer', 'writer_manifest')
    if any(name in source.data_records for name in writer_names):
        if not all(name in source.data_records for name in writer_names):
            raise ValueError('incomplete published writer provenance')
        required += writer_names
    for name in (*raw_names, *required): source.data_path(name)
    grid = json.loads(source.data_path('grid').read_text(encoding='utf-8-sig'))
    projection = json.loads(source.data_path('projection').read_text(encoding='utf-8-sig'))
    request = json.loads(source.data_path('request').read_text(encoding='utf-8-sig'))
    reopen = json.loads(source.data_path('reopen_solution').read_text(encoding='utf-8-sig'))
    solution = _published_solution_readback(reopen, grid)
    keys = ('frame_id', 'origin_mm', 'pitch_mm', 'dimensions', 'block_points',
            'study_tag', 'solution_tag', 'dataset_tag')
    validated = validate_grid({key: grid[key] for key in keys}, projection, solution)
    if any(validated[key] != grid[key] for key in (*keys, 'point_count')):
        raise ValueError('published scalar grid is inconsistent')
    from msplatform.backends.comsol.assembly_scalar_fill import InvalidNodeClassifier
    InvalidNodeClassifier(projection, request, grid)
    report = json.loads(source.data_path('report').read_text(encoding='utf-8-sig'))
    def count(name):
        value = report.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or int(value) != value:
            raise ValueError('published raw report count is invalid: ' + name)
        return int(value)
    invalid = count('invalid_count'); valid = count('fem_valid')
    if (invalid + valid != grid['point_count'] or report.get('status') != 'success'
            or report.get('scope') != 'assembly_world_scalar_samples'
            or report.get('field_qualification') is not False or type(report.get('compute_calls')) is not int
            or report['compute_calls'] != 0):
        raise ValueError('published raw report accounting or scope differs')
    validate_solution_readback(report.get('solution_readback'), study_tag=grid['study_tag'],
                               solution_tag=grid['solution_tag'], dataset_tag=grid['dataset_tag'])
    support_source = None
    if prepared_support is not None:
        support_source = open_artifact(prepared_support, expected_kind='scalar_field_samples')
        if support_source.producer.get('status') != 'success':
            raise ValueError('prepared support producer must be successful')
        for name in ('prepared_support_labels', 'conductor_support', 'sampled_field_valid', 'projection', 'grid'):
            support_source.data_path(name)
    stage, authority = read_stage_policy(context, 'export_assembly_world_scalar', required_roles=('solver_native_binary',))
    if stage.get('runtime'): raise ContractError('scalar derivation has no implicit runtime overrides')
    refs = [{'manifest_record': source.reference['manifest']}]
    if original.reference != source.reference: refs.append({'manifest_record': original.reference['manifest']})
    support_original = original_sample_source(support_source) if support_source is not None else None
    if support_source is not None: refs.append({'manifest_record': support_source.reference['manifest']})
    if support_original is not None: refs.append({'manifest_record': support_original.reference['manifest']})
    result = run_managed_stage(context, descriptor=dict(project='instrument_assembly', mode='world_scalar_derive', software=['Python']),
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__analysis__cross__assembly-scalar-derive-' + uuid4().hex[:12],
        payload=dict(action='derive_world_scalar_support', source=source.reference, stage_policy=stage,
                     publish_prepared_support=publish_prepared_support,
                     prepared_support=(support_source.reference if support_source is not None else None)),
        committed_new_bytes=stage['limits']['transient_run_directory_bytes'], commitment_inputs=[authority],
        retention=stage['artifact_retention'], source_references=refs, expected_operation_ids=(), operation_dependencies={},
        action=partial(_execute_scalar_derivation, source=source, raw_names=raw_names, required=required,
                       grid=grid, projection=projection, request=request, report=dict(report, invalid_count=invalid),
                       support_source=support_source, support_original=support_original, original=original,
                       publish_prepared_support=publish_prepared_support),
        action_record=file_record(Path(__file__).resolve(), 'required_evidence'),
        completion_api=no_particle_batch_completion_api)
    return open_artifact({'manifest': result['manifest'], 'product_id': 'samples'}, expected_kind='scalar_field_samples')


def _execute_scalar_derivation(session: Any, *, source: Any, raw_names: tuple[str, str], required: tuple[str, ...],
                               grid: Mapping[str, Any], projection: Mapping[str, Any], request: Mapping[str, Any],
                               report: Mapping[str, Any], support_source: Any, publish_prepared_support: bool,
                               original: Any = None, support_original: Any = None):
    """Borrow verified source records; only newly derived files belong to this run."""
    if session.expected_operation_ids != ():
        raise ValueError('scalar derivation does not start native operations')
    original = original or source
    guards = [source.reference['manifest']]
    session.add_input('raw_samples_manifest', source.reference['manifest'])
    if original.reference != source.reference:
        guards.append(original.reference['manifest'])
        session.add_input('original_raw_samples_manifest', original.reference['manifest'])
    records = {}
    for name in (*raw_names, *required):
        record = dict(source.data_records[name], path=str(source.data_locations[name]))
        session.add_input('raw_samples_' + name, record)
        records[name] = record
        guards.append(record)
    support_guards = []
    if support_original is not None:
        support_guards.append(support_original.reference['manifest'])
        session.add_input('prepared_support_original_manifest', support_original.reference['manifest'])
    if support_source is not None:
        support_guards.append(support_source.reference['manifest'])
        session.add_input('prepared_support_manifest', support_source.reference['manifest'])
        for name in ('prepared_support_labels', 'conductor_support', 'sampled_field_valid', 'projection', 'grid'):
            record = dict(support_source.data_records[name], path=str(support_source.data_locations[name]))
            session.add_input('prepared_support_' + name, record)
            support_guards.append(record)
    support_code = _freeze_support_sources(session)
    for record in (*guards, *support_guards): verify_record('scalar derivation source before fill', record)
    outputs = [Path(source.data_locations[name]) for name in raw_names]
    for path in outputs: _validate_scalar_pa(path, grid)
    output_dir = session.run_dir / 'scalar'; output_dir.mkdir()
    primary = None
    try:
        filled, support_record, _, labels, support_path = _postprocess_scalar(
            session, outputs=outputs, output_dir=output_dir, grid=grid, projection=projection, request=request,
            frozen={'projection': records['projection'], 'request': records['request']}, grid_record=records['grid'],
            manifest_record=records['field_solution_manifest'], row=report, support_code=support_code,
            support_guards=support_guards, support_source=support_source, fill_conductor_interiors=True,
            publish_prepared_support=publish_prepared_support, raw_mask_record=records[raw_names[1]], owned_raw=False)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            for record in (*guards, *support_guards): verify_record('scalar derivation source after fill', record)
        except BaseException as error:
            if primary is None: raise
            primary.add_note('scalar derivation input guard: ' + repr(error))
    data = {name: records[name] for name in required}
    data.update(field_v=file_record(filled[0], 'solver_native_binary'), field_valid=file_record(filled[1], 'solver_native_binary'),
                sampled_field_v=records[raw_names[0]], sampled_field_valid=records[raw_names[1]], conductor_support=support_record)
    if labels is not None: data['prepared_support_labels'] = file_record(labels, 'required_evidence')
    report_path = session.declare_file(session.result_dir / 'scalar_derivation.json', 'required_evidence')
    write_json_atomic(report_path, dict(schema_version=1, role='assembly_scalar_offline_derivation',
        source_samples=source.reference, native_operations=0, compute_calls=0, scientific_qualification='not_granted'))
    data['derivation_report'] = file_record(report_path, 'required_evidence')
    metadata = dict(source.metadata, conductor_support_policy='unique_dirichlet_solid_interiors',
                    derivation='offline_from_published_raw_samples', original_samples_reference=original.reference,
                    native_operations_requested=0, compute_calls_requested=0)
    owned = [*filled, support_path, report_path, *([labels] if labels is not None else [])]
    return dict(status='success', summary=metadata, output_paths=list(map(str, owned)),
        required_output_paths=list(map(str, owned)), retention_preserve_paths=[],
        manifest_extra_fields=dict(products=dict(samples=dict(schema_version=1, kind='scalar_field_samples',
            status='complete', metadata=metadata, data=data))))


def _postprocess_scalar(session: Any, *, outputs: list[Path], output_dir: Path, grid: Mapping[str, Any],
                        projection: Mapping[str, Any], request: Mapping[str, Any], frozen: Mapping[str, Any],
                        grid_record: Mapping[str, Any], manifest_record: Mapping[str, Any], row: Mapping[str, Any],
                        support_code: list, support_guards: list, support_source: Any,
                        fill_conductor_interiors: bool, publish_prepared_support: bool,
                        raw_mask_record: Mapping[str, Any] | None = None, owned_raw: bool = True,
                        failure_report: Path | None = None):
    """Apply one shared strict-interior postprocess to owned or borrowed raw samples."""
    published_outputs = list(outputs)
    support_record = None
    labels_path = None
    support_path = None
    if fill_conductor_interiors:
        support_path = session.declare_file(session.result_dir / 'scalar_conductor_support.json', 'required_evidence')
        filled = [session.declare_file(output_dir / name, 'solver_native_binary') for name in ('field_v_filled.pa', 'field_valid_filled.pa')]
        labels_path = (session.declare_file(session.result_dir / 'scalar_conductor_labels.csv', 'required_evidence')
                       if publish_prepared_support else None)
        try:
            raw_mask_record = dict(raw_mask_record) if raw_mask_record is not None else file_record(outputs[1], 'solver_native_binary')
            if support_source is not None:
                for record in support_guards: verify_record('prepared support before use', record)
                prior = json.loads(support_source.data_path('conductor_support').read_text(encoding='utf-8-sig'))
                expected = prior.get('prepared_identity')
                if (not isinstance(expected, Mapping)
                        or expected.get('projection_sha256') != support_source.data_records['projection']['sha256']
                        or expected.get('raw_mask_sha256') != support_source.data_records['sampled_field_valid']['sha256']
                        or expected.get('grid') != _classification_grid_identity(json.loads(support_source.data_path('grid').read_text(encoding='utf-8-sig')))):
                    raise ValueError('prepared support identity differs from source records')
                current = dict(projection_sha256=frozen['projection']['sha256'], grid=_classification_grid_identity(grid),
                               raw_mask_sha256=raw_mask_record['sha256'],
                               support_code_sha256=[r['sha256'] for r in support_code[::2]],
                               groups=sorted([list((r['instance_id'], r['electrode_group_id'])) for r in projection['electrode_groups']]))
                if expected != current:
                    raise ValueError('prepared support geometry/grid/mask/query identity differs')
            for record in support_code: verify_record('scalar support code before fill', record)
            from msplatform.backends.comsol.assembly_scalar_fill import fill_invalid_scalar_pa
            primary = None
            try:
                support = fill_invalid_scalar_pa(*outputs, *filled, projection=projection, request=request, grid=grid, chunk_nodes=grid['block_points'],
                    write_labels_path=labels_path, read_labels_path=(support_source.data_path('prepared_support_labels') if support_source is not None else None))
            except BaseException as failure:
                primary = failure
                raise
            finally:
                try:
                    for record in [*support_code, *support_guards]: verify_record('scalar support code and inputs after fill', record)
                except BaseException as failure:
                    if primary is None: raise
                    primary.add_note('scalar support post-check failed: ' + repr(failure))
            for path in filled: _validate_scalar_pa(path, grid)
            if support_source is None:
                counts = support['classifications']
                if sum(counts.values()) != row['invalid_count'] or counts.get('interior', 0) != support['filled_conductor_count']:
                    raise ValueError('scalar support raw mask accounting differs')
            if support_source is not None:
                counts = prior.get('result', {}).get('classifications')
                if (not isinstance(counts, Mapping) or any(
                        not isinstance(key, str) or type(value) is not int or value < 0
                        for key, value in counts.items())
                        or sum(counts.values()) != row['invalid_count']
                        or counts.get('interior', 0) != support['filled_conductor_count']):
                    raise ValueError('prepared support classification accounting differs')
                support['classifications'] = dict(counts)
                support['prepared_support_manifest'] = support_source.reference['manifest']
            prepared_identity = None
            if labels_path is not None:
                prepared_identity = dict(projection_sha256=frozen['projection']['sha256'], grid=_classification_grid_identity(grid),
                    raw_mask_sha256=raw_mask_record['sha256'],
                    support_code_sha256=[r['sha256'] for r in support_code[::2]],
                    groups=sorted([list((r['instance_id'], r['electrode_group_id'])) for r in projection['electrode_groups']]))
            write_json_atomic(support_path, dict(schema_version=1, role='assembly_scalar_conductor_support',
                grid=grid_record, projection=frozen['projection'], request=frozen['request'],
                field_solution_manifest=manifest_record, result=support, prepared_identity=prepared_identity))
            support_record = file_record(support_path, 'required_evidence')
            published_outputs = filled
        except BaseException as error:
            prior = list(getattr(error, 'failure_output_paths', ()))
            error.failure_output_paths = [*prior, *(path for path in [*(outputs if owned_raw else []), *filled, support_path, *([failure_report] if owned_raw and failure_report is not None else []), *([labels_path] if labels_path is not None else [])] if path.is_file())]
            raise
    return published_outputs, support_record, raw_mask_record, labels_path, support_path


def _freeze_pa_encoder_sources(session: Any) -> list[dict[str, Any]]:
    """Bind actual executed encoder and its existing header authorities."""
    from msplatform.backends.simion import scalar_pa_payload, standalone_pa_composition, collision_overlay
    records=[]
    for index,module in enumerate((scalar_pa_payload,standalone_pa_composition,collision_overlay)):
        src=Path(module.__file__).resolve(strict=True)
        if src.suffix!='.py' or not src.is_file():
            raise ValueError('scalar PA encoder source is unavailable: '+module.__name__)
        original=file_record(src,'required_evidence');verify_record('scalar PA encoder original',original)
        target=session.declare_file(session.input_dir/'scalar_pa_encoder'/str(index)/src.name,'required_evidence')
        target.parent.mkdir(parents=True,exist_ok=True);freeze_file(src,target)
        frozen=file_record(target,'required_evidence')
        if any(original[key]!=frozen[key] for key in ('bytes','sha256')):
            raise ValueError('scalar PA encoder frozen source differs: '+module.__name__)
        verify_record('scalar PA encoder frozen',frozen)
        session.add_input('scalar_pa_encoder_original_'+str(index),original)
        session.add_input('scalar_pa_encoder_frozen_'+str(index),frozen)
        records.extend((original,frozen))
    return records


def _finalize_scalar_outputs(outputs: list[Path], grid: Mapping[str, Any], code: list[dict[str, Any]]) -> None:
    for record in code: verify_record('scalar PA encoder before finalization',record)
    primary=None
    try:
        finalize_scalar_pair(outputs[0],outputs[1],grid)
    except BaseException as error:
        primary=error
        raise
    finally:
        try:
            for record in code: verify_record('scalar PA encoder after finalization',record)
        except BaseException as error:
            if primary is None: raise
            primary.add_note('scalar PA encoder source verification failed: '+repr(error))


def _freeze_support_sources(session: Any) -> list[dict[str, Any]]:
    """Record only the actual selected small Python support source files."""
    from msplatform.backends.comsol import assembly_scalar_fill
    from msplatform.components import shape_query
    from msplatform.contracts import rigid_transform
    from msplatform.backends.simion import standalone_pa_composition, collision_overlay
    modules = (assembly_scalar_fill, shape_query, rigid_transform, standalone_pa_composition, collision_overlay)
    records = []
    for index, module in enumerate(modules):
        name = module.__name__
        src = Path(module.__file__).resolve(strict=True)
        if src.suffix != '.py' or not src.is_file():
            raise ValueError('scalar support module source is unavailable: ' + name)
        original = file_record(src, 'required_evidence')
        verify_record('scalar support original', original)
        target = session.declare_file(session.input_dir / 'scalar_support' / str(index) / src.name, 'required_evidence')
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(src, target)
        frozen = file_record(target, 'required_evidence')
        if any(original[key] != frozen[key] for key in ('bytes', 'sha256')):
            raise ValueError('scalar support frozen source differs: ' + name)
        verify_record('scalar support frozen', frozen)
        session.add_input('scalar_support_original_' + str(index), original)
        session.add_input('scalar_support_frozen_' + str(index), frozen)
        records.extend((original, frozen))
    return records

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
    if any(
        not (
            type(value) is int and value >= 0
            or type(value) is float and math.isfinite(value) and value >= 0 and value.is_integer()
        )
        for value in (finite, invalid)
    ) or finite + invalid != grid['point_count']:
        raise ValueError('world scalar mask accounting differs')
    row['fem_valid'], row['invalid_count'] = int(finite), int(invalid)
    validate_solution_readback(row.get('solution_readback'), study_tag=grid['study_tag'],
                               solution_tag=grid['solution_tag'], dataset_tag=grid['dataset_tag'])
    for name in ('study_tag', 'solution_tag', 'dataset_tag', 'dataset_solution', 'solution_empty', 'solution_dofs', 'solution_count', 'stored_main_solutions'):
        if row['solution_readback'].get(name) != solution_identity.get(name):
            raise ValueError('world scalar stored solution readback differs: ' + name)
