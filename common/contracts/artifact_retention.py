"""Classify and enforce run-artifact retention without device assumptions."""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

if __package__:
    from .recorded_file_removal import remove_recorded_files, write_json_atomic
    from .file_identity import file_sha256
else:
    from recorded_file_removal import remove_recorded_files, write_json_atomic
    from file_identity import file_sha256

POLICY_PATH = Path(__file__).with_name("artifact_retention.json")


def _simion_completion_api() -> ModuleType:
    """Load one sibling adapter for package and existing direct-file consumers."""
    if __package__:
        from common.simion import native_completion
        return native_completion
    name = f"{__name__}._simion_native_completion"
    if name in sys.modules:
        return sys.modules[name]
    source = Path(__file__).resolve().parents[1] / "simion/native_completion.py"
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"SIMION completion adapter cannot be loaded: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass resolves annotations through this entry.
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


@dataclass(frozen=True)
class Retention:
    """Validated retention selection frozen by one run."""

    class_id: str
    reason: str | None
    policy_version: int


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    """Load the repository retention policy."""

    return json.loads(path.read_text(encoding="utf-8"))


def validate_retention(
    value: object, policy: dict[str, Any] | None = None
) -> Retention:
    """Validate one run_config artifact_retention object."""

    policy = policy or load_policy()
    if not isinstance(value, dict):
        raise ValueError("artifact_retention must be an object")
    expected = {"policy_version", "class", "reason"}
    unknown = set(value) - expected
    if unknown:
        raise ValueError(
            f"artifact_retention contains unknown fields: {sorted(unknown)}"
        )
    if value.get("policy_version") != policy["schema_version"]:
        raise ValueError("artifact_retention policy_version is unsupported")
    class_id = value.get("class")
    classes = policy["classes"]
    if not isinstance(class_id, str) or class_id not in classes:
        raise ValueError(f"artifact_retention class is unsupported: {class_id!r}")
    reason = value.get("reason")
    if reason is not None and (
        not isinstance(reason, str) or not reason.strip()
    ):
        raise ValueError("artifact_retention reason must be null or non-blank text")
    if classes[class_id]["requires_reason"] and reason is None:
        raise ValueError(f"artifact_retention class {class_id!r} requires a reason")
    if class_id == policy["default_class"] and reason is not None:
        raise ValueError("compact artifact retention must not carry a heavy-retention reason")
    return Retention(class_id, reason, int(policy["schema_version"]))


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


def load_failed_recovery_exemptions(
    run_dir: Path, retention: Retention
) -> set[Path]:
    """Validate explicitly retained completed TRACE files for a failed run."""

    run_dir = run_dir.resolve()
    action_path = run_dir / "retention_actions.json"
    if not action_path.is_file():
        return set()
    action = json.loads(action_path.read_text(encoding="utf-8-sig"))
    if (
        action.get("schema_version") != 1
        or action.get("role") != "artifact_retention_actions"
        or action.get("retention_class") != retention.class_id
        or action.get("status", "complete") != "complete"
        or not isinstance(action.get("preserved", []), list)
    ):
        raise ValueError("failed-run retention actions differ")
    if not action.get("preserved", []):
        return set()
    completion = _simion_completion_api()

    exemptions: set[Path] = set()
    for record in action.get("preserved", []):
        if not isinstance(record, dict) or set(record) != {
            "path", "bytes", "retention_role", "action"
        }:
            raise ValueError("failed-run recovery record differs")
        relative = Path(str(record["path"]))
        path = (run_dir / relative).resolve()
        try:
            path.relative_to(run_dir)
        except ValueError as exc:
            raise ValueError("failed-run recovery path escapes run directory") from exc
        if (
            relative.is_absolute()
            or not path.is_file()
            or not completion.has_recoverable_batch_completion(path)
            or record["action"] not in {
                "retained_completed_native_trace_for_recovery",
                "retained_completed_simion_batch_log_for_recovery",
            }
            or (
                record["action"] == "retained_completed_native_trace_for_recovery"
                and completion.recoverable_batch_log_kind(path) != "trace"
            )
            or record["retention_role"] != classify_file(path)
            or int(record["bytes"]) != path.stat().st_size
        ):
            raise ValueError("failed-run recovery TRACE differs")
        exemptions.add(path)
    return exemptions


