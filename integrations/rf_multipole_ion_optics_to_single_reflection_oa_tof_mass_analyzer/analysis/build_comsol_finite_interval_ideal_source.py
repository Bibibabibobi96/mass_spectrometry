from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from common.contracts.file_identity import file_sha256

E_CHARGE = 1.602176634e-19
AMU_KG = 1.66053906660e-27


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--expected-geometry-sha256", required=True)
    parser.add_argument("--formal-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--particles", type=int, default=100)
    args = parser.parse_args()

    geometry_sha = file_sha256(args.geometry)
    if geometry_sha != args.expected_geometry_sha256.upper():
        raise ValueError("resolved geometry SHA changed")
    contract = json.loads(args.geometry.read_text(encoding="utf-8"))
    source = contract["particle_source"]
    theory = contract["geometry_derivation"]["accelerator"]["finite_interval_theory"]
    if not math.isclose(float(source["size_z_mm"]), 2.2, abs_tol=1e-12):
        raise ValueError("resolved source width is not 2.2 mm")
    if not math.isclose(float(theory["source_full_width_mm"]), 2.2, abs_tol=1e-12):
        raise ValueError("finite-interval theory width is not 2.2 mm")

    with args.formal_source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))[: args.particles]
    if len(rows) != args.particles:
        raise ValueError("formal ideal-source sample is too short")
    old_x = [float(row["initial_x_mm"]) for row in rows]
    old_y = [float(row["initial_y_mm"]) for row in rows]
    old_x_mid = 0.5 * (min(old_x) + max(old_x))
    old_y_mid = 0.5 * (min(old_y) + max(old_y))
    old_x_span = max(old_x) - min(old_x)
    old_y_span = max(old_y) - min(old_y)
    center_x = float(source["center_x_mm"])
    center_y = float(source["center_y_mm"])
    center_z = float(source["center_z_mm"])
    width_z = float(source["size_z_mm"])
    speed = math.sqrt(2 * 10.0 * E_CHARGE / (100.0 * AMU_KG))
    output_rows: list[list[float | int]] = []
    for index, row in enumerate(rows):
        x = center_x + (float(row["initial_x_mm"]) - old_x_mid) / old_x_span
        y = center_y + (float(row["initial_y_mm"]) - old_y_mid) / old_y_span
        z = center_z - width_z / 2 + width_z * index / (args.particles - 1)
        vz = float(theory["mean_initial_velocity_m_per_s"]) + float(
            theory["velocity_slope_m_per_s_per_mm"]
        ) * (z - center_z)
        vx = math.sqrt(speed * speed - vz * vz)
        output_rows.append([index + 1, 100, 1, x, y, z, vx, 0.0, vz, 10.0])
    if not math.isclose(output_rows[-1][5] - output_rows[0][5], 2.2, abs_tol=1e-12):
        raise AssertionError("materialized z width is not 2.2 mm")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([
            "particle_id", "mass_amu", "charge_state", "x_mm", "y_mm", "z_mm",
            "vx_m_per_s", "vy_m_per_s", "vz_m_per_s", "kinetic_energy_eV",
        ])
        writer.writerows(output_rows)
    metadata = {
        "schema_version": 1,
        "role": "rf_oatof_comsol_cartesian_retrace_release",
        "particles": args.particles,
        "resolved_geometry_sha256": geometry_sha,
        "source_center_mm": [center_x, center_y, center_z],
        "source_size_mm": [1.0, 1.0, 2.2],
        "energy_eV": 10.0,
        "mass_amu": 100.0,
        "global_velocity": {
            "vy_m_per_s": 0.0,
            "vz_mean_m_per_s": theory["mean_initial_velocity_m_per_s"],
            "vz_slope_m_per_s_per_mm": theory["velocity_slope_m_per_s_per_mm"],
            "vx_rule": "sqrt(v_10eV^2-vz^2)",
        },
        "coordinate_frame": "shared_global_cartesian",
        "velocity_error_limit_m_per_s": 1e-6,
        "maximum_velocity_serialization_error_m_per_s": 0.0,
        "output": {
            "path": str(args.output.resolve()),
            "sha256": file_sha256(args.output),
            "bytes": args.output.stat().st_size,
        },
        "sampling": "first 100 governed formal ideal-source x/y samples rescaled to exact 1x1 mm extrema; deterministic inclusive 2.2 mm z lattice",
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
