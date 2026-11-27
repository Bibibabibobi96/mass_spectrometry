"""Project one resolved OA-TOF design into its two physical component authors."""
from __future__ import annotations

from typing import Any, Mapping

from msplatform.components.single_reflection_oa_tof.accelerator_geometry import (
    apply_side_opening, resolve_accelerator_geometry, resolve_oa_provider,
)
from msplatform.components.single_reflection_tof.legacy_projection import project_legacy_downstream


def project_split_component_requests(resolved: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return exact OA and downstream physical authors for a resolved three-zone design.

    This projection never invents a Study, release, clock, voltage schedule,
    numerical setting, assembly pose or solver. Those remain explicit authors.
    """
    if not isinstance(resolved, Mapping) or not isinstance(resolved.get("mechanical_side_opening"), Mapping):
        raise ValueError("resolved OA-TOF design requires its explicit mechanical side opening")
    physical = apply_side_opening(resolve_accelerator_geometry(resolved, variant_id="three_zone_square"),
                                  side_opening=resolved["mechanical_side_opening"])
    oa = resolve_oa_provider(resolved, projection=physical, geometry_profile_id=None)
    return {"oa": {"provider_id": "orthogonal_accelerator", "design": {"instrument_geometry": oa["source"]}},
            "tof": {"provider_id": "single_reflection_tof", "design": project_legacy_downstream(resolved)}}


def validate_split_study_physical_author(resolved: Mapping[str, Any], study: Mapping[str, Any], *,
                                         oa_instance_id: str, tof_instance_id: str) -> dict[str, Any]:
    """Check exact physical authors and on-workpoint voltages, without claiming waveform equivalence."""
    import math
    from msplatform.components.single_reflection_tof.geometry import resolve_downstream_geometry

    if (not isinstance(oa_instance_id, str) or not oa_instance_id or not isinstance(tof_instance_id, str)
            or not tof_instance_id or oa_instance_id == tof_instance_id or not isinstance(study, Mapping)):
        raise ValueError("two distinct explicit component instance IDs are required")
    expected = project_split_component_requests(resolved)
    requests = study.get("component_requests")
    if (not isinstance(requests, Mapping) or requests.get(oa_instance_id) != expected["oa"]
            or requests.get(tof_instance_id) != expected["tof"]):
        raise ValueError("Study physical component authors differ from the resolved design")
    projection = apply_side_opening(resolve_accelerator_geometry(resolved, variant_id="three_zone_square"),
                                    side_opening=resolved["mechanical_side_opening"])
    electrical = resolve_oa_provider(resolved, projection=projection, geometry_profile_id=None)["electrical"]
    oa_voltages = electrical["operating_voltages_v"]
    oa_expected = {"grounded_shield": oa_voltages["shield"],
                   **{name: oa_voltages[name] for name in ("repeller", "intermediate_grid_1", "intermediate_grid_2", "exit_grid")},
                   **{f"ring_{index:04d}": value for index, value in enumerate(oa_voltages["rings"], start=1)}}
    design = expected["tof"]["design"]
    physical = resolve_downstream_geometry(design["geometry_mm"], design["coordinate_convention"],
                                           design["rings"], design["electrodes_v"])
    grounded = {"flight_tube_shield", "reflectron_entry_grid", "detector"}
    tof_expected = {}
    for electrode in physical["electrodes"]:
        name = "common_ground" if electrode["role"] in grounded else electrode["role"]
        value = electrode["operating_voltage_v"]
        if name in tof_expected and tof_expected[name] != value:
            raise ValueError("grounded physical members have different voltages")
        tof_expected[name] = value
    groups = study.get("drive", {}).get("groups", {})
    for instance, expected_voltages in ((oa_instance_id, oa_expected), (tof_instance_id, tof_expected)):
        actual = groups.get(instance) if isinstance(groups, Mapping) else None
        if not isinstance(actual, Mapping) or set(actual) != set(expected_voltages):
            raise ValueError("Study electrode groups differ from the physical projection")
        for name, expected_voltage in expected_voltages.items():
            row = actual[name]
            if not isinstance(row, Mapping):
                raise ValueError("Study voltage group is invalid")
            value = row.get("on_voltage_v") if row.get("kind") == "pulse" else row.get("voltage_v") if row.get("kind") == "static" else None
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or value != expected_voltage):
                raise ValueError("Study on-workpoint voltage differs from the physical projection")
    return {"scope": "geometry_and_on_workpoint_only", "oa_instance_id": oa_instance_id,
            "tof_instance_id": tof_instance_id,
            "not_verified": ["off_workpoint", "pulse", "clock", "release", "numerics"]}
