"""Resolve the human-edited oa-TOF design and run mode once."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256 as _sha256
from common.multipole.grounded_shield import require_grounded_potential


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = PROJECT_ROOT / "config" / "baseline.json"
MODE_PATH = PROJECT_ROOT / "config" / "modes" / "formal.json"
NUMERICS_PATH = PROJECT_ROOT / "config" / "formal_solver_numerics.json"
RESOLVED_PATH = PROJECT_ROOT / "config" / "resolved_geometry.json"


def _close(label: str, actual: float, expected: float, tolerance: float = 1e-10) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(f"inconsistent {label}: {actual} != {expected}")


def _input_label(path: Path, run_role: str) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return f"run_input:{run_role}"


def _require_exact_keys(document: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(document) - allowed
    if unknown:
        raise ValueError(f"{label} contains cross-layer or unknown fields: {sorted(unknown)}")


def _validate_layers(baseline: dict[str, Any], science: dict[str, Any], numerics: dict[str, Any]) -> None:
    require_grounded_potential(baseline["electrodes_V"]["shield"], "oaTOF shield")
    if "seed" in baseline.get("particle_source", {}):
        raise ValueError("science baseline must not contain particle_source.seed; freeze it in the run instance")
    _require_exact_keys(science, {"schema_version", "role", "mode", "contract_layers", "particle"}, "science contract")
    if science.get("role") != "oa_tof_formal_science_contract" or science.get("mode") != "formal":
        raise ValueError("unsupported formal science contract")
    if science.get("contract_layers") != ["science", "solver_numerics", "run_instance"]:
        raise ValueError("formal science contract has an invalid layer declaration")
    _require_exact_keys(numerics, {"schema_version", "role", "comsol", "simion"}, "solver numerics contract")
    if numerics.get("role") != "oa_tof_formal_solver_numerics":
        raise ValueError("unsupported formal solver numerics contract")
    if not isinstance(science.get("particle"), dict) or not isinstance(numerics.get("comsol"), dict) or not isinstance(numerics.get("simion"), dict):
        raise ValueError("formal contracts are missing required science or solver sections")
    runtime = numerics["comsol"]
    if runtime.get("solver_steps") not in ("free", "intermediate", "strict"):
        raise ValueError("comsol.solver_steps must be free, intermediate or strict")
    if runtime.get("times_to_store") != "tlist":
        raise ValueError("comsol.times_to_store must be tlist for OA-TOF detector sampling")


def derive_simion_geometry(
    *, geometry: dict[str, Any], coordinate: dict[str, Any],
    build: dict[str, Any], marker: dict[str, Any], source: dict[str, Any],
) -> dict[str, Any]:
    """Derive provider-local PA placements and samples from the final design.

    These placements map native PA domains into oatof_global; cross-component
    assembly transforms are applied separately by the consuming integration.
    """
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
    """Project the final frozen design into physical objects and native bindings.

    Physical IDs identify provider objects, never PA-local electrode numbers.
    The continuous instrument enclosure owns both native shield fragments. The
    real detector cylinder and the SIMION return marker remain separate models.
    This pure projection changes neither the scientific contract nor any file.
    """
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import resolve_accelerator_geometry
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_electrical import resolve_accelerator_electrical_design

    if contract.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("physical geometry requires the final resolved oaTOF contract")
    if contract["coordinate_convention"]["frame_id"] != "oatof_global":
        raise ValueError("physical geometry requires oatof_global")
    if accelerator_projection is None:
        realization = contract["geometry_derivation"]["accelerator"].get("realization_id", "square_3d")
        cross_section = {"square_3d": "square", "cylindrical_3d": "cylindrical"}[realization]
        zones = "three_zone" if "accelerator_topology" in contract else "two_zone"
        accelerator_projection = resolve_accelerator_geometry(contract, variant_id=zones + "_" + cross_section)
    accelerator = accelerator_projection.local_region
    electrical = resolve_accelerator_electrical_design(
        contract, variant_id=accelerator_projection.variant_id, geometry_projection=accelerator_projection)
    g, coordinate = contract["geometry_mm"], contract["coordinate_convention"]
    rings, voltage = contract["rings"], contract["electrodes_V"]
    positive = ("flight_tube_r", "flight_tube_wall", "shield_endcap_thickness", "L_reflectron",
        "ring_thickness", "shield_axial_gap", "L_stage1", "L_stage2", "bore_r", "ring_outer_r",
        "detector_radius", "detector_thickness")
    if any(isinstance(g[key], bool) or not isinstance(g[key], (int, float))
           or not math.isfinite(g[key]) or g[key] <= 0 for key in positive):
        raise ValueError("physical lengths and radii must be finite and positive")
    if not g["bore_r"] < g["ring_outer_r"] < g["flight_tube_r"]:
        raise ValueError("reflectron radii must be ordered")
    _close("reflectron length", g["L_reflectron"], g["L_stage1"]+g["L_stage2"])
    if g["L_flight"]-g["shield_outer_z_min"] <= g["shield_endcap_thickness"]:
        raise ValueError("reflectron interface must lie beyond the near cap")
    objects: list[dict[str, Any]] = []

    def electrode(role: str, geometry: dict[str, Any], *, grounded: bool = False) -> int:
        physical_id = len(objects) + 1
        objects.append(dict(component_electrode_id=physical_id, role=role,
            electrical_group_id=1 if grounded else physical_id, geometry=geometry))
        return physical_id

    oa_ids = {"shield": electrode("accelerator_side_shield", {"provider_region": "shield"}, grounded=True)}
    for role in electrical["planes_z_mm"]:
        oa_ids[role] = electrode("accelerator_" + role, {"provider_region": role})
    oa_ids["rings"] = [electrode("accelerator_ring_" + str(index),
        {"provider_region": "ring", "ring_index": index})
        for index in range(1, len(accelerator["ring_z_mm"]) + 1)]
    outer_radius = g["flight_tube_r"] + g["flight_tube_wall"]
    near = g["shield_outer_z_min"]
    interface = g["L_flight"]
    local_bore_end = g["L_reflectron"] + g["ring_thickness"] + g["shield_axial_gap"]
    local_outer_end = local_bore_end + g["shield_endcap_thickness"]
    bore_end, outer_end = interface + local_bore_end, interface + local_outer_end
    shield_parts = [
        dict(axial_mm=[near, near + g["shield_endcap_thickness"]], radius_mm=[0, outer_radius]),
        dict(axial_mm=[near + g["shield_endcap_thickness"], bore_end], radius_mm=[g["flight_tube_r"], outer_radius]),
        dict(axial_mm=[bore_end, outer_end], radius_mm=[0, outer_radius]),
    ]
    shield_id = electrode("flight_tube_shield", dict(primitive="cylindrical_union",
        axis_xy_mm=list(coordinate["reflectron_axis"]), parts=shield_parts), grounded=True)
    tube = dict(electrodes=[dict(component_electrode_id=shield_id, local_electrode_id=1,
        voltage_v=0, regions=[dict(axial_mm=[0, g["shield_endcap_thickness"]], radius_mm=[0, outer_radius]),
            dict(axial_mm=[g["shield_endcap_thickness"], interface-near], radius_mm=[g["flight_tube_r"], outer_radius])])],
        axial_span_mm=interface-near, outer_radius_mm=outer_radius)
    native: list[dict[str, Any]] = []

    def reflector_electrode(role: str, z0: float, z1: float, r0: float, r1: float,
                            volts: float, *, grounded: bool = False) -> None:
        physical_id = electrode(role, dict(primitive="cylindrical_region",
            axis_xy_mm=list(coordinate["reflectron_axis"]), axial_mm=[interface+z0, interface+z1],
            radius_mm=[r0, r1]), grounded=grounded)
        native.append(dict(component_electrode_id=physical_id, local_electrode_id=len(native)+1,
            voltage_v=volts, regions=[dict(axial_mm=[z0, z1], radius_mm=[r0, r1])]))

    reflector_electrode("reflectron_entry_grid", 0, 0, 0, g["flight_tube_r"],
        require_grounded_potential(voltage["entgrid"], "oaTOF reflectron entrance grid"), grounded=True)
    counts = [rings["stage1_count"], rings["stage2_count"]]
    if any(type(count) is not int or count < 1 for count in counts):
        raise ValueError("reflectron ring counts must be positive integers")
    for stage, count, start, length, v0, v1 in (
        (1, counts[0], 0, g["L_stage1"], 0, voltage["midgrid"]),
        (2, counts[1], g["L_stage1"], g["L_stage2"], voltage["midgrid"], voltage["backplate"]),
    ):
        for index in range(1, count+1):
            center = start + index * (length / (count+1))
            volts = v0 + (v1-v0) * index / (count+1)
            reflector_electrode(f"reflectron_stage{stage}_ring_{index}",
                center-g["ring_thickness"]/2, center+g["ring_thickness"]/2,
                g["bore_r"], g["ring_outer_r"], volts)
        if stage == 1:
            reflector_electrode("reflectron_midgrid", g["L_stage1"], g["L_stage1"],
                0, g["ring_outer_r"], voltage["midgrid"])
    reflector_electrode("reflectron_backplate", g["L_reflectron"], g["L_reflectron"]+g["ring_thickness"],
        0, g["ring_outer_r"], voltage["backplate"])
    native.append(dict(component_electrode_id=shield_id, local_electrode_id=len(native)+1, voltage_v=0,
        regions=[dict(axial_mm=[0, local_bore_end], radius_mm=[g["flight_tube_r"], outer_radius]),
                 dict(axial_mm=[local_bore_end, local_outer_end], radius_mm=[0, outer_radius])]))
    detector_id = electrode("detector", dict(primitive="cylinder", radius_mm=g["detector_radius"],
        base_center_mm=[coordinate["detector_x"], 0, g["detector_z"]-g["detector_thickness"]],
        height_mm=g["detector_thickness"], axis=[0, 0, 1]), grounded=True)
    marker = dict(contract["simion_detector_marker"])
    values = [*g.values(), *[item["voltage_v"] for item in native]]
    if any(isinstance(value, (int, float)) and not math.isfinite(value) for value in values):
        raise ValueError("physical geometry and electrode voltages must be finite")
    return dict(schema_version=1, role="oatof_physical_geometry", local_frame_id="oatof_global",
        length_unit="mm", variant_id=accelerator_projection.variant_id,
        accelerator=dict(geometry=accelerator, physical_electrode_ids=oa_ids,
            electrical=electrical), electrodes=objects,
        detector_active_face=dict(component_electrode_id=detector_id,
            center_mm=[coordinate["detector_x"], 0, g["detector_z"]], normal=[0, 0, 1], radius_mm=g["detector_radius"]),
        simion=dict(flight_tube=tube,
            reflectron=dict(electrodes=native, axial_span_mm=local_outer_end,
                outer_radius_mm=outer_radius), detector_marker=marker))


def resolve_contract(
    baseline_path: Path = BASELINE_PATH,
    mode_path: Path = MODE_PATH,
    numerics_path: Path = NUMERICS_PATH,
) -> dict[str, Any]:
    baseline_path = Path(baseline_path)
    mode_path = Path(mode_path)
    numerics_path = Path(numerics_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    numerics = json.loads(numerics_path.read_text(encoding="utf-8"))
    _validate_layers(baseline, mode, numerics)
    geometry = baseline["geometry_mm"]
    accelerator = baseline["geometry_derivation"]["accelerator"]
    source = baseline["particle_source"]

    _close("accelerator length", geometry["L_accel"], accelerator["d1_mm"] + accelerator["d2_mm"])
    _close("accelerator grid1", geometry["accelerator_grid1_z"], geometry["accelerator_repeller_z"] + accelerator["d1_mm"])
    _close("accelerator grid2", geometry["accelerator_grid2_z"], geometry["accelerator_grid1_z"] + accelerator["d2_mm"])
    _close("focus plane", geometry["accelerator_focus_z"], geometry["accelerator_grid2_z"] + accelerator["focus_drift_after_grid2_mm"])
    _close("reflectron length", geometry["L_reflectron"], geometry["L_stage1"] + geometry["L_stage2"])
    source_rule = source["center_z_rule"]
    if source_rule == "accelerator_repeller_z + accelerator_stage1_length_mm/2":
        expected_source_z = geometry["accelerator_repeller_z"] + accelerator["d1_mm"] / 2
        theory = accelerator.get("finite_interval_theory")
        if theory is not None and not math.isclose(
            source["center_z_mm"], expected_source_z, rel_tol=0.0, abs_tol=1e-10
        ):
            finite_interval_source_z = (
                theory["canonical_repeller_z_mm"] + theory["source_center_mm"]
            )
            if math.isclose(
                source["center_z_mm"], finite_interval_source_z,
                rel_tol=0.0, abs_tol=1e-10,
            ):
                expected_source_z = finite_interval_source_z
    elif source_rule == (
        "geometry_derivation.accelerator.finite_interval_theory."
        "canonical_repeller_z_mm + source_center_mm"
    ):
        theory = accelerator["finite_interval_theory"]
        expected_source_z = theory["canonical_repeller_z_mm"] + theory["source_center_mm"]
    else:
        raise ValueError(f"unsupported source center rule: {source_rule}")
    _close("source center z", source["center_z_mm"], expected_source_z)

    build = numerics["simion"]["geometry_build"]
    marker = numerics["simion"]["detector_marker"]
    if not 0 < marker["capture_depth_mm"] < marker["absorber_thickness_mm"]:
        raise ValueError("detector capture depth must lie inside the numerical absorber")
    if marker["capture_arm_distance_mm"] <= marker["front_margin_z_mm"]:
        raise ValueError("detector capture arm distance must exceed the PA front margin")
    coordinate = baseline["coordinate_convention"]
    if coordinate.get("frame_id") != "oatof_global":
        raise ValueError("oa-TOF baseline coordinate frame must be oatof_global")

    particle = mode["particle"]
    return {
        "schema_version": 1,
        "role": "oa_tof_resolved_contract_do_not_edit",
        "inputs": {
            "baseline": _input_label(baseline_path, "candidate_baseline.json"),
            "baseline_sha256": _sha256(baseline_path),
            "mode": _input_label(mode_path, "candidate_science_mode.json"),
            "mode_sha256": _sha256(mode_path),
            "solver_numerics": _input_label(
                numerics_path, "candidate_solver_numerics.json"
            ),
            "solver_numerics_sha256": _sha256(numerics_path),
        },
        "coordinate_convention": coordinate,
        "geometry_derivation": baseline["geometry_derivation"],
        "geometry_mm": geometry,
        "particle_source": source,
        "electrodes_V": baseline["electrodes_V"],
        "rings": baseline["rings"],
        "validation_target": {
            "mass_amu": particle["mass_amu"],
            "charge_state": particle["charge_state"],
            "particles": particle["statistical_count"],
            "initial_energy_mean_ev": particle["initial_energy_mean_ev"],
            "initial_energy_sigma_ev": particle["initial_energy_sigma_ev"],
        },
        "particle_count_policy": {
            "default_check_count": particle["default_check_count"],
            "statistical_count": particle["statistical_count"],
            "specialty_counts_require_explicit_purpose": True,
        },
        "simion_runtime": {
            **numerics["simion"],
            "routine_particles": particle["statistical_count"],
        },
        "simion_geometry_build": build,
        "comsol_runtime": numerics["comsol"],
        "simion_detector_marker": marker,
        "grid_policy": baseline["grid_policy"],
        "derived": derive_simion_geometry(
            geometry=geometry, coordinate=coordinate, build=build,
            marker=marker, source=source,
        ),
    }


def serialized(contract: dict[str, Any]) -> str:
    return json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
