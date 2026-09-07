"""Protocol-neutral primitives for immutable direct-file cache generations.

Callers retain ownership of cache identity, retention, locking, and manifest
schema.  This module deliberately owns only the repeatable byte-inventory and
generation-digest operations shared by SIMION PA-family cache protocols.
"""

from __future__ import annotations

import hashlib
import json
import re
import argparse
from pathlib import Path
from typing import Any, Iterable, Mapping

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
        normalized.append({"name": name, "bytes": size, "sha256": digest})
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
    parser.add_argument("--cache-key", required=True)
    parser.add_argument("--provider-run-id")
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args()
    records = inventory_direct_files(args.directory, exclude=args.exclude)
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
