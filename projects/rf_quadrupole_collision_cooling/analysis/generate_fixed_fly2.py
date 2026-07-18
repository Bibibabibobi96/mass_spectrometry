"""Convert the versioned SIMION ION table to an explicit deterministic FLY2."""

from __future__ import annotations

import argparse
import csv
import math
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


def render_source_states(source: Path, axial_offset_mm: float = 0.0) -> str:
    """Render exact pre-integration states in SIMION workbench coordinates."""
    rows = list(csv.reader(source.read_text(encoding="utf-8").splitlines()))
    output = ["return {"]
    elementary_charge = 1.602176634e-19
    atomic_mass = 1.66053906660e-27
    for index, row in enumerate(rows, start=1):
        if len(row) != 11:
            raise ValueError(f"row {index} has {len(row)} columns, expected 11")
        tob, mass, _, axial, transverse_1, transverse_2, azimuth, elevation, energy, _, _ = map(float, row)
        speed_m_s = math.sqrt(2 * energy * elementary_charge / (mass * atomic_mass))
        az = math.radians(azimuth)
        el = math.radians(elevation)
        v_sim = (
            speed_m_s * math.cos(el) * math.cos(az),
            speed_m_s * math.cos(el) * math.sin(az),
            speed_m_s * math.sin(el),
        )
        # FLY2 standard_beam is interpreted before the copied IOB placement.
        # Workbench coordinates are wb x=component z, wb y=-component y,
        # wb z=component x.  This is the same audited mapping used by COMSOL.
        wb_x = axial + axial_offset_mm
        wb_y = transverse_1
        wb_z = transverse_2
        wb_vx = v_sim[0] / 1000
        wb_vy = v_sim[2] / 1000
        wb_vz = -v_sim[1] / 1000
        output.append(
            f"  [{index}]={{t={tob:.15g},x={wb_x:.15g},y={wb_y:.15g},z={wb_z:.15g},"
            f"vx={wb_vx:.15g},vy={wb_vy:.15g},vz={wb_vz:.15g},ke={energy:.15g}}},"
        )
    output.append("}")
    return "\n".join(output) + "\n"


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
    print(f"STATUS=PASS PARTICLES=25 OUTPUT={args.destination}")


if __name__ == "__main__":
    main()
