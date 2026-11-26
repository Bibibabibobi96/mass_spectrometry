"""Physical single-reflection TOF projection, independent of OA or a solver."""
from __future__ import annotations

import math
from msplatform.components.rf_multipole.grounded_shield import require_grounded_potential

DOWNSTREAM_GEOMETRY_KEYS = frozenset({
    "flight_tube_r", "flight_tube_wall", "shield_endcap_thickness", "L_reflectron",
    "ring_thickness", "shield_axial_gap", "L_stage1", "L_stage2", "bore_r", "ring_outer_r",
    "detector_radius", "detector_thickness", "shield_outer_z_min", "L_flight", "detector_z",
})


def resolve_downstream_geometry(g: dict, coordinate: dict, rings: dict, voltage: dict) -> dict:
    """Return the ordered physical members, potentials and vacuum envelope in mm/V."""
    positive = ("flight_tube_r", "flight_tube_wall", "shield_endcap_thickness", "L_reflectron",
                "ring_thickness", "shield_axial_gap", "L_stage1", "L_stage2", "bore_r", "ring_outer_r",
                "detector_radius", "detector_thickness")
    if any(isinstance(g[k], bool) or not isinstance(g[k], (int, float)) or not math.isfinite(g[k]) or g[k] <= 0 for k in positive):
        raise ValueError("downstream physical lengths must be finite and positive")
    if not g["bore_r"] < g["ring_outer_r"] < g["flight_tube_r"]:
        raise ValueError("reflectron radii must be ordered")
    if not math.isclose(g["L_reflectron"], g["L_stage1"] + g["L_stage2"], rel_tol=0, abs_tol=1e-10):
        raise ValueError("reflectron length is inconsistent")
    if g["L_flight"] - g["shield_outer_z_min"] <= g["shield_endcap_thickness"]:
        raise ValueError("reflectron interface must lie beyond the near cap")
    objects = []
    def electrode(role, geometry, *, volts=0, grounded=False):
        body = dict(role=role, grounded=grounded, geometry=geometry, operating_voltage_v=volts)
        objects.append(body)
        return body
    outer_radius = g["flight_tube_r"] + g["flight_tube_wall"]
    near = g["shield_outer_z_min"]
    interface = g["L_flight"]
    local_bore_end = g["L_reflectron"] + g["ring_thickness"] + g["shield_axial_gap"]
    local_outer_end = local_bore_end + g["shield_endcap_thickness"]
    bore_end, outer_end = interface + local_bore_end, interface + local_outer_end
    shield_parts = [
        dict(axial_mm=[near, near + g["shield_endcap_thickness"]], radius_mm=[0, outer_radius]),
        dict(axial_mm=[near + g["shield_endcap_thickness"], bore_end], radius_mm=[g["flight_tube_r"], outer_radius]),
        dict(axial_mm=[bore_end, outer_end], radius_mm=[0, outer_radius]),
    ]
    shield = electrode("flight_tube_shield", dict(primitive="cylindrical_union",
        axis_xy_mm=list(coordinate["reflectron_axis"]), parts=shield_parts), grounded=True)
    shield["flight_tube_local_regions"] = [
        dict(axial_mm=[0, g["shield_endcap_thickness"]], radius_mm=[0, outer_radius]),
        dict(axial_mm=[g["shield_endcap_thickness"], interface-near], radius_mm=[g["flight_tube_r"], outer_radius])]
    def reflector_electrode(role: str, z0: float, z1: float, r0: float, r1: float,
                            volts: float, *, grounded: bool = False) -> None:
        body = electrode(role, dict(primitive="cylindrical_region",
            axis_xy_mm=list(coordinate["reflectron_axis"]), axial_mm=[interface+z0, interface+z1],
            radius_mm=[r0, r1]), volts=volts, grounded=grounded)
        body["reflectron_local_regions"] = [dict(axial_mm=[z0, z1], radius_mm=[r0, r1])]

    reflector_electrode("reflectron_entry_grid", 0, 0, 0, g["flight_tube_r"],
        require_grounded_potential(voltage["entgrid"], "oaTOF reflectron entrance grid"), grounded=True)
    counts = [rings["stage1_count"], rings["stage2_count"]]
    if any(type(count) is not int or count < 1 for count in counts):
        raise ValueError("reflectron ring counts must be positive integers")
    for stage, count, start, length, v0, v1 in (
        (1, counts[0], 0, g["L_stage1"], 0, voltage["midgrid"]),
        (2, counts[1], g["L_stage1"], g["L_stage2"], voltage["midgrid"], voltage["backplate"]),
    ):
        for index in range(1, count+1):
            center = start + index * (length / (count+1))
            volts = v0 + (v1-v0) * index / (count+1)
            reflector_electrode(f"reflectron_stage{stage}_ring_{index}",
                center-g["ring_thickness"]/2, center+g["ring_thickness"]/2,
                g["bore_r"], g["ring_outer_r"], volts)
        if stage == 1:
            reflector_electrode("reflectron_midgrid", g["L_stage1"], g["L_stage1"],
                0, g["ring_outer_r"], voltage["midgrid"])
    reflector_electrode("reflectron_backplate", g["L_reflectron"], g["L_reflectron"]+g["ring_thickness"],
        0, g["ring_outer_r"], voltage["backplate"])
    shield["reflectron_local_regions"] = [
        dict(axial_mm=[0, local_bore_end], radius_mm=[g["flight_tube_r"], outer_radius]),
        dict(axial_mm=[local_bore_end, local_outer_end], radius_mm=[0, outer_radius])]
    electrode("detector", dict(primitive="cylinder", radius_mm=g["detector_radius"],
        base_center_mm=[coordinate["detector_x"], 0, g["detector_z"]-g["detector_thickness"]],
        height_mm=g["detector_thickness"], axis=[0, 0, 1]), grounded=True)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in [*g.values(), *coordinate["reflectron_axis"], coordinate["detector_x"], *voltage.values()]):
        raise ValueError("downstream geometry and voltages must be finite")
    return dict(electrodes=objects, detector_active_face=dict(role="detector",
        center_mm=[coordinate["detector_x"], 0, g["detector_z"]], normal=[0, 0, 1], radius_mm=g["detector_radius"]),
        local_extents=dict(flight_tube_axial_span_mm=interface-near, reflectron_axial_span_mm=local_outer_end, outer_radius_mm=outer_radius),
        vacuum_domain=dict(domain_id="flight_tube_cavity", shape="cylinder", axis="z",
            center_xy_mm=list(coordinate["reflectron_axis"]), z_min_mm=near+g["shield_endcap_thickness"],
            z_max_mm=bore_end, radius_mm=g["flight_tube_r"]))
