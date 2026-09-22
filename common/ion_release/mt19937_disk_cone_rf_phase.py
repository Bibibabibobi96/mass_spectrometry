"""Deterministic MT19937 disk, filled-cone, and RF-phase ion release.

This is the repository implementation of the historical RF-multipole source
sequence.  Its draw order and Python ``repr`` CSV serialization are explicit
because frozen family CSVs bind those bytes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import speed_m_s_from_kinetic_energy_ev
from common.ion_release.cylinder import CANONICAL_COLUMNS, ROLE, SCHEMA_VERSION


STRATEGY = "mt19937_uniform_disk_filled_cone_rf_phase_v1"
IDEAL_TRANSPORT_STRATEGY = "mt19937_uniform_disk_sqrt_cone_rf_phase_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise ValueError(f"{label} must be finite" + (" and positive" if positive else ""))
    return result


def _vector3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must contain exactly three values")
    return tuple(_number(item, label) for item in value)  # type: ignore[return-value]


def _mapping(value: Any, label: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(keys))}")
    return value


def _validate_release_spec(spec: Mapping[str, Any], *, strategy: str) -> None:
    """Validate the complete, solver-neutral disk/cone/RF release request."""
    required = {"schema_version", "role", "frame_id", "particle_count", "mother_particle_count", "geometry", "species", "sampling"}
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError("release specification has unknown or missing fields")
    if spec["schema_version"] != SCHEMA_VERSION or spec["role"] != ROLE:
        raise ValueError("release specification schema or role is invalid")
    if not isinstance(spec["frame_id"], str) or not spec["frame_id"].strip():
        raise ValueError("frame_id must identify the caller's local Cartesian frame")
    count, mother = spec["particle_count"], spec["mother_particle_count"]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (count, mother)):
        raise ValueError("particle_count and mother_particle_count must be positive integers")
    if count > mother:
        raise ValueError("particle_count must be a prefix of mother_particle_count")
    geometry = _mapping(spec["geometry"], "geometry", {"shape", "center_mm", "radius_mm"})
    if geometry["shape"] != "disk":
        raise ValueError("disk/cone materializer requires geometry.shape=disk")
    _vector3(geometry["center_mm"], "geometry.center_mm")
    _number(geometry["radius_mm"], "geometry.radius_mm", positive=True)
    species = _mapping(spec["species"], "species", {"mass_amu", "charge_state"})
    _number(species["mass_amu"], "species.mass_amu", positive=True)
    if isinstance(species["charge_state"], bool) or not isinstance(species["charge_state"], int) or species["charge_state"] == 0:
        raise ValueError("species.charge_state must be a nonzero integer")
    sampling = _mapping(spec["sampling"], "sampling", {"strategy", "seed", "rf_frequency_hz", "kinetic_energy_ev", "cone_half_angle_deg"})
    if sampling["strategy"] != strategy:
        raise ValueError("disk/cone/RF sampling strategy is invalid")
    if isinstance(sampling["seed"], bool) or not isinstance(sampling["seed"], int):
        raise ValueError("sampling.seed must be an integer")
    _number(sampling["rf_frequency_hz"], "sampling.rf_frequency_hz", positive=True)
    _number(sampling["kinetic_energy_ev"], "sampling.kinetic_energy_ev", positive=True)
    half_angle = _number(sampling["cone_half_angle_deg"], "sampling.cone_half_angle_deg")
    if half_angle < 0.0 or half_angle >= 90.0:
        raise ValueError("sampling.cone_half_angle_deg must be in [0, 90)")


def validate_mt19937_disk_cone_rf_phase_release_spec(spec: Mapping[str, Any]) -> None:
    """Validate the filled-solid-angle disk/cone/RF release request."""
    _validate_release_spec(spec, strategy=STRATEGY)


def validate_mt19937_disk_sqrt_cone_rf_phase_release_spec(spec: Mapping[str, Any]) -> None:
    """Validate the historical ideal-transport disk/cone/RF request."""
    _validate_release_spec(spec, strategy=IDEAL_TRANSPORT_STRATEGY)


def generate_mt19937_disk_cone_rf_phase_states(spec: Mapping[str, Any]) -> list[dict[str, object]]:
    """Generate canonical states using the frozen five-draw MT19937 sequence."""
    validate_mt19937_disk_cone_rf_phase_release_spec(spec)
    geometry = spec["geometry"]
    species = spec["species"]
    sampling = spec["sampling"]
    center = _vector3(geometry["center_mm"], "geometry.center_mm")
    radius = _number(geometry["radius_mm"], "geometry.radius_mm", positive=True)
    mass = _number(species["mass_amu"], "species.mass_amu", positive=True)
    charge = int(species["charge_state"])
    frequency = _number(sampling["rf_frequency_hz"], "sampling.rf_frequency_hz", positive=True)
    speed = speed_m_s_from_kinetic_energy_ev(mass, _number(sampling["kinetic_energy_ev"], "sampling.kinetic_energy_ev", positive=True))
    cone_cosine = math.cos(math.radians(_number(sampling["cone_half_angle_deg"], "sampling.cone_half_angle_deg")))
    rng = random.Random(int(sampling["seed"]))
    states: list[dict[str, object]] = []
    for particle_id in range(1, int(spec["particle_count"]) + 1):
        birth_time = rng.random() / frequency
        radial = radius * math.sqrt(rng.random())
        position_angle = 2.0 * math.pi * rng.random()
        direction_cosine = 1.0 - rng.random() * (1.0 - cone_cosine)
        direction_sine = math.sqrt(1.0 - direction_cosine * direction_cosine)
        direction_angle = 2.0 * math.pi * rng.random()
        states.append({
            "particle_id": particle_id,
            "birth_time_s": birth_time,
            "x_mm": center[0] + radial * math.cos(position_angle),
            "y_mm": center[1] + radial * math.sin(position_angle),
            "z_mm": center[2],
            "vx_m_s": speed * direction_sine * math.cos(direction_angle),
            "vy_m_s": speed * direction_sine * math.sin(direction_angle),
            "vz_m_s": speed * direction_cosine,
            "mass_amu": mass,
            "charge_state": charge,
        })
    return states


def generate_mt19937_disk_sqrt_cone_rf_phase_states(spec: Mapping[str, Any]) -> list[dict[str, object]]:
    """Generate the L1 reference's frozen radius/angle/cone/angle/time sequence.

    This intentionally keeps the historical ``sqrt(u)`` cone-angle law and
    draw order.  It is distinct from :data:`STRATEGY`, whose direction is
    uniform over solid angle.
    """
    validate_mt19937_disk_sqrt_cone_rf_phase_release_spec(spec)
    geometry = spec["geometry"]
    species = spec["species"]
    sampling = spec["sampling"]
    center = _vector3(geometry["center_mm"], "geometry.center_mm")
    radius = _number(geometry["radius_mm"], "geometry.radius_mm", positive=True)
    mass = _number(species["mass_amu"], "species.mass_amu", positive=True)
    charge = int(species["charge_state"])
    frequency = _number(sampling["rf_frequency_hz"], "sampling.rf_frequency_hz", positive=True)
    period = 1.0 / frequency
    speed = speed_m_s_from_kinetic_energy_ev(
        mass,
        _number(sampling["kinetic_energy_ev"], "sampling.kinetic_energy_ev", positive=True),
    )
    cone_half_angle = math.radians(_number(sampling["cone_half_angle_deg"], "sampling.cone_half_angle_deg"))
    rng = random.Random(int(sampling["seed"]))
    states: list[dict[str, object]] = []
    for particle_id in range(1, int(spec["particle_count"]) + 1):
        radial = radius * math.sqrt(rng.random())
        position_angle = 2.0 * math.pi * rng.random()
        cone_angle = cone_half_angle * math.sqrt(rng.random())
        direction_angle = 2.0 * math.pi * rng.random()
        birth_time = rng.random() * period
        states.append({
            "particle_id": particle_id,
            "birth_time_s": birth_time,
            "x_mm": center[0] + radial * math.cos(position_angle),
            "y_mm": center[1] + radial * math.sin(position_angle),
            "z_mm": center[2],
            "vx_m_s": speed * math.sin(cone_angle) * math.cos(direction_angle),
            "vy_m_s": speed * math.sin(cone_angle) * math.sin(direction_angle),
            "vz_m_s": speed * math.cos(cone_angle),
            "mass_amu": mass,
            "charge_state": charge,
        })
    return states


def _serialized_rows(states: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Use Python repr to reproduce the existing frozen source CSV bytes."""
    fields = ("birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu")
    return [
        {"particle_id": int(state["particle_id"]), **{field: repr(state[field]) for field in fields}, "charge_state": int(state["charge_state"])}
        for state in states
    ]


