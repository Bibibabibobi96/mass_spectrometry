"""SIMION tracking plans/actions on one verified fixed field; no field solving."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from typing import Mapping

from msplatform.assembly.handoff import HandoffMother, HandoffResult
from msplatform.contracts.clock import ClockIdentity, require_same_clock
from msplatform.execution.executable_identity import windows_binary_version
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.contracts.particle_state import validate_component_particle_state_rows
from msplatform.contracts.rigid_transform import PhaseSpaceState, RigidTransform, relative_transform
from .artifacts import NativeStagePlan
from .model import require_prepared_model, model_geometry
from .source import project_source_states, project_handoff_source, lua_value, render_restart_fly2
from .tracking_program import validate_native_flight, validate_propagation_stop


def validate_birth_authority(authority: Mapping, particles: Mapping) -> dict:
    """Verify explicit recorded-birth producer and its selected small inputs."""
    from msplatform.io.manifest_records import validate_file_record, verify_record, require_completed_terminal_publication
    if (not isinstance(authority, Mapping) or set(authority) != {'manifest', 'records'}
            or not isinstance(authority['records'], Mapping) or not authority['records']
            or not isinstance(particles, Mapping) or particles.get('role') != 'canonical_recorded_birth_realization'):
        raise ValueError('birth authority requires a recorded birth, manifest and explicit records')
    manifest = validate_file_record(authority['manifest'], 'birth producer manifest')
    if not Path(manifest['path']).is_absolute():
        raise ValueError('birth producer manifest path must be absolute')
    verify_record('birth producer manifest', manifest)
    path = Path(manifest['path'])
    require_completed_terminal_publication(path)
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if document.get('role') != 'simulation_run_manifest' or document.get('status') != 'success':
        raise ValueError('birth producer must be a terminal successful run')
    inputs, outputs = document.get('inputs'), document.get('outputs')
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        raise ValueError('birth producer manifest lacks input/output records')
    bound = [*inputs.values(), *outputs]
    records = {}
    for name, value in authority['records'].items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError('birth authority record names must be explicit')
        record = validate_file_record(value, name)
        if not Path(record['path']).is_absolute():
            raise ValueError('birth authority paths must be absolute')
        if not any(isinstance(item, Mapping) and item.get('path') == record['path']
                   and item.get('bytes') == record['bytes']
                   and str(item.get('sha256', '')).upper() == record['sha256'].upper() for item in bound):
            raise ValueError('birth authority record is not bound by its producer')
        verify_record(name, record)
        records[name] = record
    selected = particles['recorded_source']['record']
    if not any(record['path'] == selected['path'] and record['bytes'] == selected['bytes']
               and record['sha256'].upper() == selected['sha256'].upper() for record in records.values()):
        raise ValueError('birth authority must bind the actual recorded source')
    return {'manifest': manifest, 'records': records}


def _mother_records(records):
    """Decode only canonical JSON decimal keys; never generate replacement IDs."""
    result = {}
    for key, row in records.items():
        if isinstance(key, str) and key.isascii() and key.isdecimal() and str(int(key)) == key:
            key = int(key)
        if type(key) is not int or key <= 0 or key in result or row['particle_id'] != key:
            raise ValueError('source mother has an invalid or duplicate canonical ID')
        result[key] = copy.deepcopy(row)
    return result


def validate_birth_source(packet: Mapping) -> tuple[list, HandoffMother, ClockIdentity]:
    """Validate the complete canonical birth cohort independently of geometry."""
    if isinstance(packet, Mapping) and packet.get('role') == 'canonical_recorded_birth_realization':
        from msplatform.particle_release.authoring import load_recorded_release
        source = packet['recorded_source']
        rebuilt = load_recorded_release(source['record'], clock=ClockIdentity(**packet['clock']),
            frame_id=source['frame_id'], source_component_id=source['source_component_id'],
            species_id=source['species_id'], species_kind=source['species_kind'], relative_weights=source['relative_weights'],
            instrument_origin_us=source['instrument_origin_us'], expected_particle_ids=source['expected_particle_ids'])
        if (set(packet) != set(rebuilt) or packet['schema_version'] != rebuilt['schema_version']
                or packet['state_kind'] != rebuilt['state_kind'] or packet['rows'] != rebuilt['rows']
                or packet['clock'] != rebuilt['clock'] or packet['recorded_source'] != rebuilt['recorded_source']
                or set(packet['mother']) != {'records', 'fates'}
                or _mother_records(packet['mother']['records']) != _mother_records(rebuilt['mother']['records'])
                or packet['mother']['fates'] != rebuilt['mother']['fates']):
            raise ValueError('recorded birth realization differs from its bound source and interpretation')
        count = len(source['expected_particle_ids'])
    else:
        count = None
    if (not isinstance(packet, Mapping) or type(packet.get('schema_version')) is not int
            or packet['schema_version'] != 1 or packet.get('role') not in {'canonical_release_realization', 'canonical_recorded_birth_realization'}
            or packet.get('state_kind') != 'source_birth'):
        raise ValueError('tracking birth source requires the actual canonical release realization')
    rows = validate_component_particle_state_rows(packet['rows']).rows
    records = _mother_records(packet['mother']['records'])
    ids = [row['particle_id'] for row in rows]
    if set(ids) != set(records) or len(rows) != (count if count is not None else packet['realization']['spec']['particle_count']):
        raise ValueError('birth source must contain the complete actually released mother')
    mother = HandoffMother({pid:records[pid] for pid in ids}, copy.deepcopy(packet['mother']['fates']))
    return rows, mother, ClockIdentity(**packet['clock'])


def _birth_states(packet, geometry):
    rows, mother, clock = validate_birth_source(packet)
    plan = geometry['composition_plan']
    poses = {row['instance_id']:RigidTransform.from_contract(row['transform']) for row in plan['recipe']['instances']}
    projected = []
    for row in rows:
        instance = row['source_component_id']
        if instance not in plan['scope']['instance_ids'] or instance not in poses:
            raise ValueError('birth source component is not bound to selected geometry')
        interface = plan['components'][instance]
        if row['frame_id'] != interface['local_frame_id']:
            raise ValueError('birth state frame differs from its real provider local frame')
        target = geometry['native_frame_id']
        pose = poses[instance]
        if target != plan['assembly_frame_id']:
            anchors = [key for key in plan['scope']['instance_ids']
                       if plan['components'][key]['local_frame_id'] == target and key in poses]
            if len(anchors) != 1:
                raise ValueError('native tracking frame has missing or ambiguous selected anchor')
            pose = relative_transform(pose, poses[anchors[0]])
        if pose.to_frame_id != target:
            # The compiled native frame is explicit; do not guess another
            # transform when the source pose does not reach that frame.
            raise ValueError('birth pose does not directly target the native tracking frame')
        state = pose.transform_state(PhaseSpaceState(row['frame_id'],
            tuple(row['position_'+a+'_mm'] for a in 'xyz'),
            tuple(row['velocity_'+a+'_m_s'] for a in 'xyz'), row['instrument_time_us']))
        item = copy.deepcopy(row)
        item['frame_id'] = state.frame_id
        item.update({'position_'+a+'_mm':value for a,value in zip('xyz',state.position_mm,strict=True)})
        item.update({'velocity_'+a+'_m_s':value for a,value in zip('xyz',state.velocity_m_s,strict=True)})
        item['kinetic_energy_eV'] = kinetic_energy_ev(item['mass_amu'],*state.velocity_m_s)
        projected.append(item)
    validate_component_particle_state_rows(projected)
    return projected, mother, clock


def _resolve_scalar_basis(source, model, plan, selection):
    """Admit selected scalar products against the actual source-free SFI model."""
    import json
    if not isinstance(selection, Mapping) or not {'geometry_artifact', 'samples'} <= set(selection) or set(selection) - {'geometry_artifact', 'samples', 'refinement_windows'}:
        raise ValueError('scalar basis requires explicit geometry_artifact and samples')
    if plan['propagation']['scope'] != 'continuous_assembly' or not plan['rows']:
        raise ValueError('scalar basis requires a nonempty continuous original-birth flight')
    geometry = model_geometry(model, downstream_drive=True).frontend_geometry
    if geometry.get('role') == 'simion_split_oa_tof_geometry':
        from .frontend import split_frontend_instances
        from .split_scalar_binding import resolve_split_scalar_basis
        rf_instances, _, _ = split_frontend_instances(geometry['composition_plan'])
        if rf_instances:
            raise ValueError('split scalar field currently supports only OA and TOF without RF')
        if 'native_field_observation' in plan['observations']:
            raise ValueError('split scalar field observations are not yet supported')
        binding = resolve_split_scalar_basis(model=model, geometry_artifact=selection['geometry_artifact'],
                                             samples=selection['samples'], refinement_windows=selection.get('refinement_windows'))
        from .split_scalar_workbench import WORLD_REPRESENTATION, WORLD_SLOTS, _admit_world, project_split_scalar_world
        metadata = source.metadata
        if (metadata.get('field_representation') != WORLD_REPRESENTATION or metadata.get('world_slots') != WORLD_SLOTS
                or metadata.get('background_native_cold_reopen') is not True or metadata.get('background_priority_observed') is not True):
            raise ValueError('split scalar tracking requires a verified world background PA and workbench binding')
        original, bound_model, checked, carriers = _admit_world(metadata['collision_source_reference'], selection)
        if require_prepared_model(bound_model) != require_prepared_model(model) or checked != binding:
            raise ValueError('world collision source or scalar binding differs from tracking')
        projection = json.loads(source.data_path('world_binding').read_text(encoding='utf-8-sig'))
        background = source.data_path('background')
        if Path(projection['slots'][0]['path']).resolve() != background.resolve():
            raise ValueError('world background binding differs from its published file')
        expected = project_split_scalar_world(model, binding, carriers=carriers, background_path=Path(projection['slots'][0]['path']))
        expected['collision_source_reference'] = original.reference
        if projection != expected or metadata.get('world_background_grid') != projection['grid']:
            raise ValueError('world workbench binding differs from its verified source inputs')
        source.data_path('workbench')
        source.data_path('zero_particle_format_control')
        plan['flight']['detector_instance'] = WORLD_SLOTS['detector']
        return dict(binding, world_projection=projection, collision_source_reference=original.reference)
    from .sfi_scalar_binding import resolve_sfi_scalar_basis
    design = json.loads(source.data_path('field_design').read_text(encoding='utf-8-sig'))
    return resolve_sfi_scalar_basis(model=model, geometry=geometry, field_design=design, flight=plan['flight'],
                                    geometry_artifact=selection['geometry_artifact'], samples=selection['samples'],
                                    refinement_windows=selection.get('refinement_windows'))


def _split_tracking_contract(geometry: Mapping, propagation: Mapping, observations: Mapping) -> int:
    """Require continuous original-birth split tracking and its actual detector disk."""
    if (not isinstance(propagation, Mapping) or propagation.get('scope') != 'continuous_assembly'
            or propagation.get('stop') is not None or propagation.get('consumed_plane_events') != []):
        raise ValueError('split OA–TOF requires one original-birth continuous flight without relaunch')
    face = geometry['detector_active_face']
    definitions = observations.get('plane_observations') if isinstance(observations, Mapping) else None
    selected = [item for item in definitions or [] if isinstance(item, Mapping) and item.get('schema_version') == 2
                and item.get('source_instance_id') == face['instance_id'] and item.get('surface_id') == face['surface_id']]
    if len(selected) != 1 or len(definitions) != 1:
        raise ValueError('split OA–TOF requires exactly one observation of its actual detector active face')
    detector = [row for row in geometry['downstream_pa_instances'] if row.get('role') == 'detector']
    if len(detector) != 1 or type(detector[0].get('workbench_index')) is not int or detector[0]['workbench_index'] < 1:
        raise ValueError('split OA–TOF requires one explicit detector native workbench instance')
    return detector[0]['workbench_index']


def _validate_split_birth_instance(geometry, rows):
    from .frontend import split_frontend_instances
    rf_instances, oa_instance, _ = split_frontend_instances(geometry['composition_plan'])
    selected = set(rf_instances) | {oa_instance}
    downstream = {edge['downstream']['instance_id'] for edge in geometry['composition_plan']['recipe']['connections']
                  if edge['upstream']['instance_id'] in selected and edge['downstream']['instance_id'] in selected}
    first = selected - downstream
    if len(first) != 1 or any(row['source_component_id'] not in first for row in rows):
        raise ValueError('split births must originate in the declared first component')


def _guard_complete_tof_flight(geometry, particles, propagation):
    """Keep complete TOF instruments on one original-birth continuous flight."""
    plan = geometry.get('composition_plan', {})
    components = plan.get('components', {})
    scope = plan.get('scope', {}).get('instance_ids', ())
    complete_tof = geometry.get('role') == 'simion_split_oa_tof_geometry' or any(
        components[instance].get('project_id') == 'single_reflection_oa_tof_mass_analyzer'
        for instance in scope)
    if complete_tof and (isinstance(particles, HandoffResult) or not isinstance(propagation, Mapping)
                         or propagation.get('scope') != 'continuous_assembly'):
        raise ValueError('complete OA–TOF requires original births and continuous assembly propagation')


def resolve_discovery_selection(discovery, model, *, field_manifest_record=None, field_product_id=None, provenance=None):
    """Recompute a pulse from a completed, manifest-bound original-birth pilot."""
    import json
    from msplatform.analysis.pulse_selection import select_discovery_pulse
    from msplatform.results.artifacts import open_artifact
    from .artifacts import CompiledPreparedModel
    from .tracking_program import discovery_pilot_pulse

    if not isinstance(discovery, Mapping) or set(discovery) != {'phase', 'author', 'pilot'} or discovery['phase'] != 'selected':
        raise ValueError('selected discovery requires its author and published pilot')
    author = discovery['author']
    document = require_prepared_model(model)
    pilot_author = {'phase': 'discovery', 'author': author}
    discovery_pilot_pulse(pilot_author, document['drive']['pulse'])
    pilot = open_artifact(discovery['pilot'], expected_kind='trajectory_result')
    if pilot.metadata.get('backend') != 'simion':
        raise ValueError('discovery pilot requires a SIMION tracking product')
    def read(key):
        return json.loads(pilot.data_path(key).read_text(encoding='utf-8-sig'))
    collection, observations, source = read('collection'), read('observations'), read('source_provenance')
    pilot_model = CompiledPreparedModel(pilot.data_path('compiled_model').read_text(encoding='utf-8-sig'))
    if require_prepared_model(pilot_model) != document:
        raise ValueError('discovery pilot model differs from the selected field model')
    if (collection.get('role') != 'simion_tracking_collection' or collection.get('native_complete') is not True
            or collection.get('observation_complete') is False or collection.get('pulse_discovery') != pilot_author
            or observations.get('pulse_discovery') != pilot_author
            or observations.get('observation_times_us') != author['candidate_times_us']
            or collection.get('effective_flight', {}).get('pulse') != {'mode': 'held_off'}
            or collection.get('clock_epoch_id') != document['drive']['clock']['clock_epoch_id']
            or collection.get('model_identity_sha256') != document['model_identity_sha256']
            or collection.get('source_provenance_record') != pilot.data_records['source_provenance']
            or source.get('state_kind') != 'source_birth'):
        raise ValueError('discovery pilot is incomplete or differs from the frozen author, model or clock')
    if field_manifest_record is not None:
        previous = collection.get('field_reference', {}).get('manifest', {})
        if (any(k not in previous or k not in field_manifest_record for k in ('bytes', 'sha256'))
                or any(str(previous[k]).lower() != str(field_manifest_record[k]).lower() for k in ('bytes', 'sha256'))):
            raise ValueError('discovery pilot and selected tracking field identities differ')
        if not isinstance(field_product_id, str) or collection['field_reference'].get('product_id') != field_product_id:
            raise ValueError('discovery pilot and selected tracking field product IDs differ')
    keys = ('mother_particle_ids', 'mother_records', 'mother_fates', 'clock_authority_sha256')
    if provenance is not None and any(source.get(k) != provenance.get(k) for k in keys):
        raise ValueError('discovery pilot and selected tracking original mother or clock differ')
    birth_rows = [row for row in collection['canonical_events'] if row['event'] == 'source_release']
    births = {row['particle_id']: row['instrument_time_us'] for row in birth_rows}
    terminals = {row['particle_id']: row['instrument_time_us'] for row in collection['native_terminals']}
    ids = source.get('mother_particle_ids')
    if (not isinstance(ids, list) or len(ids) != len(set(ids)) or len(birth_rows) != len(ids)
            or source.get('execution_particle_ids') != ids or len(collection['native_terminals']) != len(ids)
            or set(births) != set(ids) or set(terminals) != set(ids)):
        raise ValueError('discovery pilot birth and terminal evidence must cover the original mother')
    from msplatform.contracts.particle_state import binary64_serialization_close
    mother = source.get('mother_records', [])
    if ([row.get('particle_id') for row in mother] != ids
            or any(not binary64_serialization_close(births[row['particle_id']], row['particle_birth_time_us'])
                   for row in mother)):
        raise ValueError('discovery pilot native births differ from the frozen original mother')
    decision = select_discovery_pulse(births_us=births, terminal_times_us=terminals,
        snapshots=collection['native_shared_states'], candidate_times_us=author['candidate_times_us'],
        frontend_geometry=model_geometry(model, downstream_drive=True).frontend_geometry,
        pulse_width_us=author['width_us'], input_records={
            'collection': pilot.data_records['collection'], 'request': pilot.data_records['observations'],
            'frontend_geometry': pilot.data_records['compiled_model']})
    if decision['status'] != 'success':
        raise ValueError('discovery pilot has no supported eligible pulse candidate')
    return dict(decision=decision, effective_pulse=dict(mode='timed',
        time_us=decision['actual_pulse_time_us'], width_us=author['width_us']))


def plan_tracking_execution(model, *, particles, clock_records: Mapping, propagation: Mapping,
                            observations: Mapping, numerics: Mapping, unit_size=None,
                            reused_unit_keys=(), field_manifest_record=None, field_product_id=None, birth_source_authority=None, hs1_request=None, ip_mr_field_reference=None, neutral_sampled_field_reference=None, focus_testplane_record=None) -> dict:
    """Validate the complete cohort and an explicit ordinal unit partition.

    The shared dispatcher controls real concurrency; units fix replay boundaries. Handoff producer
    references are verified by the execution action, not self-certified here.
    """
    document = require_prepared_model(model)
    raw_geometry = model_geometry(model).frontend_geometry
    _guard_complete_tof_flight(raw_geometry, particles, propagation)
    source_rows = particles.rows if isinstance(particles, HandoffResult) else particles.get('rows', []) if isinstance(particles, Mapping) else []
    if any(type(row.get('particle_id')) is not int or not 0 < row['particle_id'] <= 2**31 - 1 for row in source_rows):
        raise ValueError('SIMION Lua numeric log ABI requires particle IDs in 1..2147483647')
    species_registry = None
    if source_rows and not isinstance(particles, HandoffResult):
        from msplatform.particle_release.authoring import resolved_birth_species
        species_registry = resolved_birth_species(particles)
        if any(row['species_kind'] == 'electron' for row in species_registry):
            raise ValueError('SIMION native electron tracing is not yet validated')
    split = raw_geometry.get('role') == 'simion_split_oa_tof_geometry'
    detector_instance = _split_tracking_contract(raw_geometry, propagation, observations) if split else None
    ip_mr = raw_geometry.get('role') == 'simion_ip_mr_complete_geometry'
    joint_ip = raw_geometry.get('role') == 'simion_rf_ip_geometry'
    static_world = raw_geometry.get('role') in {'simion_neutral_world_collision_geometry', 'simion_neutral_multi_domain_collision_geometry'}
    neutral_sampled = neutral_sampled_field_reference is not None
    if raw_geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry' and not neutral_sampled:
        raise ValueError('multi-domain tracking requires its published sampled FieldBundle')
    if neutral_sampled:
        if not static_world:
            raise ValueError('neutral sampled field requires its world collision geometry')
        from .rf_tracking_execution import admit_neutral_sampled_tracking_fields
        neutral_admission = admit_neutral_sampled_tracking_fields(neutral_sampled_field_reference)
        if require_prepared_model(neutral_admission['model']) != document:
            raise ValueError('neutral sampled field and model differ')
        if field_manifest_record is not None and any(str(field_manifest_record[k]).lower() != str(neutral_admission['source'].reference['manifest'][k]).lower() for k in ('bytes', 'sha256')):
            raise ValueError('neutral sampled field manifest differs')
    if ip_mr:
        if ip_mr_field_reference is None:
            raise ValueError('IP–MR tracking requires a published common-field binding')
        from .ip_mr_tracking_admission import admit_ip_mr_tracking_fields
        admission = admit_ip_mr_tracking_fields(ip_mr_field_reference)
        if require_prepared_model(admission['model'])['model_identity_sha256'] != document['model_identity_sha256']:
            raise ValueError('IP–MR field and tracking model identities differ')
        if field_manifest_record is not None and any(
                str(field_manifest_record[k]).lower() != str(admission['source'].reference['manifest'][k]).lower()
                for k in ('bytes', 'sha256')):
            raise ValueError('IP–MR tracking field manifest differs')
        field_manifest_record = admission['source'].reference['manifest']
        from .rf_tracking_execution import prepare_ip_mr_hs1
        hs1 = prepare_ip_mr_hs1(model, hs1_request, common_world_domain=admission['world_domain'],
                                 common_world_frame_id=admission['world_frame_id'])
    elif ip_mr_field_reference is not None:
        raise ValueError('IP–MR field reference requires IP–MR geometry')
    independent_component = raw_geometry.get('role') in {'simion_independent_rf_geometry','simion_independent_oa_geometry'} or joint_ip or ip_mr or static_world
    neutral_hs1 = neutral_sampled and hs1_request is not None
    if neutral_hs1 and raw_geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry':
        raise ValueError('multi-domain neutral HS1 is not yet supported')
    if neutral_hs1:
        if not any(row['kind'] == 'ip_schedule' for row in document['native_drive_rows']):
            raise ValueError('neutral HS1 requires one canonical IP schedule')
        from .rf_tracking_execution import prepare_neutral_ip_hs1
        hs1 = prepare_neutral_ip_hs1(model, hs1_request, basis=neutral_admission['basis'])
    if joint_ip:
        from .rf_tracking_execution import prepare_rf_ip_hs1
        hs1 = prepare_rf_ip_hs1(model, hs1_request)
    elif not ip_mr and not neutral_hs1 and hs1_request is not None:
        raise ValueError('HS1 request is supported only for joint IP tracking')
    geometry = (dict(raw_geometry,native_frame_id=document['native_frame_id']) if independent_component else
                model_geometry(model,downstream_drive=True).frontend_geometry)
    if static_world:
        if isinstance(particles, HandoffResult) or not isinstance(propagation, Mapping) or propagation.get('scope') != 'continuous_assembly':
            raise ValueError('static world tracking requires original births in one continuous assembly')
        geometry['composition_plan'] = copy.deepcopy(raw_geometry['source_snapshot']['composition_plan'])
    expected = {'schema_version','scope','end_policy','consumed_plane_events','stop'}
    publication = propagation.get('publication_contract') if isinstance(propagation, Mapping) else None
    focus_authority = observations.get('oa_focus_authority') if isinstance(observations, Mapping) else None
    focus = focus_authority is not None
    if publication is not None:
        valid_publication = (publication == 'original_birth_si_v1' and joint_ip) or (publication == 'oa_focus_original_birth_si_v1' and focus and raw_geometry.get('role') == 'simion_independent_oa_geometry')
        if (not valid_publication or isinstance(particles, HandoffResult)
                or propagation.get('scope') != 'continuous_assembly' or propagation.get('stop') is not None
                or propagation.get('consumed_plane_events') != []):
            raise ValueError('RF–IP SI publication requires one continuous original-birth cohort')
        expected.add('publication_contract')
    if independent_component:
        expected.add('dynamics')
        if not isinstance(propagation,Mapping) or propagation.get('dynamics') != dict(kinematics='nonrelativistic',collisions='hs1' if joint_ip or ip_mr or neutral_hs1 else 'none',space_charge='none'):
            raise ValueError('RF tracking requires explicit collision-free nonrelativistic external-field dynamics')
    if (not isinstance(propagation,Mapping) or set(propagation) != expected
            or type(propagation['schema_version']) is not int or propagation['schema_version'] != 1
            or propagation['scope'] not in {'continuous_assembly','segmented_upstream','state_relaunch'}):
        raise ValueError('explicit supported tracking propagation policy required')
    if (not isinstance(observations,Mapping) or 'plane_observations' not in observations
            or set(observations)-{'plane_observations','observation_times_us','native_field_observation','field_intervention','pulse_discovery','oa_focus_authority','oa_focus_field_mode'} or not isinstance(observations['plane_observations'],list)):
        raise ValueError('tracking observations require the explicit existing plane definitions')
    if publication is not None and not focus and observations['plane_observations'] != []:
        raise ValueError('RF–IP SI publication currently requires explicit empty plane observations')
    if 'field_intervention' in observations:
        from .field_intervention import _case
        case = observations['field_intervention']
        if not split or not isinstance(case, Mapping) or set(case) != {'id', 'selector'}:
            raise ValueError('field intervention requires an explicit split OA–TOF case')
        _case(case)
    definitions = copy.deepcopy(observations['plane_observations'])
    focus_field_mode=observations.get('oa_focus_field_mode')
    if focus_field_mode is not None and (not focus or not isinstance(focus_field_mode,str) or focus_field_mode not in {'native','zone1_ideal','zone2_ideal','full_ideal'}):
        raise ValueError('OA focus field mode requires an authorized focus and one declared mode')
    focus_runtime = None
    if focus:
        if publication != 'oa_focus_original_birth_si_v1' or not source_rows:
            raise ValueError('OA focus requires explicit original births and internally derived planes')
        from msplatform.io.file_identity import guarded_file_identity
        from msplatform.io.manifest_records import verify_record
        from .oa_focus_model_projection import validate_focus_authority
        from contextlib import ExitStack
        with ExitStack() as stack:
            documents=[]
            for key in ('campaign','component_contract'):
                record=focus_authority[key]
                verify_record('OA focus '+key,record)
                stack.enter_context(guarded_file_identity(record['path'],expected_bytes=record['bytes'],expected_sha256=record['sha256']))
                documents.append(json.loads(Path(record['path']).read_text(encoding='utf-8-sig')))
            validate_focus_authority(focus_authority,campaign=documents[0],component_contract=documents[1],model_document=document)
        if not isinstance(focus_testplane_record,Mapping):
            raise ValueError('OA focus requires a frozen SIMION TestPlane record')
        verify_record('OA focus TestPlane',dict(focus_testplane_record))
        component=focus_authority['component_id']
        recipe=geometry['composition_plan']['recipe']
        poses=[row['transform'] for row in recipe['instances'] if row['instance_id']==component]
        if len(poses)!=1 or any(row['source_component_id']!=component for row in source_rows):
            raise ValueError('OA focus source and actual placement differ')
        pose=poses[0];rotation=pose['rotation'];translation=pose['translation_mm']
        normal=[-rotation[i][2] for i in range(3)]
        planes=[]
        for name,key in (('oa_focus_exit','exit_z_mm'),('oa_focus_plane','focus_z_mm')):
            center=[translation[i]+rotation[i][2]*focus_authority[key] for i in range(3)]
            planes.append(dict(observation_id=name,center_mm=center,normal=normal))
        focus_runtime=dict(planes=planes,exit_id='oa_focus_exit',focus_id='oa_focus_plane')
        derived=[dict(schema_version=1,observation_id=p['observation_id'],source_instance_id=component,port_id=p['observation_id'],max_records=1) for p in planes]
        if definitions and definitions != derived:
            raise ValueError('OA focus plane definitions differ from the frozen authority')
        definitions=derived
    elif focus_testplane_record is not None:
        raise ValueError('TestPlane record requires OA focus authority')
    validate_propagation_stop(propagation['stop'], definitions)
    if (propagation['scope']=='segmented_upstream') != (propagation['stop'] is not None):
        raise ValueError('only explicit segmented upstream propagation may request a cut stop')
    clock = ClockIdentity(document['drive']['clock']['clock_epoch_id'],document['drive']['clock']['authority_sha256'])
    consumed = propagation['consumed_plane_events']
    if isinstance(particles,HandoffResult):
        if birth_source_authority is not None:
            raise ValueError('birth source authority cannot be used for a handoff')
        if propagation['scope'] != 'state_relaunch':
            raise ValueError('handoff/snapshot propagation must declare state_relaunch')
        require_same_clock(particles.clock.source,particles.clock.target)
        require_same_clock(particles.clock.target,clock)
        rows = copy.deepcopy(list(particles.rows))
        if any(row['frame_id'] != geometry['native_frame_id'] for row in rows):
            raise ValueError('handoff must already be explicitly mapped to the native tracking frame')
        native,provenance = project_handoff_source(particles,clock_records=clock_records,consumed_plane_events=consumed)
        mother = particles.mother
    else:
        if propagation['scope']=='state_relaunch':
            raise ValueError('state_relaunch requires an actual canonical handoff result')
        rows,mother,source_clock = _birth_states(particles,geometry)
        if split:
            _validate_split_birth_instance(raw_geometry, rows)
        if static_world:
            if raw_geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry':
                grid = neutral_admission['basis']['grid']
                domain = dict(minimum_mm=grid['origin_mm'], maximum_mm=[
                    grid['origin_mm'][i] + (grid['dimensions'][i] - 1) * grid['pitch_mm'][i]
                    for i in range(3)])
            else:
                domain = raw_geometry['domain']
            for row in rows:
                if any(not domain['minimum_mm'][i] <= row['position_'+axis+'_mm'] <= domain['maximum_mm'][i]
                       for i, axis in enumerate('xyz')):
                    raise ValueError('static world birth is outside the explicit field domain')
        require_same_clock(source_clock,clock)
        native,provenance = project_source_states(rows,mother=mother,clock=clock,state_kind='source_birth',
            clock_records=clock_records,consumed_plane_events=consumed)
        if publication is not None:
            ids = [row['particle_id'] for row in rows]
            if (not ids or provenance.get('mother_particle_ids') != ids
                    or provenance.get('execution_particle_ids') != ids
                    or [row.get('particle_id') for row in provenance.get('mother_records', [])] != ids
                    or any(row['instrument_time_us'] != row['particle_birth_time_us'] for row in rows)):
                raise ValueError('RF–IP SI publication requires the complete original-birth mother')
        if particles.get('role') == 'canonical_recorded_birth_realization':
            provenance['recorded_birth_source'] = copy.deepcopy(particles['recorded_source'])
        if birth_source_authority is not None:
            provenance['birth_source_authority'] = validate_birth_authority(birth_source_authority, particles)
    policy = propagation['end_policy']
    if not isinstance(policy,Mapping) or set(policy) not in ({'maximum_particle_age_us'},{'absolute_instrument_end_us'}):
        raise ValueError('tracking end_policy must select exactly one absolute-clock rule')
    value = next(iter(policy.values()))
    if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
        raise ValueError('tracking end policy must be finite and positive')
    deadlines = {pid:(record['particle_birth_time_us']+value if 'maximum_particle_age_us' in policy else value)
                 for pid,record in mother.records.items()}
    if any(not math.isfinite(end) for end in deadlines.values()):
        raise ValueError('tracking absolute deadline is nonfinite')
    if any(deadlines[row['particle_id']] <= row['instrument_time_us'] for row in rows):
        raise ValueError('tracking absolute deadline is not later than each actual start')
    has_ip_schedule = any(row['kind']=='ip_schedule' for row in document['native_drive_rows'])
    if static_world and has_ip_schedule and not neutral_sampled:
        raise ValueError('scheduled neutral model requires published sampled field')
    rf = any(row['kind']=='rf' for row in document['native_drive_rows']) or has_ip_schedule
    keys = {'maximum_step_us','trajectory_quality',*({'rf_steps_per_period'} if rf else set())}
    if independent_component and isinstance(numerics,Mapping) and 'grouped' in numerics:
        keys.add('grouped')
    if not isinstance(numerics,Mapping) or set(numerics) != keys:
        raise ValueError('tracking numerics must not contain source, drive or field-solve controls')
    horizon = max((deadlines[row['particle_id']]-row['instrument_time_us'] for row in rows),default=value)
    flight_input = dict(numerics,maximum_flight_us=horizon)
    if not independent_component:
        flight_input['pulse'] = copy.deepcopy(document['drive']['pulse'])
    discovery = observations.get('pulse_discovery')
    discovery_resolution = None
    if discovery is not None:
        from .tracking_program import discovery_pilot_pulse
        if not isinstance(discovery, Mapping) or not split:
            raise ValueError('pulse discovery requires the split OA–TOF geometry')
        if discovery.get('phase') == 'discovery':
            flight_input['pulse'] = discovery_pilot_pulse(discovery, document['drive']['pulse'])
            if observations.get('observation_times_us') != discovery['author']['candidate_times_us']:
                raise ValueError('discovery pilot must observe each explicit candidate time')
        else:
            if field_manifest_record is None:
                raise ValueError('selected discovery requires the bound field manifest identity')
            discovery_resolution = resolve_discovery_selection(discovery, model,
                field_manifest_record=field_manifest_record, field_product_id=field_product_id, provenance=provenance)
            flight_input['pulse'] = discovery_resolution['effective_pulse']
    if 'observation_times_us' in observations:
        flight_input['observation_times_us'] = copy.deepcopy(observations['observation_times_us'])
    if independent_component:
        from .rf_tracking_program import validate_rf_flight
        flight = validate_rf_flight(flight_input,requires_rf=rf)
        if raw_geometry['role']=='simion_independent_oa_geometry':flight['tracking_kind']='independent_oa'
        if static_world:flight['tracking_kind']='neutral_sampled' if neutral_sampled else 'static_world'
        if static_world and has_ip_schedule:flight['has_ip_schedule']=True
        if neutral_hs1:flight['has_hs1']=True
        if joint_ip: flight['tracking_kind']='rf_ip'
        if publication is not None: flight['original_birth_si'] = True
        if focus_runtime is not None: flight['oa_focus_runtime'] = focus_runtime
        if focus_field_mode is not None: flight['oa_focus_field_mode'] = focus_field_mode
        if ip_mr: flight['tracking_kind']='ip_mr'
    else:
        flight = validate_native_flight(flight_input,requires_rf=rf)
        if split:
            flight.update(tracking_kind='split_oa_tof', detector_instance=detector_instance)
    if 'native_field_observation' in observations:
        if independent_component or isinstance(particles,HandoffResult) or not rows:
            raise ValueError('native field observation requires a nonempty original-birth assembly flight')
        from .frontend import native_frontend_instances, split_frontend_instances
        from .tracking_program import validate_native_field_observation
        if split:
            rf_instances, _, _ = split_frontend_instances(geometry['composition_plan'])
        else:
            rf_instances, _ = native_frontend_instances(geometry['composition_plan'])
        spec = validate_native_field_observation(observations['native_field_observation'],
            particle_ids=provenance['mother_particle_ids'],source_instances=rf_instances,
            domain_ids=[*geometry['numerical_domains'],'flight_tube','reflectron','detector'],clock_epoch_id=clock.clock_epoch_id,flight=flight)
        if any(row['source_component_id'] != spec['source_instance_id'] for row in rows):
            raise ValueError('native field observation source differs from the original births')
    from dataclasses import asdict
    result = dict(source_realization=asdict(particles) if isinstance(particles,HandoffResult) else copy.deepcopy(particles),
        schema_version=1,role='simion_tracking_plan',model_identity_sha256=document['model_identity_sha256'],
        execution_profile='explicit_one_complete_cohort_unit_v1' if unit_size is None else 'explicit_fixed_ordinal_tracking_units_v1',
        rows=rows,native_source_rows=native,source_provenance=provenance,
        absolute_deadlines_us_by_particle_id=deadlines,flight=flight,propagation=copy.deepcopy(dict(propagation)),
        observations=copy.deepcopy(dict(observations)),numerics=copy.deepcopy(dict(numerics)),
        native_requested=bool(rows))
    if species_registry is not None:
        result['species'] = species_registry
    if focus_runtime is not None:
        result['observations']['plane_observations'] = definitions
        result['focus_testplane_identity'] = {key:focus_testplane_record[key] for key in ('bytes','sha256')}
    if discovery_resolution is not None:
        result['discovery_resolution'] = discovery_resolution
        result['discovery_field_product_id'] = field_product_id
    if ip_mr and (isinstance(particles,HandoffResult) or propagation['scope'] != 'continuous_assembly'):
        raise ValueError('IP–MR requires one continuous original-birth cohort')
    if neutral_sampled:
        result['scalar_field_basis'] = copy.deepcopy(neutral_admission['basis'])
        result['neutral_source_identity'] = {name: {key: record[key] for key in ('bytes', 'sha256')}
            for name, record in neutral_admission['code_records'].items()}
    if ip_mr:
        result['scalar_field_basis'] = copy.deepcopy(admission['basis'])
        result['collision_priority'] = copy.deepcopy(admission['priority'])
    if joint_ip or ip_mr or neutral_hs1:
        if any(type(row['particle_id']) is not int or row['particle_id'] < 1
               or hs1['identity']['numerics']['seed'] + row['particle_id'] - 1 > 2147483646 for row in rows):
            raise ValueError('RF-IP HS1 requires supported original integer particle seeds')
        if flight.get('grouped') != 0:
            raise ValueError('RF-IP HS1 requires sequential particle processing')
        result['hs1_identity'] = hs1['identity']
    from .tracking_units import partition_tracking_units
    result.update(partition_tracking_units(result,unit_size=unit_size,reused_unit_keys=reused_unit_keys))
    result['field_manifest_identity'] = ({key:field_manifest_record[key] for key in ('bytes','sha256')}
                                         if field_manifest_record is not None else None)
    result['native_requested'] = bool(result['expected_operation_ids'])
    return result


def plan_tracking_workbench(compiled, *, field_design, components_resolved, carriers,
                             response_fields, field_workbench_record, run_directory,
                             program, native_source_rows, native_path_resource, ip_mr_admission=None, neutral_admission=None, program_metadata=None, world_projection=None, canonical_run_directory=None) -> NativeStagePlan:
    """Reuse the sole full solved-slot projection, changing only control transport.

    The verified structural seed supplies private bootstrap slots; published
    field records remain protected inputs and supply every solved carrier.
    """
    if world_projection is not None:
        from .native_plans import plan_split_scalar_world_tracking
        return plan_split_scalar_world_tracking(world_projection, world_iob_record=field_workbench_record,
            program=program, native_source_rows=native_source_rows, run_directory=run_directory,
            native_path_resource=native_path_resource, canonical_run_directory=canonical_run_directory)
    if neutral_admission is not None:
        from .rf_tracking_execution import plan_neutral_sampled_tracking_workbench
        return plan_neutral_sampled_tracking_workbench(compiled, admission=neutral_admission, run_directory=run_directory, program=program, native_source_rows=native_source_rows, native_path_resource=native_path_resource)
    if compiled.frontend_geometry.get('role') == 'simion_ip_mr_complete_geometry':
        if ip_mr_admission is None:
            raise ValueError('verified sampled IP–MR FieldBundle admission required')
        from .rf_tracking_execution import plan_ip_mr_tracking_workbench
        return plan_ip_mr_tracking_workbench(compiled, admission=ip_mr_admission, run_directory=run_directory,
            program=program, program_metadata=program_metadata, native_source_rows=native_source_rows, native_path_resource=native_path_resource)
    if ip_mr_admission is not None:
        raise ValueError('sampled IP–MR admission requires the matching geometry role')
    if compiled.frontend_geometry.get('role') in {'simion_independent_rf_geometry','simion_independent_oa_geometry','simion_rf_ip_geometry','simion_neutral_world_collision_geometry'}:
        from .rf_tracking_execution import plan_rf_tracking_workbench
        return plan_rf_tracking_workbench(compiled,carriers=carriers,run_directory=run_directory,
            program=program,native_source_rows=native_source_rows,native_path_resource=native_path_resource,
            program_metadata=program_metadata)
    from .native_plans import plan_field_workbench
    from .resources import structural_seed_path, STRUCTURAL_SEEDS, native_resource_path
    from .field_identity import _require_sha256
    if not native_source_rows:
        raise ValueError('zero handoff must not construct a native tracking workbench')
    root = Path(run_directory)
    if not root.is_absolute() or not str(root).isascii():
        raise ValueError('tracking requires the existing owner absolute ASCII native projection')
    count = 4 + int('entrance_refinement' in compiled.frontend_geometry['numerical_domains'])
    size,digest = STRUCTURAL_SEEDS[count]
    template = dict(path=str(structural_seed_path(count)),bytes=size,sha256=digest)
    projection = plan_field_workbench(compiled,field_design=field_design,components_resolved=components_resolved,
        carriers=carriers,response_fields=response_fields,run_directory=root,
        seed_record=template,native_path_resource=native_path_resource)
    if type(field_workbench_record.get('bytes')) is not int or field_workbench_record['bytes'] <= 0:
        raise ValueError('tracking requires its actual published solved workbench record')
    _require_sha256(field_workbench_record.get('sha256'),'field workbench')
    seed = Path(field_workbench_record['path'])
    if not seed.is_absolute() or not str(seed).isascii() or seed.suffix.lower() != '.iob':
        raise ValueError('field workbench needs an explicit supported native input path')
    original = projection.materializations[str(root/'inputs/field_iob.lua')]
    canonical_output = canonical_run_directory is not None and compiled.frontend_geometry.get('role') == 'simion_split_oa_tof_geometry'
    output = (Path(canonical_run_directory) if canonical_output else root)/'simion/tracking/instrument.iob'
    spec = root/'inputs/tracking_iob.lua'
    text = ('local spec=(function()\n'+original+'\nend)()\n'
            +'spec.output_iob='+lua_value(str(output))+'\n'
            +('spec.preserve_canonical_output=true\n' if canonical_output else '')+'return spec\n')
    materializations = {str(spec):text,str(output.with_suffix('.lua')):program,
                        str(output.with_suffix('.fly2')):render_restart_fly2(native_source_rows)}
    wrapper = native_resource_path('build_tracking_iob.lua')
    operations = tuple(dict(operation_id=name,role='SIMION',stage='prepare',
        arguments=['--nogui','--noprompt','lua',str(wrapper),str(spec),mode,str(native_path_resource)],
        outputs=[str(output)] if mode=='build' else [],success_marker=marker)
        for name,mode,marker in [('build_tracking_iob','build','SINGLE_REFLECTION_IOB=PASS'),
                                 ('verify_tracking_iob','verify','SINGLE_REFLECTION_IOB_REOPEN=PASS')])
    return NativeStagePlan(materializations,projection.input_copies,operations,(str(output),))


def _render_tracking_controls(model, plan: dict, *, field_design: dict, stored_bank: dict,
                              frontend_records: Mapping, downstream_assets: Mapping,
                              downstream_receipt: Mapping, native_sources: Mapping) -> dict:
    """Adapt published field protocols once; never read a cache generation path.

    The caller obtains frontend_records from FieldBundle domain/member data keys
    and downstream_assets from the unique full-family closure validator.
    """
    if plan['flight'].get('tracking_kind') == 'neutral_sampled':
        from .rf_tracking_program import render_rf_controls
        geometry = model_geometry(model).frontend_geometry
        slots = ([None] + [f'domain_{i:02d}' for i in range(1, len(geometry['domain_order']) + 1)]
                 if geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry'
                 else [None, 'world'])
        return render_rf_controls(model, plan, assets=frontend_records, native_sources=native_sources,
                                  scalar_bindings=plan['scalar_field_basis'], slot_domains=slots)
    if plan['flight'].get('tracking_kind') == 'ip_mr':
        from .rf_tracking_program import render_rf_controls
        policy = plan['collision_priority']
        roles = policy['roles']
        domains = [None, roles['rf'], roles['ip'], roles['analyzer'], roles['detector']]
        result = render_rf_controls(model,plan,assets=frontend_records,native_sources=native_sources,
                                    scalar_bindings=plan['scalar_field_basis'],slot_domains=domains)
        if result['build_metadata'].get('collision_priority_applied') is not True:
            raise ValueError('sampled tracking requires the verified collision priority Program')
        return result
    if plan['flight'].get('tracking_kind') in {'independent_rf','independent_oa','rf_ip','static_world'}:
        from .rf_tracking_program import render_rf_controls
        return render_rf_controls(model,plan,assets=frontend_records,native_sources=native_sources)
    from .field_bank import field_bank
    from .field_identity import working_point_member_id
    from .frontend import native_frontend_instances, split_frontend_instances
    from .tracking_program import build_successor_program, DOWNSTREAM_STATIC_ASSET_ROLE, DOWNSTREAM_STATIC_ASSET_REPRESENTATION

    if not plan['rows']:
        raise ValueError('zero handoff has no native Program or particle file')
    document = require_prepared_model(model)
    compiled = model_geometry(model,downstream_drive=True)
    geometry = compiled.frontend_geometry
    domains = [row['domain_id'] for row in field_design['domains']]
    if stored_bank != field_bank(field_design,domains):
        raise ValueError('published field bank differs from its actual design')
    expected_members = [working_point_member_id(point) for point in field_design['working_points']]
    if set(frontend_records) != set(domains) or any(set(rows) != set(expected_members) for rows in frontend_records.values()):
        raise ValueError('published owned response records do not cover the actual bank')
    bank = copy.deepcopy(stored_bank)
    world = plan.get('scalar_field_basis', {}).get('role') == 'split_off_on_scalar_binding'
    paths,carriers,responses,guards = {},{},[],[]
    for domain,row in zip(domains,bank['dynamic_roles'],strict=True):
        role = 'accelerator_main' if domain=='parent' else domain
        row.update(role=role,instance_index=(4 if world else 3) if domain=='parent' else 5)
        records = frontend_records[domain]
        for member,record in records.items():
            if Path(record['path']).name != ('frontend' if domain=='parent' else 'frontend_entrance_refinement')+'.'+member+'.pa':
                raise ValueError('published response basename differs from canonical field member')
        carriers['accelerator' if domain=='parent' else domain] = records['carrier_off']
        rf_members = [working_point_member_id(point) for point in field_design['working_points'] if point['kind']=='rf_reference']
        paths[role] = dict(rf_differential_pa_paths=[records[key]['path'] for key in rf_members],
                          **({'pulse_delta_pa_path':records['pulse_delta']['path']} if 'pulse_delta' in records else {}))
        definition = next(value for value in field_design['domains'] if value['domain_id']==domain)
        grid = dict(definition['dimensions'],**{f'd{a}_mm':definition['cell_mm_xyz'][a] for a in 'xyz'})
        responses.extend(dict(domain=domain,kind=key,path=record['path'],grid=grid)
                         for key,record in records.items() if key!='carrier_off')
        guards.extend(records.values())
    static_rows = []
    if set(downstream_assets) != {'flight_tube','reflectron','detector'}:
        raise ValueError('tracking needs all actual downstream field roles')
    for role,index in ([('flight_tube',2),('reflectron',3),('detector',5)] if world
                       else [('flight_tube',1),('reflectron',2),('detector',4)]):
        asset = downstream_assets[role]
        record = asset['carrier_record']
        carriers[role] = record
        guards.extend(asset['family_records'])
        if record not in asset['family_records']:
            guards.append(record)
        representation = ('standalone_voltageized_static_pa' if role == 'reflectron'
                          else 'run_private_native_static_family' if record['path'].lower().endswith('.pa0')
                          else 'analytic_zero_ground_standalone')
        static_rows.append(dict(role=role,instance_index=index,
            representation=representation, carrier_pa_basename=Path(record['path']).name,
            **({} if role=='reflectron' else {'family_members':[Path(value['path']).name for value in asset['family_records']]})))
    static = dict(schema_version=1,role=DOWNSTREAM_STATIC_ASSET_ROLE,
        runtime_representation=DOWNSTREAM_STATIC_ASSET_REPRESENTATION,
        receipt={key:downstream_receipt[key] for key in ('path','bytes','sha256')},static_roles=static_rows)
    if geometry.get('role') == 'simion_split_oa_tof_geometry':
        multipoles, _, tof = split_frontend_instances(geometry['composition_plan'])
    else:
        multipoles,tof = native_frontend_instances(geometry['composition_plan'])
    ids = [row['particle_id'] for row in plan['rows']]
    metadata = {}
    observation = plan['observations'].get('native_field_observation')
    selected_observation = None
    if observation is not None and observation['eligible_batch_anchor_particle_id'] in ids:
        selected_observation = dict(specification=observation, evidence_context=dict(
            phase='public_track', clock_epoch_id=document['drive']['clock']['clock_epoch_id'],
            mother_particle_ids=copy.deepcopy(plan['source_provenance']['mother_particle_ids']),
            field_records=copy.deepcopy(frontend_records),
            field_manifest_identity=copy.deepcopy(plan['field_manifest_identity'])))
        if plan.get('scalar_field_basis') is not None:
            selected_observation['evidence_context']['scalar_sources'] = {
                name: copy.deepcopy(item['records']) for name, item in plan['scalar_field_basis']['bases'].items()}
        if observation['domain_id'] in downstream_assets:
            selected_observation['evidence_context']['observation_basis'] = 'native_entry_gradient_no_extra_query'
            selected_observation['evidence_context']['static_carrier_record'] = copy.deepcopy(downstream_assets[observation['domain_id']]['carrier_record'])
    scalar = plan.get('scalar_field_basis')
    if scalar is not None:
        for item in scalar['bases'].values():
            guards.extend(item['records'].values())
            for level in item.get('refinement_windows', []): guards.extend(level['records'].values())
        unique = {}; distinct = []
        for record in guards:
            key = os.path.normcase(str(Path(record['path']).resolve()))
            identity = (record['bytes'], record['sha256'], record.get('retention_role'))
            if key in unique:
                if unique[key] != identity: raise ValueError('conflicting immutable input record: ' + key)
                continue
            unique[key] = identity; distinct.append(record)
        guards = distinct
    program = build_successor_program({key:document['components_resolved'][key] for key in multipoles},
        field_design,document['components_resolved'][tof],frontend_geometry=geometry,flight=plan['flight'],
        birth_times_us=[row['instrument_time_us'] for row in plan['rows']],particle_ids=ids,
        initial_velocities_mm_per_us=[[row['velocity_'+a+'_m_s']/1000 for a in 'xyz'] for row in plan['rows']],
        original_birth_times_us=[row['particle_birth_time_us'] for row in plan['rows']],
        absolute_deadlines_us=[plan['absolute_deadlines_us_by_particle_id'][pid] for pid in ids],
        standalone_dynamic_field_bank=bank,standalone_dynamic_field_paths=paths,downstream_static_fields=static,
        build_metadata=metadata,plane_observations=plan['observations']['plane_observations'] or None,
        consumed_plane_events=plan['propagation']['consumed_plane_events'],propagation_stop=plan['propagation']['stop'],
        prepared_model=model,field_intervention=plan['observations'].get('field_intervention'),
        pulse_discovery=plan['observations'].get('pulse_discovery'),
        field_manifest_identity=plan.get('field_manifest_identity'),
        field_product_id=plan.get('discovery_field_product_id'),
        **({'field_observation':selected_observation} if selected_observation is not None else {}),
        **({'scalar_field_basis':scalar} if scalar is not None else {}),**native_sources)
    return dict(program=program,build_metadata=metadata,carriers=carriers,response_fields=responses,
                immutable_input_records=list(guards),flight=plan['flight'])


def _artifact_record(source, key):
    """Use the reader's verified location, not a guessed author/generation path."""
    return dict(source.data_records[key],path=str(source.data_path(key)))


