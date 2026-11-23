"""Test-owned provider with ordinary neutral box/union geometry."""
from msplatform.components.registry import ProviderDescriptor
from msplatform.contracts.machine_contracts import ContractError

def resolve(source,profile):
    if set(source)!={'width_mm'} or type(source['width_mm']) not in (int,float) or source['width_mm']<=0:
        raise ContractError('toy width must be explicitly positive')
    width=source['width_mm']
    interface=dict(schema_version=3,role='component_geometry_interface',project_id='toy_registered',variant_id='box_union',
        geometry_profile_id=profile,local_frame_id='toy_local',length_unit='mm',
        ports={'out':dict(surface_kind='aperture_outer_face',center_mm=[0,0,width/2],outward_normal=[0,0,1],
            wall_thickness_mm=1,cross_section=dict(shape='rectangle',width_mm=1,height_mm=1,width_axis=[1,0,0],height_axis=[0,1,0]))},
        component_electrodes=[dict(electrode_group_id='body',role='body')])
    return dict(width_mm=width),interface

def validate(source,resolved,interface):
    expected,expected_interface=resolve(source,interface.get('geometry_profile_id'))
    if (expected,expected_interface)!=(resolved,interface):raise ContractError('toy source or interface mismatch')

def members(resolved,interface):
    width=resolved['width_mm']
    box=lambda center:dict(kind='box',center_mm=center,size_mm=[width,width,width])
    return [dict(member_id='body',electrode_group_id='body',shape=dict(kind='union',parts=[box([0,0,0]),box([width,0,0])]),
        source_refs=['/width_mm'],local_frame_id='toy_local',length_unit='mm',representation_role='physical_solid')]

DESCRIPTOR=ProviderDescriptor('toy_registered','toy_registered',resolve,validate,members,('tests.contracts.test_support.registered_component',))


def ensure_registered():
    """Register this test descriptor once without masking foreign registrations."""
    from msplatform.components.registry import provider_descriptor, register_provider
    try:
        existing = provider_descriptor(DESCRIPTOR.provider_id)
    except ContractError:
        register_provider(DESCRIPTOR)
    else:
        if existing is not DESCRIPTOR:
            raise ContractError('toy provider already bound to another descriptor')
