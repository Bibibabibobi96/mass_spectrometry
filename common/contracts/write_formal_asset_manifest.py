"""Write the single manifest for a project's current formal release."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from common.contracts.artifact_naming import validate_run_id
    from common.contracts.file_identity import file_sha256
except ModuleNotFoundError:
    from artifact_naming import validate_run_id
    from file_identity import file_sha256


def record(path: Path, relative_to: Path) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(relative_to.resolve()).as_posix()
    if not resolved.is_file():
        raise ValueError(f"not a file: {resolved}")
    return {"path": relative, "bytes": resolved.stat().st_size, "sha256": file_sha256(resolved)}


def parse_asset(value: str) -> tuple[str, str]:
    role, separator, path = value.partition("=")
    if not separator or not role or not path:
        raise argparse.ArgumentTypeError("asset must be ROLE=FORMAL_RELATIVE_PATH")
    return role, path


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
    assets: dict[str, dict[str, object]] = {}
    naming_exceptions = dict(args.asset_naming_exception)
    for role, relative_path in args.asset:
        if role in assets:
            raise ValueError(f"duplicate asset role: {role}")
        assets[role] = record(formal_root / relative_path, formal_root)
        if role in naming_exceptions:
            assets[role]["naming_exception"] = naming_exceptions[role]
    unknown_exceptions = set(naming_exceptions) - set(assets)
    if unknown_exceptions:
        raise ValueError(f"naming exceptions have no matching asset: {sorted(unknown_exceptions)}")
    if not assets:
        raise ValueError("at least one --asset is required")

    manifest = {
        "schema_version": 1,
        "role": "formal_asset_manifest",
        "project": args.project,
        "release_id": args.source_run_id,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_run": {
            "run_id": args.source_run_id,
            "path": source_root.relative_to(project_root).as_posix(),
            "run_config": record(source_root / "run_config.json", project_root),
            "summary": record(source_root / "summary.json", project_root),
            "run_manifest": record(source_root / "run_manifest.json", project_root),
        },
        "validation_contract": record(args.validation_contract, repository_root),
        "assets": dict(sorted(assets.items())),
    }
    destination = formal_root / "asset_manifest.json"
    destination.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"FORMAL_ASSET_MANIFEST=PASS PATH={destination} ASSETS={len(assets)}")


if __name__ == "__main__":
    main()
