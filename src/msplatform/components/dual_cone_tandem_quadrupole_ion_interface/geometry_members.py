"""Declared dual-cone metal bodies in the resolved device frame, independent of PA."""
from __future__ import annotations

import math


def cone_shell_profile(cone, truncation_radius_mm):
    """Return the existing shell polygon as (z,r) mm, with normal wall thickness.

    Both inner and outer conical faces terminate at the declared truncation
    radius. This is the sole profile consumed by CAD and the GEM renderer.
    """
    z0 = float(cone['aperture_reference_z_mm'])
    angle = math.radians(float(cone['half_angle_deg']))
    radius = float(truncation_radius_mm)
    inner0 = float(cone['aperture_radius_mm'])
    thickness = float(cone['wall_normal_thickness_mm'])
    if not all(math.isfinite(x) for x in (z0, angle, radius, inner0, thickness)):
        raise ValueError('cone shell dimensions must be finite')
    if not 0 < angle < math.pi / 2 or min(inner0, thickness) <= 0:
        raise ValueError('cone shell requires a positive aperture, thickness and acute half angle')
    slope = math.tan(angle)
    outer0 = inner0 + thickness / math.cos(angle)
    if radius <= outer0:
        raise ValueError('cone truncation must extend beyond the upstream outer shell')
    inner_z1 = z0 + (radius - inner0) / slope
    outer_z1 = z0 + (radius - outer0) / slope
    return ((z0, outer0), (outer_z1, radius), (inner_z1, radius), (z0, inner0))


def stage_1_cut_profile(resolved):
    """The declared axial-offset cone boundary; not the flat GEM C0 surrogate."""
    geometry = resolved['geometry_mm']
    stage = geometry['stage_1_elliptical_quadrupole']
    surface = stage['upstream_end_surface']
    if surface['model'] != 'second_cone_surface_plus_axial_offset':
        raise ValueError('unsupported declared stage-one upstream surface')
    base = (float(geometry['second_cone']['aperture_reference_z_mm'])
            + float(surface['axial_offset_mm']))
    end = float(stage['downstream_flat_end_z_mm'])
    slope = math.tan(math.radians(float(geometry['second_cone']['half_angle_deg'])))
    if not all(math.isfinite(x) for x in (base, end, slope)) or end <= base or slope <= 0:
        raise ValueError('declared cone-following rod interval is empty or invalid')
    return ((base, 0.), (end, 0.), (end, (end - base) * slope))


def iter_geometry_members(resolved):
    """Eleven actual metal bodies in seven groups; no enclosure or pump invented."""
    if (resolved.get('role') != 'dual_cone_tandem_quadrupole_resolved_geometry'
            or resolved.get('project_id') != 'dual_cone_tandem_quadrupole_ion_interface'):
        raise ValueError('current resolved dual-cone geometry required')
    geometry = resolved['geometry_mm']
    frame = resolved['coordinate_frame']['frame_id']
    radius = geometry['nested_cone_computational_closure']['truncation_radius_mm']
    members = []

    def member(identity, group, refs, shape):
        members.append(dict(member_id=identity, electrode_group_id=group,
            source_refs=refs, shape=shape, representation_role='physical_solid',
            local_frame_id=frame, length_unit='mm'))

    for name in ('first_cone', 'second_cone'):
        member(name, name, ['/geometry_mm/' + name,
            '/geometry_mm/nested_cone_computational_closure/truncation_radius_mm'],
            dict(kind='revolved_profile', points_zr_mm=cone_shell_profile(geometry[name], radius)))
    for stage_id, stage_name in ((1, 'stage_1_elliptical_quadrupole'), (2, 'stage_2_round_quadrupole')):
        stage = geometry[stage_name]
        for index, rod in enumerate(stage['rod_array']['rods']):
            shape = dict(kind='rod', center_xy_mm=[rod['center_x_mm'], rod['center_y_mm']],
                         z_min_mm=rod['z_min_mm'], z_max_mm=rod['z_max_mm'])
            if stage_id == 1:
                shape.update({key: rod[key] for key in
                    ('semi_major_axis_mm', 'semi_minor_axis_mm', 'major_axis_angle_rad')})
                shape = dict(kind='intersection', parts=[shape,
                    dict(kind='revolved_profile', points_zr_mm=stage_1_cut_profile(resolved))])
            else:
                shape['radius_mm'] = rod['radius_mm']
            pointer = f'/geometry_mm/{stage_name}/rod_array/rods/{index}'
            refs = [pointer]
            if stage_id == 1:
                refs.extend(['/geometry_mm/' + stage_name + '/upstream_end_surface',
                             '/geometry_mm/second_cone/half_angle_deg',
                             '/geometry_mm/second_cone/aperture_reference_z_mm'])
            member(f'stage_{stage_id}/rod_{rod["rod_id"]:04d}',
                f'stage_{stage_id}_group_{rod["electrode_group"]}', refs, shape)
    plate = geometry['downstream_aperture_plate']
    member('downstream_aperture_plate', 'downstream_aperture_plate',
        ['/geometry_mm/downstream_aperture_plate'], dict(kind='annulus', center_xy_mm=[0., 0.],
            z_min_mm=plate['upstream_face_z_mm'], z_max_mm=plate['downstream_face_z_mm'],
            inner_radius_mm=plate['aperture_radius_mm'], outer_radius_mm=plate['outer_radius_mm']))
    return tuple(members)
