"""Build the deterministic N=1000 short-focus ideal linear z-vz entry source."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

E_CHARGE = 1.602176634e-19
AMU_KG = 1.66053906660e-27
PARTICLES = 1000
MASS_AMU = 100.0
ENTRY_GLOBAL_X_MM = -88.01362184380704
ACCELERATOR_AXIS_X_MM = -69.01362184380704
REGISTRATION_X_MM = -168.61362184380704
REGISTRATION_Z_MM = -68.45815512803617
HANDOFF_LOCAL_Z_MM = ENTRY_GLOBAL_X_MM - REGISTRATION_X_MM
SOURCE_CENTER_Z_MM = -68.45815512803617
NOMINAL_PULSE_US = 45.40674277644788
MEAN_VZ_M_S = -2.9323518410018137
SLOPE_VZ_M_S_PER_MM = 228.80604377795845


def build(output: Path) -> None:
    speed = math.sqrt(2.0 * 10.0 * E_CHARGE / (MASS_AMU * AMU_KG))
    rows = []
    for index in range(PARTICLES):
        desired_z = SOURCE_CENTER_Z_MM - 0.5 + index / (PARTICLES - 1)
        global_vz = MEAN_VZ_M_S + SLOPE_VZ_M_S_PER_MM * (
            desired_z - SOURCE_CENTER_Z_MM
        )
        global_vx = math.sqrt(speed * speed - global_vz * global_vz)
        flight_us = (ACCELERATOR_AXIS_X_MM - ENTRY_GLOBAL_X_MM) / (global_vx / 1000.0)
        entry_global_z = desired_z - (global_vz / 1000.0) * flight_us
        rows.append({
            "particle_id": index + 1,
            "birth_time_s": (NOMINAL_PULSE_US - flight_us) / 1e6,
            "x_mm": 0.0,
            "y_mm": entry_global_z - REGISTRATION_Z_MM,
            "z_mm": HANDOFF_LOCAL_Z_MM,
            "vx_m_s": 0.0,
            "vy_m_s": global_vz,
            "vz_m_s": global_vx,
            "mass_amu": MASS_AMU,
            "charge_state": 1,
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output)


if __name__ == "__main__":
    main()
