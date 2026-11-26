"""Pure oaTOF design and complete physical electrode projection."""
from __future__ import annotations
import json
import math
from typing import Any
from msplatform.components.rf_multipole.grounded_shield import require_grounded_potential
from msplatform.components.single_reflection_tof.geometry import DOWNSTREAM_GEOMETRY_KEYS

def _close(label: str, actual: float, expected: float, tolerance: float = 1e-10) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(f"inconsistent {label}: {actual} != {expected}")

def _require_exact_keys(document: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(document) - allowed
    if unknown:
        raise ValueError(f"{label} contains cross-layer or unknown fields: {sorted(unknown)}")

def _validate_science(baseline: dict[str, Any], science: dict[str, Any]) -> None:
    require_grounded_potential(baseline["electrodes_V"]["shield"], "oaTOF shield")
    if "seed" in baseline.get("particle_source", {}):
        raise ValueError("science baseline must not contain particle_source.seed; freeze it in the run instance")
    _require_exact_keys(science, {"schema_version", "role", "mode", "contract_layers", "particle"}, "science contract")
    if science.get("role") != "oa_tof_formal_science_contract" or science.get("mode") != "formal":
        raise ValueError("unsupported formal science contract")
    if science.get("contract_layers") != ["science", "solver_numerics", "run_instance"]:
        raise ValueError("formal science contract has an invalid layer declaration")

def resolve_electrode_geometry(
    contract: dict[str, Any], *, accelerator_projection: Any = None,
) -> dict[str, Any]:
    """Resolve physical electrode bodies and ON potentials without a backend.

    Explicit local-frame regions preserve the original arithmetic for the
    legacy native adapter; they are physical coordinates, not native labels.
    Numerical detector markers and solver meshes are not required here.
    """
    from msplatform.components.single_reflection_oa_tof.accelerator_geometry import resolve_accelerator_geometry
    from msplatform.components.single_reflection_oa_tof.accelerator_electrical import resolve_accelerator_electrical_design

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
        contract, variant_id=accelerator_projection.variant_id, geometry_projection=accelerator_projection, schema_version=1)
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

    def electrode(role: str, geometry: dict[str, Any], *, volts: float = 0,
                  grounded: bool = False) -> dict[str, Any]:
        body = dict(role=role, grounded=grounded, geometry=geometry, operating_voltage_v=volts)
        objects.append(body)
        return body

    electrode("accelerator_side_shield", {"provider_region": "shield"}, grounded=True)
    for role in electrical["planes_z_mm"]:
        electrode("accelerator_" + role, {"provider_region": role},
                  volts=electrical["operating_voltages_v"][role])
    for index, volts in enumerate(electrical["operating_voltages_v"]["rings"], 1):
        electrode("accelerator_ring_" + str(index),
                  {"provider_region": "ring", "ring_index": index}, volts=volts)
    from msplatform.components.single_reflection_tof.geometry import resolve_downstream_geometry
    downstream = resolve_downstream_geometry(
        {key: g[key] for key in DOWNSTREAM_GEOMETRY_KEYS},
        {key: coordinate[key] for key in ("reflectron_axis", "detector_x")},
        {key: rings[key] for key in ("stage1_count", "stage2_count")},
        {key: voltage[key] for key in ("entgrid", "midgrid", "backplate")})
    objects.extend(downstream["electrodes"])
    near = g["shield_outer_z_min"]
    interface = g["L_flight"]
    local_outer_end = g["L_reflectron"] + g["ring_thickness"] + g["shield_axial_gap"] + g["shield_endcap_thickness"]
    outer_radius = g["flight_tube_r"] + g["flight_tube_wall"]
    values = [*g.values(), *[item["operating_voltage_v"] for item in objects]]
    if any(isinstance(value, (int, float)) and not math.isfinite(value) for value in values):
        raise ValueError("physical geometry and electrode voltages must be finite")
    return dict(schema_version=1, role="oatof_electrode_geometry", local_frame_id="oatof_global",
        length_unit="mm", variant_id=accelerator_projection.variant_id,
        accelerator=dict(geometry=accelerator, electrical=electrical), electrodes=objects,
        detector_active_face=dict(role="detector",
            center_mm=[coordinate["detector_x"], 0, g["detector_z"]], normal=[0, 0, 1], radius_mm=g["detector_radius"]),
        local_extents=dict(flight_tube_axial_span_mm=interface-near,
                          reflectron_axial_span_mm=local_outer_end, outer_radius_mm=outer_radius))

def resolve_contract_documents(
    baseline: dict[str, Any], mode: dict[str, Any], *,
    input_identity: dict[str, Any],
) -> dict[str, Any]:
    """Resolve already loaded inputs using the same physical projection.

    The caller supplies the frozen input labels and hashes. This pure boundary
    permits capacity planning before a managed run is admitted or created.
    """
    _validate_science(baseline, mode)
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

    coordinate = baseline["coordinate_convention"]
    if coordinate.get("frame_id") != "oatof_global":
        raise ValueError("oa-TOF baseline coordinate frame must be oatof_global")

    particle = mode["particle"]
    return {
        "schema_version": 1,
        "role": "oa_tof_resolved_contract_do_not_edit",
        "inputs": dict(input_identity),
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
        "grid_policy": baseline["grid_policy"],

    }

def serialized(contract: dict[str, Any]) -> str:
    return json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
