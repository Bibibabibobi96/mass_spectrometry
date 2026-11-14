"""RF provider-local Assembly capabilities."""
from msplatform.components.registry import ProviderDescriptor
from msplatform.contracts.machine_contracts import ContractError

def resolve(design,profile):
    from msplatform.components.rf_multipole.compile_design_request import compile_design_request
    from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
    resolved=compile_design_request(design,expected_identity=design['identity'])
    return resolved,build_assembly_interface(resolved,geometry_profile_id=profile)

def validate(source,resolved,interface):
    from msplatform.components.rf_multipole.compile_design_request import compile_design_request
    from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
    canonical=build_assembly_interface(resolved,geometry_profile_id=interface.get('geometry_profile_id'))
    expected=compile_design_request(source,expected_identity=resolved['identity'],source_records=resolved['sources'])
    if canonical!=interface or expected!=resolved:
        raise ContractError('RF resolved design or interface differs from explicit source')

def members(resolved,interface):
    from msplatform.components.rf_multipole.geometry_members import iter_geometry_members
    return iter_geometry_members(resolved)

DESCRIPTOR=ProviderDescriptor('rf_multipole','rf_multipole_ion_optics',resolve,validate,members,('msplatform.components.rf_multipole',))
