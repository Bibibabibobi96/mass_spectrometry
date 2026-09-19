"""Content-addressed, device-neutral cache for complete SIMION PA families.

The cache deliberately knows no electrode IDs, geometry coordinates, or PA file
suffix conventions.  A caller supplies the complete direct-file family it has
built and a full numerical identity.  A cache entry is usable only when both
the identity and every recorded byte are intact.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from typing import Any, Mapping, Sequence
from uuid import uuid4

from common.contracts import capacity_protection
from common.contracts.file_identity import canonical_json_sha256, file_sha256
from common.simion.cache_generation import (
    _WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES,
    _remove_tree_writable,
    materialize_direct_inventory, inventory_named_files, copy_verified_file,
    snapshot_immutable_file, stable_inventory_direct_files,
)
from common.simion.immutable_pa_parity import (
    ALGORITHM as PARITY_ALGORITHM,
    MANIFEST_FILENAME as PARITY_MANIFEST_NAME,
    create_xor_parity_bundle,
    verify_and_recover_xor_parity,
)


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
ROLE = "simion_pa_family_cache"
MANIFEST_NAME = "cache_manifest.json"
POINTER_NAME = "current_generation.json"
STAGING_DIRECTORY = ".staging"
LOCK_DIRECTORY = ".locks"
RECOVERY_DIRECTORY = "recovery"
CACHE_KEY_FIELDS = (
    "geometry",
    "gem",
    "basis_namespace",
    "mesh",
    "grid_phase",
    "surface",
    "simion_identity",
    "refine_policy",
    "builder_identity",
)
SHA256 = re.compile(r"^[0-9A-F]{64}$")
REDUNDANCY_CREATION_MAX_ATTEMPTS = 3
NO_REDUNDANCY_ALGORITHM = "none_reconstructible"
PAYLOAD_VERIFICATION_ATTEMPTS = 3
PAYLOAD_RECOVERY_CONSECUTIVE_MATCHES = 2
PAYLOAD_VERIFICATION_RETRY_DELAY_S = 0.2


class PAFamilyCacheError(ValueError):
    """Raised when a cache identity, inventory, or publication is invalid."""


class CacheDisposition(str, Enum):
    """Outcome of probing or publishing a content-addressed PA family."""

    HIT = "hit"
    MISS = "miss"
    CORRUPT = "corrupt"
    PUBLISHED = "published"


@dataclass(frozen=True)
class CacheProbe:
    disposition: CacheDisposition
    cache_key: str
    generation_directory: Path | None = None
    detail: str | None = None


@dataclass(frozen=True)
class CachePublication:
    disposition: CacheDisposition
    cache_key: str
    generation_sha256: str
    generation_directory: Path
    manifest: dict[str, Any]


@dataclass(frozen=True)
class MaterializedFamily:
    destination_directory: Path
    files: tuple[dict[str, Any], ...]
    source_generation_directory: Path
    predecessor_generation_directory: Path | None = None
    repair_receipt_path: Path | None = None


@dataclass(frozen=True)
class CacheRepair:
    cache_key: str
    generation_sha256: str
    repaired_member: str
    generation_directory: Path
    predecessor_directory: Path
    receipt_path: Path
    current_pointer_advanced: bool


@dataclass(frozen=True)
class ValidatedFamilySubset:
    manifest: dict[str, Any]
    generation_directory: Path
    predecessor_generation_directory: Path | None = None
    repair_receipt_path: Path | None = None


def _set_file_read_only(path: Path) -> None:
    """Seal one published cache payload against solver-side family writes."""
    path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _set_file_writable(path: Path) -> None:
    """Make one private materialization writable without changing its bytes."""
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _verify_payload_record(root: Path, record: Mapping[str, Any]) -> None:
    """Verify one immutable payload, recovering only from a transient read.

    A normal cache hit still performs one full read.  If that read differs,
    accept the payload only after two consecutive complete re-reads reproduce
    the manifest exactly.  This keeps persistent damage fail-closed while
    avoiding a false CORRUPT result from one unstable large-file read.
    """

    path = root / record["name"]
    observations: list[str] = []
    mismatch_seen = False
    consecutive_matches = 0
    for attempt in range(1, PAYLOAD_VERIFICATION_ATTEMPTS + 1):
        if path.is_file():
            observed_bytes = path.stat().st_size
            observed_sha256 = file_sha256(path)
        else:
            observed_bytes = None
            observed_sha256 = None
        observations.append(
            f"attempt={attempt},bytes={observed_bytes},sha256={observed_sha256}"
        )
        matches = (
            observed_bytes == record["bytes"]
            and observed_sha256 == record["sha256"]
        )
        if matches:
            consecutive_matches += 1
            required = PAYLOAD_RECOVERY_CONSECUTIVE_MATCHES if mismatch_seen else 1
            if consecutive_matches >= required:
                return
        else:
            mismatch_seen = True
            consecutive_matches = 0
            # A large Windows PA can retain stale pages in the ordinary
            # buffered view even though an unbuffered read of the persisted
            # file is correct.  Recover only by making one disposable /J
            # snapshot and validating that independent file against the
            # manifest.  The cache payload itself remains untouched.
            if (
                os.name == "nt"
                and observed_bytes == record["bytes"]
                and observed_bytes is not None
                and observed_bytes >= _WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES
            ):
                with tempfile.TemporaryDirectory(
                    prefix="pa-cache-verify-", dir=root.parent
                ) as temporary:
                    snapshot = Path(temporary) / path.name
                    try:
                        snapshot_record = snapshot_immutable_file(path, snapshot, record)
                    except ValueError:
                        snapshot_record = None
                    observations.append(
                        "unbuffered_snapshot="
                        f"{snapshot_record['sha256'] if snapshot_record else 'MISMATCH'}"
                    )
                    if snapshot_record == {
                        "name": record["name"],
                        "bytes": record["bytes"],
                        "sha256": record["sha256"],
                    }:
                        return
        if attempt < PAYLOAD_VERIFICATION_ATTEMPTS:
            time.sleep(PAYLOAD_VERIFICATION_RETRY_DELAY_S)
    raise PAFamilyCacheError(
        "PA cache family payload differs: "
        f"{record['name']} expected_bytes={record['bytes']} "
        f"expected_sha256={record['sha256']} observations=[{' ; '.join(observations)}]"
    )


def _seal_generation_files(directory: Path, manifest: Mapping[str, Any]) -> None:
    for record in manifest["files"]:
        _set_file_read_only(directory / record["name"])
    _set_file_read_only(directory / MANIFEST_NAME)


def _canonical_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(identity, Mapping) or set(identity) != set(CACHE_KEY_FIELDS):
        raise PAFamilyCacheError(
            "PA cache identity fields must be exactly " + ", ".join(CACHE_KEY_FIELDS)
        )
    document = {field: identity[field] for field in CACHE_KEY_FIELDS}
    # canonical_json_sha256 supplies the finite-JSON, stable-serialization gate.
    try:
        canonical_json_sha256(document)
    except ValueError as exc:
        raise PAFamilyCacheError("PA cache identity is not canonical finite JSON") from exc
    return document


def canonical_pa_family_cache_key(identity: Mapping[str, Any]) -> str:
    """Return the content key for all numerical and builder inputs to one PA family."""

    return canonical_json_sha256(_canonical_identity(identity))


def _safe_name(value: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise PAFamilyCacheError(f"PA family filename must be one direct filename: {value!r}")
    if value in {MANIFEST_NAME, POINTER_NAME}:
        raise PAFamilyCacheError(f"PA family filename is reserved: {value}")
    return value


def _family_names(filenames: Sequence[str]) -> tuple[str, ...]:
    if isinstance(filenames, (str, bytes)) or not isinstance(filenames, Sequence):
        raise PAFamilyCacheError("PA family filenames must be a non-empty sequence")
    names = tuple(sorted(_safe_name(name) for name in filenames))
    if not names or len(set(names)) != len(names):
        raise PAFamilyCacheError("PA family filenames must be non-empty and unique")
    return names


def pa_family_inventory(directory: str | Path, filenames: Sequence[str]) -> list[dict[str, Any]]:
    """Return sorted direct-file records (name, bytes, SHA-256) for one family."""

    root = Path(directory)
    names = _family_names(filenames)
    try:
        return inventory_named_files(root, names)
    except ValueError as exc:
        raise PAFamilyCacheError(str(exc)) from exc


def _actual_payload_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        raise PAFamilyCacheError(f"PA family directory is missing: {directory}")
    unexpected_nodes = [item.name for item in directory.iterdir() if not item.is_file()]
    if unexpected_nodes:
        raise PAFamilyCacheError(f"PA family directory contains non-files: {sorted(unexpected_nodes)}")
    return {item.name for item in directory.iterdir() if item.name != MANIFEST_NAME}


def _generation_sha256(
    cache_key: str,
    records: Sequence[Mapping[str, Any]],
    redundancy: Mapping[str, Any] | None = None,
    predecessor_generation_sha256: str | None = None,
) -> str:
    if redundancy is None:
        return canonical_json_sha256({"cache_key": cache_key, "files": list(records)})
    return canonical_json_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "cache_key": cache_key,
            "files": list(records),
            "redundancy": dict(redundancy),
            "predecessor_generation_sha256": predecessor_generation_sha256,
        }
    )


def _manifest(
    cache_key: str,
    identity: Mapping[str, Any],
    records: list[dict[str, Any]],
    redundancy: Mapping[str, Any] | None = None,
    predecessor_generation_sha256: str | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION if redundancy is not None else LEGACY_SCHEMA_VERSION,
        "role": ROLE,
        "cache_key": cache_key,
        "identity": _canonical_identity(identity),
        "generation_sha256": _generation_sha256(
            cache_key, records, redundancy, predecessor_generation_sha256
        ),
        "files": records,
    }
    if redundancy is not None:
        document["redundancy"] = dict(redundancy)
        document["predecessor_generation_sha256"] = predecessor_generation_sha256
    return document


def _redundancy_groups(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Group every large immutable payload into one recoverable XOR set per size."""

    by_size: dict[int, list[str]] = {}
    for record in records:
        size = int(record["bytes"])
        by_size.setdefault(size, []).append(str(record["name"]))
    return [
        {
            "bundle": canonical_json_sha256(
                {"algorithm": PARITY_ALGORITHM, "bytes": size, "members": sorted(names)}
            )[:24],
            "member_length_bytes": size,
            "members": sorted(names),
        }
        for size, names in sorted(by_size.items())
    ]


