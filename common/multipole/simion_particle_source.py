"""Convert the solver-neutral multipole particle table to SIMION FLY2 and Lua states."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

AMU_KG = 1.66053906660e-27
E_CHARGE_C = 1.602176634e-19


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--particles", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--fly2", required=True, type=Path)
    parser.add_argument("--source-states-lua", required=True, type=Path)
    args = parser.parse_args()
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
