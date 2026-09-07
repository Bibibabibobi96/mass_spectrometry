"""Emit resolved rectangular/circular two- or three-zone accelerator CSG.

All instrument placement, connections, PA decomposition and voltage plans remain
with the caller. This module has no integration dependency and starts no solver.
"""
from __future__ import annotations

from typing import Any

from common.simion.gem_primitives import centered_box3d as _box, cylinder_z as _cylinder_z


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
    axis_x = float(geometry["axis_x_mm"])
    axis_y = float(geometry["axis_y_mm"])
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
    if cross_section == "square":
        entrance_lines = [
        f"  e({grounded_shield_id}) {{ fill {{",
        f"    within {{ {_box(axis_x, axis_y, float(geometry['shield_center_z_mm']), float(geometry['shield_outer_width_mm']), float(geometry['shield_outer_width_mm']), float(geometry['shield_span_z_mm']))} }}",
        f"    notin {{ {_box(axis_x, axis_y, float(geometry['shield_center_z_mm']), float(geometry['shield_inner_width_mm']), float(geometry['shield_inner_width_mm']), float(geometry['shield_span_z_mm']))} }}",
        f"    notin_inside_or_on {{ {_box(float(geometry['negative_x_face_mm'])+float(geometry['shield_wall_mm'])/2, float(geometry['port_center_y_mm']), float(geometry['port_center_z_mm']), float(geometry['shield_wall_mm'])+2*cell_x_mm, float(geometry['numerical_port_width_mm']), float(geometry['numerical_port_height_mm']))} }}",
        "  } }",
        f"  e({grounded_shield_id}) {{ fill {{ within {{ {_box(axis_x, axis_y, float(geometry['shield_back_z_mm'])+float(geometry['shield_wall_mm'])/2, float(geometry['shield_outer_width_mm']), float(geometry['shield_outer_width_mm']), float(geometry['shield_wall_mm']))} }} }} }}",
        f"  e({repeller_id}) {{ fill {{ within {{ {_box(axis_x,axis_y,float(geometry['repeller_front_z_mm'])-float(geometry['repeller_thickness_mm'])/2,float(geometry['electrode_width_mm']),float(geometry['electrode_width_mm']),float(geometry['repeller_thickness_mm']))} }} }} }}",
        "  ; Zero-grid-unit sheets are one-row ideal 100% transmission grids.",
        f"  e({grid1_id}) {{ fill {{ within {{ {_box(axis_x,axis_y,float(geometry['grid1_z_mm']),float(geometry['electrode_width_mm']),float(geometry['electrode_width_mm']),0.0)} }} }} }}",
        ]
        plate = lambda z, width: _box(axis_x, axis_y, z, width, width, 0.0)
        ring_outer = lambda z: _box(
            axis_x, axis_y, z, float(geometry["electrode_width_mm"]),
            float(geometry["electrode_width_mm"]), float(geometry["ring_thickness_mm"])
        )
        ring_inner = lambda z: _box(
            axis_x, axis_y, z, float(geometry["bore_width_mm"]),
            float(geometry["bore_width_mm"]), float(geometry["ring_thickness_mm"]) + cell_z_mm
        )
    else:
        outer_radius = float(geometry["shield_outer_width_mm"]) / 2.0
        inner_radius = float(geometry["shield_inner_width_mm"]) / 2.0
        electrode_radius = float(geometry["electrode_width_mm"]) / 2.0
        bore_radius = float(geometry["bore_width_mm"]) / 2.0
        entrance_lines = [
            f"  e({grounded_shield_id}) {{ fill {{",
            f"    within {{ {_cylinder_z(axis_x, axis_y, float(geometry['shield_center_z_mm']), outer_radius, float(geometry['shield_span_z_mm']))} }}",
            f"    notin {{ {_cylinder_z(axis_x, axis_y, float(geometry['shield_center_z_mm']), inner_radius, float(geometry['shield_span_z_mm']) + 2*cell_z_mm)} }}",
            f"    notin_inside_or_on {{ {_box(float(geometry['negative_x_face_mm'])+float(geometry['shield_wall_mm'])/2, float(geometry['port_center_y_mm']), float(geometry['port_center_z_mm']), float(geometry['shield_wall_mm'])+2*cell_x_mm, float(geometry['numerical_port_width_mm']), float(geometry['numerical_port_height_mm']))} }}",
            "  } }",
            f"  e({grounded_shield_id}) {{ fill {{ within {{ {_cylinder_z(axis_x, axis_y, float(geometry['shield_back_z_mm'])+float(geometry['shield_wall_mm'])/2, outer_radius, float(geometry['shield_wall_mm']))} }} }} }}",
            f"  e({repeller_id}) {{ fill {{ within {{ {_cylinder_z(axis_x, axis_y, float(geometry['repeller_front_z_mm'])-float(geometry['repeller_thickness_mm'])/2, electrode_radius, float(geometry['repeller_thickness_mm']))} }} }} }}",
            "  ; Zero-grid-unit circular sheets are one-row ideal 100% transmission grids.",
            f"  e({grid1_id}) {{ fill {{ within {{ {_cylinder_z(axis_x,axis_y,float(geometry['grid1_z_mm']),electrode_radius,0.0)} }} }} }}",
        ]
        plate = lambda z, width: _cylinder_z(axis_x, axis_y, z, width / 2.0, 0.0)
        ring_outer = lambda z: _cylinder_z(axis_x, axis_y, z, electrode_radius, float(geometry["ring_thickness_mm"]))
        ring_inner = lambda z: _cylinder_z(axis_x, axis_y, z, bore_radius, float(geometry["ring_thickness_mm"]) + cell_z_mm)
    lines = entrance_lines if include_entrance else []
    intermediate2_id = electrodes.get("accelerator_intermediate2_id")
    if intermediate2_id is not None and render_intermediate2_sheet:
        lines.append(
            f"  e({int(intermediate2_id)}) {{ fill {{ within {{ {plate(float(geometry['intermediate2_z_mm']), float(geometry['electrode_width_mm']))} }} }} }}"
        )
    ring_count = int(geometry["ring_count"])
    ring_z_mm = geometry.get("ring_z_mm")
    if ring_z_mm is None:
        ring_pitch = float(geometry["ring_pitch_mm"])
        ring_z_mm = [
            float(geometry["grid1_z_mm"]) + index * ring_pitch
            for index in range(1, ring_count + 1)
        ]
    if not isinstance(ring_z_mm, list) or len(ring_z_mm) != ring_count:
        raise ValueError("accelerator ring_z_mm must match ring_count")
    if include_downstream:
        for ring_index in range(1, ring_count + 1):
            ring_z = float(ring_z_mm[ring_index - 1])
            lines.extend(
                [
                    f"  e({ring_ids[ring_index-1]}) {{ fill {{",
                    f"    within {{ {ring_outer(ring_z)} }}",
                    f"    notin {{ {ring_inner(ring_z)} }}",
                    "  } }",
                ]
            )
        lines.append(
            f"  e({grid2_id}) {{ fill {{ within {{ {plate(float(geometry['grid2_z_mm']), float(geometry['shield_inner_width_mm']))} }} }} }}"
        )
    return lines
