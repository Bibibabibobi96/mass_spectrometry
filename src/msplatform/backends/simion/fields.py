"""Prepare actual operating fields from the selected frozen native bodies.

This prepares the coupled multipole/OA field domain only. Downstream analyzer
domains remain provider metadata; no field or flight qualification is implied.
"""
from __future__ import annotations

import math

from msplatform.contracts.rigid_transform import RigidTransform, relative_transform
from msplatform.backends.simion.physical_samples import box_sample, cylinder_sample, sample_node
from msplatform.backends.simion.rf_geometry import physical_electrode_view
from msplatform.backends.simion.electrode_contract import (
    physical_multipole_voltages,
    multipole_rod_pieces,
    scientific_multipole_voltages,
    scientific_multipole_rod_pieces,
)
from msplatform.backends.simion.frontend import (
    frontend_electrode_maps, native_frontend_instances, frontend_accelerator_operating_voltages,
)
from msplatform.components.single_reflection_oa_tof.accelerator_electrical import resolve_accelerator_electrical_design

POLICY = "all_accelerator_electrodes_zero_before_pulse_v1"
IDENTITY = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]


def _box(center: list, size: list) -> dict:
    return {f'{axis}_{end}_mm': center[k]+sign*size[k]/2
            for k,axis in enumerate('xyz') for end,sign in (('min',-1),('max',1))}


