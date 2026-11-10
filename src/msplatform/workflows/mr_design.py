"""Explicit global/restart searches for the ideal MR mirror L0 model.

Search controls and physical bounds are supplied by the caller. L0 family
selection does not qualify transverse L1 stability or native three-dimensional
fields. Execution and result ownership remain with the existing caller.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import math
import os
import random
from typing import Iterable

from scipy.optimize import differential_evolution

from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.mirror_l0 import (
    MirrorL0Design,
    _finite,
    optimize_fixed_geometry_voltages,
    three_point_normalized_period_slopes_per_v,
)


def global_l0_family_search(
    transverse_half_gap_mm: float,
    transition_z_mm: Iterable[float],
    voltage_lower_bounds_v: Iterable[float],
    voltage_upper_bounds_v: Iterable[float],
    period_slope_derivative_step_v: float,
    maximum_abs_normalized_period_slope_per_v: float,
    energies_v: Iterable[float],
    random_seed: int,
    population_size: int,
    maximum_iterations: int,
    relative_convergence_tolerance: float,
    terminal_electrode_plane_z_mm: float | None = None,
    maximum_local_function_evaluations: int | None = None,
) -> dict[str, object]:
    """Generate a reproducible global seed before local L0 refinement."""
    transitions = tuple(_finite(value, "transition_z_mm") for value in transition_z_mm)
    lower = tuple(_finite(value, "voltage_lower_bounds_v") for value in voltage_lower_bounds_v)
    upper = tuple(_finite(value, "voltage_upper_bounds_v") for value in voltage_upper_bounds_v)
    energies = tuple(_finite(value, "energies_v") for value in energies_v)
    if len(lower) != 4 or len(upper) != 4 or any(lo >= hi for lo, hi in zip(lower, upper)):
        raise CandidateContractError("global L0 search needs four ordered voltage bounds")
    if not isinstance(random_seed, int) or population_size <= 0 or maximum_iterations <= 0:
        raise CandidateContractError("global L0 numerical seed, population and iterations must be positive integers")
    relative_tolerance = _finite(relative_convergence_tolerance, "relative_convergence_tolerance")
    if relative_tolerance <= 0.0:
        raise CandidateContractError("global L0 relative convergence tolerance must be positive")
    if maximum_local_function_evaluations is not None and maximum_local_function_evaluations <= 0:
        raise CandidateContractError("global L0 maximum local function evaluations must be positive when specified")

    def objective(values: Iterable[float]) -> float:
        non_ground = tuple(float(value) for value in values)
        try:
            design = MirrorL0Design(
                transverse_half_gap_mm,
                transitions,
                (0.0, *non_ground),
                terminal_electrode_plane_z_mm,
                non_ground[-1] if terminal_electrode_plane_z_mm is not None else None,
            )
            slopes = three_point_normalized_period_slopes_per_v(
                design, energies, period_slope_derivative_step_v,
            )
        except CandidateContractError:
            return 1e30
        return sum((1e6 * value) ** 2 for value in slopes)

    global_result = differential_evolution(
        objective, list(zip(lower, upper)), seed=random_seed, popsize=population_size,
        maxiter=maximum_iterations, tol=relative_tolerance, polish=False, updating="immediate",
    )
    try:
        local_result = optimize_fixed_geometry_voltages(
            transverse_half_gap_mm, transitions, global_result.x, lower, upper,
            period_slope_derivative_step_v, maximum_abs_normalized_period_slope_per_v,
            energies, terminal_electrode_plane_z_mm,
            maximum_function_evaluations=maximum_local_function_evaluations,
        )
    except CandidateContractError as exc:
        local_result = {
            "status": "l0_voltage_family_final_evaluation_failed",
            "geometry_fixed": True,
            "transition_z_mm": list(transitions),
            "transverse_half_gap_mm": float(transverse_half_gap_mm),
            "terminal_electrode_plane_z_mm": terminal_electrode_plane_z_mm,
            "electrode_voltages_v": [0.0, *[float(value) for value in global_result.x]],
            "normalized_period_slopes_per_v": [None, None, None],
            "maximum_abs_normalized_period_slope_per_v": maximum_abs_normalized_period_slope_per_v,
            "failure_reason": str(exc),
            "not_evaluated": ["poincare_map", "symplecticity", "gamma", "three_dimensional_fields", "simion_pa"],
        }
    local_result["global_seed_search"] = {
        "random_seed": random_seed,
        "population_size": population_size,
        "maximum_iterations": maximum_iterations,
        "relative_convergence_tolerance": relative_tolerance,
        "maximum_local_function_evaluations": maximum_local_function_evaluations,
        "optimizer_success": bool(global_result.success),
        "optimizer_message": str(global_result.message),
        "objective_ppm_squared": float(global_result.fun),
        "derived_global_seed_non_ground_voltages_v": [float(value) for value in global_result.x],
    }
    return local_result


def _global_l0_restart(arguments: tuple[object, ...]) -> dict[str, object]:
    """Process-safe entry point for one independent global-to-local restart."""
    return global_l0_family_search(*arguments)  # type: ignore[arg-type]


def parallel_global_l0_family_search(
    transverse_half_gap_mm: float,
    transition_z_mm: Iterable[float],
    voltage_lower_bounds_v: Iterable[float],
    voltage_upper_bounds_v: Iterable[float],
    period_slope_derivative_step_v: float,
    maximum_abs_normalized_period_slope_per_v: float,
    energies_v: Iterable[float],
    base_random_seed: int,
    restart_count: int,
    maximum_workers: int,
    population_size: int,
    maximum_iterations: int,
    relative_convergence_tolerance: float,
    terminal_electrode_plane_z_mm: float | None,
    maximum_local_function_evaluations: int,
) -> dict[str, object]:
    """Search independent full-envelope L0 starts concurrently and retain all receipts.

    Every restart spans the same physical B--E envelope; ``random_seed`` only
    controls stochastic sampling and never narrows a restart around a seed.
    A best L0 member is selected solely by the declared three-slope gate.
    L1 selection deliberately remains a separate stage.
    """
    if not isinstance(base_random_seed, int) or restart_count <= 0 or maximum_workers <= 0:
        raise CandidateContractError("parallel L0 search needs an integer base seed and positive restart/worker counts")
    worker_count = min(restart_count, maximum_workers)
    if maximum_local_function_evaluations <= 0:
        raise CandidateContractError("parallel L0 search needs positive local function-evaluation budget")
    generator = random.Random(base_random_seed)
    restart_seeds = [generator.randrange(2**32) for _ in range(restart_count)]
    common = (
        transverse_half_gap_mm,
        tuple(transition_z_mm),
        tuple(voltage_lower_bounds_v),
        tuple(voltage_upper_bounds_v),
        period_slope_derivative_step_v,
        maximum_abs_normalized_period_slope_per_v,
        tuple(energies_v),
    )
    jobs = [
        (*common, seed, population_size, maximum_iterations, relative_convergence_tolerance,
         terminal_electrode_plane_z_mm, maximum_local_function_evaluations)
        for seed in restart_seeds
    ]
    thread_limits = {}
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        if variable not in os.environ:
            os.environ[variable] = "1"
        thread_limits[variable] = os.environ[variable]
    # Differential evolution is scalar here.  Independent restarts are the
    # parallel unit, which keeps each stochastic trajectory reproducible.
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(_global_l0_restart, jobs))

    def ranking(item: tuple[int, dict[str, object]]) -> tuple[float, float, int]:
        index, result = item
        raw_slopes = result.get("normalized_period_slopes_per_v", [])
        slopes = [abs(float(value)) for value in raw_slopes if value is not None]
        is_l0_member = result["status"] == "l0_voltage_family_member_not_l1_validated"
        return (0.0 if is_l0_member else 1.0, max(slopes) if slopes else math.inf, index)

    selected_index, selected_result = min(enumerate(results), key=ranking)
    # The selected restart is also an element of ``results``.  Copy its
    # top-level mapping before attaching the complete receipt list, otherwise
    # the output graph contains itself and cannot be serialized as JSON.
    selected = dict(selected_result)
    accepted_indices = [
        index for index, result in enumerate(results)
        if result["status"] == "l0_voltage_family_member_not_l1_validated"
    ]
    selected["parallel_restart_search"] = {
        "base_random_seed": base_random_seed,
        "restart_count": restart_count,
        "maximum_workers": maximum_workers,
        "actual_workers": worker_count,
        "restart_seeds": restart_seeds,
        "accepted_l0_restart_indices": accepted_indices,
        "selected_restart_index": selected_index,
        "selection_semantics": "L0 only: accepted three-slope gate first, then smallest maximum absolute slope; L1 has not selected a voltage-family member.",
        "per_worker_numeric_thread_limits": thread_limits,
    }
    selected["restart_receipts"] = results
    return selected
