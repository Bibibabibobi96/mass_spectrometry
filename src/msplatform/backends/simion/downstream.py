"""Validated downstream GEM specifications, without execution or file writes."""
from __future__ import annotations
import copy
import math
from .resources import gem_template_text
from .tof_geometry import resolve_physical_geometry, derive_simion_instances

def _validate_provider_inputs(g: dict, b: dict, m: dict, rings: dict, v: dict) -> None:
    """Apply the three provider builders' numeric preconditions before staging."""
    # Sources: simion/workbench/build_{flight_tube,detector}_variant.lua and
    # simion/reflectron/build_reflectron_variant.lua under the oaTOF provider.
    positive = [
        ("geometry_mm", g, ("flight_tube_r", "flight_tube_wall", "shield_endcap_thickness",
                            "L_reflectron", "ring_thickness", "shield_axial_gap", "L_stage1",
                            "L_stage2", "bore_r", "ring_outer_r")),
        ("flight_tube", b["flight_tube"], ("cell_axial_mm", "cell_radial_mm", "max_gib")),
        ("reflectron", b["reflectron"], ("cell_axial_mm", "cell_radial_mm", "max_gib")),
        ("detector", b["detector"], ("margin_xy_mm", "max_mib")),
        ("simion_detector_marker", m, ("cell_xy_mm", "cell_z_mm", "active_radius_mm",
                                      "absorber_thickness_mm", "front_margin_z_mm", "back_margin_z_mm")),
    ]
    for label, values, keys in positive:
        for key in keys:
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"downstream {label}.{key} must be finite and positive")
    for label, values, keys in (("geometry_mm", g, ("shield_outer_z_min", "L_flight")),
                                ("electrodes_V", v, ("midgrid", "backplate"))):
        for key in keys:
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"downstream {label}.{key} must be finite")
    if g["L_flight"] - g["shield_outer_z_min"] <= g["shield_endcap_thickness"]:
        raise ValueError("downstream flight_tube interface must lie beyond the near cap")
    if not g["bore_r"] < g["ring_outer_r"] < g["flight_tube_r"]:
        raise ValueError("downstream reflectron radii must be ordered")
    if abs(g["L_reflectron"] - g["L_stage1"] - g["L_stage2"]) >= 1e-9:
        raise ValueError("downstream reflectron length must equal stage1 + stage2")
    for key in ("stage1_count", "stage2_count"):
        value = rings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 1 or value != math.floor(value):
            raise ValueError(f"downstream rings.{key} must be a positive integer")
    middle = g["L_stage1"] / b["reflectron"]["cell_axial_mm"]
    if abs(middle - math.floor(middle + 0.5)) > 1e-8:
        raise ValueError("downstream reflectron midgrid zero-width sheet must lie on a raw PA row")
    for key, minimum in (("absorber_thickness_mm", 5 * m["cell_z_mm"]),
                          ("front_margin_z_mm", 10 * m["cell_z_mm"]),
                          ("back_margin_z_mm", 5 * m["cell_z_mm"])):
        if m[key] < minimum:
            raise ValueError(f"downstream detector {key} is below its provider cell-span minimum")
    if b["detector"]["margin_xy_mm"] < m["cell_xy_mm"]:
        raise ValueError("downstream detector margin_xy_mm must span at least one xy cell")


def compile_downstream_specs(resolved: dict) -> tuple[dict, ...]:
    """Bind the three original templates to complete provider/numerical inputs.

    Templates use SIMION's documented Lua preprocessing context ``_G.var``.
    No Refine/Fly or scientific source is required to compile these specs.
    """
    g, b, m = (resolved[k] for k in ("geometry_mm", "simion_geometry_build", "simion_detector_marker"))
    _validate_provider_inputs(g, b, m, resolved["rings"], resolved["electrodes_V"])
    physical = resolve_physical_geometry(resolved)
    face = physical["detector_active_face"]
    if m["active_plane_z_mm"] != face["center_mm"][2] or m["active_radius_mm"] != face["radius_mm"]:
        raise ValueError("numerical detector marker differs from the physical detector active face")
    domains = derive_simion_instances(geometry=g, coordinate=resolved["coordinate_convention"], build=b, marker=m)
    by_role = {("flight_tube" if d["role"]=="flight_tube_shield" else d["role"]):d for d in domains}
    specs = []
    for role in ("flight_tube", "reflectron", "detector"):
        mesh = b[role]
        if role == "detector":
            variables = dict(mmgu_xy=m["cell_xy_mm"], mmgu_z=m["cell_z_mm"], radius=m["active_radius_mm"],
                absorber_thickness=m["absorber_thickness_mm"], margin_xy=mesh["margin_xy_mm"],
                front_margin_z=m["front_margin_z_mm"], back_margin_z=m["back_margin_z_mm"])
        else:
            variables = dict(mmgu_axial=mesh["cell_axial_mm"], mmgu_radial=mesh["cell_radial_mm"],
                             component=copy.deepcopy(physical["simion"][role]))
        specs.append(dict(role=role, template_text=gem_template_text(role), template_variables=variables,
            native_instance=copy.deepcopy(by_role[role]),
            template_context="SIMION_GEM_Lua_global_var", action="gem2pa_only"))
    return tuple(specs)
