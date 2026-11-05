"""SIMION 8.1 native labels for the provider-owned oaTOF frontend domain.

This adapter validates the mapping and domain protocol, not the scientific
validity or provenance of the opaque provider projection supplied by its caller.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


# SIMION 8.1 default adjustable-electrode limit, not a physical group limit:
# https://simion.com/info/max_electrodes.html (verified 2026-11-03).
SIMION_MAX_ADJUSTABLE_ELECTRODE_ID = 1000

# Provider domain protocol 1 -> existing sectioned-accelerator renderer names.
# In that renderer grid2 means the exit grid, not the second intermediate grid.
_FRONTEND_V1_RENDERER_KEYS = {
    "common_ground": "grounded_shield_id",
    "accelerator_repeller": "accelerator_repeller_id",
    "accelerator_intermediate_grid_1": "accelerator_grid1_id",
    "accelerator_intermediate_grid_2": "accelerator_intermediate2_id",
    "accelerator_exit_grid": "accelerator_grid2_id",
}


def _frontend_group_ids(frontend_domain: Mapping[str, Any]) -> list[str]:
    if (not isinstance(frontend_domain, Mapping)
            or type(frontend_domain.get("schema_version")) is not int
            or frontend_domain["schema_version"] != 1
            or frontend_domain.get("role") != "oatof_frontend_field_domain"
            or frontend_domain.get("domain_id") != "accelerator_frontend"
            or frontend_domain.get("variant_id") != "three_zone_square"):
        raise ValueError("unsupported oaTOF frontend domain protocol or variant")
    groups = frontend_domain.get("electrode_group_ids")
    if (not isinstance(groups, list) or not groups
            or any(not isinstance(group, str) for group in groups)
            or len(groups) != len(set(groups))):
        raise ValueError("frontend domain requires unique electrode_group_ids")
    fixed = set(_FRONTEND_V1_RENDERER_KEYS)
    rings = [group for group in groups if group not in fixed]
    if (not fixed.issubset(groups)
            or any(re.fullmatch(r"accelerator_ring_[0-9]{4}", group) is None
                   or int(group.rsplit("_", 1)[1]) < 1 for group in rings)):
        raise ValueError("frontend domain contains missing or unsupported electrode groups")
    members = frontend_domain.get("members")
    if (not isinstance(members, list) or len(members) != len(groups)
            or any(not isinstance(row, Mapping) for row in members)
            or [row.get("electrode_group_id") for row in members] != groups
            or any(not isinstance(row.get("member_refs"), list) or not row["member_refs"]
                   or any(not isinstance(ref, str) or not ref.startswith("/sources/oa_mechanical/")
                          for ref in row["member_refs"]) for row in members)):
        raise ValueError("frontend domain members must match the provider group projection")
    return groups


def validate_frontend_electrode_map(
    mapping: Mapping[str, int], *, frontend_domain: Mapping[str, Any],
) -> dict[str, int]:
    """Return an independent exact group-to-native map for domain protocol 1.

    Callers must obtain and authenticate the domain from its scientific provider;
    a binding record cannot authorize its own reduced physical group scope.
    """
    groups = _frontend_group_ids(frontend_domain)
    if not isinstance(mapping, Mapping) or set(mapping) != set(groups):
        raise ValueError("frontend electrode map must cover exactly the provider domain groups")
    values = list(mapping.values())
    if any(type(value) is not int or not 1 <= value <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
           for value in values):
        raise ValueError("SIMION 8.1 native electrode IDs must be integers in 1..1000")
    if len(values) != len(set(values)):
        raise ValueError("frontend electrode groups require distinct native IDs")
    return {group: mapping[group] for group in groups}


def native_frontend_electrodes(
    mapping: Mapping[str, int], *, frontend_domain: Mapping[str, Any],
) -> dict[str, Any]:
    """Project validated scientific groups to the existing renderer's protocol.

    Rings retain the provider's actual member order, independent of native labels.
    No voltage, geometry, scientific scope or physical identity is inferred here.
    """
    validated = validate_frontend_electrode_map(mapping, frontend_domain=frontend_domain)
    result = {native_key: validated[group]
              for group, native_key in _FRONTEND_V1_RENDERER_KEYS.items()}
    result["accelerator_ring_ids"] = [value for group, value in validated.items()
                                      if group not in _FRONTEND_V1_RENDERER_KEYS]
    return result
