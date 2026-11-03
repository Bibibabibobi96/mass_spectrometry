"""Provider-owned electrical groups referencing one resolved RF geometry.

Member references are JSON pointers into the supplied document, not copied
geometry. Native numbering and solver capacity are outside this module.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def build_electrode_topology(resolved: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return complete scientific groups without loading any solver adapter.

    Continuous groups use RF polarity; segmented groups additionally use the
    declared segment identity. Invalid member coverage or drive conflicts raise
    ValueError. The document and its dimensions/voltages are never modified.
    """
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("electrode topology requires a multipole resolved design")
    geometry = resolved["geometry_mm"]
    if geometry["enclosure"]["model"] not in {"bare", "cylindrical_grounded_shell"}:
        raise ValueError("electrode topology requires a bare or grounded-shell multipole")
    rods = geometry["rod_array"]["rods"]
    if not isinstance(rods, list) or not rods:
        raise ValueError("electrode topology requires physical rods")
    parents = {}
    for rod in rods:
        identity, group = rod.get("rod_id"), rod.get("electrode_group")
        if type(identity) is not int or identity < 1 or identity in parents or type(group) is not int or group not in (1, 2):
            raise ValueError("physical rod identity/group is invalid or duplicated")
        parents[identity] = group
    if set(parents.values()) != {1, 2}:
        raise ValueError("physical rods require both RF groups")
    drive = resolved["drive"]
    if any(not _finite(drive.get(key)) for key in ("common_mode_offset_V", "dc_amplitude_V_per_group")):
        raise ValueError("resolved drive source must be finite")
    groups = {}
    segmented = resolved["segmentation"]["segmented_rod_array"]
    if segmented is None:
        for index, rod in enumerate(rods):
            group = rod["electrode_group"]
            key = f"rod_group_{group}"
            if key not in groups:
                groups[key] = dict(electrode_group_id=key, roles=["rod"], member_refs=[], voltage_source=dict(
                    kind="rf_drive", rf_group=group, common_mode_pointer="/drive/common_mode_offset_V",
                    dc_amplitude_pointer="/drive/dc_amplitude_V_per_group"))
            groups[key]["member_refs"].append(f"/geometry_mm/rod_array/rods/{index}")
    else:
        count, members = segmented.get("segment_count"), segmented.get("electrodes")
        if type(count) is not int or count < 2 or not isinstance(members, list) or not members:
            raise ValueError("segmented topology requires complete declared segments")
        seen, voltages, intervals = set(), {}, {}
        for index, member in enumerate(members):
            segment, group = member.get("segment_id"), member.get("electrode_group")
            parent = member.get("parent_rod_id", member.get("rod_id"))
            if (type(segment) is not int or not 1 <= segment <= count or type(parent) is not int
                    or parent not in parents or type(group) is not int or group != parents[parent]):
                raise ValueError("segmented physical table is missing or duplicates a rod group identity")
            pair = (segment, parent)
            if pair in seen:
                raise ValueError("segmented physical table is missing or duplicates a rod group")
            seen.add(pair)
            voltage = member.get("common_mode_V")
            if not _finite(voltage):
                raise ValueError("segmented rod must declare finite common-mode voltage")
            lo, hi = member.get("z_min_mm"), member.get("z_max_mm")
            if not _finite(lo) or not _finite(hi) or lo >= hi:
                raise ValueError("segmented rod length must be finite and positive")
            if segment in intervals and intervals[segment] != (lo, hi):
                raise ValueError("segmented rods disagree on their physical axial interval")
            intervals[segment] = (lo, hi)
            if segment in voltages and voltages[segment] != voltage:
                raise ValueError("segmented rod has conflicting resolved drive source")
            voltages[segment] = voltage
            key = f"segment_{segment:04d}_rf_group_{group}"
            if key not in groups:
                groups[key] = dict(electrode_group_id=key, roles=["rod"], member_refs=[], voltage_source=dict(
                    kind="rf_drive", rf_group=group,
                    common_mode_pointer=f"/segmentation/segmented_rod_array/electrodes/{index}/common_mode_V",
                    dc_amplitude_pointer="/drive/dc_amplitude_V_per_group"))
            groups[key]["member_refs"].append(f"/segmentation/segmented_rod_array/electrodes/{index}")
        if len(seen) != count * len(parents):
            raise ValueError("segmented physical table is missing or duplicates a rod group")
    bodies, static = geometry["enclosure_layout"]["bodies"], resolved["static_electrodes_V"]
    if bodies:
        if (geometry["enclosure"]["model"] != "cylindrical_grounded_shell"
                or static.get("role") != "grounded_shell_static_electrodes"
                or not _finite(static.get("ground_V")) or static["ground_V"] != 0):
            raise ValueError("the enclosure and its optional endcaps must share ground")
        roles = [body["role"] for body in bodies]
        expected_roles = {"shell"} | {side + "_endcap" for side in geometry["enclosure"].get("endcaps", {})}
        if len(set(roles)) != len(roles) or set(roles) != expected_roles:
            raise ValueError("enclosure body roles are incomplete or duplicated")
        groups["grounded_shell"] = dict(electrode_group_id="grounded_shell", roles=roles,
            member_refs=[f"/geometry_mm/enclosure_layout/bodies/{index}" for index in range(len(bodies))],
            voltage_source=dict(kind="static", pointer="/static_electrodes_V/ground_V"))
    elif geometry["enclosure"]["model"] != "bare" or static != {"role": "bare_multipole_static_electrodes"}:
        raise ValueError("a bare multipole cannot declare enclosure voltages or missing shell bodies")
    return tuple(groups.values())
