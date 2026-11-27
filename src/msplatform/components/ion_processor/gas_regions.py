"""The IP's declared HP/LP prescribed bath in its mechanical local frame."""
from __future__ import annotations

from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasRegion, GasSource, GasSpecies, GasState
from msplatform.contracts.rigid_transform import RigidTransform


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


def validate_continuous_hs1_gas(bath: GasFieldSpec, outer: GasFieldSpec, *, gas_mass_amu: float) -> None:
    """Check two explicit field authorities against one HS1 collision gas.

    Domain coverage and immutable source records remain the caller's duties.
    """
    if not isinstance(bath, GasFieldSpec) or not isinstance(outer, GasFieldSpec):
        raise ValueError("continuous HS1 requires explicit bath and outer gas fields")
    if bath.frame_id != outer.frame_id or bath.composition_id != outer.composition_id:
        raise ValueError("continuous HS1 gas frames and composition identities must agree")
    if bath.composition != outer.composition or len(bath.composition) != 1:
        raise ValueError("continuous HS1 requires the same explicit single gas species")
    if type(gas_mass_amu) not in (int, float) or gas_mass_amu <= 0 or bath.composition[0].mass_amu != gas_mass_amu:
        raise ValueError("continuous HS1 gas mass differs from the selected species")


def validate_continuous_parent_coverage(outer: GasFieldSpec, *, placement: RigidTransform, parent_domain: BoxDomain) -> None:
    """Require explicit outer coverage of the complete transformed parent box."""
    from itertools import product
    from msplatform.contracts.rigid_transform import FramedPosition
    from msplatform.gas.field import _inside

    if (not isinstance(outer, GasFieldSpec) or not isinstance(outer.domain, BoxDomain)
            or outer.representation != "uniform"):
        raise ValueError("continuous HS1 outer coverage requires an explicit box field")
    if not isinstance(placement, RigidTransform) or placement.from_frame_id != outer.frame_id:
        raise ValueError("continuous HS1 gas placement differs from its local frame")
    if not isinstance(parent_domain, BoxDomain):
        raise ValueError("continuous HS1 requires the explicit parent box")
    if (outer.uniform_state.status not in {'gas', 'vacuum'}
            or outer.uniform_state.temperature_k is None
            or outer.uniform_state.bulk_velocity_m_s is None):
        raise ValueError("continuous HS1 outer state must provide gas or vacuum temperature and velocity")
    inverse = placement.inverse()
    for point in product(*zip(parent_domain.minimum_mm, parent_domain.maximum_mm, strict=True)):
        local = inverse.transform_position(FramedPosition(placement.to_frame_id, point))
        if not _inside(outer.domain, local.coordinates_mm):
            raise ValueError("continuous HS1 outer gas field does not cover the complete parent box")
