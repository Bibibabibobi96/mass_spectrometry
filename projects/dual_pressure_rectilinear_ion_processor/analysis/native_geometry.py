"""Compile explicit simplified metal electrodes into SIMION 2020 legacy GEM.

This module defines geometry only; Refine must solve the potential separately.
Millimetres and electrode IDs are preserved in the semantic projection. Corner
and axial auxiliary electrodes use declared staircase segments by default;
explicit contour variants use continuous solid boundaries. Neither imposes
analytical fields. Gas pressure remains a prescribed bath outside this module.
"""

from __future__ import annotations

import math
from typing import Any

from common.simion.gem_primitives import centered_box3d, format_number
from projects.dual_pressure_rectilinear_ion_processor.analysis.electrode_contours import apply_contours
from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import convex_planes


NATIVE_GEOMETRY_FIELDS = frozenset("""
guide_rod_radius_mm guide_rod_end_gap_mm rf_plate_thickness_mm rf_plate_halfwidth_mm
segment_end_gap_mm hp_aux_axial_inset_mm hp_aux_inner_radius_start_mm
hp_aux_inner_radius_end_mm hp_aux_thickness_mm lp_aux_axial_inset_mm
lp_aux_halfwidth_y_mm lp_outer_inner_surface_center_z_mm lp_outer_inner_surface_end_z_mm lp_outer_thickness_z_mm
lp_inner_half_length_x_mm lp_inner_center_z_mm lp_inner_thickness_z_mm
lp_side_split_half_gap_y_mm lens_thickness_mm entrance_aperture_diameter_mm exit_lens_half_aperture_mm
lens_outer_halfwidth_mm domain_start_x_mm domain_end_x_margin_mm domain_min_y_mm
domain_max_y_mm domain_halfwidth_z_mm
shield_inner_halfwidth_mm shield_outer_halfwidth_mm shield_extraction_slit_width_mm
""".split())


def _box(lo: list[float], hi: list[float]) -> dict[str, Any]:
    if any(a > b for a, b in zip(lo, hi)):
        raise ValueError("negative electrode span")
    return {"shape": "box", "min_mm": lo, "max_mm": hi}


def _inputs(baseline: dict, numerics: dict) -> tuple[dict, dict, float, int]:
    n = baseline["native_geometry"]
    # Recorded schema-v1 geometry had one shared Pull/shield aperture. Preserve
    # that exact meaning for frozen MR/analysis consumers, without rewriting it.
    # Current author inputs are separately required to declare the new field.
    if baseline["schema_version"] == 1 and set(n) == NATIVE_GEOMETRY_FIELDS - {"shield_extraction_slit_width_mm"}:
        n = {**n, "shield_extraction_slit_width_mm": baseline["geometry"]["extraction_slit_width_mm"]}
    if set(n) != NATIVE_GEOMETRY_FIELDS:
        raise ValueError("unknown or missing native_geometry fields")
    for key, value in n.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"native_geometry.{key} must be finite")
        if key not in {"domain_start_x_mm", "domain_min_y_mm"} and value <= 0:
            raise ValueError(f"native_geometry.{key} must be positive")
    grid, segments = numerics["native_grid_mm"], numerics["native_aux_segments"]
    if isinstance(grid, bool) or not math.isfinite(grid) or grid <= 0:
        raise ValueError("native_grid_mm must be positive and finite")
    if isinstance(segments, bool) or int(segments) != segments or segments < 10:
        raise ValueError("native_aux_segments must be an integer at least 10")
    if (n["exit_lens_half_aperture_mm"] >= n["lens_outer_halfwidth_mm"] or
            n["entrance_aperture_diameter_mm"] / 2 >= n["lens_outer_halfwidth_mm"]):
        raise ValueError("entrance and exit apertures must fit inside their metal frames")
    if n["guide_rod_end_gap_mm"] <= n["lens_thickness_mm"]:
        raise ValueError("guide rods must end before the entrance lens")
    if n["lp_side_split_half_gap_y_mm"] >= n["rf_plate_halfwidth_mm"]:
        raise ValueError("LP split side electrode must retain positive width")
    if n["lp_aux_halfwidth_y_mm"] >= n["lp_side_split_half_gap_y_mm"]:
        raise ValueError("LP auxiliary electrodes must fit inside side-electrode gap")
    if n["shield_inner_halfwidth_mm"] >= n["shield_outer_halfwidth_mm"]:
        raise ValueError("shield must have positive metal thickness")
    if n["shield_extraction_slit_width_mm"] >= 2*n["shield_inner_halfwidth_mm"]:
        raise ValueError("shield extraction aperture must fit inside its frame")
    return baseline["geometry"], n, float(grid), int(segments)


