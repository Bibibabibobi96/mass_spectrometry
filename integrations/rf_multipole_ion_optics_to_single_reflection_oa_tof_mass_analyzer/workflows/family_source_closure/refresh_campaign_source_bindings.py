"""Refresh or check frozen file identities in one family-source campaign."""

from __future__ import annotations

import argparse
import copy
import hashlib
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
    compiled = compile_campaign(repo_root, campaign_path)
    rendered = canonical_bytes(compiled)
    if campaign_path.read_bytes() != rendered:
        return False
    if (
        _published_target_manifests(repo_root, compiled)
        or _published_campaign_receipts(repo_root, campaign_path)
    ):
        try:
            _validate_published_format_recovery(
                repo_root, campaign_path, compiled, rendered
            )
        except ValueError:
            return False
    return True


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


def _published_campaign_receipts(
    repo_root: Path, campaign_path: Path
) -> list[tuple[Path, dict[str, Any]]]:
    run_root = (
        repo_root.parent
        / "artifacts"
        / "projects"
        / INTEGRATION_ID
        / "runs"
    )
    if not run_root.is_dir():
        return []
    relative_campaign = campaign_path.resolve().relative_to(repo_root.resolve()).as_posix()
    receipts = []
    for receipt_path in run_root.glob("*/execution_receipt.json"):
        receipt = _load(receipt_path)
        if receipt.get("campaign_path") == relative_campaign:
            receipts.append((receipt_path, receipt))
    return receipts


def _validate_published_format_recovery(
    repo_root: Path,
    campaign_path: Path,
    compiled: dict[str, Any],
    rendered: bytes,
) -> None:
    receipts = _published_campaign_receipts(repo_root, campaign_path)
    manifests = _published_target_manifests(repo_root, compiled)
    if not receipts:
        if manifests:
            raise ValueError("published campaign identity receipt is missing")
        return
    expected_sha256 = hashlib.sha256(rendered).hexdigest().upper()
    experiments = {str(row["run_id"]): row for row in compiled.get("experiments", [])}
    if len(experiments) != len(compiled.get("experiments", [])):
        raise ValueError("campaign run identities are not unique")
    relative_campaign = campaign_path.resolve().relative_to(repo_root.resolve()).as_posix()
    for receipt_path, receipt in receipts:
        run_id = receipt_path.parent.name
        experiment = experiments.get(run_id)
        if (
            receipt.get("role")
            != "integration_family_source_closure_execution_receipt"
            or receipt.get("integration_run_id") != run_id
            or receipt.get("campaign_path") != relative_campaign
            or receipt.get("campaign_sha256") != expected_sha256
            or receipt.get("campaign_id") != compiled.get("campaign_id")
            or experiment is None
            or receipt.get("experiment_id") != experiment.get("experiment_id")
        ):
            raise ValueError(f"published campaign identity differs: {run_id}")


def write_campaign(repo_root: Path, campaign_path: Path) -> bool:
    """Refresh identities unless a published target run makes the campaign immutable."""
    compiled = compile_campaign(repo_root, campaign_path)
    rendered = canonical_bytes(compiled)
    published = _published_target_manifests(repo_root, compiled)
    receipts = _published_campaign_receipts(repo_root, campaign_path)
    if published or receipts:
        if _load(campaign_path) != compiled:
            published_ids = ",".join(
                sorted({path.parent.name for path in published} | {
                    path.parent.name for path, _ in receipts
                })
            )
            raise ValueError(
                f"published campaign source bindings are immutable: {published_ids}"
            )
        _validate_published_format_recovery(
            repo_root, campaign_path, compiled, rendered
        )
    if campaign_path.read_bytes() == rendered:
        return False
    campaign_path.write_bytes(rendered)
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
