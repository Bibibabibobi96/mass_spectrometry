"""Content-addressed, device-neutral cache for complete SIMION PA families.

The cache deliberately knows no electrode IDs, geometry coordinates, or PA file
suffix conventions.  A caller supplies the complete direct-file family it has
built and a full numerical identity.  A cache entry is usable only when both
the identity and every recorded byte are intact.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any, Mapping, Sequence
from uuid import uuid4

from common.contracts.file_identity import canonical_json_sha256, file_sha256


SCHEMA_VERSION = 1
ROLE = "simion_pa_family_cache"
MANIFEST_NAME = "cache_manifest.json"
POINTER_NAME = "current_generation.json"
STAGING_DIRECTORY = ".staging"
LOCK_DIRECTORY = ".locks"
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
    records: list[dict[str, Any]] = []
    for name in names:
        path = root / name
        if not path.is_file():
            raise PAFamilyCacheError(f"PA family file is missing: {path}")
        records.append({"name": name, "bytes": path.stat().st_size, "sha256": file_sha256(path)})
    return records


def _actual_payload_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        raise PAFamilyCacheError(f"PA family directory is missing: {directory}")
    unexpected_nodes = [item.name for item in directory.iterdir() if not item.is_file()]
    if unexpected_nodes:
        raise PAFamilyCacheError(f"PA family directory contains non-files: {sorted(unexpected_nodes)}")
    return {item.name for item in directory.iterdir() if item.name != MANIFEST_NAME}


def _generation_sha256(cache_key: str, records: Sequence[Mapping[str, Any]]) -> str:
    return canonical_json_sha256({"cache_key": cache_key, "files": list(records)})


def _manifest(cache_key: str, identity: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "role": ROLE,
        "cache_key": cache_key,
        "identity": _canonical_identity(identity),
        "generation_sha256": _generation_sha256(cache_key, records),
        "files": records,
    }


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
    required = {"schema_version", "role", "cache_key", "identity", "generation_sha256", "files"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise PAFamilyCacheError("PA cache manifest fields differ")
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["role"] != ROLE:
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
        path = root / name
        if not path.is_file() or path.stat().st_size != record["bytes"] or file_sha256(path) != record["sha256"]:
            raise PAFamilyCacheError(f"PA cache family payload differs: {name}")
        names.append(name)
    if names != sorted(names) or len(names) != len(set(names)):
        raise PAFamilyCacheError("PA cache inventory filenames are not sorted and unique")
    if _actual_payload_names(root) != set(names):
        raise PAFamilyCacheError("PA cache family inventory is incomplete or has extra files")
    if expected_filenames is not None and tuple(names) != _family_names(expected_filenames):
        raise PAFamilyCacheError("PA cache family filenames differ")
    if manifest["generation_sha256"] != _generation_sha256(cache_key, records):
        raise PAFamilyCacheError("PA cache generation identity differs")
    return manifest


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
        return CacheProbe(CacheDisposition.CORRUPT, key, detail=str(exc))
    return CacheProbe(CacheDisposition.HIT, key, directory)


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
        shutil.copy2(source / name, destination / name)
    return pa_family_inventory(destination, names)


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


def publish_pa_family_cache(
    cache_root: str | Path,
    identity: Mapping[str, Any],
    source_directory: str | Path,
    filenames: Sequence[str],
    *,
    lock_timeout_s: float = 30.0,
) -> CachePublication:
    """Copy, verify, and atomically publish one complete PA family generation.

    Existing valid identical content is a ``hit``.  ``source_directory`` may
    contain unrelated run-local sidecars; only ``filenames`` are admitted into
    the immutable generation.  A corrupt existing entry is
    never silently overwritten: callers must investigate or use a new identity.
    """

    key = canonical_pa_family_cache_key(identity)
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    with _PAFamilyCacheKeyLock(root, key, lock_timeout_s):
        existing = probe_pa_family_cache(root, identity, expected_filenames=filenames)
        if existing.disposition is CacheDisposition.HIT:
            manifest = validate_pa_family_cache_generation(existing.generation_directory, expected_cache_key=key, expected_filenames=filenames)
            return CachePublication(CacheDisposition.HIT, key, manifest["generation_sha256"], existing.generation_directory, manifest)
        if existing.disposition is CacheDisposition.CORRUPT:
            raise PAFamilyCacheError(f"refusing to overwrite corrupt PA cache entry {key}: {existing.detail}")

        staging_root = root / STAGING_DIRECTORY
        staging_root.mkdir(exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="pa-family-", dir=staging_root))
        try:
            generation_stage = staging / "generation"
            records = _copy_payload(Path(source_directory), generation_stage, filenames)
            manifest = _manifest(key, identity, records)
            _write_json(generation_stage / MANIFEST_NAME, manifest)
            validate_pa_family_cache_generation(generation_stage, expected_cache_key=key, expected_filenames=filenames)
            key_root = root / key
            generations = key_root / "generations"
            generations.mkdir(parents=True, exist_ok=True)
            destination = generations / manifest["generation_sha256"]
            if destination.exists():
                incumbent = validate_pa_family_cache_generation(destination, expected_cache_key=key, expected_filenames=filenames)
                if incumbent["generation_sha256"] != manifest["generation_sha256"]:
                    raise PAFamilyCacheError("existing PA cache generation identity differs")
                _publish_pointer(key_root, key, incumbent["generation_sha256"])
                return CachePublication(CacheDisposition.HIT, key, incumbent["generation_sha256"], destination, incumbent)
            os.replace(generation_stage, destination)
            _publish_pointer(key_root, key, manifest["generation_sha256"])
            return CachePublication(CacheDisposition.PUBLISHED, key, manifest["generation_sha256"], destination, manifest)
        finally:
            if staging.exists():
                shutil.rmtree(staging)


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
    manifest = validate_pa_family_cache_generation(source, expected_filenames=expected_filenames)
    destination = Path(destination_directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not destination.is_dir():
        raise PAFamilyCacheError(f"run-local PA materialization destination is not a directory: {destination}")
    names = [record["name"] for record in manifest["files"]]
    if destination.exists():
        collisions = [name for name in names if (destination / name).exists()]
        if collisions:
            raise PAFamilyCacheError(
                "run-local PA materialization would overwrite existing family files: "
                + ", ".join(collisions)
            )
    stage = destination.parent / f".{destination.name}.staging-{uuid4().hex}"
    try:
        stage.mkdir()
        for name in names:
            shutil.copy2(source / name, stage / name)
        copied = pa_family_inventory(stage, names)
        if copied != manifest["files"]:
            raise PAFamilyCacheError("run-local PA materialization hash verification failed")
        destination.mkdir(exist_ok=True)
        for name in names:
            os.replace(stage / name, destination / name)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    # Verify the published run-local bytes as well; a successful copy is not enough evidence.
    copied = pa_family_inventory(destination, names)
    if copied != manifest["files"]:
        raise PAFamilyCacheError("published run-local PA family hash verification failed")
    return MaterializedFamily(destination.resolve(), tuple(copied))


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
    parser.add_argument("--action", choices=("probe", "publish", "materialize"), required=True)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--filenames", required=True, help="comma-separated direct PA-family filenames")
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--destination-directory", type=Path)
    parser.add_argument("--lock-timeout-s", type=float, default=30.0)
    args = parser.parse_args(arguments)
    identity = _cli_identity(args.identity)
    filenames = _cli_filenames(args.filenames)
    if args.action == "probe":
        if args.source_directory is not None or args.destination_directory is not None:
            parser.error("probe accepts neither --source-directory nor --destination-directory")
        result = probe_pa_family_cache(args.cache_root, identity, expected_filenames=filenames)
        document: dict[str, Any] = {"disposition": result.disposition.value, "cache_key": result.cache_key,
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
    else:
        if args.destination_directory is None or args.source_directory is not None:
            parser.error("materialize requires --destination-directory and forbids --source-directory")
        probe = probe_pa_family_cache(args.cache_root, identity, expected_filenames=filenames)
        if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
            raise PAFamilyCacheError(f"cannot materialize PA cache {probe.cache_key}: {probe.disposition.value}: {probe.detail}")
        result = materialize_pa_family_cache(
            probe.generation_directory, args.destination_directory, expected_filenames=filenames,
        )
        document = {"disposition": "materialized", "cache_key": probe.cache_key,
                    "generation_directory": str(probe.generation_directory),
                    "destination_directory": str(result.destination_directory), "files": list(result.files)}
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
