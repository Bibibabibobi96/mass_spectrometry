"""Owner admission for two reproducible fine-field performance caches.

No CLI and no deletion: approval delegates the exact sealed inventory to the
public capacity retirement executor. The coarse frontend remains an input.
"""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
import shutil
from typing import Any, Mapping

from common.contracts import capacity_ledger, capacity_protection
from common.contracts.file_identity import file_sha256, canonical_json_sha256
from common.contracts.recorded_file_removal import write_json_atomic
from common.simion.cache_generation import generation_sha256, payload_sha256, generation_input

OWNER = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
ROLES = {"simion_single_flight_accelerator_main", "simion_single_flight_upstream_bridge"}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _record(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 2 * 1024**2:
        raise ValueError("Reconstruction evidence must be a regular small file")
    return dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=file_sha256(path))


def _inventory(target: Path) -> list[dict]:
    records = []
    for path in sorted(target.rglob("*")):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 1024:
            raise ValueError("Cache inventory contains a link or reparse point")
        if path.is_file():
            records.append(dict(path=path.relative_to(target).as_posix(), bytes=path.stat().st_size))
    return records


def _generation(key: Path) -> tuple[dict, Path, dict]:
    pointer = _read(key / "current_generation.json")
    relative = "generations/" + pointer["generation_sha256"]
    if pointer["cache_key"] != key.name or pointer["generation_relative_path"] != relative:
        raise ValueError("Cache pointer identity differs")
    directory = key / relative
    if list((key / "generations").iterdir()) != [directory]:
        raise ValueError("Owner retirement requires one complete current generation")
    manifest = _read(directory / "cache_manifest.json")
    if (manifest["cache_key"] != key.name or manifest["generation_sha256"] != pointer["generation_sha256"]
            or pointer["role"] != manifest["role"]
            or json.loads(manifest["cache_key_input"]) != manifest["identity"]
            or hashlib.sha256(manifest["cache_key_input"].encode()).hexdigest() != key.name.lower()
            or generation_input(key.name, manifest["payload_sha256"], manifest["provider_run_id"]) != manifest["generation_input"]
            or generation_sha256(manifest["generation_input"]) != manifest["generation_sha256"]
            or payload_sha256(manifest["files"]) != manifest["payload_sha256"]
            or pointer["payload_sha256"] != manifest["payload_sha256"]):
        raise ValueError("Cache generation digest differs")
    expected = {r["name"]: r["bytes"] for r in manifest["files"]}
    actual = {p.name: p.stat().st_size for p in directory.iterdir() if p.is_file() and p.name != "cache_manifest.json"}
    if expected != actual or len(expected) != len(manifest["files"]):
        raise ValueError("Cache generation file inventory differs")
    return pointer, directory, manifest


