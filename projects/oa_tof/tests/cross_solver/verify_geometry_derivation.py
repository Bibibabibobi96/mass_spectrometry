"""Verify that oa-TOF engineering geometry is derived from baseline physics inputs."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = PROJECT_ROOT / "analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

from accelerator_time_focus import accelerator_state
from oatof_oaaccelerator_coupling import solve_coupled_reflectron_fields


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
        "L_flight": focus_z + float(source["outbound_field_free_length_mm"]),
    }
    for name, target in accelerator_expected.items():
        actual = float(geometry[name])
        if not math.isclose(actual, target, rel_tol=0.0, abs_tol=1e-12):
            raise AssertionError(f"{name}={actual} but accelerator linkage requires {target}")
    if not math.isclose(grid1_z, repeller_z + accel_d1, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("canonical grid1 coordinate is not linked to d1")
    if not math.isclose(grid2_z, grid1_z + accel_d2, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("canonical grid2 coordinate is not linked to d2")
    accelerator_ring_count = int(contract["rings"]["accelerator_count"])
    accelerator_ring_pitch = accel_d2 / (accelerator_ring_count + 1)
    quantum = float(accelerator["geometry_quantum_mm"])
    if not math.isclose(
        accelerator_ring_pitch / quantum,
        round(accelerator_ring_pitch / quantum),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise AssertionError("accelerator ring pitch is not aligned to geometry quantum")

    if source.get("model_id") != "oatof.oaaccelerator_reflectron_coupled.ideal_1d.v1":
        raise AssertionError("formal reflectron derivation is not the coupled model")
    length_mm = float(source["total_field_free_length_mm"])
    split_length_mm = float(source["outbound_field_free_length_mm"]) + float(
        source["return_field_free_length_mm"]
    )
    if not math.isclose(split_length_mm, length_mm, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("outbound+return field-free lengths do not equal total")
    d1_mm = float(source["stage1_length_mm"])
    margin = float(source["stage2_margin_fraction"])
    margin_mm = float(source.get("stage2_margin_absolute_mm", 0.0))
    digits = int(source["engineering_length_decimals_mm"])
    voltage_digits = int(source["engineering_voltage_decimals_V"])
    voltage = contract["electrodes_V"]
    accelerator_state_value = accelerator_state(
        float(voltage["repeller"]),
        float(voltage["grid1"]),
        accel_d1,
        accel_d2,
    )
    spatial_half_range = (
        accelerator_state_value.field1_v_per_mm
        * float(contract["particle_source"]["size_z_mm"])
        / 2.0
    )
    intrinsic_half_range = float(
        source.get("intrinsic_axial_energy_per_charge_half_range_V", 0.0)
    )
    energy_min = (
        accelerator_state_value.nominal_energy_per_charge_v
        - spatial_half_range
        - intrinsic_half_range
    )
    energy_max = (
        accelerator_state_value.nominal_energy_per_charge_v
        + spatial_half_range
        + intrinsic_half_range
    )
    solution = solve_coupled_reflectron_fields(
        accelerator_state_value,
        d1_mm,
        float(source["outbound_field_free_length_mm"]),
        float(source["return_field_free_length_mm"]),
        energy_min_v=energy_min,
        energy_max_v=energy_max,
        stage2_margin_fraction=margin,
        stage2_margin_mm=margin_mm,
    )
    u1 = solution.stage1_voltage_drop_v
    e2_v_per_mm = solution.stage2_field_v_per_mm
    d2_min_mm = solution.nominal_stage2_penetration_mm
    d2_raw_mm = solution.required_stage2_depth_mm
    l_reflectron_raw_mm = d1_mm + d2_raw_mm
    v_mirror_raw = u1 + e2_v_per_mm * d2_raw_mm
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
    metadata_expected = {
        "nominal_energy_per_charge_V": accelerator_state_value.nominal_energy_per_charge_v,
        "spatial_energy_half_range_V": spatial_half_range,
        "energy_min_V": energy_min,
        "energy_max_V": energy_max,
    }
    for name, target in metadata_expected.items():
        actual = float(source[name])
        if not math.isclose(actual, target, rel_tol=0.0, abs_tol=1e-12):
            raise AssertionError(f"{name}={actual} but coupled derivation requires {target}")

    print("GEOMETRY_DERIVATION_STATUS=PASS")
    print(f"DERIVED_NOMINAL_D2_PENETRATION_MM={d2_min_mm:.15g}")
    print(f"DERIVED_D2_RAW_MM={d2_raw_mm:.15g}")
    print(f"DERIVED_L_REFLECTRON_RAW_MM={l_reflectron_raw_mm:.15g}")
    print(f"DERIVED_V_MIRROR_RAW_V={v_mirror_raw:.15g}")
    print(f"ENGINEERING_LENGTH_DECIMALS_MM={digits}")
    print(f"ENGINEERING_L_REFLECTRON_MM={l_reflectron_engineering_mm:.{digits}f}")
    print(f"ENGINEERING_V_MIRROR_V={round(v_mirror_raw, voltage_digits):.{voltage_digits}f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