def _unique_inputs(records):
    result = {}
    for row in records:
        path = str(Path(row['path']).resolve())
        identity = row['bytes'],str(row['sha256']).upper()
        if path in result and (result[path]['bytes'],str(result[path]['sha256']).upper()) != identity:
            raise ValueError('immutable tracking inputs contain conflicting file identities')
        result[path] = dict(row,path=path)
    return list(result.values())


def _verified_handoff_source(session, source_reference, particles, plan, geometry):
    """Bind actual incoming states to published observations, not caller assertions."""
    import json
    from msplatform.results.artifacts import open_artifact
    from .model_execution import _protected_source
    from .source import prepare_plane_handoff_states
    from msplatform.contracts.particle_state import binary64_serialization_close

    if source_reference is None:
        raise ValueError('state relaunch requires its published trajectory source reference')
    source = open_artifact(source_reference,expected_kind='trajectory_result')
    _protected_source(session,source.reference['manifest'])
    collection = json.loads(source.data_path('collection').read_text(encoding='utf-8-sig'))
    if collection.get('native_complete') is not True:
        raise ValueError('handoff source lacks completed actual native observation evidence')
    if collection.get('model_identity_sha256') != plan['model_identity_sha256']:
        raise ValueError('current fixed-field relaunch requires the same model operator')
    # Re-read the actual manifest-bound raw wire, source and frozen control
    # facts using C's unique collector. Published6D alone is not observation.
    from .tracking_collection import collect_tracking_logs
    original_rows = json.loads(source.data_path('canonical_source_states').read_text(encoding='utf-8-sig'))
    original_provenance = json.loads(source.data_path('source_provenance').read_text(encoding='utf-8-sig'))
    controls = json.loads(source.data_path('native_controls').read_text(encoding='utf-8-sig'))
    stdout_keys = controls.get('stdout_data_keys',['native_stdout'])
    actual_collection = collect_tracking_logs([source.data_path(key) for key in stdout_keys],
        source_rows={row['particle_id']:row for row in original_rows},source_provenance=original_provenance,
        flight=controls['flight'],batches=controls['batches'])
    original = actual_collection.get('original_mother')
    if not isinstance(original,dict):
        raise ValueError('handoff source lacks the complete original mother')
    records = {row['particle_id']:row for row in original['mother_records']}
    if (records != dict(particles.mother.records) or original['mother_fates'] != list(particles.mother.fates)
            or original['clock_authority_sha256'].upper() != particles.clock.source.authority_sha256.upper()):
        raise ValueError('handoff reshapes published original mother or clock authority')
    require_same_clock(particles.clock.source,ClockIdentity(collection['clock_epoch_id'],original['clock_authority_sha256']))
    events = plan['propagation']['consumed_plane_events']
    if particles.state_kind=='plane_crossing':
        observations = actual_collection.get('plane_observations')
        if not isinstance(observations,dict) or observations.get('status') != 'complete':
            raise ValueError('plane relaunch requires complete published original plane wire')
        if not events:
            if particles.rows:
                raise ValueError('nonempty plane handoff lacks consumed event identities')
            policy = actual_collection.get('propagation_stop')
            if not policy:
                raise ValueError('empty plane handoff lacks its published first-outward selection policy')
            selection = policy['observation_id'],policy['direction'],policy['occurrence']
        else:
            selections = {(event['observation_id'],event['direction'],event['occurrence']) for event in events}
            if len(selections) != 1:
                raise ValueError('current relaunch supports one explicit plane occurrence selection')
            selection = next(iter(selections))
        definition = [row for row in observations['definitions'] if row['observation_id']==selection[0]]
        if len(definition) != 1:
            raise ValueError('handoff selection is not a published plane definition')
        native = geometry['native_frame_id']
        transform = RigidTransform(native,native,((1,0,0),(0,1,0),(0,0,1)),(0,0,0))
        targets = {row['target_component_id'] for row in particles.rows}
        if len(targets)>1:
            raise ValueError('current plane handoff requires one declared receiving component')
        target = next(iter(targets)) if targets else definition[0]['source_instance_id']
        expected = prepare_plane_handoff_states(observations,observation_id=selection[0],direction=selection[1],occurrence=selection[2],
            source_instance_id=definition[0]['source_instance_id'],target_instance_id=target,frame_id=native,
            transform=transform,clock=particles.clock,mother=particles.mother,producer_completed=True)
        if expected.rows != particles.rows or expected.selected_particle_ids != particles.selected_particle_ids:
            raise ValueError('handoff states differ from the original published plane wire')
    else:
        shared = actual_collection.get('native_shared_states',[])
        for row in particles.rows:
            matches = [value for value in shared if value['particle_id']==row['particle_id']
                       and value['instrument_time_us']==row['instrument_time_us']]
            if len(matches) != 1:
                raise ValueError('snapshot state lacks its unique actual published shared-time observation')
            actual = matches[0]
            for axis in 'xyz':
                if (not binary64_serialization_close(row['position_'+axis+'_mm'],actual[axis+'_mm'])
                        or not binary64_serialization_close(row['velocity_'+axis+'_m_s'],actual['v'+axis+'_mm_per_us']*1000)):
                    raise ValueError('snapshot 6D state differs from actual published observation')
    return source


