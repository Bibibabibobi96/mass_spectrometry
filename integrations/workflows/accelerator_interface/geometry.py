"""Materialize one IP/MR design through the shared mechanical composition plan."""
from __future__ import annotations

from pathlib import Path
import copy
import itertools

from common.contracts.file_identity import file_sha256
from common.simion.gem_primitives import format_number
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_transform
from common.contracts.verify_run_manifest import verify_record
from projects.dual_pressure_rectilinear_ion_processor.analysis.assembly_interface import resolve_assembly_interface as ip_interface
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection, render_gem
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.assembly_interface import resolve_assembly_interface as mr_interface
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import (
    _bounds, _finite, _gem, _grid_plan, _inside_body, _point, _primitive, _read,
    _shield_contains, _transform_projection, _write, derive_lift_seed,
)


def resolve_ion_processor_design(source: dict, trajectory: dict, request: dict,
                                 geometry: dict, coordinate: dict, *, extraction_gap_mm: float) -> dict:
    """Derive IP seed and MR clearances from the caller's unique native-to-MR pose.

    This pure scientific stage changes declared LP length/lift/P1 extension only.
    It does not place the final conductors, write files or transform handoff states.
    """
    target = _finite(request["target"]["axial_energy_per_charge_v"])
    measured = _finite(request["current_measured_baseline"]["directional_energy"]["z"]["mean"])
    if (
        target <= 0
        or measured <= 0
        or request["requirements"]["energy_definition"] != "exit_axial_kinetic_energy_per_charge"
    ):
        raise ValueError("positive measured and target axial energy per charge required")
    geometry = copy.deepcopy(geometry)
    if (
        geometry["frame_id"] != request["target"]["frame_id"]
        or trajectory["coordinate_system"]["frame_id"] != geometry["frame_id"]
    ):
        raise ValueError("MR assembly reference frame differs")
    baseline, numerics = copy.deepcopy(source["baseline"]), copy.deepcopy(source["numerics"])
    # Author the current explicit aperture from the measured provider's resolved
    # metal opening, not a current default or the independently defined Pull slit.
    source_projection = source["native_projection"]
    if (source_projection["frame_id"] != baseline["clock"]["frame_id"]
            or source_projection["length_unit"] != "mm"):
        raise ValueError("source native_projection E14 aperture frame or unit differs")
    shields = [e for e in source_projection["electrodes"] if e["electrode_id"] == 14]
    if len(shields) != 1 or len(shields[0]["cutouts"]) != 1:
        raise ValueError("source native_projection requires one E14 extraction cutout")
    aperture = shields[0]["cutouts"][0]
    if aperture["shape"] != "box":
        raise ValueError("source native_projection E14 extraction cutout must be rectangular")
    low, high = _finite(aperture["min_mm"][2]), _finite(aperture["max_mm"][2])
    shield_width = high - low
    if low != -high or shield_width <= 0:
        raise ValueError("source native_projection E14 extraction cutout must be centered with positive width")
    native = baseline["native_geometry"]
    if "shield_extraction_slit_width_mm" in native and native["shield_extraction_slit_width_mm"] != shield_width:
        raise ValueError("source baseline shield aperture differs from native_projection E14 cutout")
    native["shield_extraction_slit_width_mm"] = shield_width
    # Historical source evidence stays immutable; author only the current native seed.
    for section, names in {
        "geometry": ("interface_halfwidth_mm", "guide_blend_halfwidth_mm"),
        "electric": ("hp_axial_curvature_v_per_mm2", "lp_axial_curvature_v_per_mm2",
                     "lp_capture_offset_v", "hp_transfer_offset_v", "extraction_gradient_v_per_mm",
                     "hp_transfer_gradient_v_per_mm", "lp_transfer_axial_curvature_v_per_mm2"),
    }.items():
        for name in names:
            baseline[section].pop(name, None)
    point = copy.deepcopy(source["native_operating_point"])
    old_lift = _finite(point["lift_v"])
    if baseline["electric"]["lift_v"] != old_lift:
        raise ValueError("provider native and baseline lift bindings differ")
    point["lift_v"] = derive_lift_seed(source, request)
    if point["lift_v"] <= 0:
        raise ValueError("derived lift seed must remain positive")
    baseline["electric"]["lift_v"] = point["lift_v"]
    rotation, translation = coordinate["rotation"], coordinate["translation_mm"]
    if coordinate["from_frame_id"] != source_projection["frame_id"] or coordinate["to_frame_id"] != geometry["frame_id"]:
        raise ValueError("IP native design pose must map directly into the MR geometry frame")
    before_projection = native_projection(baseline, numerics)
    central = next(s for s in geometry["prism_ground_shields"] if s["station"] == "central_ground_left")
    p1 = next(s for s in geometry["prism_ground_shields"] if s["station"] == "accelerator_exit")
    clearance = _finite(trajectory["prisms"]["ground_shields"][0]["extension_to_accelerator_exit"]["clearance_mm"])
    if clearance <= 0 or rotation != [[0, 0, -1], [1, 0, 0], [0, -1, 0]]:
        raise ValueError("positive existing P1 clearance and current IP native orientation required")
    gap = _finite(extraction_gap_mm)
    if gap < clearance:
        raise ValueError("extraction recipe gap must meet the MR minimum clearance")
    central_min_y = min(p[0] for p in central["outer_polygon_yz_mm"])
    old_length = baseline["geometry"]["lp_length_mm"]
    permitted_end = central_min_y - clearance - translation[1] - baseline["native_geometry"]["lens_thickness_mm"]
    g = baseline["geometry"]
    g["lp_length_mm"] = min(old_length, permitted_end - g["guide_length_mm"] - g["hp_length_mm"])
    end = g["guide_length_mm"] + g["hp_length_mm"] + g["lp_length_mm"]
    if (
        end - baseline["native_geometry"]["lp_aux_axial_inset_mm"]
        <= g["lp_center_mm"] + g["extraction_slit_length_mm"] / 2
    ):
        raise ValueError("MR clearance leaves insufficient LP extraction geometry")
    projection = native_projection(baseline, numerics)
    # Replace the old OA-dependent extension using the actual IP shield exit face.
    shield_outer_y = max(_bounds(s)[4] for e in projection["electrodes"] if e["electrode_id"] == 14 for s in e["solids"])
    exit_face = _point([0, shield_outer_y, 0], rotation, translation)[2]
    old_end = max(p[1] for p in p1["outer_polygon_yz_mm"])
    new_end = exit_face - gap
    for polygon in [p1["outer_polygon_yz_mm"], *[s["polygon_yz_mm"] for s in p1["body_sections"]]]:
        for p in polygon:
            if p[1] == old_end:
                p[1] = new_end
    for slot in p1["rectangular_slots_mm"]:
        if slot[5] == old_end:
            slot[5] = new_end
    p1["extension_to_accelerator_exit"] = {
        "provider": "ion_processor",
        "clearance_mm": gap,
        "exit_support_downstream_z_mm": exit_face,
        "resolved_end_z_mm": new_end,
    }
    geometry.pop("accelerator_component_layout", None)
    configs = {k: source[k] for k in ("source", "acceptance", "diagnostics", "field_diagnostics")}
    configs.update(
        baseline=baseline,
        numerics=numerics,
        native_operating_point=point,
        coordinate_transform=copy.deepcopy(source["coordinate_transform"]),
    )
    return {
        "configs": configs, "geometry": geometry, "projection": projection,
        "before_projection": before_projection,
        "energy_seed": {
            "policy": request["policies"]["energy_adjustment"],
            "formula": ("lift_seed = lift_baseline" if request["policies"]["energy_adjustment"] == "preserve_measured_workpoint"
                        else "lift_seed = lift_baseline + target_Ez_per_q - measured_baseline_mean_Ez_per_q"),
            "baseline_lift_v": old_lift,
            "target_ez_per_q_v": target,
            "measured_baseline_ez_per_q_v": measured,
            "new_lift_v": point["lift_v"],
            "measured_minus_target_ez_per_q_v": measured - target,
            "qualification": ("measured_workpoint_preserved__target_difference_reported_without_acceptance"
                              if request["policies"]["energy_adjustment"] == "preserve_measured_workpoint"
                              else "first_order_seed_only_requires_fresh_IP_flight_no_velocity_scaling"),
        },
        "geometry_changes": {
            "shield_extraction_slit_width_mm": shield_width,
            "shield_extraction_aperture_basis": "source.native_projection/electrodes[electrode_id=14]/cutouts[0]",
            "lp_length_before_mm": old_length,
            "lp_length_after_mm": g["lp_length_mm"],
            "clearance_mm": clearance,
            "extraction_gap_mm": gap,
            "clearance_basis": "/prisms/ground_shields/0/extension_to_accelerator_exit/clearance_mm",
            "clearance_reuse": "MR existing minimum governs LP clearance; recipe gap governs the extraction face",
            "central_shield_min_y_mm": central_min_y,
            "ip_exit_lens_max_y_mm": end + baseline["native_geometry"]["lens_thickness_mm"] + translation[1],
            "p1_extension_end_before_z_mm": old_end,
            "p1_extension_end_after_z_mm": new_end,
            "ip_shield_min_z_mm": exit_face,
        },
    }


