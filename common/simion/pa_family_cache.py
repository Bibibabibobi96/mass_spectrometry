"""Content-addressed, device-neutral cache for complete SIMION PA families.

The cache deliberately knows no electrode IDs, geometry coordinates, or PA file
suffix conventions.  A caller supplies the complete direct-file family it has
built and a full numerical identity.  A cache entry is usable only when both
the identity and every recorded byte are intact.
"""
from __future__ import annotations

import argparse
import hashlib
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

from common.contracts import capacity_ledger, capacity_protection
from common.contracts.file_identity import canonical_json_sha256, file_sha256, file_sha256_unbuffered
from common.simion.cache_generation import (
    _WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES,
    _flush_writable_source,
    _remove_tree_writable,
    materialize_direct_inventory, inventory_named_files, copy_verified_file,
    snapshot_immutable_file, stable_inventory_direct_files,
    validate_direct_inventory,
)
from common.simion.immutable_pa_parity import (
    ALGORITHM as PARITY_ALGORITHM,
    MANIFEST_FILENAME as PARITY_MANIFEST_NAME,
    create_xor_parity_bundle,
    verify_and_recover_xor_parity,
)
from common.simion.standalone_pa_response_set import (
    ResponseExport, _normalize_exports, write_standalone_pa_response_set,
)


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
ROLE = "simion_pa_family_cache"
MANIFEST_NAME = "cache_manifest.json"
POINTER_NAME = "current_generation.json"
STAGING_DIRECTORY = ".staging"
TRANSACTION_DIRECTORY = ".transactions"
TRANSACTION_NAME = "transaction.json"
LOCK_DIRECTORY = ".locks"
RECOVERY_DIRECTORY = "recovery"
PUBLICATION_ERROR_NAME = "publication_error.json"
TRANSACTION_ROLE = "simion_pa_family_cache_transaction"
VERIFICATION_EVIDENCE_ROLE = "simion_pa_family_verification"
TRANSACTION_STATES = {"building", "prepared", "published", "retired"}
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
class TransactionAdvance:
    cache_key: str
    status: str
    action_required: str
    transaction_directory: Path
    build_directory: Path
    scratch_directory: Path
    inventory_sha256: str | None = None
    generation_sha256: str | None = None
    generation_directory: Path | None = None
    missing_files: tuple[str, ...] = ()
    publication_metadata_correction_receipt: Path | None = None


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


