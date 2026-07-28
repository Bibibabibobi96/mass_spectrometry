"""Build deterministic N=100/N=1000 RF-multipole family particle sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import random
from pathlib import Path


SEED = 2026072801
PREFIX_COUNT = 100
TOTAL_COUNT = 1000
RF_FREQUENCY_HZ = 1_100_000.0
SOURCE_RADIUS_MM = 0.5
MAX_DIVERGENCE_DEG = 5.0
SOURCE_Z_MM = -1.5
MASS_AMU = 100.0
CHARGE_STATE = 1
KINETIC_ENERGY_EV = 2.0
AMU_KG = 1.66053906660e-27
ELEMENTARY_CHARGE_C = 1.602176634e-19
COLUMNS = (
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
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def rows() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    speed_m_s = math.sqrt(
        2.0 * KINETIC_ENERGY_EV * ELEMENTARY_CHARGE_C / (MASS_AMU * AMU_KG)
    )
    cone_cosine = math.cos(math.radians(MAX_DIVERGENCE_DEG))
    rows: list[dict[str, object]] = []
    for particle_id in range(1, TOTAL_COUNT + 1):
        birth_time_s = rng.random() / RF_FREQUENCY_HZ
        radius_mm = SOURCE_RADIUS_MM * math.sqrt(rng.random())
        position_angle = 2.0 * math.pi * rng.random()
        direction_cosine = 1.0 - rng.random() * (1.0 - cone_cosine)
        direction_sine = math.sqrt(1.0 - direction_cosine * direction_cosine)
        direction_angle = 2.0 * math.pi * rng.random()
        rows.append(
            {
                "particle_id": particle_id,
                "birth_time_s": repr(birth_time_s),
                "x_mm": repr(radius_mm * math.cos(position_angle)),
                "y_mm": repr(radius_mm * math.sin(position_angle)),
                "z_mm": repr(SOURCE_Z_MM),
                "vx_m_s": repr(speed_m_s * direction_sine * math.cos(direction_angle)),
                "vy_m_s": repr(speed_m_s * direction_sine * math.sin(direction_angle)),
                "vz_m_s": repr(speed_m_s * direction_cosine),
                "mass_amu": repr(MASS_AMU),
                "charge_state": CHARGE_STATE,
            }
        )
    return rows


def _render(selected: list[dict[str, object]]) -> bytes:
    with io.StringIO(newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(selected)
        return stream.getvalue().encode("utf-8")


def build(n100_path: Path, n1000_path: Path) -> None:
    sample = rows()
    n100_path.parent.mkdir(parents=True, exist_ok=True)
    n1000_path.parent.mkdir(parents=True, exist_ok=True)
    n100_path.write_bytes(_render(sample[:PREFIX_COUNT]))
    n1000_path.write_bytes(_render(sample))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-n100", required=True, type=Path)
    parser.add_argument("--output-n1000", required=True, type=Path)
    args = parser.parse_args()
    build(args.output_n100, args.output_n1000)
    print(
        "RF_MULTIPOLE_FAMILY_MOTHER_SAMPLE=PASS "
        f"N100_SHA256={sha256(args.output_n100)} "
        f"N1000_SHA256={sha256(args.output_n1000)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
