"""Compile frozen COMSOL native study inputs without launching a solver."""
from __future__ import annotations

import copy
import math
from typing import Any

from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.comsol.geometry_execution import resolve_geometry_request
from msplatform.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform
from msplatform.physics import CONSTANTS


def compile_comsol_inputs(recipe: dict, instrument: Any, particles: Any) -> dict:
    """Resolve one real source batch, complete field requests and pulse timing.

    This validates compilation only; geometry, mesh, field and CPT execution and
    scientific accuracy remain distinct native evidence requirements.
    """
    study = recipe['study']['document']
    if study['physics']['boundary_policy'] != 'comsol_finite_exterior_potential':
        raise ValueError('COMSOL requires explicit finite exterior potential boundary policy')
    if study['physics']['field_model'] != 'external_electrostatic_linear':
        raise ValueError('COMSOL requires the linear external electrostatic field model')
    geometry = study['numerics']['geometry']
    if set(geometry) != {'outer_box_mm', 'geometry_validation'}:
        raise ValueError('COMSOL requires explicit outer box and geometry validation')
    projection = resolve_geometry_request(instrument, **geometry)['projection']
    fields = study['numerics']['fields']
    if set(fields) != {'relative_permittivity', 'exterior', 'mesh'}:
        raise ValueError('COMSOL requires explicit permittivity, exterior and mesh')
    if fields['exterior'].get('kind') != 'potential':
        raise ValueError('COMSOL finite exterior requires an explicit potential')
    drive = study['drive']
    pulse = drive['pulse']
    if set(pulse) != {'mode', 'time_us', 'width_us'} or pulse['mode'] != 'timed':
        raise ValueError('COMSOL currently requires an explicit timed pulse')
    on, width = pulse['time_us'], pulse['width_us']
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (on, width)) or width <= 0:
        raise ValueError('COMSOL pulse time and width must be finite and ordered')
    voltages = {'off': [], 'on': []}
    pulse_groups = []
    for instance, groups in drive['groups'].items():
        for group, value in groups.items():
            kind = value.get('kind')
            if kind == 'static' and set(value) == {'kind', 'voltage_v'}:
                low = high = value['voltage_v']
            elif kind == 'pulse' and set(value) == {'kind', 'off_voltage_v', 'on_voltage_v'}:
                low, high = value['off_voltage_v'], value['on_voltage_v']
                if low != 0:
                    raise ValueError('COMSOL pulse OFF voltages must be zero')
                pulse_groups.append({'instance_id': instance, 'electrode_group_id': group})
            else:
                raise ValueError('unsupported COMSOL electrode drive')
            for state, voltage in (('off', low), ('on', high)):
                voltages[state].append({'instance_id': instance, 'electrode_group_id': group, 'voltage_v': voltage})
    if not pulse_groups:
        raise ValueError('COMSOL requires explicit pulse electrode groups')
    requests = {name: validate_request(projection, {'group_voltages': values, **copy.deepcopy(fields),
                                                    'study': {'kind': 'stationary'}})
                for name, values in voltages.items()}
    rows = copy.deepcopy(particles.to_dict()['rows'])
    if not rows:
        raise ValueError('COMSOL requires original source births')
    if any(type(row['particle_id']) is not int or not 0 < row['particle_id'] <= 2**53 for row in rows):
        raise ValueError('COMSOL JSON particle IDs must be positive integers at most 2**53')
    source_id = rows[0]['source_component_id']
    instances = study['recipe']['instances']
    matches = [instance for instance in instances if instance['instance_id'] == source_id]
    if len(matches) != 1 or any(row['source_component_id'] != source_id for row in rows):
        raise ValueError('COMSOL source batch requires one assembly source instance')
    transform = RigidTransform.from_contract(matches[0]['transform'])
    for row in rows:
        if row['state_event'] != 'source_birth' or row['parent_particle_id'] is not None:
            raise ValueError('COMSOL requires original primary births')
        position = transform.transform_position(FramedPosition(row['frame_id'], tuple(row[f'position_{a}_mm'] for a in 'xyz')))
        velocity = transform.transform_vector(FramedVector(row['frame_id'], tuple(row[f'velocity_{a}_m_s'] for a in 'xyz')))
        row['frame_id'] = position.frame_id
        for axis, value in zip('xyz', position.coordinates_mm, strict=True):
            row[f'position_{axis}_mm'] = value
        for axis, value in zip('xyz', velocity.components, strict=True):
            row[f'velocity_{axis}_m_s'] = value
    if any((r['instrument_time_us'], r['species_id'], r['mass_amu'], r['charge_state'], r['clock_epoch_id']) !=
           (rows[0]['instrument_time_us'], rows[0]['species_id'], rows[0]['mass_amu'], rows[0]['charge_state'], rows[0]['clock_epoch_id']) for r in rows):
        raise ValueError('COMSOL requires one species and common birth time per batch')
    releases = study['release'].get('species_requests', [study['release']])
    selected = [item for item in releases if item['species_id'] == rows[0]['species_id']]
    if len(selected) != 1 or selected[0]['release_spec']['sampling'].get('constants_id') != CONSTANTS['version']:
        raise ValueError('COMSOL source constants version must match the actual birth generator')
    tracing = study['numerics']['tracing']
    validation = tracing['birth_validation']
    if set(validation) != {'position_atol_m', 'velocity_atol_m_s'} or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in validation.values()):
        raise ValueError('COMSOL needs explicit positive SI birth comparison tolerances')
    times = recipe['recording']['observation_times_us']
    end = tracing['end_policy']
    end_time = (rows[0]['instrument_time_us'] + end['maximum_particle_age_us'] if 'maximum_particle_age_us' in end
                else end['absolute_instrument_end_us'])
    if (not isinstance(times, list) or len(times) < 2 or times[0] != rows[0]['instrument_time_us'] or times[-1] != end_time
            or times[-1] <= on + width or on < times[0] or any(type(t) not in (int, float) or not math.isfinite(t) for t in times)
            or any(a >= b for a, b in zip(times, times[1:]))):
        raise ValueError('COMSOL observations must start at birth and end at the declared horizon after pulse')
    return {'geometry': copy.deepcopy(geometry), 'projection': projection, 'requests': requests,
            'pulse_groups': pulse_groups, 'drive': {'on_us': on, 'off_us': on + width},
            'source': {'rows': rows, 'clock': selected[0]['clock'], 'constants_version': CONSTANTS['version'],
                       'species': [item for item in recipe['species']
                                   if item['species_id'] in {row['species_id'] for row in rows}]},
            'numerics': copy.deepcopy(tracing['comsol']), 'birth_validation': copy.deepcopy(validation),
            'observation_times_us': list(times)}


