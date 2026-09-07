"""Theory-owned L0 reference for an ideal planar five-electrode mirror.

The ideal Berdnikov model contains no physical slots or finite electrode
thickness.  Its documented image construction can represent an ideal terminal
electrode plane. CAD supplies the axial reference locations before PA build.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import math
import os
import random
import warnings
from dataclasses import dataclass
from typing import Iterable

from scipy.integrate import IntegrationWarning, quad
from scipy.optimize import brentq, differential_evolution, least_squares

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError


@dataclass(frozen=True)
class MirrorL0Design:
    transverse_half_gap_mm: float
    transition_z_mm: tuple[float, ...]
    electrode_voltages_v: tuple[float, ...]
    terminal_electrode_plane_z_mm: float | None = None
    terminal_electrode_voltage_v: float | None = None


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be finite")
    return result


def step_response(zeta: float) -> float:
    """Berdnikov's on-axis unit-potential step response F0(zeta)."""
    return 0.5 + math.atan(math.sinh(math.pi * _finite(zeta, "zeta") / 2.0)) / math.pi


def validate_design(design: MirrorL0Design) -> None:
    if design.transverse_half_gap_mm <= 0.0:
        raise CandidateContractError("mirror L0 transverse half-gap must be positive")
    if len(design.transition_z_mm) != len(design.electrode_voltages_v):
        raise CandidateContractError("mirror L0 needs one axial transition per electrode voltage")
    if len(design.transition_z_mm) != 5:
        raise CandidateContractError("mirror L0 is defined for exactly five active electrodes")
    if _finite(design.transition_z_mm[0], "transition_z_mm[0]") != 0.0:
        raise CandidateContractError("the theoretical grounded A segment must begin at central z=0")
    if any(_finite(v, "transition_z_mm") <= 0.0 for v in design.transition_z_mm[1:]):
        raise CandidateContractError("non-ground mirror transitions must lie on the positive-z mirror")
    if any(design.transition_z_mm[i] >= design.transition_z_mm[i + 1] for i in range(4)):
        raise CandidateContractError("mirror L0 transitions must be strictly ordered")
    if _finite(design.electrode_voltages_v[0], "electrode_0_v") != 0.0:
        raise CandidateContractError("the Stripe-facing mirror electrode must be grounded")
    if (design.terminal_electrode_plane_z_mm is None) != (design.terminal_electrode_voltage_v is None):
        raise CandidateContractError("terminal electrode plane and voltage must be specified together")
    if design.terminal_electrode_plane_z_mm is not None:
        if _finite(design.terminal_electrode_plane_z_mm, "terminal_electrode_plane_z_mm") <= design.transition_z_mm[-1]:
            raise CandidateContractError("terminal electrode plane must be outside the final voltage step")
        _finite(design.terminal_electrode_voltage_v, "terminal_electrode_voltage_v")


def axial_potential_v(z_mm: float, design: MirrorL0Design) -> float:
    """Symmetric 1-D Berdnikov potential, referenced to central 0 V."""
    validate_design(design)
    position = abs(_finite(z_mm, "z_mm"))
    previous = 0.0
    potential = 0.0
    for boundary, voltage in zip(design.transition_z_mm, design.electrode_voltages_v):
        voltage = _finite(voltage, "electrode_voltage_v")
        delta = voltage - previous
        potential += delta * step_response((position - boundary) / design.transverse_half_gap_mm)
        if design.terminal_electrode_plane_z_mm is not None:
            potential += delta * step_response(
                (position - (2.0 * design.terminal_electrode_plane_z_mm - boundary))
                / design.transverse_half_gap_mm
            )
        previous = voltage
    if design.terminal_electrode_plane_z_mm is not None:
        potential += 2.0 * (design.terminal_electrode_voltage_v - previous) * step_response(
            (position - design.terminal_electrode_plane_z_mm) / design.transverse_half_gap_mm
        )
    return potential


