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
    from msplatform.components.single_reflection_tof.geometry_members import iter_downstream_members
    result.extend(iter_downstream_members(physical, frame='oatof_global'))
    return tuple(result)
