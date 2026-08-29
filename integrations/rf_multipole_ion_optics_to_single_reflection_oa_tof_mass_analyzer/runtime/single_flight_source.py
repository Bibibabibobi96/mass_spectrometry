"""Map a multipole mother sample into the continuous oaTOF SIMION workbench."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path

from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C,
    kinetic_energy_ev,
)
from common.multipole.sources.continuous_axial_volume_source import (
    METHOD as ION_SOURCE_VOLUME_METHOD,
    materialize as materialize_ion_source_volume,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.rf_handoff_adapter import (
    encode_simion_accelerator_velocity,
)


SOURCE_COLUMNS = [
    "particle_id",
    "birth_time_s",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "mass_amu",
    "charge_state",
]
GLOBAL_COLUMNS = [
    "particle_id",
    "instrument_time_us",
    "mass_amu",
    "charge_state",
    "position_x_mm",
    "position_y_mm",
    "position_z_mm",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "velocity_z_m_s",
    "kinetic_energy_eV",
]
ATTRIBUTION_COLUMNS = [
    "simulation_particle_id", "source_particle_id", "arm_id",
    "instrument_time_us", "mass_amu", "charge_state", "x_mm", "y_mm",
    "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "kinetic_energy_eV",
]
ROW_MAP_COLUMNS = ["simulation_particle_id", "source_particle_id"]
UPSTREAM_TERMINAL_COLUMNS = [
    "particle_id", "event", "status", "terminal_reason", "time_us",
    "elapsed_time_us", "rf_phase_rad", "axial_z_mm", "transverse_x_mm",
    "transverse_y_mm", "velocity_axial_m_s", "velocity_x_m_s",
    "velocity_y_m_s", "kinetic_energy_eV", "radial_position_mm",
    "divergence_angle_deg", "max_rod_radius_mm",
]

def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _ordered_id_sha256(count: int) -> str:
    payload = json.dumps(
        list(range(1, count + 1)), separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def resolve_source_materialization_profile(
    profile: dict[str, object], integration_root: Path,
) -> dict[str, object]:
    """Resolve affine z-vz values from their single frozen machine authority."""
    resolved = copy.deepcopy(profile)
    authority = resolved.get("phase_space_authority")
    if not isinstance(authority, str) or not authority.startswith("config/"):
        return resolved
    if {
        "mean_velocity_z_m_per_s",
        "velocity_z_slope_m_per_s_per_mm",
    } & resolved.keys():
        raise ValueError(
            "authority-backed source profile must not duplicate affine z-vz values"
        )
    authority_path = (integration_root / authority).resolve()
    try:
        authority_path.relative_to(integration_root.resolve())
    except ValueError as exc:
        raise ValueError("source phase-space authority escapes integration") from exc
    authority_document = json.loads(authority_path.read_text(encoding="utf-8-sig"))
    frozen = authority_document.get("frozen_phase_space_input")
    if not isinstance(frozen, dict):
        raise ValueError("source phase-space authority lacks frozen input")
    resolved["mean_velocity_z_m_per_s"] = float(
        frozen["mean_initial_velocity_m_per_s"]
    )
    resolved["velocity_z_slope_m_per_s_per_mm"] = float(
        frozen["velocity_slope_m_per_s_per_mm"]
    )
    return resolved


def materialize_independent_ion_source_volume(
    output_path: Path,
    receipt_path: Path,
    profile: dict[str, object],
    integration_root: Path,
) -> dict[str, object]:
    """Materialize a frozen ion-source volume without inventing z--vz coupling."""
    source_spec = profile.get("source_spec")
    if not isinstance(source_spec, str) or not source_spec.startswith("config/"):
        raise ValueError("ion-source volume profile lacks a local source specification")
    spec_path = (integration_root / source_spec).resolve()
    try:
        spec_path.relative_to(integration_root.resolve())
    except ValueError as exc:
        raise ValueError("ion-source volume specification escapes integration") from exc
    receipt = materialize_ion_source_volume(spec_path, output_path, receipt_path)
    if int(receipt["particle_count"]) != int(profile["particle_count"]):
        raise ValueError("ion-source volume profile and source specification counts differ")
    if receipt.get("method") != ION_SOURCE_VOLUME_METHOD:
        raise ValueError("ion-source volume materialization method differs")
    receipt.update({
        "profile_id": profile["profile_id"],
        "source_profile_id": profile["source_profile_id"],
        "materialization_mode": "independent_spatial_velocity_ion_source_snapshot",
        "source_spec": source_spec,
        "coordinate_transform": "canonical_multipole_to_oatof_registration_applied_by_single_flight_source",
    })
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def materialize_ideal_linear_source(
    output_path: Path,
    receipt_path: Path,
    connection: dict[str, object],
    geometry: dict[str, object],
    pulse_schedule: dict[str, object],
    profile: dict[str, object],
    pulse_target_output_path: Path | None = None,
) -> dict[str, object]:
    """Build a deterministic ideal z-vz source from resolved runtime authorities."""
    registration = connection["spatial_registration"]
    rotation = registration["rotation_upstream_to_downstream"]
    if rotation != [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]:
        raise ValueError("ideal source requires the canonical multipole-to-oaTOF rotation")
    tx, ty, tz = map(float, registration["translation_mm"])
    count = int(profile["particle_count"])
    width = float(profile["source_full_width_mm"])
    mass = float(profile["mass_amu"])
    charge = int(profile["charge_state"])
    energy = float(profile["kinetic_energy_eV"])
    mean_vz = float(profile["mean_velocity_z_m_per_s"])
    slope = float(profile["velocity_z_slope_m_per_s_per_mm"])
    if count < 1 or width <= 0 or mass <= 0 or charge <= 0 or energy <= 0:
        raise ValueError("ideal source profile has invalid population or physics")
    particle_source = geometry["particle_source"]
    target_x = float(particle_source["center_x_mm"])
    target_y = float(particle_source["center_y_mm"])
    target_z = float(particle_source["center_z_mm"])
    entry_x = float(pulse_schedule["entry_surface_x_mm"])
    pulse_time_us = float(pulse_schedule["pulse_effective_time_us"])
    speed = math.sqrt(
        2.0 * energy * ELEMENTARY_CHARGE_C / (mass * AMU_KG)
    )
    rows: list[dict[str, object]] = []
    pulse_target_rows: list[dict[str, object]] = []
    for index in range(count):
        desired_z = (
            target_z
            if count == 1
            else target_z - width / 2.0 + width * index / (count - 1)
        )
        global_vz = mean_vz + slope * (desired_z - target_z)
        if abs(global_vz) >= speed:
            raise ValueError("ideal source prescribed z velocity exceeds total speed")
        global_vx = math.sqrt(speed * speed - global_vz * global_vz)
        flight_us = 1000.0 * (target_x - entry_x) / global_vx
        entry_z = desired_z - global_vz * flight_us / 1000.0
        rows.append({
            "particle_id": index + 1,
            "birth_time_s": (pulse_time_us - flight_us) / 1e6,
            "x_mm": target_y - ty,
            "y_mm": entry_z - tz,
            "z_mm": entry_x - tx,
            "vx_m_s": 0.0,
            "vy_m_s": global_vz,
            "vz_m_s": global_vx,
            "mass_amu": mass,
            "charge_state": charge,
        })
        pulse_target_rows.append({
            "particle_id": index + 1,
            "instrument_time_us": format(pulse_time_us, ".17g"),
            "mass_amu": format(mass, ".17g"),
            "charge_state": charge,
            "position_x_mm": format(target_x, ".17g"),
            "position_y_mm": format(target_y, ".17g"),
            "position_z_mm": format(desired_z, ".17g"),
            "velocity_x_m_s": format(global_vx, ".17g"),
            "velocity_y_m_s": "0",
            "velocity_z_m_s": format(global_vz, ".17g"),
            "kinetic_energy_eV": format(energy, ".17g"),
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    pulse_target_record = None
    if pulse_target_output_path is not None:
        pulse_target_output_path.parent.mkdir(parents=True, exist_ok=True)
        with pulse_target_output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(pulse_target_rows)
        pulse_target_record = {
            "path": pulse_target_output_path.name,
            "sha256": _file_sha256(pulse_target_output_path),
            "particle_count": count,
            "source_state_epoch": "pulse_effective_time",
            "source_state_locus": {
                "kind": "accelerator_stage1_interior_fixed_transverse_finite_local_z_interval",
                "resolved_target_center_mm": [target_x, target_y, target_z],
                "z_local_interval_mm": [target_z - width / 2.0, target_z + width / 2.0],
            },
            "coordinate_frame": "oatof_global_cartesian",
            "clock_basis": "canonical_instrument_time_us",
            "clock_authority": "resolved_single_flight_pulse_schedule",
            "ordered_particle_id_sha256": _ordered_id_sha256(count),
        }
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_source_materialization_receipt",
        "profile_id": profile["profile_id"],
        "source_profile_id": profile["source_profile_id"],
        "method": "resolved_layout_pulse_contract_ideal_linear_z_vz_v1",
        "particle_count": count,
        "source_full_width_mm": width,
        "resolved_target_center_mm": [target_x, target_y, target_z],
        "resolved_entry_surface_x_mm": entry_x,
        "resolved_pulse_time_us": pulse_time_us,
        "coordinate_transform": {
            "rotation_upstream_to_downstream": rotation,
            "translation_mm": [tx, ty, tz],
        },
        "physics": {
            "mass_amu": mass,
            "charge_state": charge,
            "kinetic_energy_eV": energy,
            "mean_velocity_z_m_per_s": mean_vz,
            "velocity_z_slope_m_per_s_per_mm": slope,
        },
        "particle_source": {
            "path": output_path.name,
            "sha256": _file_sha256(output_path),
            "particle_count": count,
            "sampling_mode": "continuous_injection_full_population",
        },
        "pulse_target_state": pulse_target_record,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def render_restart_fly2(rows: list[dict[str, str]]) -> str:
    """Render official individual-particle FLY2 direct-velocity definitions."""
    lines = ["particles {", "  coordinates = 0,"]
    for row in rows:
        position = ", ".join(row[f"position_{axis}_mm"] for axis in "xyz")
        velocity = ", ".join(
            format(float(row[f"velocity_{axis}_m_s"]) / 1000.0, ".17g")
            for axis in "xyz"
        )
        lines.append(
            "  standard_beam { tob = 0, mass = "
            + row["mass_amu"] + ", charge = " + row["charge_state"]
            + ", cwf = 1, color = 0, position = vector(" + position
            + "), velocity = vector(" + velocity + ") },"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_pre_pulse_fly2(rows: list[dict[str, str]]) -> str:
    """Retain the established pre-pulse API over the generic official renderer."""
    return render_restart_fly2(rows)


def materialize_pre_pulse_restart(
    source_path: Path, pulse_time_us: float,
) -> tuple[str, list[dict[str, str]]]:
    """Materialize an oaTOF-global pre-pulse state without upstream remapping."""
    if pulse_time_us < 0:
        raise ValueError("pre-pulse restart clock is invalid")
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames not in (GLOBAL_COLUMNS, ATTRIBUTION_COLUMNS):
            raise ValueError("pre-pulse source-state columns differ from the global contract")
        rows = list(reader)
    attribution = reader.fieldnames == ATTRIBUTION_COLUMNS
    id_key = "simulation_particle_id" if attribution else "particle_id"
    if not rows or [int(row[id_key]) for row in rows] != list(
        range(1, len(rows) + 1)
    ):
        raise ValueError("pre-pulse source-state IDs must be contiguous and ordered")
    global_rows: list[dict[str, str]] = []
    for row in rows:
        if abs(float(row["instrument_time_us"]) - pulse_time_us) > 1e-9:
            raise ValueError("pre-pulse source-state clock differs from the pulse time")
        velocity = tuple(float(row[f"v{axis}_m_s"] if attribution else row[f"velocity_{axis}_m_s"]) for axis in "xyz")
        mass = float(row["mass_amu"])
        energy = kinetic_energy_ev(mass, *velocity)
        if abs(energy - float(row["kinetic_energy_eV"])) > 1e-9:
            raise ValueError("pre-pulse source-state kinetic energy differs")
        global_row = {
            "particle_id": str(int(row[id_key])),
            "instrument_time_us": format(pulse_time_us, ".17g"),
            "mass_amu": format(mass, ".17g"),
            "charge_state": str(int(row["charge_state"])),
            **{f"position_{axis}_mm": format(float(row[f"{axis}_mm"] if attribution else row[f"position_{axis}_mm"]), ".17g") for axis in "xyz"},
            **{f"velocity_{axis}_m_s": format(value, ".17g") for axis, value in zip("xyz", velocity)},
            "kinetic_energy_eV": format(energy, ".17g"),
        }
        global_rows.append(global_row)
    return render_pre_pulse_fly2(global_rows), global_rows


def materialize_terminal_handoff_continuation(
    source_path: Path,
    connection: dict[str, object],
    *,
    mass_amu: float,
    charge_state: int,
    smoke_source_particle_id: int | None = None,
    execution_particle_count: int | None = None,
) -> tuple[list[list[str]], list[dict[str, str]], list[dict[str, str]], dict[str, object]]:
    """Continue only manifest-recorded terminal handoffs into the OA frame.

    This is not a pre-pulse restart: each successful upstream handoff retains
    its own absolute instrument time and starts the downstream continuous-field
    trajectory there.  Upstream losses remain in the returned mother-cohort
    census and never become simulated particles.
    """
    if not math.isfinite(mass_amu) or mass_amu <= 0 or charge_state <= 0:
        raise ValueError("terminal-handoff mass or charge is invalid")
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != UPSTREAM_TERMINAL_COLUMNS:
            raise ValueError("terminal-handoff source columns differ from the governed upstream contract")
        all_rows = list(reader)
    handoff_by_id: dict[int, dict[str, str]] = {}
    terminal_by_id: dict[int, dict[str, str]] = {}
    for row in all_rows:
        if row["event"] not in {"handoff", "terminal"}:
            continue
        particle_id = int(row["particle_id"])
        target = handoff_by_id if row["event"] == "handoff" else terminal_by_id
        if particle_id in target:
            raise ValueError("terminal-handoff source has duplicate rows for one event")
        target[particle_id] = row
    # A successful handoff may later receive a terminal diagnostic at the
    # acceptance surface.  The handoff, not that downstream diagnostic, is
    # the physical state to continue into the OA coordinate frame.
    final_by_id = {
        particle_id: (
            handoff_by_id[particle_id]
            if particle_id in handoff_by_id else terminal_by_id[particle_id]
        )
        for particle_id in set(handoff_by_id) | set(terminal_by_id)
    }
    if not final_by_id or sorted(final_by_id) != list(range(1, len(final_by_id) + 1)):
        raise ValueError("terminal-handoff source lacks one final row per contiguous mother particle ID")
    registration = connection["spatial_registration"]
    if registration["rotation_upstream_to_downstream"] != [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]:
        raise ValueError("terminal-handoff continuation requires the canonical multipole-to-oaTOF rotation")
    tx, ty, tz = map(float, registration["translation_mm"])
    ion_rows: list[list[str]] = []
    global_rows: list[dict[str, str]] = []
    row_map: list[dict[str, str]] = []
    loss_ids: list[int] = [
        particle_id for particle_id, item in final_by_id.items()
        if not (item["event"] == "handoff" and item["status"] == "transmitted"
                and item["terminal_reason"] == "none")
    ]
    if smoke_source_particle_id is not None and execution_particle_count is not None:
        raise ValueError("terminal-handoff selection modes cannot be combined")
    transmitted_ids = [
        particle_id for particle_id in sorted(final_by_id)
        if final_by_id[particle_id]["event"] == "handoff"
        and final_by_id[particle_id]["status"] == "transmitted"
        and final_by_id[particle_id]["terminal_reason"] == "none"
    ]
    if smoke_source_particle_id is not None:
        if isinstance(smoke_source_particle_id, bool) or smoke_source_particle_id < 1:
            raise ValueError("terminal-handoff smoke source particle ID is invalid")
        selected_ids = [smoke_source_particle_id]
    elif execution_particle_count is not None:
        if (
            isinstance(execution_particle_count, bool)
            or execution_particle_count < 1
            or execution_particle_count > len(transmitted_ids)
        ):
            raise ValueError("terminal-handoff execution particle count is invalid")
        selected_ids = transmitted_ids[:execution_particle_count]
    else:
        selected_ids = sorted(final_by_id)
    for particle_id in selected_ids:
        if particle_id not in final_by_id:
            raise ValueError("terminal-handoff smoke source particle is absent")
        row = final_by_id[particle_id]
        transmitted = row["event"] == "handoff" and row["status"] == "transmitted" and row["terminal_reason"] == "none"
        if not transmitted:
            if smoke_source_particle_id is not None:
                raise ValueError("terminal-handoff smoke source particle is not transmitted")
            continue
        local_position = (float(row["transverse_x_mm"]), float(row["transverse_y_mm"]), float(row["axial_z_mm"]))
        local_velocity = (float(row["velocity_x_m_s"]), float(row["velocity_y_m_s"]), float(row["velocity_axial_m_s"]))
        x, y, z = local_position[2] + tx, local_position[0] + ty, local_position[1] + tz
        vx, vy, vz = local_velocity[2], local_velocity[0], local_velocity[1]
        time_us = float(row["time_us"])
        if not math.isfinite(time_us) or time_us < 0:
            raise ValueError("terminal-handoff source clock is invalid")
        energy = kinetic_energy_ev(mass_amu, vx, vy, vz)
        azimuth, elevation = encode_simion_accelerator_velocity((vx, vy, vz))
        ion_rows.append(["0", format(mass_amu, ".17g"), str(charge_state), format(x, ".17g"), format(y, ".17g"), format(z, ".17g"), format(azimuth, ".17g"), format(elevation, ".17g"), format(energy, ".17g"), "1", "3"])
        simulation_particle_id = (
            len(global_rows) + 1 if smoke_source_particle_id is not None else particle_id
        )
        global_rows.append({
            "particle_id": str(simulation_particle_id), "instrument_time_us": format(time_us, ".17g"),
            "mass_amu": format(mass_amu, ".17g"), "charge_state": str(charge_state),
            "position_x_mm": format(x, ".17g"), "position_y_mm": format(y, ".17g"), "position_z_mm": format(z, ".17g"),
            "velocity_x_m_s": format(vx, ".17g"), "velocity_y_m_s": format(vy, ".17g"), "velocity_z_m_s": format(vz, ".17g"),
            "kinetic_energy_eV": format(energy, ".17g"),
        })
        row_map.append({
            "simulation_particle_id": str(len(row_map) + 1),
            "source_particle_id": str(particle_id),
        })
    if not global_rows:
        raise ValueError("terminal-handoff source has no transmitted particles")
    receipt = {
        "role": "rf_oatof_terminal_handoff_continuation_receipt", "schema_version": 1,
        "source_event": "handoff", "source_status": "transmitted",
        "source_release_mode": "continuous_frontend_handoff",
        "coordinate_frame": "oatof_global_cartesian", "clock_basis": "canonical_instrument_time_us",
        "mother_particle_count": len(final_by_id), "continued_particle_count": len(global_rows),
        "upstream_loss_count": len(loss_ids), "upstream_loss_particle_ids": loss_ids,
        "continued_particle_ids": [int(row["source_particle_id"]) for row in row_map],
        "smoke_source_particle_id": smoke_source_particle_id,
        "execution_particle_count": execution_particle_count,
        "transform": {"rotation_upstream_to_downstream": registration["rotation_upstream_to_downstream"], "translation_mm": [tx, ty, tz]},
    }
    return ion_rows, global_rows, row_map, receipt


def materialize(
    source_path: Path,
    connection: dict[str, object],
) -> tuple[list[list[str]], list[dict[str, str]]]:
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SOURCE_COLUMNS:
            raise ValueError("mother-sample columns differ from the canonical source contract")
        source_rows = list(reader)
    if not source_rows:
        raise ValueError("mother sample is empty")
    registration = connection["spatial_registration"]
    rotation = registration["rotation_upstream_to_downstream"]
    translation = registration["translation_mm"]
    if rotation != [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]:
        raise ValueError("single-flight source requires the canonical multipole-to-oaTOF rotation")
    tx, ty, tz = map(float, translation)
    ion_rows: list[list[str]] = []
    global_rows: list[dict[str, str]] = []
    expected_ids = list(range(1, len(source_rows) + 1))
    actual_ids = [int(row["particle_id"]) for row in source_rows]
    if actual_ids != expected_ids:
        raise ValueError("mother-sample particle IDs must be contiguous and ordered")
    for row in source_rows:
        particle_id = int(row["particle_id"])
        local_x, local_y, local_z = (float(row[f"{axis}_mm"]) for axis in "xyz")
        local_vx, local_vy, local_vz = (float(row[f"v{axis}_m_s"]) for axis in "xyz")
        x, y, z = local_z + tx, local_x + ty, local_y + tz
        vx, vy, vz = local_vz, local_vx, local_vy
        mass = float(row["mass_amu"])
        charge = int(row["charge_state"])
        time_us = float(row["birth_time_s"]) * 1e6
        energy = kinetic_energy_ev(mass, vx, vy, vz)
        azimuth, elevation = encode_simion_accelerator_velocity((vx, vy, vz))
        ion_rows.append(
            [
                "0",
                format(mass, ".17g"),
                str(charge),
                format(x, ".17g"),
                format(y, ".17g"),
                format(z, ".17g"),
                format(azimuth, ".17g"),
                format(elevation, ".17g"),
                format(energy, ".17g"),
                "1",
                "3",
            ]
        )
        global_rows.append(
            {
                "particle_id": str(particle_id),
                "instrument_time_us": format(time_us, ".17g"),
                "mass_amu": format(mass, ".17g"),
                "charge_state": str(charge),
                "position_x_mm": format(x, ".17g"),
                "position_y_mm": format(y, ".17g"),
                "position_z_mm": format(z, ".17g"),
                "velocity_x_m_s": format(vx, ".17g"),
                "velocity_y_m_s": format(vy, ".17g"),
                "velocity_z_m_s": format(vz, ".17g"),
                "kinetic_energy_eV": format(energy, ".17g"),
            }
        )
    return ion_rows, global_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--connection", required=True, type=Path)
    parser.add_argument("--particle-input", required=True, type=Path)
    parser.add_argument("--global-state", required=True, type=Path)
    parser.add_argument("--row-map", type=Path)
    parser.add_argument(
        "--source-release-mode",
        choices=(
            "continuous_frontend",
            "continuous_frontend_handoff",
            "pre_pulse_restart",
        ),
        default="continuous_frontend",
    )
    parser.add_argument("--pulse-time-us", type=float)
    parser.add_argument("--handoff-mass-amu", type=float)
    parser.add_argument("--handoff-charge-state", type=int)
    parser.add_argument("--handoff-receipt", type=Path)
    parser.add_argument("--handoff-smoke-source-particle-id", type=int)
    parser.add_argument("--handoff-execution-particle-count", type=int)
    args = parser.parse_args()
    connection = json.loads(args.connection.read_text(encoding="utf-8-sig"))
    if args.source_release_mode == "pre_pulse_restart":
        if args.pulse_time_us is None:
            raise ValueError("pre-pulse restart requires the pulse time")
        particle_input, global_rows = materialize_pre_pulse_restart(
            args.source, args.pulse_time_us
        )
        row_map = None
    elif args.source_release_mode == "continuous_frontend_handoff":
        if (
            args.handoff_mass_amu is None
            or args.handoff_charge_state is None
            or args.handoff_receipt is None
        ):
            raise ValueError("terminal-handoff continuation requires mass, charge, and receipt output")
        ion_rows, global_rows, row_map, receipt = materialize_terminal_handoff_continuation(
            args.source, connection, mass_amu=args.handoff_mass_amu,
            charge_state=args.handoff_charge_state,
            smoke_source_particle_id=args.handoff_smoke_source_particle_id,
            execution_particle_count=args.handoff_execution_particle_count,
        )
        args.handoff_receipt.parent.mkdir(parents=True, exist_ok=True)
        args.handoff_receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        particle_input = None
    else:
        ion_rows, global_rows = materialize(args.source, connection)
        particle_input = None
        row_map = None
    args.particle_input.parent.mkdir(parents=True, exist_ok=True)
    args.global_state.parent.mkdir(parents=True, exist_ok=True)
    if particle_input is not None:
        args.particle_input.write_text(particle_input, encoding="utf-8", newline="\n")
    else:
        with args.particle_input.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(ion_rows)
    with args.global_state.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(global_rows)
    if args.row_map is not None:
        args.row_map.parent.mkdir(parents=True, exist_ok=True)
        with args.row_map.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=ROW_MAP_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(row_map if row_map is not None else (
                {"simulation_particle_id": simulation_id, "source_particle_id": row["particle_id"]}
                for simulation_id, row in enumerate(global_rows, start=1)
            ))
    print(
        "SINGLE_FLIGHT_SOURCE=PASS "
        f"PARTICLES={len(global_rows)} PARTICLE_INPUT={args.particle_input}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
