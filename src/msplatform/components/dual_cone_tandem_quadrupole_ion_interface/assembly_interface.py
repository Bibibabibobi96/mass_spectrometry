"""Real dual-cone aperture ports and electrical groups, without a solver mapping."""
from __future__ import annotations

from msplatform.contracts.machine_contracts import validate_schema
from .geometry_members import iter_geometry_members


def build_assembly_interface(resolved, *, geometry_profile_id=None):
    """Publish only the explicit declared cone-following physical profile."""
    profile = 'declared_cone_following_v1'
    if geometry_profile_id not in (None, profile):
        raise ValueError('unknown dual-cone geometry profile')
    geometry = resolved['geometry_mm']
    first, plate = geometry['first_cone'], geometry['downstream_aperture_plate']
    groups = dict.fromkeys(member['electrode_group_id'] for member in iter_geometry_members(resolved))
    result = dict(schema_version=3, role='component_geometry_interface',
        project_id=resolved['project_id'], variant_id='dual_cone_tandem_quadrupole',
        geometry_profile_id=profile, local_frame_id=resolved['coordinate_frame']['frame_id'], length_unit='mm',
        ports=dict(
            axial_entry=dict(surface_kind='aperture_outer_face',
                center_mm=[0., 0., first['aperture_reference_z_mm']], outward_normal=[0, 0, -1],
                cross_section=dict(shape='circle', radius_mm=first['aperture_radius_mm']),
                # A conical shell has no uniform straight aperture-wall thickness.
                wall_thickness_mm=None),
            axial_exit=dict(surface_kind='aperture_outer_face',
                center_mm=[0., 0., plate['downstream_face_z_mm']], outward_normal=[0, 0, 1],
                cross_section=dict(shape='circle', radius_mm=plate['aperture_radius_mm']),
                wall_thickness_mm=plate['thickness_mm'])),
        component_electrodes=[dict(electrode_group_id=group,
            role='rf_phase' if '_group_' in group else group) for group in groups])
    validate_schema(result, 'component_geometry_interface_v3.schema.json')
    return result
