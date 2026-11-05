"""Complete TOF physical CAD members from OA and downstream neutral authorities."""
from __future__ import annotations
import copy
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members as oa_members
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import resolve_accelerator_geometry, apply_side_opening, resolve_oa_provider
from msplatform.components.single_reflection_oa_tof.geometry_contract import resolve_electrode_geometry


def iter_geometry_members(resolved):
    """Return the complete three-zone square instrument; include OA exactly once.

    Physical solids and ideal sheets remain separate. The three-part grounded
    flight shield keeps both caps; no numerical detector marker is constructed.
    """
    projection=apply_side_opening(resolve_accelerator_geometry(resolved,variant_id='three_zone_square'),side_opening=resolved['mechanical_side_opening'])
    oa=resolve_oa_provider(resolved,projection=projection,geometry_profile_id=None)
    result=[]
    for member in oa_members(oa['mechanical']):
        row=copy.deepcopy(member)
        row['member_id']='accelerator/'+row['member_id'];row['local_frame_id']='oatof_global'
        row['source_refs']=['/geometry_mm','/geometry_derivation','/rings','/coordinate_convention','/accelerator_topology','/mechanical_side_opening']
        row['electrode_group_id']='common_ground' if row['electrode_group_id']=='grounded_shield' else 'accelerator_'+row['electrode_group_id']
        result.append(row)
    physical=resolve_electrode_geometry(resolved,accelerator_projection=projection)
    for index,body in enumerate(physical['electrodes']):
        role=body['role']
        if role.startswith('accelerator_'): continue
        g=body['geometry'];primitive=g['primitive'];kind='physical_solid'
        def cylindrical(region):
            return dict(kind='annulus',center_xy_mm=list(g['axis_xy_mm']),z_min_mm=region['axial_mm'][0],z_max_mm=region['axial_mm'][1],
                        inner_radius_mm=region['radius_mm'][0],outer_radius_mm=region['radius_mm'][1])
        if primitive=='cylindrical_union': shape=dict(kind='union',parts=[cylindrical(part) for part in g['parts']])
        elif primitive=='cylindrical_region':
            shape=cylindrical(g)
            if g['axial_mm'][0]==g['axial_mm'][1]: kind='ideal_surface'
        elif primitive=='cylinder':
            if g['axis']!=[0,0,1]: raise ValueError('unsupported detector physical axis')
            shape=dict(kind='cylinder',center_mm=[*g['base_center_mm'][:2],g['base_center_mm'][2]+g['height_mm']/2],radius_mm=g['radius_mm'],height_mm=g['height_mm'])
        else: raise ValueError('unknown TOF physical primitive')
        result.append(dict(member_id=role,electrode_group_id='common_ground' if body['grounded'] else role,
            shape=shape,representation_role=kind,local_frame_id='oatof_global',length_unit='mm',
            source_refs=['/geometry_mm','/coordinate_convention','/rings']))
    return tuple(result)
