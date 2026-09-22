"""Deterministically materialize solver-neutral full-volume cylinder releases.

The module owns sampling, canonical source-table serialization, and receipt
identity.  Projects own the physical placement, frame registration, and their
solver adapters.  No geometry, field, or solver assumption is accepted here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import speed_m_s_from_kinetic_energy_ev


ROLE = "repository_ion_release"
SCHEMA_VERSION = 1
CANONICAL_COLUMNS = (
    "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s",
    "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
)
HALTON_STRATEGY = "center_first_halton_cylinder_v1"
GAUSSIAN_STRATEGY = "seeded_independent_gaussian_cylinder_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        qualifier = " and positive" if positive else ""
        raise ValueError(f"{label} must be finite{qualifier}")
    return result


def _vector3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must contain exactly three values")
    return tuple(_number(item, label) for item in value)  # type: ignore[return-value]


def _unit(vector: Sequence[float], label: str) -> tuple[float, float, float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= 0.0 or not math.isfinite(magnitude):
        raise ValueError(f"{label} must be nonzero")
    return tuple(value / magnitude for value in vector)  # type: ignore[return-value]


def _tangent_basis(direction: Sequence[float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    unit = _unit(direction, "nominal_direction")
    reference = (0.0, 0.0, 1.0) if abs(unit[2]) < 0.9 else (1.0, 0.0, 0.0)
    first = _unit((
        unit[1] * reference[2] - unit[2] * reference[1],
        unit[2] * reference[0] - unit[0] * reference[2],
        unit[0] * reference[1] - unit[1] * reference[0],
    ), "tangent basis")
    second = _unit((
        unit[1] * first[2] - unit[2] * first[1],
        unit[2] * first[0] - unit[0] * first[2],
        unit[0] * first[1] - unit[1] * first[0],
    ), "tangent basis")
    return first, second


def _radical_inverse(index: int, base: int) -> float:
    value = 0.0
    factor = 1.0 / base
    while index:
        index, digit = divmod(index, base)
        value += digit * factor
        factor /= base
    return value


def _axis_index(axis: Any) -> int:
    if axis not in ("x", "y", "z"):
        raise ValueError("geometry.axis must be one of x, y, z")
    return "xyz".index(axis)


def _mapping(value: Any, label: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(keys))}")
    return value


def validate_cylinder_release_spec(spec: Mapping[str, Any]) -> None:
    """Fail closed unless *spec* is a complete versioned release request."""
    required = {
        "schema_version", "role", "frame_id", "particle_count", "mother_particle_count",
        "common_time_of_birth_s", "geometry", "species", "sampling",
    }
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError("release specification has unknown or missing fields")
    if spec["schema_version"] != SCHEMA_VERSION or spec["role"] != ROLE:
        raise ValueError("release specification schema or role is invalid")
    frame = spec["frame_id"]
    if not isinstance(frame, str) or not frame.strip():
        raise ValueError("frame_id must identify the caller's local Cartesian frame")
    count = spec["particle_count"]
    mother = spec["mother_particle_count"]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (count, mother)):
        raise ValueError("particle_count and mother_particle_count must be positive integers")
    if count > mother:
        raise ValueError("particle_count must be a prefix of mother_particle_count")
    _number(spec["common_time_of_birth_s"], "common_time_of_birth_s")
    geometry = _mapping(spec["geometry"], "geometry", {"shape", "center_mm", "axis", "radius_mm", "height_mm"})
    if geometry["shape"] != "cylinder":
        raise ValueError("cylinder materializer requires geometry.shape=cylinder")
    _vector3(geometry["center_mm"], "geometry.center_mm")
    _axis_index(geometry["axis"])
    _number(geometry["radius_mm"], "geometry.radius_mm", positive=True)
    _number(geometry["height_mm"], "geometry.height_mm", positive=True)
    species = _mapping(spec["species"], "species", {"mass_amu", "charge_state"})
    _number(species["mass_amu"], "species.mass_amu", positive=True)
    charge = species["charge_state"]
    if isinstance(charge, bool) or not isinstance(charge, int) or charge == 0:
        raise ValueError("species.charge_state must be a nonzero integer")
    sampling = spec["sampling"]
    if not isinstance(sampling, dict) or not isinstance(sampling.get("strategy"), str):
        raise ValueError("sampling.strategy is required")
    strategy = sampling["strategy"]
    if strategy == HALTON_STRATEGY:
        required_sampling = {"strategy", "kinetic_energy", "nominal_direction", "angular_full_width_deg"}
        if set(sampling) != required_sampling:
            raise ValueError("Halton sampling fields are invalid")
        energy = _mapping(sampling["kinetic_energy"], "sampling.kinetic_energy", {"center_ev", "full_width_ev"})
        center = _number(energy["center_ev"], "sampling.kinetic_energy.center_ev", positive=True)
        width = _number(energy["full_width_ev"], "sampling.kinetic_energy.full_width_ev")
        if width < 0.0 or center <= width / 2.0:
            raise ValueError("Halton kinetic-energy interval is not physical")
        _unit(_vector3(sampling["nominal_direction"], "sampling.nominal_direction"), "sampling.nominal_direction")
        angle = _number(sampling["angular_full_width_deg"], "sampling.angular_full_width_deg")
        if angle < 0.0 or angle >= 180.0:
            raise ValueError("Halton angular_full_width_deg must be in [0, 180)")
    elif strategy == GAUSSIAN_STRATEGY:
        required_sampling = {"strategy", "seed", "velocity_distribution"}
        if set(sampling) != required_sampling:
            raise ValueError("Gaussian sampling fields are invalid")
        if isinstance(sampling["seed"], bool) or not isinstance(sampling["seed"], int):
            raise ValueError("Gaussian seed must be an integer")
        distribution = _mapping(
            sampling["velocity_distribution"], "sampling.velocity_distribution",
            {"mean_m_s", "sigma_m_s", "minimum_axis_m_s"},
        )
        means = _vector3(distribution["mean_m_s"], "sampling.velocity_distribution.mean_m_s")
        sigmas = _vector3(distribution["sigma_m_s"], "sampling.velocity_distribution.sigma_m_s")
        if any(value < 0.0 for value in sigmas):
            raise ValueError("Gaussian velocity sigmas must be nonnegative")
        minimum = _number(distribution["minimum_axis_m_s"], "sampling.velocity_distribution.minimum_axis_m_s", positive=True)
        axis = _axis_index(geometry["axis"])
        if means[axis] <= minimum:
            raise ValueError("Gaussian axial mean velocity must exceed minimum_axis_m_s")
    else:
        raise ValueError("sampling.strategy is unsupported")


def _position(center: Sequence[float], axis: int, radius: float, height: float, radial: float, azimuth: float, axial: float) -> tuple[float, float, float]:
    result = list(center)
    transverse = [index for index in range(3) if index != axis]
    result[transverse[0]] += radial * math.cos(azimuth)
    result[transverse[1]] += radial * math.sin(azimuth)
    result[axis] += axial * height
    return tuple(result)  # type: ignore[return-value]


def _truncated_normal(rng: random.Random, mean: float, sigma: float, minimum: float) -> float:
    if sigma == 0.0:
        return mean
    for _ in range(10_000):
        value = rng.gauss(mean, sigma)
        if value >= minimum:
            return value
    raise RuntimeError("Gaussian axial velocity truncation did not converge")



def generate_center_first_halton_cylinder_phase_space(
    *,
    particle_count: int,
    center_mm: Sequence[float],
    transverse_axes: Sequence[int],
    axis: int,
    radius_mm: float,
    height_mm: float,
    kinetic_energy_center_ev: float,
    kinetic_energy_full_width_ev: float,
    nominal_direction: Sequence[float],
    angular_full_width_deg: float,
) -> list[dict[str, Any]]:
    """Generate a prefix-stable centre-first cylinder phase-space cohort.

    This solver-neutral primitive retains kinetic energy and direction rather
    than choosing a solver velocity representation.  Callers supply their
    local Cartesian frame and may choose the ordered transverse axes; this
    makes the cylinder orientation explicit without encoding project geometry.
    """
    if isinstance(particle_count, bool) or not isinstance(particle_count, int) or particle_count < 1:
        raise ValueError("particle_count must be a positive integer")
    if (
        not isinstance(transverse_axes, (list, tuple))
        or len(transverse_axes) != 2
        or set(transverse_axes) | {axis} != {0, 1, 2}
        or any(type(item) is not int or item not in (0, 1, 2) for item in transverse_axes)
        or type(axis) is not int
        or axis not in (0, 1, 2)
    ):
        raise ValueError("transverse_axes and axis must form one ordered Cartesian basis")
    center = _vector3(list(center_mm), "center_mm")
    radius = _number(radius_mm, "radius_mm", positive=True)
    height = _number(height_mm, "height_mm", positive=True)
    energy_center = _number(kinetic_energy_center_ev, "kinetic_energy_center_ev", positive=True)
    energy_width = _number(kinetic_energy_full_width_ev, "kinetic_energy_full_width_ev")
    if energy_width < 0.0 or energy_center <= energy_width / 2.0:
        raise ValueError("kinetic-energy interval is not physical")
    nominal = _unit(_vector3(list(nominal_direction), "nominal_direction"), "nominal_direction")
    angular_width = _number(angular_full_width_deg, "angular_full_width_deg")
    if angular_width < 0.0 or angular_width >= 180.0:
        raise ValueError("angular_full_width_deg must be in [0, 180)")
    tangent_1, tangent_2 = _tangent_basis(nominal)
    half_angle = math.radians(angular_width) / 2.0
    samples: list[dict[str, Any]] = []
    for offset in range(particle_count):
        if offset == 0:
            disk_radius = azimuth = axial = energy_delta = tilt_1 = tilt_2 = 0.0
        else:
            disk_radius = radius * math.sqrt(_radical_inverse(offset, 2))
            azimuth = 2.0 * math.pi * _radical_inverse(offset, 3)
            axial = _radical_inverse(offset, 5) - 0.5
            energy_delta = energy_width * (_radical_inverse(offset, 7) - 0.5)
            tilt_1 = half_angle * (2.0 * _radical_inverse(offset, 11) - 1.0)
            tilt_2 = half_angle * (2.0 * _radical_inverse(offset, 13) - 1.0)
        position = list(center)
        position[transverse_axes[0]] += disk_radius * math.cos(azimuth)
        position[transverse_axes[1]] += disk_radius * math.sin(azimuth)
        position[axis] += axial * height
        direction = _unit(tuple(
            nominal[index] + tilt_1 * tangent_1[index] + tilt_2 * tangent_2[index]
            for index in range(3)
        ), "sampled direction")
        samples.append({
            "particle_id": offset + 1,
            "position_mm": position,
            "kinetic_energy_ev": energy_center + energy_delta,
            "direction": list(direction),
        })
    return samples

def generate_cylinder_release_states(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate explicit canonical states from a validated cylinder-release spec."""
    validate_cylinder_release_spec(spec)
    geometry = spec["geometry"]
    sampling = spec["sampling"]
    center = _vector3(geometry["center_mm"], "geometry.center_mm")
    axis = _axis_index(geometry["axis"])
    radius = _number(geometry["radius_mm"], "geometry.radius_mm", positive=True)
    height = _number(geometry["height_mm"], "geometry.height_mm", positive=True)
    mass = _number(spec["species"]["mass_amu"], "species.mass_amu", positive=True)
    charge = int(spec["species"]["charge_state"])
    birth = _number(spec["common_time_of_birth_s"], "common_time_of_birth_s")
    count = int(spec["particle_count"])
    states: list[dict[str, Any]] = []
    if sampling["strategy"] == HALTON_STRATEGY:
        energy = sampling["kinetic_energy"]
        samples = generate_center_first_halton_cylinder_phase_space(
            particle_count=count,
            center_mm=center,
            transverse_axes=[index for index in range(3) if index != axis],
            axis=axis,
            radius_mm=radius,
            height_mm=height,
            kinetic_energy_center_ev=_number(energy["center_ev"], "sampling.kinetic_energy.center_ev", positive=True),
            kinetic_energy_full_width_ev=_number(energy["full_width_ev"], "sampling.kinetic_energy.full_width_ev"),
            nominal_direction=_vector3(sampling["nominal_direction"], "sampling.nominal_direction"),
            angular_full_width_deg=_number(sampling["angular_full_width_deg"], "sampling.angular_full_width_deg"),
        )
        for sample in samples:
            speed = speed_m_s_from_kinetic_energy_ev(mass, float(sample["kinetic_energy_ev"]))
            direction = sample["direction"]
            velocity = tuple(speed * float(item) for item in direction)
            states.append(_state(
                int(sample["particle_id"]), birth, sample["position_mm"], velocity, mass, charge,
            ))
    else:
        rng = random.Random(int(sampling["seed"]))
        distribution = sampling["velocity_distribution"]
        means = _vector3(distribution["mean_m_s"], "sampling.velocity_distribution.mean_m_s")
        sigmas = _vector3(distribution["sigma_m_s"], "sampling.velocity_distribution.sigma_m_s")
        minimum = _number(distribution["minimum_axis_m_s"], "sampling.velocity_distribution.minimum_axis_m_s", positive=True)
        for offset in range(count):
            radial = radius * math.sqrt(rng.random())
            azimuth = 2.0 * math.pi * rng.random()
            position = _position(center, axis, radius, height, radial, azimuth, rng.random() - 0.5)
            # Draw transverse components first, then the positive axial
            # component. This keeps the seeded Gaussian sequence stable for
            # a z-axis source while avoiding an unused axial draw.
            velocity = [
                _truncated_normal(rng, means[index], sigmas[index], minimum)
                if index == axis else rng.gauss(means[index], sigmas[index])
                for index in range(3)
            ]
            states.append(_state(offset + 1, birth, position, tuple(velocity), mass, charge))
    return states


