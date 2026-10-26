"""Compile explicit bare-guide geometry and resolve native frontend instance bindings."""

from __future__ import annotations

import json
import math
from typing import Any

from common.multipole.axial_acceleration import SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
from common.multipole.simion_geometry import (
    render_grouped_rod_array_gem,
)
from common.simion.aperture import resolve_rectangular_aperture_discretization
from common.simion.gem_primitives import (
    format_number as _fmt,
)
from integrations.runtime.single_flight_electrode_contract import (
    ROD_ELECTRODE_IDS,
    THREE_ZONE_BARE_VARIANT,
    frontend_electrodes,
    resolve_frontend_electrode_topology,
)

_COMPONENT_ROTATION = [[0, 1, 0], [1, 0, 0], [0, 0, -1]]
_BARE_VARIANT = "canonical_two_zone_bare_continuous_rods_v1"


def _component_point(point: list[float], rotation: list, translation: list) -> list[float]:
    return [sum(rotation[a][k]*point[k] for k in range(3))+translation[a] for a in range(3)]


def _component_bounds(boxes: list[list[float]], rotation: list, translation: list) -> dict[str, float]:
    points = [_component_point([box[0 if x == 0 else 3], box[1 if y == 0 else 4],
                                box[2 if z == 0 else 5]], rotation, translation)
              for box in boxes for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    return {f"{axis}_{side}": operation(p[a] for p in points)
            for a, axis in enumerate("xyz") for side, operation in (("min", min), ("max", max))}


def _canonical_three_zone_component(component: dict[str, Any], *, cells: dict[str, float],
                                    target_solver_frame: str | None) -> dict[str, Any]:
    """Project the existing explicit sectioned provider; copy no OA CSG model."""
    from projects.orthogonal_accelerator.simion.bare_three_zone_component import (
        resolve_bare_three_zone_component, render_bare_three_zone_electrode_body,
    )
    from integrations.runtime.single_flight_electrode_contract import (
        project_pa_plus_mode_voltages, resolve_three_zone_bare_pa_plus_solution_model,
    )
    required = {"schema_version", "role", "variant_id", "geometry_profile_id", "requirements",
                "transform", "local_electrode_ids", "electrode_voltages_v", "pulse_voltage_policy_id"}
    if (set(component) != required or type(component["schema_version"]) is not int or component["schema_version"] != 1
            or component["role"] != "rf_oatof_accelerator_component" or component["variant_id"] != "three_zone"
            or not isinstance(component["geometry_profile_id"], str) or not component["geometry_profile_id"]):
        raise ValueError("explicit canonical three-zone accelerator component required")
    if target_solver_frame not in (None, "mrtof_global_cartesian"):
        raise ValueError("unsupported canonical three-zone solver frame")
    mr = target_solver_frame == "mrtof_global_cartesian"
    rotation = _COMPONENT_ROTATION if mr else [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    transform = component["transform"]
    if not isinstance(transform, dict) or set(transform) != {"rotation", "translation_mm"} or transform["rotation"] != rotation:
        raise ValueError("sectioned component requires proper slow+x/main+z to native slow+y/main-z pose")
    translation = transform["translation_mm"]
    if (not isinstance(translation, list) or len(translation) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in translation)):
        raise ValueError("sectioned component translation must be finite xyz")
    resolved = resolve_bare_three_zone_component(component["requirements"])
    electrodes = frontend_electrodes(ring_count=len(resolved["ring_z_mm"]), three_zone=True, variant=THREE_ZONE_BARE_VARIANT)
    expected = {1: electrodes["grounded_shield_id"], 2: electrodes["accelerator_repeller_id"],
                3: electrodes["accelerator_grid1_id"], 4: electrodes["accelerator_intermediate2_id"],
                5: electrodes["accelerator_grid2_id"],
                **dict(zip(resolved["electrodes"]["accelerator_ring_ids"], electrodes["accelerator_ring_ids"]))}
    mapping, volts = component["local_electrode_ids"], component["electrode_voltages_v"]
    if (not isinstance(mapping, dict) or set(mapping) != {str(k) for k in expected}
            or any(type(v) is not int for v in mapping.values()) or {int(k): v for k, v in mapping.items()} != expected):
        raise ValueError("sectioned component namespace differs from the actual bare three-zone basis")
    if (not isinstance(volts, dict) or set(volts) != set(mapping)
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in volts.values())):
        raise ValueError("complete finite sectioned component electrode voltages required")
    values = {expected[int(k)]: float(v) for k, v in volts.items()}
    if values[9] != 0. or component["pulse_voltage_policy_id"] != "all_accelerator_electrodes_zero_before_pulse_v1":
        raise ValueError("explicit grounded sectioned shield and zero-before-pulse policy required")
    def world_bounds(box: dict) -> dict:
        return _component_bounds([[box[f"{a}_{side}"] for side in ("min", "max") for a in "xyz"]], rotation, translation)
    planes = {name: translation[2] + (-z if mr else z) for name, z in resolved["planes"].items()}
    rings = [translation[2] + (-z if mr else z) for z in resolved["ring_z_mm"]]
    model = resolve_three_zone_bare_pa_plus_solution_model(electrodes, planes_global_z_mm=planes, ring_z_mm=rings,
                                                          acceleration_direction=-1 if mr else 1)
    project_pa_plus_mode_voltages(model, {**dict.fromkeys(ROD_ELECTRODE_IDS, 0.), **values})
    local_cells = dict(x=cells["y"], y=cells["x"], z=cells["z"]) if mr else cells
    lines = render_bare_three_zone_electrode_body(resolved, cell_mm_xyz=local_cells, local_electrode_ids=expected)
    body = [f"  locate({_fmt(translation[0])},{_fmt(translation[1])},{_fmt(translation[2])}) {{"]
    if mr:
        body.extend(["    rotate_z(90) { rotate_x(180) {", *lines, "    } }"])
    else:
        body.extend(lines)
    body.append("  }")
    g, raw_port = resolved["geometry"], resolved["port"]
    port = dict(raw_port, normal_axis="y" if mr else "x",
                center_mm=_component_point(raw_port["center_mm"], rotation, translation),
                flange_min_mm=translation[1 if mr else 0]+raw_port["flange_min_mm"],
                flange_max_mm=translation[1 if mr else 0]+raw_port["flange_max_mm"])
    if not mr:
        port["negative_x_face_mm"] = port["flange_min_mm"]
    return dict(body=body, electrodes=electrodes, actual_bounds_mm=world_bounds(resolved["actual_bounds_mm"]),
                planes=planes, ring_z_mm=rings, port=port, pa_plus_solution_model=model,
                first_gap_bounds_mm=world_bounds(resolved["first_gap_bounds_mm"]),
                axis_center_mm=_component_point([g["axis_x_mm"], g["axis_y_mm"], 0.], rotation, translation),
                operating_voltages_v={str(k): v for k, v in values.items()},
                off_voltages_v={str(k): 0. for k in values}, pulse_voltage_policy_id=component["pulse_voltage_policy_id"],
                canonical_electrodes=resolved["canonical_electrodes"], accelerator_component=component)


