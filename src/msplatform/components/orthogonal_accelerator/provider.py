"""Independent two/three-zone OA component resolution without repository I/O."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .assembly_interface import build_assembly_interface
from .sectioned_geometry import resolve_bare_three_zone_component
from .two_zone_geometry import resolve_closed_two_zone_geometry


def resolve_component(design: Mapping[str, Any], *, geometry_profile_id: str | None = None) -> dict[str, Any]:
    """Resolve explicit OA requirements and physical profile content, with no native action."""
    if not isinstance(design, Mapping) or set(design) - {"requirements", "geometry_profile"} or "requirements" not in design:
        raise ValueError("OA design requires requirements and optional geometry_profile content")
    requirements = design["requirements"]
    if not isinstance(requirements, Mapping):
        raise ValueError("OA requirements must be a mapping")
    variant = requirements.get("variant_id")
    if variant == "two_zone":
        if not isinstance(geometry_profile_id, str) or not geometry_profile_id:
            raise ValueError("two-zone OA requires an explicit geometry_profile_id")
        if "geometry_profile" not in design:
            raise ValueError("two-zone OA requires explicit geometry_profile content")
        model = resolve_closed_two_zone_geometry(requirements, geometry_profile_id=geometry_profile_id,
                                                geometry_profile=design["geometry_profile"])
        resolved = {**model.as_dict(), "schema_version": 1, "role": "orthogonal_accelerator_two_zone_geometry",
                    "variant_id": "two_zone", "geometry_profile_id": geometry_profile_id}
    elif variant == "three_zone":
        if geometry_profile_id is not None or "geometry_profile" in design:
            raise ValueError("three-zone OA uses explicit sectioned requirements, not a geometry profile")
        resolved = resolve_bare_three_zone_component(dict(requirements))
    else:
        raise ValueError("OA provider requires two_zone or three_zone")
    interface = build_assembly_interface(resolved, geometry_profile_id=geometry_profile_id)
    return dict(resolved_design=resolved, assembly_interface=interface)