def validate_retained_files(
    retention: Retention,
    files: Iterable[Path],
    *,
    policy: dict[str, Any] | None = None,
    exempt_paths: Iterable[Path] = (),
) -> list[tuple[Path, str]]:
    """Return classified files or fail if the selected class forbids one."""

    policy = policy or load_policy()
    allowed = set(policy["classes"][retention.class_id]["allowed_roles"])
    exemptions = {path.resolve() for path in exempt_paths}
    classified = [(path, classify_file(path, policy=policy)) for path in files]
    forbidden = [
        (path, role)
        for path, role in classified
        if role not in allowed and path.resolve() not in exemptions
    ]
    if forbidden:
        details = ", ".join(f"{path.name} ({role})" for path, role in forbidden[:5])
        raise ValueError(
            f"artifact retention class {retention.class_id!r} forbids: {details}"
        )
    return classified


def load_run_retention(run_config_path: Path) -> tuple[Path, Retention]:
    """Load v2 retention from a run-local run_config."""

    resolved = run_config_path.resolve()
    document = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if document.get("schema_version") != 2:
        raise ValueError("retention enforcement requires run_config schema_version 2")
    return resolved.parent, validate_retention(document.get("artifact_retention"))


def _execute_removals(
    run_dir: Path, retention: Retention, removed: list[dict[str, Any]],
    preserved: list[dict[str, Any]],
    *, recovery_inputs: list[dict[str, Any]] | None = None,
    maximum_run_bytes: int | None = None,
) -> Path:
    """Publish the exact discard list without reading disposable payload bytes."""
    action_path = run_dir / "retention_actions.json"
    existing = None
    if action_path.exists():
        existing = json.loads(action_path.read_text(encoding="utf-8-sig"))
        expected_planned = [
            {"path": item["path"], "bytes": int(item["bytes"])}
            for item in removed
        ]
        if (
            not isinstance(existing, dict)
            or existing.get("status") != "preflight_pending"
            or existing.get("retention_class") != retention.class_id
            or existing.get("planned") != expected_planned
        ):
            raise ValueError("run already has a retention reconciliation receipt")
    for item in removed:
        path = run_dir / item["path"]
        path.resolve().relative_to(run_dir.resolve())
        if path.is_symlink() or path.stat().st_size != item["bytes"]:
            raise ValueError(f"retention file identity changed: {path}")
    action = {
        "schema_version": 1, "role": "artifact_retention_actions",
        "retention_class": retention.class_id, "status": "pending",
        "removed_file_count": 0, "removed_bytes": 0,
        "removed": removed, "preserved": preserved,
    }
    if recovery_inputs is not None:
        action["recovery_inputs"] = recovery_inputs

    _write_retention_action(action_path, action, maximum_run_bytes)
    for item in remove_recorded_files(run_dir, removed, identities_verified=True):
        action["removed_file_count"] += 1
        action["removed_bytes"] += item["bytes"]
        _write_retention_action(action_path, action, maximum_run_bytes)
    action["status"] = "complete"
    _write_retention_action(action_path, action, maximum_run_bytes)
    return action_path


