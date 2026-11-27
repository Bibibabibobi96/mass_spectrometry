"""Resolve dual-cone gas conditions from one author and current physical data."""

import copy
import math
from collections.abc import Mapping

from msplatform.contracts.gas_species import NITROGEN, NITROGEN_TRANSPORT, SDS_MODEL, resolve_nitrogen, resolve_sds_model
from msplatform.contracts.particle_physics import CONSTANTS


def require_sds_positive_ion(source_spec: dict) -> None:
    """Fail closed for species outside the current SDS damping implementation."""
    species = source_spec.get("species", {}) if isinstance(source_spec, Mapping) else {}
    if (not isinstance(species, Mapping) or species.get("species_kind") != "ion"
            or type(species.get("charge_state")) is not int or species["charge_state"] <= 0):
        raise ValueError("dual-cone SDS supports explicitly positive ions only; other particle collisions are unqualified")


def resolve_dual_cone_conditions(author: dict, geometry: dict) -> dict:
    """Bind inlet, outlet and rear proxy to one N2/model authority and geometry."""
    keys = {"schema_version", "environment_id", "species_ref", "collision_model_ref",
            "temperature_k", "inlet_pressure_pa", "outlet_pressure_pa", "uniform_rear"}
    if not isinstance(author, dict) or set(author) != keys or author["schema_version"] != 1:
        raise ValueError("unsupported dual-cone gas environment")
    if author["environment_id"] != "dual_cone_n2_reservoirs_v1":
        raise ValueError("unsupported dual-cone gas environment identity")
    rear = author["uniform_rear"]
    if (not isinstance(rear, dict) or set(rear) != {"start_ref", "pressure_ref", "axial_velocity_m_per_s", "radial_velocity_m_per_s", "upstream"}
            or rear["start_ref"] != "second_cone_aperture" or rear["pressure_ref"] != "outlet_pressure_pa"
            or rear["upstream"] != "prescribed_zero_pressure_collision_omission"):
        raise ValueError("unsupported dual-cone rear proxy references")
    for key in ("temperature_k", "inlet_pressure_pa", "outlet_pressure_pa"):
        value = author[key]
        if (type(value) not in (int, float) or not math.isfinite(value)
                or (value < 0 if key == "outlet_pressure_pa" else value <= 0)):
            raise ValueError("dual-cone temperature/inlet must be positive and outlet nonnegative")
    for key in ("axial_velocity_m_per_s", "radial_velocity_m_per_s"):
        if type(rear[key]) not in (int, float) or not math.isfinite(rear[key]):
            raise ValueError("dual-cone rear velocity must be finite")
    if (not isinstance(geometry, dict) or geometry.get("schema_version") != 1
            or geometry.get("role") != "dual_cone_tandem_quadrupole_resolved_geometry"
            or geometry.get("project_id") != "dual_cone_tandem_quadrupole"):
        raise ValueError("dual-cone gas requires its selected resolved geometry")
    z = geometry["geometry_mm"]["second_cone"]["aperture_reference_z_mm"]
    if type(z) not in (int, float) or not math.isfinite(z):
        raise ValueError("second-cone aperture reference must be finite")
    species = resolve_nitrogen(author["species_ref"])
    model = resolve_sds_model(author["collision_model_ref"])
    return {"environment_id": author["environment_id"], "species_data": species, "collision_model": model,
            "transport_data": dict(NITROGEN_TRANSPORT),
            "temperature_k": author["temperature_k"], "inlet_pressure_pa": author["inlet_pressure_pa"],
            "outlet_pressure_pa": author["outlet_pressure_pa"], "rear_start_z_mm": z,
            "rear_axial_velocity_m_per_s": rear["axial_velocity_m_per_s"],
            "rear_radial_velocity_m_per_s": rear["radial_velocity_m_per_s"],
            "boltzmann_constant_j_per_k": CONSTANTS["boltzmann_constant_j_k"],
            "constants_version": CONSTANTS["version"]}


