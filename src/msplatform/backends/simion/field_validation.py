"""Source-independent solved-field checks; no flight/source context is loaded."""
from __future__ import annotations

import math
from .frontend import frontend_electrode_maps


def require_supported_split_interfaces(geometry: dict, design: dict) -> None:
    """Reject unsupported biased ideal screening exits before any Refine.

    This is an applicability constraint of the existing imposed-zero-sheet
    field audit, not an instruction to alter the requested drive.
    """
    _, ids = frontend_electrode_maps(geometry)
    exit_id = ids['accelerator_grid2_id']
    operating = design['accelerator_voltage_states']['operating_voltages_v']
    tables = [operating, *(row['electrode_voltages_v'] for row in design['working_points'])]
    for table in tables:
        value = table.get(str(exit_id), table.get(exit_id))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value != 0:
            raise ValueError('split-field ideal OA exit requires actual ON and working-point potential zero')


def native_priority_occupancy_probes(geometry: dict, design: dict, *,
                                    terminal_observations: list[dict] | None = None) -> list[dict]:
    """Freeze declared native point checks; terminal neighborhoods are observations.

    Every field sample retains its source integer-node electrode check. Node
    positions are observations in continuous collision space. Metal must support
    an adjacent full cell in its unmasked domain; fine samples verify metal that
    masks a parent sample. Ideal sheets need no volume.
    Exact numerical faces retain world-query observations without asserting boundary instance choice;
    these checks do not qualify boundary-field continuity or dynamic fields.
    """
    if design.get("surface") != "none":
        raise ValueError("adjacent electrode-node cell checks require surface=none")
    domains = {row["domain_id"]: row for row in design["domains"]}
    parent, fine = domains["parent"], domains.get("entrance_refinement")
    fine_samples = {(row['label'], row['kind'], row['electrode_id'])
                    for row in fine['physical_samples']} if fine else set()

    def selected(point):
        return 5 if fine and all(fine["bounds_mm"][axis + "_min"] < value <
                                 fine["bounds_mm"][axis + "_max"]
                                 for axis, value in zip("xyz", point, strict=True)) else 3

    probes = []
    for domain in domains.values():
        for sample in domain["physical_samples"]:
            point = [domain["instance_origin_mm"][axis] + domain["cell_mm_xyz"][axis] * gu
                     for axis, gu in zip("xyz", sample["gu"], strict=True)]
            on_boundary = any(gu in (0, domain["dimensions"]["n" + axis] - 1)
                              for axis, gu in zip("xyz", sample["gu"], strict=True)) or any(
                all(other["bounds_mm"][axis + "_min"] <= value <= other["bounds_mm"][axis + "_max"]
                    for axis, value in zip("xyz", point, strict=True)) and
                any(value in (other["bounds_mm"][axis + "_min"], other["bounds_mm"][axis + "_max"])
                    for axis, value in zip("xyz", point, strict=True)) for other in domains.values())
            probe = dict(label=domain["domain_id"] + ":" + sample["label"], point_mm=point,
                expected_node_electrode=True,
                basis=dict(kind="resolved_physical_sample", domain_id=domain["domain_id"],
                           sample_label=sample["label"], sample_kind=sample["kind"],
                           electrode_id=sample["electrode_id"], gu=sample["gu"],
                           world_query_scope="numerical_boundary_observation" if on_boundary else "source_node_location_observation"))
            if sample["kind"] != "ideal_sheet":
                if domain['domain_id'] == 'parent' and fine and all(
                        fine['active_bounds_mm'][axis+'_min'] < value < fine['active_bounds_mm'][axis+'_max']
                        for axis, value in zip('xyz', point, strict=True)):
                    if (sample['label'], sample['kind'], sample['electrode_id']) not in fine_samples:
                        raise ValueError('masked parent metal lacks its fine physical sample: ' + sample['label'])
                else:
                    probe["expected_adjacent_metal_cell"] = True
            if not on_boundary:
                probe["expected_instance"] = selected(point)
            probes.append(probe)
    accelerator = geometry["accelerator_projection"]
    if accelerator.get("numerical_port_width_mm", 0) > 0 and accelerator.get("numerical_port_height_mm", 0) > 0:
        point = [accelerator["negative_x_face_mm"] + accelerator["shield_wall_mm"] / 2,
                 accelerator["port_center_y_mm"], accelerator["port_center_z_mm"]]
        probes.append(dict(label="provider_side_opening_center", point_mm=point,
            expected_instance=selected(point), basis=dict(kind="provider_side_opening_center",
                occupancy="observe_only_no_independent_point_in_metal_classifier")))
    if fine:
        anchor = [(fine["bounds_mm"][axis + "_min"] + fine["bounds_mm"][axis + "_max"]) / 2
                  for axis in "xyz"]
        for index, axis in enumerate("xyz"):
            for side, sign in (("min", -1), ("max", 1)):
                edge = fine["bounds_mm"][axis + "_" + side]
                gap = sign * (parent["bounds_mm"][axis + "_" + side] - edge)
                if gap <= 0:
                    continue
                for location, displacement, instance in (
                        ("inside", -sign * fine["cell_mm_xyz"][axis], 5),
                        ("outside", sign * min(parent["cell_mm_xyz"][axis], gap / 2), 3)):
                    point = list(anchor)
                    point[index] = edge + displacement
                    probes.append(dict(label=f"fine_{axis}_{side}_{location}", point_mm=point,
                        expected_instance=instance, basis=dict(kind="declared_numerical_domain_transition",
                            axis=axis, side=side, location=location, boundary_mm=edge,
                            displacement_mm=displacement, occupancy="observe_only")))
    for terminal in terminal_observations or ():
        instance = int(terminal["instance"])
        if instance not in (3, 5) or (instance == 5 and fine is None):
            raise ValueError("terminal neighborhoods require the declared parent or fine Cartesian domain")
        domain = fine if instance == 5 else parent
        center = [terminal[axis + "_mm"] for axis in "xyz"]
        offsets = [("center", [0., 0., 0.])]
        for index, axis in enumerate("xyz"):
            for sign in (-1, 1):
                offset = [0., 0., 0.]
                offset[index] = sign * domain["cell_mm_xyz"][axis]
                offsets.append((axis + ("_minus_cell" if sign < 0 else "_plus_cell"), offset))
        for name, offset in offsets:
            probes.append(dict(label=f"terminal_{terminal['particle_id']}_{name}",
                point_mm=[value + delta for value, delta in zip(center, offset, strict=True)],
                basis=dict(kind="observed_native_terminal_neighborhood", particle_id=terminal["particle_id"],
                    recorded_instance=instance, instrument_time_us=terminal["instrument_time_us"],
                    offset_mm=offset, occupancy="observe_only_no_physical_object_attribution")))
    return probes


