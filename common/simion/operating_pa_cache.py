"""Content-addressed cache for composed standalone SIMION operating PAs.

Publication reuses :mod:`pa_family_cache`: private staging, atomic generation
and pointer publication, exact manifests, full hash validation, and read-only
cache hits.  This module adds only the standalone operating-point synthesis
identity.  Version-1 PA0/family-member identities are intentionally rejected:
published family members are not valid inputs to the standalone contract.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import canonical_json_sha256, file_sha256
from common.simion.pa_family_cache import (
    CacheDisposition,
    CacheProbe,
    CachePublication,
    MaterializedFamily,
    PAFamilyCacheError,
    canonical_pa_family_cache_key,
    ensure_pa_family_cache,
    materialize_pa_family_cache,
    probe_pa_family_cache,
    publish_pa_family_cache,
    validate_pa_family_cache_generation,
)


SCHEMA_VERSION = 2
ROLE = "simion_standalone_operating_pa_group"
LINEAR_BASIS_ALGORITHM_ID = "standalone_linear_response_composition"
LINEAR_BASIS_ALGORITHM_FORMAT_VERSION = 2
SHA256 = re.compile(r"^[0-9A-F]{64}$")
_IDENTITY_FIELDS = {"schema_version", "role", "members", "synthesis"}
_MEMBER_FIELDS = {"output_name", "base_pa", "responses", "target_voltage_vector_v"}
_CONTENT_FIELDS = {"bytes", "sha256"}
_RESPONSE_FIELDS = {
    "coordinate", "content", "basis_normalization_v", "applied_voltage_delta_v",
}
_SYNTHESIS_FIELDS = {
    "algorithm_id", "algorithm_format_version", "implementation_sha256", "pa_format_version",
}


class OperatingPACacheError(PAFamilyCacheError):
    """Raised when an operating-PA identity or generation is invalid."""


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OperatingPACacheError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise OperatingPACacheError(f"{label} must be a finite number")
    return result


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OperatingPACacheError(f"{label} must be a positive integer")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperatingPACacheError(f"{label} must be a non-empty string")
    return value


def _output_name(value: object) -> str:
    name = _text(value, "operating PA output_name")
    if Path(name).name != name or Path(name).suffix.lower() != ".pa":
        raise OperatingPACacheError("operating PA output_name must be one direct standalone .pa filename")
    return name


def _standalone_pa_path(value: str | Path, label: str) -> Path:
    path = Path(value)
    if path.suffix.lower() != ".pa":
        raise OperatingPACacheError(
            f"{label} must be a standalone .pa; .paN/.pa0/.pa+/.pa_ family forms are forbidden"
        )
    if not path.is_file():
        raise OperatingPACacheError(f"{label} is missing: {path}")
    surface = path.with_name(f"{path.name}-surf")
    if surface.exists():
        raise OperatingPACacheError(f"{label} uses unsupported surface metadata: {surface}")
    return path


def _content_identity(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _CONTENT_FIELDS:
        raise OperatingPACacheError(f"{label} content fields differ")
    size, digest = value["bytes"], value["sha256"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise OperatingPACacheError(f"{label} byte count is invalid")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise OperatingPACacheError(f"{label} SHA-256 is invalid")
    return {"bytes": size, "sha256": digest}


def file_content_identity(path: str | Path) -> dict[str, object]:
    """Return the exact byte identity used for a PA synthesis input."""

    source = Path(path)
    if not source.is_file():
        raise OperatingPACacheError(f"operating PA input is missing: {source}")
    return {"bytes": source.stat().st_size, "sha256": file_sha256(source)}


def content_identity_from_verified_record(
    record: Mapping[str, object], *, path: str | Path | None = None,
) -> dict[str, object]:
    """Reuse content identity from a receipt already verified by its owner.

    Supplying ``path`` adds an inexpensive existence and byte-count guard, but
    deliberately does not rescan a potentially multi-gigabyte PA payload.  A
    first cache publication and periodic artifact audit still perform complete
    payload hashing; this helper only avoids repeating that work while building
    the key for an operating-point cache probe.
    """

    content = _content_identity(record, "verified manifest record")
    if path is not None:
        source = Path(path)
        if not source.is_file():
            raise OperatingPACacheError(f"verified operating PA input is missing: {source}")
        if source.stat().st_size != content["bytes"]:
            raise OperatingPACacheError(
                f"verified operating PA input byte count differs from its receipt: {source}"
            )
    return content


def operating_pa_member_identity(
    output_name: str,
    base_pa: str | Path,
    responses: Sequence[Mapping[str, object]],
    target_voltage_vector_v: Sequence[float],
) -> dict[str, object]:
    """Hash and describe one standalone output and every response applied to it."""

    if isinstance(responses, (str, bytes)) or not isinstance(responses, Sequence):
        raise OperatingPACacheError("operating PA responses must be a sequence")
    response_identities: list[dict[str, object]] = []
    coordinates: set[str] = set()
    for index, response in enumerate(responses):
        required = {"coordinate", "path", "basis_normalization_v", "applied_voltage_delta_v"}
        if not isinstance(response, Mapping) or set(response) != required:
            raise OperatingPACacheError(f"operating PA response {index} fields differ")
        coordinate = _text(response["coordinate"], f"response {index} coordinate")
        if coordinate in coordinates:
            raise OperatingPACacheError(f"duplicate operating PA response coordinate: {coordinate}")
        coordinates.add(coordinate)
        normalization = _finite(response["basis_normalization_v"], f"response {index} basis normalization")
        if normalization == 0.0:
            raise OperatingPACacheError("basis normalization must be nonzero")
        response_path = _standalone_pa_path(
            Path(str(response["path"])), f"response {index} PA"
        )
        response_identities.append({
            "coordinate": coordinate,
            "content": file_content_identity(response_path),
            "basis_normalization_v": normalization,
            "applied_voltage_delta_v": _finite(
                response["applied_voltage_delta_v"], f"response {index} applied voltage delta"
            ),
        })
    if isinstance(target_voltage_vector_v, (str, bytes)) or not isinstance(target_voltage_vector_v, Sequence):
        raise OperatingPACacheError("target voltage vector must be a sequence")
    target = [_finite(value, "target voltage") for value in target_voltage_vector_v]
    if not target:
        raise OperatingPACacheError("target voltage vector must not be empty")
    return {
        "output_name": _output_name(output_name),
        "base_pa": file_content_identity(_standalone_pa_path(base_pa, "base PA")),
        "responses": response_identities,
        "target_voltage_vector_v": target,
    }


def canonical_operating_pa_identity(identity: Mapping[str, object]) -> dict[str, object]:
    """Validate and canonicalize the complete operating-PA group identity."""

    if not isinstance(identity, Mapping) or set(identity) != _IDENTITY_FIELDS:
        raise OperatingPACacheError("operating PA cache identity fields differ")
    if identity["schema_version"] != SCHEMA_VERSION or identity["role"] != ROLE:
        raise OperatingPACacheError("operating PA cache identity role or version differs")
    raw_members = identity["members"]
    if isinstance(raw_members, (str, bytes)) or not isinstance(raw_members, Sequence) or not raw_members:
        raise OperatingPACacheError("operating PA cache members must be a non-empty sequence")
    members: list[dict[str, object]] = []
    names: list[str] = []
    for member_index, raw_member in enumerate(raw_members):
        if not isinstance(raw_member, Mapping) or set(raw_member) != _MEMBER_FIELDS:
            raise OperatingPACacheError(f"operating PA member {member_index} fields differ")
        name = _output_name(raw_member["output_name"])
        names.append(name)
        raw_responses = raw_member["responses"]
        if isinstance(raw_responses, (str, bytes)) or not isinstance(raw_responses, Sequence):
            raise OperatingPACacheError(f"member {name} responses must be a sequence")
        responses: list[dict[str, object]] = []
        coordinates: list[str] = []
        for response_index, raw_response in enumerate(raw_responses):
            if not isinstance(raw_response, Mapping) or set(raw_response) != _RESPONSE_FIELDS:
                raise OperatingPACacheError(f"member {name} response {response_index} fields differ")
            coordinate = _text(raw_response["coordinate"], "response coordinate")
            coordinates.append(coordinate)
            normalization = _finite(raw_response["basis_normalization_v"], "basis normalization")
            if normalization == 0.0:
                raise OperatingPACacheError("basis normalization must be nonzero")
            responses.append({
                "coordinate": coordinate,
                "content": _content_identity(raw_response["content"], f"member {name} response {coordinate}"),
                "basis_normalization_v": normalization,
                "applied_voltage_delta_v": _finite(
                    raw_response["applied_voltage_delta_v"], "applied voltage delta"
                ),
            })
        if len(coordinates) != len(set(coordinates)):
            raise OperatingPACacheError(f"member {name} response coordinates are not unique")
        raw_target = raw_member["target_voltage_vector_v"]
        if isinstance(raw_target, (str, bytes)) or not isinstance(raw_target, Sequence) or not raw_target:
            raise OperatingPACacheError(f"member {name} target voltage vector is invalid")
        members.append({
            "output_name": name,
            "base_pa": _content_identity(raw_member["base_pa"], f"member {name} base PA"),
            "responses": responses,
            "target_voltage_vector_v": [_finite(value, "target voltage") for value in raw_target],
        })
    if names != sorted(names) or len(names) != len(set(names)):
        raise OperatingPACacheError("operating PA members must have sorted unique output names")
    raw_synthesis = identity["synthesis"]
    if not isinstance(raw_synthesis, Mapping) or set(raw_synthesis) != _SYNTHESIS_FIELDS:
        raise OperatingPACacheError("operating PA synthesis identity fields differ")
    implementation = raw_synthesis["implementation_sha256"]
    if not isinstance(implementation, str) or not SHA256.fullmatch(implementation):
        raise OperatingPACacheError("operating PA synthesis implementation SHA-256 is invalid")
    synthesis = {
        "algorithm_id": _text(raw_synthesis["algorithm_id"], "synthesis algorithm_id"),
        "algorithm_format_version": _positive_integer(
            raw_synthesis["algorithm_format_version"], "synthesis algorithm_format_version"
        ),
        "implementation_sha256": implementation,
        "pa_format_version": _positive_integer(raw_synthesis["pa_format_version"], "PA format version"),
    }
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION, "role": ROLE, "members": members, "synthesis": synthesis,
    }
    try:
        canonical_json_sha256(document)
    except ValueError as exc:
        raise OperatingPACacheError("operating PA identity is not canonical finite JSON") from exc
    return document


def operating_pa_group_identity(
    members: Sequence[Mapping[str, object]], *, algorithm_id: str,
    algorithm_format_version: int, implementation_sha256: str, pa_format_version: int,
) -> dict[str, object]:
    """Create a validated group identity from pre-built member identities."""

    return canonical_operating_pa_identity({
        "schema_version": SCHEMA_VERSION,
        "role": ROLE,
        "members": sorted(
            (deepcopy(dict(member)) for member in members), key=lambda item: str(item.get("output_name"))
        ),
        "synthesis": {
            "algorithm_id": algorithm_id,
            "algorithm_format_version": algorithm_format_version,
            "implementation_sha256": implementation_sha256,
            "pa_format_version": pa_format_version,
        },
    })


def linear_basis_operating_pa_group_identity(
    members: Sequence[Mapping[str, object]], *, pa_format_version: int,
    implementation_path: str | Path | None = None,
) -> dict[str, object]:
    """Bind a group to the standalone linear-response composer.

    The public name is retained for source compatibility, but schema 2 accepts
    only ``base_pa`` identities and direct ``.pa`` outputs.  Version-1
    ``source_pa0``/``.paN`` identities require an explicit migration.
    """

    implementation = (
        Path(implementation_path)
        if implementation_path is not None
        else Path(__file__).with_name("compose_standalone_pa.lua")
    )
    return operating_pa_group_identity(
        members,
        algorithm_id=LINEAR_BASIS_ALGORITHM_ID,
        algorithm_format_version=LINEAR_BASIS_ALGORITHM_FORMAT_VERSION,
        implementation_sha256=str(file_content_identity(implementation)["sha256"]),
        pa_format_version=pa_format_version,
    )


def _backend_identity(identity: Mapping[str, object]) -> dict[str, object]:
    operating = canonical_operating_pa_identity(identity)
    return {
        "geometry": {"artifact_role": ROLE, "operating_identity": operating},
        "gem": {"not_applicable": True},
        "basis_namespace": {"artifact_role": ROLE},
        "mesh": {"not_applicable": True},
        "grid_phase": {"not_applicable": True},
        "surface": "standalone_surface_none",
        "simion_identity": {"bound_by_pa_format_version": operating["synthesis"]["pa_format_version"]},
        "refine_policy": {
            "refine_performed": False,
            "operation": "standalone_linear_response_composition",
        },
        "builder_identity": operating["synthesis"],
    }


def canonical_operating_pa_cache_key(identity: Mapping[str, object]) -> str:
    """Return the exact 64-hex key accepted by artifact capacity gates."""

    return canonical_pa_family_cache_key(_backend_identity(identity))


def _filenames(identity: Mapping[str, object]) -> tuple[str, ...]:
    canonical = canonical_operating_pa_identity(identity)
    return tuple(str(member["output_name"]) for member in canonical["members"])


def probe_operating_pa_cache(cache_root: str | Path, identity: Mapping[str, object]) -> CacheProbe:
    """Return hit/miss/corrupt after full manifest and payload validation."""

    return probe_pa_family_cache(cache_root, _backend_identity(identity), expected_filenames=_filenames(identity))


def ensure_operating_pa_cache(
    cache_root: str | Path,
    identity: Mapping[str, object],
    *,
    lock_timeout_s: float = 30.0,
) -> CacheProbe:
    """Return a usable operating-PA cache state, repairing one v2 member."""

    try:
        return ensure_pa_family_cache(
            cache_root,
            _backend_identity(identity),
            expected_filenames=_filenames(identity),
            lock_timeout_s=lock_timeout_s,
        )
    except PAFamilyCacheError as exc:
        raise OperatingPACacheError(str(exc)) from exc


def validate_operating_pa_cache_generation(
    generation_directory: str | Path, *, expected_identity: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Fail closed unless a generation is an exact operating-PA group."""

    expected_key = canonical_operating_pa_cache_key(expected_identity) if expected_identity is not None else None
    expected_names = _filenames(expected_identity) if expected_identity is not None else None
    try:
        manifest = validate_pa_family_cache_generation(
            generation_directory, expected_cache_key=expected_key, expected_filenames=expected_names,
        )
    except PAFamilyCacheError as exc:
        raise OperatingPACacheError(str(exc)) from exc
    embedded = manifest.get("identity", {}).get("geometry", {}).get("operating_identity")
    canonical_embedded = canonical_operating_pa_identity(embedded)
    if expected_identity is not None and canonical_embedded != canonical_operating_pa_identity(expected_identity):
        raise OperatingPACacheError("operating PA generation identity differs from expected identity")
    return manifest


