"""Publish and check explicit multipole structures through the common compiler."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
import tempfile

from common.contracts.file_identity import file_sha256 as _sha256
from common.contracts.machine_contracts import validate_schema
from projects.rf_multipole_ion_optics.core.compile_design_request import (
    compile_governed_design_request_file,
)
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.core.component_port import build_exit_component_port
from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
CONFIG = PROJECT_ROOT / "variants" / "quadrupole" / "config"
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
    "project_id": "rf_multipole_ion_optics",
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


def publish_ports() -> None:
    """Rebuild each provided port from its own published resolved authority."""
    for variant in ("quadrupole", "hexapole", "octupole"):
        config = PROJECT_ROOT / "variants" / variant / "config"
        source = config / "resolved_design_no_acceleration_full_length.json"
        name = "rf_multipole_exit_no_acceleration_full_length.json" if variant == "quadrupole" else "rf_multipole_exit.json"
        port = build_exit_component_port(
            _load(source), design_profile_id=f"{variant}_no_acceleration_full_length",
            authority_path=source.relative_to(REPOSITORY_ROOT).as_posix(),
            authority_sha256=_sha256(source),
        )
        _atomic_write_json(config / "interfaces" / "provided" / name, port)
    source = CONFIG / "resolved_design_official.json"
    port = build_exit_component_port(
        _load(source), design_profile_id="quadrupole_official_transport",
        authority_path=source.relative_to(REPOSITORY_ROOT).as_posix(),
        authority_sha256=_sha256(source),
    )
    port["profile_scope"] = {
        "scope_id": "official_transport_oatof_oracle",
        "scope_kind": "integration_oracle",
        "family_experiment_port": False,
    }
    _atomic_write_json(CONFIG / "interfaces" / "provided" / "rf_multipole_exit.json", port)


def publish_governance() -> None:
    """Refresh source identities and tracked publications, not qualify every profile.

    Unpublished legacy references may deliberately fail compilation; independent
    migration tests retain those failures without blocking valid publications.
    """
    profiles_path = PROJECT_ROOT / "config" / "design_profiles.json"
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
    profiles["operating_mode_registry_sha256"] = _sha256(
        PROJECT_ROOT / profiles["operating_mode_registry"]
    )
    validate_schema(profiles, "design_profiles.schema.json")
    _atomic_write_json(profiles_path, profiles)
    print(f"UPDATED={profiles_path.relative_to(PROJECT_ROOT).as_posix()}")

    publications: dict[Path, dict] = {}
    for profile_name in PROFILES:
        selected = PROFILES[profile_name]
        publications[selected["output"]] = resolve(profile_name)
    for output, document in publications.items():
        _atomic_write_json(output, document)
        print(f"UPDATED={output.relative_to(PROJECT_ROOT).as_posix()}")
    for variant in ("quadrupole", "hexapole", "octupole"):
        resolution = resolve_design_profile(
            REPOSITORY_ROOT, EXPECTED_IDENTITY["project_id"],
            f"{variant}_no_acceleration_full_length",
        )
        output = PROJECT_ROOT / "variants" / variant / "config" / "resolved_design_no_acceleration_full_length.json"
        _atomic_write_json(output, resolution["resolved_design"])
    publish_ports()
    publish_budget_design_bindings()
    print("DESIGN_GOVERNANCE_PUBLICATION=PASS")


def publish_budget_design_bindings() -> None:
    """Rebind author budgets using the runner's frozen input names and compiler."""
    names = {
        "design_request": "multipole_design_request.json",
        "design_variables": "design_variables.json",
        "optimization_envelope": "optimization_envelope.json",
        "operating_mode_registry": "operating_modes.json",
    }
    for path in sorted((PROJECT_ROOT / "variants").glob("*/config/**/*budget*.json")):
        document = _load(path)
        scope = document.get("pilot_authorization", {}).get("scope", {})
        if "expected_run_parent_resolved_design_sha256" not in scope:
            continue
        selection = resolve_design_profile(REPOSITORY_ROOT, EXPECTED_IDENTITY["project_id"], scope["design_profile_id"])
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory)
            for key, source in selection["paths"].items():
                shutil.copyfile(source, frozen / names[key])
            resolved = compile_governed_design_request_file(
                frozen / names["design_request"], frozen / names["design_variables"],
                frozen / names["optimization_envelope"],
                expected_identity=selection["profile"]["identity"], provenance_root=frozen,
                operating_mode_registry_path=frozen / names["operating_mode_registry"],
                mode_id=selection["profile"]["mode_id"], repository_text_sources=False,
            )
        scope["expected_run_parent_resolved_design_sha256"] = resolved["resolved_sha256"]
        _atomic_write_json(path, document)
        print(f"UPDATED={path.relative_to(PROJECT_ROOT).as_posix()}")


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


def check_variant(variant: str) -> None:
    """Check the selected structure's published design, port and runtime binding."""
    profile_id = f"{variant}_no_acceleration_full_length"
    selection = resolve_design_profile(REPOSITORY_ROOT, EXPECTED_IDENTITY["project_id"], profile_id)
    config = PROJECT_ROOT / "variants" / variant / "config"
    source = config / "resolved_design_no_acceleration_full_length.json"
    if source.read_bytes() != _json_bytes(selection["resolved_design"]):
        raise SystemExit(f"STALE={source.relative_to(PROJECT_ROOT).as_posix()}")
    name = "rf_multipole_exit_no_acceleration_full_length.json" if variant == "quadrupole" else "rf_multipole_exit.json"
    port_path = config / "interfaces" / "provided" / name
    port = build_exit_component_port(
        selection["resolved_design"], design_profile_id=profile_id,
        authority_path=source.relative_to(REPOSITORY_ROOT).as_posix(),
        authority_sha256=_sha256(source),
    )
    if _load(port_path) != port:
        raise SystemExit(f"STALE={port_path.relative_to(PROJECT_ROOT).as_posix()}")
    resolve_runtime_profile(REPOSITORY_ROOT, EXPECTED_IDENTITY["project_id"], profile_id)
    print(f"VARIANT_PUBLICATION=PASS STRUCTURAL_VARIANT={variant}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, default="official")
    parser.add_argument("--structural-variant", choices=("quadrupole", "hexapole", "octupole"))
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--write", action="store_true")
    choice.add_argument("--publish-governance", action="store_true")
    args = parser.parse_args()
    if args.structural_variant:
        if not args.check:
            parser.error("--structural-variant requires --check; use --publish-governance to rebuild publications")
        check_variant(args.structural_variant)
        return
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
