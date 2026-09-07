"""Classify and enforce run-artifact retention without device assumptions."""

from __future__ import annotations

import argparse
import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

POLICY_PATH = Path(__file__).with_name("artifact_retention.json")


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
    if size is not None and size >= int(policy["large_file_threshold_bytes"]):
        return "large_optional"
    if (
        name in {"run_config.json", "summary.json", "run_manifest.json"}
        or name.endswith("_summary.json")
        or "metrics" in name
        or "particle_state" in name
        or "particle_events" in name
        or name == "retention_actions.json"
        or suffix in {".log", ".txt"}
    ):
        return "required_evidence"
    return "lightweight_optional"


def is_recoverable_native_trace(path: Path) -> bool:
    """Recognize the one native TRACE shape eligible for failed-run recovery."""

    return (
        path.parent.name.lower() == "logs"
        and fnmatch.fnmatch(path.name.lower(), "simion__batch*.trace.log")
    )


def is_recoverable_simion_batch_log(path: Path) -> bool:
    """Recognize governed pre-pulse TRACE or continuous full-flight stdout."""

    return is_recoverable_native_trace(path) or (
        path.parent.name.lower() == "logs"
        and fnmatch.fnmatch(path.name.lower(), "simion__batch*.stdout.log")
    )


def _has_native_completion_sentinel(path: Path) -> bool:
    """Check the final nonempty line without loading a potentially huge TRACE."""

    with path.open("rb") as stream:
        stream.seek(0, 2)
        position = stream.tell()
        tail = bytearray()
        while position > 0 and tail.count(b"\n") < 2:
            chunk_size = min(4096, position)
            position -= chunk_size
            stream.seek(position)
            tail[:0] = stream.read(chunk_size)
    lines = [line.strip() for line in bytes(tail).splitlines() if line.strip()]
    if not lines:
        return False
    if is_recoverable_native_trace(path):
        return lines[-1] == b"status,Fly completed."
    return lines[-1].startswith(b"status,Fly completed.")


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
        or not isinstance(action.get("preserved", []), list)
    ):
        raise ValueError("failed-run retention actions differ")
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
            or not is_recoverable_simion_batch_log(path)
            or not _has_native_completion_sentinel(path)
            or record["action"] not in {
                "retained_completed_native_trace_for_recovery",
                "retained_completed_simion_batch_log_for_recovery",
            }
            or (
                record["action"] == "retained_completed_native_trace_for_recovery"
                and not is_recoverable_native_trace(path)
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


def apply_retention(
    run_config_path: Path, *, preserve_paths: Iterable[Path] = (),
    remove_paths: Iterable[Path] = (),
) -> Path:
    """Remove only future-run files forbidden by its frozen retention class."""

    run_dir, retention = load_run_retention(run_config_path)
    if run_dir.parent.name != "runs":
        raise ValueError("run_config must be a direct child of a runs/<run_id> directory")
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("status") in {"success", "failed", "superseded"}:
            raise ValueError("retention cannot modify a run with a terminal manifest")
    policy = load_policy()
    allowed = set(policy["classes"][retention.class_id]["allowed_roles"])
    action_path = run_dir / "retention_actions.json"
    preserved_paths = {path.resolve() for path in preserve_paths}
    remove_paths = {path.resolve() for path in remove_paths}
    if preserved_paths & remove_paths:
        raise ValueError("retention cannot both preserve and remove one path")
    for path in preserved_paths | remove_paths:
        try:
            path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("retention preserve path escapes run directory") from exc
        if not path.is_file() or not is_recoverable_simion_batch_log(path):
            raise ValueError("retention may target only a run-local native TRACE")
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
            path.unlink()
            removed.append(record)
            continue
        if path.resolve() in preserved_paths:
            preserved.append({
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": path.stat().st_size,
                "retention_role": role,
                "action": (
                    "retained_completed_native_trace_for_recovery"
                    if is_recoverable_native_trace(path)
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
        path.unlink()
        removed.append(record)
    action = {
        "schema_version": 1,
        "role": "artifact_retention_actions",
        "retention_class": retention.class_id,
        "removed_file_count": len(removed),
        "removed_bytes": sum(int(item["bytes"]) for item in removed),
        "removed": removed,
        "preserved": preserved,
    }
    action_path.write_text(
        json.dumps(action, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return action_path


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--run-config", required=True, type=Path)
    apply_parser.add_argument("--preserve-path", action="append", type=Path, default=[])
    apply_parser.add_argument("--remove-path", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.command == "apply":
        action_path = apply_retention(
            args.run_config,
            preserve_paths=args.preserve_path,
            remove_paths=args.remove_path,
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
