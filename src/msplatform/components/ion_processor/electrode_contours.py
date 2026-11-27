"""Literature-guided formed LP electrodes and continuous auxiliary boundaries.

The explicit author dimensions are hypotheses, not manufacturer CAD. This
compiler changes geometry only; RF, gas, source and timing remain with baseline.
All coordinates are native local millimetres (x along the trap).
"""
from __future__ import annotations

import math
from typing import Any


FIELDS = frozenset("schema_version mode nose_halfwidth_mm shoulder_halfwidth_mm nose_depth_mm backing_thickness_mm slit_lip_depth_mm slit_outlet_width_mm push_window_length_mm push_window_width_mm".split())
MODES = {"formed_extraction", "formed_extraction_continuous_aux", "formed_extraction_continuous_aux_parabolic_inner"}


def validate_contours(c: dict, baseline: dict) -> None:
    """Reject unspecified, nonfinite or interfering author dimensions."""
    parabolic = c.get("mode") == "formed_extraction_continuous_aux_parabolic_inner"
    expected = FIELDS | {"inner_parabola_sag_mm"} if parabolic else FIELDS
    outer_bounds = "outer_axial_bounds_mm" in c
    if outer_bounds and c.get("mode") in {"formed_extraction_continuous_aux", "formed_extraction_continuous_aux_parabolic_inner"}:
        expected |= {"outer_axial_bounds_mm"}
    if set(c) != expected or c["schema_version"] != 1 or c["mode"] not in MODES:
        raise ValueError("unsupported electrode_contours schema/fields/mode")
    for key in expected - {"schema_version", "mode", "outer_axial_bounds_mm"}:
        v = c[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise ValueError(f"electrode_contours.{key} must be finite and positive")
    g, n = baseline["geometry"], baseline["native_geometry"]
    if outer_bounds:
        bounds = c["outer_axial_bounds_mm"]
        if (not isinstance(bounds, list) or len(bounds) != 2 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bounds)):
            raise ValueError("outer_axial_bounds_mm requires two finite native axial coordinates")
        lp_start = g["guide_length_mm"] + g["hp_length_mm"]
        gap = n["segment_end_gap_mm"]
        if not (lp_start + gap <= bounds[0] < g["lp_center_mm"] < bounds[1] <= lp_start + g["lp_length_mm"] - gap):
            raise ValueError("outer auxiliary bounds must contain the extraction center and retain LP end gaps")
    if parabolic and c["inner_parabola_sag_mm"] >= n["lp_inner_thickness_z_mm"]:
        raise ValueError("parabolic inner sheet must retain positive thickness at both ends")
    depth = c["nose_depth_mm"] + c["backing_thickness_mm"]
    if not n["lp_side_split_half_gap_y_mm"] < c["nose_halfwidth_mm"] < c["shoulder_halfwidth_mm"] < g["r0_mm"]:
        raise ValueError("formed nose must retain split tips and inter-electrode clearance")
    if g["r0_mm"] + depth >= n["shield_inner_halfwidth_mm"]:
        raise ValueError("formed electrode reaches common-mode shield")
    if not g["extraction_slit_width_mm"] <= c["slit_outlet_width_mm"] < 2*c["nose_halfwidth_mm"]:
        raise ValueError("slit bevel must preserve both finite lips")
    if c["slit_lip_depth_mm"] >= depth:
        raise ValueError("slit straight lip must end before backing plane")
    if c["push_window_length_mm"] >= g["lp_length_mm"]-2*n["segment_end_gap_mm"] or c["push_window_width_mm"] >= 2*c["shoulder_halfwidth_mm"]:
        raise ValueError("pumping window must retain its surrounding frame")


def _extrude_x(x0: float, x1: float, yz: list[list[float]]) -> dict[str, Any]:
    return {"shape": "convex_polyhedron", "vertices_mm": [[x, y, z] for x in (x0, x1) for y, z in yz]}


def _formed_extraction(electrodes: list[dict], b: dict, grid: float) -> None:
    g, n, c = b["geometry"], b["native_geometry"], b["electrode_contours"]
    r, w, W, h, t = (g["r0_mm"], c["nose_halfwidth_mm"], c["shoulder_halfwidth_mm"], c["nose_depth_mm"], c["backing_thickness_mm"])
    x0 = g["guide_length_mm"]+g["hp_length_mm"]+n["segment_end_gap_mm"]
    x1 = g["guide_length_mm"]+g["hp_length_mm"]+g["lp_length_mm"]-n["segment_end_gap_mm"]
    yz = [[r,-w], [r,w], [r+h,W], [r+h+t,W], [r+h+t,-W], [r+h,-W]]
    for eid, sign in ((5,1), (6,-1)):
        electrodes[eid-1]["solids"] = [_extrude_x(x0,x1,[[sign*y,z] for y,z in yz])]
    # Keep the reported 8 x 0.8 mm entrance throat. Only the downstream
    # opening is beveled, using explicit assumed lip depth and outlet width.
    cx, L, a = g["lp_center_mm"], g["extraction_slit_length_mm"]/2, g["extraction_slit_width_mm"]/2
    neck, back, outlet = r+c["slit_lip_depth_mm"], r+h+t, c["slit_outlet_width_mm"]/2
    end = back+grid
    beyond = outlet+(outlet-a)*grid/(back-neck)
    electrodes[4]["cutouts"] = [
        {"shape":"box","min_mm":[cx-L,r-grid,-a],"max_mm":[cx+L,neck,a]},
        _extrude_x(cx-L,cx+L,[[neck,-a],[end,-beyond],[end,beyond],[neck,a]])]
    pL, pW = c["push_window_length_mm"]/2, c["push_window_width_mm"]/2
    electrodes[5]["cutouts"] = [{"shape":"box", "min_mm":[cx-pL,-back-grid,-pW], "max_mm":[cx+pL,-r+grid,pW]}]
    # Swap the profile's normal/transverse axes and retain the existing split.
    split = n["lp_side_split_half_gap_y_mm"]
    positive_half = [[split,r],[w,r],[W,r+h],[W,back],[split,back]]
    for eid, sy in ((7,1),(8,-1)):
        electrodes[eid-1]["solids"] = [_extrude_x(x0,x1,[[sy*y,sz*z] for y,z in positive_half]) for sz in (-1,1)]