def _canonical_component(component: dict[str, Any], *, target_solver_frame: str | None = None, cells: dict[str, float] | None = None) -> dict[str, Any]:
    """Adapt the owned OA projection; no legacy scalar geometry or voltages."""
    if isinstance(component, dict) and component.get("variant_id") == "three_zone":
        if cells is None:
            raise ValueError("sectioned canonical adapter requires its actual xyz PA grid")
        return _canonical_three_zone_component(component, cells=cells, target_solver_frame=target_solver_frame)
    from projects.orthogonal_accelerator.simion.two_zone_candidate import (
        compile_closed_two_zone_accelerator, render_closed_two_zone_electrode_body,
    )
    from integrations.runtime.single_flight_electrode_contract import (
        project_pa_plus_mode_voltages, resolve_two_zone_bare_pa_plus_solution_model,
    )
    required = {"schema_version", "role", "variant_id", "geometry_profile_id", "requirements",
                "transform", "local_electrode_ids", "electrode_voltages_v", "pulse_voltage_policy_id"}
    if (not isinstance(component, dict) or set(component) != required or type(component["schema_version"]) is not int or component["schema_version"] != 1
            or component["role"] != "rf_oatof_accelerator_component" or component["variant_id"] != "two_zone"):
        raise ValueError("explicit canonical two-zone accelerator component required")
    mr_frame = target_solver_frame == "mrtof_global_cartesian"
    if target_solver_frame not in (None, "mrtof_global_cartesian"):
        raise ValueError("unsupported canonical target solver frame")
    rotation = [[1, 0, 0], [0, 1, 0], [0, 0, 1]] if mr_frame else _COMPONENT_ROTATION
    transform = component["transform"]
    if (not isinstance(transform, dict) or set(transform) != {"rotation", "translation_mm"}
            or transform["rotation"] != rotation):
        raise ValueError("component requires the proper +y to +x, -z to +z rotation")
    translation = transform["translation_mm"]
    if (not isinstance(translation, list) or len(translation) != 3
            or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in translation)):
        raise ValueError("component translation must be finite xyz")
    compiled = compile_closed_two_zone_accelerator(component["requirements"], geometry_profile_id=component["geometry_profile_id"])
    resolved = compiled.resolved_electrodes
    if resolved.side_entry is None:
        raise ValueError("continuous bare guide requires an explicit provider side entry")
    electrodes = frontend_electrodes(ring_count=len(resolved.rings), three_zone=False, variant=_BARE_VARIANT)
    expected = {15: electrodes["grounded_shield_id"], 22: electrodes["accelerator_repeller_id"],
                23: electrodes["accelerator_grid1_id"], 24: electrodes["accelerator_grid2_id"],
                **{int(r["id"]): target for r, target in zip(resolved.rings, electrodes["accelerator_ring_ids"])}}
    mapping = component["local_electrode_ids"]
    volts = component["electrode_voltages_v"]
    if (not isinstance(mapping, dict) or len(mapping) != len(expected) or {str(k) for k in mapping} != {str(k) for k in expected}
            or any(type(value) is not int for value in mapping.values())
            or {int(k): v for k, v in mapping.items()} != expected):
        raise ValueError("component namespace differs from the canonical bare-guide physical basis")
    if (not isinstance(volts, dict) or len(volts) != len(expected) or {str(k) for k in volts} != {str(k) for k in expected}
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in volts.values())):
        raise ValueError("complete finite component electrode voltages required")
    values = {expected[int(k)]: float(v) for k, v in volts.items()}
    if values[electrodes["grounded_shield_id"]] != 0:
        raise ValueError("canonical side-wall must remain grounded")
    if component["pulse_voltage_policy_id"] != "all_accelerator_electrodes_zero_before_pulse_v1":
        raise ValueError("explicit canonical OA zero-before-pulse policy required")
    data = resolved.to_dict()
    boxes = [data["grounded_enclosure"]["outer_box_mm"], data["repeller"]["solid_box_mm"],
             *[s["frame_outer_box_mm"] for s in data["grid_supports"]], *[r["outer_box_mm"] for r in data["rings"]]]
    arrays = [[b[f"{axis}_{side}_mm"] for side in ("min", "max") for axis in "xyz"] for b in boxes]
    bounds = _component_bounds(arrays, rotation, translation)
    sign = 1 if mr_frame else -1
    planes = {name: translation[2]+sign*z for name, z in (("repeller", resolved.local_repeller_z_mm),
              ("grid1", float(resolved.grid_supports[0]["grid_z_mm"])), ("exit", resolved.local_exit_z_mm))}
    ring_z = [translation[2]+sign*float(r["center_z_mm"]) for r in resolved.rings]
    model_kwargs = {"acceleration_direction": -1} if mr_frame else {}
    model = resolve_two_zone_bare_pa_plus_solution_model(electrodes, planes_global_z_mm=planes, ring_z_mm=ring_z, **model_kwargs)
    project_pa_plus_mode_voltages(model, {**{i: 0.0 for i in ROD_ELECTRODE_IDS}, **values})
    port = resolved.side_entry
    port_center = _component_point(port["center_mm"], rotation, translation)
    body = [f"  locate({_fmt(translation[0])},{_fmt(translation[1])},{_fmt(translation[2])}) {{",
            "    rotate_z(90) { rotate_x(180) {",
            *render_closed_two_zone_electrode_body(resolved, local_electrode_ids=expected), "    } }", "  }"]
    if mr_frame:
        body = [f"  locate({_fmt(translation[0])},{_fmt(translation[1])},{_fmt(translation[2])}) {{",
                *render_closed_two_zone_electrode_body(resolved, local_electrode_ids=expected), "  }"]
    face = {"normal_axis": "y", "flange_min_mm": translation[1]-resolved.enclosure.guard_half_y_mm,
            "flange_max_mm": translation[1]-resolved.enclosure.guard_inner_half_y_mm,
            "boolean_boundary_policy": "exclude_shape_inside_only_v1"} if mr_frame else {
        "negative_x_face_mm": translation[0]-resolved.enclosure.guard_half_y_mm}
    return dict(body=body, electrodes=electrodes, actual_bounds_mm=bounds, planes=planes, ring_z_mm=ring_z,
                port=dict(center_mm=port_center, **face,
                          wall_thickness_mm=resolved.enclosure.guard_wall_mm,
                          width_mm=2*float(port["half_width_x_mm"]), height_mm=2*float(port["half_width_z_mm"])),
                pa_plus_solution_model=model, operating_voltages_v={str(k): v for k, v in values.items()},
                off_voltages_v={str(k): 0.0 for k in values}, pulse_voltage_policy_id=component["pulse_voltage_policy_id"],
                canonical_electrodes=data, accelerator_component=json.loads(json.dumps(component)))


