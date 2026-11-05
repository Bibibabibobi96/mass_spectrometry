"""Explicit legacy TOF component1 projection; component3 stays provider-owned."""
from __future__ import annotations
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import _resolve_side_entry_port
from msplatform.components.single_reflection_oa_tof.assembly_interface import resolve_assembly_interface
from .tof_geometry import resolve_physical_geometry


def resolve_legacy_assembly_interface(resolved, *, projection, geometry_profile_id, schema_version=1):
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError("legacy oaTOF assembly interface requires explicit schema_version 1")
    port = _resolve_side_entry_port(projection, geometry_profile_id=geometry_profile_id)
    electrodes = [{key: item[key] for key in ("component_electrode_id", "role", "electrical_group_id")}
                  for item in resolve_physical_geometry(resolved, accelerator_projection=projection)["electrodes"]]
    return dict(schema_version=1, role="component_geometry_interface",
        project_id="single_reflection_oa_tof_mass_analyzer", variant_id=projection.variant_id,
        geometry_profile_id=geometry_profile_id, local_frame_id=projection.local_frame_id,
        length_unit="mm", ports={"side_entry":port}, component_electrodes=electrodes)


def resolve_provider_assembly_interface(resolved, *, projection, geometry_profile_id, schema_version=3):
    if type(schema_version) is int and schema_version == 3:
        return resolve_assembly_interface(resolved, projection=projection,
            geometry_profile_id=geometry_profile_id, schema_version=3)
    return resolve_legacy_assembly_interface(resolved, projection=projection,
        geometry_profile_id=geometry_profile_id, schema_version=schema_version)