def _continuous_aux(electrodes: list[dict], b: dict) -> None:
    g, n = b["geometry"], b["native_geometry"]
    start = g["guide_length_mm"]+n["hp_aux_axial_inset_mm"]
    stop = g["guide_length_mm"]+g["hp_length_mm"]-n["hp_aux_axial_inset_mm"]
    thickness = n["hp_aux_thickness_mm"]
    corners = []
    for sy in (-1,1):
        for sz in (-1,1):
            vertices = []
            for x, radius in ((start,n["hp_aux_inner_radius_start_mm"]),(stop,n["hp_aux_inner_radius_end_mm"])):
                inner = radius/math.sqrt(2)
                vertices += [[x,sy*y,sz*z] for y in (inner,inner+thickness) for z in (inner,inner+thickness)]
            corners.append({"shape":"convex_polyhedron","vertices_mm":vertices})
    electrodes[8]["solids"] = corners
    start = g["guide_length_mm"]+g["hp_length_mm"]+n["lp_aux_axial_inset_mm"]
    stop = g["guide_length_mm"]+g["hp_length_mm"]+g["lp_length_mm"]-n["lp_aux_axial_inset_mm"]
    if "outer_axial_bounds_mm" in b["electrode_contours"]:
        start, stop = b["electrode_contours"]["outer_axial_bounds_mm"]
    center = g["lp_center_mm"]
    zc, ze, thick, half_y = (n["lp_outer_inner_surface_center_z_mm"], n["lp_outer_inner_surface_end_z_mm"], n["lp_outer_thickness_z_mm"], n["lp_aux_halfwidth_y_mm"])
    outer = []
    for sign in (-1,1):
        for a, za, d, zd in ((start,ze,center,zc),(center,zc,stop,ze)):
            vertices = [[x,y,sign*z] for x,z0 in ((a,za),(d,zd)) for y in (-half_y,half_y) for z in (z0,z0+thick)]
            outer.append({"shape":"convex_polyhedron","vertices_mm":vertices})
    electrodes[9]["solids"] = outer
    # The existing two short inner sheets are already continuous rectangular
    # solids. Their unknown in-plane shape is deliberately not invented here.


def apply_contours(projection: dict, baseline: dict) -> dict:
    """Replace only declared electrode groups in a newly compiled projection."""
    c = baseline["electrode_contours"]
    validate_contours(c,baseline)
    _formed_extraction(projection["electrodes"],baseline,projection["grid_mm"])
    if c["mode"] in {"formed_extraction_continuous_aux", "formed_extraction_continuous_aux_parabolic_inner"}:
        _continuous_aux(projection["electrodes"],baseline)
        projection["auxiliary_surface_model"] = "continuous_piecewise_planar_outer_and_lofted_corner_sheets_inner_rectangular_assumption"
    if c["mode"] == "formed_extraction_continuous_aux_parabolic_inner":
        _parabolic_inner(projection,baseline)
    projection["electrode_contours"] = c
    projection["shape_provenance"] = "Stewart_Fig2_3_topology_with_explicit_unreported_dimension_assumptions_not_manufacturer_CAD"
    return projection


def _parabolic_inner(projection: dict, b: dict) -> None:
    """Create a continuous chord approximation to the assumed inner parabola.

    z_inner(x)=z_tip+sag*((x-center)/half_length)^2, with a fixed outer
    backing plane. Existing native_aux_segments owns discretization, and the
    maximum chord sag error is sag/segments^2 (mm). This is not an optimum.
    """
    g,n,c = b["geometry"],b["native_geometry"],b["electrode_contours"]
    center,half = g["lp_center_mm"],n["lp_inner_half_length_x_mm"]
    tip = n["lp_inner_center_z_mm"]-n["lp_inner_thickness_z_mm"]/2
    back = n["lp_inner_center_z_mm"]+n["lp_inner_thickness_z_mm"]/2
    sag,segments = c["inner_parabola_sag_mm"],projection["auxiliary_segments"]
    half_y = n["lp_aux_halfwidth_y_mm"]
    solids=[]
    for sign in (-1,1):
        vertices=[]
        for i in range(segments+1):
            u = -1+2*i/segments
            vertices.extend([[center+half*u,y,sign*(tip+sag*u*u)] for y in (-half_y,half_y)])
        vertices.extend([[x,y,sign*back] for x in (center-half,center+half) for y in (-half_y,half_y)])
        solids.append({"shape":"convex_polyhedron","vertices_mm":vertices})
    projection["electrodes"][10]["solids"] = solids
    projection["auxiliary_surface_model"] = "continuous_corner_outer_and_piecewise_planar_parabolic_inner_hypothesis"
    projection["inner_parabola_chord_error_bound_mm"] = sag/segments**2
