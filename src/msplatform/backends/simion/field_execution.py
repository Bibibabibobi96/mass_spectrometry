"""Explicit solved-field action planning; the existing RunSession remains sole owner."""
from __future__ import annotations

from functools import partial
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from msplatform.execution.inputs import freeze_file
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.resources import resource_path
from msplatform.io.file_identity import file_sha256
from .field_bank import field_bank
from .field_closure import load_field_model, data_record, downstream_identity, require_downstream_reuse
from .field_worker import run_member
from .downstream_fields_worker import DOWNSTREAM_RESOURCES, run_downstream
from .model import model_geometry, require_prepared_model
from .model_execution import _protected_source, _clock_reference
from .native_io import apply_native_io_mode
from .native_plans import plan_solve_fields, operating_member_identity, _plan_downstream_solve_with_assets, plan_field_workbench
from .pa_family_cache import canonical_pa_family_cache_key
from .resources import native_resource_path


def plan_fields_execution(model, *, numerics: dict, reuse_fields_reference=None) -> dict:
    """Derive the actual stage-worker graph without source, I/O or native side effects.

    Reuse still executes real member/downstream workers, copies an owned response
    closure, and builds/reopens the new run's field workbench. It is not whole-run
    zero-native reuse. Reference validation belongs to the admitted action.
    """
    if model_geometry(model).frontend_geometry.get('role') in {'simion_independent_rf_geometry', 'simion_independent_oa_geometry'}:
        from .rf_field_execution import plan_rf_fields
        return plan_rf_fields(model, numerics=numerics, reuse_fields_reference=reuse_fields_reference)
    if not isinstance(numerics, dict) or 'downstream_convergence_v' not in numerics:
        raise ValueError('field numerics require explicit downstream convergence')
    frontend = {key:value for key,value in numerics.items() if key != 'downstream_convergence_v'}
    field_plan = plan_solve_fields(model, numerics=frontend)
    # Reject unsupported field-container science before any expensive member,
    # not after producing otherwise valid responses. The writer repeats these
    # same canonical projections at its later input-publication boundary.
    from .field_validation import interface_field_probes, native_priority_occupancy_probes
    from .frontend import native_frontend_instances
    geometry = model_geometry(model).frontend_geometry
    _, tof = native_frontend_instances(geometry['composition_plan'])
    native_priority_occupancy_probes(geometry, field_plan['field_design'])
    interface_field_probes(geometry, require_prepared_model(model)['components_resolved'][tof])
    roles = {'flight_tube','reflectron','detector'}
    convergence = numerics['downstream_convergence_v']
    import math
    if (not isinstance(convergence, dict) or set(convergence) != roles
            or any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0
                   for value in convergence.values())):
        raise ValueError('downstream convergence requires three finite positive values')
    ids = ['materialize_geometry']
    dependencies = {}
    for member in field_plan['ordered_members']:
        domain, point = member['domain_id'], member['member_id']
        name = 'frontend_' + domain + '_' + point
        parents = ['materialize_geometry']
        if member['requires_published_parent']:
            parents.append('frontend_parent_' + member['requires_published_parent'])
        dependencies[name] = parents
        ids.append(name)
    ids.extend(['downstream_fields','materialize_field_responses','build_fields','verify_fields'])
    dependencies['downstream_fields'] = ['materialize_geometry']
    dependencies['materialize_field_responses'] = ids[1:-3]
    dependencies['build_fields'] = ['materialize_field_responses']
    dependencies['verify_fields'] = ['build_fields']
    return dict(field_plan=field_plan, expected_operation_ids=ids, operation_dependencies=dependencies,
        downstream_convergence_v=dict(convergence), reuse_requested=reuse_fields_reference is not None)


FIELD_RESOURCES = (*DOWNSTREAM_RESOURCES, 'build_dirichlet_patch_operating_pa.lua',
    'export_detached_standalone_pa.lua', 'audit_frontend_working_fields.lua', 'build_field_iob.lua', 'iob_core.lua')


