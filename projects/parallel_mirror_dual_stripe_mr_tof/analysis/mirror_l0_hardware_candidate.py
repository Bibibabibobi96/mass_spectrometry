#!/usr/bin/env python3
"""Run the analytic L0 voltage search on the fixed manufactured mirror.

This command consumes only the frozen CAD-derived axial boundaries.  Its JSON
result is an exploratory L0 voltage candidate, never a voltage-table update,
PA build authorization, or a claim of transverse stability.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path

import scipy

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    derive_mirror_l0_slope_tolerance_per_v,
    parallel_global_l0_family_search,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import (
    derive_mirror_boundaries,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    derive_mirror_voltage_bounds,
    derive_operating_energy_envelope,
    load_contract,
)


def run(
    contract_path: Path,
) -> dict[str, object]:
    contract = load_contract(contract_path)
    mirror = contract["mirror"]
    boundaries = derive_mirror_boundaries(mirror)
    transitions = tuple(float(value) for value in boundaries["analytic_transition_z_mm"])
    l0_budget = mirror["theory_requirements"]["l0_acceptance_budget"]
    profile = mirror["theory_requirements"]["global_l0_search_profile"]
    energy = derive_operating_energy_envelope(contract)
    energies = energy.mirror_energy_nodes_v
    lower, upper = derive_mirror_voltage_bounds(contract)
    slope_tolerance = derive_mirror_l0_slope_tolerance_per_v(
        float(l0_budget["minimum_mass_resolution"]),
        float(l0_budget["mirror_time_width_fraction"]),
        energies,
    )
    logical_processors = os.cpu_count() or 1
    requested_workers = int(profile["maximum_parallel_workers"])
    maximum_workers = min(logical_processors, requested_workers)
    result = parallel_global_l0_family_search(
        float(mirror["theory_requirements"]["berdnikov_transverse_half_gap_mm"]), transitions, lower, upper,
        float(profile["period_slope_derivative_step_v"]), slope_tolerance,
        energies, int(profile["base_random_seed"]), int(profile["restart_count"]), maximum_workers,
        int(profile["population_size_per_restart"]), int(profile["maximum_iterations_per_restart"]),
        float(profile["relative_convergence_tolerance"]), float(boundaries["terminal_electrode_plane_z_mm"]),
        int(profile["maximum_local_function_evaluations"]),
    )
    result["input"] = {
        "contract": str(contract_path),
        "contract_sha256": file_sha256(contract_path),
        "mirror_design_status_at_run": mirror["design_status"],
        "fixed_axial_boundaries_mm": list(transitions),
        "analytic_transverse_half_gap_mm": float(mirror["theory_requirements"]["berdnikov_transverse_half_gap_mm"]),
        "physical_E_active_end_z_mm": float(boundaries["physical_E_active_end_z_mm"]),
        "terminal_electrode_plane_z_mm": float(boundaries["terminal_electrode_plane_z_mm"]),
        "active_start_z_mm": boundaries["active_start_z_mm"],
        "period_slope_derivative_step_v": float(profile["period_slope_derivative_step_v"]),
        "l0_acceptance_budget": l0_budget,
        "maximum_abs_normalized_period_slope_per_v": slope_tolerance,
        "E_midpoint_reference_mm": boundaries["E_midpoint_z_mm"],
        "voltage_envelope_v": mirror["theory_requirements"]["voltage_envelope_v"],
        "resolved_voltage_lower_bounds_v": list(lower),
        "resolved_voltage_upper_bounds_v": list(upper),
        "operating_energy_envelope": energy.__dict__,
        "global_search_profile": profile,
        "available_logical_processors": logical_processors,
        "actual_parallel_workers": maximum_workers,
    }
    result["runtime"] = {
        "python_version": platform.python_version(),
        "scipy_version": scipy.__version__,
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
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = run(arguments.contract)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MIRROR_L0_HARDWARE_CANDIDATE: status={result['status']} output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