def _write_retention_action(path: Path, action: dict[str, Any], maximum_run_bytes: int | None) -> None:
    if maximum_run_bytes is not None:
        if type(maximum_run_bytes) is not int or maximum_run_bytes < 0:
            raise ValueError("retention recovery byte ceiling is invalid")
        current = sum(item.stat().st_size for item in path.parent.rglob("*") if item.is_file())
        temporary = len((json.dumps(action, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        if current + temporary > maximum_run_bytes:
            raise ValueError("retention recovery metadata exceeds admitted run byte ceiling")
    write_json_atomic(path, action)


def _recovery_input_records(run_config: Path, inputs: Iterable[Path]) -> list[dict[str, Any]]:
    """Bind small owner evidence, without hashing disposable native payloads."""
    sources = [run_config, *inputs]
    if any(path.is_symlink() for path in sources):
        raise ValueError("retention recovery input is a symbolic link")
    paths = sorted({path.resolve() for path in sources})
    records = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"retention recovery input is not a regular file: {path}")
        records.append(dict(path=str(path), exists=True, bytes=path.stat().st_size, sha256=file_sha256(path)))
    return records


def _resume_removals(
    run_dir: Path, retention: Retention, inputs: list[dict[str, Any]],
    preserve_paths: set[Path], *, failed_run: bool,
    maximum_run_bytes: int | None,
) -> Path:
    """Continue only the original receipt, including one unlink/write gap."""
    action_path = run_dir / "retention_actions.json"
    action = json.loads(action_path.read_text(encoding="utf-8-sig"))
    if isinstance(action, dict) and action.get("status") == "preflight_pending":
        raise ValueError("preflight_pending must return to its original reconciliation owner")
    required = {"schema_version", "role", "retention_class", "status", "removed_file_count",
                "removed_bytes", "removed", "preserved", "recovery_inputs"}
    if (not isinstance(action, dict) or set(action) != required or action["schema_version"] != 1
            or action["role"] != "artifact_retention_actions" or action["retention_class"] != retention.class_id
            or action["status"] not in {"pending", "complete"}):
        raise ValueError("retention recovery receipt differs")
    if action["recovery_inputs"] != inputs:
        raise ValueError("retention recovery input identity differs")
    manifest_path = run_dir / "run_manifest.json"
    if (action["status"] != "complete" and manifest_path.is_file()
            and json.loads(manifest_path.read_text(encoding="utf-8-sig")).get("status") != "checkpoint"):
        raise ValueError("retention recovery cannot modify a terminal run")
    policy = load_policy()
    allowed = set(policy["classes"][retention.class_id]["allowed_roles"])
    seen: set[str] = set()
    for section in ("removed", "preserved"):
        if not isinstance(action[section], list):
            raise ValueError("retention recovery records must be lists")
        for record in action[section]:
            if not isinstance(record, dict) or set(record) != {"path", "bytes", "retention_role", "action"}:
                raise ValueError("retention recovery record differs")
            relative = record["path"]
            if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
                    or Path(relative).as_posix() != relative or ".." in Path(relative).parts
                    or relative.casefold() in seen or type(record["bytes"]) is not int or record["bytes"] < 0):
                raise ValueError("retention recovery record path or size differs")
            seen.add(relative.casefold())
            path = run_dir / relative
            path.resolve().relative_to(run_dir)
            if path.is_symlink() or record["retention_role"] != classify_file(path, bytes_count=record["bytes"], policy=policy):
                raise ValueError("retention recovery record type differs")
            if section == "preserved":
                completion = _simion_completion_api()
                expected = ("retained_completed_native_trace_for_recovery" if completion.recoverable_batch_log_kind(path) == "trace"
                            else "retained_completed_simion_batch_log_for_recovery")
                if (path.resolve() not in preserve_paths or not path.is_file() or path.stat().st_size != record["bytes"]
                        or not completion.has_recoverable_batch_completion(path) or record["action"] != expected):
                    raise ValueError("retention recovery preserved evidence differs")
            elif record["action"] == "removed_incomplete_native_trace_before_terminal_manifest":
                if not failed_run or _simion_completion_api().recoverable_batch_log_kind(path) is None:
                    raise ValueError("retention recovery removal is not authorized by the failed run")
            elif record["action"] != "removed_before_terminal_manifest" or record["retention_role"] in allowed:
                raise ValueError("retention recovery removal is not authorized by the frozen class")
    if {str((run_dir / item["path"]).resolve()) for item in action["preserved"]} != {str(path) for path in preserve_paths}:
        raise ValueError("retention recovery preserve selection differs")
    removed = action["removed"]
    count = action["removed_file_count"]
    if (type(count) is not int or not 0 <= count <= len(removed)
            or type(action["removed_bytes"]) is not int
            or action["removed_bytes"] != sum(item["bytes"] for item in removed[:count])):
        raise ValueError("retention recovery progress differs")
    if action["status"] == "complete" and count != len(removed):
        raise ValueError("retention recovery completion differs")
    # A sequential unlink can precede its progress write by exactly one record.
    missing_next = count < len(removed) and not (run_dir / removed[count]["path"]).exists()
    for index, item in enumerate(removed):
        path = run_dir / item["path"]
        if index < count or (index == count and missing_next):
            if path.exists():
                raise ValueError("retention removed file reappeared")
        elif not path.is_file() or path.stat().st_size != item["bytes"]:
            raise ValueError("retention remaining file identity changed")
    planned = {(run_dir / item["path"]).resolve() for item in removed}
    for path in run_dir.rglob("*"):
        if path.is_file() and path.resolve() not in planned | preserve_paths:
            if classify_file(path, policy=policy) not in allowed:
                raise ValueError("retention found forbidden payload outside the original plan")
    if action["status"] == "complete":
        return action_path  # Exact replay does not rewrite completed evidence.
    if missing_next:
        action["removed_file_count"] += 1
        action["removed_bytes"] += removed[count]["bytes"]
        _write_retention_action(action_path, action, maximum_run_bytes)
    for item in remove_recorded_files(run_dir, removed[action["removed_file_count"]:], identities_verified=True):
        action["removed_file_count"] += 1
        action["removed_bytes"] += item["bytes"]
        _write_retention_action(action_path, action, maximum_run_bytes)
    action["status"] = "complete"
    _write_retention_action(action_path, action, maximum_run_bytes)
    return action_path


def _publish_removal_preflight(
    run_dir: Path, retention: Retention, removed: list[dict[str, Any]],
) -> Path:
    """Win removal authority without hashing or deleting payload bytes."""

    action_path = run_dir / "retention_actions.json"
    if action_path.exists():
        raise ValueError("run already has a retention reconciliation receipt")
    planned = [
        {"path": item["path"], "bytes": int(item["bytes"])} for item in removed
    ]
    write_json_atomic(
        action_path,
        {
            "schema_version": 1,
            "role": "artifact_retention_actions",
            "retention_class": retention.class_id,
            "status": "preflight_pending",
            "planned": planned,
            "planned_bytes": sum(item["bytes"] for item in planned),
        },
    )
    return action_path


def apply_retention(
    run_config_path: Path, *, preserve_paths: Iterable[Path] = (),
    remove_paths: Iterable[Path] = (), failed_run: bool = False,
    recovery_inputs: Iterable[Path] = (), resume: bool = False,
    maximum_run_bytes: int | None = None,
) -> Path:
    """Remove only future-run files forbidden by its frozen retention class."""

    run_dir, retention = load_run_retention(run_config_path)
    if run_dir.parent.name != "runs":
        raise ValueError("run_config must be a direct child of a runs/<run_id> directory")
    manifest_path = run_dir / "run_manifest.json"
    recovery_inputs = tuple(recovery_inputs)
    input_records = _recovery_input_records(run_config_path, recovery_inputs) if recovery_inputs or resume else None
    if resume:
        if tuple(remove_paths):
            raise ValueError("retention recovery cannot supply a new removal selection")
        return _resume_removals(run_dir, retention, input_records,
                               {path.resolve() for path in preserve_paths}, failed_run=failed_run,
                               maximum_run_bytes=maximum_run_bytes)
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("status") != "checkpoint":
            raise ValueError("retention cannot modify a run with a terminal manifest")
    policy = load_policy()
    allowed = set(policy["classes"][retention.class_id]["allowed_roles"])
    action_path = run_dir / "retention_actions.json"
    preserved_paths = {path.resolve() for path in preserve_paths}
    remove_paths = {path.resolve() for path in remove_paths}
    if failed_run or preserved_paths or remove_paths:
        completion = _simion_completion_api()
        if failed_run:
            remove_paths |= completion.recoverable_batch_logs(run_dir) - preserved_paths
    if preserved_paths & remove_paths:
        raise ValueError("retention cannot both preserve and remove one path")
    for path in preserved_paths | remove_paths:
        try:
            path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("retention preserve path escapes run directory") from exc
        if not path.is_file() or completion.recoverable_batch_log_kind(path) is None:
            raise ValueError("retention may target only a run-local native TRACE")
        if path in preserved_paths and not completion.has_recoverable_batch_completion(path):
            raise ValueError(f"retention requires a completed SIMION batch log: {path}")
    removed: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if (
            not path.is_file()
            or path.is_symlink()
            or path in {action_path, manifest_path}
        ):
            continue
        role = classify_file(path, policy=policy)
        if path.resolve() in remove_paths:
            record = {
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": path.stat().st_size,
                "retention_role": role,
                "action": "removed_incomplete_native_trace_before_terminal_manifest",
            }
            removed.append(record)
            continue
        if path.resolve() in preserved_paths:
            preserved.append({
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": path.stat().st_size,
                "retention_role": role,
                "action": (
                    "retained_completed_native_trace_for_recovery"
                    if completion.recoverable_batch_log_kind(path) == "trace"
                    else "retained_completed_simion_batch_log_for_recovery"
                ),
            })
            continue
        if role in allowed:
            continue
        record = {
            "path": path.relative_to(run_dir).as_posix(),
            "bytes": path.stat().st_size,
            "retention_role": role,
            "action": "removed_before_terminal_manifest",
        }
        removed.append(record)
    return _execute_removals(run_dir, retention, removed, preserved, recovery_inputs=input_records,
                             maximum_run_bytes=maximum_run_bytes)


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
