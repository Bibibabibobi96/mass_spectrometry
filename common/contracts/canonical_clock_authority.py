"""Validate the workspace-wide canonical instrument-clock authority contract.

Finite legacy CLI/alias; active validation body lives in msplatform.execution.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from msplatform.execution.clock_authority import SCHEMA_PATH as SCHEMA_PATH, validate_clock_authority


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    args = parser.parse_args()
    report = validate_clock_authority(args.contract, args.repository_root)
    print(f"CANONICAL_CLOCK_AUTHORITY={report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
