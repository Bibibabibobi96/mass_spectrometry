"""Render IP neutral electrode geometry as SIMION legacy GEM.

All dimensions are supplied in native local millimetres. This module performs
serialization only; it does not solve fields or place assembled components.
"""
from __future__ import annotations

from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import convex_planes
from msplatform.backends.simion.gem_primitives import centered_box3d, format_number


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
