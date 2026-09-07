"""Theory-owned L0 reference for an ideal planar five-electrode mirror.

The ideal Berdnikov model contains no physical slots or finite electrode
thickness.  Its documented image construction can represent an ideal terminal
electrode plane. CAD supplies the axial reference locations before PA build.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from scipy.integrate import quad
from scipy.optimize import brentq, least_squares

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

    return 2.0 * quad(integrand, 0.0, math.pi / 2.0, epsabs=1e-8, limit=200)[0]


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
        "relative_period_residual_ppm": [1e6 * (value - central) / central for value in periods],
        "central_slope_per_v": (periods[2] - periods[0]) / (central * (energies[2] - energies[0])),
    }


def optimize_fixed_geometry_voltages(
    transverse_half_gap_mm: float,
    transition_z_mm: Iterable[float],
    initial_nonzero_voltages_v: Iterable[float],
    voltage_lower_bounds_v: Iterable[float],
    voltage_upper_bounds_v: Iterable[float],
    target_turning_point_mm: float | None,
    energies_v: Iterable[float],
    terminal_electrode_plane_z_mm: float | None = None,
) -> dict[str, object]:
    """Find an L0 voltage candidate while explicitly holding geometry fixed.

    The residual combines the two independent three-point period differences
    with a nominal-energy turning-point target.  It is intentionally *not* an
    acceptance test: L1 must still establish transverse stability and gamma.
    """
    transitions = tuple(_finite(value, "transition_z_mm") for value in transition_z_mm)
    initial = tuple(_finite(value, "initial_nonzero_voltages_v") for value in initial_nonzero_voltages_v)
    lower = tuple(_finite(value, "voltage_lower_bounds_v") for value in voltage_lower_bounds_v)
    upper = tuple(_finite(value, "voltage_upper_bounds_v") for value in voltage_upper_bounds_v)
    energies = tuple(_finite(value, "energies_v") for value in energies_v)
    target_turn = None if target_turning_point_mm is None else _finite(target_turning_point_mm, "target_turning_point_mm")
    terminal_plane = (
        None
        if terminal_electrode_plane_z_mm is None
        else _finite(terminal_electrode_plane_z_mm, "terminal_electrode_plane_z_mm")
    )
    if len(initial) != 4 or len(lower) != 4 or len(upper) != 4:
        raise CandidateContractError("fixed-geometry voltage solve needs four non-ground electrode voltages")
    if any(not low < high for low, high in zip(lower, upper)):
        raise CandidateContractError("each voltage bound must be ordered")
    if len(energies) != 3 or energies != tuple(sorted(energies)) or (target_turn is not None and target_turn <= 0.0):
        raise CandidateContractError("fixed-geometry solve needs ordered three-point energies and an optional positive turn target")
    if lower[-1] <= max(energies):
        raise CandidateContractError(
            "terminal E lower bound must exceed the highest energy-per-charge so the outer mirror barrier retains ions"
        )

    def design(values: Iterable[float]) -> MirrorL0Design:
        values_tuple = tuple(float(value) for value in values)
        return MirrorL0Design(
            float(transverse_half_gap_mm), transitions, (0.0, *values_tuple),
            terminal_plane, values_tuple[-1] if terminal_plane is not None else None,
        )

    def residual(values: Iterable[float]) -> list[float]:
        try:
            report = three_point_report(design(values), energies)
        except CandidateContractError:
            # Optimizers legitimately probe non-reflecting voltage sets.  They
            # are infeasible trial points, not a reason to abort the complete
            # fixed-geometry search.
            return [1e9, 1e9, 1e9]
        periods = report["reduced_periods"]
        turning = report["turning_points_mm"]
        nominal = periods[1]
        # ppm-scale period residuals and a millimetre-scale turn residual are
        # normalized so neither numerical unit silently dominates the search.
        result = [
            1e6 * (periods[0] - nominal) / nominal,
            1e6 * (periods[2] - nominal) / nominal,
        ]
        if target_turn is not None:
            result.append((turning[1] - target_turn) / 0.1)
        return result

    solution = least_squares(residual, initial, bounds=(lower, upper), max_nfev=500)
    result_design = design(solution.x)
    report = three_point_report(result_design, energies)
    if not solution.success:
        status = "l0_voltage_search_not_converged"
    else:
        status = "l0_voltage_candidate_not_l1_validated"
    return {
        "status": status,
        "geometry_fixed": True,
        "transition_z_mm": list(transitions),
        "transverse_half_gap_mm": float(transverse_half_gap_mm),
        "terminal_electrode_plane_z_mm": terminal_plane,
        "electrode_voltages_v": [0.0, *[float(value) for value in solution.x]],
        "terminal_e_voltage_v": float(solution.x[-1]),
        "terminal_e_retention_constraint_v": {"strictly_greater_than_energy_per_charge_v": max(energies)},
        "optimizer": {"success": bool(solution.success), "message": str(solution.message), "cost": float(solution.cost)},
        "three_point": report,
        "residual": residual(solution.x),
        "not_evaluated": ["poincare_map", "symplecticity", "gamma", "three_dimensional_fields", "simion_pa"],
    }