def turning_point_mm(energy_per_charge_v: float, design: MirrorL0Design) -> float:
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    if energy <= 0.0:
        raise CandidateContractError("mirror L0 energy must be positive")
    upper = design.terminal_electrode_plane_z_mm or max(design.transition_z_mm) + 20.0 * design.transverse_half_gap_mm
    grid = [upper * i / 256.0 for i in range(257)]
    values = [axial_potential_v(value, design) - energy for value in grid]
    brackets = [(grid[i], grid[i + 1]) for i in range(256) if values[i] <= 0.0 <= values[i + 1]]
    if not brackets:
        raise CandidateContractError("mirror L0 has no positive-energy turning point")
    # A closed grounded outer plate can make the analytic boundary fall again
    # after the reflecting barrier.  The physical turning point encountered
    # from the central plane is the first upward energy crossing, not the
    # later exit-side crossing.
    lower, upper = brackets[0]
    return brentq(lambda z: axial_potential_v(z, design) - energy, lower, upper)


def reduced_period(energy_per_charge_v: float, design: MirrorL0Design) -> float:
    """Mass-independent full two-mirror period integral in sqrt(mm²/V) units."""
    turning = turning_point_mm(energy_per_charge_v, design)

    def integrand(theta: float) -> float:
        if theta >= math.pi / 2.0 - 1e-10:
            return 0.0
        z = turning * math.sin(theta)
        return turning * math.cos(theta) / math.sqrt(max(energy_per_charge_v - axial_potential_v(z, design), 1e-14))

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", IntegrationWarning)
            integral = quad(integrand, 0.0, math.pi / 2.0, epsabs=1e-8, limit=200)[0]
    except IntegrationWarning as exc:
        raise CandidateContractError("mirror period integral did not converge reliably") from exc
    return 2.0 * integral


def effective_axial_width_mm(energy_per_charge_v: float, reduced_period_mm_per_sqrt_v: float) -> float:
    """Convert a full-two-mirror reduced period into the theory's ``W``.

    With this module's period convention, physical time is
    ``T0 = R*sqrt(2m/q)`` and the adiabatic-drift definition is
    ``W=T0*sqrt(q*E/(2m))``.  Therefore all ion properties cancel and
    ``W=R*sqrt(E)`` in millimetres.  It is an analytic mirror result, not a
    mechanical terminal-plane separation.
    """
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    period = _finite(reduced_period_mm_per_sqrt_v, "reduced_period_mm_per_sqrt_v")
    if energy <= 0.0 or period <= 0.0:
        raise CandidateContractError("energy and reduced period must be positive when deriving W")
    return period * math.sqrt(energy)


def three_point_report(design: MirrorL0Design, energies_v: Iterable[float]) -> dict[str, object]:
    energies = tuple(_finite(value, "three_point_energy_v") for value in energies_v)
    if len(energies) != 3 or energies != tuple(sorted(energies)):
        raise CandidateContractError("mirror L0 needs three ordered energy points")
    periods = tuple(reduced_period(value, design) for value in energies)
    central = periods[1]
    return {
        "energies_v": list(energies),
        "reduced_periods": list(periods),
        "turning_points_mm": [turning_point_mm(value, design) for value in energies],
        "effective_axial_widths_mm": [effective_axial_width_mm(energy, period) for energy, period in zip(energies, periods)],
        "relative_period_residual_ppm": [1e6 * (value - central) / central for value in periods],
        "central_slope_per_v": (periods[2] - periods[0]) / (central * (energies[2] - energies[0])),
    }


def normalized_period_slope_per_v(
    design: MirrorL0Design,
    energy_per_charge_v: float,
    derivative_step_v: float,
) -> float:
    """Return the local normalized period slope ``s_T=(dT/dw)/T``.

    This is deliberately not reconstructed from the three sampled period
    values.  The mirror theory requires one *local* slope at each energy
    node, so each is differentiated around its own point.  ``derivative_step_v``
    is an explicit numerical-contract input; callers must establish its
    convergence rather than inheriting a hidden voltage step.
    """
    energy = _finite(energy_per_charge_v, "period-slope energy_per_charge_v")
    step = _finite(derivative_step_v, "period-slope derivative_step_v")
    if energy <= 0.0 or step <= 0.0 or energy - step <= 0.0:
        raise CandidateContractError("period-slope derivative needs positive energy and a positive step smaller than energy")
    lower = reduced_period(energy - step, design)
    central = reduced_period(energy, design)
    upper = reduced_period(energy + step, design)
    if central <= 0.0:
        raise CandidateContractError("period-slope central period must be positive")
    return (upper - lower) / (2.0 * step * central)


