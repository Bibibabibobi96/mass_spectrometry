"""Prune rebuildable binary baggage from an artifact-v1 migration snapshot."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


MODEL_BINARY_SUFFIXES = {".mph", ".iob"}
CAD_BINARY_SUFFIXES = {".sldasm", ".sldprt", ".step", ".stp"}


def is_simion_array(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix == ".pa" or suffix == ".pa#" or (
        suffix.startswith(".pa") and suffix[3:].isdigit()
    )


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    snapshot = args.snapshot.resolve()
    archive_manifest_path = snapshot / "archive_manifest.json"
    legacy = snapshot / "legacy-layout"
    if snapshot.parent.name != "archive" or not archive_manifest_path.is_file():
        raise SystemExit("snapshot must be one named archive/<archive_id> directory")
    archive_manifest = json.loads(archive_manifest_path.read_text(encoding="utf-8"))
    if archive_manifest.get("reason") != "migration-snapshot" or not legacy.is_dir():
        raise SystemExit("only an artifact-v1 migration-snapshot can be pruned")

    records: list[dict[str, object]] = []
    for path in legacy.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        suffix = path.suffix.lower()
        rebuildable = (
            suffix in MODEL_BINARY_SUFFIXES
            or suffix in CAD_BINARY_SUFFIXES
            or is_simion_array(path)
            or (suffix == ".7z" and "models" in path.relative_to(legacy).parts)
        )
        if rebuildable:
            records.append(
                {
                    "path": path.relative_to(snapshot).as_posix(),
                    "bytes": path.stat().st_size,
                    "reason": "rebuildable_binary",
                }
            )
    for directory_name in ("scratch", "staging"):
        area = legacy / directory_name
        if not area.is_dir():
            continue
        for path in area.rglob("*"):
            if path.is_file() and not path.is_symlink():
                records.append(
                    {
                        "path": path.relative_to(snapshot).as_posix(),
                        "bytes": path.stat().st_size,
                        "reason": "non_authoritative_workspace",
                    }
                )

    total_bytes = sum(int(record["bytes"]) for record in records)
    print(f"PRUNE_CANDIDATES={len(records)} BYTES={total_bytes}")
    if not args.execute:
        print("DRY_RUN=1")
        return

    for record in records:
        target = (snapshot / str(record["path"])).resolve()
        target.relative_to(legacy.resolve())
        target.unlink()
    for directory_name in ("scratch", "staging"):
        area = legacy / directory_name
        if area.is_dir():
            shutil.rmtree(area)
    for area in (legacy / "models", legacy / "cad"):
        if area.is_dir():
            for directory in sorted(
                (path for path in area.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass

    prior_manifest_path = snapshot / "pruning_manifest.json"
    prior = (
        json.loads(prior_manifest_path.read_text(encoding="utf-8"))
        if prior_manifest_path.is_file()
        else {}
    )
    all_records = list(prior.get("removed", [])) + records
    all_removed_bytes = sum(int(record["bytes"]) for record in all_records)
    pruning = {
        "schema_version": 1,
        "role": "migration_snapshot_pruning_manifest",
        "archive_id": archive_manifest["archive_id"],
        "pruned_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": (
            "Retain numerical results, figures, logs, configurations, and reports; "
            "remove rebuildable model/CAD binaries and non-authoritative scratch/staging."
        ),
        "removed_file_count": len(all_records),
        "removed_bytes": all_removed_bytes,
        "removed": all_records,
    }
    atomic_json(snapshot / "pruning_manifest.json", pruning)
    archive_manifest["pruning"] = {
        key: pruning[key]
        for key in (
            "pruned_at_utc",
            "policy",
            "removed_file_count",
            "removed_bytes",
        )
    }
    archive_manifest["pruning"]["manifest"] = "pruning_manifest.json"
    atomic_json(archive_manifest_path, archive_manifest)
    print(
        f"PRUNE_STATUS=PASS FILES={len(all_records)} BYTES={all_removed_bytes} "
        f"THIS_PASS_FILES={len(records)} THIS_PASS_BYTES={total_bytes}"
    )


if __name__ == "__main__":
    main()
