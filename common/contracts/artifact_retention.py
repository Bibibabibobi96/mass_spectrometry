"""Classify and enforce run-artifact retention without device assumptions."""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
from msplatform.execution.resources import resource_path
from msplatform.execution import artifact_retention as _retention_runtime
from types import ModuleType
from typing import Any, Iterable

POLICY_PATH = resource_path("artifact_retention.json")


def _simion_completion_api() -> ModuleType:
    """Use the canonical parser from the current frozen import closure."""
    from msplatform.backends.simion import native_completion
    return native_completion


Retention = _retention_runtime.Retention


load_policy = _retention_runtime.load_policy


validate_retention = _retention_runtime.validate_retention


def is_numbered_simion_suffix(suffix: str, prefixes: Iterable[str]) -> bool:
    """Return whether suffix is a numbered SIMION PA solution suffix."""

    lowered = suffix.lower()
    return any(
        lowered.startswith(prefix.lower())
        and lowered[len(prefix) :].isdigit()
        for prefix in prefixes
    )


def classify_file(
    path: Path, *, bytes_count: int | None = None, policy: dict[str, Any] | None = None
) -> str:
    """Classify a run file by evidence value and rebuildability."""

    policy = policy or load_policy()
    name = path.name.lower()
    suffix = path.suffix.lower()
    # IOB slot templates are executable inputs frozen with the code, not solved
    # fields. Every slot must survive, including multi-instance workbenches.
    if path.parent.as_posix().endswith(
        "runtime_snapshot/common/simion/assets/iob_instance_seeds"
    ) and fnmatch.fnmatch(name, "iob_seed_placeholder_[0-9][0-9].pa0"):
        return "required_evidence"
    if any(
        fnmatch.fnmatch(name, pattern.lower())
        for pattern in policy["dense_trajectory_globs"]
    ):
        return "dense_trajectory"
    if suffix in policy["solver_native_suffixes"] or is_numbered_simion_suffix(
        suffix, policy["solver_native_numbered_suffix_prefixes"]
    ):
        return "solver_native_binary"
    # This table is the mandatory handoff from the pre-pulse SIMION child to
    # the detector-blind selector in its governed parent.  It may be large,
    # but removing it at the child's terminal boundary makes that parent
    # impossible to execute or reproduce.
    if name in {
        "pre_pulse_time_series_states.csv",
        "pre_pulse_time_series_states.csv.gz",
    }:
        return "required_evidence"
    size = path.stat().st_size if bytes_count is None and path.is_file() else bytes_count
    # Small candidate receipts have historically been lightweight optional
    # outputs.  Only promote an oversized receipt, which compact retention
    # would otherwise forbid, because it is the complete auditable selector
    # record behind the governed parent conclusion.
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


def load_failed_recovery_exemptions(run_dir: Path, retention: Retention) -> set[Path]:
    return _retention_runtime.load_failed_recovery_exemptions(run_dir, retention,
        classifier=classify_file, completion_api=_simion_completion_api)


def validate_retained_files(retention: Retention, files: Iterable[Path], *,
                            policy: dict[str, Any] | None = None,
                            exempt_paths: Iterable[Path] = ()) -> list[tuple[Path, str]]:
    return _retention_runtime.validate_retained_files(retention, files, classifier=classify_file,
        policy=policy, exempt_paths=exempt_paths)


load_run_retention = _retention_runtime.load_run_retention


_execute_removals = _retention_runtime._execute_removals


_write_retention_action = _retention_runtime._write_retention_action


_recovery_input_records = _retention_runtime._recovery_input_records


_resume_removals = _retention_runtime._resume_removals


_publish_removal_preflight = _retention_runtime._publish_removal_preflight


def apply_retention(run_config_path: Path, *, preserve_paths: Iterable[Path] = (),
                    remove_paths: Iterable[Path] = (), failed_run: bool = False,
                    recovery_inputs: Iterable[Path] = (), resume: bool = False,
                    maximum_run_bytes: int | None = None) -> Path:
    return _retention_runtime.apply_retention(run_config_path, classifier=classify_file,
        completion_api=_simion_completion_api, preserve_paths=preserve_paths,
        remove_paths=remove_paths, failed_run=failed_run, recovery_inputs=recovery_inputs,
        resume=resume, maximum_run_bytes=maximum_run_bytes)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--run-config", required=True, type=Path)
    apply_parser.add_argument("--preserve-path", action="append", type=Path, default=[])
    apply_parser.add_argument("--remove-path", action="append", type=Path, default=[])
    apply_parser.add_argument("--failed-run", action="store_true")
    apply_parser.add_argument("--recovery-input", action="append", type=Path, default=[])
    apply_parser.add_argument("--resume", action="store_true")
    apply_parser.add_argument("--maximum-run-bytes", type=int)
    args = parser.parse_args()
    if args.command == "apply":
        action_path = apply_retention(
            args.run_config,
            preserve_paths=args.preserve_path,
            remove_paths=args.remove_path,
            failed_run=args.failed_run,
            recovery_inputs=args.recovery_input, resume=args.resume,
            maximum_run_bytes=args.maximum_run_bytes,
        )
        action = json.loads(action_path.read_text(encoding="utf-8"))
        print(
            "ARTIFACT_RETENTION=PASS "
            f"CLASS={action['retention_class']} "
            f"REMOVED_FILES={action['removed_file_count']} "
            f"REMOVED_BYTES={action['removed_bytes']}"
        )


if __name__ == "__main__":
    main()