def resolve_registered_ion_processor_geometry(design: dict, source: dict, request: dict,
                                              coordinate: dict, authority: dict, old_plan: dict) -> dict:
    """Project physical CSG using the checked plan pose and validate MR field fit."""
    rotation, translation = coordinate["rotation"], coordinate["translation_mm"]
    electrodes = _transform_projection(design["projection"], rotation, translation)
    before = _transform_projection(design["before_projection"], rotation, translation)
    geometry = {
        **design["geometry"],
        "ion_processor_electrodes": electrodes,
    }
    geometry.pop("ion_processor_instance_id", None)
    central = next(s for s in geometry["prism_ground_shields"] if s["station"] == "central_ground_left")
    p1 = next(s for s in geometry["prism_ground_shields"] if s["station"] == "accelerator_exit")
    baseline, point = design["configs"]["baseline"], design["configs"]["native_operating_point"]
    references = request["field_assembly_reference"]
    voltage_projection = references["provider_voltage_projection"]
    if (
        voltage_projection["basis"] != "post_extraction_pulse_held_rf_zero"
        or voltage_projection["evaluated_native_operating_point"] != point
        or voltage_projection["evaluated_baseline_lift_v"] != baseline["electric"]["lift_v"]
        or _finite(voltage_projection["evaluation_time_us"]) < source["native_timing"]["pulse_start_us"]
    ):
        raise ValueError("provider voltage projection differs from prepared seed or pulse phase")
    volts = [_finite(v) for v in voltage_projection["values_v15"]]
    if len(volts) != 15:
        raise ValueError("complete 15-electrode native provider projection required")
    parent = _grid_plan(old_plan["box_mm"], old_plan["pitch_mm"], "grounded_enclosure", old_plan["convergence_v"])
    if authority["boundary_contract"]["box_mm"] != parent["box_mm"]:
        raise ValueError("parent numerical and voltage boundary differ")
    full = [-parent["box_mm"][3], *parent["box_mm"][1:]]
    bounds = [_bounds(s) for e in electrodes for s in e["solids"]]
    fit = all(full[a] <= b[a] and b[a + 3] <= full[a + 3] for b in bounds for a in range(3))
    if not fit:
        raise ValueError("registered IP conductors do not fit MR C0")

    def evidence(items: list) -> list:
        hits = []
        for e in items:
            for s in e["solids"]:
                if s["shape"] != "box":
                    continue
                b = _bounds(s)
                for p in itertools.product(
                    *[[b[a] + (b[a + 3] - b[a]) * u for u in (0.25, 0.5, 0.75)] for a in range(3)]
                ):
                    p = list(p)
                    if any(_inside_body(p, h) for h in e["cutouts"]):
                        continue
                    for shield in (central, p1):
                        if _shield_contains(p, shield):
                            hits.append(
                                {"ip_electrode_id": e["electrode_id"], "mr_electrode_id": shield["id"], "point_mm": p}
                            )
                            break
        return hits

    before_hits, after_hits = evidence(before), evidence(electrodes)
    if after_hits:
        raise ValueError("prepared IP still intersects MR shield CSG samples")
    return {
        "geometry": geometry, "electrodes": electrodes, "volts": volts, "parent": parent, "bounds": bounds,
        "geometry_checks": {
            "c0_domain_fit": fit,
            "before_shield_csg_interior_witnesses": before_hits,
            "after_shield_csg_interior_witnesses": after_hits,
            "scope": "Finite interior witnesses against actual polygon/box slot CSG, not exhaustive clearance or CAD qualification",
        },
    }


