"""Pure design-variable compilation against an explicit catalog."""
from __future__ import annotations
import copy
import math
from typing import Any
from msplatform.contracts.machine_contracts import validate_schema
from msplatform.components.rf_multipole.grounded_shield import require_grounded_potential
from msplatform.components.orthogonal_accelerator.accelerator_time_focus import accelerator_state, focus_drift_mm
from msplatform.components.single_reflection_oa_tof.oatof_oaaccelerator_coupling import solve_coupled_reflectron_fields


class EnvelopeReviewRequired(ValueError):
    """The requested candidate is valid in principle but exceeds the approved envelope."""


def _derive_accelerator_focus(baseline: dict[str, Any]) -> None:
    geometry = baseline["geometry_mm"]
    derivation = baseline["geometry_derivation"]["accelerator"]
    voltage = baseline["electrodes_V"]
    d1, d2 = float(derivation["d1_mm"]), float(derivation["d2_mm"])
    drift = focus_drift_mm(float(voltage["repeller"]), float(voltage["grid1"]), d1, d2)
    if drift <= 0:
        raise ValueError("accelerator time focus must lie beyond grid2")
    focus = float(geometry["accelerator_focus_z"])
    grid2 = focus - drift
    grid1 = grid2 - d2
    repeller = grid1 - d1
    geometry["L_accel"] = d1 + d2
    geometry["accelerator_repeller_z"] = repeller
    geometry["accelerator_grid1_z"] = grid1
    geometry["accelerator_grid2_z"] = grid2
    derivation["canonical_repeller_z_mm"] = repeller
    derivation["canonical_grid1_z_mm"] = grid1
    derivation["canonical_grid2_z_mm"] = grid2
    derivation["canonical_focus_z_mm"] = focus
    derivation["focus_drift_after_grid2_mm"] = drift
    baseline["particle_source"]["center_z_mm"] = repeller + d1 / 2.0


def pointer_tokens(pointer: str) -> list[str]:
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer.lstrip("/").split("/")]


def pointer_get(document: dict[str, Any], pointer: str) -> Any:
    value: Any = document
    for token in pointer_tokens(pointer):
        value = value[token]
    return value


def pointer_set(document: dict[str, Any], pointer: str, value: int | float) -> None:
    parent: Any = document
    tokens = pointer_tokens(pointer)
    for token in tokens[:-1]:
        parent = parent[token]
    parent[tokens[-1]] = value


def _derive_reflectron_for_flight_length(baseline: dict[str, Any]) -> None:
    geometry = baseline["geometry_mm"]
    derivation = baseline["geometry_derivation"]["reflectron"]
    accelerator_derivation = baseline["geometry_derivation"]["accelerator"]
    voltage = baseline["electrodes_V"]
    flight = float(geometry["L_flight"])
    total_field_free = 2.0 * flight
    accelerator = accelerator_state(
        float(voltage["repeller"]),
        float(voltage["grid1"]),
        float(accelerator_derivation["d1_mm"]),
        float(accelerator_derivation["d2_mm"]),
    )
    source_width = float(baseline["particle_source"]["size_z_mm"])
    spatial_half_range = accelerator.field1_v_per_mm * source_width / 2.0
    intrinsic_half_range = float(
        derivation.get("intrinsic_axial_energy_per_charge_half_range_V", 0.0)
    )
    energy_min = (
        accelerator.nominal_energy_per_charge_v
        - spatial_half_range
        - intrinsic_half_range
    )
    energy_max = (
        accelerator.nominal_energy_per_charge_v
        + spatial_half_range
        + intrinsic_half_range
    )
    fields = solve_coupled_reflectron_fields(
        accelerator,
        float(geometry["L_stage1"]),
        flight,
        flight,
        energy_min_v=energy_min,
        energy_max_v=energy_max,
        stage2_margin_fraction=float(derivation["stage2_margin_fraction"]),
        stage2_margin_mm=float(derivation.get("stage2_margin_absolute_mm", 0.0)),
    )
    stage2_raw_mm = fields.required_stage2_depth_mm
    stage2 = round(stage2_raw_mm, int(derivation["engineering_length_decimals_mm"]))
    mirror_voltage = (
        fields.stage1_voltage_drop_v
        + fields.stage2_field_v_per_mm * stage2_raw_mm
    )
    voltage_decimals = int(derivation["engineering_voltage_decimals_V"])
    geometry["L_stage2"] = stage2
    geometry["L_reflectron"] = geometry["L_stage1"] + stage2
    baseline["electrodes_V"]["midgrid"] = round(
        fields.stage1_voltage_drop_v, voltage_decimals
    )
    baseline["electrodes_V"]["backplate"] = round(mirror_voltage, voltage_decimals)
    derivation["total_field_free_length_mm"] = total_field_free
    derivation["outbound_field_free_length_mm"] = flight
    derivation["return_field_free_length_mm"] = flight
    derivation.pop("incident_energy_eV", None)
    derivation.update(
        {
            "model_id": "oatof.oaaccelerator_reflectron_coupled.ideal_1d.v1",
            "nominal_energy_per_charge_V": accelerator.nominal_energy_per_charge_v,
            "source_release_full_width_mm": source_width,
            "spatial_energy_half_range_V": spatial_half_range,
            "intrinsic_axial_energy_per_charge_half_range_V": intrinsic_half_range,
            "energy_min_V": energy_min,
            "energy_max_V": energy_max,
            "stage2_margin_basis": "full_energy_envelope_high_tail_penetration",
            "stage2_margin_absolute_mm": float(
                derivation.get("stage2_margin_absolute_mm", 0.0)
            ),
            "rule": (
                "Solve the coupled accelerator-to-detector first- and second-order "
                "conditions for U_R1 and F_2; derive the source-correlated full "
                "energy envelope from accelerator E_A1 and source z width; set "
                "L_stage2=((W_max-U_R1)/F_2)*(1+margin_fraction)+margin_absolute; "
                "derive V_backplate=U_R1+F_2*L_stage2_raw; round only final "
                "engineering lengths and voltages."
            ),
        }
    )


