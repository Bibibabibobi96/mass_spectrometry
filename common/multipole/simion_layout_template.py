"""Validate and resolve the registered multipole SIMION layout template."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from common.contracts.artifact_identity_migration import (
    relocated_manifest_path,
    resolve_legacy_artifact_root,
)


EXPECTED_TRANSFORM = {
    "x": 0,
    "y": 0,
    "z": 0,
    "az": -90,
    "el": 0,
    "rt": 180,
    "scale": 1,
}
REPORT_TOKENS = (
    "STATUS=PASS",
    "INSTANCE_COUNT=1",
    "INSTANCE_1_TRANSFORM=0,0,0,-90,0,180,1",
    "PROGRAM_EXECUTED=false",
    "PARTICLE_FLY_EXECUTED=false",
)


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def resolve_simion_layout_template(
    repo_root: Path, registry_path: Path | None = None
) -> dict:
    """Return IOB+CON from one successful, GUI-approved registration run."""
    repo_root = repo_root.resolve()
    registry_path = (
        registry_path.resolve()
        if registry_path
        else repo_root / "common/multipole/simion_layout_template.json"
    )
    registry = _load(registry_path)
    expected_keys = {
        "schema_version",
        "role",
        "template_id",
        "provider_project_id",
        "legacy_evidence_identity",
        "registration_run_id",
        "run_manifest_sha256",
        "iob_sha256",
        "con_sha256",
        "manual_gui_review",
    }
    if set(registry) != expected_keys:
        raise ValueError("template binding keys differ")
    if (
        registry["schema_version"] != 1
        or registry["role"] != "multipole_simion_layout_template_binding"
    ):
        raise ValueError("template binding identity differs")
    provider = registry["provider_project_id"]
    evidence_identity = registry["legacy_evidence_identity"]
    expected_evidence_keys = {
        "mapping_id",
        "recorded_project_id",
        "artifact_access",
    }
    if (
        not isinstance(evidence_identity, dict)
        or set(evidence_identity) != expected_evidence_keys
        or evidence_identity["mapping_id"] != "rf_quad_rename_20260728"
        or evidence_identity["recorded_project_id"]
        != "rf_quadrupole_collision_cooling"
        or evidence_identity["artifact_access"] != "read_only"
    ):
        raise ValueError("template legacy evidence identity differs")
    provider_descriptor = _load(
        repo_root / "projects" / provider / "config" / "project.json"
    )
    matching_mappings = [
        mapping
        for mapping in provider_descriptor.get("legacy_identities", [])
        if mapping.get("mapping_id") == evidence_identity["mapping_id"]
    ]
    if len(matching_mappings) != 1:
        raise ValueError("template provider legacy identity mapping is unavailable")
    provider_mapping = matching_mappings[0]
    if (
        provider_descriptor.get("project_id") != provider
        or provider_mapping.get("project_id")
        != evidence_identity["recorded_project_id"]
        or provider_mapping.get("artifact_access")
        != evidence_identity["artifact_access"]
        or provider_mapping.get("verification_identity") != "recorded_project_id"
        or provider_mapping.get("new_runs_allowed") is not False
    ):
        raise ValueError("template provider legacy identity mapping differs")
    review = registry["manual_gui_review"]
    if (
        not isinstance(review, dict)
        or set(review) != {"status", "recorded_at", "scope"}
        or review["status"] != "pass"
        or review["scope"]
        != "run_local_iob_reopened_single_instance_transform_no_program_no_particles"
    ):
        raise ValueError("manual GUI review has not approved runtime binding")

    recorded_project = evidence_identity["recorded_project_id"]
    run_id = registry["registration_run_id"]
    artifact_root = resolve_legacy_artifact_root(
        repo_root.parent, provider_mapping, provider
    )
    recorded_artifact_root = (
        repo_root.parent / "artifacts" / "projects" / recorded_project
    ).resolve()
    runs_root = (artifact_root / "runs").resolve()
    run_root = (runs_root / run_id).resolve()
    if run_root.parent != runs_root or not run_root.is_dir():
        raise ValueError("template registration run is unavailable")
    config_path = run_root / "run_config.json"
    summary_path = run_root / "summary.json"
    manifest_path = run_root / "run_manifest.json"
    report_path = run_root / "logs/simion_layout_structure_report.txt"
    if any(
        not path.is_file()
        for path in (config_path, summary_path, manifest_path, report_path)
    ):
        raise ValueError("template registration evidence is incomplete")
    if _sha256(manifest_path) != registry["run_manifest_sha256"]:
        raise ValueError("template registration manifest SHA-256 differs")

    config = _load(config_path)
    summary = _load(summary_path)
    manifest = _load(manifest_path)
    if (
        config.get("role") != "multipole_simion_layout_template_build"
        or config.get("project") != recorded_project
        or config.get("run_id") != run_id
        or config.get("mode") != "simion_layout_template_build"
        or config.get("physical_model") is not False
        or summary.get("status") != "success"
        or summary.get("runtime_structure_verified") is not True
        or summary.get("program_executed") is not False
        or summary.get("particle_fly_executed") is not False
        or manifest.get("status") != "success"
        or manifest.get("run_id") != run_id
        or manifest.get("project") != recorded_project
    ):
        raise ValueError("template registration is not a structure-only success")
    structure = config.get("structural_contract", {})
    if (
        structure.get("instance_count") != 1
        or structure.get("pa_basename") != "quad_monolithic.pa0"
        or structure.get("transform") != EXPECTED_TRANSFORM
    ):
        raise ValueError("template structural contract differs")
    report = report_path.read_text(encoding="utf-8", errors="replace")
    if not all(token in report for token in REPORT_TOKENS):
        raise ValueError("template runtime structure evidence is incomplete")

    bundle = {}
    manifest_inputs = manifest.get("inputs", {})
    for role, manifest_role, expected_sha in (
        ("iob", "template_iob", registry["iob_sha256"]),
        ("con", "template_con", registry["con_sha256"]),
    ):
        manifest_record = manifest_inputs.get(manifest_role, {})
        path = relocated_manifest_path(
            str(manifest_record.get("path", "")),
            recorded_artifact_root,
            artifact_root,
        )
        expected_sha = str(expected_sha).upper()
        if (
            not path.is_file()
            or _sha256(path) != expected_sha
            or str(manifest_record.get("sha256", "")).upper() != expected_sha
        ):
            raise ValueError(f"template bundle identity differs: {role}")
        bundle[role] = {"path": str(path), "sha256": expected_sha}

    return {
        "schema_version": 1,
        "role": "multipole_resolved_simion_layout_template",
        "template_id": registry["template_id"],
        "provider_project_id": provider,
        "legacy_evidence_identity": evidence_identity,
        "registration_run_id": run_id,
        "registry_path": str(registry_path),
        "registry_sha256": _sha256(registry_path),
        "run_manifest": {"path": str(manifest_path), "sha256": _sha256(manifest_path)},
        "manual_gui_review": review,
        "bundle": bundle,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = resolve_simion_layout_template(args.repo_root, args.registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MULTIPOLE_SIMION_LAYOUT_TEMPLATE=PASS TEMPLATE={result['template_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
