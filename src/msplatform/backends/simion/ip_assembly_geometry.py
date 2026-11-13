"""Render an explicitly selected IP physical body for a joint SIMION domain."""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from msplatform.backends.simion.ip_geometry import render_projection_electrodes
from msplatform.backends.simion.rf_electrode_mapping import SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
from msplatform.components.dual_pressure_rectilinear_ion_processor.assembly_interface import build_assembly_interface
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import select_legacy_physical_design


def render_selected_ip_body(
    selected: Mapping[str, Any], *, baseline: Mapping[str, Any], native_ids: Mapping[str, int],
) -> tuple[str, dict[str, int]]:
    """Render all selected CSG in local mm with explicit scientific-to-native IDs.

    The caller owns pose, PA domain, collision-free IDs across components, field
    solving and source tracking. No numerical domain or operating voltage is chosen.
    """
    if not isinstance(baseline, Mapping) or not isinstance(selected, Mapping):
        raise ValueError("selected IP design and baseline must be mappings")
    choice = baseline.get("physical_design_selection")
    if not isinstance(choice, dict) or set(choice) != {"native_grid_mm", "native_aux_segments"}:
        raise ValueError("IP body requires an explicit physical design selection")
    expected = select_legacy_physical_design(dict(baseline), selection_grid_mm=choice["native_grid_mm"],
                                             auxiliary_segments=choice["native_aux_segments"])
    if json.dumps(selected, sort_keys=True, separators=(",", ":"), allow_nan=False) != json.dumps(
            expected, sort_keys=True, separators=(",", ":"), allow_nan=False):
        raise ValueError("selected IP physical design differs from its source authority")
    interface = build_assembly_interface(expected)
    groups = [row["electrode_group_id"] for row in interface["component_electrodes"]]
    if not isinstance(native_ids, Mapping) or set(native_ids) != set(groups):
        raise ValueError("IP native IDs must cover all physical electrode groups")
    ids = [native_ids[group] for group in groups]
    if any(type(value) is not int or not 1 <= value <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("IP native IDs must be distinct valid adjustable electrodes")
    projection = copy.deepcopy(expected["projection"])
    for row in projection["electrodes"]:
        row["electrode_id"] = native_ids[row["name"]]
    return render_projection_electrodes(projection), {group: native_ids[group] for group in groups}
