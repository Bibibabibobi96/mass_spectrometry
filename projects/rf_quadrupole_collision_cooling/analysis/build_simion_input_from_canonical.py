"""Derive a SIMION ION adapter from a canonical component-exit table."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

try:
    from build_oatof_handoff import CANONICAL_COLUMNS, ROW_MAP_COLUMNS, simion_accelerator_instance_angles
except ModuleNotFoundError:
    from projects.rf_quadrupole_collision_cooling.analysis.build_oatof_handoff import (
        CANONICAL_COLUMNS,
        ROW_MAP_COLUMNS,
        simion_accelerator_instance_angles,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(source: Path, canonical_output: Path, ion_output: Path,
          row_map_output: Path, metadata_output: Path) -> dict[str, object]:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CANONICAL_COLUMNS:
            raise ValueError("source is not the complete canonical particle-state schema")
        rows = sorted(reader, key=lambda row: int(row["particle_id"]))
    if not rows or len({row["particle_id"] for row in rows}) != len(rows):
        raise ValueError("canonical source must contain unique particle IDs")

    mapping: list[dict[str, object]] = []
    ion_lines: list[str] = []
    frames = {row["frame_id"] for row in rows}
    epochs = {row["clock_epoch_id"] for row in rows}
    for solver_index, row in enumerate(rows, start=1):
        velocity = [float(row[f"velocity_{axis}_m_s"]) for axis in "xyz"]
        azimuth, elevation = simion_accelerator_instance_angles(velocity)
        birth_time = float(row["instrument_time_us"])
        values = [
            birth_time, float(row["mass_amu"]), int(float(row["charge_state"])),
            *(float(row[f"position_{axis}_mm"]) for axis in "xyz"),
            azimuth, elevation, float(row["kinetic_energy_eV"]), 1, 3,
        ]
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("canonical state contains a non-finite SIMION input value")
        ion_lines.append(",".join(f"{float(value):.15g}" for value in values))
        mapping.append({
            "solver_row_index": solver_index,
            "particle_id": int(row["particle_id"]),
            "instrument_time_us": row["instrument_time_us"],
            "lineage_age_us": row["lineage_age_us"],
            "particle_age_us": row["particle_age_us"],
            "solver_birth_time_us": f"{birth_time:.15g}",
            "azimuth_deg": f"{azimuth:.15g}",
            "elevation_deg": f"{elevation:.15g}",
        })

    canonical_output.parent.mkdir(parents=True, exist_ok=True)
    canonical_output.write_bytes(source.read_bytes())
    _write_csv(row_map_output, ROW_MAP_COLUMNS, mapping)
    ion_output.write_text("\n".join(ion_lines) + "\n", encoding="utf-8", newline="\n")
    metadata = {
        "schema_version": 1,
        "role": "canonical_component_exit_to_simion_adapter",
        "status": "PASS",
        "particles": len(rows),
        "source": {"path": str(source.resolve()), "sha256": _sha256(source)},
        "transform": {"kind": "identity", "position_projection_applied": False},
        "coordinate_contract": {"frames": sorted(frames), "simion_accelerator_instance": 3},
        "clock_contract": {"epochs": sorted(epochs), "solver_birth_time": "instrument_time_us"},
        "outputs": {
            "canonical": {"path": str(canonical_output.resolve()), "sha256": _sha256(canonical_output)},
            "ion": {"path": str(ion_output.resolve()), "sha256": _sha256(ion_output)},
            "row_map": {"path": str(row_map_output.resolve()), "sha256": _sha256(row_map_output)},
        },
    }
    metadata_output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--canonical-output", type=Path, required=True)
    parser.add_argument("--ion-output", type=Path, required=True)
    parser.add_argument("--row-map-output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source, args.canonical_output, args.ion_output,
                   args.row_map_output, args.metadata_output)
    print(f"CANONICAL_SIMION_ADAPTER=PASS PARTICLES={result['particles']}")


if __name__ == "__main__":
    main()
