"""Prepare compact, paired single-mass particle tables for a COMSOL scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.multipole.paired_mass_scan import generate_paired_case_tables


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mode", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    mode = json.loads(args.mode.read_text(encoding="utf-8"))
    screen = mode["solver_screen"]
    cases = generate_paired_case_tables(
        args.source,
        args.output_dir,
        screen["paired_source_masses_Th"],
        int(screen["particles_per_mass"]),
    )
    metadata = {
        "schema_version": 1,
        "role": "rf_quadrupole_comsol_paired_mass_cases",
        "pairing": "every mass uses the same source rows in the same order",
        "cases": cases,
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"COMSOL_MASS_CASES=PASS CASES={len(cases)}")


if __name__ == "__main__":
    main()
