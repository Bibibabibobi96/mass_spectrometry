"""Publish a frozen Paper 1 stage-evidence package from a JSON payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_stage_evidence import (
    StageEvidence,
    publish_stage_evidence,
)


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"stage evidence JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("stage evidence JSON must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    payload = _object(args.evidence)
    required = {
        "stage_id",
        "conclusion",
        "claim_limit",
        "inputs",
        "metrics",
        "claims_supported",
        "claims_prohibited",
        "failures",
    }
    if set(payload) != required:
        raise ValueError("stage evidence JSON fields differ from the stage contract")
    published = publish_stage_evidence(args.destination, StageEvidence(**payload))
    print(f"PAPER1_STAGE_EVIDENCE=PASS DESTINATION={published}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
