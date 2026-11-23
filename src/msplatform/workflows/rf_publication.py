"""Compile, check and author explicit multipole publications from supplied roots."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from msplatform.io.file_identity import repository_text_sha256 as _sha256
from msplatform.contracts.machine_contracts import validate_schema
from msplatform.components.rf_multipole.design_request_files import (
    compile_governed_design_request_file,
)
from msplatform.workflows.rf_design_profiles import resolve_design_profile
from msplatform.workflows.rf_runtime_profiles import resolve_runtime_profile


PROFILE_RESOURCES = {
    "official": {
        "request": "src/msplatform/components/rf_multipole/variants/quadrupole/config/requests/official.json",
        "design_variables": "src/msplatform/components/rf_multipole/variants/quadrupole/config/design_variables_nonsegmented.json",
        "optimization_envelope": "src/msplatform/components/rf_multipole/variants/quadrupole/config/optimization_envelope_official.json",
        "output": "src/msplatform/components/rf_multipole/variants/quadrupole/config/resolved_design_official.json",
    },
    "interface": {
        "request": "src/msplatform/components/rf_multipole/variants/quadrupole/config/requests/official.json",
        "design_variables": "src/msplatform/components/rf_multipole/variants/quadrupole/config/design_variables_nonsegmented.json",
        "optimization_envelope": "src/msplatform/components/rf_multipole/variants/quadrupole/config/optimization_envelope_official.json",
        "output": "src/msplatform/components/rf_multipole/variants/quadrupole/config/resolved_design_official.json",
    },
    "mass_filter": {
        "request": "src/msplatform/components/rf_multipole/variants/quadrupole/config/requests/mass_filter.json",
        "design_variables": "src/msplatform/components/rf_multipole/variants/quadrupole/config/design_variables_nonsegmented.json",
        "optimization_envelope": "src/msplatform/components/rf_multipole/variants/quadrupole/config/optimization_envelope_mass_filter.json",
        "output": "src/msplatform/components/rf_multipole/variants/quadrupole/config/resolved_design_mass_filter.json",
    },
}
EXPECTED_IDENTITY = {
    "project_id": "rf_multipole_ion_optics",
    "family_id": "rf_multipole_ion_optics",
    "radial_order_n": 2,
    "electrode_count": 4,
}


def profile_paths(project_root: Path) -> dict[str, dict[str, Path]]:
    """Resolve the named research inputs beneath an explicit project root."""
    prefix = Path("src/msplatform/components/rf_multipole")
    return {
        name: {key: project_root / Path(value).relative_to(prefix) for key, value in resources.items()}
        for name, resources in PROFILE_RESOURCES.items()
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


def resolve(
    profile: str, *, project_root: Path, repository_root: Path,
    profiles: dict[str, dict[str, Path]] | None = None,
) -> dict:
    """Compile one named full request through the canonical component compiler."""
    selected = (profiles or profile_paths(project_root))[profile]
    return compile_governed_design_request_file(
        selected["request"],
        selected["design_variables"],
        selected["optimization_envelope"],
        expected_identity=EXPECTED_IDENTITY,
        provenance_root=repository_root,
    )


def check_variant(variant: str, *, project_root: Path, repository_root: Path) -> None:
    """Check the selected structure's published design and runtime binding."""
    profile_id = f"{variant}_no_acceleration_full_length"
    selection = resolve_design_profile(repository_root, EXPECTED_IDENTITY["project_id"], profile_id)
    config = project_root / "variants" / variant / "config"
    source = config / "resolved_design_no_acceleration_full_length.json"
    if source.read_bytes() != _json_bytes(selection["resolved_design"]):
        raise SystemExit(f"STALE={source.relative_to(project_root).as_posix()}")
    resolve_runtime_profile(repository_root, EXPECTED_IDENTITY["project_id"], profile_id)
    print(f"VARIANT_PUBLICATION=PASS STRUCTURAL_VARIANT={variant}")