def plan_cache_retirement(artifact_root: Path, cache_path: Path,
                          builder_sources: Mapping[str, Path], coarse_cache_path: Path) -> dict[str, Any]:
    """Return a no-write plan; missing exact producer inputs fail closed."""
    root, target = artifact_root.resolve(), cache_path.resolve()
    parts = target.relative_to(root).parts
    if len(parts) != 5 or parts[:3] != ("projects", OWNER, "cache") or parts[3] not in ROLES:
        raise ValueError("Only the two registered fine-field cache roles may retire")
    inventory = _inventory(target)
    pointer, directory, manifest = _generation(target)
    if manifest["role"] != parts[3] + "_pa_cache" or manifest["identity"]["role"] != manifest["role"]:
        raise ValueError("Fine cache role differs")
    identity_inputs = manifest["identity"]["inputs"]
    builder_keys = {k for k, v in identity_inputs.items() if k.endswith("_sha256") and v is not None and k != "fine_gem_sha256"}
    if set(builder_sources) != builder_keys:
        raise ValueError("Every exact basis/initializer/refiner source is required")
    evidence = {k: _record(Path(v)) for k, v in builder_sources.items()}
    for key, record in evidence.items():
        if record["sha256"].lower() != identity_inputs[key].lower():
            raise ValueError("Reconstruction producer identity differs: " + key)
    gem = directory / ("accelerator_main.gem" if parts[3].endswith("accelerator_main") else "upstream_bridge.gem")
    if _record(gem)["sha256"].lower() != identity_inputs["fine_gem_sha256"].lower():
        raise ValueError("Frozen fine GEM differs from source identity")
    coarse = coarse_cache_path.resolve()
    if coarse.parent != target.parent.parent / "simion_single_flight_frontend" or coarse.name != identity_inputs["coarse_frontend_cache_key"]:
        raise ValueError("The retained coarse frontend source differs")
    _, coarse_directory, coarse_manifest = _generation(coarse)
    evidence["coarse_manifest"] = _record(coarse_directory / "cache_manifest.json")
    if coarse_manifest["role"] != "simion_single_flight_frontend_pa_cache":
        raise ValueError("Retained coarse source role differs")
    # PA_ is the native working array; PA+ is a small, required mode map.
    small = [_record(p) for p in sorted(target.rglob("*")) if p.is_file()
             and re.search(r"\.pa(?:\d+|#|_|-surf)?$", p.name, re.IGNORECASE) is None]
    files = []
    files.append(dict(path="current_generation.json", **{k: _record(target / "current_generation.json")[k] for k in ("bytes", "sha256")}))
    files.append(dict(path=(directory.relative_to(target) / "cache_manifest.json").as_posix(), **{k: _record(directory / "cache_manifest.json")[k] for k in ("bytes", "sha256")}))
    for record in manifest["files"]:
        files.append(dict(path=(directory.relative_to(target) / record["name"]).as_posix(), bytes=record["bytes"], sha256=record["sha256"]))
    if {r["path"]: r["bytes"] for r in files} != {r["path"]: r["bytes"] for r in inventory}:
        raise ValueError("Owner plan must cover the whole cache without unlisted files")
    ledger = capacity_ledger.load_capacity_ledger(root)
    entry = next((r for r in ledger["objects"] if r["path"] == target.relative_to(root).as_posix()), None) if ledger else None
    if (not entry or entry.get("class") != "published_cache" or entry.get("status") != "ready"
            or entry.get("pin") is not False or entry.get("manager") is not None or entry.get("owner") != OWNER
            or entry["identity"].lower() != pointer["generation_sha256"].lower() or entry["bytes"] != sum(r["bytes"] for r in files)):
        raise ValueError("Cache is not the exact owner-managed unpinned publication")
    leases = capacity_protection.load_capacity_protection_leases(root)
    if capacity_protection.path_is_protected(target, leases["protected_paths"]) or target.name.lower() in leases["protected_cache_keys"] or entry.get("consumers"):
        raise ValueError("Cache has current consumers or protection")
    return dict(schema_version=1, role="rf_oatof_fine_cache_retirement_plan", artifact_root=str(root), cache_path=str(target),
                generation_sha256=pointer["generation_sha256"], bytes=entry["bytes"], files=files,
                small_inputs=small, builder_sources=evidence, coarse_cache_path=str(coarse), deletion_performed=False)


def approve_cache_retirement(plan: dict, evidence_directory: Path) -> dict:
    """Freeze reconstruction evidence, then approve; public maintenance deletes."""
    root, target = Path(plan["artifact_root"]), Path(plan["cache_path"])
    evidence = evidence_directory.resolve()
    cache_root = root / "projects" / OWNER / "cache"
    if evidence == cache_root or cache_root in evidence.parents:
        raise ValueError("Reconstruction evidence requires a fresh directory outside the cache")
    builder = {k: Path(v["path"]) for k, v in plan["builder_sources"].items() if k != "coarse_manifest"}
    # The public approval invokes this callback while holding its decision lock.
    # Do not take the non-reentrant kernel lock a second time here.
    def commit(disposition: dict) -> None:
        if evidence.exists():
            receipt = _read(evidence / "owner_retirement_approval.json")
            if receipt["plan"] != plan:
                raise ValueError("Prior approval names another plan")
            if _inventory(target) != [{"path": r["path"], "bytes": r["bytes"]} for r in sorted(plan["files"], key=lambda r:r["path"])]:
                raise ValueError("Approved cache inventory changed")
            for record in receipt["reconstruction_inputs"]:
                if _record(Path(record["path"])) != record:
                    raise ValueError("Archived reconstruction input changed")
            return
        current = plan_cache_retirement(root, target, builder, Path(plan["coarse_cache_path"]))
        if current != plan:
            raise ValueError("Cache or reconstruction evidence changed after planning")
        evidence.mkdir(parents=True)
        archived = []
        for index, record in enumerate([*plan["small_inputs"], *plan["builder_sources"].values()]):
            source = Path(record["path"])
            destination = evidence / (str(index) + "_" + source.name)
            shutil.copyfile(source, destination)
            copied = _record(destination)
            if any(copied[k] != record[k] for k in ("bytes", "sha256")):
                raise ValueError("Reconstruction evidence copy differs")
            archived.append(copied)
        receipt = evidence / "owner_retirement_approval.json"
        write_json_atomic(receipt, dict(schema_version=1, role="rf_oatof_cache_owner_retirement_approval",
            status="approved_pending_public_maintenance", plan=plan, reconstruction_inputs=archived,
            disposition=disposition, deletion_performed=False))
    return capacity_ledger.approve_published_cache_retirement(root, path=target,
        expected_identity=plan["generation_sha256"], expected_bytes=plan["bytes"], disposition_id=canonical_json_sha256(plan),
        manifest_sha256=canonical_json_sha256(plan), files=plan["files"], expected_project_owner=OWNER,
        commit_owner_retirement=commit)
