"""Thin validated access to the common RF-multipole resolved design."""

from __future__ import annotations

import json
from pathlib import Path

from common.multipole.compile_design_request import validate_resolved_design


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
DEFAULT_RESOLVED = PROJECT_ROOT / "config" / "resolved_design_official.json"
DEFAULT_REQUEST = PROJECT_ROOT / "config" / "requests" / "official.json"
DEFAULT_INTERFACE = PROJECT_ROOT / "config" / "interface_contract.json"
EXPECTED_IDENTITY = {
    "project_id": "rf_quadrupole_collision_cooling",
    "family_id": "rf_multipole_ion_optics",
    "radial_order_n": 2,
    "electrode_count": 4,
}


def load(
    resolved_path: Path | None = None,
    interface_path: Path | None = None,
) -> tuple[dict, dict]:
    """Load a canonical design and the separate RF-to-oaTOF interface contract."""
    resolved = json.loads(
        (resolved_path or DEFAULT_RESOLVED).read_text(encoding="utf-8")
    )
    interface = json.loads(
        (interface_path or DEFAULT_INTERFACE).read_text(encoding="utf-8")
    )
    return (
        validate_resolved_design(
            resolved,
            request_path=DEFAULT_REQUEST,
            source_root=REPOSITORY_ROOT,
            expected_identity=EXPECTED_IDENTITY,
        ),
        interface,
    )
