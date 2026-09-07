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
from scipy.optimize import brentq, least_squares
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    optimize_fixed_geometry_voltages,
    three_point_normalized_period_slopes_per_v,
    three_point_report,
)
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


def _central_plane_crossing(
    initial_x_mm: float,
    initial_alpha: float,
    energy_v: float,
    design: MirrorL0Design,
    crossing_direction: float,
) -> tuple[float, float, float]:
    """Return ``x``, slope and time at the requested central-plane crossing."""
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

    central_crossing.direction = crossing_direction
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
    if crossing_direction < 0.0 and vz >= 0.0:
        raise CandidateContractError("L1 central event has incorrect direction")
    # The return crossing has negative z velocity.  Reverse that longitudinal
    # orientation so the map compares two identically directed central-plane
    # sections; without this sign, a reversal matrix can falsely appear to
    # have trace zero and hence a spurious 90-degree phase advance.
    return float(x), float(vx / vz), float(solution.t_events[0][0])


def reflect(initial_x_mm: float, initial_alpha: float, energy_v: float, design: MirrorL0Design) -> tuple[float, float]:
    """Return x and slope at the next downward central-plane crossing."""
    x, returned_slope, _elapsed_time = _central_plane_crossing(
        initial_x_mm, initial_alpha, energy_v, design, -1.0,
    )
    return x, -returned_slope


def oscillation_time(
    initial_x_mm: float,
    initial_alpha: float,
    energy_v: float,
    design: MirrorL0Design,
) -> float:
    """Return the same-direction full two-mirror period in the analytic time unit."""
    _x, _slope, elapsed_time = _central_plane_crossing(
        initial_x_mm, initial_alpha, energy_v, design, 1.0,
    )
    return elapsed_time


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


def phase_averaged_transverse_time_aberration(
    energy_v: float,
    design: MirrorL0Design,
    position_probe_mm: float,
    angle_probe_rad: float,
) -> dict[str, float | str | None]:
    """Evaluate the L1 phase-averaged quadratic time-aberration coefficient.

    The probes are explicit numerical inputs.  For a stable map,
    ``Tbar_xx=0.5*(T_xx + f**-2*T_aa)`` where ``f`` is derived from the
    same-direction Poincare map.  An unstable map has no bounded phase ellipse,
    so the coefficient is reported as undefined rather than fabricated.
    """
    x_probe = float(position_probe_mm)
    alpha_probe = float(angle_probe_rad)
    if not math.isfinite(x_probe) or not math.isfinite(alpha_probe) or x_probe <= 0.0 or alpha_probe <= 0.0:
        raise CandidateContractError("L1 time-aberration probes must be finite and positive")
    mapping = map_at_energy(energy_v, design, x_probe, alpha_probe)
    if not mapping.stable or mapping.gamma_degrees is None:
        return {
            "status": "undefined_unstable_map",
            "Tbar_xx": None,
            "T_xx": None,
            "T_alphaalpha": None,
            "f_mm": None,
        }
    sine = math.sin(math.radians(mapping.gamma_degrees))
    if abs(sine) <= 1e-12:
        raise CandidateContractError("L1 phase ellipse scale is undefined near zero phase advance")
    f_mm = mapping.matrix[0][1] / sine
    if not math.isfinite(f_mm) or abs(f_mm) <= 1e-12:
        raise CandidateContractError("L1 phase ellipse scale is non-finite or zero")
    t0 = oscillation_time(0.0, 0.0, energy_v, design)
    t_xx = (
        oscillation_time(x_probe, 0.0, energy_v, design)
        + oscillation_time(-x_probe, 0.0, energy_v, design)
        - 2.0 * t0
    ) / (2.0 * x_probe * x_probe)
    t_alphaalpha = (
        oscillation_time(0.0, alpha_probe, energy_v, design)
        + oscillation_time(0.0, -alpha_probe, energy_v, design)
        - 2.0 * t0
    ) / (2.0 * alpha_probe * alpha_probe)
    return {
        "status": "evaluated",
        "Tbar_xx": 0.5 * (t_xx + t_alphaalpha / (f_mm * f_mm)),
        "T_xx": t_xx,
        "T_alphaalpha": t_alphaalpha,
        "f_mm": f_mm,
    }


