"""Compute stable file content identities for repository machine contracts."""

from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TypeAlias

import hashlib


FilePath: TypeAlias = str | PathLike[str]
HASH_CHUNK_BYTES = 1024 * 1024


def file_sha256(path: FilePath) -> str:
    """Return the uppercase SHA-256 hex digest of a file, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(HASH_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest().upper()
