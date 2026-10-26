"""Validate one direct local-to-assembly pose per provider component.

No pose is inferred from a neighbouring component. Ports are transformed once
into the declared assembly frame; connection checks compare those world surfaces.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform


def _finite(value: Any) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ContractError("assembly input must contain finite numbers")


def _dot(left: list | tuple, right: list | tuple) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _port_in_assembly(interface: dict, pose: RigidTransform, port_id: str) -> tuple:
    if port_id not in interface["ports"]:
        raise ContractError(f"component omits mechanical port: {port_id}")
    port = interface["ports"][port_id]
    normal = port["outward_normal"]
    # Unit-vector validity uses the shared plane/rotation roundoff scale; it
    # cannot be disabled by increasing a physical mating tolerance.
    if not math.isclose(_dot(normal, normal), 1, rel_tol=0, abs_tol=1e-12):
        raise ContractError("component port normal must be a unit vector")
    section = port["cross_section"]
    if section["shape"] == "rectangle":
        width, height = section["width_axis"], section["height_axis"]
        if any(abs(value) > 1e-12 for value in (
            _dot(width, width) - 1, _dot(height, height) - 1,
            _dot(width, height), _dot(width, normal), _dot(height, normal),
        )):
            raise ContractError("component cross-section axes must be orthonormal in the port plane")
    center = pose.transform_position(FramedPosition(pose.from_frame_id, port["center_mm"]))
    direction = pose.transform_vector(FramedVector(pose.from_frame_id, normal))
    return center.coordinates_mm, direction.components


def _check_connection(edge: dict, interfaces: dict, poses: dict, recipe: dict) -> dict:
    upstream, downstream = edge["upstream"], edge["downstream"]
    first, second = upstream["instance_id"], downstream["instance_id"]
    if first == second or first not in poses or second not in poses:
        raise ContractError("assembly connection must select two distinct known instances")
    up_center, up_normal = _port_in_assembly(interfaces[first], poses[first], upstream["port_id"])
    down_center, down_normal = _port_in_assembly(interfaces[second], poses[second], downstream["port_id"])
    if math.dist(up_normal, tuple(-value for value in down_normal)) > 2 * math.sin(recipe["angular_tolerance_rad"] / 2):
        raise ContractError(
            f"{edge['connection_id']}: assembly mating surface normals are not opposed; "
            f"{first}.{upstream['port_id']}={up_normal}, {second}.{downstream['port_id']}={down_normal}"
        )
    # A positive gap moves from the upstream face in its outward direction.
    expected_down = tuple(center + edge["gap_mm"] * normal for center, normal in zip(up_center, up_normal, strict=True))
    if math.dist(expected_down, down_center) > recipe["position_tolerance_mm"]:
        raise ContractError(
            f"{edge['connection_id']}: assembly mating faces differ from the declared gap or alignment; "
            f"{first}.{upstream['port_id']}={up_center}, outward_normal={up_normal}, "
            f"gap_mm={edge['gap_mm']}, expected {second}.{downstream['port_id']}={expected_down}, "
            f"actual={down_center} in {recipe['assembly_frame_id']}"
        )
    return {
        "connection_id": edge["connection_id"],
        "upstream_center_mm": list(up_center),
        "downstream_center_mm": list(down_center),
        "upstream_outward_normal": list(up_normal),
        "downstream_outward_normal": list(down_normal),
        "gap_mm": _dot(tuple(b - a for a, b in zip(up_center, down_center, strict=True)), up_normal),
    }


def compile_assembly_layout(
    recipe: dict, components: dict[str, dict], *, local_scope: dict | None = None,
) -> dict[str, Any]:
    """Freeze the complete recipe, or an explicit local selection from it.

    Components are provider-owned geometry interfaces. This pure stage does not
    publish particle handoffs, voltages, clocks, fields or physical qualification.
    """
    validate_schema(recipe, "assembly_recipe.schema.json")
    _finite(recipe)
    _finite(components)
    instances = {item["instance_id"]: item for item in recipe["instances"]}
    if len(instances) != len(recipe["instances"]):
        raise ContractError("duplicate assembly instance_id")
    if set(components) != set(instances):
        raise ContractError(
            "assembly provider outputs differ from recipe instances: "
            f"missing={sorted(instances.keys() - components.keys())}, "
            f"unexpected={sorted(components.keys() - instances.keys())}"
        )
    poses = {}
    for instance_id, item in instances.items():
        interface = components[instance_id]
        validate_schema(interface, "component_geometry_interface.schema.json")
        if interface["project_id"] != item["project_id"]:
            raise ContractError(
                f"{instance_id}: recipe project={item['project_id']}, "
                f"provider project={interface['project_id']}"
            )
        ids = [electrode["component_electrode_id"] for electrode in interface["component_electrodes"]]
        if len(ids) != len(set(ids)):
            raise ContractError("component physical electrode identities are not unique")
        try:
            pose = RigidTransform.from_contract(item["transform"])
        except ValueError as exc:
            raise ContractError(f"invalid assembly rigid transform: {exc}") from exc
        if pose.from_frame_id != interface["local_frame_id"] or pose.to_frame_id != recipe["assembly_frame_id"]:
            raise ContractError("assembly pose must map the provider local frame directly to the assembly frame")
        poses[instance_id] = pose
    seen = set()
    checks = []
    for edge in sorted(recipe["connections"], key=lambda item: item["connection_id"]):
        if edge["connection_id"] in seen:
            raise ContractError("duplicate assembly connection_id")
        seen.add(edge["connection_id"])
        checks.append(_check_connection(edge, components, poses, recipe))
    selected = list(instances)
    if local_scope is not None:
        if (not isinstance(local_scope, dict)
                or not isinstance(local_scope.get("instance_ids"), list)
                or not all(isinstance(item, str) for item in local_scope["instance_ids"])):
            raise ContractError("local_scope.instance_ids must be an explicit list of instance IDs")
        requested = local_scope["instance_ids"]
        if not requested or len(requested) != len(set(requested)):
            raise ContractError("local_scope.instance_ids must be nonempty and unique")
        unknown = set(requested) - instances.keys()
        if unknown:
            raise ContractError(f"local_scope selects unknown instances: {sorted(unknown)}")
        selected = [instance_id for instance_id in instances if instance_id in requested]
    selected_ids = set(selected)
    internal, boundary = [], []
    for edge in sorted(recipe["connections"], key=lambda item: item["connection_id"]):
        included = sum(endpoint["instance_id"] in selected_ids
                       for endpoint in (edge["upstream"], edge["downstream"]))
        if included == 2:
            internal.append(edge["connection_id"])
        elif included == 1:
            boundary.append(edge["connection_id"])
    plan = {
        "schema_version": 3,
        "role": "integration_composition_plan_do_not_edit",
        "integration_id": recipe["integration_id"],
        "recipe_id": recipe["recipe_id"],
        "stage": "layout_only",
        "assembly_frame_id": recipe["assembly_frame_id"],
        "recipe": copy.deepcopy(recipe),
        "components": copy.deepcopy(components),
        "connection_checks": checks,
        "scope": {"kind": "full" if local_scope is None else "local",
                  "instance_ids": selected, "connection_ids": internal,
                  "boundary_connection_ids": boundary},
    }
    if local_scope is not None:
        plan["local_scope"] = copy.deepcopy(local_scope)
    validate_schema(plan, "composition_plan.schema.json")
    return plan


def derive_assembly_scope(parent_plan: dict, *, local_scope: dict | None = None) -> dict:
    """Validate a frozen full parent and derive its explicitly selected scope.

    Embedded recipe/components are the authority after freezing. Optional
    input_files records describe provenance; their mutable paths are not read.
    File identity verification belongs to the caller's freezing boundary.
    """
    full = compile_assembly_layout(parent_plan["recipe"], parent_plan["components"])
    if {key: value for key, value in parent_plan.items() if key != "input_files"} != full:
        raise ContractError("parent composition plan differs from its frozen full assembly inputs")
    return (compile_assembly_layout(full["recipe"], full["components"], local_scope=local_scope)
            if local_scope is not None else full)
