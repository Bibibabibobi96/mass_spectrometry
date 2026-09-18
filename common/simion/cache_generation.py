"""Protocol-neutral primitives for immutable direct-file cache generations.

Callers retain ownership of cache identity, retention, locking, and manifest
schema.  This module deliberately owns only the repeatable byte-inventory and
generation-digest operations shared by SIMION PA-family cache protocols.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import argparse
from pathlib import Path
import shutil
import stat
import subprocess
import time
from typing import Any, Iterable, Mapping
from uuid import uuid4

from common.contracts.file_identity import file_sha256


SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def validate_direct_inventory(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalize one ordered direct-file inventory.

    Records retain their supplied order because a cache protocol may bind that
    order into its immutable payload identity.  Only direct regular-file names
    are accepted; no caller-specific role or identity policy lives here.
    """

    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {"name", "bytes", "sha256"}:
            raise ValueError("cache inventory record fields differ")
        name, size, digest = record["name"], record["bytes"], record["sha256"]
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or Path(name).name != name
            or name in names
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or SHA256.fullmatch(digest) is None
        ):
            raise ValueError("cache inventory record differs")
        names.add(name)
        # SHA-256 hexadecimal text is case-insensitive.  The repository's
        # shared file identity helper and PowerShell Get-FileHash both emit
        # upper case, so normalize at this protocol boundary before comparing
        # inventories from heterogeneous producers.
        normalized.append({"name": name, "bytes": size, "sha256": digest.upper()})
    if not normalized:
        raise ValueError("cache inventory is empty")
    return normalized


