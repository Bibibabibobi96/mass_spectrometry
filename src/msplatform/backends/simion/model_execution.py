"""Materialize a published geometry's unsolved model through the one run owner.

Large PA transportation is an explicit existing-owner callback, never the small
input copier. Missing transportation or source protection fails before native
work. This action owns no scheduler, capacity ledger, publisher or recovery.
"""
from __future__ import annotations

from functools import partial
import inspect
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from msplatform.results.artifacts import open_artifact
from msplatform.contracts.clock import ClockIdentity, require_same_clock
from msplatform.execution.clock_authority import validate_clock_authority
from msplatform.execution.inputs import freeze_file
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.resources import resource_path
from msplatform.execution.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
from msplatform.execution.run_session import RunSession

from .model import require_prepared_model
from .native_io import apply_native_io_mode
from .native_plans import plan_model_preparation
from .resources import native_resource_path


MODEL_RESOURCES = ('build_model_iob.lua', 'iob_core.lua', 'model_drive.lua', 'rf_drive.lua',
                   'single_flight_pulse_hook.lua', 'voltage_waveforms.lua')


def _clock_reference(document: dict, reference: Mapping[str, Any]) -> Path:
    """Validate actual byte authorities through the unique canonical validator."""
    if not isinstance(reference, Mapping) or set(reference) != {'contract', 'authority', 'data_root'}:
        raise ValueError('model clock authority requires contract/authority records and explicit data_root')
    root = Path(reference['data_root'])
    if not root.is_absolute() or any(not Path(reference[key]['path']).is_absolute() for key in ('contract', 'authority')):
        raise ValueError('model clock authority paths must be explicit absolute paths')
    for key in ('contract', 'authority'):
        verify_record('model clock '+key, dict(reference[key]))
    receipt = validate_clock_authority(Path(reference['contract']['path']), root)
    contract = json.loads(Path(reference['contract']['path']).read_text(encoding='utf-8-sig'))
    pointer = Path(contract['authority']['path'])
    if pointer.is_absolute():
        raise ValueError('owned model clock profile requires a relative authority path; original contract is not rewritten')
    authority = (root/pointer).resolve()
    if authority != Path(reference['authority']['path']).resolve() or not authority.is_relative_to(root.resolve()):
        raise ValueError('model epoch record differs from the actual contract authority path')
    if document['geometry']['frontend_geometry'].get('role') == 'simion_rf_ip_geometry':
        value = json.loads(authority.read_text(encoding='utf-8-sig')).get('instrument_time_us')
        if type(value) not in (int, float) or value != 0:
            raise ValueError('RF–IP model requires the existing zero instrument epoch')
    expected = document['drive']['clock']
    require_same_clock(ClockIdentity(expected['clock_epoch_id'], expected['authority_sha256']),
        ClockIdentity(receipt['clock_epoch_id'], receipt['authority_sha256']))
    if str(reference['authority']['sha256']).upper() != receipt['authority_sha256'].upper():
        raise ValueError('model epoch record differs from the validated clock bytes')
    return authority.relative_to(root.resolve())


def _protected_source(session: RunSession, manifest: Mapping[str, Any], *, required_paths=()) -> None:
    source = resolve_consumed_run_capacity_owner(dict(manifest), consumer_artifact_root=session.artifact_root)
    capacity = session.capacity_session
    if capacity.get('status') != 'active':
        raise ValueError('model source requires the active original capacity owner')
    paths = list(capacity['protected_paths'])
    for lease in capacity['source_protection_leases']:
        if lease['status'] == 'active':
            paths.extend(lease['protected_paths'])
    if not any(Path(source['run_directory']).resolve().is_relative_to(Path(path).resolve()) for path in paths):
        raise ValueError('model geometry source manifest has no active owner protection')
    if any(not any(Path(required).resolve().is_relative_to(Path(path).resolve()) for path in paths)
           for required in required_paths):
        raise ValueError('model geometry member has no active owner protection')


def _require_materializer(materialize_geometry: Callable | None, materializer_record: Mapping[str, Any] | None) -> None:
    """Bind the same actual byte-copy callback for both model preparation callers."""
    if not callable(materialize_geometry) or materializer_record is None:
        raise ValueError('installed native geometry materializer is required; no small-file or source-path fallback')
    verify_record('native geometry materializer', dict(materializer_record))
    function = materialize_geometry.func if isinstance(materialize_geometry, partial) else materialize_geometry
    source = inspect.getsourcefile(inspect.unwrap(function))
    if source is None or Path(source).resolve() != Path(materializer_record['path']).resolve():
        raise ValueError('native geometry materializer source identity differs')


