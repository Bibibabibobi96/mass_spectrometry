"""Project complete canonical Assembly members for a bounded COMSOL geometry stage.

This is a geometry description, not a solved model or field qualification.
The source members, group identities and transforms are not edited.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping

from msplatform.components.geometry_members import assembly_geometry_members


def _supported(shape: Mapping, *, ideal: bool) -> None:
    kind = shape.get("kind")
    if kind in {"union", "difference"}:
        if ideal:
            raise ValueError("COMSOL ideal surface Boolean is not supported by this projection")
        children = shape["parts"] if kind == "union" else [shape["base"], *shape["tools"]]
        for child in children:
            _supported(child, ideal=False)
    elif kind == "box":
        if ideal and (shape["size_mm"][2] != 0 or min(shape["size_mm"][:2]) <= 0):
            raise ValueError("COMSOL ideal box must be an xy sheet")
    elif kind == "annulus":
        if ideal and (shape["z_min_mm"] != shape["z_max_mm"] or shape["inner_radius_mm"] != 0):
            raise ValueError("COMSOL ideal annulus must be a full disk")
    elif kind == "extruded_yz_polygon":
        extent, vertices = shape.get("x"), shape.get("polygon_yz_mm")
        if (ideal or not isinstance(extent, (list, tuple)) or len(extent) != 2
                or not isinstance(vertices, (list, tuple)) or len(vertices) < 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in extent)
                or extent[0] >= extent[1]
                or any(not isinstance(row, (list, tuple)) or len(row) != 2
                       or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)
                       for row in vertices)):
            raise ValueError("COMSOL requires a finite solid extruded yz polygon")
        # Exact arithmetic on the actual input numbers; no geometric tolerance.
        from fractions import Fraction
        points = [(Fraction(y), Fraction(z)) for y, z in vertices]
        area2 = sum(y1*z2-y2*z1 for (y1,z1),(y2,z2) in zip(points, points[1:]+points[:1], strict=True))
        if len(set(points)) < 3 or area2 == 0:
            raise ValueError("COMSOL extruded yz polygon is degenerate")
    elif kind == "rod":
        if ideal or "radius_mm" not in shape:
            raise ValueError("COMSOL reference requires circular solid rods")
    elif kind == "cylinder":
        if ideal:
            raise ValueError("COMSOL ideal cylinder is unsupported")
    else:
        raise ValueError("unsupported COMSOL geometry member shape: " + str(kind))



def _local_bounds(shape: Mapping) -> tuple[list[float], list[float]]:
    kind = shape["kind"]
    if kind == "difference":
        return _local_bounds(shape["base"])
    if kind == "union":
        boxes = [_local_bounds(part) for part in shape["parts"]]
        return ([min(b[0][i] for b in boxes) for i in range(3)],
                [max(b[1][i] for b in boxes) for i in range(3)])
    if kind == "extruded_yz_polygon":
        points = shape["polygon_yz_mm"]
        return ([shape["x"][0], min(p[0] for p in points), min(p[1] for p in points)],
                [shape["x"][1], max(p[0] for p in points), max(p[1] for p in points)])
    if kind in {"box", "cylinder"}:
        center = shape["center_mm"]
        size = shape["size_mm"] if kind == "box" else [2*shape["radius_mm"], 2*shape["radius_mm"], shape["height_mm"]]
        return ([c-v/2 for c,v in zip(center,size,strict=True)], [c+v/2 for c,v in zip(center,size,strict=True)])
    radius = shape["radius_mm"] if kind == "rod" else shape["outer_radius_mm"]
    x,y = shape["center_xy_mm"]
    return ([x-radius,y-radius,shape["z_min_mm"]], [x+radius,y+radius,shape["z_max_mm"]])


def _world_bounds(member: Mapping) -> tuple[list[float], list[float]]:
    lo,hi = _local_bounds(member["shape"])
    pose = member["transform"]
    rotation, translation = pose["rotation"], pose["translation_mm"]
    lower, upper = [], []
    for i in range(3):
        contributions = [(rotation[i][j]*lo[j],rotation[i][j]*hi[j]) for j in range(3)]
        lower.append(translation[i]+sum(min(a,b) for a,b in contributions))
        upper.append(translation[i]+sum(max(a,b) for a,b in contributions))
    return lower,upper

def project_assembly_geometry(assembly: Mapping, *, outer_box_mm: Mapping) -> dict:
    """Bind exact canonical members and an explicit assembly-frame outer box.

    Only signed-permutation poses and world-xy ideal sheets are admitted in the
    initial adapter. Bounding boxes are checked before native execution; the
    caller must establish boundary conditions and native selection semantics.
    """
    if not isinstance(outer_box_mm, Mapping) or set(outer_box_mm) != {"min", "max"}:
        raise ValueError("explicit outer box requires min and max")
    lo, hi = outer_box_mm["min"], outer_box_mm["max"]
    if any(not isinstance(v, (list, tuple)) or len(v) != 3 for v in (lo, hi)):
        raise ValueError("outer box coordinates must have three axes")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (*lo, *hi)) or any(a >= b for a,b in zip(lo,hi,strict=True)):
        raise ValueError("outer box must have finite positive extents")
    members = assembly_geometry_members(assembly)
    if not members:
        raise ValueError("complete assembly has no physical members")
    groups: dict[tuple[str, str], list[str]] = {}
    for member in members:
        pose = member["transform"]
        rotation = pose["rotation"]
        if any(sum(v != 0 for v in row) != 1 or any(v not in (-1,0,1) for v in row) for row in rotation):
            raise ValueError("COMSOL reference supports only axis-permutation poses")
        if any(sum(row[j] != 0 for row in rotation) != 1 for j in range(3)):
            raise ValueError("COMSOL reference pose is not a signed permutation")
        ideal = member["representation_role"] == "ideal_surface"
        if ideal and (rotation[2] != [0,0,1] or rotation[0][2] != 0 or rotation[1][2] != 0):
            raise ValueError("COMSOL reference supports only world-xy ideal sheets")
        _supported(member["shape"], ideal=ideal)
        member_lo,member_hi = _world_bounds(member)
        if any(member_lo[i] <= lo[i] or member_hi[i] >= hi[i] for i in range(3)):
            raise ValueError("explicit outer box clips or touches canonical member: " + member["member_id"])
        key = (member["instance_id"], member["electrode_group_id"])
        groups.setdefault(key, []).append(member["member_id"])
    return {"role": "comsol_canonical_assembly_geometry_projection", "schema_version": 1,
            "assembly_frame_id": assembly["composition_plan"]["assembly_frame_id"],
            "outer_box_mm": {"min": list(lo), "max": list(hi)},
            "members": copy.deepcopy(list(members)),
            "electrode_groups": [{"instance_id": k[0], "electrode_group_id": k[1], "member_ids": v}
                                 for k,v in groups.items()]}