def three_point_normalized_period_slopes_per_v(
    design: MirrorL0Design,
    energies_v: Iterable[float],
    derivative_step_v: float,
) -> tuple[float, float, float]:
    """Evaluate the three independent local mirror-theory slope residuals."""
    energies = tuple(_finite(value, "three-point slope energy_v") for value in energies_v)
    if len(energies) != 3 or energies != tuple(sorted(energies)):
        raise CandidateContractError("three-point period slopes need three ordered energy nodes")
    return tuple(normalized_period_slope_per_v(design, energy, derivative_step_v) for energy in energies)


def derive_mirror_l0_slope_tolerance_per_v(
    minimum_mass_resolution: float,
    mirror_time_width_fraction: float,
    energies_v: Iterable[float],
) -> float:
    """Derive a mirror-only local period-slope gate from the resolution budget."""
    resolution = _finite(minimum_mass_resolution, "minimum_mass_resolution")
    fraction = _finite(mirror_time_width_fraction, "mirror_time_width_fraction")
    energies = tuple(_finite(value, "energies_v") for value in energies_v)
    if resolution <= 0.0 or not 0.0 < fraction <= 1.0 or len(energies) != 3:
        raise CandidateContractError("L0 budget needs positive resolution, fraction in (0,1], and three energies")
    nominal = energies[1]
    lower_offset, upper_offset = nominal - energies[0], energies[2] - nominal
    if lower_offset <= 0.0 or upper_offset <= 0.0 or not math.isclose(lower_offset, upper_offset, rel_tol=0.0, abs_tol=1e-12):
        raise CandidateContractError("L0 budget needs a nonzero symmetric energy half-window")
    half_window = lower_offset
    return fraction / (2.0 * resolution * half_window)


