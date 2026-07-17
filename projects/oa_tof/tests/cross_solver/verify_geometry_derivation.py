"""Verify that oa-TOF engineering geometry is derived from baseline physics inputs."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_geometry_derivation.py baseline.json")
    contract = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    source = contract["geometry_derivation"]["reflectron"]
    geometry = contract["geometry_mm"]

    accelerator = contract["geometry_derivation"]["accelerator"]
    accel_d1 = float(accelerator["d1_mm"])
    accel_d2 = float(accelerator["d2_mm"])
    repeller_z = float(accelerator["canonical_repeller_z_mm"])
    grid1_z = float(accelerator["canonical_grid1_z_mm"])
    grid2_z = float(accelerator["canonical_grid2_z_mm"])
    focus_z = float(accelerator["canonical_focus_z_mm"])
    focus_drift = float(accelerator["focus_drift_after_grid2_mm"])
    accelerator_expected = {
        "L_accel": accel_d1 + accel_d2,
        "accelerator_repeller_z": repeller_z,
        "accelerator_grid1_z": repeller_z + accel_d1,
        "accelerator_grid2_z": repeller_z + accel_d1 + accel_d2,
        "accelerator_focus_z": grid2_z + focus_drift,
        "detector_z": focus_z,
        "L_flight": focus_z + 600.0,
    }
    for name, target in accelerator_expected.items():
        actual = float(geometry[name])
        if not math.isclose(actual, target, rel_tol=0.0, abs_tol=1e-12):
            raise AssertionError(f"{name}={actual} but accelerator linkage requires {target}")
    if not math.isclose(grid1_z, repeller_z + accel_d1, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("canonical grid1 coordinate is not linked to d1")
    if not math.isclose(grid2_z, grid1_z + accel_d2, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("canonical grid2 coordinate is not linked to d2")
    if not math.isclose(accel_d2 / 6.0, 2.8, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("accelerator ring pitch is not exactly 2.8 mm")

    u0 = float(source["incident_energy_eV"])
    length_m = float(source["total_field_free_length_mm"]) / 1000.0
    d1_mm = float(source["stage1_length_mm"])
    d1_m = d1_mm / 1000.0
    margin = float(source["stage2_margin_fraction"])
    digits = int(source["engineering_length_decimals_mm"])
    voltage_digits = int(source["engineering_voltage_decimals_V"])

    u1 = 2.0 * u0 * (length_m + 2.0 * d1_m) / (3.0 * length_m)
    sqrt3 = math.sqrt(3.0)
    e2 = 12.0 * u0 * (
        sqrt3 * math.sqrt(length_m) + math.sqrt(length_m - 4.0 * d1_m)
    ) / (
        sqrt3 * length_m**1.5
        + 8.0 * sqrt3 * math.sqrt(length_m) * d1_m
        + 3.0 * length_m * math.sqrt(length_m - 4.0 * d1_m)
    )
    d2_min_mm = ((u0 - u1) / e2) * 1000.0
    d2_raw_mm = d2_min_mm * (1.0 + margin)
    l_reflectron_raw_mm = d1_mm + d2_raw_mm
    v_mirror_raw = u1 + e2 * (d2_raw_mm / 1000.0)
    d2_engineering_mm = round(d2_raw_mm, digits)
    l_reflectron_engineering_mm = round(l_reflectron_raw_mm, digits)

    expected = {
        "L_stage1": d1_mm,
        "L_stage2": d2_engineering_mm,
        "L_reflectron": l_reflectron_engineering_mm,
    }
    for name, target in expected.items():
        actual = float(geometry[name])
        if not math.isclose(actual, target, rel_tol=0.0, abs_tol=10 ** (-(digits + 2))):
            raise AssertionError(f"{name}={actual} but physics derivation requires {target}")
    voltage_expected = {
        "midgrid": round(u1, voltage_digits),
        "backplate": round(v_mirror_raw, voltage_digits),
    }
    for name, target in voltage_expected.items():
        actual = float(contract["electrodes_V"][name])
        if not math.isclose(actual, target, rel_tol=0.0, abs_tol=10 ** (-(voltage_digits + 2))):
            raise AssertionError(f"{name}={actual} but physics derivation requires {target}")

    print("GEOMETRY_DERIVATION_STATUS=PASS")
    print(f"DERIVED_D2_MIN_RAW_MM={d2_min_mm:.15g}")
    print(f"DERIVED_D2_RAW_MM={d2_raw_mm:.15g}")
    print(f"DERIVED_L_REFLECTRON_RAW_MM={l_reflectron_raw_mm:.15g}")
    print(f"DERIVED_V_MIRROR_RAW_V={v_mirror_raw:.15g}")
    print(f"ENGINEERING_LENGTH_DECIMALS_MM={digits}")
    print(f"ENGINEERING_L_REFLECTRON_MM={l_reflectron_engineering_mm:.{digits}f}")
    print(f"ENGINEERING_V_MIRROR_V={round(v_mirror_raw, voltage_digits):.{voltage_digits}f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
