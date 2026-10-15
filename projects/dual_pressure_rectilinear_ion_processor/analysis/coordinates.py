"""Frame-safe project/local mappings; native PA and mechanical geometry stay local."""
from __future__ import annotations

from typing import Any, Sequence

from common.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform


LOCAL_FRAME_ID = "dual_pressure_ion_processor_local_v1"


def transform_from_config(config: dict[str, Any]) -> RigidTransform:
    """Read the common exact transform contract; legacy runs retain local identity."""
    frame = config.get("baseline", {}).get("clock", {}).get("frame_id", LOCAL_FRAME_ID)
    if "coordinate_transform" not in config:
        return RigidTransform.identity(frame)
    transform = RigidTransform.from_contract(config["coordinate_transform"])
    if transform.from_frame_id != frame:
        raise ValueError("coordinate transform source frame differs from local scientific frame")
    return transform


def to_project_position(config: dict[str, Any], xyz: Sequence[float]) -> tuple[float, float, float]:
    """Rotate and translate local position [mm] into the declared project frame."""
    transform = transform_from_config(config)
    return transform.transform_position(FramedPosition(transform.from_frame_id, xyz)).coordinates_mm


def to_local_position(config: dict[str, Any], xyz: Sequence[float]) -> tuple[float, float, float]:
    """Invert project position [mm] into the native local mechanical frame."""
    transform = transform_from_config(config).inverse()
    return transform.transform_position(FramedPosition(transform.from_frame_id, xyz)).coordinates_mm


def to_project_vector(config: dict[str, Any], xyz: Sequence[float]) -> tuple[float, float, float]:
    """Rotate local vector into project axes, preserving units and magnitude."""
    transform = transform_from_config(config)
    return transform.transform_vector(FramedVector(transform.from_frame_id, xyz)).components


def to_local_vector(config: dict[str, Any], xyz: Sequence[float]) -> tuple[float, float, float]:
    """Rotate project vector into local axes without translating free vectors."""
    transform = transform_from_config(config).inverse()
    return transform.transform_vector(FramedVector(transform.from_frame_id, xyz)).components