def _render(states: Sequence[Mapping[str, object]]) -> bytes:
    with io.StringIO(newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(_serialized_rows(states))
        return stream.getvalue().encode("utf-8")


def _state_identity(states: Sequence[Mapping[str, object]]) -> dict[str, str]:
    return {
        "ordered_particle_ids_sha256": _sha256_text(_canonical_json([int(state["particle_id"]) for state in states])),
        "canonical_states_sha256": _sha256_text(_canonical_json(list(states))),
    }


def _materialize(
    spec: Mapping[str, Any], state_table_path: Path, receipt_path: Path,
    spec_record: Mapping[str, Any] | None, generator: Any,
) -> dict[str, Any]:
    """Write the canonical source table and its content-bound receipt."""
    states = generator(spec)
    state_table_path.parent.mkdir(parents=True, exist_ok=True)
    state_table_path.write_bytes(_render(states))
    receipt = {
        "schema_version": SCHEMA_VERSION, "role": ROLE, "status": "materialized",
        "frame_id": spec["frame_id"], "particle_count": int(spec["particle_count"]),
        "mother_particle_count": int(spec["mother_particle_count"]), "release_spec": dict(spec),
        "release_spec_sha256": _sha256_text(_canonical_json(spec)), "state_identity": _state_identity(states),
        "state_table": {"path": str(state_table_path.resolve()), "bytes": state_table_path.stat().st_size, "sha256": file_sha256(state_table_path), "columns": list(CANONICAL_COLUMNS)},
        "source_spec": dict(spec_record) if spec_record is not None else None,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return receipt


def materialize_mt19937_disk_cone_rf_phase_release(spec: Mapping[str, Any], state_table_path: Path, receipt_path: Path, spec_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Write the filled-solid-angle disk/cone source table and receipt."""
    return _materialize(spec, state_table_path, receipt_path, spec_record, generate_mt19937_disk_cone_rf_phase_states)


def materialize_mt19937_disk_sqrt_cone_rf_phase_release(spec: Mapping[str, Any], state_table_path: Path, receipt_path: Path, spec_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Write the historical ideal-transport disk/cone source table and receipt."""
    return _materialize(spec, state_table_path, receipt_path, spec_record, generate_mt19937_disk_sqrt_cone_rf_phase_states)


def _validate_materialized_release(receipt_path: Path, *, validator: Any, generator: Any) -> dict[str, Any]:
    """Regenerate and validate a disk/cone/RF receipt without a solver."""
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("release receipt is unreadable") from error
    if not isinstance(receipt, dict) or receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("role") != ROLE or receipt.get("status") != "materialized":
        raise ValueError("release receipt identity is invalid")
    spec = receipt.get("release_spec")
    if not isinstance(spec, dict):
        raise ValueError("release receipt lacks its release specification")
    validator(spec)
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
    table_path = Path(str(table.get("path", "")))
    if not table_path.is_file() or table_path.stat().st_size != table.get("bytes") or file_sha256(table_path) != table.get("sha256"):
        raise ValueError("release state-table identity changed")
    states = generator(spec)
    if table_path.read_bytes() != _render(states) or receipt.get("state_identity") != _state_identity(states):
        raise ValueError("release state-table differs from deterministic specification")
    return receipt


def validate_materialized_mt19937_disk_cone_rf_phase_release(receipt_path: Path) -> dict[str, Any]:
    """Regenerate and validate a filled-solid-angle disk/cone/RF receipt."""
    return _validate_materialized_release(
        receipt_path,
        validator=validate_mt19937_disk_cone_rf_phase_release_spec,
        generator=generate_mt19937_disk_cone_rf_phase_states,
    )


def validate_materialized_mt19937_disk_sqrt_cone_rf_phase_release(receipt_path: Path) -> dict[str, Any]:
    """Regenerate and validate a historical ideal-transport source receipt."""
    return _validate_materialized_release(
        receipt_path,
        validator=validate_mt19937_disk_sqrt_cone_rf_phase_release_spec,
        generator=generate_mt19937_disk_sqrt_cone_rf_phase_states,
    )
