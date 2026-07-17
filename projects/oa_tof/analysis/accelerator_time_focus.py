"""Solver-independent three-grid accelerator first-order time-focus reference.

The equations follow docs/theory/三栅加速器总长度符号推导.docx.  Lengths
are in millimetres and electrode potentials are in volts.  The mass/charge
factor cancels, so the derived drift distance is species independent.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def focus_drift_mm(u1_v: float, u2_v: float, d1_mm: float, d2_mm: float) -> float:
    """Return field-free drift D from grid3 to the first-order time focus."""
    if not (u1_v > u2_v > 0.0 and d1_mm > 0.0 and d2_mm > 0.0):
        raise ValueError("require U1 > U2 > 0 and d1,d2 > 0")
    e1 = (u1_v - u2_v) / d1_mm
    e2 = u2_v / d2_mm
    v2 = math.sqrt(u1_v - u2_v)
    v3 = math.sqrt(u1_v + u2_v)
    return (v3**3 / e1) * (1.0 / v2 + (e1 / e2) * (1.0 / v3 - 1.0 / v2))


def derive(contract: dict[str, Any]) -> dict[str, Any]:
    design = contract["design"]
    geometry = design["local_geometry_mm"]
    voltage = design["electrodes_V"]
    d1 = float(geometry["d1"])
    d2 = float(geometry["d2"])
    pitch = float(geometry["ring_pitch"])
    count = int(geometry["ring_count"])
    if not math.isclose(d2, (count + 1) * pitch, abs_tol=1e-12):
        raise ValueError("d2 must equal (ring_count+1)*ring_pitch")
    local_centers = [d1 + k * pitch for k in range(1, count + 1)]
    drift = focus_drift_mm(float(voltage["repeller"]), float(voltage["grid1"]), d1, d2)
    local_focus = d1 + d2 + drift
    reference = design.get("reference_geometry")
    if reference:
        reference_voltage = reference["electrodes_V"]
        reference_drift = focus_drift_mm(
            float(reference_voltage["repeller"]),
            float(reference_voltage["grid1"]),
            float(reference["d1_mm"]),
            float(reference["d2_mm"]),
        )
        target_focus = (
            float(reference["assembly_translation_z_mm"])
            + float(reference["d1_mm"])
            + float(reference["d2_mm"])
            + reference_drift
        )
    else:
        reference_drift = None
        target_focus = float(design["target_global_focus_z_mm"])
    translation = target_focus - local_focus
    result = {
        "d1_mm": d1,
        "d2_mm": d2,
        "ring_pitch_mm": pitch,
        "ring_centers_local_mm": local_centers,
        "grid2_local_z_mm": d1 + d2,
        "focus_drift_after_grid2_mm": drift,
        "focus_local_z_mm": local_focus,
        "assembly_translation_z_mm": translation,
        "repeller_global_z_mm": translation,
        "grid1_global_z_mm": translation + d1,
        "ring_centers_global_mm": [translation + z for z in local_centers],
        "grid2_global_z_mm": translation + d1 + d2,
        "focus_global_z_mm": translation + local_focus,
    }
    if reference_drift is not None:
        result["reference_focus_drift_after_grid2_mm"] = reference_drift
        result["reference_global_focus_z_mm"] = target_focus
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", type=Path)
    parser.add_argument("--write-derived", type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = derive(contract)
    expected = contract.get("expected_derived", {})
    for key, expected_value in expected.items():
        actual = result[key]
        if isinstance(expected_value, list):
            if len(actual) != len(expected_value) or any(
                not math.isclose(float(a), float(e), abs_tol=1e-10)
                for a, e in zip(actual, expected_value, strict=True)
            ):
                raise SystemExit(f"MISMATCH {key}: actual={actual} expected={expected_value}")
        elif not math.isclose(float(actual), float(expected_value), abs_tol=1e-10):
            raise SystemExit(f"MISMATCH {key}: actual={actual} expected={expected_value}")
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.write_derived:
        args.write_derived.write_text(text + "\n", encoding="utf-8")
    print(text)
    print("ACCELERATOR_TIME_FOCUS_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
