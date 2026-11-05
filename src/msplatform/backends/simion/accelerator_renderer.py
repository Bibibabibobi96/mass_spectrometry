"""Emit resolved rectangular/circular two- or three-zone accelerator CSG.

All instrument placement, connections, PA decomposition and voltage plans remain
with the caller. This module has no integration dependency and starts no solver.
"""
from __future__ import annotations

from typing import Any
from msplatform.components.orthogonal_accelerator.geometry_members import sectioned_shapes

from msplatform.backends.simion.gem_primitives import centered_box3d as _box, cylinder_z as _cylinder_z


def render_accelerator_local_geometry(
    geometry: dict[str, Any],
    *,
    cell_x_mm: float,
    cell_z_mm: float,
    electrodes: dict[str, Any],
    render_intermediate2_sheet: bool = False,
    render_region: str = "whole_accelerator",
) -> list[str]:
    """Render accelerator geometry with native one-row ideal grids.

    SIMION treats a zero-grid-unit-thick electrode as one electrode-point row:
    it contributes to Refine but particles pass through it. A real wire mesh
    is a different physical profile and must not be routed through this helper.
    """
    grounded_shield_id = int(electrodes["grounded_shield_id"])
    repeller_id = int(electrodes["accelerator_repeller_id"])
    grid1_id = int(electrodes["accelerator_grid1_id"])
    ring_ids = [int(value) for value in electrodes["accelerator_ring_ids"]]
    grid2_id = int(electrodes["accelerator_grid2_id"])
    cross_section = str(geometry.get("cross_section", "square"))
    if cross_section not in {"square", "cylindrical"}:
        raise ValueError("accelerator cross section is unsupported")
    if render_region not in {"whole_accelerator", "entrance", "intermediate2", "directed_corridor"}:
        raise ValueError("accelerator local geometry region is unsupported")
    include_entrance = render_region in {"whole_accelerator", "entrance", "directed_corridor"}
    include_downstream = render_region == "whole_accelerator"
    shapes = sectioned_shapes(geometry)
    def emit(shape, *, padding_z=0., padding_x=0.):
        center=shape['center_mm']
        if shape['kind']=='box':
            size=list(shape['size_mm']);size[0]+=padding_x;size[2]+=padding_z
            return _box(*center,*size)
        return _cylinder_z(*center,shape['radius_mm'],shape['height_mm']+padding_z)
    entrance_lines = [
        f"  e({grounded_shield_id}) {{ fill {{",
        f"    within {{ {emit(shapes['shield_outer'])} }}",
        f"    notin {{ {emit(shapes['shield_cavity'],padding_z=2*cell_z_mm if cross_section=='cylindrical' else 0.)} }}",
        f"    notin_inside_or_on {{ {emit(shapes['side_opening'],padding_x=2*cell_x_mm)} }}",
        "  } }",
        f"  e({grounded_shield_id}) {{ fill {{ within {{ {emit(shapes['rear_cap'])} }} }} }}",
        f"  e({repeller_id}) {{ fill {{ within {{ {emit(shapes['repeller'])} }} }} }}",
        ("  ; Zero-grid-unit sheets are one-row ideal 100% transmission grids." if cross_section=='square' else
         "  ; Zero-grid-unit circular sheets are one-row ideal 100% transmission grids."),
        f"  e({grid1_id}) {{ fill {{ within {{ {emit(shapes['grid1'])} }} }} }}",
    ]
    lines = entrance_lines if include_entrance else []
    intermediate2_id = electrodes.get("accelerator_intermediate2_id")
    if intermediate2_id is not None and render_intermediate2_sheet:
        lines.append(
            f"  e({int(intermediate2_id)}) {{ fill {{ within {{ {emit(shapes['intermediate2'])} }} }} }}"
        )
    if include_downstream:
        for ring_index, ring in enumerate(shapes["rings"], 1):
            lines.extend(
                [
                    f"  e({ring_ids[ring_index-1]}) {{ fill {{",
                    f"    within {{ {emit(ring['outer'])} }}",
                    f"    notin {{ {emit(ring['inner'],padding_z=cell_z_mm)} }}",
                    "  } }",
                ]
            )
        lines.append(
            f"  e({grid2_id}) {{ fill {{ within {{ {emit(shapes['exit'])} }} }} }}"
        )
    return lines
