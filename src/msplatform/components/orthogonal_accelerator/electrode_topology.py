"""OA electrical groups over existing mechanical and explicit drive sources.

Member JSON pointers address the supplied three-zone document, or asdict() of
ClosedTwoZoneGeometry. Several parameter references can jointly describe one
physical member; a pointer is not necessarily a separately manufactured solid.
No solver numbering, geometry dimensions or voltage values are copied here.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from math import isfinite
from typing import Any

from msplatform.components.orthogonal_accelerator.two_zone_geometry import ClosedTwoZoneGeometry


def _at_pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("source/member reference requires a nonempty JSON pointer")
    value = document
    for raw in pointer[1:].split("/"):
        if any(not part or part[0] not in "01" for part in raw.split("~")[1:]):
            raise ValueError("invalid JSON pointer escape")
        key = raw.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, (list, tuple)):
                if not key.isascii() or not key.isdecimal() or str(int(key)) != key:
                    raise ValueError("array reference requires a canonical nonnegative index")
                value = value[int(key)]
            elif isinstance(value, Mapping):
                value = value[key]
            else:
                raise ValueError("reference traverses a scalar")
        except (KeyError, IndexError) as error:
            raise ValueError(f"reference does not exist: {pointer}") from error
    return value


def _mechanical_groups(resolved: ClosedTwoZoneGeometry | Mapping[str, Any]) -> tuple[Mapping[str, Any], list[tuple[str, list[str], list[str]]]]:
    if isinstance(resolved, ClosedTwoZoneGeometry):
        document = asdict(resolved)
    elif isinstance(resolved, Mapping) and resolved.get("role") == "orthogonal_accelerator_two_zone_geometry":
        document = resolved
    else:
        document = None
    if document is not None:
        if len(document["grid_supports"]) != 2 or not document["rings"]:
            raise ValueError("two-zone topology requires both supports and its rings")
        enclosure = [f"/enclosure/{key}" for key in document["enclosure"]
                     if key not in {"lateral_clearance_mm", "electrode_half_x_mm", "electrode_half_y_mm"}]
        groups = [
            ("grounded_shield", ["shield", "rear_cap"], enclosure + ["/local_exit_z_mm", "/aperture_half_x_mm", "/aperture_half_y_mm"]),
            ("repeller", ["repeller"], ["/local_repeller_z_mm", "/repeller_thickness_mm",
                                        "/enclosure/electrode_half_x_mm", "/enclosure/electrode_half_y_mm"]),
            ("intermediate_grid_1", ["intermediate_grid_1", "grid_support", "ideal_transparent_sheet"], ["/grid_supports/0"]),
            ("exit_grid", ["exit_grid", "grid_support", "ideal_transparent_sheet"], ["/grid_supports/1"]),
        ]
        if document["side_entry"] is not None:
            groups[0][2].append("/side_entry/physical_cutout_box_mm")
        groups.extend((f"ring_{index + 1:04d}", ["ring"], [f"/rings/{index}",
                       "/enclosure/electrode_half_x_mm", "/enclosure/electrode_half_y_mm",
                       "/aperture_half_x_mm", "/aperture_half_y_mm"])
                      for index in range(len(document["rings"])))
    elif isinstance(resolved, Mapping) and resolved.get("role") in {
        "orthogonal_accelerator_sectioned_three_zone_geometry", "instrument_sectioned_accelerator_mechanics_projection",
    }:
        if type(resolved.get("schema_version")) is not int or resolved["schema_version"] != 1:
            raise ValueError("three-zone topology requires explicit sectioned geometry schema 1")
        if resolved["role"] == "instrument_sectioned_accelerator_mechanics_projection" and (
            resolved.get("producer") != "single_reflection_oa_tof_mass_analyzer"
            or resolved.get("source_role") != "oatof_validated_sectioned_accelerator_geometry"
            or type(resolved.get("source_schema_version")) is not int or resolved["source_schema_version"] != 1
            or resolved.get("standalone_component_capability") is not False
        ):
            raise ValueError("unknown instrument mechanics source or capability")
        document = resolved
        geometry = resolved["geometry"]
        rings = resolved["ring_z_mm"]
        sheets = resolved["canonical_electrodes"]["ideal_sheets"]
        if (not rings or len(rings) != geometry["ring_count"] or rings != geometry["ring_z_mm"]
                or [row["name"] for row in sheets] != ["grid1", "intermediate2", "exit"]):
            raise ValueError("three-zone topology requires all declared rings and sheets")
        shield = ["axis_x_mm", "axis_y_mm", "shield_outer_width_mm", "shield_inner_width_mm",
                  "shield_back_z_mm", "grid2_z_mm", "shield_wall_mm", "cross_section",
                  "negative_x_face_mm", "port_center_y_mm", "port_center_z_mm",
                  "numerical_port_width_mm", "numerical_port_height_mm"]
        groups = [
            ("grounded_shield", ["shield", "rear_cap"], [f"/geometry/{key}" for key in shield]),
            ("repeller", ["repeller"], ["/canonical_electrodes/repeller"]),
            *[(name, [name, "ideal_zero_thickness_sheet"], [f"/canonical_electrodes/ideal_sheets/{index}"])
              for index, name in enumerate(("intermediate_grid_1", "intermediate_grid_2", "exit_grid"))],
        ]
        groups.extend((f"ring_{index + 1:04d}", ["ring"], [f"/geometry/ring_z_mm/{index}",
                       *[f"/geometry/{key}" for key in ("ring_thickness_mm", "cross_section", "axis_x_mm",
                                                       "axis_y_mm", "electrode_width_mm", "bore_width_mm")]])
                      for index in range(len(rings)))
    else:
        raise ValueError("topology requires resolved OA two-zone or three-zone mechanics")
    for _, _, refs in groups:
        for ref in refs:
            _at_pointer(document, ref)
    return document, groups


def build_electrode_topology(
    resolved: ClosedTwoZoneGeometry | Mapping[str, Any], *,
    voltage_sources: Mapping[str, Mapping[str, str]], source_document: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Bind every real OA group to an explicit finite voltage-source reference.

    Sources must cover electrode-group IDs exactly, each as {'pointer': JSONPointer}
    into source_document. References do not imply a static waveform; the caller
    retains source identity, units (V), clock and freezing in its existing record.
    Repeated pointers are allowed without merging groups. The existing grounded
    shield contract requires 0 V. Invalid coverage/references raise ValueError;
    inputs are never modified, and schema-1 interface publication is unaffected.
    """
    _, groups = _mechanical_groups(resolved)
    if not isinstance(source_document, Mapping) or not isinstance(voltage_sources, Mapping):
        raise ValueError("explicit OA voltage source document and bindings required")
    if set(voltage_sources) != {name for name, _, _ in groups}:
        raise ValueError("voltage sources must cover exactly every scientific electrode")
    result = []
    for name, roles, refs in groups:
        source = voltage_sources[name]
        if not isinstance(source, Mapping) or set(source) != {"pointer"}:
            raise ValueError("voltage source must contain exactly its pointer")
        value = _at_pointer(source_document, source["pointer"])
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError(f"voltage source for {name} must reference a finite number in V")
        if name == "grounded_shield" and value != 0:
            raise ValueError("grounded shield source must be 0 V")
        result.append(dict(electrode_group_id=name, roles=roles, member_refs=refs, voltage_source=dict(source)))
    return tuple(result)