def render_detector_geometry(geometry: dict, trajectory: dict) -> tuple[str, dict]:
    """Render the existing detector CSG and numerical registration without I/O."""
    detector = geometry["detector"]["box"]
    span = trajectory["simion"]["detector_pa_span_mm"]
    detector_pitch = trajectory["simion"]["component_mesh_mm_per_gu"]["detector"]
    detector_origin = [(detector[a] + detector[a + 3] - span[a]) / 2 for a in range(3)]
    detector_dimensions = [round(span[a] / detector_pitch[a]) + 1 for a in range(3)]
    if any(abs((detector_dimensions[a] - 1) * detector_pitch[a] - span[a]) > 1e-8 for a in range(3)):
        raise ValueError("detector extent not aligned to declared mesh")
    detector_gem = (
        "pa_define("
        + ",".join(map(str, detector_dimensions))
        + ",planar,none,electrostatic,,"
        + ",".join(map(format_number, detector_pitch))
        + ",surface=fractional)\nlocate("
        + ",".join(format_number(-v) for v in detector_origin)
        + ") { e(1) { "
        + _primitive({"shape": "box", "min_mm": detector[:3], "max_mm": detector[3:]})
        + " } }\n"
    )
    return detector_gem, dict(origin_mm=detector_origin, pitch_mm=detector_pitch,
                              dimensions=detector_dimensions, physical_box_mm=detector,
                              mirror_axes=[], all_metal_electrode_value=1)



