"""Prepare actual operating fields from the selected frozen native bodies.

This prepares the coupled multipole/OA field domain only. Downstream analyzer
domains remain provider metadata; no field or flight qualification is implied.
"""
from __future__ import annotations

import math

from common.contracts.rigid_transform import RigidTransform, relative_transform
from integrations.runtime.frontend_field_plan import box_sample, cylinder_sample, sample_node
from common.multipole.simion_geometry import physical_electrode_view
from integrations.runtime.single_flight_electrode_contract import (
    physical_multipole_voltages,
    segmented_through_exit_rod_pieces,
)
from integrations.runtime.single_flight_frontend import frontend_electrode_maps, native_frontend_instances
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_electrical import resolve_accelerator_electrical_design

POLICY = "all_accelerator_electrodes_zero_before_pulse_v1"
IDENTITY = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]


def _box(center: list, size: list) -> dict:
    return {f'{axis}_{end}_mm': center[k]+sign*size[k]/2
            for k,axis in enumerate('xyz') for end,sign in (('min',-1),('max',1))}


def prepare_field_design(multipoles: dict[str, dict], oatof: dict, geometry: dict, *,
                         variant_id: str, pulse_voltage_policy_id: str,
                         boundary_policy: str, frontend_domains: dict,
                         rf_reference_voltage_v: float | None = None, flight: dict | None = None) -> dict:
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
    electrical = resolve_accelerator_electrical_design(oatof, variant_id=variant_id)
    multipole_ids, ids = frontend_electrode_maps(geometry)
    operating = electrical['operating_voltages_v']
    on = {ids['accelerator_'+role+'_id']: operating[role]
          for role in ('repeller','grid1','intermediate2','grid2')}
    on.update(zip(ids['accelerator_ring_ids'], operating['rings'], strict=True))
    ground_ids = [ids['grounded_shield_id']]
    on.update({key: 0. for key in ground_ids})
    # Ground is a declared model constraint, not an inferred aperture potential.
    if operating['shield'] != 0:
        raise ValueError("OA field design requires the provider shield to be grounded")
    region = dict(pulse_voltage_policy_id=POLICY,
                  off_voltages_v={key:0. for key in on}, operating_voltages_v=on)
    physical_ids = set(on)
    carrier = {key: 0. for key in physical_ids}
    rf_groups = {}
    for instance_id in multipole_instances:
        values, groups = physical_multipole_voltages(multipoles[instance_id], multipole_ids[instance_id])
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
                      multipole_ids: dict[str, dict[int, int]], ids: dict, *, entrance: bool) -> list[dict]:
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
        view = physical_electrode_view(upstream)
        if set(mapping) != {row['native_electrode_id'] for row in view}:
            raise ValueError(f'{instance_id}: physical electrode binding must cover every provider group')
        rods = segmented_through_exit_rod_pieces(upstream)
        for rod in rods:
            electrode = mapping[rod['electrode_id']]
            physical.append(dict(label=f'segment_{rod["segment_id"]}_rod_{rod["parent_rod_id"]}_e{electrode}',
                kind='rod', electrode_id=electrode, segment_id=rod['segment_id'], parent_rod_id=rod['parent_rod_id'],
                gu=cylinder_sample(rod, rotation, translation, origin, pitch, dimensions)))
        enclosure = upstream['geometry_mm']['enclosure']
        inner, outer = enclosure['shield_inner_radius_mm'], enclosure['shield_outer_radius_mm']
        static_rows = [row for row in view if row['voltage_source']['kind'] == 'static']
        for row in static_rows:
            roles = set(row['roles'])
            if 'entrance_reference_sleeve' in roles:
                sleeve = upstream['axial_dc']['entrance_reference_sleeve']
                radial_low, radial_high = sleeve['inner_radius_mm'], sleeve['outer_radius_mm']
                zlo, zhi = sleeve['upstream_face_z_mm'], sleeve['downstream_face_z_mm']
            elif 'shield' in roles:
                radial_low, radial_high = inner, outer
                zlo, zhi = enclosure['entrance_outer_endcap_downstream_face_z_mm'], enclosure['exit_outer_endcap_upstream_face_z_mm']
            elif roles & {'exit_aperture_plate', 'entrance_aperture_plate'}:
                # Mating endcap faces can belong to the adjacent component.
                # Audit this electrode on its own internal aperture plate.
                side = 'exit' if 'exit_aperture_plate' in roles else 'entrance'
                interface = upstream['interfaces_mm'][side]
                radial_low, radial_high = interface['aperture_radius_mm'], outer
                zlo, zhi = interface['aperture_plate_upstream_face_z_mm'], interface['aperture_plate_downstream_face_z_mm']
            else:
                raise ValueError(f'{instance_id}: no supported static metal sample for roles {sorted(roles)}')
            gu, _ = sample_node([(radial_low + radial_high) / 2, 0, (zlo + zhi) / 2], rotation, translation, origin, pitch, dimensions)
            physical.append(dict(label=f'static_e{mapping[row["native_electrode_id"]]}', kind='static',
                                 electrode_id=mapping[row['native_electrode_id']], gu=gu))
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
