"""Public SIMION operations over complete domain objects."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from msplatform.assembly.model import Assembly
from msplatform.contracts.machine_contracts import ContractError
from .compiler import CompiledSimionGeometry, compile_geometry as compile_simion_geometry


def compile_geometry(assembly: Assembly, *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile native geometry specifications only; no source, writes, solve or Fly."""
    if not isinstance(assembly, Assembly):
        raise ContractError("SIMION geometry compilation requires an explicitly assembled design")
    selected = assembly.composition_plan["scope"]["instance_ids"]
    compiled = compile_simion_geometry(
        {"composition_plan": copy.deepcopy(dict(assembly.composition_plan)),
         "components_resolved": {name: copy.deepcopy(assembly.components_resolved[name]) for name in selected}},
        numerics=copy.deepcopy(dict(numerics)),
    )
    return replace(compiled, components_resolved=assembly.components_resolved)
