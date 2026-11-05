"""Freeze selected small inputs; native payload families keep their own owner."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from .manifest_records import file_record, verify_record


def freeze_file(source: Path, destination: Path, *, retention_classifier: Any = None) -> dict[str, Any]:
    """Copy exact input bytes to a caller-selected, previously absent path.

    The caller creates the parent. This is the existing small-input primitive;
    solver-native payloads use their dedicated owner mechanisms.
    """
    if destination.exists():
        raise FileExistsError(destination)
    before = file_record(source.resolve(), retention_classifier=retention_classifier)
    shutil.copyfile(source, destination)
    verify_record("frozen input", {**before, "path": str(destination)},
                  retention_classifier=retention_classifier)
    return {**before, "path": str(destination.resolve()), "source_path": str(source.resolve())}
