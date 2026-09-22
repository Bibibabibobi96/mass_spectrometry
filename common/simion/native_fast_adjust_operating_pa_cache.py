"""Cache detached operating PAs exported from a private native PA0 family.

The native controller is valid only while its writable build staging exists.
This module binds every detached output to that family's content identity and
to a complete Fast Adjust voltage table, then delegates immutable publication
and writable materialization to :mod:`common.simion.pa_family_cache`.
It never publishes or materializes ``.pa0``/``.paN`` family members.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
import re
import stat
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
    migrate_current_pa_family_cache,
    probe_pa_family_cache,
    publish_pa_family_cache,
    validate_pa_family_cache_generation,
)


SCHEMA_VERSION = 1
ROLE = "simion_native_family_operating_pa_group"
ALGORITHM_ID = "native_pa0_fast_adjust_detached_export"
ALGORITHM_FORMAT_VERSION = 1
PA_FORMAT_VERSION = 2020
EXPORT_RECEIPT_SUFFIX = ".boundary_mask_restoration.json"
SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_IDENTITY_FIELDS = {"schema_version", "role", "source_family", "members", "synthesis"}
_SOURCE_FIELDS = {"role", "cache_key", "controller_basename", "solution_ids"}
_MEMBER_FIELDS = {"output_name", "electrode_voltages_v"}
_VOLTAGE_FIELDS = {"electrode_id", "voltage_v"}
_SYNTHESIS_FIELDS = {
    "algorithm_id", "algorithm_format_version", "exporter_sha256", "pa_format_version",
}


class NativeOperatingPACacheError(PAFamilyCacheError):
    """Raised when a native-family operating PA contract is invalid."""


@dataclass(frozen=True)
class NativeOperatingPAExport:
    """One validated exporter invocation, excluding the SIMION executable."""

    exporter_path: Path
    source_controller: Path
    output_path: Path
    receipt_path: Path
    voltage_arguments: tuple[str, ...]

    @property
    def lua_arguments(self) -> tuple[str, ...]:
        """Return arguments following ``simion ... lua`` for this export."""

        return (
            str(self.exporter_path),
            str(self.source_controller),
            str(self.output_path),
            str(self.receipt_path),
            *self.voltage_arguments,
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NativeOperatingPACacheError(f"{label} must be a non-empty string")
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NativeOperatingPACacheError(f"{label} must be a positive integer")
    return value


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NativeOperatingPACacheError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise NativeOperatingPACacheError(f"{label} must be a finite number")
    return result


def _direct_filename(value: object, label: str, suffix: str) -> str:
    name = _text(value, label)
    if Path(name).name != name or not name.lower().endswith(suffix):
        raise NativeOperatingPACacheError(
            f"{label} must be one direct filename ending in {suffix}"
        )
    return name


def _solution_ids(value: object) -> list[int]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise NativeOperatingPACacheError("source family solution_ids must be non-empty")
    values = [_positive_integer(item, "solution ID") for item in value]
    if values != sorted(values) or len(values) != len(set(values)):
        raise NativeOperatingPACacheError("source family solution_ids must be sorted and unique")
    return values


def _voltage_table(value: object, solution_ids: Sequence[int], label: str) -> list[dict[str, object]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise NativeOperatingPACacheError(f"{label} must be a non-empty sequence")
    entries: list[dict[str, object]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping) or set(raw) != _VOLTAGE_FIELDS:
            raise NativeOperatingPACacheError(f"{label} entry {index} fields differ")
        entries.append({
            "electrode_id": _positive_integer(raw["electrode_id"], "electrode ID"),
            "voltage_v": _finite(raw["voltage_v"], "electrode voltage"),
        })
    electrode_ids = [int(entry["electrode_id"]) for entry in entries]
    if electrode_ids != sorted(electrode_ids) or len(electrode_ids) != len(set(electrode_ids)):
        raise NativeOperatingPACacheError(f"{label} electrode IDs must be sorted and unique")
    if electrode_ids != list(solution_ids):
        raise NativeOperatingPACacheError(
            f"{label} must cover every source family solution ID exactly once"
        )
    return entries


def native_operating_pa_member_identity(
    output_name: str,
    electrode_voltages_v: Mapping[int, float],
) -> dict[str, object]:
    """Create one member identity from a complete positive-ID voltage mapping.

    Completeness relative to the native family is checked when the group
    identity is assembled, because the family owns the solution-ID inventory.
    """

    if not isinstance(electrode_voltages_v, Mapping) or not electrode_voltages_v:
        raise NativeOperatingPACacheError("electrode voltage table must be a non-empty mapping")
    entries = [
        {
            "electrode_id": _positive_integer(electrode_id, "electrode ID"),
            "voltage_v": _finite(voltage, "electrode voltage"),
        }
        for electrode_id, voltage in electrode_voltages_v.items()
    ]
    entries.sort(key=lambda entry: int(entry["electrode_id"]))
    if len(entries) != len({int(entry["electrode_id"]) for entry in entries}):
        raise NativeOperatingPACacheError("electrode voltage IDs must be unique")
    return {
        "output_name": _direct_filename(output_name, "operating PA output_name", ".pa"),
        "electrode_voltages_v": entries,
    }


def canonical_native_operating_pa_identity(
    identity: Mapping[str, object],
) -> dict[str, object]:
    """Validate and canonicalize one complete native-family cache identity."""

    if not isinstance(identity, Mapping) or set(identity) != _IDENTITY_FIELDS:
        raise NativeOperatingPACacheError("native operating PA identity fields differ")
    if identity["schema_version"] != SCHEMA_VERSION or identity["role"] != ROLE:
        raise NativeOperatingPACacheError("native operating PA identity role or version differs")

    raw_source = identity["source_family"]
    if not isinstance(raw_source, Mapping) or set(raw_source) != _SOURCE_FIELDS:
        raise NativeOperatingPACacheError("native operating PA source family fields differ")
    cache_key = raw_source["cache_key"]
    if not isinstance(cache_key, str) or not SHA256.fullmatch(cache_key):
        raise NativeOperatingPACacheError("source family cache_key must be 64-hex")
    solution_ids = _solution_ids(raw_source["solution_ids"])
    source_family = {
        "role": _text(raw_source["role"], "source family role"),
        "cache_key": cache_key.upper(),
        "controller_basename": _direct_filename(
            raw_source["controller_basename"], "source family controller_basename", ".pa0"
        ),
        "solution_ids": solution_ids,
    }

    raw_members = identity["members"]
    if isinstance(raw_members, (str, bytes)) or not isinstance(raw_members, Sequence) or not raw_members:
        raise NativeOperatingPACacheError("native operating PA members must be non-empty")
    members: list[dict[str, object]] = []
    for index, raw_member in enumerate(raw_members):
        if not isinstance(raw_member, Mapping) or set(raw_member) != _MEMBER_FIELDS:
            raise NativeOperatingPACacheError(f"native operating PA member {index} fields differ")
        output_name = _direct_filename(
            raw_member["output_name"], "operating PA output_name", ".pa"
        )
        members.append({
            "output_name": output_name,
            "electrode_voltages_v": _voltage_table(
                raw_member["electrode_voltages_v"], solution_ids, f"member {output_name} voltage table"
            ),
        })
    names = [str(member["output_name"]) for member in members]
    if names != sorted(names) or len(names) != len(set(names)):
        raise NativeOperatingPACacheError(
            "native operating PA members must have sorted unique output names"
        )

    raw_synthesis = identity["synthesis"]
    if not isinstance(raw_synthesis, Mapping) or set(raw_synthesis) != _SYNTHESIS_FIELDS:
        raise NativeOperatingPACacheError("native operating PA synthesis fields differ")
    exporter_sha256 = raw_synthesis["exporter_sha256"]
    if not isinstance(exporter_sha256, str) or not SHA256.fullmatch(exporter_sha256):
        raise NativeOperatingPACacheError("native operating PA exporter SHA-256 is invalid")
    if raw_synthesis["pa_format_version"] != PA_FORMAT_VERSION:
        raise NativeOperatingPACacheError("native operating PA format must be SIMION 2020")
    synthesis = {
        "algorithm_id": _text(raw_synthesis["algorithm_id"], "synthesis algorithm_id"),
        "algorithm_format_version": _positive_integer(
            raw_synthesis["algorithm_format_version"], "synthesis algorithm format version"
        ),
        "exporter_sha256": exporter_sha256.upper(),
        "pa_format_version": PA_FORMAT_VERSION,
    }
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "role": ROLE,
        "source_family": source_family,
        "members": members,
        "synthesis": synthesis,
    }
    try:
        canonical_json_sha256(document)
    except ValueError as exc:
        raise NativeOperatingPACacheError(
            "native operating PA identity is not canonical finite JSON"
        ) from exc
    return document


def native_operating_pa_group_identity(
    *,
    source_family_role: str,
    source_family_cache_key: str,
    controller_basename: str,
    solution_ids: Sequence[int],
    members: Sequence[Mapping[str, object]],
    exporter_path: str | Path | None = None,
) -> dict[str, object]:
    """Create the identity for outputs exported during one family build."""

    exporter = (
        Path(exporter_path)
        if exporter_path is not None
        else Path(__file__).with_name("export_fast_adjusted_standalone_pa.lua")
    )
    if not exporter.is_file():
        raise NativeOperatingPACacheError(f"native operating PA exporter is missing: {exporter}")
    return canonical_native_operating_pa_identity({
        "schema_version": SCHEMA_VERSION,
        "role": ROLE,
        "source_family": {
            "role": source_family_role,
            "cache_key": source_family_cache_key,
            "controller_basename": controller_basename,
            "solution_ids": list(solution_ids),
        },
        "members": sorted(
            (deepcopy(dict(member)) for member in members),
            key=lambda member: str(member.get("output_name")),
        ),
        "synthesis": {
            "algorithm_id": ALGORITHM_ID,
            "algorithm_format_version": ALGORITHM_FORMAT_VERSION,
            "exporter_sha256": file_sha256(exporter),
            "pa_format_version": PA_FORMAT_VERSION,
        },
    })


def build_native_operating_pa_export_plan(
    identity: Mapping[str, object],
    staging_directory: str | Path,
    output_directory: str | Path,
    *,
    exporter_path: str | Path | None = None,
) -> tuple[NativeOperatingPAExport, ...]:
    """Validate private staging and return deterministic Lua export requests.

    The caller owns SIMION process execution and the staging lifecycle.  This
    function requires a writable direct ``.pa0`` controller, an exact exporter
    implementation, and outputs that do not already exist.
    """

    canonical = canonical_native_operating_pa_identity(identity)
    exporter = (
        Path(exporter_path)
        if exporter_path is not None
        else Path(__file__).with_name("export_fast_adjusted_standalone_pa.lua")
    )
    if not exporter.is_file() or file_sha256(exporter) != canonical["synthesis"]["exporter_sha256"]:
        raise NativeOperatingPACacheError("native operating PA exporter differs from identity")
    staging = Path(staging_directory)
    output_root = Path(output_directory)
    controller = staging / str(canonical["source_family"]["controller_basename"])
    if not controller.is_file():
        raise NativeOperatingPACacheError(f"native family staging controller is missing: {controller}")
    if not controller.stat().st_mode & stat.S_IWUSR:
        raise NativeOperatingPACacheError("native family staging controller must be writable")
    if controller.with_name(controller.name[:-1] + "-surf").exists():
        raise NativeOperatingPACacheError("surface-enhanced native families are unsupported")
    if not output_root.is_dir():
        raise NativeOperatingPACacheError(f"native operating PA output directory is missing: {output_root}")

    plans: list[NativeOperatingPAExport] = []
    for member in canonical["members"]:
        output = output_root / str(member["output_name"])
        receipt = output.with_name(output.name + EXPORT_RECEIPT_SUFFIX)
        if output.exists() or output.is_symlink():
            raise NativeOperatingPACacheError(f"native operating PA output already exists: {output}")
        if receipt.exists() or receipt.is_symlink():
            raise NativeOperatingPACacheError(
                f"native operating PA export receipt already exists: {receipt}"
            )
        voltage_arguments = tuple(
            f"{entry['electrode_id']}={format(float(entry['voltage_v']), '.17g')}"
            for entry in member["electrode_voltages_v"]
        )
        plans.append(
            NativeOperatingPAExport(
                exporter, controller, output, receipt, voltage_arguments
            )
        )
    return tuple(plans)


def _backend_identity(identity: Mapping[str, object]) -> dict[str, object]:
    canonical = canonical_native_operating_pa_identity(identity)
    return {
        "geometry": {"artifact_role": ROLE, "operating_identity": canonical},
        "gem": {"not_applicable": True},
        "basis_namespace": {"artifact_role": ROLE},
        "mesh": {"bound_by_source_family_cache_key": canonical["source_family"]["cache_key"]},
        "grid_phase": {"bound_by_source_family_cache_key": canonical["source_family"]["cache_key"]},
        "surface": "standalone_surface_none",
        "simion_identity": {"pa_format_version": PA_FORMAT_VERSION},
        "refine_policy": {
            "refine_performed": False,
            "operation": ALGORITHM_ID,
            "source_family_refine_bound_by_cache_key": True,
        },
        "builder_identity": canonical["synthesis"],
    }


def canonical_native_operating_pa_cache_key(identity: Mapping[str, object]) -> str:
    """Return the content-addressed key for one detached operating group."""

    return canonical_pa_family_cache_key(_backend_identity(identity))


def _filenames(identity: Mapping[str, object]) -> tuple[str, ...]:
    canonical = canonical_native_operating_pa_identity(identity)
    return tuple(str(member["output_name"]) for member in canonical["members"])


def probe_native_operating_pa_cache(
    cache_root: str | Path, identity: Mapping[str, object]
) -> CacheProbe:
    """Probe one immutable native-family operating PA group."""

    return probe_pa_family_cache(
        cache_root, _backend_identity(identity), expected_filenames=_filenames(identity)
    )


def ensure_native_operating_pa_cache(
    cache_root: str | Path,
    identity: Mapping[str, object],
    *,
    lock_timeout_s: float = 30.0,
) -> CacheProbe:
    """Return a usable native operating cache state, repairing one v2 member."""

    try:
        return ensure_pa_family_cache(
            cache_root,
            _backend_identity(identity),
            expected_filenames=_filenames(identity),
            lock_timeout_s=lock_timeout_s,
        )
    except PAFamilyCacheError as exc:
        raise NativeOperatingPACacheError(str(exc)) from exc


def validate_native_operating_pa_cache_generation(
    generation_directory: str | Path,
    *,
    expected_identity: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Fail closed unless a generation is the exact requested operating group."""

    expected_key = (
        canonical_native_operating_pa_cache_key(expected_identity)
        if expected_identity is not None else None
    )
    expected_names = _filenames(expected_identity) if expected_identity is not None else None
    try:
        manifest = validate_pa_family_cache_generation(
            generation_directory,
            expected_cache_key=expected_key,
            expected_filenames=expected_names,
        )
    except PAFamilyCacheError as exc:
        raise NativeOperatingPACacheError(str(exc)) from exc
    embedded = manifest.get("identity", {}).get("geometry", {}).get("operating_identity")
    canonical_embedded = canonical_native_operating_pa_identity(embedded)
    if (
        expected_identity is not None
        and canonical_embedded != canonical_native_operating_pa_identity(expected_identity)
    ):
        raise NativeOperatingPACacheError(
            "native operating PA generation identity differs from expected identity"
        )
    return manifest


