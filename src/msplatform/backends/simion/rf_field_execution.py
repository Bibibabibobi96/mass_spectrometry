"""Independent RF fractional fields; the existing RunSession owns every operation.

Families stay at their original producer. They are not detached standalone cache
responses and must never be copied after publication for native consumption.
"""
from __future__ import annotations

import inspect
import json
import math
from pathlib import Path
from typing import Mapping

from msplatform.execution.inputs import freeze_file
from msplatform.io.file_identity import canonical_json_sha256, file_sha256
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from .field_closure import data_record
from .model import model_geometry, require_prepared_model, RF_PHYSICS, RF_IP_PHYSICS
from .model_execution import _clock_reference, _protected_source, _require_materializer
from .native_io import apply_native_io_mode
from .resources import native_resource_path
from .source import lua_value

REPRESENTATION = 'producer_owned_rf_fractional_family'


def _field_contract(geometry):
    """Select actual produced component semantics; utility Lua report names are legacy."""
    role = geometry.get('role')
    if role == 'simion_rf_ip_geometry':
        return 'producer_owned_rf_ip_fractional_family', 'simion_rf_ip_fractional_spatial_identity'
    if role == 'simion_independent_rf_geometry':
        return REPRESENTATION, 'simion_rf_fractional_spatial_identity'
    if role == 'simion_independent_oa_geometry':
        return 'producer_owned_oa_fractional_family', 'simion_oa_fractional_spatial_identity'
    raise ValueError('independent field families require actual RF or OA PreparedModel geometry')


def _domain_labels(geometry, name):
    if geometry.get('role') == 'simion_rf_ip_geometry':
        if name != 'parent': raise ValueError('RF–IP field requires the parent domain')
        labels = [value for mapping in geometry['electrode_bindings'].values() for value in mapping.values()]
        if len(labels) != len(set(labels)) or any(type(value) is not int or value <= 0 for value in labels):
            raise ValueError('RF–IP physical native labels differ')
        return sorted(labels)
    return sorted(set(geometry['electrode_bindings'][name].values()))

def plan_rf_fields(model, *, numerics: Mapping, reuse_fields_reference=None) -> dict:
    """Select real domain Refine operations, retaining the explicit vendor default."""
    geometry = model_geometry(model).frontend_geometry
    _field_contract(geometry)
    if require_prepared_model(model)['physics'] != (RF_IP_PHYSICS if geometry.get('role') == 'simion_rf_ip_geometry' else RF_PHYSICS):
        raise ValueError('independent field families require the existing linear external electrostatic physics')
    names = list(geometry['numerical_domains']) if geometry.get('role') == 'simion_rf_ip_geometry' else list(geometry['composition_plan']['scope']['instance_ids'])
    if not isinstance(numerics, Mapping):
        raise ValueError('RF fields require explicit refinement numerics')
    policy = numerics.get('refine_policy')
    if policy == 'vendor_default':
        if set(numerics) != {'refine_policy'}:
            raise ValueError('vendor_default refinement has no convergence override')
    elif policy == 'explicit_convergence':
        values = numerics.get('convergence_v')
        if (set(numerics) != {'refine_policy', 'convergence_v'}
                or not isinstance(values, Mapping) or set(values) != set(names)
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) or v <= 0 for v in values.values())):
            raise ValueError('explicit convergence requires one positive finite value per RF domain')
    else:
        raise ValueError('RF refine_policy must be vendor_default or explicit_convergence')
    ids = [] if reuse_fields_reference is not None else ['materialize_geometry', *('refine_'+name for name in names)]
    dependencies = {name: ['materialize_geometry'] for name in ids[1:]}
    dependencies['audit_fields'] = ids[1:]
    ids.append('audit_fields')
    return dict(expected_operation_ids=ids, operation_dependencies=dependencies,
                numerical_domains=names, numerics=dict(numerics), reuse_requested=reuse_fields_reference is not None)


