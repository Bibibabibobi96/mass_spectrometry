"""Compatibility wrapper for the common multipole SIMION source exporter."""

from __future__ import annotations

import argparse
from pathlib import Path

from common.multipole.simion_particle_source import render_ion11_fly2, render_ion11_source_states

def render(source: Path, axial_offset_mm: float = 0.0) -> str:
    return render_ion11_fly2(source, axial_offset_mm)


def render_source_states(source: Path, axial_offset_mm: float = 0.0) -> str:
    """Render exact pre-integration states in SIMION workbench coordinates."""
    return render_ion11_source_states(source, axial_offset_mm)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--axial-offset-mm", type=float, default=0.0)
    parser.add_argument("--source-states-lua", type=Path)
    args = parser.parse_args()
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(render(args.source, args.axial_offset_mm), encoding="utf-8", newline="\n")
    if args.source_states_lua:
        args.source_states_lua.write_text(
            render_source_states(args.source, args.axial_offset_mm), encoding="utf-8", newline="\n"
        )
    particles = len(args.source.read_text(encoding="utf-8").splitlines())
    print(f"STATUS=PASS PARTICLES={particles} OUTPUT={args.destination}")


if __name__ == "__main__":
    main()