def _collect_unit_field_observation(plan, batches, logs, render_unit):
    """Bind native unit metadata to current inputs before parsing final logs."""
    from .tracking_field_observation import collect_native_field_observations
    observation=plan['observations']['native_field_observation']
    source_rows={row['particle_id']:row for row in plan['rows']}
    if len(plan['units'])!=len(batches):raise ValueError('tracking observation units differ')
    expected={}
    for unit,case in zip(plan['units'],batches,strict=True):
        if unit['expected_particle_ids']!=case['expected_particle_ids']:
            raise ValueError('tracking observation unit identity differs')
        if observation['eligible_batch_anchor_particle_id'] not in unit['expected_particle_ids']:
            continue
        rebuilt=render_unit(unit)
        actual=case.get('build_metadata',{}).get('native_field_observation')
        if rebuilt is None or rebuilt!=actual or rebuilt['specification']!=observation:
            raise ValueError('tracking unit observation context differs from current verified inputs')
        expected[tuple(unit['expected_particle_ids'])]=rebuilt['context']
    def expected_context(case):return expected[tuple(case['expected_particle_ids'])]
    return collect_native_field_observations(logs,batches,source_rows,observation,expected_context)


def _execute_tracking_units(session, *, model, plan, design, stored_bank, frontend, downstream, source,
                            compiled, field_workbench, borrowed, frozen, native_path, sources,
                            resource_names, small, records, limits, allow_asynchronous_io,
                            recovery, dispatch_profiles, executable_identity, ip_mr_admission=None, neutral_admission=None):
    """Prepare whole units, dispatch actual Fly operations, then collect once."""
    import json
    from msplatform.io.manifest_records import file_record,verify_record
    from msplatform.execution.recorded_file_removal import write_json_atomic
    from msplatform.execution.simion_dispatch import plan_simion_dispatch,prepare_fixed_partition_dispatch
    from .native_io import apply_native_io_mode
    from .tracking_collection import collect_tracking_logs
    from .tracking_units import slice_tracking_plan,tracking_applicability,_validate_completed_unit

    index_path = session.declare_file(session.log_dir/'tracking_units.json','required_evidence')
    index = dict(schema_version=1,role='simion_tracking_units',applicability_sha256=tracking_applicability(plan),
        native_executable_identity=executable_identity,immutable_inputs=list(records.values()),
        units=[dict(key=unit['key'],source_row_range=unit['source_row_range'],
                    expected_particle_ids=unit['expected_particle_ids'],complete=False) for unit in plan['units']])
    write_json_atomic(index_path,index)
    batches, stdout_keys, fly_specs, prepared = [],[],[],[]
    native_calls = 0
    reused = {row['key']:row for row in recovery['index']['units'] if row['complete']} if recovery else {}
    for unit,row in zip(plan['units'],index['units'],strict=True):
        key = unit['key']
        stdout_key = 'native_stdout' if plan['unit_size'] is None else 'native_stdout__'+key
        stdout_keys.append(stdout_key)
        if unit['action']=='reuse':
            previous = reused[key]
            row.update(complete=True,build_metadata=copy.deepcopy(previous['build_metadata']),
                stdout_record=small(stdout_key,session.input_dir/'reused'/key/'stdout.log',source_path=previous['stdout_record']['path']),
                process_record=small('reused_process__'+key,session.input_dir/'reused'/key/'process.json',source_path=previous['process_record']['path']))
            batches.append(dict(source_row_range=unit['source_row_range'],expected_particle_ids=unit['expected_particle_ids'],
                                build_metadata=row['build_metadata']))
            continue
        subset = slice_tracking_plan(plan,unit)
        if subset['flight'].get('oa_focus_runtime') is not None:
            subset['flight']['oa_focus_runtime']['testplane_path'] = str(session.input_dir/'native_sources/testplanelib.lua')
        controls = _render_tracking_controls(model,subset,field_design=design,stored_bank=stored_bank,
            frontend_records=frontend,downstream_assets=downstream,downstream_receipt=None if plan['flight'].get('tracking_kind') in {'independent_rf','independent_oa','rf_ip','ip_mr','static_world','neutral_sampled'} else _artifact_record(source,'downstream_audit'),
            native_sources=sources)
        from .terminal_evidence import append_terminal_recorder
        controls['program'] = append_terminal_recorder(controls['program'],
            recorder_source=Path(frozen['native_terminal_recording.lua']['path']).read_text(encoding='utf-8'), native_run=key)
        controls['build_metadata']['terminal_evidence'] = dict(schema_version=1, native_run=key)
        row['build_metadata'] = controls['build_metadata']
        batches.append(dict(source_row_range=unit['source_row_range'],expected_particle_ids=unit['expected_particle_ids'],
                            build_metadata=row['build_metadata']))
        root = session.run_dir if plan['unit_size'] is None else session.run_dir/'units'/key
        native_plan = plan_tracking_workbench(compiled,field_design=design,components_resolved=require_prepared_model(model)['components_resolved'],
            carriers=controls['carriers'],response_fields=controls['response_fields'],field_workbench_record=field_workbench,
            run_directory=root,program=controls['program'],native_source_rows=subset['native_source_rows'],
            native_path_resource=session.input_dir/'native_sources/native_run_path.lua',
            ip_mr_admission=ip_mr_admission, neutral_admission=neutral_admission, program_metadata=controls['build_metadata'],
            world_projection=plan.get('scalar_field_basis', {}).get('world_projection'),
            canonical_run_directory=session.canonical_path(root))
        control_records = {}
        for number,(path,text) in enumerate(native_plan.materializations.items(),1):
            name = 'tracking_control_'+str(number) if plan['unit_size'] is None else 'tracking_control__'+key+'_'+str(number)
            control_records[path] = small(name,Path(path),text=text)
        seed_records=[]
        for number,copy_row in enumerate(native_plan.input_copies,1):
            verify_record('tracking structural container',copy_row['source_record'])
            seed_records.append(small('tracking_seed__'+key+'_'+str(number),Path(copy_row['destination']),
                source_path=copy_row['source_record']['path'],retention_role=copy_row['source_record'].get('retention_role','required_evidence')))
        iob = session.declare_file(native_plan.declared_outputs[0],'solver_native_binary')
        for generated in native_plan.declared_outputs[1:]:
            session.declare_file(generated,'solver_native_binary')
        spec_name = ('tracking_world_iob.lua' if plan.get('scalar_field_basis', {}).get('role') == 'split_off_on_scalar_binding'
                     else 'tracking_iob.lua')
        control_guards = [control_records[str(root/'inputs'/spec_name)]]
        if plan['flight'].get('tracking_kind') in {'ip_mr', 'neutral_sampled'}:
            control_guards.append(control_records[str(root/'inputs/sampled_basis.json')])
        immutable = _unique_inputs([*borrowed,*controls['immutable_input_records'],*seed_records,*frozen.values(),native_path,*control_guards])
        for operation,name in zip(native_plan.operations,unit['operation_ids'][:2],strict=True):
            arguments = [str(session.input_dir/'native_sources'/Path(value).name)
                         if Path(value).name in resource_names else value for value in operation['arguments']]
            argv = apply_native_io_mode([str(session.context.tools['simion']),*arguments],allow_asynchronous_io=allow_asynchronous_io)
            session.run_process(name,executable=session.context.tools['simion'],arguments=argv[1:],role='SIMION',stage='prepare',
                limits=limits,immutable_input_records=immutable)
            native_calls += 1
            ordinal = session.expected_operation_ids.index(name)+1
            stdout = session.log_dir/f'operation_{ordinal:04d}.stdout.log'
            if operation['success_marker'].encode() not in stdout.read_bytes():
                raise ValueError('tracking workbench completion marker is absent')
            for record in control_records.values(): verify_record('unchanged tracking control',record)
            if name==unit['operation_ids'][0]:
                iob_record = file_record(session.canonical_path(iob),'solver_native_binary')
                records['tracking_workbench__'+key] = iob_record
                immutable = _unique_inputs([*immutable,*control_records.values(),iob_record])
        name = unit['operation_ids'][2]
        ordinal = session.expected_operation_ids.index(name)+1
        row['stdout_record'] = dict(path=str(session.canonical_path(session.log_dir/f'operation_{ordinal:04d}.stdout.log')))
        row['process_record'] = dict(path=str(session.canonical_path(session.log_dir/f'operation_{ordinal:04d}.process.json')))
        prepared.append((unit,row,control_records,immutable,stdout_key))
        # declare_file returns the canonical manifest path. The saved IOB's
        # relative PA references were built/reopened at the execution alias.
        fly_argv = apply_native_io_mode([str(session.context.tools['simion']),'--nogui','--noprompt',
            'fly','--retain-trajectories','0',str(native_plan.declared_outputs[0])],allow_asynchronous_io=allow_asynchronous_io)
        fly_specs.append(dict(operation_id=name,executable=session.context.tools['simion'],
            arguments=fly_argv[1:],scheduler_batch=unit['scheduler_batch']))
        write_json_atomic(index_path,index)
    small('native_controls',session.input_dir/'native_controls.json',
        value=dict(flight=plan['flight'],batches=batches,stdout_data_keys=stdout_keys))
    primary = None
    try:
        if fly_specs:
            if plan['unit_size'] is None:
                spec = fly_specs[0]
                session.run_process(spec['operation_id'],executable=spec['executable'],arguments=spec['arguments'],
                    role='SIMION',stage='flight',limits=limits,immutable_input_records=prepared[0][3])
                native_calls += 1
            else:
                request = dict(solver='SIMION',field_kind='rf' if 'rf_steps_per_period' in plan['numerics'] else 'electrostatic',
                    particle_count=len(plan['rows']),independent_particles=True,
                    case_input_sha256=index['applicability_sha256'],trajectory_quality=plan['numerics']['trajectory_quality'],
                    rf_steps_per_period=plan['numerics'].get('rf_steps_per_period'))
                dispatch = plan_simion_dispatch(request,list(dispatch_profiles))
                fixed = dict(role='simion_single_wave_particle_batch_plan',coverage='complete_population',particle_count=len(plan['rows']),
                    batches=[unit['scheduler_batch'] for unit in plan['units']])
                dispatch = prepare_fixed_partition_dispatch(dispatch,fixed,[unit['index'] for unit, *_ in prepared],profiles=list(dispatch_profiles))
                small('tracking_dispatch',session.input_dir/'tracking_dispatch.json',value=dispatch)
                formal = dispatch['estimation'].get('observed_missing_batch_index')
                formal_id = next((unit['operation_ids'][2] for unit,*_ in prepared if unit['index']==formal),None)
                if dispatch['estimation'].get('kind')!='formal_first_batch_observation':formal_id=None
                receipt = session.run_process_group(fly_specs,dispatch_plan=dispatch,group_id='tracking_fly',role='SIMION',stage='flight',
                    formal_operation_id=formal_id,immutable_input_records=_unique_inputs([record for _,_,_,inputs,_ in prepared for record in inputs]))
                native_calls += len(receipt.get('attempts',receipt['observations']))
    except BaseException as failure:
        primary = failure
        raise
    finally:
        try:
            for unit,row,control_records,_,stdout_key in prepared:
                process_path = Path(row['process_record']['path'])
                if not process_path.is_file():continue
                receipt = json.loads(process_path.read_text(encoding='utf-8-sig'))
                if receipt.get('observation',{}).get('exit_code') != 0:continue
                try:
                    for record in control_records.values():verify_record('unchanged flown tracking control',record)
                    row['stdout_record'] = file_record(Path(row['stdout_record']['path']),'required_evidence')
                    row['process_record'] = file_record(process_path,'required_evidence')
                    _validate_completed_unit(row,plan,unit)
                    row['complete'] = True
                    records[stdout_key] = row['stdout_record']
                except BaseException as secondary:
                    if primary is None:raise
                    primary.add_note(f"Completed sibling evidence rejected: {secondary!r}")
            index['immutable_inputs'] = [record for key,record in records.items()
                if key!='tracking_units' and not key.startswith(('tracking_workbench','native_stdout'))]
            write_json_atomic(index_path,index)
            records['tracking_units'] = file_record(session.canonical_path(index_path),'required_evidence')
        except BaseException as secondary:
            if primary is None:raise
            primary.add_note(f"Tracking unit completion preservation failed: {secondary!r}")
    if not all(row['complete'] for row in index['units']):
        raise ValueError('tracking units lack verified natural native completion')
    collection = collect_tracking_logs([Path(records[key]['path']) for key in stdout_keys],
        source_rows={row['particle_id']:row for row in plan['rows']},source_provenance=plan['source_provenance'],
        flight=plan['flight'],batches=batches)
    observation=plan['observations'].get('native_field_observation')
    if observation is not None:
        def render_unit(unit):
            subset=slice_tracking_plan(plan,unit)
            return _render_tracking_controls(model,subset,field_design=design,stored_bank=stored_bank,
                frontend_records=frontend,downstream_assets=downstream,downstream_receipt=None if plan['flight'].get('tracking_kind') in {'independent_rf','independent_oa','rf_ip','ip_mr','static_world','neutral_sampled'} else _artifact_record(source,'downstream_audit'),
                native_sources=sources)['build_metadata'].get('native_field_observation')
        observed=_collect_unit_field_observation(plan,batches,[Path(records[key]['path']) for key in stdout_keys],render_unit)
        collection['native_field_observation']=observed
        collection['native_field_observation_status']=observed['status']
        collection['native_field_observation_scope']=observed['claim']
    return collection,native_calls


