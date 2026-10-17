"""Prepare fresh IP scientific seeds and full MR CSG; never build PA or fly ions."""

from __future__ import annotations

import copy
import itertools
import json
import math
import re
import struct
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import verify_record
from common.simion.gem_primitives import centered_box3d, format_number
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection, render_gem
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import _analyzer_geometry_lines


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite numeric assembly input required")
    return float(value)


def _point(point: list, rotation: list, translation: list) -> list:
    return [sum(a * b for a, b in zip(row, point)) + shift for row, shift in zip(rotation, translation)]


def transform_shape(shape: dict, rotation: list, translation: list) -> dict:
    """Preserve boxes and circular holes under an axis permutation rigid pose."""
    if any(sorted(abs(v) for v in row) != [0, 0, 1] for row in rotation):
        raise ValueError("assembly CSG requires axis permutation rotation")
    if shape["shape"] == "box":
        vertices = [
            _point(list(p), rotation, translation) for p in itertools.product(*zip(shape["min_mm"], shape["max_mm"]))
        ]
        return {
            "shape": "box",
            "min_mm": [min(p[a] for p in vertices) for a in range(3)],
            "max_mm": [max(p[a] for p in vertices) for a in range(3)],
        }
    if shape["shape"] != "cylinder_x":
        raise ValueError("unsupported provider primitive")
    ends = [
        _point([x, shape["center_y_mm"], shape["center_z_mm"]], rotation, translation)
        for x in (shape["x_min_mm"], shape["x_max_mm"])
    ]
    return {"shape": "cylinder3d", "endpoints_mm": ends, "radius_mm": shape["radius_mm"]}


def _bounds(shape: dict) -> list:
    if shape["shape"] == "box":
        return shape["min_mm"] + shape["max_mm"]
    ends, r = shape["endpoints_mm"], shape["radius_mm"]
    return [min(p[a] for p in ends) - (r if ends[0][a] == ends[1][a] else 0) for a in range(3)] + [
        max(p[a] for p in ends) + (r if ends[0][a] == ends[1][a] else 0) for a in range(3)
    ]


def _primitive(shape: dict) -> str:
    if shape["shape"] == "box":
        low, high = shape["min_mm"], shape["max_mm"]
        return centered_box3d(*[(a + b) / 2 for a, b in zip(low, high)], *[b - a for a, b in zip(low, high)])
    return (
        "cylinder3d("
        + ",".join(format_number(v) for p in shape["endpoints_mm"] for v in p)
        + ","
        + format_number(shape["radius_mm"])
        + ")"
    )


def _polygon(point: list, polygon: list) -> bool:
    y, z = point[1:]
    inside = False
    for (a, b), (c, d) in zip(polygon, polygon[1:] + polygon[:1]):
        if (b > z) != (d > z) and y < (c - a) * (z - b) / (d - b) + a:
            inside = not inside
    return inside


def _inside_body(point: list, body: dict) -> bool:
    if "polygon_yz_mm" in body:
        return body["x"][0] < point[0] < body["x"][1] and _polygon(point, body["polygon_yz_mm"])
    b = body.get("box", body.get("min_mm", []) + body.get("max_mm", []))
    return len(b) == 6 and all(b[a] < point[a] < b[a + 3] for a in range(3))


def _shield_contains(point: list, shield: dict) -> bool:
    if not any(_inside_body(point, part) for part in shield["body_sections"]):
        return False
    if _inside_body(point, {"x": shield["x"], "polygon_yz_mm": shield["prism_clearance_polygon_yz_mm"]}):
        return False
    return not any(_inside_body(point, {"box": b}) for b in shield.get("rectangular_slots_mm", []))


def _transform_projection(projection: dict, rotation: list, translation: list) -> list:
    return [
        {
            "namespace": "ion_processor",
            "electrode_id": e["electrode_id"],
            "assembly_id": 100 + e["electrode_id"],
            "name": e["name"],
            **{k: [transform_shape(s, rotation, translation) for s in e[k]] for k in ("solids", "cutouts")},
        }
        for e in projection["electrodes"]
    ]


