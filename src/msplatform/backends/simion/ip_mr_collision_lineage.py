"""Bind source-free collision conversion to one published geometry producer."""
from __future__ import annotations

import copy
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Mapping

from msplatform.backends.simion.model import model_geometry
from msplatform.io.manifest_records import record_path, verify_record
from msplatform.results.artifacts import open_artifact


def plan_collision_conversions(model: Any, geometry_reference: Mapping[str, Any], *,
                               output_directory: Path) -> dict[str, Any]:
    """Derive four collision conversions from the verified producer and model.

    The owner supplies a fresh private run output directory and registers the
    returned geometry reference as a protected source. No PA is created here.
    """
    source = open_artifact(geometry_reference, expected_kind='geometry_artifact')
    if (source.producer['status'] != 'success' or source.producer['mode'] != 'geometry_only'
            or source.metadata.get('backend') != 'simion'
            or source.metadata.get('geometry_materialized') is not True
            or source.metadata.get('field_status') != 'not_solved'):
        raise ValueError('successful SIMION geometry producer required')
    compiled = model_geometry(model)
    if compiled.frontend_geometry.get('role') != 'simion_ip_mr_complete_geometry':
        raise ValueError('complete selected RF/IP/MR geometry required')
    actual = json.loads(source.data_path('compiled_geometry').read_text(encoding='utf8'))
    # JSON canonicalizes the dataclass downstream tuple to a list.
    if actual != json.loads(json.dumps(asdict(compiled), allow_nan=False)):
        raise ValueError('published compiled geometry differs from prepared model')
    assets = source.metadata.get('native_assets')
    components = compiled.frontend_geometry.get('asset_components')
    if (not isinstance(assets, dict) or not isinstance(components, dict)
            or set(assets) != set(compiled.frontend_gems) or set(assets) != set(components)
            or len(assets) != 4):
        raise ValueError('exact four physical geometry assets required')
    scope = compiled.frontend_geometry['composition_plan']['scope']['instance_ids']
    projects = compiled.frontend_geometry['composition_plan']['components']
    if sum(projects[name]['project_id'] == 'rf_multipole_ion_optics' for name in scope) != 1:
        raise ValueError('selected five-slot case requires exactly one RF component')
    if source.metadata.get('provider_content_identities') != compiled.provider_content_identities:
        raise ValueError('geometry producer component source identities differ')
    output = Path(output_directory)
    if not output.is_absolute():
        raise ValueError('explicit absolute run output directory required')
    records = source.data_records
    paths = source.data_locations
    verify_record('geometry source manifest',dict(source.reference['manifest'],path=str(source.manifest_location)))
    manifest=json.loads(source.manifest_location.read_text(encoding='utf-8-sig'))
    if records['compiled_geometry'] not in manifest['inputs'].values():
        raise ValueError('compiled geometry must be the producer input')
    from types import SimpleNamespace
    from msplatform.execution.owner import _writer_completion
    from msplatform.backends.simion.native_plans import plan_geometry_build
    run_root=source.manifest_location.parent
    seed=dict(manifest['inputs']['structural_seed'])
    seed['path']=str(record_path(seed,base_dir=run_root))
    verify_record('geometry structural seed',seed)
    geometry_plan=plan_geometry_build(compiled,run_directory=run_root,seed_record=seed,
        native_path_resource=run_root/'inputs/native_sources/native_run_path.lua')
    expected_ops=[row['operation_id'] for row in geometry_plan.operations]
    by_operation={row['operation_id']:row for row in geometry_plan.operations}
    completion_path=run_root/'results/execution_completion.json'
    matches=[r for r in manifest['outputs'] if record_path(r,base_dir=run_root)==completion_path.resolve()]
    if len(matches)!=1:raise ValueError('unique geometry completion output required')
    completion_record=dict(matches[0],path=str(completion_path))
    verify_record('geometry producer completion',completion_record)
    completion=json.loads(completion_path.read_text(encoding='utf-8-sig'))
    if (completion.get('role')!='run_artifact_workflow_completion' or completion.get('status')!='success'
            or completion.get('run_id')!=source.producer['run_id']):
        raise ValueError('successful matching geometry completion required')
    writer=completion['writer_completion']
    _writer_completion(SimpleNamespace(writers_stopped=True,operations=writer['operations'],
        resource_releases=writer['resource_releases'],expected_operation_ids=expected_ops))
    if ([row['operation_id'] for row in writer['operations']]!=expected_ops
            or any(row['observation']['returncode']!=0 for row in writer['operations'])):
        raise ValueError('complete successful geometry operations required')
    tasks = []
    for index, role in enumerate(sorted(assets), 1):
        member = assets[role]
        labels = ['raw_geometry','surface_witnesses']
        if 'surface_state' in member: labels.append('surface_state')
        if 'fractional_surface' in member: labels.append('fractional_surface')
        if 'surface_state' not in member and 'fractional_surface' not in member: raise ValueError('missing surface evidence')
        expected = {label: role+'_'+label for label in labels}
        if (member != expected or any(key not in records for key in expected.values())
                or any(records[key] not in manifest['outputs'] for key in expected.values())):
            raise ValueError('published native geometry asset closure differs')
        located = {label: Path(paths[key]) for label, key in expected.items()}
        selected = {label: dict(copy.deepcopy(records[key]), path=str(located[label]))
                    for label, key in expected.items()}
        raw = located['raw_geometry']; surface = located.get('fractional_surface')
        if 'surface_state' in located:
            state=json.loads(located['surface_state'].read_text(encoding='utf8'))
            domain=compiled.frontend_geometry['numerical_domains'][role]
            dimensions=[domain['dimensions']['n'+axis] for axis in 'xyz']
            pitch=[domain['cell_mm_xyz'][axis] for axis in 'xyz']
            from .native_surface_state import validate_native_surface_state
            native_grid=dict(zip(('nx','ny','nz'),dimensions,strict=True), **dict(zip(('dx_mm','dy_mm','dz_mm'),pitch,strict=True)))
            validate_native_surface_state(state,grid=native_grid,surface_present=surface is not None)
        operation=by_operation.get('geometry_'+role)
        if operation is None: raise ValueError('geometry role differs from its actual planned operation outputs')
        outputs=operation['outputs']
        if 'optional_surface' in operation:
            expected_paths={'raw_geometry':outputs[0], 'surface_witnesses':outputs[1], 'surface_state':outputs[2], 'fractional_surface':operation['optional_surface']}
        else:
            expected_paths=dict(zip(('raw_geometry','fractional_surface','surface_witnesses'),outputs,strict=True))
        if any(path.resolve()!=Path(expected_paths[key]).resolve() for key,path in located.items()):
            raise ValueError('geometry role differs from its actual planned operation outputs')
        if raw.suffix.lower() != '.pa#' or (surface is not None and surface != raw.with_suffix('.pa-surf')):
            raise ValueError('published raw PA and fractional companion stems differ')
        target = output / f'collision_{index:02d}.pa'
        if target.exists() or target.with_suffix('.pa-surf').exists():
            raise FileExistsError('collision conversion destinations must be fresh')
        tasks.append(dict(role=role, source_records=selected,
            raw_path=str(raw), output_path=str(target),
            build_operation=f'collision_build_{index:02d}', verify_operation=f'collision_verify_{index:02d}',
            operations=[dict(operation_id=f'collision_build_{index:02d}',mode='build',depends_on=[]),
                        dict(operation_id=f'collision_verify_{index:02d}',mode='verify',
                             depends_on=[f'collision_build_{index:02d}'])]))
    reference=source.reference
    compiled_record=dict(records['compiled_geometry'],path=str(paths['compiled_geometry']))
    guards=[dict(reference['manifest']),compiled_record,seed,completion_record]
    for task in tasks:
        guards.extend(copy.deepcopy(list(task['source_records'].values())))
    return dict(geometry_reference=reference, source_references=[dict(manifest_record=reference['manifest'])],
        compiled_geometry_record=compiled_record, geometry_completion_record=completion_record,
        immutable_input_records=guards,
        provider_content_identities=copy.deepcopy(compiled.provider_content_identities), tasks=tasks)


