"""Solver-independent rigid transforms and oriented plane surfaces.

Positions use millimetres and transform as ``R @ r + t``. Free vectors,
velocities, and plane normals transform as ``R @ v``. Spatial registration
does not change the instrument time stored in a :class:`PhaseSpaceState`.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Literal, Mapping, Sequence

SCHEMA_VERSION = 1
_ORTHOGONAL_TOLERANCE = 1e-12
Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]
Matrix6 = tuple[
    tuple[float, float, float, float, float, float],
    tuple[float, float, float, float, float, float],
    tuple[float, float, float, float, float, float],
    tuple[float, float, float, float, float, float],
    tuple[float, float, float, float, float, float],
    tuple[float, float, float, float, float, float],
]
VectorKind = Literal["free", "polar", "axial"]


def _frame_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a nonempty trimmed string")
    return value


def _vector3(values: Sequence[float], label: str) -> Vector3:
    if isinstance(values, (str, bytes)) or len(values) != 3:
        raise ValueError(f"{label} must contain exactly three values")
    result = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} must contain only finite values")
    return result  # type: ignore[return-value]


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right))


def _matvec(matrix: Matrix3, vector: Vector3) -> Vector3:
    return tuple(_dot(row, vector) for row in matrix)  # type: ignore[return-value]


def _transpose(matrix: Matrix3) -> Matrix3:
    return tuple(
        tuple(matrix[row][column] for row in range(3)) for column in range(3)
    )  # type: ignore[return-value]


def _matmul(left: Matrix3, right: Matrix3) -> Matrix3:
    columns = _transpose(right)
    return tuple(
        tuple(_dot(row, column) for column in columns) for row in left
    )  # type: ignore[return-value]


def _determinant(matrix: Matrix3) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _rotation3(values: Sequence[Sequence[float]]) -> Matrix3:
    if isinstance(values, (str, bytes)) or len(values) != 3:
        raise ValueError("rotation must be a 3x3 matrix")
    rotation = tuple(_vector3(row, "rotation row") for row in values)
    for row_index, row in enumerate(rotation):
        for other_index, other in enumerate(rotation):
            expected = 1.0 if row_index == other_index else 0.0
            if not math.isclose(
                _dot(row, other),
                expected,
                rel_tol=0.0,
                abs_tol=_ORTHOGONAL_TOLERANCE,
            ):
                raise ValueError("rotation must be orthonormal")
    if not math.isclose(
        _determinant(rotation),
        1.0,
        rel_tol=0.0,
        abs_tol=_ORTHOGONAL_TOLERANCE,
    ):
        raise ValueError("rotation must be right handed with determinant +1")
    return rotation


def _matrix3(values: Sequence[Sequence[float]], label: str) -> Matrix3:
    if isinstance(values, (str, bytes)) or len(values) != 3:
        raise ValueError(f"{label} must be a 3x3 matrix")
    return tuple(_vector3(row, f"{label} row") for row in values)


def _matrix6(values: Sequence[Sequence[float]], label: str) -> Matrix6:
    if isinstance(values, (str, bytes)) or len(values) != 6:
        raise ValueError(f"{label} must be a 6x6 matrix")
    rows = []
    for row in values:
        if isinstance(row, (str, bytes)) or len(row) != 6:
            raise ValueError(f"{label} must be a 6x6 matrix")
        converted = tuple(float(value) for value in row)
        if not all(math.isfinite(value) for value in converted):
            raise ValueError(f"{label} must contain only finite values")
        rows.append(converted)
    return tuple(rows)  # type: ignore[return-value]


def _transpose6(matrix: Matrix6) -> Matrix6:
    return tuple(
        tuple(matrix[row][column] for row in range(6)) for column in range(6)
    )  # type: ignore[return-value]


def _matmul6(left: Matrix6, right: Matrix6) -> Matrix6:
    columns = _transpose6(right)
    return tuple(
        tuple(sum(a * b for a, b in zip(row, column)) for column in columns)
        for row in left
    )  # type: ignore[return-value]


def _require_symmetric(values: Sequence[Sequence[float]], label: str) -> None:
    for row in range(len(values)):
        for column in range(row):
            if not math.isclose(
                values[row][column],
                values[column][row],
                rel_tol=0.0,
                abs_tol=_ORTHOGONAL_TOLERANCE,
            ):
                raise ValueError(f"{label} must be symmetric")


def _schema_version(value: int) -> int:
    if isinstance(value, bool) or int(value) != value or int(value) != SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
    return int(value)


def _require_frame(actual: str, expected: str, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} frame mismatch: expected {expected}, got {actual}")


@dataclass(frozen=True)
class FramedPosition:
    """A position in millimetres expressed in one named frame."""

    frame_id: str
    coordinates_mm: Vector3

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frame_id", _frame_id(self.frame_id, "position frame_id")
        )
        object.__setattr__(
            self,
            "coordinates_mm",
            _vector3(self.coordinates_mm, "position coordinates_mm"),
        )


@dataclass(frozen=True)
class FramedVector:
    """A free, polar, or axial vector transformed without translation.

    Proper rotations have determinant +1, so polar and axial vectors both use
    ``R @ v``. The kind remains explicit to prevent later improper transforms
    from silently conflating their semantics.
    """

    frame_id: str
    components: Vector3
    kind: VectorKind = "free"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frame_id", _frame_id(self.frame_id, "vector frame_id")
        )
        object.__setattr__(
            self, "components", _vector3(self.components, "vector components")
        )
        if self.kind not in {"free", "polar", "axial"}:
            raise ValueError("vector kind must be free, polar, or axial")


@dataclass(frozen=True)
class FramedTensor:
    """A second-order 3x3 tensor expressed in one named frame."""

    frame_id: str
    components: Matrix3

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frame_id", _frame_id(self.frame_id, "tensor frame_id")
        )
        object.__setattr__(
            self, "components", _matrix3(self.components, "tensor components")
        )


@dataclass(frozen=True)
class FramedCovariance:
    """A symmetric 3x3 covariance expressed in one named frame."""

    frame_id: str
    components: Matrix3

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frame_id", _frame_id(self.frame_id, "covariance frame_id")
        )
        components = _matrix3(self.components, "covariance components")
        _require_symmetric(components, "covariance components")
        object.__setattr__(self, "components", components)


@dataclass(frozen=True)
class PhaseSpaceCovariance:
    """Symmetric covariance of ``(position[3], velocity[3])`` without unit conversion."""

    frame_id: str
    components: Matrix6

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "frame_id",
            _frame_id(self.frame_id, "phase-space covariance frame_id"),
        )
        components = _matrix6(self.components, "phase-space covariance components")
        _require_symmetric(components, "phase-space covariance components")
        object.__setattr__(self, "components", components)


@dataclass(frozen=True)
class PhaseSpaceState:
    """Three-dimensional particle state with shared-clock time semantics."""

    frame_id: str
    position_mm: Vector3
    velocity_m_s: Vector3
    instrument_time_us: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frame_id", _frame_id(self.frame_id, "state frame_id")
        )
        object.__setattr__(
            self, "position_mm", _vector3(self.position_mm, "state position_mm")
        )
        object.__setattr__(
            self, "velocity_m_s", _vector3(self.velocity_m_s, "state velocity_m_s")
        )
        time_us = float(self.instrument_time_us)
        if not math.isfinite(time_us):
            raise ValueError("instrument_time_us must be finite")
        object.__setattr__(self, "instrument_time_us", time_us)


@dataclass(frozen=True)
class PlaneSurface:
    """An oriented plane whose unit normal defines its forward side."""

    frame_id: str
    center_mm: Vector3
    normal: Vector3
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _schema_version(self.schema_version)
        )
        object.__setattr__(
            self, "frame_id", _frame_id(self.frame_id, "plane frame_id")
        )
        object.__setattr__(
            self, "center_mm", _vector3(self.center_mm, "plane center_mm")
        )
        normal = _vector3(self.normal, "plane normal")
        if not math.isclose(
            _dot(normal, normal),
            1.0,
            rel_tol=0.0,
            abs_tol=_ORTHOGONAL_TOLERANCE,
        ):
            raise ValueError("plane normal must be a unit vector")
        object.__setattr__(self, "normal", normal)

    def signed_distance_mm(self, position: FramedPosition) -> float:
        """Return positive distance on the normal side of the plane."""

        _require_frame(position.frame_id, self.frame_id, "plane position")
        offset = tuple(
            value - center
            for value, center in zip(position.coordinates_mm, self.center_mm)
        )
        return _dot(offset, self.normal)  # type: ignore[arg-type]

    def is_forward_crossing(
        self,
        previous: FramedPosition,
        current: FramedPosition,
        velocity: FramedVector,
        *,
        tolerance_mm: float = 0.0,
    ) -> bool:
        """Return whether a step crosses from the negative to positive side."""

        tolerance = float(tolerance_mm)
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("tolerance_mm must be finite and nonnegative")
        _require_frame(current.frame_id, self.frame_id, "current position")
        _require_frame(velocity.frame_id, self.frame_id, "crossing velocity")
        return (
            self.signed_distance_mm(previous) < -tolerance
            and self.signed_distance_mm(current) >= tolerance
            and _dot(velocity.components, self.normal) > 0.0
        )

    def to_contract(self) -> dict[str, Any]:
        """Return the versioned JSON-compatible plane contract."""

        return {
            "schema_version": self.schema_version,
            "role": "oriented_plane_surface",
            "frame_id": self.frame_id,
            "center_mm": list(self.center_mm),
            "normal": list(self.normal),
        }


@dataclass(frozen=True)
class RigidTransform:
    """Versioned right-handed transform from one named frame to another."""

    from_frame_id: str
    to_frame_id: str
    rotation: Matrix3
    translation_mm: Vector3
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _schema_version(self.schema_version)
        )
        object.__setattr__(
            self, "from_frame_id", _frame_id(self.from_frame_id, "from_frame_id")
        )
        object.__setattr__(
            self, "to_frame_id", _frame_id(self.to_frame_id, "to_frame_id")
        )
        object.__setattr__(self, "rotation", _rotation3(self.rotation))
        object.__setattr__(
            self,
            "translation_mm",
            _vector3(self.translation_mm, "translation_mm"),
        )

    @classmethod
    def identity(cls, frame_id: str) -> RigidTransform:
        """Return an identity transform in one frame."""

        return cls(
            frame_id,
            frame_id,
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            (0.0, 0.0, 0.0),
        )

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> RigidTransform:
        """Validate an exact version-1 JSON-compatible transform contract."""

        expected = {
            "schema_version",
            "role",
            "from_frame_id",
            "to_frame_id",
            "rotation",
            "translation_mm",
        }
        if set(contract) != expected:
            raise ValueError(
                "rigid-transform contract fields differ from schema version 1"
            )
        if contract["role"] != "rigid_transform":
            raise ValueError("rigid-transform contract role is invalid")
        return cls(
            from_frame_id=contract["from_frame_id"],
            to_frame_id=contract["to_frame_id"],
            rotation=contract["rotation"],
            translation_mm=contract["translation_mm"],
            schema_version=contract["schema_version"],
        )

    def to_contract(self) -> dict[str, Any]:
        """Return the versioned JSON-compatible transform contract."""

        return {
            "schema_version": self.schema_version,
            "role": "rigid_transform",
            "from_frame_id": self.from_frame_id,
            "to_frame_id": self.to_frame_id,
            "rotation": [list(row) for row in self.rotation],
            "translation_mm": list(self.translation_mm),
        }

    def transform_position(self, position: FramedPosition) -> FramedPosition:
        """Rotate and translate one position in millimetres."""

        _require_frame(position.frame_id, self.from_frame_id, "position")
        rotated = _matvec(self.rotation, position.coordinates_mm)
        transformed = tuple(
            value + offset for value, offset in zip(rotated, self.translation_mm)
        )
        return FramedPosition(
            self.to_frame_id, transformed  # type: ignore[arg-type]
        )

    def transform_vector(self, vector: FramedVector) -> FramedVector:
        """Rotate a free, polar, or axial vector without translation."""

        _require_frame(vector.frame_id, self.from_frame_id, "vector")
        return FramedVector(
            self.to_frame_id,
            _matvec(self.rotation, vector.components),
            vector.kind,
        )

    def transform_tensor(self, tensor: FramedTensor) -> FramedTensor:
        """Transform a second-order tensor as ``R @ T @ R.T``."""
        _require_frame(tensor.frame_id, self.from_frame_id, "tensor")
        components = _matmul(
            _matmul(self.rotation, tensor.components), _transpose(self.rotation)
        )
        return FramedTensor(self.to_frame_id, components)

    def transform_covariance(
        self, covariance: FramedCovariance
    ) -> FramedCovariance:
        """Transform a 3x3 covariance as ``R @ C @ R.T``."""
        _require_frame(covariance.frame_id, self.from_frame_id, "covariance")
        transformed = self.transform_tensor(
            FramedTensor(covariance.frame_id, covariance.components)
        )
        return FramedCovariance(self.to_frame_id, transformed.components)

    def transform_phase_space_covariance(
        self, covariance: PhaseSpaceCovariance
    ) -> PhaseSpaceCovariance:
        """Transform 6D covariance with ``diag(R, R)`` without unit conversion."""
        _require_frame(
            covariance.frame_id, self.from_frame_id, "phase-space covariance"
        )
        zero = (0.0, 0.0, 0.0)
        block_rotation: Matrix6 = (
            self.rotation[0] + zero,
            self.rotation[1] + zero,
            self.rotation[2] + zero,
            zero + self.rotation[0],
            zero + self.rotation[1],
            zero + self.rotation[2],
        )
        components = _matmul6(
            _matmul6(block_rotation, covariance.components),
            _transpose6(block_rotation),
        )
        return PhaseSpaceCovariance(self.to_frame_id, components)

    def transform_plane(self, plane: PlaneSurface) -> PlaneSurface:
        """Transform a plane center as a position and its normal as a vector."""

        _require_frame(plane.frame_id, self.from_frame_id, "plane")
        center = self.transform_position(
            FramedPosition(plane.frame_id, plane.center_mm)
        )
        normal = self.transform_vector(FramedVector(plane.frame_id, plane.normal))
        return PlaneSurface(
            self.to_frame_id, center.coordinates_mm, normal.components
        )

    def transform_state(self, state: PhaseSpaceState) -> PhaseSpaceState:
        """Transform position and velocity while preserving instrument time."""

        _require_frame(state.frame_id, self.from_frame_id, "phase-space state")
        position = self.transform_position(
            FramedPosition(state.frame_id, state.position_mm)
        )
        velocity = self.transform_vector(
            FramedVector(state.frame_id, state.velocity_m_s)
        )
        return PhaseSpaceState(
            self.to_frame_id,
            position.coordinates_mm,
            velocity.components,
            state.instrument_time_us,
        )

    def transform_scalar(self, value: float) -> float:
        """Return one finite spatial scalar unchanged and without unit conversion."""
        scalar = float(value)
        if not math.isfinite(scalar):
            raise ValueError("spatial scalar must be finite")
        return scalar

    def transform_time(self, instrument_time_us: float) -> float:
        """Return finite shared-clock instrument time unchanged."""
        time_us = float(instrument_time_us)
        if not math.isfinite(time_us):
            raise ValueError("instrument_time_us must be finite")
        return time_us

    def inverse(self) -> RigidTransform:
        """Return the exact inverse frame transform."""

        rotation = _transpose(self.rotation)
        translation = tuple(
            -value for value in _matvec(rotation, self.translation_mm)
        )
        return RigidTransform(
            self.to_frame_id,
            self.from_frame_id,
            rotation,
            translation,  # type: ignore[arg-type]
        )

    def then(self, following: RigidTransform) -> RigidTransform:
        """Compose this transform followed by ``following``."""

        if self.to_frame_id != following.from_frame_id:
            raise ValueError(
                "transform composition frame mismatch: "
                f"{self.to_frame_id} != {following.from_frame_id}"
            )
        rotation = _matmul(following.rotation, self.rotation)
        first_offset = _matvec(following.rotation, self.translation_mm)
        translation = tuple(
            value + offset
            for value, offset in zip(first_offset, following.translation_mm)
        )
        return RigidTransform(
            self.from_frame_id,
            following.to_frame_id,
            rotation,
            translation,  # type: ignore[arg-type]
        )


def relative_transform(
    source_to_reference: RigidTransform,
    target_to_reference: RigidTransform,
) -> RigidTransform:
    """Derive source-to-target registration from poses in one reference frame."""

    if source_to_reference.to_frame_id != target_to_reference.to_frame_id:
        raise ValueError("component poses do not share the same reference frame")
    return source_to_reference.then(target_to_reference.inverse())
