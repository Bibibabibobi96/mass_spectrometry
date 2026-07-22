"""Compare functional L3 multipole results without asserting numerical equivalence."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def simion_case(path: Path) -> dict[str, float | int]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    handoff = [row for row in rows if row["event"] == "handoff" and row["status"] == "transmitted"]
    particle_count = len({int(row["particle_id"]) for row in rows if row["event"] == "source"})
    radii = [float(row["radial_position_mm"]) for row in handoff]
    max_rod = max(float(row["max_rod_radius_mm"]) for row in rows)
    return {
        "particles": particle_count,
        "transmitted": len(handoff),
        "transmission_fraction": len(handoff) / particle_count,
        "exit_rms_radius_mm": math.sqrt(sum(value * value for value in radii) / len(radii)) if radii else 0.0,
        "maximum_rod_radius_mm": max_rod,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rf-state", required=True, type=Path)
    parser.add_argument("--zero-state", required=True, type=Path)
    parser.add_argument("--comsol-metrics", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    comsol = json.loads(args.comsol_metrics.read_text(encoding="utf-8-sig"))
    simion_rf = simion_case(args.rf_state)
    simion_zero = simion_case(args.zero_state)
    comsol_rf = comsol["cases"]["finite_3d_rf_on"]
    comsol_zero = comsol["cases"]["zero_rf_control"]
    result = {
        "schema_version": 1,
        "role": "multipole_l3_cross_solver_functional_comparison",
        "status": "PASS" if simion_rf["transmission_fraction"] >= 0.8 and
        simion_rf["transmission_fraction"] - simion_zero["transmission_fraction"] >= 0.2 else "FAIL",
        "comparison_scope": "Functional transport only; radius differences are diagnostic and not a convergence claim.",
        "simion": {"finite_3d_rf_on": simion_rf, "zero_rf_control": simion_zero},
        "comsol": {"finite_3d_rf_on": comsol_rf, "zero_rf_control": comsol_zero},
        "differences_simion_minus_comsol": {
            "rf_transmission_fraction": simion_rf["transmission_fraction"] - comsol_rf["transmission_fraction"],
            "zero_rf_transmission_fraction": simion_zero["transmission_fraction"] - comsol_zero["transmission_fraction"],
            "rf_exit_rms_radius_mm": simion_rf["exit_rms_radius_mm"] - comsol_rf["exit_rms_radius_mm"],
            "rf_maximum_rod_radius_mm": simion_rf["maximum_rod_radius_mm"] - comsol_rf["maximum_rod_radius_mm"],
        },
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
