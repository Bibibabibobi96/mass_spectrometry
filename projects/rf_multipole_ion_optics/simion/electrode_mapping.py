"""SIMION capacity and numbering for provider-owned RF electrical groups."""
from __future__ import annotations

from typing import Any, Mapping


SIMION_MAX_ADJUSTABLE_ELECTRODE_ID = 1000


def build_simion_electrode_map(
    resolved: Mapping[str, Any], topology: tuple[dict[str, Any], ...], *,
    requested_native_ids: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Bind every scientific group once; retain the existing default PA labels.

    Explicit permutations must cover precisely the supplied provider topology.
    The caller owns field-domain conflicts with other instances and reserved
    slots; this local adapter rejects invalid integers and local capacity.
    """
    from projects.rf_multipole_ion_optics.core.electrode_topology import build_electrode_topology

    if topology != build_electrode_topology(resolved):
        raise ValueError("electrode topology differs from the resolved provider")
    keys = [row["scientific_id"] for row in topology]
    default = {}
    for row in topology:
        key, source = row["scientific_id"], row["voltage_source"]
        if source["kind"] == "rf_drive":
            if resolved["segmentation"]["segmented_rod_array"] is None:
                native = source["rf_group"]
            else:
                index = int(row["member_refs"][0].split("/")[-1])
                segment = resolved["segmentation"]["segmented_rod_array"]["electrodes"][index]["segment_id"]
                native = 2 * (segment - 1) + source["rf_group"]
            default[key] = native
    if "grounded_shell" in keys:
        default["grounded_shell"] = max(default.values()) + 1
    mapping = default if requested_native_ids is None else dict(requested_native_ids)
    if set(mapping) != set(keys):
        raise ValueError("SIMION map must cover every scientific electrode without extras")
    if (any(type(value) is not int or not 1 <= value <= SIMION_MAX_ADJUSTABLE_ELECTRODE_ID
            for value in mapping.values()) or len(set(mapping.values())) != len(mapping)):
        raise ValueError("SIMION electrode map exceeds capacity or has invalid/duplicate native IDs")
    return mapping
