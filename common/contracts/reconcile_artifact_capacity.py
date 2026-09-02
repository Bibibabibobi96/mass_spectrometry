"""Keep an artifact scope below a governed capacity watermark.

The gate is deliberately conservative.  It only ever removes reconstructible
material.  Candidates receive a deletion priority from the checked-in policy:
lower-priority material is evicted first, then the oldest item within that
same priority.  Formal evidence, active runs, and explicitly protected paths
are never candidates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from common.contracts import reconcile_interrupted_compact_runs as compact
from common.contracts.artifact_retention import apply_retention

GIB = 1024**3
# Run manifests in this repository publish successful solver work as
# ``success``. Terminal runs cannot keep a reconstructible cache active.
TERMINAL = {"success", "completed", "failed", "interrupted", "cancelled", "aborted"}
CACHE_KEY = re.compile(r"\b[a-f0-9]{64}\b", re.IGNORECASE)
POLICY_PATH = Path(__file__).with_name("artifact_capacity_policy.json")


def _capacity_policy() -> dict[str, Any]:
    """Load and minimally validate the versioned repository eviction policy."""

    policy = _load_object(POLICY_PATH)
    if policy is None or int(policy.get("schema_version", 0)) != 1:
        raise RuntimeError(f"invalid artifact-capacity policy: {POLICY_PATH}")
    roles = policy.get("l2_role_deletion_priorities")
    if not isinstance(roles, dict):
        raise RuntimeError(f"invalid L2 role priorities in {POLICY_PATH}")
    for field in ("default_l2_deletion_priority", "l1_deletion_priority", "l3_deletion_priority"):
        if not isinstance(policy.get(field), int) or int(policy[field]) < 0:
            raise RuntimeError(f"invalid {field} in {POLICY_PATH}")
    if any(not isinstance(value, int) or value < 0 for value in roles.values()):
        raise RuntimeError(f"invalid L2 role priority in {POLICY_PATH}")
    return policy


def _deletion_priority(*, level: str, cache_role: str | None, policy: dict[str, Any]) -> int:
    """Return a policy-owned priority; unknown published roles stay conservative."""

    if level == "L1":
        return int(policy["l1_deletion_priority"])
    if level == "L3":
        return int(policy["l3_deletion_priority"])
    if level != "L2":
        raise ValueError(f"unknown artifact cleanup level: {level}")
    role_priorities = policy["l2_role_deletion_priorities"]
    return int(role_priorities.get(cache_role, policy["default_l2_deletion_priority"]))


def _directory_bytes(root: Path) -> dict[Path, int]:
    """Return inclusive byte counts for every real directory in one walk.

    Capacity planning needs both the whole artifact footprint and individual
    cache footprints.  Re-walking each cache made a dry-run scale with the
    number of cache keys.  A bottom-up walk preserves the exact file and
    symlink rules while sharing that I/O across all candidates.
    """
    sizes: dict[Path, int] = {}

    def measure(directory: Path) -> int:
        """Measure once with DirEntry's cached type/stat information.

        This is the bounded slow path: no valid conservative upper bound is
        available, so the gate must inspect the artifact tree before it may
        remove anything.  ``os.walk`` reconstructs paths and performs fresh
        metadata lookups for every file; on the large PA cache that makes an
        otherwise single walk unnecessarily slow.  ``scandir`` retains the
        same no-symlink accounting rule while avoiding those extra lookups.
        """
        total = 0
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    total += measure(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
        sizes[directory] = total
        return total

    measure(root)
    return sizes


def _load_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _active_cache_keys(root: Path) -> set[str]:
    """Keys mentioned by a non-terminal run are protected from L2 cleanup."""

    protected: set[str] = set()
    for manifest in root.rglob("run_manifest.json"):
        document = _load_object(manifest)
        if document is None or str(document.get("status", "")).lower() in TERMINAL:
            continue
        try:
            protected.update(CACHE_KEY.findall(manifest.read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeDecodeError):
            continue
    return {key.lower() for key in protected}


def _is_formal(path: Path) -> bool:
    return any(part.lower() == "formal" for part in path.parts)


def _protected(path: Path, protected_paths: Iterable[Path]) -> bool:
    return any(path == item or item in path.parents or path in item.parents for item in protected_paths)


def _cache_candidate(cache_key_dir: Path, protected_keys: set[str], now: float, staging_grace_seconds: int,
                     protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
                     policy: dict[str, Any]) -> dict[str, Any] | None:
    if _is_formal(cache_key_dir) or _protected(cache_key_dir, protected_paths):
        return None
    name = cache_key_dir.name.lower()
    mtime = cache_key_dir.stat().st_mtime
    payload = {"path": str(cache_key_dir), "bytes": directory_bytes.get(cache_key_dir, 0), "timestamp": mtime}
    if name.startswith("b-") and not (cache_key_dir / "cache_manifest.json").exists():
        if now - mtime >= staging_grace_seconds:
            payload.update(level="L1", reason="old_unpublished_cache_staging",
                           deletion_priority=_deletion_priority(level="L1", cache_role=None, policy=policy))
            return payload
        return None
    if not CACHE_KEY.fullmatch(name) or name in protected_keys:
        return None
    pointer = cache_key_dir / "current_generation.json"
    if not pointer.is_file():
        return None
    selected = _load_object(pointer)
    relative = selected.get("generation_relative_path") if selected else None
    published = cache_key_dir / str(relative) / "cache_manifest.json" if isinstance(relative, str) else None
    manifest = _load_object(published) if published and published.is_file() else None
    generation = Path(relative).name if isinstance(relative, str) else ""
    verified = bool(manifest and int(manifest.get("schema_version", 0)) >= 3
                    and str(manifest.get("cache_key", "")).lower() == name
                    and str(manifest.get("generation_sha256", "")) == generation)
    if not verified:
        # A malformed pointer or selected generation is an incomplete cache,
        # not a published L2 object.  It is only eligible as L1 and never if
        # a caller explicitly pins the key.
        payload.update(level="L1", reason="damaged_or_incomplete_cache_generation",
                       deletion_priority=_deletion_priority(level="L1", cache_role=None, policy=policy))
        return payload
    payload["timestamp"] = published.stat().st_mtime  # legacy publication-time fallback
    cache_role = str(manifest.get("role", cache_key_dir.parent.name))
    payload.update(level="L2", reason="inactive_reconstructible_published_cache", cache_role=cache_role,
                   deletion_priority=_deletion_priority(level="L2", cache_role=cache_role, policy=policy))
    return payload


def _cache_candidates(root: Path, protected_keys: set[str], now: float, staging_grace_seconds: int,
                      protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
                      policy: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for cache_root in root.rglob("cache"):
        if not cache_root.is_dir() or _is_formal(cache_root):
            continue
        for role_dir in cache_root.iterdir():
            if not role_dir.is_dir() or _is_formal(role_dir):
                continue
            for child in role_dir.iterdir():
                if child.is_dir():
                    candidate = _cache_candidate(child, protected_keys, now, staging_grace_seconds, protected_paths, directory_bytes, policy)
                    if candidate:
                        candidates.append(candidate)
    return candidates


def _compact_candidates(root: Path, protected_paths: Iterable[Path], policy: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for run_root in root.rglob("runs"):
        if not run_root.is_dir() or _is_formal(run_root):
            continue
        for run_dir in run_root.iterdir():
            if not run_dir.is_dir() or _protected(run_dir, protected_paths):
                continue
            try:
                report = compact.inspect_run(run_dir)
            except (AssertionError, KeyError, TypeError, ValueError):
                continue
            if report["removable_bytes"]:
                candidates.append({"level": "L3", "reason": "verified_interrupted_compact_payload",
                                   "path": str(run_dir), "bytes": int(report["removable_bytes"]),
                                   "timestamp": run_dir.stat().st_mtime, "compact_report": report,
                                   "deletion_priority": _deletion_priority(level="L3", cache_role=None, policy=policy)})
    return candidates


def plan(root: Path, *, target_bytes: int, required_headroom_bytes: int = 0,
         minimum_free_bytes: int = 0,
         staging_grace_seconds: int = 900, protected_paths: Iterable[Path] = (),
         protected_cache_keys: Iterable[str] = (),
         known_measured_bytes: int | None = None,
         maximum_new_artifact_bytes: int | None = None) -> dict[str, Any]:
    # Keep the caller's absolute spelling.  On Windows, resolve() can rewrite
    # an 8.3 temporary-root path to its long form, making the receipt disagree
    # with the paths accepted by the caller despite denoting the same cache.
    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    if (known_measured_bytes is None) != (maximum_new_artifact_bytes is None):
        raise ValueError("known capacity fast path requires both byte values")
    if known_measured_bytes is not None and (
        known_measured_bytes < 0 or maximum_new_artifact_bytes is None
        or maximum_new_artifact_bytes < 0
    ):
        raise ValueError("known capacity fast-path bytes must be nonnegative")
    protected = tuple(path.absolute() for path in protected_paths)
    # A launch receipt plus its governed maximum transient footprint supplies
    # a conservative upper bound while the shared solver lease excludes a
    # second concurrent SIMION publication.  Avoid a full artifact walk when
    # that upper bound is already safely below the watermark and the physical
    # disk floor is met.  This is an optimization only: uncertainty falls back
    # to the existing exhaustive, level-then-age planner.
    free_bytes = shutil.disk_usage(root).free
    if (
        known_measured_bytes is not None
        and known_measured_bytes + maximum_new_artifact_bytes + required_headroom_bytes
        <= target_bytes
        and free_bytes >= minimum_free_bytes
    ):
        upper_bound = known_measured_bytes + maximum_new_artifact_bytes
        return {
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "free_bytes_before": free_bytes, "staging_grace_seconds": staging_grace_seconds,
            "protected_paths": [str(path) for path in protected],
            "protected_cache_keys": sorted(str(key).lower() for key in protected_cache_keys),
            "measurement_mode": "SAFE_NO_RECONCILIATION",
            "known_measured_bytes": known_measured_bytes,
            "maximum_new_artifact_bytes": maximum_new_artifact_bytes,
            "estimated_upper_bound_bytes": upper_bound,
            "free_deficit_bytes": 0, "measured_bytes": known_measured_bytes,
            "limit_bytes": target_bytes - required_headroom_bytes,
            "active_cache_key_count": None, "candidate_count": 0,
            "planned": [], "projected_bytes": upper_bound, "satisfied": True,
        }
    directory_bytes = _directory_bytes(root)
    measured = directory_bytes[root]
    if minimum_free_bytes < 0:
        raise ValueError("minimum free bytes must be nonnegative")
    free_bytes = shutil.disk_usage(root).free
    # A current full measurement can close the ordinary no-cleanup case without
    # enumerating cache manifests or interrupted runs.  apply() repeats this
    # measurement immediately before publication; if the state changed, it
    # falls through to the established L1/L2/L3 planner below.
    if (
        measured + required_headroom_bytes <= target_bytes
        and free_bytes >= minimum_free_bytes
    ):
        return {
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "free_bytes_before": free_bytes, "staging_grace_seconds": staging_grace_seconds,
            "protected_paths": [str(path) for path in protected],
            "protected_cache_keys": sorted(
                str(key).lower() for key in protected_cache_keys
            ),
            "measurement_mode": "FULL_NO_RECONCILIATION",
            "free_deficit_bytes": 0, "measured_bytes": measured,
            "limit_bytes": target_bytes - required_headroom_bytes,
            "active_cache_key_count": None, "candidate_count": 0,
            "planned": [], "projected_bytes": measured, "satisfied": True,
        }
    now = time.time()
    policy = _capacity_policy()
    active_keys = _active_cache_keys(root)
    active_keys.update(key.lower() for key in protected_cache_keys if CACHE_KEY.fullmatch(key))
    candidates = _cache_candidates(root, active_keys, now, staging_grace_seconds, protected, directory_bytes, policy)
    candidates.extend(_compact_candidates(root, protected, policy))
    candidates.sort(key=lambda item: (item["deletion_priority"], item["timestamp"], item["path"]))
    free_deficit = max(0, minimum_free_bytes - free_bytes)
    # Every byte removed from this artifact root returns one byte to the same
    # volume.  Intersect the repository watermark with the physical-free-space
    # requirement so the existing L1/L2/L3 ordering remains the sole deletion
    # policy.
    limit = min(target_bytes - required_headroom_bytes, measured - free_deficit)
    planned: list[dict[str, Any]] = []
    projected = measured
    for candidate in candidates:
        if projected <= limit:
            break
        planned.append(candidate)
        projected -= candidate["bytes"]
    return {"schema_version": 1, "role": "artifact_capacity_gate", "artifact_root": str(root),
            "target_bytes": target_bytes, "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes, "free_bytes_before": free_bytes,
            "staging_grace_seconds": staging_grace_seconds,
            "protected_paths": [str(path) for path in protected],
            "protected_cache_keys": sorted(active_keys),
            "free_deficit_bytes": free_deficit,
            "measured_bytes": measured, "limit_bytes": limit, "active_cache_key_count": len(active_keys),
            "candidate_count": len(candidates), "planned": planned, "projected_bytes": projected,
            "satisfied": projected <= limit}


def _remove_tree(path: Path) -> None:
    def onerror(function: Any, value: str, _: Any) -> None:
        os.chmod(value, stat.S_IWRITE)
        function(value)
    shutil.rmtree(path, onerror=onerror)


def apply(receipt: dict[str, Any]) -> dict[str, Any]:
    # Active SIMION does not prohibit cleanup: plan() excludes every cache key
    # mentioned by a non-terminal manifest, and the plan is refreshed here to
    # close the interval between a capacity decision and deletion.  This keeps
    # the disk floor enforceable while another independent channel is solving.
    root = Path(receipt["artifact_root"])
    if receipt.get("measurement_mode") == "FULL_NO_RECONCILIATION":
        sizes = _directory_bytes(root)
        measured_after = sizes[root]
        free_after = shutil.disk_usage(root).free
        if (
            measured_after + int(receipt["required_headroom_bytes"])
            <= int(receipt["target_bytes"])
            and free_after >= int(receipt["minimum_free_bytes"])
        ):
            outcome = dict(receipt)
            outcome.update(
                applied=True, removed=[], removed_bytes=0,
                measured_after_bytes=measured_after,
                free_bytes_after=free_after,
                satisfied_after_apply=True,
            )
            return outcome
    if receipt.get("measurement_mode") == "SAFE_NO_RECONCILIATION":
        outcome = dict(receipt)
        outcome.update(
            applied=True, removed=[], removed_bytes=0,
            measured_after_bytes=receipt["known_measured_bytes"],
            estimated_upper_bound_after_bytes=receipt["estimated_upper_bound_bytes"],
            free_bytes_after=shutil.disk_usage(root).free,
            satisfied_after_apply=True,
        )
        return outcome
    receipt = plan(
        root,
        target_bytes=int(receipt["target_bytes"]),
        required_headroom_bytes=int(receipt["required_headroom_bytes"]),
        minimum_free_bytes=int(receipt["minimum_free_bytes"]),
        staging_grace_seconds=int(receipt.get("staging_grace_seconds", 900)),
        protected_paths=(Path(path) for path in receipt.get("protected_paths", ())),
        protected_cache_keys=receipt.get("protected_cache_keys", ()),
    )
    removed: list[dict[str, Any]] = []
    for item in receipt["planned"]:
        path = Path(item["path"])
        if item["level"] in {"L1", "L2"}:
            _remove_tree(path)
        else:
            actions = apply_retention(path / "run_config.json")
            removed.append({"path": str(path), "level": item["level"], "bytes": item["bytes"],
                            "retention_actions": str(actions)})
            continue
        removed.append({"path": str(path), "level": item["level"], "bytes": item["bytes"]})
    receipt = dict(receipt)
    receipt["applied"] = True
    receipt["removed"] = removed
    receipt["removed_bytes"] = sum(item["bytes"] for item in removed)
    receipt["measured_after_bytes"] = _directory_bytes(Path(receipt["artifact_root"]))[
        Path(receipt["artifact_root"])
    ]
    receipt["free_bytes_after"] = shutil.disk_usage(Path(receipt["artifact_root"])).free
    receipt["satisfied_after_apply"] = (
        receipt["measured_after_bytes"] + receipt["required_headroom_bytes"] <= receipt["target_bytes"]
        and receipt["free_bytes_after"] >= receipt["minimum_free_bytes"]
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--target-gib", type=float, default=500.0)
    parser.add_argument("--required-headroom-bytes", type=int, default=0)
    parser.add_argument("--minimum-free-gib", type=float, default=500.0)
    parser.add_argument("--staging-grace-seconds", type=int, default=900)
    parser.add_argument("--protect-path", action="append", type=Path, default=[])
    parser.add_argument("--protect-cache-key", action="append", default=[])
    parser.add_argument("--known-measured-bytes", type=int)
    parser.add_argument("--maximum-new-artifact-bytes", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if (args.target_gib <= 0 or args.required_headroom_bytes < 0 or
            args.minimum_free_gib < 0 or args.staging_grace_seconds < 0):
        parser.error("capacity values must be nonnegative and target positive")
    receipt = plan(args.artifact_root, target_bytes=int(args.target_gib * GIB),
                   required_headroom_bytes=args.required_headroom_bytes,
                   minimum_free_bytes=int(args.minimum_free_gib * GIB),
                   staging_grace_seconds=args.staging_grace_seconds, protected_paths=args.protect_path,
                   protected_cache_keys=args.protect_cache_key,
                   known_measured_bytes=args.known_measured_bytes,
                   maximum_new_artifact_bytes=args.maximum_new_artifact_bytes)
    if args.apply:
        receipt = apply(receipt)
        satisfied = receipt["satisfied_after_apply"]
    else:
        satisfied = receipt["satisfied"]
    print(json.dumps(receipt, indent=2))
    if not satisfied:
        sys.exit(2)


if __name__ == "__main__":
    main()
