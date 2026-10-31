"""Explicit bare-guide adapter for the existing sectioned three-zone provider.

This is a geometry adapter, not a solver or an alternative accelerator model.
All dimensions and ring positions are authored. Existing sectioned rendering
owns the CSG, including its ideal sheets and negative-x side opening.
"""
from __future__ import annotations

import math
from typing import Any

from projects.orthogonal_accelerator.simion.sectioned_accelerator import render_accelerator_local_geometry


def render_bare_three_zone_electrode_body(resolved: dict[str, Any], *, cell_mm_xyz: dict[str, float],
                                          local_electrode_ids: dict[int, int]) -> list[str]:
    """Render the existing provider body in its native frame and explicit namespace."""
    if (not isinstance(resolved, dict) or resolved.get("role") != "orthogonal_accelerator_sectioned_three_zone_geometry"):
        raise ValueError("resolved sectioned three-zone geometry required")
    if set(cell_mm_xyz) != set("xyz") or any(isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) or v <= 0 for v in cell_mm_xyz.values()):
        raise ValueError("finite positive complete xyz grid required")
    g = resolved["geometry"]
    original = resolved["electrodes"]
    ids = {1, 2, 3, 4, 5, *original["accelerator_ring_ids"]}
    if (set(local_electrode_ids) != ids or any(type(v) is not int or v <= 0 for v in local_electrode_ids.values())
            or len(set(local_electrode_ids.values())) != len(ids)):
        raise ValueError("sectioned component namespace must map every physical electrode exactly once")
    electrodes = {k: [local_electrode_ids[i] for i in v] if isinstance(v, list) else local_electrode_ids[v]
                  for k, v in original.items()}
    return render_accelerator_local_geometry(g, cell_x_mm=cell_mm_xyz["x"], cell_z_mm=cell_mm_xyz["z"],
                                             electrodes=electrodes, render_intermediate2_sheet=True)
