"""Streaming XOR redundancy for equal-length immutable SIMION PA members.

The parity bundle is only a recovery aid.  A damaged published generation is
never modified: at most one reconstructed member is written to a caller-owned
staging directory, which an owning cache protocol may validate and atomically
publish as part of a new generation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, BinaryIO, Sequence
from uuid import uuid4

from common.simion.cache_generation import (
    _WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES,
    _remove_tree_writable,
    snapshot_immutable_file,
)


ROLE = "immutable_pa_xor_parity"
SCHEMA_VERSION = 1
ALGORITHM = "xor-bytewise-v1"
PARITY_FILENAME = "payload.xor"
MANIFEST_FILENAME = "xor_parity_manifest.json"
DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024
SHA256 = re.compile(r"^[0-9A-F]{64}$")


class ImmutablePaParityError(ValueError):
    """Raised when parity creation, verification, or recovery cannot be trusted."""


@dataclass(frozen=True)
class ParityRecovery:
    """Result of verifying a parity group and optionally recovering one member."""

    status: str
    damaged_name: str | None = None
    staging_directory: Path | None = None
    recovered_path: Path | None = None
    recovered_bytes: int | None = None
    recovered_sha256: str | None = None


def _direct_name(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or Path(value).name != value
    ):
        raise ImmutablePaParityError(f"{label} must be one direct filename")
    return value


def _member_names(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ImmutablePaParityError("parity members must be a sequence")
    names = tuple(sorted(_direct_name(value, "parity member") for value in values))
    if not names:
        raise ImmutablePaParityError("XOR parity requires at least one member")
    if len(names) != len({name.casefold() for name in names}):
        raise ImmutablePaParityError("parity member names must be unique")
    if PARITY_FILENAME in names or MANIFEST_FILENAME in names:
        raise ImmutablePaParityError("parity member name collides with bundle metadata")
    return names


def _chunk_bytes(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ImmutablePaParityError("chunk byte count must be a positive integer")
    return value


def _outside_source(source: Path, destination: Path, label: str) -> None:
    source_resolved = source.resolve()
    destination_resolved = destination.resolve()
    if destination_resolved == source_resolved or source_resolved in destination_resolved.parents:
        raise ImmutablePaParityError(f"{label} must be outside the immutable generation")


def _open_member(path: Path) -> BinaryIO:
    if path.is_symlink() or not path.is_file():
        raise ImmutablePaParityError(f"immutable parity member is missing or indirect: {path}")
    return path.open("rb")


def _file_record(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(DEFAULT_CHUNK_BYTES), b""):
            digest.update(block)
            size += len(block)
    return {"name": path.name, "bytes": size, "sha256": digest.hexdigest().upper()}


def _xor_blocks(blocks: Sequence[bytes]) -> bytes:
    width = len(blocks[0])
    if any(len(block) != width for block in blocks):
        raise ImmutablePaParityError("parity member streams ended at different offsets")
    value = 0
    for block in blocks:
        value ^= int.from_bytes(block, "little")
    return value.to_bytes(width, "little")


def _write_json(path: Path, value: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def create_xor_parity_bundle(
    generation_directory: str | Path,
    member_names: Sequence[str],
    destination_directory: str | Path,
    *,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> dict[str, Any]:
    """Atomically create one XOR parity file and manifest outside a generation.

    Every member must be a direct, regular, equal-length file.  Member SHA-256
    values and parity are computed from the same streaming reads.
    """

    source = Path(generation_directory)
    if not source.is_dir():
        raise ImmutablePaParityError(f"immutable generation is missing: {source}")
    names = _member_names(member_names)
    block_size = _chunk_bytes(chunk_bytes)
    destination = Path(destination_directory)
    _outside_source(source, destination, "parity bundle")
    if destination.exists():
        raise ImmutablePaParityError(f"parity bundle destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging-{uuid4().hex}"
    staging.mkdir()
    streams: list[BinaryIO] = []
    try:
        paths = [source / name for name in names]
        lengths = []
        for path in paths:
            stream = _open_member(path)
            streams.append(stream)
            lengths.append(os.fstat(stream.fileno()).st_size)
        if len(set(lengths)) != 1 or lengths[0] <= 0:
            raise ImmutablePaParityError("parity members must have one positive common byte length")
        digests = [hashlib.sha256() for _ in streams]
        parity_digest = hashlib.sha256()
        parity_path = staging / PARITY_FILENAME
        written = 0
        with parity_path.open("xb") as parity_stream:
            while written < lengths[0]:
                width = min(block_size, lengths[0] - written)
                blocks = [stream.read(width) for stream in streams]
                parity_block = _xor_blocks(blocks)
                for digest, block in zip(digests, blocks, strict=True):
                    digest.update(block)
                parity_stream.write(parity_block)
                parity_digest.update(parity_block)
                written += width
            parity_stream.flush()
            os.fsync(parity_stream.fileno())
        if any(stream.read(1) for stream in streams):
            raise ImmutablePaParityError("parity member grew during streaming")
        if any(os.fstat(stream.fileno()).st_size != lengths[0] for stream in streams):
            raise ImmutablePaParityError("parity member length changed during streaming")
        members = [
            {"name": name, "bytes": lengths[0], "sha256": digest.hexdigest().upper()}
            for name, digest in zip(names, digests, strict=True)
        ]
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "role": ROLE,
            "algorithm": ALGORITHM,
            "member_length_bytes": lengths[0],
            "members": members,
            "parity": {
                "name": PARITY_FILENAME,
                "bytes": written,
                "sha256": parity_digest.hexdigest().upper(),
            },
        }
        _write_json(staging / MANIFEST_FILENAME, manifest)
        os.replace(staging, destination)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        for stream in streams:
            stream.close()


def _load_manifest(bundle: Path) -> dict[str, Any]:
    path = bundle / MANIFEST_FILENAME
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImmutablePaParityError(f"parity manifest is unreadable: {path}") from exc
    required = {
        "schema_version", "role", "algorithm", "member_length_bytes", "members", "parity"
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ImmutablePaParityError("parity manifest fields differ")
    if (
        value["schema_version"] != SCHEMA_VERSION
        or value["role"] != ROLE
        or value["algorithm"] != ALGORITHM
    ):
        raise ImmutablePaParityError("parity manifest identity differs")
    common_size = value["member_length_bytes"]
    if isinstance(common_size, bool) or not isinstance(common_size, int) or common_size <= 0:
        raise ImmutablePaParityError("parity manifest member length is invalid")
    members = value["members"]
    if not isinstance(members, list) or not members:
        raise ImmutablePaParityError("parity manifest member inventory is incomplete")
    names: list[str] = []
    for record in members:
        if not isinstance(record, dict) or set(record) != {"name", "bytes", "sha256"}:
            raise ImmutablePaParityError("parity member record fields differ")
        names.append(_direct_name(record["name"], "parity member record"))
        if (
            isinstance(record["bytes"], bool)
            or not isinstance(record["bytes"], int)
            or record["bytes"] != common_size
            or not isinstance(record["sha256"], str)
            or SHA256.fullmatch(record["sha256"]) is None
        ):
            raise ImmutablePaParityError("parity member record identity is invalid")
    if names != sorted(names) or len(names) != len({name.casefold() for name in names}):
        raise ImmutablePaParityError("parity member records must be sorted and unique")
    parity = value["parity"]
    if not isinstance(parity, dict) or set(parity) != {"name", "bytes", "sha256"}:
        raise ImmutablePaParityError("parity payload record fields differ")
    if (
        _direct_name(parity["name"], "parity payload") != PARITY_FILENAME
        or isinstance(parity["bytes"], bool)
        or not isinstance(parity["bytes"], int)
        or parity["bytes"] != common_size
        or not isinstance(parity["sha256"], str)
        or SHA256.fullmatch(parity["sha256"]) is None
    ):
        raise ImmutablePaParityError("parity payload record identity is invalid")
    return value


def _record_matches(path: Path, expected: dict[str, object]) -> bool:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected["bytes"]:
        return False
    return _file_record(path)["sha256"] == expected["sha256"]


def verify_and_recover_xor_parity(
    generation_directory: str | Path,
    parity_bundle_directory: str | Path,
    staging_directory: str | Path,
    *,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> ParityRecovery:
    """Verify a group and reconstruct exactly one bad member into staging.

    Zero bad members returns ``intact`` without creating staging.  A damaged
    parity payload or more than one bad member fails closed.  The source
    generation is opened read-only and is never repaired in place.
    """

    source = Path(generation_directory)
    bundle = Path(parity_bundle_directory)
    staging = Path(staging_directory)
    if not source.is_dir() or not bundle.is_dir():
        raise ImmutablePaParityError("generation or parity bundle is missing")
    _outside_source(source, bundle, "parity bundle")
    _outside_source(source, staging, "recovery staging")
    _outside_source(bundle, staging, "recovery staging")
    if staging.exists():
        raise ImmutablePaParityError(f"recovery staging already exists: {staging}")
    block_size = _chunk_bytes(chunk_bytes)
    manifest = _load_manifest(bundle)
    staging.parent.mkdir(parents=True, exist_ok=True)
    audit = staging.parent / f".{staging.name}.audit-{uuid4().hex}"
    audit.mkdir()
    parity_record = manifest["parity"]
    parity_path = bundle / parity_record["name"]
    parity_input = parity_path
    member_inputs: dict[str, Path] = {}
    damaged: list[dict[str, object]] = []
    try:
        if parity_record["bytes"] >= _WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES:
            parity_input = audit / "parity" / parity_record["name"]
            parity_input.parent.mkdir()
            try:
                snapshot_immutable_file(parity_path, parity_input, parity_record)
            except ValueError as exc:
                raise ImmutablePaParityError("XOR parity payload is damaged") from exc
        elif not _record_matches(parity_path, parity_record):
            raise ImmutablePaParityError("XOR parity payload is damaged")
        for record in manifest["members"]:
            path = source / record["name"]
            if record["bytes"] >= _WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES:
                snapshot = audit / "members" / record["name"]
                snapshot.parent.mkdir(exist_ok=True)
                try:
                    snapshot_immutable_file(path, snapshot, record)
                    member_inputs[record["name"]] = snapshot
                except (OSError, ValueError):
                    damaged.append(record)
            elif _record_matches(path, record):
                member_inputs[record["name"]] = path
            else:
                damaged.append(record)
        if not damaged:
            return ParityRecovery(status="intact")
        if len(damaged) != 1:
            raise ImmutablePaParityError("XOR parity can recover exactly one damaged member")

        target = damaged[0]
        temporary = staging.parent / f".{staging.name}.staging-{uuid4().hex}"
        temporary.mkdir()
        streams: list[BinaryIO] = []
        try:
            parity_stream = parity_input.open("rb")
            streams.append(parity_stream)
            for record in manifest["members"]:
                if record["name"] != target["name"]:
                    streams.append(_open_member(member_inputs[record["name"]]))
            output = temporary / target["name"]
            digest = hashlib.sha256()
            written = 0
            with output.open("xb") as output_stream:
                while written < target["bytes"]:
                    width = min(block_size, target["bytes"] - written)
                    block = _xor_blocks([stream.read(width) for stream in streams])
                    output_stream.write(block)
                    digest.update(block)
                    written += width
                output_stream.flush()
                os.fsync(output_stream.fileno())
            if any(stream.read(1) for stream in streams):
                raise ImmutablePaParityError("recovery input grew during streaming")
            if written != target["bytes"] or digest.hexdigest().upper() != target["sha256"]:
                raise ImmutablePaParityError("reconstructed member differs from its frozen identity")
            os.replace(temporary, staging)
            return ParityRecovery(
                status="recovered",
                damaged_name=target["name"],
                staging_directory=staging,
                recovered_path=staging / target["name"],
                recovered_bytes=target["bytes"],
                recovered_sha256=target["sha256"],
            )
        except Exception:
            if temporary.exists():
                _remove_tree_writable(temporary)
            raise
        finally:
            for stream in streams:
                stream.close()
    finally:
        if audit.exists():
            _remove_tree_writable(audit)


__all__ = [
    "ImmutablePaParityError",
    "ParityRecovery",
    "create_xor_parity_bundle",
    "verify_and_recover_xor_parity",
]
