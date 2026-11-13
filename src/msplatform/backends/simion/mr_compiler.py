"""Compile one explicit OA鈥揗R assembly into source-free SIMION GEM specifications.

The physical OA is the selected canonical OA instance; the MR embedded OA
projection is matching authority only. This pure stage does not build, refine,
track, or establish field coverage and coupling.
"""

from __future__ import annotations
import copy
import math
from collections.abc import Mapping
from typing import Any

from msplatform.assembly.model import Assembly
from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.orthogonal_accelerator.geometry_members import (
    iter_geometry_members,
)
from msplatform.backends.simion.compiler import CompiledSimionGeometry, _content_sha256
from msplatform.backends.simion.mr_geometry import (
    _analyzer_geometry_lines,
    validate_generation_grid_pitch,
)
from msplatform.backends.simion.oa_compiler import compile_independent_accelerators
from msplatform.backends.simion.physical_samples import box_sample, sample_node
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.assembly_interface import (
    _component_electrodes,
    _scientific_groups,
)


def _domain(value: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"cell_mm_xyz", "pa_bounds_mm"}:
        raise ValueError("MR domain requires explicit cell_mm_xyz and pa_bounds_mm")
    cell = value["cell_mm_xyz"]
    bounds = value["pa_bounds_mm"]
    if (
        not isinstance(cell, Mapping)
        or set(cell) != set("xyz")
        or not isinstance(bounds, Mapping)
        or set(bounds)
        != {axis + suffix for axis in "xyz" for suffix in ("_min", "_max")}
    ):
        raise ValueError("MR grid requires exact xyz cell and six bounds")
    numeric = [*cell.values(), *bounds.values()]
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in numeric):
        raise ValueError("MR grid inputs must be finite numbers")
    validate_generation_grid_pitch(contract, [cell[a] for a in "xyz"])
    dimensions = {}
    for axis in "xyz":
        count = (bounds[axis + "_max"] - bounds[axis + "_min"]) / cell[axis]
        if count <= 0 or not math.isclose(count, round(count), rel_tol=0, abs_tol=1e-9):
            raise ValueError("MR bounds must span positive whole grid intervals")
        dimensions["n" + axis] = round(count) + 1
    return {
        "dimensions": dimensions,
        "cell_mm_xyz": dict(cell),
        "instance_origin_mm": {a: bounds[a + "_min"] for a in "xyz"},
        "bounds_mm": dict(bounds),
    }


def _shape_bounds(shape: Mapping[str, Any]) -> list[float]:
    if "x" in shape and "polygon_yz_mm" in shape:
        x = shape["x"]
        polygon = shape["polygon_yz_mm"]
        if len(x) != 2 or not polygon:
            raise ValueError("MR solid polygon differs")
        return [
            min(x),
            min(p[0] for p in polygon),
            min(p[1] for p in polygon),
            max(x),
            max(p[0] for p in polygon),
            max(p[1] for p in polygon),
        ]
    if "box" in shape:
        box = shape["box"]
        if not isinstance(box, list) or len(box) != 6:
            raise ValueError("MR solid box differs")
        return list(box)
    raise ValueError("unsupported MR physical solid")


def _analyzer_members(resolved: Mapping[str, Any]) -> list[dict[str, Any]]:
    members = []
    for family in (
        "mirror_electrodes",
        "mirror_ground_shields",
        "mirror_e_closures",
        "stripe_electrodes",
        "central_ground_electrodes",
        "prism_ground_shields",
    ):
        for index, solid in enumerate(resolved[family]):
            shapes = solid.get("body_sections", [solid])
            for part, shape in enumerate(shapes):
                members.append(
                    {
                        "family": family,
                        "index": index,
                        "part": part,
                        "bounds_mm": _shape_bounds(shape),
                        "shape": copy.deepcopy(shape),
                        "source_geometry": copy.deepcopy(solid),
                    }
                )
            if family == "stripe_electrodes":
                members.append(
                    {
                        "family": family,
                        "index": index,
                        "part": "terminal",
                        "bounds_mm": _shape_bounds(
                            {
                                "x": solid["x"],
                                "polygon_yz_mm": solid["terminal_polygon_yz_mm"],
                            }
                        ),
                        "shape": {
                            "x": copy.deepcopy(solid["x"]),
                            "polygon_yz_mm": copy.deepcopy(
                                solid["terminal_polygon_yz_mm"]
                            ),
                        },
                        "source_geometry": copy.deepcopy(solid),
                    }
                )
    for index, prism in enumerate(resolved["prism_electrodes"]):
        for part, shape in enumerate(prism["parts"]):
            members.append(
                {
                    "family": "prism_electrodes",
                    "index": index,
                    "part": part,
                    "bounds_mm": _shape_bounds(shape),
                    "shape": copy.deepcopy(shape),
                    "source_geometry": copy.deepcopy(prism),
                }
            )
    if not members:
        raise ValueError("MR analyzer has no physical members")
    return members


