"""Independent downstream TOF provider descriptor."""
from collections.abc import Mapping
from typing import Any

from msplatform.components.registry import ProviderDescriptor
from msplatform.contracts.machine_contracts import ContractError
from .provider import resolve_component
from .geometry import resolve_downstream_geometry
from .geometry_members import iter_downstream_members


def resolve(design: Mapping[str, Any], profile: str | None) -> tuple[dict, dict]:
    """Resolve explicit downstream source data through its sole provider."""
    result = resolve_component(design, geometry_profile_id=profile)
    return result["resolved_design"], result["assembly_interface"]


def validate(source: Mapping[str, Any], resolved: Mapping[str, Any], interface: Mapping[str, Any]) -> None:
    """Reject a component whose derived geometry or interface was altered."""
    expected, canonical = resolve(source, interface.get("geometry_profile_id"))
    if resolved != expected or interface != canonical:
        raise ContractError("single_reflection_tof design or interface differs from its source")


def members(resolved: Mapping[str, Any], interface: Mapping[str, Any]) -> tuple[dict, ...]:
    """Return physical downstream members in their explicit provider frame."""
    physical = resolve_downstream_geometry(resolved["geometry_mm"], resolved["coordinate_convention"],
                                           resolved["rings"], resolved["electrodes_v"])
    return iter_downstream_members(physical, frame=interface["local_frame_id"])


DESCRIPTOR = ProviderDescriptor("single_reflection_tof", "single_reflection_tof", resolve, validate, members,
                                ("msplatform.components.single_reflection_tof", "msplatform.components.rf_multipole"))
