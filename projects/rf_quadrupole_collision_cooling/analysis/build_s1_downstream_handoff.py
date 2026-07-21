"""Build a no-projection oaTOF handoff from the S1 local-joint exit states."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from build_oatof_handoff import (
    ATOMIC_MASS_KG,
    CANONICAL_COLUMNS,
    ELEMENTARY_CHARGE_C,
    ROW_MAP_COLUMNS,
    simion_accelerator_instance_angles,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(
    events_path: Path,
    entry_path: Path,
    canonical_output: Path,
    ion_output: Path,
    row_map_output: Path,
    metadata_output: Path,
) -> dict[str, object]:
    events = read_rows(events_path)
    entries = {int(row["particle_id"]): row for row in read_rows(entry_path)}
    exits = sorted(
        (row for row in events if row["event"] == "local_joint_exit" and row["status"] == "transmitted"),
        key=lambda row: int(row["particle_id"]),
    )
    if not exits:
        raise ValueError("S1 result contains no transmitted local-joint exits")
    if len({int(row["particle_id"]) for row in exits}) != len(exits):
        raise ValueError("S1 local-joint exit particle IDs are not unique")

    canonical: list[dict[str, object]] = []
    row_map: list[dict[str, object]] = []
    ion_lines: list[str] = []
    max_energy_residual = 0.0
    for solver_index, event in enumerate(exits, start=1):
        particle_id = int(event["particle_id"])
        if particle_id not in entries:
            raise ValueError(f"S1 exit particle {particle_id} has no canonical entry state")
        entry = entries[particle_id]
        instrument_time = float(event["instrument_time_us"])
        entry_time = float(entry["instrument_time_us"])
        elapsed = instrument_time - entry_time
        if elapsed < 0:
            raise ValueError("S1 local-joint exit precedes its entry time")
        position = [float(event[name]) for name in ("x_mm", "y_mm", "z_mm")]
        velocity = [float(event[name]) for name in ("vx_m_s", "vy_m_s", "vz_m_s")]
        mass_amu = float(entry["mass_amu"])
        charge_state = int(float(entry["charge_state"]))
        kinetic_energy = float(event["kinetic_energy_eV"])
        velocity_energy = (
            0.5 * mass_amu * ATOMIC_MASS_KG * sum(value * value for value in velocity)
            / ELEMENTARY_CHARGE_C
        )
        residual = abs(velocity_energy - kinetic_energy) / kinetic_energy
        max_energy_residual = max(max_energy_residual, residual)
        if residual > 1e-9:
            raise ValueError("S1 exit kinetic energy is inconsistent with its velocity")
        azimuth, elevation = simion_accelerator_instance_angles(velocity)
        lineage_age = float(entry["lineage_age_us"]) + elapsed
        particle_age = float(entry["particle_age_us"]) + elapsed
        canonical.append({
            "particle_id": particle_id,
            "parent_particle_id": entry.get("parent_particle_id", ""),
            "generation": int(float(entry["generation"])),
            "source_component_id": "rf_oatof_s1_local_joint",
            "target_component_id": "oa_tof_downstream_analyzer",
            "state_event": "local_joint_exit",
            "frame_id": entry["frame_id"],
            "clock_epoch_id": entry["clock_epoch_id"],
            "instrument_time_us": f"{instrument_time:.15g}",
            "lineage_age_us": f"{lineage_age:.15g}",
            "particle_age_us": f"{particle_age:.15g}",
            "last_component_elapsed_time_us": f"{elapsed:.15g}",
            "lineage_birth_time_us": entry["lineage_birth_time_us"],
            "particle_birth_time_us": entry["particle_birth_time_us"],
            "mass_to_charge_Th": entry["mass_to_charge_Th"],
            "mass_amu": entry["mass_amu"],
            "charge_state": charge_state,
            "position_x_mm": f"{position[0]:.15g}",
            "position_y_mm": f"{position[1]:.15g}",
            "position_z_mm": f"{position[2]:.15g}",
            "velocity_x_m_s": f"{velocity[0]:.15g}",
            "velocity_y_m_s": f"{velocity[1]:.15g}",
            "velocity_z_m_s": f"{velocity[2]:.15g}",
            "kinetic_energy_eV": f"{kinetic_energy:.15g}",
            "source_rf_phase_rad": event["rf_phase_rad"],
        })
        row_map.append({
            "solver_row_index": solver_index,
            "particle_id": particle_id,
            "instrument_time_us": f"{instrument_time:.15g}",
            "lineage_age_us": f"{lineage_age:.15g}",
            "particle_age_us": f"{particle_age:.15g}",
            "solver_birth_time_us": f"{instrument_time:.15g}",
            "azimuth_deg": f"{azimuth:.15g}",
            "elevation_deg": f"{elevation:.15g}",
        })
        ion_values = [instrument_time, mass_amu, charge_state, *position, azimuth, elevation,
                      kinetic_energy, 1, 3]
        ion_lines.append(",".join(f"{float(value):.15g}" for value in ion_values))

    write_csv(canonical_output, CANONICAL_COLUMNS, canonical)
    write_csv(row_map_output, ROW_MAP_COLUMNS, row_map)
    ion_output.parent.mkdir(parents=True, exist_ok=True)
    ion_output.write_text("\n".join(ion_lines) + "\n", encoding="utf-8", newline="\n")
    metadata = {
        "schema_version": 1,
        "role": "rf_to_oatof_s1_no_projection_downstream_handoff",
        "status": "PASS",
        "particles": len(exits),
        "source": {
            "events": {"path": str(events_path.resolve()), "sha256": sha256(events_path)},
            "entry_canonical": {"path": str(entry_path.resolve()), "sha256": sha256(entry_path)},
        },
        "transform": {"kind": "identity", "position_projection_applied": False},
        "clock": {"solver_clock": "instrument_time", "per_particle_birth_time_preserved": True},
        "pulse": {"already_applied_in_local_joint": True, "downstream_waveform_must_continue_on_shared_clock": True},
        "diagnostics": {"maximum_energy_velocity_relative_residual": max_energy_residual},
        "outputs": {
            "canonical": {"path": str(canonical_output.resolve()), "sha256": sha256(canonical_output)},
            "ion": {"path": str(ion_output.resolve()), "sha256": sha256(ion_output)},
            "row_map": {"path": str(row_map_output.resolve()), "sha256": sha256(row_map_output)},
        },
        "physical_link_claim_allowed": False,
        "resolution_claim_allowed": False,
    }
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--entry-canonical", type=Path, required=True)
    parser.add_argument("--canonical-output", type=Path, required=True)
    parser.add_argument("--ion-output", type=Path, required=True)
    parser.add_argument("--row-map-output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.events, args.entry_canonical, args.canonical_output, args.ion_output,
                   args.row_map_output, args.metadata_output)
    print(f"S1_DOWNSTREAM_HANDOFF=PASS PARTICLES={result['particles']} PROJECTION=false")


if __name__ == "__main__":
    main()