def prepare_field_design(multipoles: dict[str, dict], oatof: dict, geometry: dict, *,
                         variant_id: str, pulse_voltage_policy_id: str,
                         boundary_policy: str, frontend_domains: dict,
                         rf_reference_voltage_v: float | None = None, flight: dict | None = None,
                         electrical_projection: dict | None = None) -> dict:
    """Return actual physical samples and complete operating electrode tables.

    Samples use body midpoints and the exact recipe pose; only the sample node
    is rounded, with an inverse-body check before any native solver can run.
    """
    if variant_id != 'three_zone_square':
        raise ValueError('native single-reflection field/drive execution supports only three_zone_square')
    if pulse_voltage_policy_id != POLICY or boundary_policy != 'native_zero_neumann':
        raise ValueError("explicit all-zero OA OFF and native_zero_neumann boundary are required")
    multipole_instances, _ = native_frontend_instances(geometry['composition_plan'])
    local = not multipole_instances
    if not isinstance(multipoles, dict) or set(multipoles) != set(multipole_instances):
        raise ValueError('field design multipole providers differ from the selected scope')
    # Only a whole-workflow held-OFF author proves the pulse response unused.
    # Discovery's temporary held-OFF phase and unspecified future flight retain it.
    pulse_required = flight is None or flight.get('pulse', {}).get('mode') != 'held_off'
    kinds = ('carrier_off', *("rf_reference",) * len(multipole_instances),
             *(('pulse_delta',) if pulse_required else ()))
    if local and rf_reference_voltage_v is not None:
        raise ValueError('oatof-only local scope has no RF reference field')
    if set(frontend_domains) != set(geometry['numerical_domains']):
        raise ValueError("field numerical domains differ from geometry")
    for domain_id, author in frontend_domains.items():
        convergence = author['refine_convergence_v']
        if (not isinstance(convergence, dict)
                or not set(kinds) <= set(convergence) <= (set(kinds) | ({'pulse_delta'} if not pulse_required else set()))):
            raise ValueError(f"{domain_id}: Refine convergence must declare every selected working field")
        values = list(convergence.items())
        if not local:
            values.append(('rf_reference_voltage_v', rf_reference_voltage_v))
        for label, value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{domain_id}.{label} must be finite and positive")
    scientific = geometry['composition_plan']['schema_version'] == 5
    multipole_ids, ids = frontend_electrode_maps(geometry)
    if electrical_projection is not None:
        if not scientific:
            raise ValueError('model electrical projection requires scientific plan5')
        on = {int(key): value for key, value in electrical_projection['accelerator_on'].items()}
        expected_ids = set(geometry['electrode_bindings'][native_frontend_instances(geometry['composition_plan'])[1]].values())
        if set(on) != expected_ids or on[ids['grounded_shield_id']] != 0.:
            raise ValueError('model accelerator projection differs from geometry/ground')
    elif scientific:
        on = frontend_accelerator_operating_voltages(oatof, geometry)
    else:
        electrical = resolve_accelerator_electrical_design(oatof, variant_id=variant_id, schema_version=1)
        operating = electrical['operating_voltages_v']
        on = {ids['accelerator_'+role+'_id']: operating[role]
              for role in ('repeller','grid1','intermediate2','grid2')}
        on.update(zip(ids['accelerator_ring_ids'], operating['rings'], strict=True))
        on[ids['grounded_shield_id']] = 0.
        # Ground is a declared model constraint, not an inferred aperture potential.
        if operating['shield'] != 0:
            raise ValueError("OA field design requires the provider shield to be grounded")
    region = dict(pulse_voltage_policy_id=POLICY,
                  off_voltages_v={key:0. for key in on}, operating_voltages_v=on)
    physical_ids = set(on)
    carrier = {key: 0. for key in physical_ids}
    rf_groups = {}
    if electrical_projection is not None:
        values = {int(key): value for key, value in electrical_projection['carrier'].items()}
        expected_ids = {eid for mapping in multipole_ids.values() for eid in mapping.values()}
        if set(values) != expected_ids:
            raise ValueError('model RF/static projection differs from geometry')
        carrier.update(values)
        physical_ids.update(values)
        rf_groups = {instance: {int(key): value for key, value in groups.items()}
                     for instance, groups in electrical_projection['rf_groups'].items()}
        if set(rf_groups) != set(multipole_instances):
            raise ValueError('model RF instances differ from geometry')
    else:
        for instance_id in multipole_instances:
            voltage_projection = scientific_multipole_voltages if scientific else physical_multipole_voltages
            values, groups = voltage_projection(multipoles[instance_id], multipole_ids[instance_id])
            if set(values) != set(multipole_ids[instance_id].values()):
                raise ValueError(f'{instance_id}: physical voltage view differs from the provider binding')
            physical_ids.update(values)
            carrier.update(values)
            rf_groups[instance_id] = groups
    carrier = {key: carrier.get(key, 0.) for key in sorted(physical_ids)}
    working_points = [dict(kind='carrier_off', electrode_voltages_v={str(k): v for k, v in carrier.items()})]
    rf_instances = sorted(multipole_instances, key=lambda item: tuple(sorted(multipole_ids[item].values())))
    for ordinal, instance_id in enumerate(rf_instances, 1):
        values = {key: 0. for key in carrier}
        for electrode, group in rf_groups[instance_id].items():
            values[electrode] = rf_reference_voltage_v if group == 1 else -rf_reference_voltage_v
        point = dict(kind='rf_reference', electrode_voltages_v={str(k): v for k, v in values.items()})
        # One RF reference retains the frozen N=1 representation.  Multiple
        # references receive a stable physical ordinal, never an instance name.
        if len(rf_instances) > 1:
            point['working_point_id'] = f'rf_reference_{ordinal:02d}'
        working_points.append(point)
    if pulse_required:
        working_points.append(dict(kind='pulse_delta', electrode_voltages_v={str(k): on.get(k, 0.) for k in carrier}))
    domains = []
    for domain_id, domain in geometry['numerical_domains'].items():
        entrance = domain_id == 'entrance_refinement'
        row = dict(domain_id=domain_id, **domain,
            boundary_policy='parent_dirichlet' if entrance else boundary_policy,
            physical_samples=_physical_samples(multipoles, geometry, domain, multipole_ids, ids, entrance=entrance),
            refine_convergence_v={kind: frontend_domains[domain_id]['refine_convergence_v'][kind] for kind in dict.fromkeys(kinds)})
        if entrance:
            row['parent_domain_id'] = 'parent'
        domains.append(row)
    result = dict(schema_version=3,role='frontend_native_field_design',
        scope='accelerator_domain_only' if local else 'coupled_multipole_accelerator_domain_only',
        domains=domains, rf_reference_voltage_v=rf_reference_voltage_v, surface='none',
        working_points=working_points,accelerator_voltage_states=region)
    if local:
        del result['rf_reference_voltage_v']
    return result


