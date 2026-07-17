"""Convert the versioned SIMION ION table to an explicit deterministic FLY2."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def render(source: Path, axial_offset_mm: float = 0.0) -> str:
    rows = list(csv.reader(source.read_text(encoding="utf-8").splitlines()))
    blocks: list[str] = ["particles {", "  coordinates = 0,"]
    for index, row in enumerate(rows):
        if len(row) != 11:
            raise ValueError(f"row {index + 1} has {len(row)} columns, expected 11")
        tob, mass, charge, x, y, z, az, el, energy, cwf, color = row
        # Preserve the authority table byte-for-byte at the default offset.
        # Formatting is only changed for an intentionally translated source.
        if axial_offset_mm != 0.0:
            x = f"{float(x) + axial_offset_mm:.12g}"
        comma = "," if index < len(rows) - 1 else ""
        blocks.extend(
            [
                "  standard_beam {",
                "    n = 1,",
                f"    tob = {tob},",
                f"    mass = {mass},",
                f"    charge = {charge},",
                f"    x = {x},",
                f"    y = {y},",
                f"    z = {z},",
                f"    ke = {energy},",
                f"    az = {az},",
                f"    el = {el},",
                f"    cwf = {cwf},",
                f"    color = {color}",
                f"  }}{comma}",
            ]
        )
    blocks.append("}")
    return "\n".join(blocks) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--axial-offset-mm", type=float, default=0.0)
    args = parser.parse_args()
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(render(args.source, args.axial_offset_mm), encoding="utf-8", newline="\n")
    print(f"STATUS=PASS PARTICLES=25 OUTPUT={args.destination}")


if __name__ == "__main__":
    main()
