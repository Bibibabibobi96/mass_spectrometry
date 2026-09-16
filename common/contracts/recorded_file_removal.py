"""Execute exact, identity-bound file removals; callers own admission and receipts."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator

if __package__:
    from .file_identity import file_sha256
else:
    from file_identity import file_sha256


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """Flush a complete JSON record before atomically publishing it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def remove_recorded_files(
    root: Path, records: Iterable[dict[str, Any]], *, missing_ok: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield each removed record after size/SHA revalidation; never scan for files.

    Callers must durably publish the planned identities before iterating, and
    publish their own progress/terminal schema. Missing-file tolerance is only
    for concurrent disposal of already audited capacity candidates.
    """
    root = root.resolve()
    for record in records:
        path = root / record["path"]
        path.resolve().relative_to(root)
        if path.is_symlink():
            raise ValueError(f"recorded removal is a symbolic link: {path}")
        if missing_ok and not path.exists():
            continue
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or file_sha256(path) != record["sha256"]):
            raise ValueError(f"recorded removal file identity changed: {path}")
        try:
            try:
                path.unlink()
            except PermissionError:
                path.chmod(path.stat().st_mode | stat.S_IWRITE)
                path.unlink()
        except FileNotFoundError:
            if missing_ok:
                continue
            raise
        yield record
