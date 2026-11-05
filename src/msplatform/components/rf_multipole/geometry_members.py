"""Physical multipole members projected from the unique resolved rod/body tables."""
from __future__ import annotations
import copy
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology


def iter_geometry_members(resolved):
    """Return every actual rod piece and declared shell/cap, never native IDs."""
    groups=build_electrode_topology(resolved)
    result=[]
    for group in groups:
        for pointer in group['member_refs']:
            value=resolved
            for key in pointer.split('/')[1:]: value=value[int(key)] if isinstance(value,list) else value[key]
            row=copy.deepcopy(value)
            if group['electrode_group_id']=='grounded_shell':
                shape=dict(kind='annulus',center_xy_mm=[0,0],z_min_mm=row['z_min_mm'],z_max_mm=row['z_max_mm'],inner_radius_mm=row['inner_radius_mm'],outer_radius_mm=row['outer_radius_mm'])
            else:
                shape=dict(kind='rod',center_xy_mm=[row['center_x_mm'],row['center_y_mm']],z_min_mm=row['z_min_mm'],z_max_mm=row['z_max_mm'])
                if 'radius_mm' in row:
                    if any(k in row for k in ('semi_major_axis_mm','semi_minor_axis_mm','major_axis_angle_rad')):
                        raise ValueError('rod mixes round and ellipse fields')
                    shape['radius_mm']=row['radius_mm']
                else:
                    shape.update({k:row[k] for k in ('semi_major_axis_mm','semi_minor_axis_mm','major_axis_angle_rad')})
            result.append(dict(member_id=pointer,electrode_group_id=group['electrode_group_id'],source_refs=[pointer],
                shape=shape,representation_role='physical_solid',local_frame_id=resolved['coordinate']['coordinate_id'],length_unit='mm'))
    return tuple(result)
