"""Generate the fixed paired realization of the SIMION built-in quad source."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.multipole.particle_source_preflight import COLUMNS


SEED = 20260716
MASTER_COUNT = 1000
STANDARD_COUNTS = (100, 1000)


def generate(count: int = 100) -> np.ndarray:
    validate_standard_particle_count(count)
    rng = np.random.default_rng(SEED)
    n = MASTER_COUNT
    birth = rng.uniform(0.0, 0.909091, n)
    y = rng.uniform(-0.05, 0.05, n)
    z = rng.uniform(-0.05, 0.05, n)
    energy = rng.uniform(1.8, 2.2, n)
    phi = rng.uniform(0.0, 2.0 * np.pi, n)
    cos_theta = rng.uniform(np.cos(np.deg2rad(5.0)), 1.0, n)
    theta = np.arccos(cos_theta)
    vx = np.cos(theta)
    vy = np.sin(theta) * np.cos(phi)
    vz = np.sin(theta) * np.sin(phi)
    azimuth = np.rad2deg(np.arctan2(vy, vx))
    elevation = np.rad2deg(np.arcsin(vz))
    master = np.column_stack(
        [birth, np.full(n, 100.0), np.ones(n), np.zeros(n), y, z,
         azimuth, elevation, energy, np.ones(n), np.full(n, 3.0)]
    )
    return master[:count]


def generate_canonical(count: int, resolved_design: dict[str, object]) -> list[dict[str, str]]:
    """Project the official local ION11 realization onto the governed release plane."""
    source = generate(count)
    release_z_mm = float(
        resolved_design["interfaces_mm"]["entrance"]["release_plane_z_mm"]  # type: ignore[index]
    )
    rows: list[dict[str, str]] = []
    for particle_id, values in enumerate(source, start=1):
        birth_us, mass_amu, charge_state = values[:3]
        transverse_1_mm, transverse_2_mm = values[4:6]
        azimuth_rad = math.radians(values[6])
        elevation_rad = math.radians(values[7])
        energy_eV = values[8]
        speed_m_s = math.sqrt(
            2.0 * energy_eV * ELEMENTARY_CHARGE_C / (mass_amu * AMU_KG)
        )
        axial_fraction = math.cos(elevation_rad) * math.cos(azimuth_rad)
        transverse_1_fraction = math.cos(elevation_rad) * math.sin(azimuth_rad)
        transverse_2_fraction = math.sin(elevation_rad)
        rows.append(
            {
                "particle_id": str(particle_id),
                "birth_time_s": format(birth_us * 1e-6, ".17g"),
                "x_mm": format(transverse_2_mm, ".17g"),
                "y_mm": format(-transverse_1_mm, ".17g"),
                "z_mm": format(release_z_mm, ".17g"),
                "vx_m_s": format(-speed_m_s * transverse_1_fraction, ".17g"),
                "vy_m_s": format(-speed_m_s * transverse_2_fraction, ".17g"),
                "vz_m_s": format(speed_m_s * axial_fraction, ".17g"),
                "mass_amu": format(mass_amu, ".17g"),
                "charge_state": str(int(charge_state)),
            }
        )
    return rows


def write_canonical(
    output: Path, count: int, resolved_design_path: Path
) -> None:
    resolved = json.loads(resolved_design_path.read_text(encoding="utf-8-sig"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(generate_canonical(count, resolved))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path)
    parser.add_argument("--check-canonical", type=Path)
    parser.add_argument("--resolved-design", type=Path)
    parser.add_argument("--particles", type=int, choices=STANDARD_COUNTS, default=100)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--canonical-output", type=Path)
    args = parser.parse_args()
    generated = generate(args.particles)
    if args.check:
        current = np.loadtxt(args.check, delimiter=",")
        if current.shape != generated.shape or not np.allclose(current, generated, atol=5e-10, rtol=0):
            raise SystemExit("fixed particle table does not match seed/distribution contract")
    elif args.output or not args.canonical_output:
        output = args.output or Path(f"official_fixed_{args.particles}.ion")
        output.parent.mkdir(parents=True, exist_ok=True)
        np.savetxt(output, generated, delimiter=",", fmt="%.12g")
    if args.check_canonical or args.canonical_output:
        if args.resolved_design is None:
            parser.error("--resolved-design is required for canonical output or check")
        target = args.check_canonical or args.canonical_output
        expected = generate_canonical(
            args.particles,
            json.loads(args.resolved_design.read_text(encoding="utf-8-sig")),
        )
        if args.check_canonical:
            with args.check_canonical.open(encoding="ascii", newline="") as handle:
                current = list(csv.DictReader(handle))
            if current != expected:
                raise SystemExit("canonical particle table differs from governed source")
        else:
            write_canonical(target, args.particles, args.resolved_design)
    if args.check or args.check_canonical:
        print("STATUS=PASS")


if __name__ == "__main__":
    main()
