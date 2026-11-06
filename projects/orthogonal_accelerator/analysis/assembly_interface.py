"""Project configuration loader for the installed OA mechanical provider."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from msplatform.components.orthogonal_accelerator.assembly_interface import (
    resolve_assembly_interface as _resolve_installed,
)
from .two_zone_geometry import load_geometry_profile


def resolve_assembly_interface(requirements: Mapping[str, Any], *, geometry_profile_id: str | None,
                               schema_version: int = 3) -> dict[str, Any]:
    """Load the declared project profile, then delegate the unique mechanical implementation."""
    if not isinstance(requirements, Mapping):
        raise ValueError("assembly requirements must be an object")
    profile = None
    if requirements.get("variant_id") == "two_zone":
        profile = load_geometry_profile(geometry_profile_id)
    return _resolve_installed(requirements, geometry_profile_id=geometry_profile_id,
                              schema_version=schema_version, geometry_profile=profile)
