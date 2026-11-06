"""Physical OA member views; no solver mesh, CAD kernel or host access."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import asdict
from msplatform.components.orthogonal_accelerator.two_zone_geometry import ClosedTwoZoneGeometry


def sectioned_shapes(g):
    """Project the existing sectioned physical construction in mm once.

    Mesh widening of a subtraction tool belongs to the consuming rasterizer.
    Cylinders/boxes use center and full spans, not a numerical grid origin.
    """
    x,y=float(g['axis_x_mm']),float(g['axis_y_mm'])
    square=g.get('cross_section','square')=='square'
    if g.get('cross_section','square') not in {'square','cylindrical'}:
        raise ValueError('unsupported OA physical cross section')
    def body(z,width,height):
        return dict(kind='box',center_mm=[x,y,z],size_mm=[width,width,height]) if square else dict(
            kind='cylinder',center_mm=[x,y,z],radius_mm=width/2,height_mm=height)
    rings=g.get('ring_z_mm')
    if rings is None:
        rings=[float(g['grid1_z_mm'])+i*float(g['ring_pitch_mm']) for i in range(1,int(g['ring_count'])+1)]
    if not isinstance(rings,list) or len(rings)!=int(g['ring_count']):
        raise ValueError('accelerator ring_z_mm must match ring_count')
    wall=float(g['shield_wall_mm'])
    result=dict(shield_outer=body(float(g['shield_center_z_mm']),float(g['shield_outer_width_mm']),float(g['shield_span_z_mm'])),
        shield_cavity=body(float(g['shield_center_z_mm']),float(g['shield_inner_width_mm']),float(g['shield_span_z_mm'])),
        side_opening=dict(kind='box',center_mm=[float(g['negative_x_face_mm'])+wall/2,float(g['port_center_y_mm']),float(g['port_center_z_mm'])],
                          size_mm=[wall,float(g['numerical_port_width_mm']),float(g['numerical_port_height_mm'])]),
        rear_cap=body(float(g['shield_back_z_mm'])+wall/2,float(g['shield_outer_width_mm']),wall),
        repeller=body(float(g['repeller_front_z_mm'])-float(g['repeller_thickness_mm'])/2,float(g['electrode_width_mm']),float(g['repeller_thickness_mm'])),
        grid1=body(float(g['grid1_z_mm']),float(g['electrode_width_mm']),0.),
        exit=body(float(g['grid2_z_mm']),float(g['shield_inner_width_mm']),0.),
        rings=[dict(outer=body(float(z),float(g['electrode_width_mm']),float(g['ring_thickness_mm'])),
                    inner=body(float(z),float(g['bore_width_mm']),float(g['ring_thickness_mm']))) for z in rings])
    if 'intermediate2_z_mm' in g:
        result['intermediate2']=body(float(g['intermediate2_z_mm']),float(g['electrode_width_mm']),0.)
    return result


def _member(identity,group,shape,refs,frame,role='physical_solid'):
    return dict(member_id=identity,electrode_group_id=group,shape=copy.deepcopy(shape),source_refs=list(refs),
                local_frame_id=frame,length_unit='mm',representation_role=role)


def iter_geometry_members(resolved):
    """Return complete mechanics and explicit ideal sheets/tools, without mutation."""
    if isinstance(resolved,ClosedTwoZoneGeometry) or (isinstance(resolved,Mapping) and resolved.get('role')=='orthogonal_accelerator_two_zone_geometry'):
        d=asdict(resolved) if isinstance(resolved,ClosedTwoZoneGeometry) else resolved
        e=d['enclosure'];frame='orthogonal_accelerator_exit_origin_v1'
        def box(x,y,z0,z1): return dict(kind='box',center_mm=[0,0,(z0+z1)/2],size_mm=[2*x,2*y,z1-z0])
        outer=box(e['guard_half_x_mm'],e['guard_half_y_mm'],d['local_exit_z_mm'],e['rear_cap_outer_z_mm'])
        cavity=box(e['guard_inner_half_x_mm'],e['guard_inner_half_y_mm'],d['local_exit_z_mm'],e['rear_cap_inner_z_mm'])
        tools=[cavity]
        if d['side_entry']:
            b=d['side_entry']['physical_cutout_box_mm'];tools.append(dict(kind='box',center_mm=[(b[i]+b[i+3])/2 for i in range(3)],size_mm=[b[i+3]-b[i] for i in range(3)]))
        result=[_member('grounded_shield','grounded_shield',dict(kind='difference',base=outer,tools=tools),['/enclosure','/side_entry','/local_exit_z_mm'],frame),
                _member('repeller','repeller',box(e['electrode_half_x_mm'],e['electrode_half_y_mm'],d['local_repeller_z_mm'],d['local_repeller_z_mm']+d['repeller_thickness_mm']),['/local_repeller_z_mm','/repeller_thickness_mm','/enclosure'],frame)]
        for index,s in enumerate(d['grid_supports']):
            group=('intermediate_grid_1','exit_grid')[index]
            shape=dict(kind='difference',base=box(s['outer_half_x_mm'],s['outer_half_y_mm'],s['front_z_mm'],s['back_z_mm']),
                       tools=[box(s['aperture_half_x_mm'],s['aperture_half_y_mm'],s['front_z_mm'],s['back_z_mm'])])
            result.append(_member(group+'_support',group,shape,[f'/grid_supports/{index}'],frame))
            result.append(_member(group+'_ideal_sheet',group,box(s['aperture_half_x_mm'],s['aperture_half_y_mm'],s['grid_z_mm'],s['grid_z_mm']),[f'/grid_supports/{index}'],frame,'ideal_surface'))
        for index,r in enumerate(d['rings']):
            z,t=r['center_z_mm'],r['thickness_z_mm']
            shape=dict(kind='difference',base=box(e['electrode_half_x_mm'],e['electrode_half_y_mm'],z-t/2,z+t/2),tools=[box(d['aperture_half_x_mm'],d['aperture_half_y_mm'],z-t/2,z+t/2)])
            result.append(_member(f'ring_{index+1:04d}',f'ring_{index+1:04d}',shape,[f'/rings/{index}','/enclosure','/aperture_half_x_mm','/aperture_half_y_mm'],frame))
        return tuple(result)
    if not isinstance(resolved,dict) or resolved.get('role') not in {'orthogonal_accelerator_sectioned_three_zone_geometry','instrument_sectioned_accelerator_mechanics_projection'}:
        raise ValueError('OA members require actual resolved two/three-zone mechanics')
    shapes=sectioned_shapes(resolved['geometry']);frame=resolved['coordinate_frame']
    shield=dict(kind='union',parts=[dict(kind='difference',base=shapes['shield_outer'],tools=[shapes['shield_cavity'],shapes['side_opening']]),shapes['rear_cap']])
    result=[_member('grounded_shield','grounded_shield',shield,['/geometry'],frame),_member('repeller','repeller',shapes['repeller'],['/canonical_electrodes/repeller'],frame)]
    for name,group in (('grid1','intermediate_grid_1'),('intermediate2','intermediate_grid_2'),('exit','exit_grid')):
        result.append(_member(name,group,shapes[name],['/canonical_electrodes/ideal_sheets'],frame,'ideal_surface'))
    for index,r in enumerate(shapes['rings']):
        result.append(_member(f'ring_{index+1:04d}',f'ring_{index+1:04d}',dict(kind='difference',base=r['outer'],tools=[r['inner']]),[f'/geometry/ring_z_mm/{index}','/geometry'],frame))
    return tuple(result)
