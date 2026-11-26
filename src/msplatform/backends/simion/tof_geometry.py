"""SIMION placements and explicit legacy native labels over neutral TOF geometry."""
from __future__ import annotations
import math
from typing import Any
from msplatform.components.single_reflection_oa_tof.geometry_contract import resolve_electrode_geometry
from msplatform.components.single_reflection_tof.geometry import resolve_downstream_geometry

def derive_simion_instances(*, geometry: dict[str, Any], coordinate: dict[str, Any],
                            build: dict[str, Any], marker: dict[str, Any],
                            physical_detector: dict[str, Any], include_accelerator: bool = True) -> list[dict[str, Any]]:
    """Project native geometry domains without a particle source or field samples."""
    detector_radius = physical_detector["radius_mm"]
    detector_half = detector_radius + build["detector"]["margin_xy_mm"]
    back_cells = physical_detector["back_cells"]
    front_cells = physical_detector["front_cells"]

    instances = [
        {"role": "flight_tube_shield", "workbench_index": 1, "priority_number": 1, "name": "flight_tube_ground.pa0", "x_mm": coordinate["reflectron_axis"][0], "y_mm": coordinate["reflectron_axis"][1], "z_mm": geometry["shield_outer_z_min"], "az_deg": -90.0,
         "nx": math.ceil((geometry["L_flight"] - geometry["shield_outer_z_min"]) / build["flight_tube"]["cell_axial_mm"]) + 1,
         "ny": math.ceil((geometry["flight_tube_r"] + geometry["flight_tube_wall"]) / build["flight_tube"]["cell_radial_mm"]) + 1, "nz": 1, "cell_mm": build["flight_tube"]["cell_axial_mm"]},
        {"role": "reflectron", "workbench_index": 2, "priority_number": 2, "name": "reflectron.pa0", "x_mm": coordinate["reflectron_axis"][0], "y_mm": coordinate["reflectron_axis"][1], "z_mm": geometry["L_flight"], "az_deg": -90.0,
         "nx": math.ceil((geometry["L_reflectron"] + geometry["ring_thickness"] + geometry["shield_axial_gap"] + geometry["shield_endcap_thickness"]) / build["reflectron"]["cell_axial_mm"]) + 1,
         "ny": math.ceil((geometry["flight_tube_r"] + geometry["flight_tube_wall"]) / build["reflectron"]["cell_radial_mm"]) + 1, "nz": 1, "cell_mm": build["reflectron"]["cell_axial_mm"]},
        {"role": "detector", "workbench_index": 4, "priority_number": 4, "name": "detector_ground.pa0", "x_mm": coordinate["detector_x"] - detector_half, "y_mm": -detector_half,
         "z_mm": marker["active_plane_z_mm"] - back_cells * marker["cell_z_mm"], "az_deg": 0.0,
         # Match simion/workbench/build_detector_variant.lua at half-cell ties.
         "nx": math.floor(2 * detector_half / marker["cell_xy_mm"] + 0.5) + 1,
         "ny": math.floor(2 * detector_half / marker["cell_xy_mm"] + 0.5) + 1,
         "nz": back_cells + front_cells + 1,
         "cell_mm": marker["cell_xy_mm"]},
    ]

    if include_accelerator:
        accelerator_half = geometry["accelerator_bore_half"] + geometry["accelerator_ring_width"] + geometry["accelerator_insulation_gap"] + geometry["accelerator_shield_wall"]
        accelerator_local_z_min = -geometry["accelerator_repeller_thickness"] - geometry["accelerator_rear_clearance"] - geometry["accelerator_shield_wall"]
        accelerator_local_z_max = geometry["L_accel"] + geometry["accelerator_front_vacuum_margin"]
        instances.insert(2,
            {"role": "accelerator", "workbench_index": 3, "priority_number": 3, "name": "accelerator.pa0", "x_mm": coordinate["accelerator_axis_x"] - accelerator_half, "y_mm": -accelerator_half,
         "z_mm": geometry["accelerator_repeller_z"] + accelerator_local_z_min, "az_deg": 0.0,
         "nx": round(2 * accelerator_half / build["accelerator"]["cell_xy_mm"]) + 1,
         "ny": round(2 * accelerator_half / build["accelerator"]["cell_xy_mm"]) + 1,
         "nz": round((accelerator_local_z_max - accelerator_local_z_min) / build["accelerator"]["cell_z_mm"]) + 1,
         "cell_mm": build["accelerator"]["cell_xy_mm"]})
    instances[-1]["physical_back_cells"] = back_cells
    instances[-1]["physical_front_cells"] = front_cells
    return instances