def _canonical_grid(raw_bounds: dict[str, float], cells: dict[str, float], *, origin: dict | None = None) -> dict:
    """Resolve the numerical grid without rendering or projecting any metal."""
    if (set(cells) != {"x", "y", "z"} or any(isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) or v <= 0 for v in cells.values())):
        raise ValueError("explicit finite positive canonical PA xyz cells required")
    origin = {a: 0.0 for a in "xyz"} if origin is None else origin
    bounds = {f"{a}_{side}": _outward_aligned_boundary(raw_bounds[f"{a}_{side}"], origin[a], cells[a], side=side)
              for a in "xyz" for side in ("min", "max")}
    dimensions = {f"n{a}": round((bounds[f"{a}_max"]-bounds[f"{a}_min"])/cells[a])+1 for a in "xyz"}
    if any(n < 3 for n in dimensions.values()):
        raise ValueError("canonical PA needs interior nodes in every axis")
    return dict(cell_mm_xyz=dict(cells), dimensions=dimensions, instance_bounds_mm=bounds,
                instance_origin_mm={a: bounds[f"{a}_min"] for a in "xyz"})


def _canonical_pa(body: list[str], numerical: dict) -> str:
    """Wrap a prepared body in its already resolved final PA grid."""
    cells, dimensions, bounds = (numerical[key] for key in ("cell_mm_xyz", "dimensions", "instance_bounds_mm"))
    lines = ["; Canonical provider electrodes; shared frontend workflow.",
             f"pa_define({dimensions['nx']},{dimensions['ny']},{dimensions['nz']},planar,none,electrostatic,,{_fmt(cells['x'])},{_fmt(cells['y'])},{_fmt(cells['z'])},surface=none)",
             f"locate({_fmt(-bounds['x_min'])},{_fmt(-bounds['y_min'])},{_fmt(-bounds['z_min'])}) {{", *body, "}", ""]
    return "\n".join(lines)


