"""The IP's declared HP/LP prescribed bath in its mechanical local frame."""
from __future__ import annotations

from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasRegion, GasSource, GasSpecies, GasState


def build_gas_field_spec(baseline: dict, *, domain: BoxDomain) -> GasFieldSpec:
    """Project explicit IP geometry/gas onto the actual finite query domain, in mm.

    LP continues beyond its nominal electrode length to this domain's downstream
    boundary. Exterior-to-bath vacuum is a prescribed omission of collisions,
    not measured vacuum; unavailable points outside the PA are not zero-filled.
    """
    if not isinstance(domain, BoxDomain):
        raise ValueError("IP gas requires its explicit native query BoxDomain")
    geometry, gas = baseline["geometry"], baseline["gas"]
    start = geometry["guide_length_mm"]
    interface = start + geometry["hp_length_mm"]
    radius = geometry["r0_mm"]
    if not domain.minimum_mm[0] < start < interface < domain.maximum_mm[0]:
        raise ValueError("IP query domain must cover both declared gas regions")
    def state(pressure):
        return GasState("vacuum" if pressure == 0 else "gas", pressure,
                        gas["temperature_k"], (0, 0, 0))
    return GasFieldSpec(field_id="ion_processor_prescribed_bath_v1",
        frame_id=baseline["clock"]["frame_id"], representation="piecewise_uniform",
        composition_id="ion_processor_explicit_single_gas",
        composition=(GasSpecies("ion_processor_model_gas", gas["mass_amu"], 1),),
        domain=domain, source=GasSource("prescribed_proxy", "selected_ip_baseline_gas",
            ("Prescribed HP/LP pressures, not a solved or measured gas field",
             "Outside the finite bath, collisions are omitted within the declared query domain")),
        regions=(
            GasRegion("hp", BoxDomain((start, -radius, -radius), (interface, radius, radius),
                (True, False, False), (False, False, False)), state(gas["hp_pressure_pa"])),
            GasRegion("lp", BoxDomain((interface, -radius, -radius), (domain.maximum_mm[0], radius, radius),
                (True, False, False), (domain.upper_closed[0], False, False)), state(gas["lp_pressure_pa"]))),
        background_state=GasState("vacuum", 0, gas["temperature_k"], (0, 0, 0)))


def build_cooled_gas_field_spec(conditioner: dict, *, pressure_scale: float,
                               domain: BoxDomain) -> GasFieldSpec:
    """Project the existing finite cooled bath, retaining its explicit 0/1 control.

    Domain is the caller's entire carrier coverage in conditioner-native mm,
    not the bath or metal box. Release voltages do not change this static field.
    """
    if type(pressure_scale) not in (int, float) or pressure_scale not in (0, 1):
        raise ValueError("cooled pressure control must be exactly zero or one")
    if not isinstance(domain, BoxDomain):
        raise ValueError("cooled gas requires its explicit carrier query BoxDomain")
    gas = conditioner["gas"]
    parameters, bath = gas["parameters"], gas["domain_native_mm"]
    pressure = parameters["hp_pressure_pa"] * pressure_scale
    radius = bath["transverse_halfwidth"]
    state = GasState("gas" if pressure > 0 else "vacuum", pressure,
                     parameters["temperature_k"], (0, 0, 0))
    return GasFieldSpec(field_id="cooled_frontend_prescribed_bath_v1",
        frame_id=conditioner["native_projection_fragment"]["frame_id"], representation="piecewise_uniform",
        composition_id="cooled_frontend_explicit_single_gas",
        composition=(GasSpecies("cooled_frontend_model_gas", parameters["mass_amu"], 1),),
        domain=domain, source=GasSource("prescribed_proxy", "selected_cooled_conditioner_gas",
            ("Finite prescribed HP bath; not a solved or measured gas field",
             "Outside the bath, collisions are omitted within the carrier query domain")),
        regions=(GasRegion("cooled_bath", BoxDomain((bath["x_min"], -radius, -radius),
            (bath["x_max"], radius, radius), (True, False, False), (False, False, False)), state),),
        background_state=GasState("vacuum", 0, parameters["temperature_k"], (0, 0, 0)))
