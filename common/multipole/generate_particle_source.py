"""Write the deterministic multipole source as a solver-neutral particle table."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from common.multipole.ideal_transport import source_particles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--release-z-mm", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    contract = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
    rows = source_particles(contract)
    fields = [
        "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
        "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for particle in rows:
            writer.writerow({
                "particle_id": int(particle["particle_id"]),
                "birth_time_s": particle["birth_time_s"],
                "x_mm": particle["x_m"] * 1e3,
                "y_mm": particle["y_m"] * 1e3,
                "z_mm": args.release_z_mm,
                "vx_m_s": particle["vx_m_s"],
                "vy_m_s": particle["vy_m_s"],
                "vz_m_s": particle["vz_m_s"],
                "mass_amu": contract["particle_source"]["mass_amu"],
                "charge_state": contract["particle_source"]["charge_state"],
            })
    print(f"MULTIPOLE_SOURCE=PASS PARTICLES={len(rows)} PATH={args.output}")


if __name__ == "__main__":
    main()