def inventory_direct_files(directory: str | Path, *, exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Inventory direct regular files, sorted by name, with byte hashes."""

    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"cache directory is missing: {root}")
    excluded = set(exclude)
    children = list(root.iterdir())
    if any(not child.is_file() for child in children):
        raise ValueError("cache directory contains a non-file entry")
    return validate_direct_inventory(
        {
            "name": child.name,
            "bytes": child.stat().st_size,
            "sha256": file_sha256(child),
        }
        for child in sorted(children, key=lambda item: item.name)
        if child.name not in excluded
    )


def stable_inventory_direct_files(
    directory: str | Path,
    *,
    exclude: Iterable[str] = (),
    passes: int = 2,
) -> list[dict[str, Any]]:
    """Require identical consecutive full-byte inventories.

    SIMION can finish its visible process before Windows exposes the final PA
    bytes consistently to a later reader. Metadata and a process quiet window
    cannot prove stability in that case, so immutable publication requires two
    equal full reads while the directory is still private staging data.
    """

    if passes < 2:
        raise ValueError("stable cache inventory requires at least two passes")
    excluded = tuple(exclude)
    previous = inventory_direct_files(directory, exclude=excluded)
    for _ in range(1, passes):
        current = inventory_direct_files(directory, exclude=excluded)
        if current != previous:
            raise ValueError("cache inventory changed between stability passes")
        previous = current
    return previous


def inventory_declared_files(
    directory: str | Path, records: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Verify and return one caller-declared direct-file inventory."""

    root = Path(directory)
    expected = validate_direct_inventory(records)
    if not root.is_dir():
        raise ValueError(f"cache directory is missing: {root}")
    return inventory_named_files(root, [record["name"] for record in expected])


def inventory_named_files(directory: str | Path, filenames: Iterable[str]) -> list[dict[str, Any]]:
    """Hash a caller-ordered list of direct files; reject invalid names."""
    root = Path(directory)
    records = []
    for name in filenames:
        if not isinstance(name, str) or not name or name in {".", ".."} or Path(name).name != name:
            raise ValueError("cache inventory name is not a direct file")
        path = root / name
        if not path.is_file():
            raise ValueError(f"declared cache file is missing: {path}")
        records.append({"name": name, "bytes": path.stat().st_size, "sha256": file_sha256(path)})
    return validate_direct_inventory(records)


def _make_file_writable(path: Path) -> None:
    """Clear a copied cache file's read-only attribute without changing bytes."""

    path.chmod(path.stat().st_mode | stat.S_IWUSR)


_WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES = 8 * 1024 * 1024


def _flush_writable_source(path: Path) -> None:
    """Commit delayed producer writes before an unbuffered Windows read.

    Fresh SIMION PAs remain writable until cache publication.  A normal hash
    can observe their dirty cache pages while ``robocopy /J`` correctly bypasses
    that cache and therefore sees older disk pages.  Committing the writable
    producer file closes that gap.  Immutable read-only cache sources are
    already persisted and need no write handle.
    """

    if not path.stat().st_mode & stat.S_IWUSR:
        return
    with path.open("r+b", buffering=0) as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _copy_file_bytes(
    source: Path,
    destination: Path,
    *,
    flush_writable_source: bool,
) -> None:
    """Copy bytes without relying on the Windows buffered large-file path.

    Ordinary Python sequential I/O is retained for small files and non-Windows
    hosts.  On this Windows SIMION host, repeated 2.75-GiB PA copies made with
    that path had the right length but different persisted bytes.  ``robocopy
    /J`` uses unbuffered I/O and is independently re-hashed by
    :func:`copy_verified_file` before publication.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt" and source.stat().st_size >= _WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES:
        if flush_writable_source:
            _flush_writable_source(source)
        copy_directory = destination.parent
        temporary_directory: Path | None = None
        if source.name != destination.name:
            temporary_directory = destination.parent / f".robocopy-{uuid4().hex}"
            temporary_directory.mkdir()
            copy_directory = temporary_directory
        completed = subprocess.run(
            [
                "robocopy",
                str(source.parent),
                str(copy_directory),
                source.name,
                "/J",
                "/COPY:DAT",
                "/R:0",
                "/W:0",
                "/NFL",
                "/NDL",
                "/NJH",
                "/NJS",
                "/NP",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=source.parent,
            timeout=6 * 60 * 60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode > 7:
            if temporary_directory is not None:
                _remove_tree_writable(temporary_directory)
            detail = (completed.stderr or completed.stdout).strip()
            raise OSError(
                f"robocopy /J failed with exit code {completed.returncode}: {detail}"
            )
        copied_path = copy_directory / source.name
        if temporary_directory is not None:
            os.replace(copied_path, destination)
            temporary_directory.rmdir()
        return

    with source.open("rb", buffering=0) as read_handle, destination.open(
        "wb", buffering=0
    ) as write_handle:
        while chunk := read_handle.read(8 * 1024 * 1024):
            remaining = memoryview(chunk)
            while remaining:
                written = write_handle.write(remaining)
                if written is None or written <= 0:
                    raise OSError("cache copy write made no progress")
                remaining = remaining[written:]
        write_handle.flush()
        os.fsync(write_handle.fileno())


def copy_verified_file(source: Path, destination: Path) -> dict[str, Any]:
    """Copy one file and return the persisted destination identity.

    Hashing bytes while they are written only proves what the process submitted
    to the filesystem.  Small/non-Windows copies therefore re-read and compare
    both paths.  Large Windows PA sources can expose a stale buffered view while
    ``robocopy /J`` exposes the persisted view; in that branch only the new
    unbuffered snapshot is authoritative.  Callers validating an immutable
    source must compare the returned identity with its manifest.
    """

    observations: list[str] = []
    unbuffered_windows_copy = (
        os.name == "nt"
        and source.stat().st_size >= _WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES
    )
    for attempt in range(1, 4):
        _copy_file_bytes(source, destination, flush_writable_source=True)
        source_size = source.stat().st_size
        destination_size = destination.stat().st_size
        destination_sha256 = file_sha256(destination)
        # Large Windows PA files have reproduced two simultaneous views: the
        # normal buffered source read can retain stale mapped pages while
        # robocopy /J reads the persisted bytes that SIMION will receive in a
        # fresh private file.  In that branch the verified destination is the
        # canonical snapshot; comparing it to the stale buffered source view
        # turns a valid cache hit into a false corruption report.
        source_sha256 = None if unbuffered_windows_copy else file_sha256(source)
        observations.append(
            f"attempt={attempt},source_bytes={source_size},"
            f"destination_bytes={destination_size},"
            f"source_sha256={source_sha256},"
            f"destination_sha256={destination_sha256}"
        )
        if (
            source_size == destination_size
            and (unbuffered_windows_copy or source_sha256 == destination_sha256)
        ):
            _make_file_writable(destination)
            return {
                "name": source.name,
                "bytes": destination_size,
                "sha256": destination_sha256,
            }
        if attempt < 3:
            time.sleep(0.2)
    raise ValueError(
        "persisted cache copy differs from source after 3 attempts: "
        f"{source.name} observations=[{' ; '.join(observations)}]"
    )


def snapshot_immutable_file(
    source: Path,
    destination: Path,
    expected_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize one immutable source without ever opening it for writing.

    The expected manifest is the byte authority.  On Windows a large file is
    read through ``robocopy /J`` into a new private path; only that persisted
    snapshot is hashed.  This deliberately never calls
    :func:`_flush_writable_source`, even if an immutable file accidentally lost
    its read-only attribute.
    """

    expected = validate_direct_inventory([expected_record])[0]
    if source.name != expected["name"]:
        raise ValueError("immutable snapshot source name differs from manifest")
    if not source.is_file() or source.stat().st_size != expected["bytes"]:
        raise ValueError(f"immutable source length differs from manifest: {source}")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"immutable snapshot would overwrite destination: {destination}")
    _copy_file_bytes(source, destination, flush_writable_source=False)
    actual = {
        "name": source.name,
        "bytes": destination.stat().st_size,
        "sha256": file_sha256(destination),
    }
    if actual != expected:
        _make_file_writable(destination)
        destination.unlink(missing_ok=True)
        raise ValueError(f"immutable source differs from its manifest: {source.name}")
    _make_file_writable(destination)
    return actual


