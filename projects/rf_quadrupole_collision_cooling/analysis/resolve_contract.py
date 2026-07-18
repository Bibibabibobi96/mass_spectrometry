"""Resolve immutable official and candidate interface-readiness contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config"
BASELINE = CONFIG / "baseline.json"
PROFILES = {
    "official": {
        "mode": CONFIG / "modes" / "transport_no_collision.json",
        "source": CONFIG / "official_particle_source.json",
        "output": CONFIG / "resolved_geometry.json",
    },
    "interface": {
        "mode": CONFIG / "modes" / "transport_interface_readiness.json",
        "source": CONFIG / "interface_readiness_particle_source.json",
        "interface": CONFIG / "interface_contract.json",
        "output": CONFIG / "resolved_interface_readiness.json",
    },
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def resolve(profile: str) -> dict:
    selected = PROFILES[profile]
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    mode_path = selected["mode"]
    source_path = selected["source"]
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    geometry = baseline["geometry_mm"]
    if abs(geometry["rod_radius"] - geometry["field_radius_r0"] * geometry["rod_radius_ratio"]) > 1e-12:
        raise ValueError("rod radius derivation mismatch")
    if abs(geometry["rod_length"] - (geometry["rod_z_max"] - geometry["rod_z_min"])) > 1e-12:
        raise ValueError("rod length derivation mismatch")
    inputs = {
        "baseline": relative(BASELINE), "baseline_sha256": digest(BASELINE),
        "mode": relative(mode_path), "mode_sha256": digest(mode_path),
        "particle_source": relative(source_path), "particle_source_sha256": digest(source_path),
    }
    resolved = {
        "schema_version": 1,
        "role": f"rf_quadrupole_resolved_{profile}_contract_do_not_edit",
        "inputs": inputs,
        "coordinate_convention": baseline["coordinate_convention"],
        "geometry_mm": geometry,
        "mode": mode,
        "particle_source": source,
    }
    if "interface" in selected:
        interface_path = selected["interface"]
        resolved["inputs"]["interface_contract"] = relative(interface_path)
        resolved["inputs"]["interface_contract_sha256"] = digest(interface_path)
        resolved["interface_contract"] = json.loads(interface_path.read_text(encoding="utf-8"))
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, default="official")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--write", action="store_true")
    args = parser.parse_args()
    output = PROFILES[args.profile]["output"]
    expected = json.dumps(resolve(args.profile), indent=2, ensure_ascii=False) + "\n"
    current = output.read_text(encoding="utf-8") if output.exists() else ""
    if current != expected:
        if args.check:
            raise SystemExit(f"STALE={relative(output)}")
        output.write_text(expected, encoding="utf-8", newline="\n")
        print(f"UPDATED={relative(output)}")
    print(f"RESOLVED_CONTRACT=PASS PROFILE={args.profile}")


if __name__ == "__main__":
    main()
