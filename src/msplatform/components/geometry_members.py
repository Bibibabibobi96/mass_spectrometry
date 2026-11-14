"""Provider-owned full-Assembly physical member traversal without backend kernels."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.catalog import _from_provider
from msplatform.components.registry import project_descriptor
from msplatform.contracts.rigid_transform import RigidTransform


def assembly_geometry_members(assembly: Mapping[str, Any]) -> tuple[dict, ...]:
    """Resolve complete members and retain each explicit local-to-Assembly pose."""
    if not isinstance(assembly, Mapping) or set(assembly) != {'composition_plan', 'components_resolved', 'components_source'}:
        raise ValueError('complete Assembly snapshot with component sources required')
    plan, components = assembly['composition_plan'], assembly['components_resolved']
    sources = assembly['components_source']
    selected = plan['scope']['instance_ids']
    if not selected or set(plan['components']) != set(components) or set(sources) != set(components):
        raise ValueError('complete parent Assembly source/resolved coverage differs')
    if compile_assembly_layout(plan['recipe'], plan['components'], local_scope=plan.get('local_scope')) != plan:
        raise ValueError('CAD Assembly plan differs from its canonical parent layout')
    poses = {row['instance_id']: row['transform'] for row in plan['recipe']['instances']}
    result = []
    for instance in selected:
        interface = plan['components'][instance]
        resolved = components[instance]
        descriptor = project_descriptor(interface['project_id'])
        _from_provider(descriptor.provider_id, resolved, interface, source_design=sources[instance])
        member_source = copy.deepcopy(resolved)
        member_interface = copy.deepcopy(interface)
        members = tuple(descriptor.members(member_source, member_interface))
        if member_source != resolved or member_interface != interface:
            raise ValueError('provider member projection mutated its source')
        transform = RigidTransform.from_contract(poses[instance])
        if transform.from_frame_id != interface['local_frame_id']:
            raise ValueError('CAD source frame differs from interface')
        identities = set()
        for member in members:
            if member['member_id'] in identities:
                raise ValueError('duplicate physical member identity')
            identities.add(member['member_id'])
            if member['local_frame_id'] != transform.from_frame_id:
                raise ValueError('member frame differs from its actual pose')
            if member['representation_role'] not in {'physical_solid', 'ideal_surface'}:
                raise ValueError('unknown physical representation')
            for ref in member['source_refs']:
                value = resolved
                for token in ref.split('/')[1:]:
                    value = value[int(token)] if isinstance(value, (list, tuple)) else value[token]
            result.append(dict(copy.deepcopy(member), instance_id=instance, transform=copy.deepcopy(poses[instance])))
    for instance in selected:
        descriptor = project_descriptor(plan['components'][instance]['project_id'])
        if descriptor.validate_connections is not None:
            arguments = copy.deepcopy((plan, components, sources, poses))
            descriptor.validate_connections(instance, *arguments)
            if arguments != (plan, components, sources, poses):
                raise ValueError('provider connection validation mutated its source')
    return tuple(result)
