"""Generate a deterministic paired particle table for a named operating point."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-family", type=Path, required=True)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--operating-point", required=True)
    parser.add_argument("--particles", type=int, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    if args.particles <= 0:
        raise ValueError("particle count must be positive")

    family = json.loads(args.source_family.read_text(encoding="utf-8"))
    distribution = json.loads(args.distribution.read_text(encoding="utf-8"))
    point = family["operating_points"][args.operating_point]
    seed = args.seed if args.seed is not None else int(family["paired_sampling"]["base_seed"]) + args.particles
    rng = np.random.default_rng(seed)
    n = args.particles
    birth_contract = distribution["time_of_birth_us"]
    position = distribution["position_mm"]
    direction = distribution["direction"]
    birth = rng.uniform(birth_contract["min"], birth_contract["max"], n)
    transverse_1 = rng.uniform(position["transverse_1"]["min"], position["transverse_1"]["max"], n)
    transverse_2 = rng.uniform(position["transverse_2"]["min"], position["transverse_2"]["max"], n)
    energy_contract = point["kinetic_energy_eV"]
    # Consume one energy quantile for every operating point so fixed- and
    # distributed-energy tables remain particle-wise paired downstream.
    energy_quantile = rng.random(n)
    if energy_contract["distribution"] == "uniform":
        energy = energy_contract["min"] + (energy_contract["max"] - energy_contract["min"]) * energy_quantile
    elif energy_contract["distribution"] == "fixed":
        energy = np.full(n, energy_contract["value"])
    else:
        raise ValueError(f"unsupported energy distribution: {energy_contract['distribution']}")
    phi = rng.uniform(0.0, 2.0 * np.pi, n)
    half_angle = np.deg2rad(direction["half_angle_deg"])
    theta = np.arccos(rng.uniform(np.cos(half_angle), 1.0, n))
    v_axial = np.cos(theta)
    v_transverse_1 = np.sin(theta) * np.cos(phi)
    v_transverse_2 = np.sin(theta) * np.sin(phi)
    azimuth = np.rad2deg(np.arctan2(v_transverse_1, v_axial))
    elevation = np.rad2deg(np.arcsin(v_transverse_2))
    table = np.column_stack([
        birth, np.full(n, point["mass_amu"]), np.full(n, point["charge_state"]),
        np.full(n, position["axial"]), transverse_1, transverse_2,
        azimuth, elevation, energy, np.full(n, distribution["cwf"]), np.full(n, distribution["color"]),
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(args.output, table, delimiter=",", fmt="%.12g")
    metadata = {
        "schema_version": 1,
        "role": "rf_quadrupole_fixed_paired_particle_table",
        "operating_point": args.operating_point,
        "particles": n,
        "seed": seed,
        "mass_amu": point["mass_amu"],
        "charge_state": point["charge_state"],
        "source_family_sha256": sha256(args.source_family),
        "distribution_sha256": sha256(args.distribution),
        "particle_table": str(args.output.resolve()),
        "particle_table_sha256": sha256(args.output),
    }
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"STATUS=PASS PARTICLES={n} OPERATING_POINT={args.operating_point} SHA256={metadata['particle_table_sha256']}")


if __name__ == "__main__":
    main()