def _copy_records(session, copies: list[dict], *, callback: Callable, operation_id: str) -> list[dict]:
    """Consume the unique admitted payload worker's actual guarded-copy records."""
    for row in copies:
        session.declare_file(row['destination'], 'solver_native_binary')
    actual = callback(copies, session=session, operation_id=operation_id)
    operations = [row for row in session.operations if row['operation_id'] == operation_id]
    if (len(operations) != 1 or operations[0]['observation'].get('exit_confirmed') is not True
            or operations[0]['observation'].get('returncode') != 0 or not isinstance(actual, (list,tuple))
            or len(actual) != len(copies)):
        raise ValueError('field materializer did not complete its actual declared payload operation')
    records = []
    for copy, record in zip(copies, actual, strict=True):
        path, source = session.canonical_path(copy['destination']), copy['source_record']
        if (Path(record['path']).resolve() != path or not path.is_file() or path.is_symlink()
                or path.stat().st_size != source['bytes'] or record.get('exists') is not True
                or record['bytes'] != source['bytes'] or str(record['sha256']).upper() != str(source['sha256']).upper()
                or path.samefile(source['path'])):
            raise ValueError('field copy receipt differs from its independent declared source/destination')
        records.append(dict(path=str(path), exists=True, bytes=record['bytes'], sha256=str(record['sha256']).upper(),
                            retention_role='solver_native_binary'))
    return records


