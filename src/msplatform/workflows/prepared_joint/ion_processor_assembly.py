"""Compose a registered IP replacement and derive its workpoint policies."""
from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _finite(value: Any) -> float:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite numeric assembly input required")
    return float(value)


def _point(point: list, rotation: list, translation: list) -> list:
    return [sum(a * b for a, b in zip(row, point)) + shift for row, shift in zip(rotation, translation)]


def transform_shape(shape: dict, rotation: list, translation: list) -> dict:
    """Preserve boxes, convex vertices and circular holes in an axis-permutation pose."""
    if any(sorted(abs(v) for v in row) != [0, 0, 1] for row in rotation):
        raise ValueError("assembly CSG requires axis permutation rotation")
    if shape["shape"] == "convex_polyhedron":
        from msplatform.components.ion_processor.convex_geometry import shape_bounds

        shape_bounds(shape)
        return {"shape": "convex_polyhedron",
                "vertices_mm": [_point(vertex, rotation, translation) for vertex in shape["vertices_mm"]]}
    if shape["shape"] == "box":
        vertices = [
            _point(list(p), rotation, translation) for p in itertools.product(*zip(shape["min_mm"], shape["max_mm"]))
        ]
        return {
            "shape": "box",
            "min_mm": [min(p[a] for p in vertices) for a in range(3)],
            "max_mm": [max(p[a] for p in vertices) for a in range(3)],
        }
    if shape["shape"] != "cylinder_x":
        raise ValueError("unsupported provider primitive")
    ends = [
        _point([x, shape["center_y_mm"], shape["center_z_mm"]], rotation, translation)
        for x in (shape["x_min_mm"], shape["x_max_mm"])
    ]
    return {"shape": "cylinder3d", "endpoints_mm": ends, "radius_mm": shape["radius_mm"]}


def _polygon(point: list, polygon: list) -> bool:
    y, z = point[1:]
    inside = False
    for (a, b), (c, d) in zip(polygon, polygon[1:] + polygon[:1]):
        if (b > z) != (d > z) and y < (c - a) * (z - b) / (d - b) + a:
            inside = not inside
    return inside


def _inside_body(point: list, body: dict) -> bool:
    if "polygon_yz_mm" in body:
        return body["x"][0] < point[0] < body["x"][1] and _polygon(point, body["polygon_yz_mm"])
    b = body.get("box", body.get("min_mm", []) + body.get("max_mm", []))
    return len(b) == 6 and all(b[a] < point[a] < b[a + 3] for a in range(3))


def _shield_contains(point: list, shield: dict) -> bool:
    if not any(_inside_body(point, part) for part in shield["body_sections"]):
        return False
    if _inside_body(point, {"x": shield["x"], "polygon_yz_mm": shield["prism_clearance_polygon_yz_mm"]}):
        return False
    return not any(_inside_body(point, {"box": b}) for b in shield.get("rectangular_slots_mm", []))


def _transform_projection(projection: dict, rotation: list, translation: list) -> list:
    return [
        {
            "namespace": "ion_processor",
            "electrode_id": e["electrode_id"],
            "assembly_id": 100 + e["electrode_id"],
            "name": e["name"],
            **{k: [transform_shape(s, rotation, translation) for s in e[k]] for k in ("solids", "cutouts")},
        }
        for e in projection["electrodes"]
    ]


def derive_lift_seed(source: dict, request: dict) -> float:
    """Apply the explicit voltage policy without rescaling measured trajectories."""
    lift = _finite(source["native_operating_point"]["lift_v"])
    target = _finite(request["target"]["axial_energy_per_charge_v"])
    measured = _finite(request["current_measured_baseline"]["directional_energy"]["z"]["mean"])
    policy = request["policies"]["energy_adjustment"]
    if policy == "provider_voltage_and_geometry":
        result = lift + target - measured
    elif policy == "preserve_measured_workpoint":
        result = lift
    else:
        raise ValueError("unsupported IP energy adjustment policy")
    if min(lift, target, measured, result) <= 0:
        raise ValueError("positive lift and axial energies required")
    return result
