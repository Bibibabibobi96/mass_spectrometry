"""Retention and manifest policies for the MR COMSOL scalar-field operation."""
from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from msplatform.execution import artifact_retention
from msplatform.execution.manifest_publication import build_run_manifest as build
from msplatform.execution.resources import resource_path

POLICY_PATH = resource_path("artifact_retention.json")


def classify_file(
    path: Path,
    *,
    bytes_count: int | None = None,
    policy: dict[str, Any] | None = None,
) -> str:
    """Classify run evidence without device-specific assumptions."""
    policy = policy or artifact_retention.load_policy(POLICY_PATH)
    name = path.name.lower()
    suffix = path.suffix.lower()
    if any(fnmatch.fnmatch(name, pattern.lower()) for pattern in policy["dense_trajectory_globs"]):
        return "dense_trajectory"
    if suffix in policy["solver_native_suffixes"] or _numbered_simion_suffix(
        suffix, policy["solver_native_numbered_suffix_prefixes"]
    ):
        return "solver_native_binary"
    if name in {"pre_pulse_time_series_states.csv", "pre_pulse_time_series_states.csv.gz"}:
        return "required_evidence"
    size = path.stat().st_size if bytes_count is None and path.is_file() else bytes_count
    if (
        name == "detector_blind_pulse_timing_candidate_receipt.json"
        and size is not None
        and size >= int(policy["large_file_threshold_bytes"])
    ):
        return "required_evidence"
    if (
        name in {"run_config.json", "summary.json", "run_manifest.json"}
        or name.endswith("_summary.json")
        or "metrics" in name
        or "particle_state" in name
        or "particle_events" in name
        or name == "retention_actions.json"
    ):
        return "required_evidence"
    if size is not None and size >= int(policy["large_file_threshold_bytes"]):
        return "large_optional"
    if suffix in {".log", ".txt"}:
        return "required_evidence"
    return "lightweight_optional"


def _numbered_simion_suffix(suffix: str, prefixes: list[str]) -> bool:
    lowered = suffix.lower()
    return any(
        lowered.startswith(prefix.lower()) and lowered[len(prefix):].isdigit()
        for prefix in prefixes
    )


def validate_retained_files(
    retention: artifact_retention.Retention,
    files: Iterable[Path],
    *,
    policy: dict[str, Any] | None = None,
    exempt_paths: Iterable[Path] = (),
) -> list[tuple[Path, str]]:
    """Validate retained files through the installed policy engine."""
    return artifact_retention.validate_retained_files(
        retention, files, classifier=classify_file, policy=policy, exempt_paths=exempt_paths
    )


def retention_api() -> tuple[Any, Any, Any, Any]:
    """Return the complete installed policy tuple expected by manifest publication."""
    return (
        classify_file,
        lambda run_dir, retention: artifact_retention.load_failed_recovery_exemptions(
            run_dir, retention, classifier=classify_file
        ),
        validate_retained_files,
        artifact_retention.validate_retention,
    )


def apply_retention(run_config_path: Path, **kwargs: Any) -> Path:
    """Apply the installed retention engine to one COMSOL provider run."""
    return artifact_retention.apply_retention(
        run_config_path, classifier=classify_file, **kwargs
    )


def build_run_manifest(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Build a manifest using the installed retention policy."""
    return build(*args, retention_api=retention_api, **kwargs)
