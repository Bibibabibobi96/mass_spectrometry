"""Publish RF-quadrupole profiles through the common multipole compiler."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from common.contracts.file_identity import file_sha256 as _sha256
from common.contracts.machine_contracts import validate_schema
from common.multipole.compile_design_request import (
    compile_governed_design_request_file,
)
from common.multipole.design_profile import resolve_design_profile


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
    "project_id": "rf_quadrupole_ion_optics",
    "family_id": "rf_multipole_ion_optics",
    "radial_order_n": 2,
    "electrode_count": 4,
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _json_bytes(document: dict) -> bytes:
    return (
        json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def _atomic_write_json(path: Path, document: dict) -> None:
    payload = _json_bytes(document)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=path.parent, prefix=f".{path.name}.tmp."
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def publish_governance() -> None:
    """Refresh governed references, then rebuild tracked resolved publications."""
    profiles_path = CONFIG / "design_profiles.json"
    profiles = _load(profiles_path)
    envelope_paths = {CONFIG / "optimization_envelope.json"}
    for profile in profiles["profiles"]:
        envelope_paths.add(PROJECT_ROOT / profile["optimization_envelope"])

    updated_envelopes: dict[Path, dict] = {}
    for envelope_path in sorted(envelope_paths):
        envelope = _load(envelope_path)
        request_path = PROJECT_ROOT / envelope["reference"]["design_request"]
        envelope["reference"]["design_request_sha256"] = _sha256(request_path)
        validate_schema(envelope, "optimization_envelope.schema.json")
        updated_envelopes[envelope_path] = envelope

    for envelope_path, envelope in updated_envelopes.items():
        _atomic_write_json(envelope_path, envelope)
        print(
            "UPDATED="
            f"{envelope_path.relative_to(PROJECT_ROOT).as_posix()}"
        )

    for profile in profiles["profiles"]:
        sources = {
            "design_request": PROJECT_ROOT / profile["design_request"],
            "design_variables": PROJECT_ROOT / profile["design_variables"],
            "optimization_envelope": PROJECT_ROOT
            / profile["optimization_envelope"],
        }
        profile["sha256"] = {
            label: _sha256(path) for label, path in sources.items()
        }
    validate_schema(profiles, "design_profiles.schema.json")
    _atomic_write_json(profiles_path, profiles)
    print(f"UPDATED={profiles_path.relative_to(PROJECT_ROOT).as_posix()}")

    for profile in profiles["profiles"]:
        resolve_design_profile(
            REPOSITORY_ROOT,
            EXPECTED_IDENTITY["project_id"],
            profile["design_profile_id"],
        )

    publications: dict[Path, dict] = {}
    for profile_name in PROFILES:
        selected = PROFILES[profile_name]
        publications[selected["output"]] = resolve(profile_name)
    for output, document in publications.items():
        _atomic_write_json(output, document)
        print(f"UPDATED={output.relative_to(PROJECT_ROOT).as_posix()}")
    print("DESIGN_GOVERNANCE_PUBLICATION=PASS")


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
    choice.add_argument("--publish-governance", action="store_true")
    args = parser.parse_args()
    if args.publish_governance:
        publish_governance()
        return
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