def execute_model(session: RunSession, *, model, geometry_reference: Mapping[str, Any],
                  clock_authority_reference: Mapping[str, Any],
                  seed_record: Mapping[str, Any], limits: Mapping[str, Any],
                  materialize_geometry: Callable | None, materializer_record: Mapping[str, Any] | None,
                  allow_asynchronous_io: bool | None = None) -> dict[str, Any]:
    """Save/reopen an unsolved model; transport and source closure stay explicit.

    materialize_geometry(copies, *, session, operation_id) returns actual copied
    file records after its one admitted ``materialize_geometry`` process exits.
    It must use the shared native-payload transport with source guards. This
    method neither supplies a fallback nor treats a no-op callback as success.
    """
    _require_materializer(materialize_geometry, materializer_record)
    if session.expected_operation_ids != ('materialize_geometry', 'build_model', 'verify_model'):
        raise ValueError('model plan differs from the admitted owner operations')
    document = require_prepared_model(model)
    _clock_reference(document, clock_authority_reference)
    geometry = open_artifact(geometry_reference, expected_kind='geometry_artifact')
    metadata = geometry.metadata
    if (metadata.get('backend') != 'simion' or metadata.get('geometry_materialized') is not True
            or metadata.get('field_status') != 'not_solved' or metadata.get('source_status') != 'not_requested'):
        raise ValueError('prepared model requires the published unsolved source-independent SIMION geometry profile')
    manifest_record = geometry.reference['manifest']
    _protected_source(session, manifest_record)
    compiled_path = geometry.data_path('compiled_geometry')
    if json.loads(compiled_path.read_text(encoding='utf-8-sig')) != document['geometry']:
        raise ValueError('model scientific geometry differs from the published native geometry')
    assets = {}
    native_sources = geometry.metadata.get('native_assets')
    if not isinstance(native_sources, Mapping):
        raise ValueError('published geometry lacks explicit native asset bindings')
    independent_component = document['geometry']['frontend_geometry'].get('role') in {'simion_independent_rf_geometry', 'simion_independent_oa_geometry', 'simion_rf_ip_geometry'}
    for domain, names in native_sources.items():
        expected = ({'raw_geometry', 'fractional_surface', 'surface_witnesses'} if independent_component else
                    {'raw_geometry', 'fractional_surface'} if domain in {'flight_tube', 'detector'} else {'raw_geometry'})
        if set(names) != expected:
            raise ValueError('published model geometry surface closure differs')
        if any(name not in geometry.data_records for name in names.values()):
            raise ValueError('published geometry native asset binding names an undeclared data record')
        raw = dict(geometry.data_records[names['raw_geometry']], path=str(geometry.data_path(names['raw_geometry'])))
        surfaces = [dict(geometry.data_records[names['fractional_surface']],
            path=str(geometry.data_path(names['fractional_surface'])))] if 'fractional_surface' in names else []
        assets[domain] = dict(raw_record=raw, surface_records=surfaces)
        if independent_component:
            assets[domain]['witness_record'] = dict(geometry.data_records[names['surface_witnesses']],
                path=str(geometry.data_path(names['surface_witnesses'])))
    _protected_source(session, manifest_record, required_paths=[compiled_path,
        *(row['raw_record']['path'] for row in assets.values()),
        *(record['path'] for row in assets.values() for record in row['surface_records']),
        *(row['witness_record']['path'] for row in assets.values() if 'witness_record' in row)])
    return _execute_model_preparation(session, model=model, assets=assets, source_manifest_record=manifest_record,
        clock_authority_reference=clock_authority_reference, seed_record=seed_record, limits=limits,
        materialize_geometry=materialize_geometry, materializer_record=materializer_record,
        allow_asynchronous_io=allow_asynchronous_io)


