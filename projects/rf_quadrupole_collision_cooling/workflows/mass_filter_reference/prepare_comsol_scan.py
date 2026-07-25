"""Prepare compact, paired single-mass particle tables for a COMSOL scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.multipole.paired_mass_scan import (
    generate_paired_case_tables,
    load_ion_rows,
)


def generate(
    source_path: Path,
    mode_path: Path,
    output_directory: Path,
    metadata_path: Path,
) -> dict:
    """Generate COMSOL cases using the frozen source row count."""
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    scan_spec = mode["mass_scan_spec"]
    particles_per_mass = len(load_ion_rows(source_path))
    cases = generate_paired_case_tables(
        source_path,
        output_directory,
        scan_spec["paired_source_masses_Th"],
        particles_per_mass,
    )
    metadata = {
        "schema_version": 1,
        "role": "rf_quadrupole_comsol_paired_mass_cases",
        "pairing": "every mass uses the same source rows in the same order",
        "particles_per_mass": particles_per_mass,
        "cases": cases,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mode", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    metadata = generate(
        args.source,
        args.mode,
        args.output_dir,
        args.metadata,
    )
    print(f"COMSOL_MASS_CASES=PASS CASES={len(metadata['cases'])}")


if __name__ == "__main__":
    main()