def execute_tracking(session, *, fields_reference, particles, propagation, observations, numerics,
                     limits, source_reference=None, allow_asynchronous_io=None, unit_size=None,
                     recovery_reference=None, dispatch_profiles=(), birth_source_authority=None, hs1_request=None, expected_tracking_applicability=None,
                     scalar_field_basis=None, expected_scalar_basis=None, focus_testplane_record=None) -> dict:
    """Execute one explicit fixed-field cohort through the existing run owner.

    No Refine/GEM2PA/cache transaction occurs. The public observed-process owner
    owns per-operation immutable input guards and confirmed-handle draining.
    """
    import inspect
    import json
    from msplatform.results.artifacts import OpenedArtifact,open_artifact
    from .artifacts import CompiledPreparedModel
    from .field_closure import require_downstream_reuse
    from .field_identity import working_point_member_id
    from .model_execution import _protected_source,_clock_reference

    if 'immutable_input_records' not in inspect.signature(session.run_process).parameters:
        raise ValueError('tracking requires the installed immutable-input observed-process boundary')
    source = fields_reference if isinstance(fields_reference,OpenedArtifact) else open_artifact(fields_reference,expected_kind='field_bundle')
    meta = source.metadata
    if (source.kind!='field_bundle' or meta.get('backend')!='simion' or meta.get('field_status')!='available'
            or meta.get('source_status')!='not_requested'):
        raise ValueError('tracking requires a complete published source-independent SIMION FieldBundle')
    model = CompiledPreparedModel(source.data_path('compiled_model').read_text(encoding='utf-8-sig'))
    document = require_prepared_model(model)
    if meta.get('model_identity_sha256')!=document['model_identity_sha256'] or meta.get('clock')!=document['drive']['clock']:
        raise ValueError('FieldBundle model/clock identity differs')
    geometry_role = model_geometry(model).frontend_geometry.get('role')
    if (geometry_role in {'simion_neutral_world_collision_geometry', 'simion_neutral_multi_domain_collision_geometry'}
            and meta.get('field_representation') not in {'producer_owned_static_world_standalone_operating_pa', 'neutral_sampled_basis_with_collision_geometry', 'neutral_multi_sampled_basis_with_collision_geometry'}):
        raise ValueError('static world tracking requires its published standalone operating field')
    if meta.get('field_representation') in {'neutral_sampled_basis_with_collision_geometry', 'neutral_multi_sampled_basis_with_collision_geometry'}:
        if scalar_field_basis is not None or expected_scalar_basis is not None:
            raise ValueError('neutral sampled field already owns its scalar basis')
        from .rf_tracking_execution import execute_neutral_sampled_tracking
        return execute_neutral_sampled_tracking(session, source=source, model=model, document=document, particles=particles, propagation=propagation, observations=observations, numerics=numerics, limits=limits, source_reference=source_reference, allow_asynchronous_io=allow_asynchronous_io, unit_size=unit_size, recovery_reference=recovery_reference, dispatch_profiles=dispatch_profiles, birth_source_authority=birth_source_authority, hs1_request=hs1_request, expected_tracking_applicability=expected_tracking_applicability)
    sampled_ip_mr = meta.get('field_representation') == 'assembly_sampled_basis_with_collision_geometry'
    if sampled_ip_mr:
        if geometry_role != 'simion_ip_mr_complete_geometry':
            raise ValueError('sampled IP–MR field requires matching complete geometry')
        if scalar_field_basis is not None or expected_scalar_basis is not None:
            raise ValueError('sampled IP–MR field already owns its scalar basis')
        from .rf_tracking_execution import execute_ip_mr_tracking
        return execute_ip_mr_tracking(session,source=source,model=model,document=document,particles=particles,
            propagation=propagation,observations=observations,numerics=numerics,limits=limits,
            source_reference=source_reference,allow_asynchronous_io=allow_asynchronous_io,unit_size=unit_size,
            recovery_reference=recovery_reference,dispatch_profiles=dispatch_profiles,birth_source_authority=birth_source_authority,
            hs1_request=hs1_request,expected_tracking_applicability=expected_tracking_applicability)
    if geometry_role == 'simion_ip_mr_complete_geometry':
        raise ValueError('IP–MR tracking requires its published sampled FieldBundle')
    if geometry_role in {'simion_independent_rf_geometry','simion_independent_oa_geometry','simion_rf_ip_geometry','simion_neutral_world_collision_geometry'}:
        if scalar_field_basis is not None:
            raise ValueError('scalar basis is supported only for SFI tracking')
        from .rf_tracking_execution import execute_rf_tracking
        return execute_rf_tracking(session,source=source,model=model,document=document,particles=particles,
            propagation=propagation,observations=observations,numerics=numerics,limits=limits,
            source_reference=source_reference,allow_asynchronous_io=allow_asynchronous_io,unit_size=unit_size,
            recovery_reference=recovery_reference,dispatch_profiles=dispatch_profiles,birth_source_authority=birth_source_authority,hs1_request=hs1_request,expected_tracking_applicability=expected_tracking_applicability,focus_testplane_record=focus_testplane_record)
    compiled = model_geometry(model,downstream_drive=True)
    geometry = compiled.frontend_geometry
    _,downstream = require_downstream_reuse(source,meta['downstream_identity'])
    if meta.get('ground_representation') != 'analytic_zero_on_native_geometry':
        raise ValueError('OA–TOF tracking requires a derived analytic ground FieldBundle; published PA families cannot be reopened')
    design = json.loads(source.data_path('field_design').read_text(encoding='utf-8-sig'))
    stored_bank = json.loads(source.data_path('field_bank').read_text(encoding='utf-8-sig'))
    expected = {row['domain_id'] for row in design['domains']}
    bindings = meta.get('frontend_members')
    members = {working_point_member_id(row) for row in design['working_points']}
    if not isinstance(bindings,dict) or set(bindings)!=expected or any(set(rows)!=members for rows in bindings.values()):
        raise ValueError('FieldBundle owned frontend member bindings are incomplete')
    frontend = {domain:{member:_artifact_record(source,row['data_key']) for member,row in rows.items()}
                for domain,rows in bindings.items()}
    # Reject accidental old author-path consumption under a relocated resolver.
    for role,asset in downstream.items():
        keys = meta['native_assets'][role]
        for key,record in [(keys['carrier'],asset['carrier_record']),
                           *zip(keys['family'],asset['family_records'],strict=True)]:
            actual = _artifact_record(source,key)
            if Path(actual['path']).resolve()!=Path(record['path']).resolve():
                raise ValueError('native FieldBundle relocation is not qualified by this adapter')
    original_clock = dict(contract=_artifact_record(source,'clock_authority'),authority=_artifact_record(source,'instrument_epoch'))
    original_clock['data_root'] = str(Path(original_clock['contract']['path']).parent)
    relative_epoch = _clock_reference(document,original_clock)
    borrowed = [record for rows in frontend.values() for record in rows.values()]
    borrowed.extend(record for asset in downstream.values() for record in (asset['family_records'] or [asset['carrier_record']]))
    field_workbench = _artifact_record(source,'workbench')
    zero_control = _artifact_record(source,'zero_particle_format_control')
    stem = Path(field_workbench['path']).with_suffix('')
    if Path(zero_control['path']).resolve() != Path(str(stem)+'.fly2').resolve():
        raise ValueError('field workbench zero-particle companion differs from its owned record')
    for suffix in ('.lua','.wgem','.ion','.con','.rec'):
        if Path(str(stem)+suffix).exists():
            raise ValueError('field workbench has an undeclared automatic source/Program companion')
    borrowed.extend((field_workbench,zero_control))
    if meta.get('field_representation') == 'split_scalar_world_with_collision_geometry':
        if scalar_field_basis is None:
            raise ValueError('split scalar world tracking requires its explicit OFF/ON scalar selection')
        _protected_source(session, meta['collision_source_reference']['manifest'],
                          required_paths=[row['path'] for row in borrowed if row not in (field_workbench, zero_control)])
        borrowed.extend((_artifact_record(source, 'background'), _artifact_record(source, 'world_binding')))
    _protected_source(session,source.reference['manifest'],required_paths=[row['path'] for row in borrowed])
    return _execute_tracking_bound_source(session,source=source,model=model,document=document,compiled=compiled,
        geometry=geometry,design=design,stored_bank=stored_bank,frontend=frontend,downstream=downstream,
        field_workbench=field_workbench,borrowed=borrowed,original_clock=original_clock,relative_epoch=relative_epoch,
        particles=particles,propagation=propagation,observations=observations,numerics=numerics,limits=limits,
        source_reference=source_reference,allow_asynchronous_io=allow_asynchronous_io,unit_size=unit_size,
        recovery_reference=recovery_reference,dispatch_profiles=dispatch_profiles,birth_source_authority=birth_source_authority,hs1_request=hs1_request,expected_tracking_applicability=expected_tracking_applicability,
        scalar_field_basis=scalar_field_basis,expected_scalar_basis=expected_scalar_basis)


