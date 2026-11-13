"""Geometry-only complete RF and OA assembly in one explicit parent PA."""

from __future__ import annotations

import copy
import itertools
import math
from collections.abc import Mapping

from msplatform.assembly.model import Assembly
from msplatform.backends.simion.compiler import CompiledSimionGeometry, _content_sha256
from msplatform.backends.simion.gem_primitives import format_number, grounded_pa_face_lines
from msplatform.backends.simion.geometry import _numerical_box
from msplatform.backends.simion.native_plans import rigid_iob_placement
from msplatform.backends.simion.numerics import normalize_cell_mm_xyz
from msplatform.backends.simion.oa_compiler import _extent, _inside, _samples, render_accelerator_body
from msplatform.backends.simion.physical_samples import sample_node, standalone_rf_samples
from msplatform.backends.simion.rf_electrode_mapping import (
    build_simion_electrode_map,
    SIMION_MAX_ADJUSTABLE_ELECTRODE_ID,
)
from msplatform.backends.simion.rf_geometry import render_physical_gem
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from msplatform.contracts.rigid_transform import RigidTransform


def _local_domain(pose, box, cells, dims):
    # Existing individual-body witness finders require an axis-aligned lattice.
    rot, trans = pose.rotation, pose.translation_mm
    if any(sum(abs(v) == 1.0 for v in row) != 1 or any(v not in (-1.0, 0.0, 1.0) for v in row) for row in rot):
        raise ValueError("joint physical witnesses require an axis-permutation pose")
    corners = itertools.product(*[(box[a + "_min"], box[a + "_max"]) for a in "xyz"])
    local = [[sum(rot[i][j] * (corner[i] - trans[i]) for i in range(3)) for j in range(3)] for corner in corners]
    origin = {a: min(row[j] for row in local) for j, a in enumerate("xyz")}
    local_cells = {a: cells["xyz"[next(i for i in range(3) if rot[i][j])]] for j, a in enumerate("xyz")}
    local_dims = {"n" + a: dims["n" + "xyz"[next(i for i in range(3) if rot[i][j])]] for j, a in enumerate("xyz")}
    return dict(instance_origin_mm=origin, cell_mm_xyz=local_cells, dimensions=local_dims)


def _world_gu(sample, domain, pose, box, cells, dims):
    pt = [domain["instance_origin_mm"][a] + sample["gu"][i] * domain["cell_mm_xyz"][a] for i, a in enumerate("xyz")]
    gu, actual = sample_node(pt, pose.rotation, pose.translation_mm, {a: box[a + "_min"] for a in "xyz"}, cells, dims)
    if any(
        not math.isclose(x, y, rel_tol=0.0, abs_tol=64 * math.ulp(max(1.0, abs(x), abs(y))))
        for x, y in zip(pt, actual, strict=True)
    ):
        raise ValueError("component witness is not represented at the parent PA node")
    return {**sample, "gu": gu}


def _rf_inside(design, point):
    from msplatform.components.rf_multipole.round_rod_geometry import points_inside_rods
    import numpy as np

    for group in build_electrode_topology(design):
        for pointer in group["member_refs"]:
            body = design
            for token in pointer.split("/")[1:]:
                body = body[int(token)] if isinstance(body, list) else body[token]
            if not body["z_min_mm"] <= point[2] <= body["z_max_mm"]:
                continue
            if group["electrode_group_id"] == "grounded_shell":
                r2 = point[0] ** 2 + point[1] ** 2
                if body["inner_radius_mm"] ** 2 <= r2 <= body["outer_radius_mm"] ** 2:
                    return True
            elif points_inside_rods(np.array([point[:2]]), {"rods": [body]}, include_boundary=True)[0]:
                return True
    return False


def _local_point(gu, pose, box, cells):
    world = [box[a + "_min"] + gu[i] * cells[a] for i, a in enumerate("xyz")]
    return [sum(pose.rotation[i][j] * (world[i] - pose.translation_mm[i]) for i in range(3)) for j in range(3)]


