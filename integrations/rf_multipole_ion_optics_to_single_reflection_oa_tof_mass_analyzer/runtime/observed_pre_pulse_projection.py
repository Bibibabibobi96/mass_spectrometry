"""Project one frozen observed pre-pulse cohort into a current source locus."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256 as _sha256
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
ARM_FULL = "full_observed_6d"
ARM_COLLAPSED = "observed_z_vz_energy_transverse_collapsed"
ARM_AFFINE_FIXED_10EV = "affine_zvz_fixed_10eV_transverse_collapsed"
ARM_OBSERVED_FIXED_10EV = "observed_zvz_fixed_10eV_transverse_collapsed"
ZVZ_AFFINE_RESIDUAL_REMOVED = "zvz_affine_residual_removed"


def remove_zvz_affine_residual(
    rows: list[dict[str, str | int]],
) -> dict[str, float | str]:
    """Replace each row's vz by its cohort OLS prediction and recompute KE."""
    if not rows:
        raise ValueError("diagnostic state transform requires a nonempty cohort")
    z_values = [_finite(row, "position_z_mm", "diagnostic restart state") for row in rows]
    vz_values = [_finite(row, "velocity_z_m_s", "diagnostic restart state") for row in rows]
    mean_z = sum(z_values) / len(z_values)
    mean_vz = sum(vz_values) / len(vz_values)
    denominator = sum((value - mean_z) ** 2 for value in z_values)
    if not math.isfinite(denominator) or denominator <= 0:
        raise ValueError("diagnostic z-vz affine fit is degenerate")
    slope = sum(
        (z - mean_z) * (vz - mean_vz)
        for z, vz in zip(z_values, vz_values, strict=True)
    ) / denominator
    intercept = mean_vz - slope * mean_z
    if not all(math.isfinite(value) for value in (intercept, slope)):
        raise ValueError("diagnostic z-vz affine fit is non-finite")
    residuals: list[float] = []
    for row, z, observed_vz in zip(rows, z_values, vz_values, strict=True):
        predicted_vz = intercept + slope * z
        residuals.append(observed_vz - predicted_vz)
        row["velocity_z_m_s"] = format(predicted_vz, ".17g")
        row["kinetic_energy_eV"] = format(
            kinetic_energy_ev(
                _finite(row, "mass_amu", "diagnostic restart state"),
                _finite(row, "velocity_x_m_s", "diagnostic restart state"),
                _finite(row, "velocity_y_m_s", "diagnostic restart state"),
                predicted_vz,
            ),
            ".17g",
        )
    return {
        "state_transform": ZVZ_AFFINE_RESIDUAL_REMOVED,
        "ols_intercept_vz_m_per_s": intercept,
        "ols_slope_vz_m_per_s_per_mm": slope,
        "mean_z_mm": mean_z,
        "mean_vz_m_per_s": mean_vz,
        "residual_rms_m_per_s": math.sqrt(
            sum(value ** 2 for value in residuals) / len(residuals)
        ),
        "residual_max_abs_m_per_s": max(abs(value) for value in residuals),
    }


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
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
    ):
        raise ValueError("observed authority manifest is not a successful simulation run")
    prepared = _load_json(prepared_path, "prepared-arm receipt")
    if prepared.get("role") != "rf_oatof_resolution_attribution_prepared_arms":
        raise ValueError("prepared-arm receipt role differs")
    state_sha = _sha256(state_path)
    arms = prepared.get("arms")
    if not isinstance(arms, list):
        raise ValueError("prepared-arm receipt lacks arms")
    matches = [arm for arm in arms if arm.get("state_sha256") == state_sha]
    if len(matches) != 1:
        raise ValueError("prepared-arm receipt does not bind observed state")

    rows = _load_csv(state_path, OBSERVED_COLUMNS, "observed state")
    source_ids: list[int] = []
    for row in rows:
        source_id_value = _finite(row, "source_particle_id", "observed state")
        if source_id_value < 1 or not source_id_value.is_integer():
            raise ValueError("observed state source particle IDs must be positive integers")
        source_ids.append(int(source_id_value))
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("observed state source particle IDs are not unique")
    if matches[0].get("particles") != len(rows):
        raise ValueError("prepared-arm observed population differs")
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
    affine_fixed_10ev_output_path: Path | None = None,
    observed_fixed_10ev_output_path: Path | None = None,
    affine_mean_velocity_z_m_per_s: float | None = None,
    affine_velocity_z_slope_m_per_s_per_mm: float | None = None,
    affine_center_z_mm: float | None = None,
    fixed_kinetic_energy_eV: float | None = None,
) -> dict[str, Any]:
    """Write the v1 C/D pair or the v2 observed-z four-arm decomposition."""
    four_arm_values = (
        affine_fixed_10ev_output_path,
        observed_fixed_10ev_output_path,
        affine_mean_velocity_z_m_per_s,
        affine_velocity_z_slope_m_per_s_per_mm,
        affine_center_z_mm,
        fixed_kinetic_energy_eV,
    )
    four_arm = any(value is not None for value in four_arm_values)
    if four_arm and any(value is None for value in four_arm_values):
        raise ValueError("four-arm projection requires both outputs and frozen affine authority")
    if four_arm and (
        not math.isfinite(float(fixed_kinetic_energy_eV))
        or fixed_kinetic_energy_eV <= 0
    ):
        raise ValueError("four-arm projection requires a finite positive fixed kinetic energy")
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
    affine_rows: list[dict[str, object]] = []
    observed_fixed_rows: list[dict[str, object]] = []
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
        if four_arm:
            fixed_energy_speed = math.sqrt(
                float(fixed_kinetic_energy_eV)
                / kinetic_energy_ev(mass, 1.0, 0.0, 0.0)
            )
            observed_vz = velocity[2]
            affine_vz = float(affine_mean_velocity_z_m_per_s) + float(
                affine_velocity_z_slope_m_per_s_per_mm
            ) * (position[2] - float(affine_center_z_mm))

            def fixed_energy_row(vz: float, arm: str) -> dict[str, object]:
                transverse_squared = fixed_energy_speed**2 - vz**2
                if transverse_squared <= 0:
                    raise ValueError(
                        f"{arm} axial kinetic energy exceeds fixed energy"
                    )
                row = dict(base)
                row.update({
                    "position_x_mm": format(current_center[0], ".17g"),
                    "position_y_mm": format(current_center[1], ".17g"),
                    "position_z_mm": format(position[2], ".17g"),
                    "velocity_x_m_s": format(math.sqrt(max(0.0, transverse_squared)), ".17g"),
                    "velocity_y_m_s": "0",
                    "velocity_z_m_s": format(vz, ".17g"),
                })
                recomputed_energy = kinetic_energy_ev(
                    mass,
                    float(row["velocity_x_m_s"]),
                    0.0,
                    float(row["velocity_z_m_s"]),
                )
                if not math.isclose(
                    recomputed_energy, float(fixed_kinetic_energy_eV),
                    rel_tol=1e-14, abs_tol=1e-12,
                ):
                    raise ValueError(f"{arm} velocity rounding violates fixed energy")
                row["kinetic_energy_eV"] = format(float(fixed_kinetic_energy_eV), ".17g")
                return row

            affine_rows.append(fixed_energy_row(affine_vz, ARM_AFFINE_FIXED_10EV))
            observed_fixed_rows.append(
                fixed_energy_row(observed_vz, ARM_OBSERVED_FIXED_10EV)
            )
        id_map.append({"simulation_particle_id": simulation_id, "source_particle_id": source_id})

    _write_rows(full_output_path, full_rows)
    _write_rows(collapsed_output_path, collapsed_rows)
    if four_arm:
        _write_rows(Path(affine_fixed_10ev_output_path), affine_rows)
        _write_rows(Path(observed_fixed_10ev_output_path), observed_fixed_rows)
    for full, collapsed in zip(full_rows, collapsed_rows):
        if any(full[field] != collapsed[field] for field in (
            "particle_id", "instrument_time_us", "mass_amu", "charge_state",
            "position_z_mm", "velocity_z_m_s", "kinetic_energy_eV",
        )):
            raise ValueError("collapsed-arm paired invariants differ")
    arms = {
        ARM_FULL: _reference(full_output_path),
        ARM_COLLAPSED: _reference(collapsed_output_path),
    }
    invariants = {
        "full_observed_velocity_preserved": True,
        "full_observed_position_common_translation": True,
        "collapsed_z_vz_energy_clock_equal_full": True,
        "collapsed_x_y_equal_current_center": True,
        "collapsed_vy_zero": True,
        "collapsed_positive_vx_preserves_transverse_speed": True,
        "energy_recomputed_from_velocity": True,
    }
    projection = {
        "method": (
            "observed_z_four_arm_energy_decomposition_v2"
            if four_arm
            else "common_center_translation_and_current_epoch_transplant_v1"
        ),
        "old_center_mm": old_center,
        "current_center_mm": current_center,
        "translation_mm": translation,
        "old_instrument_time_us": old_clock,
        "current_instrument_time_us": current_clock,
        "simulation_to_source_particle_id": id_map,
    }
    if four_arm:
        arms.update({
            ARM_AFFINE_FIXED_10EV: _reference(Path(affine_fixed_10ev_output_path)),
            ARM_OBSERVED_FIXED_10EV: _reference(Path(observed_fixed_10ev_output_path)),
        })
        projection.update({
            "fixed_kinetic_energy_eV": float(fixed_kinetic_energy_eV),
            "affine_authority": {
                "mean_velocity_z_m_per_s": affine_mean_velocity_z_m_per_s,
                "velocity_z_slope_m_per_s_per_mm": affine_velocity_z_slope_m_per_s_per_mm,
                "center_z_mm": affine_center_z_mm,
            },
        })
        invariants.update({
            "all_arms_observed_z_id_clock_equal": True,
            "affine_arm_vz_from_frozen_authority": True,
            "observed_fixed_arm_observed_vz_preserved": True,
            "fixed_10eV_arms_energy_equal": True,
            "fixed_10eV_arms_centered_xy_vy_zero_positive_vx": True,
        })
    receipt = {
        "schema_version": 2 if four_arm else 1,
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
        },
        "projection": projection,
        "arms": arms,
        "invariants": invariants,
    }
    receipt_output_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_output_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