def rf_spatial_identity(source, *, numerics, tool_identity, auditor_identity) -> dict:
    """Bind the linear spatial operator, not RF phase, particle source or clock."""
    geometry = model_geometry(source.model).frontend_geometry
    records = lambda rows: [dict(bytes=r['bytes'], sha256=str(r['sha256']).upper()) for r in rows]
    result = dict(schema_version=1, role=_field_contract(geometry)[1],
        raw_geometry={name: records([row['raw_record'], *row['surface_records']])
                      for name, row in source.native_assets.items()},
        numerical_domains=geometry['numerical_domains'], electrode_bindings=geometry['electrode_bindings'],
        physics=require_prepared_model(source.model)['physics'], numerics=dict(numerics),
        tool_identity=dict(tool_identity), auditor_identity=auditor_identity)
    result = json.loads(json.dumps(result, allow_nan=False))
    return dict(result, identity_sha256=canonical_json_sha256(result))


def _family_assets(artifact, geometry) -> dict:
    bindings = artifact.metadata.get('native_assets')
    if not isinstance(bindings, Mapping) or set(bindings) != set(geometry['numerical_domains']):
        raise ValueError('RF FieldBundle lacks exactly its actual numerical domains')
    assets, used = {}, set()
    for name, keys in bindings.items():
        if set(keys) != {'carrier', 'family', 'surface_witnesses'} or not isinstance(keys['family'], list):
            raise ValueError('RF field family binding is incomplete')
        labels = _domain_labels(geometry, name)
        family = [data_record(artifact, key) for key in keys['family']]
        carrier = data_record(artifact, keys['carrier'])
        paths = [Path(row['path']) for row in family]
        if (len(paths) != len(set(paths)) or used.intersection(paths) or carrier not in family
                or Path(carrier['path']).suffix.lower() != '.pa0'):
            raise ValueError('RF family carrier or member identity is ambiguous')
        used.update(paths)
        stem = Path(carrier['path']).with_suffix('')
        expected = {str(stem)+suffix for suffix in ['.pa#', '.pa0', '.pa-surf', *('.pa'+str(eid) for eid in labels)]}
        if {str(path) for path in paths} != expected:
            raise ValueError('RF family lacks its exact same-producer fractional closure')
        assets[name] = dict(carrier_record=carrier, family_records=family,
                            witness_record=data_record(artifact, keys['surface_witnesses']))
    return assets


def require_rf_reuse(reference, *, identity, geometry):
    """Follow one explicit original producer, never a search or reference chain."""
    source = open_artifact(reference, expected_kind='field_bundle')
    def validate(artifact):
        meta = artifact.metadata
        if (meta.get('backend') != 'simion' or meta.get('field_status') != 'available'
                or meta.get('field_representation') != _field_contract(geometry)[0] or meta.get('spatial_identity') != identity):
            raise ValueError('RF reuse differs from the actual fractional spatial operator')
        return _family_assets(artifact, geometry)
    assets = validate(source)
    original_reference = source.metadata.get('family_producer_reference')
    producer = source if original_reference is None else open_artifact(original_reference, expected_kind='field_bundle')
    if 'family_producer_reference' in producer.metadata:
        raise ValueError('RF reuse requires its original producer, not a reference chain')
    if validate(producer) != assets:
        raise ValueError('RF reused family differs from its original producer')
    producer_root = Path(producer.reference['manifest']['path']).resolve().parent
    if any(not Path(record['path']).resolve().is_relative_to(producer_root)
           for row in assets.values() for record in [*row['family_records'], row['witness_record']]):
        raise ValueError('RF fractional family is not owned by its declared original producer')
    receipts = json.loads(producer.data_path('field_native_receipts').read_text(encoding='utf-8'))
    expected = {'refine_'+name for name in geometry['numerical_domains']}
    if (not isinstance(receipts, list) or {row.get('operation_id') for row in receipts} != expected
            or len(receipts) != len(expected)
            or any(row.get('observation', {}).get('exit_confirmed') is not True
                   or row['observation'].get('returncode') != 0
                   or type(row['observation'].get('process_id')) is not int
                   or row['observation']['process_id'] <= 0
                   or type(row['observation'].get('process_started_at_utc_ticks')) is not int
                   or row['observation']['process_started_at_utc_ticks'] <= 0 for row in receipts)):
        raise ValueError('RF original producer lacks its successful actual Refine receipts')
    return source, producer, assets