def native_projection(baseline: dict, numerics: dict) -> dict[str, Any]:
    """Return native electrode solids, holes, PA extent and numbering in mm.

    Raises ValueError/KeyError for invalid or missing scientific inputs. No I/O
    or solver API is used. The returned geometry is the single GEM input model.
    """
    g, n, grid, segments = _inputs(baseline, numerics)
    guide_end = g["guide_length_mm"]
    hp_end = guide_end + g["hp_length_mm"]
    lp_end = hp_end + g["lp_length_mm"]
    r, thickness, width = g["r0_mm"], n["rf_plate_thickness_mm"], n["rf_plate_halfwidth_mm"]
    gap = n["segment_end_gap_mm"]
    names = ["guide_positive", "guide_negative", "hp_y_rf", "hp_z_rf", "lp_pull",
             "lp_push", "lp_side_upper", "lp_side_lower", "hp_corner_auxiliary",
             "lp_outer_auxiliary", "lp_inner_auxiliary", "entrance_lens", "exit_lens",
             "lp_commonmode_shield", "hp_commonmode_shield"]
    electrodes = [{"electrode_id": index, "name": name, "solids": [], "cutouts": []}
                  for index, name in enumerate(names, 1)]

    def add(electrode_id: int, shape: dict) -> None:
        electrodes[electrode_id - 1]["solids"].append(shape)

    radius = n["guide_rod_radius_mm"]
    center_radius = g["guide_r0_mm"] + radius
    for k in range(2 * g["guide_order"]):
        angle = math.pi * k / g["guide_order"]
        add(1 if k % 2 == 0 else 2,
            {"shape": "cylinder_x", "x_min_mm": 0,
             "x_max_mm": guide_end - n["guide_rod_end_gap_mm"],
             "center_y_mm": center_radius * math.cos(angle),
             "center_z_mm": center_radius * math.sin(angle), "radius_mm": radius})

    for sign in (-1, 1):
        low, high = sorted((sign * r, sign * (r + thickness)))
        add(3, _box([guide_end + gap, low, -width], [hp_end - gap, high, width]))
        add(4, _box([guide_end + gap, -width, low], [hp_end - gap, width, high]))
    add(5, _box([hp_end + gap, r, -width], [lp_end - gap, r + thickness, width]))
    add(6, _box([hp_end + gap, -r - thickness, -width], [lp_end - gap, -r, width]))
    slit_half_length = g["extraction_slit_length_mm"] / 2
    slit_half_width = g["extraction_slit_width_mm"] / 2
    slit = _box(
        [g["lp_center_mm"] - slit_half_length, r - grid, -slit_half_width],
        [g["lp_center_mm"] + slit_half_length, n["shield_outer_halfwidth_mm"] + grid, slit_half_width])
    electrodes[4]["cutouts"].append(slit)
    for sign in (-1, 1):
        low, high = sorted((sign * r, sign * (r + thickness)))
        add(7, _box([hp_end + gap, n["lp_side_split_half_gap_y_mm"], low],
                    [lp_end - gap, width, high]))
        add(8, _box([hp_end + gap, -width, low],
                    [lp_end - gap, -n["lp_side_split_half_gap_y_mm"], high]))

    hp_start = guide_end + n["hp_aux_axial_inset_mm"]
    hp_stop = hp_end - n["hp_aux_axial_inset_mm"]
    for index in range(segments):
        x0 = hp_start + (hp_stop - hp_start) * index / segments
        x1 = hp_start + (hp_stop - hp_start) * (index + 1) / segments
        # Midpoint sampling is the declared staircase approximation, not a
        # modification of the RF plate or a synthetic field gradient.
        u = (index + 0.5) / segments
        inner = (n["hp_aux_inner_radius_start_mm"] + u *
                 (n["hp_aux_inner_radius_end_mm"] - n["hp_aux_inner_radius_start_mm"])) / math.sqrt(2)
        for sy in (-1, 1):
            for sz in (-1, 1):
                y0, y1 = sorted((sy * inner, sy * (inner + n["hp_aux_thickness_mm"])))
                z0, z1 = sorted((sz * inner, sz * (inner + n["hp_aux_thickness_mm"])))
                add(9, _box([x0, y0, z0], [x1, y1, z1]))

    lp_start = hp_end + n["lp_aux_axial_inset_mm"]
    lp_stop = lp_end - n["lp_aux_axial_inset_mm"]
    for index in range(segments):
        x0 = lp_start + (lp_stop - lp_start) * index / segments
        x1 = lp_start + (lp_stop - lp_start) * (index + 1) / segments
        x_mid = (x0 + x1) / 2
        extent = (g["lp_center_mm"] - lp_start if x_mid <= g["lp_center_mm"]
                  else lp_stop - g["lp_center_mm"])
        u = abs(x_mid - g["lp_center_mm"]) / extent
        # Literature gaps 4/3.7 mm locate the opposed inner surfaces. Finite
        # sheet thickness grows away from the ion volume, not into that gap.
        inner_z = n["lp_outer_inner_surface_center_z_mm"] + u * (
            n["lp_outer_inner_surface_end_z_mm"] - n["lp_outer_inner_surface_center_z_mm"])
        for sign in (-1, 1):
            z0, z1 = sorted((sign * inner_z, sign * (inner_z + n["lp_outer_thickness_z_mm"])))
            add(10, _box([x0, -n["lp_aux_halfwidth_y_mm"], z0],
                         [x1, n["lp_aux_halfwidth_y_mm"], z1]))
    for sign in (-1, 1):
        z0, z1 = sorted((sign * (n["lp_inner_center_z_mm"] - n["lp_inner_thickness_z_mm"] / 2),
                         sign * (n["lp_inner_center_z_mm"] + n["lp_inner_thickness_z_mm"] / 2)))
        add(11, _box([g["lp_center_mm"] - n["lp_inner_half_length_x_mm"], -n["lp_aux_halfwidth_y_mm"], z0],
                     [g["lp_center_mm"] + n["lp_inner_half_length_x_mm"], n["lp_aux_halfwidth_y_mm"], z1]))
    for electrode_id, x0, x1 in ((12, guide_end - n["lens_thickness_mm"], guide_end),
                                (13, lp_end, lp_end + n["lens_thickness_mm"])):
        outer = n["lens_outer_halfwidth_mm"]
        add(electrode_id, _box([x0, -outer, -outer], [x1, outer, outer]))
        if electrode_id == 12:
            # Interpret the paper's "2 mm steel aperture" as a diameter. The
            # circular bore is an explicit model interpretation, not a verified
            # manufacturing drawing; its plate thickness remains an assumption.
            aperture = {"shape": "cylinder_x", "x_min_mm": x0 - grid, "x_max_mm": x1 + grid,
                        "center_y_mm": 0, "center_z_mm": 0,
                        "radius_mm": n["entrance_aperture_diameter_mm"] / 2}
        else:
            halfwidth = n["exit_lens_half_aperture_mm"]
            aperture = _box([x0 - grid, -halfwidth, -halfwidth], [x1 + grid, halfwidth, halfwidth])
        electrodes[electrode_id - 1]["cutouts"].append(aperture)

    shield_inner, shield_outer = n["shield_inner_halfwidth_mm"], n["shield_outer_halfwidth_mm"]
    for electrode_id, x0, x1 in ((14, hp_end + gap, lp_end - gap),
                                (15, guide_end + gap, hp_end - gap)):
        for sign in (-1, 1):
            low, high = sorted((sign * shield_inner, sign * shield_outer))
            add(electrode_id, _box([x0, low, -shield_outer], [x1, high, shield_outer]))
            add(electrode_id, _box([x0, -shield_inner, low], [x1, shield_inner, high]))
    # The reported Pull slit and the model-completion shield opening are
    # independent boundaries. A shield clearance change must not widen Pull.
    shield_half_width = n["shield_extraction_slit_width_mm"] / 2
    shield_slit = _box(
        [g["lp_center_mm"] - slit_half_length, r - grid, -shield_half_width],
        [g["lp_center_mm"] + slit_half_length, n["shield_outer_halfwidth_mm"] + grid, shield_half_width])
    electrodes[13]["cutouts"].append(shield_slit)

    minimum = [n["domain_start_x_mm"], n["domain_min_y_mm"], -n["domain_halfwidth_z_mm"]]
    requested_maximum = [lp_end + n["domain_end_x_margin_mm"], n["domain_max_y_mm"], n["domain_halfwidth_z_mm"]]
    shape = [math.ceil((high - low) / grid - 1e-12) + 1 for low, high in zip(minimum, requested_maximum)]
    if any(value < 3 for value in shape):
        raise ValueError("native PA domain must have at least three nodes per axis")
    maximum = [low + (count - 1) * grid for low, count in zip(minimum, shape)]
    projection = {"schema_version": 1, "role": "native_electrode_geometry_projection",
            "frame_id": baseline["clock"]["frame_id"], "length_unit": "mm",
            "origin_mm": minimum, "maximum_mm": maximum, "shape_gu": shape,
            "span_mm": [(count - 1) * grid for count in shape],
            "grid_mm": grid, "electrode_ids": list(range(1, 16)), "electrodes": electrodes,
            "boundary": "explicit_zero_volt_dirichlet_pa_faces_electrode_0_not_mechanical_shell",
            "auxiliary_surface_model": "midpoint_sampled_staircase_boxes",
            "entrance_aperture_interpretation": "literature_2_mm_aperture_as_circular_diameter_model_interpretation",
            "exit_aperture_provenance": "independent_square_bore_model_assumption",
            "auxiliary_segments": segments, "gas_model": "prescribed_pressure_not_gas_flow_solution"}
    return apply_contours(projection, baseline) if "electrode_contours" in baseline else projection


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
    """Render semantic native CSG electrodes only, without PA/domain or pose.

    The caller owns assembly, numbering and rigid placement. This shares the
    exact primitive/cutout semantics used by the independent IP workbench.
    """
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
