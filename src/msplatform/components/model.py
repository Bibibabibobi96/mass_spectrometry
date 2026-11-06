"""Provider-neutral resolved component data with independent value views."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from msplatform.contracts.machine_contracts import ContractError


@dataclass(frozen=True, init=False)
class ResolvedComponent:
    """A complete design and interface validated together by the provider factory."""

    provider_id: str
    _resolved_design: dict[str, Any]
    _assembly_interface: dict[str, Any]
    _source_design: dict[str, Any] | None

    def __init__(self, provider_id: str, resolved_design: Mapping[str, Any],
                 assembly_interface: Mapping[str, Any], *, source_design: Mapping[str, Any] | None = None):
        if not isinstance(provider_id, str) or not provider_id:
            raise ContractError("component provider_id must be a nonempty string")
        if not isinstance(resolved_design, Mapping) or not isinstance(assembly_interface, Mapping):
            raise ContractError("component design and assembly interface must be mappings")
        if source_design is not None and not isinstance(source_design, Mapping):
            raise ContractError("component source_design must be a mapping when supplied")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "_resolved_design", copy.deepcopy(dict(resolved_design)))
        object.__setattr__(self, "_assembly_interface", copy.deepcopy(dict(assembly_interface)))
        object.__setattr__(self, "_source_design",
                           copy.deepcopy(dict(source_design)) if source_design is not None else None)

    @property
    def resolved_design(self) -> dict[str, Any]:
        return copy.deepcopy(self._resolved_design)

    @property
    def assembly_interface(self) -> dict[str, Any]:
        return copy.deepcopy(self._assembly_interface)

    @property
    def source_design(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._source_design)

    def port(self, port_id: str) -> dict[str, Any]:
        """Return a local-frame port view suitable for explicit mating."""
        if port_id not in self.assembly_interface["ports"]:
            raise ContractError(f"{self.provider_id} has no declared port: {port_id}")
        return {**copy.deepcopy(self.assembly_interface["ports"][port_id]),
                "frame_id": self.assembly_interface["local_frame_id"]}
