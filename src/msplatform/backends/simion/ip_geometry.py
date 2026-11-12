"""Render IP neutral electrode geometry as SIMION legacy GEM.

All dimensions are supplied in native local millimetres. This module performs
serialization only; it does not solve fields or place assembled components.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import convex_planes
from msplatform.backends.simion.gem_primitives import centered_box3d, format_number


def _represent_selected_ip_design(selected: dict, *, baseline: dict, grid_mm: float) -> dict:
    """Represent a freshly verified IP CSG at an independent PA pitch."""
    if (not isinstance(selected, dict) or set(selected) != {'schema_version', 'role', 'baseline_sha256', 'selection', 'projection'}
            or type(selected['schema_version']) is not int or selected['schema_version'] != 1
            or selected['role'] != 'ip_legacy_selected_physical_design'):
        raise ValueError('explicit selected IP physical design required')
    identity = hashlib.sha256(json.dumps(baseline, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    if selected['baseline_sha256'] != identity:
        raise ValueError('selected IP physical design belongs to a different baseline')
    if isinstance(grid_mm, bool) or not isinstance(grid_mm, (int, float)) or not math.isfinite(grid_mm) or grid_mm <= 0:
        raise ValueError('representation grid must be positive and finite')
    grid = float(grid_mm)
    g, n = baseline['geometry'], baseline['native_geometry']
    low = [n['domain_start_x_mm'], n['domain_min_y_mm'], -n['domain_halfwidth_z_mm']]
    high = [g['guide_length_mm'] + g['hp_length_mm'] + g['lp_length_mm'] + n['domain_end_x_margin_mm'],
            n['domain_max_y_mm'], n['domain_halfwidth_z_mm']]
    shape = [math.ceil((b-a)/grid-1e-12)+1 for a,b in zip(low, high)]
    if any(value < 3 for value in shape):
        raise ValueError('native PA domain must have at least three nodes per axis')
    projection = copy.deepcopy(selected['projection'])
    projection.update(origin_mm=low, maximum_mm=[a+(count-1)*grid for a,count in zip(low,shape)],
                      shape_gu=shape, span_mm=[(count-1)*grid for count in shape], grid_mm=grid)
    return projection


def represent_selected_ip_design(selected: dict, *, baseline: dict, grid_mm: float) -> dict:
    """Revalidate an external selection before representing its immutable CSG."""
    from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import select_legacy_physical_design
    if (not isinstance(selected, dict) or type(selected.get('schema_version')) is not int
            or not isinstance(selected.get('selection'), dict)):
        raise ValueError('explicit selected IP physical design required')
    choice = selected['selection']
    if set(choice) != {'native_grid_mm', 'native_aux_segments'}:
        raise ValueError('selected IP physical design parameters differ')
    actual = select_legacy_physical_design(baseline, selection_grid_mm=choice['native_grid_mm'],
                                          auxiliary_segments=choice['native_aux_segments'])
    if json.dumps(selected, sort_keys=True, separators=(',', ':'), allow_nan=False) != json.dumps(actual, sort_keys=True, separators=(',', ':'), allow_nan=False):
        raise ValueError('selected IP physical design differs from its declared source')
    return _represent_selected_ip_design(actual, baseline=baseline, grid_mm=grid_mm)


def _box(lo: list[float], hi: list[float]) -> dict:
    if any(a > b for a, b in zip(lo, hi)):
        raise ValueError("negative electrode span")
    return {"shape": "box", "min_mm": lo, "max_mm": hi}


def _primitive(shape: dict) -> str:
    if shape["shape"] == "box":
        low, high = shape["min_mm"], shape["max_mm"]
        return centered_box3d(*[(a + b) / 2 for a, b in zip(low, high)],
                              *[b - a for a, b in zip(low, high)])
    if shape["shape"] == "convex_polyhedron":
        # Official SIMION 8.2 half_space: the normal points out of material.
        # Each supporting plane is intersected by the surrounding within{}.
        planes = convex_planes(shape)
        return " ".join("half_space(" + ",".join(format_number(v) for v in [*[-d*x for x in (nx,ny,nz)],nx,ny,nz]) + ")" for nx,ny,nz,d in planes)
    if shape["shape"] != "cylinder_x":
        raise ValueError("unsupported native primitive")
    # SIMION's cylinder extends in local -Z; +90 degree azimuth maps it
    # toward -X. Locate at x_max so the rod occupies [x_min,x_max].
    f = format_number
    return (f"locate({f(shape['x_max_mm'])},{f(shape['center_y_mm'])},"
            f"{f(shape['center_z_mm'])},1,90) {{ cylinder(0,0,0,"
            f"{f(shape['radius_mm'])},,{f(shape['x_max_mm']-shape['x_min_mm'])}) }}")


def render_projection_electrodes(projection: dict) -> str:
    """Render semantic native CSG electrodes only, without PA/domain or pose."""
    lines = []
    for electrode in projection["electrodes"]:
        lines.append(f"  e({electrode['electrode_id']}) {{ ; {electrode['name']}")
        for shape in electrode["solids"]:
            lines.append("    fill {")
            lines.append("      within { " + _primitive(shape) + " }")
            for cutout in electrode["cutouts"]:
                lines.append("      notin_inside { " + _primitive(cutout) + " }")
            lines.append("    }")
        lines.append("  }")
    return "\n".join(lines)


def render_gem(projection: dict) -> str:
    """Render legacy GEM from the native semantic projection; no Refine or I/O."""
    p = projection
    f = format_number
    nx, ny, nz = p["shape_gu"]
    grid = f(p["grid_mm"])
    origin = p["origin_mm"]
    lines = ["; Simplified native electrodes; Refine required; no analytical field override.",
             ("; Auxiliary surfaces: " + p["auxiliary_surface_model"] + ".") if "electrode_contours" in p else "; Auxiliary surfaces are midpoint-sampled staircase discretizations.",
             f"pa_define({nx},{ny},{nz},planar,none,electrostatic,,{grid},{grid},{grid},surface=fractional)",
             f"locate({f(-origin[0])},{f(-origin[1])},{f(-origin[2])}) {{"]
    lines.extend(render_projection_electrodes(p).splitlines())
    # These sheets explicitly define the numerical boundary condition, rather
    # than silently assuming that an unelectroded PA boundary is grounded.
    lines.append("  e(0) { ; numerical Dirichlet faces, not physical housing")
    for axis in range(3):
        for side in (0, 1):
            low, high = list(origin), list(p["maximum_mm"])
            low[axis] = high[axis] = (origin if side == 0 else p["maximum_mm"])[axis]
            lines.append("    fill { within { " + _primitive(_box(low, high)) + " } }")
    lines.extend(["  }", "}", ""])
    return "\n".join(lines)