def optimize_fixed_geometry_voltages(
    transverse_half_gap_mm: float,
    transition_z_mm: Iterable[float],
    initial_nonzero_voltages_v: Iterable[float],
    voltage_lower_bounds_v: Iterable[float],
    voltage_upper_bounds_v: Iterable[float],
    period_slope_derivative_step_v: float,
    maximum_abs_normalized_period_slope_per_v: float,
    energies_v: Iterable[float],
    terminal_electrode_plane_z_mm: float | None = None,
    fixed_terminal_e_voltage_v: float | None = None,
    maximum_function_evaluations: int | None = None,
) -> dict[str, object]:
    """Find one member of the fixed-geometry three-equation L0 family.

    The only L0 equalities are the local normalized period slopes at the
    three declared energies.  A turning point is reported as a feasibility
    diagnostic, never promoted to an arbitrary fourth equality.
    """
    transitions = tuple(_finite(value, "transition_z_mm") for value in transition_z_mm)
    initial = tuple(_finite(value, "initial_nonzero_voltages_v") for value in initial_nonzero_voltages_v)
    lower = tuple(_finite(value, "voltage_lower_bounds_v") for value in voltage_lower_bounds_v)
    upper = tuple(_finite(value, "voltage_upper_bounds_v") for value in voltage_upper_bounds_v)
    energies = tuple(_finite(value, "energies_v") for value in energies_v)
    slope_step = _finite(period_slope_derivative_step_v, "period_slope_derivative_step_v")
    slope_tolerance = _finite(
        maximum_abs_normalized_period_slope_per_v,
        "maximum_abs_normalized_period_slope_per_v",
    )
    terminal_plane = (
        None
        if terminal_electrode_plane_z_mm is None
        else _finite(terminal_electrode_plane_z_mm, "terminal_electrode_plane_z_mm")
    )
    fixed_terminal_e = (
        None
        if fixed_terminal_e_voltage_v is None
        else _finite(fixed_terminal_e_voltage_v, "fixed_terminal_e_voltage_v")
    )
    if len(initial) != 4 or len(lower) != 4 or len(upper) != 4:
        raise CandidateContractError("fixed-geometry voltage solve needs four non-ground electrode voltages")
    if any(not low < high for low, high in zip(lower, upper)):
        raise CandidateContractError("each voltage bound must be ordered")
    if len(energies) != 3 or energies != tuple(sorted(energies)) or slope_step <= 0.0 or slope_tolerance <= 0.0:
        raise CandidateContractError("fixed-geometry solve needs ordered energies plus positive slope step and tolerance")
    if lower[-1] <= max(energies):
        raise CandidateContractError(
            "terminal E lower bound must exceed the highest energy-per-charge so the outer mirror barrier retains ions"
        )
    if fixed_terminal_e is not None and not lower[-1] <= fixed_terminal_e <= upper[-1]:
        raise CandidateContractError("fixed terminal E voltage must lie inside the declared E envelope")

    variable_initial = initial[:3] if fixed_terminal_e is not None else initial
    variable_lower = lower[:3] if fixed_terminal_e is not None else lower
    variable_upper = upper[:3] if fixed_terminal_e is not None else upper

    def design(values: Iterable[float]) -> MirrorL0Design:
        values_tuple = tuple(float(value) for value in values)
        non_ground_voltages = (*values_tuple, fixed_terminal_e) if fixed_terminal_e is not None else values_tuple
        return MirrorL0Design(
            float(transverse_half_gap_mm), transitions, (0.0, *non_ground_voltages),
            terminal_plane, non_ground_voltages[-1] if terminal_plane is not None else None,
        )

    def residual(values: Iterable[float]) -> list[float]:
        try:
            slopes = three_point_normalized_period_slopes_per_v(design(values), energies, slope_step)
        except CandidateContractError:
            # Optimizers legitimately probe non-reflecting voltage sets.  They
            # are infeasible trial points, not a reason to abort the complete
            # fixed-geometry search.
            return [1e9, 1e9, 1e9]
        return [1e6 * value for value in slopes]

    if maximum_function_evaluations is not None and maximum_function_evaluations <= 0:
        raise CandidateContractError("maximum_function_evaluations must be positive when specified")
    solution = least_squares(
        residual, variable_initial, bounds=(variable_lower, variable_upper),
        max_nfev=maximum_function_evaluations,
    )
    result_design = design(solution.x)
    report = three_point_report(result_design, energies)
    slopes = three_point_normalized_period_slopes_per_v(result_design, energies, slope_step)
    if not solution.success:
        status = "l0_voltage_slice_search_not_converged" if fixed_terminal_e is not None else "l0_voltage_family_search_not_converged"
    elif any(abs(value) > slope_tolerance for value in slopes):
        status = "l0_voltage_slice_residual_above_tolerance" if fixed_terminal_e is not None else "l0_voltage_family_search_residual_above_tolerance"
    else:
        status = "l0_voltage_slice_member_not_l1_validated" if fixed_terminal_e is not None else "l0_voltage_family_member_not_l1_validated"
    return {
        "status": status,
        "geometry_fixed": True,
        "transition_z_mm": list(transitions),
        "transverse_half_gap_mm": float(transverse_half_gap_mm),
        "terminal_electrode_plane_z_mm": terminal_plane,
        "electrode_voltages_v": list(result_design.electrode_voltages_v),
        "terminal_e_voltage_v": result_design.electrode_voltages_v[-1],
        "fixed_terminal_e_voltage_v": fixed_terminal_e,
        "terminal_e_retention_constraint_v": {"strictly_greater_than_energy_per_charge_v": max(energies)},
        "optimizer": {
            "success": bool(solution.success), "message": str(solution.message), "cost": float(solution.cost),
            "maximum_function_evaluations": maximum_function_evaluations,
        },
        "three_point": report,
        "normalized_period_slopes_per_v": list(slopes),
        "period_slope_derivative_step_v": slope_step,
        "maximum_abs_normalized_period_slope_per_v": slope_tolerance,
        "residual": residual(solution.x),
        "not_evaluated": ["poincare_map", "symplecticity", "gamma", "three_dimensional_fields", "simion_pa"],
    }


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
