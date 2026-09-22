"""Solve the mirror L0 voltage family from sampled finite-3-D PA responses.

The manufactured geometry and its refined response PAs are immutable inputs.
Only the four symmetric mirror coordinates B--E are recombined.  The axial
model is a fast search surrogate; every selected member still requires a
native SIMION trajectory and transverse L1 validation.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.integrate import IntegrationWarning, quad
from scipy.interpolate import CubicSpline, PPoly
from scipy.optimize import least_squares

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period import (
    load_exact_k_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


GROUPS = ("mirror_B", "mirror_C", "mirror_D", "mirror_E")

def load_numerical_profile(contract_path: Path) -> dict[str, Any]:
    """Load the sole authority for finite-3-D L0 family numerics."""
    contract = _object(contract_path, "MR-TOF baseline contract")
    try:
        source = contract["mirror"]["theory_requirements"][
            "real_3d_l0_voltage_family_profile"
        ]
    except (KeyError, TypeError) as exc:
        raise CandidateContractError(
            "baseline contract lacks the real-3-D L0 voltage-family profile"
        ) from exc
    if not isinstance(source, Mapping):
        raise CandidateContractError("real-3-D L0 voltage-family profile must be an object")
    scheme = str(source.get("voltage_jacobian_scheme", ""))
    if scheme != "three_point_central":
        raise CandidateContractError("real-3-D L0 voltage Jacobian scheme is unsupported")
    try:
        profile = {
            "response_grid_spacing_mm": float(source["response_grid_spacing_mm"]),
            "axis_probe_y_mm": float(source["axis_probe_y_mm"]),
            "e_voltage_slice_count": int(source["e_voltage_slice_count"]),
            "voltage_jacobian_scheme": scheme,
            "voltage_jacobian_relative_step": float(
                source["voltage_jacobian_relative_step"]
            ),
            "least_squares_relative_tolerance": float(
                source["least_squares_relative_tolerance"]
            ),
            "continuation_predictor": str(source["continuation_predictor"]),
            "maximum_function_evaluations_per_e_slice": int(
                source["maximum_function_evaluations_per_e_slice"]
            ),
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CandidateContractError(
            "real-3-D L0 voltage-family profile is incomplete"
        ) from exc
    finite_positive = (
        "response_grid_spacing_mm",
        "voltage_jacobian_relative_step",
        "least_squares_relative_tolerance",
    )
    if any(
        not math.isfinite(profile[key]) or profile[key] <= 0.0
        for key in finite_positive
    ):
        raise CandidateContractError("real-3-D L0 profile contains a non-positive value")
    if not math.isfinite(profile["axis_probe_y_mm"]):
        raise CandidateContractError("real-3-D L0 axis probe must be finite")
    if (
        profile["e_voltage_slice_count"] < 3
        or profile["maximum_function_evaluations_per_e_slice"] < 1
        or profile["continuation_predictor"]
        != "implicit_tangent_from_three_slope_jacobian"
    ):
        raise CandidateContractError("real-3-D L0 profile contains an invalid count")
    return profile


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object")
    return value


@dataclass(frozen=True)
class AxisResponseBasis:
    z_mm: np.ndarray
    response_v: np.ndarray
    normalization_v: float

    def potential(self, voltages_v: Sequence[float]) -> CubicSpline:
        values = np.asarray(tuple(float(value) for value in voltages_v), dtype=float)
        if values.shape != (4,) or not np.all(np.isfinite(values)):
            raise CandidateContractError("real-field mirror model needs finite B--E voltages")
        samples = self.response_v @ (values / self.normalization_v)
        interpolator = CubicSpline(self.z_mm, samples, extrapolate=False)
        zero = float(interpolator(0.0))
        return CubicSpline(self.z_mm, samples - zero, extrapolate=False)


@dataclass(frozen=True)
class AxisFieldResponseBasis:
    """Axis potential reconstructed consistently from linearly interpolated Ez.

    The sampled L1 field model linearly interpolates each electric-field
    response between adjacent native 0.5-mm nodes.  Integrating that linear
    field exactly gives a piecewise-quadratic potential, represented here as
    a ``PPoly``.  This keeps the L0 period calculation on the same axial field
    representation as the sampled-field L1 trajectory instead of introducing
    a second cubic-spline potential between identical PA nodes.
    """

    z_mm: np.ndarray
    ez_response_v_per_mm: np.ndarray
    normalization_v: float

    def __post_init__(self) -> None:
        z = np.asarray(self.z_mm, dtype=float)
        response = np.asarray(self.ez_response_v_per_mm, dtype=float)
        if (
            z.ndim != 1
            or len(z) < 3
            or not np.all(np.isfinite(z))
            or not np.all(np.diff(z) > 0.0)
            or response.shape != (len(z), len(GROUPS))
            or not np.all(np.isfinite(response))
            or not math.isfinite(float(self.normalization_v))
            or float(self.normalization_v) <= 0.0
            or np.count_nonzero(z == 0.0) != 1
        ):
            raise CandidateContractError("axis field response basis is invalid")

    def potential(self, voltages_v: Sequence[float]) -> PPoly:
        values = np.asarray(tuple(float(value) for value in voltages_v), dtype=float)
        if values.shape != (len(GROUPS),) or not np.all(np.isfinite(values)):
            raise CandidateContractError("real-field mirror model needs finite B--E voltages")
        z = np.asarray(self.z_mm, dtype=float)
        ez = np.asarray(self.ez_response_v_per_mm, dtype=float) @ (
            values / float(self.normalization_v)
        )
        potential_nodes = np.zeros_like(z)
        zero_index = int(np.flatnonzero(z == 0.0)[0])
        for index in range(zero_index + 1, len(z)):
            step = z[index] - z[index - 1]
            potential_nodes[index] = potential_nodes[index - 1] - 0.5 * (
                ez[index - 1] + ez[index]
            ) * step
        for index in range(zero_index - 1, -1, -1):
            step = z[index + 1] - z[index]
            potential_nodes[index] = potential_nodes[index + 1] + 0.5 * (
                ez[index + 1] + ez[index]
            ) * step
        steps = np.diff(z)
        coefficients = np.vstack((
            -0.5 * np.diff(ez) / steps,
            -ez[:-1],
            potential_nodes[:-1],
        ))
        return PPoly(coefficients, z, extrapolate=False)


AxisBasis = AxisResponseBasis | AxisFieldResponseBasis


def load_axis_response_basis_csv(
    path: Path,
    *,
    normalization_v: float,
) -> tuple[AxisResponseBasis, AxisFieldResponseBasis]:
    """Load the canonical schema-2 potential+Ez axis response basis."""

    try:
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as exc:
        raise CandidateContractError(f"axis response basis is unreadable: {path}") from exc
    expected_columns = {
        "z_mm",
        *(column for group in GROUPS for column in (
            f"{group}_potential_v", f"{group}_ez_v_per_mm",
        )),
    }
    if not rows or set(rows[0]) != expected_columns:
        raise CandidateContractError(
            "axis response basis columns differ from the field-consistent B--E contract"
        )
    z = np.asarray([float(row["z_mm"]) for row in rows], dtype=float)
    potential_response = np.asarray([
        [float(row[f"{group}_potential_v"]) for group in GROUPS]
        for row in rows
    ], dtype=float)
    ez_response = np.asarray([
        [float(row[f"{group}_ez_v_per_mm"]) for group in GROUPS]
        for row in rows
    ], dtype=float)
    if (
        not np.all(np.isfinite(z))
        or not np.all(np.isfinite(potential_response))
        or not np.all(np.isfinite(ez_response))
        or not np.all(np.diff(z) > 0.0)
    ):
        raise CandidateContractError("axis response basis contains invalid or unordered samples")
    return (
        AxisResponseBasis(z, potential_response, normalization_v),
        AxisFieldResponseBasis(z, ez_response, normalization_v),
    )


def _first_turn(interpolator: CubicSpline | PPoly, energy: float, direction: int, z_limit: float) -> float:
    roots = np.asarray(
        interpolator.solve(y=float(energy), discontinuity=False, extrapolate=False),
        dtype=float,
    )
    if direction > 0:
        candidates = roots[(roots > 0.0) & (roots <= z_limit)]
    else:
        candidates = roots[(roots < 0.0) & (roots >= z_limit)]
    if len(candidates):
        return float(candidates[np.argmin(np.abs(candidates))])
    raise CandidateContractError("real-field voltage trial has no retained first mirror turn")


def reduced_period_from_basis(
    basis: AxisBasis, energy_ev: float, voltages_v: Sequence[float],
) -> tuple[float, tuple[float, float]]:
    energy = float(energy_ev)
    if not math.isfinite(energy) or energy <= 0.0:
        raise CandidateContractError("real-field mirror energy must be positive")
    potential = basis.potential(voltages_v)
    left = _first_turn(potential, energy, -1, float(basis.z_mm[0]))
    right = _first_turn(potential, energy, 1, float(basis.z_mm[-1]))

    def side(turn: float) -> float:
        length = abs(turn)
        sign = 1.0 if turn > 0.0 else -1.0
        derivative = abs(float(potential.derivative()(turn)))
        if derivative <= 0.0:
            raise CandidateContractError("real-field mirror turn is not a simple crossing")

        def integrand(t: float) -> float:
            if t <= 1e-10:
                return 2.0 * math.sqrt(length / derivative)
            z = turn - sign * length * t * t
            kinetic = energy - float(potential(z))
            negative_tolerance = max(1.0e-12, energy * 1.0e-12)
            if kinetic < -negative_tolerance:
                raise CandidateContractError(
                    "real-field period path contains materially negative kinetic energy"
                )
            return 2.0 * length * t / math.sqrt(max(kinetic, 1e-14))

        with warnings.catch_warnings():
            warnings.simplefilter("error", IntegrationWarning)
            try:
                return float(quad(integrand, 0.0, 1.0, epsabs=1e-7, epsrel=1e-8, limit=200)[0])
            except IntegrationWarning as exc:
                raise CandidateContractError("real-field period quadrature did not converge") from exc

    return side(left) + side(right), (left, right)


def normalized_slopes(
    basis: AxisBasis,
    voltages_v: Sequence[float],
    energies_ev: Sequence[float],
    derivative_step_ev: float,
) -> tuple[float, float, float]:
    if len(energies_ev) != 3:
        raise CandidateContractError("real-field mirror solve needs three energy nodes")
    slopes = []
    for energy in energies_ev:
        low = reduced_period_from_basis(basis, energy - derivative_step_ev, voltages_v)[0]
        mid = reduced_period_from_basis(basis, energy, voltages_v)[0]
        high = reduced_period_from_basis(basis, energy + derivative_step_ev, voltages_v)[0]
        slopes.append((high - low) / (2.0 * derivative_step_ev * mid))
    return tuple(slopes)  # type: ignore[return-value]


def solve_l0_family(
    basis: AxisBasis,
    energies_ev: Sequence[float],
    derivative_step_ev: float,
    base_voltages_v: Sequence[float],
    voltage_bounds_v: Mapping[str, Sequence[float]],
    maximum_abs_normalized_period_slope_per_v: float,
    numerical_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Solve B--D on deterministic E slices, preserving the L0 nullity."""
    slope_tolerance = float(maximum_abs_normalized_period_slope_per_v)
    if not math.isfinite(slope_tolerance) or slope_tolerance <= 0.0:
        raise CandidateContractError("real-field mirror slope tolerance must be positive")
    lower = np.array([float(voltage_bounds_v[group][0]) for group in GROUPS])
    upper = np.array([float(voltage_bounds_v[group][1]) for group in GROUPS])
    raw_base = np.asarray(tuple(base_voltages_v), dtype=float)
    e_slice_count = int(numerical_profile["e_voltage_slice_count"])
    jacobian_relative_step = float(numerical_profile["voltage_jacobian_relative_step"])
    solver_tolerance = float(numerical_profile["least_squares_relative_tolerance"])
    maximum_evaluations = int(
        numerical_profile["maximum_function_evaluations_per_e_slice"]
    )
    if (
        raw_base.shape != (4,)
        or e_slice_count < 3
        or jacobian_relative_step <= 0.0
        or solver_tolerance <= 0.0
        or maximum_evaluations < 1
        or numerical_profile.get("voltage_jacobian_scheme") != "three_point_central"
        or numerical_profile.get("continuation_predictor")
        != "implicit_tangent_from_three_slope_jacobian"
    ):
        raise CandidateContractError("real-field family input dimensions are invalid")
    if not np.all(np.isfinite(raw_base)) or not lower[3] <= raw_base[3] <= upper[3]:
        raise CandidateContractError("real-field family insertion E voltage is outside its bounds")
    base = np.concatenate((np.clip(raw_base[:3], lower[:3], upper[:3]), raw_base[3:]))
    uniform_e_values = np.linspace(lower[3], upper[3], e_slice_count)
    e_values = np.unique(np.append(uniform_e_values, base[3]))
    base_slopes = normalized_slopes(
        basis, base, energies_ev, derivative_step_ev,
    )
    base_periods_and_turns = [
        reduced_period_from_basis(basis, energy, base) for energy in energies_ev
    ]

    def unscaled_residual(values: Sequence[float], e_voltage: float) -> np.ndarray:
        return np.asarray(normalized_slopes(
            basis, (*values, float(e_voltage)), energies_ev, derivative_step_ev,
        ))

    def predictor(
        values: np.ndarray, source_e: float, target_e: float,
    ) -> tuple[np.ndarray, float | None, str]:
        point = np.asarray((*values, source_e), dtype=float)
        columns = []
        for index in range(4):
            step = jacobian_relative_step * max(abs(float(point[index])), 1.0)
            low_point = point.copy()
            high_point = point.copy()
            low_point[index] = max(float(lower[index]), float(point[index] - step))
            high_point[index] = min(float(upper[index]), float(point[index] + step))
            width = float(high_point[index] - low_point[index])
            if width <= 0.0:
                raise CandidateContractError("real-field family predictor has no voltage stencil")
            try:
                low_residual = unscaled_residual(low_point[:3], float(low_point[3]))
                high_residual = unscaled_residual(high_point[:3], float(high_point[3]))
            except CandidateContractError:
                return (
                    values.copy(),
                    None,
                    "invalid_stencil_fallback_to_previous_solution",
                )
            columns.append((high_residual - low_residual) / width)
        jacobian = np.column_stack(columns)
        bcd_jacobian = jacobian[:, :3]
        if np.linalg.matrix_rank(bcd_jacobian) != 3:
            return (
                values.copy(),
                None,
                "rank_deficient_fallback_to_previous_solution",
            )
        tangent = -np.linalg.solve(bcd_jacobian, jacobian[:, 3])
        predicted = values + tangent * (target_e - source_e)
        return (
            np.clip(predicted, lower[:3], upper[:3]),
            float(np.linalg.cond(bcd_jacobian)),
            "implicit_tangent",
        )

    def solve_slice(
        e_voltage: float,
        start: np.ndarray,
        *,
        continuation_branch: str,
        continuation_order: int,
        seed_e_voltage_v: float,
        predictor_condition_number: float | None,
        predictor_status: str,
    ) -> tuple[dict[str, Any], np.ndarray]:
        def residual(values: np.ndarray) -> np.ndarray:
            try:
                return 1e7 * np.asarray(normalized_slopes(
                    basis, (*values, float(e_voltage)), energies_ev, derivative_step_ev,
                ))
            except CandidateContractError:
                return np.full(3, 1e6)

        solution = least_squares(
            residual, start, bounds=(lower[:3], upper[:3]),
            x_scale=np.maximum(upper[:3] - lower[:3], 1.0),
            jac="3-point",
            diff_step=jacobian_relative_step,
            max_nfev=maximum_evaluations,
            ftol=solver_tolerance,
            xtol=solver_tolerance,
            gtol=solver_tolerance,
        )
        voltages = [*map(float, solution.x), float(e_voltage)]
        evaluable = False
        try:
            slopes = normalized_slopes(basis, voltages, energies_ev, derivative_step_ev)
            periods_and_turns = [reduced_period_from_basis(basis, energy, voltages) for energy in energies_ev]
            evaluable = True
            feasible = bool(solution.success and max(abs(value) for value in slopes) <= slope_tolerance)
        except CandidateContractError:
            slopes = (None, None, None)
            periods_and_turns = []
            feasible = False
        member = {
            "mirror_voltages_v": [0.0, *voltages],
            "normalized_period_slopes_per_v": list(slopes),
            "reduced_periods_mm_per_sqrt_v": [item[0] for item in periods_and_turns],
            "turning_points_mm": [list(item[1]) for item in periods_and_turns],
            "optimizer_success": bool(solution.success),
            "optimizer_message": str(solution.message),
            "function_evaluations": int(solution.nfev),
            "optimizer_cost": float(solution.cost),
            "optimizer_optimality": float(solution.optimality),
            "l0_feasible": feasible,
            "e_voltage_v": float(e_voltage),
            "continuation_branch": continuation_branch,
            "continuation_order": int(continuation_order),
            "seed_e_voltage_v": float(seed_e_voltage_v),
            "predictor_condition_number": predictor_condition_number,
            "predictor_status": predictor_status,
        }
        next_start = solution.x if evaluable and np.all(np.isfinite(solution.x)) else start
        return member, np.asarray(next_start, dtype=float)

    members = []
    base_member, center_start = solve_slice(
        float(base[3]), base[:3], continuation_branch="inserted_seed_slice",
        continuation_order=0, seed_e_voltage_v=float(base[3]),
        predictor_condition_number=None,
        predictor_status="not_applicable_seed_slice",
    )
    members.append(base_member)
    below = sorted((value for value in e_values if value < base[3]), reverse=True)
    above = sorted(value for value in e_values if value > base[3])
    for branch, direction in (("lower_E", below), ("upper_E", above)):
        start = center_start.copy()
        seed_e = float(base[3])
        for order, e_voltage in enumerate(direction, start=1):
            predicted_start, predictor_condition_number, predictor_status = predictor(
                start, seed_e, float(e_voltage),
            )
            member, next_start = solve_slice(
                float(e_voltage), predicted_start, continuation_branch=branch,
                continuation_order=order, seed_e_voltage_v=seed_e,
                predictor_condition_number=predictor_condition_number,
                predictor_status=predictor_status,
            )
            members.append(member)
            if member["reduced_periods_mm_per_sqrt_v"]:
                seed_e = float(e_voltage)
            start = next_start
    members.sort(key=lambda item: item["mirror_voltages_v"][-1])
    for index, member in enumerate(members):
        member["e_slice_index"] = index
    member_e_values = np.asarray([item["e_voltage_v"] for item in members], dtype=float)
    if not np.array_equal(member_e_values, e_values):
        raise CandidateContractError("real-field family did not evaluate every declared E slice exactly once")
    feasible_members = [item for item in members if item["l0_feasible"]]
    axis_period_authority = (
        "integrated_piecewise_linear_sampled_Ez"
        if isinstance(basis, AxisFieldResponseBasis)
        else "cubic_spline_sampled_potential_nodes"
    )
    return {
        "schema_version": 1,
        "role": "mrtof_real_3d_mirror_l0_voltage_family",
        "status": "l0_family_found__l1_and_native_flight_pending" if feasible_members else "no_l0_family_member_found",
        "qualification": "sampled_0p5mm_axis_surrogate__not_a_simion_operating_point",
        "axis_period_authority": axis_period_authority,
        "e_voltage_slices_v": list(map(float, e_values)),
        "uniform_e_slice_count": int(e_slice_count),
        "actual_e_slice_count": int(len(e_values)),
        "inserted_seed_e_voltage_v": float(base[3]),
        "energy_centers_ev": list(map(float, energies_ev)),
        "period_slope_derivative_step_ev": float(derivative_step_ev),
        "maximum_abs_normalized_period_slope_per_v": slope_tolerance,
        "voltage_bounds_v": {key: list(map(float, value)) for key, value in voltage_bounds_v.items()},
        "family_nullity": 1,
        "numerics": {
            "voltage_jacobian_scheme": "three_point_central",
            "voltage_jacobian_relative_step": jacobian_relative_step,
            "least_squares_relative_tolerance": solver_tolerance,
            "maximum_function_evaluations_per_e_slice": maximum_evaluations,
            "requested_e_slice_count": int(e_slice_count),
            "continuation": "independent_lower_and_upper_e_sweeps_with_implicit_tangent_predictor",
        },
        "continuation_seed_point": {
            "source": "exact_k_analytic_2d",
            "used_as_seed_only": True,
            "mirror_voltages_v": [0.0, *map(float, base)],
            "normalized_period_slopes_per_v": list(base_slopes),
            "reduced_periods_mm_per_sqrt_v": [item[0] for item in base_periods_and_turns],
            "turning_points_mm": [list(item[1]) for item in base_periods_and_turns],
        },
        "member_count": len(members),
        "feasible_member_count": len(feasible_members),
        "members": members,
        "limitations": [
            "The axial surrogate does not evaluate gamma, transverse stability, Tbar_xx, or peak field.",
            "Every selected member requires native SIMION period and transverse-map validation.",
        ],
    }