def execute_rf_fields(session, *, source, numerics, limits, materialize_geometry, materializer_record,
                      allow_asynchronous_io=None, reuse_fields_reference=None):
    """Refine fresh raw geometry or audit the protected original fractional family."""
    from .field_execution import _copy_records
    _require_materializer(materialize_geometry, materializer_record)
    graph = plan_rf_fields(source.model, numerics=numerics, reuse_fields_reference=reuse_fields_reference)
    if (tuple(graph['expected_operation_ids']) != session.expected_operation_ids
            or dict(session.operation_dependencies) != graph['operation_dependencies']):
        raise ValueError('RF field graph differs from its admitted owner operations')
    if type(limits.get('reserved_run_payload_bytes')) is not int or limits['reserved_run_payload_bytes'] < 0:
        raise ValueError('RF fields require explicit reserved_run_payload_bytes')
    if allow_asynchronous_io is not None and type(allow_asynchronous_io) is not bool:
        raise TypeError('RF asynchronous I/O control must be boolean or None')
    _protected_source(session, source.artifact.reference['manifest'], required_paths=[
        record['path'] for row in source.native_assets.values()
        for record in [row['raw_record'], *row['surface_records'], row['witness_record']]])
    document = require_prepared_model(source.model)
    geometry = model_geometry(source.model).frontend_geometry
    records = {}
    def small(name, path, *, source_path=None, value=None, text=None):
        path = session.declare_file(path, 'required_evidence')
        if path.exists():
            raise FileExistsError('RF fields refuse an existing input or output: '+str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        if source_path is not None:
            freeze_file(Path(source_path), path)
        else:
            path.write_text(text if text is not None else json.dumps(value, allow_nan=False, indent=2)+'\n', encoding='utf-8', newline='\n')
        record = file_record(session.canonical_path(path), 'required_evidence')
        session.add_input(name, record)
        records[name] = record
        return path
    refiner = small('rf_field_refiner', session.input_dir/'native_sources/refine_rf_field_family.lua',
                    source_path=native_resource_path('refine_rf_field_family.lua'))
    auditor = small('rf_field_auditor', session.input_dir/'native_sources/audit_rf_field_family.lua',
                    source_path=native_resource_path('audit_rf_field_family.lua'))
    small('rf_field_action', session.input_dir/'rf_field_execution.py', source_path=Path(inspect.getsourcefile(execute_rf_fields)))
    small('compiled_model', session.input_dir/'compiled_model.json', value=document)
    small('source_model_manifest', session.input_dir/'source_model_manifest.json', source_path=source.artifact.reference['manifest']['path'])
    small('field_numerics', session.input_dir/'field_numerics.json', value=numerics)
    clock_relative = _clock_reference(document, source.clock_authority_reference)
    small('clock_authority', session.input_dir/'clock/clock_authority.json', source_path=source.clock_authority_reference['contract']['path'])
    small('instrument_epoch', session.input_dir/'clock'/clock_relative, source_path=source.clock_authority_reference['authority']['path'])
    _clock_reference(document, dict(contract=records['clock_authority'], authority=records['instrument_epoch'], data_root=str(session.input_dir/'clock')))
    executable = session.context.tools['simion']
    tool = dict(release='SIMION 2020', executable_bytes=executable.stat().st_size, executable_sha256=file_sha256(executable))
    identity = rf_spatial_identity(source, numerics=numerics, tool_identity=tool, auditor_identity={key:records[key]['sha256'] for key in ['rf_field_auditor','rf_field_refiner']})
    small('spatial_identity', session.input_dir/'spatial_identity.json', value=identity)
    assets, producer = {}, None
    if reuse_fields_reference is not None:
        selected, producer, assets = require_rf_reuse(reuse_fields_reference, identity=identity, geometry=geometry)
        for artifact in [selected, producer]:
            _protected_source(session, artifact.reference['manifest'], required_paths=[
                record['path'] for row in assets.values() for record in [*row['family_records'], row['witness_record']]])
        small('reuse_field_manifest', session.input_dir/'reuse_field_manifest.json', source_path=selected.reference['manifest']['path'])
        small('family_producer_manifest', session.input_dir/'family_producer_manifest.json', source_path=producer.reference['manifest']['path'])
    else:
        copies = []
        for name, row in source.native_assets.items():
            target = session.run_dir/'simion/fields'/name/(name+'.pa#')
            for record, destination in [(row['raw_record'],target),
                    (row['surface_records'][0],target.with_suffix('.pa-surf'))]:
                copies.append(dict(source_record=record, destination=str(destination)))
            small(name+'_surface_witnesses', session.run_dir/'results'/(name+'_surface.csv'), source_path=row['witness_record']['path'])
        for copy in copies:
            Path(copy['destination']).parent.mkdir(parents=True, exist_ok=True)
        _copy_records(session, copies, callback=materialize_geometry, operation_id='materialize_geometry')
        for name in graph['numerical_domains']:
            raw = session.run_dir/'simion/fields'/name/(name+'.pa#')
            labels = _domain_labels(geometry, name)
            paths = [raw.with_suffix(suffix) for suffix in ['.pa#','.pa0','.pa-surf', *('.pa'+str(eid) for eid in labels)]]
            if any(path.exists() for path in paths if path.suffix not in {'.pa#','.pa-surf'}):
                raise FileExistsError('RF Refine refuses a preexisting response')
            for path in paths:
                session.declare_file(path, 'solver_native_binary')
            refine_spec = dict(input=str(raw))
            if numerics['refine_policy'] == 'explicit_convergence':
                refine_spec['convergence_v'] = numerics['convergence_v'][name]
            spec_path = small(name+'_refine_spec', session.input_dir/(name+'_refine.lua'),
                              text='return '+lua_value(refine_spec)+'\n')
            argv = apply_native_io_mode([str(executable),'--nogui','--noprompt','lua',str(refiner),str(spec_path)],
                                        allow_asynchronous_io=allow_asynchronous_io)
            session.run_process('refine_'+name, executable=executable, arguments=argv[1:], role='SIMION', stage='pa_refine', limits=limits)
            ordinal = session.expected_operation_ids.index('refine_'+name)+1
            if b'INDEPENDENT_RF_REFINE=PASS' not in (session.log_dir/f'operation_{ordinal:04d}.stdout.log').read_bytes():
                raise ValueError('RF Refine completion marker is absent')
            family = [file_record(session.canonical_path(path), 'solver_native_binary') for path in paths]
            if any(not row['exists'] or row['bytes'] <= 0 for row in family):
                raise ValueError('RF Refine did not produce its complete fractional family')
            assets[name] = dict(carrier_record=family[1], family_records=family,
                witness_record=records[name+'_surface_witnesses'])
        receipt_rows = [row for row in session.operations if row['operation_id'].startswith('refine_')]
        small('field_native_receipts', session.input_dir/'field_native_receipts.json', value=receipt_rows)
    audit_path = session.declare_file(session.run_dir/'results/rf_field_audit.json', 'required_evidence')
    if audit_path.exists():
        raise FileExistsError('RF field audit already exists')
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audits, guards = [], []
    native_assets = {}
    for name in graph['numerical_domains']:
        asset = assets[name]
        grid = geometry['numerical_domains'][name]
        keys = []
        for index, record in enumerate(asset['family_records']):
            key = name+'_family_'+str(index)
            records[key] = record
            keys.append(key)
        witness_key = name+'_surface_witnesses'
        records[witness_key] = asset['witness_record']
        carrier_key = next(key for key in keys if records[key] == asset['carrier_record'])
        native_assets[name] = dict(carrier=carrier_key, family=keys, surface_witnesses=witness_key)
        guards.extend([*asset['family_records'], asset['witness_record']])
        audits.append(dict(domain_id=name, carrier_path=asset['carrier_record']['path'],
            family_paths=[row['path'] for row in asset['family_records']],
            response_ids=_domain_labels(geometry, name),
            grid=dict(grid['dimensions'], **{'d'+axis+'_mm':grid['cell_mm_xyz'][axis] for axis in 'xyz'}),
            physical_samples=geometry['raw_physical_samples'][name], surface_witnesses=asset['witness_record']['path']))
    spec = small('field_audit_spec', session.input_dir/'rf_field_audit.lua', text='return '+lua_value(dict(assets=audits, output=str(audit_path)))+'\n')
    argv = apply_native_io_mode([str(executable),'--nogui','--noprompt','lua',str(auditor),str(spec)], allow_asynchronous_io=allow_asynchronous_io)
    session.run_process('audit_fields', executable=executable, arguments=argv[1:], role='SIMION', stage='inspect', limits=limits,
                        immutable_input_records=guards)
    ordinal = session.expected_operation_ids.index('audit_fields')+1
    if b'INDEPENDENT_RF_FIELDS_READBACK=PASS' not in (session.log_dir/f'operation_{ordinal:04d}.stdout.log').read_bytes():
        raise ValueError('RF cold field readback completion marker is absent')
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    if (audit.get('status') != 'success' or audit.get('role') != 'simion_rf_fractional_field_audit'
            or audit.get('checked_domains') != graph['numerical_domains']):
        raise ValueError('RF cold field readback report differs from the actual domain scope')
    records['field_audit'] = file_record(session.canonical_path(audit_path), 'required_evidence')
    if producer is not None:
        records['field_native_receipts'] = data_record(producer, 'field_native_receipts')
    metadata = dict(backend='simion', field_status='available', source_status='not_requested',
        field_representation=_field_contract(geometry)[0], spatial_identity=identity, native_assets=native_assets,
        model_identity_sha256=document['model_identity_sha256'], clock=document['drive']['clock'],
        fields_reused=producer is not None, refine_calls=0 if producer else len(assets),
        sampled_particles=0, fly_calls=0, gui_calls=0, scientific_qualification='not_granted',
        relocation_qualification='not_assessed', requested_allow_asynchronous_io=allow_asynchronous_io)
    if geometry['role'] == 'simion_independent_oa_geometry':
        # The immutable Lua utility predates OA support. Its RF-named report
        # format describes generic fractional electrode-response checks only.
        metadata.update(component_kind='orthogonal_accelerator',
            field_domain_coupling='independent_component_domains',
            native_audit_format='legacy_shared_simion_rf_fractional_field_audit')
    if producer is not None:
        metadata['family_producer_reference'] = producer.reference
    # External members remain owned by the original producer. Bind them as
    # consumed inputs so the normal artifact reader can verify every product row.
    for name, record in records.items():
        if not Path(record['path']).is_relative_to(session.artifact_run_dir):
            session.add_input('rf_reuse_'+name, record)
    outputs = [Path(record['path']) for record in records.values() if Path(record['path']).is_relative_to(session.artifact_run_dir)]
    return dict(status='success', summary=metadata, output_paths=outputs, required_output_paths=outputs,
        retention_preserve_paths=[], manifest_extra_fields={'products':{'fields':dict(schema_version=1,
            kind='field_bundle',status='complete',metadata=metadata,data=records)}})
