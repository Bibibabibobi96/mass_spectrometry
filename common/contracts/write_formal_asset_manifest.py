"""Write the single manifest for a project's current formal release."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

try:
    from common.contracts.artifact_naming import validate_run_id
    from common.contracts.file_identity import file_sha256
except ModuleNotFoundError:
    from artifact_naming import validate_run_id
    from file_identity import file_sha256


def record(
    path: Path, relative_to: Path, *, key: str = "path"
) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(relative_to.resolve()).as_posix()
    if not resolved.is_file():
        raise ValueError(f"not a file: {resolved}")
    return {
        key: relative,
        "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def parse_asset(value: str) -> tuple[str, str]:
    role, separator, path = value.partition("=")
    if not separator or not role or not path:
        raise argparse.ArgumentTypeError("asset must be ROLE=FORMAL_RELATIVE_PATH")
    return role, path


def write_formal_asset_manifest(
    *,
    destination: Path,
    formal_root: Path,
    project: str,
    source_run_id: str,
    source_run_root: Path,
    validation_contract_path: str,
    validation_contract_bytes: bytes,
    assets: Mapping[str, Path],
    naming_exceptions: Mapping[str, str] | None = None,
    recorded_at_utc: str | None = None,
) -> dict[str, object]:
    """Write one Formal manifest to an explicit release or staging root."""
    validate_run_id(source_run_id)
    if not project:
        raise ValueError("project identity must be nonempty")
    if not validation_contract_path or Path(validation_contract_path).is_absolute():
        raise ValueError("validation contract path must be repository-relative")
    if ".." in Path(validation_contract_path).parts:
        raise ValueError("validation contract path escapes the repository")

    formal_root = Path(formal_root).resolve(strict=True)
    destination = Path(destination).resolve()
    destination.relative_to(formal_root)
    source_run_root = Path(source_run_root).resolve(strict=True)
    if source_run_root.name != source_run_id or source_run_root.parent.name != "runs":
        raise ValueError("source run root differs from source_run_id or runs layout")
    artifact_project_root = source_run_root.parent.parent.resolve(strict=True)

    exceptions = dict(naming_exceptions or {})
    unknown_exceptions = set(exceptions) - set(assets)
    if unknown_exceptions:
        raise ValueError(
            f"naming exceptions have no matching asset: {sorted(unknown_exceptions)}"
        )
    if not assets:
        raise ValueError("at least one Formal asset is required")

    asset_records: dict[str, dict[str, object]] = {}
    seen_paths: set[str] = set()
    for role, path in assets.items():
        if not role or role in asset_records:
            raise ValueError(f"invalid or duplicate asset role: {role!r}")
        item = record(Path(path), formal_root)
        relative = str(item["path"])
        if relative in seen_paths:
            raise ValueError(f"Formal asset path has multiple roles: {relative}")
        seen_paths.add(relative)
        if role in exceptions:
            item["naming_exception"] = exceptions[role]
        asset_records[role] = item

    manifest: dict[str, object] = {
        "schema_version": 1,
        "role": "formal_asset_manifest",
        "project": project,
        "release_id": source_run_id,
        "recorded_at_utc": recorded_at_utc
        or datetime.now(timezone.utc).isoformat(),
        "source_run": {
            "run_id": source_run_id,
            "path": source_run_root.relative_to(artifact_project_root).as_posix(),
            "run_config": record(
                source_run_root / "run_config.json", artifact_project_root
            ),
            "summary": record(
                source_run_root / "summary.json", artifact_project_root
            ),
            "run_manifest": record(
                source_run_root / "run_manifest.json", artifact_project_root
            ),
        },
        "validation_contract": {
            "path": validation_contract_path,
            "bytes": len(validation_contract_bytes),
            "sha256": hashlib.sha256(validation_contract_bytes)
            .hexdigest()
            .upper(),
        },
        "assets": dict(sorted(asset_records.items())),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--validation-contract", required=True, type=Path)
    parser.add_argument("--asset", action="append", type=parse_asset, default=[])
    parser.add_argument("--asset-naming-exception", action="append", type=parse_asset, default=[])
    args = parser.parse_args()

    validate_run_id(args.source_run_id)
    project_root = args.project_root.resolve(strict=True)
    repository_root = args.repository_root.resolve(strict=True)
    formal_root = (project_root / "formal").resolve(strict=True)
    source_root = (project_root / "runs" / args.source_run_id).resolve(strict=True)
    source_root.relative_to(project_root)
    asset_paths: dict[str, Path] = {}
    naming_exceptions = dict(args.asset_naming_exception)
    for role, relative_path in args.asset:
        if role in asset_paths:
            raise ValueError(f"duplicate asset role: {role}")
        asset_paths[role] = formal_root / relative_path
    destination = formal_root / "asset_manifest.json"
    validation_path = args.validation_contract.resolve(strict=True)
    write_formal_asset_manifest(
        destination=destination,
        formal_root=formal_root,
        project=args.project,
        source_run_id=args.source_run_id,
        source_run_root=source_root,
        validation_contract_path=validation_path.relative_to(repository_root).as_posix(),
        validation_contract_bytes=validation_path.read_bytes(),
        assets=asset_paths,
        naming_exceptions=naming_exceptions,
    )
    print(
        f"FORMAL_ASSET_MANIFEST=PASS PATH={destination} "
        f"ASSETS={len(asset_paths)}"
    )


if __name__ == "__main__":
    main()
