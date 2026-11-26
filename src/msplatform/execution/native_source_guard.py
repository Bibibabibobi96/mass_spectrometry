"""Protect a published native owner product during cross-stage consumption."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
from typing import Any

from msplatform.execution.capacity_protection import capacity_decision_lock
from msplatform.execution.file_lock import shared_process_file_lock
from msplatform.execution.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
from msplatform.execution.terminal_publication import TERMINAL_LOCK_NAME
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import record_path, validate_file_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact


@contextmanager
def guard_native_source(reference: Mapping[str, Any], *, expected_kind: str,
                        expected_artifact_root: Path) -> Iterator[OpenedArtifact]:
    """Verify and hold precisely the declared product files until consumption ends.

    The explicit root belongs to the existing native owner. It is not the new
    ArtifactStore. Keep this context alive through downstream admission and
    every source read/copy. OS handles protect the declared files while the
    controller is alive; native child lifetime needs its own input guards.
    """
    if not isinstance(reference, Mapping) or set(reference) != {"manifest", "product_id"}:
        raise ValueError("native source requires an explicit manifest reference and product_id")
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
        stack.enter_context(shared_process_file_lock(manifest_path.parent / TERMINAL_LOCK_NAME))
        # The existing GC and retirement decisions hold this same root lock.
        # Acquire exact file handles before releasing it so there is no gap
        # between validating a finished owner and excluding file removal.
        with capacity_decision_lock(raw_root):
            artifact = open_artifact(reference, expected_kind=expected_kind)
            owner = resolve_consumed_run_capacity_owner(dict(manifest_record), consumer_artifact_root=raw_root)
            if (Path(owner["artifact_root"]).resolve(strict=True) != raw_root or
                    Path(owner["run_directory"]).resolve(strict=True) != manifest_path.parent):
                raise ValueError("native source owner differs from the expected owner root and run")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            config_record = validate_file_record(manifest["run_config"], "native source run config")
            config_path = record_path(config_record, base_dir=manifest_path.parent)
            files = [(manifest_path, manifest_record), (config_path, config_record)]
            files.extend((artifact.data_locations[name], record) for name, record in artifact.data_records.items())
            guarded: dict[Path, tuple[int, str]] = {}
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
        yield artifact