def render_bare_frontend_body(upstream: dict, registration: dict, accelerator_body: list[str], *, mr_frame: bool) -> list[str]:
    """Render previously validated canonical guide/OA solids without PA bounds.

    A containing compiler owns validation, PA extent and boundary conditions.
    This permits a real upstream conditioner in the same field solve without
    extracting GEM text or duplicating the existing provider geometry.
    """
    rotation, translation = registration["rotation_upstream_to_downstream"], registration["translation_mm"]
    phi = math.atan2(-rotation[2][0], rotation[0][0]) if mr_frame else math.atan2(rotation[2][0], rotation[1][0])
    angle_degrees = math.degrees(phi)
    rods = upstream["rod_array"]["rods"]
    body = [f"  locate({_fmt(translation[0])},{_fmt(translation[1])},{_fmt(translation[2])}) {{"]
    if angle_degrees != 0:
        body.append(f"    rotate_{'y' if mr_frame else 'x'}({_fmt(angle_degrees)}) {{")
    body.append("    rotate_x(-90) {" if mr_frame else "    rotate_y(90) { rotate_z(90) {")
    for pair in range(4):
        ids = (2*pair+1, 2*pair+2)
        array = {**upstream["rod_array"], "rods": [r for r in rods if r["physical_electrode_id"] in ids]}
        body.extend(render_grouped_rod_array_gem(array, electrode_group_ids={1: ids[0], 2: ids[1]}).splitlines())
    body.append("    }" if mr_frame else "    } }")
    if angle_degrees != 0:
        body.append("    }")
    body.extend(["  }", *accelerator_body])
    return body