def derive_simion_geometry(
    *, geometry: dict[str, Any], coordinate: dict[str, Any],
    build: dict[str, Any], marker: dict[str, Any], source: dict[str, Any],
    physical_detector: dict[str, Any],
) -> dict[str, Any]:
    """Derive provider-local PA placements and samples from the final design.

    These placements map native PA domains into oatof_global; cross-component
    assembly transforms are applied separately by the consuming integration.
    """
    instances = derive_simion_instances(geometry=geometry, coordinate=coordinate, build=build, marker=marker, physical_detector=physical_detector)

    return {
        "simion_instances": instances,
        "field_sample_points_mm": {
            "source_center": [coordinate["accelerator_axis_x"], 0.0, source["center_z_mm"]],
            "accelerator_mid": [coordinate["accelerator_axis_x"], 0.0, (geometry["accelerator_grid1_z"] + geometry["accelerator_grid2_z"]) / 2],
            "accelerator_exit": [coordinate["accelerator_axis_x"], 0.0, geometry["accelerator_grid2_z"] - build["accelerator"]["cell_z_mm"]],
            "drift_mid": [coordinate["reflectron_axis"][0], coordinate["reflectron_axis"][1], (marker["active_plane_z_mm"] + geometry["L_flight"]) / 2],
            "reflectron_stage1": [coordinate["reflectron_axis"][0], coordinate["reflectron_axis"][1], geometry["L_flight"] + geometry["L_stage1"] / 2],
            "reflectron_stage2": [coordinate["reflectron_axis"][0], coordinate["reflectron_axis"][1], geometry["L_flight"] + geometry["L_stage1"] + geometry["L_stage2"] / 2],
        },
    }

def resolve_physical_geometry(
    contract: dict[str, Any], *, accelerator_projection: Any = None,
) -> dict[str, Any]:
    """Keep the explicit legacy physical/native projection and label protocol.

    Physics and potentials come from the one neutral resolver. Only this adapter
    allocates legacy IDs and requires the numerical SIMION detector marker.
    """
    neutral = resolve_electrode_geometry(contract, accelerator_projection=accelerator_projection)
    return _native_physical_projection(neutral, contract["simion_detector_marker"], include_accelerator=True)


def resolve_split_physical_geometry(contract: dict[str, Any]) -> dict[str, Any]:
    """Project only the independent TOF physical members to SIMION labels."""
    neutral = resolve_downstream_geometry(contract["geometry_mm"], contract["coordinate_convention"],
                                          contract["rings"], contract["electrodes_v"])
    neutral["local_frame_id"] = contract["local_frame_id"]
    return _native_physical_projection(neutral, contract["simion_detector_marker"], include_accelerator=False)


