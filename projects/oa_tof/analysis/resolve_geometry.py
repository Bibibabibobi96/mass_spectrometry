"""Generate or verify config/resolved_geometry.json."""

from __future__ import annotations

import argparse

from projects.oa_tof.analysis.geometry_contract import RESOLVED_PATH, resolve_contract, serialized


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = serialized(resolve_contract())
    current = RESOLVED_PATH.read_text(encoding="utf-8") if RESOLVED_PATH.exists() else ""
    if current != expected:
        if args.check:
            raise SystemExit("STALE=config/resolved_geometry.json")
        RESOLVED_PATH.write_text(expected, encoding="utf-8", newline="\n")
        print("UPDATED=config/resolved_geometry.json")
    print("RESOLVED_GEOMETRY=PASS")


if __name__ == "__main__":
    main()
