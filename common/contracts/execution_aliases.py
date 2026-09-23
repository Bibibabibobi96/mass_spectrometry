"""Validate Windows execution aliases without traversing their targets."""

from __future__ import annotations

import stat
from pathlib import Path


def execution_alias_root_is_valid(root: Path, path: Path) -> bool:
    """Return whether direct children are internal directory junctions."""

    root_resolved = root.resolve(strict=False)
    for alias in sorted(path.iterdir()):
        try:
            # A target can disappear after an interrupted workflow.  The
            # junction itself remains a bounded, owner-managed alias and must
            # stay visible to maintenance so that it can be retired safely.
            target = alias.resolve(strict=False)
            target.relative_to(root_resolved)
        except (OSError, RuntimeError, ValueError):
            return False
        attributes = getattr(alias.lstat(), "st_file_attributes", 0)
        if not (attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return False
    return True
