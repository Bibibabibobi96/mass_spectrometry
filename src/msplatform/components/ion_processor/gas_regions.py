"""The IP's declared HP/LP prescribed bath in its mechanical local frame."""
from __future__ import annotations

from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasRegion, GasSource, GasSpecies, GasState
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.contracts.gas_species import HS1_EXAMPLE_ASSUMPTION, NITROGEN, project_nitrogen_hs1_assumption
from msplatform.contracts.gas_environment import GasEnvironment


def project_ip_baseline(author: dict, baseline: dict) -> dict:
    """Produce a native compatibility view from the sole experimental authority."""
    if not isinstance(baseline, dict) or baseline.get("schema_version") != 2 or "gas" in baseline:
        raise ValueError("current IP baseline must reference the separate gas environment")
    required = {"schema_version", "environment_id", "species_ref", "collision_model_ref",
                "temperature_k", "bulk_velocity_m_s", "regions", "background"}
    if not isinstance(author, dict) or set(author) not in (required, required | {"outer_state"}) or author["schema_version"] != 1:
        raise ValueError("unsupported IP gas environment author contract")
    if author["environment_id"] != "ion_processor_prescribed_n2_v1" or author["background"] != "prescribed_zero_pressure_collision_omission":
        raise ValueError("unsupported IP gas environment identity or background")
    expected = [("hp", "guide_end", "hp_end"), ("lp", "hp_end", "query_domain_end")]
    regions = author["regions"]
    if (not isinstance(regions, list) or len(regions) != 2
            or any(not isinstance(row, dict) or set(row) != {"region_id", "start_ref", "end_ref", "pressure_pa"} for row in regions)
            or [(row["region_id"], row["start_ref"], row["end_ref"]) for row in regions] != expected):
        raise ValueError("IP gas regions must reference the declared HP/LP geometry")
    view = project_nitrogen_hs1_assumption(author["species_ref"], author["collision_model_ref"])
    projected = {**baseline, "gas": {"temperature_k": author["temperature_k"],
        "mass_amu": view["gas_mass_amu"], "hp_pressure_pa": regions[0]["pressure_pa"],
        "lp_pressure_pa": regions[1]["pressure_pa"], "cross_section_m2": view["cross_section_m2"],
        "mean_free_path_mm": -1}}
    velocity = author["bulk_velocity_m_s"]
    if velocity != [0, 0, 0]:
        raise ValueError("IP prescribed bath supports explicit stationary gas only")
    for row in regions:
        pressure = row["pressure_pa"]
        GasState("vacuum" if pressure == 0 else "gas", pressure, author["temperature_k"], velocity)
    return projected


def resolve_ip_environment(author: dict, baseline: dict, *, domain: BoxDomain) -> GasEnvironment:
    """Resolve explicit experiment and geometry references against this query domain."""
    projected = project_ip_baseline(author, baseline)
    field = _build_gas_field_spec(projected, domain=domain)
    ref = {"gas_field_id": field.field_id, **author["collision_model_ref"]}
    return GasEnvironment("gas", (field,), (ref,))


def resolve_ip_continuous_environment(author: dict, baseline: dict, *, bath_domain: BoxDomain,
                                      outer_domain: BoxDomain) -> GasEnvironment:
    """Resolve both continuous-field views from the same frozen experiment author."""
    if not isinstance(outer_domain, BoxDomain):
        raise ValueError("continuous IP gas requires an explicit outer query domain")
    bath = resolve_ip_environment(author, baseline, domain=bath_domain).fields[0]
    state = author.get("outer_state")
    if not isinstance(state, dict) or set(state) != {"pressure_pa", "temperature_k", "bulk_velocity_m_s"}:
        raise ValueError("continuous IP gas requires explicitly authored outer_state")
    pressure = state["pressure_pa"]
    value = GasState("vacuum" if pressure == 0 else "gas", pressure,
                     state["temperature_k"], tuple(state["bulk_velocity_m_s"]))
    outer = GasFieldSpec(field_id="ion_processor_outer_bath_v1", frame_id=bath.frame_id,
        representation="uniform", composition_id=bath.composition_id, composition=bath.composition,
        domain=outer_domain, source=GasSource("prescribed", "ip_experiment_gas_environment_v1",
            ("Explicit outer state from the same IP experimental gas environment",)), uniform_state=value)
    refs = tuple({"gas_field_id": field.field_id, **author["collision_model_ref"]} for field in (bath, outer))
    return GasEnvironment("gas", (bath, outer), refs)


