"""Generate deterministic oa-TOF SIMION ION sources in Python."""

from __future__ import annotations

import argparse
import math
from pathlib import Path


class DotNetFrameworkRandom:
    """Reproduce the seeded System.Random sequence used by the legacy generator."""

    MBIG = 2_147_483_647
    MSEED = 161_803_398

    def __init__(self, seed: int) -> None:
        subtraction = self.MBIG if seed == -2_147_483_648 else abs(seed)
        mj = self.MSEED - subtraction
        if mj < 0:
            mj += self.MBIG
        self._seed_array = [0] * 56
        self._seed_array[55] = mj
        mk = 1
        for index in range(1, 55):
            position = (21 * index) % 55
            self._seed_array[position] = mk
            mk = mj - mk
            if mk < 0:
                mk += self.MBIG
            mj = self._seed_array[position]
        for _ in range(4):
            for index in range(1, 56):
                self._seed_array[index] -= self._seed_array[1 + (index + 30) % 55]
                if self._seed_array[index] < 0:
                    self._seed_array[index] += self.MBIG
        self._inext = 0
        self._inextp = 21

    def next_double(self) -> float:
        self._inext += 1
        if self._inext >= 56:
            self._inext = 1
        self._inextp += 1
        if self._inextp >= 56:
            self._inextp = 1
        value = self._seed_array[self._inext] - self._seed_array[self._inextp]
        if value == self.MBIG:
            value -= 1
        if value < 0:
            value += self.MBIG
        self._seed_array[self._inext] = value
        return value / self.MBIG


def _dotnet_e8(value: float) -> str:
    mantissa, exponent = f"{value:.8E}".split("E")
    return f"{mantissa}E{int(exponent):+04d}"


def generate_ion_source(
    *,
    particle_count: int,
    mass_amu: float,
    charge: int,
    energy_mean_ev: float,
    energy_std_ev: float,
    half_width_xyz_mm: tuple[float, float, float],
    center_xyz_mm: tuple[float, float, float],
    seed: int,
) -> list[str]:
    if particle_count <= 0 or mass_amu <= 0 or charge == 0:
        raise ValueError("Particle count, mass, and charge must be physically valid")
    if energy_mean_ev <= 0 or energy_std_ev < 0:
        raise ValueError("Energy mean must be positive and sigma nonnegative")
    if min(half_width_xyz_mm) < 0:
        raise ValueError("Source half-widths must be nonnegative")
    random = DotNetFrameworkRandom(seed)
    lines: list[str] = []
    for _ in range(particle_count):
        position = [
            center + (2.0 * random.next_double() - 1.0) * half_width
            for center, half_width in zip(center_xyz_mm, half_width_xyz_mm)
        ]
        energy = -1.0
        while energy <= 0:
            u1 = max(random.next_double(), 1.0e-15)
            u2 = random.next_double()
            normal = math.sqrt(-2.0 * math.log(u1)) * math.cos(
                2.0 * math.pi * u2
            )
            energy = energy_mean_ev + energy_std_ev * normal
        lines.append(
            "0,"
            f"{_dotnet_e8(mass_amu)},{charge},"
            f"{_dotnet_e8(position[0])},{_dotnet_e8(position[1])},"
            f"{_dotnet_e8(position[2])},0,0,{_dotnet_e8(energy)},1,0"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--particle-count", type=int, default=100)
    parser.add_argument("--mass-amu", type=float, default=524)
    parser.add_argument("--charge", type=int, default=1)
    parser.add_argument("--energy-mean-ev", type=float, default=5)
    parser.add_argument("--energy-std-ev", type=float, default=0.4)
    parser.add_argument("--half-width-mm", type=float, default=0.5)
    parser.add_argument("--half-width-x-mm", type=float)
    parser.add_argument("--half-width-y-mm", type=float)
    parser.add_argument("--half-width-z-mm", type=float)
    parser.add_argument("--center-x-mm", type=float, default=-48.8)
    parser.add_argument("--center-y-mm", type=float, default=0.0)
    parser.add_argument("--center-z-mm", type=float, default=-18.42918680341103)
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-nonstandard-diagnostic-count", action="store_true")
    args = parser.parse_args()
    if (
        args.particle_count not in (100, 1000)
        and not args.allow_nonstandard_diagnostic_count
    ):
        raise ValueError(
            "Standard particle count must be N=100 or N=1000; "
            "use the explicit diagnostic override otherwise"
        )
    half_widths = tuple(
        args.half_width_mm if value is None else value
        for value in (
            args.half_width_x_mm,
            args.half_width_y_mm,
            args.half_width_z_mm,
        )
    )
    lines = generate_ion_source(
        particle_count=args.particle_count,
        mass_amu=args.mass_amu,
        charge=args.charge,
        energy_mean_ev=args.energy_mean_ev,
        energy_std_ev=args.energy_std_ev,
        half_width_xyz_mm=half_widths,
        center_xyz_mm=(args.center_x_mm, args.center_y_mm, args.center_z_mm),
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
    print(
        f"generated={args.output.resolve()} N={args.particle_count} "
        f"mass_amu={args.mass_amu} charge={args.charge} seed={args.seed}"
    )


if __name__ == "__main__":
    main()