def collision_conversion_result(plan: Mapping[str, Any], task: Mapping[str, Any], *,
                                output_record: Mapping[str, Any], surface_record: Mapping[str, Any] | None,
                                build_log_record: Mapping[str, Any], verify_log_record: Mapping[str, Any],
                                converter_record: Mapping[str, Any]) -> dict[str, Any]:
    """Bind an owner's verified full-node audit logs to exact inputs and outputs.

    The caller must have run the exact task with the existing RunSession and
    checked its process and host-release receipts. Marker text alone does not
    establish that a process ran; this helper validates and binds its evidence.
    """
    if task not in plan['tasks']:
        raise ValueError('conversion task is not in this geometry plan')
    verify_record('geometry source manifest',dict(plan['geometry_reference']['manifest']))
    verify_record('compiled geometry',dict(plan['compiled_geometry_record']))
    verify_record('collision converter',dict(converter_record))
    for label, record in task['source_records'].items():
        verify_record('conversion source '+label, dict(record))
    for label, record in [('output', output_record), *([('surface', surface_record)] if surface_record is not None else []),
                          ('build log', build_log_record), ('verify log', verify_log_record)]:
        verify_record('conversion '+label, dict(record))
    target=Path(task['output_path']).resolve()
    if (Path(output_record['path']).resolve()!=target
            or (surface_record is not None and Path(surface_record['path']).resolve()!=target.with_suffix('.pa-surf'))):
        raise ValueError('converted output belongs to a different planned task')
    state_record=task['source_records'].get('surface_state')
    state=json.loads(Path(state_record['path']).read_text(encoding='utf8')) if state_record else None
    empty=state is not None and state.get('mode')=='empty'
    if empty != (surface_record is None): raise ValueError('converted surface representation differs from source state')
    if empty and (state.get('offset_nodes')!=0 or state.get('scanned_nodes')!=state['grid'][0]*state['grid'][1]*state['grid'][2]):
        raise ValueError('empty source surface proof differs')
    import re
    pattern=r'RAW_COLLISION_(BUILD|VERIFY)=PASS nodes=(\d+) metal_nodes=(\d+) surface_nodes=(\d+) FIELD_STATUS=not_solved REFINE=False FLY=False'
    counts=[]
    for mode,record in [('BUILD',build_log_record),('VERIFY',verify_log_record)]:
        lines=Path(record['path']).read_text(encoding='utf8').splitlines()
        matches=[re.fullmatch(pattern,line) for line in lines if line.startswith('RAW_COLLISION_')]
        if len(matches)!=1 or matches[0] is None or matches[0].group(1)!=mode:
            raise ValueError('exact native collision conversion marker required')
        values=tuple(int(x) for x in matches[0].groups()[1:])
        if values[0]<=0 or values[1]<=0 or values[1]>values[0] or values[2]>values[0] or (values[2]!=0 if empty else values[2]<=0):
            raise ValueError('invalid native collision node counts')
        counts.append(values)
    if empty and counts[0][0]!=state['scanned_nodes']: raise ValueError('conversion node count differs from source proof')
    if counts[0]!=counts[1]:
        raise ValueError('build and cold verification node counts differ')
    return dict(role=task['role'],geometry_reference=copy.deepcopy(plan['geometry_reference']),
        compiled_geometry_record=copy.deepcopy(plan['compiled_geometry_record']),
        source_records=copy.deepcopy(task['source_records']),output_record=dict(output_record),
        surface_record=dict(surface_record) if surface_record is not None else None,build_log_record=dict(build_log_record),
        verify_log_record=dict(verify_log_record),converter_record=dict(converter_record),nodes=counts[0][0],metal_nodes=counts[0][1],
        surface_nodes=counts[0][2],native_process_receipts='owner_required')