def _publish_split_particle_data(session, plan, collection, geometry, document, executable_identity, records, *, recovery=None):
    from msplatform.io.manifest_records import file_record
    from msplatform.physics import CONSTANTS
    from msplatform.results.particle_data import read_particle_data, write_particle_data
    from .particle_data import adapt_native_results
    if plan['expected_operation_ids']:
        version = windows_binary_version(session.context.tools.get('simion'))
        binary = file_record(Path(session.context.tools['simion']), 'solver_native_binary')
        if executable_identity != {key: binary[key] for key in ('bytes', 'sha256')}:
            raise ValueError('SIMION version evidence does not match the tracked native binary')
    else:
        # Whole-unit recovery authenticates the predecessor manifest and index.
        # An interrupted predecessor may have no completed product/version.
        product = recovery.get('manifest', {}).get('products', {}).get('trajectory', {}) if recovery else {}
        candidate = product.get('metadata', {}).get('backend_version') if product.get('status') == 'complete' else None
        previous = recovery.get('index', {}).get('native_executable_identity') if recovery else None
        if (previous is None or previous != executable_identity or not isinstance(candidate, str)
                or not candidate.strip() or candidate.strip().lower() == 'unavailable'):
            raise ValueError('complete tracking reuse requires authenticated predecessor SIMION version and binary identity')
        version = candidate
    definitions = plan['observations'].get('plane_observations', [])
    focus = plan['flight'].get('oa_focus_runtime') is not None
    bindings = {row['observation_id']: dict(component_id=row['source_instance_id'],
                surface_id=row['observation_id'] if focus else row['surface_id'], electrode_id=None,
                kind='observation' if focus else 'detector') for row in definitions}
    result = adapt_native_results({row['particle_id']: row for row in plan['rows']}, collection,
        backend_version=version, observation_bindings=bindings,
        observation_times_us=plan['observations'].get('observation_times_us', []), constants=CONSTANTS,
        detector_instance=plan['flight'].get('detector_instance'))
    directory = session.result_dir/'particle_data'
    directory.mkdir(parents=True, exist_ok=True)
    names = ('initial_states.parquet', 'terminal_states.parquet', 'events.parquet', 'trajectories.h5', 'execution.json')
    declared = {name: session.declare_file(directory/name, 'required_evidence') for name in names}
    drive_clock = document['drive']['clock']
    scientific_clock = dict(basis='experiment_relative', unit='s', clock_epoch_id=drive_clock['clock_epoch_id'],
                            authority_sha256=drive_clock['authority_sha256'])
    write_particle_data(directory, result, metadata=dict(schema_version=2, initial_state_basis='native_birth_verified',
                        frame_id=geometry['native_frame_id'], clock=scientific_clock, species=plan['species']))
    read_particle_data(directory)
    for name, path in declared.items():
        records['particle_data_'+name.replace('.', '_')] = file_record(session.canonical_path(path), 'required_evidence')
    return result, version


