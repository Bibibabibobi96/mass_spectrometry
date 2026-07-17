"""Resolve the RF-quadrupole design, active mode, and particle source."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE = PROJECT_ROOT / "config" / "baseline.json"
MODE = PROJECT_ROOT / "config" / "modes" / "transport_no_collision.json"
SOURCE = PROJECT_ROOT / "config" / "official_particle_source.json"
OUTPUT = PROJECT_ROOT / "config" / "resolved_geometry.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def resolve() -> dict:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    mode = json.loads(MODE.read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    geometry = baseline["geometry_mm"]
    if abs(geometry["rod_radius"] - geometry["field_radius_r0"] * geometry["rod_radius_ratio"]) > 1e-12:
        raise ValueError("rod radius derivation mismatch")
    if abs(geometry["rod_length"] - (geometry["rod_z_max"] - geometry["rod_z_min"])) > 1e-12:
        raise ValueError("rod length derivation mismatch")
    return {
        "schema_version": 1,
        "role": "rf_quadrupole_resolved_contract_do_not_edit",
        "inputs": {
            "baseline": "config/baseline.json", "baseline_sha256": digest(BASELINE),
            "mode": "config/modes/transport_no_collision.json", "mode_sha256": digest(MODE),
            "particle_source": "config/official_particle_source.json", "particle_source_sha256": digest(SOURCE),
        },
        "coordinate_convention": baseline["coordinate_convention"],
        "geometry_mm": geometry,
        "mode": mode,
        "particle_source": source,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(resolve(), indent=2, ensure_ascii=False) + "\n"
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
    if current != expected:
        if args.check:
            raise SystemExit("STALE=config/resolved_geometry.json")
        OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
        print("UPDATED=config/resolved_geometry.json")
    print("RESOLVED_GEOMETRY=PASS")


if __name__ == "__main__":
    main()
