"""Refresh or check frozen file identities in one family-source campaign."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    _canonical_sha256,
    _derive_pulse_discovery_run_id,
    expand_flat_experiment_authoring,
)


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
    records: list[dict[str, Any]] = []
    authoring = campaign.get("experiments", [])
    if isinstance(authoring, list):
        authoring_rows = authoring
    elif isinstance(authoring, dict):
        authoring_rows = [authoring.get("shared", {})] + [
            row.get("overrides", {}) for row in authoring.get("rows", [])
            if isinstance(row, dict)
        ]
    else:
        raise ValueError("campaign experiments must be an array or flat authoring object")
    for experiment in authoring_rows:
        if not isinstance(experiment, dict):
            raise ValueError("campaign experiment authoring row must be an object")
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


def expanded_campaign_semantic_sha256(campaign: dict[str, Any]) -> str:
    """Hash the execution-relevant campaign, independent of flat authoring layout.

    A legacy raw campaign hash may remain in published receipts.  It is accepted
    only when this complete semantic projection is unchanged; the projection
    includes qualification and all materialized experiment fields.  Execution
    policy is a runtime-binding concern: it is frozen separately in each run
    receipt and must not invalidate campaign scientific identity.
    """

    semantic = expand_flat_experiment_authoring(copy.deepcopy(campaign))
    semantic.pop("published_authoring_identity", None)
    semantic.pop("execution_policy", None)
    return _canonical_sha256(semantic)


def _accepted_published_campaign_sha256(
    compiled: dict[str, Any], rendered: bytes
) -> set[str]:
    accepted = {hashlib.sha256(rendered).hexdigest().upper()}
    legacy = compiled.get("published_authoring_identity")
    if legacy is None:
        return accepted
    if (
        not isinstance(legacy, dict)
        or set(legacy) != {"legacy_campaign_sha256", "semantic_sha256"}
        or not all(isinstance(value, str) and re.fullmatch(r"[A-F0-9]{64}", value)
                   for value in legacy.values())
        or expanded_campaign_semantic_sha256(compiled) != legacy["semantic_sha256"]
    ):
        raise ValueError("published authoring identity semantic projection differs")
    accepted.add(legacy["legacy_campaign_sha256"])
    return accepted


def is_fresh(repo_root: Path, campaign_path: Path) -> bool:
    compiled = compile_campaign(repo_root, campaign_path)
    materialized = expand_flat_experiment_authoring(compiled)
    rendered = canonical_bytes(compiled)
    if campaign_path.read_bytes() != rendered:
        return False
    if (
        _published_target_manifests(repo_root, materialized)
        or _published_campaign_receipts(repo_root, campaign_path)
    ):
        try:
            _validate_published_format_recovery(
                repo_root, campaign_path, materialized, rendered
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
    targets = [
        run_root / str(experiment["run_id"]) / "run_manifest.json"
        for experiment in campaign.get("experiments", [])
        if (run_root / str(experiment["run_id"]) / "run_manifest.json").is_file()
    ]
    finalized = _validated_failed_parent_recoveries(repo_root, campaign, targets)
    return [path for path in targets if path not in finalized]


def _validated_failed_parent_recoveries(
    repo_root: Path, campaign: dict[str, Any], targets: list[Path]
) -> set[Path]:
    """Return failed target manifests replaced by one verified analysis recovery.

    A recovery never makes the original parent successful.  It only permits a
    source-binding refresh when the separate ``__r01`` successor proves that
    the immutable failed parent and completed raw-log child were reanalysed.
    Any malformed successor remains a hard failure rather than silently
    weakening published-campaign immutability.
    """

    finalized: set[Path] = set()
    for candidate in targets:
        manifest = _load(candidate)
        if manifest.get("status") != "failed":
            continue
        experiment = next(
            row for row in campaign.get("experiments", []) if str(row["run_id"]) == candidate.parent.name
        )
        # A solver retry is a separate, immutable run.  Failed retry attempts
        # are retained but do not invalidate the campaign; the first successful
        # retry must carry the original campaign/experiment identity.
        retry_manifests = sorted(
            candidate.parent.parent.glob(candidate.parent.name + "__r[0-9][0-9]/run_manifest.json")
        )
        successful_retry = next(
            (
                path for path in retry_manifests
                if (_load(path).get("status") == "success"
                    and _load(path).get("mode") == "multipole_family_source_closure")
            ),
            None,
        )
        if successful_retry is not None:
            retry_manifest = _load(successful_retry)
            verify_record("solver retry run_config", retry_manifest["run_config"], base_dir=successful_retry.parent)
            retry_config = _load(record_path(retry_manifest["run_config"], base_dir=successful_retry.parent))
            if (
                retry_config.get("campaign_id") != campaign.get("campaign_id")
                or retry_config.get("experiment_id") != experiment.get("experiment_id")
                or retry_config.get("experiment_row_sha256") != _canonical_sha256(experiment)
            ):
                raise ValueError(f"failed-parent solver retry is invalid: {candidate.parent.name}")
            finalized.add(candidate)
            continue
        recovery = candidate.parent.parent / (candidate.parent.name + "__r01") / "run_manifest.json"
        if not recovery.is_file():
            continue
        if _load(recovery).get("status") == "failed":
            continue
        try:
            recovery_manifest = _load(recovery)
            if (
                recovery_manifest.get("role") != "simulation_run_manifest"
                or recovery_manifest.get("status") != "success"
                or recovery_manifest.get("mode")
                != "multipole_family_source_closure_analysis_recovery"
            ):
                raise ValueError("recovery parent identity differs")
            verify_record("recovery parent run_config", recovery_manifest["run_config"], base_dir=recovery.parent)
            for name, record in recovery_manifest.get("inputs", {}).items():
                verify_record(f"recovery parent input {name}", record, base_dir=recovery.parent)
            for record in recovery_manifest.get("outputs", []):
                verify_record("recovery parent output", record, base_dir=recovery.parent)
            parent_config = _load(record_path(recovery_manifest["run_config"], base_dir=recovery.parent))
            failed_parent_path = Path(parent_config["inputs"]["failed_parent_manifest"])
            child_manifest_path = Path(parent_config["inputs"]["recovered_child_manifest"])
            receipt_path = Path(parent_config["inputs"]["recovery_receipt"])
            if failed_parent_path.resolve() != candidate.resolve():
                raise ValueError("recovery parent source differs")
            for label, path in (("recovery child", child_manifest_path), ("recovery receipt", receipt_path)):
                if not path.is_file():
                    raise ValueError(f"{label} is missing")
            child_manifest = _load(child_manifest_path)
            if (
                child_manifest.get("status") != "success"
                or child_manifest.get("mode") != "rf_to_oatof_simion_single_flight_analysis_recovery"
            ):
                raise ValueError("recovery child identity differs")
            for name, record in child_manifest.get("inputs", {}).items():
                verify_record(f"recovery child input {name}", record, base_dir=child_manifest_path.parent)
            child_config = _load(record_path(child_manifest["run_config"], base_dir=child_manifest_path.parent))
            if Path(child_config["inputs"]["failed_parent_manifest"]).resolve() != candidate.resolve():
                raise ValueError("recovery child source differs")
            receipt = _load(receipt_path)
            if (
                receipt.get("role") != "rf_oatof_completed_single_flight_analysis_recovery_receipt"
                or receipt.get("status") != "success"
                or receipt.get("solver_reexecuted") is not False
                or receipt.get("source_failed_parent_manifest_sha256") != file_sha256(candidate)
            ):
                raise ValueError("recovery receipt identity differs")
            if receipt.get("campaign", {}).get("experiment_id") != experiment.get("experiment_id"):
                raise ValueError("recovery receipt experiment differs")
        except (AssertionError, KeyError, StopIteration, TypeError, ValueError) as exc:
            raise ValueError(f"failed-parent recovery is invalid: {candidate.parent.name}") from exc
        if not campaign.get("campaign_id"):
            raise ValueError("recovery campaign identity is missing")
        finalized.add(candidate)
    return finalized


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
    accepted_campaign_sha256 = _accepted_published_campaign_sha256(compiled, rendered)
    rows = compiled.get("experiments", [])
    experiments = {str(row["run_id"]): row for row in rows}
    experiments_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        experiments_by_id.setdefault(str(row["experiment_id"]), []).append(row)
    if len(experiments) != len(rows):
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
            or receipt.get("campaign_sha256") not in accepted_campaign_sha256
            or receipt.get("campaign_id") != compiled.get("campaign_id")
            or (
                experiment is not None
                and receipt.get("experiment_id") != experiment.get("experiment_id")
            )
        ):
            raise ValueError(f"published campaign identity differs: {run_id}")
        if experiment is not None:
            continue
        retry_matches = [
            row for base_run_id, row in experiments.items()
            if re.fullmatch(re.escape(base_run_id) + r"__r[0-9]{2}", run_id)
        ]
        if len(retry_matches) == 1:
            retry_experiment = retry_matches[0]
            if (
                receipt.get("execution_strategy") != "simion_single_flight"
                or receipt.get("experiment_id") != retry_experiment.get("experiment_id")
                or receipt.get("experiment_row_sha256") != _canonical_sha256(retry_experiment)
            ):
                raise ValueError(f"published campaign retry identity differs: {run_id}")
            continue
        matches = experiments_by_id.get(str(receipt.get("experiment_id")), [])
        if len(matches) != 1:
            raise ValueError(f"published campaign identity differs: {run_id}")
        _validate_internal_discovery_receipt(
            receipt_path=receipt_path,
            receipt=receipt,
            run_id=run_id,
            experiment=matches[0],
        )


def _validate_internal_discovery_receipt(
    *,
    receipt_path: Path,
    receipt: dict[str, Any],
    run_id: str,
    experiment: dict[str, Any],
) -> None:
    """Validate one machine-bound internal pulse-discovery publication."""

    expected_run_id = _derive_pulse_discovery_run_id(str(experiment["run_id"]))
    plan_path = receipt_path.parent / "composition_plan.json"
    if (
        run_id != expected_run_id
        or receipt.get("execution_strategy") != "simion_single_flight"
        or receipt.get("experiment_row_sha256") != _canonical_sha256(experiment)
        or not plan_path.is_file()
        or receipt.get("composition_plan_sha256") != file_sha256(plan_path)
    ):
        raise ValueError(f"published campaign identity differs: {run_id}")


def write_campaign(repo_root: Path, campaign_path: Path) -> bool:
    """Refresh identities unless a published target run makes the campaign immutable."""
    compiled = compile_campaign(repo_root, campaign_path)
    materialized = expand_flat_experiment_authoring(compiled)
    rendered = canonical_bytes(compiled)
    published = _published_target_manifests(repo_root, materialized)
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
            repo_root, campaign_path, materialized, rendered
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
