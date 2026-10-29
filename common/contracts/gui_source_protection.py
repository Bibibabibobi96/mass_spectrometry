"""Project current-GUI receipts into explicit source protection paths.

Capacity summaries may reuse one local snapshot. Destructive retirement reads
fresh receipts for each decision; no process-global cache can hide a new GUI
consumer between calls. This projection does not create retention authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_receipt(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def current_gui_source_paths(root: Path) -> tuple[str, ...]:
    """Read explicit current-GUI source paths for one caller-owned decision."""

    sources: set[str] = set()
    for review_root in root.glob("projects/*/reviews"):
        if not review_root.is_dir() or review_root.is_symlink():
            continue
        for package in review_root.glob("current_*"):
            if not package.is_dir() or package.is_symlink():
                continue
            for name in ("inspection_receipt.json", "release_receipt.json"):
                receipt = _load_receipt(package / name)
                if receipt is None or receipt.get("status") not in {"ready", "materialized"}:
                    continue
                source_run = receipt.get("source_run")
                if isinstance(source_run, str) and source_run:
                    sources.add(str((review_root.parent / "runs" / source_run).resolve(strict=False)))
                for value in (
                    receipt.get("trajectory_log"), receipt.get("materialization"),
                    receipt.get("observation"),
                    receipt.get("native_runtime", {}).get("checkpoint")
                    if isinstance(receipt.get("native_runtime"), dict) else None,
                ):
                    if isinstance(value, str) and value:
                        sources.add(str(Path(value).resolve(strict=False)))
    return tuple(sorted(sources))


def current_gui_source_retention(
    root: Path, target: Path, *, sources: tuple[str, ...] | None = None,
) -> bool:
    """Return whether a current GUI receipt explicitly names this source tree."""

    target_resolved = target.resolve(strict=False)
    source_paths = current_gui_source_paths(root) if sources is None else sources
    return any(
        target_resolved == Path(source) or target_resolved in Path(source).parents
        for source in source_paths
    )
