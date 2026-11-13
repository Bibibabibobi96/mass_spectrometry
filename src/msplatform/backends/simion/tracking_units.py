"""Ordinal tracking units and manifest-bound native completion projections.

The shared recovery planner owns reuse/replay; this adapter verifies SIMION
completion and scientific applicability. A unit is never a new mother cohort.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from msplatform.io.manifest_records import file_record,verify_record
from msplatform.execution.recovery import (
    WholeUnitReplayUnit, build_whole_unit_replay_plan, _whole_unit_artifact_hashes,
)


def partition_tracking_units(plan, *, unit_size=None, reused_unit_keys=()):
    """Slice insertion-order source ordinals, preserving every scientific ID."""
    count = len(plan['rows'])
    if unit_size is not None and (type(unit_size) is not int or unit_size <= 0):
        raise ValueError('tracking unit_size must be a positive integer')
    size = unit_size if unit_size is not None else max(count, 1)
    units = []
    for index, start in enumerate(range(0, count, size), 1):
        high = min(start+size, count)
        key = f'unit_{index:04d}'
        names = (['build_tracking_iob','verify_tracking_iob','track_fly'] if unit_size is None
                 else [f'{name}__{key}' for name in ('build_tracking_iob','verify_tracking_iob','track_fly')])
        units.append(dict(key=key,index=index,source_row_range=[start+1,high],
            expected_particle_ids=[row['particle_id'] for row in plan['rows'][start:high]],
            operation_ids=names,scheduler_batch=dict(index=index,count=high-start,
                particle_id_min=start+1,particle_id_max=high,simion_particle_id_offset=start)))
    reused = set(reused_unit_keys)
    if len(reused) != len(tuple(reused_unit_keys)) or not reused <= {unit['key'] for unit in units}:
        raise ValueError('tracking reused unit keys differ from the frozen ordinal partition')
    operations, dependencies = [], {}
    for unit in units:
        unit['action'] = 'reuse' if unit['key'] in reused else 'replay'
        if unit['action'] == 'replay':
            build, verify, fly = unit['operation_ids']
            operations.extend((build,verify,fly))
            dependencies.update({verify:[build],fly:[verify]})
    return dict(units=units,unit_size=unit_size,expected_operation_ids=operations,operation_dependencies=dependencies)


def slice_tracking_plan(plan, unit):
    """Only native execution rows/events are sliced; provenance mother stays full."""
    result = copy.deepcopy(plan)
    low, high = unit['source_row_range']
    result['rows'] = result['rows'][low-1:high]
    result['native_source_rows'] = result['native_source_rows'][low-1:high]
    ids = set(unit['expected_particle_ids'])
    result['propagation']['consumed_plane_events'] = [event for event in result['propagation']['consumed_plane_events']
                                                    if event['particle_id'] in ids]
    return result


def tracking_applicability(plan):
    """Freeze scientific meanings and exact renderer bytes, not owner paths.

    Clock record locations are transportation; their full remaining identities
    are retained. Every other selected source/policy field is included exactly.
    """
    from .resources import native_resource_path
    from . import tracking_program
    from msplatform.execution.resources import resource_path
    names = ('build_tracking_iob.lua','iob_core.lua','oatof_analyzer_component.lua',
             'single_flight_pulse_hook.lua','single_flight_frontend_hook.lua','rf_drive.lua','voltage_waveforms.lua')
    if plan['flight'].get('tracking_kind') in {'independent_rf','independent_oa','rf_ip'}:
        names=('build_tracking_iob.lua','iob_core.lua','model_drive.lua','rf_drive.lua','rf_tracking.lua')
        if plan['flight']['tracking_kind']=='independent_oa':names+=('single_flight_pulse_hook.lua','voltage_waveforms.lua')
        if plan['flight']['tracking_kind']=='rf_ip':
            names+=('single_flight_pulse_hook.lua','voltage_waveforms.lua','native_drive.lua',
                    'collision_hs1_gas.lua','rf_ip_gas_selection.lua','rf_ip_tracking_hs1.lua')
    resources = {name:hashlib.sha256(native_resource_path(name).read_bytes()).hexdigest() for name in names}
    resources['native_run_path.lua'] = hashlib.sha256(resource_path('native_run_path.lua').read_bytes()).hexdigest()
    resources['tracking_program.py'] = hashlib.sha256(Path(tracking_program.__file__).read_bytes()).hexdigest()
    resources['tracking_execution.py'] = hashlib.sha256(Path(__file__).with_name('tracking_execution.py').read_bytes()).hexdigest()
    resources['tracking_units.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if plan['flight'].get('tracking_kind') in {'independent_rf','independent_oa','rf_ip'}:
        for name in ('rf_tracking_program.py','rf_tracking_execution.py','rf_tracking_collection.py'):
            resources[name]=hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    if plan['flight'].get('tracking_kind') == 'rf_ip':
        resources['tracking_collection.py'] = hashlib.sha256(Path(__file__).with_name('tracking_collection.py').read_bytes()).hexdigest()
    fields = ('source_realization','field_manifest_identity','model_identity_sha256','rows','native_source_rows','source_provenance',
              'absolute_deadlines_us_by_particle_id','flight','propagation','observations','numerics')
    value = {key:copy.deepcopy(plan[key]) for key in fields}
    if plan['flight'].get('tracking_kind') == 'rf_ip':
        value['hs1_identity'] = copy.deepcopy(plan['hs1_identity'])
    clocks = value['source_provenance']['clock_records']
    for key in ('clock_authority','instrument_epoch'):
        clocks[key].pop('path',None)
    # Provenance2 data_root resolves only the two explicitly bound clock files.
    clocks.pop('data_root',None)
    value['units'] = [{key:unit[key] for key in ('key','source_row_range','expected_particle_ids')}
                      for unit in plan['units']]
    value['renderer_resources'] = resources
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()



def require_tracking_executable_identity(plan, recovery, executable):
    """Bind native replay to the actual binary; pure reuse needs no tool.

    Paths are deployment details. A partial replay may combine completed units
    only when their recorded binary bytes match the newly selected executable.
    Historical missing identity stays unknown on read-only/complete reuse.
    """
    previous = recovery['index'].get('native_executable_identity') if recovery else None
    if not plan['expected_operation_ids']:
        return copy.deepcopy(previous)
    if executable is None or not Path(executable).is_file():
        raise ValueError('tracking executable identity requires the selected native executable')
    record = file_record(Path(executable),'solver_native_binary')
    selected = {key:record[key] for key in ('bytes','sha256')}
    if recovery and recovery['reused_unit_keys']:
        if previous is None:
            raise ValueError('tracking predecessor executable identity is missing for partial replay')
        if previous != selected:
            raise ValueError('tracking predecessor executable identity differs for partial replay')
    return selected


def _validate_completed_unit(row, plan, unit):
    from .tracking_collection import collect_tracking_logs
    from .native_completion import require_one_fly_completion
    for key in ('stdout_record','process_record'):
        verify_record('completed tracking unit '+key,row[key])
    receipt = json.loads(Path(row['process_record']['path']).read_text(encoding='utf-8-sig'))
    observed, release = receipt.get('observation'),receipt.get('host_release')
    if (not isinstance(observed,dict) or observed.get('exit_code') != 0
            or observed.get('resource_budget_exceeded') is True
            or any(type(observed.get(key)) is not int or observed[key] <= 0
                   for key in ('root_process_id','root_process_started_at_utc_ticks'))
            or not isinstance(release,dict) or release.get('error') is not None
            or release.get('inherited') is not False or not release.get('token')
            or release.get('result') != dict(status='released',token=release['token'])):
        raise ValueError('tracking unit lacks natural successful exit and released actual owner')
    stdout = Path(row['stdout_record']['path'])
    with stdout.open(encoding='utf-8-sig') as stream:
        require_one_fly_completion(stream)
    subset = slice_tracking_plan(plan,unit)
    batch = dict(source_row_range=[1,len(subset['rows'])],expected_particle_ids=unit['expected_particle_ids'],
                 build_metadata=row['build_metadata'])
    return collect_tracking_logs([stdout],source_rows={item['particle_id']:item for item in subset['rows']},
        source_provenance=plan['source_provenance'],flight=plan['flight'],batches=[batch])


def inspect_tracking_recovery(plan, recovery_reference):
    """Read only a directly bound terminal manifest; never search ancestors."""
    verify_record('tracking predecessor manifest',recovery_reference)
    manifest_path = Path(recovery_reference['path']).resolve()
    if manifest_path.name != 'run_manifest.json':
        raise ValueError('tracking recovery requires the canonical run_manifest.json record')
    hashes, manifest = _whole_unit_artifact_hashes(manifest_path.parent)
    candidates = [path for path in hashes if path.name=='tracking_units.json' and path.parent.name=='logs']
    if len(candidates) != 1:
        raise ValueError('predecessor requires its unique manifest-bound tracking units output')
    path = candidates[0]
    if hashlib.sha256(path.read_bytes()).hexdigest().upper() != hashes[path]:
        raise ValueError('tracking unit index hash differs')
    index = json.loads(path.read_text(encoding='utf-8-sig'))
    if (type(index.get('schema_version')) is not int or index['schema_version'] != 1
            or index.get('role') != 'simion_tracking_units' or index.get('applicability_sha256') != tracking_applicability(plan)
            or [row['key'] for row in index.get('units',[])] != [unit['key'] for unit in plan['units']]):
        raise ValueError('tracking predecessor scientific applicability or partition differs')
    immutable = index.get('immutable_inputs')
    if not isinstance(immutable,list) or not immutable:
        raise ValueError('tracking predecessor lacks its frozen execution input closure')
    for record in immutable:
        if hashes.get(Path(record['path']).resolve()) != record['sha256'].upper():
            raise ValueError('tracking predecessor immutable input is not manifest-bound')
        verify_record('tracking predecessor immutable input',record)
    reused = []
    for row,unit in zip(index['units'],plan['units'],strict=True):
        if (row['source_row_range'] != unit['source_row_range'] or row['expected_particle_ids'] != unit['expected_particle_ids']
                or type(row.get('complete')) is not bool):
            raise ValueError('tracking predecessor ordinal/ID/completion facts differ')
        if not row['complete']:
            continue  # Do not read or reinterpret partial native output.
        for name in ('stdout_record','process_record'):
            record = row[name]; target = Path(record['path']).resolve()
            if hashes.get(target) != record['sha256'].upper():
                raise ValueError('completed tracking unit record is not direct-parent manifest-bound')
        _validate_completed_unit(row,plan,unit)
        reused.append(unit['key'])
    return dict(reused_unit_keys=reused,index=index,index_path=str(path),manifest=manifest,
                predecessor_run_dir=str(manifest_path.parent))


def prepare_tracking_recovery(plan, recovery_reference, *, output_dir):
    """Revalidate actual completion, then invoke the sole whole-unit planner."""
    inspected = inspect_tracking_recovery(plan,recovery_reference)
    reused = set(inspected['reused_unit_keys'])
    units = [WholeUnitReplayUnit(row['key'],
        (Path(inspected['index_path']),Path(row['stdout_record']['path']),Path(row['process_record']['path']))
        if row['key'] in reused else (Path('not-read-incomplete-'+row['key']),),row['key'] in reused)
        for row in inspected['index']['units']]
    replay = build_whole_unit_replay_plan(predecessor_run_dir=Path(inspected['predecessor_run_dir']),
        output_dir=Path(output_dir),units=units)
    return inspected,replay
