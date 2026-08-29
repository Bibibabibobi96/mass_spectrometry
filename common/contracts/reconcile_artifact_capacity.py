"""Keep an artifact scope below a governed capacity watermark.

The gate is deliberately conservative.  It only ever removes three classes
of reconstructible material, in this exact order: (L1) old unpublished cache
staging, (L2) inactive published non-Formal cache keys, and (L3) forbidden
payload in verified interrupted compact runs.  Within each class candidates
are ordered oldest first.  Formal evidence, active runs, and explicitly
protected paths are never candidates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from common.contracts import reconcile_interrupted_compact_runs as compact
from common.contracts.artifact_retention import apply_retention

GIB = 1024**3
TERMINAL = {"completed", "failed", "interrupted", "cancelled", "aborted"}
CACHE_KEY = re.compile(r"\b[a-f0-9]{64}\b", re.IGNORECASE)


def _tree_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())


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


def _has_active_simion() -> bool:
    if os.name != "nt":
        return False
    listing = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], cwd=Path.cwd(), text=True, capture_output=True,
                             encoding="utf-8", errors="replace", check=False, timeout=15)
    if listing.returncode != 0:
        raise RuntimeError("cannot establish that SIMION is inactive")
    return any(line.lower().startswith('"simion') for line in listing.stdout.splitlines())


def _is_formal(path: Path) -> bool:
    return any(part.lower() == "formal" for part in path.parts)


def _protected(path: Path, protected_paths: Iterable[Path]) -> bool:
    return any(path == item or item in path.parents or path in item.parents for item in protected_paths)


def _cache_candidate(cache_key_dir: Path, protected_keys: set[str], now: float, staging_grace_seconds: int,
                     protected_paths: Iterable[Path]) -> dict[str, Any] | None:
    if _is_formal(cache_key_dir) or _protected(cache_key_dir, protected_paths):
        return None
    name = cache_key_dir.name.lower()
    mtime = cache_key_dir.stat().st_mtime
    payload = {"path": str(cache_key_dir), "bytes": _tree_bytes(cache_key_dir), "timestamp": mtime}
    if name.startswith("b-") and not (cache_key_dir / "cache_manifest.json").exists():
        if now - mtime >= staging_grace_seconds:
            payload.update(level="L1", reason="old_unpublished_cache_staging")
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
        payload.update(level="L1", reason="damaged_or_incomplete_cache_generation")
        return payload
    payload["timestamp"] = published.stat().st_mtime  # legacy publication-time fallback
    payload.update(level="L2", reason="inactive_reconstructible_published_cache")
    return payload


def _cache_candidates(root: Path, protected_keys: set[str], now: float, staging_grace_seconds: int,
                      protected_paths: Iterable[Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for cache_root in root.rglob("cache"):
        if not cache_root.is_dir() or _is_formal(cache_root):
            continue
        for role_dir in cache_root.iterdir():
            if not role_dir.is_dir() or _is_formal(role_dir):
                continue
            for child in role_dir.iterdir():
                if child.is_dir():
                    candidate = _cache_candidate(child, protected_keys, now, staging_grace_seconds, protected_paths)
                    if candidate:
                        candidates.append(candidate)
    return candidates


def _compact_candidates(root: Path, protected_paths: Iterable[Path]) -> list[dict[str, Any]]:
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
                                   "timestamp": run_dir.stat().st_mtime, "compact_report": report})
    return candidates


def plan(root: Path, *, target_bytes: int, required_headroom_bytes: int = 0,
         minimum_free_bytes: int = 0,
         staging_grace_seconds: int = 900, protected_paths: Iterable[Path] = (),
         protected_cache_keys: Iterable[str] = ()) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    protected = tuple(path.resolve() for path in protected_paths)
    now = time.time()
    active_keys = _active_cache_keys(root)
    active_keys.update(key.lower() for key in protected_cache_keys if CACHE_KEY.fullmatch(key))
    candidates = _cache_candidates(root, active_keys, now, staging_grace_seconds, protected)
    candidates.extend(_compact_candidates(root, protected))
    candidates.sort(key=lambda item: ({"L1": 1, "L2": 2, "L3": 3}[item["level"]], item["timestamp"], item["path"]))
    measured = _tree_bytes(root)
    if minimum_free_bytes < 0:
        raise ValueError("minimum free bytes must be nonnegative")
    free_bytes = shutil.disk_usage(root).free
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
    if _has_active_simion():
        raise RuntimeError("refusing capacity cleanup while SIMION is active")
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
    receipt["measured_after_bytes"] = _tree_bytes(Path(receipt["artifact_root"]))
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
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if (args.target_gib <= 0 or args.required_headroom_bytes < 0 or
            args.minimum_free_gib < 0 or args.staging_grace_seconds < 0):
        parser.error("capacity values must be nonnegative and target positive")
    receipt = plan(args.artifact_root, target_bytes=int(args.target_gib * GIB),
                   required_headroom_bytes=args.required_headroom_bytes,
                   minimum_free_bytes=int(args.minimum_free_gib * GIB),
                   staging_grace_seconds=args.staging_grace_seconds, protected_paths=args.protect_path,
                   protected_cache_keys=args.protect_cache_key)
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
