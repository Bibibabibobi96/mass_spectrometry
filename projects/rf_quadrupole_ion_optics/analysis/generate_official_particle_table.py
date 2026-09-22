"""Generate the fixed paired realization of the SIMION built-in quad source."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.contracts.particle_count_policy import validate_positive_particle_count
from common.ion_release.numpy_ion11_box import (
    render_numpy_ion11_box_table,
    sample_numpy_ion11_box_latent,
)
from common.multipole.particle_source_preflight import COLUMNS


SEED = 20260716
MASTER_COUNT = 1000


OFFICIAL_SOURCE_PATH = Path(__file__).resolve().parents[1] / "config" / "official_particle_source.json"


def _official_distribution() -> dict[str, Any]:
    """Read the declared source parameters; common owns the sampler itself."""
    source = json.loads(OFFICIAL_SOURCE_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(source, dict):
        raise ValueError("official particle source must be an object")
    return source


def generate(count: int = 100) -> np.ndarray:
    validate_positive_particle_count(count)
    source = _official_distribution()
    latent = sample_numpy_ion11_box_latent(
        distribution=source,
        seed=SEED,
        particle_count=count,
        master_particle_count=MASTER_COUNT,
    )
    energy = source["kinetic_energy_eV"]
    return render_numpy_ion11_box_table(
        latent=latent,
        mass_amu=float(source["mass_amu"]),
        charge_state=int(source["charge_state"]),
        axial_mm=float(source["position_mm"]["axial"]),
        energy_min_ev=float(energy["min"]),
        energy_max_ev=float(energy["max"]),
        cwf=float(source["cwf"]),
        color=float(source["color"]),
    )


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
    parser.add_argument("--particles", type=int, default=100)
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
