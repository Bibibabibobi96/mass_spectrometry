"""Validate the selected monolithic ion processor to MR assembly connection."""
from __future__ import annotations

from typing import Any

from msplatform.contracts.rigid_transform import RigidTransform, relative_transform


def resolve_ip_mr_connection(plan: dict[str, Any]) -> dict[str, Any]:
    """Select the supported IP/MR connection from the frozen actual scope."""
    recipe = plan["recipe"]
    selected = set(plan["scope"]["instance_ids"])
    by_id = {item["instance_id"]: item for item in recipe["instances"] if item["instance_id"] in selected}
    edges = [edge for edge in recipe["connections"] if edge["connection_id"] in plan["scope"]["connection_ids"]]
    if len(selected) != 2 or len(edges) != 1:
        raise ValueError("IP/MR selected scope requires two distinct instances and one connection")
    edge = edges[0]
    upstream, downstream = edge["upstream"], edge["downstream"]
    source, target = upstream["instance_id"], downstream["instance_id"]
    if (source == target or source not in by_id or target not in by_id
            or by_id[source]["project_id"] != "ion_processor"
            or by_id[target]["project_id"] != "multi_reflection_tof"
            or upstream["port_id"] != "extraction_exit" or downstream["port_id"] != "accelerator_entry"
            or edge["coupling_mode"] != "monolithic_joint_solve"):
        raise ValueError("IP/MR preparation requires one extraction_exit to accelerator_entry monolithic_joint_solve connection")
    return edge


def resolve_ip_mr_transform(plan: dict[str, Any], connection: dict[str, Any]) -> RigidTransform:
    """Return the supported native-IP to provider-local MR registration."""
    poses = {item["instance_id"]: RigidTransform.from_contract(item["transform"])
             for item in plan["recipe"]["instances"]}
    relative = relative_transform(poses[connection["upstream"]["instance_id"]],
                                  poses[connection["downstream"]["instance_id"]])
    if relative.rotation != ((0, 0, -1), (1, 0, 0), (0, -1, 0)):
        raise ValueError("IP/MR preparation requires the supported native orientation relative to MR")
    return relative
