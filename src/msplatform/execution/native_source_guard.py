"""Protect a published native owner product during cross-stage consumption."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
from typing import Any

from msplatform.execution.file_lock import shared_process_file_lock
from msplatform.execution.terminal_publication import TERMINAL_LOCK_NAME
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import record_path, validate_file_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact


@contextmanager
def guard_native_source(reference: Mapping[str, Any], *, expected_kind: str,
                        expected_artifact_root: Path, artifact_store=None) -> Iterator[OpenedArtifact]:
    """Verify and hold precisely the declared product files until consumption ends.

    Store products retain a verified claim. Historical sources are opened
    read-only using their frozen manifest and exact file handles, without a
    legacy ledger. Keep this context alive through downstream admission and
    reads; native children must hold their own immutable input guards.
    """
    if not isinstance(reference, Mapping) or set(reference) != {"manifest", "product_id"}:
        raise ValueError("native source requires an explicit manifest reference and product_id")
    from msplatform.execution.owner import current_managed_native_store
    scope = current_managed_native_store()
    store = artifact_store if artifact_store is not None else (scope["store"] if scope else None)
    candidate = record_path(validate_file_record(reference["manifest"], "native source manifest"))
    if store is not None and candidate.is_absolute() and candidate.resolve().is_relative_to(store.root / "assets"):
        resolved = candidate.resolve(strict=True)
        parts = resolved.relative_to(store.root).parts
        if len(parts) < 6 or parts[:2] != ("assets", "native_stage") or resolved.name != "run_manifest.json":
            raise ValueError("native Store source path differs")
        identity = parts[3]
        with ExitStack() as stack:
            asset_root = stack.enter_context(store.claim_verified(identity))
            if asset_root != store.root.joinpath(*parts[:4]) or not resolved.is_relative_to(asset_root):
                raise ValueError("native Store source identity differs")
            stack.enter_context(shared_process_file_lock(resolved.parent / TERMINAL_LOCK_NAME))
            manifest = json.loads(resolved.read_text(encoding="utf-8-sig"))
            product = manifest.get("products", {}).get(reference["product_id"], {})
            origin_reference = product.get("metadata", {}).get("ground_source_reference")
            borrowed = {}
            if origin_reference is not None:
                origin = stack.enter_context(guard_native_source(origin_reference, expected_kind="field_bundle",
                    expected_artifact_root=expected_artifact_root, artifact_store=store))
                borrowed = {Path(origin.data_locations[name]).resolve(): (record["bytes"], str(record["sha256"]).upper())
                            for name, record in origin.data_records.items()}
            artifact = open_artifact(reference, expected_kind=expected_kind)
            config_record = validate_file_record(manifest["run_config"], "native source run config")
            config_path = record_path(config_record, base_dir=resolved.parent)
            files = [(resolved, validate_file_record(reference["manifest"], "native source manifest")),
                     (config_path, config_record)]
            files.extend((artifact.data_locations[name], record) for name, record in artifact.data_records.items())
            guarded = {}
            for path, record in files:
                actual = Path(path).resolve(strict=True)
                identity_record = (record["bytes"], str(record["sha256"]).upper())
                if not actual.is_relative_to(asset_root):
                    if borrowed.get(actual) != identity_record:
                        raise ValueError("native Store product contains an unprotected external payload")
                    continue  # Exact origin guard already holds this file.
                if actual in guarded:
                    if guarded[actual] != identity_record:
                        raise ValueError("native source contains conflicting file identities")
                    continue
                stack.enter_context(guarded_file_identity(actual, expected_bytes=identity_record[0],
                                                           expected_sha256=identity_record[1]))
                guarded[actual] = identity_record
            yield artifact
        return
    raw_root = Path(expected_artifact_root)
    if not raw_root.is_absolute():
        raise ValueError("native owner artifact root must be absolute")
    raw_root = raw_root.resolve(strict=True)
    manifest_record = validate_file_record(reference["manifest"], "native source manifest")
    manifest_path = record_path(manifest_record)
    if not manifest_path.is_absolute() or manifest_path.name != "run_manifest.json":
        raise ValueError("native source requires an absolute owner run manifest")
    manifest_path = manifest_path.resolve(strict=True)
    if not manifest_path.is_relative_to(raw_root):
        raise ValueError("native source manifest is outside the expected owner root")
    with ExitStack() as stack:
        # Freeze the manifest before resolving any paths. A concurrent legacy
        # deletion either loses this OS handle race or leaves a missing member;
        # neither case requires invoking the legacy ledger or creating a lock.
        stack.enter_context(guarded_file_identity(manifest_path, expected_bytes=manifest_record["bytes"],
                                                   expected_sha256=manifest_record["sha256"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        config_record = validate_file_record(manifest.get("run_config"), "native source run config")
        product = manifest.get("products", {}).get(reference["product_id"])
        if not isinstance(product, dict) or not isinstance(product.get("data"), dict):
            raise ValueError("native source product records are unavailable")
        files = [(record_path(config_record, base_dir=manifest_path.parent), config_record)]
        files.extend((record_path(validate_file_record(record, "native source data"), base_dir=manifest_path.parent), record)
                     for record in product["data"].values())
        guarded: dict[Path, tuple[int, str]] = {manifest_path: (manifest_record["bytes"], str(manifest_record["sha256"]).upper())}
        for path, record in files:
            actual = Path(path).resolve(strict=True)
            if not actual.is_relative_to(raw_root):
                raise ValueError("native source data is outside the expected owner root")
            identity = (record["bytes"], str(record["sha256"]).upper())
            if actual in guarded:
                if guarded[actual] != identity:
                    raise ValueError("native source contains conflicting file identities")
                continue
            stack.enter_context(guarded_file_identity(actual, expected_bytes=identity[0], expected_sha256=identity[1]))
            guarded[actual] = identity
        # Validate publication and manifest/product membership only after every
        # actual file is held; this opens no legacy owner or mutable ledger.
        artifact = open_artifact(reference, expected_kind=expected_kind)
        yield artifact
