"""Explicit rigid port mating in mm; no pose or rotation is guessed."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from msplatform.contracts.machine_contracts import ContractError
from msplatform.contracts.rigid_transform import FramedVector, PlaneSurface, RigidTransform


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _norm(vector: list[float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _subtract(left: list[float], right: list[float]) -> list[float]:
    return [a - b for a, b in zip(left, right, strict=True)]


def _matrix_vector(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [_dot(row, vector) for row in matrix]


def derive_direct_mating_translation(
    rotation_upstream_to_downstream: list[list[float]],
    upstream_center_mm: list[float],
    downstream_center_mm: list[float],
) -> list[float]:
    """Return the rigid translation that makes two port centers coincide."""
    if (
        len(rotation_upstream_to_downstream) != 3
        or any(len(row) != 3 for row in rotation_upstream_to_downstream)
        or len(upstream_center_mm) != 3
        or len(downstream_center_mm) != 3
    ):
        raise ContractError("direct-mating translation requires 3D rotation and centers")
    values = [
        float(value)
        for row in rotation_upstream_to_downstream
        for value in row
    ] + [float(value) for value in upstream_center_mm + downstream_center_mm]
    if not all(math.isfinite(value) for value in values):
        raise ContractError("direct-mating translation inputs must be finite")
    transformed = _matrix_vector(
        rotation_upstream_to_downstream, list(map(float, upstream_center_mm))
    )
    return _subtract(list(map(float, downstream_center_mm)), transformed)


def derive_mating_translation_with_gap(
    rotation_upstream_to_downstream: list[list[float]],
    upstream_center_mm: list[float],
    upstream_outward_normal: list[float],
    downstream_center_mm: list[float],
    gap_mm: float,
) -> list[float]:
    """Return a rigid translation with a nonnegative normal gap in millimetres."""
    direct_translation = derive_direct_mating_translation(
        rotation_upstream_to_downstream,
        upstream_center_mm,
        downstream_center_mm,
    )
    if len(upstream_outward_normal) != 3:
        raise ContractError("gap-mating translation requires a 3D upstream normal")
    normal = list(map(float, upstream_outward_normal))
    gap = float(gap_mm)
    if not all(math.isfinite(value) for value in [*normal, gap]):
        raise ContractError("gap-mating translation inputs must be finite")
    if gap < 0.0:
        raise ContractError("gap-mating translation gap must be nonnegative")
    if not math.isclose(_norm(normal), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ContractError("gap-mating translation upstream normal must be a unit vector")
    _validate_rotation(rotation_upstream_to_downstream, 1e-12)
    transformed_normal = _matrix_vector(rotation_upstream_to_downstream, normal)
    return [
        value - gap * component
        for value, component in zip(
            direct_translation, transformed_normal, strict=True
        )
    ]


def _determinant(matrix: list[list[float]]) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _validate_rotation(matrix: list[list[float]], tolerance: float) -> None:
    for row in matrix:
        if abs(_norm(row) - 1.0) > tolerance:
            raise ContractError("spatial registration rotation is not orthonormal")
    for left in range(3):
        for right in range(left + 1, 3):
            if abs(_dot(matrix[left], matrix[right])) > tolerance:
                raise ContractError("spatial registration rotation is not orthonormal")
    if abs(_determinant(matrix) - 1.0) > tolerance:
        raise ContractError("spatial registration rotation must be right-handed")


def _port_geometry(port: Mapping[str, Any]) -> tuple[PlaneSurface, dict[str, Any]]:
    if not isinstance(port, Mapping) or not {"frame_id", "center_mm", "outward_normal", "cross_section"} <= port.keys():
        raise ContractError("mating port requires frame_id, center_mm, outward_normal and cross_section")
    surface = PlaneSurface(port["frame_id"], tuple(port["center_mm"]), tuple(port["outward_normal"]))
    section = dict(port["cross_section"])
    shape = section.get("shape")
    if shape == "rectangle":
        axes = [FramedVector(surface.frame_id, tuple(section[key])) for key in ("width_axis", "height_axis")]
        for axis in axes:
            if abs(_norm(axis.components) - 1.) > 1e-12 or abs(_dot(axis.components, surface.normal)) > 1e-12:
                raise ContractError("rectangular mating axes must be unit vectors in the port plane")
        if abs(_dot(axes[0].components, axes[1].components)) > 1e-12:
            raise ContractError("rectangular mating axes must be orthogonal")
        dimensions = [section[key] for key in ("width_mm", "height_mm")]
    elif shape in ("circle", "open_rod_envelope"):
        dimensions = [section["radius_mm" if shape == "circle" else "inscribed_radius_mm"]]
    else:
        raise ContractError(f"unsupported mating cross-section: {shape}")
    if any(isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0 for value in dimensions):
        raise ContractError("mating cross-section dimensions must be finite and positive")
    return surface, section


def mate_ports(upstream_port: Mapping[str, Any], downstream_port: Mapping[str, Any], *,
               rotation: Sequence[Sequence[float]], gap_mm: float) -> RigidTransform:
    """Map a downstream local port to an upstream reference frame, in mm.

    Rotation is mandatory, including the remaining roll for a circular port.
    Normals must oppose; paired rectangular width/height axes must correspond.
    The translation reuses the existing gap-mating algorithm with reversed
    source/target roles. This checks mating geometry, not conductor clearance,
    field coupling, or backend support. Inputs are not changed; no I/O occurs.
    """
    upstream, up_section = _port_geometry(upstream_port)
    downstream, down_section = _port_geometry(downstream_port)
    pose = RigidTransform(downstream.frame_id, upstream.frame_id, rotation, (0., 0., 0.))
    normal = pose.transform_vector(FramedVector(downstream.frame_id, downstream.normal)).components
    # This is the existing rigid-registration roundoff scale, not a clearance budget.
    if any(abs(a + b) > 1e-12 for a, b in zip(normal, upstream.normal, strict=True)):
        raise ContractError("mating port normals must oppose under the explicit rotation")
    if up_section["shape"] == down_section["shape"] == "rectangle":
        for key in ("width_axis", "height_axis"):
            axis = pose.transform_vector(FramedVector(downstream.frame_id, tuple(down_section[key]))).components
            if abs(abs(_dot(axis, up_section[key])) - 1.) > 1e-12:
                raise ContractError(f"rectangular mating {key} does not correspond under the explicit rotation")
    if isinstance(gap_mm, bool):
        raise ContractError("mating gap must be a finite nonnegative length")
    translation = derive_mating_translation_with_gap(
        [list(row) for row in pose.rotation], list(downstream.center_mm), list(downstream.normal),
        list(upstream.center_mm), gap_mm)
    return RigidTransform(pose.from_frame_id, pose.to_frame_id, pose.rotation, tuple(translation))
