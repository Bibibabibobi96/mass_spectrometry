"""Compute stable file content identities for repository machine contracts."""

from __future__ import annotations

import argparse
import json
import os
from os import PathLike
from pathlib import Path
from typing import Any, Iterable, TypeAlias

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


def _windows_file_api() -> Any:
    """Bind only the synchronous Win32 calls used by unbuffered hashing."""
    import ctypes
    from ctypes import wintypes as w

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateFileW": ([w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
        "GetFileSizeEx": ([w.HANDLE, ctypes.POINTER(ctypes.c_longlong)], w.BOOL),
        "GetFileInformationByHandleEx": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
        "VirtualAlloc": ([w.LPVOID, ctypes.c_size_t, w.DWORD, w.DWORD], w.LPVOID),
        "VirtualFree": ([w.LPVOID, ctypes.c_size_t, w.DWORD], w.BOOL),
        "ReadFile": ([w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID], w.BOOL),
        "CloseHandle": ([w.HANDLE], w.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


def file_sha256_unbuffered(path: FilePath) -> str:
    """Hash a closed Windows file once, bypassing the system data cache.

    Explicit opt-in for large PA owners; no fallback to buffered reads. The
    read-only, share-read handle excludes ordinary writers and replacement.
    This does not flush dirty data or establish hardware durability. Callers
    still own solver completion and mapped-writer exclusion. See README's
    Microsoft API references for alignment and EOF rules (Windows 8+).
    """
    if os.name != "nt":
        raise OSError("unbuffered file identity requires Windows 8 or later")
    import ctypes
    from ctypes import wintypes as w

    api = _windows_file_api()
    # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_FLAG_NO_BUFFERING.
    handle = api.CreateFileW(str(Path(path).resolve()), 0x80000000, 1, None, 3, 0x20000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    allocation = None
    try:
        size = ctypes.c_longlong()
        if not api.GetFileSizeEx(handle, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        # FILE_STORAGE_INFO is seven ULONGs; the first four are sector sizes.
        storage = (w.DWORD * 7)()
        if not api.GetFileInformationByHandleEx(handle, 16, ctypes.byref(storage), ctypes.sizeof(storage)):
            raise ctypes.WinError(ctypes.get_last_error())
        sectors = list(storage[:4])
        if any(value <= 0 or value & (value - 1) for value in sectors):
            raise OSError("file storage reports unsupported sector alignment")
        alignment = max(sectors)
        chunk = max(HASH_CHUNK_BYTES, alignment)
        if chunk > 0xFFFFFFFF:
            raise OSError("file storage alignment exceeds a ReadFile request")
        # Allocate extra space and align explicitly even if sectors exceed pages.
        allocation = api.VirtualAlloc(None, chunk + alignment - 1, 0x3000, 0x04)
        if not allocation:
            raise ctypes.WinError(ctypes.get_last_error())
        address = (allocation + alignment - 1) & ~(alignment - 1)
        buffer = (ctypes.c_ubyte * chunk).from_address(address)
        digest = hashlib.sha256()
        remaining = size.value
        while remaining:
            request = min(chunk, ((remaining + alignment - 1) // alignment) * alignment)
            received = w.DWORD()
            if not api.ReadFile(handle, address, request, ctypes.byref(received), None):
                raise ctypes.WinError(ctypes.get_last_error())
            expected = min(request, remaining)
            if received.value != expected:
                raise OSError(f"unbuffered file read was short: expected {expected}, got {received.value}")
            digest.update(memoryview(buffer).cast("B")[:received.value])
            remaining -= received.value
        return digest.hexdigest().upper()
    finally:
        try:
            if allocation and not api.VirtualFree(allocation, 0, 0x8000):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if not api.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


def repository_text_sha256(path: FilePath) -> str:
    """Hash Git-managed UTF-8 text after canonical CRLF/CR to LF conversion.

    This identity is only for repository text authorities.  Solver outputs,
    manifests, frozen run inputs and other artifacts must continue to use
    :func:`file_sha256` so their original bytes remain auditable.
    """
    payload = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(payload).hexdigest().upper()


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
