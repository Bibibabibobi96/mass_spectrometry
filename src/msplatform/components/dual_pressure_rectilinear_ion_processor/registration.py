"""IP source-validated Assembly and complete physical-member capability."""
import copy
from msplatform.components.registry import ProviderDescriptor
from msplatform.contracts.machine_contracts import ContractError

def resolve(design, profile):
    from msplatform.components.dual_pressure_rectilinear_ion_processor.provider import resolve_component
    result=resolve_component(design,geometry_profile_id=profile)
    return result['resolved_design'],result['assembly_interface']

def validate(source,resolved,interface):
    expected,canonical=resolve(source,interface.get('geometry_profile_id'))
    if expected!=resolved or canonical!=interface:
        raise ContractError('IP resolved design or interface differs from explicit source')

def members(resolved,interface):
    return _ip_members(resolved)

def _ip_members(resolved):
    """Project the provider's selected electrode CSG, retaining each source record."""
    projection = resolved['projection']
    electrodes = projection['electrodes']
    if [row['electrode_id'] for row in electrodes] != list(range(1, 16)):
        raise ValueError('IP STEP requires its complete ordered 15 electrode groups')
    result = []
    for index, row in enumerate(electrodes):
        if set(row) != {'electrode_id', 'name', 'solids', 'cutouts'} or not row['solids']:
            raise ValueError('IP STEP electrode source is incomplete')
        def convert(shape):
            from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import shape_bounds
            shape_bounds(shape)
            return dict(kind='ip_'+shape['shape'], **{k: copy.deepcopy(v) for k,v in shape.items() if k != 'shape'})
        parts = [convert(shape) for shape in row['solids']]
        base = parts[0] if len(parts) == 1 else dict(kind='union', parts=parts)
        tools = [convert(shape) for shape in row['cutouts']]
        shape = dict(kind='difference', base=base, tools=tools) if tools else base
        result.append(dict(member_id=row['name'], electrode_group_id=row['name'], shape=shape,
            source_refs=[f'/projection/electrodes/{index}'], local_frame_id=projection['frame_id'],
            length_unit='mm', representation_role='physical_solid'))
    return tuple(result)


DESCRIPTOR=ProviderDescriptor('dual_pressure_rectilinear_ion_processor','dual_pressure_rectilinear_ion_processor',resolve,validate,members,('msplatform.components.dual_pressure_rectilinear_ion_processor','msplatform.components.rf_multipole'))
