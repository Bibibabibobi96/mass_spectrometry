"""Original recorded-birth SFI consumer of an explicitly published FieldBundle."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from msplatform.backends import simion
from msplatform.backends.simion.artifacts import CompiledPreparedModel
from msplatform.backends.simion.frontend import native_frontend_instances
from msplatform.backends.simion.tracking_program import _bound_tracking_model, validate_native_flight
from msplatform.contracts.clock import ClockIdentity
from msplatform.execution.context import ExecutionContext
from msplatform.io.manifest_records import validate_file_record, verify_record, require_completed_terminal_publication
from msplatform.ion_release import load_recorded_release
from msplatform.results.artifacts import OpenedArtifact, open_artifact


def track_recorded_birth(*, preparation_manifest: Mapping[str, Any], fields: OpenedArtifact | Mapping[str, Any],
                         species_id: str, expected_particle_ids: Sequence[int], observations: Mapping[str, Any],
                         context: ExecutionContext, unit_size: int | None = None,
                         recovery_reference: Mapping[str, Any] | None = None,
                         dispatch_profiles: Sequence[Mapping[str, Any]] = ()) -> OpenedArtifact:
    """Track an explicitly prepared original mother; this does not qualify field coupling."""
    manifest_record = validate_file_record(preparation_manifest, 'SFI preparation manifest')
    manifest_path = Path(manifest_record['path'])
    if not manifest_path.is_absolute() or manifest_path.name != 'run_manifest.json':
        raise ValueError('SFI preparation requires an explicit run manifest')
    verify_record('SFI preparation manifest', manifest_record)
    require_completed_terminal_publication(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if manifest.get('role') != 'simulation_run_manifest' or manifest.get('status') != 'success':
        raise ValueError('SFI preparation producer must be a terminal successful run')
    if not isinstance(manifest.get('inputs'), dict) or not isinstance(manifest.get('outputs'), list):
        raise ValueError('SFI producer lacks manifest input/output records')
    bound = [*manifest['inputs'].values(), *manifest['outputs']]
    inputs = manifest_path.parent / 'inputs'
    records: dict[str, dict] = {}

    def frozen(name: str, relative: str) -> dict:
        path = inputs / relative
        matches = [row for row in bound if isinstance(row, dict) and row.get('path')
                   and Path(row['path']).resolve() == path.resolve()]
        if not matches or any(any(row.get(key) != matches[0].get(key) for key in ('path', 'bytes', 'sha256'))
                              for row in matches):
            raise ValueError('SFI frozen input lacks a unique producer record: ' + name)
        record = validate_file_record(matches[0], name)
        verify_record(name, record)
        records[name] = record
        return record

    def read(record: Mapping[str, Any]) -> dict:
        return json.loads(Path(record['path']).read_text(encoding='utf-8-sig'))

    request = read(frozen('request', 'request.json'))
    provenance = read(frozen('source_provenance', 'source_provenance.json'))
    source = request.get('source', {})
    if source.get('kind') != 'recorded_birth' or provenance.get('source_kind') != 'recorded_birth':
        raise ValueError('only original recorded births are supported by this consumer')
    if ('local_scope' in request or 'continuation' in request or 'validation_contract' in request
            or request.get('verify_saved_workbench_replay', False)):
        raise ValueError('local scope, legacy continuation, validation and saved replay are unsupported here')
    if provenance.get('population_policy') != 'complete_original_source_no_selection_no_resampling':
        raise ValueError('prepared source is not the complete original birth cohort')
    flight = validate_native_flight(request.get('flight'), requires_rf=True)
    if flight['pulse']['mode'] != 'timed':
        raise ValueError('this consumer requires an explicit timed pulse')
    raw = frozen('particle_source', 'particle_source.csv')
    frozen('particle_source_metadata', 'particle_source_metadata.json')
    epoch = frozen('instrument_epoch', 'instrument_epoch.json')
    frozen('clock_authority', 'clock_authority.json')
    for name in ('particle_source', 'metadata', 'clock_authority', 'instrument_epoch', 'request'):
        actual_name = 'particle_source_metadata' if name == 'metadata' else name
        original, selected_record = provenance['input_records'][name], records[actual_name]
        if any(original.get(key) != selected_record.get(key) for key in ('path', 'bytes', 'sha256')):
            raise ValueError('prepared source authority differs from its provenance: ' + name)
    geometry = read(frozen('frontend_geometry', 'frontend_geometry.json'))
    design = read(frozen('frontend_field_design', 'frontend_field_design.json'))
    rf_ids, tof_id = native_frontend_instances(geometry['composition_plan'])
    components = {name: read(frozen('component_' + name, 'components/' + name + '/resolved_design.json'))
                  for name in (*rf_ids, tof_id)}
    selected = open_artifact(fields, expected_kind='field_bundle')
    model = CompiledPreparedModel(selected.data_path('compiled_model').read_text(encoding='utf-8-sig'))
    _bound_tracking_model(model, {name: components[name] for name in rf_ids}, components[tof_id], geometry, design, flight)
    packet = load_recorded_release(raw, clock=ClockIdentity(provenance['clock_epoch_id'], epoch['sha256']),
        frame_id=source['frame_id'], source_component_id=source['instance_id'], species_id=species_id,
        relative_weights=None, instrument_origin_us=0., expected_particle_ids=expected_particle_ids)
    if len(packet['rows']) != provenance['particle_count'] or provenance['state_time_semantics'] != 'original_birth_time_s_times_1e6_no_epoch_shift':
        raise ValueError('prepared source population or birth-time semantics differ')
    propagation = dict(schema_version=1, scope='continuous_assembly',
        end_policy=dict(maximum_particle_age_us=flight['maximum_flight_us']), consumed_plane_events=[], stop=None)
    numerics = {key: flight[key] for key in ('maximum_step_us', 'trajectory_quality', 'rf_steps_per_period')}
    return simion.track(selected, packet, propagation=propagation, observations=observations, numerics=numerics,
        context=context, unit_size=unit_size, recovery_reference=recovery_reference, dispatch_profiles=dispatch_profiles,
        birth_source_authority={'manifest': manifest_record, 'records': records})