def native_frontend_instances(plan: dict) -> tuple[tuple[str, ...], str]:
    """Select all native multipoles and the one oaTOF body in scope."""
    multipoles, analyzers = [], []
    for instance_id in plan['scope']['instance_ids']:
        project = plan['components'][instance_id]['project_id']
        if project == 'single_reflection_oa_tof_mass_analyzer':
            analyzers.append(instance_id)
        elif project in ('rf_quadrupole_ion_optics', 'rf_hexapole_ion_optics', 'rf_octupole_ion_optics'):
            multipoles.append(instance_id)
        else:
            raise ValueError(f'{instance_id}: native single-reflection renderer/field/drive is unsupported for {project}')
    if len(analyzers) != 1:
        raise ValueError(f'native single-reflection requires one oaTOF and zero or more multipoles; '
                         f'oaTOF={analyzers}, multipoles={multipoles}')
    return tuple(multipoles), analyzers[0]


def instance_design_record(preparation: dict, instance_id: str) -> dict:
    """Return the selected instance's sole frozen resolved-design record."""
    key = 'instance_design__' + instance_id
    try:
        return preparation['input_records'][key]
    except KeyError as error:
        raise ValueError(f'{instance_id}: frozen resolved-design record is missing') from error


def _electrodes(mapping: dict, ring_count: int, three_zone: bool,
                multipole_bindings: dict[str, dict[int, int]]) -> None:
    required = {"grounded_shield_id", "accelerator_repeller_id", "accelerator_grid1_id",
                "accelerator_grid2_id", "accelerator_ring_ids"}
    if three_zone:
        required.add("accelerator_intermediate2_id")
    if set(mapping) != required or len(mapping["accelerator_ring_ids"]) != ring_count:
        raise ValueError("accelerator electrode mapping must match all rendered planes and rings")
    values = [value for key, value in mapping.items() if key != "accelerator_ring_ids"]
    values += list(mapping["accelerator_ring_ids"])
    values += [value for binding in multipole_bindings.values() for value in binding.values()]
    if (any(type(value) is not int or not 1 <= value <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID for value in values)
            or len(values) != len(set(values))):
        raise ValueError("assembly electrical groups require distinct valid solver electrode IDs")


