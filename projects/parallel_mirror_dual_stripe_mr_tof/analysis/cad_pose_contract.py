"""Validate the explicit SolidWorks-to-project coordinate transform."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class CadPoseContractError(ValueError):
    """Raised when CAD evidence cannot be used in the project frame."""


EXPECTED_FRAME = "astral.xyz.reflection_z.drift_y.transverse_x.v1"
EXPECTED_ASSIGNMENT = {
    "drift_stripe_set_1": ["ion foil 1-3", "ion foil 1-4"],
    "drift_stripe_set_2": ["ion foil 3-3", "ion foil 3-4"],
    "central_ground_candidate": "ion foil 2-2",
}


def load_cad_pose_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("project_id") != "parallel_mirror_dual_stripe_mr_tof":
        raise CadPoseContractError("CAD pose contract belongs to a different project")
    if data.get("target_frame") != EXPECTED_FRAME:
        raise CadPoseContractError("CAD pose must target the documented project frame")
    transform = data.get("target_from_source", {})
    rotation = transform.get("rotation")
    translation = transform.get("translation_mm")
    if not isinstance(rotation, list) or len(rotation) != 3 or any(not isinstance(row, list) or len(row) != 3 for row in rotation):
        raise CadPoseContractError("CAD pose rotation must be a 3x3 matrix")
    if not isinstance(translation, list) or len(translation) != 3:
        raise CadPoseContractError("CAD pose translation must be a length-3 vector")
    values = [float(value) for row in rotation for value in row] + [float(value) for value in translation]
    if not all(math.isfinite(value) for value in values):
        raise CadPoseContractError("CAD pose values must be finite")
    for row in rotation:
        if not math.isclose(sum(float(value) ** 2 for value in row), 1.0, abs_tol=1e-12):
            raise CadPoseContractError("CAD pose rotation rows must be unit length")
    for left in range(3):
        for right in range(left + 1, 3):
            if not math.isclose(sum(float(rotation[left][axis]) * float(rotation[right][axis]) for axis in range(3)), 0.0, abs_tol=1e-12):
                raise CadPoseContractError("CAD pose rotation rows must be orthogonal")
    if data.get("stable_candidate_assignment") != {**EXPECTED_ASSIGNMENT, "additional_ground_components": ["grounded-1", "grounded 2-1"]}:
        raise CadPoseContractError("CAD pose assignment must retain the four-stripe/two-bias contract")
    return data


def source_to_project(point_mm: tuple[float, float, float], contract: dict[str, Any]) -> tuple[float, float, float]:
    """Apply the frozen CAD-to-theory rigid transform to a point."""
    transform = contract["target_from_source"]
    rotation = transform["rotation"]
    translation = transform["translation_mm"]
    return tuple(
        sum(float(rotation[row][axis]) * point_mm[axis] for axis in range(3)) + float(translation[row])
        for row in range(3)
    )


def project_to_source(point_mm: tuple[float, float, float], contract: dict[str, Any]) -> tuple[float, float, float]:
    """Invert the orthonormal CAD-to-theory rigid transform."""
    transform = contract["target_from_source"]
    rotation = transform["rotation"]
    translation = transform["translation_mm"]
    shifted = [point_mm[index] - float(translation[index]) for index in range(3)]
    return tuple(sum(float(rotation[row][axis]) * shifted[row] for row in range(3)) for axis in range(3))
