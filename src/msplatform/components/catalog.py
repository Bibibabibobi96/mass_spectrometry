"""Registered provider dispatch and cross-object component validation."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from msplatform.contracts.machine_contracts import ContractError
from .model import ResolvedComponent
from .registry import provider_descriptor


def _from_provider(provider: str, resolved: Mapping[str, Any], interface: Mapping[str, Any],
                   *, source_design: Mapping[str, Any]) -> ResolvedComponent:
    """Revalidate a complete provider object against its source and interface."""
    descriptor = provider_descriptor(provider)
    if not isinstance(resolved, Mapping) or not isinstance(interface, Mapping) or not isinstance(source_design, Mapping):
        raise ContractError('provider design, interface and source must be mappings')
    design = copy.deepcopy(dict(resolved))
    canonical = copy.deepcopy(dict(interface))
    source = copy.deepcopy(dict(source_design))
    if canonical.get('project_id') != descriptor.project_id:
        raise ContractError('registered provider project differs from its interface')
    before = copy.deepcopy((source, design, canonical))
    descriptor.validate(source, design, canonical)
    if (source, design, canonical) != before:
        raise ContractError('provider validation mutated its input authorities')
    return ResolvedComponent(provider, design, canonical, source_design=source)


def resolve_component(request: Mapping[str, Any]) -> ResolvedComponent:
    """Resolve one explicitly registered provider without execution or discovery."""
    required = {'provider_id', 'design'}
    if not isinstance(request, Mapping) or not required <= request.keys() or set(request)-required-{'geometry_profile_id'}:
        raise ContractError('component request requires provider_id and design; only geometry_profile_id is optional')
    descriptor = provider_descriptor(request['provider_id'])
    source = copy.deepcopy(request['design'])
    before = copy.deepcopy(source)
    design, interface = descriptor.resolve(source, request.get('geometry_profile_id'))
    if source != before:
        raise ContractError('provider resolver mutated its source authority')
    return _from_provider(descriptor.provider_id, design, interface, source_design=source)
