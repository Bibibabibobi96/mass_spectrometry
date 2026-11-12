"""Freeze the official one-instance IOB seed with its required placeholder."""
from __future__ import annotations

from pathlib import Path

from msplatform.execution.retention import classify_file
from msplatform.execution.inputs import freeze_file
from msplatform.execution.retention import verify_record
from msplatform.execution.retention import file_record
from msplatform.backends.simion.resources import structural_seed_path


def freeze_workbench_seed(run: Path, *, placeholder_path: Path, seed_path: Path | None = None) -> dict:
    """Prepare the same small pair once; never copy a scientific PA family."""
    seed_source = structural_seed_path(1) if seed_path is None else Path(seed_path)
    placeholder_source = Path(placeholder_path)
    destination = Path(run)/"simion/iob_seed"
    destination.mkdir(parents=True, exist_ok=True)
    identities = {}
    for name, key in (("1_instance_seed.iob", "seed"), ("iob_seed_placeholder_01.pa0", "placeholder")):
        source = seed_source if key == "seed" else placeholder_source
        frozen = destination/name
        if frozen.exists():
            original = file_record(source)
            verify_record("official frozen IOB seed", dict(original, path=str(frozen)))
            target = dict(original, path=str(frozen.resolve()))
        else:
            record = freeze_file(source, frozen, retention_classifier=classify_file)
            original = dict(path=record["source_path"],
                **{key: record[key] for key in ("exists", "bytes", "sha256")})
            target = dict(original, path=record["path"])
        identities[key] = dict(source=original, frozen=target,
            frozen_path_utf16_units=len(str(frozen).encode("utf-16-le"))//2)
    return identities
