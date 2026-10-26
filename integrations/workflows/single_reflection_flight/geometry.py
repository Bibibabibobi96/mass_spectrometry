"""Direct native-body assembly for a multipole and oaTOF accelerator entrance.

This prepares geometry only, without fields, clocks, source or flight acceptance.
The two providers own their solids; the recipe owns their direct placement.
"""
from __future__ import annotations

import math
import copy
from typing import Any

from common.contracts.rigid_transform import RigidTransform, relative_transform
from common.multipole.component_port import build_assembly_interface
from common.multipole.simion_geometry import render_physical_gem
from common.multipole.simion_numerics import normalize_cell_mm_xyz
from common.simion.gem_primitives import format_number as _fmt
from integrations.runtime.single_flight_frontend import _electrodes, native_frontend_instances
from projects.orthogonal_accelerator.simion.sectioned_accelerator import render_accelerator_local_geometry
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import (
    project_side_opening, resolve_accelerator_geometry,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.assembly_interface import resolve_assembly_interface
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import derive_simion_geometry

FRAME = "oatof_global"
MULTIPOLE_ROTATION = ((0., 0., 1.), (1., 0., 0.), (0., 1., 0.))


def _numerical_box(bounds: dict, cells: dict) -> tuple[dict, dict]:
    if set(bounds) != {f"{axis}_{end}" for axis in "xyz" for end in ("min", "max")}:
        raise ValueError("pa_bounds_mm requires exactly x/y/z_min/max")
    box = {key: float(value) for key, value in bounds.items()}
    dimensions = {}
    for axis in "xyz":
        lower, upper = box[f"{axis}_min"], box[f"{axis}_max"]
        count = (upper - lower) / cells[axis]
        if (not all(math.isfinite(value) for value in (lower, upper)) or count <= 0
                or not math.isclose(count, round(count), rel_tol=0, abs_tol=1e-8)):
            raise ValueError("PA bounds must be finite, increasing and span whole cells")
        dimensions["n" + axis] = round(count) + 1
    return box, dimensions


def _require_domain_contains(box: dict, multipoles: list[tuple[dict, tuple]], accelerator: dict,
                             *, entrance_opening: dict | None = None) -> None:
    """Check conservative provider envelopes, without altering a physical face."""
    envelopes = []
    for multipole, translation in multipoles:
        _require_multipole_domain_contains(box, multipole, translation)
    half = float(accelerator["shield_outer_width_mm"]) / 2
    x, y = float(accelerator["axis_x_mm"]), float(accelerator["axis_y_mm"])
    if entrance_opening is None:
        envelopes.append(((x-half, y-half, float(accelerator["shield_back_z_mm"])),
                          (x+half, y+half, float(accelerator["grid2_z_mm"]))))
    else:
        port_x, port_y, port_z = entrance_opening["center_mm"]
        dy, dz = entrance_opening["width_mm"]/2, entrance_opening["height_mm"]/2
        envelopes.append(((port_x, port_y-dy, port_z-dz),
                          (port_x+float(accelerator["shield_wall_mm"]), port_y+dy, port_z+dz)))
    for lower, upper in envelopes:
        if any(lower[index] < box[f"{axis}_min"] - 1e-9 or upper[index] > box[f"{axis}_max"] + 1e-9
               for index, axis in enumerate("xyz")):
            raise ValueError("PA bounds clip a provider physical envelope")


def _require_multipole_domain_contains(box: dict, multipole: dict, translation: tuple) -> None:
    enclosure = multipole["geometry_mm"]["enclosure"]
    radius = float(enclosure["shield_outer_radius_mm"])
    entrance, exit_port = (multipole["interfaces_mm"][side] for side in ("entrance", "exit"))
    axial_min = min(float(enclosure["vacuum_z_min_mm"]), float(entrance["connector_upstream_face_z_mm"]))
    axial_max = max(float(enclosure["exit_outer_endcap_downstream_face_z_mm"]), float(exit_port["connector_downstream_face_z_mm"]))
    sleeve = multipole.get("axial_dc", {}).get("entrance_reference_sleeve")
    if sleeve is not None:
        radius = max(radius, float(sleeve["outer_radius_mm"]))
        axial_min = min(axial_min, float(sleeve["upstream_face_z_mm"]))
        axial_max = max(axial_max, float(sleeve["downstream_face_z_mm"]))
    tx, ty, tz = translation
    lower = (tx + axial_min, ty - radius, tz - radius)
    upper = (tx + axial_max, ty + radius, tz + radius)
    if any(lower[index] < box[f"{axis}_min"] - 1e-9 or upper[index] > box[f"{axis}_max"] + 1e-9
           for index, axis in enumerate("xyz")):
        raise ValueError("PA bounds clip a provider physical envelope")


def render_frontend_body(
    multipoles: list[tuple[dict, tuple, dict[int, int]]], *, accelerator_projection: dict,
    cell_mm_xyz: dict, accelerator_electrodes: dict,
    render_intermediate2_sheet: bool,
    include_multipole: bool = True,
) -> str:
    """Render the complete physical body after the assembly pose is validated.

    Cells retain the providers' Boolean subtraction overruns, not a PA domain.
    Reuse this returned body unchanged when wrapping additional numerical domains.
    """
    cells = cell_mm_xyz
    native_cells = dict(x=cells["y"], y=cells["z"], z=cells["x"])
    native_lines = []
    if include_multipole:
        for multipole_resolved, multipole_translation_mm, multipole_electrode_ids in multipoles:
            native_body = render_physical_gem(multipole_resolved, native_cells, electrode_ids=multipole_electrode_ids)
            native_lines.extend([
                "  locate(" + ",".join(_fmt(value) for value in multipole_translation_mm) + ",1,90,90,0) {",
                native_body.rstrip(), "  }",
            ])
    accelerator_body = render_accelerator_local_geometry(
        accelerator_projection, cell_x_mm=cells["x"], cell_z_mm=cells["z"],
        electrodes=accelerator_electrodes, render_intermediate2_sheet=render_intermediate2_sheet,
    )
    # Official locate order: rt about X, el about Z, az about Y. Ry90 Rz90
    # equals the validated single recipe rotation; no numerical origin is here.
    return "\n".join([*native_lines, *accelerator_body])


def render_frontend_domain(
    body: str, *, dimensions: dict, cell_mm_xyz: dict, pa_origin_mm: dict,
) -> str:
    """Wrap one unchanged body in an already validated numerical PA domain.

    This serializer neither resolves providers nor changes component poses,
    electrodes, openings or sheets. Domain coverage is the planner's contract.
    """
    # surface=none's ordinary within expands fills beyond the physical solid.
    # Use the supported node-inside-or-on instruction for these generated bodies;
    # preserve all explicit hole operators and the original provider body.
    # https://simion.com/info/gem_geometry_file.html (SIMION 8.1.1.25+).
    body = body.replace(" within {", " within_inside_or_on {")
    return "\n".join([
        "; Provider-native bodies, direct assembly poses; geometry preparation only.",
        f"pa_define({dimensions['nx']},{dimensions['ny']},{dimensions['nz']},planar,none,electrostatic,,"
        f"{_fmt(cell_mm_xyz['x'])},{_fmt(cell_mm_xyz['y'])},{_fmt(cell_mm_xyz['z'])},surface=none)",
        "locate(" + ",".join(_fmt(-pa_origin_mm[axis]) for axis in "xyz") + ") {",
        body, "}", "",
    ])


def compile_frontend_geometry(
    multipoles_resolved: dict[str, dict], oatof_resolved: dict, *, composition_plan: dict,
    accelerator_variant: str, numerical_domains: dict, electrode_bindings: dict,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Compile one directly posed chain of native multipoles and one OA body."""
    if not isinstance(numerical_domains, dict) or not {'parent'} <= numerical_domains.keys() <= {'parent', 'entrance_refinement'}:
        raise ValueError("numerical domains require parent and optional entrance_refinement only")
    domains = {}
    for domain_id in ('parent', 'entrance_refinement'):
        if domain_id not in numerical_domains:
            continue
        author = numerical_domains[domain_id]
        if not isinstance(author['cell_mm_xyz'], dict):
            raise ValueError(f"{domain_id}: cell_mm_xyz requires explicit x, y and z")
        pitch = normalize_cell_mm_xyz(author['cell_mm_xyz'])
        box, sizes = _numerical_box(author['pa_bounds_mm'], pitch)
        domain = dict(dimensions=sizes, cell_mm_xyz=pitch,
                      instance_origin_mm={axis: box[axis + '_min'] for axis in 'xyz'}, bounds_mm=box)
        if domain_id == 'entrance_refinement':
            parent = domains['parent']['bounds_mm']
            if any(box[a+'_min'] < parent[a+'_min'] or box[a+'_max'] > parent[a+'_max'] for a in 'xyz'):
                raise ValueError("entrance_refinement bounds must lie within parent")
            guard = author['guard_cells']
            if type(guard) is not int or guard < 1:
                raise ValueError("entrance_refinement guard_cells must be a positive integer")
            active = {a+'_'+end: box[a+'_'+end]+sign*guard*pitch[a]
                      for a in 'xyz' for end, sign in (('min', 1), ('max', -1))}
            if any(active[a+'_min'] >= active[a+'_max'] for a in 'xyz'):
                raise ValueError("entrance_refinement guard leaves no active interior")
            domain['active_bounds_mm'] = active
        domains[domain_id] = domain
    parent = domains['parent']
    cells, bounds, origin = parent['cell_mm_xyz'], parent['bounds_mm'], parent['instance_origin_mm']
    plan = composition_plan
    multipole_ids, downstream_id = native_frontend_instances(plan)
    if not isinstance(multipoles_resolved, dict) or set(multipoles_resolved) != set(multipole_ids):
        raise ValueError('resolved multipole designs must name exactly the selected native multipoles')
    if set(electrode_bindings) != set(plan['scope']['instance_ids']):
        raise ValueError('electrode bindings must name exactly the selected assembly instances')
    multipole_electrodes = {
        instance_id: {int(key): value for key, value in electrode_bindings[instance_id].items()}
        for instance_id in multipole_ids
    }
    accelerator_electrodes = electrode_bindings[downstream_id]
    parent_interface = plan['components'][downstream_id]
    port = parent_interface['ports']['side_entry']
    section = port['cross_section']
    if section['shape'] != 'rectangle':
        raise ValueError(f'{downstream_id}: native side opening requires a rectangle')
    side_opening = dict(center_mm=port['center_mm'], width_mm=section['width_mm'], height_mm=section['height_mm'])
    projection = resolve_accelerator_geometry(oatof_resolved, variant_id=accelerator_variant)
    project_side_opening(projection.local_region, side_opening=side_opening, cell_mm_xyz=cells, pa_origin_mm=origin)
    actual = resolve_assembly_interface(oatof_resolved, projection=projection, geometry_profile_id=parent_interface['geometry_profile_id'])
    if actual != parent_interface:
        raise ValueError(f'{downstream_id}: resolved provider mechanical interface differs from the parent composition plan')
    for instance_id in multipole_ids:
        expected = plan['components'][instance_id]
        actual = build_assembly_interface(multipoles_resolved[instance_id], geometry_profile_id=expected['geometry_profile_id'])
        if actual != expected:
            raise ValueError(f'{instance_id}: resolved provider mechanical interface differs from the parent composition plan')
    edges = plan['recipe']['connections']
    selected = set(multipole_ids) | {downstream_id}
    relevant = [edge for edge in edges if edge['upstream']['instance_id'] in selected and edge['downstream']['instance_id'] in selected]
    next_by_multipole, incoming = {}, set()
    for instance_id in multipole_ids:
        outgoing = [edge for edge in relevant if edge['upstream']['instance_id'] == instance_id]
        if len(outgoing) != 1:
            raise ValueError(f'{instance_id}: native chain requires exactly one downstream mechanical connection')
        edge = outgoing[0]
        target = edge['downstream']['instance_id']
        if target not in selected or edge['gap_mm'] != 0 or edge['coupling_mode'] != 'monolithic_joint_solve' or edge['upstream']['port_id'] != 'mechanical_exit':
            raise ValueError(f'{instance_id}: native chain requires zero-gap monolithic mechanical_exit')
        if target == downstream_id:
            if edge['downstream']['port_id'] != 'side_entry':
                raise ValueError('last native multipole must connect mechanical_exit to the OA side_entry')
        elif target in multipole_ids:
            if edge['downstream']['port_id'] != 'mechanical_entrance':
                raise ValueError('intermediate native multipole requires a real mechanical_entrance')
            incoming.add(target)
        else:
            raise ValueError('native multipole chain target is unsupported')
        next_by_multipole[instance_id] = target
    if multipole_ids:
        heads = set(multipole_ids) - incoming
        if len(heads) != 1:
            raise ValueError('native multipoles must form one unbranched chain')
        ordered = []
        cursor = next(iter(heads))
        while cursor != downstream_id:
            if cursor in ordered:
                raise ValueError('native multipole chain contains a cycle')
            ordered.append(cursor)
            cursor = next_by_multipole.get(cursor)
            if cursor is None:
                raise ValueError('native multipole chain is incomplete')
        if set(ordered) != set(multipole_ids):
            raise ValueError('native multipole chain has an unattached instance')
        multipole_ids = tuple(ordered)
    if not multipole_ids and 'entrance_refinement' in domains:
        raise ValueError('OA-only native scope cannot use multipole entrance_refinement')
    poses = {item['instance_id']: RigidTransform.from_contract(item['transform']) for item in plan['recipe']['instances']}
    native_frame = plan['components'][downstream_id]['local_frame_id']
    poses = {key: relative_transform(pose, poses[downstream_id]) for key, pose in poses.items()}
    if (plan['integration_id'] != 'instrument_assembly' or native_frame != FRAME
            or any(poses[instance_id].rotation != MULTIPOLE_ROTATION for instance_id in multipole_ids)):
        raise ValueError('geometry requires the native oaTOF local frame and the explicit relative multipole Z-to-X cyclic rotation')
    g = projection.local_region
    three_zone = accelerator_variant == 'three_zone_square'
    _electrodes(accelerator_electrodes, g['ring_count'], three_zone, multipole_electrodes)
    physical_multipoles = [(multipoles_resolved[instance_id], poses[instance_id].translation_mm)
                            for instance_id in multipole_ids]
    _require_domain_contains(bounds, physical_multipoles, g)
    if 'entrance_refinement' in domains:
        _require_domain_contains(domains['entrance_refinement']['active_bounds_mm'], physical_multipoles, g,
                                 entrance_opening=side_opening)
    body = render_frontend_body(
        [(multipoles_resolved[instance_id], poses[instance_id].translation_mm, multipole_electrodes[instance_id])
         for instance_id in multipole_ids],
        accelerator_projection=g, cell_mm_xyz=cells, accelerator_electrodes=accelerator_electrodes,
        render_intermediate2_sheet=three_zone, include_multipole=bool(multipole_ids),
    )
    gems = {name: render_frontend_domain(body, dimensions=domain['dimensions'],
            cell_mm_xyz=domain['cell_mm_xyz'], pa_origin_mm=domain['instance_origin_mm'])
            for name, domain in domains.items()}
    build, marker = oatof_resolved['simion_geometry_build'], oatof_resolved['simion_detector_marker']
    provider_domains = derive_simion_geometry(
        geometry=oatof_resolved['geometry_mm'], coordinate=oatof_resolved['coordinate_convention'],
        build=build, marker=marker, source=oatof_resolved['particle_source'])
    downstream = []
    for instance in provider_domains['simion_instances']:
        role = instance['role']
        if role == 'accelerator':
            continue
        if role == 'detector':
            downstream.append(dict(instance, frame_id=FRAME, numerical_marker=dict(marker),
                grid_numerics=dict(build['detector'], cell_xy_mm=marker['cell_xy_mm'], cell_z_mm=marker['cell_z_mm']),
                scope='numerical_detector_marker__not_mechanical_detector'))
        else:
            downstream.append(dict(instance, frame_id=FRAME,
                grid_numerics=dict(build['flight_tube' if role == 'flight_tube_shield' else role]),
                scope='provider_PA_domain_description__not_generated_PA'))
    bindings = {downstream_id: copy.deepcopy(accelerator_electrodes)}
    bindings.update({instance_id: dict(multipole_electrodes[instance_id]) for instance_id in multipole_ids})
    return gems, dict(composition_plan=plan, native_frame_id=native_frame, accelerator_projection=g, numerical_domains=domains,
                      electrode_bindings=bindings, downstream_pa_instances=downstream)
