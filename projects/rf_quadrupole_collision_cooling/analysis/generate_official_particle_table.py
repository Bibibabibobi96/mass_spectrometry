"""Generate the fixed paired realization of the SIMION built-in quad source."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from common.contracts.particle_count_policy import validate_standard_particle_count


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path)
    parser.add_argument("--particles", type=int, choices=STANDARD_COUNTS, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    generated = generate(args.particles)
    if args.check:
        current = np.loadtxt(args.check, delimiter=",")
        if current.shape != generated.shape or not np.allclose(current, generated, atol=5e-10, rtol=0):
            raise SystemExit("fixed particle table does not match seed/distribution contract")
        print("STATUS=PASS")
        return
    output = args.output or Path(f"official_fixed_{args.particles}.ion")
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(output, generated, delimiter=",", fmt="%.12g")


if __name__ == "__main__":
    main()