def interface_field_probes(geometry: dict, oatof: dict) -> list[dict]:
    """Declare bounded checks at the provider's grounded ideal-grid interfaces.

    These are screening boundaries of the supported split-field model, not a
    certificate of the omitted finite-grid edge coupling. Normal field jumps
    across an ideal electrode are permitted. No PA payload is read here.
    """
    g = geometry['accelerator_projection']
    parent = geometry['numerical_domains']['parent']
    downstream = {row['role']: row for row in geometry['downstream_pa_instances']}
    reflectron = downstream['reflectron']
    coord = oatof['coordinate_convention']
    definitions = (
        ('accelerator_exit', 3, [g['axis_x_mm'], g['axis_y_mm'], g['grid2_z_mm']],
         g['bore_width_mm'] / 4, parent['cell_mm_xyz']['z'],
         min(parent['cell_mm_xyz']['x'], parent['cell_mm_xyz']['y'])),
        ('reflectron_entry', 2, [coord['reflectron_axis'][0], coord['reflectron_axis'][1],
                               oatof['geometry_mm']['L_flight']],
         oatof['geometry_mm']['bore_r'] / 2,
         reflectron['grid_numerics']['cell_axial_mm'],
         reflectron['grid_numerics']['cell_radial_mm']),
    )
    probes = []
    for label, instance, center, radius, axial_step, tangent_step in definitions:
        points = [list(center)]
        for axis in (0, 1):
            for sign in (-1, 1):
                point = list(center)
                point[axis] += sign * radius
                points.append(point)
        probes.append(dict(label=label, instance_index=instance, grounded_instance_index=1,
            normal=[0., 0., 1.], points_mm=points, axial_step_mm=axial_step,
            tangent_step_mm=tangent_step, physical_surface='zero_thickness_grounded_ideal_grid',
            expected_potential_v=0., voltage_tolerance_v=1e-8,
            tolerance_basis='bounded imposed-zero-electrode binary64/interpolation audit; not field accuracy',
            validity_scope='declared interior grid samples only; finite-grid edge coupling unqualified'))
    return probes
