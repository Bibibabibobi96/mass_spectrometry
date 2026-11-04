"""Content identity for explicit files, independent of repository and host state."""
from __future__ import annotations

import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any, TypeAlias

FilePath: TypeAlias = str | PathLike[str]
HASH_CHUNK_BYTES = 1024 * 1024


def file_sha256(path: FilePath) -> str:
    """Return the uppercase SHA-256 hex digest of a file, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(HASH_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_json_sha256(value: Any) -> str:
    """Return the SHA-256 for finite canonical compact JSON content.

    This identity is for JSON values, not files.  It fixes object-key order,
    UTF-8 encoding and separators so independent contract consumers derive the
    same identity without owning another serialization recipe.
    """

    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("value is not canonical finite JSON") from error
    return hashlib.sha256(payload).hexdigest().upper()
