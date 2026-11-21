"""Validate bounded directory-junction structure without inspecting targets.

Structure grants no source consumption, write or cleanup authority. The workflow
owner separately validates frozen references, active protection and alias owner.
"""
from __future__ import annotations
import os
import stat
from pathlib import Path


def execution_alias_root_is_valid(root: Path, path: Path) -> bool:
    """Accept direct absolute directory junctions, including explicit cross-root targets.

    root remains part of the callers' existing API; target location is not a
    structural permission. No target inventory or payload accounting occurs here.
    """
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    mount_point = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & reparse:
            return False
        for alias in path.iterdir():
            info = alias.lstat()
            if (not stat.S_ISDIR(info.st_mode)
                    or not getattr(info, "st_file_attributes", 0) & reparse
                    or getattr(info, "st_reparse_tag", None) != mount_point
                    or not Path(os.readlink(alias)).is_absolute()):
                return False
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def reconcile_execution_alias_root(root: Path) -> dict[str, int]:
    """Correct only the recorded zero-byte junction range, without scanning targets."""
    from msplatform.execution import capacity_ledger

    alias_root = root / "common" / "execution_aliases"
    if not alias_root.exists():
        return {"corrected_count": 0, "released_bytes": 0}
    if not execution_alias_root_is_valid(root, alias_root):
        raise RuntimeError("execution alias root is not a bounded directory junction set")
    ledger = capacity_ledger.load_capacity_ledger(root)
    if ledger is None:
        raise RuntimeError("capacity ledger is missing or invalid")
    recorded = next((
        item for item in ledger["objects"]
        if item.get("path") == "common/execution_aliases" and item.get("status") != "retired"
    ), None)
    if recorded is None:
        raise RuntimeError("execution alias root is absent from the calibrated ledger")
    if recorded.get("class") != "light_evidence" or recorded.get("owner") != "common.run_artifact_support":
        raise RuntimeError("execution alias root has an unexpected ledger identity")
    stale_count = 0
    for alias in alias_root.iterdir():
        try:
            internal_target = alias.resolve(strict=False).is_relative_to(root.resolve())
        except (OSError, RuntimeError, ValueError):
            internal_target = False
        if internal_target and not alias.exists():
            alias.rmdir()
            stale_count += 1
    previous_bytes = int(recorded["bytes"])
    if previous_bytes:
        capacity_ledger.record_capacity_object(
            root, path=alias_root, object_class="light_evidence", bytes_count=0,
            owner="common.run_artifact_support",
        )
    return {
        "corrected_count": int(previous_bytes != 0) + stale_count,
        "released_bytes": previous_bytes,
    }
