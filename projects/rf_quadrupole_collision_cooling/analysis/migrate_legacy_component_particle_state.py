"""Explicitly migrate the historical RF-to-oaTOF 25-column state table.

The input is read-only legacy evidence. Callers must bind the new species,
statistical weight, and phase-reference identities; this adapter never invents
them or rewrites the source file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th


LEGACY_25_COLUMNS = [
    "particle_id", "parent_particle_id", "generation", "source_component_id",
    "target_component_id", "state_event", "frame_id", "clock_epoch_id",
    "instrument_time_us", "lineage_age_us", "particle_age_us",
    "last_component_elapsed_time_us", "lineage_birth_time_us",
    "particle_birth_time_us", "mass_to_charge_Th", "mass_amu", "charge_state",
    "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s",
    "velocity_y_m_s", "velocity_z_m_s", "kinetic_energy_eV",
    "source_rf_phase_rad",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def migrate(
    source: Path,
    output: Path,
    metadata_output: Path,
    *,
    species_id: str,
    particle_weight: float,
    phase_reference_id: str,
) -> dict[str, object]:
    """Write a validated common-v1 copy while preserving the legacy source."""
    if not species_id or not phase_reference_id:
        raise ValueError("species_id and phase_reference_id bindings are required")
    if not math.isfinite(particle_weight) or particle_weight <= 0:
        raise ValueError("particle_weight binding must be finite and positive")
    source_sha = _sha256(source)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != LEGACY_25_COLUMNS:
            raise ValueError("input is not the exact legacy RF-to-oaTOF 25-column schema")
        legacy_rows = list(reader)
    if not legacy_rows:
        raise ValueError("legacy particle-state table is empty")

    rows: list[dict[str, object]] = []
    for legacy in legacy_rows:
        mass_amu = float(legacy["mass_amu"])
        charge_state = int(legacy["charge_state"])
        if charge_state == 0:
            raise ValueError("legacy charge_state must be non-zero")
        velocity = tuple(float(legacy[f"velocity_{axis}_m_s"]) for axis in "xyz")
        row = {
            name: legacy[name]
            for name in LEGACY_25_COLUMNS
            if name not in {
                "mass_to_charge_Th", "kinetic_energy_eV", "source_rf_phase_rad",
            }
        }
        row.update({
            "species_id": species_id,
            "particle_weight": f"{particle_weight:.15g}",
            "mass_to_charge_Th": f"{mass_to_charge_th(mass_amu, charge_state):.15g}",
            "kinetic_energy_eV": f"{kinetic_energy_ev(mass_amu, *velocity):.15g}",
            "phase_reference_id": phase_reference_id,
            "phase_rad": legacy["source_rf_phase_rad"],
        })
        rows.append(row)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    validate_component_particle_state_csv(output)
    if _sha256(source) != source_sha:
        raise RuntimeError("legacy source changed during migration")

    metadata = {
        "schema_version": 1,
        "role": "legacy_25_column_component_state_to_common_v1_migration",
        "status": "PASS",
        "source_preserved": True,
        "source": {"path": str(source.resolve()), "sha256": source_sha},
        "bindings": {
            "species_id": species_id,
            "particle_weight": particle_weight,
            "phase_reference_id": phase_reference_id,
        },
        "output": {"path": str(output.resolve()), "sha256": _sha256(output)},
        "rows": len(rows),
    }
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    parser.add_argument("--species-id", required=True)
    parser.add_argument("--particle-weight", type=float, required=True)
    parser.add_argument("--phase-reference-id", required=True)
    args = parser.parse_args()
    result = migrate(
        args.source,
        args.output,
        args.metadata_output,
        species_id=args.species_id,
        particle_weight=args.particle_weight,
        phase_reference_id=args.phase_reference_id,
    )
    print(f"LEGACY_COMPONENT_STATE_MIGRATION=PASS ROWS={result['rows']}")


if __name__ == "__main__":
    main()
