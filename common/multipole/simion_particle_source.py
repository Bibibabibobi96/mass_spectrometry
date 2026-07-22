"""Convert the solver-neutral multipole particle table to SIMION FLY2 and Lua states."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from common.simion.particle_source import render_source_states, render_standard_beams

AMU_KG = 1.66053906660e-27
E_CHARGE_C = 1.602176634e-19


def _ion11_rows(source: Path) -> list[list[str]]:
    rows = list(csv.reader(source.read_text(encoding="utf-8-sig").splitlines()))
    for index, row in enumerate(rows, start=1):
        if len(row) != 11:
            raise ValueError(f"row {index} has {len(row)} columns, expected 11")
    return rows


def render_ion11_fly2(source: Path, axial_offset_mm: float = 0.0) -> str:
    """Render the established eleven-column SIMION source without numeric drift."""
    rows = _ion11_rows(source)
    beams = []
    for row in rows:
        tob, mass, charge, x, y, z, az, el, energy, cwf, color = row
        if axial_offset_mm != 0.0:
            x = f"{float(x) + axial_offset_mm:.12g}"
        beams.append({"tob":tob,"mass":mass,"charge":charge,"x":x,"y":y,"z":z,
                      "ke":energy,"az":az,"el":el,"cwf":cwf,"color":color})
    return render_standard_beams(beams)


def render_ion11_source_states(source: Path, axial_offset_mm: float = 0.0) -> str:
    """Render exact pre-integration states in the established SIMION workbench frame."""
    states = []
    for index, row in enumerate(_ion11_rows(source), start=1):
        tob, mass, _, axial, transverse_1, transverse_2, azimuth, elevation, energy, _, _ = map(float, row)
        speed = math.sqrt(2 * energy * E_CHARGE_C / (mass * AMU_KG))
        az, el = math.radians(azimuth), math.radians(elevation)
        v_sim = (
            speed * math.cos(el) * math.cos(az),
            speed * math.cos(el) * math.sin(az),
            speed * math.sin(el),
        )
        states.append({"particle_id":index,"t":tob,"x":axial+axial_offset_mm,"y":transverse_1,
                       "z":transverse_2,"vx":v_sim[0]/1000,"vy":v_sim[2]/1000,
                       "vz":-v_sim[1]/1000,"ke":energy})
    return render_source_states(states)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--particles", type=Path, help="canonical multipole particle CSV")
    source.add_argument("--ion-table", type=Path, help="established eleven-column SIMION ION table")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--fly2", required=True, type=Path)
    parser.add_argument("--source-states-lua", required=True, type=Path)
    parser.add_argument("--axial-offset-mm", type=float, default=0.0)
    args = parser.parse_args()
    args.fly2.parent.mkdir(parents=True, exist_ok=True)
    args.source_states_lua.parent.mkdir(parents=True, exist_ok=True)
    if args.ion_table:
        rows = _ion11_rows(args.ion_table)
        args.fly2.write_text(render_ion11_fly2(args.ion_table, args.axial_offset_mm), encoding="ascii")
        args.source_states_lua.write_text(
            render_ion11_source_states(args.ion_table, args.axial_offset_mm), encoding="ascii"
        )
        print(f"MULTIPOLE_SIMION_SOURCE=PASS FORMAT=ion11 PARTICLES={len(rows)}")
        return 0
    if args.baseline is None or args.geometry is None:
        parser.error("--baseline and --geometry are required with --particles")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
    geometry = json.loads(args.geometry.read_text(encoding="utf-8-sig"))
    origin = geometry["grounded_enclosure_mm"]["shield_outer_radius"]
    z_shift = -geometry["grounded_enclosure_mm"]["vacuum_z_min"]
    mass = float(baseline["particle_source"]["mass_amu"])
    charge = int(baseline["particle_source"]["charge_state"])
    rows = list(csv.DictReader(args.particles.open(encoding="utf-8-sig")))
    fly = ["particles {", "  coordinates = 0,"]
    states = ["return {"]
    for row in rows:
        vx, vy, vz = (float(row[key]) for key in ("vx_m_s", "vy_m_s", "vz_m_s"))
        speed2 = vx * vx + vy * vy + vz * vz
        ke = 0.5 * mass * AMU_KG * speed2 / E_CHARGE_C
        pa_x = origin + float(row["x_mm"])
        pa_y = origin + float(row["y_mm"])
        pa_z = z_shift + float(row["z_mm"])
        # Verified quad_monolithic IOB basis: PA x -> WB z,
        # PA y -> -WB y, PA z -> WB x.
        x, y, z = pa_z, -pa_y, pa_x
        wb_vx, wb_vy, wb_vz = vz, -vy, vx
        tob = float(row["birth_time_s"]) * 1e6
        fly.extend([
            "  standard_beam {",
            f"    n=1, tob={tob:.12g}, mass={mass:.12g}, charge={charge}, ke={ke:.12g},",
            f"    position=vector({x:.12g},{y:.12g},{z:.12g}),",
            f"    direction=vector({wb_vx:.12g},{wb_vy:.12g},{wb_vz:.12g}), cwf=1, color=3",
            "  },",
        ])
        states.append(
            f"  [{int(row['particle_id'])}]={{t={tob:.12g},x={x:.12g},y={y:.12g},z={z:.12g},"
            f"vx={wb_vx/1000:.12g},vy={wb_vy/1000:.12g},vz={wb_vz/1000:.12g},ke={ke:.12g}}},"
        )
    fly.append("}\n")
    states.append("}\n")
    args.fly2.write_text("\n".join(fly), encoding="ascii")
    args.source_states_lua.write_text("\n".join(states), encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
