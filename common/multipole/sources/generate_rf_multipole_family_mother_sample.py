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
STEADY_CANDIDATE_SEED = 2026081001
STEADY_CANDIDATE_COUNT = 2000
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


def generate_rows(seed: int, total_count: int) -> list[dict[str, object]]:
    if total_count < 1:
        raise ValueError("particle count must be positive")
    rng = random.Random(seed)
    speed_m_s = math.sqrt(
        2.0 * KINETIC_ENERGY_EV * ELEMENTARY_CHARGE_C / (MASS_AMU * AMU_KG)
    )
    cone_cosine = math.cos(math.radians(MAX_DIVERGENCE_DEG))
    rows: list[dict[str, object]] = []
    for particle_id in range(1, total_count + 1):
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


def rows() -> list[dict[str, object]]:
    """Return the frozen family N=1000 mother sample."""
    return generate_rows(SEED, TOTAL_COUNT)


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


def build(
    n100_path: Path,
    n1000_path: Path,
    steady_candidate_path: Path | None = None,
) -> None:
    sample = rows()
    n100_path.parent.mkdir(parents=True, exist_ok=True)
    n1000_path.parent.mkdir(parents=True, exist_ok=True)
    n100_path.write_bytes(_render(sample[:PREFIX_COUNT]))
    n1000_path.write_bytes(_render(sample))
    if steady_candidate_path is not None:
        steady_candidate_path.parent.mkdir(parents=True, exist_ok=True)
        steady_candidate_path.write_bytes(
            _render(generate_rows(STEADY_CANDIDATE_SEED, STEADY_CANDIDATE_COUNT))
        )


def build_steady_batches(directory: Path, batch_count: int = 4) -> list[Path]:
    if STEADY_CANDIDATE_COUNT % batch_count:
        raise ValueError("steady candidate count must divide evenly into batches")
    sample = generate_rows(STEADY_CANDIDATE_SEED, STEADY_CANDIDATE_COUNT)
    size = STEADY_CANDIDATE_COUNT // batch_count
    directory.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for batch_index in range(batch_count):
        selected = sample[batch_index * size : (batch_index + 1) * size]
        selected = [dict(row, particle_id=index) for index, row in enumerate(selected, 1)]
        path = directory / f"rf_multipole_steady_candidate_v1_batch{batch_index + 1:02d}_{size}.csv"
        path.write_bytes(_render(selected))
        outputs.append(path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-n100", required=True, type=Path)
    parser.add_argument("--output-n1000", required=True, type=Path)
    parser.add_argument("--output-steady-candidate", type=Path)
    parser.add_argument("--steady-batch-directory", type=Path)
    args = parser.parse_args()
    build(args.output_n100, args.output_n1000, args.output_steady_candidate)
    batch_paths = (
        build_steady_batches(args.steady_batch_directory)
        if args.steady_batch_directory is not None
        else []
    )
    print(
        "RF_MULTIPOLE_FAMILY_MOTHER_SAMPLE=PASS "
        f"N100_SHA256={sha256(args.output_n100)} "
        f"N1000_SHA256={sha256(args.output_n1000)}"
        + (
            f" STEADY_CANDIDATE_SHA256={sha256(args.output_steady_candidate)}"
            if args.output_steady_candidate is not None
            else ""
        )
        + "".join(f" BATCH{index:02d}_SHA256={sha256(path)}" for index, path in enumerate(batch_paths, 1))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
