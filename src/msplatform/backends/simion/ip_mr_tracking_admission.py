"""Read-only admission of the published IP–MR sampled-field tracking inputs."""
import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from msplatform.contracts.gas import BoxDomain
from msplatform.io.manifest_records import record_path, verify_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact
from .artifacts import CompiledPreparedModel
from .ip_mr_field_execution import _priority_projection
from .model import require_prepared_model
from .scalar_sample_binding import original_sample_source
from .rf_tracking_program import _ip_mr_bindings


def admit_ip_mr_tracking_fields(reference: Mapping[str, Any] | OpenedArtifact) -> dict[str, Any]:
    """Bind published basis, millimetre world domain and priority without Fly."""
    source = open_artifact(reference, expected_kind='field_bundle')
    meta = source.metadata
    if (meta.get('backend') != 'simion' or meta.get('field_status') != 'available'
            or meta.get('source_status') != 'not_requested'
            or meta.get('field_representation') != 'assembly_sampled_basis_with_collision_geometry'):
        raise ValueError('complete IP–MR sampled FieldBundle required')
    model = CompiledPreparedModel(source.data_path('compiled_model').read_text(encoding='utf-8-sig'))
    document = require_prepared_model(model)
    producer = json.loads(source.manifest_location.read_text(encoding='utf-8-sig'))
    request_record = producer['inputs']['execution_request']
    verify_record('sampled field execution request', request_record, base_dir=source.manifest_location.parent)
    request_path = record_path(request_record, base_dir=source.manifest_location.parent)
    request = json.loads(request_path.read_text(encoding='utf-8-sig'))
    if request.get('role') != 'run_artifact_workflow_request' or request['payload'].get('action') != 'solve_fields':
        raise ValueError('sampled field producer request differs')
    prepared = open_artifact(request['payload']['model'], expected_kind='prepared_model')
    for key in ('compiled_model', 'clock_authority', 'instrument_epoch'):
        original, selected = prepared.data_records[key], source.data_records[key]
        if any(str(original[k]).lower() != str(selected[k]).lower() for k in ('bytes', 'sha256')):
            raise ValueError('sampled field prepared model record differs: ' + key)
    if (meta.get('model_identity_sha256') != document['model_identity_sha256']
            or meta.get('clock') != document['drive']['clock']):
        raise ValueError('sampled FieldBundle model or clock differs')
    basis = json.loads(source.data_path('sampled_basis').read_text(encoding='utf-8-sig'))
    policy = json.loads(source.data_path('collision_priority').read_text(encoding='utf-8-sig'))
    _, sample_records = _ip_mr_bindings(document, basis)
    evidence = policy.get('evidence_records')
    if not isinstance(evidence, list) or len(evidence) != 3:
        raise ValueError('three collision priority evidence records required')
    projected = _priority_projection(model, basis, dict(zip(
        ('boxes_record', 'clearance_record', 'source_record'), evidence, strict=True)))
    if projected['verified_priority'] != policy:
        raise ValueError('published collision priority differs from verified model and evidence')
    bounds = policy['background_bounds_mm']
    world = BoxDomain(tuple(row[0] for row in bounds), tuple(row[1] for row in bounds),
                      (True, True, True), (True, True, True))
    roles = policy['roles']
    keys = ['compiled_model', 'clock_authority', 'instrument_epoch', 'sampled_basis',
            'collision_priority', 'collision_iob_spec', 'zero_particle_format_control',
            'collision_audits', 'background', 'workbench']
    for name in (roles['rf'], roles['ip'], roles['analyzer'], roles['detector']):
        keys.extend((name + '_collision', name + '_witness'))
        if name + '_surface' in source.data_records: keys.append(name + '_surface')
        if name + '_surface_state' in source.data_records: keys.append(name + '_surface_state')
        if name + '_surface' not in source.data_records and name + '_surface_state' not in source.data_records: raise ValueError('collision surface evidence missing')
    collision_reference = meta.get('collision_producer_reference')
    collision_source = None
    if collision_reference is not None:
        collision_source = open_artifact(collision_reference, expected_kind='field_bundle')
        if (collision_source.producer['status'] != 'success'
                or collision_source.metadata.get('field_representation') != 'assembly_sampled_basis_with_collision_geometry'
                or collision_source.metadata.get('collision_producer_reference') is not None):
            raise ValueError('collision producer must be the successful original sampled field')
        if (collision_source.metadata.get('model_identity_sha256') != meta.get('model_identity_sha256')
                or collision_source.metadata.get('clock') != meta.get('clock')):
            raise ValueError('collision producer model or clock differs')
        excluded = {'compiled_model', 'clock_authority', 'instrument_epoch', 'sampled_basis'}
        selected = set(source.data_records) - excluded
        if selected != set(collision_source.data_records) - excluded:
            raise ValueError('collision producer record closure differs')
        for key in selected:
            selected_record = dict(source.data_records[key], path=str(source.data_locations[key]))
            producer_record = dict(collision_source.data_records[key], path=str(collision_source.data_locations[key]))
            if selected_record != producer_record:
                raise ValueError('collision producer record differs: ' + key)
    records = [dict(source.data_records[key], path=str(source.data_path(key))) for key in keys]
    records.extend(copy.deepcopy(sample_records))
    unique = {}
    for record in records:
        verify_record('IP–MR tracking immutable input', record)
        path = str(Path(record['path']).resolve(strict=True))
        identity = (record['bytes'], str(record['sha256']).lower())
        if path in unique and unique[path][0] != identity:
            raise ValueError('conflicting tracking input identities')
        unique[path] = (identity, dict(record, path=path))
    references = [source.reference['manifest'], prepared.reference['manifest'], basis['geometry_reference']['manifest']]
    if collision_source is not None:
        references.append(collision_source.reference['manifest'])
    for item in basis['bases'].values():
        for level in [item, *item.get('refinement_windows', [])]:
            sample = open_artifact(level['reference'], expected_kind='scalar_field_samples')
            solution = open_artifact(level['field_solution_reference'], expected_kind='field_solution')
            for key, record in level['records'].items():
                selected = sample.data_records[key]
                if any(str(record[k]).lower() != str(selected[k]).lower() for k in ('bytes', 'sha256')):
                    raise ValueError('sampled basis record differs from published ' + key)
                if Path(record['path']).resolve(strict=True) != sample.data_path(key).resolve(strict=True):
                    raise ValueError('sampled basis relocation is not qualified')
            references.extend((sample.reference['manifest'], solution.reference['manifest']))
            original = original_sample_source(sample)
            expected_original = level.get('original_samples_reference')
            if expected_original != (original.reference if original is not None else None):
                raise ValueError('sample original producer reference differs')
            if original is not None:
                references.append(original.reference['manifest'])
    return dict(source=source, collision_reference=collision_reference, prepared_reference=prepared.reference, model=model, basis=basis, priority=policy, world_domain=world,
                world_frame_id=document['native_frame_id'],
                immutable_input_records=[row[1] for row in unique.values()], source_manifests=references)


def protect_ip_mr_tracking_fields(session: Any, admission: Mapping[str, Any]) -> None:
    """Protect every published owner and register the exact borrowed field bytes."""
    from .model_execution import _protected_source
    source = admission['source']
    owned = [str(source.data_path(key)) for key in source.data_records]
    _protected_source(session, source.reference['manifest'], required_paths=owned)
    if admission.get('collision_reference') is not None:
        _protected_source(session, admission['collision_reference']['manifest'])
    basis = admission['basis']
    _protected_source(session, admission['prepared_reference']['manifest'])
    _protected_source(session, basis['geometry_reference']['manifest'],
                      required_paths=[basis['geometry_execution_request']['path']])
    for item in basis['bases'].values():
        for level in [item, *item.get('refinement_windows', [])]:
            _protected_source(session, level['reference']['manifest'],
                              required_paths=[row['path'] for row in level['records'].values()])
            _protected_source(session, level['field_solution_reference']['manifest'])
    for index, record in enumerate(admission['immutable_input_records']):
        verify_record('IP–MR tracking source protection', record)
        session.add_input('ip_mr_field_input_'+str(index), record)
