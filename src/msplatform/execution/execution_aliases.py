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
