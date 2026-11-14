"""Explicit provider dispatch and cross-object component validation."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from msplatform.contracts.machine_contracts import ContractError
from .model import ResolvedComponent


def _component_interface(provider: str, resolved: dict[str, Any], profile: str | None) -> dict[str, Any]:
    """Derive the public interface from the same complete provider design."""
    if provider == "dual_pressure_rectilinear_ion_processor":
        from msplatform.components.dual_pressure_rectilinear_ion_processor.assembly_interface import build_assembly_interface
        return build_assembly_interface(resolved, geometry_profile_id=profile)
    if provider == "parallel_mirror_dual_stripe_mr_tof":
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.assembly_interface import resolve_assembly_interface
        return resolve_assembly_interface(resolved, geometry_profile_id=profile, schema_version=3)
    if provider == "rf_multipole":
        from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
        return build_assembly_interface(resolved, geometry_profile_id=profile)
    if provider == "orthogonal_accelerator":
        from msplatform.components.orthogonal_accelerator.assembly_interface import build_assembly_interface
        return build_assembly_interface(resolved, geometry_profile_id=profile)
    if provider == "single_reflection_oa_tof":
        if type(resolved.get("schema_version")) is not int or resolved["schema_version"] != 1:
            raise ContractError("unsupported TOF resolved design version")
        if resolved.get("role") != "oa_tof_resolved_contract_do_not_edit":
            raise ContractError("unsupported TOF resolved design role")
        from msplatform.components.single_reflection_oa_tof.accelerator_geometry import (
            apply_side_opening, resolve_accelerator_geometry,
        )
        from msplatform.components.single_reflection_oa_tof.assembly_interface import resolve_assembly_interface
        projection = apply_side_opening(resolve_accelerator_geometry(resolved, variant_id="three_zone_square"),
                                       side_opening=resolved["mechanical_side_opening"])
        return resolve_assembly_interface(resolved, projection=projection, geometry_profile_id=profile)
    if provider == "dual_cone_tandem_quadrupole":
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.assembly_interface import build_assembly_interface
        return build_assembly_interface(resolved, geometry_profile_id=profile)
    raise ContractError(f"unsupported component provider for this installed slice: {provider}")


def _from_provider(provider: str, resolved: Mapping[str, Any], interface: Mapping[str, Any],
                   *, source_design: Mapping[str, Any]) -> ResolvedComponent:
    """Validate provider outputs before constructing the neutral data object."""
    design = copy.deepcopy(dict(resolved))
    interface = copy.deepcopy(dict(interface))
    canonical = _component_interface(provider, design, interface.get("geometry_profile_id"))
    if canonical != interface:
        raise ContractError(f"{provider}: assembly interface differs from the resolved design")
    if provider == "rf_multipole":
        from msplatform.components.rf_multipole.compile_design_request import compile_design_request
        if not isinstance(source_design, Mapping):
            raise ContractError("RF resolved design requires its explicit source request")
        expected = compile_design_request(source_design, expected_identity=design["identity"],
                                          source_records=design["sources"])
        if expected != design:
            raise ContractError("RF resolved design differs from its explicit source request")
    if provider == "parallel_mirror_dual_stripe_mr_tof":
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.provider import resolve_component as resolve
        expected = resolve(source_design, geometry_profile_id=interface["geometry_profile_id"])
        if expected["resolved_design"] != design:
            raise ContractError("MR resolved design differs from its explicit source authorities")
    if provider == "dual_pressure_rectilinear_ion_processor":
        from msplatform.components.dual_pressure_rectilinear_ion_processor.provider import resolve_component as resolve
        expected = resolve(source_design, geometry_profile_id=interface["geometry_profile_id"] )
        if expected["resolved_design"] != design:
            raise ContractError("IP resolved design differs from its explicit source authority")
    if provider == "orthogonal_accelerator":
        from msplatform.components.orthogonal_accelerator.provider import resolve_component as resolve
        expected = resolve(source_design, geometry_profile_id=interface["geometry_profile_id"])
        if expected["resolved_design"] != design:
            raise ContractError("OA resolved design differs from its source requirements and geometry profile")
    if provider == "single_reflection_oa_tof":
        if not isinstance(source_design, Mapping):
            raise ContractError("TOF resolved design requires its explicit source design documents")
        from msplatform.components.single_reflection_oa_tof.provider import resolve_component as resolve
        expected = resolve(source_design, geometry_profile_id=interface["geometry_profile_id"])
        if expected["resolved_design"] != design:
            raise ContractError("TOF resolved design differs from its source design documents")
    if provider == "dual_cone_tandem_quadrupole":
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry import resolve_geometry
        if (source_design.get("role") != "dual_cone_tandem_quadrupole_geometry_baseline"
                or source_design.get("schema_version") != 1
                or source_design.get("project_id") != "dual_cone_tandem_quadrupole_ion_interface"
                or resolve_geometry(dict(source_design)) != design):
            raise ContractError("dual-cone resolved geometry differs from its explicit source baseline")
    return ResolvedComponent(provider, design, interface, source_design=source_design)


def resolve_component(request: Mapping[str, Any]) -> ResolvedComponent:
    """Resolve one explicit supported provider request, without sampling or execution."""
    required = {"provider_id", "design"}
    if not isinstance(request, Mapping) or not required <= request.keys() or set(request) - required - {"geometry_profile_id"}:
        raise ContractError("component request requires provider_id and design; only geometry_profile_id is optional")
    design = copy.deepcopy(request["design"])
    profile = request.get("geometry_profile_id")
    provider = request["provider_id"]
    if provider == "parallel_mirror_dual_stripe_mr_tof":
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.provider import resolve_component as resolve
        result = resolve(design, geometry_profile_id=profile)
        resolved, interface = result["resolved_design"], result["assembly_interface"]
    elif provider == "dual_pressure_rectilinear_ion_processor":
        from msplatform.components.dual_pressure_rectilinear_ion_processor.provider import resolve_component as resolve
        result = resolve(design, geometry_profile_id=profile)
        resolved, interface = result["resolved_design"], result["assembly_interface"]
    elif provider == "rf_multipole":
        from msplatform.components.rf_multipole.compile_design_request import compile_design_request
        from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
        resolved = compile_design_request(design, expected_identity=design["identity"])
        interface = build_assembly_interface(resolved, geometry_profile_id=profile)
    elif provider == "orthogonal_accelerator":
        from msplatform.components.orthogonal_accelerator.provider import resolve_component as resolve
        result = resolve(design, geometry_profile_id=profile)
        resolved, interface = result["resolved_design"], result["assembly_interface"]
    elif provider == "single_reflection_oa_tof":
        from msplatform.components.single_reflection_oa_tof.provider import resolve_component as resolve
        result = resolve(design, geometry_profile_id=profile)
        resolved, interface = result["resolved_design"], result["assembly_interface"]
    elif provider == "dual_cone_tandem_quadrupole":
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry import resolve_geometry
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.assembly_interface import build_assembly_interface
        resolved = resolve_geometry(design)
        interface = build_assembly_interface(resolved, geometry_profile_id=profile)
    else:
        raise ContractError(f"unsupported component provider for this installed slice: {provider}")
    return _from_provider(provider, resolved, interface, source_design=design)
