"""Render the legacy mass-scan ION11 table for the project SIMION workbench."""

from __future__ import annotations

import argparse
from pathlib import Path

from common.multipole.simion_particle_source import (
    render_ion11_fly2,
    render_ion11_source_states,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ion-table", required=True, type=Path)
    parser.add_argument("--fly2", required=True, type=Path)
    parser.add_argument("--source-states-lua", required=True, type=Path)
    args = parser.parse_args()
    args.fly2.parent.mkdir(parents=True, exist_ok=True)
    args.source_states_lua.parent.mkdir(parents=True, exist_ok=True)
    args.fly2.write_text(render_ion11_fly2(args.ion_table), encoding="ascii")
    args.source_states_lua.write_text(
        render_ion11_source_states(args.ion_table), encoding="ascii"
    )
    print("RFQUAD_SIMION_SOURCE=PASS FORMAT=ion11")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
