"""Prepare the bounded post-exit IP/P1 comparison, without invoking a solver.

Distances use the IP observation plane and the P1 side-electrode projection at
the inner-auxiliary centre y, not a purported sharp electric-field entrance.
Canonical CSG serializers are reused; the independent local ground boundary is
an explicit approximation and does not feed back into the measured source.
"""
from __future__ import annotations

import copy
import itertools
import math

import numpy as np
from scipy.spatial import ConvexHull

from common.simion.gem_primitives import format_number
from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import convex_planes
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_candidate_geometry import (
    _extrude_polygon_bands, _prism_ground_shield_lines,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import (
    _bounds, _finite, _primitive,
)


def _projected_near_z(parts: list, y_mm: float) -> float:
    crossings = []
    for part in parts:
        polygon = part["polygon_yz_mm"]
        for (y0, z0), (y1, z1) in zip(polygon, polygon[1:] + polygon[:1]):
            if y0 == y1:
                if y_mm == y0:
                    crossings.extend((z0, z1))
            elif min(y0, y1) <= y_mm <= max(y0, y1):
                crossings.append(z0 + (z1 - z0) * (y_mm - y0) / (y1 - y0))
    if len(crossings) < 2:
        raise ValueError("nominal source y does not intersect the P1 projection")
    return max(crossings)


def _shift_shape(shape: dict, delta_z_mm: float) -> None:
    if shape["shape"] == "box":
        shape["min_mm"][2] += delta_z_mm
        shape["max_mm"][2] += delta_z_mm
    elif shape["shape"] == "convex_polyhedron":
        for vertex in shape["vertices_mm"]:
            vertex[2] += delta_z_mm
    elif shape["shape"] == "cylinder3d":
        for endpoint in shape["endpoints_mm"]:
            endpoint[2] += delta_z_mm
    else:
        raise ValueError("unsupported canonical IP shape")


def _grid(box: list, pitch: list) -> list[int]:
    if len(box) != 6 or len(pitch) != 3:
        raise ValueError("explicit local box6 and pitch3 required")
    box[:], pitch[:] = [*map(_finite, box)], [*map(_finite, pitch)]
    if box[0] != 0 or any(p <= 0 for p in pitch):
        raise ValueError("local grid requires x=0 symmetry and positive pitches")
    dimensions = []
    for a in range(3):
        intervals = (box[a + 3] - box[a]) / pitch[a]
        if intervals < 1 or not math.isclose(intervals, round(intervals), abs_tol=1e-9):
            raise ValueError("local box must contain integral positive grid intervals")
        if not math.isclose(pitch[a] / 0.01, round(pitch[a] / 0.01), abs_tol=1e-9):
            raise ValueError("MR grid pitch must be an integer multiple of 0.01 mm")
        dimensions.append(round(intervals) + 1)
    return dimensions


def _clip_report(electrodes: list, box: list) -> list[dict]:
    records = []
    for electrode in electrodes:
        for index, solid in enumerate(electrode["solids"]):
            bounds = _bounds(solid)
            # The negative-x half is represented by the x-mirror condition.
            if bounds[3] <= 0:
                continue
            overlap = all(max(bounds[a], box[a]) < min(bounds[a + 3], box[a + 3]) for a in range(3))
            clipped = ["xyz"[a] for a in range(3) if
                       (a != 0 and bounds[a] < box[a]) or bounds[a + 3] > box[a + 3]]
            if not overlap or clipped:
                records.append(dict(electrode_id=electrode["electrode_id"], solid_index=index,
                                    bounds_mm=bounds, intersects_local_box=overlap,
                                    clipped_axes=clipped))
    return records


def _aperture_specification(spec: dict, frame_id: str) -> dict:
    """Validate the explicitly limited world-z plate and x-mirror geometry."""
    common = {"frame_id", "shape", "center_mm", "normal", "thickness_mm", "outer_half_widths_mm", "voltage_v", "connection"}
    shape = spec.get("shape")
    opening = {"circle": {"radius_mm"}, "y_slit": {"half_widths_mm"}}
    if shape not in opening or set(spec) != common | opening[shape] or spec["frame_id"] != frame_id:
        raise ValueError("complete physical aperture fields and matching frame required")
    result = copy.deepcopy(spec)
    for key, size in (("center_mm", 3), ("normal", 3), ("outer_half_widths_mm", 2)):
        values = result[key]
        if not isinstance(values, list) or len(values) != size:
            raise ValueError(f"physical aperture {key} requires {size} coordinates")
        result[key] = [_finite(v) for v in values]
    if result["center_mm"][0] != 0 or result["normal"] not in ([0, 0, -1], [0, 0, 1]):
        raise ValueError("physical aperture supports world-z normals and center_x=0 with x symmetry only")
    result["thickness_mm"] = _finite(result["thickness_mm"])
    result["voltage_v"] = _finite(result["voltage_v"])
    outer = result["outer_half_widths_mm"]
    if result["thickness_mm"] <= 0 or min(outer) <= 0:
        raise ValueError("finite positive plate thickness and outer half widths required")
    if shape == "circle":
        result["radius_mm"] = _finite(result["radius_mm"])
        widths = [result["radius_mm"]] * 2
    else:
        if not isinstance(result["half_widths_mm"], list) or len(result["half_widths_mm"]) != 2:
            raise ValueError("finite y slit requires explicit x/y half widths")
        widths = result["half_widths_mm"] = [_finite(v) for v in result["half_widths_mm"]]
    if min(widths) <= 0 or any(a >= b for a, b in zip(widths, outer)):
        raise ValueError("physical aperture opening must be strictly inside the finite plate")
    if result["connection"] not in {"isolated", "prism_ground_shield"}:
        raise ValueError("explicit isolated or prism_ground_shield connection required")
    if result["connection"] == "prism_ground_shield" and result["voltage_v"] != 0:
        raise ValueError("connected prism ground shield aperture must be at zero volts")
    return result


def _extreme_points(points: list | np.ndarray) -> np.ndarray:
    """Reduce a clipped convex set, retaining face/edge/point contacts too."""
    points = np.unique(np.asarray(points, dtype=float).reshape(-1, 3), axis=0)
    if len(points) < 2:
        return points
    centered = points - points.mean(axis=0)
    _, singular, axes = np.linalg.svd(centered, full_matrices=False)
    tolerance = 64 * np.finfo(float).eps * max(1., float(np.max(np.abs(points))))
    rank = int(np.sum(singular > tolerance))
    if rank == 0:
        return points[:1]
    projected = centered @ axes[:rank].T
    if rank == 1:
        return points[[int(np.argmin(projected[:, 0])), int(np.argmax(projected[:, 0]))]]
    return points[ConvexHull(projected).vertices]


def _clip_points(points: np.ndarray, plane: list | np.ndarray) -> np.ndarray:
    """Intersect a convex point set with one outward-normal halfspace."""
    if not len(points):
        return points
    plane = np.asarray(plane)
    distances = points @ plane[:3] + plane[3]
    # Predicate roundoff only: no mechanical geometry or GEM hole is enlarged.
    tolerance = 64 * np.finfo(float).eps * max(1., float(np.max(np.abs(points))), abs(float(plane[3])))
    kept = list(points[distances <= tolerance])
    for a, b in itertools.combinations(range(len(points)), 2):
        if distances[a] * distances[b] < 0:
            kept.append(points[a] + distances[a] / (distances[a]-distances[b]) * (points[b]-points[a]))
    return _extreme_points(kept) if kept else np.empty((0, 3))


def _extrusion_planes(part: dict) -> list:
    """Derive exact halfspaces for an existing convex yz polygon extrusion."""
    polygon = np.asarray(part["polygon_yz_mm"], dtype=float)
    crosses = [float((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
               for a, b, c in zip(polygon, np.roll(polygon, -1, axis=0), np.roll(polygon, -2, axis=0))]
    if min(crosses) < 0 < max(crosses):
        raise ValueError("physical aperture overlap requires convex canonical polygon extrusions")
    return convex_planes(dict(shape="convex_polyhedron", vertices_mm=[[x, *p] for x in part["x"] for p in polygon.tolist()]))


def _subtract_convex(points: np.ndarray, planes: list) -> list[np.ndarray]:
    """Partition a convex intersection outside one convex cutout; retain contacts."""
    outside = []
    remaining = points
    for plane in planes:
        piece = _clip_points(remaining, -np.asarray(plane))
        if len(piece):
            outside.append(piece)
        remaining = _clip_points(remaining, plane)
        if not len(remaining):
            break
    return outside


def _plate_intersects(spec: dict, vertices: np.ndarray, solid_planes: list, cutout_planes: list) -> bool:
    """Check actual finite plate material against one convex CSG solid minus holes."""
    intersection = vertices
    for plane in solid_planes:
        intersection = _clip_points(intersection, plane)
    pieces = [intersection] if len(intersection) else []
    for hole in cutout_planes:
        pieces = [part for piece in pieces for part in _subtract_convex(piece, hole)]
    center = np.asarray(spec["center_mm"][:2])
    tolerance = 64 * np.finfo(float).eps * max(1., float(np.max(np.abs(vertices))))
    for piece in pieces:
        transverse = piece[:, :2] - center
        if spec["shape"] == "circle":
            if np.max(np.linalg.norm(transverse, axis=1)) >= spec["radius_mm"] - tolerance:
                return True
        elif np.any(np.max(np.abs(transverse), axis=0) >= np.asarray(spec["half_widths_mm"]) - tolerance):
            return True
    return False


def _prepare_aperture(spec: dict, local: dict, box: list, exit_z: float, downstream_z: float | None) -> dict:
    """Prepare one finite world-z plate, checking real P1/shield CSG contacts."""
    aperture = _aperture_specification(spec, local["frame_id"])
    x, y, z = aperture["center_mm"]
    hx, hy = aperture["outer_half_widths_mm"]
    hz = aperture["thickness_mm"] / 2
    lower, upper = [x-hx, y-hy, z-hz], [x+hx, y+hy, z+hz]
    if hx >= box[3] or lower[1] <= box[1] or upper[1] >= box[4] or lower[2] <= box[2] or upper[2] >= box[5]:
        raise ValueError("physical aperture must be fully inside the local domain with x mirror")
    if downstream_z is None or not box[2] < _finite(downstream_z) < lower[2] < upper[2] < exit_z:
        raise ValueError("physical aperture must lie strictly between measured exit and downstream observation")
    # Existing conservative IP/P1 separation puts all IP metal above the exit plane.
    if upper[2] >= min(_bounds(s)[2] for e in local["ion_processor_electrodes"] for s in e["solids"]):
        raise ValueError("physical aperture may intersect IP metal")
    solid = dict(shape="box", min_mm=lower, max_mm=upper)
    vertices = np.asarray(list(itertools.product(*zip(lower, upper))))
    for electrode in local["prism_electrodes"]:
        if any(_plate_intersects(aperture, vertices, _extrusion_planes(part), []) for part in electrode["parts"]):
            raise ValueError("physical aperture intersects nonzero P1 material")
    shield = local["prism_ground_shields"][0]
    holes = [_extrusion_planes(dict(x=shield["x"], polygon_yz_mm=shield["prism_clearance_polygon_yz_mm"]))]
    for bounds in shield["rectangular_slots_mm"]:
        holes.append(convex_planes(dict(shape="convex_polyhedron", vertices_mm=[list(p) for p in itertools.product(*zip(bounds[:3], bounds[3:]))])))
    contact = any(_plate_intersects(aperture, vertices, _extrusion_planes(part), holes) for part in shield["body_sections"])
    if contact != (aperture["connection"] == "prism_ground_shield"):
        raise ValueError("physical aperture shield contact differs from explicit electrical connection")
    if aperture["shape"] == "circle":
        hole = dict(shape="cylinder3d", endpoints_mm=[[x, y, lower[2]], [x, y, upper[2]]], radius_mm=aperture["radius_mm"])
    else:
        ax, ay = aperture["half_widths_mm"]
        hole = dict(shape="box", min_mm=[x-ax, y-ay, lower[2]], max_mm=[x+ax, y+ay, upper[2]])
    return dict(namespace="physical_aperture", specification=aperture, solids=[solid], cutouts=[hole],
                voltage_v=aperture["voltage_v"], shield_contact=contact,
                boolean_boundary_policy="within_notin_fractional_v1", through_hole_extent="exact_plate_front_to_back_no_epsilon",
                overlap_method="convex_halfspace_intersections_minus_actual_shield_cutouts; closed material contacts retained",
                downstream_observation_z_mm=downstream_z)


def _aperture_gem_subtraction(aperture: dict, box: list, pitch: list) -> dict:
    """Extend only a subtraction tool, keeping the physical plate/hole intact.

    SIMION's surface=fractional can mark a cut cylinder/box end face as metal
    when tool and solid end at the same plane. The official GEM intersection
    example recommends a longer cutting cylinder. The tool covers this local
    domain plus one axial cell on both sides; its transverse dimensions are
    exactly the declared hole. Intersecting it with this plate removes the same
    physical bore, without an epsilon in any mechanical dimension.
    """
    tool = copy.deepcopy(aperture["cutouts"][0])
    low, high = box[2]-pitch[2], box[5]+pitch[2]
    if tool["shape"] == "cylinder3d":
        tool["endpoints_mm"][0][2], tool["endpoints_mm"][1][2] = low, high
    elif tool["shape"] == "box":
        tool["min_mm"][2], tool["max_mm"][2] = low, high
    else:
        raise ValueError("physical aperture subtraction requires axial cylinder or box")
    return dict(policy="axial_tool_beyond_domain_one_cell_v1", cutting_tool=tool,
                cutting_tool_z_extent_mm=[low, high], axial_extension_outside_domain_mm=pitch[2],
                physical_geometry_changed=False, transverse_hole_expansion_mm=0,
                official_source="https://simion.com/info/gem_geometry_file.html#intersecting-within-and-notin-inside",
                official_source_checked="2026-10-20", vendor_version="SIMION 2020",
                scope="GEM boolean tool only; actual solids, cutouts, specification and physical plate faces remain unchanged. No extension of physical hole outside the finite plate.")


def _render(geometry: dict, ip_voltages: list, prism_voltage: float, box: list,
            pitch: list, dimensions: list) -> str:
    lines = ["; Bounded IP/P1 post-exit comparison; grounded five faces, x mirror.",
             "pa_define(" + ",".join(map(str, dimensions)) + ",planar,x,electrostatic,,"
             + ",".join(map(format_number, pitch)) + ",surface=fractional)",
             "locate(" + ",".join(format_number(-v) for v in box[:3]) + ") {"]
    for electrode in geometry["prism_electrodes"]:
        lines.append("e(" + format_number(prism_voltage) + ") {")
        for part in electrode["parts"]:
            lines.extend(_extrude_polygon_bands(part["x"], part["polygon_yz_mm"]))
        lines.append("}")
    for aperture in geometry.get("aperture_electrodes", []):
        lines.extend(("; namespace=physical_aperture", "e(" + format_number(aperture["voltage_v"]) + ") {",
                      "fill {", "within { " + _primitive(aperture["solids"][0]) + " }",
                      "notin { " + _primitive(aperture["gem_subtraction"]["cutting_tool"]) + " }", "}", "}"))
    shield = copy.deepcopy(geometry["prism_ground_shields"][0])
    shield["id"] = 0
    lines.extend(_prism_ground_shield_lines({"prism_ground_shields": [shield]}))
    for electrode in geometry["ion_processor_electrodes"]:
        lines.append("e(" + format_number(ip_voltages[electrode["electrode_id"] - 1]) + ") {")
        for solid in electrode["solids"]:
            lines.extend(("fill {", "within { " + _primitive(solid) + " }"))
            lines.extend("notin_inside { " + _primitive(hole) + " }" for hole in electrode["cutouts"])
            lines.append("}")
        lines.append("}")
    for axis, side in ((0, 1), (1, 0), (1, 1), (2, 0), (2, 1)):
        face = list(box)
        face[axis] = face[axis + 3] = box[axis + 3 * side]
        lines.append("e(0) { " + _primitive({"shape": "box", "min_mm": face[:3], "max_mm": face[3:]}) + " }")
    return "\n".join([*lines, "}", ""])


def prepare_geometry(geometry: dict, ip_voltages: list, prism_voltage: float,
                     distance_mm: float, box_mm: list, pitch_mm: list,
                     convergence_v: float, *, physical_aperture: dict | None = None,
                     downstream_observation_z_mm: float | None = None) -> dict:
    """Return isolated canonical CSG/GEM and checks in mm/V, without side effects.

    Raises ValueError for invalid grids, gap, identity, source location or a
    conservative IP/P1 overlap. Optional physical plates are restricted to
    world-z normals and x symmetry; downstream_observation_z_mm is mandatory
    for those plates. Exact CSG contacts do not replace compiled PA topology.
    Other MR bodies are deliberately excluded.
    """
    volts = [*map(_finite, ip_voltages)]
    prism_voltage, distance_mm, convergence_v = map(_finite, (prism_voltage, distance_mm, convergence_v))
    if len(volts) != 15 or distance_mm <= 0 or convergence_v <= 0:
        raise ValueError("complete IP15 voltages, positive distance and convergence required")
    box, pitch = list(box_mm), list(pitch_mm)
    dimensions = _grid(box, pitch)
    ip = copy.deepcopy(geometry["ion_processor_electrodes"])
    if sorted(e["electrode_id"] for e in ip) != list(range(1, 16)):
        raise ValueError("exactly one of every IP15 electrode required")
    p1 = [copy.deepcopy(e) for e in geometry["prism_electrodes"] if e["station"] == "accelerator_exit"]
    shields = [copy.deepcopy(s) for s in geometry["prism_ground_shields"] if s["station"] == "accelerator_exit"]
    if len(p1) != 1 or len(shields) != 1:
        raise ValueError("one P1 electrode and one P1 shield required")
    shield = shields[0]
    gap = _finite(shield["extension_to_accelerator_exit"]["clearance_mm"])
    if gap != 1.0:
        raise ValueError("distance comparison requires the declared 1 mm mechanical gap")
    inner = next(e for e in ip if e["electrode_id"] == 11)
    inner_bounds = [_bounds(s) for s in inner["solids"]]
    nominal_y = (min(b[1] for b in inner_bounds) + max(b[4] for b in inner_bounds)) / 2
    near_z = _projected_near_z(p1[0]["parts"], nominal_y)
    delta = near_z + distance_mm  # Original measured observation plane is z=0.
    for e in ip:
        for shape in [*e["solids"], *e["cutouts"]]:
            _shift_shape(shape, delta)
    lip = min(_bounds(s)[2] for e in ip if e["electrode_id"] == 14 for s in e["solids"])
    old_end = max(p[1] for p in shield["outer_polygon_yz_mm"])
    new_end = lip - gap
    for polygon in [shield["outer_polygon_yz_mm"], *[b["polygon_yz_mm"] for b in shield["body_sections"]]]:
        for point in polygon:
            if point[1] == old_end:
                point[1] = new_end
    for slot in shield["rectangular_slots_mm"]:
        if slot[5] == old_end:
            slot[5] = new_end
    shield["extension_to_accelerator_exit"].update(exit_support_downstream_z_mm=lip, resolved_end_z_mm=new_end)
    all_low = min(_bounds(s)[2] for e in ip for s in e["solids"])
    p1_high = max(p[1] for part in p1[0]["parts"] for p in part["polygon_yz_mm"])
    shield_high = max(p[1] for part in shield["body_sections"] for p in part["polygon_yz_mm"])
    if all_low <= p1_high or all_low < lip - 1e-12 or shield_high > new_end + 1e-12:
        raise ValueError("local IP/P1 solids fail conservative separating-z checks")
    if not (box[1] < nominal_y < box[4] and box[2] < delta < box[5]):
        raise ValueError("relocated source plane centre lies outside local domain")
    local = dict(schema_version=1, frame_id=geometry["frame_id"], ion_processor_electrodes=ip,
                 prism_electrodes=p1, prism_ground_shields=shields)
    if physical_aperture is not None:
        local["aperture_electrodes"] = [_prepare_aperture(physical_aperture, local, box, delta, downstream_observation_z_mm)]
        aperture = local["aperture_electrodes"][0]
        aperture["gem_subtraction"] = _aperture_gem_subtraction(aperture, box, pitch)
        spec = aperture["specification"]
        widths = [2*spec["radius_mm"]]*2 if spec["shape"] == "circle" else [2*v for v in spec["half_widths_mm"]]
        aperture["grid_representation"] = dict(thickness_cells=spec["thickness_mm"]/pitch[2],
                    opening_width_cells_xy=[widths[a]/pitch[a] for a in range(2)],
                    plate_faces_z_gu=[(spec["center_mm"][2]+side*spec["thickness_mm"]/2-box[2])/pitch[2] for side in (-1, 1)],
                    compiled_pa_through_hole_and_guard_validation_required=True,
                    surface="fractional", numerical_thickening_or_hole_expansion_mm=0)
    checks = dict(status="PASS_conservative_separating_planes", nominal_y_mm=nominal_y,
                  ip_to_p1_z_separation_mm=all_low-p1_high, ip_to_shield_z_separation_mm=all_low-shield_high,
                  grid_dimensions=dimensions, box_mm=box, pitch_mm=pitch, convergence_v=convergence_v,
                  clipped_ip_solids=_clip_report(ip, box), boundary_mode="grounded_five_faces_x_mirror",
                  boundary_scope="Independent local grounded enclosure; no inherited full-MR field or upstream source feedback",
                  negative_x_geometry="Represented by the x=0 mirror boundary, not physical clipping",
                  official_geometry_reference="https://simion.com/info/gem_geometry_file.html",
                  scope="Static CSG separation and clipping inventory; not CAD or mesh convergence qualification")
    return dict(geometry=local, gem=_render(local, volts, prism_voltage, box, pitch, dimensions),
                delta_z_mm=delta, exit_z_mm=delta, gap_mm=lip-new_end,
                projected_near_z_mm=near_z, geometry_checks=checks)
