"""Paired multi-mass particle-table construction for RF multipole scans."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    """Return the uppercase SHA-256 digest of ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_ion_rows(path: Path) -> list[list[str]]:
    """Load and validate an eleven-column SIMION ION table."""
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    if not rows or any(len(row) != 11 for row in rows):
        raise ValueError("source ION table must contain non-empty eleven-column rows")
    return rows


def validate_masses(values: list[Any]) -> list[float]:
    """Return strictly increasing, finite positive scan masses in Th."""
    masses = [float(value) for value in values]
    if len(masses) < 3 or any(not math.isfinite(value) or value <= 0 for value in masses):
        raise ValueError("scan masses must contain at least three finite positive values")
    if masses != sorted(set(masses)):
        raise ValueError("scan masses must be strictly increasing and unique")
    return masses


def build_paired_ion_rows(source_rows: list[list[str]], masses_Th: list[float]) -> list[list[str]]:
    """Replicate identical phase-space rows at each requested mass."""
    output: list[list[str]] = []
    for mass in validate_masses(masses_Th):
        mass_text = f"{mass:.12g}"
        for source in source_rows:
            row = source.copy()
            row[1] = mass_text
            output.append(row)
    return output


def write_ion_table(path: Path, rows: list[list[str]]) -> None:
    """Write an ASCII-compatible ION table without a BOM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream, lineterminator="\n").writerows(rows)


def generate_paired_ion_table(
    source_path: Path,
    destination: Path,
    metadata_path: Path,
    masses_Th: list[float],
    expected_particles_per_mass: int,
    provenance: dict[str, str],
) -> dict[str, Any]:
    """Generate a paired ION table and a compact provenance document."""
    source_rows = load_ion_rows(source_path)
    if len(source_rows) != int(expected_particles_per_mass):
        raise ValueError("source row count differs from expected_particles_per_mass")
    masses = validate_masses(masses_Th)
    output_rows = build_paired_ion_rows(source_rows, masses)
    write_ion_table(destination, output_rows)
    metadata = {
        "schema_version": 1,
        "role": "rf_multipole_paired_mass_scan_particle_table",
        "source": str(source_path.resolve()),
        "source_sha256": sha256(source_path),
        "masses_Th": masses,
        "particles_per_mass": int(expected_particles_per_mass),
        "particles": len(output_rows),
        "pairing": "each mass uses the same source rows in the same order",
        "particle_table": str(destination.resolve()),
        "particle_table_sha256": sha256(destination),
        "provenance": provenance,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata
