"""orthogonal_accelerator provider-local Assembly capabilities."""
from msplatform.components.registry import ProviderDescriptor
from msplatform.contracts.machine_contracts import ContractError

def resolve(design, profile):
    from msplatform.components.orthogonal_accelerator.provider import resolve_component
    result = resolve_component(design, geometry_profile_id=profile)
    return result['resolved_design'], result['assembly_interface']

def validate(source, resolved, interface):
    expected, canonical = resolve(source, interface.get('geometry_profile_id'))
    if type(resolved.get('schema_version')) is not int or resolved.get('schema_version') != expected.get('schema_version'):
        raise ContractError('OA resolved design version differs from its explicit source')
    if canonical != interface or expected != resolved:
        raise ContractError('orthogonal_accelerator: resolved design or interface differs from its explicit source')

def members(resolved, interface):
    from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
    return iter_geometry_members(resolved)

DESCRIPTOR = ProviderDescriptor('orthogonal_accelerator', 'orthogonal_accelerator', resolve, validate, members, ('msplatform.components.orthogonal_accelerator',))
