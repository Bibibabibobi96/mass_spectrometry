"""Provider-owned full-Assembly physical member traversal without backend kernels."""
from __future__ import annotations
import copy
import math
from collections.abc import Mapping
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.catalog import _from_provider
from msplatform.components.rf_multipole.geometry_members import iter_geometry_members as rf_members
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members as oa_members
from msplatform.components.single_reflection_oa_tof.geometry_members import iter_geometry_members as tof_members

def assembly_geometry_members(assembly: Mapping) -> tuple[dict, ...]:
    """Resolve full selected member coverage without importing a CAD engine.

    Local shapes are retained; the proper local-to-assembly transform is applied
    once only by the exporter. Source refs address the exact resolved snapshot.
    """
    if not isinstance(assembly,Mapping) or set(assembly)!={'composition_plan','components_resolved','components_source'}:
        raise ValueError('complete Assembly snapshot with component sources required')
    plan,components=assembly['composition_plan'],assembly['components_resolved']
    sources=assembly['components_source']
    selected=plan['scope']['instance_ids']
    if not selected or set(plan['components'])!=set(components) or set(sources)!=set(components):
        raise ValueError('complete parent Assembly source/resolved coverage differs')
    if compile_assembly_layout(plan['recipe'],plan['components'],local_scope=plan.get('local_scope'))!=plan:
        raise ValueError('CAD Assembly plan differs from its canonical parent layout')
    poses={row['instance_id']:row['transform'] for row in plan['recipe']['instances']}
    result=[]
    for instance in selected:
        interface=plan['components'][instance]
        project=interface['project_id'];resolved=components[instance]
        if project=='rf_multipole_ion_optics':
            provider='rf_multipole';members=rf_members(resolved)
        elif project=='orthogonal_accelerator':
            provider='orthogonal_accelerator';members=oa_members(resolved)
        elif project=='single_reflection_oa_tof_mass_analyzer':
            if interface['variant_id']!='three_zone_square': raise ValueError('complete TOF STEP requires three_zone_square')
            provider='single_reflection_oa_tof';members=tof_members(resolved)
        elif project=='dual_cone_tandem_quadrupole_ion_interface':
            from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry_members import iter_geometry_members
            provider='dual_cone_tandem_quadrupole';members=iter_geometry_members(resolved)
        elif project=='dual_pressure_rectilinear_ion_processor':
            provider='dual_pressure_rectilinear_ion_processor';members=_ip_members(resolved)
        elif project=='parallel_mirror_dual_stripe_mr_tof':
            from msplatform.components.parallel_mirror_dual_stripe_mr_tof.geometry_members import iter_geometry_members
            provider='parallel_mirror_dual_stripe_mr_tof';members=iter_geometry_members(resolved)
        else: raise ValueError('STEP provider not implemented: '+project)
        _from_provider(provider,resolved,interface,source_design=sources[instance])
        transform=RigidTransform.from_contract(poses[instance])
        if transform.from_frame_id!=interface['local_frame_id']: raise ValueError('CAD source frame differs from interface')
        identities=set()
        for member in members:
            if member['member_id'] in identities: raise ValueError('duplicate physical member identity')
            identities.add(member['member_id'])
            if member['local_frame_id']!=transform.from_frame_id: raise ValueError('member frame differs from its actual pose')
            if member['representation_role'] not in {'physical_solid','ideal_surface'}: raise ValueError('unknown physical representation')
            for ref in member['source_refs']:
                value=resolved
                for token in ref.split('/')[1:]: value=value[int(token)] if isinstance(value,(list,tuple)) else value[token]
            result.append(dict(copy.deepcopy(member),instance_id=instance,transform=copy.deepcopy(poses[instance])))
    _validate_connected_oa_mr(plan, components, sources, poses)
    return tuple(result)


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


def _validate_connected_oa_mr(plan, components, sources, poses):
    """Match a connected real OA to MR authority; never synthesize one."""
    selected=set(plan['scope']['instance_ids'])
    edges=[edge for edge in plan['recipe']['connections'] if edge['connection_id'] in plan['scope']['connection_ids']]
    for mr in selected:
        if plan['components'][mr]['project_id'] != 'parallel_mirror_dual_stripe_mr_tof':continue
        links=[edge for edge in edges if edge['downstream']=={'instance_id':mr,'port_id':'accelerator_entry'}
               and edge['upstream']['instance_id'] in selected
               and plan['components'][edge['upstream']['instance_id']]['project_id']=='orthogonal_accelerator'
               and edge['upstream']['port_id']=='axial_exit']
        if len(links)>1:raise ValueError('MR accelerator connection is ambiguous')
        if not links:continue
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
