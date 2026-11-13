"""Certify the existing IP convex vertices as a translated polygon prism."""
from __future__ import annotations

import math
from collections import Counter
from fractions import Fraction
from collections.abc import Mapping

import numpy as np
from scipy.spatial import ConvexHull

from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import shape_bounds


def _fraction_points(vertices):
    return [tuple(Fraction.from_float(float(x)) for x in row) for row in vertices]


def _det(a, b, c, d):
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    w = [d[i] - a[i] for i in range(3)]
    return (u[0]*(v[1]*w[2]-v[2]*w[1])
            - u[1]*(v[0]*w[2]-v[2]*w[0])
            + u[2]*(v[0]*w[1]-v[1]*w[0]))


def _exact_polygon_indices(points):
    """Order the 2-D convex boundary using exact binary-rational predicates."""
    values = [(Fraction.from_float(float(p[0])), Fraction.from_float(float(p[1])), i)
              for i,p in enumerate(points)]
    values.sort()
    def cross(a,b,c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower=[]
    for point in values:
        while len(lower)>=2 and cross(lower[-2],lower[-1],point)<=0: lower.pop()
        lower.append(point)
    upper=[]
    for point in reversed(values):
        while len(upper)>=2 and cross(upper[-2],upper[-1],point)<=0: upper.pop()
        upper.append(point)
    result=[point[2] for point in lower[:-1]+upper[:-1]]
    if len(result)<3:
        raise ValueError("unsupported COMSOL IP hull: degenerate prism polygon")
    return result


def _exact_prism(vertices):
    """Use exact binary-rational source coordinates, before pose arithmetic."""
    points = _fraction_points(vertices)
    for axis in range(3):
        lo, hi = min(p[axis] for p in points), max(p[axis] for p in points)
        a, b = [p for p in points if p[axis] == lo], [p for p in points if p[axis] == hi]
        if not hi > lo or len(a) != len(b) or len(a)*2 != len(points):
            continue
        for point in b:
            delta = tuple(point[i]-a[0][i] for i in range(3))
            if {tuple(p[i]+delta[i] for i in range(3)) for p in a} == set(b):
                return axis
    return None


def _certified_tetrahedra(vertices):
    """Accept Qhull facets only after exact support and closed-edge checks."""
    points = _fraction_points(vertices)
    hull = ConvexHull(np.asarray(vertices, dtype=float))
    facets = [tuple(map(int, face)) for face in hull.simplices]
    edges = Counter()
    for a,b,c in facets:
        signs = {_det(points[a], points[b], points[c], p) > 0 for p in points
                 if _det(points[a], points[b], points[c], p) != 0}
        if len(signs) != 1:
            raise ValueError("unsupported COMSOL IP hull: Qhull facet is not an exact supporting plane")
        for first,second in ((a,b),(b,c),(c,a)):
            edges[tuple(sorted((first,second)))] += 1
    if any(count != 2 for count in edges.values()):
        raise ValueError("unsupported COMSOL IP hull: facet boundary is not closed")
    neighbors = {i:set() for i in range(len(facets))}
    edge_faces = {}
    for index,(a,b,c) in enumerate(facets):
        for edge in ((a,b),(b,c),(c,a)):
            edge_faces.setdefault(tuple(sorted(edge)), []).append(index)
    for first,second in edge_faces.values():
        neighbors[first].add(second); neighbors[second].add(first)
    reached, pending = set(), [0]
    while pending:
        index = pending.pop()
        if index not in reached:
            reached.add(index); pending.extend(neighbors[index] - reached)
    if len(reached) != len(facets):
        raise ValueError("unsupported COMSOL IP hull: disconnected facet boundary")
    # A source vertex is in the hull. Coning every boundary triangle visible
    # from it decomposes the convex hull; coplanar triangles have zero volume.
    anchor = 0
    tetrahedra = []
    for a,b,c in facets:
        orientation = _det(points[a],points[b],points[c],points[anchor])
        if orientation:
            if orientation < 0:
                b,c = c,b
            tetrahedra.append([vertices[a],vertices[b],vertices[c],vertices[anchor]])
    if not tetrahedra:
        raise ValueError("unsupported COMSOL IP hull: no nonzero tetrahedra")
    return dict(kind="ip_certified_tetra_union", tetrahedra=tetrahedra,
                source_vertex_count=len(vertices), source_facet_count=len(facets))


def certify_ip_prism(shape: Mapping, transform: Mapping) -> dict:
    """Return a bounded world-coordinate extrusion of the unchanged source hull.

    Source endpoints must match exactly as binary rationals before pose. Every
    transformed input vertex must lie on one of two axis-aligned endpoint planes and
    each endpoint set must be a one-to-one translation. The convex hull of that
    union is the translated polygon prism. A non-prism uses exactly verified source facets and original-vertex tetrahedra.
    The transformed-prism residual is bounded solely by
    float64 arithmetic roundoff, not by a physical tolerance.
    """
    shape_bounds({"shape": "convex_polyhedron", "vertices_mm": shape["vertices_mm"]})
    rotation = np.asarray(transform["rotation"], dtype=float)
    translation = np.asarray(transform["translation_mm"], dtype=float)
    points = np.asarray(shape["vertices_mm"], dtype=float) @ rotation.T + translation
    if len({tuple(row) for row in points}) != len(points):
        raise ValueError("unsupported COMSOL IP hull: transformed source vertices collapse")
    source = _fraction_points(shape["vertices_mm"])
    exact_rotation = _fraction_points(transform["rotation"])
    exact_translation = tuple(Fraction.from_float(float(v)) for v in transform["translation_mm"])
    transform_error = max(abs(Fraction.from_float(float(points[j,i])) -
        (sum(exact_rotation[i][k]*source[j][k] for k in range(3))+exact_translation[i]))
        for j in range(len(source)) for i in range(3))
    source_axis = _exact_prism(shape["vertices_mm"])
    if source_axis is None:
        result = _certified_tetrahedra(shape["vertices_mm"])
        result["world_transform_max_abs_error_mm"] = float(transform_error)
        return result
    world_axis = int(np.argmax(np.abs(rotation[:, source_axis])))
    scale = max(1.0, float(np.max(np.abs(points))))
    # Source congruence was proved exactly before this pose projection. For
    # transformed coordinates bounded by scale, pair subtraction, point-plus-
    # shift and residual subtraction have magnitudes at most 2, 3 and 4 times
    # scale respectively. Their binary64 rounding errors sum to at most
    # (2+3+4)*eps*scale; 64*eps*scale also covers endpoint subtraction and
    # subnormal absolute error. It is not a tolerance on source coordinates.
    # Pose arithmetic error is measured separately against rational inputs.
    bound = 64 * np.finfo(float).eps * scale
    for axis, other, plane in ((0, (1, 2), "yz"), (1, (2, 0), "zx"), (2, (0, 1), "xy")):
        if axis != world_axis:
            continue
        low, high = float(points[:, axis].min()), float(points[:, axis].max())
        if not high > low:
            continue
        low_mask = np.abs(points[:, axis] - low) <= bound
        high_mask = np.abs(points[:, axis] - high) <= bound
        if not np.all(low_mask | high_mask) or np.any(low_mask & high_mask):
            continue
        a, b = points[low_mask][:, other], points[high_mask][:, other]
        if len(a) != len(b) or len(a) < 3:
            continue
        shift = None
        residual = math.inf
        # An endpoint of one polygon must correspond to some endpoint of the
        # other. Try each actual candidate; never average or move the polygon.
        for candidate in b - a[0]:
            unused = set(range(len(b)))
            error = 0.0
            for row in a:
                index = min(unused, key=lambda j: float(np.max(np.abs(row + candidate - b[j]))))
                error = max(error, float(np.max(np.abs(row + candidate - b[index]))))
                unused.remove(index)
                if error > bound:
                    break
            if error < residual:
                shift, residual = candidate, error
                if error <= bound:
                    break
        residual = max(residual, float(np.max(np.abs(points[low_mask, axis] - low))),
                       float(np.max(np.abs(points[high_mask, axis] - high))))
        if shift is None or not math.isfinite(residual) or residual > bound:
            continue
        try:
            polygon = _exact_polygon_indices(a)
        except ValueError:
            continue

        return dict(kind="ip_certified_prism", plane=plane, offset_mm=low,
                    polygon_mm=a[polygon].tolist(), distance_mm=high-low,
                    displacement_mm=shift.tolist(), reconstruction_residual_mm=residual,
                    arithmetic_bound_mm=bound, world_transform_max_abs_error_mm=float(transform_error))
    raise ValueError("unsupported COMSOL IP convex hull: not a certified translated prism")
