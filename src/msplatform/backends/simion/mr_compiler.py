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
    _polygon_bands,
    validate_generation_grid_pitch,
)
from msplatform.backends.simion.mrtof_observations import _polygon_contains, _strict_polygon_hole
from msplatform.backends.simion.oa_compiler import compile_independent_accelerators
from msplatform.backends.simion.rf_compiler import compile_independent_multipoles
from msplatform.backends.simion.physical_samples import box_sample, sample_node
from msplatform.backends.simion.geometry import _numerical_box
from msplatform.backends.simion.numerics import normalize_cell_mm_xyz
from msplatform.backends.simion.ip_assembly_geometry import render_selected_ip_body
from msplatform.backends.simion.ip_compiler import _ip_physical_samples
from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import shape_bounds
from msplatform.components.geometry_members import assembly_geometry_members
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
            gu = _polygon_mirror_witness(solid,domain,members,index)
        else:
            try:
                gu = box_sample(
                    _sample_box(solid["box"]), _sample_box(solid["beam_slot"]),
                    rotation, translation, origin, pitch, dimensions)
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
        "MR analyzer has no unambiguous represented mirror witness on the declared grid"
    )


def _polygon_mirror_witness(solid: Mapping[str, Any], domain: Mapping[str, Any],
                            members: list[dict[str, Any]], index: int) -> list[int] | None:
    """Prove one grid node inside rendered polygon metal and outside every hole."""
    origin, pitch, dims = (domain[key] for key in ('instance_origin_mm','cell_mm_xyz','dimensions'))
    breaks = sorted({solid['x'][0],solid['x'][1],*(x for hole in solid['holes'] for x in hole['x']
                    if solid['x'][0] < x < solid['x'][1])})
    for band in _polygon_bands(solid['polygon_yz_mm']):
        for x0,x1 in zip(breaks,breaks[1:]):
            point = [(x0+x1)/2,sum(p[0] for p in band)/len(band),sum(p[1] for p in band)/len(band)]
            try:
                gu, snapped = sample_node(point, [[1,0,0],[0,1,0],[0,0,1]], [0,0,0], origin, pitch, dims)
            except ValueError:
                continue
            if not solid['x'][0] < snapped[0] < solid['x'][1]: continue
            if not _strict_polygon_hole((snapped[1],snapped[2]),solid['polygon_yz_mm'],0.): continue
            if any(hole['x'][0] <= snapped[0] <= hole['x'][1]
                   and _polygon_contains((snapped[1],snapped[2]),hole['polygon_yz_mm'],0.) for hole in solid['holes']):
                continue
            if not _outside_member_bounds(snapped,members,skip=('mirror_electrodes',index)): continue
            return gu
    return None


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