def _create_redundancy(
    generation_stage: Path,
    recovery_stage: Path,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    records_by_name = {str(record["name"]): dict(record) for record in records}
    groups: list[dict[str, Any]] = []
    for plan in _redundancy_groups(records):
        bundle = recovery_stage / str(plan["bundle"])
        expected_members = [records_by_name[name] for name in plan["members"]]
        parity_manifest: dict[str, Any] | None = None
        observed_members: list[object] = []
        for attempt in range(1, REDUNDANCY_CREATION_MAX_ATTEMPTS + 1):
            if bundle.exists():
                _remove_tree_writable(bundle)
            candidate = create_xor_parity_bundle(
                generation_stage, list(plan["members"]), bundle
            )
            observed_members.append(candidate["members"])
            if candidate["members"] == expected_members:
                parity_manifest = candidate
                break
            if attempt < REDUNDANCY_CREATION_MAX_ATTEMPTS:
                time.sleep(PAYLOAD_VERIFICATION_RETRY_DELAY_S)
        if parity_manifest is None:
            if bundle.exists():
                _remove_tree_writable(bundle)
            raise PAFamilyCacheError(
                "PA redundancy read differs from the just-published payload identity "
                f"after {REDUNDANCY_CREATION_MAX_ATTEMPTS} attempts: "
                f"members={plan['members']} observations={observed_members}"
            )
        groups.append(
            {
                **plan,
                "manifest_sha256": file_sha256(bundle / PARITY_MANIFEST_NAME),
                "parity_sha256": parity_manifest["parity"]["sha256"],
            }
        )
    return {"algorithm": PARITY_ALGORITHM, "groups": groups}


def _validate_redundancy_metadata(root: Path, manifest: Mapping[str, Any]) -> None:
    redundancy = manifest.get("redundancy")
    if not isinstance(redundancy, dict) or set(redundancy) != {"algorithm", "groups"}:
        raise PAFamilyCacheError("PA cache redundancy metadata differs")
    if redundancy["algorithm"] == NO_REDUNDANCY_ALGORITHM:
        if redundancy["groups"] != []:
            raise PAFamilyCacheError("reconstructible PA cache must not declare recovery groups")
        recovery_root = root.parents[1] / RECOVERY_DIRECTORY / manifest["generation_sha256"]
        if recovery_root.exists():
            raise PAFamilyCacheError("reconstructible PA cache has an unexpected recovery bundle")
        return
    if redundancy["algorithm"] != PARITY_ALGORITHM or not isinstance(
        redundancy["groups"], list
    ):
        raise PAFamilyCacheError("PA cache redundancy identity differs")
    expected_plans = _redundancy_groups(manifest["files"])
    compact_groups = [
        {
            "bundle": group.get("bundle"),
            "member_length_bytes": group.get("member_length_bytes"),
            "members": group.get("members"),
        }
        for group in redundancy["groups"]
        if isinstance(group, dict)
    ]
    if compact_groups != expected_plans or len(compact_groups) != len(redundancy["groups"]):
        raise PAFamilyCacheError("PA cache redundancy groups differ from payload inventory")
    recovery_root = root.parents[1] / RECOVERY_DIRECTORY / manifest["generation_sha256"]
    records_by_name = {record["name"]: record for record in manifest["files"]}
    for group in redundancy["groups"]:
        if set(group) != {
            "bundle", "member_length_bytes", "members", "manifest_sha256", "parity_sha256"
        }:
            raise PAFamilyCacheError("PA cache redundancy group fields differ")
        if not SHA256.fullmatch(str(group["manifest_sha256"])) or not SHA256.fullmatch(
            str(group["parity_sha256"])
        ):
            raise PAFamilyCacheError("PA cache redundancy digest is invalid")
        bundle = recovery_root / group["bundle"]
        parity_manifest_path = bundle / PARITY_MANIFEST_NAME
        if not parity_manifest_path.is_file() or file_sha256(parity_manifest_path) != group[
            "manifest_sha256"
        ]:
            raise PAFamilyCacheError("PA cache redundancy manifest differs")
        try:
            parity_manifest = json.loads(parity_manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PAFamilyCacheError("PA cache redundancy manifest is unreadable") from exc
        if parity_manifest.get("algorithm") != PARITY_ALGORITHM:
            raise PAFamilyCacheError("PA cache redundancy algorithm differs")
        if parity_manifest.get("members") != [
            records_by_name[name] for name in group["members"]
        ]:
            raise PAFamilyCacheError("PA cache redundancy members differ")
        parity = parity_manifest.get("parity")
        if not isinstance(parity, dict) or parity.get("sha256") != group["parity_sha256"]:
            raise PAFamilyCacheError("PA cache redundancy parity identity differs")
        parity_path = bundle / str(parity.get("name", ""))
        if not parity_path.is_file() or parity_path.stat().st_size != group[
            "member_length_bytes"
        ]:
            raise PAFamilyCacheError("PA cache redundancy payload is missing or truncated")
        try:
            _verify_payload_record(bundle, parity)
        except PAFamilyCacheError as exc:
            raise PAFamilyCacheError("PA cache redundancy payload differs") from exc


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_pa_family_cache_generation(
    generation_directory: str | Path,
    *,
    expected_cache_key: str | None = None,
    expected_filenames: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Fail closed unless a generation's manifest and exact payload inventory agree."""

    root = Path(generation_directory)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise PAFamilyCacheError(f"PA cache manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError(f"PA cache manifest is unreadable: {manifest_path}") from exc
    schema_version = manifest.get("schema_version") if isinstance(manifest, dict) else None
    required = {"schema_version", "role", "cache_key", "identity", "generation_sha256", "files"}
    if schema_version == SCHEMA_VERSION:
        required.update(("redundancy", "predecessor_generation_sha256"))
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise PAFamilyCacheError("PA cache manifest fields differ")
    if manifest["schema_version"] not in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION} or manifest["role"] != ROLE:
        raise PAFamilyCacheError("PA cache manifest identity differs")
    identity = _canonical_identity(manifest["identity"])
    cache_key = manifest["cache_key"]
    if not isinstance(cache_key, str) or not SHA256.fullmatch(cache_key):
        raise PAFamilyCacheError("PA cache key is invalid")
    if canonical_pa_family_cache_key(identity) != cache_key:
        raise PAFamilyCacheError("PA cache key differs from identity")
    if expected_cache_key is not None and cache_key != expected_cache_key:
        raise PAFamilyCacheError("PA cache key differs from requested identity")
    records = manifest["files"]
    if not isinstance(records, list) or not records:
        raise PAFamilyCacheError("PA cache family inventory is empty")
    names: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "bytes", "sha256"}:
            raise PAFamilyCacheError("PA cache inventory record fields differ")
        name = _safe_name(record["name"])
        if not isinstance(record["bytes"], int) or isinstance(record["bytes"], bool) or record["bytes"] < 0:
            raise PAFamilyCacheError("PA cache inventory byte count is invalid")
        if not isinstance(record["sha256"], str) or not SHA256.fullmatch(record["sha256"]):
            raise PAFamilyCacheError("PA cache inventory SHA-256 is invalid")
        _verify_payload_record(root, record)
        names.append(name)
    if names != sorted(names) or len(names) != len(set(names)):
        raise PAFamilyCacheError("PA cache inventory filenames are not sorted and unique")
    if _actual_payload_names(root) != set(names):
        raise PAFamilyCacheError("PA cache family inventory is incomplete or has extra files")
    if expected_filenames is not None and tuple(names) != _family_names(expected_filenames):
        raise PAFamilyCacheError("PA cache family filenames differ")
    redundancy = manifest.get("redundancy") if manifest["schema_version"] == SCHEMA_VERSION else None
    predecessor = manifest.get("predecessor_generation_sha256")
    if predecessor is not None and (
        not isinstance(predecessor, str) or not SHA256.fullmatch(predecessor)
    ):
        raise PAFamilyCacheError("PA cache predecessor generation is invalid")
    if manifest["generation_sha256"] != _generation_sha256(
        cache_key, records, redundancy, predecessor
    ):
        raise PAFamilyCacheError("PA cache generation identity differs")
    if manifest["schema_version"] == SCHEMA_VERSION:
        _validate_redundancy_metadata(root, manifest)
    return manifest


def validate_pa_family_cache_subset(
    generation_directory: str | Path,
    filenames: Sequence[str],
    *,
    expected_cache_key: str | None = None,
) -> dict[str, Any]:
    """Validate an independently consumable subset without opening native siblings.

    SIMION native ``.paN`` members are build-stage payloads and can be finalized
    after the visible solver process exits.  A caller that consumes only detached
    standalone ``.pa`` outputs must not reopen those native siblings merely to
    validate files it will never use.  This function still validates the complete
    manifest metadata and generation identity, then hashes every requested file
    against its unique manifest record.  Unrequested payload bytes are deliberately
    not read and this function does not qualify the complete generation as intact.
    """

    root = Path(generation_directory)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise PAFamilyCacheError(f"PA cache manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError(f"PA cache manifest is unreadable: {manifest_path}") from exc
    schema_version = manifest.get("schema_version") if isinstance(manifest, dict) else None
    required = {"schema_version", "role", "cache_key", "identity", "generation_sha256", "files"}
    if schema_version == SCHEMA_VERSION:
        required.update(("redundancy", "predecessor_generation_sha256"))
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise PAFamilyCacheError("PA cache manifest fields differ")
    if manifest["schema_version"] not in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION} or manifest["role"] != ROLE:
        raise PAFamilyCacheError("PA cache manifest identity differs")
    identity = _canonical_identity(manifest["identity"])
    cache_key = manifest["cache_key"]
    if not isinstance(cache_key, str) or not SHA256.fullmatch(cache_key):
        raise PAFamilyCacheError("PA cache key is invalid")
    if canonical_pa_family_cache_key(identity) != cache_key:
        raise PAFamilyCacheError("PA cache key differs from identity")
    if expected_cache_key is not None and cache_key != expected_cache_key:
        raise PAFamilyCacheError("PA cache key differs from requested identity")
    records = manifest["files"]
    if not isinstance(records, list) or not records:
        raise PAFamilyCacheError("PA cache family inventory is empty")
    names: list[str] = []
    records_by_name: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "bytes", "sha256"}:
            raise PAFamilyCacheError("PA cache inventory record fields differ")
        name = _safe_name(record["name"])
        if not isinstance(record["bytes"], int) or isinstance(record["bytes"], bool) or record["bytes"] < 0:
            raise PAFamilyCacheError("PA cache inventory byte count is invalid")
        if not isinstance(record["sha256"], str) or not SHA256.fullmatch(record["sha256"]):
            raise PAFamilyCacheError("PA cache inventory SHA-256 is invalid")
        names.append(name)
        records_by_name[name] = record
    if names != sorted(names) or len(names) != len(set(names)):
        raise PAFamilyCacheError("PA cache inventory filenames are not sorted and unique")
    redundancy = manifest.get("redundancy") if manifest["schema_version"] == SCHEMA_VERSION else None
    predecessor = manifest.get("predecessor_generation_sha256")
    if predecessor is not None and (
        not isinstance(predecessor, str) or not SHA256.fullmatch(predecessor)
    ):
        raise PAFamilyCacheError("PA cache predecessor generation is invalid")
    if manifest["generation_sha256"] != _generation_sha256(
        cache_key, records, redundancy, predecessor
    ):
        raise PAFamilyCacheError("PA cache generation identity differs")
    if manifest["schema_version"] == SCHEMA_VERSION:
        _validate_redundancy_metadata(root, manifest)
    selected = _family_names(filenames)
    missing = [name for name in selected if name not in records_by_name]
    if missing:
        raise PAFamilyCacheError(
            "PA cache subset is absent from the generation manifest: " + ", ".join(missing)
        )
    for name in selected:
        _verify_payload_record(root, records_by_name[name])
    return manifest


def validate_pa_family_cache_subset_with_repair(
    generation_directory: str | Path,
    filenames: Sequence[str],
    *,
    expected_cache_key: str | None = None,
    lock_timeout_s: float = 30.0,
) -> ValidatedFamilySubset:
    """Validate an exact subset, recovering its pinned generation if possible."""

    source = Path(generation_directory)
    try:
        manifest = validate_pa_family_cache_subset(
            source,
            filenames,
            expected_cache_key=expected_cache_key,
        )
        return ValidatedFamilySubset(manifest, source.resolve())
    except PAFamilyCacheError as original_error:
        try:
            repair = repair_pa_family_cache_generation(
                source, lock_timeout_s=lock_timeout_s
            )
        except PAFamilyCacheError as repair_error:
            # The repair scan re-verifies every payload.  A transient Windows
            # large-file view can therefore make the first subset check fail
            # while the immediately following repair scan observes no damaged
            # member.  Re-run the requested subset once before preserving the
            # original failure; this accepts only a complete manifest-backed
            # verification and never publishes a repair for intact bytes.
            try:
                manifest = validate_pa_family_cache_subset(
                    source,
                    filenames,
                    expected_cache_key=expected_cache_key,
                )
            except PAFamilyCacheError:
                raise original_error from repair_error
            return ValidatedFamilySubset(manifest, source.resolve())
        manifest = validate_pa_family_cache_subset(
            repair.generation_directory,
            filenames,
            expected_cache_key=expected_cache_key,
        )
        return ValidatedFamilySubset(
            manifest,
            repair.generation_directory,
            repair.predecessor_directory,
            repair.receipt_path,
        )


def probe_pa_family_cache(
    cache_root: str | Path,
    identity: Mapping[str, Any],
    *,
    expected_filenames: Sequence[str] | None = None,
) -> CacheProbe:
    """Classify the current generation as hit, miss, or corrupt without mutating it."""

    key = canonical_pa_family_cache_key(identity)
    key_root = Path(cache_root) / key
    pointer_path = key_root / POINTER_NAME
    if not pointer_path.is_file():
        return CacheProbe(CacheDisposition.MISS, key, detail="current generation pointer is absent")
    directory: Path | None = None
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
        generation = pointer["generation_sha256"]
        if set(pointer) != {"cache_key", "generation_sha256"} or pointer["cache_key"] != key or not isinstance(generation, str) or not SHA256.fullmatch(generation):
            raise PAFamilyCacheError("generation pointer differs")
        directory = key_root / "generations" / generation
        manifest = validate_pa_family_cache_generation(
            directory, expected_cache_key=key, expected_filenames=expected_filenames
        )
        if manifest["generation_sha256"] != generation:
            raise PAFamilyCacheError("generation pointer differs from manifest")
    except (OSError, json.JSONDecodeError, KeyError, PAFamilyCacheError) as exc:
        return CacheProbe(CacheDisposition.CORRUPT, key, directory, detail=str(exc))
    return CacheProbe(CacheDisposition.HIT, key, directory)


def ensure_pa_family_cache(
    cache_root: str | Path,
    identity: Mapping[str, Any],
    *,
    expected_filenames: Sequence[str] | None = None,
    lock_timeout_s: float = 30.0,
) -> CacheProbe:
    """Return a usable hit or miss, repairing one damaged v2 payload once.

    This is the production-consumer counterpart to the read-only ``probe``.
    It never builds a missing family.  A recoverable current generation is
    replaced by a fully validated immutable successor; every other corruption
    remains fail-closed.
    """

    result = probe_pa_family_cache(
        cache_root, identity, expected_filenames=expected_filenames
    )
    if (
        result.disposition is CacheDisposition.CORRUPT
        and result.generation_directory is not None
    ):
        repair_pa_family_cache_generation(
            result.generation_directory, lock_timeout_s=lock_timeout_s
        )
        result = probe_pa_family_cache(
            cache_root, identity, expected_filenames=expected_filenames
        )
    if result.disposition is CacheDisposition.CORRUPT:
        raise PAFamilyCacheError(
            f"cannot ensure PA cache {result.cache_key}: {result.detail}"
        )
    return result


def repair_pa_family_cache_generation(
    generation_directory: str | Path,
    *,
    lock_timeout_s: float = 30.0,
) -> CacheRepair:
    """Recover one damaged payload into a new immutable successor generation.

    If ``generation_directory`` is still current, the pointer advances with a
    compare-under-lock update.  A frozen older generation can also be repaired;
    its successor is returned without regressing a newer current pointer.
    """

    source = Path(generation_directory).resolve()
    if source.parent.name != "generations" or not source.is_dir():
        raise PAFamilyCacheError("PA cache repair requires one published generation")
    key_root = source.parents[1]
    cache_key = key_root.name
    if not SHA256.fullmatch(cache_key) or not SHA256.fullmatch(source.name):
        raise PAFamilyCacheError("PA cache repair path identity is invalid")
    try:
        manifest = json.loads((source / MANIFEST_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError("PA cache repair manifest is unreadable") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("role") != ROLE
        or manifest.get("cache_key") != cache_key
        or manifest.get("generation_sha256") != source.name
        or not isinstance(manifest.get("files"), list)
    ):
        raise PAFamilyCacheError("PA cache repair requires a v2 redundancy manifest")
    records = manifest["files"]
    if manifest["generation_sha256"] != _generation_sha256(
        cache_key,
        records,
        manifest["redundancy"],
        manifest.get("predecessor_generation_sha256"),
    ):
        raise PAFamilyCacheError("PA cache repair generation identity differs")
    _validate_redundancy_metadata(source, manifest)
    damaged: list[Mapping[str, Any]] = []
    for record in records:
        try:
            _verify_payload_record(source, record)
        except PAFamilyCacheError:
            damaged.append(record)
    if len(damaged) != 1:
        raise PAFamilyCacheError(
            f"PA cache parity repair requires exactly one damaged payload; observed={len(damaged)}"
        )
    damaged_record = damaged[0]
    group = next(
        (
            item for item in manifest["redundancy"]["groups"]
            if damaged_record["name"] in item["members"]
        ),
        None,
    )
    if group is None:
        raise PAFamilyCacheError("damaged PA payload has no recovery group")

    cache_root = key_root.parent
    with _protected_key_lock(cache_root, cache_key, lock_timeout_s):
        try:
            pointer = json.loads((key_root / POINTER_NAME).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PAFamilyCacheError("PA cache repair pointer is unreadable") from exc
        if (
            not isinstance(pointer, dict)
            or set(pointer) != {"cache_key", "generation_sha256"}
            or pointer.get("cache_key") != cache_key
            or not isinstance(pointer.get("generation_sha256"), str)
            or not SHA256.fullmatch(pointer["generation_sha256"])
        ):
            raise PAFamilyCacheError("PA cache repair pointer is invalid")
        source_is_current = pointer["generation_sha256"] == source.name
        stage_parent = cache_root / STAGING_DIRECTORY
        stage_parent.mkdir(exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="pa-repair-", dir=stage_parent))
        recovered_stage = stage / "recovered"
        replacement = stage / "generation"
        published_generation: Path | None = None
        published_recovery: Path | None = None
        publication_committed = False
        pointer_advanced = False
        try:
            result = verify_and_recover_xor_parity(
                source,
                key_root / RECOVERY_DIRECTORY / source.name / group["bundle"],
                recovered_stage,
            )
            if result.status != "recovered" or result.damaged_name != damaged_record["name"]:
                raise PAFamilyCacheError("PA cache parity did not recover the expected member")
            replacement.mkdir()
            copied: list[dict[str, Any]] = []
            for record in records:
                origin = (
                    result.recovered_path
                    if record["name"] == damaged_record["name"]
                    else source / record["name"]
                )
                copied_record = (
                    copy_verified_file(origin, replacement / record["name"])
                    if record["name"] == damaged_record["name"]
                    else snapshot_immutable_file(
                        origin, replacement / record["name"], record
                    )
                )
                if copied_record != record:
                    raise PAFamilyCacheError(
                        f"PA cache repair copy differs from manifest: {record['name']}"
                    )
                copied.append(copied_record)
            recovery_stage = stage / "successor-recovery"
            redundancy = _create_redundancy(replacement, recovery_stage, copied)
            successor_manifest = _manifest(
                cache_key,
                manifest["identity"],
                copied,
                redundancy,
                predecessor_generation_sha256=source.name,
            )
            _write_json(replacement / MANIFEST_NAME, successor_manifest)
            _seal_generation_files(replacement, successor_manifest)
            successor = key_root / "generations" / successor_manifest["generation_sha256"]
            recovery_destination = (
                key_root / RECOVERY_DIRECTORY / successor_manifest["generation_sha256"]
            )
            if successor.exists() != recovery_destination.exists():
                raise PAFamilyCacheError(
                    "PA cache repair successor is only partially published"
                )
            if successor.exists():
                incumbent = validate_pa_family_cache_generation(
                    successor,
                    expected_cache_key=cache_key,
                    expected_filenames=[record["name"] for record in records],
                )
                if incumbent != successor_manifest:
                    raise PAFamilyCacheError(
                        "existing PA cache repair successor identity differs"
                    )
            else:
                recovery_destination.parent.mkdir(parents=True, exist_ok=True)
                for bundle in recovery_stage.iterdir():
                    for item in bundle.iterdir():
                        _set_file_read_only(item)
                os.replace(recovery_stage, recovery_destination)
                published_recovery = recovery_destination
                os.replace(replacement, successor)
                published_generation = successor
                validate_pa_family_cache_generation(
                    successor,
                    expected_cache_key=cache_key,
                    expected_filenames=[record["name"] for record in records],
                )
            publication_committed = True
            if source_is_current:
                _publish_pointer(
                    key_root, cache_key, successor_manifest["generation_sha256"]
                )
                pointer_advanced = True
            receipt_directory = key_root / "repair_receipts"
            receipt_directory.mkdir(exist_ok=True)
            receipt = receipt_directory / f"{time.time_ns()}-{uuid4().hex}.json"
            _write_json(
                receipt,
                {
                    "schema_version": 1,
                    "role": "simion_pa_family_cache_single_member_repair",
                    "cache_key": cache_key,
                    "generation_sha256": successor.name,
                    "predecessor_generation_sha256": source.name,
                    "repaired_member": damaged_record["name"],
                    "current_pointer_advanced": pointer_advanced,
                    "files": copied,
                },
            )
            return CacheRepair(
                cache_key,
                successor.name,
                damaged_record["name"],
                successor,
                source,
                receipt,
                pointer_advanced,
            )
        finally:
            if not publication_committed:
                if published_generation is not None and published_generation.exists():
                    _remove_tree_writable(published_generation)
                if published_recovery is not None and published_recovery.exists():
                    _remove_tree_writable(published_recovery)
            if stage.exists():
                _remove_tree_writable(stage)


def _copy_payload(source: Path, destination: Path, filenames: Sequence[str]) -> list[dict[str, Any]]:
    names = _family_names(filenames)
    # A run-local SIMION directory normally also contains GEM, IOB, Lua and
    # frozen-input sidecars.  The explicit family inventory is the authority:
    # require every requested direct file, but never mistake unrelated run
    # inputs for PA-family members.  The *published generation* remains
    # exact-only and is verified by _actual_payload_names.
    if not source.is_dir():
        raise PAFamilyCacheError(f"source PA family directory is missing: {source}")
    missing = [name for name in names if not (source / name).is_file()]
    if missing:
        raise PAFamilyCacheError("source PA family is incomplete: " + ", ".join(missing))
    destination.mkdir(parents=True, exist_ok=False)
    for name in names:
        copy_verified_file(source / name, destination / name)
        shutil.copystat(source / name, destination / name)
    # Bind the generation identity to two consecutive reads of the private
    # persisted snapshot.  On Windows, a just-created large PA can otherwise
    # expose a transient buffered view to the first hash while the following
    # parity pass sees the durable bytes and correctly rejects publication.
    return stable_inventory_direct_files(destination, passes=2)


def _publish_pointer(key_root: Path, cache_key: str, generation_sha256: str) -> None:
    temporary = key_root / f".{POINTER_NAME}.{uuid4().hex}.tmp"
    _write_json(temporary, {"cache_key": cache_key, "generation_sha256": generation_sha256})
    os.replace(temporary, key_root / POINTER_NAME)


class _PAFamilyCacheKeyLock:
    """A small cross-process directory lock for one cache key publication.

    The cache never deletes an unowned lock.  A crashed publisher therefore
    fails closed rather than allowing a second writer to race a partial
    generation; an operator may inspect and remove that precise lock as a
    capacity/scratch object under the repository retention rules.
    """

    def __init__(self, cache_root: Path, cache_key: str, timeout_s: float) -> None:
        if timeout_s < 0.0:
            raise PAFamilyCacheError("PA cache publication lock timeout must be non-negative")
        self.path = cache_root / LOCK_DIRECTORY / cache_key
        self.timeout_s = timeout_s
        self.acquired = False

    def __enter__(self) -> "_PAFamilyCacheKeyLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                self.path.mkdir()
                self.acquired = True
                _write_json(self.path / "owner.json", {"cache_key": self.path.name, "pid": os.getpid()})
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise PAFamilyCacheError(f"PA cache publication lock is held: {self.path}")
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        if self.acquired:
            try:
                (self.path / "owner.json").unlink(missing_ok=True)
                self.path.rmdir()
            except OSError as exc:
                raise PAFamilyCacheError(f"cannot release PA cache publication lock: {self.path}") from exc


@contextmanager
def _capacity_protected_key(cache_root: Path, cache_key: str):
    """Protect one cache key from governed cleanup for a bounded operation."""
    artifact_root = next(
        (path for path in (cache_root, *cache_root.parents) if path.name.lower() == "artifacts"),
        None,
    )
    lease_id: str | None = None
    if artifact_root is not None and artifact_root.is_dir():
        lease_id = f"pa-family-{os.getpid()}-{uuid4().hex}"
        capacity_protection.create_capacity_protection_lease(
            artifact_root,
            lease_id=lease_id,
            owner=f"common.simion.pa_family_cache pid={os.getpid()}",
            ttl_seconds=6 * 60 * 60,
            protected_cache_keys=[cache_key],
        )
    try:
        yield
    finally:
        if lease_id is not None:
            capacity_protection.delete_capacity_protection_lease(
                artifact_root, lease_id=lease_id
            )


@contextmanager
def _protected_key_lock(cache_root: Path, cache_key: str, timeout_s: float):
    """Hold both the publisher lock and cleanup-visible capacity protection."""

    with _capacity_protected_key(cache_root, cache_key):
        with _PAFamilyCacheKeyLock(cache_root, cache_key, timeout_s):
            yield


def publish_pa_family_cache(
    cache_root: str | Path,
    identity: Mapping[str, Any],
    source_directory: str | Path,
    filenames: Sequence[str],
    *,
    lock_timeout_s: float = 30.0,
    recovery_policy: str = "xor",
) -> CachePublication:
    """Copy, verify, and atomically publish one complete PA family generation.

    Existing valid identical content is a ``hit``.  ``source_directory`` may
    contain unrelated run-local sidecars; only ``filenames`` are admitted into
    the immutable generation.  A corrupt existing entry is
    never silently overwritten: callers must investigate or use a new identity.
    """

    if recovery_policy not in {"xor", "none"}:
        raise PAFamilyCacheError("PA cache recovery policy must be 'xor' or 'none'")
    key = canonical_pa_family_cache_key(identity)
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    with _protected_key_lock(root, key, lock_timeout_s):
        existing = probe_pa_family_cache(root, identity, expected_filenames=filenames)
        if existing.disposition is CacheDisposition.HIT:
            manifest = validate_pa_family_cache_generation(existing.generation_directory, expected_cache_key=key, expected_filenames=filenames)
            existing_algorithm = (
                manifest.get("redundancy", {}).get("algorithm")
                if manifest["schema_version"] == SCHEMA_VERSION
                else None
            )
            if manifest["schema_version"] == SCHEMA_VERSION and (
                recovery_policy == "none" or existing_algorithm == PARITY_ALGORITHM
            ):
                return CachePublication(CacheDisposition.HIT, key, manifest["generation_sha256"], existing.generation_directory, manifest)
            # A v1 generation has no recoverable redundancy.  Re-publish the
            # caller's verified source as v2 instead of silently extending the
            # lifetime of an unprotected legacy payload.
        if existing.disposition is CacheDisposition.CORRUPT:
            legacy_corrupt = False
            if existing.generation_directory is not None:
                try:
                    legacy_document = json.loads(
                        (existing.generation_directory / MANIFEST_NAME).read_text(
                            encoding="utf-8-sig"
                        )
                    )
                    legacy_corrupt = legacy_document.get("schema_version") == LEGACY_SCHEMA_VERSION
                except (OSError, json.JSONDecodeError, AttributeError):
                    legacy_corrupt = False
            if not legacy_corrupt:
                raise PAFamilyCacheError(f"refusing to overwrite corrupt PA cache entry {key}: {existing.detail}")
        predecessor_generation_sha256 = (
            existing.generation_directory.name
            if existing.generation_directory is not None
            and SHA256.fullmatch(existing.generation_directory.name)
            else None
        )

        staging_root = root / STAGING_DIRECTORY
        staging_root.mkdir(exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="pa-family-", dir=staging_root))
        published_generation: Path | None = None
        published_recovery: Path | None = None
        pointer_published = False
        try:
            generation_stage = staging / "generation"
            records = _copy_payload(Path(source_directory), generation_stage, filenames)
            recovery_stage = staging / "recovery"
            redundancy = (
                _create_redundancy(generation_stage, recovery_stage, records)
                if recovery_policy == "xor"
                else {"algorithm": NO_REDUNDANCY_ALGORITHM, "groups": []}
            )
            manifest = _manifest(
                key,
                identity,
                records,
                redundancy,
                predecessor_generation_sha256=predecessor_generation_sha256,
            )
            _write_json(generation_stage / MANIFEST_NAME, manifest)
            key_root = root / key
            generations = key_root / "generations"
            generations.mkdir(parents=True, exist_ok=True)
            destination = generations / manifest["generation_sha256"]
            if destination.exists():
                incumbent = validate_pa_family_cache_generation(destination, expected_cache_key=key, expected_filenames=filenames)
                if incumbent["generation_sha256"] != manifest["generation_sha256"]:
                    raise PAFamilyCacheError("existing PA cache generation identity differs")
                _publish_pointer(key_root, key, incumbent["generation_sha256"])
                pointer_published = True
                return CachePublication(CacheDisposition.HIT, key, incumbent["generation_sha256"], destination, incumbent)
            recovery_destination = key_root / RECOVERY_DIRECTORY / manifest["generation_sha256"]
            if recovery_destination.exists():
                raise PAFamilyCacheError(
                    "orphan or conflicting PA cache recovery bundle already exists"
                )
            recovery_destination.parent.mkdir(parents=True, exist_ok=True)
            for bundle in recovery_stage.iterdir() if recovery_stage.exists() else ():
                for item in bundle.iterdir():
                    _set_file_read_only(item)
            if recovery_stage.exists():
                os.replace(recovery_stage, recovery_destination)
                published_recovery = recovery_destination
            _seal_generation_files(generation_stage, manifest)
            os.replace(generation_stage, destination)
            published_generation = destination
            validate_pa_family_cache_generation(
                destination,
                expected_cache_key=key,
                expected_filenames=filenames,
            )
            _publish_pointer(key_root, key, manifest["generation_sha256"])
            pointer_published = True
            return CachePublication(CacheDisposition.PUBLISHED, key, manifest["generation_sha256"], destination, manifest)
        finally:
            if not pointer_published:
                if published_generation is not None and published_generation.exists():
                    _remove_tree_writable(published_generation)
                if published_recovery is not None and published_recovery.exists():
                    _remove_tree_writable(published_recovery)
            if staging.exists():
                _remove_tree_writable(staging)


def migrate_current_pa_family_cache(
    cache_root: str | Path,
    identity: Mapping[str, Any],
    filenames: Sequence[str],
    *,
    lock_timeout_s: float = 30.0,
) -> CachePublication:
    """Migrate the current healthy v1 generation to recoverable schema v2.

    The legacy generation is consumed only through immutable snapshots into a
    disposable writable staging directory.  Publication then follows the same
    v2 atomic path as a normal build, without SIMION or Refine.
    """

    root = Path(cache_root)
    key = canonical_pa_family_cache_key(identity)
    with _capacity_protected_key(root, key):
        probe = probe_pa_family_cache(
            root, identity, expected_filenames=filenames
        )
        if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
            raise PAFamilyCacheError(
                f"cannot migrate PA cache {key}: {probe.disposition.value}: {probe.detail}"
            )
        manifest = validate_pa_family_cache_generation(
            probe.generation_directory,
            expected_cache_key=key,
            expected_filenames=filenames,
        )
        if manifest["schema_version"] == SCHEMA_VERSION:
            return CachePublication(
                CacheDisposition.HIT,
                key,
                manifest["generation_sha256"],
                probe.generation_directory,
                manifest,
            )
        if manifest["schema_version"] != LEGACY_SCHEMA_VERSION:
            raise PAFamilyCacheError("PA cache migration source schema is unsupported")
        with tempfile.TemporaryDirectory(prefix="pa-family-migrate-") as temporary:
            staging = Path(temporary)
            materialize_pa_family_cache(
                probe.generation_directory,
                staging,
                expected_filenames=filenames,
            )
            return publish_pa_family_cache(
                root,
                identity,
                staging,
                filenames,
                lock_timeout_s=lock_timeout_s,
            )


def materialize_pa_family_cache(
    generation_directory: str | Path,
    destination_directory: str | Path,
    *,
    expected_filenames: Sequence[str] | None = None,
) -> MaterializedFamily:
    """Copy a validated family into a run-local directory without overwriting it.

    A run's SIMION directory commonly already contains frozen GEM, Lua and
    Fly2 inputs.  Those sidecars are not cache payload and may remain in the
    destination.  Every declared PA filename, however, must be absent before
    publication; this prevents a cache hit from silently mixing two families.
    """

    source = Path(generation_directory)
    repair: CacheRepair | None = None
    try:
        manifest = validate_pa_family_cache_generation(
            source, expected_filenames=expected_filenames
        )
    except PAFamilyCacheError as original_error:
        try:
            repair = repair_pa_family_cache_generation(source)
        except PAFamilyCacheError as repair_error:
            raise original_error from repair_error
        source = repair.generation_directory
        manifest = validate_pa_family_cache_generation(
            source, expected_filenames=expected_filenames
        )
    destination = Path(destination_directory)
    collisions = [
        record["name"] for record in manifest["files"]
        if (destination / record["name"]).exists()
        or (destination / record["name"]).is_symlink()
    ]
    if collisions:
        raise PAFamilyCacheError(
            "materialization would overwrite existing files: " + ", ".join(collisions)
        )
    try:
        if not destination.exists():
            copied = materialize_direct_inventory(source, destination, manifest["files"])
        else:
            if not destination.is_dir():
                raise ValueError("materialization destination is not a directory")
            temporary = destination.parent / f".{destination.name}.family-{uuid4().hex}"
            moved: list[Path] = []
            try:
                copied = materialize_direct_inventory(source, temporary, manifest["files"])
                for record in manifest["files"]:
                    target = destination / record["name"]
                    os.replace(temporary / record["name"], target)
                    moved.append(target)
            except Exception:
                for target in moved:
                    target.unlink(missing_ok=True)
                raise
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
    except ValueError as exc:
        raise PAFamilyCacheError(str(exc)) from exc
    return MaterializedFamily(
        destination.resolve(),
        tuple(copied),
        source.resolve(),
        repair.predecessor_directory if repair is not None else None,
        repair.receipt_path if repair is not None else None,
    )


def _cli_identity(path: Path) -> dict[str, Any]:
    """Read one caller-owned cache identity without adding device semantics."""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError(f"PA cache identity JSON is unreadable: {path}") from exc
    return _canonical_identity(value)


def _cli_filenames(value: str) -> tuple[str, ...]:
    """Parse an explicit direct-file inventory for the command-line adapter."""
    return _family_names(value.split(","))


def main(arguments: Sequence[str] | None = None) -> int:
    """Expose the device-neutral cache to thin PowerShell/project adapters.

    The caller owns the identity JSON and filename inventory.  A materialize
    miss is an error rather than an implicit build: only the device workflow
    may decide when it is valid to invoke SIMION Refine.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=("probe", "ensure", "publish", "migrate", "repair", "materialize"), required=True
    )
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--filenames", required=True, help="comma-separated direct PA-family filenames")
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--destination-directory", type=Path)
    parser.add_argument("--lock-timeout-s", type=float, default=30.0)
    args = parser.parse_args(arguments)
    identity = _cli_identity(args.identity)
    filenames = _cli_filenames(args.filenames)
    if args.action in {"probe", "ensure"}:
        if args.source_directory is not None or args.destination_directory is not None:
            parser.error(
                f"{args.action} accepts neither --source-directory nor --destination-directory"
            )
        result = (
            probe_pa_family_cache(
                args.cache_root, identity, expected_filenames=filenames
            )
            if args.action == "probe"
            else ensure_pa_family_cache(
                args.cache_root,
                identity,
                expected_filenames=filenames,
                lock_timeout_s=args.lock_timeout_s,
            )
        )
        document: dict[str, Any] = {"disposition": result.disposition.value, "cache_key": result.cache_key,
                                    "generation_sha256": result.generation_directory.name if result.generation_directory else None,
                                    "generation_directory": str(result.generation_directory) if result.generation_directory else None,
                                    "detail": result.detail}
    elif args.action == "publish":
        if args.source_directory is None or args.destination_directory is not None:
            parser.error("publish requires --source-directory and forbids --destination-directory")
        result = publish_pa_family_cache(
            args.cache_root, identity, args.source_directory, filenames, lock_timeout_s=args.lock_timeout_s,
        )
        document = {"disposition": result.disposition.value, "cache_key": result.cache_key,
                    "generation_sha256": result.generation_sha256,
                    "generation_directory": str(result.generation_directory)}
    elif args.action == "migrate":
        if args.source_directory is not None or args.destination_directory is not None:
            parser.error("migrate accepts neither --source-directory nor --destination-directory")
        result = migrate_current_pa_family_cache(
            args.cache_root,
            identity,
            filenames,
            lock_timeout_s=args.lock_timeout_s,
        )
        document = {
            "disposition": result.disposition.value,
            "cache_key": result.cache_key,
            "generation_sha256": result.generation_sha256,
            "generation_directory": str(result.generation_directory),
            "schema_version": result.manifest["schema_version"],
            "predecessor_generation_sha256": result.manifest.get(
                "predecessor_generation_sha256"
            ),
        }
    elif args.action == "repair":
        if args.source_directory is not None or args.destination_directory is not None:
            parser.error("repair accepts neither --source-directory nor --destination-directory")
        probe = probe_pa_family_cache(
            args.cache_root, identity, expected_filenames=filenames
        )
        if (
            probe.disposition is not CacheDisposition.CORRUPT
            or probe.generation_directory is None
        ):
            raise PAFamilyCacheError(
                f"cannot repair PA cache {probe.cache_key}: {probe.disposition.value}"
            )
        repaired = repair_pa_family_cache_generation(
            probe.generation_directory, lock_timeout_s=args.lock_timeout_s
        )
        document = {
            "disposition": "repaired",
            "cache_key": repaired.cache_key,
            "generation_sha256": repaired.generation_sha256,
            "generation_directory": str(repaired.generation_directory),
            "predecessor_generation_directory": str(repaired.predecessor_directory),
            "repaired_member": repaired.repaired_member,
            "receipt_path": str(repaired.receipt_path),
        }
    else:
        if args.destination_directory is None or args.source_directory is not None:
            parser.error("materialize requires --destination-directory and forbids --source-directory")
        probe = ensure_pa_family_cache(
            args.cache_root,
            identity,
            expected_filenames=filenames,
            lock_timeout_s=args.lock_timeout_s,
        )
        if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
            raise PAFamilyCacheError(f"cannot materialize PA cache {probe.cache_key}: {probe.disposition.value}: {probe.detail}")
        result = materialize_pa_family_cache(
            probe.generation_directory, args.destination_directory, expected_filenames=filenames,
        )
        document = {"disposition": "materialized", "cache_key": probe.cache_key,
                    "generation_directory": str(result.source_generation_directory),
                    "predecessor_generation_directory": (
                        str(result.predecessor_generation_directory)
                        if result.predecessor_generation_directory else None
                    ),
                    "repair_receipt_path": (
                        str(result.repair_receipt_path) if result.repair_receipt_path else None
                    ),
                    "destination_directory": str(result.destination_directory), "files": list(result.files)}
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