def _state(particle_id: int, birth: float, position: Sequence[float], velocity: Sequence[float], mass: float, charge: int) -> dict[str, Any]:
    return {
        "particle_id": particle_id, "birth_time_s": birth,
        "x_mm": position[0], "y_mm": position[1], "z_mm": position[2],
        "vx_m_s": velocity[0], "vy_m_s": velocity[1], "vz_m_s": velocity[2],
        "mass_amu": mass, "charge_state": charge,
    }


def _serialized_rows(states: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for state in states:
        rows.append({
            "particle_id": str(int(state["particle_id"])),
            "birth_time_s": format(float(state["birth_time_s"]), ".17g"),
            **{name: format(float(state[name]), ".17g") for name in ("x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu")},
            "charge_state": str(int(state["charge_state"])),
        })
    return rows


def _state_identity(states: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    canonical = _canonical_json(list(states))
    ids = [int(state["particle_id"]) for state in states]
    return {
        "ordered_particle_ids_sha256": _sha256_text(_canonical_json(ids)),
        "canonical_states_sha256": _sha256_text(canonical),
    }


def materialize_cylinder_release(spec: Mapping[str, Any], state_table_path: Path, receipt_path: Path, *, spec_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Write the canonical table and a receipt that binds its complete identity."""
    states = generate_cylinder_release_states(spec)
    rows = _serialized_rows(states)
    state_table_path.parent.mkdir(parents=True, exist_ok=True)
    with state_table_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "role": ROLE,
        "status": "materialized",
        "frame_id": spec["frame_id"],
        "particle_count": int(spec["particle_count"]),
        "mother_particle_count": int(spec["mother_particle_count"]),
        "release_spec": dict(spec),
        "release_spec_sha256": _sha256_text(_canonical_json(spec)),
        "state_identity": _state_identity(states),
        "state_table": {
            "path": str(state_table_path.resolve()),
            "bytes": state_table_path.stat().st_size,
            "sha256": file_sha256(state_table_path),
            "columns": list(CANONICAL_COLUMNS),
        },
        "source_spec": dict(spec_record) if spec_record is not None else None,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return receipt


def materialize_cylinder_release_from_file(spec_path: Path, state_table_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Materialize a release and bind the frozen JSON request by bytes and SHA-256."""
    spec_path = spec_path.resolve(strict=True)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("release specification is unreadable") from error
    if not isinstance(spec, dict):
        raise ValueError("release specification must be an object")
    return materialize_cylinder_release(
        spec, state_table_path, receipt_path,
        spec_record={"path": str(spec_path), "bytes": spec_path.stat().st_size, "sha256": file_sha256(spec_path)},
    )


def validate_materialized_cylinder_release(receipt_path: Path) -> dict[str, Any]:
    """Rebuild and validate a materialized table without invoking a solver."""
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("release receipt is unreadable") from error
    if not isinstance(receipt, dict) or (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("role") != ROLE
        or receipt.get("status") != "materialized"
    ):
        raise ValueError("release receipt identity is invalid")
    spec = receipt.get("release_spec")
    if not isinstance(spec, dict):
        raise ValueError("release receipt lacks its release specification")
    validate_cylinder_release_spec(spec)
    if receipt.get("release_spec_sha256") != _sha256_text(_canonical_json(spec)):
        raise ValueError("release specification identity changed")
    source_spec = receipt.get("source_spec")
    if source_spec is not None:
        if not isinstance(source_spec, dict) or not isinstance(source_spec.get("path"), str):
            raise ValueError("release receipt source-spec binding is incomplete")
        source_path = Path(source_spec["path"])
        if (
            not source_path.is_file()
            or source_path.stat().st_size != source_spec.get("bytes")
            or file_sha256(source_path) != source_spec.get("sha256")
        ):
            raise ValueError("release source specification identity changed")
    table = receipt.get("state_table")
    if not isinstance(table, dict) or table.get("columns") != list(CANONICAL_COLUMNS):
        raise ValueError("release receipt state-table binding is incomplete")
    path = Path(str(table.get("path", "")))
    if not path.is_file() or path.stat().st_size != table.get("bytes") or file_sha256(path) != table.get("sha256"):
        raise ValueError("release state-table identity changed")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CANONICAL_COLUMNS:
            raise ValueError("release state-table columns changed")
        rows = list(reader)
    expected = _serialized_rows(generate_cylinder_release_states(spec))
    if rows != expected:
        raise ValueError("release state-table differs from deterministic specification")
    states = generate_cylinder_release_states(spec)
    if receipt.get("state_identity") != _state_identity(states):
        raise ValueError("release state identity changed")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--materialize", type=Path)
    action.add_argument("--validate", type=Path)
    parser.add_argument("--state-table", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.materialize is not None:
        if args.state_table is None or args.receipt is None:
            parser.error("--materialize requires --state-table and --receipt")
        result = materialize_cylinder_release_from_file(args.materialize, args.state_table, args.receipt)
    else:
        if args.state_table is not None or args.receipt is not None:
            parser.error("--validate accepts only the receipt path")
        result = validate_materialized_cylinder_release(args.validate)
    print(f"ION_RELEASE_CYLINDER=PASS PARTICLES={result['particle_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
