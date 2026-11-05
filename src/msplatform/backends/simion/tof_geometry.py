"""SIMION placements and explicit legacy native labels over neutral TOF geometry."""
from __future__ import annotations
import math
from typing import Any
from msplatform.components.single_reflection_oa_tof.geometry_contract import resolve_electrode_geometry

def derive_simion_instances(*, geometry: dict[str, Any], coordinate: dict[str, Any],
                            build: dict[str, Any], marker: dict[str, Any]) -> list[dict[str, Any]]:
    """Project native geometry domains without a particle source or field samples."""
    accelerator_half = geometry["accelerator_bore_half"] + geometry["accelerator_ring_width"] + geometry["accelerator_insulation_gap"] + geometry["accelerator_shield_wall"]
    accelerator_local_z_min = -geometry["accelerator_repeller_thickness"] - geometry["accelerator_rear_clearance"] - geometry["accelerator_shield_wall"]
    accelerator_local_z_max = geometry["L_accel"] + geometry["accelerator_front_vacuum_margin"]
    detector_half = marker["active_radius_mm"] + build["detector"]["margin_xy_mm"]

    instances = [
        {"role": "flight_tube_shield", "workbench_index": 1, "priority_number": 1, "name": "flight_tube_ground.pa0", "x_mm": coordinate["reflectron_axis"][0], "y_mm": coordinate["reflectron_axis"][1], "z_mm": geometry["shield_outer_z_min"], "az_deg": -90.0,
         "nx": math.ceil((geometry["L_flight"] - geometry["shield_outer_z_min"]) / build["flight_tube"]["cell_axial_mm"]) + 1,
         "ny": math.ceil((geometry["flight_tube_r"] + geometry["flight_tube_wall"]) / build["flight_tube"]["cell_radial_mm"]) + 1, "nz": 1, "cell_mm": build["flight_tube"]["cell_axial_mm"]},
        {"role": "reflectron", "workbench_index": 2, "priority_number": 2, "name": "reflectron.pa0", "x_mm": coordinate["reflectron_axis"][0], "y_mm": coordinate["reflectron_axis"][1], "z_mm": geometry["L_flight"], "az_deg": -90.0,
         "nx": math.ceil((geometry["L_reflectron"] + geometry["ring_thickness"] + geometry["shield_axial_gap"] + geometry["shield_endcap_thickness"]) / build["reflectron"]["cell_axial_mm"]) + 1,
         "ny": math.ceil((geometry["flight_tube_r"] + geometry["flight_tube_wall"]) / build["reflectron"]["cell_radial_mm"]) + 1, "nz": 1, "cell_mm": build["reflectron"]["cell_axial_mm"]},
        {"role": "accelerator", "workbench_index": 3, "priority_number": 3, "name": "accelerator.pa0", "x_mm": coordinate["accelerator_axis_x"] - accelerator_half, "y_mm": -accelerator_half,
         "z_mm": geometry["accelerator_repeller_z"] + accelerator_local_z_min, "az_deg": 0.0,
         "nx": round(2 * accelerator_half / build["accelerator"]["cell_xy_mm"]) + 1,
         "ny": round(2 * accelerator_half / build["accelerator"]["cell_xy_mm"]) + 1,
         "nz": round((accelerator_local_z_max - accelerator_local_z_min) / build["accelerator"]["cell_z_mm"]) + 1,
         "cell_mm": build["accelerator"]["cell_xy_mm"]},
        {"role": "detector", "workbench_index": 4, "priority_number": 4, "name": "detector_ground.pa0", "x_mm": coordinate["detector_x"] - detector_half, "y_mm": -detector_half,
         "z_mm": marker["active_plane_z_mm"] - marker["back_margin_z_mm"] - marker["absorber_thickness_mm"], "az_deg": 0.0,
         # Match simion/workbench/build_detector_variant.lua at half-cell ties.
         "nx": math.floor(2 * detector_half / marker["cell_xy_mm"] + 0.5) + 1,
         "ny": math.floor(2 * detector_half / marker["cell_xy_mm"] + 0.5) + 1,
         "nz": math.floor((marker["front_margin_z_mm"] + marker["absorber_thickness_mm"] + marker["back_margin_z_mm"]) / marker["cell_z_mm"] + 0.5) + 1,
         "cell_mm": marker["cell_xy_mm"]},
    ]

    return instances


def derive_simion_geometry(
    *, geometry: dict[str, Any], coordinate: dict[str, Any],
    build: dict[str, Any], marker: dict[str, Any], source: dict[str, Any],
) -> dict[str, Any]:
    """Derive provider-local PA placements and samples from the final design.

    These placements map native PA domains into oatof_global; cross-component
    assembly transforms are applied separately by the consuming integration.
    """
    instances = derive_simion_instances(geometry=geometry, coordinate=coordinate, build=build, marker=marker)

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
    bodies = neutral["electrodes"]
    ids = {body["role"]: index for index, body in enumerate(bodies, 1)}
    objects = [dict(component_electrode_id=ids[body["role"]], role=body["role"],
                    electrical_group_id=1 if body["grounded"] else ids[body["role"]],
                    geometry=body["geometry"]) for body in bodies]
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
    return dict(schema_version=1, role="oatof_physical_geometry", local_frame_id=neutral["local_frame_id"],
        length_unit="mm", variant_id=neutral["variant_id"],
        accelerator=dict(geometry=neutral["accelerator"]["geometry"], physical_electrode_ids=oa_ids,
                         electrical=neutral["accelerator"]["electrical"]), electrodes=objects,
        detector_active_face=dict(component_electrode_id=ids["detector"],
                                  **{key: value for key, value in neutral["detector_active_face"].items() if key != "role"}),
        simion=dict(flight_tube=dict(electrodes=[native_row(shield, 1, shield["flight_tube_local_regions"])],
                                    axial_span_mm=extent["flight_tube_axial_span_mm"], outer_radius_mm=extent["outer_radius_mm"]),
                    reflectron=dict(electrodes=native, axial_span_mm=extent["reflectron_axial_span_mm"],
                                    outer_radius_mm=extent["outer_radius_mm"]),
                    detector_marker=dict(contract["simion_detector_marker"])))
