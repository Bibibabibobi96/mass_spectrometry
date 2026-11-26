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
                         dispatch_profiles: Sequence[Mapping[str, Any]] = (),
                         scalar_field_basis: Mapping[str, Any] | None = None) -> OpenedArtifact:
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
    if request.get('schema_version') == 12:
        from msplatform.backends.simion.model import require_prepared_model
        from .prepare import validate_preparation_request
        validate_preparation_request(request)
        if (provenance.get('role') != 'split_recorded_birth_preparation'
                or provenance.get('population_policy') != 'complete_original_source_no_selection_no_resampling'
                or provenance.get('source_time_mapping') != dict(instrument_origin_us=source['instrument_origin_us'],
                    native_origin_us=0., source_time_unit='s', instrument_time_unit='us')
                or species_id != source['species_id'] or list(expected_particle_ids) != source['particle_ids']):
            raise ValueError('recorded birth request differs from the frozen original mother')
        raw = frozen('particle_source', 'particle_source.csv')
        frozen('metadata', 'particle_source_metadata.json')
        frozen('instrument_epoch', 'instrument_epoch.json')
        frozen('clock_authority', 'clock_authority.json')
        for name in ('request', 'particle_source', 'metadata', 'instrument_epoch', 'clock_authority'):
            original, actual = provenance['input_records'][name], records[name]
            if any(original.get(key) != actual.get(key) for key in ('path', 'bytes', 'sha256')):
                raise ValueError('recorded birth source authority differs: '+name)
        selected = open_artifact(fields, expected_kind='field_bundle')
        bound = provenance['fields_reference']
        if (selected.reference['product_id'] != bound['product_id']
                or any(str(selected.reference['manifest'][key]).upper() != str(bound['manifest'][key]).upper()
                       for key in ('bytes', 'sha256'))):
            raise ValueError('recorded birth FieldBundle differs from preparation')
        model = CompiledPreparedModel(selected.data_path('compiled_model').read_text(encoding='utf8'))
        document = require_prepared_model(model)
        if (document['model_identity_sha256'] != provenance['model_identity_sha256']
                or document['geometry']['frontend_geometry'].get('role') != 'simion_split_oa_tof_geometry'):
            raise ValueError('recorded birth model differs from the frozen split model')
        clock = document['drive']['clock']
        if (clock['clock_epoch_id'] != provenance['clock_epoch_id']
                or clock['authority_sha256'].upper() != records['instrument_epoch']['sha256'].upper()):
            raise ValueError('recorded birth clock differs from the frozen split model')
        packet = load_recorded_release(raw, clock=ClockIdentity(clock['clock_epoch_id'], clock['authority_sha256']),
            frame_id=source['frame_id'], source_component_id=source['instance_id'], species_id=species_id,
            relative_weights=None, instrument_origin_us=source['instrument_origin_us'], expected_particle_ids=expected_particle_ids)
        if len(packet['rows']) != provenance['particle_count']:
            raise ValueError('recorded birth population differs from preparation')
        return simion.track(selected, packet, propagation=request['propagation'], observations=observations,
            numerics=request['numerics'], context=context, unit_size=unit_size, recovery_reference=recovery_reference,
            dispatch_profiles=dispatch_profiles, birth_source_authority={'manifest': manifest_record, 'records': records},
            **({'scalar_field_basis': scalar_field_basis} if scalar_field_basis is not None else {}))
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
        birth_source_authority={'manifest': manifest_record, 'records': records},
        **({'scalar_field_basis': scalar_field_basis} if scalar_field_basis is not None else {}))


def main() -> None:
    """Track explicit previously published inputs using the public owner."""
    import argparse
    from msplatform.execution import load_environment
    from msplatform.io.manifest_records import file_record

    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--preparation-manifest', type=Path)
    source.add_argument('--release-request', type=Path)
    parser.add_argument('--fields-reference', type=Path, required=True)
    parser.add_argument('--species-id')
    parser.add_argument('--expected-particle-ids', type=Path)
    parser.add_argument('--propagation', type=Path)
    parser.add_argument('--numerics', type=Path)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--environment', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--scalar-field-basis', type=Path)
    parser.add_argument('--recovery-reference', type=Path)
    parser.add_argument('--dispatch-profiles', type=Path)
    parser.add_argument('--unit-size', type=int)
    args = parser.parse_args()

    def document(path: Path) -> Any:
        return json.loads(path.read_text(encoding='utf-8-sig'))

    if args.release_request:
        if args.species_id or args.expected_particle_ids or not args.propagation or not args.numerics:
            parser.error('fresh release requires propagation and numerics; species and IDs belong in the release request')
    elif not args.species_id or not args.expected_particle_ids or args.propagation or args.numerics:
        parser.error('historical preparation requires species and IDs; propagation and numerics come from preparation')
    context = load_environment(args.environment, workspace=args.workspace, profile=args.profile)
    common = dict(fields=document(args.fields_reference), observations=document(args.observations), context=context,
        unit_size=args.unit_size, recovery_reference=document(args.recovery_reference) if args.recovery_reference else None,
        dispatch_profiles=document(args.dispatch_profiles) if args.dispatch_profiles else (),
        scalar_field_basis=document(args.scalar_field_basis) if args.scalar_field_basis else None)
    if args.release_request:
        from msplatform.ion_release import sample_release
        result = simion.track(particles=sample_release(document(args.release_request)),
            propagation=document(args.propagation), numerics=document(args.numerics), **common)
    else:
        result = track_recorded_birth(preparation_manifest=file_record(args.preparation_manifest.resolve()),
            species_id=args.species_id, expected_particle_ids=document(args.expected_particle_ids), **common)
    print('OWNER_RETURNED=' + json.dumps(result.reference, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
