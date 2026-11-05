"""Complete oaTOF scientific boundary groups and its real frontend domain.

OA owns accelerator mechanics and groups. This provider composes those with
its existing downstream physical projection, preserving the declared common
ground. Native labels and numerical detector markers do not define groups.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from msplatform.components.orthogonal_accelerator.electrode_topology import build_electrode_topology as build_oa_topology
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import (
    ResolvedAcceleratorGeometry, resolve_oa_provider,
)
from msplatform.components.single_reflection_oa_tof.geometry_contract import resolve_electrode_geometry


_COMMON_GROUND_MEMBERS = frozenset({
    "accelerator_side_shield", "flight_tube_shield", "reflectron_entry_grid", "detector",
})


def _downstream_sources(physical: Mapping[str, Any]) -> dict[str, Any]:
    """Read existing physical voltage/geometry results without redoing dividers."""
    ground = {row["role"] for row in physical["electrodes"] if row["grounded"]}
    if ground != _COMMON_GROUND_MEMBERS:
        raise ValueError("resolved common ground does not preserve its four physical members")
    result = {}
    for row in physical["electrodes"]:
        role = row["role"]
        if role.startswith("accelerator_"):
            continue
        if role in result:
            raise ValueError("duplicate downstream physical role")
        result[role] = dict(geometry=copy.deepcopy(row["geometry"]),
            operating_voltage_v=row["operating_voltage_v"])
    return result


def _oa_sources(electrical: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    sources = {name: {"pointer": f"/operating_voltages_v/{name}"}
               for name in electrical["planes_z_mm"]}
    sources["grounded_shield"] = {"pointer": "/operating_voltages_v/shield"}
    sources.update({f"ring_{index + 1:04d}": {"pointer": f"/operating_voltages_v/rings/{index}"}
                    for index in range(len(electrical["ring_z_mm"]))})
    return sources


def build_electrode_topology(
    resolved: dict[str, Any], *, projection: ResolvedAcceleratorGeometry,
    geometry_profile_id: str | None = None,
) -> dict[str, Any]:
    """Publish every scientific group for the supported three-zone square body.

    Member references address this returned document. The neutral physical source is
    read solely for its provider-owned downstream solids and voltage results;
    scientific identities are explicit roles/physical ring order, not its IDs.
    """
    oa = resolve_oa_provider(resolved, projection=projection, geometry_profile_id=geometry_profile_id)
    physical = resolve_electrode_geometry(resolved, accelerator_projection=projection)
    downstream = _downstream_sources(physical)
    groups = []
    for row in build_oa_topology(oa["mechanical"], voltage_sources=_oa_sources(oa["electrical"]),
                                 source_document=oa["electrical"]):
        grounded = row["electrode_group_id"] == "grounded_shield"
        refs = ["/sources/oa_mechanical" + pointer for pointer in row["member_refs"]]
        if grounded:
            refs.extend(f"/sources/downstream/{role}/geometry" for role in sorted(_COMMON_GROUND_MEMBERS)
                        if role != "accelerator_side_shield")
        groups.append(dict(electrode_group_id=("common_ground" if grounded else
                                              "accelerator_" + row["electrode_group_id"]),
            roles=(["grounded_boundary", *row["roles"], "reflectron_entry_grid", "detector"]
                   if grounded else list(row["roles"])), member_refs=refs,
            voltage_source={"pointer": "/sources/oa_electrical" + row["voltage_source"]["pointer"]}))
    frontend_ids = [row["electrode_group_id"] for row in groups]
    for role in downstream:
        if role in _COMMON_GROUND_MEMBERS:
            continue
        groups.append(dict(electrode_group_id=role, roles=[role.rsplit("_ring_", 1)[0] + "_ring"
                           if "_ring_" in role else role],
            member_refs=[f"/sources/downstream/{role}/geometry"],
            voltage_source={"pointer": f"/sources/downstream/{role}/operating_voltage_v"}))
    return dict(schema_version=1, role="oatof_electrode_topology", local_frame_id="oatof_global",
        length_unit="mm", voltage_unit="V", variant_id=projection.variant_id,
        sources=dict(oa_mechanical=oa["mechanical"], oa_electrical=oa["electrical"], downstream=downstream),
        groups=groups, frontend_electrode_group_ids=frontend_ids)


def resolve_frontend_field_domain(
    resolved: dict[str, Any], *, projection: ResolvedAcceleratorGeometry,
    geometry_profile_id: str | None = None,
) -> dict[str, Any]:
    """Independently publish the actual accelerator frontend group/member scope.

    The complete common-ground group also has downstream members. Only its OA
    shield is instantiated in this physical field domain. A binding record is
    never an authority for deciding the expected scope.
    """
    topology = build_electrode_topology(resolved, projection=projection, geometry_profile_id=geometry_profile_id)
    selected = [dict(electrode_group_id=row["electrode_group_id"],
                     member_refs=[ref for ref in row["member_refs"] if ref.startswith("/sources/oa_mechanical/")])
                for row in topology["groups"] if row["electrode_group_id"] in topology["frontend_electrode_group_ids"]]
    return dict(schema_version=1, role="oatof_frontend_field_domain", domain_id="accelerator_frontend",
                variant_id=projection.variant_id, local_frame_id="oatof_global", length_unit="mm",
                electrode_group_ids=[row["electrode_group_id"] for row in selected], members=selected)