def frontend_electrode_maps(geometry: dict) -> tuple[dict[str, dict[int, int]], dict]:
    """Read the actual selected instances' native-group and OA-role mappings.

    These mappings apply to the shared body in every numerical domain. They
    neither select a physical scope nor assign voltages or component poses.
    """
    plan = geometry['composition_plan']
    multipoles, downstream = native_frontend_instances(plan)
    bindings = geometry.get('electrode_bindings')
    if not isinstance(bindings, dict) or set(bindings) != set(plan['scope']['instance_ids']):
        raise ValueError('electrode bindings must name exactly the selected assembly instances')
    if not isinstance(bindings[downstream], dict):
        raise ValueError('instance electrode binding must be a provider mapping')
    multipole = {}
    for upstream in multipoles:
        raw = bindings.get(upstream)
        if not isinstance(raw, dict):
            raise ValueError(f'{upstream}: instance electrode binding must be a provider mapping')
        try:
            parsed = {int(key): value for key, value in raw.items()}
        except (TypeError, ValueError) as error:
            raise ValueError(f'{upstream}: native electrode IDs must be integers') from error
        if len(parsed) != len(raw):
            raise ValueError(f'{upstream}: duplicate native electrode identity')
        multipole[upstream] = parsed
    accelerator = bindings[downstream]
    projection = geometry['accelerator_projection']
    try:
        _electrodes(accelerator, projection['ring_count'], 'intermediate2_z_mm' in projection, multipole)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{multipoles}/{downstream}: {error}') from error
    return multipole, accelerator


