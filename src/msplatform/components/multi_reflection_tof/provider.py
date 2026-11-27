"""Explicit MR physical design resolution without repository I/O."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from msplatform.contracts.rigid_transform import RigidTransform
from .assembly_interface import resolve_assembly_interface
from .candidate_contract import validate_contract
from .resolved_geometry import resolve_geometry


def resolve_component(design: Mapping[str, Any], *, geometry_profile_id: str | None = None) -> dict[str, Any]:
    """Resolve the complete explicit MR and selected OA physical authorities."""
    required = {"contract", "accelerator_requirements", "geometry_profile"}
    optional = {"inherited_dual_stripe_topology_contract", "accelerator_to_mr"}
    if not isinstance(design, Mapping) or not required <= set(design) or set(design) - required - optional:
        raise ValueError("MR design requires the candidate contract and explicit OA requirements and profile")
    placement = design.get("accelerator_to_mr")
    if placement is not None:
        if not isinstance(placement, Mapping):
            raise ValueError("MR accelerator_to_mr must be a rigid-transform contract")
        placement = RigidTransform.from_contract(placement)
    resolved = resolve_geometry(
        validate_contract(design["contract"]), accelerator_requirements=design["accelerator_requirements"],
        geometry_profile=design["geometry_profile"], geometry_profile_id=geometry_profile_id,
        inherited_dual_stripe_topology_contract=design.get("inherited_dual_stripe_topology_contract"),
        accelerator_to_mr=placement,
    )
    interface = resolve_assembly_interface(resolved, geometry_profile_id=geometry_profile_id, schema_version=3)
    return {"resolved_design": resolved, "assembly_interface": interface}
