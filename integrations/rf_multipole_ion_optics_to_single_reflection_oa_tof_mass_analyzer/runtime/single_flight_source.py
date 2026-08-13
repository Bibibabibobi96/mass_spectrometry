"""Map a multipole mother sample into the continuous oaTOF SIMION workbench."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from common.contracts.particle_physics import kinetic_energy_ev
from projects.single_reflection_oa_tof_mass_analyzer.analysis.rf_handoff_adapter import (
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


def materialize_pre_pulse_restart(
    source_path: Path, pulse_time_us: float, initial_pa_instance: int = 3,
) -> tuple[list[list[str]], list[dict[str, str]]]:
    """Materialize an oaTOF-global pre-pulse state without upstream remapping."""
    if pulse_time_us < 0 or initial_pa_instance not in {3, 5}:
        raise ValueError("pre-pulse restart clock or PA instance is invalid")
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != GLOBAL_COLUMNS:
            raise ValueError("pre-pulse source-state columns differ from the global contract")
        rows = list(reader)
    if not rows or [int(row["particle_id"]) for row in rows] != list(
        range(1, len(rows) + 1)
    ):
        raise ValueError("pre-pulse source-state IDs must be contiguous and ordered")
    ion_rows: list[list[str]] = []
    for row in rows:
        if abs(float(row["instrument_time_us"]) - pulse_time_us) > 1e-9:
            raise ValueError("pre-pulse source-state clock differs from the pulse time")
        velocity = tuple(float(row[f"velocity_{axis}_m_s"]) for axis in "xyz")
        mass = float(row["mass_amu"])
        energy = kinetic_energy_ev(mass, *velocity)
        if abs(energy - float(row["kinetic_energy_eV"])) > 1e-9:
            raise ValueError("pre-pulse source-state kinetic energy differs")
        azimuth, elevation = encode_simion_accelerator_velocity(velocity)
        ion_rows.append([
            format(pulse_time_us, ".17g"), format(mass, ".17g"),
            str(int(row["charge_state"])),
            *(format(float(row[f"position_{axis}_mm"]), ".17g") for axis in "xyz"),
            format(azimuth, ".17g"), format(elevation, ".17g"),
            format(energy, ".17g"), "1", str(initial_pa_instance),
        ])
    return ion_rows, rows


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
                format(time_us, ".17g"),
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
    parser.add_argument("--ion", required=True, type=Path)
    parser.add_argument("--global-state", required=True, type=Path)
    parser.add_argument(
        "--source-release-mode",
        choices=("continuous_frontend", "pre_pulse_restart"),
        default="continuous_frontend",
    )
    parser.add_argument("--pulse-time-us", type=float)
    args = parser.parse_args()
    connection = json.loads(args.connection.read_text(encoding="utf-8-sig"))
    if args.source_release_mode == "pre_pulse_restart":
        if args.pulse_time_us is None:
            raise ValueError("pre-pulse restart requires the pulse time")
        ion_rows, global_rows = materialize_pre_pulse_restart(
            args.source, args.pulse_time_us
        )
    else:
        ion_rows, global_rows = materialize(args.source, connection)
    args.ion.parent.mkdir(parents=True, exist_ok=True)
    args.global_state.parent.mkdir(parents=True, exist_ok=True)
    with args.ion.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(ion_rows)
    with args.global_state.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(global_rows)
    print(f"SINGLE_FLIGHT_SOURCE=PASS PARTICLES={len(ion_rows)} ION={args.ion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
