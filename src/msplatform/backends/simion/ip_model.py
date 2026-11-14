"""Pure unsolved IP–MR drive compilation; no joint field or flight is produced."""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .artifacts import CompiledPreparedModel
from .compiler import CompiledSimionGeometry, _content_sha256
from .model import (RF_IP_PHYSICS, _exact, _validate_groups, _validate_timing,
                    _validated_ip_schedule, scientific_multipole_drive)
from .mr_model import _validated_mr_voltages


def compile_ip_mr_model(compiled: CompiledSimionGeometry, components: Mapping[str, dict], *,
                        drive: Mapping[str, Any], physics: Mapping[str, Any]) -> CompiledPreparedModel:
    """Bind exact physical authorities and an explicit requested future BVP.

    Grounded PA faces are the caller's requested common-domain policy. The
    three local geometry assets do not establish or realize a coupled field.
    """
    if not isinstance(compiled, CompiledSimionGeometry):
        raise TypeError('IP–MR requires compiled SIMION geometry')
    geo=compiled.frontend_geometry
    if geo.get('role')!='simion_ip_mr_complete_geometry' or not isinstance(physics,Mapping) or dict(physics)!=RF_IP_PHYSICS:
        raise ValueError('IP–MR requires explicit requested grounded-face linear physics')
    plan=geo['composition_plan'];selected=plan['scope']['instance_ids']
    if len(selected) not in (2,3) or set(components)!=set(selected) or set(compiled.components_resolved)!=set(selected):
        raise ValueError('IP–MR selected component scope differs')
    ip=[name for name in selected if plan['components'][name]['project_id']=='dual_pressure_rectilinear_ion_processor']
    mr=[name for name in selected if plan['components'][name]['project_id']=='parallel_mirror_dual_stripe_mr_tof']
    rf=[name for name in selected if plan['components'][name]['project_id']=='rf_multipole_ion_optics']
    if len(ip)!=1 or len(mr)!=1 or len(rf)>1 or len(ip)+len(mr)+len(rf)!=len(selected):
        raise ValueError('IP–MR requires one IP, one MR and at most one RF multipole')
    ip,mr=ip[0],mr[0]
    if dict(components)!=compiled.components_resolved:
        raise ValueError('IP–MR resolved components differ from compiled geometry')
    expected_assets={ip:ip,mr+'_analyzer':mr,mr+'_detector':mr}
    if rf: expected_assets[rf[0]]=rf[0]
    if geo['asset_components']!=expected_assets or set(compiled.frontend_gems)!=set(expected_assets) or set(geo['numerical_domains'])!=set(expected_assets):
        raise ValueError('IP–MR requires its exact component-owned geometry assets')
    poses={row['instance_id']:row['transform'] for row in plan['recipe']['instances'] if row['instance_id'] in selected}
    if len(poses)!=len(selected) or geo['asset_poses']!={name:poses[owner] for name,owner in expected_assets.items()}:
        raise ValueError('IP–MR physical asset poses differ from Assembly')
    _exact(drive,{'clock','ip_schedule','mr_authority'} | ({'groups'} if rf else set()),'IP–MR drive')
    _validate_timing(drive,requires_pulse=False)
    frozen=_validated_ip_schedule(drive['ip_schedule'],drive['clock'],compiled,components,selected,ip)
    mappings=geo['electrode_bindings']
    if set(mappings)!=set(selected): raise ValueError('IP–MR scientific component maps differ')
    if rf:
        expected={rf[0]:scientific_multipole_drive(components[rf[0]],mappings[rf[0]])}
        _validate_groups(drive['groups'],expected)
    electrodes=components[ip]['projection']['electrodes']
    if len(electrodes)!=15 or set(mappings[ip])!={row['name'] for row in electrodes}:
        raise ValueError('IP scientific groups differ from selected metal')
    values=_validated_mr_voltages(drive['mr_authority'],components[mr],mappings[mr])
    roles=geo['electrode_group_roles'][mr]
    expected_roles={row['electrode_group_id']:row['role'] for row in plan['components'][mr]['component_electrodes']}
    if roles!=expected_roles or set(roles)!=set(values): raise ValueError('MR scientific group roles differ')
    rows=[]
    if rf:
        rows.extend(dict(instance_id=rf[0],electrode_group_id=group,
                         native_targets=[dict(domain=rf[0],electrode_id=mappings[rf[0]][group])],**value)
                    for group,value in drive['groups'][rf[0]].items())
    rows.extend(dict(instance_id=ip,electrode_group_id=row['name'],kind='ip_schedule',schedule_index=row['electrode_id'],
               native_targets=[dict(domain=ip,electrode_id=mappings[ip][row['name']])]) for row in electrodes)
    rows.extend(dict(instance_id=mr,electrode_group_id=name,kind='static',voltage_v=value,
                     native_targets=[dict(domain=mr+('_detector' if roles[name]=='detector' else '_analyzer'),
                                          electrode_id=mappings[mr][name])]) for name,value in values.items())
    targets=[(row['native_targets'][0]['domain'],row['native_targets'][0]['electrode_id']) for row in rows]
    if any(type(eid) is not int or eid<=0 for _,eid in targets) or len(targets)!=len(set(targets)):
        raise ValueError('IP–MR native targets must be positive and distinct within each asset')
    full_drive=dict(clock=copy.deepcopy(drive['clock']),ip_schedule=frozen,mr_authority=copy.deepcopy(drive['mr_authority']))
    if rf: full_drive['groups']=copy.deepcopy(drive['groups'])
    document=dict(schema_version=1,role='compiled_prepared_simion_model',field_status='not_solved',source_status='not_requested',
        native_frame_id=plan['assembly_frame_id'],geometry=asdict(compiled),components_resolved=copy.deepcopy(dict(components)),
        drive=full_drive,physics=copy.deepcopy(dict(physics)),native_drive_rows=rows)
    document=json.loads(json.dumps(document,sort_keys=True,allow_nan=False))
    document['model_identity_sha256']=_content_sha256(document)
    return CompiledPreparedModel(json.dumps(document,sort_keys=True,separators=(',',':'),allow_nan=False))
