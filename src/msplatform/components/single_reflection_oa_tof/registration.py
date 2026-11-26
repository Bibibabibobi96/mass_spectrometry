"""single_reflection_oa_tof provider-local Assembly capabilities."""
from msplatform.components.registry import ProviderDescriptor
from msplatform.contracts.machine_contracts import ContractError

def resolve(design, profile):
    from msplatform.components.single_reflection_oa_tof.provider import resolve_component
    result = resolve_component(design, geometry_profile_id=profile)
    return result['resolved_design'], result['assembly_interface']

def validate(source, resolved, interface):
    expected, canonical = resolve(source, interface.get('geometry_profile_id'))
    if type(resolved.get('schema_version')) is not int or resolved.get('schema_version') != expected.get('schema_version'):
        raise ContractError('TOF resolved design version differs from its explicit source')
    if canonical != interface or expected != resolved:
        raise ContractError('single_reflection_oa_tof: resolved design or interface differs from its explicit source')

def members(resolved, interface):
    if interface.get('variant_id') != 'three_zone_square': raise ValueError('complete TOF STEP requires three_zone_square')
    from msplatform.components.single_reflection_oa_tof.geometry_members import iter_geometry_members
    return iter_geometry_members(resolved)

DESCRIPTOR = ProviderDescriptor('single_reflection_oa_tof', 'single_reflection_oa_tof_mass_analyzer', resolve, validate, members, ('msplatform.components.single_reflection_oa_tof', 'msplatform.components.orthogonal_accelerator', 'msplatform.components.rf_multipole', 'msplatform.components.single_reflection_tof'))
