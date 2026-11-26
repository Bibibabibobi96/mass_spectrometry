"""Convert a frozen legacy complete instrument to downstream-only author inputs."""
from __future__ import annotations

import copy
from typing import Any, Mapping
from .geometry import DOWNSTREAM_GEOMETRY_KEYS


def project_legacy_downstream(resolved: Mapping[str, Any]) -> dict:
    """Copy only downstream physical inputs; the returned design contains no OA."""
    if resolved.get("role") != "oa_tof_resolved_contract_do_not_edit" or resolved.get("coordinate_convention", {}).get("frame_id") != "oatof_global":
        raise ValueError("explicit frozen legacy oaTOF resolved geometry required")
    return copy.deepcopy({"schema_version": 1, "role": "single_reflection_tof_design",
        "local_frame_id": "single_reflection_tof_cartesian",
        "geometry_mm": {k: resolved["geometry_mm"][k] for k in DOWNSTREAM_GEOMETRY_KEYS},
        "coordinate_convention": {k: resolved["coordinate_convention"][k] for k in ("reflectron_axis", "detector_x")},
        "rings": {k: resolved["rings"][k] for k in ("stage1_count", "stage2_count")},
        "electrodes_v": {k: resolved["electrodes_V"][k] for k in ("entgrid", "midgrid", "backplate")}})
