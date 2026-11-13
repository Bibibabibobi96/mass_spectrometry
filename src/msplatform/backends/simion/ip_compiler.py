"""Compile an explicitly assembled RF–IP physical domain; no native execution."""
from __future__ import annotations

import copy
import math
import itertools
from collections.abc import Mapping
from typing import Any

from msplatform.assembly.model import Assembly
from msplatform.backends.simion.compiler import CompiledSimionGeometry, _content_sha256
from msplatform.backends.simion.gem_primitives import format_number, grounded_pa_face_lines
from msplatform.backends.simion.geometry import MULTIPOLE_ROTATION, _numerical_box
from msplatform.backends.simion.ip_assembly_geometry import render_selected_ip_body
from msplatform.backends.simion.numerics import normalize_cell_mm_xyz
from msplatform.backends.simion.rf_electrode_mapping import build_simion_electrode_map
from msplatform.backends.simion.rf_geometry import render_physical_gem
from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import contains_shape, convex_planes, shape_bounds
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from msplatform.contracts.rigid_transform import RigidTransform


def _rf_physical_bounds(resolved: Mapping[str, Any], translation: tuple) -> tuple[tuple, tuple]:
    """Bound each actual rod and enclosure in the supported RF-to-IP rotation."""
    geometry = resolved["geometry_mm"]
    segmented = resolved["segmentation"]["segmented_rod_array"]
    rods = geometry["rod_array"]["rods"] if segmented is None else segmented["electrodes"]
    bounds = []
    for rod in rods:
        if "radius_mm" in rod:
            dx = dy = rod["radius_mm"]
        else:
            a, b, angle = rod["semi_major_axis_mm"], rod["semi_minor_axis_mm"], rod["major_axis_angle_rad"]
            dx = math.hypot(a * math.cos(angle), b * math.sin(angle))
            dy = math.hypot(a * math.sin(angle), b * math.cos(angle))
        bounds.append(((rod["z_min_mm"], rod["center_x_mm"] - dx, rod["center_y_mm"] - dy),
                       (rod["z_max_mm"], rod["center_x_mm"] + dx, rod["center_y_mm"] + dy)))
    for body in geometry["enclosure_layout"]["bodies"]:
        radius = body["outer_radius_mm"]
        bounds.append(((body["z_min_mm"], -radius, -radius), (body["z_max_mm"], radius, radius)))
    if not bounds:
        raise ValueError("RF geometry has no physical members")
    return (tuple(min(row[0][i] for row in bounds) + translation[i] for i in range(3)),
            tuple(max(row[1][i] for row in bounds) + translation[i] for i in range(3)))

def _inside_ip_electrode(electrode: dict, point: list[float]) -> bool:
    return any(contains_shape(shape, point) for shape in electrode["solids"]) and not any(
        _strict_inside(shape, point) for shape in electrode["cutouts"])


def _strict_inside(shape: dict, point: list[float]) -> bool:
    low, high = shape_bounds(shape)
    if any(not a < p < b for a, p, b in zip(low, point, high, strict=True)):
        return False
    if shape["shape"] == "box":
        return True
    if shape["shape"] == "cylinder_x":
        return math.hypot(point[1] - shape["center_y_mm"], point[2] - shape["center_z_mm"]) < shape["radius_mm"]
    return all(sum(plane[i] * point[i] for i in range(3)) + plane[3] < 0 for plane in convex_planes(shape))


