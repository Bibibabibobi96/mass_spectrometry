"""Read transport observation planes and numerical domains from resolved components."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def transport_observations(resolved: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read explicit observations; the rectangular reference owns its interface layout."""
    geometry = resolved["geometry_mm"]
    if geometry["enclosure"]["model"] != "rectangular_reference_enclosure_v1":
        return geometry["observations"]
    interfaces = resolved["interfaces_mm"]
    return dict(release_plane_z_mm=interfaces["entrance"]["release_plane_z_mm"],
                handoff_plane_z_mm=interfaces["exit"]["handoff_plane_z_mm"],
                census_plane_z_mm=interfaces["exit"]["census_plane_z_mm"],
                acceptance_radius_mm=interfaces["exit"]["aperture_radius_mm"])


def transport_numerical_domain(resolved: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read the numerical domain without inferring it from physical shell dimensions."""
    geometry = resolved["geometry_mm"]
    if geometry["enclosure"]["model"] != "rectangular_reference_enclosure_v1":
        return geometry["numerical_domain"]
    enclosure = geometry["enclosure"]
    return dict(radius_mm=enclosure["outer_half_width_mm"],
                z_min_mm=enclosure["vacuum_z_min_mm"], z_max_mm=enclosure["vacuum_z_max_mm"],
                working_region_radius_mm=enclosure["working_region_radius_mm"])