def prepare_bare_frontend_geometry(upstream: dict, registration: dict, component: dict, cells: dict, *,
                                   geometry_cells: dict, target_solver_frame: str | None = None) -> tuple[list[str], dict]:
    """Prepare validated metal once; defer GEM and aperture metadata to the final grid."""
    vacuum = upstream.get("vacuum", {})
    if (upstream.get("schema_version") != 1 or upstream.get("role") != "ion_processor_bare_guide_interface"
            or upstream.get("mechanical_components") != dict(shield=False, entrance_plate=False, exit_plate=False, reference_sleeve=False)
            or vacuum.get("pressure_pa") != 0 or vacuum.get("collision_model") != "none"
            or vacuum.get("policy_id") != "native_guide_before_hp_vacuum_v1"
            or upstream.get("frame_id") != "multipole_cartesian_z_axis_v1" or upstream.get("length_unit") != "mm"):
        raise ValueError("canonical frontend requires the explicit bare vacuum guide topology")
    if (set(cells) != set("xyz") or any(isinstance(v, bool) or not isinstance(v, (float, int))
            or not math.isfinite(v) or v <= 0 for v in cells.values())):
        raise ValueError("canonical frontend requires positive finite xyz cells")
    mr_frame = target_solver_frame == "mrtof_global_cartesian"
    projected = _canonical_component(component, target_solver_frame=target_solver_frame, cells=geometry_cells)
    rotation = registration.get("rotation_upstream_to_downstream")
    translation = registration.get("translation_mm")
    if (not isinstance(rotation, list) or len(rotation) != 3
            or any(not isinstance(row, list) or len(row) != 3
                   or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in row) for row in rotation)
            or not isinstance(translation, list) or len(translation) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in translation)):
        raise ValueError("bare-guide registration must declare finite rotation and translation")
    phi = math.atan2(-rotation[2][0], rotation[0][0]) if mr_frame else math.atan2(rotation[2][0], rotation[1][0])
    cosine, sine = math.cos(phi), math.sin(phi)
    expected = [[cosine, -sine, 0], [0, 0, 1], [-sine, -cosine, 0]] if mr_frame else [[0, 0, 1], [cosine, -sine, 0], [sine, cosine, 0]]
    if any(not math.isclose(rotation[a][k], expected[a][k], abs_tol=1e-12, rel_tol=0) for a in range(3) for k in range(3)):
        raise ValueError("bare-guide proper rotation must map its longitudinal axis to the declared slow axis")
    rods = upstream["rod_array"]["rods"]
    if (len(rods) != 8 or sorted(r["physical_electrode_id"] for r in rods) != list(ROD_ELECTRODE_IDS)
            or any(r["electrode_group"] != (1 if r["physical_electrode_id"] % 2 else 2) for r in rods)):
        raise ValueError("eight independent physical rods with alternating groups required")
    if any(any(isinstance(r[k], bool) or not isinstance(r[k], (float, int)) or not math.isfinite(r[k])
               for k in ("center_x_mm", "center_y_mm", "radius_mm", "z_min_mm", "z_max_mm"))
           or r["radius_mm"] <= 0 or r["z_min_mm"] >= r["z_max_mm"] for r in rods):
        raise ValueError("finite continuous rod geometry required")
    if (any((r["z_min_mm"], r["z_max_mm"]) != (rods[0]["z_min_mm"], rods[0]["z_max_mm"]) for r in rods)
            or upstream.get("guide_exit_surface") != dict(center_mm=[0, 0, rods[0]["z_max_mm"]], normal=[0, 0, 1])):
        raise ValueError("continuous rods and the declared axial exit must coincide")
    body = render_bare_frontend_body(upstream, registration, projected["body"], mr_frame=mr_frame)
    boxes = [[r["center_x_mm"]-r["radius_mm"], r["center_y_mm"]-r["radius_mm"], r["z_min_mm"],
              r["center_x_mm"]+r["radius_mm"], r["center_y_mm"]+r["radius_mm"], r["z_max_mm"]] for r in rods]
    envelope = upstream.get("source_envelope_bounds_mm")
    if not isinstance(envelope, dict) or set(envelope) != {"min_mm", "max_mm"}:
        raise ValueError("complete declared source envelope is required for frontend coverage")
    if any(not isinstance(envelope[k], list) or len(envelope[k]) != 3
           or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in envelope[k])
           for k in ("min_mm", "max_mm")):
        raise ValueError("finite xyz source envelope required")
    if any(envelope["min_mm"][a] >= envelope["max_mm"][a] for a in range(3)):
        raise ValueError("source envelope must have positive extents")
    boxes.append([*envelope["min_mm"], *envelope["max_mm"]])
    guide_bounds = _component_bounds(boxes, rotation, translation)
    guide_exit = _component_point(upstream["guide_exit_surface"]["center_mm"], rotation, translation)
    port = projected["port"]
    slow_axis = 1 if mr_frame else 0
    face_position = port["flange_min_mm" if mr_frame else "negative_x_face_mm"]
    bounds = {f"{a}_{s}": op(guide_bounds[f"{a}_{s}"], projected["actual_bounds_mm"][f"{a}_{s}"])
              + (-cells[a] if s == "min" else cells[a]) for a in "xyz" for s, op in (("min", min), ("max", max))}
    numerical = _canonical_grid(bounds, cells)
    source_exit = list(port["center_mm"])
    source_exit[slow_axis] = face_position
    contract = dict(schema_version=2, role="rf_oatof_simion_single_flight_frontend_contract", frame_id="mrtof_global_cartesian" if mr_frame else "oatof_global",
                    **numerical, frontend_variant=resolve_frontend_electrode_topology(projected["electrodes"])["topology_id"], accelerator_component=projected["accelerator_component"],
                    electrodes=projected["electrodes"], accelerator_local_region={k: v for k, v in projected.items() if k != "body"},
                    guide_contract=upstream, guide_registration=registration,
                    guide_exit_center_mm=dict(zip("xyz", guide_exit)), source_exit_center_mm=dict(zip("xyz", source_exit)),
                    aperture=dict(shape="rectangular", width_mm=port["width_mm"], height_mm=port["height_mm"]),
                    cylindrical_sideport=None, connector_terminal=dict(present=False), entrance_reference_sleeve=None,
                    pa_plus_solution_model=projected["pa_plus_solution_model"], bare_guide_generated_shield_or_plate=False)
    if mr_frame:
        contract.update(native_frame_id="mrtof_global_cartesian", slow_axis="y", acceleration_direction=-1)
        contract["accelerator_local_region"].update(native_frame_id="mrtof_global_cartesian", slow_axis="y", acceleration_direction=-1)
    return body, contract