def _physical_samples(multipoles: dict[str, dict], geometry: dict, domain: dict,
                      multipole_ids: dict[str, dict[int | str, int]], ids: dict, *, entrance: bool) -> list[dict]:
    """Sample each declared physical group directly from its resolved provider."""
    g = geometry['accelerator_projection']
    origin, pitch, dimensions = domain['instance_origin_mm'], domain['cell_mm_xyz'], domain['dimensions']
    physical = []
    sample_bounds = domain['active_bounds_mm'] if entrance else None

    def append_box(label, kind, electrode, box, hole=None):
        gu = box_sample(box, hole, IDENTITY, [0.,0.,0.], origin, pitch, dimensions,
                        local_bounds_mm=sample_bounds)
        if gu is not None:
            physical.append(dict(label=label, kind=kind, electrode_id=electrode, gu=gu))

    plan = geometry['composition_plan']
    _, downstream_id = native_frontend_instances(plan)
    poses = {row['instance_id']: RigidTransform.from_contract(row['transform']) for row in plan['recipe']['instances']}
    for instance_id, upstream in multipoles.items():
        pose = relative_transform(poses[instance_id], poses[downstream_id])
        rotation, translation = pose.rotation, pose.translation_mm
        mapping = multipole_ids[instance_id]
        scientific = plan['schema_version'] == 5
        if scientific:
            from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
            view = build_electrode_topology(upstream)
        else:
            view = physical_electrode_view(upstream)
        identity_field = 'electrode_group_id' if scientific else 'native_electrode_id'
        if set(mapping) != {row[identity_field] for row in view}:
            raise ValueError(f'{instance_id}: physical electrode binding must cover every provider group')
        rods = scientific_multipole_rod_pieces(upstream) if scientific else multipole_rod_pieces(upstream)
        for rod in rods:
            electrode = mapping[rod['electrode_group_id'] if scientific else rod['electrode_id']]
            physical.append(dict(label=f'segment_{rod["segment_id"]}_rod_{rod["parent_rod_id"]}_e{electrode}',
                kind='rod', electrode_id=electrode, segment_id=rod['segment_id'], parent_rod_id=rod['parent_rod_id'],
                gu=cylinder_sample(rod, rotation, translation, origin, pitch, dimensions)))
        static_rows = [row for row in view if row['voltage_source']['kind'] == 'static']
        for row in static_rows:
            if row['electrode_group_id' if scientific else 'scientific_id'] != 'grounded_shell':
                raise ValueError(f'{instance_id}: unsupported provider static electrode')
            electrode = mapping[row[identity_field]]
            for body in upstream['geometry_mm']['enclosure_layout']['bodies']:
                gu, _ = sample_node([(body['inner_radius_mm'] + body['outer_radius_mm']) / 2, 0,
                    (body['z_min_mm'] + body['z_max_mm']) / 2], rotation, translation, origin, pitch, dimensions)
                physical.append(dict(label=f'{body["role"]}_e{electrode}', kind='static',
                                     electrode_id=electrode, gu=gu))
    x,y = g['axis_x_mm'],g['axis_y_mm']
    width = g['electrode_width_mm']
    for role,z,thickness,w,kind in (
        ('repeller',g['repeller_front_z_mm']-g['repeller_thickness_mm']/2,g['repeller_thickness_mm'],width,'endpoint'),
        ('grid1',g['grid1_z_mm'],0.,width,'ideal_sheet'),('intermediate2',g['intermediate2_z_mm'],0.,width,'ideal_sheet'),
        ('grid2',g['grid2_z_mm'],0.,g['shield_inner_width_mm'],'ideal_sheet')):
        box = _box([x,y,z],[w,w,thickness])
        append_box(role+'_metal', kind, ids['accelerator_'+role+'_id'], box)
    for index,(eid,z) in enumerate(zip(ids['accelerator_ring_ids'],g['ring_z_mm'],strict=True),1):
        box = _box([x,y,z],[width,width,g['ring_thickness_mm']])
        hole = _box([x,y,z],[g['bore_width_mm'],g['bore_width_mm'],g['ring_thickness_mm']+geometry['numerical_domains']['parent']['cell_mm_xyz']['z']])
        append_box(f'accelerator_ring_{index}', 'ring', eid, box, hole)
    # The parent samples its positive-X wall. A local entrance patch samples
    # the actual negative-X wall minus the provider's side opening.
    z = (g['shield_back_z_mm']+g['grid2_z_mm'])/2
    side = -1 if entrance else 1
    box = _box([x+side*(g['shield_outer_width_mm']-g['shield_wall_mm'])/2,y,z],
               [g['shield_wall_mm'],g['shield_inner_width_mm'],g['shield_span_z_mm']])
    hole = (_box([g['negative_x_face_mm']+g['shield_wall_mm']/2,g['port_center_y_mm'],g['port_center_z_mm']],
                 [g['shield_wall_mm']+geometry['numerical_domains']['parent']['cell_mm_xyz']['x'],
                  g['numerical_port_width_mm'],g['numerical_port_height_mm']]) if entrance else None)
    append_box('accelerator_shield', 'ground', ids['grounded_shield_id'], box, hole)
    physical_ids = {value for key,value in ids.items() if key != 'accelerator_ring_ids'} | set(ids['accelerator_ring_ids'])
    multipole_solver_ids = {solver_id for binding in multipole_ids.values() for solver_id in binding.values()}
    physical_ids.update(multipole_solver_ids)
    expected = (multipole_solver_ids | {ids['grounded_shield_id']}
                if entrance else physical_ids)
    actual = {row['electrode_id'] for row in physical}
    if (not expected <= actual or not actual <= physical_ids
            or (not entrance and actual != expected)):
        raise ValueError("actual metal samples do not cover the admitted physical electrode namespace")
    return physical
