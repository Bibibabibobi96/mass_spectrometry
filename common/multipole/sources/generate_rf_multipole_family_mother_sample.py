"""Build deterministic nested N=100/N=1000/N=5000 RF-multipole sources."""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

from common.contracts.file_identity import file_sha256 as sha256
from common.ion_release.mt19937_disk_cone_rf_phase import (
    STRATEGY,
)
from common.ion_release.release import generate_release_states


SEED = 2026072801
PREFIX_COUNT = 100
TOTAL_COUNT = 1000
HIGH_STATISTICAL_COUNT = 5000
RF_FREQUENCY_HZ = 1_100_000.0
SOURCE_RADIUS_MM = 0.5
MAX_DIVERGENCE_DEG = 5.0
SOURCE_Z_MM = -1.5
MASS_AMU = 100.0
CHARGE_STATE = 1
KINETIC_ENERGY_EV = 2.0
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


def generate_rows(seed: int, total_count: int) -> list[dict[str, object]]:
    """Return the legacy family rows through the repository release registry API.

    The historical CSV records use Python ``repr`` strings.  Keeping that
    conversion here preserves the frozen tables while the sampling algorithm
    itself is owned by :mod:`common.ion_release`.
    """
    if total_count < 1:
        raise ValueError("particle count must be positive")
    spec = {
        "schema_version": 1,
        "role": "repository_ion_release",
        "frame_id": "rf_multipole_source_local_cartesian_v1",
        "particle_count": total_count,
        "mother_particle_count": total_count,
        "geometry": {
            "shape": "disk",
            "center_mm": [0.0, 0.0, SOURCE_Z_MM],
            "radius_mm": SOURCE_RADIUS_MM,
        },
        "species": {"mass_amu": MASS_AMU, "charge_state": CHARGE_STATE},
        "sampling": {
            "strategy": STRATEGY,
            "seed": seed,
            "rf_frequency_hz": RF_FREQUENCY_HZ,
            "kinetic_energy_ev": KINETIC_ENERGY_EV,
            "cone_half_angle_deg": MAX_DIVERGENCE_DEG,
        },
    }
    text_fields = (
        "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s",
        "vz_m_s", "mass_amu",
    )
    return [
        {
            "particle_id": state["particle_id"],
            **{field: repr(state[field]) for field in text_fields},
            "charge_state": state["charge_state"],
        }
        for state in generate_release_states(spec)
    ]


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
    n5000_path: Path | None = None,
) -> None:
    sample = generate_rows(SEED, HIGH_STATISTICAL_COUNT)
    n100_path.parent.mkdir(parents=True, exist_ok=True)
    n1000_path.parent.mkdir(parents=True, exist_ok=True)
    n100_path.write_bytes(_render(sample[:PREFIX_COUNT]))
    n1000_path.write_bytes(_render(sample[:TOTAL_COUNT]))
    if n5000_path is not None:
        n5000_path.parent.mkdir(parents=True, exist_ok=True)
        n5000_path.write_bytes(_render(sample))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-n100", type=Path)
    parser.add_argument("--output-n1000", type=Path)
    parser.add_argument("--output-n5000", type=Path)
    parser.add_argument("--output-sample", type=Path,
                        help="Write one independently seeded canonical source sample.")
    parser.add_argument("--sample-count", type=int,
                        help="Particle count used with --output-sample.")
    parser.add_argument("--seed", type=int, default=SEED,
                        help="MT19937 seed; the default rebuilds the v1 family.")
    args = parser.parse_args()
    if args.output_sample is not None:
        if args.sample_count is None or args.sample_count < 1:
            parser.error("--output-sample requires a positive --sample-count")
        if any((args.output_n100, args.output_n1000, args.output_n5000)):
            parser.error("--output-sample cannot be combined with family rebuild outputs")
        args.output_sample.parent.mkdir(parents=True, exist_ok=True)
        args.output_sample.write_bytes(_render(generate_rows(args.seed, args.sample_count)))
        print(
            "RF_MULTIPOLE_INDEPENDENT_MOTHER_SAMPLE=PASS "
            f"SEED={args.seed} COUNT={args.sample_count} "
            f"SHA256={sha256(args.output_sample)}"
        )
        return 0
    if args.seed != SEED:
        parser.error("--seed is only valid with --output-sample")
    if args.output_n100 is None or args.output_n1000 is None:
        parser.error("family rebuild requires --output-n100 and --output-n1000")
    build(
        args.output_n100, args.output_n1000, args.output_n5000,
    )
    print(
        "RF_MULTIPOLE_FAMILY_MOTHER_SAMPLE=PASS "
        f"N100_SHA256={sha256(args.output_n100)} "
        f"N1000_SHA256={sha256(args.output_n1000)}"
        + (f" N5000_SHA256={sha256(args.output_n5000)}" if args.output_n5000 is not None else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
