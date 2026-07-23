"""Derive plotting-only axial sampling planes from the canonical design."""

from __future__ import annotations


def diagnostic_planes(
    resolved: dict,
    interface: dict,
    *,
    simion_cell_mm: float = 0.2,
) -> dict[str, float]:
    """Return named analysis planes; these are not design or solver inputs."""
    geometry = resolved["geometry_mm"]
    detector_plane = resolved["interfaces_mm"]["exit"]["particle_plane_z_mm"]
    return {
        "first_common_plane": simion_cell_mm,
        "rod_entry": geometry["rod_z_min"],
        "rod_midpoint": (geometry["rod_z_min"] + geometry["rod_z_max"]) / 2,
        "rod_exit": interface["planes"]["rod_exit"]["z_mm"],
        "exit_enclosure_front": interface["planes"]["handoff"]["z_mm"],
        "pre_detector": detector_plane - 6 * simion_cell_mm,
        "detector_front": detector_plane - 2 * simion_cell_mm,
    }
