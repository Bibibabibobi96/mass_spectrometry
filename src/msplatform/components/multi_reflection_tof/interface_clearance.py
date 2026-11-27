"""MR grounded shield interior and clearance tests."""
from __future__ import annotations


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
