"""Resolve an explicitly selected IP physical design without solver state."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .assembly_interface import build_assembly_interface
from .native_geometry import select_legacy_physical_design


def resolve_component(design: Mapping[str, Any], *, geometry_profile_id: str | None = None) -> dict[str, Any]:
    """Resolve the complete selected metal and its real ports, without selecting a PA grid."""
    if not isinstance(design, Mapping) or set(design) != {"baseline"}:
        raise ValueError("IP design requires exactly the explicit baseline")
    baseline = copy.deepcopy(design["baseline"])
    if not isinstance(baseline, dict):
        raise ValueError("IP baseline must be a mapping")
    selection = baseline.get("physical_design_selection")
    if not isinstance(selection, dict) or set(selection) != {"native_grid_mm", "native_aux_segments"}:
        raise ValueError("IP provider requires an explicit physical design selection")
    if geometry_profile_id is not None:
        raise ValueError("IP provider uses the explicit selected physical design")
    selected = select_legacy_physical_design(
        baseline, selection_grid_mm=selection["native_grid_mm"],
        auxiliary_segments=selection["native_aux_segments"],
    )
    return {"resolved_design": selected,
            "assembly_interface": build_assembly_interface(selected, geometry_profile_id=geometry_profile_id)}