def _native_physical_projection(neutral, marker, *, include_accelerator):
    bodies = neutral["electrodes"]
    ids = {body["role"]: index for index, body in enumerate(bodies, 1)}
    objects = [dict(component_electrode_id=ids[body["role"]], role=body["role"],
                    electrical_group_id=1 if body["grounded"] else ids[body["role"]],
                    geometry=body["geometry"]) for body in bodies]
    oa_ids = {}
    if include_accelerator:
        oa_ids = {"shield": ids["accelerator_side_shield"]}
        oa_ids.update({role: ids["accelerator_" + role]
                       for role in neutral["accelerator"]["electrical"]["planes_z_mm"]})
        oa_ids["rings"] = [ids["accelerator_ring_" + str(index)]
                           for index in range(1, len(neutral["accelerator"]["geometry"]["ring_z_mm"]) + 1)]
    shield = next(body for body in bodies if body["role"] == "flight_tube_shield")
    def native_row(body: dict[str, Any], label: int, regions: list[dict[str, Any]]) -> dict[str, Any]:
        return dict(component_electrode_id=ids[body["role"]], local_electrode_id=label,
                    voltage_v=body["operating_voltage_v"], regions=regions)
    native = [native_row(body, index, body["reflectron_local_regions"])
              for index, body in enumerate((body for body in bodies
                                            if body["role"].startswith("reflectron_")), 1)]
    native.append(native_row(shield, len(native) + 1, shield["reflectron_local_regions"]))
    extent = neutral["local_extents"]
    detector_body = dict(next(body["geometry"] for body in bodies if body["role"] == "detector"))
    detector_body["back_cells"] = math.ceil((detector_body["height_mm"] + marker["back_margin_z_mm"]) / marker["cell_z_mm"])
    detector_body["front_cells"] = math.ceil(marker["front_margin_z_mm"] / marker["cell_z_mm"])
    return dict(schema_version=1, role="oatof_physical_geometry" if include_accelerator else "single_reflection_tof_physical_geometry",
        local_frame_id=neutral["local_frame_id"], length_unit="mm",
        **({"variant_id": neutral["variant_id"]} if include_accelerator else {}),
        accelerator=(dict(geometry=neutral["accelerator"]["geometry"], physical_electrode_ids=oa_ids,
                         electrical=neutral["accelerator"]["electrical"]) if include_accelerator else None), electrodes=objects,
        detector_active_face=dict(component_electrode_id=ids["detector"],
                                  **{key: value for key, value in neutral["detector_active_face"].items() if key != "role"}),
        simion=dict(flight_tube=dict(electrodes=[native_row(shield, 1, shield["flight_tube_local_regions"])],
                                    axial_span_mm=extent["flight_tube_axial_span_mm"], outer_radius_mm=extent["outer_radius_mm"]),
                    reflectron=dict(electrodes=native, axial_span_mm=extent["reflectron_axial_span_mm"],
                                    outer_radius_mm=extent["outer_radius_mm"]),
                    detector_marker=dict(marker), detector_body=detector_body))


def resolve_oatof_contract_documents(baseline, mode, numerics, *, input_identity):
    """Compose neutral TOF science with its explicit legacy SIMION projection."""
    from msplatform.components.single_reflection_oa_tof.geometry_contract import (
        _require_exact_keys, _validate_science, resolve_contract_documents,
    )
    _validate_science(baseline, mode)
    _require_exact_keys(numerics, {"schema_version", "role", "comsol", "simion"}, "solver numerics contract")
    if type(numerics["schema_version"]) is not int or numerics["schema_version"] != 1:
        raise ValueError("unsupported solver numerics schema_version; requires integer 1")
    if numerics.get("role") != "oa_tof_formal_solver_numerics":
        raise ValueError("unsupported formal solver numerics contract")
    if not isinstance(mode.get("particle"), dict) or not isinstance(numerics.get("comsol"), dict) or not isinstance(numerics.get("simion"), dict):
        raise ValueError("formal contracts are missing required science or solver sections")
    runtime = numerics["comsol"]
    for key in ("routine_reflectron_hmax_mm", "routine_accelerator_hmax_mm", "convergence_accelerator_hmax_mm",
                "fine_output_step_ns", "field_free_output_step_ns"):
        value = runtime.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"comsol.{key} must be a finite positive number")
    if runtime.get("solver_steps") not in ("free", "intermediate", "strict"):
        raise ValueError("comsol.solver_steps must be free, intermediate or strict")
    if runtime.get("times_to_store") != "tlist":
        raise ValueError("comsol.times_to_store must be tlist for OA-TOF detector sampling")
    build = numerics["simion"]["geometry_build"]
    marker = numerics["simion"]["detector_marker"]
    if not 0 < marker["capture_depth_mm"] < marker["absorber_thickness_mm"]:
        raise ValueError("detector capture depth must lie inside the numerical absorber")
    if marker["capture_arm_distance_mm"] <= marker["front_margin_z_mm"]:
        raise ValueError("detector capture arm distance must exceed the PA front margin")
    resolved = resolve_contract_documents(baseline, mode, input_identity=input_identity)
    resolved.update(simion_runtime={**numerics["simion"], "routine_particles": mode["particle"]["statistical_count"]},
        simion_geometry_build=build, comsol_runtime=runtime, simion_detector_marker=marker)
    physical = resolve_physical_geometry(resolved)
    face = physical["detector_active_face"]
    if marker["active_plane_z_mm"] != face["center_mm"][2] or marker["active_radius_mm"] != face["radius_mm"]:
        raise ValueError("numerical detector marker differs from the physical detector active face")
    detector_body = physical["simion"]["detector_body"]
    resolved["derived"] = derive_simion_geometry(geometry=resolved["geometry_mm"],
        coordinate=resolved["coordinate_convention"], build=build, marker=marker,
        source=resolved["particle_source"], physical_detector=detector_body)
    return resolved