def _execute_model_preparation(session: RunSession, *, model, assets: Mapping[str, dict],
        source_manifest_record: Mapping[str, Any], clock_authority_reference: Mapping[str, Any],
        seed_record: Mapping[str, Any], limits: Mapping[str, Any], materialize_geometry: Callable,
        materializer_record: Mapping[str, Any], allow_asynchronous_io: bool | None = None) -> dict[str, Any]:
    """One raw model materialization body for prepare-model and explicit GUI views.

    Callers own their distinct published source-kind and scientific validation.
    This body never finalizes the outer run or opens a GUI.
    """
    admitted = session.expected_operation_ids
    if admitted not in {('materialize_geometry', 'build_model', 'verify_model'),
                        ('materialize_geometry', 'build_model', 'verify_model', 'view_model')}:
        raise ValueError('model preparation requires exactly its three operations or the explicit four-operation view')
    document = require_prepared_model(model)
    clock_relative = _clock_reference(document, clock_authority_reference)
    manifest_record = dict(source_manifest_record)
    source_members = {}
    for domain, row in assets.items():
        for label, record in [('raw_geometry', row['raw_record']),
                *(('fractional_surface', record) for record in row['surface_records']),
                *([('surface_witnesses', row['witness_record'])] if 'witness_record' in row else [])]:
            identity = (Path(record['path']).resolve(), record['bytes'], str(record['sha256']).upper())
            if identity in source_members:
                raise ValueError('published geometry member binding is ambiguous across domains')
            source_members[identity] = (domain, label)
    frozen = session.input_dir / 'native_sources'
    plan = plan_model_preparation(model, geometry_assets=assets, run_directory=session.run_dir,
        seed_record=seed_record, native_path_resource=frozen/'native_run_path.lua')
    if tuple(row['operation_id'] for row in plan.operations) != admitted[:3]:
        raise ValueError('model plan differs from the admitted owner operations')

    def owned(path: str | Path, role: str) -> Path:
        value = Path(path)
        if not value.is_absolute() or not session.canonical_path(value).is_relative_to(session.artifact_run_dir):
            raise ValueError('model destination escapes the admitted run')
        session.declare_file(value, role)
        return value

    sources = {name: native_resource_path(name) for name in MODEL_RESOURCES}
    if document['geometry']['frontend_geometry'].get('role') == 'simion_rf_ip_geometry':
        sources['native_drive.lua'] = native_resource_path('native_drive.lua')
    sources['native_run_path.lua'] = resource_path('native_run_path.lua')
    model_path = owned(session.input_dir/'compiled_model.json', 'required_evidence')
    provenance = owned(session.input_dir/'geometry_source_manifest.json', 'required_evidence')
    callback_source = owned(session.input_dir/'geometry_materializer_source.py', 'required_evidence')
    clock_root = session.input_dir/'clock'
    clock_contract = owned(clock_root/'clock_authority.json', 'required_evidence')
    clock_epoch = owned(clock_root/clock_relative, 'required_evidence')
    if session.canonical_path(clock_epoch) == session.canonical_path(clock_contract):
        raise ValueError('model clock contract and epoch destinations collide')
    all_destinations = [model_path, provenance, callback_source, clock_contract, clock_epoch,
        *(owned(path, 'required_evidence') for path in plan.materializations),
        *(owned(row['destination'], 'required_evidence' if index == 0 or str(row['destination']).endswith('.csv') else 'solver_native_binary')
          for index, row in enumerate(plan.input_copies)),
        *(owned(path, 'required_evidence' if str(path).endswith(('.txt', '.fly2', '.csv')) else 'solver_native_binary') for path in plan.declared_outputs),
        *(owned(frozen/name, 'required_evidence') for name in sources)]
    # Copied raw files are also declared outputs; this is deliberate, not an
    # authorization to overwrite an already existing destination.
    if any(path.exists() for path in all_destinations):
        raise FileExistsError('model action refuses existing inputs or outputs')
    for path in all_destinations:
        path.parent.mkdir(parents=True, exist_ok=True)

    def bind(name: str, path: Path, role: str = 'required_evidence') -> dict:
        record = file_record(session.canonical_path(path), role)
        session.add_input(name, record)
        return record

    model_path.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    records = {'compiled_model': bind('compiled_model', model_path)}
    for label, key, destination in (('clock_authority', 'contract', clock_contract),
                                    ('instrument_epoch', 'authority', clock_epoch)):
        selected = clock_authority_reference[key]
        verify_record('selected model clock '+key, dict(selected))
        actual = freeze_file(Path(selected['path']), destination)
        if (actual['bytes'], str(actual['sha256']).upper()) != (selected['bytes'], str(selected['sha256']).upper()):
            raise ValueError('model clock source changed before freezing: '+key)
        records[label] = bind(label, destination)
    _clock_reference(document, dict(contract=records['clock_authority'], authority=records['instrument_epoch'],
        data_root=str(clock_root)))
    freeze_file(Path(manifest_record['path']), provenance)
    records['source_manifest'] = bind('geometry_source_manifest', provenance)
    freeze_file(Path(materializer_record['path']), callback_source)
    bind('geometry_materializer_source', callback_source)
    for name, path in sources.items():
        freeze_file(path, frozen/name)
        records['resource_'+name] = bind('model_source_'+name, frozen/name)
    for index, (path, content) in enumerate(plan.materializations.items(), 1):
        Path(path).write_text(content, encoding='utf-8', newline='\n')
        label = {'model_drive_configuration.lua':'configuration', 'no_particles.fly2':'zero_particle_input'}.get(Path(path).name, 'iob_specification')
        records[label] = bind('model_spec_'+str(index), Path(path))
    seed = plan.input_copies[0]
    verify_record('model structural seed', dict(seed['source_record']))
    freeze_file(Path(seed['source_record']['path']), Path(seed['destination']))
    records['structural_seed'] = bind('model_structural_seed', Path(seed['destination']))
    seed_parent = Path(seed['destination']).parent
    count = (len(assets) if document['geometry']['frontend_geometry'].get('role') in {'simion_independent_rf_geometry', 'simion_independent_oa_geometry', 'simion_rf_ip_geometry'}
             else 4 + int('entrance_refinement' in assets))
    for index in range(1, count+1):
        owned(seed_parent/f'iob_seed_placeholder_{index:02d}.pa0', 'solver_native_binary')
    payloads = plan.input_copies[1:]
    result = materialize_geometry(payloads, session=session, operation_id='materialize_geometry')
    operations = [row for row in session.operations if row['operation_id']=='materialize_geometry']
    if (len(operations) != 1 or operations[0]['observation'].get('exit_confirmed') is not True
            or operations[0]['observation'].get('returncode') != 0):
        raise ValueError('geometry materializer did not complete its original admitted process')
    if not isinstance(result, (list, tuple)) or len(result) != len(payloads):
        raise ValueError('geometry materializer omitted declared payloads')
    native_assets = {domain: {} for domain in assets}
    for index, (copy, actual) in enumerate(zip(payloads, result, strict=True), 1):
        path, original = Path(copy['destination']), copy['source_record']
        if (not path.is_file() or path.is_symlink() or os.path.samefile(path, original['path'])
                or actual.get('exists') is not True or path.stat().st_size != original['bytes']
                or Path(actual['path']).resolve() != session.canonical_path(path)
                or (actual.get('bytes'), str(actual.get('sha256', '')).upper()) !=
                   (original['bytes'], str(original['sha256']).upper())):
            raise ValueError('geometry materializer did not produce an independent identity-preserving file')
        # The admitted transport's receipt owns the guarded source/destination
        # byte verification. Do not reread a multi-GB PA three more times here.
        # These are declared owned outputs; the original closed-payload publisher
        # records/verifies them again before binding product data to its outputs.
        identity = (Path(original['path']).resolve(), original['bytes'], str(original['sha256']).upper())
        if identity not in source_members:
            raise ValueError('materialized geometry lacks its exact source member binding')
        domain, label = source_members.pop(identity)
        key = 'geometry_'+str(index)
        records[key] = dict(path=str(session.canonical_path(path)), exists=True,
            bytes=actual['bytes'], sha256=str(actual['sha256']).upper(),
            retention_role='required_evidence' if label == 'surface_witnesses' else 'solver_native_binary')
        native_assets[domain][label] = key
    if source_members:
        raise ValueError('materialized geometry omitted a declared native member binding')
    for ordinal, operation in enumerate(plan.operations[1:], 2):
        arguments = [str(frozen/Path(value).name) if value in {str(path) for path in sources.values()} else value
                     for value in operation['arguments']]
        arguments = apply_native_io_mode([str(session.context.tools['simion']), *arguments],
            allow_asynchronous_io=allow_asynchronous_io)[1:]
        session.run_process(operation['operation_id'], executable=session.context.tools['simion'], arguments=arguments,
            role=operation['role'], stage=operation['stage'], limits=limits)
        if operation['success_marker'].encode('ascii') not in (session.log_dir/f'operation_{ordinal:04d}.stdout.log').read_bytes():
            raise ValueError('model native completion marker missing: '+operation['operation_id'])
        for path in operation['outputs']:
            if not Path(path).is_file():
                raise FileNotFoundError('model native declared output missing: '+path)
    for path in plan.declared_outputs:
        name = Path(path).name
        if name.endswith(('.iob', '.txt', '.fly2')):
            label = 'workbench' if name.endswith('.iob') else 'zero_particle_format_control' if name.endswith('.fly2') else 'drive_readback'
            records[label] = file_record(session.canonical_path(path),
                'solver_native_binary' if name.endswith('.iob') else 'required_evidence')
    metadata = dict(backend='simion', geometry_materialized=True, drive_configured=True, field_status='not_solved',
        source_status='not_requested', refine_calls=0, fly_calls=0, gui_calls=0,
        particle_format_control='explicit_zero_beam_native_serialization', sampled_particles=0,
        model_identity_sha256=document['model_identity_sha256'], scientific_qualification='not_granted',
        native_assets=native_assets,
        view_profile='raw_geometry_no_program_hook', drive_profile='explicit_saved_model_consumer_readback',
        relocation_qualification='not_assessed', requested_allow_asynchronous_io=allow_asynchronous_io)
    if 'native_frame_id' in document:
        metadata['native_frame_id'] = document['native_frame_id']
    return dict(status='success', summary=metadata, output_paths=list(plan.declared_outputs),
        required_output_paths=list(plan.declared_outputs), retention_preserve_paths=[],
        manifest_extra_fields={'products': {'model': dict(schema_version=1, kind='prepared_model', status='complete',
            metadata=metadata, data=records)}})
