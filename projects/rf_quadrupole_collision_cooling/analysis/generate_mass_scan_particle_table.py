"""Build a paired multi-mass SIMION ION table from one authoritative source realization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.multipole.paired_mass_scan import generate_paired_ion_table, sha256, validate_masses


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "config" / "particles" / "official_fixed_25.ion"
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json"


def generate(source_path: Path, mode_path: Path, destination: Path, metadata_path: Path) -> dict:
    """Generate the paired scan table and its identity metadata."""
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    masses = validate_masses(mode["solver_screen"]["paired_source_masses_Th"])
    expected_per_mass = int(mode["solver_screen"]["particles_per_mass"])
    return generate_paired_ion_table(
        source_path,
        destination,
        metadata_path,
        masses,
        expected_per_mass,
        {"mode": str(mode_path.resolve()), "mode_sha256": sha256(mode_path)},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    metadata = generate(args.source, args.mode, args.output, args.metadata)
    print(f"MASS_SCAN_PARTICLES=PASS MASSES={len(metadata['masses_Th'])} PARTICLES={metadata['particles']}")


if __name__ == "__main__":
    main()
