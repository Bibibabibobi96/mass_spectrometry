"""Read-only access to the generated RF-quadrupole design publication."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESOLVED = PROJECT_ROOT / "config" / "resolved_geometry.json"
DEFAULT_INTERFACE = PROJECT_ROOT / "config" / "interface_contract.json"


def load(resolved_path: Path | None = None, interface_path: Path | None = None) -> tuple[dict, dict]:
    resolved = json.loads((resolved_path or DEFAULT_RESOLVED).read_text(encoding="utf-8"))
    interface = json.loads((interface_path or DEFAULT_INTERFACE).read_text(encoding="utf-8"))
    if resolved.get("role") != "rf_quadrupole_resolved_official_contract_do_not_edit":
        raise ValueError("unsupported RF-quadrupole resolved contract")
    return resolved, interface


def diagnostic_planes(resolved: dict, interface: dict) -> dict[str, float]:
    g = resolved["geometry_mm"]
    cell = g["simion_cell_mm"]
    return {
        "first_common_plane": cell,
        "rod_entry": g["rod_z_min"],
        "rod_midpoint": (g["rod_z_min"] + g["rod_z_max"]) / 2,
        "rod_exit": interface["planes"]["rod_exit"]["z_mm"],
        "exit_enclosure_front": interface["planes"]["handoff"]["z_mm"],
        "pre_detector": resolved["coordinate_convention"]["detector_plane_z_mm"] - 6 * cell,
        "detector_front": resolved["coordinate_convention"]["detector_plane_z_mm"] - 2 * cell,
    }
