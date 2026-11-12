"""Direct native-body assembly for a multipole and oaTOF accelerator entrance.

This prepares geometry only, without fields, clocks, source or flight acceptance.
The two providers own their solids; the recipe owns their direct placement.
"""
from __future__ import annotations

import math
import copy
from typing import Any

from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform, relative_transform
from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from msplatform.components.rf_multipole.face_sections import local_face_conductor_sections
from msplatform.backends.simion.rf_electrode_mapping import build_simion_electrode_map
from msplatform.backends.simion.rf_assembly_interface import build_legacy_assembly_interface
from msplatform.backends.simion.rf_geometry import render_physical_gem
from msplatform.backends.simion.numerics import normalize_cell_mm_xyz
from msplatform.backends.simion.gem_primitives import format_number as _fmt
from msplatform.backends.simion.frontend import _electrodes, native_frontend_instances
from msplatform.backends.simion.accelerator_renderer import render_accelerator_local_geometry
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import (
    resolve_accelerator_geometry,
)
from msplatform.components.single_reflection_oa_tof.electrode_topology import resolve_frontend_field_domain
from msplatform.assembly.electrode_binding import validate_electrode_bindings
from msplatform.backends.simion.tof_geometry import derive_simion_instances, resolve_physical_geometry
from msplatform.backends.simion.accelerator_projection import project_side_opening
from msplatform.backends.simion.tof_assembly_interface import resolve_provider_assembly_interface as resolve_assembly_interface

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
    geometry = multipole["geometry_mm"]
    rods = geometry["rod_array"]["rods"]
    radius = max(math.hypot(rod["center_x_mm"], rod["center_y_mm"]) + rod["radius_mm"] for rod in rods)
    axial_min, axial_max = geometry["rod_z_min"], geometry["rod_z_max"]
    for body in geometry["enclosure_layout"]["bodies"]:
        radius = max(radius, body["outer_radius_mm"])
        axial_min = min(axial_min, body["z_min_mm"])
        axial_max = max(axial_max, body["z_max_mm"])
    tx, ty, tz = translation
    lower = (tx + axial_min, ty - radius, tz - radius)
    upper = (tx + axial_max, ty + radius, tz + radius)
    if any(lower[index] < box[f"{axis}_min"] - 1e-9 or upper[index] > box[f"{axis}_max"] + 1e-9
           for index, axis in enumerate("xyz")):
        raise ValueError("PA bounds clip a provider physical envelope")


