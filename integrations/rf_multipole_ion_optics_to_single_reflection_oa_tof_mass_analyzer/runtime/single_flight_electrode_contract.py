"""Exact published electrode basis for the current joint single-flight runtime."""

from __future__ import annotations

from typing import Any, Mapping


ROD_ELECTRODE_IDS = tuple(range(1, 9))
ACCELERATOR_RING_COUNT = 5
MAXIMUM_ELECTRODE_ID = 19
BASIS_ELECTRODE_IDS = tuple(range(MAXIMUM_ELECTRODE_ID + 1))
FRONTEND_ELECTRODES: dict[str, Any] = {
    "multipole_rod_ids": list(ROD_ELECTRODE_IDS),
    "grounded_shield_id": 9,
    "accelerator_repeller_id": 10,
    "accelerator_grid1_id": 11,
    "accelerator_ring_ids": list(range(12, 17)),
    "accelerator_grid2_id": 17,
    "entrance_reference_sleeve_id": 18,
    "entrance_plate_id": 19,
}


def require_published_frontend_electrodes(value: Mapping[str, Any]) -> None:
    """Fail closed unless a frontend uses the exact published Program PA basis."""
    if dict(value) != FRONTEND_ELECTRODES:
        raise ValueError("frontend electrodes differ from the published Program PA basis")
    flattened = {
        0,
        *value["multipole_rod_ids"],
        value["grounded_shield_id"],
        value["accelerator_repeller_id"],
        value["accelerator_grid1_id"],
        *value["accelerator_ring_ids"],
        value["accelerator_grid2_id"],
        value["entrance_reference_sleeve_id"],
        value["entrance_plate_id"],
    }
    if flattened != set(BASIS_ELECTRODE_IDS):
        raise ValueError("frontend electrode basis must be exactly 0 through 19")
