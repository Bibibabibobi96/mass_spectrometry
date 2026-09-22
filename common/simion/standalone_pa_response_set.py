"""Contract for detached standalone responses published with a PA family.

The build stage first writes a receipt that binds each native ``.paN`` source
to a newly exported standalone ``.pa`` object.  Cache publication then includes
that receipt, every source, and every standalone output in its ordinary file
inventory.  This two-stage order avoids a receipt/manifest hash cycle while
still making the immutable generation manifest the byte authority for all
runtime inputs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.simion.cache_generation import _flush_writable_source


SCHEMA_VERSION = 1
ROLE = "simion_standalone_pa_response_set"
POLICY_ID = "new_pa_object_export_surface_none_v1"
SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
NATIVE_RESPONSE = re.compile(r"^.+\.pa([0-9]+)$", re.IGNORECASE)


class StandalonePaResponseSetError(ValueError):
    """Raised when a standalone-response receipt or generation is invalid."""


@dataclass(frozen=True)
class ResponseExport:
    """One build-stage mapping from a native response to a standalone PA."""

    response_id: int
    source_name: str
    standalone_name: str


@dataclass(frozen=True)
class StandalonePaRecord:
    """One manifest-bound standalone response safe for runtime copying."""

    response_id: int
    name: str
    bytes: int
    sha256: str


def _direct_name(value: Any, *, role: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or Path(value).name != value
    ):
        raise StandalonePaResponseSetError(f"{role} must be one direct filename")
    return value


def _response_id(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StandalonePaResponseSetError(
            "standalone response_id must be a non-negative integer"
        )
    return value


def _file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StandalonePaResponseSetError(f"standalone response file is missing: {path}")
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _normalize_exports(exports: Sequence[ResponseExport]) -> tuple[ResponseExport, ...]:
    if isinstance(exports, (str, bytes)) or not isinstance(exports, Sequence) or not exports:
        raise StandalonePaResponseSetError("standalone response mappings are empty")
    normalized: list[ResponseExport] = []
    response_ids: set[int] = set()
    source_names: set[str] = set()
    standalone_names: set[str] = set()
    for export in exports:
        if not isinstance(export, ResponseExport):
            raise StandalonePaResponseSetError("standalone response mapping type differs")
        response_id = _response_id(export.response_id)
        source_name = _direct_name(export.source_name, role="native response source")
        standalone_name = _direct_name(
            export.standalone_name, role="standalone response output"
        )
        source_match = NATIVE_RESPONSE.fullmatch(source_name)
        if source_match is None:
            raise StandalonePaResponseSetError(
                "native response source must use a .paN suffix"
            )
        if int(source_match.group(1)) != response_id:
            raise StandalonePaResponseSetError(
                "native response suffix differs from response_id"
            )
        if not standalone_name.lower().endswith(".pa"):
            raise StandalonePaResponseSetError(
                "standalone response output must use the exact .pa suffix"
            )
        if NATIVE_RESPONSE.fullmatch(standalone_name) is not None:
            raise StandalonePaResponseSetError(
                "standalone response output must not use a .paN suffix"
            )
        if source_name.lower() == standalone_name.lower():
            raise StandalonePaResponseSetError(
                "standalone response output must differ from its native source"
            )
        if (
            response_id in response_ids
            or source_name.lower() in source_names
            or standalone_name.lower() in standalone_names
        ):
            raise StandalonePaResponseSetError(
                "standalone response ids and filenames must be unique"
            )
        response_ids.add(response_id)
        source_names.add(source_name.lower())
        standalone_names.add(standalone_name.lower())
        normalized.append(ResponseExport(response_id, source_name, standalone_name))
    return tuple(sorted(normalized, key=lambda item: item.response_id))


def write_standalone_pa_response_set(
    directory: str | Path,
    exporter: str | Path,
    exports: Sequence[ResponseExport],
    receipt_path: str | Path,
    *,
    policy_id: str = POLICY_ID,
    _owner_inventory: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write the pre-publication receipt for one detached response set.

    The receipt deliberately does not contain its own length or hash.  The
    subsequently-created cache manifest must inventory the receipt itself.
    """

    root = Path(directory)
    if not root.is_dir():
        raise StandalonePaResponseSetError(
            f"standalone response directory is missing: {root}"
        )
    exporter_path = Path(exporter)
    exporter_record = _file_record(exporter_path)
    destination = Path(receipt_path)
    if destination.exists() or destination.is_symlink():
        raise StandalonePaResponseSetError(
            f"standalone response receipt already exists: {destination}"
        )
    if destination.parent.resolve() != root.resolve():
        raise StandalonePaResponseSetError(
            "standalone response receipt must be a direct file in the response directory"
        )
    _direct_name(destination.name, role="standalone response receipt")
    if not isinstance(policy_id, str) or not policy_id:
        raise StandalonePaResponseSetError("standalone response policy_id is invalid")

    # Internal handoff from the transaction owner immediately after its one
    # flush/inventory/read-only boundary; never accepted by this module's CLI.
    indexed = None if _owner_inventory is None else _manifest_records(
        {"schema_version": 1, "files": list(_owner_inventory)}
    )

    def record(name: str) -> dict[str, Any]:
        path = root / name
        if indexed is None:
            _flush_writable_source(path)
            return _file_record(path)
        item = indexed.get(name.lower())
        if (item is None or item["name"] != name or path.is_symlink() or not path.is_file()
                or path.stat().st_size != item["bytes"] or path.stat().st_mode & stat.S_IWUSR):
            raise StandalonePaResponseSetError("owner inventory does not cover response")
        return dict(item)

    response_records: list[dict[str, Any]] = []
    for export in _normalize_exports(exports):
        # The receipt and the later transaction seal must observe the same
        # persisted producer bytes. Reuse the cache owner's flush primitive;
        # immutable retained members require no write handle.
        response_records.append(
            {
                "response_id": export.response_id,
                "source": record(export.source_name),
                "standalone": record(export.standalone_name),
            }
        )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "role": ROLE,
        "policy_id": policy_id,
        "exporter": exporter_record,
        "responses": response_records,
    }
    destination.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt


