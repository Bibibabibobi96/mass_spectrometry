"""Project profile loading around the unique installed mechanical provider."""
from __future__ import annotations
import json
from pathlib import Path
from collections.abc import Mapping
from msplatform.components.orthogonal_accelerator.two_zone_geometry import (
    TwoZoneGeometryError as TwoZoneGeometryError,
    UniformRingPlaneLayout as UniformRingPlaneLayout,
    ShieldedRectangularEnclosure as ShieldedRectangularEnclosure,
    _positive as _positive,
    derive_uniform_ring_planes as derive_uniform_ring_planes,
    derive_shielded_rectangular_enclosure as derive_shielded_rectangular_enclosure,
    CLOSED_TWO_ZONE_PROFILE_ID as CLOSED_TWO_ZONE_PROFILE_ID,
    _GEOMETRY_PROFILE_KEYS as _GEOMETRY_PROFILE_KEYS,
    _REQUIRED_REQUEST_KEYS as _REQUIRED_REQUEST_KEYS,
    _mapping as _mapping,
    _finite_positive as _finite_positive,
    ClosedTwoZoneGeometry as ClosedTwoZoneGeometry,
    resolve_closed_two_zone_geometry as _resolve_geometry,
    validate_geometry_profile as validate_geometry_profile,
)

def load_geometry_profile(profile_id: str = CLOSED_TWO_ZONE_PROFILE_ID) -> Mapping[str, float | int]:
    """Load the sole component-owned physical profile from its frozen contract."""
    path = Path(__file__).parents[1] / "config" / "component_contract.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        profiles = document["geometry_profiles"]
        profile = profiles[profile_id]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise TwoZoneGeometryError("closed two-zone geometry profile is unavailable") from error
    return validate_geometry_profile(profile)


def resolve_closed_two_zone_geometry(requirements, *, geometry_profile_id=CLOSED_TWO_ZONE_PROFILE_ID):
    return _resolve_geometry(requirements, geometry_profile_id=geometry_profile_id, geometry_profile=load_geometry_profile(geometry_profile_id))