def screen_l1_fixed_geometry(
    design: MirrorL0Design,
    energy_points_v: tuple[float, float, float],
    position_probe_mm: float,
    angle_probe_rad: float,
) -> dict[str, object]:
    """Screen one L0 mirror-family member using transverse mirror theory.

    The fixed-geometry axial problem has exactly three equal-time equations.
    This function deliberately does not change B--E or add ``gamma=90°`` as a
    fourth axial equation.  It reports the Poincare maps needed to rank or
    reject an L0 family member solely with mirror-theory criteria.
    """
    if len(design.electrode_voltages_v) != 5 or design.electrode_voltages_v[0] != 0.0:
        raise CandidateContractError("L1 screening requires five voltages with grounded first electrode")
    if len(energy_points_v) != 3 or tuple(sorted(energy_points_v)) != energy_points_v:
        raise CandidateContractError("L1 screening requires three ordered contract energy points")
    maps = tuple(map_at_energy(energy, design, position_probe_mm, angle_probe_rad) for energy in energy_points_v)
    nominal_mapping = maps[1]
    return {
        "status": "l1_screened_stable_not_3d_validated" if all(item.stable for item in maps) else "l1_screened_unstable",
        "geometry_fixed": True,
        "electrode_voltages_v": list(design.electrode_voltages_v),
        "transition_z_mm": list(design.transition_z_mm),
        "terminal_electrode_plane_z_mm": design.terminal_electrode_plane_z_mm,
        "terminal_electrode_voltage_v": design.terminal_electrode_voltage_v,
        "terminal_electrode_equals_e": design.terminal_electrode_voltage_v == design.electrode_voltages_v[-1],
        "nominal_mapping": _mapping_record(nominal_mapping),
        "maps_by_energy_v": {
            str(energy): _mapping_record(mapping)
            for energy, mapping in zip(energy_points_v, maps)
        },
        "phase_averaged_time_aberration_by_energy_v": {
            str(energy): phase_averaged_transverse_time_aberration(
                energy, design, position_probe_mm, angle_probe_rad,
            )
            for energy in energy_points_v
        },
        "time_aberration_probes": {
            "position_probe_mm": position_probe_mm,
            "angle_probe_rad": angle_probe_rad,
        },
    }


