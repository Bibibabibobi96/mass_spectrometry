"""Convert the solver-neutral multipole particle table to SIMION FLY2 and Lua states."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C,
    kinetic_energy_ev,
)
from common.multipole.particle_source_preflight import validate_source
from common.simion.particle_source import render_source_states, render_standard_beams


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
        speed = math.sqrt(2 * energy * ELEMENTARY_CHARGE_C / (mass * AMU_KG))
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


def render_canonical_source(
    particles: Path,
    resolved_design: Path,
) -> tuple[str, str, int]:
    """Project canonical particles into the SIMION workbench frame."""
    resolved = json.loads(resolved_design.read_text(encoding="utf-8-sig"))
    metadata = validate_source(particles, resolved)
    mass_amu = float(metadata["mass_amu"])
    enclosure = resolved["geometry_mm"]["enclosure"]
    rectangular = enclosure["model"] == "rectangular_reference_enclosure_v1"
    origin = 0.0 if rectangular else float(enclosure["shield_outer_radius_mm"])
    z_shift = 0.0 if rectangular else -float(enclosure["vacuum_z_min_mm"])
    charge = int(resolved["particle_source"]["charge_state"])
    source_z = float(resolved["interfaces_mm"]["entrance"]["particle_plane_z_mm"])
    rows = list(csv.DictReader(particles.open(encoding="utf-8-sig")))
    fly = ["particles {", "  coordinates = 0,"]
    states = ["return {"]
    for row in rows:
        if abs(float(row["z_mm"]) - source_z) > 1e-12:
            raise ValueError("canonical particle source plane differs from resolved design")
        vx, vy, vz = (float(row[key]) for key in ("vx_m_s", "vy_m_s", "vz_m_s"))
        ke = kinetic_energy_ev(mass_amu, vx, vy, vz)
        pa_x = origin + float(row["x_mm"])
        pa_y = origin + float(row["y_mm"])
        pa_z = z_shift + float(row["z_mm"])
        x, y, z = pa_z, -pa_y, pa_x
        wb_vx, wb_vy, wb_vz = vz, -vy, vx
        tob = float(row["birth_time_s"]) * 1e6
        fly.extend([
            "  standard_beam {",
            f"    n=1, tob={tob:.12g}, mass={mass_amu:.12g}, charge={charge}, ke={ke:.12g},",
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
    return "\n".join(fly), "\n".join(states), len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--particles", required=True, type=Path)
    parser.add_argument("--resolved-design", required=True, type=Path)
    parser.add_argument("--fly2", required=True, type=Path)
    parser.add_argument("--source-states-lua", required=True, type=Path)
    args = parser.parse_args()
    args.fly2.parent.mkdir(parents=True, exist_ok=True)
    args.source_states_lua.parent.mkdir(parents=True, exist_ok=True)
    fly, states, count = render_canonical_source(
        args.particles, args.resolved_design
    )
    args.fly2.write_text(fly, encoding="ascii")
    args.source_states_lua.write_text(states, encoding="ascii")
    print(f"MULTIPOLE_SIMION_SOURCE=PASS FORMAT=canonical PARTICLES={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
