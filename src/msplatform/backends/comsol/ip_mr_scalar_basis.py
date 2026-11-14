"""Project a verified complete IP–MR model into explicit stationary unit bases.

This is input planning only: no field is solved, sampled, bound or qualified.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from msplatform.assembly.model import Assembly
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.simion.compiler import _content_sha256
from msplatform.backends.simion.ip_model import compile_ip_mr_model
from msplatform.backends.simion.model import model_geometry, require_prepared_model


def project_ip_mr_scalar_basis(model: Any, *, assembly: Assembly, projection: Mapping[str, Any],
                               operator: Mapping[str, Any]) -> dict[str, Any]:
    """Build explicit carrier, unit-IP and optional full-amplitude RF requests.

    IP coefficients are the corresponding volts returned by the existing
    ``model_drive.evaluate_at`` consumer, not a separately evaluated schedule.
    The RF coefficient is the dimensionless waveform of its one signature.
    """
    if not isinstance(assembly, Assembly): raise TypeError('complete Assembly required')
    assembly = Assembly(assembly.composition_plan, assembly.components)
    document = require_prepared_model(model)
    geometry = model_geometry(model)
    if geometry.frontend_geometry.get('role') != 'simion_ip_mr_complete_geometry':
        raise ValueError('complete IP–MR model required')
    plan = assembly.composition_plan
    if geometry.frontend_geometry['composition_plan'] != plan or geometry.components_resolved != assembly.components_resolved:
        raise ValueError('model and Assembly physical geometry differ')
    for name, component in assembly.components.items():
        identity=geometry.provider_content_identities[name]
        expected=dict(resolved_content_sha256=_content_sha256(component.resolved_design),
                      component_interface_sha256=_content_sha256(component.assembly_interface),
                      source_content_sha256=_content_sha256(component.source_design))
        if identity != expected: raise ValueError('model and Assembly component source identities differ: '+name)
    source_drive=copy.deepcopy(document['drive'])
    # Model compilation derives this field; compare its re-derived value below.
    source_drive['ip_schedule'].pop('native_timing')
    rebuilt=compile_ip_mr_model(geometry,assembly.components_resolved,drive=source_drive,physics=document['physics'])
    if require_prepared_model(rebuilt) != document:
        raise ValueError('prepared model is not the canonical source-derived model')
    if not isinstance(projection,Mapping) or 'outer_box_mm' not in projection:
        raise ValueError('explicit COMSOL Assembly projection required')
    snapshot=dict(composition_plan=plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
    if _content_sha256(dict(projection)) != _content_sha256(project_assembly_geometry(snapshot,outer_box_mm=projection['outer_box_mm'])):
        raise ValueError('COMSOL projection differs from the canonical Assembly')
    if not isinstance(operator,Mapping) or set(operator) != {'relative_permittivity','exterior','mesh','study'}:
        raise ValueError('explicit material, exterior, mesh and study required')
    if operator['exterior'] != {'kind':'potential','voltage_v':0.}:
        raise ValueError('basis superposition requires explicit zero exterior potential')
    groups=[(row['instance_id'],row['electrode_group_id']) for row in projection['electrode_groups']]
    if len(groups)!=len(set(groups)): raise ValueError('ambiguous physical group identities')
    rows=document['native_drive_rows']
    by_group={(row['instance_id'],row['electrode_group_id']):row for row in rows}
    if len(rows)!=len(by_group) or set(by_group)!=set(groups):
        raise ValueError('model and projection scientific group coverage differs')
    projects={name:plan['components'][name]['project_id'] for name in plan['scope']['instance_ids']}
    ips=[name for name,project in projects.items() if project=='dual_pressure_rectilinear_ion_processor']
    mrs=[name for name,project in projects.items() if project=='parallel_mirror_dual_stripe_mr_tof']
    rfs=[name for name,project in projects.items() if project=='rf_multipole_ion_optics']
    if len(ips)!=1 or len(mrs)!=1 or len(rfs)>1 or len(projects)!=2+len(rfs):
        raise ValueError('one complete IP, one MR and at most one RF required')
    ip,mr=ips[0],mrs[0]; ip_keys=[key for key in groups if key[0]==ip]
    if len(ip_keys)!=15 or any(by_group[key]['kind']!='ip_schedule' for key in ip_keys):
        raise ValueError('all fifteen actual IP schedule groups required')
    indices=[by_group[key]['schedule_index'] for key in ip_keys]
    if sorted(indices)!=list(range(1,16)): raise ValueError('IP schedule indices differ')
    if any(by_group[key]['kind']!='static' for key in groups if key[0]==mr):
        raise ValueError('MR groups must have their actual static voltages')
    rf_keys=[key for key in groups if rfs and key[0]==rfs[0]]
    if any(by_group[key]['kind']!='rf' for key in rf_keys): raise ValueError('unsupported external RF group kind')
    signatures={(by_group[key]['waveform'],by_group[key]['frequency_hz'],by_group[key]['phase_rad']) for key in rf_keys}
    if len(signatures)>1: raise ValueError('multiple incompatible external RF signatures are unsupported')

    def request(values: Mapping[tuple[str,str],float]) -> dict[str,Any]:
        return validate_request(projection,dict(group_voltages=[dict(instance_id=a,electrode_group_id=b,voltage_v=values[(a,b)])
            for a,b in groups],**copy.deepcopy(dict(operator))))
    carrier={key:(by_group[key]['voltage_v'] if key[0]==mr else
                  by_group[key]['common_mode_v']+by_group[key]['dc_v'] if key in rf_keys else 0.) for key in groups}
    zero=dict.fromkeys(groups,0.)
    ip_bases=[]
    for key in ip_keys:
        vector=dict(zero);vector[key]=1.
        ip_bases.append(dict(instance_id=key[0],electrode_group_id=key[1],
            schedule_index=by_group[key]['schedule_index'],coefficient='model_drive.evaluate_at.voltage_v',request=request(vector)))
    rf_basis=None
    if rf_keys:
        vector=dict(zero)
        for key in rf_keys: vector[key]=by_group[key]['polarity']*by_group[key]['rf_amplitude_v']
        waveform,frequency,phase=next(iter(signatures))
        rf_basis=dict(instance_id=rfs[0],waveform=waveform,frequency_hz=frequency,phase_rad=phase,
                      coefficient='dimensionless_rf_waveform',request=request(vector))
    return dict(schema_version=1,role='ip_mr_stationary_basis_requests',status='not_solved_not_qualified',
        model_identity_sha256=document['model_identity_sha256'],clock=copy.deepcopy(document['drive']['clock']),
        projection_sha256=_content_sha256(projection),carrier=request(carrier),ip_unit_volt=ip_bases,rf_reference=rf_basis)
