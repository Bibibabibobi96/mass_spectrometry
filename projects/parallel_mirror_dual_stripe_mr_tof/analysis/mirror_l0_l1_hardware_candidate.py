#!/usr/bin/env python3
"""Run the fixed-geometry combined analytic L0/L1 voltage search."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l1 import optimize_l0_l1_fixed_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--l0-seed", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--target-turning-point-mm", type=float)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    seed = json.loads(arguments.l0_seed.read_text(encoding="utf-8"))
    contract = load_contract(arguments.contract)
    nominal = float(contract["nominal"]["energy_per_charge_v"])
    search = contract["mirror"]["theory_requirements"]["voltage_search_dimensionless"]
    keys = ("B", "C", "D", "E")
    lower = tuple(nominal * float(search[key]["lower"]) for key in keys)
    upper = tuple(nominal * float(search[key]["upper"]) for key in keys)
    energies = tuple(float(value) for value in contract["mirror"]["theory_requirements"]["energies_v"])
    design = MirrorL0Design(
        float(seed["transverse_half_gap_mm"]),
        tuple(float(value) for value in seed["transition_z_mm"]),
        tuple(float(value) for value in seed["electrode_voltages_v"]),
        seed.get("terminal_electrode_plane_z_mm"),
        float(seed["electrode_voltages_v"][-1]) if seed.get("terminal_electrode_plane_z_mm") is not None else None,
    )
    result = optimize_l0_l1_fixed_geometry(
        design,
        arguments.target_turning_point_mm,
        lower,
        upper,
        energies,
    )
    result["limitations"] = [
        "Analytic infinite-y 2-D screening only; it includes the ideal Berdnikov terminal-electrode plane but excludes real slots, electrode thickness, sidewalls, and three-dimensional hardware.",
        "Search bounds are not power-supply limits and result is not written to the main voltage contract.",
        "PA, IOB, SIMION flight, grid convergence, and hardware feasibility remain unevaluated.",
    ]
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MIRROR_L0_L1_HARDWARE_CANDIDATE: status={result['status']} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