def _execute_tracking_bound_source(session,*,source,model,document,compiled,geometry,design,stored_bank,
        frontend,downstream,field_workbench,borrowed,original_clock,relative_epoch,particles,propagation,observations,
        numerics,limits,source_reference,allow_asynchronous_io,unit_size,recovery_reference,dispatch_profiles,birth_source_authority=None,hs1_request=None,expected_tracking_applicability=None,
        scalar_field_basis=None,expected_scalar_basis=None,ip_mr_admission=None,neutral_admission=None,focus_testplane_record=None):
    """The same unit runner and result publisher for verified TOF/RF source bindings."""
    import json
    from dataclasses import asdict
    from msplatform.execution.inputs import freeze_file
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.resources import resource_path
    from .model_execution import _protected_source,_clock_reference
    from .resources import native_resource_path
    records = {}

    def small(name, target, *, value=None, source_path=None, text=None, content=None, retention_role='required_evidence'):
        target = session.declare_file(target,retention_role)
        target.parent.mkdir(parents=True,exist_ok=True)
        if source_path is not None:
            record = freeze_file(Path(source_path),target,retention_role=retention_role)
        elif content is not None:
            with target.open('xb') as stream:
                stream.write(content)
            record = file_record(session.canonical_path(target),retention_role)
        else:
            payload = text if text is not None else json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
            with target.open('x',encoding='utf-8',newline='\n') as stream: stream.write(payload)
            record = file_record(session.canonical_path(target),retention_role)
        record.pop('source_path', None)
        session.add_input(name,record)
        records[name] = record
        return record

    neutral_code_guards = []
    if neutral_admission is not None:
        from . import rf_tracking_execution, rf_tracking_program, rf_tracking_collection, tracking_units, tracking_collection
        from .neutral_sampled_field import neutral_source_paths
        from msplatform.io.manifest_records import verify_record
        modules = neutral_source_paths(model)
        modules.update({module.__name__: Path(module.__file__).resolve(strict=True) for module in
            (rf_tracking_execution, rf_tracking_program, rf_tracking_collection, tracking_units, tracking_collection)})
        for module_name, path in modules.items():
            original = file_record(path, 'required_evidence')
            if module_name in neutral_admission['code_records'] and any(
                    original[key] != neutral_admission['code_records'][module_name][key] for key in ('bytes', 'sha256')):
                raise ValueError('neutral tracking source changed since admission: '+module_name)
            name = module_name.replace('.', '_')
            copied = small('neutral_tracking_code_'+name,
                session.input_dir/'native_sources'/(name+'.py'), source_path=path)
            verify_record('neutral tracking original source after freezing', original)
            if any(original[k] != copied[k] for k in ('bytes', 'sha256')):
                raise ValueError('neutral tracking source copy differs: '+name)
            neutral_code_guards.extend((original, copied))
        borrowed = [*borrowed, *neutral_code_guards]
    clocks = dict(clock_authority=small('clock_authority',session.input_dir/'clock/clock_authority.json',source_path=original_clock['contract']['path']),
        instrument_epoch=small('instrument_epoch',session.input_dir/'clock'/relative_epoch,source_path=original_clock['authority']['path']))
    _clock_reference(document,dict(contract=clocks['clock_authority'],authority=clocks['instrument_epoch'],data_root=str(session.input_dir/'clock')))
    if observations.get('oa_focus_authority') is not None:
        from msplatform.io.manifest_records import verify_record
        executable = Path(session.context.tools['simion']).resolve(strict=True)
        expected_library = (executable.parent/'examples/test_plane/testplanelib.lua').resolve(strict=True)
        if not isinstance(focus_testplane_record, Mapping) or Path(focus_testplane_record['path']).resolve(strict=True) != expected_library:
            raise ValueError('OA focus TestPlane must come from the selected SIMION installation')
        verify_record('OA focus TestPlane',dict(focus_testplane_record))
        for name,record in [('testplanelib',focus_testplane_record),
                            ('focus_campaign',observations['oa_focus_authority']['campaign']),
                            ('focus_component_contract',observations['oa_focus_authority']['component_contract'])]:
            copied=small('focus_'+name,session.input_dir/'native_sources'/(name+('.lua' if name=='testplanelib' else '.json')),source_path=record['path'])
            if any(copied[k]!=record[k] for k in ('bytes','sha256')):
                raise ValueError('OA focus frozen authority differs: '+name)
            verify_record('OA focus source after freezing',dict(record))
            borrowed.extend([dict(record),copied])
        for name in ('oa_focus_model_projection.py','oa_focus_plan.py'):
            original=file_record(Path(__file__).with_name(name).resolve(strict=True),'required_evidence')
            copied=small('focus_code_'+name,session.input_dir/'native_sources'/name,source_path=original['path'])
            if any(original[k]!=copied[k] for k in ('bytes','sha256')):
                raise ValueError('OA focus validation code changed while freezing')
            verify_record('OA focus validation code',original)
            borrowed.extend([original,copied])
    plan = plan_tracking_execution(model,particles=particles,clock_records=clocks,propagation=propagation,observations=observations,
        numerics=numerics,unit_size=unit_size,field_manifest_record=source.reference['manifest'],
        field_product_id=source.reference['product_id'],
        birth_source_authority=birth_source_authority,hs1_request=hs1_request,focus_testplane_record=focus_testplane_record,
        **({'ip_mr_field_reference':source.reference} if ip_mr_admission is not None else {}),
        **({'neutral_sampled_field_reference':source.reference} if neutral_admission is not None else {}))
    if plan['observations'].get('pulse_discovery') is not None:
        from msplatform.io.manifest_records import verify_record
        selector_path = Path(__file__).resolve().parents[2] / 'analysis' / 'pulse_selection.py'
        selector_original = file_record(selector_path, 'required_evidence')
        selector_copy = small('discovery_selector', session.input_dir/'native_sources'/'pulse_selection.py',
                              source_path=selector_path)
        verify_record('discovery selector source after freezing', selector_original)
        if any(selector_original[k] != selector_copy[k] for k in ('bytes', 'sha256')):
            raise ValueError('discovery selector source changed while freezing')
        borrowed = [*borrowed, selector_original, selector_copy]
    if plan.get('discovery_resolution') is not None:
        from msplatform.results.artifacts import open_artifact
        from .model_execution import _protected_source
        pilot = open_artifact(plan['observations']['pulse_discovery']['pilot'], expected_kind='trajectory_result')
        _protected_source(session, pilot.reference['manifest'], required_paths=[
            str(pilot.data_path(key)) for key in ('collection', 'observations', 'compiled_model', 'source_provenance')])
        checked = resolve_discovery_selection(plan['observations']['pulse_discovery'], model,
            field_manifest_record=source.reference['manifest'], field_product_id=source.reference['product_id'],
            provenance=plan['source_provenance'])
        if checked != plan['discovery_resolution']:
            raise ValueError('discovery pilot changed during tracking admission')
    if neutral_admission is not None and plan['scalar_field_basis'] != neutral_admission['basis']:
        raise ValueError('neutral sampled field admission changed after planning')
    if ip_mr_admission is not None:
        if plan['scalar_field_basis'] != ip_mr_admission['basis'] or plan['collision_priority'] != ip_mr_admission['priority']:
            raise ValueError('sampled IP–MR admission changed after planning')
        from .ip_mr_tracking_admission import protect_ip_mr_tracking_fields
        protect_ip_mr_tracking_fields(session,ip_mr_admission)
    if scalar_field_basis is not None:
        from .model_execution import _protected_source
        from msplatform.io.manifest_records import verify_record
        admitted = _resolve_scalar_basis(source, model, plan, scalar_field_basis)
        if admitted != expected_scalar_basis:
            raise ValueError('selected scalar basis changed after planning')
        plan['scalar_field_basis'] = admitted
        from .neutral_sampled_field import protect_neutral_records
        references = [admitted['geometry_reference']]
        protected = [admitted['geometry_execution_request']]
        for item in admitted['bases'].values():
            for level in [item, *item.get('refinement_windows', [])]:
                references.extend((level['reference'], level['field_solution_reference']))
                if level.get('original_samples_reference') is not None:
                    references.append(level['original_samples_reference'])
                protected.extend(level['records'].values())
        from msplatform.execution.owner import current_managed_native_store
        if current_managed_native_store() is None:
            _protected_source(session, admitted['geometry_reference']['manifest'],
                              required_paths=[admitted['geometry_execution_request']['path']])
            for item in admitted['bases'].values():
                for level in [item, *item.get('refinement_windows', [])]:
                    _protected_source(session, level['reference']['manifest'],
                                      required_paths=[record['path'] for record in level['records'].values()])
                    _protected_source(session, level['field_solution_reference']['manifest'])
        else:
            protect_neutral_records(session, references, protected)
        for name, item in admitted['bases'].items():
            for index, level in enumerate([item, *item.get('refinement_windows', [])]):
                for key, record in level['records'].items():
                    verify_record('selected scalar ' + name + ' ' + key, record)
                    session.add_input('scalar_' + name + ('_window_' + str(index) if index else '') + '_' + key, record)
        small('scalar_field_basis', session.input_dir/'scalar_field_basis.json', value=admitted)
    if birth_source_authority is not None:
        authority = validate_birth_authority(birth_source_authority, particles)
        _protected_source(session, authority['manifest'], required_paths=[record['path'] for record in authority['records'].values()])
        frozen_manifest = small('birth_authority_manifest', session.input_dir/'birth_authority/manifest.json', source_path=authority['manifest']['path'])
        if (frozen_manifest['bytes'] != authority['manifest']['bytes']
                or frozen_manifest['sha256'].upper() != authority['manifest']['sha256'].upper()):
            raise ValueError('frozen birth authority manifest differs from selected input')
        for index, record in enumerate(authority['records'].values(), 1):
            if record['path'] == particles['recorded_source']['record']['path']:
                continue  # The existing recorded-source freeze below owns this copy.
            frozen = small(f'birth_authority_{index:04d}', session.input_dir/f'birth_authority/input_{index:04d}', source_path=record['path'])
            if frozen['bytes'] != record['bytes'] or frozen['sha256'].upper() != record['sha256'].upper():
                raise ValueError('frozen birth authority differs from selected input')
    if isinstance(particles, Mapping) and particles.get('role') == 'canonical_recorded_birth_realization':
        from msplatform.io.manifest_records import verify_record
        selected = particles['recorded_source']['record']
        frozen_source = small('recorded_birth_source', session.input_dir/'recorded_birth_source.csv',
                              source_path=selected['path'])
        verify_record('recorded birth source after freezing', selected)
        if (frozen_source['bytes'] != selected['bytes']
                or frozen_source['sha256'].upper() != selected['sha256'].upper()):
            raise ValueError('frozen recorded birth source differs from selected source')
    hs1_frozen = {}
    if plan['flight'].get('tracking_kind') in {'rf_ip','ip_mr'} or plan['flight'].get('has_hs1'):
        from .rf_tracking_execution import prepare_rf_ip_hs1, prepare_ip_mr_hs1, prepare_neutral_ip_hs1
        from msplatform.io.manifest_records import verify_record
        if plan['flight']['tracking_kind'] == 'ip_mr':
            if ip_mr_admission is None:
                raise ValueError('verified sampled IP–MR admission required')
            selected_hs1 = prepare_ip_mr_hs1(model, hs1_request, common_world_domain=ip_mr_admission['world_domain'],
                common_world_frame_id=ip_mr_admission['world_frame_id'])
        elif plan['flight'].get('has_hs1'):
            selected_hs1 = prepare_neutral_ip_hs1(model, hs1_request, basis=neutral_admission['basis'])
        else:
            selected_hs1 = prepare_rf_ip_hs1(model, hs1_request)
        if selected_hs1['identity'] != plan['hs1_identity']:
            raise ValueError('RF-IP HS1 inputs changed after planning')
        environment_bytes = selected_hs1['environment_bytes']
        if not isinstance(environment_bytes, bytes):
            raise ValueError('HS1 gas environment must preserve its author bytes')
        import hashlib
        environment_sha = hashlib.sha256(environment_bytes).hexdigest()
        if environment_sha.lower() != plan['hs1_identity']['environment_author_sha256'].lower():
            raise ValueError('HS1 gas environment bytes differ from planned identity')
        frozen_environment = small('hs1_gas_environment', session.input_dir/'hs1/gas_environment.json',
                                   content=environment_bytes)
        if frozen_environment['sha256'].lower() != environment_sha.lower():
            raise ValueError('frozen HS1 gas environment differs from its author bytes')
        hs1_frozen['gas_environment'] = frozen_environment
        vendor = selected_hs1['vendor_record']
        verify_record('selected original HS1 before freeze', vendor)
        original = small('hs1_vendor_original', session.input_dir/'hs1/original.lua', source_path=vendor['path'])
        verify_record('selected original HS1 after freeze', vendor)
        if (original['bytes'], original['sha256'].upper()) != (vendor['bytes'], vendor['sha256'].upper()):
            raise ValueError('frozen original HS1 differs from selected input')
        hs1_frozen['hs1_original'] = original
        for name, value in (('vendor', selected_hs1['vendor_adapted']),
                            ('bath', selected_hs1['bath_runtime']), ('outer', selected_hs1['outer_runtime'])):
            hs1_frozen[name] = small('hs1_'+name, session.input_dir/('hs1/'+name+'.lua'), text=value)
        plan['hs1'] = dict(vendor_path=str(session.input_dir/'hs1/vendor.lua'), bath_path=str(session.input_dir/'hs1/bath.lua'),
                           outer_path=str(session.input_dir/'hs1/outer.lua'), query_frame_id=selected_hs1['query_frame_id'],
                           numerics=selected_hs1['identity']['numerics'])
        expected = {'vendor': 'vendor_adapted_sha256', 'bath': 'bath_runtime_sha256', 'outer': 'outer_runtime_sha256'}
        for name, identity_key in expected.items():
            if hs1_frozen[name]['sha256'].lower() != plan['hs1_identity'][identity_key].lower():
                raise ValueError('frozen RF-IP HS1 runtime differs from its planned identity')
        hs1_frozen['identity'] = small('hs1_identity', session.input_dir/'hs1/identity.json', value=plan['hs1_identity'])
    recovery = None
    if recovery_reference is not None:
        from .tracking_units import prepare_tracking_recovery,partition_tracking_units
        from msplatform.execution.owner import current_managed_native_store
        scope = current_managed_native_store()
        if scope is not None:
            from msplatform.execution.native_source_guard import guard_tracking_recovery
            scope['lifetime'].enter_context(guard_tracking_recovery(scope['store'], recovery_reference,
                raw_root=session.context.workspace/'artifacts'))
        recovery,replay = prepare_tracking_recovery(plan,recovery_reference,output_dir=session.result_dir/'recovery')
        if scope is None:
            _protected_source(session,recovery_reference,required_paths=[recovery['index_path'],
                *[row[name]['path'] for row in recovery['index']['units'] if row['complete'] for name in ('stdout_record','process_record')]])
        replay_path = session.declare_file(session.result_dir/'recovery/simion_whole_unit_replay_plan.json','required_evidence')
        records['recovery_plan'] = file_record(session.canonical_path(replay_path),'required_evidence')
        session.add_input('recovery_plan',records['recovery_plan'])
        plan.update(partition_tracking_units(plan,unit_size=unit_size,reused_unit_keys=recovery['reused_unit_keys']))
    if expected_tracking_applicability is not None:
        from .tracking_units import tracking_applicability
        if tracking_applicability(plan) != expected_tracking_applicability:
            raise ValueError('RF-IP tracking scientific inputs or renderer resources changed after planning')
    if tuple(plan['expected_operation_ids'])!=session.expected_operation_ids or dict(plan['operation_dependencies'])!=dict(session.operation_dependencies):
        raise ValueError('tracking graph differs from the admitted owner operations')
    from .tracking_units import require_tracking_executable_identity
    executable_identity = require_tracking_executable_identity(plan,recovery,session.context.tools.get('simion'))
    parent_source = None
    if isinstance(particles,HandoffResult):
        parent_source = _verified_handoff_source(session,source_reference,particles,plan,geometry)
    elif source_reference is not None:
        raise ValueError('new birth realization cannot claim a handoff producer reference')
    small('field_reference',session.input_dir/'field_reference.json',value=source.reference)
    small('compiled_model',session.input_dir/'compiled_model.json',source_path=source.data_path('compiled_model'))
    small('source_realization',session.input_dir/'source_realization.json',value=asdict(particles) if isinstance(particles,HandoffResult) else particles)
    small('canonical_source_states',session.input_dir/'canonical_source_states.json',value=plan['rows'])
    small('source_provenance',session.input_dir/'source_provenance.json',value=plan['source_provenance'])
    small('propagation',session.input_dir/'propagation.json',value=plan['propagation'])
    small('observations',session.input_dir/'observations.json',value=plan['observations'])
    small('tracking_numerics',session.input_dir/'tracking_numerics.json',value=plan['numerics'])
    if plan['flight'].get('tracking_kind') in {'independent_rf','independent_oa','rf_ip','ip_mr','static_world','neutral_sampled'}:
        import inspect
        from . import rf_tracking_execution,rf_tracking_program,rf_tracking_collection
        for module in (rf_tracking_execution,rf_tracking_program,rf_tracking_collection):
            small('rf_source_'+module.__name__.rsplit('.',1)[-1],session.input_dir/'native_sources'/Path(module.__file__).name,
                source_path=Path(inspect.getsourcefile(module)))
    if parent_source is not None:
        small('source_reference',session.input_dir/'source_reference.json',value=parent_source.reference)
    output = session.declare_file(session.result_dir/'collection.json','required_evidence')
    output.parent.mkdir(parents=True,exist_ok=True)
    if not plan['rows']:
        collection = dict(schema_version=1,role='simion_tracking_collection',native_complete=None,
            execution_status='not_requested_zero_handoff',native_calls=0,canonical_events=[],native_terminals=[],
            original_mother={key:plan['source_provenance'][key] for key in
                ('mother_particle_ids','mother_records','mother_fates','clock_authority_sha256','clock_records')})
    else:
        resource_names = ('build_tracking_iob.lua','iob_core.lua','oatof_analyzer_component.lua',
            'single_flight_pulse_hook.lua','single_flight_frontend_hook.lua','rf_drive.lua','voltage_waveforms.lua')
        if plan['flight'].get('tracking_kind') in {'independent_rf','independent_oa','rf_ip','ip_mr','static_world','neutral_sampled'}:
            resource_names=('build_tracking_iob.lua','iob_core.lua','model_drive.lua','rf_drive.lua','rf_tracking.lua')
            if plan['flight']['tracking_kind'] in {'independent_oa','neutral_sampled'}:resource_names+=('single_flight_pulse_hook.lua','voltage_waveforms.lua')
            if plan['flight']['tracking_kind'] in {'rf_ip','ip_mr'}:resource_names+=('single_flight_pulse_hook.lua','voltage_waveforms.lua','native_drive.lua','collision_hs1_gas.lua','rf_ip_gas_selection.lua','rf_ip_tracking_hs1.lua')
            if plan['flight'].get('has_ip_schedule'):resource_names+=('native_drive.lua',)
            if plan['flight'].get('has_hs1'):resource_names+=('collision_hs1_gas.lua','rf_ip_gas_selection.lua','rf_ip_tracking_hs1.lua')
        if plan.get('scalar_field_basis') is not None:
            scalar_composer = ('split_scalar_field.lua' if plan['scalar_field_basis'].get('role') == 'split_off_on_scalar_binding'
                else 'generic_scalar_field.lua' if plan['flight'].get('tracking_kind') in {'ip_mr', 'neutral_sampled'} else 'sfi_scalar_field.lua')
            resource_names += ('scalar_field_adapter.lua', scalar_composer)
        if plan['flight'].get('oa_focus_runtime') is not None:
            resource_names += ('oa_focus_observer.lua',)
        resource_names += ('native_terminal_recording.lua',)
        frozen = {}
        for name in resource_names:
            frozen[name] = small('resource_'+name,session.input_dir/'native_sources'/name,source_path=native_resource_path(name))
        frozen.update(hs1_frozen)
        native_path = small('resource_native_run_path.lua',session.input_dir/'native_sources/native_run_path.lua',source_path=resource_path('native_run_path.lua'))
        if plan['flight'].get('tracking_kind') in {'independent_rf','independent_oa','rf_ip','ip_mr','static_world','neutral_sampled'}:
            sources={name:Path(frozen[name]['path']).read_text(encoding='utf-8-sig') for name in resource_names if name not in {'build_tracking_iob.lua','iob_core.lua'}}
        else:
            names = dict(analyzer_component_source='oatof_analyzer_component.lua',pulse_hook_source='single_flight_pulse_hook.lua',
                frontend_hook_source='single_flight_frontend_hook.lua',rf_drive_kernel_source='rf_drive.lua',voltage_waveforms_source='voltage_waveforms.lua')
            sources = {key:Path(frozen[value]['path']).read_text(encoding='utf-8-sig') for key,value in names.items()}
        if plan.get('scalar_field_basis') is not None and plan['flight'].get('tracking_kind') not in {'ip_mr', 'neutral_sampled'}:
            sources['scalar_adapter_source'] = Path(frozen['scalar_field_adapter.lua']['path']).read_text(encoding='utf-8-sig')
            sources['scalar_composer_source'] = Path(frozen[scalar_composer]['path']).read_text(encoding='utf-8-sig')
        sources['native_path_source'] = Path(native_path['path']).read_text(encoding='utf-8-sig')
        collection,native_calls = _execute_tracking_units(session,model=model,plan=plan,design=design,
            stored_bank=stored_bank,frontend=frontend,downstream=downstream,source=source,
            compiled=compiled,field_workbench=field_workbench,borrowed=borrowed,frozen=frozen,
            native_path=native_path,sources=sources,resource_names=resource_names,small=small,
            records=records,limits=limits,allow_asynchronous_io=allow_asynchronous_io,
            recovery=recovery,dispatch_profiles=dispatch_profiles,executable_identity=executable_identity,ip_mr_admission=ip_mr_admission,neutral_admission=neutral_admission)
    if neutral_code_guards:
        from msplatform.io.manifest_records import verify_record
        for record in neutral_code_guards:
            verify_record('neutral tracking source before publication', record)
    collection.update(schema_version=1,role='simion_tracking_collection',clock_epoch_id=document['drive']['clock']['clock_epoch_id'],
        field_reference=source.reference,model_identity_sha256=document['model_identity_sha256'],
        source_provenance_record=records['source_provenance'],propagation=plan['propagation'],
        execution_profile=plan['execution_profile'],native_calls=native_calls if plan['rows'] else 0,
        requested_allow_asynchronous_io_for_iob=allow_asynchronous_io,
        # Existing scheduled headless policy, not sim_trajectory_image_control=0.
        fly_trajectory_retention=dict(requested=False,mechanism='native_cli_--retain-trajectories_0'),
        fly_io_mode_override=dict(requested=allow_asynchronous_io,
            mechanism='not_requested' if allow_asynchronous_io is None else 'pre_command_lua',
            verification='actual_native_stdout_readback_only_not_inferred_from_request',
            phase='before_fly_command_not_after_iob_load',
            stdout_data_keys=[key for key in records if key=='native_stdout' or key.startswith('native_stdout__')]))
    if plan['observations'].get('pulse_discovery') is not None:
        collection['pulse_discovery'] = copy.deepcopy(plan['observations']['pulse_discovery'])
        collection['effective_flight'] = copy.deepcopy(plan['flight'])
        if plan.get('discovery_resolution') is not None:
            collection['discovery_resolution'] = copy.deepcopy(plan['discovery_resolution'])
    publish_rf_ip = (plan['flight'].get('tracking_kind') == 'rf_ip'
                     and plan['flight'].get('original_birth_si') is True)
    publish_focus = plan['flight'].get('oa_focus_runtime') is not None
    if plan['flight'].get('tracking_kind') in {'split_oa_tof', 'neutral_sampled'} or publish_rf_ip or publish_focus:
        if plan['flight']['tracking_kind'] == 'neutral_sampled' or publish_rf_ip or publish_focus:
            if not publish_focus and plan['observations'].get('plane_observations'):
                raise ValueError('this SI publication currently requires no plane observations')
            provenance = plan['source_provenance']
            ids = [row['particle_id'] for row in plan['rows']]
            if (provenance.get('state_kind') != 'source_birth'
                    or provenance.get('mother_particle_ids') != ids
                    or provenance.get('execution_particle_ids') != ids
                    or [row.get('particle_id') for row in provenance.get('mother_records', [])] != ids):
                raise ValueError('SI publication requires the complete original birth cohort')
        result, version = _publish_split_particle_data(session, plan, collection, geometry, document, executable_identity, records, recovery=recovery)
    if collection.get('terminal_evidence',{}).get('status') == 'recorded_v1':
        from .terminal_evidence import render_terminal_6d_rec
        terminal_rec = session.declare_file(session.result_dir/'terminal-6d.rec','required_evidence')
        with terminal_rec.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(render_terminal_6d_rec(collection['terminal_evidence']))
        records['terminal_6d_rec'] = file_record(session.canonical_path(terminal_rec),'required_evidence')
    with output.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(collection,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
    records['collection'] = file_record(session.canonical_path(output),'required_evidence')
    # PA/IOB execution dependencies are deliberately not mandatory analysis data.
    data = {key:record for key,record in records.items() if not key.startswith('tracking_workbench') and not key.startswith('resource_')}
    paths = [Path(record['path']) for record in records.values()]
    metadata = dict(backend='simion',model_identity_sha256=document['model_identity_sha256'],clock=document['drive']['clock'],
        execution_profile=plan['execution_profile'],execution_count=len(plan['rows']),mother_count=len(plan['source_provenance']['mother_records']),
        native_calls=collection['native_calls'],refine_calls=0,field_recomputed=False,scientific_qualification='not_granted',
        shared_dispatcher_migration='installed',unit_count=len(plan['units']),unit_size=unit_size,
        reused_unit_count=len(recovery['reused_unit_keys']) if recovery else 0)
    if plan['flight'].get('tracking_kind') in {'split_oa_tof', 'neutral_sampled'} or publish_rf_ip or publish_focus:
        metadata.update(particle_data_schema_version=2, particle_data_integrity=result.data_integrity,
                        backend_version=version, backend_version_evidence='producer_verified',
                        frame_id=geometry['native_frame_id'])
    if plan['flight'].get('tracking_kind') == 'neutral_sampled':
        metadata.update(tracking_kind='neutral_sampled', field_domain_coupling='external_sampled_field')
    if plan['flight'].get('tracking_kind')=='independent_oa':
        metadata.update(component_kind='orthogonal_accelerator',tracking_kind='independent_oa',field_domain_coupling='independent_component_domains',native_state_wire_format='legacy_shared_RF_NATIVE_STATE_V1')
    if plan['flight'].get('tracking_kind')=='rf_ip':
        metadata.update(tracking_kind='rf_ip',collision_model='hs1',field_domain_coupling='monolithic_joint_solve',native_state_wire_format='legacy_shared_RF_NATIVE_STATE_V1')
    return dict(status='success',summary=metadata,output_paths=paths,required_output_paths=paths,retention_preserve_paths=[],
        manifest_extra_fields={'products':{'trajectory':dict(schema_version=1,kind='trajectory_result',status='complete',metadata=metadata,data=data)}})
