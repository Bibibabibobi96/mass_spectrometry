"""SIMION projection of explicitly independent OA and single-reflection TOF."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping

from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
from msplatform.components.orthogonal_accelerator.provider import resolve_component as resolve_oa
from msplatform.components.single_reflection_tof.provider import resolve_component as resolve_tof
from .compiler import CompiledSimionGeometry, _content_sha256
from .downstream import compile_downstream_specs, split_downstream_targets
from .frontend import split_frontend_instances
from .geometry import _numerical_box, render_frontend_domain
from .numerics import normalize_cell_mm_xyz
from .oa_compiler import _samples
from .accelerator_renderer import render_accelerator_local_geometry
from .rf_electrode_mapping import SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
from .tof_geometry import resolve_split_physical_geometry


def compile_split_geometry(assembly, *, numerics):
    """Compile the verified two-component native subset; no field is solved."""
    if not isinstance(assembly, Mapping) or set(assembly) != {"composition_plan", "components_resolved"}:
        raise ValueError("split geometry requires plan and resolved components")
    plan = copy.deepcopy(assembly["composition_plan"])
    if {k: v for k, v in plan.items() if k != "input_files"} != compile_assembly_layout(
            plan["recipe"], plan["components"], local_scope=plan.get("local_scope")):
        raise ValueError("split composition plan differs from canonical layout")
    rf, oa, tof = split_frontend_instances(plan)
    if len(rf) > 1:
        raise ValueError("split frontend currently supports at most one RF component")
    components = assembly["components_resolved"]
    if not isinstance(components, Mapping) or set(components) != {oa, tof, *rf}:
        raise ValueError("split provider snapshots must exactly cover the selected components")
    oa_design = components[oa]
    if oa_design.get("role") != "instrument_sectioned_accelerator_mechanics_projection":
        raise ValueError("split OA requires the validated instrument mechanical projection")
    source = dict(schema_version=oa_design["source_schema_version"], role=oa_design["source_role"],
                  producer=oa_design["producer"], frame_id="oatof_global",
                  geometry=copy.deepcopy(oa_design["geometry"]))
    actual_oa = resolve_oa({"instrument_geometry": source})
    actual_tof = resolve_tof(components[tof])
    for name, actual in ((oa, actual_oa), (tof, actual_tof)):
        if actual["resolved_design"] != components[name] or actual["assembly_interface"] != plan["components"][name]:
            raise ValueError(f"{name}: resolved component differs from its mechanical interface")
    poses = {row["instance_id"]: row["transform"] for row in plan["recipe"]["instances"]}
    if any(poses[oa][key] != poses[tof][key] for key in ("rotation", "translation_mm")):
        raise ValueError("split OA and TOF require the same validated native pose")
    required = {"frontend_domains", "geometry_build", "detector_marker"}
    if not isinstance(numerics, Mapping) or not required <= set(numerics) or set(numerics) - required - {"electrode_group_native_ids"}:
        raise ValueError("split numerical inputs differ")
    authors = numerics["frontend_domains"]
    if not isinstance(authors, Mapping) or set(authors) != {"parent"}:
        raise ValueError("split OA currently requires exactly one explicit parent domain")
    author = authors["parent"]
    if not isinstance(author, Mapping) or set(author) != {"cell_mm_xyz", "pa_bounds_mm"}:
        raise ValueError("split parent requires explicit cells and bounds")
    cell = normalize_cell_mm_xyz(author["cell_mm_xyz"])
    box, dimensions = _numerical_box(author["pa_bounds_mm"], cell)
    domain = dict(dimensions=dimensions, cell_mm_xyz=cell,
                  instance_origin_mm={a: box[a + "_min"] for a in "xyz"}, bounds_mm=box)
    members = iter_geometry_members(oa_design)
    groups = list(dict.fromkeys(row["electrode_group_id"] for row in members))
    requested = numerics.get("electrode_group_native_ids")
    if requested is not None and (not isinstance(requested, Mapping) or set(requested) != {oa, *rf}):
        raise ValueError("split native frontend mapping must cover the OA instance")
    mapping = dict(zip(groups, range(1, len(groups) + 1), strict=True)) if requested is None else requested[oa]
    if (not isinstance(mapping, Mapping) or set(mapping) != set(groups)
            or any(type(value) is not int or not 1 <= value <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID for value in mapping.values())
            or len(set(mapping.values())) != len(mapping)):
        raise ValueError("split OA native labels must uniquely cover actual electrode groups")
    rf_bindings, rf_body, rf_samples = {}, [], []
    if rf:
        from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
        from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
        from msplatform.contracts.rigid_transform import RigidTransform, relative_transform
        from .geometry import MULTIPOLE_ROTATION, _require_multipole_domain_contains
        from .rf_electrode_mapping import build_simion_electrode_map
        from .rf_geometry import render_physical_gem
        from .gem_primitives import format_number
        name = rf[0]
        interface = plan["components"][name]
        actual = build_assembly_interface(components[name], geometry_profile_id=interface["geometry_profile_id"])
        if actual != interface:
            raise ValueError("RF resolved provider differs from its interface")
        edges = plan["recipe"]["connections"]
        if len(edges) != 1 or edges[0]["upstream"] != {"instance_id": name, "port_id": "mechanical_exit"} or edges[0]["downstream"] != {"instance_id": oa, "port_id": "side_entry"} or edges[0]["coupling_mode"] != "monolithic_joint_solve" or edges[0]["gap_mm"] <= 0:
            raise ValueError("split RF requires one positive-gap monolithic connection to the actual OA side entrance")
        relative = relative_transform(RigidTransform.from_contract(poses[name]), RigidTransform.from_contract(poses[oa]))
        if relative.rotation != MULTIPOLE_ROTATION:
            raise ValueError("split RF requires the validated native axis rotation")
        _require_multipole_domain_contains(box, components[name], relative.translation_mm)
        topology = build_electrode_topology(components[name])
        if requested is None:
            next_id = max(mapping.values()) + 1
            native = {row["electrode_group_id"]: next_id + i for i, row in enumerate(topology)}
        else:
            native = requested[name]
        native = build_simion_electrode_map(components[name], topology, requested_native_ids=native)
        if set(native.values()) & set(mapping.values()):
            raise ValueError("RF and OA native labels overlap in their shared field domain")
        rf_bindings[name] = native
        from .physical_samples import standalone_rf_samples
        translation = relative.translation_mm
        axes = (("x", "y", 1), ("y", "z", 2), ("z", "x", 0))
        local_origin = {local: domain["instance_origin_mm"][world] - translation[index]
                        for local, world, index in axes}
        local_cell = {local: cell[world] for local, world, _ in axes}
        local_dimensions = {"n" + local: dimensions["n" + world] for local, world, _ in axes}
        local_bounds = {local + "_" + edge: box[world + "_" + edge] - translation[index]
                        for local, world, index in axes for edge in ("min", "max")}
        local_domain = dict(instance_origin_mm=local_origin, cell_mm_xyz=local_cell,
                            dimensions=local_dimensions, bounds_mm=local_bounds)
        for sample in standalone_rf_samples(components[name], native, local_domain):
            if sample.get("metal"):
                sample["gu"] = [sample["gu"][2], sample["gu"][0], sample["gu"][1]]
                sample["label"] = name + ":" + sample["label"]
                rf_samples.append(sample)
        native_body = render_physical_gem(components[name], {"x": cell["y"], "y": cell["z"], "z": cell["x"]}, electrode_group_native_ids=native)
        rf_body = ["  locate(" + ",".join(format_number(v) for v in relative.translation_mm) + ",1,90,90,0) {", native_body.rstrip(), "  }"]
    from msplatform.components.shape_query import oa_witness_extent
    for member in members:
        for axis, (lo, hi) in zip("xyz", oa_witness_extent(member["shape"]), strict=True):
            lower, upper = box[axis + "_min"], box[axis + "_max"]
            # Same 32-ULP coordinate policy as components.shape_query's
            # ideal-plane comparison: this admits rounding, not physical gaps.
            tolerance = 32 * math.ulp(max(1., abs(lo), abs(hi), abs(lower), abs(upper)))
            if lo < lower - tolerance or hi > upper + tolerance:
                raise ValueError("split parent domain omits OA material")
    electrodes = {"grounded_shield_id": mapping["grounded_shield"],
        "accelerator_repeller_id": mapping["repeller"], "accelerator_grid1_id": mapping["intermediate_grid_1"],
        "accelerator_intermediate2_id": mapping["intermediate_grid_2"], "accelerator_grid2_id": mapping["exit_grid"],
        "accelerator_ring_ids": [mapping[f"ring_{index:04d}"] for index in range(1, len(oa_design["ring_z_mm"]) + 1)]}
    body = "\n".join([*rf_body, *render_accelerator_local_geometry(oa_design["geometry"], cell_x_mm=cell["x"],
        cell_z_mm=cell["z"], electrodes=electrodes, render_intermediate2_sheet=True)])
    gem = render_frontend_domain(body, dimensions=dimensions, cell_mm_xyz=cell, pa_origin_mm=domain["instance_origin_mm"])
    view = copy.deepcopy(components[tof])
    view.update(simion_geometry_build=copy.deepcopy(numerics["geometry_build"]),
                simion_detector_marker=copy.deepcopy(numerics["detector_marker"]))
    specs = compile_downstream_specs(view, split=True)
    face = resolve_split_physical_geometry(view)["detector_active_face"]
    surface = dict(instance_id=tof, surface_id="detector_active_face",
        local_frame_id=plan["components"][tof]["local_frame_id"],
        native_frame_id=plan["components"][oa]["local_frame_id"],
        local={key: copy.deepcopy(face[key]) for key in ("center_mm", "normal", "radius_mm")},
        native={key: copy.deepcopy(face[key]) for key in ("center_mm", "normal", "radius_mm")})
    identities = {name: dict(resolved_content_sha256=_content_sha256(components[name]),
                             component_interface_sha256=_content_sha256(plan["components"][name])) for name in (oa, tof, *rf)}
    geometry = dict(role="simion_split_oa_tof_geometry", composition_plan=plan,
        native_frame_id=plan["components"][oa]["local_frame_id"], oa_instance_id=oa, tof_instance_id=tof,
        numerical_domains={"parent": domain}, accelerator_projection=copy.deepcopy(oa_design["geometry"]),
        electrode_bindings={oa: dict(mapping), **rf_bindings},
        downstream_targets=split_downstream_targets(view), detector_active_face=surface,
        downstream_pa_instances=[dict(copy.deepcopy(spec["native_instance"]),
            grid_numerics=copy.deepcopy(numerics["geometry_build"][spec["role"]])) for spec in specs],
        downstream_build_contract=view, raw_physical_samples={"parent": [*_samples(members, mapping, domain), *rf_samples]})
    return CompiledSimionGeometry({"parent": gem}, geometry, specs, identities, copy.deepcopy(dict(components)))
