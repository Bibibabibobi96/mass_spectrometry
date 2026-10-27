"""Paired multi-mass particle-table construction for RF multipole scans."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256 as sha256


def load_ion_rows(path: Path) -> list[list[str]]:
    """Load an ION11 source within the positive singly charged scan scope."""
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    _validate_source_rows(rows)
    return rows


def _validate_source_rows(rows: list[list[str]]) -> None:
    """The scan writes Th into the physical mass column only for charge +1."""
    if not rows or any(len(row) != 11 for row in rows):
        raise ValueError("source ION table must contain non-empty eleven-column rows")
    for row in rows:
        mass, charge = row[1], row[2]
        if isinstance(mass, bool) or not math.isfinite(float(mass)) or float(mass) <= 0:
            raise ValueError("mass-scan source mass_amu must be finite and positive")
        if isinstance(charge, bool) or not math.isfinite(float(charge)) or float(charge) != 1.0:
            raise ValueError("mass scan requires charge_state exactly +1")


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
    _validate_source_rows(source_rows)
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
        "species_scope": "positive_single_charge_mass_amu_equals_mass_to_charge_Th",
        "charge_state": 1,
        "particle_table": str(destination.resolve()),
        "particle_table_sha256": sha256(destination),
        "provenance": provenance,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata


def generate_paired_case_tables(
    source_path: Path,
    output_directory: Path,
    masses_Th: list[float],
    expected_particles_per_mass: int,
) -> list[dict[str, Any]]:
    """Write one solver-ready ION table per mass from the same source rows."""
    source_rows = load_ion_rows(source_path)
    if len(source_rows) != int(expected_particles_per_mass):
        raise ValueError("source row count differs from expected_particles_per_mass")
    output_directory.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    masses = validate_masses(masses_Th)
    for mass in masses:
        token = f"{mass:.12g}".replace(".", "p")
        destination = output_directory / f"mass_{token}_Th.ion"
        mass_text = f"{mass:.12g}"
        rows = []
        for source in source_rows:
            row = source.copy()
            row[1] = mass_text
            rows.append(row)
        write_ion_table(destination, rows)
        cases.append({
            "mass_Th": mass,
            "charge_state": 1,
            "species_scope": "positive_single_charge_mass_amu_equals_mass_to_charge_Th",
            "particles": len(rows),
            "particle_table": str(destination.resolve()),
            "particle_table_sha256": sha256(destination),
        })
    return cases