def publish_governance(*, project_root: Path, repository_root: Path) -> None:
    """Refresh source identities and tracked publications, not qualify profiles."""
    profiles_path = project_root / "config" / "design_profiles.json"
    profiles = _load(profiles_path)
    envelope_paths = {project_root / "variants/quadrupole/config/optimization_envelope.json"}
    for profile in profiles["profiles"]:
        envelope_paths.add(project_root / profile["optimization_envelope"])

    updated_envelopes: dict[Path, dict] = {}
    for envelope_path in sorted(envelope_paths):
        envelope = _load(envelope_path)
        request_path = project_root / envelope["reference"]["design_request"]
        envelope["reference"]["design_request_sha256"] = _sha256(request_path)
        validate_schema(envelope, "optimization_envelope.schema.json")
        updated_envelopes[envelope_path] = envelope

    for envelope_path, envelope in updated_envelopes.items():
        _atomic_write_json(envelope_path, envelope)
        print(f"UPDATED={envelope_path.relative_to(project_root).as_posix()}")

    for profile in profiles["profiles"]:
        sources = {
            "design_request": project_root / profile["design_request"],
            "design_variables": project_root / profile["design_variables"],
            "optimization_envelope": project_root / profile["optimization_envelope"],
        }
        profile["sha256"] = {label: _sha256(path) for label, path in sources.items()}
    profiles["operating_mode_registry_sha256"] = _sha256(
        project_root / profiles["operating_mode_registry"]
    )
    validate_schema(profiles, "design_profiles.schema.json")
    _atomic_write_json(profiles_path, profiles)
    print(f"UPDATED={profiles_path.relative_to(project_root).as_posix()}")

    selected_profiles = profile_paths(project_root)
    publications = {
        selected["output"]: resolve(
            profile_name, project_root=project_root, repository_root=repository_root,
            profiles=selected_profiles,
        )
        for profile_name, selected in selected_profiles.items()
    }
    for output, document in publications.items():
        _atomic_write_json(output, document)
        print(f"UPDATED={output.relative_to(project_root).as_posix()}")
    for variant in ("quadrupole", "hexapole", "octupole"):
        resolution = resolve_design_profile(
            repository_root, EXPECTED_IDENTITY["project_id"],
            f"{variant}_no_acceleration_full_length",
        )
        output = project_root / "variants" / variant / "config" / "resolved_design_no_acceleration_full_length.json"
        _atomic_write_json(output, resolution["resolved_design"])
    publish_budget_design_bindings(project_root=project_root, repository_root=repository_root)
    print("DESIGN_GOVERNANCE_PUBLICATION=PASS")


def publish_budget_design_bindings(*, project_root: Path, repository_root: Path) -> None:
    """Rebind author budgets using the runner's frozen input names and compiler."""
    names = {
        "design_request": "multipole_design_request.json",
        "design_variables": "design_variables.json",
        "optimization_envelope": "optimization_envelope.json",
        "operating_mode_registry": "operating_modes.json",
    }
    registry = _load(project_root / "config/runtime_profiles.json")
    active_budgets = {project_root / row["engineering_budget_path"] for row in registry["profiles"].values()}
    for path in sorted(active_budgets):
        document = _load(path)
        scope = document.get("pilot_authorization", {}).get("scope", {})
        if "expected_run_parent_resolved_design_sha256" not in scope:
            continue
        selection = resolve_design_profile(repository_root, EXPECTED_IDENTITY["project_id"], scope["design_profile_id"])
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
        print(f"UPDATED={path.relative_to(project_root).as_posix()}")


def main(
    *, project_root: Path, repository_root: Path,
    profiles: dict[str, dict[str, Path]] | None = None,
) -> None:
    """Check or author publications using only the supplied research roots."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--profile", choices=PROFILE_RESOURCES, default="official")
    parser.add_argument("--structural-variant", choices=("quadrupole", "hexapole", "octupole"))
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--write", action="store_true")
    choice.add_argument("--publish-governance", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root or project_root
    repository_root = args.repository_root or repository_root
    if args.structural_variant:
        if not args.check:
            parser.error("--structural-variant requires --check; use --publish-governance to rebuild publications")
        check_variant(args.structural_variant, project_root=project_root, repository_root=repository_root)
        return
    if args.publish_governance:
        publish_governance(project_root=project_root, repository_root=repository_root)
        return
    selected_profiles = profiles or profile_paths(project_root)
    output = selected_profiles[args.profile]["output"]
    expected = _json_bytes(resolve(
        args.profile, project_root=project_root, repository_root=repository_root,
        profiles=selected_profiles,
    )).decode("utf-8")
    current = output.read_text(encoding="utf-8") if output.exists() else ""
    if current != expected:
        if args.check:
            raise SystemExit(f"STALE={output.relative_to(project_root).as_posix()}")
        output.write_text(expected, encoding="utf-8", newline="\n")
        print(f"UPDATED={output.relative_to(project_root).as_posix()}")
    print(f"RESOLVED_DESIGN=PASS PROFILE={args.profile}")


if __name__ == "__main__":
    installed_project_root = Path(__file__).resolve().parents[1] / "components" / "rf_multipole"
    installed_repository_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", type=Path, default=installed_project_root)
    parser.add_argument("--repository-root", type=Path, default=installed_repository_root)
    roots, remaining = parser.parse_known_args()
    import sys
    sys.argv = [sys.argv[0], *remaining]
    main(
        project_root=roots.project_root.resolve(),
        repository_root=roots.repository_root.resolve(),
    )
