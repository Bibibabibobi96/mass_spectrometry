"""Compute stable file content identities for repository machine contracts."""

from __future__ import annotations

import argparse
import json
from os import PathLike
from pathlib import Path
from typing import Any, Iterable, TypeAlias

import hashlib


FilePath: TypeAlias = str | PathLike[str]
HASH_CHUNK_BYTES = 1024 * 1024


from msplatform.io.file_identity import file_sha256, canonical_json_sha256 as canonical_json_sha256


from msplatform.execution.file_identity import (
    FileIdentityGuard as FileIdentityGuard,
    guarded_file_identity as guarded_file_identity,
    file_sha256_unbuffered as file_sha256_unbuffered,
    _windows_file_api as _windows_file_api,
)


def repository_text_sha256(path: FilePath) -> str:
    """Hash Git-managed UTF-8 text after canonical CRLF/CR to LF conversion.

    This identity is only for repository text authorities.  Solver outputs,
    manifests, frozen run inputs and other artifacts must continue to use
    :func:`file_sha256` so their original bytes remain auditable.
    """
    payload = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(payload).hexdigest().upper()




def files_have_same_identity(left: FilePath, right: FilePath) -> bool:
    """Compare two artifact files by byte length and SHA-256 content identity."""
    left_path = Path(left)
    right_path = Path(right)
    return left_path.stat().st_size == right_path.stat().st_size and file_sha256(
        left_path
    ) == file_sha256(right_path)


def files_match_manifest_records(root: FilePath, records: Iterable[dict[str, Any]]) -> bool:
    """Return whether every simple-name manifest record matches bytes and SHA-256.

    This is the shared byte-identity primitive for reusable artifacts.  It is
    deliberately limited to direct files below *root*: callers decide the
    semantic identity of an artifact, while this function answers only whether
    its already-declared payload is still the same.
    """
    directory = Path(root).resolve()
    seen: set[str] = set()
    records = list(records)
    if not records:
        return False
    for record in records:
        if not isinstance(record, dict):
            return False
        name = record.get("name")
        expected_size = record.get("bytes")
        expected_hash = record.get("sha256")
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or name in seen
            or not isinstance(expected_size, int)
            or expected_size < 0
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
        ):
            return False
        seen.add(name)
        payload = directory / name
        if (
            not payload.is_file()
            or payload.stat().st_size != expected_size
            or file_sha256(payload).upper() != expected_hash.upper()
        ):
            return False
    return True


def _main() -> int:
    parser = argparse.ArgumentParser(description="Verify manifest-recorded file bytes and SHA-256.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--manifest", type=Path)
    mode.add_argument("--left", type=Path)
    mode.add_argument("--unbuffered", type=Path)
    parser.add_argument("--right", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--records-key", default="files")
    args = parser.parse_args()
    if args.unbuffered is not None:
        if args.right is not None or args.root is not None:
            parser.error("--unbuffered accepts neither --right nor --root")
        print(file_sha256_unbuffered(args.unbuffered))
        return 0
    if args.left is not None:
        if args.right is None:
            parser.error("--left requires --right")
        if files_have_same_identity(args.left, args.right):
            print("FILE_IDENTITY_PAIR=PASS")
            return 0
        print("FILE_IDENTITY_PAIR=FAIL")
        return 1
    if args.root is None:
        parser.error("--manifest requires --root")
    document = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    records = document.get(args.records_key) if isinstance(document, dict) else None
    if not isinstance(records, list) or not files_match_manifest_records(args.root, records):
        print("FILE_IDENTITY_RECORDS=FAIL")
        return 1
    print(f"FILE_IDENTITY_RECORDS=PASS COUNT={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