def _grid_plan(box: list, pitch: list, boundary: str, convergence: float) -> dict:
    pitch = [_finite(v) for v in pitch]
    if any(v <= 0 or abs(v / 0.01 - round(v / 0.01)) > 1e-8 for v in pitch):
        raise ValueError("MR grid must use positive 0.01 mm quanta")
    dimensions = [round((box[a + 3] - box[a]) / pitch[a]) + 1 for a in range(3)]
    if any(abs((dimensions[a] - 1) * pitch[a] - (box[a + 3] - box[a])) > 1e-8 for a in range(3)):
        raise ValueError("assembly domain must align to its numerical grid")
    return {
        "box_mm": box,
        "pitch_mm": pitch,
        "dimensions": dimensions,
        "mirror_axes": ["x"],
        "surface": "fractional",
        "boundary_mode": boundary,
        "convergence_v": convergence,
        "ordinary_static_pa": True,
        "parent_label": None if boundary == "grounded_enclosure" else "parent",
    }


def extend_fine_z_domain(grid: dict, active: list, update: dict, parent_grid: dict) -> tuple[dict, list]:
    """Derive one lower-z extension without changing any other numerical coordinate."""
    if not isinstance(update, dict) or set(update) != {"solve_z_min_mm", "active_z_min_mm"}:
        raise ValueError("IP fine extension requires only solve_z_min_mm and active_z_min_mm")
    lower, route = (_finite(update[key]) for key in ("solve_z_min_mm", "active_z_min_mm"))
    old_lower = grid["origin_mm"][2]
    if not lower < old_lower or not route < active[2][0] or not lower < route:
        raise ValueError("IP fine extension must extend both lower-z bounds downward with a halo")
    result = copy.deepcopy(grid)
    steps = (old_lower - lower) / grid["pitch_mm"][2]
    if not math.isclose(steps, round(steps), abs_tol=1e-8, rel_tol=0):
        raise ValueError("IP fine extension must align with its unchanged z pitch")
    result["origin_mm"][2] = lower
    result["dimensions"][2] += round(steps)
    coverage = copy.deepcopy(active)
    coverage[2][0] = route
    if (lower < parent_grid["origin_mm"][2]
            or route - lower < grid["pitch_mm"][2]):
        raise ValueError("IP fine extension exceeds its unchanged parent or lacks a gradient halo")
    return result, coverage


def _gem(
    geometry: dict,
    electrodes: list,
    voltages: list,
    analyzer_voltages: list,
    detector_voltage: float,
    plan: dict,
    *,
    occupancy: bool = False,
) -> str:
    box = plan["box_mm"]
    lines = [
        "; Fresh IP replacement assembly; Refine required; no reused OA fields.",
        "pa_define("
        + ",".join(map(str, plan["dimensions"]))
        + ",planar,x,electrostatic,,"
        + ",".join(map(format_number, plan["pitch_mm"]))
        + ",surface=fractional)",
        "locate(" + ",".join(format_number(-v) for v in box[:3]) + ") {",
    ]
    for line in _analyzer_geometry_lines(geometry):
        lines.append(
            re.sub(r"\be\((\d+)\)", lambda m: "e(" + format(analyzer_voltages[int(m[1]) - 1], ".17g") + ")", line)
        )
    for electrode, voltage in zip(electrodes, voltages):
        lines.append(
            "e(" + format(voltage, ".17g") + ") { ; namespace=ion_processor id=" + str(electrode["electrode_id"])
        )
        for solid in electrode["solids"]:
            lines.extend(["fill {", "within { " + _primitive(solid) + " }"])
            lines.extend("notin_inside { " + _primitive(hole) + " }" for hole in electrode["cutouts"])
            lines.append("}")
        lines.append("}")
    d = geometry["detector"]["box"]
    lines.append(
        "e("
        + format(detector_voltage, ".17g")
        + ") { "
        + _primitive({"shape": "box", "min_mm": d[:3], "max_mm": d[3:]})
        + " }"
    )
    if plan["boundary_mode"] == "grounded_enclosure" and not occupancy:
        for axis, side in ((0, 1), (1, 0), (1, 1), (2, 0), (2, 1)):
            face = list(box)
            face[axis] = face[axis + 3] = box[axis + 3 * side]
            lines.append("e(0) { " + _primitive({"shape": "box", "min_mm": face[:3], "max_mm": face[3:]}) + " }")
    text = "\n".join([*lines, "}", ""])
    return re.sub(r"\be\([^)]*\)", "e(1)", text) if occupancy else text