def publish_operating_pa_cache(
    cache_root: str | Path, identity: Mapping[str, object], source_directory: str | Path, *,
    lock_timeout_s: float = 30.0,
) -> CachePublication:
    """Atomically publish a complete, read-only group of standalone operating PAs."""

    canonical = canonical_operating_pa_identity(identity)
    try:
        return publish_pa_family_cache(
            cache_root, _backend_identity(canonical), source_directory, _filenames(canonical),
            lock_timeout_s=lock_timeout_s,
            recovery_policy="none",
        )
    except PAFamilyCacheError as exc:
        raise OperatingPACacheError(str(exc)) from exc


def materialize_operating_pa_cache(
    generation_directory: str | Path, destination_directory: str | Path, *,
    expected_identity: Mapping[str, object] | None = None,
) -> MaterializedFamily:
    """Copy a validated group to a writable private run directory."""

    try:
        if expected_identity is None:
            manifest = validate_operating_pa_cache_generation(generation_directory)
            names = tuple(record["name"] for record in manifest["files"])
        else:
            names = _filenames(expected_identity)
        result = materialize_pa_family_cache(
            generation_directory, destination_directory, expected_filenames=names
        )
        validate_operating_pa_cache_generation(
            result.source_generation_directory, expected_identity=expected_identity
        )
        return result
    except PAFamilyCacheError as exc:
        raise OperatingPACacheError(str(exc)) from exc


__all__ = [
    "CacheDisposition", "LINEAR_BASIS_ALGORITHM_FORMAT_VERSION", "LINEAR_BASIS_ALGORITHM_ID",
    "OperatingPACacheError", "canonical_operating_pa_cache_key",
    "canonical_operating_pa_identity", "content_identity_from_verified_record",
    "ensure_operating_pa_cache", "file_content_identity", "materialize_operating_pa_cache",
    "linear_basis_operating_pa_group_identity", "operating_pa_group_identity",
    "operating_pa_member_identity", "probe_operating_pa_cache", "publish_operating_pa_cache",
    "validate_operating_pa_cache_generation",
]