def publish_native_operating_pa_cache(
    cache_root: str | Path,
    identity: Mapping[str, object],
    source_directory: str | Path,
    *,
    lock_timeout_s: float = 30.0,
) -> CachePublication:
    """Atomically publish only detached direct ``.pa`` outputs."""

    canonical = canonical_native_operating_pa_identity(identity)
    source = Path(source_directory)
    for name in _filenames(canonical):
        path = source / name
        if not path.is_file():
            raise NativeOperatingPACacheError(f"native operating PA output is missing: {path}")
        if path.with_name(f"{path.name}-surf").exists():
            raise NativeOperatingPACacheError(
                f"native operating PA output uses unsupported surface metadata: {path}"
            )
    try:
        return publish_pa_family_cache(
            cache_root,
            _backend_identity(canonical),
            source,
            _filenames(canonical),
            lock_timeout_s=lock_timeout_s,
        )
    except PAFamilyCacheError as exc:
        raise NativeOperatingPACacheError(str(exc)) from exc


def migrate_native_operating_pa_cache(
    cache_root: str | Path,
    identity: Mapping[str, object],
    *,
    lock_timeout_s: float = 30.0,
) -> CachePublication:
    """Migrate the current native operating group to recoverable schema v2."""

    canonical = canonical_native_operating_pa_identity(identity)
    try:
        return migrate_current_pa_family_cache(
            cache_root,
            _backend_identity(canonical),
            _filenames(canonical),
            lock_timeout_s=lock_timeout_s,
        )
    except PAFamilyCacheError as exc:
        raise NativeOperatingPACacheError(str(exc)) from exc


