"""Canonical complete MR analyzer members, without its separately selected OA."""
from __future__ import annotations
import copy
from .assembly_interface import _component_electrodes, _scientific_groups


def _box(values):
    if not isinstance(values, list) or len(values) != 6:
        raise ValueError('MR physical box requires six bounds')
    return dict(kind='box',center_mm=[(values[i]+values[i+3])/2 for i in range(3)],
                size_mm=[values[i+3]-values[i] for i in range(3)])


def _polygon(x, points):
    return dict(kind='extruded_yz_polygon',x=copy.deepcopy(x),polygon_yz_mm=copy.deepcopy(points))


def _solid(row):
    if 'polygon_yz_mm' in row:
        base=_polygon(row['x'],row['polygon_yz_mm'])
        tools=[_polygon(h['x'],h['polygon_yz_mm']) for h in row.get('holes',[])]
    elif 'box' in row:
        base=_box(row['box']);tools=[_box(row['beam_slot'])] if 'beam_slot' in row else []
    else:
        raise ValueError('unsupported MR physical solid')
    return dict(kind='difference',base=base,tools=tools) if tools else base


def _union(parts):
    if not parts:raise ValueError('MR physical group cannot be empty')
    return parts[0] if len(parts)==1 else dict(kind='union',parts=parts)


def _subtract(base,tools):
    return dict(kind='difference',base=base,tools=tools) if tools else base


def iter_geometry_members(resolved):
    """Keep real MR conductor ownership, complete source geometry and holes."""
    rows=_component_electrodes(resolved);groups=_scientific_groups(resolved,rows)
    names={row['component_electrode_id']:group['electrode_group_id'] for row,group in zip(rows,groups,strict=False)}
    frame=resolved['frame_id'];members=[]
    def add(identity,group,shape,refs):
        members.append(dict(member_id=identity,electrode_group_id=group,shape=shape,source_refs=refs,
            local_frame_id=frame,length_unit='mm',representation_role='physical_solid'))
    for family in ('mirror_electrodes','mirror_e_closures'):
        for i,row in enumerate(resolved[family]):
            add(f'{family}/{i}',names[row['id']],_solid(row),[f'/{family}/{i}'])
    for i,row in enumerate(resolved['mirror_ground_shields']):
        shape=_solid(row);refs=[f'/mirror_ground_shields/{i}']
        if 'polygon_yz_mm' not in row and row['role']=='inner_stripe_facing_4mm_slot':
            shape=_subtract(shape,[_box(resolved['mirror_inner_shield_slot'])]);refs.append('/mirror_inner_shield_slot')
        add(f'mirror_ground_shields/{i}',('positive_mirror_ground_shield','negative_mirror_ground_shield')[i],shape,refs)
    for i,row in enumerate(resolved['stripe_electrodes']):
        body=_union([_polygon(row['x'],row['polygon_yz_mm']),_polygon(row['x'],row['terminal_polygon_yz_mm'])])
        add(f'stripe_electrodes/{i}',names[row['id']],_subtract(body,[_box(resolved['stripe_slot'])]),
            [f'/stripe_electrodes/{i}','/stripe_slot'])
    central=_union([_polygon(row['x'],row['polygon_yz_mm']) for row in resolved['central_ground_electrodes']])
    add('central_ground_electrodes','central_ground',_subtract(central,[_box(x) for x in resolved['central_ground_slots']]),
        ['/central_ground_electrodes','/central_ground_slots'])
    for i,row in enumerate(resolved['prism_electrodes']):
        add(f'prism_electrodes/{i}',names[row['id']],_union([_polygon(p['x'],p['polygon_yz_mm']) for p in row['parts']]),[f'/prism_electrodes/{i}'])
    for i,row in enumerate(resolved['prism_ground_shields']):
        body=_union([_polygon(p['x'],p['polygon_yz_mm']) for p in row['body_sections']])
        cuts=[_polygon(row['x'],row['prism_clearance_polygon_yz_mm'])]+[_box(x) for x in row.get('rectangular_slots_mm',[])]
        add(f'prism_ground_shields/{i}',names[row['id']],_subtract(body,cuts),[f'/prism_ground_shields/{i}'])
    add('detector',names[resolved['detector']['id']],_box(resolved['detector']['box']),['/detector'])
    if {m['electrode_group_id'] for m in members}!={g['electrode_group_id'] for g in groups}:
        raise ValueError('MR physical member coverage differs from canonical groups')
    return tuple(members)