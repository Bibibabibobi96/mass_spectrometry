"""Compile an explicit physical drive into an unsolved SIMION model snapshot.

No paths, particles, time-step settings or native actions are needed. Geometry
and provider snapshots are authenticated before deriving the sole electrical
projection consumed by both the saved Lua model and field preparation.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import json
import math
from typing import Any, Mapping

from msplatform.contracts.clock import ClockIdentity
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import ResolvedAcceleratorGeometry
from msplatform.components.single_reflection_oa_tof.electrode_topology import build_electrode_topology
from .artifacts import CompiledPreparedModel
from .compiler import CompiledSimionGeometry, _content_sha256
from .electrode_contract import _physical_voltage_value, scientific_multipole_drive
from .frontend import frontend_electrode_maps, native_frontend_instances
from .source import lua_value
from .tof_geometry import resolve_physical_geometry


RF_PHYSICS = dict(field_model='external_electrostatic_linear', boundary_policy='native_zero_neumann')

PHYSICS = dict(field_model='external_electrostatic_linear', boundary_policy='native_zero_neumann',
    pulse_voltage_policy_id='all_accelerator_electrodes_zero_before_pulse_v1')


def _exact(value: Any, fields: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f'{label} fields differ')


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{label} must be finite')
    return float(value)


def _authorities(compiled: CompiledSimionGeometry, components: Mapping[str, dict]) -> tuple:
    if not isinstance(compiled, CompiledSimionGeometry):
        raise TypeError('prepared model requires compiled SIMION geometry')
    geometry = compiled.frontend_geometry
    plan = geometry['composition_plan']
    if geometry.get('role') == 'simion_independent_rf_geometry':
        from .rf_compiler import compile_independent_multipoles
        selected = plan['scope']['instance_ids']
        if not isinstance(components, Mapping) or set(components) != set(selected):
            raise ValueError('model providers differ from selected independent RF scope')
        snapshots = copy.deepcopy(compiled.components_resolved)
        snapshots.update(copy.deepcopy(dict(components)))
        actual = compile_independent_multipoles(dict(composition_plan=plan, components_resolved=snapshots),
            numerics=dict(component_domains={name: dict(cell_mm_xyz=domain['cell_mm_xyz'])
                for name, domain in geometry['numerical_domains'].items()},
                electrode_group_native_ids=geometry['electrode_bindings']))
        if asdict(actual) != asdict(compiled):
            raise ValueError('independent RF geometry differs from its canonical providers')
        return selected, None, None
    multipoles, tof = native_frontend_instances(plan)
    if not isinstance(components, Mapping) or set(components) != set(plan['scope']['instance_ids']):
        raise ValueError('model providers differ from selected geometry scope')
    for instance, document in components.items():
        expected = dict(resolved_content_sha256=_content_sha256(document),
            component_interface_sha256=_content_sha256(plan['components'][instance]))
        if compiled.provider_content_identities.get(instance) != expected:
            raise ValueError(f'{instance}: stale model provider identity')
    frontend_electrode_maps(geometry)
    interface = plan['components'][tof]
    projection = ResolvedAcceleratorGeometry(interface['variant_id'], geometry['native_frame_id'],
        geometry['accelerator_projection'])
    topology = build_electrode_topology(components[tof], projection=projection,
        geometry_profile_id=interface['geometry_profile_id'])
    return multipoles, tof, topology


def project_resolved_drive(compiled: CompiledSimionGeometry, components_resolved: Mapping[str, dict], *,
                           clock: Mapping[str, Any], pulse: Mapping[str, Any] | None = None) -> dict:
    """Expand defaults from the same actual providers; timing/clock stay explicit.

    The returned author input is mutable. Changing it does not change geometry
    or any existing model. Compilation validates it and makes a fresh snapshot.
    """
    multipoles, tof, topology = _authorities(compiled, components_resolved)
    maps = compiled.frontend_geometry['electrode_bindings']
    groups = {instance: scientific_multipole_drive(components_resolved[instance], maps[instance])
              for instance in multipoles}
    if tof is None:
        if pulse is not None:
            raise ValueError('independent RF drive has no pulse component')
        return dict(groups=groups, clock=copy.deepcopy(dict(clock)))
    if pulse is None:
        raise ValueError('TOF model requires an explicit pulse')
    frontend = set(topology['frontend_electrode_group_ids'])
    groups[tof] = {}
    for row in topology['groups']:
        group = row['electrode_group_id']
        voltage = _physical_voltage_value(topology, row['voltage_source']['pointer'])
        groups[tof][group] = (dict(kind='pulse', off_voltage_v=0., on_voltage_v=voltage)
                             if group in frontend and group != 'common_ground'
                             else dict(kind='static', voltage_v=voltage))
    return dict(groups=groups, pulse=copy.deepcopy(dict(pulse)), clock=copy.deepcopy(dict(clock)))


def _validate_timing(drive: Mapping[str, Any], *, requires_pulse: bool = True) -> None:
    clock = drive['clock']
    _exact(clock, {'clock_epoch_id', 'authority_sha256', 'phase_reference_instrument_time_us'}, 'model clock')
    ClockIdentity(clock['clock_epoch_id'], clock['authority_sha256'])
    # This first adapter preserves the existing RF definition omega*t + phase.
    # Supporting another anchor requires an explicit physical projection change.
    if _finite(clock['phase_reference_instrument_time_us'], 'phase reference') != 0.:
        raise ValueError('this SIMION model adapter supports phase reference instrument time 0 only')
    if not requires_pulse:
        return
    pulse = drive['pulse']
    if not isinstance(pulse, Mapping) or pulse.get('mode') not in {'timed', 'held_off', 'held_on'}:
        raise ValueError('model pulse mode is unsupported')
    _exact(pulse, {'mode', 'time_us', 'width_us'} if pulse['mode'] == 'timed' else {'mode'}, 'model pulse')
    if pulse['mode'] == 'timed':
        start, width = (_finite(pulse[key], 'pulse ' + key) for key in ('time_us', 'width_us'))
        if width <= 0 or not math.isfinite(start + width) or start + width <= start:
            raise ValueError('pulse width/end must be positive and finite')


def _validate_groups(groups: Mapping, expected: Mapping) -> None:
    _exact(groups, set(expected), 'model drive instances')
    for instance, expected_rows in expected.items():
        _exact(groups[instance], set(expected_rows), f'{instance} scientific groups')
        rf_contract = None
        for group, template in expected_rows.items():
            row = groups[instance][group]
            _exact(row, set(template), f'{instance}.{group} drive')
            if row['kind'] != template['kind']:
                raise ValueError(f'{instance}.{group}: physical drive kind differs')
            for key, value in row.items():
                if key not in {'kind', 'waveform'}:
                    _finite(value, f'{instance}.{group}.{key}')
            if row['kind'] == 'static' and template['voltage_v'] == 0. and group in {'common_ground', 'grounded_shell'}:
                if row['voltage_v'] != 0.:
                    raise ValueError('declared common ground must remain zero')
            if row['kind'] == 'pulse' and row['off_voltage_v'] != 0.:
                raise ValueError('selected OA policy requires all-zero OFF voltage')
            if row['kind'] == 'rf':
                if (row['waveform'] not in {'sine', 'cosine'} or row['frequency_hz'] <= 0
                        or row['rf_amplitude_v'] < 0 or row['polarity'] != template['polarity']):
                    raise ValueError('RF waveform/frequency/amplitude/polarity differs')
                contract = tuple(row[key] for key in ('waveform', 'frequency_hz', 'phase_rad', 'rf_amplitude_v'))
                if rf_contract is not None and rf_contract != contract:
                    raise ValueError('one RF provider requires one physical differential waveform')
                rf_contract = contract


def _native_physical_projection(compiled: CompiledSimionGeometry, resolved: dict) -> dict:
    """Bind backend marker input to the unchanged native-label adapter only.

    Scientific provider snapshots intentionally contain no SIMION numerical
    marker. This private, independent adapter view gets that value exclusively
    from the authenticated compiled geometry, never from defaults or a source.
    """
    view = copy.deepcopy(resolved)
    view['simion_detector_marker'] = copy.deepcopy(
        compiled.frontend_geometry['downstream_build_contract']['simion_detector_marker'])
    return resolve_physical_geometry(view)


def _native_targets(compiled: CompiledSimionGeometry, components: Mapping, tof: str, topology: dict) -> dict:
    geometry = compiled.frontend_geometry
    targets = {instance: {group: [dict(domain=domain, electrode_id=eid)
                for domain in geometry['numerical_domains']] for group, eid in mapping.items()}
               for instance, mapping in geometry['electrode_bindings'].items()}
    # One common-ground group has real members in multiple PA domains. Local
    # labels are never global identities and may repeat between these domains.
    physical = _native_physical_projection(compiled, components[tof])
    roles = {row['component_electrode_id']: row['role'] for row in physical['electrodes']}
    for group in topology['groups']:
        targets[tof].setdefault(group['electrode_group_id'], [])
    for domain in ('flight_tube', 'reflectron'):
        for row in physical['simion'][domain]['electrodes']:
            role = roles[row['component_electrode_id']]
            group = 'common_ground' if role in {'flight_tube_shield', 'reflectron_entry_grid'} else role
            targets[tof][group].append(dict(domain=domain, electrode_id=row['local_electrode_id']))
    targets[tof]['common_ground'].append(dict(domain='detector', electrode_id=1))
    if any(not rows for groups in targets.values() for rows in groups.values()):
        raise ValueError('scientific group lacks a native geometry consumer')
    occupied = set()
    for groups in targets.values():
        for rows in groups.values():
            for row in rows:
                key = row['domain'], row['electrode_id']
                if key in occupied:
                    raise ValueError('native group alias in model mapping')
                occupied.add(key)
    return targets


def compile_prepared_model(compiled: CompiledSimionGeometry, components_resolved: Mapping[str, dict], *,
                           drive: Mapping[str, Any], physics: Mapping[str, Any]) -> CompiledPreparedModel:
    """Return a complete physical-drive snapshot, not a solved/published artifact."""
    multipoles, tof, topology = _authorities(compiled, components_resolved)
    if tof is None:
        if not isinstance(physics, Mapping) or dict(physics) != RF_PHYSICS:
            raise ValueError('independent RF physics/boundary policy is unsupported')
        _exact(drive, {'groups', 'clock'}, 'independent RF model drive')
        _validate_timing(drive, requires_pulse=False)
        expected = project_resolved_drive(compiled, components_resolved, clock=drive['clock'])
        _validate_groups(drive['groups'], expected['groups'])
        mappings = compiled.frontend_geometry['electrode_bindings']
        rows = [dict(instance_id=instance, electrode_group_id=group,
                native_targets=[dict(domain=instance, electrode_id=mappings[instance][group])], **value)
                for instance, groups in drive['groups'].items() for group, value in groups.items()]
        document = dict(schema_version=1, role='compiled_prepared_simion_model',
            field_status='not_solved', source_status='not_requested',
            native_frame_id=compiled.frontend_geometry['composition_plan']['assembly_frame_id'],
            geometry=asdict(compiled), components_resolved=copy.deepcopy(dict(components_resolved)),
            drive=copy.deepcopy(dict(drive)), physics=copy.deepcopy(dict(physics)), native_drive_rows=rows)
        document = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
        document['model_identity_sha256'] = _content_sha256(document)
        return CompiledPreparedModel(json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False))
    if not isinstance(physics, Mapping) or dict(physics) != PHYSICS:
        raise ValueError('model physics/boundary policy is unsupported')
    _exact(drive, {'groups', 'pulse', 'clock'}, 'model drive')
    _validate_timing(drive)
    expected = project_resolved_drive(compiled, components_resolved, pulse=drive['pulse'], clock=drive['clock'])
    _validate_groups(drive['groups'], expected['groups'])
    targets = _native_targets(compiled, components_resolved, tof, topology)
    bindings = compiled.frontend_geometry['electrode_bindings']
    carrier, rf_groups, on = {}, {}, {}
    for instance in multipoles:
        rf_groups[instance] = {}
        for group, row in drive['groups'][instance].items():
            eid = bindings[instance][group]
            carrier[eid] = row['voltage_v'] if row['kind'] == 'static' else row['common_mode_v'] + row['dc_v']
            if row['kind'] == 'rf':
                rf_groups[instance][eid] = 1 if row['polarity'] == 1 else 2
    for group, eid in bindings[tof].items():
        row = drive['groups'][tof][group]
        on[eid] = row['voltage_v'] if row['kind'] == 'static' else row['on_voltage_v']
    downstream = copy.deepcopy(compiled)
    physical = _native_physical_projection(compiled, components_resolved[tof])
    roles = {row['component_electrode_id']: row['role'] for row in physical['electrodes']}
    for spec in downstream.downstream_specs:
        if spec['role'] == 'detector':
            continue
        for row in spec['template_variables']['component']['electrodes']:
            role = roles[row['component_electrode_id']]
            group = 'common_ground' if role in {'flight_tube_shield', 'reflectron_entry_grid'} else role
            row['voltage_v'] = drive['groups'][tof][group]['voltage_v']
    contract = downstream.frontend_geometry['downstream_build_contract']
    contract['electrodes_V']['midgrid'] = drive['groups'][tof]['reflectron_midgrid']['voltage_v']
    contract['electrodes_V']['backplate'] = drive['groups'][tof]['reflectron_backplate']['voltage_v']
    rows = [dict(instance_id=instance, electrode_group_id=group, native_targets=targets[instance][group], **value)
            for instance, groups in drive['groups'].items() for group, value in groups.items()]
    document = dict(schema_version=1, role='compiled_prepared_simion_model', field_status='not_solved',
        source_status='not_requested', geometry=asdict(compiled), components_resolved=copy.deepcopy(dict(components_resolved)),
        drive=copy.deepcopy(dict(drive)), physics=copy.deepcopy(dict(physics)), native_drive_rows=rows,
        electrical_projection=dict(carrier=carrier, rf_groups=rf_groups, accelerator_on=on),
        downstream_geometry=asdict(downstream))
    # Identity binds the persisted JSON value, including its string object keys
    # and array representation. Sorting pre-JSON integer labels numerically and
    # post-read string labels lexically otherwise gives different identities.
    document = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
    document['model_identity_sha256'] = _content_sha256(document)
    return CompiledPreparedModel(json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False))


def require_prepared_model(model: CompiledPreparedModel) -> dict:
    """Check serialized identity before any pure consumer uses its private view."""
    if not isinstance(model, CompiledPreparedModel):
        raise TypeError('field preparation requires a CompiledPreparedModel')
    document = model.document
    identity = document.pop('model_identity_sha256', None)
    if _content_sha256(document) != identity:
        raise ValueError('prepared model identity differs')
    if document.get('role') != 'compiled_prepared_simion_model' or document.get('field_status') != 'not_solved':
        raise ValueError('prepared model kind/status differs')
    document['model_identity_sha256'] = identity
    return document


def render_model_configuration(model: CompiledPreparedModel) -> str:
    """Save the actual Lua consumer input; it contains no particles or field paths."""
    document = require_prepared_model(model)
    configuration = dict(schema_version=1, role='simion_model_drive',
        model_identity_sha256=document['model_identity_sha256'], clock=document['drive']['clock'],
        groups=document['native_drive_rows'])
    if 'native_frame_id' in document:
        configuration['native_frame_id'] = document['native_frame_id']
    if 'pulse' in document['drive']:
        configuration['pulse'] = document['drive']['pulse']
    return 'return ' + lua_value(configuration) + '\n'


def model_geometry(model: CompiledPreparedModel, *, downstream_drive: bool = False) -> CompiledSimionGeometry:
    """Restore the typed geometry view from the verified portable JSON snapshot."""
    document = require_prepared_model(model)
    if downstream_drive and document['geometry']['frontend_geometry'].get('role') == 'simion_independent_rf_geometry':
        raise ValueError('independent RF fields/tracking require a separately validated fractional field protocol')
    values = document['downstream_geometry' if downstream_drive else 'geometry']
    values['downstream_specs'] = tuple(values['downstream_specs'])
    return CompiledSimionGeometry(**values)
