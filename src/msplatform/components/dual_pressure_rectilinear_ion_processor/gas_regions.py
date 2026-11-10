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
