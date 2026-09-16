"""Project adapter for publishing and selecting standalone SIMION responses.

SIMION native ``.paN`` members exist only in writable build staging.  This
adapter gives the PowerShell runner a small deterministic CLI for writing the
common response-set receipt and for selecting only manifest-bound standalone
``.pa`` payloads from an immutable cache generation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from common.simion.standalone_pa_response_set import (
    ResponseExport,
    select_standalone_pa_records,
    write_standalone_pa_response_set,
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


def response_exports(prefix: str, response_ids: Sequence[int]) -> tuple[ResponseExport, ...]:
    """Return the one-to-one native-to-standalone naming contract."""

    if not prefix or Path(prefix).name != prefix or "." in prefix:
        raise ValueError("PA prefix must be one direct extension-free filename")
    return tuple(
        ResponseExport(
            response_id=response_id,
            source_name=f"{prefix}.pa{response_id}",
            standalone_name=f"{prefix}.response_{response_id}.pa",
        )
        for response_id in response_ids
    )


def write_mode_map(path: Path, records: Sequence[dict[str, object]]) -> None:
    """Write the strict mode map consumed by the six-face boundary builder."""

    lines = ["standalone_pa_mode_map_v1"]
    for record in records:
        lines.append(f"{int(record['response_id'])}\t{Path(str(record['path'])).resolve()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=("write-receipt", "select"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--response-ids", required=True)
    parser.add_argument("--receipt-name", default="standalone_response_set.json")
    parser.add_argument("--exporter", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode-map", type=Path)
    args = parser.parse_args()

    response_ids = parse_response_ids(args.response_ids)
    exports = response_exports(args.prefix, response_ids)
    receipt = args.directory / args.receipt_name
    if args.action == "write-receipt":
        if args.exporter is None or args.manifest is not None or args.output is not None:
            raise ValueError("write-receipt requires only --exporter")
        write_standalone_pa_response_set(
            args.directory, args.exporter, exports, receipt
        )
        return 0

    if args.manifest is None or args.output is None or args.exporter is not None:
        raise ValueError("select requires --manifest and --output")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    selected = select_standalone_pa_records(
        args.directory,
        manifest,
        args.receipt_name,
        expected_response_ids=response_ids,
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
    if args.mode_map is not None:
        write_mode_map(args.mode_map, records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