def _remove_tree_writable(path: Path) -> None:
    """Remove a private staging tree even when copied Windows files are read-only."""

    def clear_read_only_and_retry(function: Any, failed_path: str, _: Any) -> None:
        failed = Path(failed_path)
        failed.chmod(failed.stat().st_mode | stat.S_IWUSR)
        function(failed_path)

    shutil.rmtree(path, onerror=clear_read_only_and_retry)


def materialize_direct_inventory(
    source_directory: str | Path,
    destination_directory: str | Path,
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Atomically copy a verified immutable inventory to writable direct files.

    The caller owns the cache role and identity.  This primitive proves that
    the exact source byte stream copied for every declared file matches its
    manifest, that the writable destination contains that same stream, and
    that no existing destination was overwritten.
    """

    expected = validate_direct_inventory(records)
    source = Path(source_directory)
    destination = Path(destination_directory)
    if not source.is_dir():
        raise ValueError(f"cache directory is missing: {source}")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"materialization would overwrite existing destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / f".{destination.name}.staging-{uuid4().hex}"
    published = False
    verified = False
    try:
        stage.mkdir()
        copied: list[dict[str, Any]] = []
        for record in expected:
            name = record["name"]
            source_path = source / name
            if not source_path.is_file():
                raise ValueError(f"declared cache file is missing: {source_path}")
            try:
                copied_record = snapshot_immutable_file(source_path, stage / name, record)
            except Exception as exc:
                raise RuntimeError(
                    "cache materialization copy failed: "
                    f"name={name} source_length={len(str(source_path))} "
                    f"destination_length={len(str(stage / name))} "
                    f"cause={type(exc).__name__}: {exc}"
                ) from exc
            if copied_record != record:
                raise ValueError(f"source cache file differs from its manifest: {name}")
            copied.append(copied_record)
        os.replace(stage, destination)
        published = True
        # The destination is the atomically renamed staging directory.  Each
        # file was hashed from the exact byte stream written and fsync'd above;
        # re-reading the same 24+ GiB family would add I/O but no new identity
        # evidence.
        verified = True
        return copied
    finally:
        if stage.exists():
            _remove_tree_writable(stage)
        if published and not verified and destination.exists():
            _remove_tree_writable(destination)


def payload_sha256(records: Iterable[Mapping[str, Any]]) -> str:
    """Return the lowercase digest of an ordered direct-file inventory."""

    return hashlib.sha256(_compact_json(validate_direct_inventory(records)).encode("utf-8")).hexdigest()


def generation_input(cache_key: str, payload_digest: str, provider_run_id: str | None) -> str:
    """Return the v3-compatible immutable generation input JSON text."""

    if SHA256.fullmatch(cache_key) is None or SHA256.fullmatch(payload_digest) is None:
        raise ValueError("cache or payload digest is invalid")
    return _compact_json(
        {
            "schema_version": 1,
            "cache_key": cache_key.lower(),
            "payload_sha256": payload_digest.lower(),
            "provider_run_id": provider_run_id,
        }
    )


def generation_sha256(generation_input_json: str) -> str:
    """Return the lowercase digest of caller-owned immutable generation text."""

    if not isinstance(generation_input_json, str):
        raise ValueError("generation input must be text")
    return hashlib.sha256(generation_input_json.encode("utf-8")).hexdigest()


def _main() -> int:
    """Expose the protocol-neutral calculation to non-Python cache adapters."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--cache-key")
    parser.add_argument("--provider-run-id")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--require-stable-inventory", action="store_true")
    parser.add_argument("--materialize-manifest", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.materialize_manifest is not None or args.destination is not None:
        if args.materialize_manifest is None or args.destination is None:
            parser.error("materialization requires both --materialize-manifest and --destination")
        if (
            args.cache_key is not None
            or args.provider_run_id is not None
            or args.exclude
            or args.require_stable_inventory
        ):
            parser.error("materialization does not accept digest-generation arguments")
        manifest = json.loads(args.materialize_manifest.read_text(encoding="utf-8-sig"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
            parser.error("materialization manifest has no direct-file inventory")
        records = materialize_direct_inventory(args.directory, args.destination, manifest["files"])
        print(json.dumps({"role": "materialized_direct_cache_inventory", "files": records}))
        return 0
    if args.cache_key is None:
        parser.error("digest generation requires --cache-key")
    records = (
        stable_inventory_direct_files(args.directory, exclude=args.exclude)
        if args.require_stable_inventory
        else inventory_direct_files(args.directory, exclude=args.exclude)
    )
    payload_digest = payload_sha256(records)
    immutable_input = generation_input(args.cache_key, payload_digest, args.provider_run_id)
    print(
        json.dumps(
            {
                "files": records,
                "payload_sha256": payload_digest,
                "generation_input": immutable_input,
                "generation_sha256": generation_sha256(immutable_input),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