def execute_fields(session, *, model_reference: Mapping, numerics: dict, limits: Mapping,
                   materialize_geometry: Callable, materializer_record: Mapping,
                   allow_asynchronous_io: bool | None = None,
                   reuse_fields_reference: Mapping | None = None) -> dict[str, Any]:
    """Solve only explicit model fields and publish their owned source-free data closure.

    This action returns the original owner's six completion keys. It never
    creates a scheduler, samples particles, installs a Program, flies, or writes
    another manifest. Cache source keys remain protected through publication.
    """
    if not callable(materialize_geometry) or materializer_record is None:
        raise ValueError('field execution requires the unique admitted payload materializer')
    reserve = limits.get('reserved_run_payload_bytes')
    if type(reserve) is not int or reserve < 0:
        raise ValueError('field execution requires explicit reserved_run_payload_bytes')
    if allow_asynchronous_io is not None and type(allow_asynchronous_io) is not bool:
        raise TypeError('field asynchronous I/O control must be boolean or None')
    verify_record('field payload materializer', dict(materializer_record))
    callback = materialize_geometry.func if isinstance(materialize_geometry, partial) else materialize_geometry
    source_file = inspect.getsourcefile(inspect.unwrap(callback))
    if source_file is None or Path(source_file).resolve() != Path(materializer_record['path']).resolve():
        raise ValueError('field payload materializer source differs from its bound record')
    source = load_field_model(model_reference)
    if model_geometry(source.model).frontend_geometry.get('role') in {'simion_independent_rf_geometry', 'simion_independent_oa_geometry'}:
        from .rf_field_execution import execute_rf_fields
        return execute_rf_fields(session, source=source, numerics=numerics, limits=limits,
            materialize_geometry=materialize_geometry, materializer_record=materializer_record,
            allow_asynchronous_io=allow_asynchronous_io, reuse_fields_reference=reuse_fields_reference)
    model, document = source.model, require_prepared_model(source.model)
    graph = plan_fields_execution(model, numerics=numerics, reuse_fields_reference=reuse_fields_reference)
    if tuple(graph['expected_operation_ids']) != session.expected_operation_ids:
        raise ValueError('field graph differs from its admitted original owner operations')
    if dict(session.operation_dependencies) != graph['operation_dependencies']:
        raise ValueError('field dependencies differ from their frozen owner graph')
    _protected_source(session, source.artifact.reference['manifest'],
        required_paths=[row['raw_record']['path'] for row in source.native_assets.values()])
    frozen = session.input_dir/'native_sources'
    records = {}

    def small(name, target, *, source_path=None, value=None):
        target = session.declare_file(target, 'required_evidence')
        if target.exists():
            raise FileExistsError('field action refuses existing input: '+str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        if source_path is not None:
            freeze_file(Path(source_path), target)
        else:
            target.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8', newline='\n')
        record = file_record(session.canonical_path(target), 'required_evidence')
        session.add_input(name, record)
        return record

    for name in FIELD_RESOURCES:
        records['resource_'+name] = small('field_source_'+name, frozen/name, source_path=native_resource_path(name))
    records['resource_native_run_path.lua'] = small('field_source_native_run_path', frozen/'native_run_path.lua',
                                                  source_path=resource_path('native_run_path.lua'))
    records['compiled_model'] = small('compiled_model', session.input_dir/'compiled_model.json', value=document)
    records['source_model_manifest'] = small('model_source_manifest', session.input_dir/'source_model_manifest.json',
                                            source_path=source.artifact.reference['manifest']['path'])
    small('field_materializer_source', session.input_dir/'field_materializer_source.py', source_path=source_file)
    clock_root = session.input_dir/'clock'
    clock_relative = _clock_reference(document, source.clock_authority_reference)
    records['clock_authority'] = small('clock_authority', clock_root/'clock_authority.json',
        source_path=source.clock_authority_reference['contract']['path'])
    records['instrument_epoch'] = small('instrument_epoch', clock_root/clock_relative,
        source_path=source.clock_authority_reference['authority']['path'])
    _clock_reference(document, dict(contract=records['clock_authority'], authority=records['instrument_epoch'], data_root=str(clock_root)))
    records['field_design'] = small('field_design', session.input_dir/'field_design.json', value=graph['field_plan']['field_design'])
    records['field_numerics'] = small('field_numerics', session.input_dir/'field_numerics.json', value=numerics)
    resources = {name:frozen/name for name in FIELD_RESOURCES}
    executable = session.context.tools['simion']
    tool = dict(release='SIMION 2020', executable_bytes=executable.stat().st_size, executable_sha256=file_sha256(executable))
    member_tool = dict(simion_identity=tool, builder_identity=dict(
        operating_builder=records['resource_build_dirichlet_patch_operating_pa.lua']['sha256'],
        exporter=records['resource_export_detached_standalone_pa.lua']['sha256']))
    raw_static = {role:source.native_assets[role] for role in ('flight_tube','reflectron','detector')}
    static_identity = downstream_identity(model, raw_assets=raw_static, convergence_v=graph['downstream_convergence_v'],
        tool_identity=tool, builder_identities={name:records['resource_'+name]['sha256'] for name in DOWNSTREAM_RESOURCES})
    work = session.run_dir/'simion/fields/downstream'
    downstream_plan, asset_plan = _plan_downstream_solve_with_assets(model, raw_geometry_assets=raw_static,
        working_directory=work, convergence_v=graph['downstream_convergence_v'],
        exporter_resource=resources['export_standalone_pa.lua'], verifier_resource=resources['audit_downstream_fields.lua'])
    copies, frontend_raw = [], {}
    for domain in graph['field_plan']['field_design']['domains']:
        name = domain['domain_id']
        target = session.run_dir/'simion/fields/geometry'/name/'frontend.pa#'
        copies.append(dict(source_record=source.native_assets[name]['raw_record'], destination=str(target)))
        frontend_raw[name] = target
    reused_assets = None
    reuse_source = None
    if reuse_fields_reference is None:
        copies.extend(downstream_plan.input_copies)
    else:
        reuse_source, prior = require_downstream_reuse(reuse_fields_reference, static_identity)
        _protected_source(session, reuse_source.reference['manifest'], required_paths=[row['carrier_record']['path'] for row in prior.values()])
        records['reuse_field_manifest'] = small('reuse_field_manifest', session.input_dir/'reuse_field_manifest.json',
            source_path=reuse_source.reference['manifest']['path'])
        records['reuse_downstream_audit'] = small('reuse_downstream_audit', session.input_dir/'reuse_downstream_audit.json',
            source_path=data_record(reuse_source, 'downstream_audit')['path'])
        reused_assets = {}
        for row in asset_plan:
            role = row['role']
            targets = {Path(path).suffix:Path(path) for path in row['family_paths']}
            entries = prior[role]['family_records'] or [prior[role]['carrier_record']]
            for record in entries:
                target = targets[Path(record['path']).suffix] if targets else Path(row['carrier_path'])
                copies.append(dict(source_record=record, destination=str(target)))
            reused_assets[role] = dict(carrier_path=row['carrier_path'], family_paths=row['family_paths'])
    copied = _copy_records(session, copies, callback=materialize_geometry, operation_id='materialize_geometry')
    by_path = {row['path']:row for row in copied}
    frontend_records = {name:by_path[str(session.canonical_path(path))] for name,path in frontend_raw.items()}
    if reused_assets is not None:
        reused_assets = {role:dict(carrier_record=by_path[str(session.canonical_path(row['carrier_path']))],
            family_records=[by_path[str(session.canonical_path(path))] for path in row['family_paths']]) for role,row in reused_assets.items()}
    cache_root = session.artifact_root/'common/simion/pa_family_cache'
    parents, members = {}, []
    for member in graph['field_plan']['ordered_members']:
        domain, member_id = member['domain_id'], member['member_id']
        parent = parents.get(member_id) if member['requires_published_parent'] else None
        identity = operating_member_identity(graph['field_plan'], domain_id=domain, member_id=member_id,
            tool_identity=member_tool, published_parent=parent)
        key = canonical_pa_family_cache_key(identity)
        session.renew_capacity(protected_cache_keys=[key])
        report = run_member(session, operation_id='frontend_'+domain+'_'+member_id, limits=limits,
            parameters=dict(field_plan=graph['field_plan'], domain_id=domain, member_id=member_id,
                tool_identity=member_tool, raw_geometry_record=frontend_records[domain], cache_root=cache_root,
                resources=dict(operating_builder=resources['build_dirichlet_patch_operating_pa.lua'],
                    exporter=resources['export_detached_standalone_pa.lua'], verifier=resources['audit_frontend_working_fields.lua']),
                published_parent=parent, allow_asynchronous_io=allow_asynchronous_io))
        point = next(point for point in graph['field_plan']['field_design']['working_points']
                     if (point.get('working_point_id') or point['kind']) == member_id)
        bound = dict(report['record'], kind=point['kind'])
        if point.get('working_point_id'): bound['working_point_id'] = point['working_point_id']
        if domain == 'parent': parents[member_id] = dict(cache_key=key, record=bound)
        members.append(dict(domain_id=domain, member_id=member_id, report=report, record=bound))
        accounted = report['newly_accounted_cache_bytes']
        if type(accounted) is not int or accounted < 0:
            raise ValueError('field member did not report actual published capacity bytes')
        # Preserve the explicit run reserve; never lower it using an estimate.
        remaining = session.capacity_session['committed_new_bytes'] - accounted
        if remaining < reserve:
            raise ValueError('actual published cache exceeds the original commitment plus reserved run payload')
        if accounted: session.renew_capacity(remaining_committed_new_bytes=remaining)
    for path in downstream_plan.declared_outputs:
        session.declare_file(path, 'required_evidence' if Path(path).suffix == '.json' else 'solver_native_binary')
    for path in downstream_plan.materializations:
        session.declare_file(path, 'required_evidence')
    downstream = run_downstream(session, limits=limits, parameters=dict(compiled_model_record=records['compiled_model'],
        raw_geometry_assets=raw_static, owned_geometry_records=copied, working_directory=work,
        convergence_v=graph['downstream_convergence_v'], resources={name:resources[name] for name in DOWNSTREAM_RESOURCES},
        spatial_identity=static_identity, reuse_assets=reused_assets,
        reuse_identity=static_identity if reused_assets is not None else None,
        reuse_audit_record=records.get('reuse_downstream_audit'), allow_asynchronous_io=allow_asynchronous_io))
    response_copies = [dict(source_record=row['record'], destination=str(session.run_dir/'simion/fields/frontend'/
        row['domain_id']/Path(row['record']['path']).name)) for row in members]
    owned_responses = _copy_records(session, response_copies, callback=materialize_geometry, operation_id='materialize_field_responses')
    carriers = {row['role']:row['carrier_record'] for row in downstream['assets']}
    frontend_meta, responses = {}, []
    field_design = graph['field_plan']['field_design']
    for index, (member, record) in enumerate(zip(members, owned_responses, strict=True), 1):
        domain, member_id = member['domain_id'], member['member_id']
        key = 'frontend_'+str(index)
        records[key] = record
        frontend_meta.setdefault(domain, {})[member_id] = dict(data_key=key, cache_key=member['report']['cache_key'],
            generation_directory=member['report']['generation_directory'])
        if member_id == 'carrier_off': carriers['accelerator' if domain == 'parent' else domain] = record
        else:
            definition = next(row for row in field_design['domains'] if row['domain_id'] == domain)
            grid = dict(definition['dimensions'], **{f'd{axis}_mm':definition['cell_mm_xyz'][axis] for axis in 'xyz'})
            responses.append(dict(domain=domain, kind=member_id, path=record['path'], grid=grid))
        records['member_audit_'+str(index)] = small('member_audit_'+str(index), session.input_dir/('member_audit_'+str(index)+'.json'),
            source_path=member['report']['audit_record']['path'])
        records['member_receipt_'+str(index)] = file_record(session.canonical_path(session.result_dir/('frontend_'+domain+'_'+member_id+'.json')), 'required_evidence')
    records['field_bank'] = small('field_bank', session.input_dir/'field_bank.json',
        value=field_bank(field_design, [row['domain_id'] for row in field_design['domains']]))
    seed = data_record(source.artifact, 'structural_seed')
    compiled = model_geometry(model, downstream_drive=True)
    plan = plan_field_workbench(compiled, field_design=field_design, components_resolved=document['components_resolved'],
        carriers=carriers, response_fields=responses, run_directory=session.run_dir, seed_record=seed,
        native_path_resource=frozen/'native_run_path.lua')
    for ordinal, copy in enumerate(plan.input_copies, 1):
        small('field_structural_seed_'+str(ordinal), Path(copy['destination']), source_path=copy['source_record']['path'])
        for index in range(1, len(carriers)+1):
            session.declare_file(Path(copy['destination']).parent/f'iob_seed_placeholder_{index:02d}.pa0', 'solver_native_binary')
    for index, (path, text) in enumerate(plan.materializations.items(), 1):
        target = session.declare_file(path, 'required_evidence')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8', newline='\n') as stream: stream.write(text)
        records['field_spec_'+str(index)] = file_record(session.canonical_path(target), 'required_evidence')
        session.add_input('field_spec_'+str(index), records['field_spec_'+str(index)])
    for path in plan.declared_outputs:
        session.declare_file(path, 'required_evidence' if Path(path).suffix == '.fly2' else 'solver_native_binary')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    for operation in plan.operations:
        arguments = [str(frozen/Path(value).name) if Path(value).name in FIELD_RESOURCES else value for value in operation['arguments']]
        argv = apply_native_io_mode([str(executable),*arguments], allow_asynchronous_io=allow_asynchronous_io)
        session.run_process(operation['operation_id'], executable=executable, arguments=argv[1:],
            role=operation['role'], stage=operation['stage'], limits=limits)
        ordinal = session.expected_operation_ids.index(operation['operation_id'])+1
        if operation['success_marker'].encode() not in (session.log_dir/f'operation_{ordinal:04d}.stdout.log').read_bytes():
            raise ValueError('field workbench actual completion marker is absent')
    native_assets = {}
    for asset in downstream['assets']:
        role = asset['role']
        carrier_key = role+'_carrier'
        records[carrier_key] = asset['carrier_record']
        keys = []
        for index, record in enumerate(asset['family_records'], 1):
            key = role+'_family_'+str(index)
            records[key] = record
            keys.append(key)
        native_assets[role] = dict(carrier=carrier_key, family=keys)
    records['downstream_audit'] = downstream['audit_record']
    for path in plan.declared_outputs:
        key = 'workbench' if Path(path).suffix == '.iob' else 'zero_particle_format_control'
        records[key] = file_record(session.canonical_path(path), 'solver_native_binary' if key == 'workbench' else 'required_evidence')
    metadata = dict(backend='simion', field_status='available', source_status='not_requested',
        model_identity_sha256=document['model_identity_sha256'], clock=document['drive']['clock'],
        native_assets=native_assets, frontend_members=frontend_meta, downstream_identity=static_identity,
        downstream_reused=reuse_source is not None, downstream_native_operations=downstream['native_count'],
        frontend_native_operations=sum(row['report']['native_count'] for row in members),
        sampled_particles=0, fly_calls=0, gui_calls=0, scientific_qualification='not_granted',
        particle_format_control='explicit_zero_beam_native_serialization', relocation_qualification='not_assessed',
        requested_allow_asynchronous_io=allow_asynchronous_io)
    outputs = [Path(record['path']) for record in records.values()
               if Path(record['path']).is_relative_to(session.artifact_run_dir)]
    return dict(status='success', summary=metadata, output_paths=outputs, required_output_paths=outputs,
        retention_preserve_paths=[], manifest_extra_fields={'products': {'fields': dict(schema_version=1,
            kind='field_bundle', status='complete', metadata=metadata, data=records)}})
