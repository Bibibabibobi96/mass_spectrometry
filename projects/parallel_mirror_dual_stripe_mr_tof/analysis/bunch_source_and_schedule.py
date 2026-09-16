"""Deterministic MR-TOF bunch states and detector-blind accelerator timing.

This module contains no solver calls and chooses no physical widths.  Callers
must supply the complete source envelope and the trajectory step used by the
pilot flight.  The generated particle order is prefix-stable, so the standard
N=100 cohort is the exact leading prefix of the N=1000 mother cohort.
"""
from __future__ import annotations

import argparse
import hashlib
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.simion.particle_source import render_standard_beams
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_two_zone_placement,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    parse_events,
)


_CLOCK_BASIS = "ion_time_of_flight_us_from_common_tob_zero_release"
_SAMPLING_METHOD = "center_first_halton_position_energy_angle_v1"
_SOURCE_DEFINITION_ROLE = "mrtof_ideal_bunch_source_definition"
_CURRENT_SOURCE_DEFINITION_SCHEMA = 2
_COORDINATE_SEMANTICS = {
    "x": "transverse_mirror_focusing",
    "y": "slow_drift_positive_stripe_function_argument",
    "z": "fast_reflection_and_acceleration_axis",
    "workbench_from_project": "identity",
}


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _vector3(values: Sequence[float], label: str) -> tuple[float, float, float]:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise CandidateContractError(f"{label} must contain three values")
    return tuple(_finite(value, label) for value in values)  # type: ignore[return-value]


def _radical_inverse(index: int, base: int) -> float:
    if index < 0 or base < 2:
        raise ValueError("radical inverse requires index >= 0 and base >= 2")
    value = 0.0
    factor = 1.0 / base
    while index:
        index, digit = divmod(index, base)
        value += digit * factor
        factor /= base
    return value


def _normalize(values: Sequence[float]) -> tuple[float, float, float]:
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0.0:
        raise CandidateContractError("source direction must be nonzero")
    return tuple(value / norm for value in values)  # type: ignore[return-value]