def derive_accelerator_outer_envelope_min_z(baseline: dict[str, Any]) -> float:
    """Return the accelerator assembly's upstream-most outer-envelope coordinate."""
    geometry = baseline["geometry_mm"]
    endpoint = (
        geometry["accelerator_repeller_z"]
        - geometry["accelerator_repeller_thickness"]
        - geometry["accelerator_rear_clearance"]
        - geometry["accelerator_shield_wall"]
    )
    baseline["geometry_derivation"]["accelerator"][
        "outer_envelope_min_z_mm"
    ] = endpoint
    return endpoint


def derive_shield_bounds(
    baseline: dict[str, Any], accelerator_outer_envelope_min_z_mm: float
) -> None:
    """Derive shield bounds from component envelope endpoints only."""
    geometry = baseline["geometry_mm"]
    near = (
        accelerator_outer_envelope_min_z_mm
        - geometry["shield_near_endcap_gap"]
    )
    far = geometry["L_flight"] + geometry["L_reflectron"] + geometry["ring_thickness"] + geometry["shield_axial_gap"]
    geometry["shield_bore_z_min"] = near
    geometry["shield_bore_z_max"] = far
    geometry["shield_outer_z_min"] = near - geometry["shield_endcap_thickness"]
    geometry["shield_outer_z_max"] = far + geometry["shield_endcap_thickness"]


def _validate_invariants(baseline: dict[str, Any], *, catalog: dict[str, Any]) -> None:
    require_grounded_potential(baseline["electrodes_V"]["shield"], "oaTOF shield")
    geometry = baseline["geometry_mm"]
    rings = baseline["rings"]
    if not geometry["bore_r"] < geometry["ring_outer_r"] < geometry["flight_tube_r"]:
        raise ValueError("reflectron radial order must be bore < ring outer radius < shield inner radius")
    convention = baseline["coordinate_convention"]
    reflectron_axis_x = float(convention["reflectron_axis"][0])
    detector_outer_radius = (
        abs(float(convention["detector_x"]) - reflectron_axis_x)
        + float(geometry["detector_radius"])
    )
    accelerator_outer_half_width = (
        float(geometry["accelerator_bore_half"])
        + float(geometry["accelerator_ring_width"])
        + float(geometry["accelerator_insulation_gap"])
        + float(geometry["accelerator_shield_wall"])
    )
    accelerator_outer_radius = (
        abs(float(convention["accelerator_axis_x"]) - reflectron_axis_x)
        + accelerator_outer_half_width
    )
    required_shield_inner_radius = max(
        detector_outer_radius, accelerator_outer_radius
    )
    if geometry["flight_tube_r"] < required_shield_inner_radius:
        raise ValueError(
            "shared flight-tube/reflectron shield inner radius cannot contain "
            f"the transverse hardware envelope: required>={required_shield_inner_radius:g} mm"
        )
    minimum_ring_gap = float(
        catalog["manufacturing_constraints"][
            "reflectron_minimum_axial_ring_gap_mm"
        ]
    )
    stage1_gap = geometry["L_stage1"] / (rings["stage1_count"] + 1) - geometry["ring_thickness"]
    stage2_gap = geometry["L_stage2"] / (rings["stage2_count"] + 1) - geometry["ring_thickness"]
    if stage1_gap + 1e-12 < minimum_ring_gap:
        raise ValueError(
            "stage-1 ring gap violates the manufacturing minimum: "
            f"actual={stage1_gap:g} mm required>={minimum_ring_gap:g} mm"
        )
    if stage2_gap + 1e-12 < minimum_ring_gap:
        raise ValueError(
            "stage-2 ring gap violates the manufacturing minimum: "
            f"actual={stage2_gap:g} mm required>={minimum_ring_gap:g} mm"
        )
    accelerator = baseline["geometry_derivation"]["accelerator"]
    if geometry["accelerator_ring_thickness"] >= accelerator["d2_mm"] / (rings["accelerator_count"] + 1):
        raise ValueError("accelerator rings overlap at the requested count and thickness")
    if baseline["particle_source"]["size_z_mm"] > accelerator["d1_mm"]:
        raise ValueError("particle-source axial size must fit between repeller and grid1")
    if geometry["accelerator_exit_grid_half_width"] < geometry["accelerator_bore_half"]:
        raise ValueError("accelerator exit grid must cover the clear aperture")
    if not math.isclose(geometry["L_reflectron"], geometry["L_stage1"] + geometry["L_stage2"], abs_tol=1e-10):
        raise ValueError("reflectron length identity failed")
    if not math.isclose(geometry["L_accel"], accelerator["d1_mm"] + accelerator["d2_mm"], abs_tol=1e-10):
        raise ValueError("accelerator length identity failed")


