"""Fail closed when a resolved design's embedded logical hash is stale."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common.multipole.compile_design_request import resolved_design_sha256


def verify(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    embedded = document.get("resolved_sha256")
    if not isinstance(embedded, str) or re.fullmatch(r"[0-9A-Fa-f]{64}", embedded) is None:
        raise ValueError("resolved_sha256 must contain exactly 64 hexadecimal characters")
    recomputed = resolved_design_sha256(document)
    if embedded.upper() != recomputed:
        raise ValueError("resolved_sha256 differs from the recomputed logical design hash")
    return recomputed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("resolved_design", type=Path)
    args = parser.parse_args()
    print(f"RESOLVED_DESIGN_IDENTITY=PASS SHA256={verify(args.resolved_design)}")


if __name__ == "__main__":
    main()