def _tangent_basis(
    direction: Sequence[float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    unit = _normalize(direction)
    reference = (0.0, 0.0, 1.0) if abs(unit[2]) < 0.9 else (1.0, 0.0, 0.0)
    first = _normalize((
        unit[1] * reference[2] - unit[2] * reference[1],
        unit[2] * reference[0] - unit[0] * reference[2],
        unit[0] * reference[1] - unit[1] * reference[0],
    ))
    second = _normalize((
        unit[1] * first[2] - unit[2] * first[1],
        unit[2] * first[0] - unit[0] * first[2],
        unit[0] * first[1] - unit[1] * first[0],
    ))
    return first, second


def deterministic_ideal_bunch_states(
    *,
    particle_count: int,
    mother_particle_count: int,
    center_workbench_mm: Sequence[float],
    aperture_plane_axes: tuple[int, int],
    acceleration_axis: int,
    position_radius_mm: float,
    acceleration_axis_full_width_mm: float,
    kinetic_energy_center_ev: float,
    kinetic_energy_full_width_ev: float,
    nominal_direction_workbench: Sequence[float],
    angular_full_width_deg: float,
    mass_th: float,
    charge_e: int,
    common_time_of_birth_us: float = 0.0,
) -> list[dict[str, Any]]:
    """Return an explicit, byte-stable ideal cohort with a centre-first prefix.

    All spreads are full widths.  The first particle is exactly the nominal
    centre state.  Later particles use fixed Halton coordinates; no solver RNG
    participates in the source identity.
    """
    try:
        validate_standard_particle_count(particle_count)
        validate_standard_particle_count(mother_particle_count)
    except ValueError as error:
        raise CandidateContractError(str(error)) from error
    if mother_particle_count < particle_count:
        raise CandidateContractError("particle count must be a mother-cohort prefix")
    if any(axis not in (0, 1, 2) for axis in aperture_plane_axes) or len(set(aperture_plane_axes)) != 2:
        raise CandidateContractError("aperture plane axes must be two unique axes")
    if acceleration_axis not in (0, 1, 2) or acceleration_axis in aperture_plane_axes:
        raise CandidateContractError("acceleration axis must complement the aperture plane")
    center = _vector3(center_workbench_mm, "source centre")
    nominal = _normalize(_vector3(nominal_direction_workbench, "nominal direction"))
    tangent_1, tangent_2 = _tangent_basis(nominal)
    radius = _finite(position_radius_mm, "position radius")
    axial_width = _finite(acceleration_axis_full_width_mm, "axial full width")
    energy_center = _finite(kinetic_energy_center_ev, "kinetic-energy centre")
    energy_width = _finite(kinetic_energy_full_width_ev, "kinetic-energy full width")
    angular_width = _finite(angular_full_width_deg, "angular full width")
    mass = _finite(mass_th, "particle mass")
    tob = _finite(common_time_of_birth_us, "common time of birth")
    if radius < 0 or axial_width < 0 or energy_width < 0 or angular_width < 0:
        raise CandidateContractError("source spread widths must be nonnegative")
    if energy_center <= energy_width / 2.0 or mass <= 0 or type(charge_e) is not int or charge_e == 0:
        raise CandidateContractError("source species and energy envelope must be physical")

    states: list[dict[str, Any]] = []
    for offset in range(particle_count):
        if offset == 0:
            disk_radius = angle = axial = energy_delta = tilt_1 = tilt_2 = 0.0
        else:
            disk_radius = radius * math.sqrt(_radical_inverse(offset, 2))
            angle = 2.0 * math.pi * _radical_inverse(offset, 3)
            axial = axial_width * (_radical_inverse(offset, 5) - 0.5)
            energy_delta = energy_width * (_radical_inverse(offset, 7) - 0.5)
            half_angle_rad = math.radians(angular_width) / 2.0
            tilt_1 = half_angle_rad * (2.0 * _radical_inverse(offset, 11) - 1.0)
            tilt_2 = half_angle_rad * (2.0 * _radical_inverse(offset, 13) - 1.0)
        position = list(center)
        position[aperture_plane_axes[0]] += disk_radius * math.cos(angle)
        position[aperture_plane_axes[1]] += disk_radius * math.sin(angle)
        position[acceleration_axis] += axial
        direction = _normalize(tuple(
            nominal[axis] + tilt_1 * tangent_1[axis] + tilt_2 * tangent_2[axis]
            for axis in range(3)
        ))
        states.append({
            "particle_id": offset + 1,
            "tob_us": tob,
            "mass_th": mass,
            "charge_e": charge_e,
            "kinetic_energy_ev": energy_center + energy_delta,
            "position_workbench_mm": position,
            "direction_workbench": list(direction),
        })
    return states


def materialize_bunch_source_from_definition(
    *,
    definition_path: Path,
    state_table_path: Path,
    fly2_path: Path,
    receipt_path: Path,
    geometry_contract_path: Path | None = None,
) -> dict[str, Any]:
    """Materialize a cohort only from one complete frozen source definition."""
    definition = _load_object(definition_path, "bunch source definition")
    schema_version = definition.get("schema_version")
    if (
        schema_version not in (1, _CURRENT_SOURCE_DEFINITION_SCHEMA)
        or definition.get("role") != _SOURCE_DEFINITION_ROLE
        or definition.get("status") != "frozen"
    ):
        raise CandidateContractError("bunch source definition identity is invalid")
    required = (
        "source_profile_id", "frame_id", "particle_count", "mother_particle_count",
        "center_workbench_mm", "aperture_plane_axes", "acceleration_axis",
        "position_radius_mm", "acceleration_axis_full_width_mm",
        "kinetic_energy_center_ev", "kinetic_energy_full_width_ev",
        "nominal_direction_workbench", "angular_full_width_deg",
        "mass_th", "charge_e", "common_time_of_birth_us",
    )
    missing = [name for name in required if name not in definition]
    if missing:
        raise CandidateContractError(
            "bunch source definition is incomplete: " + ", ".join(missing)
        )
    geometry_binding: dict[str, Any] | None = None
    if schema_version == _CURRENT_SOURCE_DEFINITION_SCHEMA:
        if geometry_contract_path is None:
            raise CandidateContractError(
                "schema-2 bunch source definition requires its geometry contract"
            )
        geometry_contract = load_contract(geometry_contract_path)
        frame = geometry_contract["coordinate_system"]
        transform = frame.get("simion_workbench_from_project")
        if (
            definition.get("frame_id") != frame.get("frame_id")
            or definition.get("coordinate_semantics") != _COORDINATE_SEMANTICS
            or not isinstance(transform, dict)
            or transform.get("rotation") != [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
            or transform.get("translation_mm") != [0, 0, 0]
        ):
            raise CandidateContractError(
                "bunch source coordinates must use the identity project/workbench x-y-z frame"
            )
        placement = derive_two_zone_placement(geometry_contract)
        release = _finite(
            geometry_contract["accelerator"].get("release_position_in_gap_1_mm"),
            "accelerator release position",
        )
        expected_center = (
            0.0,
            placement.focus_y_mm,
            placement.repeller_z_mm - release,
        )
        actual_center = _vector3(definition["center_workbench_mm"], "source centre")
        if any(
            not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)
            for actual, expected in zip(actual_center, expected_center, strict=True)
        ):
            raise CandidateContractError(
                "bunch source centre differs from the resolved accelerator release position"
            )
        authority = definition.get("center_authority")
        geometry_sha = file_sha256(geometry_contract_path).lower()
        if (
            not isinstance(authority, dict)
            or authority.get("method")
            != "derived_two_zone_placement_repeller_minus_gap1_release"
            or str(authority.get("geometry_contract_sha256", "")).lower() != geometry_sha
        ):
            raise CandidateContractError("bunch source centre authority is invalid")
        geometry_binding = {
            "path": str(geometry_contract_path.resolve()),
            "bytes": geometry_contract_path.stat().st_size,
            "sha256": geometry_sha,
            "derived_center_workbench_mm": list(expected_center),
        }
    states = deterministic_ideal_bunch_states(
        particle_count=definition["particle_count"],
        mother_particle_count=definition["mother_particle_count"],
        center_workbench_mm=definition["center_workbench_mm"],
        aperture_plane_axes=tuple(definition["aperture_plane_axes"]),
        acceleration_axis=definition["acceleration_axis"],
        position_radius_mm=definition["position_radius_mm"],
        acceleration_axis_full_width_mm=definition["acceleration_axis_full_width_mm"],
        kinetic_energy_center_ev=definition["kinetic_energy_center_ev"],
        kinetic_energy_full_width_ev=definition["kinetic_energy_full_width_ev"],
        nominal_direction_workbench=definition["nominal_direction_workbench"],
        angular_full_width_deg=definition["angular_full_width_deg"],
        mass_th=definition["mass_th"],
        charge_e=definition["charge_e"],
        common_time_of_birth_us=definition["common_time_of_birth_us"],
    )
    receipt = materialize_bunch_source(
        states=states,
        mother_particle_count=definition["mother_particle_count"],
        source_profile_id=definition["source_profile_id"],
        frame_id=definition["frame_id"],
        state_table_path=state_table_path,
        fly2_path=fly2_path,
        receipt_path=receipt_path,
    )
    receipt["definition"] = {
        "path": str(definition_path.resolve()),
        "bytes": definition_path.stat().st_size,
        "sha256": file_sha256(definition_path).lower(),
    }
    if geometry_binding is not None:
        receipt["geometry_contract"] = geometry_binding
        receipt["center_authority"] = dict(definition["center_authority"])
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return receipt


def bunch_identity(states: Sequence[Mapping[str, Any]], mother_particle_count: int) -> dict[str, Any]:
    """Return the exact ordered state and particle-ID identities."""
    try:
        validate_standard_particle_count(mother_particle_count)
    except ValueError as error:
        raise CandidateContractError(str(error)) from error
    if mother_particle_count < len(states):
        raise CandidateContractError("mother cohort cannot be smaller than its materialized prefix")
    particle_ids = [int(state["particle_id"]) for state in states]
    if particle_ids != list(range(1, len(states) + 1)):
        raise CandidateContractError("bunch particle IDs must be contiguous and one-based")
    canonical = json.dumps(list(states), sort_keys=True, separators=(",", ":"), allow_nan=False)
    ids = json.dumps(particle_ids, separators=(",", ":"))
    return {
        "sampling_method": _SAMPLING_METHOD,
        "particle_count": len(states),
        "mother_particle_count": mother_particle_count,
        "prefix_rule": "ordered_first_n_states_of_one_mother_cohort",
        "clock_basis": _CLOCK_BASIS,
        "expected_particle_ids": particle_ids,
        "expected_particle_ids_sha256": hashlib.sha256(ids.encode("utf-8")).hexdigest(),
        "particle_states_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def render_bunch_fly2(states: Sequence[Mapping[str, Any]]) -> str:
    """Serialize every frozen state as its own SIMION ``n=1`` beam."""
    beams = []
    for state in states:
        position = _vector3(state["position_workbench_mm"], "state position")
        direction = _normalize(_vector3(state["direction_workbench"], "state direction"))
        charge = state.get("charge_e")
        if type(charge) is not int or charge == 0:
            raise CandidateContractError("state charge must be a nonzero integer")
        beams.append({
            "tob": f"{_finite(state['tob_us'], 'state tob'):.17g}",
            "mass": f"{_finite(state['mass_th'], 'state mass'):.17g}",
            "charge": str(charge),
            "x": f"{position[0]:.17g}", "y": f"{position[1]:.17g}", "z": f"{position[2]:.17g}",
            "direction": [f"{value:.17g}" for value in direction],
            "ke": f"{_finite(state['kinetic_energy_ev'], 'state energy'):.17g}",
            "cwf": "1", "color": "0",
        })
    return render_standard_beams(beams)


def materialize_bunch_source(
    *,
    states: Sequence[Mapping[str, Any]],
    mother_particle_count: int,
    source_profile_id: str,
    frame_id: str,
    state_table_path: Path,
    fly2_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    """Write one explicit cohort as a prefix-comparable CSV and Fly2 pair."""
    if not source_profile_id or not frame_id:
        raise CandidateContractError("source profile and frame identities are required")
    if not states:
        raise CandidateContractError("bunch source must contain at least one state")
    masses = {_finite(state["mass_th"], "state mass") for state in states}
    charges = {state.get("charge_e") for state in states}
    birth_times = {_finite(state["tob_us"], "state tob") for state in states}
    if len(masses) != 1 or len(charges) != 1 or len(birth_times) != 1:
        raise CandidateContractError("bunch source must use one species and one common birth time")
    charge = next(iter(charges))
    if type(charge) is not int or charge == 0:
        raise CandidateContractError("bunch source charge must be a nonzero integer")
    identity = bunch_identity(states, mother_particle_count)
    columns = (
        "particle_id", "tob_us", "mass_th", "charge_e", "kinetic_energy_ev",
        "x_mm", "y_mm", "z_mm", "direction_x", "direction_y", "direction_z",
    )
    state_table_path.parent.mkdir(parents=True, exist_ok=True)
    with state_table_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(columns)
        for state in states:
            position = _vector3(state["position_workbench_mm"], "state position")
            direction = _normalize(_vector3(state["direction_workbench"], "state direction"))
            writer.writerow((
                int(state["particle_id"]),
                f"{_finite(state['tob_us'], 'state tob'):.17g}",
                f"{_finite(state['mass_th'], 'state mass'):.17g}",
                int(state["charge_e"]),
                f"{_finite(state['kinetic_energy_ev'], 'state energy'):.17g}",
                *(f"{value:.17g}" for value in position),
                *(f"{value:.17g}" for value in direction),
            ))
    fly2_path.parent.mkdir(parents=True, exist_ok=True)
    fly2_path.write_text(render_bunch_fly2(states), encoding="utf-8", newline="\n")
    receipt = {
        "schema_version": 1,
        "role": "mrtof_deterministic_ideal_bunch_source",
        "status": "materialized",
        "source_profile_id": source_profile_id,
        "frame_id": frame_id,
        "species": {"mass_th": next(iter(masses)), "charge_e": charge},
        "common_time_of_birth_us": next(iter(birth_times)),
        **identity,
        "state_table": {
            "path": str(state_table_path.resolve()),
            "bytes": state_table_path.stat().st_size,
            "sha256": file_sha256(state_table_path).lower(),
        },
        "fly2": {
            "path": str(fly2_path.resolve()),
            "bytes": fly2_path.stat().st_size,
            "sha256": file_sha256(fly2_path).lower(),
        },
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    return receipt


def load_verified_bunch_source_receipt(receipt_path: Path) -> dict[str, Any]:
    """Load a materialized bunch only when both payloads retain their identity."""
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError("bunch source receipt is unreadable") from error
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or receipt.get("role") != "mrtof_deterministic_ideal_bunch_source"
        or receipt.get("status") != "materialized"
        or receipt.get("sampling_method") != _SAMPLING_METHOD
        or receipt.get("clock_basis") != _CLOCK_BASIS
    ):
        raise CandidateContractError("bunch source receipt identity is invalid")
    species = receipt.get("species")
    if (
        not isinstance(species, dict)
        or _finite(species.get("mass_th"), "bunch source mass") <= 0
        or type(species.get("charge_e")) is not int
        or species["charge_e"] == 0
    ):
        raise CandidateContractError("bunch source receipt species is invalid")
    _finite(receipt.get("common_time_of_birth_us"), "bunch source common birth time")
    if type(receipt.get("particle_count")) is not int or type(receipt.get("mother_particle_count")) is not int:
        raise CandidateContractError("bunch source receipt has a nonstandard particle count")
    try:
        validate_standard_particle_count(receipt["particle_count"])
        validate_standard_particle_count(receipt["mother_particle_count"])
    except (TypeError, ValueError) as error:
        raise CandidateContractError("bunch source receipt has a nonstandard particle count") from error
    expected = receipt.get("expected_particle_ids")
    count = int(receipt["particle_count"])
    if int(receipt["mother_particle_count"]) < count:
        raise CandidateContractError("bunch source mother cohort is smaller than its prefix")
    if expected != list(range(1, count + 1)):
        raise CandidateContractError("bunch source receipt has the wrong ordered particle IDs")
    ids = json.dumps(expected, separators=(",", ":")).encode("utf-8")
    if receipt.get("expected_particle_ids_sha256") != hashlib.sha256(ids).hexdigest():
        raise CandidateContractError("bunch source ordered-ID identity changed")
    for key in ("state_table", "fly2"):
        record = receipt.get(key)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise CandidateContractError(f"bunch source {key} binding is incomplete")
        path = Path(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != record.get("bytes")
            or file_sha256(path).lower() != str(record.get("sha256", "")).lower()
        ):
            raise CandidateContractError(f"bunch source {key} identity changed")
    for key in ("definition", "geometry_contract"):
        record = receipt.get(key)
        if record is None:
            continue
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise CandidateContractError(f"bunch source {key} binding is incomplete")
        path = Path(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != record.get("bytes")
            or file_sha256(path).lower() != str(record.get("sha256", "")).lower()
        ):
            raise CandidateContractError(f"bunch source {key} identity changed")
    state_table_path = Path(receipt["state_table"]["path"])
    with state_table_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != count or [int(row["particle_id"]) for row in rows] != expected:
        raise CandidateContractError("bunch state table differs from its particle contract")
    fly2_text = Path(receipt["fly2"]["path"]).read_text(encoding="utf-8")
    if fly2_text.count("standard_beam {") != count or "circle_distribution" in fly2_text:
        raise CandidateContractError("bunch Fly2 is not an explicit per-particle source")
    return receipt


def source_cohort_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Project the immutable source fields used by pilot and fixed-time flights."""
    keys = (
        "source_profile_id", "frame_id", "sampling_method", "particle_count",
        "mother_particle_count", "prefix_rule", "clock_basis",
        "expected_particle_ids_sha256", "particle_states_sha256",
    )
    if any(key not in receipt for key in keys):
        raise CandidateContractError("bunch source receipt lacks cohort identity")
    return {key: receipt[key] for key in keys}


def solver_problem_identity_from_trial_receipt(
    trial_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the field, geometry, voltages and numerics shared by pilot/final runs."""
    required = (
        "selected_axial_energy_per_charge_v", "mirror_voltages_v",
        "stripe_biases_v", "prism_voltages_v", "accelerator_endpoint_voltages_v",
        "accelerator_ring_voltages_v", "trajectory_profile", "inputs",
    )
    missing = [name for name in required if name not in trial_receipt]
    if missing:
        raise CandidateContractError(
            "pilot trial receipt lacks solver identity: " + ", ".join(missing)
        )
    inputs = trial_receipt.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("pilot trial receipt inputs are invalid")
    stable_inputs = {
        key: value for key, value in inputs.items()
        if key != "accelerator_pulse_schedule_sha256"
    }
    flight_scope = trial_receipt.get("flight_scope")
    if flight_scope is None:
        raise CandidateContractError(
            "pilot trial receipt does not identify the complete 3-D flight scope"
        )
    if flight_scope != "complete_three_dimensional_static_return":
        raise CandidateContractError("pilot trial receipt has a forbidden flight scope")
    projection = {
        "schema_version": 1,
        "role": "mrtof_bunch_solver_problem_identity",
        **{name: trial_receipt[name] for name in required if name != "inputs"},
        "inputs": stable_inputs,
        "flight_scope": flight_scope,
        "target_drift_period_ratio": trial_receipt.get("target_drift_period_ratio"),
        "target_half_oscillation_count": trial_receipt.get("target_half_oscillation_count"),
    }
    return {**projection, "canonical_sha256": _canonical_sha256(projection)}


def freeze_bunch_pulse_schedule_from_files(
    *,
    source_receipt_path: Path,
    pilot_log_path: Path,
    pilot_trial_receipt_path: Path,
    guard_us: float,
    output_path: Path,
) -> dict[str, Any]:
    """Freeze a detector-blind schedule from one complete frozen pilot cohort."""
    source = load_verified_bunch_source_receipt(source_receipt_path)
    trial = _load_object(pilot_trial_receipt_path, "pilot trial receipt")
    if trial.get("source_particle_count") != source["particle_count"]:
        raise CandidateContractError("pilot trial particle count differs from source cohort")
    if trial.get("source_cohort") != source_cohort_identity(source):
        raise CandidateContractError("pilot trial consumed a different source cohort")
    if str(trial.get("fly2_sha256", "")).lower() != str(source["fly2"]["sha256"]).lower():
        raise CandidateContractError("pilot trial Fly2 differs from source cohort")
    pulse = trial.get("accelerator_pulse")
    if (
        not isinstance(pulse, dict)
        or pulse.get("mode") != "static"
        or pulse.get("qualification") != "static_accelerator"
        or pulse.get("fixed_global_time_applied") is not False
    ):
        raise CandidateContractError(
            "bunch safe-exit pilot must use the static accelerator state"
        )
    trajectory = trial.get("trajectory_profile")
    if not isinstance(trajectory, dict):
        raise CandidateContractError("pilot trial has no trajectory profile")
    maximum_step_us = _finite(
        trajectory.get("maximum_step_us"), "pilot maximum trajectory step"
    )
    events = parse_events(pilot_log_path.read_text(encoding="utf-8"))
    schedule = derive_bunch_pulse_schedule(
        events=events,
        expected_particle_ids=source["expected_particle_ids"],
        guard_us=guard_us,
        pilot_maximum_step_us=maximum_step_us,
        source_cohort_identity=source_cohort_identity(source),
        solver_problem_identity=solver_problem_identity_from_trial_receipt(trial),
    )
    schedule["inputs"] = {
        "source_receipt_sha256": file_sha256(source_receipt_path).lower(),
        "pilot_log_sha256": file_sha256(pilot_log_path).lower(),
        "pilot_trial_receipt_sha256": file_sha256(pilot_trial_receipt_path).lower(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schedule, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return schedule


def derive_bunch_pulse_schedule(
    *,
    events: Iterable[Mapping[str, Any]],
    expected_particle_ids: Sequence[int],
    guard_us: float,
    pilot_maximum_step_us: float,
    source_cohort_identity: Mapping[str, Any],
    solver_problem_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive one global off time from every particle's unique safe exit."""
    expected = list(expected_particle_ids)
    if expected != list(range(1, len(expected) + 1)):
        raise CandidateContractError("expected bunch IDs must be contiguous and one-based")
    guard = _finite(guard_us, "accelerator pulse guard")
    maximum_step = _finite(pilot_maximum_step_us, "pilot maximum step")
    if maximum_step <= 0 or guard < maximum_step:
        raise CandidateContractError("accelerator pulse guard must cover at least one pilot maximum step")
    if not source_cohort_identity or not solver_problem_identity:
        raise CandidateContractError("source and solver identities are required")

    materialized = [dict(event) for event in events]
    exits = [event for event in materialized if event.get("kind") == "accelerator_safe_exit"]
    unknown = sorted({int(event.get("ion", -1)) for event in exits} - set(expected))
    if unknown:
        raise CandidateContractError(f"safe-exit events contain unknown particles: {unknown}")
    selected: list[dict[str, Any]] = []
    for particle_id in expected:
        matches = [event for event in exits if int(event.get("ion", -1)) == particle_id]
        if len(matches) != 1:
            raise CandidateContractError(
                f"particle {particle_id} must have exactly one accelerator safe exit"
            )
        event = matches[0]
        time_us = _finite(event.get("t_us"), "safe-exit time")
        if (
            int(event.get("from_instance", -1)) != 7
            or int(event.get("to_instance", 7)) == 7
            or _finite(event.get("vz_mm_us"), "safe-exit axial velocity") >= 0
        ):
            raise CandidateContractError(f"particle {particle_id} has a non-injection safe exit")
        if any(
            item.get("kind") in {"terminal", "splat"}
            and int(item.get("ion", -1)) == particle_id
            and _finite(item.get("t_us"), "pre-exit terminal time") <= time_us
            for item in materialized
        ):
            raise CandidateContractError(f"particle {particle_id} terminated before its safe exit")
        selected.append({
            "particle_id": particle_id,
            "time_us": time_us,
            "from_instance": 7,
            "to_instance": int(event["to_instance"]),
        })
    last = max(selected, key=lambda item: (item["time_us"], item["particle_id"]))
    return {
        "schema_version": 2,
        "role": "mrtof_accelerator_global_pulse_schedule",
        "status": "frozen",
        "qualification": "complete_bunch_safe_exit_schedule__numerical_convergence_pending",
        "mode": "fixed_global_time",
        "time_basis": _CLOCK_BASIS,
        "source_cohort": dict(source_cohort_identity),
        "solver_problem_identity": dict(solver_problem_identity),
        "safe_exit_definition": {
            "from_instance": 7,
            "to_instance_rule": "not_7",
            "required_project_z_direction": "negative",
            "event_count": len(selected),
            "first_safe_exit_time_us": min(item["time_us"] for item in selected),
            "last_safe_exit_time_us": last["time_us"],
            "last_safe_exit_particle_id": last["particle_id"],
        },
        "guard": {
            "value_us": guard,
            "minimum_basis": "at_least_one_frozen_pilot_maximum_step",
            "pilot_maximum_step_us": maximum_step,
        },
        "pulse_off_time_us": last["time_us"] + guard,
        "after_state": {
            "accelerator_electrode_ids": list(range(1, 10)),
            "voltage_v": 0.0,
        },
    }


def validate_fixed_global_pulse_events(
    *,
    events: Iterable[Mapping[str, Any]],
    expected_particle_ids: Sequence[int],
    pulse_off_time_us: float,
    time_tolerance_us: float,
) -> dict[str, Any]:
    """Require one common fixed-time application event for every particle."""
    expected = list(expected_particle_ids)
    if expected != list(range(1, len(expected) + 1)):
        raise CandidateContractError("expected bunch IDs must be contiguous and one-based")
    scheduled = _finite(pulse_off_time_us, "scheduled accelerator pulse time")
    tolerance = _finite(time_tolerance_us, "accelerator pulse time tolerance")
    if scheduled <= 0 or tolerance < 0:
        raise CandidateContractError("pulse time must be positive and tolerance nonnegative")
    selected = [
        dict(event) for event in events
        if event.get("kind") == "accelerator_global_pulse_applied"
    ]
    unknown = sorted({int(event.get("ion", -1)) for event in selected} - set(expected))
    if unknown:
        raise CandidateContractError(f"global pulse events contain unknown particles: {unknown}")
    actual_times: list[float] = []
    for particle_id in expected:
        matches = [event for event in selected if int(event.get("ion", -1)) == particle_id]
        if len(matches) != 1:
            raise CandidateContractError(
                f"particle {particle_id} must have exactly one fixed global pulse event"
            )
        event = matches[0]
        actual = _finite(event.get("t_us"), "actual accelerator pulse time")
        declared = _finite(event.get("scheduled_t_us"), "event scheduled pulse time")
        if event.get("trigger") != "fixed_global_time":
            raise CandidateContractError(f"particle {particle_id} has the wrong pulse trigger")
        if abs(declared - scheduled) > tolerance or abs(actual - scheduled) > tolerance:
            raise CandidateContractError(f"particle {particle_id} missed the common pulse boundary")
        if int(event.get("instance", 7)) == 7:
            raise CandidateContractError(f"particle {particle_id} remained in the accelerator at pulse-off")
        actual_times.append(actual)
    return {
        "status": "pass",
        "particle_count": len(expected),
        "event_count": len(selected),
        "scheduled_pulse_off_time_us": scheduled,
        "maximum_absolute_time_error_us": max(
            (abs(value - scheduled) for value in actual_times), default=0.0,
        ),
        "all_particles_outside_accelerator": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize-source")
    materialize.add_argument("--definition", required=True, type=Path)
    materialize.add_argument("--state-table", required=True, type=Path)
    materialize.add_argument("--fly2", required=True, type=Path)
    materialize.add_argument("--receipt", required=True, type=Path)
    materialize.add_argument("--geometry-contract", type=Path)
    freeze = subparsers.add_parser("freeze-schedule")
    freeze.add_argument("--source-receipt", required=True, type=Path)
    freeze.add_argument("--pilot-log", required=True, type=Path)
    freeze.add_argument("--pilot-trial-receipt", required=True, type=Path)
    freeze.add_argument("--guard-us", required=True, type=float)
    freeze.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.command == "materialize-source":
        result = materialize_bunch_source_from_definition(
            definition_path=arguments.definition,
            state_table_path=arguments.state_table,
            fly2_path=arguments.fly2,
            receipt_path=arguments.receipt,
            geometry_contract_path=arguments.geometry_contract,
        )
        print(
            "MRTOF_BUNCH_SOURCE_MATERIALIZE=PASS "
            f"N={result['particle_count']} SHA256={result['particle_states_sha256']}"
        )
    else:
        result = freeze_bunch_pulse_schedule_from_files(
            source_receipt_path=arguments.source_receipt,
            pilot_log_path=arguments.pilot_log,
            pilot_trial_receipt_path=arguments.pilot_trial_receipt,
            guard_us=arguments.guard_us,
            output_path=arguments.output,
        )
        print(
            "MRTOF_BUNCH_PULSE_SCHEDULE=PASS "
            f"N={result['safe_exit_definition']['event_count']} "
            f"TIME_US={result['pulse_off_time_us']:.12g}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
