"""Downstream physical and ideal members from the shared TOF projection."""
from __future__ import annotations


def iter_downstream_members(physical, *, frame):
    """Convert validated physical geometry to canonical members in the supplied frame."""
    result = []
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
            shape=shape,representation_role=kind,local_frame_id=frame,length_unit='mm',
            source_refs=['/geometry_mm','/coordinate_convention','/rings']))
    return tuple(result)