def compile_design_overrides(
    base_contract: dict[str, Any], overrides: list[dict[str, Any]], *, catalog: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply catalog variables and automatically close all theoretical dependencies."""
    validate_schema(catalog, "design_variable_catalog.schema.json")
    definitions = {item["variable_id"]: item for item in catalog["variables"]}
    values: dict[str, float | int] = {}
    for item in overrides:
        variable_id = str(item["variable"])
        if variable_id in values:
            raise ValueError(f"duplicate design override: {variable_id}")
        definition = definitions.get(variable_id)
        if definition is None:
            raise ValueError(f"unknown design override: {variable_id}")
        if definition["kind"] == "derived":
            raise ValueError(f"derived variable cannot be specified: {variable_id}")
        if definition["kind"] == "topology":
            raise ValueError(
                f"topology variable requires a dedicated compiler: {variable_id}"
            )
        if item["unit"] != definition["unit"]:
            raise ValueError(f"unit mismatch for {variable_id}")
        value = float(item["value"])
        if not math.isfinite(value) or not definition["minimum"] <= value <= definition["maximum"]:
            raise ValueError(f"design override outside compilation bounds: {variable_id}")
        if definition["kind"] == "integer":
            if not value.is_integer():
                raise ValueError(f"integer design override required: {variable_id}")
            values[variable_id] = int(value)
        else:
            values[variable_id] = value

    candidate = copy.deepcopy(base_contract)
    reflectron_voltage_ids = {
        "reflectron_midgrid_voltage", "reflectron_backplate_voltage"
    }
    for variable_id, value in values.items():
        if variable_id not in reflectron_voltage_ids:
            pointer_set(candidate, definitions[variable_id]["json_pointer"], value)
    accelerator_focus_inputs = {
        "accelerator_repeller_voltage", "accelerator_grid1_voltage",
        "accelerator_stage1_length", "accelerator_stage2_length",
    }
    if accelerator_focus_inputs & values.keys():
        _derive_accelerator_focus(candidate)
    coupled_longitudinal_inputs = accelerator_focus_inputs | {
        "flight_length", "reflectron_stage1_length", "source_release_full_width"
    }
    if coupled_longitudinal_inputs & values.keys():
        _derive_reflectron_for_flight_length(candidate)
    if values:
        derive_shield_bounds(
            candidate, derive_accelerator_outer_envelope_min_z(candidate)
        )
    for variable_id in reflectron_voltage_ids & values.keys():
        pointer_set(
            candidate, definitions[variable_id]["json_pointer"], values[variable_id]
        )
    _validate_invariants(candidate, catalog=catalog)

    changed = []
    rebuild_effects: set[str] = set()
    for variable_id, value in values.items():
        definition = definitions[variable_id]
        before = pointer_get(base_contract, definition["json_pointer"])
        after = pointer_get(candidate, definition["json_pointer"])
        if before != after:
            changed.append({
                "variable": variable_id, "before": before, "after": after,
                "unit": definition["unit"],
            })
            rebuild_effects.update(definition["rebuild_effects"])
    rebuild_plan = {
        "frontend_pa": bool(
            accelerator_focus_inputs & values.keys()
            or any(name.startswith("accelerator_") and "voltage" not in name
                   for name in values)
        ),
        "flight_tube_pa": bool(
            accelerator_focus_inputs & values.keys()
            or {"flight_length", "accelerator_shield_wall_thickness",
             "accelerator_rear_clearance", "accelerator_repeller_thickness",
             "reflectron_shield_inner_radius",
             "reflectron_shield_wall_thickness",
             "reflectron_shield_endcap_thickness",
             "reflectron_shield_near_endcap_gap"} & values.keys()
        ),
        "reflectron_pa": bool(
            coupled_longitudinal_inputs & values.keys()
            or any(name.startswith("reflectron_") and "voltage" not in name
                   for name in values)
        ),
    }
    return candidate, {
        "method": "catalog_design_overrides_with_theory_closure_v1",
        "changed_variables": changed,
        "rebuild_effects": sorted(rebuild_effects),
        "simion_rebuild_plan": rebuild_plan,
    }
