"""Pure, source-free complete OA–MR scientific drive projection."""
from __future__ import annotations

import copy
from dataclasses import asdict
import json
from collections.abc import Mapping
from typing import Any

from msplatform.components.parallel_mirror_dual_stripe_mr_tof.assembly_interface import (
    _component_electrodes, _scientific_groups,
)
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_voltage import candidate_authority
from .artifacts import CompiledPreparedModel
from .compiler import CompiledSimionGeometry, _content_sha256


def _validated_mr_voltages(authority: Mapping[str, Any], resolved: dict, mapping: Mapping) -> dict:
    """Validate the actual candidate and project every MR scientific voltage."""
    from .model import _exact, _finite

    _exact(authority, {'source', 'candidate', 'mirror_voltages_v', 'detector_voltage_v', 'mirror_shield_voltages_v'}, 'MR authority')
    voltage = candidate_authority(authority['source'], authority['candidate'], mirror_voltages_v=authority['mirror_voltages_v'])
    shields = authority['mirror_shield_voltages_v']
    _exact(shields, {'positive_mirror_ground_shield','negative_mirror_ground_shield'}, 'MR mirror shields')
    rows = _component_electrodes(resolved)
    groups = _scientific_groups(resolved, rows)
    values = {}
    if len(groups) != len(rows) + 2:
        raise ValueError('MR physical groups differ from the two explicit shields')
    for electrode, group in zip(rows, groups[:-2], strict=True):
        physical_id = electrode['component_electrode_id']; name = group['electrode_group_id']
        if group['role'] == 'detector':
            values[name] = _finite(authority['detector_voltage_v'], 'MR detector voltage')
        elif 1 <= physical_id <= 20:
            values[name] = _finite(voltage['analyzer_electrode_voltages_v'][physical_id-1], name)
        else:
            raise ValueError(f'no declared analyzer voltage for {name}')
    # Physical group order must survive JSON key sorting on a saved model.
    for group in groups[-2:]:
        name = group['electrode_group_id']
        values[name] = _finite(shields[name], name)
    if set(values) != set(mapping):
        raise ValueError('MR voltage authority does not cover exact scientific groups')
    return values


def compile_oa_mr_model(compiled: CompiledSimionGeometry, components: Mapping[str, dict], *,
                        drive: Mapping[str, Any], physics: Mapping[str, Any]) -> CompiledPreparedModel:
    """Bind explicit OA waveform and MR physical voltages to three actual assets."""
    from .model import RF_PHYSICS, _exact, _validate_oa_drive

    if not isinstance(compiled, CompiledSimionGeometry):
        raise TypeError('OA–MR requires compiled SIMION geometry')
    geo = compiled.frontend_geometry
    if geo.get('role') != 'simion_oa_mr_complete_geometry' or dict(physics) != RF_PHYSICS:
        raise ValueError('unsupported OA–MR geometry or physics')
    plan = geo['composition_plan']; selected = plan['scope']['instance_ids']
    if set(components) != set(selected):
        raise ValueError('OA–MR selected component scope differs')
    for name in selected:
        if compiled.provider_content_identities.get(name) != dict(
            resolved_content_sha256=_content_sha256(components[name]),
            component_interface_sha256=_content_sha256(plan['components'][name])):
            raise ValueError(f'{name}: stale model provider identity')
    asset_components = geo['asset_components']
    oa = next((name for name in selected if plan['components'][name]['project_id'] == 'orthogonal_accelerator'), None)
    mr = next((name for name in selected if plan['components'][name]['project_id'] == 'parallel_mirror_dual_stripe_mr_tof'), None)
    if not oa or not mr or set(compiled.frontend_gems) != {oa, mr+'_analyzer', mr+'_detector'}:
        raise ValueError('OA–MR requires its three complete geometry assets')
    if asset_components != {oa: oa, mr+'_analyzer': mr, mr+'_detector': mr}:
        raise ValueError('OA–MR asset component ownership differs')
    _exact(drive, {'clock', 'oa_groups', 'pulse', 'mr_authority'}, 'OA–MR drive')
    mappings = geo['electrode_bindings']
    _validate_oa_drive(dict(groups={oa: drive['oa_groups']}, clock=drive['clock'], pulse=drive['pulse']),
                       {oa: mappings[oa]})
    values = _validated_mr_voltages(drive['mr_authority'], components[mr], mappings[mr])
    oa_group_ids = [row['electrode_group_id'] for row in plan['components'][oa]['component_electrodes']]
    native_rows = [dict(instance_id=oa, electrode_group_id=group,
                        native_targets=[dict(domain=oa, electrode_id=mappings[oa][group])],
                        **copy.deepcopy(drive['oa_groups'][group]))
                   for group in oa_group_ids]
    native_rows.extend(dict(instance_id=mr, electrode_group_id=group,
                            native_targets=[dict(domain=mr+('_detector' if group == 'detector' else '_analyzer'),
                                                 electrode_id=mappings[mr][group])], kind='static', voltage_v=value)
                       for group, value in values.items())
    targets = [(row['native_targets'][0]['domain'], row['native_targets'][0]['electrode_id']) for row in native_rows]
    if len(set(targets)) != len(targets):
        raise ValueError('OA–MR native targets alias within an asset')
    document = dict(schema_version=1, role='compiled_prepared_simion_model', field_status='not_solved',
                    source_status='not_requested', native_frame_id=plan['assembly_frame_id'],
                    geometry=asdict(compiled), components_resolved=copy.deepcopy(dict(components)),
                    drive=copy.deepcopy(dict(drive)), physics=copy.deepcopy(dict(physics)), native_drive_rows=native_rows)
    document = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
    document['model_identity_sha256'] = _content_sha256(document)
    return CompiledPreparedModel(json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False))
