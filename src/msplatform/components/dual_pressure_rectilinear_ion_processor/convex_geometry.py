"""Project-local CSG bounds, convex sections and preparation-time containment.

The author representation stores vertices only, never a second list of planes.
Halfspaces are derived with SciPy ConvexHull (installed 1.17.1; official API:
https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.ConvexHull.html,
reviewed 2026-10-20). Its triangulated coplanar facets are merged for GEM use.
These operations are geometry preparation tools, not per-ion runtime callbacks.
"""
from __future__ import annotations

from itertools import combinations
import math
from numbers import Real
from typing import Any

import numpy as np
from scipy.spatial import ConvexHull, QhullError


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite real number")
    return float(value)


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain three coordinates in mm")
    return [_number(item, label) for item in value]


def _kind(shape: dict[str, Any]) -> str:
    if not isinstance(shape, dict):
        raise ValueError("shape must be a dictionary")
    fields = {"box": {"shape", "min_mm", "max_mm"},
              "cylinder_x": {"shape", "x_min_mm", "x_max_mm", "center_y_mm", "center_z_mm", "radius_mm"},
              "convex_polyhedron": {"shape", "vertices_mm"}}
    kind = shape.get("shape")
    if not isinstance(kind, str) or kind not in fields or set(shape) != fields[kind]:
        raise ValueError("Unknown shape or missing/extra geometry fields")
    return kind


def _convex_hull(shape: dict[str, Any]) -> ConvexHull:
    if _kind(shape) != "convex_polyhedron":
        raise ValueError("This operation requires convex_polyhedron")
    raw = shape["vertices_mm"]
    if not isinstance(raw, list) or len(raw) < 4:
        raise ValueError("vertices_mm requires at least four xyz vertices")
    vertices = np.array([_vector(row, "vertices_mm") for row in raw])
    if len(np.unique(vertices, axis=0)) != len(vertices):
        raise ValueError("vertices_mm must not duplicate vertices")
    try:
        # No QJ/joggling: a degenerate input must not be silently perturbed.
        return ConvexHull(vertices)
    except QhullError as error:
        raise ValueError("vertices_mm must define a nondegenerate three-dimensional convex solid") from error


def _roundoff_mm(points: np.ndarray) -> float:
    # Floating-point geometric predicates only; not a physical clearance.
    return 64 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(points))))


def shape_bounds(shape: dict[str, Any]) -> tuple[list[float], list[float]]:
    """Return exact axis-aligned lower/upper xyz bounds in mm.

    Accept box, cylinder_x and vertices-only convex_polyhedron. Reject unknown
    fields, nonfinite values, inverted extents and degenerate convex solids.
    """
    kind = _kind(shape)
    if kind == "box":
        lower, upper = _vector(shape["min_mm"], "min_mm"), _vector(shape["max_mm"], "max_mm")
        if any(a > b for a, b in zip(lower, upper)):
            raise ValueError("box extents are inverted")
        return lower, upper
    if kind == "cylinder_x":
        left, right = (_number(shape[key], key) for key in ("x_min_mm", "x_max_mm"))
        y, z, radius = (_number(shape[key], key) for key in ("center_y_mm", "center_z_mm", "radius_mm"))
        if left > right or radius <= 0:
            raise ValueError("cylinder_x requires ordered x extents and positive radius")
        return [left, y - radius, z - radius], [right, y + radius, z + radius]
    hull = _convex_hull(shape)
    return hull.points.min(axis=0).tolist(), hull.points.max(axis=0).tolist()


def convex_planes(shape: dict[str, Any]) -> list[list[float]]:
    """Return unique outward normalized [nx,ny,nz,d] halfspaces.

    The solid satisfies n·p+d <= 0, with p/d in mm and unitless unit normals.
    Triangulation duplicates are merged using floating-point roundoff only;
    the returned planes must be frozen once during geometry preparation.
    """
    hull = _convex_hull(shape)
    tolerance_mm = _roundoff_mm(hull.points)
    tolerance_normal = 64 * np.finfo(float).eps
    planes: list[np.ndarray] = []
    for equation in hull.equations:
        plane = equation / np.linalg.norm(equation[:3])
        if not any(np.max(np.abs(plane[:3] - old[:3])) <= tolerance_normal and
                   abs(plane[3] - old[3]) <= tolerance_mm for old in planes):
            planes.append(plane)
    return sorted((plane.tolist() for plane in planes), key=tuple)


def convex_section(shape: dict[str, Any], localaxis: int, value: float) -> list[list[float]]:
    """Intersect a convex solid with xyz[localaxis]=value in mm.

    Return xyz polygon vertices counterclockwise in the remaining increasing
    axis order. A tangent point/edge returns one/two vertices; an absent
    intersection returns []. No area is invented for a zero-area section.
    """
    if isinstance(localaxis, bool) or not isinstance(localaxis, int) or localaxis not in (0, 1, 2):
        raise ValueError("localaxis must be the integer 0, 1 or 2")
    value = _number(value, "section value")
    hull = _convex_hull(shape)
    vertices = hull.points
    if value < vertices[:, localaxis].min() or value > vertices[:, localaxis].max():
        return []
    tolerance = _roundoff_mm(vertices)
    candidates = [vertex.copy() for vertex in vertices if abs(vertex[localaxis] - value) <= tolerance]
    edges = {tuple(sorted(edge)) for facet in hull.simplices for edge in combinations(facet, 2)}
    for first, second in edges:
        a, b = vertices[first], vertices[second]
        da, db = a[localaxis] - value, b[localaxis] - value
        if (da < 0 < db) or (db < 0 < da):
            candidates.append(a + (-da / (db - da)) * (b - a))
    unique: list[np.ndarray] = []
    for point in candidates:
        point[localaxis] = value
        if not any(np.max(np.abs(point - old)) <= tolerance for old in unique):
            unique.append(point)
    if len(unique) <= 2:
        return sorted((point.tolist() for point in unique), key=tuple)
    points = np.array(unique)
    axes = [axis for axis in range(3) if axis != localaxis]
    projected = points[:, axes]
    centered = projected - projected.mean(axis=0)
    singular_values = np.linalg.svd(centered, compute_uv=False)
    if singular_values[-1] <= tolerance:
        direction = np.linalg.svd(centered, full_matrices=False)[2][0]
        coordinates = centered @ direction
        return points[[int(coordinates.argmin()), int(coordinates.argmax())]].tolist()
    return points[ConvexHull(projected).vertices].tolist()


def contains_shape(shape: dict[str, Any], point: list[float] | tuple[float, float, float]) -> bool:
    """Return boundary-inclusive preparation-time solid containment in local mm.

    Convex predicate roundoff is 64 eps times coordinate scale; this is not a
    physical aperture margin. Do not call hull construction in an ion callback.
    """
    position = _vector(point, "point")
    lower, upper = shape_bounds(shape)
    kind = shape["shape"]
    if kind == "box":
        return all(a <= p <= b for a, p, b in zip(lower, position, upper))
    if kind == "cylinder_x":
        return (lower[0] <= position[0] <= upper[0] and
                math.hypot(position[1] - shape["center_y_mm"], position[2] - shape["center_z_mm"]) <= shape["radius_mm"])
    tolerance = _roundoff_mm(np.array([lower, upper, position]))
    return all(float(np.dot(plane[:3], position)) + plane[3] <= tolerance for plane in convex_planes(shape))