def analyze_preserved_basis(
    basis_run: Path,
    exact_k_run: Path,
    contract_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Re-solve an immutable sampled response basis without reopening SIMION PAs."""
    root = basis_run.resolve()
    manifest = _object(root / "run_manifest.json", "response-basis run manifest")
    if (
        manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") != "real_3d_mirror_l0_voltage_family"
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("response basis must come from one successful managed run")

    def manifest_output(name: str) -> Path:
        path = (root / "results" / name).resolve()
        matches = [
            item for item in manifest.get("outputs", [])
            if isinstance(item, Mapping) and Path(str(item.get("path", ""))).resolve() == path
        ]
        if len(matches) != 1 or not path.is_file():
            raise CandidateContractError(f"response-basis output is not uniquely manifest-bound: {name}")
        if str(matches[0].get("sha256", "")).upper() != file_sha256(path):
            raise CandidateContractError(f"response-basis output hash differs: {name}")
        return path

    basis_path = manifest_output("real_3d_mirror_axis_response_basis.csv")
    receipt = _object(
        manifest_output("mirror_response_sampling_receipt.json"), "response sampling receipt",
    )
    numerical_profile = load_numerical_profile(contract_path)
    if (
        receipt.get("role") != "mrtof_real_3d_mirror_axis_response_sampling_plan"
        or receipt.get("status") != "sampled"
        or float(receipt.get("sample_step_mm"))
        != float(numerical_profile["response_grid_spacing_mm"])
        or int(receipt.get("axis_basis_schema_version", 0)) != 2
        or receipt.get("axis_period_authority")
        != "integrated_piecewise_linear_sampled_Ez"
        or receipt.get("sampled_axis_quantities") != ["potential_v", "ez_v_per_mm"]
    ):
        raise CandidateContractError(
            "response basis grid or field-consistent schema differs from the baseline contract"
        )
    _potential_basis, basis = load_axis_response_basis_csv(
        basis_path,
        normalization_v=float(receipt["basis_normalization_v"]),
    )

    loaded = load_exact_k_point(exact_k_run)
    l0 = loaded["l0"]
    energies = [float(value) for value in l0["three_point"]["energies_v"]]
    base_voltages = [float(value) for value in loaded["point"]["mirror_voltages_v"]]
    bounds = {
        "mirror_B": [-10000.0, energies[0]],
        "mirror_C": [-5000.0, energies[0]],
        "mirror_D": [-5000.0, energies[0]],
        "mirror_E": [energies[-1] + 1e-6, 10000.0],
    }
    report = solve_l0_family(
        basis,
        energies,
        float(l0["period_slope_derivative_step_v"]),
        base_voltages[1:],
        bounds,
        float(l0["maximum_abs_normalized_period_slope_per_v"]),
        numerical_profile,
    )
    report.update({
        "probe_y_mm": float(receipt["probe_y_mm"]),
        "sample_step_mm": float(receipt["sample_step_mm"]),
        "source_exact_k_run_id": loaded["manifest"]["run_id"],
        "source_response_basis_run_id": manifest["run_id"],
        "source_response_basis_sha256": file_sha256(basis_path),
        "source_contract_sha256": file_sha256(contract_path),
        "source_response_basis_contract_sha256": receipt["source_contract_sha256"],
        "basis_cache_generations": receipt["cache_generations"],
        "axis_response_basis_filename": basis_path.name,
        "axis_basis_schema_version": int(receipt["axis_basis_schema_version"]),
        "sampled_axis_quantities": list(receipt["sampled_axis_quantities"]),
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basis-run", type=Path, required=True)
    parser.add_argument("--exact-k-run", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze_preserved_basis(
        args.basis_run, args.exact_k_run, args.contract, args.output,
    )
    print(
        "MRTOF_REAL_FIELD_MIRROR_L0_REUSE="
        f"{report['status']} FEASIBLE={report['feasible_member_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
