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


def validate_retained_files(
    retention: Retention,
    files: Iterable[Path],
    *,
    policy: dict[str, Any] | None = None,
) -> list[tuple[Path, str]]:
    """Return classified files or fail if the selected class forbids one."""

    policy = policy or load_policy()
    allowed = set(policy["classes"][retention.class_id]["allowed_roles"])
    classified = [(path, classify_file(path, policy=policy)) for path in files]
    forbidden = [(path, role) for path, role in classified if role not in allowed]
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


def apply_retention(run_config_path: Path) -> Path:
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
    removed: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if (
            not path.is_file()
            or path.is_symlink()
            or path in {action_path, manifest_path}
        ):
            continue
        role = classify_file(path, policy=policy)
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
    args = parser.parse_args()
    if args.command == "apply":
        action_path = apply_retention(args.run_config)
        action = json.loads(action_path.read_text(encoding="utf-8"))
        print(
            "ARTIFACT_RETENTION=PASS "
            f"CLASS={action['retention_class']} "
            f"REMOVED_FILES={action['removed_file_count']} "
            f"REMOVED_BYTES={action['removed_bytes']}"
        )


if __name__ == "__main__":
    main()