def prepare_ion_processor_assembly(
    source: dict, trajectory: dict, request: dict, *, connection: dict, input_paths: list[Path], output_directory: Path,
) -> dict:
    """Validate the actual mechanical boundary before writing any CSG or seed."""
    if output_directory.exists():
        raise FileExistsError(output_directory)
    references = request["field_assembly_reference"]
    authorities = {}
    for name in ("geometry_authority", "voltage_authority", "numerical_plan"):
        verify_record("MR field assembly reference " + name, references[name])
        authorities[name] = _read(Path(references[name]["path"]))
    verify_record("unique provider native drive", references["provider_voltage_projection"]["source_native_drive"])
    composition_plan = request["composition_plan"]
    source_id, target_id = connection["upstream"]["instance_id"], connection["downstream"]["instance_id"]
    if (set(composition_plan["scope"]["instance_ids"]) != {source_id, target_id}
            or composition_plan["scope"]["connection_ids"] != [connection["connection_id"]]):
        raise ValueError("IP/MR mechanical instances differ from the resolved connection")
    pose = resolve_ip_mr_transform(composition_plan, connection)
    coordinate = pose.to_contract()
    design = resolve_ion_processor_design(source, trajectory, request, authorities["geometry_authority"], coordinate,
        extraction_gap_mm=connection["gap_mm"])
    interfaces = {source_id: ip_interface(design["projection"]),
                  target_id: mr_interface(design["geometry"])}
    for instance_id, interface in interfaces.items():
        if composition_plan['components'][instance_id] != interface:
            raise ValueError(f'{instance_id}: resolved mechanical interface differs from frozen parent composition')
    registered = resolve_registered_ion_processor_geometry(
        design, source, request, coordinate, authorities["voltage_authority"], authorities["numerical_plan"])
    geometry, electrodes, volts, parent, bounds = [registered[k] for k in ("geometry", "electrodes", "volts", "parent", "bounds")]
    configs = design["configs"]
    authority, old_plan = authorities["voltage_authority"], authorities["numerical_plan"]
    output_directory.mkdir(parents=True)
    seed = output_directory / "ion_processor_seed"
    seed.mkdir()
    for key, value in configs.items():
        _write(seed / (key + ".json"), value)
    (seed / "processor.gem").write_text(render_gem(design["projection"]), encoding="utf-8", newline="\n")
    _write(output_directory / "assembly_geometry.json", geometry)
    detector_voltage = next(
        v["voltage_v"] for v in authority["component_voltages_v"] if v["component_namespace"] == "detector"
    )
    fields = []
    plans = [("parent", parent)]
    for window in references["refinement_windows"]:
        verify_record("MR refinement numerical reference", window["numerical_plan"])
        old = _read(Path(window["numerical_plan"]["path"]))
        if "crop" in old:
            verify_record("MR full solve numerical reference", window["full_solve_numerical_plan"])
            old = _read(Path(window["full_solve_numerical_plan"]["path"]))
        plans.append(
            (
                window["name"],
                _grid_plan(old["box_mm"], old["pitch_mm"], "x_mirror_five_faces", old_plan["convergence_v"]),
            )
        )
    central_names = [
        name for name, plan in plans if name != "parent" and plan["box_mm"][1] <= min(b[1] for b in bounds)
    ]
    # If the original central window starts downstream of the IP tail, it still
    # owns the MR corridor and provides all five mirror boundary faces.
    if not central_names and len(plans) > 1:
        central_names = [max(plans[1:], key=lambda item: item[1]["box_mm"][3])[0]]
    central_name = central_names[0] if central_names else "parent"
    for name, plan in plans:
        if name not in ("parent", central_name):
            plan["parent_label"] = central_name
        directory = output_directory / name
        directory.mkdir()
        _write(directory / "numerical_plan.json", plan)
        (directory / "assembly.gem").write_text(
            _gem(geometry, electrodes, volts, references["analyzer_electrode_voltages_v"], detector_voltage, plan),
            encoding="utf-8",
            newline="\n",
        )
        fields.append(
            {
                "name": name,
                "gem_path": str((directory / "assembly.gem").resolve()),
                "numerical_plan_path": str((directory / "numerical_plan.json").resolve()),
                "reuse_old_pa": False,
                "grid": {k: plan[k] for k in ("box_mm", "pitch_mm", "dimensions")},
                "active_box_mm": next(
                    (w["active_box_mm"] for w in references["refinement_windows"] if w["name"] == name), None
                ),
                "boundary_parent": plan["parent_label"],
                "boundary_values": "new_parent_dirichlet_required"
                if name != "parent"
                else "five_faces_grounded_x_mirror",
            }
        )
    collision_path = output_directory / "collision.gem"
    collision_path.write_text(
        _gem(
            geometry,
            electrodes,
            volts,
            references["analyzer_electrode_voltages_v"],
            detector_voltage,
            parent,
            occupancy=True,
        ),
        encoding="utf-8",
        newline="\n",
    )
    detector_gem, detector_geometry = render_detector_geometry(geometry, trajectory)
    detector_path = output_directory / "detector.gem"
    detector_path.write_text(detector_gem, encoding="utf-8", newline="\n")
    runtime_geometry = {
        "collision": {
            "gem_path": str(collision_path.resolve()),
            "origin_mm": parent["box_mm"][:3],
            "grid": parent,
            "mirror_axes": ["x"],
            "numerical_boundary_faces_included": False,
            "all_metal_electrode_value": 1,
        },
        "detector": {
            "gem_path": str(detector_path.resolve()),
            **detector_geometry,
        },
    }
    report = {
        "schema_version": 1,
        "role": "mrtof_ion_processor_assembly_preparation",
        "status": "prepared_unvalidated_seed",
        "solver_executed": False,
        "joint_simulation_executed": False,
        "field_qualified": False,
        "old_oa_removed": True,
        "old_oa_field_reuse_allowed": False,
        "historical_exit_state_matches_new_seed": False,
        "source_config_paths": {k: str((seed / (k + ".json")).resolve()) for k in configs},
        "assembly_geometry_path": str((output_directory / "assembly_geometry.json").resolve()),
        "field_plan_path": str((output_directory / "field_assembly_plan.json").resolve()),
        "parent_gem_path": str((output_directory / "parent/assembly.gem").resolve()),
        "assembly_coordinate_transform": coordinate,
        "composition_plan": composition_plan,
        "composition_scope": "IP extraction shield to MR entry frame mechanical boundary only; not whole-instrument electrode binding or qualification",
        "runtime_geometry": runtime_geometry,
        "energy_seed": design["energy_seed"],
        "geometry_changes": design["geometry_changes"],
        "geometry_checks": registered["geometry_checks"],
        "input_identities": [
            {"path": str(p.resolve()), "bytes": p.stat().st_size, "sha256": file_sha256(p)}
            for p in input_paths
        ],
        "required_before_joint_flight": [
            ("Verify prepared IP configuration matches the measured source; retain measured states and complete census"
             if request["policies"]["energy_adjustment"] == "preserve_measured_workpoint"
             else "Fresh IP GEM build/Refine and N100 flight with seed voltage and shortened LP; export actual states preserving full census"),
            "Rebuild C0 and every local field from this assembly; inherit boundaries only from the new parent",
            "Verify field handover guards, collisions, state transfer and instrument clock before joint flight",
            "Match downstream spatial/time response; old OA working point is an initial seed only",
        ],
    }
    _write(
        output_directory / "field_assembly_plan.json",
        {
            "schema_version": 1,
            "role": "mrtof_new_ip_field_assembly_plan",
            "execution_scope": "prepare_only_no_solver",
            "post_extraction_state": "pulse_held_rf_zero",
            "fields": fields,
            "execution_order": ["parent"]
            + ([central_name] if central_name != "parent" else [])
            + [f["name"] for f in fields if f["name"] not in ("parent", central_name)],
            "field_priority": "local windows in frozen reference order then new parent",
            "collision_authority": "assembly_geometry.json physical CSG; numerical faces are not metal",
            "old_oa_pa_or_boundary_reuse": False,
            "source_config_paths": report["source_config_paths"],
            "runtime_geometry": runtime_geometry,
            "official_reference": {
                "title": "SIMION GEM Geometry File: cylinder3d and CSG",
                "url": "https://simion.com/info/gem_geometry_file.html",
                "accessed": "2026-10-16",
                "compatibility": "cylinder3d supported since 8.2EA-20170324; target SIMION 2020",
                "usage": "Project CSG input preparation only, no vendor execution or qualification",
            },
        },
    )
    _write(output_directory / "assembly_preparation.json", report)
    return {"report": report, "seed_configs": configs}
