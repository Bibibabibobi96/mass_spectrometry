"""Project interface dispatch with explicit legacy native projection."""
from msplatform.components.single_reflection_oa_tof.assembly_interface import resolve_assembly_interface as _resolve_current
from msplatform.backends.simion.tof_assembly_interface import resolve_legacy_assembly_interface


def resolve_assembly_interface(resolved, *, projection, geometry_profile_id, schema_version=3):
    if type(schema_version) is not int or schema_version not in (1, 3):
        raise ValueError("oaTOF assembly interface requires explicit schema_version 1 or 3")
    implementation = _resolve_current if schema_version == 3 else resolve_legacy_assembly_interface
    return implementation(resolved, projection=projection, geometry_profile_id=geometry_profile_id, schema_version=schema_version)
