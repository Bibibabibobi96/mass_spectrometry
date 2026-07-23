"""Publish RF-quadrupole profiles through the common multipole compiler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.multipole.compile_design_request import (
    compile_governed_design_request_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
CONFIG = PROJECT_ROOT / "config"
BASELINE = CONFIG / "requests" / "baseline.json"
PROFILES = {
    "official": {
        "request": CONFIG / "requests" / "official.json",
        "design_variables": CONFIG / "design_variables_nonsegmented.json",
        "optimization_envelope": CONFIG / "optimization_envelope_official.json",
        "output": CONFIG / "resolved_design_official.json",
    },
    "interface": {
        "request": CONFIG / "requests" / "official.json",
        "design_variables": CONFIG / "design_variables_nonsegmented.json",
        "optimization_envelope": CONFIG / "optimization_envelope_official.json",
        "output": CONFIG / "resolved_design_official.json",
    },
    "mass_filter": {
        "request": CONFIG / "requests" / "mass_filter.json",
        "design_variables": CONFIG / "design_variables_nonsegmented.json",
        "optimization_envelope": CONFIG / "optimization_envelope_mass_filter.json",
        "output": CONFIG / "resolved_design_mass_filter.json",
    },
}
EXPECTED_IDENTITY = {
    "project_id": "rf_quadrupole_collision_cooling",
    "family_id": "rf_multipole_ion_optics",
    "radial_order_n": 2,
    "electrode_count": 4,
}


def resolve(profile: str) -> dict:
    """Compile one named full request through the common compiler."""
    selected = PROFILES[profile]
    return compile_governed_design_request_file(
        selected["request"],
        selected["design_variables"],
        selected["optimization_envelope"],
        expected_identity=EXPECTED_IDENTITY,
        provenance_root=REPOSITORY_ROOT,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, default="official")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--write", action="store_true")
    args = parser.parse_args()
    output = PROFILES[args.profile]["output"]
    expected = json.dumps(
        resolve(args.profile), indent=2, ensure_ascii=False, allow_nan=False
    ) + "\n"
    current = output.read_text(encoding="utf-8") if output.exists() else ""
    if current != expected:
        if args.check:
            raise SystemExit(f"STALE={output.relative_to(PROJECT_ROOT).as_posix()}")
        output.write_text(expected, encoding="utf-8", newline="\n")
        print(f"UPDATED={output.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"RESOLVED_DESIGN=PASS PROFILE={args.profile}")


if __name__ == "__main__":
    main()
