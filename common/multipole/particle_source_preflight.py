"""Validate a canonical multipole particle source and freeze its physical metadata."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts import particle_physics
from common.contracts.particle_count_policy import validate_standard_particle_count

# Backward-compatible public names for existing source builders and tests.
AMU_KG = particle_physics.AMU_KG
E_CHARGE_C = particle_physics.ELEMENTARY_CHARGE_C

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


def _load_operating_point(
    source_family_path: Path | None,
    operating_point_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if (source_family_path is None) != (operating_point_id is None):
        raise ValueError(
            "source-family operating-point binding requires both path and point ID"
        )
    if source_family_path is None:
        return None, None, None
    family_bytes = source_family_path.read_bytes()
    family_sha256 = hashlib.sha256(family_bytes).hexdigest().upper()
    family = json.loads(family_bytes.decode("utf-8-sig"))
    if (
        family.get("schema_version") != 1
        or not isinstance(family.get("operating_points"), dict)
        or operating_point_id not in family["operating_points"]
    ):
        raise ValueError("source-family operating-point binding is invalid")
    point = family["operating_points"][operating_point_id]
    required = {"mass_amu", "charge_state", "kinetic_energy_eV"}
    if not isinstance(point, dict) or not required.issubset(point):
        raise ValueError("source-family operating point is incomplete")
    return family, point, family_sha256


def _validate_energy(
    particle_id: int,
    energy_ev: float,
    energy_model: dict[str, Any],
    *,
    operating_point: bool,
) -> None:
    if operating_point:
        distribution = energy_model.get("distribution")
        if distribution == "fixed":
            expected_energy = float(energy_model["value"])
            if not math.isfinite(expected_energy) or expected_energy < 0:
                raise ValueError(
                    "source-family fixed energy must be finite and nonnegative"
                )
            if not math.isclose(
                energy_ev, expected_energy, rel_tol=1e-9, abs_tol=1e-12
            ):
                raise ValueError(
                    f"particle {particle_id} kinetic energy differs from operating point"
                )
            return
        if distribution == "uniform":
            minimum = float(energy_model["min"])
            maximum = float(energy_model["max"])
            if (
                not math.isfinite(minimum)
                or not math.isfinite(maximum)
                or minimum < 0
                or maximum < minimum
            ):
                raise ValueError(
                    "source-family uniform energy bounds must be finite, "
                    "nonnegative, and ordered"
                )
        else:
            raise ValueError("source-family operating-point energy model is unsupported")
    elif energy_model["kind"] == "monoenergetic":
        expected_energy = float(energy_model["kinetic_energy_eV"])
        if not math.isclose(
            energy_ev, expected_energy, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ValueError(
                f"particle {particle_id} kinetic energy differs from resolved design"
            )
        return
    else:
        minimum = float(energy_model["minimum_energy_eV"])
        maximum = float(energy_model["maximum_energy_eV"])
    if (
        energy_ev < minimum - ENERGY_BOUND_TOLERANCE_EV
        or energy_ev > maximum + ENERGY_BOUND_TOLERANCE_EV
    ):
        authority = "operating point" if operating_point else "resolved closed interval"
        raise ValueError(f"particle {particle_id} kinetic energy is outside the {authority}")


def validate_source(
    path: Path,
    resolved: dict[str, Any],
    *,
    source_family_path: Path | None = None,
    operating_point_id: str | None = None,
    expected_source_family_sha256: str | None = None,
) -> dict[str, Any]:
    """Return frozen metadata after binding every source row to the resolved design."""
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("particle source requires a multipole resolved design")
    _, operating_point, source_family_sha256 = _load_operating_point(
        source_family_path, operating_point_id
    )
    if expected_source_family_sha256 is not None:
        if source_family_sha256 is None:
            raise ValueError("expected source-family SHA-256 requires a source family")
        if source_family_sha256 != expected_source_family_sha256.upper():
            raise ValueError("source-family SHA-256 differs from the frozen runner input")
    source_plane = float(resolved["interfaces_mm"]["entrance"]["particle_plane_z_mm"])
    expected_charge = int(resolved["particle_source"]["charge_state"])
    energy_model = (
        operating_point["kinetic_energy_eV"]
        if operating_point is not None
        else resolved["particle_source"]["energy_model"]
    )
    expected_mass = (
        float(operating_point["mass_amu"])
        if operating_point is not None
        else None
    )
    if operating_point is not None and int(operating_point["charge_state"]) != expected_charge:
        raise ValueError("source-family operating-point charge differs from resolved design")
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
        if expected_mass is not None and mass != expected_mass:
            raise ValueError(
                f"particle {particle_id} mass differs from operating point"
            )
        if charge != expected_charge:
            raise ValueError(f"particle {particle_id} charge differs from resolved design")
        if abs(float(row["z_mm"]) - source_plane) > 1e-12:
            raise ValueError(f"particle {particle_id} source plane differs from resolved design")
        if float(row["birth_time_s"]) < 0:
            raise ValueError(f"particle {particle_id} has a negative source clock")
        energy_ev = particle_physics.kinetic_energy_ev(
            mass,
            *(float(row[name]) for name in ("vx_m_s", "vy_m_s", "vz_m_s")),
        )
        _validate_energy(
            particle_id,
            energy_ev,
            energy_model,
            operating_point=operating_point is not None,
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
        "operating_point_binding": (
            {
                "operating_point_id": operating_point_id,
                "source_family_sha256": source_family_sha256,
            }
            if source_family_path is not None
            else None
        ),
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
    parser.add_argument("--source-family", type=Path)
    parser.add_argument("--operating-point")
    parser.add_argument("--expected-source-family-sha256")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    resolved = json.loads(args.resolved_design.read_text(encoding="utf-8-sig"))
    metadata = validate_source(
        args.source,
        resolved,
        source_family_path=args.source_family,
        operating_point_id=args.operating_point,
        expected_source_family_sha256=args.expected_source_family_sha256,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(
        "MULTIPOLE_CANONICAL_SOURCE=PASS "
        f"PARTICLES={metadata['particle_count']} SHA256={metadata['source_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