def finalize_frontend_geometry(body: list[str], frontend: dict) -> str:
    """Bind aperture sampling and GEM to the same final numerical domain."""
    local = frontend["accelerator_local_region"]
    port, cells = local["port"], frontend["cell_mm_xyz"]
    mr_frame = frontend.get("native_frame_id") == "mrtof_global_cartesian"
    port_axis = "y" if mr_frame else "x"
    flange_min = port["flange_min_mm"] if mr_frame else port["negative_x_face_mm"]
    local["accelerator_port_aperture_discretization"] = resolve_rectangular_aperture_discretization(
        mechanical_width_mm=port["width_mm"], mechanical_height_mm=port["height_mm"],
        cell_mm_xyz=cells, normal_axis=port_axis,
        flange_min_mm=flange_min, flange_max_mm=flange_min + port["wall_thickness_mm"],
        center_mm=dict(zip("xyz", port["center_mm"])), pa_origin_mm=frontend["instance_origin_mm"],
        boolean_boundary_policy=("exclude_shape_inside_or_on_v1" if frontend["accelerator_component"]["variant_id"] == "three_zone"
                                 else "exclude_shape_inside_only_v1"),
    )
    return _canonical_pa(body, frontend)


def compile_frontend(
    upstream: dict, connection: dict, *, accelerator_component: dict,
    cell_mm_xyz: dict, target_solver_frame: str | None = None,
) -> tuple[str, dict]:
    """Compile the explicit bare-guide/OA providers without legacy geometry inputs."""
    component, cells = accelerator_component, cell_mm_xyz
    body, contract = prepare_bare_frontend_geometry(upstream, connection.get("spatial_registration", {}), component, cells,
                                                   geometry_cells=cells, target_solver_frame=target_solver_frame)
    gap = connection.get("connector", {}).get("length_mm")
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap <= 0:
        raise ValueError("bare rod ends require an explicit positive vacuum separation from the grounded side wall")
    port = contract["accelerator_local_region"]["port"]
    mr_frame = target_solver_frame == "mrtof_global_cartesian"
    slow_axis = "y" if mr_frame else "x"
    face = port["flange_min_mm" if mr_frame else "negative_x_face_mm"]
    guide_exit = contract["guide_exit_center_mm"]
    _require_close(face-guide_exit[slow_axis], gap, "bare-guide end to OA side wall gap")
    for axis in ((0, 2) if mr_frame else (1, 2)):
        _require_close(guide_exit["xyz"[axis]], port["center_mm"][axis], "bare-guide axis to side entry")
    contract["junction_enclosure"] = dict(profile_gap_mm=gap, rod_end_to_accelerator_shield_mm=gap,
                                           geometry="vacuum_gap", generated_solids=[])
    return finalize_frontend_geometry(body, contract), contract


def _require_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(float(actual), float(expected), abs_tol=1e-9):
        raise ValueError(f"{label} differs: actual={actual}, expected={expected}")


def _outward_aligned_boundary(
    value: float, origin: float, cell: float, *, side: str
) -> float:
    """Expand one numerical boundary to its enclosing PA node."""
    coordinate = (value - origin) / cell
    nearest = round(coordinate)
    if math.isclose(coordinate, nearest, abs_tol=1e-8):
        return value
    elif side == "min":
        index = math.floor(coordinate)
    elif side == "max":
        index = math.ceil(coordinate)
    else:
        raise ValueError("numerical boundary side is invalid")
    return origin + index * cell
