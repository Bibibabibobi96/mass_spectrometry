"""parallel_mirror_dual_stripe_mr_tof provider-local Assembly capabilities."""
from msplatform.components.registry import ProviderDescriptor
import math
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members as oa_members
from msplatform.contracts.machine_contracts import ContractError

def resolve(design, profile):
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.provider import resolve_component
    result = resolve_component(design, geometry_profile_id=profile)
    return result['resolved_design'], result['assembly_interface']

def validate(source, resolved, interface):
    expected, canonical = resolve(source, interface.get('geometry_profile_id'))
    if canonical != interface or expected != resolved:
        raise ContractError('parallel_mirror_dual_stripe_mr_tof: resolved design or interface differs from its explicit source')

def members(resolved, interface):
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.geometry_members import iter_geometry_members
    return iter_geometry_members(resolved)

def validate_connections(mr, plan, components, sources, poses):
    """Match a connected real OA to MR authority; never synthesize one."""
    selected=set(plan['scope']['instance_ids'])
    edges=[edge for edge in plan['recipe']['connections'] if edge['connection_id'] in plan['scope']['connection_ids']]
    links=[edge for edge in edges if edge['downstream']=={'instance_id':mr,'port_id':'accelerator_entry'}
           and edge['upstream']['instance_id'] in selected
           and plan['components'][edge['upstream']['instance_id']]['project_id']=='orthogonal_accelerator'
           and edge['upstream']['port_id']=='axial_exit']
    if len(links)>1:raise ValueError('MR accelerator connection is ambiguous')
    if not links: return
    oa=links[0]['upstream']['instance_id']
    if oa_members(components[oa])!=oa_members(components[mr]['accelerator_component_geometry']):
        raise ValueError('selected canonical OA mechanics differ from MR matching authority')
    expected=sources[mr].get('accelerator_to_mr')
    if expected is not None:
        relative=RigidTransform.from_contract(poses[oa]).then(RigidTransform.from_contract(poses[mr]).inverse())
        declared=RigidTransform.from_contract(expected)
        if (relative.from_frame_id != declared.from_frame_id or relative.to_frame_id != declared.to_frame_id
                or any(not math.isclose(relative.rotation[i][j],declared.rotation[i][j],rel_tol=0,abs_tol=1e-12)
                       for i in range(3) for j in range(3))
                or any(not math.isclose(relative.translation_mm[i],declared.translation_mm[i],rel_tol=0,abs_tol=1e-12)
                       for i in range(3))):
            raise ValueError('MR frozen OA relative pose differs from actual assembly')

DESCRIPTOR = ProviderDescriptor('parallel_mirror_dual_stripe_mr_tof', 'parallel_mirror_dual_stripe_mr_tof', resolve, validate, members, ('msplatform.components.parallel_mirror_dual_stripe_mr_tof', 'msplatform.components.orthogonal_accelerator', 'msplatform.components.dual_pressure_rectilinear_ion_processor'), validate_connections)