def continue_fixed_e_l0_family_to_gamma(
    lower_design: MirrorL0Design,
    upper_design: MirrorL0Design,
    voltage_lower_bounds_v: tuple[float, float, float, float],
    voltage_upper_bounds_v: tuple[float, float, float, float],
    energy_points_v: tuple[float, float, float],
    target_gamma_degrees: float,
    period_slope_derivative_step_v: float,
    maximum_abs_normalized_period_slope_per_v: float,
    position_probe_mm: float,
    angle_probe_rad: float,
    continuation_node_count: int,
    e_voltage_root_tolerance_v: float,
    maximum_gamma_residual_degrees: float,
    maximum_root_iterations: int,
    maximum_local_function_evaluations: int,
) -> dict[str, object]:
    """Select ``gamma`` on a fixed-E continuation of the three-equation L0 family."""
    if lower_design.transition_z_mm != upper_design.transition_z_mm:
        raise CandidateContractError("gamma continuation endpoints must share fixed mirror geometry")
    if lower_design.transverse_half_gap_mm != upper_design.transverse_half_gap_mm:
        raise CandidateContractError("gamma continuation endpoints must share the same transverse half-gap")
    if lower_design.terminal_electrode_plane_z_mm != upper_design.terminal_electrode_plane_z_mm:
        raise CandidateContractError("gamma continuation endpoints must share the same terminal plane")
    lower_e, upper_e = lower_design.electrode_voltages_v[-1], upper_design.electrode_voltages_v[-1]
    if not lower_e < upper_e or continuation_node_count < 2:
        raise CandidateContractError("gamma continuation needs ordered E endpoints and at least two nodes")
    target_gamma = float(target_gamma_degrees)
    gamma_tolerance = float(maximum_gamma_residual_degrees)
    if (
        not 0.0 < target_gamma < 180.0
        or e_voltage_root_tolerance_v <= 0.0
        or gamma_tolerance <= 0.0
        or maximum_root_iterations <= 0
    ):
        raise CandidateContractError("gamma target and continuation root controls are invalid")

    cache: dict[float, dict[str, object]] = {}

    def evaluate(e_voltage_v: float) -> float:
        e_voltage = float(e_voltage_v)
        if e_voltage not in cache:
            weight = (e_voltage - lower_e) / (upper_e - lower_e)
            initial = tuple(
                (1.0 - weight) * lower_design.electrode_voltages_v[index]
                + weight * upper_design.electrode_voltages_v[index]
                for index in range(1, 5)
            )
            l0 = optimize_fixed_geometry_voltages(
                lower_design.transverse_half_gap_mm,
                lower_design.transition_z_mm,
                initial,
                voltage_lower_bounds_v,
                voltage_upper_bounds_v,
                period_slope_derivative_step_v,
                maximum_abs_normalized_period_slope_per_v,
                energy_points_v,
                lower_design.terminal_electrode_plane_z_mm,
                fixed_terminal_e_voltage_v=e_voltage,
                maximum_function_evaluations=maximum_local_function_evaluations,
            )
            if l0["status"] != "l0_voltage_slice_member_not_l1_validated":
                raise CandidateContractError(
                    f"gamma continuation left the accepted L0 family at E={e_voltage}: {l0['status']}"
                )
            design = MirrorL0Design(
                lower_design.transverse_half_gap_mm,
                lower_design.transition_z_mm,
                tuple(float(value) for value in l0["electrode_voltages_v"]),
                lower_design.terminal_electrode_plane_z_mm,
                e_voltage,
            )
            mapping = map_at_energy(energy_points_v[1], design, position_probe_mm, angle_probe_rad)
            if not mapping.stable or mapping.gamma_degrees is None:
                raise CandidateContractError(f"gamma continuation crossed an unstable map at E={e_voltage}")
            cache[e_voltage] = {
                "e_voltage_v": e_voltage,
                "l0": l0,
                "nominal_mapping": _mapping_record(mapping),
                "gamma_residual_degrees": mapping.gamma_degrees - target_gamma,
            }
        return float(cache[e_voltage]["gamma_residual_degrees"])

    nodes = [lower_e + (upper_e - lower_e) * index / (continuation_node_count - 1)
             for index in range(continuation_node_count)]
    node_residuals = [evaluate(node) for node in nodes]
    brackets = [
        (nodes[index], nodes[index + 1])
        for index in range(len(nodes) - 1)
        if node_residuals[index] == 0.0 or node_residuals[index] * node_residuals[index + 1] < 0.0
    ]
    if not brackets:
        raise CandidateContractError("stable fixed-E continuation nodes do not bracket the requested gamma")
    bracket = min(brackets, key=lambda pair: abs(evaluate(pair[0])) + abs(evaluate(pair[1])))
    root_e = brentq(
        evaluate, bracket[0], bracket[1], xtol=e_voltage_root_tolerance_v,
        maxiter=maximum_root_iterations,
    )
    evaluate(root_e)
    brent_root = cache[root_e]

    # The three fixed-E L0 equations can possess nearby numerical branches.
    # A scalar Brent solve may therefore stop at a small E interval even when
    # independently re-solving B--D leaves a non-negligible gamma residual.
    # Refine the four-dimensional intersection here: the first three residuals
    # remain the declared L0 equations and gamma is solely the L1 family-member
    # selector.  This does not promote gamma to a fourth L0 equation.
    initial_intersection = tuple(float(value) for value in brent_root["l0"]["electrode_voltages_v"][1:])

    def intersection_residual(non_ground_voltages_v: tuple[float, ...]) -> list[float]:
        design = MirrorL0Design(
            lower_design.transverse_half_gap_mm,
            lower_design.transition_z_mm,
            (0.0, *tuple(float(value) for value in non_ground_voltages_v)),
            lower_design.terminal_electrode_plane_z_mm,
            float(non_ground_voltages_v[-1]),
        )
        try:
            slopes = three_point_normalized_period_slopes_per_v(
                design, energy_points_v, period_slope_derivative_step_v,
            )
            mapping = map_at_energy(energy_points_v[1], design, position_probe_mm, angle_probe_rad)
        except CandidateContractError:
            return [1e9, 1e9, 1e9, 1e9]
        if not mapping.stable or mapping.gamma_degrees is None:
            return [1e9, 1e9, 1e9, 1e9]
        return [
            *(float(value) / maximum_abs_normalized_period_slope_per_v for value in slopes),
            (mapping.gamma_degrees - target_gamma) / gamma_tolerance,
        ]

    intersection = least_squares(
        intersection_residual,
        initial_intersection,
        bounds=(voltage_lower_bounds_v, voltage_upper_bounds_v),
        max_nfev=maximum_local_function_evaluations,
        x_scale="jac",
    )
    root_voltages = tuple(float(value) for value in intersection.x)
    root_design = MirrorL0Design(
        lower_design.transverse_half_gap_mm,
        lower_design.transition_z_mm,
        (0.0, *root_voltages),
        lower_design.terminal_electrode_plane_z_mm,
        root_voltages[-1],
    )
    root_slopes = three_point_normalized_period_slopes_per_v(
        root_design, energy_points_v, period_slope_derivative_step_v,
    )
    root_mapping = map_at_energy(energy_points_v[1], root_design, position_probe_mm, angle_probe_rad)
    if not root_mapping.stable or root_mapping.gamma_degrees is None:
        raise CandidateContractError("gamma-target intersection refinement produced an unstable map")
    gamma_residual = root_mapping.gamma_degrees - target_gamma
    if (
        not intersection.success
        or any(abs(value) > maximum_abs_normalized_period_slope_per_v for value in root_slopes)
        or abs(gamma_residual) > gamma_tolerance
    ):
        raise CandidateContractError(
            "gamma-target intersection refinement did not satisfy the declared L0 and L1 residual gates"
        )
    root_l0 = {
        "status": "l0_voltage_slice_member_not_l1_validated",
        "geometry_fixed": True,
        "transition_z_mm": list(root_design.transition_z_mm),
        "transverse_half_gap_mm": root_design.transverse_half_gap_mm,
        "terminal_electrode_plane_z_mm": root_design.terminal_electrode_plane_z_mm,
        "electrode_voltages_v": list(root_design.electrode_voltages_v),
        "terminal_e_voltage_v": root_design.electrode_voltages_v[-1],
        "fixed_terminal_e_voltage_v": root_design.electrode_voltages_v[-1],
        "terminal_e_retention_constraint_v": {
            "strictly_greater_than_energy_per_charge_v": max(energy_points_v),
        },
        "optimizer": {
            "success": bool(intersection.success),
            "message": str(intersection.message),
            "cost": float(intersection.cost),
            "maximum_function_evaluations": maximum_local_function_evaluations,
            "selection_stage": "L1 gamma intersection on the three-equation L0 family",
        },
        "three_point": three_point_report(root_design, energy_points_v),
        "normalized_period_slopes_per_v": list(root_slopes),
        "period_slope_derivative_step_v": period_slope_derivative_step_v,
        "maximum_abs_normalized_period_slope_per_v": maximum_abs_normalized_period_slope_per_v,
        "residual": intersection_residual(root_voltages)[:3],
        "not_evaluated": ["three_dimensional_fields", "simion_pa"],
    }
    return {
        "status": "gamma_target_continuation_found__probe_and_3d_validation_pending",
        "target_gamma_degrees": target_gamma,
        "root_e_voltage_v": root_design.electrode_voltages_v[-1],
        "gamma_residual_degrees": gamma_residual,
        "l0_receipt": root_l0,
        "l1_screen": screen_l1_fixed_geometry(
            root_design, energy_points_v, position_probe_mm, angle_probe_rad,
        ),
        "initial_e_voltage_bracket_v": [lower_e, upper_e],
        "selected_node_bracket_v": list(bracket),
        "continuation_nodes": [cache[node] for node in nodes],
        "evaluation_count": len(cache),
        "e_voltage_root_tolerance_v": e_voltage_root_tolerance_v,
        "maximum_gamma_residual_degrees": gamma_tolerance,
        "scalar_brent_seed": {
            "e_voltage_v": root_e,
            "gamma_residual_degrees": brent_root["gamma_residual_degrees"],
        },
    }


def _mapping_record(mapping: MirrorMap) -> dict[str, object]:
    """Serialize one transverse map without changing its physical meaning."""
    return {
        "matrix_x_alpha": [list(row) for row in mapping.matrix],
        "determinant": mapping.determinant,
        "reversibility_difference": mapping.reversibility_difference,
        "gamma_degrees": mapping.gamma_degrees,
        "stable": mapping.stable,
    }