def _joint_physical_samples(rf_design: dict, ip_design: dict, rf_map: dict, ip_map: dict,
                            rf_translation: tuple, ip_translation: tuple, box: dict,
                            cells: dict, dimensions: dict) -> list[dict]:
    """Find real represented RF/IP interior nodes, vacuum, and explicit e(0) face."""
    from msplatform.backends.simion.physical_samples import standalone_rf_samples

    tx, ty, tz = rf_translation
    origin = dict(x=box["y_min"]-ty, y=box["z_min"]-tz, z=box["x_min"]-tx)
    pitch = dict(x=cells["y"], y=cells["z"], z=cells["x"])
    dims = dict(nx=dimensions["ny"], ny=dimensions["nz"], nz=dimensions["nx"])
    geometry = rf_design["geometry_mm"]
    local_domain = dict(instance_origin_mm=origin, cell_mm_xyz=pitch, dimensions=dims,
                        bounds_mm=dict(z_min=geometry["rod_z_min"], z_max=geometry["rod_z_max"]))
    rf_samples = standalone_rf_samples(rf_design, rf_map, local_domain)
    samples = []
    electrodes = ip_design["projection"]["electrodes"]
    for sample in rf_samples:
        gx, gy, gz = sample["gu"]
        world_gu = [gz, gx, gy]
        local = [box[a+"_min"] + world_gu[i]*cells[a] - ip_translation[i] for i,a in enumerate("xyz")]
        if any(_inside_ip_electrode(e, local) for e in electrodes):
            raise ValueError("RF metal or vacuum witness overlaps IP metal")
        samples.append({**sample, "gu": world_gu})
    for index, electrode in enumerate(electrodes):
        found = None
        for shape in electrode["solids"]:
            low, high = shape_bounds(shape)
            axes = []
            for i, axis in enumerate("xyz"):
                first = max(1, math.floor((low[i]+ip_translation[i]-box[axis+"_min"])/cells[axis])+1)
                last = min(dimensions["n"+axis]-2, math.ceil((high[i]+ip_translation[i]-box[axis+"_min"])/cells[axis])-1)
                midpoint = (first+last)/2
                axes.append(sorted(range(first,last+1),key=lambda value:abs(value-midpoint)))
            for gu in itertools.product(*axes):
                point = [box[a+"_min"]+gu[i]*cells[a]-ip_translation[i] for i,a in enumerate("xyz")]
                if (_strict_inside(shape, point) and not any(contains_shape(cut, point) for cut in electrode["cutouts"])
                        and not any(_inside_ip_electrode(later, point) for later in electrodes[index+1:])):
                    found = list(gu)
                    break
            if found is not None:
                break
        if found is None:
            raise ValueError("no represented unambiguous IP metal witness: "+electrode["name"])
        samples.append(dict(label="ip_"+electrode["name"], gu=found, electrode_id=ip_map[electrode["name"]], metal=True))
    samples.append(dict(label="declared_grounded_pa_face", gu=[0,0,0], electrode_id=0, metal=True))
    return samples