def derive_lift_seed(source: dict, request: dict) -> float:
    """First-order editable seed only; measured trajectories are never rescaled."""
    lift = _finite(source["native_operating_point"]["lift_v"])
    target = _finite(request["target"]["axial_energy_per_charge_v"])
    measured = _finite(request["current_measured_baseline"]["directional_energy"]["z"]["mean"])
    result = lift + target - measured
    if min(lift, target, measured, result) <= 0:
        raise ValueError("positive lift and axial energies required")
    return result


def prepare_ion_processor_assembly(
    source_resolved_model: Path, reference_trajectory: Path, matching_request_resolved: Path, output_directory: Path
) -> dict:
    """Write new editable seeds and concrete C0/local GEM inputs without solving."""
    if output_directory.exists():
        raise FileExistsError(output_directory)
    source, trajectory, request = map(_read, (source_resolved_model, reference_trajectory, matching_request_resolved))
    target = _finite(request["target"]["axial_energy_per_charge_v"])
    measured = _finite(request["current_measured_baseline"]["directional_energy"]["z"]["mean"])
    if (
        target <= 0
        or measured <= 0
        or request["requirements"]["energy_definition"] != "exit_axial_kinetic_energy_per_charge"
    ):
        raise ValueError("positive measured and target axial energy per charge required")
    references = request["field_assembly_reference"]
    authorities = {}
    for name in ("geometry_authority", "voltage_authority", "numerical_plan"):
        verify_record("MR field assembly reference " + name, references[name])
        authorities[name] = _read(Path(references[name]["path"]))
    geometry, authority, old_plan = [
        copy.deepcopy(authorities[n]) for n in ("geometry_authority", "voltage_authority", "numerical_plan")
    ]
    if (
        geometry["frame_id"] != request["target"]["frame_id"]
        or trajectory["coordinate_system"]["frame_id"] != geometry["frame_id"]
    ):
        raise ValueError("MR assembly reference frame differs")
    baseline, numerics = copy.deepcopy(source["baseline"]), copy.deepcopy(source["numerics"])
    point = copy.deepcopy(source["native_operating_point"])
    old_lift = _finite(point["lift_v"])
    if baseline["electric"]["lift_v"] != old_lift:
        raise ValueError("provider native and baseline lift bindings differ")
    point["lift_v"] = derive_lift_seed(source, request)
    if point["lift_v"] <= 0:
        raise ValueError("derived lift seed must remain positive")
    baseline["electric"]["lift_v"] = point["lift_v"]
    transform = source["coordinate_transform"]
    rigid = request["rigid_transform"]
    if rigid["rotation"] != [[1, 0, 0], [0, 1, 0], [0, 0, 1]] or transform["to_frame_id"] != rigid["from_frame_id"]:
        raise ValueError("IP world registration must preserve the current matched axes")
    rotation = transform["rotation"]
    translation = [a + b for a, b in zip(transform["translation_mm"], rigid["translation_mm"])]
    coordinate = {**copy.deepcopy(transform), "to_frame_id": rigid["to_frame_id"], "translation_mm": translation}
    before = _transform_projection(native_projection(baseline, numerics), rotation, translation)
    central = next(s for s in geometry["prism_ground_shields"] if s["station"] == "central_ground_left")
    p1 = next(s for s in geometry["prism_ground_shields"] if s["station"] == "accelerator_exit")
    clearance = _finite(trajectory["prisms"]["ground_shields"][0]["extension_to_accelerator_exit"]["clearance_mm"])
    if clearance <= 0 or rotation != [[0, 0, -1], [1, 0, 0], [0, -1, 0]]:
        raise ValueError("positive existing P1 clearance and current IP native orientation required")
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
    electrodes = _transform_projection(projection, rotation, translation)
    # Replace the old OA-dependent extension using the actual IP shield exit face.
    exit_face = min(_bounds(s)[2] for e in electrodes if e["electrode_id"] == 14 for s in e["solids"])
    old_end = max(p[1] for p in p1["outer_polygon_yz_mm"])
    new_end = exit_face - clearance
    for polygon in [p1["outer_polygon_yz_mm"], *[s["polygon_yz_mm"] for s in p1["body_sections"]]]:
        for p in polygon:
            if p[1] == old_end:
                p[1] = new_end
    for slot in p1["rectangular_slots_mm"]:
        if slot[5] == old_end:
            slot[5] = new_end
    p1["extension_to_accelerator_exit"] = {
        "provider": "ion_processor",
        "clearance_mm": clearance,
        "exit_support_downstream_z_mm": exit_face,
        "resolved_end_z_mm": new_end,
    }
    geometry.pop("accelerator_component_layout", None)
    geometry["ion_processor_electrodes"] = electrodes
    voltage_projection = references["provider_voltage_projection"]
    verify_record("unique provider native drive", voltage_projection["source_native_drive"])
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
    output_directory.mkdir(parents=True)
    seed = output_directory / "ion_processor_seed"
    seed.mkdir()
    configs = {k: source[k] for k in ("source", "acceptance", "diagnostics", "field_diagnostics")}
    configs.update(
        baseline=baseline,
        numerics=numerics,
        native_operating_point=point,
        coordinate_transform=copy.deepcopy(source["coordinate_transform"]),
    )
    for key, value in configs.items():
        _write(seed / (key + ".json"), value)
    (seed / "processor.gem").write_text(render_gem(baseline, numerics), encoding="utf-8", newline="\n")
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
            "origin_mm": detector_origin,
            "pitch_mm": detector_pitch,
            "dimensions": detector_dimensions,
            "physical_box_mm": detector,
            "mirror_axes": [],
            "all_metal_electrode_value": 1,
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
        "runtime_geometry": runtime_geometry,
        "energy_seed": {
            "formula": "lift_seed = lift_baseline + target_Ez_per_q - measured_baseline_mean_Ez_per_q",
            "baseline_lift_v": old_lift,
            "target_ez_per_q_v": target,
            "measured_baseline_ez_per_q_v": measured,
            "new_lift_v": point["lift_v"],
            "qualification": "first_order_seed_only_requires_fresh_IP_flight_no_velocity_scaling",
        },
        "geometry_changes": {
            "lp_length_before_mm": old_length,
            "lp_length_after_mm": g["lp_length_mm"],
            "clearance_mm": clearance,
            "clearance_basis": "/prisms/ground_shields/0/extension_to_accelerator_exit/clearance_mm",
            "clearance_reuse": "MR existing accelerator-to-shield minimum gap applied to the new accelerator end face",
            "central_shield_min_y_mm": central_min_y,
            "ip_exit_lens_max_y_mm": end + baseline["native_geometry"]["lens_thickness_mm"] + translation[1],
            "p1_extension_end_before_z_mm": old_end,
            "p1_extension_end_after_z_mm": new_end,
            "ip_shield_min_z_mm": exit_face,
        },
        "geometry_checks": {
            "c0_domain_fit": fit,
            "before_shield_csg_interior_witnesses": before_hits,
            "after_shield_csg_interior_witnesses": after_hits,
            "scope": "Finite interior witnesses against actual polygon/box slot CSG, not exhaustive clearance or CAD qualification",
        },
        "namespace_map": [
            {
                "provider_electrode_id": e["electrode_id"],
                "assembly_id": e["assembly_id"],
                "name": e["name"],
                "voltage_v": v,
            }
            for e, v in zip(electrodes, volts)
        ],
        "input_identities": [
            {"path": str(p.resolve()), "bytes": p.stat().st_size, "sha256": file_sha256(p)}
            for p in (source_resolved_model, reference_trajectory, matching_request_resolved)
        ],
        "required_before_joint_flight": [
            "Fresh IP GEM build/Refine and N100 flight with seed voltage and shortened LP; export actual states preserving full census",
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
    return report


def ordinary_pa_file_bytes(dimensions: list[int], pitch_mm: list[float]) -> int:
    """Forecast SIMION's ordinary GEM-save header and double node payload.

    SIMION 2020 lib/python/SIMION/PA.py load/save: mode -1 stores the 32-byte
    fixed header and implicit unit pitch. Nonunit pitch selects mode -2 and
    adds three double pitches (56-byte header). This is not a PA parser and
    does not broaden the mode -2-only affine-composition consumer.
    """
    header_bytes = struct.calcsize("<iidiiii")
    if pitch_mm != [1, 1, 1]:
        header_bytes += 3 * struct.calcsize("<d")
    return header_bytes + math.prod(dimensions) * struct.calcsize("<d")


def compile_materializable_fields(request: dict) -> dict:
    """Project a sealed IP assembly into the existing native-provider build plan.

    All PA creation/Refine remains owned by run_native_static_field_provider.ps1.
    The extra fine occupancy instance preserves IP thin auxiliaries without
    imposing their spacing on the complete 800-mm MR enclosure.
    """
    from common.contracts.verify_run_manifest import record_path
    from common.contracts.write_run_manifest import file_record
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import (
        _native_active_box,
        resolve_native_refine_numerics,
    )

    allowed = {
        "schema_version",
        "role",
        "run_id",
        "replacement_assembly_path",
        "replacement_assembly_manifest",
        "numerical_contract_path",
        "ion_processor_local_grid",
        "surface_allowance_bytes_per_level",
    }
    if (
        set(request) != allowed
        or request["schema_version"] != 1
        or request["role"] != "mrtof_native_static_field_provider_request"
    ):
        raise ValueError("replacement field request requires its explicit closed contract")
    run_id = request["run_id"]
    if not isinstance(run_id, str) or not run_id or run_id in (".", "..") or any(c in run_id for c in "/\\"):
        raise ValueError("new replacement field run_id required")
    manifest_path = Path(request["replacement_assembly_manifest"]).resolve()
    owner = manifest_path.parent
    manifest = _read(manifest_path)
    if manifest.get("status") != "success" or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof":
        raise ValueError("replacement assembly must belong to a successful sealed MR preparation")
    inputs = {
        "replacement_manifest": str(manifest_path),
        "replacement_emitter": str(Path(__file__).resolve()),
        "numerical_contract": str(Path(request["numerical_contract_path"]).resolve()),
    }

    sealed_records = [*manifest.get("inputs", {}).values(), *manifest["outputs"]]
    preparation_path = owner / "results/accelerator_interface_preparation.json"
    preparation_records = [r for r in sealed_records if record_path(r, base_dir=owner) == preparation_path]
    if len(preparation_records) != 1:
        raise ValueError("sealed accelerator preparation receipt required")
    verify_record("sealed accelerator preparation", preparation_records[0], base_dir=owner)
    sealed_records.extend(_read(preparation_path)["inputs"].values())

    def bound(path: Path, key: str) -> dict:
        path = path.resolve()
        candidates = [r for r in sealed_records if record_path(r, base_dir=owner) == path]
        if len(candidates) == 0:
            raise ValueError("replacement manifest does not bind " + str(path))
        for record in candidates:
            verify_record("sealed replacement " + key, record, base_dir=owner)
        inputs[key] = str(path)
        return _read(path)

    receipt_path = Path(request["replacement_assembly_path"]).resolve()
    receipt = bound(receipt_path, "replacement_assembly")
    geometry = bound(Path(receipt["assembly_geometry_path"]), "replacement_geometry")
    authored_plan = bound(Path(receipt["field_plan_path"]), "replacement_field_plan")
    if not receipt.get("old_oa_removed") or receipt.get("old_oa_field_reuse_allowed") is not False:
        raise ValueError("replacement must exclude the old OA and its fields")
    matching_path = Path(receipt["input_identities"][-1]["path"])
    matching = bound(matching_path, "replacement_matching_request")
    references = matching["field_assembly_reference"]
    values = references["analyzer_electrode_voltages_v"]
    voltage = references["provider_voltage_projection"]
    if len(values) != 20 or len(voltage["values_v15"]) != 15:
        raise ValueError("complete MR20 and IP15 frozen voltage projections required")
    values = [_finite(v) for v in values]
    provider_values = [_finite(v) for v in voltage["values_v15"]]
    for index, identity in enumerate(receipt["input_identities"]):
        verify_record("assembly input identity", identity)
        inputs["replacement_source_" + str(index)] = identity["path"]
    authority = copy.deepcopy(bound(Path(references["voltage_authority"]["path"]), "replacement_original_authority"))
    authority.pop("frozen_gem_equal", None)
    authority["analyzer_electrode_voltages_v"] = values
    detector_voltage = next(
        v["voltage_v"] for v in authority["component_voltages_v"] if v["component_namespace"] == "detector"
    )
    authority["component_voltages_v"] = [
        {"component_namespace": "ion_processor", "component_electrode_id": i + 1, "voltage_v": v}
        for i, v in enumerate(provider_values)
    ] + [{"component_namespace": "detector", "component_electrode_id": 25, "voltage_v": detector_voltage}]
    authority["assembly"] = {
        "accelerator_provider": "dual_pressure_rectilinear_ion_processor",
        "assembly_scope": "full_c0_ion_processor_replacement",
        "detector": geometry["detector"],
        "ion_processor_registration": receipt["assembly_coordinate_transform"],
        "ion_processor_electrodes": geometry["ion_processor_electrodes"],
        "post_extraction_state": "pulse_held_rf_zero",
        "replacement_assembly": file_record(receipt_path),
        "replacement_assembly_manifest": file_record(manifest_path),
        "native_operating_point": voltage["evaluated_native_operating_point"],
    }
    numerical = _read(Path(request["numerical_contract_path"]))
    numerics = resolve_native_refine_numerics(numerical)
    allowance = request["surface_allowance_bytes_per_level"]
    if type(allowance) is not int or allowance <= 0:
        raise ValueError("explicit positive fractional surface forecast required")
    local_grid = request["ion_processor_local_grid"]
    if set(local_grid) != {"box_mm", "pitch_mm", "active_box_mm"}:
        raise ValueError("explicit IP local grid and active box required")
    fine = _grid_plan(local_grid["box_mm"], local_grid["pitch_mm"], "x_mirror_five_faces", numerics["convergence_v"])
    if fine["box_mm"][0] != 0:
        raise ValueError("IP fine domain requires the exact x symmetry plane")
    _native_active_box(
        local_grid["active_box_mm"],
        {
            "origin_mm": fine["box_mm"][:3],
            "pitch_mm": fine["pitch_mm"],
            "dimensions": fine["dimensions"],
            "symmetry": "x",
        },
    )
    # Require at least two complete intervals across every finite metal thickness
    # and complete domain support for all provider solids, not only the beam ray.
    for electrode in geometry["ion_processor_electrodes"]:
        for solid in electrode["solids"]:
            box = _bounds(solid)
            for axis in range(3):
                low, high = (0, max(abs(box[0]), abs(box[3]))) if axis == 0 else (box[axis], box[axis + 3])
                if low < fine["box_mm"][axis] or high > fine["box_mm"][axis + 3]:
                    raise ValueError("IP fine domain misses a native conductor")
                thickness = box[axis + 3] - box[axis]
                if thickness > 1e-10 and thickness < 2 * fine["pitch_mm"][axis] - 1e-10:
                    raise ValueError("IP fine grid under-resolves a native conductor thickness")
    parent_original = bound(Path(references["numerical_plan"]["path"]), "replacement_parent_reference_plan")
    originals = {"parent": parent_original}
    for index, window in enumerate(references["refinement_windows"]):
        identity = window.get("full_solve_numerical_plan", window["numerical_plan"])
        originals[window["name"]] = bound(Path(identity["path"]), "replacement_window_reference_" + str(index))
    levels = {}
    authored = authored_plan["fields"]
    fields = [
        (f["name"], bound(Path(f["numerical_plan_path"]), "replacement_grid_" + str(i)), f.get("active_box_mm"))
        for i, f in enumerate(authored)
    ]
    fields.append(("ion_processor_local", fine, local_grid["active_box_mm"]))
    for name, grid, active in fields:
        original = originals.get(name, parent_original)
        if original["resource_limits"]["automatic_retry_count"] != 0:
            raise ValueError("replacement field builds require no automatic retry")
        grid = copy.deepcopy(grid)
        if name == "ion_processor_local":
            grid["parent_label"] = "parent"
        size = ordinary_pa_file_bytes(grid["dimensions"], grid["pitch_mm"])
        commitment = math.ceil(size * 1.05) + allowance + 16 * 1024**2
        level = dict(
            grid,
            **numerics,
            numerical_contract_path=inputs["numerical_contract"],
            resource_budget=copy.deepcopy(original["resource_budget"]),
            resource_limits=copy.deepcopy(original["resource_limits"]),
            committed_new_bytes=commitment,
            final_retained_estimate_bytes=commitment,
            capacity_basis={
                "pa_node_bytes": size,
                "fractional_surface_allowance_bytes": allowance,
                "allowance": "5% PA + explicit surface forecast + 16MiB evidence; no old PA copies",
            },
            gem=_gem(geometry, geometry["ion_processor_electrodes"], provider_values, values, detector_voltage, grid),
            geometry_report={
                "status": "prepared",
                "accelerator_provider": "dual_pressure_rectilinear_ion_processor",
                "full_c0_new_assembly": True,
            },
        )
        if name != "parent":
            level.update(name=name, active_box_mm=active)
        levels[name] = level
    for name, level in levels.items():
        if name == "parent":
            continue
        parent = levels[level["parent_label"]]
        if any(
            level["box_mm"][a] < parent["box_mm"][a] or level["box_mm"][a + 3] > parent["box_mm"][a + 3]
            for a in range(3)
        ):
            raise ValueError("new local solve outside its new parent")

    def occupancy(grid: dict) -> dict:
        size = ordinary_pa_file_bytes(grid["dimensions"], grid["pitch_mm"])
        return dict(
            origin_mm=grid["box_mm"][:3],
            pitch_mm=grid["pitch_mm"],
            dimensions=grid["dimensions"],
            symmetry="x",
            pa_bytes=size,
            committed_new_bytes=size + allowance + 16 * 1024**2,
            surface_allowance_bytes=allowance,
            gem=_gem(
                geometry,
                geometry["ion_processor_electrodes"],
                provider_values,
                values,
                detector_voltage,
                grid,
                occupancy=True,
            ),
            refine_performed=False,
            fast_adjust_performed=False,
            occupancy_geometry="same frozen resolved_geometry.json; all native provider solids and holes retained",
        )

    collision = occupancy(levels["parent"])
    ip_collision = occupancy(fine)
    detector = copy.deepcopy(receipt["runtime_geometry"]["detector"])
    bound(Path(detector["gem_path"]), "replacement_detector_gem") if Path(
        detector["gem_path"]
    ).suffix == ".json" else None
    detector_source = Path(detector["gem_path"])
    # GEM is sealed text rather than JSON.
    records = [r for r in manifest["outputs"] if record_path(r, base_dir=owner) == detector_source.resolve()]
    if not records:
        raise ValueError("sealed detector GEM missing")
    verify_record("sealed detector GEM", records[0], base_dir=owner)
    inputs["replacement_detector_gem"] = str(detector_source)
    detector.update(
        gem=detector_source.read_text(encoding="utf-8"),
        pa_bytes=ordinary_pa_file_bytes(detector["dimensions"], detector["pitch_mm"]),
    )
    detector["committed_new_bytes"] = detector["pa_bytes"] + allowance + 16 * 1024**2
    order = [*authored_plan["execution_order"], "ion_processor_local"]
    window_labels = ["ion_processor_local"] + [f["name"] for f in authored if f["name"] != "parent"]
    retained = sum(l["final_retained_estimate_bytes"] for l in levels.values()) + sum(
        x["committed_new_bytes"] for x in (collision, ip_collision, detector)
    )
    return {
        "schema_version": 1,
        "role": "mrtof_native_static_field_provider_plan",
        "operation": "refine",
        "run_id": run_id,
        "project": "parallel_mirror_dual_stripe_mr_tof",
        "accelerator_provider": "dual_pressure_rectilinear_ion_processor",
        "assembly_scope": "full_c0_ion_processor_replacement",
        "replacement_assembly": file_record(receipt_path),
        "inputs": inputs,
        "protected_paths": [str(owner)],
        "candidate_authority": authority,
        "resolved_geometry": geometry,
        "levels": levels,
        "window_labels": window_labels,
        "execution_order": order,
        "collision_instances": [],
        "collision_build": collision,
        "ip_collision_build": ip_collision,
        "detector_build": detector,
        "committed_new_bytes": retained,
        "final_retained_estimate_bytes": retained,
        **numerics,
        "refine_options": {"convergence": numerics["convergence_v"]},
        "automatic_retry_count": 0,
        "fly_authorized": False,
        "qualification_passed": False,
        "grid_generation": {"spacing_quantum_mm": 0.01},
        "official_sources": authored_plan["official_reference"],
        "field_priority": window_labels,
    }