def _validate_sealed_generation_metadata(
    generation_directory: str | Path,
    *,
    expected_cache_key: str | None = None,
    expected_filenames: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate sealed generation structure without rereading payload bytes.

    Publication already stabilized every payload and generated parity from the
    same records.  A normal current-generation hit only needs to inspect the
    sealed manifest, exact names/sizes, read-only state and parity structure;
    the explicit ``validate_pa_family_cache_generation`` path remains the
    full-byte audit used after an anomaly or for a pinned integrity check.
    """

    root = Path(generation_directory)
    manifest_path = root / MANIFEST_NAME
    if not root.is_dir() or root.is_symlink() or not manifest_path.is_file():
        raise PAFamilyCacheError(f"PA cache generation metadata is missing: {root}")
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
    if schema_version not in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION} or manifest["role"] != ROLE:
        raise PAFamilyCacheError("PA cache manifest identity differs")
    identity = _canonical_identity(manifest["identity"])
    cache_key = manifest["cache_key"]
    if not isinstance(cache_key, str) or not SHA256.fullmatch(cache_key):
        raise PAFamilyCacheError("PA cache key is invalid")
    if canonical_pa_family_cache_key(identity) != cache_key:
        raise PAFamilyCacheError("PA cache key differs from identity")
    if expected_cache_key is not None and cache_key != expected_cache_key:
        raise PAFamilyCacheError("PA cache key differs from requested identity")
    if root.name != manifest["generation_sha256"] or not SHA256.fullmatch(root.name):
        raise PAFamilyCacheError("PA cache generation directory identity differs")
    records = manifest["files"]
    if not isinstance(records, list) or not records:
        raise PAFamilyCacheError("PA cache inventory is empty")
    records_by_name: dict[str, Mapping[str, Any]] = {}
    names: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "bytes", "sha256"}:
            raise PAFamilyCacheError("PA cache inventory record fields differ")
        name = _safe_name(record["name"])
        if (
            not isinstance(record["bytes"], int)
            or isinstance(record["bytes"], bool)
            or record["bytes"] < 0
            or not isinstance(record["sha256"], str)
            or not SHA256.fullmatch(record["sha256"])
        ):
            raise PAFamilyCacheError("PA cache inventory record identity is invalid")
        names.append(name)
        records_by_name[name] = record
    if names != sorted(names) or len(names) != len(set(names)):
        raise PAFamilyCacheError("PA cache inventory filenames are not sorted and unique")
    if _actual_payload_names(root) != set(names):
        raise PAFamilyCacheError("PA cache generation payload inventory differs")
    predecessor = manifest.get("predecessor_generation_sha256")
    if predecessor is not None and (
        not isinstance(predecessor, str) or not SHA256.fullmatch(predecessor)
    ):
        raise PAFamilyCacheError("PA cache predecessor generation is invalid")
    redundancy = manifest.get("redundancy") if schema_version == SCHEMA_VERSION else None
    if manifest["generation_sha256"] != _generation_sha256(
        cache_key, records, redundancy, predecessor
    ):
        raise PAFamilyCacheError("PA cache generation identity differs")
    if schema_version == SCHEMA_VERSION:
        if not isinstance(redundancy, dict) or set(redundancy) != {"algorithm", "groups"}:
            raise PAFamilyCacheError("PA cache redundancy metadata differs")
        if redundancy["algorithm"] == NO_REDUNDANCY_ALGORITHM:
            if redundancy["groups"] != []:
                raise PAFamilyCacheError("reconstructible PA cache must not declare recovery groups")
            recovery_root = root.parents[1] / RECOVERY_DIRECTORY / manifest["generation_sha256"]
            if recovery_root.exists():
                raise PAFamilyCacheError("reconstructible PA cache has an unexpected recovery bundle")
        elif redundancy["algorithm"] == PARITY_ALGORITHM:
            expected_groups = _redundancy_groups(records)
            groups = redundancy["groups"]
            compact_groups = [
                {
                    "bundle": group.get("bundle"),
                    "member_length_bytes": group.get("member_length_bytes"),
                    "members": group.get("members"),
                }
                for group in groups
                if isinstance(group, dict)
            ]
            if compact_groups != expected_groups or len(compact_groups) != len(groups):
                raise PAFamilyCacheError("PA cache redundancy groups differ from payload inventory")
            recovery_root = root.parents[1] / RECOVERY_DIRECTORY / manifest["generation_sha256"]
            for group in groups:
                if set(group) != {
                    "bundle", "member_length_bytes", "members", "manifest_sha256", "parity_sha256"
                }:
                    raise PAFamilyCacheError("PA cache redundancy group fields differ")
                if not SHA256.fullmatch(str(group["manifest_sha256"])) or not SHA256.fullmatch(
                    str(group["parity_sha256"])
                ):
                    raise PAFamilyCacheError("PA cache redundancy digest is invalid")
                bundle = recovery_root / str(group["bundle"])
                parity_manifest_path = bundle / PARITY_MANIFEST_NAME
                if (
                    not parity_manifest_path.is_file()
                    or parity_manifest_path.is_symlink()
                    or parity_manifest_path.stat().st_mode
                    & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
                ):
                    raise PAFamilyCacheError("PA cache redundancy manifest is missing")
                try:
                    parity_manifest = json.loads(
                        parity_manifest_path.read_text(encoding="utf-8-sig")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    raise PAFamilyCacheError("PA cache redundancy manifest is unreadable") from exc
                if file_sha256(parity_manifest_path) != group["manifest_sha256"]:
                    raise PAFamilyCacheError("PA cache redundancy manifest identity differs")
                if (
                    parity_manifest.get("algorithm") != PARITY_ALGORITHM
                    or parity_manifest.get("members") != [records_by_name[name] for name in group["members"]]
                ):
                    raise PAFamilyCacheError("PA cache redundancy members differ")
                parity = parity_manifest.get("parity")
                if not isinstance(parity, dict) or set(parity) != {"name", "bytes", "sha256"}:
                    raise PAFamilyCacheError("PA cache redundancy payload metadata differs")
                parity_path = bundle / str(parity["name"])
                if (
                    not parity_path.is_file()
                    or parity_path.is_symlink()
                    or parity_path.stat().st_size != group["member_length_bytes"]
                    or parity["bytes"] != group["member_length_bytes"]
                    or parity["sha256"] != group["parity_sha256"]
                    or not SHA256.fullmatch(str(parity["sha256"]))
                    or parity_path.stat().st_mode
                    & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
                ):
                    raise PAFamilyCacheError("PA cache redundancy payload metadata differs")
                bundle_entries = {item.name for item in bundle.iterdir()}
                if bundle_entries != {PARITY_MANIFEST_NAME, str(parity["name"])}:
                    raise PAFamilyCacheError("PA cache redundancy bundle inventory differs")
        else:
            raise PAFamilyCacheError("PA cache redundancy algorithm differs")
    selected = _family_names(expected_filenames) if expected_filenames is not None else tuple(names)
    missing = [name for name in selected if name not in records_by_name]
    if missing:
        raise PAFamilyCacheError(
            "PA cache subset is absent from the generation manifest: " + ", ".join(missing)
        )
    for name in names + [MANIFEST_NAME]:
        path = root / name
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise PAFamilyCacheError(f"PA cache generation is not sealed read-only: {name}")
        if name != MANIFEST_NAME and path.stat().st_size != records_by_name[name]["bytes"]:
            raise PAFamilyCacheError(f"PA cache payload length differs: {name}")
    return manifest


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


def _validate_redundancy_metadata(
    root: Path, manifest: Mapping[str, Any], *, verify_payload: bool = True
) -> None:
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
        if verify_payload:
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
    verify_payload: bool = True,
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
        if verify_payload:
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
        _validate_redundancy_metadata(root, manifest, verify_payload=verify_payload)
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
    """Classify the current generation without hashing a healthy payload.

    A governed artifact-cache hit advances its ledger ``last_used_epoch``.  It
    does not create a protection lease; workflows that need to exclude
    retirement while consuming a hit must hold their own explicit lease.
    """

    key = canonical_pa_family_cache_key(identity)
    root = Path(cache_root)
    key_root = root / key
    transaction_path = root / TRANSACTION_DIRECTORY / key / TRANSACTION_NAME
    if transaction_path.exists():
        try:
            transaction = _load_transaction_by_key(transaction_path, key)
        except PAFamilyCacheError as exc:
            return CacheProbe(
                CacheDisposition.CORRUPT,
                key,
                detail=f"transaction authority is unreadable: {exc}",
            )
        if transaction["status"] == "retired":
            return CacheProbe(
                CacheDisposition.MISS,
                key,
                detail="current generation has an approved retirement",
            )
        correction = transaction.get("publication_metadata_correction")
        if correction is not None and not correction["complete"]:
            return CacheProbe(CacheDisposition.CORRUPT, key, detail="publication metadata correction is pending")
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
        try:
            manifest = _validate_sealed_generation_metadata(
                directory, expected_cache_key=key, expected_filenames=expected_filenames
            )
        except PAFamilyCacheError:
            # A metadata anomaly (length, writable bit, parity structure, or
            # pointer drift) earns one full-byte audit so callers receive the
            # existing corruption detail and repair can remain fail-closed.
            manifest = validate_pa_family_cache_generation(
                directory, expected_cache_key=key, expected_filenames=expected_filenames
            )
        if manifest["generation_sha256"] != generation:
            raise PAFamilyCacheError("generation pointer differs from manifest")
    except (OSError, json.JSONDecodeError, KeyError, PAFamilyCacheError) as exc:
        return CacheProbe(CacheDisposition.CORRUPT, key, directory, detail=str(exc))
    _record_cache_hit(root, key, generation)
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
    """A small crash-releasing OS file lock for one cache key publication."""

    def __init__(self, cache_root: Path, cache_key: str, timeout_s: float) -> None:
        if timeout_s < 0.0:
            raise PAFamilyCacheError("PA cache publication lock timeout must be non-negative")
        self.path = cache_root / LOCK_DIRECTORY / f"{cache_key}.lock"
        self.timeout_s = timeout_s
        self.handle: Any | None = None

    @staticmethod
    def _try_lock(handle: Any) -> bool:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    @staticmethod
    def _unlock(handle: Any) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __enter__(self) -> "_PAFamilyCacheKeyLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_s
        while True:
            handle: Any | None = None
            try:
                try:
                    handle = self.path.open("x+b", buffering=0)
                    handle.write(b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                except FileExistsError:
                    handle = self.path.open("r+b", buffering=0)
                    if self.path.stat().st_size == 0:
                        handle.write(b"\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                break
            except PermissionError:
                if handle is not None:
                    handle.close()
                if time.monotonic() >= deadline:
                    raise PAFamilyCacheError(f"PA cache publication lock is held: {self.path}")
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        while True:
            if self._try_lock(handle):
                self.handle = handle
                owner = json.dumps(
                    {"cache_key": self.path.stem, "pid": os.getpid()},
                    sort_keys=True,
                ).encode("utf-8")
                handle.seek(0)
                handle.truncate()
                handle.write(owner + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
                return self
            if time.monotonic() >= deadline:
                handle.close()
                raise PAFamilyCacheError(f"PA cache publication lock is held: {self.path}")
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        if self.handle is not None:
            try:
                self._unlock(self.handle)
                self.handle.close()
                self.handle = None
            except OSError as exc:
                raise PAFamilyCacheError(f"cannot release PA cache publication lock: {self.path}") from exc


@dataclass(frozen=True)
class _ArtifactLedgerBinding:
    artifact_root: Path
    key_root: Path


def _artifact_root_for_cache(cache_root: Path) -> Path | None:
    absolute = cache_root.resolve(strict=False)
    return next(
        (path for path in (absolute, *absolute.parents) if path.name.lower() == "artifacts"),
        None,
    )


def _artifact_ledger_binding(
    cache_root: Path, cache_key: str, *, required: bool
) -> _ArtifactLedgerBinding | None:
    artifact_root = _artifact_root_for_cache(cache_root)
    if artifact_root is None:
        return None
    ledger = capacity_ledger.load_capacity_ledger(artifact_root)
    if ledger is None:
        if required:
            raise PAFamilyCacheError(
                "artifact PA cache publication requires a calibrated capacity ledger"
            )
        return None
    return _ArtifactLedgerBinding(
        artifact_root=artifact_root,
        key_root=(cache_root / cache_key).resolve(strict=False),
    )


def _key_root_bytes(key_root: Path) -> int:
    """Measure one governed key-root using metadata only, never payload hashes."""

    if not key_root.exists():
        return 0
    if not key_root.is_dir() or key_root.is_symlink():
        raise PAFamilyCacheError(f"PA cache key root is not a real directory: {key_root}")
    total = 0
    for directory, directories, filenames in os.walk(key_root):
        root = Path(directory)
        for name in directories:
            child = root / name
            if child.is_symlink():
                raise PAFamilyCacheError(
                    f"PA cache key root contains a directory symlink: {child}"
                )
        for name in filenames:
            child = root / name
            if child.is_symlink() or not child.is_file():
                raise PAFamilyCacheError(
                    f"PA cache key root contains a non-file payload: {child}"
                )
            total += child.stat().st_size
    return total


def _record_artifact_cache_state(
    binding: _ArtifactLedgerBinding | None,
    generation_sha256: str,
    status: str,
    *, published_pin_reason: str | None = None,
) -> None:
    if binding is None:
        return
    try:
        ledger = capacity_ledger.load_capacity_ledger(binding.artifact_root)
        _, key_relative = capacity_ledger.capacity_object_path(
            binding.artifact_root, binding.key_root
        )
        existing = (
            next(
                (item for item in ledger["objects"] if item.get("path") == key_relative),
                None,
            )
            if ledger is not None else None
        )
        owner = existing.get("owner") if isinstance(existing, dict) else None
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("PA cache range has no managed owner")
        recovery = {}
        if status == "writing":
            transaction = (
                binding.key_root.parent / TRANSACTION_DIRECTORY
                / binding.key_root.name / TRANSACTION_NAME
            )
            recovery = {
                "recovery_reason": "pa_cache_publication_incomplete",
                "review_deadline": (
                    datetime.now(timezone.utc).date() + timedelta(days=7)
                ).isoformat(),
                "recovery_task": "resume or retire the exact PA owner transaction",
                "recovery_evidence_paths": (transaction,),
            }
        capacity_ledger.record_capacity_object(
            binding.artifact_root,
            path=binding.key_root,
            object_class="published_cache",
            bytes_count=_key_root_bytes(binding.key_root),
            status=status,
            identity=generation_sha256,
            pin=published_pin_reason is not None,
            pin_reason=published_pin_reason,
            owner=owner,
            **recovery,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PAFamilyCacheError(
            f"cannot record PA cache {status} lifecycle state: {binding.key_root}"
        ) from exc


def _touch_artifact_cache(
    binding: _ArtifactLedgerBinding | None, generation_sha256: str
) -> None:
    if binding is None:
        return
    error_receipt = binding.key_root / PUBLICATION_ERROR_NAME
    error_receipt.unlink(missing_ok=True)
    _record_artifact_cache_state(binding, generation_sha256, "ready")
    try:
        capacity_ledger.touch_capacity_object(
            binding.artifact_root,
            path=binding.key_root,
            when_epoch=time.time(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PAFamilyCacheError(
            f"cannot update PA cache last-used time: {binding.key_root}"
        ) from exc


def _preserve_artifact_publication_failure(
    binding: _ArtifactLedgerBinding | None,
    generation_sha256: str | None,
    operation: str,
    error: BaseException,
) -> None:
    if binding is None or generation_sha256 is None:
        return
    binding.key_root.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": 1,
        "role": "simion_pa_family_cache_publication_error",
        "status": "writing",
        "operation": operation,
        "generation_sha256": generation_sha256,
        "error_type": type(error).__name__,
        "error": str(error)[:4096],
        "observed_at_epoch": time.time(),
    }
    try:
        _write_json(binding.key_root / PUBLICATION_ERROR_NAME, receipt)
        _record_artifact_cache_state(binding, generation_sha256, "writing")
    except Exception as receipt_error:
        raise PAFamilyCacheError(
            "PA cache publication failed and its governed writing/error state "
            f"could not be preserved: {binding.key_root}"
        ) from receipt_error


def _record_cache_hit(cache_root: Path, cache_key: str, generation_sha256: str) -> None:
    binding = _artifact_ledger_binding(cache_root, cache_key, required=False)
    if binding is None:
        return
    try:
        ledger = capacity_ledger.load_capacity_ledger(binding.artifact_root)
        if ledger is None:
            # ``_artifact_ledger_binding`` already observed a valid ledger.  A
            # disappearance or invalidation between those reads is a capacity
            # state race, not permission to continue with an ungoverned hit.
            raise ValueError("capacity ledger changed while recording cache use")
        _, relative = capacity_ledger.capacity_object_path(
            binding.artifact_root, binding.key_root
        )
        entry = next(
            (item for item in ledger["objects"] if item.get("path") == relative),
            None,
        )
        if entry is None:
            raise ValueError("calibrated capacity ledger omits the cache key root")
        if entry.get("class") != "published_cache":
            raise ValueError("cache key root has the wrong capacity object class")
        if entry.get("status") == "writing":
            # A pointer can be durably published before the final ledger touch
            # fails.  Only the matching failure receipt proves that this exact
            # current generation, rather than an in-flight successor, owns the
            # writing state.  A normal probe may then finish the interrupted
            # bookkeeping without rebuilding or weakening payload validation.
            error_path = binding.key_root / PUBLICATION_ERROR_NAME
            try:
                error = json.loads(error_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                return
            if (
                not isinstance(error, dict)
                or error.get("role") != "simion_pa_family_cache_publication_error"
                or error.get("status") != "writing"
                or error.get("generation_sha256") != generation_sha256
            ):
                return
            _touch_artifact_cache(binding, generation_sha256)
            return
        if entry.get("status") != "ready":
            raise ValueError("cache key root is not available for consumption")
        if entry.get("identity") != generation_sha256:
            raise ValueError("cache generation differs from its capacity identity")
        capacity_ledger.touch_capacity_object(
            binding.artifact_root,
            path=binding.key_root,
            when_epoch=time.time(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PAFamilyCacheError(
            f"cannot update PA cache last-used time: {binding.key_root}"
        ) from exc


def _require_managed_pa_consumer_binding(
    cache_root: Path,
    manifest: Mapping[str, Any],
    *,
    capacity_lease_id: str | None,
    capacity_lease_owner: str | None,
) -> None:
    """Fail closed before copying a governed PA into a consumer workspace.

    This checks only transaction, ledger, lease and sealed-manifest metadata.
    In particular, it deliberately does not hash PA payloads on a healthy hit.
    """

    cache_key = str(manifest["cache_key"])
    generation = str(manifest["generation_sha256"])
    binding = _artifact_ledger_binding(cache_root, cache_key, required=False)
    if _artifact_root_for_cache(cache_root) is not None and binding is None:
        raise PAFamilyCacheError(
            "managed PA consumption requires a valid capacity ledger binding"
        )
    if binding is None:
        return
    if not isinstance(capacity_lease_id, str) or not capacity_lease_id:
        raise PAFamilyCacheError("managed PA consumption requires an active protection lease id")
    if not isinstance(capacity_lease_owner, str) or not capacity_lease_owner.strip():
        raise PAFamilyCacheError("managed PA consumption requires the protection lease owner")
    try:
        transaction = _load_transaction_by_key(
            cache_root / TRANSACTION_DIRECTORY / cache_key / TRANSACTION_NAME,
            cache_key,
        )
        if (
            transaction["status"] != "published"
            or transaction["generation_sha256"] != generation
        ):
            raise ValueError("PA transaction is not the active published generation")
        ledger = capacity_ledger.load_capacity_ledger(binding.artifact_root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        _, relative = capacity_ledger.capacity_object_path(
            binding.artifact_root, binding.key_root
        )
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if (
            entry is None
            or entry.get("class") != "published_cache"
            or entry.get("status") != "ready"
            or entry.get("identity") != generation
            or entry.get("manager") != capacity_ledger.PA_CACHE_MANAGER
        ):
            raise ValueError("PA capacity ledger binding differs")
        leases = capacity_protection.load_capacity_protection_leases(binding.artifact_root)
        active = next(
            (
                item for item in leases["audit"]
                if item.get("status") == "active"
                and item.get("lease_id") == capacity_lease_id
                and item.get("owner") == capacity_lease_owner.strip()
                and cache_key.lower() in item.get("protected_cache_keys", [])
            ),
            None,
        )
        if active is None:
            raise ValueError("PA protection lease is absent, expired, or does not cover the cache key")
    except (OSError, RuntimeError, ValueError) as exc:
        raise PAFamilyCacheError(f"managed PA consumption binding is invalid: {exc}") from exc


def _complete_artifact_cache_rollback(
    binding: _ArtifactLedgerBinding | None,
    predecessor_generation_sha256: str | None,
) -> None:
    """Record the exact post-rollback key root without inventing a generation."""

    if binding is None:
        return
    (binding.key_root / PUBLICATION_ERROR_NAME).unlink(missing_ok=True)
    if predecessor_generation_sha256 is not None:
        _touch_artifact_cache(binding, predecessor_generation_sha256)
        return
    try:
        ledger = capacity_ledger.load_capacity_ledger(binding.artifact_root)
        _, key_relative = capacity_ledger.capacity_object_path(
            binding.artifact_root, binding.key_root
        )
        entry = next(
            (item for item in (ledger or {}).get("objects", []) if item.get("path") == key_relative),
            None,
        )
        owner = entry.get("owner") if isinstance(entry, dict) else None
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("rolled-back PA cache has no managed owner")
        # With no predecessor there is no published family identity to claim.
        # The rollback receipt is still resident evidence, so model the whole
        # key root as one removable rebuildable payload rather than falsely
        # retiring bytes that remain on disk.
        capacity_ledger.record_capacity_object(
            binding.artifact_root,
            path=binding.key_root,
            object_class="rebuildable_payload",
            bytes_count=_key_root_bytes(binding.key_root),
            status="ready",
            owner=owner,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PAFamilyCacheError(
            f"cannot record rolled-back PA cache evidence: {binding.key_root}"
        ) from exc


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
        yield lease_id
    finally:
        if lease_id is not None:
            capacity_protection.delete_capacity_protection_lease(
                artifact_root, lease_id=lease_id
            )


@contextmanager
def _protected_key_lock(cache_root: Path, cache_key: str, timeout_s: float):
    """Hold both the publisher lock and cleanup-visible capacity protection."""

    with _capacity_protected_key(cache_root, cache_key) as lease_id:
        with _PAFamilyCacheKeyLock(cache_root, cache_key, timeout_s):
            yield lease_id


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
    # A cache below the repository artifact root is a managed, durable asset.
    # Publishing it without the authoritative transaction would make the
    # pointer visible before there is an owner, verification record, or
    # recoverable ledger handoff.  Keep this compatibility helper for
    # disposable test/local caches only; production callers must use the
    # transaction API below.
    if _artifact_root_for_cache(root) is not None:
        raise PAFamilyCacheError(
            "artifact PA publication requires advance_pa_family_cache_transaction"
        )
    ledger_binding = _artifact_ledger_binding(root, key, required=True)
    root.mkdir(parents=True, exist_ok=True)
    with _protected_key_lock(root, key, lock_timeout_s):
        existing = probe_pa_family_cache(root, identity, expected_filenames=filenames)
        if existing.disposition is CacheDisposition.HIT:
            manifest = _validate_sealed_generation_metadata(
                existing.generation_directory,
                expected_cache_key=key,
                expected_filenames=filenames,
            )
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
        ledger_registered = False
        target_generation_sha256: str | None = None
        publication_error: BaseException | None = None
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
            target_generation_sha256 = manifest["generation_sha256"]
            _record_artifact_cache_state(
                ledger_binding, target_generation_sha256, "writing"
            )
            ledger_registered = ledger_binding is not None
            generations = key_root / "generations"
            generations.mkdir(parents=True, exist_ok=True)
            destination = generations / manifest["generation_sha256"]
            if destination.exists():
                incumbent = _validate_sealed_generation_metadata(
                    destination,
                    expected_cache_key=key,
                    expected_filenames=filenames,
                )
                if incumbent["generation_sha256"] != manifest["generation_sha256"]:
                    raise PAFamilyCacheError("existing PA cache generation identity differs")
                _publish_pointer(key_root, key, incumbent["generation_sha256"])
                pointer_published = True
                _touch_artifact_cache(ledger_binding, incumbent["generation_sha256"])
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
            _validate_sealed_generation_metadata(
                destination,
                expected_cache_key=key,
                expected_filenames=filenames,
            )
            _publish_pointer(key_root, key, manifest["generation_sha256"])
            pointer_published = True
            _touch_artifact_cache(ledger_binding, manifest["generation_sha256"])
            return CachePublication(CacheDisposition.PUBLISHED, key, manifest["generation_sha256"], destination, manifest)
        except BaseException as exc:
            publication_error = exc
            raise
        finally:
            if not pointer_published:
                if published_generation is not None and published_generation.exists():
                    _remove_tree_writable(published_generation)
                if published_recovery is not None and published_recovery.exists():
                    _remove_tree_writable(published_recovery)
            if staging.exists():
                _remove_tree_writable(staging)
            if publication_error is not None and ledger_registered:
                _preserve_artifact_publication_failure(
                    ledger_binding,
                    target_generation_sha256,
                    "publish",
                    publication_error,
                )


def _inventory_transaction_payload(
    payload: Path,
    filenames: Sequence[str],
) -> list[dict[str, Any]]:
    try:
        names = _family_names(filenames)
        # A transaction owns payload only after all producers have exited.  A
        # flush establishes its final byte view; the following single hash
        # inventory becomes the immutable generation identity.  Recopying the
        # complete family to "prove" the same closure wastes large-file I/O
        # and cannot create a stronger writer boundary than the transaction
        # lock already supplies.
        for name in names:
            _flush_writable_source(payload / name)
        return inventory_named_files(payload, names, unbuffered_large_files=True)
    except (OSError, ValueError) as exc:
        raise PAFamilyCacheError(
            f"PA transaction payload inventory is not stable: {payload}"
        ) from exc


def _write_transaction(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        _write_json(temporary, document)
        _flush_writable_source(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_transaction(
    path: Path, *, cache_key: str, identity: Mapping[str, Any], filenames: Sequence[str]
) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError(f"PA cache transaction is unreadable: {path}") from exc
    required = {
        "schema_version", "role", "cache_key", "identity", "filenames", "status",
        "owner", "files", "inventory_sha256", "verification",
        "generation_sha256", "published_pin_reason", "retirement", "last_error",
    }
    if (not isinstance(document, dict) or not required <= set(document)
            or set(document) - required - {"member_recovery", "response_receipt", "retained_inventory_recovery", "publication_metadata_correction", "abandonment", "pin_release"}):
        raise PAFamilyCacheError("PA cache transaction fields differ")
    if (
            document["schema_version"] != 1
        or document["role"] != TRANSACTION_ROLE
        or document["cache_key"] != cache_key
        or _canonical_identity(document["identity"]) != _canonical_identity(identity)
        or tuple(document["filenames"]) != _family_names(filenames)
        or document["status"] not in TRANSACTION_STATES
        or not isinstance(document["owner"], str)
        or not document["owner"].strip()
        or len(document["owner"]) > 256
        or (
            document["published_pin_reason"] is not None
            and (
                not isinstance(document["published_pin_reason"], str)
                or not document["published_pin_reason"].strip()
            )
        )
        or (document["last_error"] is not None and not isinstance(document["last_error"], str))
    ):
        raise PAFamilyCacheError("PA cache transaction identity differs")
    records = validate_direct_inventory(document["files"]) if document["files"] else []
    if records and [item["name"] for item in records] != list(_family_names(filenames)):
        raise PAFamilyCacheError("PA cache transaction inventory differs")
    digest = canonical_json_sha256(records) if records else None
    if document["inventory_sha256"] != digest:
        raise PAFamilyCacheError("PA cache transaction inventory digest differs")
    generation = document["generation_sha256"]
    if generation is not None and (
        not isinstance(generation, str) or SHA256.fullmatch(generation) is None
    ):
        raise PAFamilyCacheError("PA cache transaction generation identity differs")
    retirement = document["retirement"]
    if document["status"] == "retired":
        if (
            not isinstance(retirement, dict)
            or retirement.get("generation") != generation
            or SHA256.fullmatch(str(retirement.get("id", ""))) is None
        ):
            raise PAFamilyCacheError("PA cache transaction retirement identity differs")
    elif retirement is not None:
        raise PAFamilyCacheError("active PA cache transaction declares retirement")
    if "pin_release" in document:
        release = document["pin_release"]
        if (not isinstance(release, dict) or set(release) != {
                "retirement_intent_sha256", "replacement_evidence_sha256"}
                or any(SHA256.fullmatch(str(release.get(key, ""))) is None for key in release)):
            raise PAFamilyCacheError("PA cache transaction pin release differs")
        if document["published_pin_reason"] is not None or document["status"] != "published":
            raise PAFamilyCacheError("PA cache transaction pin release state differs")
    if "member_recovery" in document:
        journal = document["member_recovery"]
        if not isinstance(journal, dict) or set(journal) != {"request", "files", "complete"} or type(journal["complete"]) is not bool:
            raise PAFamilyCacheError("PA member recovery journal fields differ")
        _validate_member_recovery_request(journal["request"], document, journal["files"])
        if not journal["complete"] and (document["files"] or document["status"] != "building" or document["verification"] is not None or generation is not None):
            raise PAFamilyCacheError("pending PA member recovery state differs")
    if "response_receipt" in document:
        if _normalize_response_receipt(document["response_receipt"], filenames) != document["response_receipt"]:
            raise PAFamilyCacheError("PA response receipt specification differs")
    if "retained_inventory_recovery" in document:
        journal = document["retained_inventory_recovery"]
        if not isinstance(journal, dict) or set(journal) != {"request", "prior_files", "verified_records"}:
            raise PAFamilyCacheError("PA retained inventory recovery journal fields differ")
        replacements = _validate_retained_inventory_request(journal["request"], document, journal["prior_files"])
        expected_files = [replacements.get(item["name"], item) for item in journal["prior_files"]]
        compared = document.get("publication_metadata_correction", {}).get("prior_files", records)
        if journal["verified_records"] != list(replacements.values()) or compared != expected_files:
            raise PAFamilyCacheError("PA retained inventory recovery evidence differs")
    if "publication_metadata_correction" in document:
        _validate_publication_correction_journal(document)
    return document


def _load_transaction_by_key(transaction_path: Path, cache_key: str) -> dict[str, Any]:
    """Load the one authoritative transaction without caller-owned science fields."""

    try:
        raw = json.loads(transaction_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError(
            f"PA cache transaction is unreadable: {transaction_path}"
        ) from exc
    if not isinstance(raw, dict):
        raise PAFamilyCacheError("PA cache transaction must be a JSON object")
    identity = raw.get("identity")
    filenames = raw.get("filenames")
    if not isinstance(identity, Mapping) or not isinstance(filenames, list):
        raise PAFamilyCacheError("PA cache transaction identity fields differ")
    return _load_transaction(
        transaction_path,
        cache_key=cache_key,
        identity=identity,
        filenames=filenames,
    )


def _transaction_ledger_binding(
    cache_root: Path, cache_key: str, transaction_directory: Path
) -> tuple[Path, Path, Path] | None:
    artifact_root = _artifact_root_for_cache(cache_root)
    if artifact_root is None:
        return None
    if capacity_ledger.load_capacity_ledger(artifact_root) is None:
        raise PAFamilyCacheError("artifact PA transaction requires a calibrated capacity ledger")
    return artifact_root, transaction_directory.resolve(strict=False), (cache_root / cache_key).resolve(strict=False)


def _record_transaction_stage(
    binding: tuple[Path, Path, Path] | None, *, owner: str
) -> None:
    if binding is None:
        return
    artifact_root, transaction, key_root = binding
    try:
        capacity_ledger.record_capacity_object(
            artifact_root,
            path=transaction,
            object_class="rebuildable_payload",
            bytes_count=_key_root_bytes(transaction),
            status="writing",
            owner=owner,
            recovery_reason="pa_family_transaction_incomplete",
            review_deadline=(datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat(),
            recovery_task="resume or retire the exact PA owner transaction",
            recovery_evidence_paths=(transaction / TRANSACTION_NAME,),
            consumers=(key_root,),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PAFamilyCacheError(f"cannot record PA cache transaction lifecycle: {transaction}") from exc


def _handoff_transaction_stage(
    binding: tuple[Path, Path, Path] | None,
    *,
    owner: str,
    generation_sha256: str,
    published_pin_reason: str | None,
) -> None:
    if binding is None:
        return
    artifact_root, transaction, key_root = binding
    ledger = capacity_ledger.load_capacity_ledger(artifact_root)
    if ledger is None:
        raise PAFamilyCacheError("PA cache transaction ledger is unavailable")
    _, relative = capacity_ledger.capacity_object_path(artifact_root, transaction)
    entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
    if entry is None:
        _, key_relative = capacity_ledger.capacity_object_path(artifact_root, key_root)
        published = next(
            (item for item in ledger["objects"] if item.get("path") == key_relative),
            None,
        )
        if (
            published is not None
            and published.get("class") == "published_cache"
            and published.get("status") == "ready"
            and published.get("identity") == generation_sha256
            and published.get("pin") is (published_pin_reason is not None)
            and published.get("pin_reason") == published_pin_reason
        ):
            return
    if (
        entry is None
        or entry.get("class") != "rebuildable_payload"
        or entry.get("status") not in {"writing", "retired"}
        or not isinstance(entry.get("bytes"), int)
    ):
        raise PAFamilyCacheError("PA cache transaction ledger entry differs")
    try:
        capacity_ledger.handoff_prepared_cache_stage(
            artifact_root,
            stage_path=transaction,
            stage_owner=owner,
            stage_bytes=int(entry["bytes"]),
            published_path=key_root,
            published_identity=generation_sha256,
            published_bytes=_key_root_bytes(key_root),
            published_owner=owner,
            # Kept only for the current compatibility signature.  The range
            # ledger owns neither duplicate retention text nor a second route.
            published_retention_reason="managed by PA owner transaction",
            published_review_deadline=(datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat(),
            published_retirement_route="pa_manager_disposition",
            published_pin_reason=published_pin_reason,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PAFamilyCacheError(f"cannot hand off PA cache transaction: {transaction}") from exc


def _validate_verification_evidence(
    evidence: Mapping[str, Any], *, cache_key: str, inventory_sha256: str
) -> dict[str, Any]:
    required = {
        "schema_version", "role", "status", "cache_key", "inventory_sha256",
        "solver_release", "verifier_sha256", "verifier_path",
        "verification_output_path", "verification_output_sha256",
    }
    if not isinstance(evidence, Mapping) or set(evidence) != required:
        raise PAFamilyCacheError("SIMION verification evidence fields differ")
    normalized = dict(evidence)
    if (
        normalized["schema_version"] != 1
        or normalized["role"] != VERIFICATION_EVIDENCE_ROLE
        or normalized["status"] != "pass"
        or normalized["cache_key"] != cache_key
        or normalized["inventory_sha256"] != inventory_sha256
        or normalized["solver_release"] != "SIMION 2020"
    ):
        raise PAFamilyCacheError("SIMION verification evidence identity differs")
    for path_field, digest_field in (
        ("verifier_path", "verifier_sha256"),
        ("verification_output_path", "verification_output_sha256"),
    ):
        candidate = Path(str(normalized[path_field]))
        digest = normalized[digest_field]
        if (
            not isinstance(digest, str)
            or SHA256.fullmatch(digest) is None
            or candidate.is_symlink()
            or not candidate.is_file()
            or file_sha256(candidate) != digest
        ):
            raise PAFamilyCacheError(f"SIMION verification evidence {path_field} identity differs")
        normalized[path_field] = str(candidate.resolve())
    return normalized


def _transaction_progress(
    document: Mapping[str, Any],
    transaction_directory: Path,
    build_directory: Path,
    scratch_directory: Path,
    *,
    action_required: str,
    missing_files: Sequence[str] = (),
) -> TransactionAdvance:
    generation = document.get("generation_sha256")
    generation_directory = (
        transaction_directory.parents[1] / str(document["cache_key"])
        / "generations" / str(generation)
        if generation is not None else None
    )
    return TransactionAdvance(
        cache_key=str(document["cache_key"]),
        status=str(document["status"]),
        action_required=action_required,
        transaction_directory=transaction_directory,
        build_directory=build_directory,
        scratch_directory=scratch_directory,
        inventory_sha256=document.get("inventory_sha256"),
        generation_sha256=generation,
        generation_directory=generation_directory,
        missing_files=tuple(missing_files),
        publication_metadata_correction_receipt=(
            transaction_directory.parents[1] / str(document["cache_key"])
            / "metadata-correction" / "receipt.json"
            if document.get("publication_metadata_correction", {}).get("complete") else None
        ),
    )


def _validate_prepared_payload_metadata(
    payload: Path, records: Sequence[Mapping[str, Any]]
) -> None:
    """Confirm a sealed private transaction still has its frozen members.

    The final transaction inventory is the sole full-byte publication read for
    a reconstructible family.  Once that inventory is written, every member is
    read-only and the key lock excludes another cache producer.  Rehashing the
    same multi-gigabyte files immediately before the atomic directory move adds
    no independent protection; it only repeats the expensive read.  A later
    anomaly still enters the explicit full-audit path.
    """

    expected = validate_direct_inventory(records)
    if not payload.is_dir() or payload.is_symlink():
        raise PAFamilyCacheError("prepared PA transaction payload is missing or indirect")
    entries = list(payload.iterdir())
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise PAFamilyCacheError("prepared PA transaction payload contains an indirect entry")
    if {entry.name for entry in entries} != {record["name"] for record in expected}:
        raise PAFamilyCacheError("prepared PA transaction payload inventory differs")
    for record in expected:
        path = payload / record["name"]
        metadata = path.stat()
        if metadata.st_size != record["bytes"]:
            raise PAFamilyCacheError(
                f"prepared PA transaction payload length differs: {record['name']}"
            )
        if metadata.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise PAFamilyCacheError(
                f"prepared PA transaction payload is not sealed read-only: {record['name']}"
            )


def _publish_transaction_payload(
    cache_root: Path,
    document: dict[str, Any],
    transaction_directory: Path,
    transaction_path: Path,
    payload: Path,
    filenames: Sequence[str],
    *,
    recovery_policy: str,
    ledger_binding: tuple[Path, Path, Path] | None,
) -> None:
    cache_key = str(document["cache_key"])
    records = validate_direct_inventory(document["files"])
    key_root = cache_root / cache_key
    existing = probe_pa_family_cache(cache_root, document["identity"], expected_filenames=filenames)
    if existing.disposition is CacheDisposition.CORRUPT:
        raise PAFamilyCacheError(f"refusing to overwrite corrupt PA cache entry {cache_key}: {existing.detail}")
    if existing.disposition is CacheDisposition.HIT:
        observed = inventory_named_files(payload, _family_names(filenames))
        manifest = validate_pa_family_cache_generation(
            existing.generation_directory, expected_cache_key=cache_key, expected_filenames=filenames
        )
        if observed != records or manifest["files"] != records:
            raise PAFamilyCacheError("published PA family differs from the verified transaction payload")
        document["generation_sha256"] = manifest["generation_sha256"]
        document["last_error"] = None
        _write_transaction(transaction_path, document)
        _remove_tree_writable(payload)
        document["status"] = "published"
        _write_transaction(transaction_path, document)
        return

    recovery_scratch = transaction_directory / "recovery-scratch"
    if recovery_scratch.exists():
        _remove_tree_writable(recovery_scratch)
    if recovery_policy == "xor":
        redundancy = _create_redundancy(payload, recovery_scratch, records)
    else:
        _validate_prepared_payload_metadata(payload, records)
        redundancy = {"algorithm": NO_REDUNDANCY_ALGORITHM, "groups": []}
    manifest = _manifest(
        cache_key, document["identity"], records, redundancy,
        predecessor_generation_sha256=None,
    )
    generation_sha256 = manifest["generation_sha256"]
    document["generation_sha256"] = generation_sha256
    document["last_error"] = None
    _write_json(payload / MANIFEST_NAME, manifest)
    _flush_writable_source(payload / MANIFEST_NAME)
    _write_transaction(transaction_path, document)
    _record_transaction_stage(ledger_binding, owner=str(document["owner"]))

    destination = key_root / "generations" / generation_sha256
    recovery_destination = key_root / RECOVERY_DIRECTORY / generation_sha256
    if destination.exists():
        incumbent = validate_pa_family_cache_generation(
            destination, expected_cache_key=cache_key, expected_filenames=filenames
        )
        if incumbent["files"] != records:
            raise PAFamilyCacheError("existing PA generation differs from transaction payload")
        if payload.exists():
            _remove_tree_writable(payload)
        if recovery_scratch.exists():
            _remove_tree_writable(recovery_scratch)
    else:
        if recovery_policy == "xor":
            if recovery_destination.exists():
                if recovery_scratch.exists():
                    _remove_tree_writable(recovery_scratch)
            else:
                recovery_destination.parent.mkdir(parents=True, exist_ok=True)
                for bundle in recovery_scratch.iterdir():
                    for item in bundle.iterdir():
                        _set_file_read_only(item)
                os.replace(recovery_scratch, recovery_destination)
        elif recovery_destination.exists():
            raise PAFamilyCacheError("reconstructible PA transaction has an unexpected recovery bundle")
        _seal_generation_files(payload, manifest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(payload, destination)
        _validate_sealed_generation_metadata(
            destination, expected_cache_key=cache_key, expected_filenames=filenames
        )
    document["status"] = "published"
    document["last_error"] = None
    _write_transaction(transaction_path, document)


def _complete_transaction_publication(
    cache_root: Path,
    document: dict[str, Any],
    transaction_path: Path,
    filenames: Sequence[str],
    ledger_binding: tuple[Path, Path, Path] | None,
) -> None:
    cache_key = str(document["cache_key"])
    generation_sha256 = document.get("generation_sha256")
    if not isinstance(generation_sha256, str):
        raise PAFamilyCacheError("published PA transaction has no generation identity")
    generation = cache_root / cache_key / "generations" / generation_sha256
    manifest = _validate_sealed_generation_metadata(
        generation, expected_cache_key=cache_key, expected_filenames=filenames
    )
    if manifest["files"] != validate_direct_inventory(document["files"]):
        raise PAFamilyCacheError("published PA transaction payload identity differs")
    _publish_pointer(cache_root / cache_key, cache_key, generation_sha256)
    # Older sealed generations predate the transaction owner record.  They
    # have one deliberately narrow ledger shape; bind that existing record
    # before the ordinary handoff.  This is metadata-only: the manifest has
    # already supplied the member inventory and no PA member is reopened.
    if ledger_binding is not None:
        artifact_root, _, key_root = ledger_binding
        ledger = capacity_ledger.load_capacity_ledger(artifact_root)
        _, relative = capacity_ledger.capacity_object_path(artifact_root, key_root)
        entry = next((item for item in (ledger or {}).get("objects", []) if item.get("path") == relative), None)
        legacy = (entry is not None and entry.get("class") == "published_cache"
                  and entry.get("status") == "writing"
                  and entry.get("recovery_reason") == "legacy_pa_cache_missing_owner_transaction"
                  and entry.get("identity") == generation_sha256
                  and entry.get("owner") == document["owner"]
                  and entry.get("pin") is (document["published_pin_reason"] is not None)
                  and entry.get("pin_reason") == document["published_pin_reason"]
                  and entry.get("bytes") == _key_root_bytes(key_root))
        if legacy:
            capacity_ledger.record_capacity_object(
                artifact_root, path=key_root, object_class="published_cache",
                bytes_count=int(entry["bytes"]), status="ready", owner=str(document["owner"]),
                identity=generation_sha256, pin=bool(entry["pin"]),
                pin_reason=entry.get("pin_reason"),
            )
    _handoff_transaction_stage(
        ledger_binding,
        owner=str(document["owner"]),
        generation_sha256=generation_sha256,
        published_pin_reason=document["published_pin_reason"],
    )
    document["last_error"] = None
    _write_transaction(transaction_path, document)


def _published_key_inventory(
    key_root: Path, manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Describe one sealed key root without rereading large payload bytes."""

    pointer_path = key_root / POINTER_NAME
    expected: dict[str, dict[str, Any]] = {}

    def add(path: Path, *, bytes_count: int, sha256: str) -> None:
        relative = path.relative_to(key_root).as_posix()
        if relative in expected:
            raise PAFamilyCacheError(f"duplicate PA retirement payload: {relative}")
        expected[relative] = {
            "path": relative,
            "bytes": bytes_count,
            "sha256": sha256,
        }

    add(
        pointer_path,
        bytes_count=pointer_path.stat().st_size,
        sha256=file_sha256(pointer_path),
    )
    generations_root = key_root / "generations"
    if not generations_root.is_dir() or generations_root.is_symlink():
        raise PAFamilyCacheError("PA retirement generations root is invalid")
    generation_directories = sorted(generations_root.iterdir(), key=lambda path: path.name)
    if not generation_directories:
        raise PAFamilyCacheError("PA retirement generations root is empty")
    for generation_root in generation_directories:
        if not generation_root.is_dir() or generation_root.is_symlink():
            raise PAFamilyCacheError("PA retirement generation entry is indirect")
        generation_manifest = _validate_sealed_generation_metadata(
            generation_root,
            expected_cache_key=str(manifest["cache_key"]),
        )
        generation = str(generation_manifest["generation_sha256"])
        if generation_root.name != generation:
            raise PAFamilyCacheError("PA retirement generation directory differs")
        manifest_path = generation_root / MANIFEST_NAME
        add(
            manifest_path,
            bytes_count=manifest_path.stat().st_size,
            sha256=file_sha256(manifest_path),
        )
        for record in validate_direct_inventory(generation_manifest["files"]):
            add(
                generation_root / record["name"],
                bytes_count=int(record["bytes"]),
                sha256=str(record["sha256"]),
            )
        for group in generation_manifest["redundancy"]["groups"]:
            bundle = key_root / RECOVERY_DIRECTORY / generation / group["bundle"]
            parity_manifest_path = bundle / PARITY_MANIFEST_NAME
            parity_manifest = json.loads(
                parity_manifest_path.read_text(encoding="utf-8-sig")
            )
            parity = parity_manifest["parity"]
            add(
                parity_manifest_path,
                bytes_count=parity_manifest_path.stat().st_size,
                sha256=str(group["manifest_sha256"]),
            )
            add(
                bundle / parity["name"],
                bytes_count=int(parity["bytes"]),
                sha256=str(group["parity_sha256"]),
            )

    correction_root = key_root / "metadata-correction"
    if correction_root.exists():
        transaction = _load_transaction_by_key(key_root.parent / TRANSACTION_DIRECTORY / key_root.name / TRANSACTION_NAME, key_root.name)
        journal = transaction.get("publication_metadata_correction")
        if not journal or not journal["complete"]:
            raise PAFamilyCacheError("PA retirement metadata correction is not complete")
        for name, content in (("original_manifest.json", journal["prior_manifest"]), ("receipt.json", _publication_correction_receipt(journal))):
            path = correction_root / name
            if path.is_symlink() or not path.is_file() or json.loads(path.read_text(encoding="utf-8-sig")) != content:
                raise PAFamilyCacheError("PA retirement metadata correction evidence differs")
            add(path, bytes_count=path.stat().st_size, sha256=file_sha256(path))

    observed: dict[str, int] = {}
    for directory, directories, filenames in os.walk(key_root):
        root = Path(directory)
        for name in directories:
            child = root / name
            if child.is_symlink():
                raise PAFamilyCacheError(
                    f"PA retirement payload contains a directory symlink: {child}"
                )
        for name in filenames:
            child = root / name
            if child.is_symlink() or not child.is_file():
                raise PAFamilyCacheError(
                    f"PA retirement payload contains an indirect file: {child}"
                )
            observed[child.relative_to(key_root).as_posix()] = child.stat().st_size
    expected_sizes = {path: record["bytes"] for path, record in expected.items()}
    if observed != expected_sizes:
        raise PAFamilyCacheError("PA retirement payload inventory differs")
    return [expected[path] for path in sorted(expected)]


def _retired_transaction_can_restart(
    binding: tuple[Path, Path, Path] | None,
    document: Mapping[str, Any],
) -> bool:
    """Require completed capacity deletion before reusing a retired key."""

    if binding is None:
        return False
    artifact_root, _, key_root = binding
    if key_root.exists():
        return False
    ledger = capacity_ledger.load_capacity_ledger(artifact_root)
    if ledger is None:
        return False
    _, relative = capacity_ledger.capacity_object_path(artifact_root, key_root)
    entry = next(
        (item for item in ledger["objects"] if item.get("path") == relative), None
    )
    if (
        entry is None
        or entry.get("class") != "rebuildable_payload"
        or entry.get("status") != "retired"
        or entry.get("disposition") != document.get("retirement")
    ):
        return False
    # The caller already established its own short workflow lease before taking
    # the PA key lock.  Lease creation itself rejects pending dispositions, so
    # an exact retired ledger record proves deletion has completed while this
    # new build cycle remains protected from cleanup.
    return True


def _restart_retired_transaction(
    transaction_path: Path,
    transaction: Path,
    document: dict[str, Any],
    *,
    published_pin_reason: str | None,
) -> None:
    for name in ("payload", "build-scratch", "projection-scratch", "recovery-scratch"):
        if (transaction / name).exists():
            raise PAFamilyCacheError(
                f"retired PA transaction retained owned scratch: {transaction / name}"
            )
    document.pop("retained_inventory_recovery", None)
    document.pop("publication_metadata_correction", None)
    document.pop("member_recovery", None)
    document.update(
        {
            "status": "building",
            "files": [],
            "inventory_sha256": None,
            "verification": None,
            "generation_sha256": None,
            "published_pin_reason": published_pin_reason,
            "retirement": None,
            "last_error": None,
        }
    )
    _write_transaction(transaction_path, document)
    (transaction / "payload").mkdir(exist_ok=True)
    (transaction / "build-scratch").mkdir(exist_ok=True)


def _validate_member_recovery_request(
    request: Mapping[str, Any], document: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bind explicit mismatches to one old sealed inventory without reading PA bytes."""
    fields = {"schema_version", "role", "cache_key", "owner", "inventory_sha256", "receipt", "members"}
    if not isinstance(request, Mapping) or set(request) != fields:
        raise PAFamilyCacheError("PA member recovery request fields differ")
    original = validate_direct_inventory(records)
    indexed = {item["name"]: item for item in original}
    if (request["schema_version"] != 1 or request["role"] != "simion_pa_family_member_recovery"
            or request["cache_key"] != document["cache_key"] or request["owner"] != document["owner"]
            or request["inventory_sha256"] != canonical_json_sha256(original)
            or list(indexed) != list(document["filenames"])):
        raise PAFamilyCacheError("PA member recovery authority differs")
    receipt = validate_direct_inventory([request["receipt"]])[0]
    if indexed.get(receipt["name"]) != receipt:
        raise PAFamilyCacheError("PA member recovery receipt identity differs")
    members = request["members"]
    if not isinstance(members, list) or not members:
        raise PAFamilyCacheError("PA member recovery requires explicit mismatched members")
    removed = []
    for member in members:
        if not isinstance(member, dict) or set(member) != {"sealed", "expected", "receipt_record_path"}:
            raise PAFamilyCacheError("PA member recovery member fields differ")
        sealed = validate_direct_inventory([member["sealed"]])[0]
        expected = validate_direct_inventory([member["expected"]])[0]
        path = member["receipt_record_path"]
        if (indexed.get(sealed["name"]) != sealed or expected["name"] != sealed["name"]
                or expected == sealed or sealed["name"] == receipt["name"]
                or not isinstance(path, list) or not path
                or any(not isinstance(part, str) and (type(part) is not int or part < 0) for part in path)):
            raise PAFamilyCacheError("PA member recovery does not identify a sealed mismatch")
        removed.append(sealed)
    return validate_direct_inventory([*removed, receipt])


def _advance_member_recovery(
    document: dict[str, Any], transaction_path: Path, payload: Path,
    request: Mapping[str, Any] | None,
) -> None:
    """Journal invalidation before deleting only explicitly bound incomplete members."""
    journal = document.get("member_recovery")
    if request is None and (journal is None or journal["complete"]):
        return
    if (document["status"] != "building" or document["verification"] is not None
            or document["generation_sha256"] is not None):
        raise PAFamilyCacheError("PA member recovery requires building without verification or publication")
    if journal is not None and request == journal["request"] and journal["complete"]:
        return  # Repeating the same request must never delete rebuilt members.
    if "retained_inventory_recovery" in document:
        raise PAFamilyCacheError("PA member recovery cannot replace completed retained inventory evidence")
    if journal is not None and not journal["complete"]:
        if request is not None and request != journal["request"]:
            raise PAFamilyCacheError("PA member recovery differs from pending request")
        request = journal["request"]
        removed = _validate_member_recovery_request(request, document, journal["files"])
    else:
        removed = _validate_member_recovery_request(request, document, document["files"])
        _validate_prepared_payload_metadata(payload, document["files"])
        receipt_path = payload / request["receipt"]["name"]
        if file_sha256(receipt_path).upper() != request["receipt"]["sha256"].upper():
            raise PAFamilyCacheError("PA member recovery receipt bytes differ")
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            for member in request["members"]:
                referenced = receipt
                for part in member["receipt_record_path"]:
                    referenced = referenced[part]
                if validate_direct_inventory([referenced]) != validate_direct_inventory([member["expected"]]):
                    raise PAFamilyCacheError("PA member recovery receipt reference differs")
        except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise PAFamilyCacheError("PA member recovery receipt reference is invalid") from exc
        journal = {"request": dict(request), "files": document["files"], "complete": False}
        document.update(member_recovery=journal, files=[], inventory_sha256=None, last_error=None)
        _write_transaction(transaction_path, document)
    if not payload.is_dir() or payload.is_symlink():
        raise PAFamilyCacheError("PA member recovery payload is missing or indirect")
    # Preflight the whole deletion set before any mutation; no recursive removal.
    for record in removed:
        path = payload / record["name"]
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size != record["bytes"])):
            raise PAFamilyCacheError("PA member recovery target metadata differs")
    for record in removed:
        path = payload / record["name"]
        if path.exists():
            _set_file_writable(path)
            path.unlink()
    journal["complete"] = True
    _write_transaction(transaction_path, document)


def _validate_retained_member_inventory(document: Mapping[str, Any]) -> None:
    """Enforce the precise recovery promise for every retained file, including raw PA."""
    journal = document.get("member_recovery")
    if journal is None:
        return
    if journal["complete"] is not True:
        raise PAFamilyCacheError("PA retained member inventory requires completed member recovery")
    removed = {item["name"] for item in _validate_member_recovery_request(
        journal["request"], document, journal["files"]
    )}
    final = {item["name"]: item for item in document["files"]}
    mismatches = [item["name"] for item in journal["files"]
                  if item["name"] not in removed and final.get(item["name"]) != item]
    if mismatches:
        raise PAFamilyCacheError(
            "PA retained member inventory differs from original recovery journal: " + ", ".join(mismatches)
        )


def _validate_retained_inventory_request(
    request: Mapping[str, Any], document: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Select only unchanged retained members from the owner's original inventory."""
    fields = {"schema_version", "cache_key", "owner", "inventory_sha256", "names"}
    if not isinstance(request, Mapping) or set(request) != fields:
        raise PAFamilyCacheError("PA retained inventory recovery request fields differ")
    current = validate_direct_inventory(records)
    prior = document.get("member_recovery")
    if (type(request["schema_version"]) is not int or request["schema_version"] != 1
            or request["cache_key"] != document["cache_key"] or request["owner"] != document["owner"]
            or request["inventory_sha256"] != canonical_json_sha256(current)
            or [item["name"] for item in current] != document["filenames"]
            or not isinstance(prior, Mapping) or prior.get("complete") is not True):
        raise PAFamilyCacheError("PA retained inventory recovery authority differs")
    names = request["names"]
    if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
        raise PAFamilyCacheError("PA retained inventory recovery requires unique explicit names")
    removed = {item["name"] for item in _validate_member_recovery_request(prior["request"], document, prior["files"])}
    original = {item["name"]: item for item in prior["files"]}
    indexed = {item["name"]: item for item in current}
    replacements = {}
    for name in sorted(names):
        if (name in removed or name not in original or name not in indexed
                or original[name] == indexed[name]):
            raise PAFamilyCacheError("PA retained inventory recovery member is not a retained mismatch")
        replacements[name] = original[name]
    return replacements


def _advance_retained_inventory_recovery(
    document: dict[str, Any], transaction_path: Path, payload: Path, request: Mapping[str, Any] | None,
) -> None:
    """Correct only proven transient inventory reads, without touching payload bytes."""
    if request is None:
        return
    if (document["status"] != "building" or document["verification"] is not None
            or document["generation_sha256"] is not None):
        raise PAFamilyCacheError("PA retained inventory recovery requires building without verification or publication")
    journal = document.get("retained_inventory_recovery")
    if journal is not None:
        if request != journal["request"]:
            raise PAFamilyCacheError("PA retained inventory recovery differs from completed request")
        return
    replacements = _validate_retained_inventory_request(request, document, document["files"])
    _validate_prepared_payload_metadata(payload, document["files"])
    scratch = transaction_path.parent / "recovery-scratch"
    scratch.mkdir(exist_ok=True)
    try:
        for name, expected in replacements.items():
            with tempfile.TemporaryDirectory(prefix="retained-inventory-", dir=scratch) as temporary:
                observed = snapshot_immutable_file(payload / name, Path(temporary) / name, expected)
                if observed != expected:
                    raise PAFamilyCacheError("PA retained inventory snapshot differs from original identity")
    except (OSError, ValueError) as exc:
        raise PAFamilyCacheError("PA retained inventory recovery snapshot verification failed") from exc
    finally:
        if scratch.is_dir() and not any(scratch.iterdir()):
            scratch.rmdir()
    prior_files = document["files"]
    records = [replacements.get(item["name"], item) for item in prior_files]
    document.update(
        files=records, inventory_sha256=canonical_json_sha256(records), last_error=None,
        retained_inventory_recovery={"request": dict(request), "prior_files": prior_files,
                                     "verified_records": list(replacements.values())},
    )
    _write_transaction(transaction_path, document)


def _normalize_response_receipt(spec: Mapping[str, Any], names: Sequence[str]) -> dict[str, Any]:
    """Validate a receipt recipe, never accepting caller-provided PA hashes."""
    if (not isinstance(spec, Mapping)
            or set(spec) != {"schema_version", "receipt_name", "exporter_path", "exports"}
            or type(spec["schema_version"]) is not int or spec["schema_version"] != 1
            or not isinstance(spec["exports"], list)
            or not isinstance(spec["exporter_path"], str) or not spec["exporter_path"]):
        raise PAFamilyCacheError("PA response receipt specification fields differ")
    receipt_name = spec["receipt_name"]
    if not isinstance(receipt_name, str) or receipt_name not in names or not receipt_name.endswith(".json"):
        raise PAFamilyCacheError("PA response receipt must name a declared JSON member")
    try:
        exports = _normalize_exports([ResponseExport(**item) for item in spec["exports"]])
    except (TypeError, ValueError) as exc:
        raise PAFamilyCacheError("PA response receipt exports are invalid") from exc
    if any(item.source_name not in names or item.standalone_name not in names for item in exports):
        raise PAFamilyCacheError("PA response receipt export is outside the family")
    return {
        "schema_version": 1, "receipt_name": receipt_name,
        "exporter_path": str(Path(spec["exporter_path"]).resolve()),
        "exports": [dict(response_id=item.response_id, source_name=item.source_name,
                         standalone_name=item.standalone_name) for item in exports],
    }


def _inventory_with_response_receipt(
    payload: Path, names: Sequence[str], spec: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Seal data once and derive the small receipt from that same byte inventory."""
    if not Path(spec["exporter_path"]).is_file():
        raise PAFamilyCacheError("PA response receipt exporter is missing")
    data_names = [name for name in names if name != spec["receipt_name"]]
    records = _inventory_transaction_payload(payload, data_names)
    for record in records:
        _set_file_read_only(payload / record["name"])
    destination = payload / spec["receipt_name"]
    # An interrupted attempt may have left its unsealed owner-generated receipt.
    # The recipe was journaled before any creation; only that file is replaced.
    if destination.exists():
        _set_file_writable(destination)
        destination.unlink()
    write_standalone_pa_response_set(
        payload, spec["exporter_path"], [ResponseExport(**item) for item in spec["exports"]],
        destination, _owner_inventory=records,
    )
    _flush_writable_source(destination)
    return validate_direct_inventory([*records, *inventory_named_files(payload, [destination.name])])


def _correction_request(request: Mapping[str, Any]) -> dict[str, Any]:
    fields = {"schema_version", "cache_key", "owner", "generation_sha256", "inventory_sha256",
              "member_name", "sealed_sha256", "retained_sha256"}
    if not isinstance(request, Mapping) or set(request) - fields - {"capacity_lease_id", "capacity_lease_owner"} or not fields <= set(request):
        raise PAFamilyCacheError("publication metadata correction request fields differ")
    if request["schema_version"] != 1:
        raise PAFamilyCacheError("publication metadata correction schema differs")
    _family_names([request["member_name"]])
    for field in ("cache_key", "generation_sha256", "inventory_sha256", "sealed_sha256", "retained_sha256"):
        if not isinstance(request[field], str) or not SHA256.fullmatch(request[field]):
            raise PAFamilyCacheError("publication metadata correction digest differs")
    return {field: request[field] for field in sorted(fields)}


def _validate_publication_correction_journal(document: Mapping[str, Any]) -> None:
    journal = document["publication_metadata_correction"]
    fields = {"request", "prior_files", "prior_manifest", "prior_verification", "corrected_files",
              "successor_manifest", "member_metadata", "persisted_sha256", "complete"}
    if not isinstance(journal, dict) or set(journal) != fields or type(journal["complete"]) is not bool:
        raise PAFamilyCacheError("publication metadata correction journal fields differ")
    request = _correction_request(journal["request"])
    if (request["cache_key"] != document["cache_key"] or request["owner"] != document["owner"]
            or document["status"] not in ({"published", "retired"} if journal["complete"] else {"published"})):
        raise PAFamilyCacheError("publication metadata correction owner differs")
    prior = validate_direct_inventory(journal["prior_files"])
    if canonical_json_sha256(prior) != request["inventory_sha256"]:
        raise PAFamilyCacheError("publication metadata correction prior inventory differs")
    old = journal["prior_manifest"]
    if (old.get("files") != prior or old.get("generation_sha256") != request["generation_sha256"]
            or old.get("redundancy", {}).get("algorithm") != NO_REDUNDANCY_ALGORITHM
            or _generation_sha256(request["cache_key"], prior, old.get("redundancy"), old.get("predecessor_generation_sha256")) != request["generation_sha256"]):
        raise PAFamilyCacheError("publication metadata correction prior manifest differs")
    original = document.get("member_recovery")
    if not original or original["complete"] is not True:
        raise PAFamilyCacheError("publication metadata correction requires original retained evidence")
    removed = {item["name"] for item in _validate_member_recovery_request(original["request"], document, original["files"])}
    retained = next((item for item in original["files"] if item["name"] == request["member_name"]), None)
    sealed = next((item for item in prior if item["name"] == request["member_name"]), None)
    if (retained is None or sealed is None or retained["name"] in removed
            or retained["sha256"] != request["retained_sha256"] or sealed["sha256"] != request["sealed_sha256"]
            or retained["sha256"] == sealed["sha256"] or retained["bytes"] != sealed["bytes"]
            or journal["persisted_sha256"] != retained["sha256"]):
        raise PAFamilyCacheError("publication metadata correction is not an unchanged retained member")
    corrected = [retained if item["name"] == retained["name"] else item for item in prior]
    expected = _manifest(request["cache_key"], document["identity"], corrected, old["redundancy"], request["generation_sha256"])
    if journal["corrected_files"] != corrected or journal["successor_manifest"] != expected:
        raise PAFamilyCacheError("publication metadata correction successor differs")
    _validate_retained_member_inventory({**document, "files": corrected})
    expected_files = corrected if journal["complete"] else prior
    expected_generation = expected["generation_sha256"] if journal["complete"] else request["generation_sha256"]
    if document["files"] != expected_files or document["generation_sha256"] != expected_generation or document["verification"] != journal["prior_verification"]:
        raise PAFamilyCacheError("publication metadata correction transaction binding differs")


def _correction_consumers(root: Path, key: str, request: Mapping[str, Any], operation_lease: str | None) -> None:
    artifact_root = _artifact_root_for_cache(root)
    if artifact_root is None:
        return
    active = capacity_protection.load_capacity_protection_leases(artifact_root)["audit"]
    selected = request.get("capacity_lease_id")
    found = selected is None
    for lease in active:
        if lease["status"] != "active" or lease["lease_id"] == operation_lease:
            continue
        covers = (key.lower() in lease["protected_cache_keys"] or capacity_protection.path_is_protected(
            (root / key).absolute(), [Path(item) for item in lease["protected_paths"]]))
        if lease["lease_id"] == selected:
            if lease["owner"] != request.get("capacity_lease_owner") or not covers:
                raise PAFamilyCacheError("publication metadata correction workflow lease differs")
            found = True
        elif covers:
            raise PAFamilyCacheError("publication metadata correction has another active consumer")
    if not found:
        raise PAFamilyCacheError("publication metadata correction workflow lease is not active")


def _correction_metadata(directory: Path, names: Sequence[str]) -> list[dict[str, Any]]:
    result = []
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise PAFamilyCacheError("publication metadata correction member is indirect or missing")
        metadata = path.stat()
        if metadata.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise PAFamilyCacheError("publication metadata correction member is writable")
        result.append({"name": name, "bytes": metadata.st_size, "device": metadata.st_dev,
                       "inode": metadata.st_ino, "mtime_ns": metadata.st_mtime_ns})
    return result


def _publication_correction_receipt(journal: Mapping[str, Any]) -> dict[str, Any]:
    request = journal["request"]
    return {"schema_version": 1, "role": "simion_pa_publication_metadata_correction", "status": "pass",
            "no_solver_rerun": True, "pa_bytes_written": 0, "request": request,
            "prior_verification": journal["prior_verification"], "prior_inventory_sha256": request["inventory_sha256"],
            "corrected_inventory_sha256": canonical_json_sha256(journal["corrected_files"]),
            "persisted_sha256": journal["persisted_sha256"], "generation_sha256": journal["successor_manifest"]["generation_sha256"],
            "proof": "original retained identity matches current unbuffered bytes; original format verification preserved"}


def _advance_publication_metadata_correction(
    root: Path, document: dict[str, Any], transaction_path: Path,
    request: Mapping[str, Any] | None, operation_lease: str | None,
) -> bool:
    journal = document.get("publication_metadata_correction")
    if request is None and journal is None:
        return False
    normalized = _correction_request(request) if request is not None else journal["request"]
    if journal is not None and normalized != journal["request"]:
        raise PAFamilyCacheError("publication metadata correction request differs from journal")
    key = str(document["cache_key"])
    key_root = root / key
    evidence_root = key_root / "metadata-correction"
    stage = evidence_root / "payload"
    binding = _artifact_ledger_binding(root, key, required=True)
    if journal is None:
        if (document["status"] != "published" or normalized["owner"] != document["owner"]
                or normalized["cache_key"] != key or normalized["generation_sha256"] != document["generation_sha256"]
                or normalized["inventory_sha256"] != document["inventory_sha256"]):
            raise PAFamilyCacheError("publication metadata correction requires matching published owner")
        old = key_root / "generations" / normalized["generation_sha256"]
        if json.loads((key_root / POINTER_NAME).read_text(encoding="utf-8-sig")) != {
            "cache_key": key, "generation_sha256": normalized["generation_sha256"]
        }:
            raise PAFamilyCacheError("publication metadata correction pointer advanced")
        _correction_consumers(root, key, request or {}, operation_lease)
        manifest = _validate_sealed_generation_metadata(old, expected_cache_key=key, expected_filenames=document["filenames"])
        if manifest["files"] != document["files"] or evidence_root.exists():
            raise PAFamilyCacheError("publication metadata correction source evidence differs")
        _validate_verification_evidence(document["verification"], cache_key=key, inventory_sha256=document["inventory_sha256"])
        retained = next((item for item in document.get("member_recovery", {}).get("files", []) if item["name"] == normalized["member_name"]), None)
        corrected = [retained if item["name"] == normalized["member_name"] else item for item in document["files"]]
        if retained is None:
            raise PAFamilyCacheError("publication metadata correction lacks retained member evidence")
        metadata = _correction_metadata(old, document["filenames"])
        digest = file_sha256_unbuffered(old / normalized["member_name"])
        if _correction_metadata(old, document["filenames"]) != metadata:
            raise PAFamilyCacheError("publication metadata correction source changed during hash")
        journal = {"request": normalized, "prior_files": document["files"], "prior_manifest": manifest,
                   "prior_verification": document["verification"], "corrected_files": corrected,
                   "successor_manifest": _manifest(key, document["identity"], corrected, manifest.get("redundancy"), normalized["generation_sha256"]),
                   "member_metadata": metadata, "persisted_sha256": digest, "complete": False}
        _validate_publication_correction_journal({**document, "publication_metadata_correction": journal})
        _correction_consumers(root, key, request or {}, operation_lease)
        document["publication_metadata_correction"] = journal
        _write_transaction(transaction_path, document)
    _validate_publication_correction_journal(document)
    if journal["complete"]:
        _validate_sealed_generation_metadata(key_root / "generations" / document["generation_sha256"], expected_cache_key=key)
        if (json.loads((evidence_root / "receipt.json").read_text(encoding="utf-8-sig")) != _publication_correction_receipt(journal)
                or json.loads((evidence_root / "original_manifest.json").read_text(encoding="utf-8-sig")) != journal["prior_manifest"]):
            raise PAFamilyCacheError("publication metadata correction archived evidence differs")
        if json.loads((key_root / POINTER_NAME).read_text(encoding="utf-8-sig")) != {
            "cache_key": key, "generation_sha256": document["generation_sha256"]
        }:
            raise PAFamilyCacheError("publication metadata correction completed pointer differs")
        return True
    _correction_consumers(root, key, request or {}, operation_lease)
    _validate_verification_evidence(journal["prior_verification"], cache_key=key, inventory_sha256=normalized["inventory_sha256"])
    old = key_root / "generations" / normalized["generation_sha256"]
    successor_manifest = journal["successor_manifest"]
    successor = key_root / "generations" / successor_manifest["generation_sha256"]
    locations = [path for path in (old, stage, successor) if path.exists()]
    if len(locations) != 1 or locations[0].is_symlink():
        raise PAFamilyCacheError("publication metadata correction payload location is ambiguous")
    location = locations[0]
    if _correction_metadata(location, document["filenames"]) != journal["member_metadata"]:
        raise PAFamilyCacheError("publication metadata correction retained payload metadata changed")
    if {item.name for item in location.iterdir()} - set(document["filenames"]) - {MANIFEST_NAME}:
        raise PAFamilyCacheError("publication metadata correction payload contains unknown members")
    pointer = key_root / POINTER_NAME
    if pointer.exists():
        current = json.loads(pointer.read_text(encoding="utf-8-sig"))
        if current not in [{"cache_key": key, "generation_sha256": value} for value in (normalized["generation_sha256"], successor.name)]:
            raise PAFamilyCacheError("publication metadata correction pointer advanced")
    _record_artifact_cache_state(binding, normalized["generation_sha256"], "writing",
                                 published_pin_reason=document["published_pin_reason"])
    evidence_root.mkdir(exist_ok=True)
    decision_lock = (capacity_protection.capacity_decision_lock(binding.artifact_root)
                     if binding is not None else nullcontext())
    with decision_lock:
        _correction_consumers(root, key, request or {}, operation_lease)
        if pointer.exists():
            pointer.unlink()
        if location == old:
            os.replace(old, stage)
            location = stage
    archived_manifest = evidence_root / "original_manifest.json"
    if not archived_manifest.exists():
        if json.loads((location / MANIFEST_NAME).read_text(encoding="utf-8-sig")) != journal["prior_manifest"]:
            raise PAFamilyCacheError("publication metadata correction original manifest changed")
        os.replace(location / MANIFEST_NAME, archived_manifest)
    if json.loads(archived_manifest.read_text(encoding="utf-8-sig")) != journal["prior_manifest"]:
        raise PAFamilyCacheError("publication metadata correction archived manifest differs")
    receipt = _publication_correction_receipt(journal)
    _write_transaction(evidence_root / "receipt.json", receipt)
    if location == stage:
        if not (stage / MANIFEST_NAME).exists():
            _write_transaction(stage / MANIFEST_NAME, successor_manifest)
        elif json.loads((stage / MANIFEST_NAME).read_text(encoding="utf-8-sig")) != successor_manifest:
            raise PAFamilyCacheError("publication metadata correction staged manifest differs")
        _set_file_read_only(stage / MANIFEST_NAME)
        os.replace(stage, successor)
    _validate_sealed_generation_metadata(successor, expected_cache_key=key, expected_filenames=document["filenames"])
    _publish_pointer(key_root, key, successor.name)
    _record_artifact_cache_state(binding, successor.name, "ready",
                                 published_pin_reason=document["published_pin_reason"])
    if binding is not None:
        capacity_ledger.touch_capacity_object(binding.artifact_root, path=binding.key_root, when_epoch=time.time())
    document["files"] = journal["corrected_files"]
    document["inventory_sha256"] = canonical_json_sha256(document["files"])
    document["generation_sha256"] = successor.name
    journal["complete"] = True
    document["last_error"] = None
    _write_transaction(transaction_path, document)
    return True


def _validate_abandonment_producer(request: Mapping[str, Any], document: Mapping[str, Any]) -> None:
    """Consume only the failed producer manifest and its relevant light evidence."""
    path = Path(str(request["failed_producer_manifest_path"]))
    if path.is_symlink() or not path.is_file() or file_sha256(path) != request["failed_producer_manifest_sha256"]:
        raise PAFamilyCacheError("abandonment failed producer manifest identity differs")
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "failed":
        raise PAFamilyCacheError("abandonment requires a failed producer")
    verification = document.get("verification") or {}
    for record in manifest.get("outputs", []):
        candidate = Path(str(record.get("path", "")))
        verification_match = (
            verification.get("cache_key") == document["cache_key"]
            and verification.get("inventory_sha256") == document["inventory_sha256"]
            and str(candidate) == verification.get("verification_output_path")
            and record.get("sha256") == verification.get("verification_output_sha256")
        )
        if not verification_match and candidate.name != "summary.json":
            continue
        if (candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 1024 * 1024
                or candidate.stat().st_size != record.get("bytes") or file_sha256(candidate) != record.get("sha256")):
            raise PAFamilyCacheError("abandonment producer evidence differs")
        if verification_match or document["cache_key"] in candidate.read_text(encoding="utf-8-sig").upper():
            return
    raise PAFamilyCacheError("failed producer does not bind the abandoned transaction")


def _abandon_empty_transaction(
    root: Path, identity: Mapping[str, Any], filenames: Sequence[str],
    request: Mapping[str, Any], lock_timeout_s: float,
) -> TransactionAdvance:
    """Retain an empty failed transaction; never dispose existing PA payloads."""
    fields = {"schema_version", "cache_key", "owner", "transaction_sha256", "inventory_sha256",
              "failed_producer_manifest_path", "failed_producer_manifest_sha256", "reason"}
    key = canonical_pa_family_cache_key(identity)
    if (not isinstance(request, Mapping) or set(request) != fields or request["schema_version"] != 1
            or request["cache_key"] != key
            or not isinstance(request["owner"], str) or not request["owner"].strip()
            or request["reason"] != "payload_absent_failed_transaction_abandoned"
            or any(not isinstance(request[name], str) or SHA256.fullmatch(request[name]) is None
                   for name in ("transaction_sha256", "inventory_sha256", "failed_producer_manifest_sha256"))):
        raise PAFamilyCacheError("empty transaction abandonment request differs")
    transaction = root / TRANSACTION_DIRECTORY / key
    transaction_path = transaction / TRANSACTION_NAME
    binding = _transaction_ledger_binding(root, key, transaction)
    if binding is None:
        raise PAFamilyCacheError("abandonment requires a governed artifact ledger")
    # No operation protection lease: the capacity owner checks every lease while
    # holding its decision lock; the ordinary key lock still excludes producers.
    with _PAFamilyCacheKeyLock(root, key, lock_timeout_s):
        document = _load_transaction(transaction_path, cache_key=key, identity=identity, filenames=filenames)
        journal = document.get("abandonment")
        if journal is None:
            if (document["status"] not in {"building", "prepared"} or document["generation_sha256"] is not None
                    or document["owner"] != request["owner"]
                    or file_sha256(transaction_path) != request["transaction_sha256"]
                    or document["inventory_sha256"] != request["inventory_sha256"]):
                raise PAFamilyCacheError("abandonment transaction or inventory identity differs")
            prior = json.loads(json.dumps(document))
        else:
            if journal.get("request") != dict(request) or document["status"] != "retired":
                raise PAFamilyCacheError("abandonment replay request differs")
            prior = journal["prior_transaction"]
            original_text = journal.get("prior_transaction_text", "")
            if (hashlib.sha256(original_text.encode("utf-8")).hexdigest().upper() != request["transaction_sha256"]
                    or json.loads(original_text.lstrip("\ufeff")) != prior):
                raise PAFamilyCacheError("abandonment original transaction evidence differs")
            expected = {**prior, "status": "retired", "retirement": document["retirement"], "abandonment": journal}
            if document != expected or document["retirement"] != {"id": canonical_json_sha256(request), "generation": None}:
                raise PAFamilyCacheError("abandonment retained evidence differs")
        _validate_abandonment_producer(request, prior)

        def commit() -> None:
            if (root / key).exists():
                raise PAFamilyCacheError("abandonment refuses an existing publication root")
            entries = list(transaction.rglob("*"))
            if (transaction.is_symlink() or getattr(transaction.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT) or any(
                item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or (item.is_file() and item != transaction_path)
                or (item.is_dir() and item.relative_to(transaction).as_posix() not in
                    {"payload", "build-scratch", "recovery-scratch"}) for item in entries
            ):
                raise PAFamilyCacheError("abandonment requires empty payload and scratch; existing files retained")
            if journal is None:
                document["abandonment"] = {"request": dict(request), "prior_transaction": prior,
                                           "prior_transaction_text": transaction_path.read_bytes().decode("utf-8"),
                                           "physical_bytes_removed": 0}
                document["status"] = "retired"
                document["retirement"] = {"id": canonical_json_sha256(request), "generation": None}
                _write_transaction(transaction_path, document)

        capacity_ledger.reconcile_abandoned_pa_transaction(
            binding[0], path=transaction, owner=document["owner"], cache_key=key,
            commit_owner_retirement=commit,
        )
        return _transaction_progress(document, transaction, transaction / "payload",
                                     transaction / "build-scratch", action_required="complete")


def advance_pa_family_cache_transaction(
    cache_root: str | Path,
    identity: Mapping[str, Any],
    filenames: Sequence[str],
    *,
    verification_evidence: Mapping[str, Any] | None = None,
    owner: str | None = None,
    lock_timeout_s: float = 30.0,
    recovery_policy: str = "xor",
    published_pin_reason: str | None = None,
    member_recovery: Mapping[str, Any] | None = None,
    response_receipt: Mapping[str, Any] | None = None,
    retained_inventory_recovery: Mapping[str, Any] | None = None,
    publication_metadata_correction: Mapping[str, Any] | None = None,
    abandon_empty_transaction: Mapping[str, Any] | None = None,
) -> TransactionAdvance:
    """Advance one deterministic build/verify/publish transaction idempotently."""

    if abandon_empty_transaction is not None:
        if any(value is not None for value in (verification_evidence, member_recovery, response_receipt,
                                               retained_inventory_recovery, publication_metadata_correction)):
            raise PAFamilyCacheError("empty transaction abandonment cannot accompany build or recovery")
        return _abandon_empty_transaction(
            Path(cache_root), identity, filenames, abandon_empty_transaction, lock_timeout_s
        )
    if owner is not None and (
        not isinstance(owner, str) or not owner.strip() or len(owner.strip()) > 256
    ):
        raise PAFamilyCacheError("PA transaction owner must be a nonempty 1-256 character string")
    owner = owner.strip() if owner is not None else None
    if recovery_policy not in {"xor", "none"}:
        raise PAFamilyCacheError("PA cache recovery policy must be 'xor' or 'none'")
    if publication_metadata_correction is not None and any(value is not None for value in (verification_evidence, member_recovery, retained_inventory_recovery)):
        raise PAFamilyCacheError("publication metadata correction cannot accompany other recovery or verification")
    if member_recovery is not None and verification_evidence is not None:
        raise PAFamilyCacheError("PA member recovery cannot accompany verification evidence")
    if retained_inventory_recovery is not None and (verification_evidence is not None or member_recovery is not None):
        raise PAFamilyCacheError("PA retained inventory recovery cannot accompany deletion or verification")
    if published_pin_reason is not None:
        if not isinstance(published_pin_reason, str) or not published_pin_reason.strip():
            raise PAFamilyCacheError("PA cache published pin reason must be nonempty")
        published_pin_reason = published_pin_reason.strip()
    cache_key = canonical_pa_family_cache_key(identity)
    names = _family_names(filenames)
    receipt_spec = None if response_receipt is None else _normalize_response_receipt(response_receipt, names)
    root = Path(cache_root)
    # A repository artifact family becomes a heavy, durable write as soon as
    # this call returns its transaction build directory.  Its caller must
    # therefore identify the owner before that directory is exposed.  Local
    # and fixture caches retain the small compatibility API because they are
    # outside the governed artifact root.
    root.mkdir(parents=True, exist_ok=True)
    transaction = root / TRANSACTION_DIRECTORY / cache_key
    transaction_path = transaction / TRANSACTION_NAME
    if (
        _artifact_root_for_cache(root) is not None
        and owner is None
        and not transaction_path.exists()
    ):
        raise PAFamilyCacheError(
            "artifact PA transaction requires an explicit nonempty owner"
        )
    payload = transaction / "payload"
    build_scratch = transaction / "build-scratch"
    ledger_binding = _transaction_ledger_binding(root, cache_key, transaction)

    with _protected_key_lock(root, cache_key, lock_timeout_s) as operation_lease:
        transaction.mkdir(parents=True, exist_ok=True)
        transaction_path.with_name(f".{transaction_path.name}.tmp").unlink(
            missing_ok=True
        )
        allowed_entries = {
            TRANSACTION_NAME,
            "payload",
            "build-scratch",
            "recovery-scratch",
        }
        unexpected_entries = sorted(
            child.name
            for child in transaction.iterdir()
            if child.name not in allowed_entries or child.is_symlink()
        )
        if unexpected_entries:
            raise PAFamilyCacheError(
                "PA cache transaction contains unknown entries: "
                + ", ".join(unexpected_entries)
            )
        if transaction_path.exists():
            document = _load_transaction(
                transaction_path, cache_key=cache_key, identity=identity, filenames=names
            )
            if owner is not None and document["owner"] != owner:
                raise PAFamilyCacheError("PA transaction owner differs")
        else:
            if member_recovery is not None or retained_inventory_recovery is not None or publication_metadata_correction is not None:
                raise PAFamilyCacheError("PA member recovery requires an existing transaction")
            existing = probe_pa_family_cache(root, identity, expected_filenames=names)
            if existing.disposition is CacheDisposition.CORRUPT:
                raise PAFamilyCacheError(f"cannot start PA transaction over corrupt cache {cache_key}")
            document = {
                "schema_version": 1,
                "role": TRANSACTION_ROLE,
                "cache_key": cache_key,
                "identity": _canonical_identity(identity),
                "filenames": list(names),
                "status": "building",
                "owner": owner or f"common.simion.pa_family_cache:{cache_key[:32]}",
                "files": [],
                "inventory_sha256": None,
                "verification": None,
                "generation_sha256": None,
                "published_pin_reason": published_pin_reason,
                "retirement": None,
                "last_error": None,
            }
            if existing.disposition is CacheDisposition.HIT:
                manifest = _validate_sealed_generation_metadata(
                    existing.generation_directory, expected_cache_key=cache_key, expected_filenames=names
                )
                document["files"] = manifest["files"]
                document["inventory_sha256"] = canonical_json_sha256(manifest["files"])
                document["generation_sha256"] = manifest["generation_sha256"]
                document["status"] = "published"
            else:
                payload.mkdir()
                build_scratch.mkdir()
            _write_transaction(transaction_path, document)

        if document["status"] == "retired":
            if "abandonment" in document:
                raise PAFamilyCacheError("abandoned transaction is retained failure evidence; explicit abandonment replay only")
            if not _retired_transaction_can_restart(ledger_binding, document):
                raise PAFamilyCacheError(
                    "PA cache transaction retirement has not completed"
                )
            _restart_retired_transaction(
                transaction_path,
                transaction,
                document,
                published_pin_reason=published_pin_reason,
            )
        elif document["published_pin_reason"] != published_pin_reason:
            raise PAFamilyCacheError(
                "PA cache transaction published pin policy differs"
            )

        try:
            if _advance_publication_metadata_correction(root, document, transaction_path, publication_metadata_correction, operation_lease):
                return _transaction_progress(document, transaction, payload, build_scratch, action_required="complete")
            _advance_member_recovery(document, transaction_path, payload, member_recovery)
            _advance_retained_inventory_recovery(document, transaction_path, payload, retained_inventory_recovery)
            if receipt_spec is not None:
                if "response_receipt" in document:
                    if document["response_receipt"] != receipt_spec:
                        raise PAFamilyCacheError("PA response receipt recipe differs from transaction")
                else:
                    if (document["status"] != "building" or document["files"]
                            or (payload / receipt_spec["receipt_name"]).exists()):
                        raise PAFamilyCacheError("PA response receipt requires an unsealed transaction without a receipt")
                    document["response_receipt"] = receipt_spec
                    _write_transaction(transaction_path, document)
            receipt_spec = document.get("response_receipt")
            if document["status"] == "building":
                if document["files"]:
                    records = validate_direct_inventory(document["files"])
                    _validate_prepared_payload_metadata(payload, records)
                else:
                    payload.mkdir(exist_ok=True)
                    build_scratch.mkdir(exist_ok=True)
                    actual = _actual_payload_names(payload)
                    unexpected = sorted(actual - set(names))
                    if unexpected:
                        raise PAFamilyCacheError(
                            "PA transaction payload has unexpected members: " + ", ".join(unexpected)
                        )
                    missing = [name for name in names if name not in actual
                               and (receipt_spec is None or name != receipt_spec["receipt_name"])]
                    if missing:
                        _record_transaction_stage(ledger_binding, owner=str(document["owner"]))
                        return _transaction_progress(
                            document, transaction, payload, build_scratch,
                            action_required="build", missing_files=missing,
                        )
                    if build_scratch.exists():
                        _remove_tree_writable(build_scratch)
                    if receipt_spec is None:
                        for name in names:
                            _set_file_writable(payload / name)
                        records = _inventory_transaction_payload(payload, names)
                    else:
                        records = _inventory_with_response_receipt(payload, names, receipt_spec)
                    try:
                        for record in records:
                            _set_file_read_only(payload / record["name"])
                        document["files"] = records
                        document["inventory_sha256"] = canonical_json_sha256(records)
                        document["last_error"] = None
                        _write_transaction(transaction_path, document)
                    except BaseException:
                        for record in records:
                            _set_file_writable(payload / record["name"])
                        raise

                if verification_evidence is None:
                    _record_transaction_stage(ledger_binding, owner=str(document["owner"]))
                    return _transaction_progress(
                        document, transaction, payload, build_scratch, action_required="verify"
                    )
                _validate_retained_member_inventory(document)
                document["verification"] = _validate_verification_evidence(
                    verification_evidence, cache_key=cache_key,
                    inventory_sha256=str(document["inventory_sha256"]),
                )
                document["status"] = "prepared"
                document["last_error"] = None
                _write_transaction(transaction_path, document)

            if document["status"] == "prepared":
                _validate_retained_member_inventory(document)
                if verification_evidence is not None:
                    normalized = _validate_verification_evidence(
                        verification_evidence, cache_key=cache_key,
                        inventory_sha256=str(document["inventory_sha256"]),
                    )
                    if normalized != document["verification"]:
                        raise PAFamilyCacheError("SIMION verification evidence differs from the transaction")
                if payload.exists():
                    _publish_transaction_payload(
                        root, document, transaction, transaction_path, payload, names,
                        recovery_policy=recovery_policy, ledger_binding=ledger_binding,
                    )
                else:
                    generation_sha256 = document.get("generation_sha256")
                    if not isinstance(generation_sha256, str):
                        raise PAFamilyCacheError("prepared PA transaction lost its payload before publication")
                    generation = root / cache_key / "generations" / generation_sha256
                    manifest = _validate_sealed_generation_metadata(
                        generation, expected_cache_key=cache_key, expected_filenames=names
                    )
                    if manifest["files"] != validate_direct_inventory(document["files"]):
                        raise PAFamilyCacheError("landed PA generation differs from the transaction")
                    document["status"] = "published"
                    document["last_error"] = None
                    _write_transaction(transaction_path, document)

            if document["status"] == "published":
                _complete_transaction_publication(
                    root, document, transaction_path, names, ledger_binding
                )
                return _transaction_progress(
                    document, transaction, payload, build_scratch, action_required="complete"
                )
            raise PAFamilyCacheError(f"unsupported PA cache transaction state: {document['status']}")
        except BaseException as exc:
            document["last_error"] = f"{type(exc).__name__}: {str(exc)[:4096]}"
            try:
                _write_transaction(transaction_path, document)
                if document["status"] != "published":
                    _record_transaction_stage(
                        ledger_binding, owner=str(document["owner"])
                    )
            except Exception:
                pass
            raise


def release_pa_family_cache_retirement_pin(
    cache_root: str | Path, cache_key: str, expected_generation_sha256: str, *,
    owner: str, retirement_intent: Mapping[str, Any], replacement_evidence: Mapping[str, Any],
    lock_timeout_s: float = 30.0,
) -> TransactionAdvance:
    """Release one PA publication pin after its owner supplies replacement evidence.

    This changes no payload and never authorizes deletion.  Capacity can only
    proceed through the ordinary exact-generation retirement approval later.
    """
    if (not isinstance(cache_key, str) or SHA256.fullmatch(cache_key) is None
            or not isinstance(expected_generation_sha256, str)
            or SHA256.fullmatch(expected_generation_sha256) is None
            or not isinstance(owner, str) or not owner.strip()):
        raise PAFamilyCacheError("PA pin release identity is invalid")
    root = Path(cache_root)
    artifact_root = _artifact_root_for_cache(root)
    if artifact_root is None:
        raise PAFamilyCacheError("PA pin release requires an artifact-root cache")
    evidence_required = {"schema_version", "role", "status", "cache_key", "generation_sha256", "source_path", "source_sha256"}
    intent_required = {"schema_version", "role", "status", "cache_key", "generation_sha256", "owner", "replacement_generation_sha256", "replacement_evidence_sha256"}
    if (not isinstance(replacement_evidence, Mapping) or set(replacement_evidence) != evidence_required
            or replacement_evidence.get("schema_version") != 1
            or replacement_evidence.get("role") != "simion_pa_family_cache_replacement_evidence"
            or replacement_evidence.get("status") != "verified"
            or replacement_evidence.get("cache_key") != cache_key
            or not isinstance(replacement_evidence.get("source_path"), str) or not replacement_evidence["source_path"]
            or any(SHA256.fullmatch(str(replacement_evidence.get(key, ""))) is None for key in ("generation_sha256", "source_sha256"))):
        raise PAFamilyCacheError("PA pin release replacement evidence differs")
    evidence_relative = Path(str(replacement_evidence["source_path"]))
    if evidence_relative.is_absolute() or evidence_relative.drive or any(part in {"", ".", ".."} for part in evidence_relative.parts):
        raise PAFamilyCacheError("PA pin release replacement evidence path differs")
    evidence_path = artifact_root
    for part in evidence_relative.parts:
        evidence_path /= part
        if evidence_path.is_symlink():
            raise PAFamilyCacheError("PA pin release replacement evidence is indirect")
    if not evidence_path.is_file() or file_sha256(evidence_path).upper() != replacement_evidence["source_sha256"].upper():
        raise PAFamilyCacheError("PA pin release replacement evidence identity differs")
    evidence_sha = canonical_json_sha256(dict(replacement_evidence))
    if (not isinstance(retirement_intent, Mapping) or set(retirement_intent) != intent_required
            or retirement_intent.get("schema_version") != 1
            or retirement_intent.get("role") != "simion_pa_family_cache_retirement_intent"
            or retirement_intent.get("status") != "approved"
            or retirement_intent.get("cache_key") != cache_key
            or retirement_intent.get("generation_sha256") != expected_generation_sha256
            or retirement_intent.get("owner") != owner
            or retirement_intent.get("replacement_generation_sha256") != replacement_evidence["generation_sha256"]
            or retirement_intent.get("replacement_evidence_sha256") != evidence_sha
            or SHA256.fullmatch(str(retirement_intent.get("replacement_generation_sha256", ""))) is None
            or retirement_intent["replacement_generation_sha256"] == expected_generation_sha256):
        raise PAFamilyCacheError("PA pin release retirement intent differs")
    transaction = root / TRANSACTION_DIRECTORY / cache_key
    binding = _transaction_ledger_binding(root, cache_key, transaction)
    if binding is None:
        raise PAFamilyCacheError("PA pin release requires a governed artifact ledger")
    with _PAFamilyCacheKeyLock(root, cache_key, lock_timeout_s):
        document = _load_transaction_by_key(transaction / TRANSACTION_NAME, cache_key)
        if (document["status"] != "published" or document["generation_sha256"] != expected_generation_sha256
                or document["owner"] != owner):
            raise PAFamilyCacheError("PA pin release transaction differs")
        intent_sha = canonical_json_sha256(dict(retirement_intent))
        release = {"retirement_intent_sha256": intent_sha, "replacement_evidence_sha256": evidence_sha}
        if document["published_pin_reason"] is None:
            if document.get("pin_release") != release:
                raise PAFamilyCacheError("PA pin release is not the recorded owner release")
        else:
            document["published_pin_reason"] = None
            document["pin_release"] = release
            _write_transaction(transaction / TRANSACTION_NAME, document)
        _record_artifact_cache_state(
            _ArtifactLedgerBinding(artifact_root=binding[0], key_root=binding[2]),
            expected_generation_sha256, "ready",
        )
        return _transaction_progress(document, transaction, transaction / "payload", transaction / "build-scratch", action_required="retire_or_consume")


def approve_pa_family_cache_retirement(
    cache_root: str | Path,
    cache_key: str,
    expected_generation_sha256: str,
    *,
    lock_timeout_s: float = 30.0,
) -> TransactionAdvance:
    """Let capacity retire one exact unpinned generation through its PA owner."""

    if not isinstance(cache_key, str) or SHA256.fullmatch(cache_key) is None:
        raise PAFamilyCacheError("PA cache retirement key identity is invalid")
    if (
        not isinstance(expected_generation_sha256, str)
        or SHA256.fullmatch(expected_generation_sha256) is None
    ):
        raise PAFamilyCacheError("PA cache retirement generation identity is invalid")
    root = Path(cache_root)
    transaction = root / TRANSACTION_DIRECTORY / cache_key
    transaction_path = transaction / TRANSACTION_NAME
    payload = transaction / "payload"
    scratch = transaction / "build-scratch"
    binding = _transaction_ledger_binding(root, cache_key, transaction)
    if binding is None:
        raise PAFamilyCacheError("PA cache retirement requires a governed artifact ledger")

    with _PAFamilyCacheKeyLock(root, cache_key, lock_timeout_s):
        document = _load_transaction_by_key(transaction_path, cache_key)
        if document["generation_sha256"] != expected_generation_sha256:
            raise PAFamilyCacheError("PA cache retirement generation differs")
        if document["status"] not in {"published", "retired"}:
            raise PAFamilyCacheError("only a published PA cache transaction can retire")
        if document["published_pin_reason"] is not None:
            raise PAFamilyCacheError("pinned PA cache transactions cannot retire automatically")

        key_root = root / cache_key
        if document["status"] == "published":
            pointer_path = key_root / POINTER_NAME
            try:
                pointer = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PAFamilyCacheError("PA cache retirement pointer is unreadable") from exc
            if pointer != {
                "cache_key": cache_key,
                "generation_sha256": expected_generation_sha256,
            }:
                raise PAFamilyCacheError("PA cache retirement target is not current")
            generation = key_root / "generations" / expected_generation_sha256
            names = _family_names(document["filenames"])
            manifest = _validate_sealed_generation_metadata(
                generation,
                expected_cache_key=cache_key,
                expected_filenames=names,
            )
            if manifest["files"] != validate_direct_inventory(document["files"]):
                raise PAFamilyCacheError("PA cache retirement payload identity differs")
            sealed_files = _published_key_inventory(key_root, manifest)
            expected_bytes = sum(int(record["bytes"]) for record in sealed_files)
            if expected_bytes != _key_root_bytes(key_root):
                raise PAFamilyCacheError("PA cache retirement byte count differs")
            manifest_relative = (
                f"generations/{expected_generation_sha256}/{MANIFEST_NAME}"
            )
            manifest_sha256 = next(
                record["sha256"]
                for record in sealed_files
                if record["path"] == manifest_relative
            )
            disposition_id = canonical_json_sha256(
                {
                    "cache_key": cache_key,
                    "generation_sha256": expected_generation_sha256,
                    "manifest_sha256": manifest_sha256,
                    "files": sealed_files,
                }
            )
            disposition = {
                "id": disposition_id,
                "generation": expected_generation_sha256,
                "manifest_sha256": manifest_sha256,
                "files": sealed_files,
            }
        else:
            disposition = document["retirement"]
            sealed_files = disposition["files"]
            expected_bytes = sum(int(record["bytes"]) for record in sealed_files)
            disposition_id = disposition["id"]
            manifest_sha256 = disposition["manifest_sha256"]

        def commit_owner_retirement(approved: dict[str, Any]) -> None:
            if approved != disposition:
                raise PAFamilyCacheError("capacity retirement disposition differs")
            if document["status"] == "retired":
                return
            document["status"] = "retired"
            document["retirement"] = approved
            document["last_error"] = None
            _write_transaction(transaction_path, document)

        artifact_root, _, _ = binding
        try:
            capacity_ledger.approve_published_cache_retirement(
                artifact_root,
                path=key_root,
                expected_identity=expected_generation_sha256,
                expected_bytes=expected_bytes,
                disposition_id=disposition_id,
                manifest_sha256=manifest_sha256,
                files=sealed_files,
                commit_owner_retirement=commit_owner_retirement,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise PAFamilyCacheError(
                f"cannot approve PA cache retirement: {key_root}"
            ) from exc
        return _transaction_progress(
            document, transaction, payload, scratch, action_required="complete"
        )


def rollback_pa_family_cache_publication(
    cache_root: str | Path,
    identity: Mapping[str, Any],
    rejected_generation_sha256: str,
    *,
    expected_predecessor_generation_sha256: str | None,
    reason: str,
    lock_timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Compare-and-rollback one just-published, rejected generation.

    This is deliberately narrower than retention cleanup.  It succeeds only
    while the rejected generation is still current and its manifest names the
    caller-provided predecessor.  The pointer is restored (or removed when the
    publication had no predecessor) before the exact rejected generation and
    its matching recovery bundle are removed under the shared per-key lock.
    """

    key = canonical_pa_family_cache_key(identity)
    if not isinstance(rejected_generation_sha256, str) or not SHA256.fullmatch(
        rejected_generation_sha256
    ):
        raise PAFamilyCacheError("rejected PA cache generation is invalid")
    if expected_predecessor_generation_sha256 is not None and (
        not isinstance(expected_predecessor_generation_sha256, str)
        or not SHA256.fullmatch(expected_predecessor_generation_sha256)
    ):
        raise PAFamilyCacheError("rollback predecessor generation is invalid")
    if not isinstance(reason, str) or not reason.strip():
        raise PAFamilyCacheError("PA cache publication rollback requires a reason")

    root = Path(cache_root)
    ledger_binding = _artifact_ledger_binding(root, key, required=True)
    key_root = root / key
    rejected = key_root / "generations" / rejected_generation_sha256
    rejected_recovery = key_root / RECOVERY_DIRECTORY / rejected_generation_sha256
    with _protected_key_lock(root, key, lock_timeout_s):
        pointer_path = key_root / POINTER_NAME
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PAFamilyCacheError(
                "cannot roll back PA cache publication: current pointer is unreadable"
            ) from exc
        if pointer != {
            "cache_key": key,
            "generation_sha256": rejected_generation_sha256,
        }:
            raise PAFamilyCacheError(
                "cannot roll back PA cache publication: current pointer advanced"
            )
        manifest = validate_pa_family_cache_generation(
            rejected, expected_cache_key=key
        )
        if (
            manifest["generation_sha256"] != rejected_generation_sha256
            or manifest.get("predecessor_generation_sha256")
            != expected_predecessor_generation_sha256
        ):
            raise PAFamilyCacheError(
                "cannot roll back PA cache publication: rejected generation lineage differs"
            )

        predecessor_directory: Path | None = None
        rollback_identity = (
            expected_predecessor_generation_sha256 or rejected_generation_sha256
        )
        ledger_registered = False
        try:
            if expected_predecessor_generation_sha256 is not None:
                predecessor_directory = (
                    key_root
                    / "generations"
                    / expected_predecessor_generation_sha256
                )
                validate_pa_family_cache_generation(
                    predecessor_directory, expected_cache_key=key
                )
            _record_artifact_cache_state(
                ledger_binding, rollback_identity, "writing"
            )
            ledger_registered = ledger_binding is not None

            if expected_predecessor_generation_sha256 is not None:
                _publish_pointer(
                    key_root, key, expected_predecessor_generation_sha256
                )
            else:
                pointer_path.unlink()

            if rejected_recovery.exists():
                _remove_tree_writable(rejected_recovery)
            _remove_tree_writable(rejected)
            receipt = {
                "schema_version": 1,
                "role": "simion_pa_family_cache_publication_rollback",
                "status": "success",
                "cache_key": key,
                "rejected_generation_sha256": rejected_generation_sha256,
                "restored_generation_sha256": expected_predecessor_generation_sha256,
                "current_pointer_removed": expected_predecessor_generation_sha256 is None,
                "rejected_generation_removed": not rejected.exists(),
                "rejected_recovery_removed": not rejected_recovery.exists(),
                "reason": reason.strip(),
            }
            receipt_root = key_root / "rollback_receipts"
            receipt_root.mkdir(parents=True, exist_ok=True)
            receipt_path = receipt_root / (
                f"rollback-{time.time_ns()}-{uuid4().hex}.json"
            )
            _write_json(receipt_path, receipt)
            _complete_artifact_cache_rollback(
                ledger_binding, expected_predecessor_generation_sha256
            )
            return {**receipt, "receipt_path": str(receipt_path.resolve())}
        except BaseException as exc:
            if ledger_registered:
                _preserve_artifact_publication_failure(
                    ledger_binding,
                    rollback_identity,
                    "rollback",
                    exc,
                )
            raise


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
    capacity_lease_id: str | None = None,
    capacity_lease_owner: str | None = None,
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
        manifest = _validate_sealed_generation_metadata(
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
    _require_managed_pa_consumer_binding(
        source.parents[2],
        manifest,
        capacity_lease_id=capacity_lease_id,
        capacity_lease_owner=capacity_lease_owner,
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
    # Consumption updates only the governed LRU timestamp.  The caller must
    # hold an explicit workflow lease if retirement must remain excluded while
    # the private materialization is in use.
    _record_cache_hit(
        source.parents[2], manifest["cache_key"], manifest["generation_sha256"]
    )
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
    """Expose probe, one transaction advance, and writable materialization."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=("probe", "advance-transaction", "materialize"),
        required=True,
    )
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument(
        "--filenames", required=True, help="comma-separated direct PA-family filenames"
    )
    parser.add_argument("--verification-evidence", type=Path)
    parser.add_argument("--member-recovery", type=Path)
    parser.add_argument("--response-receipt", type=Path)
    parser.add_argument("--retained-inventory-recovery", type=Path)
    parser.add_argument("--publication-metadata-correction", type=Path)
    parser.add_argument("--abandon-empty-transaction", type=Path)
    parser.add_argument("--destination-directory", type=Path)
    parser.add_argument("--recovery-policy", choices=("xor", "none"), default="xor")
    parser.add_argument("--published-pin-reason")
    parser.add_argument("--owner")
    parser.add_argument("--capacity-lease-id")
    parser.add_argument("--capacity-lease-owner")
    parser.add_argument("--lock-timeout-s", type=float, default=30.0)
    args = parser.parse_args(arguments)
    identity = _cli_identity(args.identity)
    filenames = _cli_filenames(args.filenames)
    if args.action != "advance-transaction" and args.published_pin_reason is not None:
        parser.error("published pin reason is accepted only by advance-transaction")
    if args.action != "advance-transaction" and args.member_recovery is not None:
        parser.error("member recovery is accepted only by advance-transaction")
    if args.action != "advance-transaction" and args.response_receipt is not None:
        parser.error("response receipt is accepted only by advance-transaction")
    if args.action != "advance-transaction" and args.retained_inventory_recovery is not None:
        parser.error("retained inventory recovery is accepted only by advance-transaction")
    if args.action != "advance-transaction" and args.publication_metadata_correction is not None:
        parser.error("publication metadata correction is accepted only by advance-transaction")
    if args.action != "advance-transaction" and args.abandon_empty_transaction is not None:
        parser.error("empty transaction abandonment is accepted only by advance-transaction")
    if args.action != "materialize" and (
        args.capacity_lease_id is not None or args.capacity_lease_owner is not None
    ):
        parser.error("capacity lease identity is accepted only by materialize")

    if args.action == "probe":
        if args.verification_evidence is not None or args.destination_directory is not None:
            parser.error("probe accepts neither verification evidence nor a destination")
        result = probe_pa_family_cache(
            args.cache_root, identity, expected_filenames=filenames
        )
        document: dict[str, Any] = {
            "disposition": result.disposition.value,
            "cache_key": result.cache_key,
            "generation_sha256": (
                result.generation_directory.name if result.generation_directory else None
            ),
            "generation_directory": (
                str(result.generation_directory) if result.generation_directory else None
            ),
            "detail": result.detail,
        }
    elif args.action == "advance-transaction":
        if args.destination_directory is not None:
            parser.error("advance-transaction forbids --destination-directory")
        evidence = None
        if args.verification_evidence is not None:
            try:
                evidence = json.loads(
                    args.verification_evidence.read_text(encoding="utf-8-sig")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise PAFamilyCacheError(
                    f"SIMION verification evidence is unreadable: {args.verification_evidence}"
                ) from exc
        member_recovery = None
        if args.member_recovery is not None:
            try:
                member_recovery = json.loads(args.member_recovery.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PAFamilyCacheError("PA member recovery request is unreadable") from exc
        response_receipt = None
        if args.response_receipt is not None:
            try:
                response_receipt = json.loads(args.response_receipt.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PAFamilyCacheError("PA response receipt specification is unreadable") from exc
        retained_inventory_recovery = None
        if args.retained_inventory_recovery is not None:
            try:
                retained_inventory_recovery = json.loads(args.retained_inventory_recovery.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PAFamilyCacheError("PA retained inventory recovery request is unreadable") from exc
        correction = None
        if args.publication_metadata_correction is not None:
            try:
                correction = json.loads(args.publication_metadata_correction.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PAFamilyCacheError("publication metadata correction request is unreadable") from exc
        result = advance_pa_family_cache_transaction(
            args.cache_root,
            identity,
            filenames,
            verification_evidence=evidence,
            owner=args.owner,
            lock_timeout_s=args.lock_timeout_s,
            recovery_policy=args.recovery_policy,
            published_pin_reason=args.published_pin_reason,
            member_recovery=member_recovery,
            response_receipt=response_receipt,
            retained_inventory_recovery=retained_inventory_recovery,
            publication_metadata_correction=correction,
            abandon_empty_transaction=(
                json.loads(args.abandon_empty_transaction.read_text(encoding="utf-8-sig"))
                if args.abandon_empty_transaction is not None else None
            ),
        )
        document = {
            "cache_key": result.cache_key,
            "status": result.status,
            "action_required": result.action_required,
            "transaction_directory": str(result.transaction_directory),
            "build_directory": str(result.build_directory),
            "scratch_directory": str(result.scratch_directory),
            "inventory_sha256": result.inventory_sha256,
            "generation_sha256": result.generation_sha256,
            "generation_directory": (
                str(result.generation_directory)
                if result.generation_directory is not None
                else None
            ),
            "missing_files": list(result.missing_files),
            "publication_metadata_correction_receipt": (
                str(result.publication_metadata_correction_receipt)
                if result.publication_metadata_correction_receipt is not None else None
            ),
        }
    else:
        if args.destination_directory is None or args.verification_evidence is not None:
            parser.error("materialize requires a destination and forbids verification evidence")
        probe = ensure_pa_family_cache(
            args.cache_root,
            identity,
            expected_filenames=filenames,
            lock_timeout_s=args.lock_timeout_s,
        )
        if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
            raise PAFamilyCacheError(
                f"cannot materialize PA cache {probe.cache_key}: "
                f"{probe.disposition.value}: {probe.detail}"
            )
        result = materialize_pa_family_cache(
            probe.generation_directory,
            args.destination_directory,
            expected_filenames=filenames,
            capacity_lease_id=args.capacity_lease_id,
            capacity_lease_owner=args.capacity_lease_owner,
        )
        document = {
            "disposition": "materialized",
            "cache_key": probe.cache_key,
            "generation_directory": str(result.source_generation_directory),
            "destination_directory": str(result.destination_directory),
            "files": list(result.files),
        }
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