def materialize_native_operating_pa_cache(
    generation_directory: str | Path,
    destination_directory: str | Path,
    *,
    expected_identity: Mapping[str, object] | None = None,
) -> MaterializedFamily:
    """Materialize validated standalone outputs as writable private files."""

    try:
        if expected_identity is None:
            manifest = validate_native_operating_pa_cache_generation(generation_directory)
            names = tuple(str(record["name"]) for record in manifest["files"])
        else:
            names = _filenames(expected_identity)
        result = materialize_pa_family_cache(
            generation_directory, destination_directory, expected_filenames=names
        )
        validate_native_operating_pa_cache_generation(
            result.source_generation_directory, expected_identity=expected_identity
        )
        return result
    except PAFamilyCacheError as exc:
        raise NativeOperatingPACacheError(str(exc)) from exc


__all__ = [
    "ALGORITHM_FORMAT_VERSION",
    "ALGORITHM_ID",
    "CacheDisposition",
    "EXPORT_RECEIPT_SUFFIX",
    "ensure_native_operating_pa_cache",
    "NativeOperatingPACacheError",
    "NativeOperatingPAExport",
    "PA_FORMAT_VERSION",
    "build_native_operating_pa_export_plan",
    "canonical_native_operating_pa_cache_key",
    "canonical_native_operating_pa_identity",
    "materialize_native_operating_pa_cache",
    "migrate_native_operating_pa_cache",
    "native_operating_pa_group_identity",
    "native_operating_pa_member_identity",
    "probe_native_operating_pa_cache",
    "publish_native_operating_pa_cache",
    "validate_native_operating_pa_cache_generation",
]
