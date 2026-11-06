"""Validated assembly construction from explicit recipes and provider objects."""
from __future__ import annotations

import copy
from collections.abc import Mapping

from msplatform.contracts.machine_contracts import ContractError
from msplatform.components.model import ResolvedComponent
from msplatform.components.catalog import _from_provider
from .model import Assembly
from .resolve_assembly import compile_assembly_layout


def assemble(recipe: Mapping[str, object], components: Mapping[str, ResolvedComponent], *,
             local_scope: Mapping[str, object] | None = None) -> Assembly:
    """Compile the explicit parent recipe through the canonical assembly validator."""
    if not components or any(not isinstance(value, ResolvedComponent) for value in components.values()):
        raise ContractError("assembly components must be resolved provider objects")
    for value in components.values():
        _from_provider(value.provider_id, value.resolved_design, value.assembly_interface,
                       source_design=value.source_design)
    interfaces = {name: copy.deepcopy(dict(value.assembly_interface)) for name, value in components.items()}
    plan = compile_assembly_layout(copy.deepcopy(dict(recipe)), interfaces, local_scope=copy.deepcopy(local_scope))
    return Assembly(plan, components)