def project_ip_resolved_gas_view(frozen_environment: dict) -> dict:
    """Recover the unique HS1 view from an authenticated resolved IP environment."""
    environment = GasEnvironment.from_dict(frozen_environment)
    if environment.status != "gas" or len(environment.fields) not in (1, 2):
        raise ValueError("IP HS1 requires its resolved bath and optional outer view")
    field = environment.fields[0]
    ref = environment.collision_model_refs[0]
    if len(environment.fields) == 2:
        outer, outer_ref = environment.fields[1], environment.collision_model_refs[1]
        if (outer.field_id != "ion_processor_outer_bath_v1" or outer.representation != "uniform"
                or outer.frame_id != field.frame_id or outer.composition != field.composition
                or outer_ref["model_id"] != ref["model_id"] or outer_ref["version"] != ref["version"]):
            raise ValueError("IP outer gas must share the selected environment and collision model")
    if (field.field_id != "ion_processor_prescribed_bath_v1" or field.representation != "piecewise_uniform"
            or [region.region_id for region in field.regions] != ["hp", "lp"]
            or ref["model_id"] != HS1_EXAMPLE_ASSUMPTION["model_id"]
            or ref["version"] != HS1_EXAMPLE_ASSUMPTION["version"]):
        raise ValueError("resolved environment is not the current IP HS1 bath")
    hp, lp = (region.state for region in field.regions)
    if (hp.temperature_k != lp.temperature_k or hp.bulk_velocity_m_s != (0, 0, 0)
            or lp.bulk_velocity_m_s != (0, 0, 0) or field.background_state.status != "vacuum"
            or field.background_state.temperature_k != hp.temperature_k
            or field.background_state.bulk_velocity_m_s != (0, 0, 0)):
        raise ValueError("IP bath requires one temperature and stationary background")
    return {"temperature_k": hp.temperature_k, "mass_amu": field.composition[0].mass_amu,
            "hp_pressure_pa": hp.pressure_pa, "lp_pressure_pa": lp.pressure_pa,
            "cross_section_m2": HS1_EXAMPLE_ASSUMPTION["cross_section_m2"], "mean_free_path_mm": -1}


def _build_gas_field_spec(baseline: dict, *, domain: BoxDomain) -> GasFieldSpec:
    """Project explicit IP geometry/gas onto the actual finite query domain, in mm.

    LP continues beyond its nominal electrode length to this domain's downstream
    boundary. Exterior-to-bath vacuum is a prescribed omission of collisions,
    not measured vacuum; unavailable points outside the PA are not zero-filled.
    """
    if not isinstance(domain, BoxDomain):
        raise ValueError("IP gas requires its explicit native query BoxDomain")
    geometry, gas = baseline["geometry"], baseline["gas"]
    if (baseline.get("schema_version") != 2 or gas.get("mass_amu") != NITROGEN["mass_amu"]
            or gas.get("cross_section_m2") != HS1_EXAMPLE_ASSUMPTION["cross_section_m2"]):
        raise ValueError("IP gas view differs from the current N2/HS1 assumption authorities")
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
        composition_id="n2",
        composition=(GasSpecies("n2", gas["mass_amu"], 1),),
        domain=domain, source=GasSource("prescribed_proxy", "ip_experiment_gas_environment_v1",
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