def run_comsol_stages(recipe: dict, instrument: Any, particles: Any, *, context: Any,
                      invoke: Any, stage_cache: Any, implementation: dict,
                      epoch_record: dict) -> tuple[Any, dict]:
    """Run native stages through the caller's existing claims and cache lifecycle.

    ``stage_cache(name, key, kind, produce)`` returns a claimed artifact and
    receipt. Both workpoints are separate products of one protected manifest.
    """
    from msplatform.backends.comsol.assembly_electrostatic_model import prepare_model
    from msplatform.backends.comsol.assembly_particle_tracing import prepare_assembly_pulse, prepare_basis_model, trace_assembly_pulse
    from msplatform.backends.comsol.geometry_execution import build_geometry
    from msplatform.io.file_identity import canonical_json_sha256
    from msplatform.results.artifacts import open_artifact

    prepared = compile_comsol_inputs(recipe, instrument, particles)
    receipts = {}
    declared = recipe['field_source'].get('reference')
    if declared is not None:
        reference = declared['reference']
        if reference.get('product_id') != 'background':
            raise ValueError('explicit COMSOL field reference must select background')
        basis_key = canonical_json_sha256({'stage': 'comsol_explicit_basis',
            'manifest_sha256': reference['manifest']['sha256'], 'product_id': 'background',
            'projection': prepared['projection'], 'requests': prepared['requests']})
        background, receipts['basis'] = stage_cache('basis_reference', basis_key, 'field_solution',
            lambda: open_artifact(reference, expected_kind='field_solution'))
        receipts['basis']['execution_kind'] = 'explicit_reference_validation'
    else:
        geometry_key = canonical_json_sha256({'stage': 'comsol_geometry', 'projection': prepared['projection'],
                                              'validation': prepared['geometry']['geometry_validation'], 'implementation': implementation})
        geometry, receipts['geometry'] = stage_cache('geometry', geometry_key, 'geometry_artifact',
            lambda: invoke(lambda: build_geometry(instrument, context=context, **prepared['geometry'])))
        model_key = canonical_json_sha256({'stage': 'comsol_model', 'geometry': geometry_key,
                                           'request': prepared['requests']['off'], 'implementation': implementation})
        model, receipts['model'] = stage_cache('model', model_key, 'prepared_model',
            lambda: invoke(lambda: prepare_model(geometry, request=prepared['requests']['off'], context=context)))
        basis_key = canonical_json_sha256({'stage': 'comsol_basis', 'model': model_key,
                                           'on_request': prepared['requests']['on'], 'implementation': implementation})
        def produce_basis():
            return invoke(lambda: prepare_basis_model(model, on_request=prepared['requests']['on'], context=context))[0]
        background, receipts['basis'] = stage_cache('basis', basis_key, 'field_solution', produce_basis)
    if background.reference['product_id'] != 'background':
        raise ValueError('COMSOL basis cache must reference its background product')
    if declared is not None and background.reference != reference:
        raise ValueError('COMSOL field cache differs from the explicitly declared reference')
    on_key = canonical_json_sha256({'stage': 'comsol_basis_on', 'basis': basis_key})
    on, receipts['basis_on'] = stage_cache('basis_on_reference' if declared is not None else 'basis_on', on_key, 'field_solution',
        lambda: open_artifact({'manifest': background.reference['manifest'], 'product_id': 'on'}, expected_kind='field_solution'))
    if declared is not None:
        receipts['basis_on']['execution_kind'] = 'explicit_reference_validation'
    if on.reference['product_id'] != 'on' or on.reference['manifest']['sha256'] != background.reference['manifest']['sha256']:
        raise ValueError('COMSOL ON product must share the protected basis manifest')
    plan = prepare_assembly_pulse(instrument, background, on, pulse_groups=prepared['pulse_groups'],
        drive=prepared['drive'], source=prepared['source'], numerics=prepared['numerics'],
        observation_times_us=prepared['observation_times_us'])
    if (plan['background']['projection'] != prepared['projection'] or plan['on']['projection'] != prepared['projection']
            or plan['background']['request'] != prepared['requests']['off'] or plan['on']['request'] != prepared['requests']['on']):
        raise ValueError('COMSOL basis geometry or workpoints differ from the frozen study')
    trace_inputs = {key: prepared[key] for key in ('pulse_groups', 'drive', 'source', 'numerics',
                                                    'birth_validation', 'observation_times_us')}
    trace_key = canonical_json_sha256({'stage': 'comsol_particle', 'basis': basis_key, 'inputs': trace_inputs,
                                       'epoch_sha256': epoch_record['sha256'], 'implementation': implementation})
    validation = prepared['birth_validation']
    trajectory, receipts['trace'] = stage_cache('trace', trace_key, 'trajectory_result',
        lambda: invoke(lambda: trace_assembly_pulse(instrument, background.reference, on.reference,
            pulse_groups=prepared['pulse_groups'], drive=prepared['drive'], source=prepared['source'],
            numerics=prepared['numerics'], observation_times_us=prepared['observation_times_us'],
            epoch_record=epoch_record, context=context, **validation)))
    return trajectory, receipts
