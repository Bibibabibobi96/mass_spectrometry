"""Freeze the official one-instance IOB seed with its required placeholder."""
from __future__ import annotations

from pathlib import Path

from common.contracts.frozen_inputs import freeze_file
from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record


def freeze_workbench_seed(run: Path, repo: Path) -> dict:
    """Prepare the same small pair once; never copy a scientific PA family."""
    source_root = Path(repo)/"common/simion/assets/iob_instance_seeds"
    destination = Path(run)/"simion/iob_seed"
    destination.mkdir(parents=True, exist_ok=True)
    identities = {}
    for name, key in (("1_instance_seed.iob", "seed"), ("iob_seed_placeholder_01.pa0", "placeholder")):
        source, frozen = source_root/name, destination/name
        if frozen.exists():
            original = file_record(source)
            verify_record("official frozen IOB seed", dict(original, path=str(frozen)))
            target = dict(original, path=str(frozen.resolve()))
        else:
            record = freeze_file(source, frozen)
            original = dict(path=record["source_path"],
                **{key: record[key] for key in ("exists", "bytes", "sha256")})
            target = dict(original, path=record["path"])
        identities[key] = dict(source=original, frozen=target,
            frozen_path_utf16_units=len(str(frozen).encode("utf-16-le"))//2)
    return identities
