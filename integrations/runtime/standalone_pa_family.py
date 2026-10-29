"""Select manifest-bound standalone SIMION responses for the local field stage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from common.simion.standalone_pa_response_set import (
    select_standalone_pa_records,
)


def parse_response_ids(value: str) -> tuple[int, ...]:
    """Parse a sorted, unique comma-separated response namespace."""

    try:
        response_ids = tuple(int(item) for item in value.split(",") if item)
    except ValueError as exc:
        raise ValueError("response ids must be comma-separated integers") from exc
    if (
        not response_ids
        or any(response_id < 0 for response_id in response_ids)
        or response_ids != tuple(sorted(set(response_ids)))
    ):
        raise ValueError("response ids must be non-negative, sorted, and unique")
    return response_ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--response-ids", required=True)
    parser.add_argument("--receipt-name", default="standalone_response_set.json")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-only", action="store_true",
                        help="Defer PA byte verification to the guarded materializer; still verify the receipt.")
    args = parser.parse_args()

    response_ids = parse_response_ids(args.response_ids)
    if not args.prefix or Path(args.prefix).name != args.prefix or "." in args.prefix:
        raise ValueError("PA prefix must be one direct extension-free filename")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    selected = select_standalone_pa_records(
        args.directory,
        manifest,
        args.receipt_name,
        expected_response_ids=response_ids,
        verify_payload=not args.metadata_only,
    )
    records = [
        {
            "response_id": record.response_id,
            "name": record.name,
            "path": str((args.directory / record.name).resolve()),
            "bytes": record.bytes,
            "sha256": record.sha256,
        }
        for record in selected
    ]
    document = {
        "schema_version": 1,
        "role": "rf_oatof_standalone_pa_response_selection",
        "prefix": args.prefix,
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