def render_frontend_body(
    multipoles: list[tuple[dict, tuple, dict[int | str, int]]], *, accelerator_projection: dict,
    cell_mm_xyz: dict, accelerator_electrodes: dict,
    render_intermediate2_sheet: bool,
    include_multipole: bool = True,
    scientific_groups: bool = False,
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
            native_body = render_physical_gem(multipole_resolved, native_cells,
                **({'electrode_group_native_ids': multipole_electrode_ids} if scientific_groups else
                   {'electrode_ids': multipole_electrode_ids}))
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


def _multipole_face_sections(resolved: dict, pose: RigidTransform, side: str) -> list[tuple]:
    """Place provider-owned face sections in the validated OA frame, in mm."""
    sections = []
    for section in local_face_conductor_sections(resolved, side=side):
        center = pose.transform_position(FramedPosition(pose.from_frame_id, section.center_mm)).coordinates_mm
        label = f'{section.role} group {section.electrode_group_id} member {section.member_ref}'
        sections.append((label, center, section.inner_radius_mm, section.outer_radius_mm, section.is_grounded))
    return sections


def _oa_ground_face_rectangles(geometry: dict, opening: dict) -> list[tuple]:
    """Finite outer side face minus the physical aperture; a cylinder has a tangent line."""
    half = geometry['shield_outer_width_mm'] / 2 if geometry['cross_section'] == 'square' else 0.
    left, right = geometry['axis_y_mm'] - half, geometry['axis_y_mm'] + half
    bottom, top = geometry['shield_back_z_mm'], geometry['grid2_z_mm']
    _, y, z = opening['center_mm']
    hole_left, hole_right = y - opening['width_mm']/2, y + opening['width_mm']/2
    hole_bottom, hole_top = z - opening['height_mm']/2, z + opening['height_mm']/2
    rectangles = [(left, right, bottom, bottom + geometry['shield_wall_mm']),
                  (left, min(right,hole_left), bottom, top),
                  (max(left,hole_right), right, bottom, top),
                  (max(left,hole_left), min(right,hole_right), bottom, min(top,hole_bottom)),
                  (max(left,hole_left), min(right,hole_right), max(bottom,hole_top), top)]
    return [rect for rect in rectangles if rect[0] <= rect[1] and rect[2] <= rect[3]]


def _require_separate_face_conductors(upstream: str, sections: list[tuple], downstream: str,
                                      target_sections: list[tuple] | None, oa: dict, opening: dict) -> None:
    """Reject actual coplanar contact of independent conductors, not a bare/gap label.

    This circular-section check is not a general collision or HV clearance certificate.
    Grounded shells may join the grounded OA shield or another grounded shell.
    """
    for label, center, inner, outer, ground in sections:
        if target_sections is not None:
            for other_label, other_center, other_inner, other_outer, other_ground in target_sections:
                distance = math.dist(center[1:], other_center[1:])
                if (not (ground and other_ground) and math.isclose(center[0], other_center[0], abs_tol=1e-9, rel_tol=0)
                        and distance <= outer + other_outer and distance + outer >= other_inner
                        and distance + other_outer >= inner):
                    raise ValueError(f'{upstream} {label} contacts {downstream} {other_label} at the mechanical face')
        elif not ground:
            for left, right, bottom, top in _oa_ground_face_rectangles(oa, opening):
                y, z = center[1:]
                nearest = math.hypot(max(left-y, 0., y-right), max(bottom-z, 0., z-top))
                farthest = max(math.hypot(y-a, z-b) for a in (left,right) for b in (bottom,top))
                if nearest <= outer and farthest >= inner:
                    raise ValueError(f'{upstream} {label} contacts {downstream} grounded shield at the mechanical face')


def compile_frontend_geometry(
    multipoles_resolved: dict[str, dict], oatof_resolved: dict, *, composition_plan: dict,
    accelerator_variant: str, numerical_domains: dict, electrode_bindings: dict,
    provider_inputs: dict | None = None,
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
    version = plan.get('schema_version')
    if type(version) is not int or version not in (3, 4, 5):
        raise ValueError('unsupported frontend composition plan version')
    scientific = version == 5
    multipole_ids, downstream_id = native_frontend_instances(plan)
    if not isinstance(multipoles_resolved, dict) or set(multipoles_resolved) != set(multipole_ids):
        raise ValueError('resolved multipole designs must name exactly the selected native multipoles')
    if set(electrode_bindings) != set(plan['scope']['instance_ids']):
        raise ValueError('electrode bindings must name exactly the selected assembly instances')
    if scientific:
        multipole_electrodes = {instance: build_simion_electrode_map(multipoles_resolved[instance],
            build_electrode_topology(multipoles_resolved[instance]), requested_native_ids=electrode_bindings[instance])
            for instance in multipole_ids}
    else:
        multipole_electrodes = {instance: {int(key): value for key, value in electrode_bindings[instance].items()}
                               for instance in multipole_ids}
    accelerator_electrodes = electrode_bindings[downstream_id]
    parent_interface = plan['components'][downstream_id]
    port = parent_interface['ports']['side_entry']
    section = port['cross_section']
    if section['shape'] != 'rectangle':
        raise ValueError(f'{downstream_id}: native side opening requires a rectangle')
    side_opening = dict(center_mm=port['center_mm'], width_mm=section['width_mm'], height_mm=section['height_mm'])
    projection = resolve_accelerator_geometry(oatof_resolved, variant_id=accelerator_variant)
    project_side_opening(projection.local_region, side_opening=side_opening, cell_mm_xyz=cells, pa_origin_mm=origin)
    actual = resolve_assembly_interface(oatof_resolved, projection=projection,
        geometry_profile_id=parent_interface['geometry_profile_id'], schema_version=parent_interface['schema_version'])
    if actual != parent_interface:
        raise ValueError(f'{downstream_id}: resolved provider mechanical interface differs from the parent composition plan')
    binding_record = None
    if scientific:
        from msplatform.backends.simion.tof_electrode_mapping import native_frontend_electrodes

        if not isinstance(provider_inputs, dict) or set(provider_inputs) != set(plan['scope']['instance_ids']):
            raise ValueError('plan5 requires verified provider input records for every selected instance')
        domain = resolve_frontend_field_domain(oatof_resolved, projection=projection,
            geometry_profile_id=parent_interface['geometry_profile_id'])
        accelerator_electrodes = native_frontend_electrodes(accelerator_electrodes, frontend_domain=domain)
        scope = {instance: [row['electrode_group_id'] for row in plan['components'][instance]['component_electrodes']]
                 for instance in multipole_ids}
        scope[downstream_id] = domain['electrode_group_ids']
        binding_record = dict(schema_version=2, role='backend_electrode_bindings', backend='simion',
            field_domain_id=domain['domain_id'], provider_inputs=copy.deepcopy(provider_inputs),
            electrode_group_scope=scope, bindings=[dict(instance_id=instance, electrode_group_id=group,
                native_electrode_id=native) for instance, mapping in electrode_bindings.items() for group, native in mapping.items()])
        validate_electrode_bindings({instance: plan['components'][instance] for instance in plan['scope']['instance_ids']},
            binding_record, field_domain_id=domain['domain_id'], provider_inputs=provider_inputs, electrode_group_scope=scope)
    elif provider_inputs is not None:
        raise ValueError('legacy frontend plans cannot declare canonical provider input bindings')
    for instance_id in multipole_ids:
        expected = plan['components'][instance_id]
        if expected['schema_version'] == 3:
            actual = build_assembly_interface(multipoles_resolved[instance_id], geometry_profile_id=expected['geometry_profile_id'])
        else:
            actual = build_legacy_assembly_interface(multipoles_resolved[instance_id],
                geometry_profile_id=expected['geometry_profile_id'], schema_version=expected['schema_version'])
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
        if target not in selected or edge['gap_mm'] < 0 or edge['coupling_mode'] != 'monolithic_joint_solve' or edge['upstream']['port_id'] != 'mechanical_exit':
            raise ValueError(f'{instance_id}: native chain requires a nonnegative gap and monolithic mechanical_exit')
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
    for edge in relevant:
        upstream, target = edge['upstream']['instance_id'], edge['downstream']['instance_id']
        if upstream in multipoles_resolved and edge['gap_mm'] == 0:
            sections = _multipole_face_sections(multipoles_resolved[upstream], poses[upstream], 'exit')
            target_sections = (_multipole_face_sections(multipoles_resolved[target], poses[target], 'entrance')
                               if target in multipoles_resolved else None)
            _require_separate_face_conductors(upstream, sections, target, target_sections, g, side_opening)
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
        scientific_groups=scientific,
    )
    gems = {name: render_frontend_domain(body, dimensions=domain['dimensions'],
            cell_mm_xyz=domain['cell_mm_xyz'], pa_origin_mm=domain['instance_origin_mm'])
            for name, domain in domains.items()}
    build, marker = oatof_resolved['simion_geometry_build'], oatof_resolved['simion_detector_marker']
    detector_body = resolve_physical_geometry(oatof_resolved)["simion"]["detector_body"]
    provider_domains = derive_simion_instances(
        geometry=oatof_resolved['geometry_mm'], coordinate=oatof_resolved['coordinate_convention'],
        build=build, marker=marker, physical_detector=detector_body)
    downstream = []
    for instance in provider_domains:
        role = instance['role']
        if role == 'accelerator':
            continue
        if role == 'detector':
            downstream.append(dict(instance, frame_id=FRAME, numerical_marker=dict(marker), physical_detector=dict(detector_body),
                grid_numerics=dict(build['detector'], cell_xy_mm=marker['cell_xy_mm'], cell_z_mm=marker['cell_z_mm']),
                scope='physical_detector_with_numerical_observation_marker'))
        else:
            downstream.append(dict(instance, frame_id=FRAME,
                grid_numerics=dict(build['flight_tube' if role == 'flight_tube_shield' else role]),
                scope='provider_PA_domain_description__not_generated_PA'))
    bindings = copy.deepcopy(electrode_bindings) if scientific else {downstream_id: copy.deepcopy(accelerator_electrodes)}
    if not scientific:
        bindings.update({instance_id: dict(multipole_electrodes[instance_id]) for instance_id in multipole_ids})
    return gems, dict(composition_plan=plan, native_frame_id=native_frame, accelerator_projection=g, numerical_domains=domains,
                      electrode_bindings=bindings, downstream_pa_instances=downstream,
                      **(dict(frontend_field_domain=domain, backend_electrode_bindings=binding_record) if scientific else {}))
