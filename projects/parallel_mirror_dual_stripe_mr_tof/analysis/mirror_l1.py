"""Paraxial 2-D Berdnikov mirror map for L1 screening.

This is an analytic pre-screen only: it uses the same infinite-y planar
boundary model as L0, extracts the central-plane-to-central-plane reflection
map, and reports reversibility/symplectic diagnostics.  It cannot replace a
3-D PA/BEM field calculation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design, three_point_report
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError


@dataclass(frozen=True)
class MirrorMap:
    matrix: tuple[tuple[float, float], tuple[float, float]]
    determinant: float
    reversibility_difference: float
    gamma_degrees: float | None
    stable: bool


def _derivatives(z_mm: float, x_mm: float, design: MirrorL0Design) -> tuple[float, float, float]:
    """Return phi, dphi/dx, dphi/dz in V and V/mm for z >= 0."""
    if z_mm < 0.0:
        potential, dx, dz = _derivatives(-z_mm, x_mm, design)
        return potential, dx, -dz
    h = design.transverse_half_gap_mm
    def step_at(boundary: float) -> tuple[float, float, float]:
        zeta = (z_mm - boundary) / h
        xi = x_mm / h
        a = math.pi * zeta / 2.0
        b = math.pi * xi / 2.0
        sinh_a = math.sinh(a)
        cosh_a = math.cosh(a)
        cos_b = math.cos(b)
        sin_b = math.sin(b)
        denom = cos_b * cos_b + sinh_a * sinh_a
        return (
            0.5 + math.atan(sinh_a / cos_b) / math.pi,
            sinh_a * sin_b / (2.0 * h * denom),
            cosh_a * cos_b / (2.0 * h * denom),
        )

    previous = 0.0
    potential = dx = dz = 0.0
    for boundary, voltage in zip(design.transition_z_mm, design.electrode_voltages_v):
        delta = voltage - previous
        terms = [step_at(boundary)]
        if design.terminal_electrode_plane_z_mm is not None:
            terms.append(step_at(2.0 * design.terminal_electrode_plane_z_mm - boundary))
        for phi, dphi_dx, dphi_dz in terms:
            potential += delta * phi
            dx += delta * dphi_dx
            dz += delta * dphi_dz
        previous = voltage
    if design.terminal_electrode_plane_z_mm is not None:
        phi, dphi_dx, dphi_dz = step_at(design.terminal_electrode_plane_z_mm)
        correction = 2.0 * (design.terminal_electrode_voltage_v - previous)
        potential += correction * phi
        dx += correction * dphi_dx
        dz += correction * dphi_dz
    return potential, dx, dz


def reflect(initial_x_mm: float, initial_alpha: float, energy_v: float, design: MirrorL0Design) -> tuple[float, float]:
    """Return x and slope at the next downward central-plane crossing."""
    potential0, _, _ = _derivatives(0.0, initial_x_mm, design)
    if energy_v <= potential0:
        raise CandidateContractError("L1 initial point has insufficient axial energy")
    speed2 = 2.0 * (energy_v - potential0) / (1.0 + initial_alpha * initial_alpha)
    vz0 = math.sqrt(speed2)
    vx0 = initial_alpha * vz0

    def rhs(_time: float, state: list[float]) -> list[float]:
        x, z, vx, vz = state
        _, dphi_dx, dphi_dz = _derivatives(z, x, design)
        return [vx, vz, -dphi_dx, -dphi_dz]

    def central_crossing(_time: float, state: list[float]) -> float:
        return state[1]

    central_crossing.direction = -1.0
    central_crossing.terminal = True
    solution = solve_ivp(
        rhs,
        (0.0, 200.0),
        [initial_x_mm, 1e-8, vx0, vz0],
        events=central_crossing,
        rtol=1e-10,
        atol=1e-12,
        max_step=0.05,
    )
    if not solution.t_events[0].size:
        raise CandidateContractError("L1 ray did not return to central plane")
    x, _z, vx, vz = solution.y_events[0][0]
    if vz >= 0.0:
        raise CandidateContractError("L1 central event has incorrect direction")
    # The return crossing has negative z velocity.  Reverse that longitudinal
    # orientation so the map compares two identically directed central-plane
    # sections; without this sign, a reversal matrix can falsely appear to
    # have trace zero and hence a spurious 90-degree phase advance.
    return float(x), float(-vx / vz)


def map_at_energy(energy_v: float, design: MirrorL0Design, dx_mm: float = 1e-3, dalpha: float = 1e-5) -> MirrorMap:
    """Finite-difference the single-reflection central-plane map."""
    if dx_mm <= 0.0 or dalpha <= 0.0:
        raise CandidateContractError("L1 finite-difference amplitudes must be positive")
    xp, ap = reflect(dx_mm, 0.0, energy_v, design)
    xm, am = reflect(-dx_mm, 0.0, energy_v, design)
    xa, aa = reflect(0.0, dalpha, energy_v, design)
    xb, ab = reflect(0.0, -dalpha, energy_v, design)
    m11, m21 = (xp - xm) / (2.0 * dx_mm), (ap - am) / (2.0 * dx_mm)
    m12, m22 = (xa - xb) / (2.0 * dalpha), (aa - ab) / (2.0 * dalpha)
    determinant = m11 * m22 - m12 * m21
    reversible_difference = m11 - m22
    trace_half = (m11 + m22) / 2.0
    stable = abs(trace_half) < 1.0
    gamma = math.degrees(math.acos(max(-1.0, min(1.0, trace_half)))) if stable else None
    return MirrorMap(((m11, m12), (m21, m22)), determinant, reversible_difference, gamma, stable)


def optimize_l0_l1_fixed_geometry(
    design_seed: MirrorL0Design,
    target_turning_point_mm: float | None,
    lower_nonzero_voltages_v: tuple[float, float, float, float],
    upper_nonzero_voltages_v: tuple[float, float, float, float],
    energy_points_v: tuple[float, float, float],
) -> dict[str, object]:
    """Search voltages only for L0 isochrony plus a 90-degree L1 map target."""
    if len(design_seed.electrode_voltages_v) != 5 or design_seed.electrode_voltages_v[0] != 0.0:
        raise CandidateContractError("combined L0/L1 search requires five voltages with grounded first electrode")
    if len(energy_points_v) != 3 or tuple(sorted(energy_points_v)) != energy_points_v:
        raise CandidateContractError("combined L0/L1 search requires three ordered contract energy points")
    if lower_nonzero_voltages_v[-1] <= max(energy_points_v):
        raise CandidateContractError("combined L0/L1 terminal E lower bound must retain all contract energy points")
    initial = design_seed.electrode_voltages_v[1:]

    def design(values) -> MirrorL0Design:
        values_tuple = tuple(map(float, values))
        return MirrorL0Design(
            design_seed.transverse_half_gap_mm,
            design_seed.transition_z_mm,
            (0.0, *values_tuple),
            design_seed.terminal_electrode_plane_z_mm,
            values_tuple[-1] if design_seed.terminal_electrode_plane_z_mm is not None else None,
        )

    def residual(values) -> list[float]:
        try:
            candidate = design(values)
            l0 = three_point_report(candidate, energy_points_v)
            periods = l0["reduced_periods"]
            midpoint = periods[1]
            mapping = map_at_energy(energy_points_v[1], candidate)
        except CandidateContractError:
            return [1e9, 1e9, 1e9] if target_turning_point_mm is None else [1e9, 1e9, 1e9, 1e9]
        # Both L0 residuals use ppm.  The turn target and the transverse map
        # are independently normalized, so neither silently masks the other.
        values_out = [
            1e6 * (periods[0] - midpoint) / midpoint,
            1e6 * (periods[2] - midpoint) / midpoint,
            mapping.matrix[0][0],
        ]
        if target_turning_point_mm is not None:
            values_out.insert(2, (l0["turning_points_mm"][1] - target_turning_point_mm) / 0.1)
        return values_out

    solution = least_squares(residual, initial, bounds=(lower_nonzero_voltages_v, upper_nonzero_voltages_v), max_nfev=500)
    result_design = design(solution.x)
    l0 = three_point_report(result_design, energy_points_v)
    mapping = map_at_energy(energy_points_v[1], result_design)
    return {
        "status": "l0_l1_voltage_candidate_not_3d_validated" if mapping.stable else "l0_l1_search_not_stable",
        "geometry_fixed": True,
        "electrode_voltages_v": list(result_design.electrode_voltages_v),
        "transition_z_mm": list(result_design.transition_z_mm),
        "terminal_electrode_plane_z_mm": result_design.terminal_electrode_plane_z_mm,
        "terminal_electrode_voltage_v": result_design.terminal_electrode_voltage_v,
        "terminal_electrode_equals_e": result_design.terminal_electrode_voltage_v == result_design.electrode_voltages_v[-1],
        "three_point": l0,
        "mapping": {"matrix_x_alpha": [list(row) for row in mapping.matrix], "determinant": mapping.determinant, "gamma_degrees": mapping.gamma_degrees, "stable": mapping.stable},
        "residual": residual(solution.x),
        "optimizer": {"success": bool(solution.success), "message": str(solution.message), "cost": float(solution.cost), "nfev": int(solution.nfev)},
    }
