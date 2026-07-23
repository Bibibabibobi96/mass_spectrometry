"""Validate a canonical multipole particle source and freeze its physical metadata."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_count_policy import validate_standard_particle_count

AMU_KG = 1.66053906660e-27
E_CHARGE_C = 1.602176634e-19
COLUMNS = [
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
ENERGY_BOUND_TOLERANCE_EV = 2e-9


def validate_source(path: Path, resolved: dict[str, Any]) -> dict[str, Any]:
    """Return frozen metadata after binding every source row to the resolved design."""
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("particle source requires a multipole resolved design")
    source_plane = float(resolved["interfaces_mm"]["entrance"]["particle_plane_z_mm"])
    expected_charge = int(resolved["particle_source"]["charge_state"])
    energy_model = resolved["particle_source"]["energy_model"]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"canonical particle source columns differ: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise ValueError("canonical particle source is empty")
    validate_standard_particle_count(len(rows))
    particle_ids: set[int] = set()
    masses: set[float] = set()
    energies: list[float] = []
    for row in rows:
        particle_id = int(row["particle_id"])
        if particle_id in particle_ids:
            raise ValueError(f"duplicate particle_id: {particle_id}")
        particle_ids.add(particle_id)
        values = [float(row[name]) for name in COLUMNS[1:-1]]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"particle {particle_id} contains a non-finite value")
        mass = float(row["mass_amu"])
        charge = int(row["charge_state"])
        if mass <= 0 or charge == 0:
            raise ValueError(f"particle {particle_id} has invalid mass or charge")
        if charge != expected_charge:
            raise ValueError(f"particle {particle_id} charge differs from resolved design")
        if abs(float(row["z_mm"]) - source_plane) > 1e-12:
            raise ValueError(f"particle {particle_id} source plane differs from resolved design")
        if float(row["birth_time_s"]) < 0:
            raise ValueError(f"particle {particle_id} has a negative source clock")
        speed_squared = sum(float(row[name]) ** 2 for name in ("vx_m_s", "vy_m_s", "vz_m_s"))
        energy_ev = 0.5 * mass * AMU_KG * speed_squared / E_CHARGE_C
        if energy_model["kind"] == "monoenergetic":
            expected_energy = float(energy_model["kinetic_energy_eV"])
            if not math.isclose(
                energy_ev, expected_energy, rel_tol=1e-9, abs_tol=1e-12
            ):
                raise ValueError(
                    f"particle {particle_id} kinetic energy differs from resolved design"
                )
        else:
            minimum = float(energy_model["minimum_energy_eV"])
            maximum = float(energy_model["maximum_energy_eV"])
            if (
                energy_ev < minimum - ENERGY_BOUND_TOLERANCE_EV
                or energy_ev > maximum + ENERGY_BOUND_TOLERANCE_EV
            ):
                raise ValueError(
                    f"particle {particle_id} kinetic energy is outside the resolved closed interval"
                )
        energies.append(energy_ev)
        masses.add(mass)
    if len(masses) != 1:
        raise ValueError("canonical particle source contains multiple masses")
    if particle_ids != set(range(1, len(rows) + 1)):
        raise ValueError("canonical particle IDs must be contiguous from 1 through N")
    return {
        "schema_version": 1,
        "role": "multipole_canonical_particle_source_metadata",
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "parent_resolved_design_sha256": resolved["resolved_sha256"],
        "particle_count": len(rows),
        "mass_amu": masses.pop(),
        "charge_state": expected_charge,
        "source_plane_z_mm": source_plane,
        "energy_model": energy_model,
        "sample_energy_statistics_eV": {
            "minimum": min(energies),
            "maximum": max(energies),
            "mean": sum(energies) / len(energies),
        },
        "energy_validation_tolerance_eV": ENERGY_BOUND_TOLERANCE_EV,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--resolved-design", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    resolved = json.loads(args.resolved_design.read_text(encoding="utf-8-sig"))
    metadata = validate_source(args.source, resolved)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(
        "MULTIPOLE_CANONICAL_SOURCE=PASS "
        f"PARTICLES={metadata['particle_count']} SHA256={metadata['source_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
