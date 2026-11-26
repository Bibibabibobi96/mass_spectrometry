"""Real enclosure containment, independent of mechanical port mating.

These checks bound physical members by provider-validated local AABBs. They do
not establish obstacle-free flight, collision clearance or field accuracy.
"""
from __future__ import annotations

from itertools import product
import math

from msplatform.contracts.machine_contracts import ContractError
from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform


def validate_envelopes(interface: dict) -> None:
    """Validate finite local mm envelopes after the versioned schema check."""
    bounds = interface["material_bounds_mm"]
    if any(a > b for a, b in zip(bounds["min"], bounds["max"], strict=True)):
        raise ContractError("material bounds must be ordered")
    seen = set()
    for domain in interface["vacuum_domains"]:
        if domain["domain_id"] in seen or domain["z_min_mm"] >= domain["z_max_mm"]:
            raise ContractError("enclosure domains must have unique IDs and positive length")
        seen.add(domain["domain_id"])


def check_containments(recipe: dict, interfaces: dict, poses: dict[str, RigidTransform]) -> list[dict]:
    """Transform each member envelope into its explicitly selected enclosure."""
    checks, seen, parents = [], set(), {}
    for relation in sorted(recipe["containments"], key=lambda row: row["relation_id"]):
        name = relation["relation_id"]
        outer, inner = relation["container_instance_id"], relation["contained_instance_id"]
        if name in seen or outer == inner or outer not in poses or inner not in poses or inner in parents:
            raise ContractError("containment requires unique relations and a single distinct known enclosure")
        seen.add(name)
        parents[inner] = outer
        if any(interfaces[key]["schema_version"] != 4 for key in (outer, inner)):
            raise ContractError("containment endpoints require explicit version4 physical envelopes")
        domains = {row["domain_id"]: row for row in interfaces[outer]["vacuum_domains"]}
        if relation["domain_id"] not in domains:
            raise ContractError("containment selects an unknown enclosure domain")
        domain = domains[relation["domain_id"]]
        bounds = interfaces[inner]["material_bounds_mm"]
        inverse = poses[outer].inverse()
        corners = []
        tolerance = recipe["position_tolerance_mm"]
        for point in product(*zip(bounds["min"], bounds["max"], strict=True)):
            world = poses[inner].transform_position(FramedPosition(poses[inner].from_frame_id, point))
            local = inverse.transform_position(world).coordinates_mm
            radius = math.hypot(local[0] - domain["center_xy_mm"][0], local[1] - domain["center_xy_mm"][1])
            if (radius > domain["radius_mm"] + tolerance
                    or not domain["z_min_mm"] - tolerance <= local[2] <= domain["z_max_mm"] + tolerance):
                raise ContractError(f"{name}: physical member envelope lies outside the selected enclosure")
            corners.append(list(local))
        checks.append(dict(relation_id=name, status="contained_in_envelope",
                           contained_corners_in_container_mm=corners))
    for child in parents:
        visited = set()
        while child in parents:
            if child in visited:
                raise ContractError("cyclic containment is not a physical hierarchy")
            visited.add(child)
            child = parents[child]
    return checks


def validate_layout_connectivity(recipe: dict) -> None:
    """Require every declared instance in this instrument to be physically related."""
    graph = {row["instance_id"]: set() for row in recipe["instances"]}
    pairs = [(row["upstream"]["instance_id"], row["downstream"]["instance_id"]) for row in recipe["connections"]]
    pairs += [(row["contained_instance_id"], row["container_instance_id"]) for row in recipe["containments"]]
    for first, second in pairs:
        graph[first].add(second)
        graph[second].add(first)
    pending, reached = [next(iter(graph))], set()
    while pending:
        current = pending.pop()
        if current not in reached:
            reached.add(current)
            pending.extend(graph[current] - reached)
    if reached != graph.keys():
        raise ContractError("instrument instances must be connected by real mating or containment relations")
