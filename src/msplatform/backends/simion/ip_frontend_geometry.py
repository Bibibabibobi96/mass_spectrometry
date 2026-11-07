"""Render IP bare-guide and cooled-buncher component geometry for SIMION."""
from __future__ import annotations

from msplatform.backends.simion.ip_geometry import render_projection_electrodes


def render_cooled_buncher_gem_fragment(contract: dict) -> str:
    """Return native-frame e/fill metal body; caller applies native_to_mr once."""
    if contract.get("role") != "ion_processor_hp_end_buncher_provider" or contract.get("schema_version") != 1:
        raise ValueError("unsupported cooled buncher provider")
    return render_projection_electrodes(contract["native_projection_fragment"])
