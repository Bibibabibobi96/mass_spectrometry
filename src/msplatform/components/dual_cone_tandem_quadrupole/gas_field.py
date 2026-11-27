"""Explicit dual-cone gas-source projections; no Lua, tools or file writes."""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from msplatform.contracts.gas import (
    AxisymmetricGasRegion, AxisymmetricGasValues, AxisymmetricRZData,
    CylindricalDomain, GasFieldSpec, GasSource, GasSpecies,
)
from msplatform.contracts.gas_field import GasFieldData
from msplatform.gas.field import GasField, prepare_gas_field
from msplatform.io.manifest_records import validate_file_record
from .gas_field_validation import validate_gas_field_data


def _contract(interface: Mapping[str, Any]) -> dict[str, Any]:
    if interface.get("schema_version") != 2 or interface.get("role") != "dual_cone_simion_gas_field_interface":
        raise ValueError("current joint gas interface version 2 required")
    contract = copy.deepcopy(interface["runtime_artifact_contract"])
    if contract["manifest_schema_version"] != 2 or contract["runtime_lua_required_functions"] != ["sample", "_sample_sds"]:
        raise ValueError("current joint gas runtime ABI required")
    return contract


def _domain(values: Mapping[str, Any]) -> CylindricalDomain:
    return CylindricalDomain(values["minimum_z_mm"], values["maximum_z_mm"],
                             values["maximum_radius_mm"], values["minimum_radius_mm"])


def runtime_support_domain(interface: Mapping[str, Any], source_kind: str) -> CylindricalDomain:
    """Resolve this study's recorded sampling envelope, without opening data."""
    contract = _contract(interface)
    declared = _domain(contract["domain"])
    policy = contract["sampling_policies"][source_kind]
    if source_kind == "validated_comsol_axisymmetric_rz":
        if policy != dict(sampling_profile="legacy_sqrt_v1", axis_projection_policy="legacy_axis_projection_v1",
                          envelope_policy="strict_cylindrical_v1", outside_domain_policy="error",
                          interpolation_policy="bilinear_fluid_corner_weight_renormalization_v1"):
            raise ValueError("recorded CFD requires its explicit legacy sampling policy")
        return declared
    if source_kind != "prescribed_uniform_rear_gas":
        raise ValueError("unsupported dual-cone gas source")
    if (policy["sampling_profile"] != "legacy_sqrt_v1" or policy["outside_domain_policy"] != "coverage_loss"
            or policy["boundary_padding_mm"] != 1e-6
            or policy["interpolation_policy"] != "piecewise_constant_cylindrical_components_v1"):
        raise ValueError("named uniform control requires its explicit legacy sampling arithmetic")
    if policy["envelope_policy"] == "legacy_uniform_padded_v1":
        if declared.minimum_radius_mm != 0:
            raise ValueError("nonzero uniform inner radius requires explicit annular successor policy")
    elif policy["envelope_policy"] != "uniform_annular_padded_v2":
        raise ValueError("unsupported uniform envelope policy")
    padding = policy["boundary_padding_mm"]
    return CylindricalDomain(declared.minimum_z_mm-padding, declared.maximum_z_mm+padding,
        declared.maximum_radius_mm+padding, max(0., declared.minimum_radius_mm-padding))


def _metadata(field: GasField, interface, contract, source, policy) -> dict[str, Any]:
    domain = field.spec.domain
    return {
        "schema_version": 2, "role": contract["manifest_role"], "project_id": interface["project_id"],
        "source": source, "coordinate_frame": contract["coordinate_frame"],
        "domain": copy.deepcopy(contract["domain"]), "interpolation_policy": policy["interpolation_policy"],
        "sampling": copy.deepcopy(policy),
        "support_domain": dict(minimum_z_mm=domain.minimum_z_mm, maximum_z_mm=domain.maximum_z_mm,
            minimum_radius_mm=domain.minimum_radius_mm, maximum_radius_mm=domain.maximum_radius_mm),
        "field_id": field.spec.field_id,
    }