def project_dual_cone_flow_science(science: dict, conditions: dict) -> dict:
    """Materialize the native flow view from model-only science and environment."""
    if science.get("schema_version") != 2 or science.get("role") != "dual_cone_axisymmetric_gas_flow_science_contract":
        raise ValueError("current dual-cone flow model schema is required")
    result = copy.deepcopy(science)
    gas = result["physics"]["gas_species"]
    continuum = result["continuum_scope"]
    inlet = result["boundary_conditions"]["inlet"]
    outlet = result["boundary_conditions"]["outlet"]
    if ({"species_id", "molar_mass_kg_per_mol", "universal_gas_constant_j_per_mol_k", "boltzmann_constant_j_per_k",
         "specific_heat_ratio", "specific_heat_capacity_cp_j_per_kg_k"} & set(gas)
            or {"dynamic_viscosity_pa_s", "thermal_conductivity_w_per_m_k"} & set(result["physics"]["transport_model"])
            or "n2_molecular_collision_diameter_m" in continuum
            or {"static_pressure_pa", "temperature_k"} & set(inlet) or "static_pressure_pa" in outlet):
        raise ValueError("dual-cone model science must not duplicate environment or species values")
    species = conditions["species_data"]
    if conditions["outlet_pressure_pa"] <= 0:
        raise ValueError("compressible gas-flow outlet pressure must be positive")
    transport = conditions["transport_data"]
    if species != dict(NITROGEN) or transport != dict(NITROGEN_TRANSPORT) or transport["species_id"] != species["species_id"]:
        raise ValueError("flow transport data differs from the current nitrogen authority")
    gas.update(species_id=species["species_id"], molar_mass_kg_per_mol=species["molar_mass_kg_per_mol"],
               universal_gas_constant_j_per_mol_k=CONSTANTS["boltzmann_constant_j_k"] * species["avogadro_constant_per_mol"],
               boltzmann_constant_j_per_k=CONSTANTS["boltzmann_constant_j_k"],
               specific_heat_ratio=transport["specific_heat_ratio"],
               specific_heat_capacity_cp_j_per_kg_k=transport["specific_heat_capacity_cp_j_per_kg_k"])
    result["physics"]["transport_model"].update(
        dynamic_viscosity_pa_s=transport["dynamic_viscosity_pa_s"],
        thermal_conductivity_w_per_m_k=transport["thermal_conductivity_w_per_m_k"])
    continuum["n2_molecular_collision_diameter_m"] = species["effective_hard_sphere_diameter_m"]
    inlet.update(static_pressure_pa=conditions["inlet_pressure_pa"], temperature_k=conditions["temperature_k"])
    outlet["static_pressure_pa"] = conditions["outlet_pressure_pa"]
    result["gas_environment_identity"] = {"environment_id": conditions["environment_id"],
        "species_version": species["version"], "species_sha256": species["dataset_sha256"],
        "transport_version": transport["version"], "transport_sha256": transport["dataset_sha256"],
        "transport_limitation": transport["limitation"],
        "constants_version": conditions["constants_version"]}
    return result


def project_dual_cone_transport_science(science: dict, conditions: dict) -> dict:
    """Materialize SDS parameters from the same environment and material view."""
    if science.get("schema_version") != 2 or science.get("role") != "dual_cone_simion_ion_transport_science":
        raise ValueError("current dual-cone transport model schema is required")
    result = copy.deepcopy(science)
    gas = result["gas"]
    forbidden = {"species_id", "temperature_k", "collision_model", "collision_gas_mass_amu", "collision_gas_diameter_nm"}
    if forbidden & set(gas):
        raise ValueError("dual-cone transport model must not duplicate gas environment or species values")
    species, model = conditions["species_data"], conditions["collision_model"]
    if species != dict(NITROGEN) or model != dict(SDS_MODEL):
        raise ValueError("transport species or collision model differs from the shared authority")
    gas.update(species_id=species["species_id"], temperature_k=conditions["temperature_k"],
        collision_model=model["model_id"], collision_gas_mass_amu=species["mass_amu"],
        collision_gas_diameter_nm=species["effective_hard_sphere_diameter_nm"])
    result["gas_environment_identity"] = {"environment_id": conditions["environment_id"],
        "species_version": species["version"], "species_sha256": species["dataset_sha256"],
        "model_version": model["version"], "model_sha256": model["dataset_sha256"]}
    return result