def compile_ip_assembly_geometry(assembly: Assembly, *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile one RF and one complete IP with explicit parent-domain numerics.

    Only identity IP orientation and the existing RF-to-IP native orientation
    are currently supported. The explicit grounded-face/fractional representation
    uses the legacy IP fill operators; it makes no field or trajectory claim.
    """
    if not isinstance(assembly, Assembly):
        raise ValueError("IP geometry requires a canonical Assembly")
    # Revalidate even if an Assembly object's internal data was forged later.
    fresh = Assembly(assembly.composition_plan, assembly.components)
    plan, components, sources = fresh.composition_plan, fresh.components_resolved, fresh.components_source
    names = plan["scope"]["instance_ids"]
    rf = [n for n in names if plan["components"][n]["project_id"] == "rf_multipole_ion_optics"]
    ip = [n for n in names if plan["components"][n]["project_id"] == "dual_pressure_rectilinear_ion_processor"]
    if len(names) != 2 or len(rf) != 1 or len(ip) != 1 or set(names) != set(components):
        raise ValueError("IP geometry requires exactly one complete RF and one IP")
    rf, ip = rf[0], ip[0]
    if not isinstance(numerics, Mapping) or set(numerics) != {"parent_domain", "boundary", "representation", "electrode_group_native_ids"}:
        raise ValueError("IP geometry requires explicit domain, boundary, representation and mappings")
    if numerics["boundary"] != "grounded_pa_faces" or numerics["representation"] != "fractional_legacy_within":
        raise ValueError("unsupported explicit IP boundary or representation")
    domain = numerics["parent_domain"]
    if not isinstance(domain, Mapping) or set(domain) != {"cell_mm_xyz", "pa_bounds_mm"}:
        raise ValueError("parent_domain requires explicit cell_mm_xyz and pa_bounds_mm")
    cells = normalize_cell_mm_xyz(domain["cell_mm_xyz"])
    box, dimensions = _numerical_box(domain["pa_bounds_mm"], cells)
    edges = plan["recipe"]["connections"]
    if len(edges) != 1 or edges[0]["upstream"] != dict(instance_id=rf, port_id="mechanical_exit") or edges[0]["downstream"] != dict(instance_id=ip, port_id="guide_inlet") or edges[0]["coupling_mode"] != "monolithic_joint_solve":
        raise ValueError("RF–IP requires the actual continuous mechanical connection")
    poses = {row["instance_id"]: RigidTransform.from_contract(row["transform"]) for row in plan["recipe"]["instances"]}
    identity = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    if poses[ip].rotation != identity or poses[rf].rotation != MULTIPOLE_ROTATION:
        raise ValueError("unsupported RF–IP pose rotation")
    lower, upper = _rf_physical_bounds(components[rf], poses[rf].translation_mm)
    if any(lower[i] <= box[a + "_min"] or upper[i] >= box[a + "_max"] for i, a in enumerate("xyz")):
        raise ValueError("grounded PA faces must not contact RF physical metal")
    for electrode in components[ip]["projection"]["electrodes"]:
        for shape in electrode["solids"]:
            low, high = shape_bounds(shape)
            for index, axis in enumerate("xyz"):
                translation = poses[ip].translation_mm[index]
                if low[index] + translation <= box[axis + "_min"] or high[index] + translation >= box[axis + "_max"]:
                    raise ValueError("PA bounds clip an IP physical solid")
    mappings = numerics["electrode_group_native_ids"]
    if (not isinstance(mappings, Mapping) or set(mappings) != {rf, ip}
            or not all(isinstance(mappings[name], Mapping) for name in (rf, ip))):
        raise ValueError("native mappings must name both selected components")
    rf_map = build_simion_electrode_map(components[rf], build_electrode_topology(components[rf]),
                                       requested_native_ids=mappings[rf])
    ip_body, ip_map = render_selected_ip_body(components[ip], baseline=sources[ip]["baseline"], native_ids=mappings[ip])
    all_ids = [*rf_map.values(), *ip_map.values()]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("native electrode IDs must be globally distinct")
    rf_cells = dict(x=cells["y"], y=cells["z"], z=cells["x"])
    rf_body = render_physical_gem(components[rf], rf_cells, electrode_group_native_ids=rf_map)
    fmt = format_number
    def translate(values: tuple | list) -> str:
        return ",".join(fmt(value) for value in values)
    origin = [box[axis + "_min"] for axis in "xyz"]
    lines = [f"pa_define({dimensions['nx']},{dimensions['ny']},{dimensions['nz']},planar,none,electrostatic,,{fmt(cells['x'])},{fmt(cells['y'])},{fmt(cells['z'])},surface=fractional)",
             f"locate({translate([-v for v in origin])}) {{",
             f"  locate({translate(poses[rf].translation_mm)},1,90,90,0) {{", rf_body.rstrip(), "  }",
             f"  locate({translate(poses[ip].translation_mm)}) {{", ip_body, "  }", "  e(0) { ; numerical grounded faces"]
    lines.extend(grounded_pa_face_lines(box))
    lines.extend(["  }", "}", ""])
    identities = {n: dict(resolved_content_sha256=_content_sha256(components[n]),
                          component_interface_sha256=_content_sha256(plan["components"][n]),
                          source_content_sha256=_content_sha256(sources[n])) for n in names}
    samples = _joint_physical_samples(components[rf], components[ip], rf_map, ip_map, poses[rf].translation_mm,
                                      poses[ip].translation_mm, box, cells, dimensions)
    geometry = dict(role="simion_rf_ip_geometry", composition_plan=plan, parent_domain=copy.deepcopy(dict(domain)),
                    numerical_domains={"parent": dict(dimensions=dimensions, cell_mm_xyz=cells,
                        bounds_mm=box, instance_origin_mm={a: box[a+"_min"] for a in "xyz"})},
                    boundary=numerics["boundary"], representation=numerics["representation"],
                    electrode_bindings={rf: rf_map, ip: ip_map}, raw_physical_samples={"parent": samples})
    return CompiledSimionGeometry({"parent": "\n".join(lines)}, geometry, (), identities, components)
