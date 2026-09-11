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
    actual: list[dict[str, Any]] = []
    for record in expected:
        path = root / record["name"]
        if not path.is_file():
            raise ValueError(f"declared cache file is missing: {path}")
        actual.append(
            {
                "name": record["name"],
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return actual


def _make_file_writable(path: Path) -> None:
    """Clear a copied cache file's read-only attribute without changing bytes."""

    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _copy_verified_file(source: Path, destination: Path) -> dict[str, Any]:
    """Copy and hash one file in the same flushed byte stream."""

    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as read_handle, destination.open("wb") as write_handle:
        while chunk := read_handle.read(8 * 1024 * 1024):
            write_handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        write_handle.flush()
        os.fsync(write_handle.fileno())
    _make_file_writable(destination)
    return {"name": source.name, "bytes": size, "sha256": digest.hexdigest().upper()}


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
                copied_record = _copy_verified_file(source_path, stage / name)
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
