"""Complete provider electrode identity and actual mechanical entry of oaTOF.

Physical IDs come from the provider's final design projection, independently of
native PA domains, solver electrode numbers and numerical detector markers.
"""
from __future__ import annotations

from typing import Any

from msplatform.components.single_reflection_oa_tof.accelerator_geometry import (
    ResolvedAcceleratorGeometry, _resolve_side_entry_port,
)


def resolve_assembly_interface(
    resolved: dict[str, Any], *, projection: ResolvedAcceleratorGeometry,
    geometry_profile_id: str | None, schema_version: int = 3,
) -> dict[str, Any]:
    """Publish the real outer side face of an already projected square shield.

    Coordinates are in the existing oatof_global frame, in mm. The exact region
    is also consumed by the native renderer; neither its geometry nor its port
    is reconstructed here. Missing ports, curved faces and conflicting geometry
    raise ValueError. No files are read/written and the projection is unchanged.
    """
    if type(schema_version) is not int or schema_version != 3:
        raise ValueError("oaTOF assembly interface requires schema_version 3")
    port = _resolve_side_entry_port(projection, geometry_profile_id=geometry_profile_id)
    if schema_version == 3:
        from msplatform.components.single_reflection_oa_tof.electrode_topology import build_electrode_topology
        topology = build_electrode_topology(resolved, projection=projection, geometry_profile_id=geometry_profile_id)
        component_electrodes = [dict(electrode_group_id=row["electrode_group_id"], role=row["roles"][0])
                                for row in topology["groups"]]
    return {
        "schema_version": schema_version, "role": "component_geometry_interface",
        "project_id": "single_reflection_oa_tof_mass_analyzer",
        "variant_id": projection.variant_id, "geometry_profile_id": geometry_profile_id,
        "local_frame_id": projection.local_frame_id, "length_unit": "mm",
        "ports": {"side_entry": port},
        "component_electrodes": component_electrodes,
    }
