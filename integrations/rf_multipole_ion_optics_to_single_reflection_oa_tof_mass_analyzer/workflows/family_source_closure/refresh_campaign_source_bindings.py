"""Refresh or check frozen file identities in one family-source campaign."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256, repository_text_sha256


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
SOURCE_FILE_ROLES = (
    "manifest",
    "state",
    "particle_source",
    "metadata",
    "handoff_publication_contract",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _resolve_record(repo_root: Path, record: dict[str, Any]) -> tuple[Path, bool]:
    declared = record.get("path")
    if not isinstance(declared, str) or not declared or Path(declared).is_absolute():
        raise ValueError("campaign file path must be a nonempty relative path")
    root = repo_root.parent if declared.startswith("artifacts/") else repo_root
    path = (root / declared).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"campaign file is missing or escapes its root: {declared}")
    return path, root == repo_root


def compile_campaign(repo_root: Path, campaign_path: Path) -> dict[str, Any]:
    """Return a campaign with every declared source identity recomputed."""
    campaign = copy.deepcopy(_load(campaign_path))
    records = [campaign["execution_policy"]]
    for experiment in campaign.get("experiments", []):
        source = experiment.get("source", {})
        records.extend(source[role] for role in SOURCE_FILE_ROLES if role in source)
        reference = experiment.get("single_flight_design_reference", {})
        records.extend(
            reference[role] for role in SOURCE_FILE_ROLES if role in reference
        )
    for record in records:
        path, repository_text = _resolve_record(repo_root, record)
        record["sha256"] = (
            repository_text_sha256(path) if repository_text else file_sha256(path)
        )
    return campaign


def canonical_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def is_fresh(repo_root: Path, campaign_path: Path) -> bool:
    return _load(campaign_path) == compile_campaign(repo_root, campaign_path)


def _published_target_manifests(repo_root: Path, campaign: dict[str, Any]) -> list[Path]:
    run_root = (
        repo_root.parent
        / "artifacts"
        / "projects"
        / INTEGRATION_ID
        / "runs"
    )
    return [
        run_root / str(experiment["run_id"]) / "run_manifest.json"
        for experiment in campaign.get("experiments", [])
        if (run_root / str(experiment["run_id"]) / "run_manifest.json").is_file()
    ]


def write_campaign(repo_root: Path, campaign_path: Path) -> bool:
    """Refresh identities unless a published target run makes the campaign immutable."""
    compiled = compile_campaign(repo_root, campaign_path)
    if _load(campaign_path) == compiled:
        return False
    published = _published_target_manifests(repo_root, compiled)
    if published:
        rendered = ",".join(path.parent.name for path in published)
        raise ValueError(f"published campaign source bindings are immutable: {rendered}")
    campaign_path.write_bytes(canonical_bytes(compiled))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    campaign_path = args.campaign.resolve()
    if not campaign_path.is_relative_to(repo_root):
        raise SystemExit("campaign must be repository-managed")
    if args.check:
        if not is_fresh(repo_root, campaign_path):
            raise SystemExit("CAMPAIGN_SOURCE_BINDINGS=STALE")
        print("CAMPAIGN_SOURCE_BINDINGS=PASS")
        return
    changed = write_campaign(repo_root, campaign_path)
    print(f"CAMPAIGN_SOURCE_BINDINGS={'UPDATED' if changed else 'UNCHANGED'}")


if __name__ == "__main__":
    main()
