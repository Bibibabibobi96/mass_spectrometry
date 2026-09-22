"""Prepare immutable reviewed analyzer inputs without retaining a native family.

On a miss the reviewed r41 family is copied once into disposable writable
staging. SIMION exports fourteen one-hot physical-electrode responses there;
only detached PAs and a separately bound raw-geometry generation are published.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import canonical_json_sha256, file_sha256
from common.simion.cache_generation import copy_verified_file
from common.simion.native_fast_adjust_operating_pa_cache import (
    build_native_operating_pa_export_plan,
    canonical_native_operating_pa_cache_key,
    migrate_native_operating_pa_cache,
    native_operating_pa_group_identity,
    native_operating_pa_member_identity,
    publish_native_operating_pa_cache,
    validate_native_operating_pa_cache_generation,
)
from common.simion.pa_family_cache import (
    POINTER_NAME,
    PAFamilyCacheError,
    canonical_pa_family_cache_key,
    migrate_current_pa_family_cache,
    pa_family_inventory,
    publish_pa_family_cache,
    repair_pa_family_cache_generation,
    validate_pa_family_cache_generation,
)

SCHEMA_VERSION = 1
PROJECT_ID = "parallel_mirror_dual_stripe_mr_tof"
NATIVE_FILENAMES = (
    "mrtof_analyzer.pa#", "mrtof_analyzer.pa0",
    *(f"mrtof_analyzer.pa{identifier}" for identifier in range(1, 21)),
)
PHYSICAL_RESPONSE_IDS = (2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17)
RAW_GEOMETRY_FILENAME = "mrtof_analyzer.pa#"
RESPONSE_FILENAMES = {
    identifier: f"mrtof_analyzer.response{identifier}.pa"
    for identifier in PHYSICAL_RESPONSE_IDS
}
SHA256 = re.compile(r"^[0-9A-F]{64}$")


def _lightweight_pointer_probe(cache_root: Path, cache_key: str) -> dict[str, Any]:
    """Locate a candidate generation without hashing payload bytes.

    A candidate hit is fully validated exactly once by ``receipt_from_hit``.
    """
    pointer_path = cache_root / cache_key / POINTER_NAME
    if not pointer_path.is_file():
        return {"disposition": "miss", "generation_sha256": None, "generation_directory": None, "detail": "pointer absent"}
    try:
        pointer = _load_json(pointer_path, "cache pointer")
        generation = str(pointer["generation_sha256"])
    except (KeyError, PAFamilyCacheError) as exc:
        return {"disposition": "corrupt", "generation_sha256": None, "generation_directory": None, "detail": str(exc)}
    if pointer.get("cache_key") != cache_key or SHA256.fullmatch(generation) is None:
        return {"disposition": "corrupt", "generation_sha256": None, "generation_directory": None, "detail": "pointer identity differs"}
    directory = cache_root / cache_key / "generations" / generation
    if not directory.is_dir():
        return {"disposition": "corrupt", "generation_sha256": generation, "generation_directory": str(directory), "detail": "generation absent"}
    try:
        manifest = _load_json(directory / "cache_manifest.json", "cache manifest")
        files = manifest["files"]
        if (
            manifest.get("cache_key") != cache_key
            or manifest.get("generation_sha256") != generation
            or not isinstance(files, list)
            or any(
                not isinstance(record, Mapping)
                or not isinstance(record.get("bytes"), int)
                or isinstance(record.get("bytes"), bool)
                or record["bytes"] < 0
                for record in files
            )
        ):
            raise PAFamilyCacheError("cache manifest identity or file inventory differs")
        payload_bytes = sum(int(record["bytes"]) for record in files)
        migration_parity_bytes = sum({int(record["bytes"]) for record in files})
    except (KeyError, PAFamilyCacheError) as exc:
        return {"disposition": "corrupt", "generation_sha256": generation, "generation_directory": str(directory), "detail": str(exc)}
    return {
        "disposition": "hit",
        "generation_sha256": generation,
        "generation_directory": str(directory.resolve()),
        "schema_version": manifest.get("schema_version"),
        "payload_bytes": payload_bytes,
        "migration_parity_bytes": migration_parity_bytes,
        "detail": None,
    }


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PAFamilyCacheError(f"{label} must be a JSON object")
    return value


def _record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PAFamilyCacheError(f"{label} record is missing")
    name = Path(str(value.get("path", value.get("name", "")))).name
    byte_count = value.get("bytes")
    digest = str(value.get("sha256", "")).upper()
    if not name or not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
        raise PAFamilyCacheError(f"{label} record is invalid")
    if SHA256.fullmatch(digest) is None:
        raise PAFamilyCacheError(f"{label} SHA-256 is invalid")
    return {"name": name, "bytes": byte_count, "sha256": digest}


def _verify_file(path: Path, expected: Mapping[str, Any], label: str) -> None:
    if not path.is_file() or path.stat().st_size != expected["bytes"] or file_sha256(path) != expected["sha256"]:
        raise PAFamilyCacheError(f"{label} differs from its frozen record: {path}")


def _review_output_record(manifest: Mapping[str, Any], review_path: Path) -> dict[str, Any]:
    matches = [
        item for item in manifest.get("outputs", [])
        if isinstance(item, Mapping) and Path(str(item.get("path", ""))).name == review_path.name
    ]
    if len(matches) != 1:
        raise PAFamilyCacheError("run manifest must contain exactly one geometry-review output")
    return _record(matches[0], "geometry review output")


def _analyzer_review(
    review: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[int, dict[str, Any]], list[float], list[int]]:
    if (review.get("schema_version") != 1 or review.get("project_id") != PROJECT_ID
            or review.get("status") != "prototype_geometry_review_only"):
        raise PAFamilyCacheError("geometry review identity differs")
    analyzers = [
        item for item in review.get("instances", [])
        if isinstance(item, Mapping) and item.get("role") == "analyzer"
    ]
    if len(analyzers) != 1:
        raise PAFamilyCacheError("geometry review must contain exactly one analyzer instance")
    analyzer = analyzers[0]
    pa0 = _record(analyzer.get("pa0"), "reviewed analyzer pa0")
    basis: dict[int, dict[str, Any]] = {}
    for value in analyzer.get("basis_arrays", []):
        item = _record(value, "reviewed analyzer basis")
        match = re.fullmatch(r"mrtof_analyzer\.pa(\d+)", item["name"])
        if match is None:
            raise PAFamilyCacheError("reviewed analyzer basis filename is invalid")
        identifier = int(match.group(1))
        if identifier in basis:
            raise PAFamilyCacheError("reviewed analyzer basis IDs are not unique")
        basis[identifier] = item
    if tuple(sorted(basis)) != tuple(range(1, 21)):
        raise PAFamilyCacheError("reviewed analyzer basis inventory must be pa1 through pa20")
    origin = analyzer.get("origin_mm")
    if not isinstance(origin, list) or len(origin) != 3:
        raise PAFamilyCacheError("reviewed analyzer origin is invalid")
    physical_ids = analyzer.get("physical_electrode_ids")
    if (
        not isinstance(physical_ids, list)
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in physical_ids)
        or physical_ids != sorted(set(physical_ids))
        or physical_ids != [*range(1, 19), 20]
    ):
        raise PAFamilyCacheError("reviewed analyzer physical electrode IDs differ")
    return pa0, basis, [float(value) for value in origin], physical_ids


def _load_run_evidence(run_directory: Path) -> dict[str, Any]:
    run = run_directory.resolve()
    manifest_path = run / "run_manifest.json"
    review_path = run / "simion" / "three_component_geometry_review.json"
    manifest = _load_json(manifest_path, "run manifest")
    if (manifest.get("schema_version") != 2 or manifest.get("role") != "simulation_run_manifest"
            or manifest.get("project") != PROJECT_ID
            or manifest.get("mode") != "three_component_candidate_iob_assembly"
            or manifest.get("status") != "success"):
        raise PAFamilyCacheError(f"run is not a successful reviewed three-component build: {run}")
    review_record = _review_output_record(manifest, review_path)
    _verify_file(review_path, review_record, "geometry review")
    review = _load_json(review_path, "geometry review")
    pa0, basis, origin, physical_ids = _analyzer_review(review)
    inputs = manifest.get("inputs")
    if not isinstance(inputs, Mapping):
        raise PAFamilyCacheError("run manifest inputs are missing")
    gem = _record(inputs.get("analyzer_gem"), "analyzer GEM")
    raw = _record(inputs.get("analyzer_raw_pa"), "analyzer raw PA")
    manifest_pa0 = _record(inputs.get("analyzer_pa0"), "analyzer pa0")
    contract = _record(inputs.get("candidate_contract"), "candidate contract")
    if manifest_pa0 != pa0:
        raise PAFamilyCacheError("run manifest analyzer pa0 differs from geometry review")
    geometry = review.get("geometry")
    resolved = str(geometry.get("resolved_geometry_sha256", "")).upper() if isinstance(geometry, Mapping) else ""
    if SHA256.fullmatch(resolved) is None:
        raise PAFamilyCacheError("resolved geometry SHA-256 is invalid")
    contract_path = run / "inputs" / contract["name"]
    _verify_file(contract_path, contract, "candidate contract")
    contract_document = _load_json(contract_path, "candidate contract")
    try:
        mesh = [float(value) for value in contract_document["simion"]["component_mesh_mm_per_gu"]["analyzer"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise PAFamilyCacheError("candidate contract analyzer mesh is invalid") from exc
    return {
        "run_id": str(manifest.get("run_id", "")), "run_directory": str(run),
        "run_manifest": {"path": str(manifest_path), "bytes": manifest_path.stat().st_size, "sha256": file_sha256(manifest_path)},
        "geometry_review": {"path": str(review_path), **review_record},
        "resolved_geometry_sha256": resolved, "analyzer_origin_mm": origin,
        "physical_electrode_ids": physical_ids,
        "analyzer_gem": gem, "analyzer_raw_pa": raw, "analyzer_pa0": pa0,
        "candidate_contract": contract, "mesh_mm_per_gu": mesh,
        "basis_arrays": {str(key): value for key, value in sorted(basis.items())},
    }


def _controller_evidence(path: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    controller = path.resolve()
    _verify_file(controller, expected, "Fast Adjust controller PA0")
    return {
        "path": str(controller),
        "name": controller.name,
        "bytes": controller.stat().st_size,
        "sha256": file_sha256(controller),
        "matches_provider_frozen_record": True,
    }


def _source_inventory(provider: Mapping[str, Any]) -> list[dict[str, Any]]:
    # The controller is required to be an exact-byte preserved copy of the
    # provider's frozen pa0.  A geometrically compatible pa0 with a different
    # operating state changes SIMION's exported one-hot responses.
    records = [provider["analyzer_raw_pa"], provider["analyzer_pa0"]]
    records.extend(provider["basis_arrays"][str(identifier)] for identifier in range(1, 21))
    by_name = {record["name"]: record for record in records}
    if tuple(sorted(by_name)) != tuple(sorted(NATIVE_FILENAMES)):
        raise PAFamilyCacheError("provider review is not the exact 22-member native family")
    return [by_name[name] for name in sorted(NATIVE_FILENAMES)]


def _raw_identity(source_key: str, inspection: Mapping[str, Any]) -> dict[str, Any]:
    provider = inspection["evidence"]["provider"]
    return {
        "geometry": {"artifact_role": "mrtof_reviewed_analyzer_raw_geometry", "source_content_key": source_key},
        "gem": provider["analyzer_gem"], "basis_namespace": {"artifact_role": "physical_raw_geometry_only"},
        "mesh": inspection["mesh"], "grid_phase": {"analyzer_origin_mm": provider["analyzer_origin_mm"]},
        "surface": "none", "simion_identity": {"pa_format_version": 2020},
        "refine_policy": {"operation": "verified_raw_geometry_copy", "refine_performed": False},
        "builder_identity": {"adapter_sha256": file_sha256(Path(__file__))},
    }


def inspect_reviewed_sources(
    provider_run: Path, reviewed_run: Path, simion_executable: Path,
    simion_release: str, cache_root: Path | None = None,
    controller_pa0: Path | None = None,
) -> dict[str, Any]:
    if not simion_release.strip() or not simion_executable.is_file():
        raise PAFamilyCacheError("SIMION release and executable are required")
    provider, reviewed = _load_run_evidence(provider_run), _load_run_evidence(reviewed_run)
    equal_labels = (
        "resolved_geometry_sha256", "analyzer_gem", "analyzer_raw_pa",
        "candidate_contract", "mesh_mm_per_gu", "physical_electrode_ids", "basis_arrays",
    )
    differences = [label for label in equal_labels if provider[label] != reviewed[label]]
    if differences:
        raise PAFamilyCacheError("r41/r51 reviewed compatibility differs: " + ", ".join(differences))
    if provider["analyzer_pa0"] == reviewed["analyzer_pa0"]:
        raise PAFamilyCacheError("r41/r51 pa0 must differ and is explicitly excluded from compatibility")
    controller_path = (
        controller_pa0
        if controller_pa0 is not None
        else Path(provider["run_directory"]) / "simion" / "mrtof_analyzer.pa0"
    )
    controller = _controller_evidence(controller_path, provider["analyzer_pa0"])
    evidence = {
        "provider": provider, "reviewed": reviewed,
        "controller_pa0": controller,
        "compatibility": {
            "equal": ["resolved_geometry_sha256", "analyzer_gem", "analyzer_raw_pa", "analyzer_pa1_through_pa20"],
            "explicitly_excluded": ["reviewed_analyzer_pa0"],
            "provider_pa0": provider["analyzer_pa0"],
            "reviewed_pa0": reviewed["analyzer_pa0"], "pa0_equal": False,
            "controller_matches_provider_pa0": True,
        },
    }
    source_inventory = _source_inventory(provider)
    source_key = canonical_json_sha256({
        "role": "mrtof_reviewed_analyzer_native_source_content", "inventory": source_inventory,
        "provider_review_sha256": provider["geometry_review"]["sha256"],
        "reviewed_review_sha256": reviewed["geometry_review"]["sha256"],
    })
    simion_identity = {
        "release": simion_release,
        "executable_sha256": file_sha256(simion_executable),
    }
    export_source_key = canonical_json_sha256({
        "source_content_key": source_key,
        "standalone_export_simion_identity": simion_identity,
    })
    members = [
        native_operating_pa_member_identity(
            RESPONSE_FILENAMES[target],
            {
                identifier: 1.0 if identifier == target else 0.0
                for identifier in provider["physical_electrode_ids"]
            },
        )
        for target in PHYSICAL_RESPONSE_IDS
    ]
    operating_identity = native_operating_pa_group_identity(
        source_family_role="mrtof_reviewed_analyzer_native_source_content",
        source_family_cache_key=export_source_key, controller_basename="mrtof_analyzer.pa0",
        solution_ids=provider["physical_electrode_ids"], members=members,
    )
    inspection: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "role": "mrtof_reviewed_analyzer_source_inspection",
        "evidence": evidence, "mesh": {"mm_per_gu": provider["mesh_mm_per_gu"], "reviewed_global_family": True},
        "simion_identity": simion_identity, "source_content_key": source_key,
        "export_source_key": export_source_key, "source_inventory": source_inventory,
        "native_generation_published": False, "operating_identity": operating_identity,
        "prepared_cache_key": canonical_native_operating_pa_cache_key(operating_identity),
    }
    inspection["raw_identity"] = _raw_identity(source_key, inspection)
    inspection["raw_cache_key"] = canonical_pa_family_cache_key(inspection["raw_identity"])
    if cache_root is not None:
        inspection["cache_probe"] = {
            "prepared": _lightweight_pointer_probe(cache_root, inspection["prepared_cache_key"]),
            "raw": _lightweight_pointer_probe(cache_root, inspection["raw_cache_key"]),
        }
    return inspection


def stage_native_source(inspection_path: Path, staging_directory: Path) -> dict[str, Any]:
    inspection = _load_json(inspection_path, "reviewed source inspection")
    if inspection.get("role") != "mrtof_reviewed_analyzer_source_inspection":
        raise PAFamilyCacheError("reviewed source inspection identity differs")
    staging = staging_directory.resolve()
    if not staging.is_dir() or any(staging.iterdir()):
        raise PAFamilyCacheError("native staging directory must exist and be empty")
    provider_root = Path(inspection["evidence"]["provider"]["run_directory"]) / "simion"
    controller_pa0 = Path(inspection["evidence"]["controller_pa0"]["path"])
    expected = {record["name"]: record for record in inspection["source_inventory"]}
    copied: list[dict[str, Any]] = []
    for filename in NATIVE_FILENAMES:
        source = controller_pa0 if filename == "mrtof_analyzer.pa0" else provider_root / filename
        try:
            record = copy_verified_file(source, staging / filename)
        except OSError as exc:
            raise PAFamilyCacheError(f"cannot stage reviewed provider member {filename}") from exc
        normalized = {"name": filename, "bytes": record["bytes"], "sha256": record["sha256"].upper()}
        if normalized != expected[filename]:
            raise PAFamilyCacheError(f"provider {filename} differs from its own geometry review")
        copied.append(normalized)
    exporter = Path(__file__).resolve().parents[3] / "common" / "simion" / "export_fast_adjusted_standalone_pa.lua"
    return {
        "schema_version": SCHEMA_VERSION, "role": "mrtof_reviewed_analyzer_native_staging",
        "source_content_key": inspection["source_content_key"], "staging_directory": str(staging),
        "inventory": sorted(copied, key=lambda item: item["name"]),
        "exporter": {"path": str(exporter), "sha256": file_sha256(exporter)},
    }


def export_plan(inspection_path: Path, staging_directory: Path, output_directory: Path) -> dict[str, Any]:
    inspection = _load_json(inspection_path, "reviewed source inspection")
    plan = build_native_operating_pa_export_plan(inspection["operating_identity"], staging_directory, output_directory)
    by_name = {item.output_path.name: item for item in plan}
    return {
        "schema_version": SCHEMA_VERSION, "role": "mrtof_reviewed_analyzer_export_plan",
        "exports": [
            {"physical_id": identifier, "output_name": RESPONSE_FILENAMES[identifier],
             "lua_arguments": list(by_name[RESPONSE_FILENAMES[identifier]].lua_arguments),
             "receipt_path": str(by_name[RESPONSE_FILENAMES[identifier]].receipt_path)}
            for identifier in PHYSICAL_RESPONSE_IDS
        ],
    }


def _generation_receipt(publication: Any, manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "disposition": publication.disposition.value, "cache_key": publication.cache_key,
        "generation_sha256": publication.generation_sha256,
        "generation_directory": str(publication.generation_directory.resolve()), "inventory": manifest["files"],
    }


def publish_prepared(cache_root: Path, inspection_path: Path, staging_directory: Path, output_directory: Path) -> dict[str, Any]:
    inspection = _load_json(inspection_path, "reviewed source inspection")
    staged_inventory = pa_family_inventory(staging_directory, NATIVE_FILENAMES)
    if staged_inventory != inspection["source_inventory"]:
        raise PAFamilyCacheError("private native staging differs from the reviewed 22-member source inventory")
    export_receipts = []
    for identifier in PHYSICAL_RESPONSE_IDS:
        path = output_directory / f"{RESPONSE_FILENAMES[identifier]}.boundary_mask_restoration.json"
        document = _load_json(path, f"response {identifier} export receipt")
        if document.get("status") != "pass" or document.get("output_basename") != RESPONSE_FILENAMES[identifier]:
            raise PAFamilyCacheError(f"response {identifier} export receipt differs")
        export_receipts.append({
            "physical_id": identifier, "bytes": path.stat().st_size,
            "sha256": file_sha256(path), "receipt": document,
        })
    prepared = publish_native_operating_pa_cache(cache_root, inspection["operating_identity"], output_directory)
    prepared_manifest = validate_native_operating_pa_cache_generation(
        prepared.generation_directory, expected_identity=inspection["operating_identity"]
    )
    raw = publish_pa_family_cache(cache_root, inspection["raw_identity"], staging_directory, [RAW_GEOMETRY_FILENAME])
    raw_manifest = validate_pa_family_cache_generation(
        raw.generation_directory, expected_cache_key=inspection["raw_cache_key"], expected_filenames=[RAW_GEOMETRY_FILENAME]
    )
    records = {record["name"]: record for record in prepared_manifest["files"]}
    return {
        "schema_version": SCHEMA_VERSION, "role": "mrtof_reviewed_analyzer_source_cache_receipt",
        "status": "success", "qualification": "reviewed_source_cache_only__no_flight_or_focus_claim",
        "evidence": inspection["evidence"], "simion_identity": inspection["simion_identity"],
        "source_content_key": inspection["source_content_key"],
        "source_inventory": inspection["source_inventory"], "native_generation_published": False,
        "prepared_standalone_generation": {
            **_generation_receipt(prepared, prepared_manifest),
            "responses_by_physical_id": {
                str(identifier): {"physical_id": identifier, **records[RESPONSE_FILENAMES[identifier]]}
                for identifier in PHYSICAL_RESPONSE_IDS
            }, "export_receipts": export_receipts,
        },
        "raw_geometry_generation": {**_generation_receipt(raw, raw_manifest), "raw_geometry": raw_manifest["files"][0]},
    }


def receipt_from_hit(cache_root: Path, inspection: Mapping[str, Any]) -> dict[str, Any]:
    probe = inspection.get("cache_probe")
    if not isinstance(probe, Mapping):
        raise PAFamilyCacheError("inspection has no pinned cache probe")
    prepared_pin, raw_pin = probe.get("prepared"), probe.get("raw")
    if not isinstance(prepared_pin, Mapping) or prepared_pin.get("disposition") != "hit":
        raise PAFamilyCacheError("inspection has no pinned prepared generation")
    if not isinstance(raw_pin, Mapping) or raw_pin.get("disposition") != "hit":
        raise PAFamilyCacheError("inspection has no pinned raw generation")
    prepared_directory = Path(str(prepared_pin.get("generation_directory", "")))
    raw_directory = Path(str(raw_pin.get("generation_directory", "")))
    expected_prepared = (
        cache_root
        / inspection["prepared_cache_key"]
        / "generations"
        / str(prepared_pin.get("generation_sha256", ""))
    )
    expected_raw = (
        cache_root
        / inspection["raw_cache_key"]
        / "generations"
        / str(raw_pin.get("generation_sha256", ""))
    )
    if prepared_directory.resolve() != expected_prepared.resolve():
        raise PAFamilyCacheError("pinned prepared generation escapes its cache key")
    if raw_directory.resolve() != expected_raw.resolve():
        raise PAFamilyCacheError("pinned raw generation escapes its cache key")
    prepared_repair = None
    raw_repair = None
    prepared_migration = None
    raw_migration = None
    if prepared_pin.get("schema_version") == 1:
        prepared_migration = migrate_native_operating_pa_cache(
            cache_root, inspection["operating_identity"]
        )
        prepared_directory = prepared_migration.generation_directory
    if raw_pin.get("schema_version") == 1:
        raw_migration = migrate_current_pa_family_cache(
            cache_root,
            inspection["raw_identity"],
            [RAW_GEOMETRY_FILENAME],
        )
        raw_directory = raw_migration.generation_directory
    try:
        prepared_manifest = validate_native_operating_pa_cache_generation(
            prepared_directory, expected_identity=inspection["operating_identity"]
        )
        if prepared_migration is None and prepared_manifest["generation_sha256"] != prepared_pin.get("generation_sha256"):
            raise PAFamilyCacheError("pinned prepared generation SHA-256 differs")
    except PAFamilyCacheError:
        prepared_repair = repair_pa_family_cache_generation(prepared_directory)
        prepared_directory = prepared_repair.generation_directory
        prepared_manifest = validate_native_operating_pa_cache_generation(
            prepared_directory, expected_identity=inspection["operating_identity"]
        )
    try:
        raw_manifest = validate_pa_family_cache_generation(
            raw_directory, expected_cache_key=inspection["raw_cache_key"],
            expected_filenames=[RAW_GEOMETRY_FILENAME],
        )
        if raw_migration is None and raw_manifest["generation_sha256"] != raw_pin.get("generation_sha256"):
            raise PAFamilyCacheError("pinned raw generation SHA-256 differs")
    except PAFamilyCacheError:
        raw_repair = repair_pa_family_cache_generation(raw_directory)
        raw_directory = raw_repair.generation_directory
        raw_manifest = validate_pa_family_cache_generation(
            raw_directory,
            expected_cache_key=inspection["raw_cache_key"],
            expected_filenames=[RAW_GEOMETRY_FILENAME],
        )
    records = {record["name"]: record for record in prepared_manifest["files"]}
    return {
        "schema_version": SCHEMA_VERSION, "role": "mrtof_reviewed_analyzer_source_cache_receipt",
        "status": "success", "qualification": "reviewed_source_cache_only__no_flight_or_focus_claim",
        "evidence": inspection["evidence"], "simion_identity": inspection["simion_identity"],
        "source_content_key": inspection["source_content_key"],
        "source_inventory": inspection["source_inventory"], "native_generation_published": False,
        "prepared_standalone_generation": {
            "disposition": (
                prepared_migration.disposition.value
                if prepared_migration is not None else "hit"
            ), "cache_key": inspection["prepared_cache_key"],
            "generation_sha256": prepared_manifest["generation_sha256"],
            "generation_directory": str(prepared_directory.resolve()), "inventory": prepared_manifest["files"],
            "predecessor_generation_directory": (
                str(prepared_repair.predecessor_directory)
                if prepared_repair is not None else None
            ),
            "predecessor_generation_sha256": prepared_manifest.get(
                "predecessor_generation_sha256"
            ),
            "repair_receipt_path": (
                str(prepared_repair.receipt_path) if prepared_repair is not None else None
            ),
            "responses_by_physical_id": {
                str(identifier): {"physical_id": identifier, **records[RESPONSE_FILENAMES[identifier]]}
                for identifier in PHYSICAL_RESPONSE_IDS
            }, "export_receipts": [],
        },
        "raw_geometry_generation": {
            "disposition": (
                raw_migration.disposition.value if raw_migration is not None else "hit"
            ), "cache_key": inspection["raw_cache_key"], "generation_sha256": raw_manifest["generation_sha256"],
            "generation_directory": str(raw_directory.resolve()), "inventory": raw_manifest["files"],
            "predecessor_generation_directory": (
                str(raw_repair.predecessor_directory) if raw_repair is not None else None
            ),
            "predecessor_generation_sha256": raw_manifest.get(
                "predecessor_generation_sha256"
            ),
            "repair_receipt_path": (
                str(raw_repair.receipt_path) if raw_repair is not None else None
            ),
            "raw_geometry": raw_manifest["files"][0],
        },
    }


def publish_raw_from_reviewed(cache_root: Path, inspection: Mapping[str, Any]) -> dict[str, Any]:
    """Repair only the raw-geometry generation while reusing prepared responses."""

    probe = inspection.get("cache_probe")
    if not isinstance(probe, Mapping):
        raise PAFamilyCacheError("inspection has no pinned cache probe")
    prepared_pin, raw_pin = probe.get("prepared"), probe.get("raw")
    if not isinstance(prepared_pin, Mapping) or prepared_pin.get("disposition") != "hit":
        raise PAFamilyCacheError("raw-only repair requires a pinned prepared generation")
    if not isinstance(raw_pin, Mapping) or raw_pin.get("disposition") != "miss":
        raise PAFamilyCacheError("raw-only repair requires a missing raw generation")
    pinned_prepared_directory = Path(
        str(prepared_pin.get("generation_directory", ""))
    )
    expected_prepared_directory = (
        cache_root
        / inspection["prepared_cache_key"]
        / "generations"
        / str(prepared_pin.get("generation_sha256", ""))
    )
    if pinned_prepared_directory.resolve() != expected_prepared_directory.resolve():
        raise PAFamilyCacheError("pinned prepared generation escapes its cache key")
    prepared_migration = migrate_native_operating_pa_cache(
        cache_root, inspection["operating_identity"]
    )
    prepared_directory = prepared_migration.generation_directory
    prepared_manifest = validate_native_operating_pa_cache_generation(
        prepared_directory, expected_identity=inspection["operating_identity"]
    )

    provider_directory = Path(inspection["evidence"]["provider"]["run_directory"]) / "simion"
    provider_raw = pa_family_inventory(provider_directory, [RAW_GEOMETRY_FILENAME])
    if provider_raw != [inspection["evidence"]["provider"]["analyzer_raw_pa"]]:
        raise PAFamilyCacheError("provider raw geometry differs from reviewed evidence")
    raw = publish_pa_family_cache(
        cache_root, inspection["raw_identity"], provider_directory, [RAW_GEOMETRY_FILENAME]
    )
    raw_manifest = validate_pa_family_cache_generation(
        raw.generation_directory,
        expected_cache_key=inspection["raw_cache_key"],
        expected_filenames=[RAW_GEOMETRY_FILENAME],
    )
    records = {record["name"]: record for record in prepared_manifest["files"]}
    return {
        "schema_version": SCHEMA_VERSION,
        "role": "mrtof_reviewed_analyzer_source_cache_receipt",
        "status": "success",
        "qualification": "reviewed_source_cache_only__no_flight_or_focus_claim",
        "evidence": inspection["evidence"],
        "simion_identity": inspection["simion_identity"],
        "source_content_key": inspection["source_content_key"],
        "source_inventory": inspection["source_inventory"],
        "native_generation_published": False,
        "prepared_standalone_generation": {
            "disposition": prepared_migration.disposition.value,
            "cache_key": inspection["prepared_cache_key"],
            "generation_sha256": prepared_manifest["generation_sha256"],
            "generation_directory": str(prepared_directory.resolve()),
            "predecessor_generation_sha256": prepared_manifest.get(
                "predecessor_generation_sha256"
            ),
            "inventory": prepared_manifest["files"],
            "responses_by_physical_id": {
                str(identifier): {
                    "physical_id": identifier,
                    **records[RESPONSE_FILENAMES[identifier]],
                }
                for identifier in PHYSICAL_RESPONSE_IDS
            },
            "export_receipts": [],
        },
        "raw_geometry_generation": {
            **_generation_receipt(raw, raw_manifest),
            "raw_geometry": raw_manifest["files"][0],
        },
    }


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=(
            "inspect", "stage-native", "export-plan", "publish-prepared",
            "publish-raw", "receipt-from-hit",
        ),
        required=True,
    )
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--provider-run", type=Path); parser.add_argument("--reviewed-run", type=Path)
    parser.add_argument("--controller-pa0", type=Path)
    parser.add_argument("--simion-executable", type=Path); parser.add_argument("--simion-release", default="SIMION 2020")
    parser.add_argument("--inspection", type=Path); parser.add_argument("--staging-directory", type=Path)
    parser.add_argument("--output-directory", type=Path)
    args = parser.parse_args(arguments)
    if args.action == "inspect":
        if args.provider_run is None or args.reviewed_run is None or args.simion_executable is None:
            parser.error("inspect requires provider/reviewed runs and SIMION executable")
        document = inspect_reviewed_sources(
            args.provider_run, args.reviewed_run, args.simion_executable,
            args.simion_release, args.cache_root, args.controller_pa0,
        )
    else:
        if args.inspection is None:
            parser.error(f"{args.action} requires --inspection")
        if args.action == "receipt-from-hit":
            document = receipt_from_hit(args.cache_root, _load_json(args.inspection, "inspection"))
        elif args.action == "publish-raw":
            document = publish_raw_from_reviewed(
                args.cache_root, _load_json(args.inspection, "inspection")
            )
        elif args.action == "stage-native":
            if args.staging_directory is None: parser.error("stage-native requires --staging-directory")
            document = stage_native_source(args.inspection, args.staging_directory)
        elif args.action == "export-plan":
            if args.staging_directory is None or args.output_directory is None: parser.error("export-plan requires staging and output directories")
            document = export_plan(args.inspection, args.staging_directory, args.output_directory)
        else:
            if args.staging_directory is None or args.output_directory is None: parser.error("publish-prepared requires staging and output directories")
            document = publish_prepared(args.cache_root, args.inspection, args.staging_directory, args.output_directory)
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
