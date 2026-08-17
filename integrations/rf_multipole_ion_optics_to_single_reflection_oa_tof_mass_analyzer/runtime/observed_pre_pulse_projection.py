"""Project one frozen observed pre-pulse cohort into a current source locus."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev


OBSERVED_COLUMNS = [
    "simulation_particle_id", "source_particle_id", "arm_id",
    "instrument_time_us", "mass_amu", "charge_state", "x_mm", "y_mm",
    "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "kinetic_energy_eV",
]
TARGET_COLUMNS = [
    "particle_id", "instrument_time_us", "mass_amu", "charge_state",
    "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s",
    "velocity_y_m_s", "velocity_z_m_s", "kinetic_energy_eV",
]
EXPECTED_OBSERVED_COUNT = 996
EXPECTED_MISSING_SOURCE_IDS = [10, 290, 298, 701]
EXPECTED_AUTHORITY_RUN_ID = (
    "20260811_003000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000"
)
EXPECTED_AUTHORITY_PROJECT = "rf_octupole_ion_optics"
EXPECTED_AUTHORITY_MODE = "rf_oatof_resolution_attribution_counterfactual"
EXPECTED_PREPARED_PROFILE = "pre_pulse_phase_space_attribution_v3"
ARM_FULL = "full_observed_6d"
ARM_COLLAPSED = "observed_z_vz_energy_transverse_collapsed"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path: Path, role: str) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"{role} must be a JSON object")
    return document


def _load_csv(path: Path, columns: list[str], role: str) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise ValueError(f"{role} columns differ from the frozen contract")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{role} is empty")
    return rows


def _finite(row: dict[str, str], field: str, role: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{role} requires numeric field {field}") from error
    if not math.isfinite(value):
        raise ValueError(f"{role} field {field} must be finite")
    return value


def _reference(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _validate_authority(
    manifest_path: Path,
    prepared_path: Path,
    state_path: Path,
    geometry_path: Path,
) -> tuple[list[dict[str, str]], list[float], float]:
    manifest = _load_json(manifest_path, "authority manifest")
    expected_manifest = {
        "role": "simulation_run_manifest",
        "run_id": EXPECTED_AUTHORITY_RUN_ID,
        "project": EXPECTED_AUTHORITY_PROJECT,
        "mode": EXPECTED_AUTHORITY_MODE,
        "status": "success",
    }
    if any(manifest.get(key) != value for key, value in expected_manifest.items()):
        raise ValueError("observed authority manifest identity differs")
    prepared = _load_json(prepared_path, "prepared-arm receipt")
    if (
        prepared.get("role") != "rf_oatof_resolution_attribution_prepared_arms"
        or prepared.get("profile_id") != EXPECTED_PREPARED_PROFILE
    ):
        raise ValueError("prepared-arm receipt identity differs")
    state_sha = _sha256(state_path)
    arms = prepared.get("arms")
    if not isinstance(arms, list):
        raise ValueError("prepared-arm receipt lacks arms")
    matches = [arm for arm in arms if arm.get("arm_id") == "observed_restart_control"]
    if len(matches) != 1 or matches[0].get("state_sha256") != state_sha:
        raise ValueError("prepared-arm receipt does not bind observed state")
    if matches[0].get("particles") != EXPECTED_OBSERVED_COUNT:
        raise ValueError("prepared-arm observed population differs")

    rows = _load_csv(state_path, OBSERVED_COLUMNS, "observed state")
    source_ids = [int(_finite(row, "source_particle_id", "observed state")) for row in rows]
    if len(rows) != EXPECTED_OBSERVED_COUNT or len(set(source_ids)) != len(source_ids):
        raise ValueError("observed state population or IDs differ")
    missing = sorted(set(range(1, 1001)) - set(source_ids))
    if missing != EXPECTED_MISSING_SOURCE_IDS:
        raise ValueError("observed state missing-ID census differs")
    for row in rows:
        values = [_finite(row, field, "observed state") for field in (
            "instrument_time_us", "mass_amu", "x_mm", "y_mm", "z_mm",
            "vx_m_s", "vy_m_s", "vz_m_s", "kinetic_energy_eV",
        )]
        expected_energy = kinetic_energy_ev(values[1], values[5], values[6], values[7])
        if not math.isclose(expected_energy, values[8], rel_tol=1e-11, abs_tol=1e-10):
            raise ValueError("observed state velocity and energy differ")

    geometry = _load_json(geometry_path, "old geometry")
    source = geometry.get("particle_source")
    if not isinstance(source, dict):
        raise ValueError("old geometry lacks particle_source")
    old_center = [float(source[f"center_{axis}_mm"]) for axis in "xyz"]
    if not all(math.isfinite(value) for value in old_center):
        raise ValueError("old source center must be finite")
    pulse_time = float(prepared.get("pulse_time_us", math.nan))
    if not math.isfinite(pulse_time):
        raise ValueError("prepared-arm pulse time must be finite")
    return rows, old_center, pulse_time


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TARGET_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def project_observed_pre_pulse_states(
    *,
    authority_manifest_path: Path,
    prepared_arms_path: Path,
    observed_state_path: Path,
    old_geometry_path: Path,
    current_target_path: Path,
    current_subset_receipt_path: Path,
    full_output_path: Path,
    collapsed_output_path: Path,
    receipt_output_path: Path,
) -> dict[str, Any]:
    """Write paired full-observed and transverse-collapsed current-epoch states."""
    observed, old_center, old_clock = _validate_authority(
        authority_manifest_path, prepared_arms_path, observed_state_path,
        old_geometry_path,
    )
    target = _load_csv(current_target_path, TARGET_COLUMNS, "current target")
    subset = _load_json(current_subset_receipt_path, "current subset receipt")
    target_record = subset.get("pulse_target_state", {})
    if target_record.get("sha256") != _sha256(current_target_path):
        raise ValueError("current subset receipt does not bind target state")
    mapping = subset.get("selection", {}).get("simulation_to_source_particle_id")
    if not isinstance(mapping, list) or len(mapping) != len(target):
        raise ValueError("current subset particle mapping differs")
    current_center = [float(value) for value in subset["resolved_target_center_mm"]]
    current_clock = float(subset["resolved_pulse_time_us"])
    if not all(math.isfinite(value) for value in current_center + [current_clock]):
        raise ValueError("current center and clock must be finite")
    observed_by_source = {int(row["source_particle_id"]): row for row in observed}
    translation = [new - old for new, old in zip(current_center, old_center)]

    full_rows: list[dict[str, object]] = []
    collapsed_rows: list[dict[str, object]] = []
    id_map: list[dict[str, int]] = []
    for index, (target_row, identity) in enumerate(zip(target, mapping), start=1):
        simulation_id = int(identity["simulation_particle_id"])
        source_id = int(identity["source_particle_id"])
        if simulation_id != index or int(target_row["particle_id"]) != index:
            raise ValueError("current target and mapping IDs are not ordered")
        if source_id not in observed_by_source:
            raise ValueError("current target ID is absent from observed authority")
        source_row = observed_by_source[source_id]
        mass = _finite(source_row, "mass_amu", "observed state")
        charge = int(_finite(source_row, "charge_state", "observed state"))
        position = [
            _finite(source_row, f"{axis}_mm", "observed state") + translation[i]
            for i, axis in enumerate("xyz")
        ]
        velocity = [
            _finite(source_row, f"v{axis}_m_s", "observed state") for axis in "xyz"
        ]
        energy = kinetic_energy_ev(mass, *velocity)
        base = {
            "particle_id": simulation_id,
            "instrument_time_us": format(current_clock, ".17g"),
            "mass_amu": format(mass, ".17g"),
            "charge_state": charge,
        }
        full = dict(base)
        full.update({f"position_{axis}_mm": format(value, ".17g") for axis, value in zip("xyz", position)})
        full.update({f"velocity_{axis}_m_s": format(value, ".17g") for axis, value in zip("xyz", velocity)})
        full["kinetic_energy_eV"] = format(energy, ".17g")
        collapsed = dict(full)
        collapsed["position_x_mm"] = format(current_center[0], ".17g")
        collapsed["position_y_mm"] = format(current_center[1], ".17g")
        collapsed["velocity_x_m_s"] = format(math.hypot(velocity[0], velocity[1]), ".17g")
        collapsed["velocity_y_m_s"] = "0"
        full_rows.append(full)
        collapsed_rows.append(collapsed)
        id_map.append({"simulation_particle_id": simulation_id, "source_particle_id": source_id})

    _write_rows(full_output_path, full_rows)
    _write_rows(collapsed_output_path, collapsed_rows)
    for full, collapsed in zip(full_rows, collapsed_rows):
        if any(full[field] != collapsed[field] for field in (
            "particle_id", "instrument_time_us", "mass_amu", "charge_state",
            "position_z_mm", "velocity_z_m_s", "kinetic_energy_eV",
        )):
            raise ValueError("collapsed-arm paired invariants differ")
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_observed_pre_pulse_projection_receipt",
        "status": "PASS",
        "authorities": {
            "manifest": _reference(authority_manifest_path),
            "prepared_arms": _reference(prepared_arms_path),
            "observed_state": _reference(observed_state_path),
            "old_geometry": _reference(old_geometry_path),
            "current_target": _reference(current_target_path),
            "current_subset_receipt": _reference(current_subset_receipt_path),
        },
        "observed_population": {
            "particle_count": len(observed),
            "missing_source_particle_ids": EXPECTED_MISSING_SOURCE_IDS,
        },
        "projection": {
            "method": "common_center_translation_and_current_epoch_transplant_v1",
            "old_center_mm": old_center,
            "current_center_mm": current_center,
            "translation_mm": translation,
            "old_instrument_time_us": old_clock,
            "current_instrument_time_us": current_clock,
            "simulation_to_source_particle_id": id_map,
        },
        "arms": {
            ARM_FULL: _reference(full_output_path),
            ARM_COLLAPSED: _reference(collapsed_output_path),
        },
        "invariants": {
            "full_observed_velocity_preserved": True,
            "full_observed_position_common_translation": True,
            "collapsed_z_vz_energy_clock_equal_full": True,
            "collapsed_x_y_equal_current_center": True,
            "collapsed_vy_zero": True,
            "collapsed_positive_vx_preserves_transverse_speed": True,
            "energy_recomputed_from_velocity": True,
        },
    }
    receipt_output_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_output_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
