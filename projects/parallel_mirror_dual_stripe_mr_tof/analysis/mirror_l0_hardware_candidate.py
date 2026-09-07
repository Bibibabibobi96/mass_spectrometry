#!/usr/bin/env python3
"""Run the analytic L0 voltage search on the fixed manufactured mirror.

This command consumes only the frozen CAD-derived axial boundaries.  Its JSON
result is an exploratory L0 voltage candidate, never a voltage-table update,
PA build authorization, or a claim of transverse stability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    optimize_fixed_geometry_voltages,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import (
    derive_mirror_boundaries,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    load_contract,
)


def run(contract_path: Path, target_turning_point_mm: float | None, transverse_half_gap_mm: float) -> dict[str, object]:
    contract = load_contract(contract_path)
    mirror = contract["mirror"]
    boundaries = derive_mirror_boundaries(mirror)
    transitions = tuple(float(value) for value in boundaries["analytic_transition_z_mm"])
    nominal = float(contract["nominal"]["energy_per_charge_v"])
    search = mirror["theory_requirements"]["voltage_search_dimensionless"]
    keys = ("B", "C", "D", "E")
    initial = tuple(nominal * float(search[key]["initial"]) for key in keys)
    lower = tuple(nominal * float(search[key]["lower"]) for key in keys)
    upper = tuple(nominal * float(search[key]["upper"]) for key in keys)
    result = optimize_fixed_geometry_voltages(
        transverse_half_gap_mm=transverse_half_gap_mm,
        transition_z_mm=transitions,
        initial_nonzero_voltages_v=initial,
        voltage_lower_bounds_v=lower,
        voltage_upper_bounds_v=upper,
        target_turning_point_mm=target_turning_point_mm,
        terminal_electrode_plane_z_mm=float(boundaries["terminal_electrode_plane_z_mm"]),
        energies_v=tuple(float(value) for value in mirror["theory_requirements"]["energies_v"]),
    )
    result["input"] = {
        "contract": str(contract_path),
        "mirror_design_status_at_run": mirror["design_status"],
        "fixed_axial_boundaries_mm": list(transitions),
        "analytic_transverse_half_gap_mm": transverse_half_gap_mm,
        "physical_E_active_end_z_mm": float(boundaries["physical_E_active_end_z_mm"]),
        "terminal_electrode_plane_z_mm": float(boundaries["terminal_electrode_plane_z_mm"]),
        "active_start_z_mm": boundaries["active_start_z_mm"],
        "target_turning_point_mm": None if target_turning_point_mm is None else float(target_turning_point_mm),
        "E_midpoint_reference_mm": boundaries["E_midpoint_z_mm"],
        "analytic_search_dimensionless": search,
    }
    result["limitations"] = [
        "The ideal Berdnikov model has no physical slot or finite end-plate thickness; its grounded A segment begins at z=0.  It uses the documented terminal-electrode image construction at the derived plane, with terminal voltage equal to E.  H=15 mm is the currently selected ideal boundary parameter.",
        "No result is written into the voltage contract.",
        "The terminal-E retention constraint is electrical, not a zero-voltage boundary condition.  The turning location is an output of the multi-electrode theory; three-dimensional trajectory clearance must still be checked before a voltage candidate is accepted.",
        "Poincare stability, gamma, 3D field errors, PA, IOB, and flight remain unevaluated.",
    ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--target-turning-point-mm", type=float)
    parser.add_argument("--transverse-half-gap-mm", type=float)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    contract = load_contract(arguments.contract)
    selected_h = arguments.transverse_half_gap_mm
    if selected_h is None:
        selected_h = float(contract["mirror"]["theory_requirements"]["berdnikov_transverse_half_gap_mm"])
    result = run(arguments.contract, arguments.target_turning_point_mm, selected_h)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MIRROR_L0_HARDWARE_CANDIDATE: status={result['status']} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
