"""Dual-cone provider-local Assembly capabilities."""
from msplatform.components.registry import ProviderDescriptor
from msplatform.contracts.machine_contracts import ContractError

def resolve(design,profile):
    from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry import resolve_geometry
    from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.assembly_interface import build_assembly_interface
    resolved=resolve_geometry(design)
    return resolved,build_assembly_interface(resolved,geometry_profile_id=profile)

def validate(source,resolved,interface):
    from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry import resolve_geometry
    from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.assembly_interface import build_assembly_interface
    canonical=build_assembly_interface(resolved,geometry_profile_id=interface.get('geometry_profile_id'))
    if (source.get('role')!='dual_cone_tandem_quadrupole_geometry_baseline' or source.get('schema_version')!=1
            or source.get('project_id')!='dual_cone_tandem_quadrupole_ion_interface'
            or resolve_geometry(dict(source))!=resolved or canonical!=interface):
        raise ContractError('dual-cone resolved geometry or interface differs from explicit source')

def members(resolved,interface):
    from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry_members import iter_geometry_members
    return iter_geometry_members(resolved)

DESCRIPTOR=ProviderDescriptor('dual_cone_tandem_quadrupole','dual_cone_tandem_quadrupole_ion_interface',resolve,validate,members,('msplatform.components.dual_cone_tandem_quadrupole_ion_interface','msplatform.components.rf_multipole'))