def _ip_asset(assembly: Assembly, instance_id: str, domain: Mapping[str, Any],
              mapping: Mapping[str, int] | None) -> tuple[str, dict, dict, list, list]:
    """Render the selected complete IP in its own local frame and explicit grid."""
    if not isinstance(domain, Mapping) or set(domain) != {'cell_mm_xyz', 'pa_bounds_mm'}:
        raise ValueError('IP domain requires explicit cell_mm_xyz and pa_bounds_mm')
    cells = normalize_cell_mm_xyz(domain['cell_mm_xyz'])
    box, dimensions = _numerical_box(domain['pa_bounds_mm'], cells)
    selected = assembly.components_resolved[instance_id]
    source = assembly.components[instance_id].source_design
    rows = selected['projection']['electrodes']
    names = [row['name'] for row in rows]
    native_ids = mapping if mapping is not None else dict(zip(names, range(1, len(names)+1), strict=True))
    body, native_map = render_selected_ip_body(selected, baseline=source['baseline'], native_ids=native_ids)
    bounds = []
    for row in rows:
        for shape in row['solids']:
            lo, hi = shape_bounds(shape)
            if any(lo[i] <= box[a+'_min'] or hi[i] >= box[a+'_max'] for i,a in enumerate('xyz')):
                raise ValueError('IP domain clips a physical solid')
            bounds.append({'family':row['name'], 'index':0, 'bounds_mm':[*lo,*hi]})
    grid = dict(dimensions=dimensions,cell_mm_xyz=cells,bounds_mm=box,
                instance_origin_mm={a:box[a+'_min'] for a in 'xyz'})
    samples = _ip_physical_samples(selected, native_map, (0,0,0), box, cells, dimensions)
    samples.append(dict(label='ip_vacuum',gu=_vacuum_witness(grid,bounds),metal=False))
    snapshot = dict(composition_plan=assembly.composition_plan,
                    components_resolved=assembly.components_resolved,
                    components_source=assembly.components_source)
    members = [row for row in assembly_geometry_members(snapshot) if row['instance_id'] == instance_id]
    return _wrap_gem(grid, body.splitlines()),grid,native_map,members,samples


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
    ip = [name for name, project in groups.items() if project == 'dual_pressure_rectilinear_ion_processor']
    rf = [name for name, project in groups.items() if project == 'rf_multipole_ion_optics']
    mr = [
        name
        for name, project in groups.items()
        if project == "parallel_mirror_dual_stripe_mr_tof"
    ]
    if (len(mr) != 1 or not ((len(selected),len(oa),len(ip),len(rf))
                              in ((2,1,0,0),(2,0,1,0),(3,0,1,1)))):
        raise ValueError(
            "OA鈥揗R geometry requires exactly one canonical OA and one complete MR; mixed IP is unsupported"
        )
    is_ip = bool(ip)
    oa_id, mr_id = (ip if is_ip else oa)[0], mr[0]
    oa_design = components[oa_id]
    mr_design = components[mr_id]
    edges = [
        e
        for e in plan["recipe"]["connections"]
        if e["connection_id"] in plan["scope"]["connection_ids"]
        and e["upstream"] == {"instance_id": oa_id, "port_id": "extraction_exit" if is_ip else "axial_exit"}
        and e["downstream"] == {"instance_id": mr_id, "port_id": "accelerator_entry"}
    ]
    if len(edges) != 1:
        raise ValueError(
            "exactly one selected OA axial-exit to MR entry connection required"
        )
    if rf:
        rf_edges = [e for e in plan['recipe']['connections']
                    if e['connection_id'] in plan['scope']['connection_ids']
                    and e['upstream'] == {'instance_id':rf[0],'port_id':'mechanical_exit'}
                    and e['downstream'] == {'instance_id':oa_id,'port_id':'guide_inlet'}]
        if len(rf_edges) != 1:
            raise ValueError('exactly one selected RF mechanical-exit to IP inlet connection required')
    if is_ip:
        selected_edges = [e for e in plan['recipe']['connections'] if e['connection_id'] in plan['scope']['connection_ids']]
        if (len(selected_edges) != (2 if rf else 1)
                or any(e['coupling_mode'] != 'monolithic_joint_solve' for e in selected_edges)):
            raise ValueError('IP–MR geometry requires exactly the selected continuous mechanical connections')
    poses = {
        item["instance_id"]: copy.deepcopy(item["transform"])
        for item in plan["recipe"]["instances"]
        if item["instance_id"] in selected
    }
    if not is_ip and iter_geometry_members(oa_design) != iter_geometry_members(
        mr_design["accelerator_component_geometry"]
    ):
        raise ValueError(
            "selected canonical OA mechanics differ from MR matching authority"
        )
    domains = numerics["domains"]
    expected_domains = {'ip' if is_ip else 'oa','analyzer','detector'}
    if rf: expected_domains.add('multipole')
    if not isinstance(domains, Mapping) or set(domains) != expected_domains:
        raise ValueError("exact OA, analyzer and detector domains required")
    mappings = numerics.get("electrode_group_native_ids", {})
    if not isinstance(mappings, Mapping) or set(mappings) - set(selected):
        raise ValueError("native mappings name unselected component")
    if is_ip:
        upstream_gem, upstream_grid, upstream_map, upstream_members, upstream_samples = _ip_asset(
            assembly, oa_id, domains['ip'], mappings.get(oa_id))
    else:
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
            oa_numerics["electrode_group_native_ids"] = {oa_id: copy.deepcopy(mappings[oa_id])}
        oa_geometry = compile_independent_accelerators(
            {"composition_plan": local, "components_resolved": {oa_id: oa_design}}, numerics=oa_numerics)
        upstream_gem = oa_geometry.frontend_gems[oa_id]
        upstream_grid = oa_geometry.frontend_geometry['numerical_domains'][oa_id]
        upstream_map = oa_geometry.frontend_geometry['electrode_bindings'][oa_id]
        upstream_members = list(iter_geometry_members(oa_design))
        upstream_samples = oa_geometry.frontend_geometry['raw_physical_samples'][oa_id]
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
        oa_id: upstream_gem,
        mr_id + "_analyzer": _wrap_gem(analyzer, body),
        mr_id + "_detector": _wrap_gem(detector, detector_body),
    }
    rf_geometry = None
    if rf:
        rf_id = rf[0]
        local_rf = compile_assembly_layout(plan['recipe'], plan['components'], local_scope={
            'instance_ids':[rf_id], 'research_scope':'RF geometry asset within selected RF–IP–MR assembly',
            'boundary_assumptions':'Geometry asset only; no field boundary or coupling is asserted'})
        rf_numerics = {'component_domains':{rf_id:copy.deepcopy(domains['multipole'])}}
        if rf_id in mappings: rf_numerics['electrode_group_native_ids']={rf_id:copy.deepcopy(mappings[rf_id])}
        rf_geometry = compile_independent_multipoles(
            {'composition_plan':local_rf,'components_resolved':{rf_id:components[rf_id]}}, numerics=rf_numerics)
        assets[rf_id] = rf_geometry.frontend_gems[rf_id]
    if len(assets) != (4 if rf else 3):
        raise ValueError("asset identities collide")
    identities = {
        name: {
            "resolved_content_sha256": _content_sha256(components[name]),
            "component_interface_sha256": _content_sha256(plan["components"][name]),
        }
        for name in selected
    }
    if is_ip:
        for name in selected:
            identities[name]['source_content_sha256'] = _content_sha256(assembly.components[name].source_design)
    frontend = {
        "role": "simion_ip_mr_complete_geometry" if is_ip else "simion_oa_mr_complete_geometry",
        "composition_plan": plan,
        "numerical_domains": {
            oa_id: upstream_grid,
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
            oa_id: upstream_map,
            mr_id: mr_map,
        },
        "electrode_group_roles": {
            mr_id: {
                item["electrode_group_id"]: item["role"]
                for item in plan["components"][mr_id]["component_electrodes"]
            }
        },
        "physical_members": {
            oa_id: upstream_members,
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
            oa_id: upstream_samples,
            mr_id + "_analyzer": _mr_samples(mr_design, mr_map, analyzer, members),
            mr_id + "_detector": _detector_samples(
                mr_design["detector"], mr_map[detector_group], detector
            ),
        },
        "raw_witness_scope": {
            "analyzer": "one represented mirror metal anchor and one conservative vacuum anchor; remaining members and native namespace unverified",
            "detector": "one represented detector metal anchor and one conservative vacuum anchor; full native namespace unverified",
            "limitations": "unrepresentable or ambiguous grid anchors are refused; no field or native qualification",
        },
        "source_status": "not_requested",
        "field_status": "not_solved",
    }
    if is_ip:
        frontend['electrode_group_roles'][oa_id] = {
            row['electrode_group_id']: row['role']
            for row in plan['components'][oa_id]['component_electrodes']
        }
    if rf:
        rf_id=rf[0]
        frontend['numerical_domains'][rf_id]=rf_geometry.frontend_geometry['numerical_domains'][rf_id]
        frontend['asset_components'][rf_id]=rf_id
        frontend['asset_poses'][rf_id]=poses[rf_id]
        frontend['electrode_bindings'][rf_id]=rf_geometry.frontend_geometry['electrode_bindings'][rf_id]
        frontend['electrode_group_roles'][rf_id]={row['electrode_group_id']:row['role']
            for row in plan['components'][rf_id]['component_electrodes']}
        snapshot=dict(composition_plan=plan,components_resolved=components,components_source=assembly.components_source)
        frontend['physical_members'][rf_id]=[row for row in assembly_geometry_members(snapshot) if row['instance_id']==rf_id]
        frontend['raw_physical_samples'][rf_id]=rf_geometry.frontend_geometry['raw_physical_samples'][rf_id]
    return CompiledSimionGeometry(
        assets, frontend, (), identities, copy.deepcopy(components)
    )
