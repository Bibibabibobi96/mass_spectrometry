"""Freeze explicitly selected small inputs with their original byte identity."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record


def freeze_file(source: Path, destination: Path) -> dict[str, Any]:
    """Copy a small input and return its destination record plus source_path.

    The caller selects paths and creates the destination parent. Existing
    destinations, missing sources and copies differing from the original raw
    bytes fail; solver-native payloads use their dedicated owner mechanisms.
    """
    if destination.exists():
        raise FileExistsError(destination)
    before = file_record(source.resolve())
    shutil.copyfile(source, destination)
    verify_record("frozen input", {**before, "path": str(destination)})
    return {**before, "path": str(destination.resolve()), "source_path": str(source.resolve())}