def compile_rf_oa_geometry(assembly: Assembly, *, numerics: Mapping) -> CompiledSimionGeometry:
    """Compile selected whole components; field coupling and tracking remain unproven."""
    if not isinstance(assembly, Assembly):
        raise ValueError("RF–OA geometry requires a canonical Assembly")
    fresh = Assembly(assembly.composition_plan, assembly.components)
    plan, components, sources = fresh.composition_plan, fresh.components_resolved, fresh.components_source
    names = plan["scope"]["instance_ids"]
    rf = [n for n in names if plan["components"][n]["project_id"] == "rf_multipole_ion_optics"]
    oa = [n for n in names if plan["components"][n]["project_id"] == "orthogonal_accelerator"]
    if len(names) != 2 or len(rf) != 1 or len(oa) != 1 or set(components) != set(names):
        raise ValueError("joint geometry requires exactly one RF and one OA")
    rf, oa = rf[0], oa[0]
    if not isinstance(numerics, Mapping) or set(numerics) != {
        "parent_domain",
        "boundary",
        "representation",
        "electrode_group_native_ids",
    }:
        raise ValueError("explicit parent domain, boundary, representation and IDs required")
    if numerics["boundary"] != "grounded_pa_faces" or numerics["representation"] != "fractional_legacy_within":
        raise ValueError("unsupported numerical boundary or representation")
    domain = numerics["parent_domain"]
    if not isinstance(domain, Mapping) or set(domain) != {"cell_mm_xyz", "pa_bounds_mm"}:
        raise ValueError("parent domain requires explicit grid and bounds")
    cells = normalize_cell_mm_xyz(domain["cell_mm_xyz"])
    box, dims = _numerical_box(domain["pa_bounds_mm"], cells)
    edges = plan["recipe"]["connections"]
    if (
        len(edges) != 1
        or edges[0]["upstream"] != dict(instance_id=rf, port_id="mechanical_exit")
        or edges[0]["downstream"] != dict(instance_id=oa, port_id="side_entry")
        or edges[0]["coupling_mode"] != "monolithic_joint_solve"
    ):
        raise ValueError("RF–OA requires its explicit mechanical exit to side-entry connection")
    rows = {row["instance_id"]: row for row in plan["recipe"]["instances"]}
    poses = {name: RigidTransform.from_contract(rows[name]["transform"]) for name in names}
    local = {name: _local_domain(poses[name], box, cells, dims) for name in names}
    rf_geometry = components[rf]["geometry_mm"]
    local[rf]["bounds_mm"] = dict(z_min=rf_geometry["rod_z_min"], z_max=rf_geometry["rod_z_max"])
    mappings = numerics["electrode_group_native_ids"]
    if (
        not isinstance(mappings, Mapping)
        or set(mappings) != {rf, oa}
        or not all(isinstance(mappings[n], Mapping) for n in names)
    ):
        raise ValueError("native mappings must explicitly cover both components")
    rf_map = build_simion_electrode_map(
        components[rf], build_electrode_topology(components[rf]), requested_native_ids=mappings[rf]
    )
    members = iter_geometry_members(components[oa])
    groups = {m["electrode_group_id"] for m in members}
    oa_map = dict(mappings[oa])
    if set(oa_map) != groups or any(
        type(v) is not int or not 1 <= v <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID for v in oa_map.values()
    ):
        raise ValueError("OA IDs must cover each scientific group")
    allids = [*rf_map.values(), *oa_map.values()]
    if len(set(allids)) != len(allids):
        raise ValueError("native IDs must be globally distinct")
    # Strictly contain every OA shape and all real RF rods/enclosures in the declared parent box.
    for member in members:
        for j, (lo, hi) in enumerate(_extent(member["shape"])):
            origin = local[oa]["instance_origin_mm"]["xyz"[j]]
            pitch = local[oa]["cell_mm_xyz"]["xyz"[j]]
            upper = origin + (local[oa]["dimensions"]["n" + "xyz"[j]] - 1) * pitch
            if lo <= origin or hi >= upper:
                raise ValueError("grounded parent faces contact or clip OA metal")
    for group in build_electrode_topology(components[rf]):
        for pointer in group["member_refs"]:
            body = components[rf]
            for token in pointer.split("/")[1:]:
                body = body[int(token)] if isinstance(body, list) else body[token]
            if group["electrode_group_id"] == "grounded_shell":
                cx = cy = 0.0
                dx = dy = body["outer_radius_mm"]
            else:
                cx, cy = body["center_x_mm"], body["center_y_mm"]
                if "radius_mm" in body:
                    dx = dy = body["radius_mm"]
                else:
                    a, b, t = (body[k] for k in ("semi_major_axis_mm", "semi_minor_axis_mm", "major_axis_angle_rad"))
                    dx = math.hypot(a * math.cos(t), b * math.sin(t))
                    dy = math.hypot(a * math.sin(t), b * math.cos(t))
            extents = [(cx - dx, cx + dx), (cy - dy, cy + dy), (body["z_min_mm"], body["z_max_mm"])]
            for j, (lo, hi) in enumerate(extents):
                axis = "xyz"[j]
                start = local[rf]["instance_origin_mm"][axis]
                stop = start + (local[rf]["dimensions"]["n" + axis] - 1) * local[rf]["cell_mm_xyz"][axis]
                if lo <= start or hi >= stop:
                    raise ValueError("grounded parent faces contact or clip RF metal")
    rf_samples = [
        _world_gu(s, local[rf], poses[rf], box, cells, dims)
        for s in standalone_rf_samples(components[rf], rf_map, local[rf])
    ]
    oa_samples = [_world_gu(s, local[oa], poses[oa], box, cells, dims) for s in _samples(members, oa_map, local[oa])]
    for s in rf_samples:
        if any(_inside(m["shape"], _local_point(s["gu"], poses[oa], box, cells), boundary=True) for m in members):
            raise ValueError("RF physical witness overlaps OA metal")
    for s in oa_samples:
        if _rf_inside(components[rf], _local_point(s["gu"], poses[rf], box, cells)):
            raise ValueError("OA physical witness overlaps RF metal")
    fmt = format_number

    def locate(name):
        p = rigid_iob_placement(rows[name]["transform"])
        return (
            ",".join(fmt(p[k]) for k in ("x_mm", "y_mm", "z_mm"))
            + ",1,"
            + ",".join(fmt(p[k]) for k in ("az_deg", "el_deg", "rt_deg"))
        )

    rf_body = render_physical_gem(components[rf], local[rf]["cell_mm_xyz"], electrode_group_native_ids=rf_map)
    oa_body = render_accelerator_body(
        components[oa], plan["components"][oa]["variant_id"], oa_map, local[oa]["cell_mm_xyz"]
    )
    lines = [
        f"pa_define({dims['nx']},{dims['ny']},{dims['nz']},planar,none,electrostatic,,{fmt(cells['x'])},{fmt(cells['y'])},{fmt(cells['z'])},surface=fractional)",
        "locate(" + ",".join(fmt(-box[a + "_min"]) for a in "xyz") + ") {",
        "  locate(" + locate(rf) + ") {",
        rf_body.rstrip(),
        "  }",
        "  locate(" + locate(oa) + ") {",
        *oa_body,
        "  }",
        "  e(0) { ; numerical grounded faces",
        *grounded_pa_face_lines(box),
        "  }",
        "}",
        "",
    ]
    samples = [
        *rf_samples,
        *oa_samples,
        dict(label="declared_grounded_pa_face", gu=[0, 0, 0], electrode_id=0, metal=True),
    ]
    identities = {
        n: dict(
            resolved_content_sha256=_content_sha256(components[n]),
            component_interface_sha256=_content_sha256(plan["components"][n]),
            source_content_sha256=_content_sha256(sources[n]),
        )
        for n in names
    }
    frontend = dict(
        role="simion_rf_oa_geometry",
        composition_plan=plan,
        parent_domain=copy.deepcopy(dict(domain)),
        numerical_domains={
            "parent": dict(
                dimensions=dims,
                cell_mm_xyz=cells,
                bounds_mm=box,
                instance_origin_mm={a: box[a + "_min"] for a in "xyz"},
            )
        },
        boundary=numerics["boundary"],
        representation=numerics["representation"],
        electrode_bindings={rf: rf_map, oa: oa_map},
        raw_physical_samples={"parent": samples},
    )
    return CompiledSimionGeometry({"parent": "\n".join(lines)}, frontend, (), identities, components)