def _require_contained(
    members: list[dict[str, Any]], domain: Mapping[str, Any]
) -> None:
    bounds = domain["bounds_mm"]
    for member in members:
        box = member["bounds_mm"]
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in box) or any(
            box[i] > box[i + 3]
            or box[i] < bounds[a + "_min"]
            or box[i + 3] > bounds[a + "_max"]
            for i, a in enumerate("xyz")
        ):
            raise ValueError(
                "MR domain does not contain complete physical member: "
                + str(member["family"])
            )


def _sample_box(values: list[float]) -> dict[str, float]:
    return {
        axis + suffix + "_mm": values[index + offset]
        for index, axis in enumerate("xyz")
        for suffix, offset in (("_min", 0), ("_max", 3))
    }


def _outside_member_bounds(
    point: list[float],
    members: list[dict[str, Any]],
    *,
    skip: tuple[str, int] | None = None,
) -> bool:
    for member in members:
        if skip == (member["family"], member["index"]):
            continue
        box = member["bounds_mm"]
        if all(box[index] <= point[index] <= box[index + 3] for index in range(3)):
            return False
    return True


def _vacuum_witness(
    domain: Mapping[str, Any], members: list[dict[str, Any]]
) -> list[int]:
    origin, pitch, dimensions = (
        domain[key] for key in ("instance_origin_mm", "cell_mm_xyz", "dimensions")
    )
    if any(dimensions["n" + axis] < 3 for axis in "xyz"):
        raise ValueError("MR vacuum witness requires an interior PA node")
    choices = [
        [1, (dimensions["n" + axis] - 1) // 2, dimensions["n" + axis] - 2]
        for axis in "xyz"
    ]
    for x in choices[0]:
        for y in choices[1]:
            for z in choices[2]:
                gu = [x, y, z]
                point = [
                    origin[axis] + gu[index] * pitch[axis]
                    for index, axis in enumerate("xyz")
                ]
                candidate, snapped = sample_node(
                    point,
                    [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    [0, 0, 0],
                    origin,
                    pitch,
                    dimensions,
                )
                if _outside_member_bounds(snapped, members):
                    return candidate
    raise ValueError(
        "MR asset has no conservatively proven vacuum witness on the declared grid"
    )


def _mr_samples(
    resolved: Mapping[str, Any],
    mapping: Mapping[str, int],
    domain: Mapping[str, Any],
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    origin, pitch, dimensions = (
        domain[key] for key in ("instance_origin_mm", "cell_mm_xyz", "dimensions")
    )
    rotation, translation = [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0]
    groups = _scientific_groups(resolved, _component_electrodes(resolved))
    for index, solid in enumerate(resolved["mirror_electrodes"]):
        if "polygon_yz_mm" in solid:
            continue
        try:
            gu = box_sample(
                _sample_box(solid["box"]),
                _sample_box(solid["beam_slot"]),
                rotation,
                translation,
                origin,
                pitch,
                dimensions,
            )
        except ValueError:
            continue
        if gu is None:
            continue
        point = [origin[axis] + gu[i] * pitch[axis] for i, axis in enumerate("xyz")]
        if not _outside_member_bounds(
            point, members, skip=("mirror_electrodes", index)
        ):
            continue
        group = groups[
            next(
                i
                for i, item in enumerate(_component_electrodes(resolved))
                if item["component_electrode_id"] == solid["id"]
            )
        ]["electrode_group_id"]
        return [
            dict(
                label=f"mirror_{index}_actual_metal", gu=gu, electrode_id=mapping[group]
            ),
            dict(
                label="analyzer_proven_vacuum",
                gu=_vacuum_witness(domain, members),
                metal=False,
            ),
        ]
    raise ValueError(
        "MR analyzer has no unambiguous represented box-mirror witness; polygon-only or unrepresented geometry requires another supported witness"
    )


def _detector_samples(
    solid: Mapping[str, Any], native_id: int, domain: Mapping[str, Any]
) -> list[dict[str, Any]]:
    origin, pitch, dimensions = (
        domain[key] for key in ("instance_origin_mm", "cell_mm_xyz", "dimensions")
    )
    box = _shape_bounds(solid)
    gu = box_sample(
        _sample_box(box),
        None,
        [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        [0, 0, 0],
        origin,
        pitch,
        dimensions,
    )
    if gu is None:
        raise ValueError("MR detector has no represented metal witness")
    member = {"family": "detector", "index": 0, "bounds_mm": box}
    return [
        dict(label="detector_actual_metal", gu=gu, electrode_id=native_id),
        dict(
            label="detector_proven_vacuum",
            gu=_vacuum_witness(domain, [member]),
            metal=False,
        ),
    ]


def _wrap_gem(domain: Mapping[str, Any], body: list[str]) -> str:
    n = domain["dimensions"]
    cell = domain["cell_mm_xyz"]
    origin = domain["instance_origin_mm"]
    header = f"pa_define({n['nx']},{n['ny']},{n['nz']},planar,none,electrostatic,,{cell['x']:.12g},{cell['y']:.12g},{cell['z']:.12g},surface=fractional)"
    return "\n".join(
        [
            header,
            f"locate({-origin['x']:.12g},{-origin['y']:.12g},{-origin['z']:.12g}) {{",
            *body,
            "}",
            "",
        ]
    )


def compile_complete_mr_geometry(
    assembly: Assembly, *, numerics: Mapping[str, Any]
) -> CompiledSimionGeometry:
    """Compile selected canonical OA+MR physical content with explicit local grids.

    Numerical domains have keys ``oa``, ``analyzer`` and ``detector``, each
    with ``cell_mm_xyz`` and ``pa_bounds_mm``. Optional scientific-group maps
    are explicit per selected instance. Input positions are local mm; the
    original parent recipe retains both full rigid poses. Unsupported mixes,
    stale designs, unmatched physical OA, and cropped domains fail closed.
    """
    if not isinstance(assembly, Assembly):
        raise TypeError("explicit canonical Assembly required")
    assembly = Assembly(assembly.composition_plan, assembly.components)
    if (
        not isinstance(numerics, Mapping)
        or "domains" not in numerics
        or set(numerics) - {"domains", "electrode_group_native_ids"}
    ):
        raise ValueError(
            "OA鈥揗R geometry requires explicit domains and optional mappings"
        )
    plan = assembly.composition_plan
    selected = plan["scope"]["instance_ids"]
    components = assembly.components_resolved
    groups = {name: plan["components"][name]["project_id"] for name in selected}
    oa = [
        name for name, project in groups.items() if project == "orthogonal_accelerator"
    ]
    mr = [
        name
        for name, project in groups.items()
        if project == "parallel_mirror_dual_stripe_mr_tof"
    ]
    if len(selected) != 2 or len(oa) != 1 or len(mr) != 1:
        raise ValueError(
            "OA鈥揗R geometry requires exactly one canonical OA and one complete MR; mixed IP is unsupported"
        )
    oa_id, mr_id = oa[0], mr[0]
    oa_design = components[oa_id]
    mr_design = components[mr_id]
    edges = [
        e
        for e in plan["recipe"]["connections"]
        if e["connection_id"] in plan["scope"]["connection_ids"]
        and e["upstream"] == {"instance_id": oa_id, "port_id": "axial_exit"}
        and e["downstream"] == {"instance_id": mr_id, "port_id": "accelerator_entry"}
    ]
    if len(edges) != 1:
        raise ValueError(
            "exactly one selected OA axial-exit to MR entry connection required"
        )
    poses = {
        item["instance_id"]: copy.deepcopy(item["transform"])
        for item in plan["recipe"]["instances"]
        if item["instance_id"] in selected
    }
    if iter_geometry_members(oa_design) != iter_geometry_members(
        mr_design["accelerator_component_geometry"]
    ):
        raise ValueError(
            "selected canonical OA mechanics differ from MR matching authority"
        )
    domains = numerics["domains"]
    if not isinstance(domains, Mapping) or set(domains) != {
        "oa",
        "analyzer",
        "detector",
    }:
        raise ValueError("exact OA, analyzer and detector domains required")
    mappings = numerics.get("electrode_group_native_ids", {})
    if not isinstance(mappings, Mapping) or set(mappings) - {oa_id, mr_id}:
        raise ValueError("native mappings name unselected component")
    local = compile_assembly_layout(
        plan["recipe"],
        plan["components"],
        local_scope={
            "instance_ids": [oa_id],
            "research_scope": "OA geometry asset within selected OA鈥揗R assembly",
            "boundary_assumptions": "Geometry asset only; no field boundary or coupling is asserted",
        },
    )
    oa_numerics = {"component_domains": {oa_id: copy.deepcopy(domains["oa"])}}
    if oa_id in mappings:
        oa_numerics["electrode_group_native_ids"] = {
            oa_id: copy.deepcopy(mappings[oa_id])
        }
    oa_geometry = compile_independent_accelerators(
        {"composition_plan": local, "components_resolved": {oa_id: oa_design}},
        numerics=oa_numerics,
    )
    source = assembly.components[mr_id].source_design
    contract = source["contract"]
    analyzer = _domain(domains["analyzer"], contract)
    detector = _domain(domains["detector"], contract)
    members = _analyzer_members(mr_design)
    detector_member = {
        "family": "detector",
        "index": 0,
        "part": 0,
        "bounds_mm": _shape_bounds(mr_design["detector"]),
        "shape": copy.deepcopy(mr_design["detector"]),
    }
    _require_contained(members, analyzer)
    _require_contained([detector_member], detector)
    names = [
        x["electrode_group_id"]
        for x in plan["components"][mr_id]["component_electrodes"]
    ]
    mr_map = copy.deepcopy(
        mappings.get(mr_id, dict(zip(names, range(1, len(names) + 1), strict=True)))
    )
    body = _analyzer_geometry_lines(mr_design, native_group_ids=mr_map)
    detector_group = next(
        x["electrode_group_id"]
        for x in plan["components"][mr_id]["component_electrodes"]
        if x["role"] == "detector"
    )
    box = detector_member["bounds_mm"]
    detector_body = [
        "  e("
        + str(mr_map[detector_group])
        + ") { box3D("
        + ",".join(format(v, ".12g") for v in box)
        + ") }"
    ]
    assets = {
        oa_id: oa_geometry.frontend_gems[oa_id],
        mr_id + "_analyzer": _wrap_gem(analyzer, body),
        mr_id + "_detector": _wrap_gem(detector, detector_body),
    }
    if len(assets) != 3:
        raise ValueError("asset identities collide")
    identities = {
        name: {
            "resolved_content_sha256": _content_sha256(components[name]),
            "component_interface_sha256": _content_sha256(plan["components"][name]),
        }
        for name in selected
    }
    frontend = {
        "role": "simion_oa_mr_complete_geometry",
        "composition_plan": plan,
        "numerical_domains": {
            oa_id: oa_geometry.frontend_geometry["numerical_domains"][oa_id],
            mr_id + "_analyzer": analyzer,
            mr_id + "_detector": detector,
        },
        "asset_components": {
            oa_id: oa_id,
            mr_id + "_analyzer": mr_id,
            mr_id + "_detector": mr_id,
        },
        "asset_poses": {
            oa_id: poses[oa_id],
            mr_id + "_analyzer": poses[mr_id],
            mr_id + "_detector": poses[mr_id],
        },
        "electrode_bindings": {
            oa_id: oa_geometry.frontend_geometry["electrode_bindings"][oa_id],
            mr_id: mr_map,
        },
        "electrode_group_roles": {
            mr_id: {
                item["electrode_group_id"]: item["role"]
                for item in plan["components"][mr_id]["component_electrodes"]
            }
        },
        "physical_members": {
            oa_id: list(iter_geometry_members(oa_design)),
            mr_id: members + [detector_member],
        },
        "physical_cutouts": {
            mr_id: {
                key: copy.deepcopy(mr_design[key])
                for key in (
                    "mirror_inner_shield_slot",
                    "stripe_slot",
                    "central_ground_slots",
                )
            }
        },
        "raw_physical_samples": {
            oa_id: oa_geometry.frontend_geometry["raw_physical_samples"][oa_id],
            mr_id + "_analyzer": _mr_samples(mr_design, mr_map, analyzer, members),
            mr_id + "_detector": _detector_samples(
                mr_design["detector"], mr_map[detector_group], detector
            ),
        },
        "raw_witness_scope": {
            "analyzer": "one represented mirror metal anchor and one conservative vacuum anchor; remaining members and native namespace unverified",
            "detector": "one represented detector metal anchor and one conservative vacuum anchor; full native namespace unverified",
            "limitations": "polygon-only mirror anchors and unrepresentable grid anchors are refused; no field or native qualification",
        },
        "source_status": "not_requested",
        "field_status": "not_solved",
    }
    return CompiledSimionGeometry(
        assets, frontend, (), identities, copy.deepcopy(components)
    )
