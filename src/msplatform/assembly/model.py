"""Complete assembly data with independent views and no execution state."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from msplatform.contracts.machine_contracts import ContractError
from msplatform.components.model import ResolvedComponent
from msplatform.components.catalog import _from_provider
from .resolve_assembly import compile_assembly_layout


@dataclass(frozen=True, init=False)
class Assembly:
    """The complete canonical parent plan plus the corresponding provider designs."""

    _composition_plan: dict[str, Any]
    _components: dict[str, ResolvedComponent]

    def __init__(self, composition_plan: Mapping[str, Any], components: Mapping[str, ResolvedComponent]):
        if not isinstance(composition_plan, Mapping) or not components:
            raise ContractError("assembly requires a parent plan and complete resolved components")
        if any(not isinstance(value, ResolvedComponent) for value in components.values()):
            raise ContractError("assembly requires complete resolved component objects")
        for value in components.values():
            _from_provider(value.provider_id, value.resolved_design, value.assembly_interface,
                           source_design=value.source_design)
        plan = copy.deepcopy(dict(composition_plan))
        interfaces = {name: value.assembly_interface for name, value in components.items()}
        canonical = compile_assembly_layout(plan["recipe"], interfaces, local_scope=plan.get("local_scope"))
        if plan != canonical:
            raise ContractError("assembly layout differs from its complete component designs")
        object.__setattr__(self, "_composition_plan", plan)
        object.__setattr__(self, "_components", copy.deepcopy(dict(components)))

    @property
    def composition_plan(self) -> dict[str, Any]:
        return copy.deepcopy(self._composition_plan)

    @property
    def components(self) -> dict[str, ResolvedComponent]:
        return copy.deepcopy(self._components)

    @property
    def components_resolved(self) -> dict[str, dict[str, Any]]:
        return {name: value.resolved_design for name, value in self._components.items()}