def prepare_cfd_gas_field(
    data: GasFieldData,
    *,
    interface: Mapping[str, Any],
    source_records: Mapping[str, Mapping[str, Any]],
    producer_reference: Mapping[str, Any] | None = None,
) -> tuple[GasField, dict[str, Any]]:
    """Project original accepted CFD data and its actual record identities."""
    validate_gas_field_data(data)
    contract = _contract(interface)
    policy = contract["sampling_policies"]["validated_comsol_axisymmetric_rz"]
    domain = runtime_support_domain(interface, "validated_comsol_axisymmetric_rz")
    if domain.minimum_z_mm < data.z_values_mm[0] or domain.maximum_z_mm > data.z_values_mm[-1]:
        raise ValueError("validated COMSOL field does not cover the governed axial domain")
    if domain.minimum_radius_mm < data.r_values_mm[0] or domain.maximum_radius_mm > data.r_values_mm[-1]:
        raise ValueError("validated COMSOL field does not cover the governed radial domain")
    documents = data.documents
    science = documents["science"]
    species = science["physics"]["gas_species"]
    # The source declares kg/mol. The numerical g/mol mass convention expresses
    # that same molecular mass in u; SDS still consumes its separate actual
    # transport-science mass/diameter/diffusion, never this metadata projection.
    composition = (GasSpecies(species["species_id"], species["molar_mass_kg_per_mol"]*1000., 1.),)
    metadata_record = validate_file_record(source_records["field_metadata"], "gas source metadata")
    if producer_reference is not None:
        if (not isinstance(producer_reference, Mapping) or set(producer_reference) != {"manifest", "product_id"}
                or not isinstance(producer_reference["product_id"], str) or not producer_reference["product_id"].strip()):
            raise ValueError("explicit producer reference is malformed")
        validate_file_record(producer_reference["manifest"], "gas source manifest")
    names = ("p_pa", "temperature_k", "u_r_m_per_s", "u_z_m_per_s")
    arrays = [tuple(value if data.fluid_mask[index] else None for index, value in enumerate(data.columns[name]))
              for name in names]
    grid = AxisymmetricRZData(data.r_values_mm, data.z_values_mm,
        tuple(bool(value) for value in data.fluid_mask), *arrays,
        axis_projection_policy=policy["axis_projection_policy"])
    spec = GasFieldSpec(field_id=science["model_id"], frame_id=contract["coordinate_frame"]["frame_id"],
        representation="axisymmetric_rz_grid", composition_id=species["species_id"], composition=composition,
        domain=domain, source=GasSource("published_cfd", science["model_id"],
        (science["claim_scope"],), metadata_record),
        interpolation_policy="bilinear_fluid_corner_weight_renormalization_v1",
        sampling_profile=policy["sampling_profile"])
    field = prepare_gas_field(spec, data=grid)
    source = dict(kind="validated_comsol_axisymmetric_rz",
        producer_reference=None if producer_reference is None else copy.deepcopy(dict(producer_reference)),
        field_csv=copy.deepcopy(dict(source_records["field_csv"])),
        metadata=copy.deepcopy(dict(source_records["field_metadata"])),
        source_contract_records={name: copy.deepcopy(dict(source_records[name])) for name in ("science", "numerics", "geometry")},
        source_contract_sha256=documents["metadata"]["source_contract_sha256"])
    return field, _metadata(field, interface, contract, source, policy)


def prepare_uniform_rear_gas_field(
    spec: Mapping[str, Any],
    *,
    interface: Mapping[str, Any],
    composition: Sequence[GasSpecies],
    spec_record: Mapping[str, Any],
    interface_record: Mapping[str, Any],
) -> tuple[GasField, dict[str, Any]]:
    """Keep the named control and all its legal cylindrical scalar values."""
    if spec.get("role") != "dual_cone_uniform_rear_gas_field":
        raise ValueError("explicit uniform rear-gas study required")
    contract = _contract(interface)
    rear, upstream = spec["rear_region"], spec["upstream_collision_proxy"]
    model_id = spec.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("an explicit uniform gas study model_id is required")
    if model_id == "uniform_400pa_plug_flow_prototype_v1" and rear["pressure_pa"] != 400.:
        raise ValueError("the frozen minimal prototype requires a 400 Pa rear region")
    declared = _domain(contract["domain"])
    if not declared.minimum_z_mm <= rear["start_z_mm"] <= declared.maximum_z_mm:
        raise ValueError("rear-region start lies outside the gas-field domain")
    policy = contract["sampling_policies"]["prescribed_uniform_rear_gas"]
    effective = runtime_support_domain(interface, "prescribed_uniform_rear_gas")
    def values(pressure, radial, axial):
        return AxisymmetricGasValues("vacuum" if pressure == 0 else "gas", pressure,
                                     rear["temperature_k"], radial, axial)
    source = GasSource("prescribed_proxy", spec["model_id"],
        (spec["claim_scope"], upstream["interpretation"]), validate_file_record(spec_record, "uniform gas source"))
    definition = GasFieldSpec(field_id=spec["model_id"], frame_id=contract["coordinate_frame"]["frame_id"],
        representation="axisymmetric_piecewise_uniform", composition_id=spec["model_id"]+":composition",
        composition=tuple(composition), domain=effective, source=source,
        axisymmetric_regions=(AxisymmetricGasRegion("rear", rear["start_z_mm"], effective.maximum_z_mm,
            True, True, values(rear["pressure_pa"], rear["radial_velocity_m_per_s"], rear["axial_velocity_m_per_s"])),),
        axisymmetric_background=values(upstream["pressure_pa"], 0., 0.), sampling_profile=policy["sampling_profile"])
    field = prepare_gas_field(definition)
    origin = dict(kind="prescribed_uniform_rear_gas", spec_record=copy.deepcopy(dict(spec_record)),
                  interface_record=copy.deepcopy(dict(interface_record)))
    return field, _metadata(field, interface, contract, origin, policy)