def _manifest_records(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the direct inventory shared by PA-cache manifest generations.

    The response receipt needs only the sealed direct-file inventory.  Both
    generation-manifest v3 and the public PA-family-cache v1/v2 manifests use
    the same exact ``files`` record schema, so requiring the former would make
    a valid PA-family publication unusable solely because its owner added (or
    has not yet added) unrelated cache metadata.
    """
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") not in {1, 2, 3}:
        raise StandalonePaResponseSetError(
            "cache generation manifest must use a supported direct-inventory schema"
        )
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise StandalonePaResponseSetError("cache generation manifest inventory is empty")
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "bytes", "sha256"}:
            raise StandalonePaResponseSetError(
                "cache generation manifest file record fields differ"
            )
        name = _direct_name(record["name"], role="cache generation payload")
        size = record["bytes"]
        digest = record["sha256"]
        if (
            name.lower() in indexed
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or SHA256.fullmatch(digest) is None
        ):
            raise StandalonePaResponseSetError(
                "cache generation manifest file record is invalid"
            )
        indexed[name.lower()] = {
            "name": name,
            "bytes": size,
            "sha256": digest.upper(),
        }
    return indexed


def _receipt_record(value: Any, *, role: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"name", "bytes", "sha256"}:
        raise StandalonePaResponseSetError(f"{role} record fields differ")
    name = _direct_name(value["name"], role=role)
    size = value["bytes"]
    digest = value["sha256"]
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(digest, str)
        or SHA256.fullmatch(digest) is None
    ):
        raise StandalonePaResponseSetError(f"{role} record identity is invalid")
    return {"name": name, "bytes": size, "sha256": digest.upper()}


def _verify_generation_file(
    root: Path,
    manifest_records: Mapping[str, dict[str, Any]],
    expected: Mapping[str, Any],
    *,
    role: str,
    inventory_is_verified: bool,
) -> dict[str, Any]:
    name = str(expected["name"])
    manifest_record = manifest_records.get(name.lower())
    if manifest_record != dict(expected):
        raise StandalonePaResponseSetError(f"{role} is not exactly covered by manifest")
    if inventory_is_verified:
        return manifest_record
    actual = _file_record(root / name)
    if actual != dict(expected):
        raise StandalonePaResponseSetError(f"{role} bytes differ from receipt")
    return actual


def validate_standalone_pa_response_set(
    generation_directory: str | Path,
    manifest: Mapping[str, Any],
    receipt_name: str,
    *,
    expected_response_ids: Sequence[int] | None = None,
    expected_policy_id: str = POLICY_ID,
    inventory_is_verified: bool = False,
) -> tuple[StandalonePaRecord, ...]:
    """Validate a published response receipt and return standalone records only."""

    root = Path(generation_directory)
    if not root.is_dir():
        raise StandalonePaResponseSetError(
            f"cache generation directory is missing: {root}"
        )
    receipt_name = _direct_name(receipt_name, role="standalone response receipt")
    records = _manifest_records(manifest)
    receipt_manifest_record = records.get(receipt_name.lower())
    if receipt_manifest_record is None:
        raise StandalonePaResponseSetError(
            "standalone response receipt is not covered by manifest"
        )
    if not inventory_is_verified:
        actual_receipt = _file_record(root / receipt_name)
        if actual_receipt != receipt_manifest_record:
            raise StandalonePaResponseSetError(
                "standalone response receipt bytes differ from manifest"
            )
    try:
        receipt = json.loads((root / receipt_name).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StandalonePaResponseSetError(
            "standalone response receipt is unreadable"
        ) from exc
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"schema_version", "role", "policy_id", "exporter", "responses"}
        or receipt["schema_version"] != SCHEMA_VERSION
        or receipt["role"] != ROLE
        or receipt["policy_id"] != expected_policy_id
    ):
        raise StandalonePaResponseSetError("standalone response receipt identity differs")
    _receipt_record(receipt["exporter"], role="standalone response exporter")
    response_values = receipt["responses"]
    if not isinstance(response_values, list) or not response_values:
        raise StandalonePaResponseSetError("standalone response receipt has no responses")

    selected: list[StandalonePaRecord] = []
    exports: list[ResponseExport] = []
    normalized_receipt_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for value in response_values:
        if not isinstance(value, dict) or set(value) != {
            "response_id",
            "source",
            "standalone",
        }:
            raise StandalonePaResponseSetError("standalone response entry fields differ")
        source = _receipt_record(value["source"], role="native response source")
        standalone = _receipt_record(
            value["standalone"], role="standalone response output"
        )
        exports.append(
            ResponseExport(
                _response_id(value["response_id"]),
                source["name"],
                standalone["name"],
            )
        )
        normalized_receipt_records.append((source, standalone))
    normalized_exports = _normalize_exports(exports)
    if tuple(exports) != normalized_exports:
        raise StandalonePaResponseSetError(
            "standalone responses must be ordered by response_id"
        )
    expected_ids = (
        tuple(export.response_id for export in normalized_exports)
        if expected_response_ids is None
        else tuple(_response_id(value) for value in expected_response_ids)
    )
    if expected_ids != tuple(export.response_id for export in normalized_exports):
        raise StandalonePaResponseSetError("standalone response ids differ from expected set")

    for export, (source, standalone) in zip(
        normalized_exports, normalized_receipt_records, strict=True
    ):
        _verify_generation_file(
            root,
            records,
            source,
            role=f"native response {export.response_id}",
            inventory_is_verified=inventory_is_verified,
        )
        verified = _verify_generation_file(
            root,
            records,
            standalone,
            role=f"standalone response {export.response_id}",
            inventory_is_verified=inventory_is_verified,
        )
        selected.append(
            StandalonePaRecord(
                export.response_id,
                verified["name"],
                verified["bytes"],
                verified["sha256"],
            )
        )
    return tuple(selected)


def select_standalone_pa_records(
    generation_directory: str | Path,
    manifest: Mapping[str, Any],
    receipt_name: str,
    *,
    expected_response_ids: Sequence[int] | None = None,
    expected_policy_id: str = POLICY_ID,
) -> tuple[StandalonePaRecord, ...]:
    """Return only validated standalone ``.pa`` files for runtime copying."""

    records = validate_standalone_pa_response_set(
        generation_directory,
        manifest,
        receipt_name,
        expected_response_ids=expected_response_ids,
        expected_policy_id=expected_policy_id,
    )
    if any(
        not record.name.lower().endswith(".pa")
        or NATIVE_RESPONSE.fullmatch(record.name) is not None
        or record.name.lower().endswith((".pa0", ".pa+", ".pa_"))
        for record in records
    ):
        raise StandalonePaResponseSetError(
            "runtime selection contains a native PA-family member"
        )
    return records


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate a sealed response receipt without rereading its PA payload."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-sealed-receipt", action="store_true")
    parser.add_argument("--generation-directory", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--receipt-name")
    parser.add_argument("--expected-response-ids")
    args = parser.parse_args(arguments)
    if not args.validate_sealed_receipt:
        parser.error("--validate-sealed-receipt is required")
    if (
        args.generation_directory is None
        or args.inventory is None
        or not args.receipt_name
        or not args.expected_response_ids
    ):
        parser.error(
            "sealed receipt validation requires generation directory, inventory, receipt name, and response ids"
        )
    try:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StandalonePaResponseSetError("sealed response inventory is unreadable") from exc
    try:
        expected = tuple(int(value) for value in args.expected_response_ids.split(","))
    except ValueError as exc:
        raise StandalonePaResponseSetError("expected response ids are invalid") from exc
    records = validate_standalone_pa_response_set(
        args.generation_directory,
        inventory,
        args.receipt_name,
        expected_response_ids=expected,
        inventory_is_verified=True,
    )
    print(json.dumps({"role": ROLE, "status": "pass", "responses": len(records)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
