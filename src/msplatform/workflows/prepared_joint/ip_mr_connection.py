"""Identity and scope policy for the prepared IP-to-MR connection."""
from __future__ import annotations

from typing import Any


def validate_component_exit_binding(component: dict[str, Any]) -> tuple[str, str]:
    """Return the explicit instance pair separately from project provenance."""
    source, target = component.get("source_instance_id"), component.get("target_instance_id")
    if (component.get("schema_version") != 2 or component.get("role") != "ion_processor_component_exit_export"
            or component.get("status") != "prepared"
            or component.get("source_project") != "dual_pressure_rectilinear_ion_processor"
            or not isinstance(source, str) or not source
            or not isinstance(target, str) or not target or source == target):
        raise ValueError("Unsupported measured component instance binding")
    return source, target


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
            or by_id[source]["project_id"] != "dual_pressure_rectilinear_ion_processor"
            or by_id[target]["project_id"] != "parallel_mirror_dual_stripe_mr_tof"
            or upstream["port_id"] != "extraction_exit" or downstream["port_id"] != "accelerator_entry"
            or edge["coupling_mode"] != "monolithic_joint_solve"):
        raise ValueError("IP/MR preparation requires one extraction_exit to accelerator_entry monolithic_joint_solve connection")
    return edge
