"""Predict fixed-grid mirror-voltage corrections without a 0.25-mm PA family.

The coarse 0.5-mm B--E response basis supplies local derivatives.  Fixed-grid
operating points successively constrain the fine-minus-coarse discrepancy while
preserving every independent earlier voltage chord.  The three L0 period slopes
remain a rank-three system with a one-dimensional voltage-family null space;
mean directional trace-half selects a point only along that null space.  Every
output remains a proposal requiring a new fixed-grid SIMION validation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from scipy.optimize import brentq, least_squares, root as scipy_root

from common.contracts.file_identity import file_sha256
from common.host_resource_python import ensure_heavy_entry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_screen import (
    CombinedField,
    ResponseBasis,
    l1_probe_at_energy,
    load_response_basis_csv,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family import (
    GROUPS,
    load_axis_response_basis_csv,
    normalized_slopes,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


_WORKER_BASIS: ResponseBasis | None = None
_WORKER_ENERGY: float | None = None
_WORKER_POSITION_PROBE_MM: float | None = None
_WORKER_ANGLE_PROBE_RAD: float | None = None
_WORKER_TRACE_CONTROLS: Mapping[str, Any] | None = None
_WORKER_L0_AXIS_BASIS: Any | None = None
_WORKER_L0_ENERGIES: tuple[float, ...] | None = None
_WORKER_L0_DERIVATIVE_STEP: float | None = None
_WORKER_L0_SLOPE_DISCREPANCY: np.ndarray | None = None
_WORKER_L0_LOWER: np.ndarray | None = None
_WORKER_L0_UPPER: np.ndarray | None = None
_WORKER_L0_START: np.ndarray | None = None
_WORKER_L0_RELATIVE_STEP: float | None = None
_WORKER_L0_TOLERANCE: float | None = None
_WORKER_L0_MAX_NFEV: int | None = None
_WORKER_L0_RESIDUAL_GATE: float | None = None


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object")
    return value


def _initialize_gamma_worker(
    basis: ResponseBasis,
    energy: float,
    position_probe_mm: float,
    angle_probe_rad: float,
    trace_controls: Mapping[str, Any],
) -> None:
    global _WORKER_BASIS, _WORKER_ENERGY
    global _WORKER_POSITION_PROBE_MM, _WORKER_ANGLE_PROBE_RAD
    global _WORKER_TRACE_CONTROLS
    _WORKER_BASIS = basis
    _WORKER_ENERGY = energy
    _WORKER_POSITION_PROBE_MM = position_probe_mm
    _WORKER_ANGLE_PROBE_RAD = angle_probe_rad
    _WORKER_TRACE_CONTROLS = trace_controls


def _gamma_job(job: tuple[int, int, tuple[float, ...]]) -> tuple[int, int, float]:
    axis, sign, voltages = job
    if (
        _WORKER_BASIS is None
        or _WORKER_ENERGY is None
        or _WORKER_POSITION_PROBE_MM is None
        or _WORKER_ANGLE_PROBE_RAD is None
        or _WORKER_TRACE_CONTROLS is None
    ):
        raise CandidateContractError("gamma-gradient worker was not initialized")
    field = CombinedField(_WORKER_BASIS, voltages)
    traces = []
    for direction in (-1, 1):
        record = l1_probe_at_energy(
            field,
            energy_per_charge_v=_WORKER_ENERGY,
            launch_direction=direction,
            position_probe_mm=_WORKER_POSITION_PROBE_MM,
            angle_probe_rad=_WORKER_ANGLE_PROBE_RAD,
            trace_controls=_WORKER_TRACE_CONTROLS,
        )
        if not record["stable"] or record["trace_half"] is None:
            raise CandidateContractError("gamma-gradient probe left the stable branch")
        traces.append(float(record["trace_half"]))
    return axis, sign, float(sum(traces) / len(traces))


def _solve_corrected_l0_slice(
    axis_basis: Any,
    energies: tuple[float, ...],
    derivative_step: float,
    slope_discrepancy: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    start: np.ndarray,
    relative_step: float,
    tolerance: float,
    maximum_function_evaluations: int,
    residual_gate: float,
    e_voltage: float,
) -> np.ndarray:
    """Close one independent corrected L0 B--D slice at a fixed E voltage."""

    def residual(values: np.ndarray) -> np.ndarray:
        trial = np.asarray((*values, e_voltage), dtype=float)
        return np.asarray(
            normalized_slopes(axis_basis, trial, energies, derivative_step), dtype=float,
        ) + slope_discrepancy

    solution = least_squares(
        lambda values: 1.0e7 * residual(values),
        start,
        bounds=(lower[:3], upper[:3]),
        x_scale=np.maximum(upper[:3] - lower[:3], 1.0),
        jac="3-point",
        diff_step=relative_step,
        ftol=tolerance,
        xtol=tolerance,
        gtol=tolerance,
        max_nfev=maximum_function_evaluations,
    )
    refinement = scipy_root(
        lambda values: 1.0e8 * residual(values),
        solution.x,
        method="hybr",
        options={"xtol": tolerance, "maxfev": maximum_function_evaluations},
    )
    trial = np.asarray((*refinement.x, e_voltage), dtype=float)
    if (
        not solution.success
        or not np.all(np.isfinite(trial))
        or np.any(trial[:3] < lower[:3])
        or np.any(trial[:3] > upper[:3])
        or np.max(np.abs(residual(trial[:3]))) > residual_gate
    ):
        raise CandidateContractError("nonlinear corrected L0 slice did not close")
    return trial


def _initialize_l0_slice_worker(
    axis_basis: Any,
    energies: tuple[float, ...],
    derivative_step: float,
    slope_discrepancy: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    start: np.ndarray,
    relative_step: float,
    tolerance: float,
    maximum_function_evaluations: int,
    residual_gate: float,
) -> None:
    """Install immutable corrected-L0 data once per independent slice worker."""
    global _WORKER_L0_AXIS_BASIS, _WORKER_L0_ENERGIES, _WORKER_L0_DERIVATIVE_STEP
    global _WORKER_L0_SLOPE_DISCREPANCY, _WORKER_L0_LOWER, _WORKER_L0_UPPER
    global _WORKER_L0_START, _WORKER_L0_RELATIVE_STEP, _WORKER_L0_TOLERANCE
    global _WORKER_L0_MAX_NFEV, _WORKER_L0_RESIDUAL_GATE
    _WORKER_L0_AXIS_BASIS = axis_basis
    _WORKER_L0_ENERGIES = energies
    _WORKER_L0_DERIVATIVE_STEP = derivative_step
    _WORKER_L0_SLOPE_DISCREPANCY = slope_discrepancy
    _WORKER_L0_LOWER = lower
    _WORKER_L0_UPPER = upper
    _WORKER_L0_START = start
    _WORKER_L0_RELATIVE_STEP = relative_step
    _WORKER_L0_TOLERANCE = tolerance
    _WORKER_L0_MAX_NFEV = maximum_function_evaluations
    _WORKER_L0_RESIDUAL_GATE = residual_gate


def _l0_slice_job(e_voltage: float) -> tuple[float, tuple[float, ...] | None, str | None]:
    """Evaluate one coarse family slice without making a failed slice fatal."""
    values = (
        _WORKER_L0_AXIS_BASIS, _WORKER_L0_ENERGIES, _WORKER_L0_DERIVATIVE_STEP,
        _WORKER_L0_SLOPE_DISCREPANCY, _WORKER_L0_LOWER, _WORKER_L0_UPPER,
        _WORKER_L0_START, _WORKER_L0_RELATIVE_STEP, _WORKER_L0_TOLERANCE,
        _WORKER_L0_MAX_NFEV, _WORKER_L0_RESIDUAL_GATE,
    )
    if any(value is None for value in values):
        raise CandidateContractError("corrected-L0 slice worker was not initialized")
    try:
        trial = _solve_corrected_l0_slice(*values, e_voltage)
    except CandidateContractError as exc:
        return float(e_voltage), None, str(exc)
    return float(e_voltage), tuple(float(value) for value in trial), None


def decompose_l0_l1_correction(
    slope_jacobian_per_v2: Sequence[Sequence[float]],
    gamma_gradient_per_v: Sequence[float],
    fine_slope_residuals_per_v: Sequence[float],
    fine_gamma_trace_residual: float,
) -> dict[str, Any]:
    """Correct L0 first, then move only along its null space for L1."""

    jacobian = np.asarray(slope_jacobian_per_v2, dtype=float)
    gamma_gradient = np.asarray(gamma_gradient_per_v, dtype=float)
    slopes = np.asarray(fine_slope_residuals_per_v, dtype=float)
    if (
        jacobian.shape != (3, 4)
        or gamma_gradient.shape != (4,)
        or slopes.shape != (3,)
        or not np.all(np.isfinite(jacobian))
        or not np.all(np.isfinite(gamma_gradient))
        or not np.all(np.isfinite(slopes))
        or not math.isfinite(float(fine_gamma_trace_residual))
    ):
        raise CandidateContractError("fixed-grid correction arrays are invalid")
    u, singular, vt = np.linalg.svd(jacobian, full_matrices=True)
    rank = int(np.linalg.matrix_rank(jacobian))
    if rank != 3 or singular[-1] <= 0.0:
        raise CandidateContractError("three-slope Jacobian does not retain rank three")
    particular = -np.linalg.pinv(jacobian) @ slopes
    null = vt[-1].copy()
    if null[3] < 0.0:
        null *= -1.0
    null /= np.linalg.norm(null)
    directional_gamma_derivative = float(gamma_gradient @ null)
    if abs(directional_gamma_derivative) <= np.finfo(float).eps:
        raise CandidateContractError("gamma is stationary along the L0 voltage family")
    gamma_after_l0 = float(fine_gamma_trace_residual + gamma_gradient @ particular)
    null_coordinate = -gamma_after_l0 / directional_gamma_derivative
    correction = particular + null_coordinate * null
    augmented = np.vstack((jacobian, gamma_gradient))
    if np.linalg.matrix_rank(augmented) != 4:
        raise CandidateContractError("L0-family plus L1-selector Jacobian is rank deficient")
    return {
        "l0_jacobian_rank": rank,
        "l0_family_nullity": 1,
        "l0_jacobian_singular_values": singular.tolist(),
        "l0_jacobian_condition_number": float(singular[0] / singular[-1]),
        "l0_particular_voltage_correction_v": particular.tolist(),
        "l0_null_unit_vector": null.tolist(),
        "gamma_derivative_along_l0_family_per_v": directional_gamma_derivative,
        "gamma_trace_after_l0_particular": gamma_after_l0,
        "l1_null_coordinate_v": float(null_coordinate),
        "voltage_correction_v": correction.tolist(),
        "linearized_slope_residuals_per_v": (slopes + jacobian @ correction).tolist(),
        "linearized_gamma_trace_residual": float(
            fine_gamma_trace_residual + gamma_gradient @ correction
        ),
        "augmented_jacobian_rank": int(np.linalg.matrix_rank(augmented)),
        "augmented_jacobian_condition_number": float(np.linalg.cond(augmented)),
    }


def rank_one_secant_update(
    base_jacobian: Sequence[Sequence[float]] | Sequence[float],
    voltage_step_v: Sequence[float],
    observed_response_step: Sequence[float],
) -> np.ndarray:
    """Apply the minimum-Frobenius-norm update satisfying one secant equation."""

    jacobian = np.asarray(base_jacobian, dtype=float)
    step = np.asarray(voltage_step_v, dtype=float)
    observed = np.asarray(observed_response_step, dtype=float)
    if (
        step.shape != (4,)
        or jacobian.shape[-1:] != (4,)
        or observed.shape != jacobian.shape[:-1]
        or not np.all(np.isfinite(jacobian))
        or not np.all(np.isfinite(step))
        or not np.all(np.isfinite(observed))
    ):
        raise CandidateContractError("secant-update arrays are invalid")
    denominator = float(step @ step)
    if denominator <= np.finfo(float).eps:
        raise CandidateContractError("secant voltage step is zero")
    mismatch = observed - jacobian @ step
    return jacobian + np.multiply.outer(mismatch, step) / denominator


def constrained_secant_update(
    base_jacobian: Sequence[Sequence[float]] | Sequence[float],
    preserved_voltage_steps_v: Sequence[Sequence[float]],
    new_voltage_step_v: Sequence[float],
    observed_new_response_step: Sequence[float],
) -> np.ndarray:
    """Add one secant while preserving all independent earlier secants."""

    jacobian = np.asarray(base_jacobian, dtype=float)
    preserved = np.asarray(preserved_voltage_steps_v, dtype=float)
    step = np.asarray(new_voltage_step_v, dtype=float)
    observed = np.asarray(observed_new_response_step, dtype=float)
    if preserved.ndim != 2 or preserved.shape[1] != 4:
        raise CandidateContractError("preserved secant steps must have shape N-by-4")
    if jacobian.shape[-1:] != (4,) or step.shape != (4,):
        raise CandidateContractError("constrained-secant arrays are invalid")
    if observed.shape != jacobian.shape[:-1] or not all(
        np.all(np.isfinite(value)) for value in (jacobian, preserved, step, observed)
    ):
        raise CandidateContractError("constrained-secant values are invalid")
    if preserved.shape[0] == 0:
        return rank_one_secant_update(jacobian, step, observed)
    if np.linalg.matrix_rank(preserved) != preserved.shape[0]:
        raise CandidateContractError("preserved secant steps are linearly dependent")
    projector = preserved.T @ np.linalg.pinv(preserved @ preserved.T) @ preserved
    orthogonal_step = step - projector @ step
    denominator = float(orthogonal_step @ step)
    if denominator <= np.finfo(float).eps:
        raise CandidateContractError("new secant adds no independent voltage direction")
    mismatch = observed - jacobian @ step
    updated = jacobian + np.multiply.outer(mismatch, orthogonal_step) / denominator
    if not np.allclose(
        updated @ preserved.T,
        jacobian @ preserved.T,
        rtol=1e-10,
        atol=1e-12,
    ):
        raise CandidateContractError("constrained update changed a preserved secant")
    return updated


def slope_voltage_jacobian(
    axis_basis: Mapping[str, np.ndarray],
    voltages_v: Sequence[float],
    energies_v: Sequence[float],
    derivative_step_v: float,
    relative_voltage_step: float,
) -> np.ndarray:
    """Evaluate the coarse three-slope by four-voltage central Jacobian."""

    voltages = np.asarray(voltages_v, dtype=float)
    if voltages.shape != (4,) or relative_voltage_step <= 0.0:
        raise CandidateContractError("slope-Jacobian controls are invalid")
    jacobian = np.zeros((3, 4), dtype=float)
    for index in range(4):
        step = relative_voltage_step * max(abs(float(voltages[index])), 1.0)
        low, high = voltages.copy(), voltages.copy()
        low[index] -= step
        high[index] += step
        jacobian[:, index] = (
            np.asarray(normalized_slopes(axis_basis, high, energies_v, derivative_step_v))
            - np.asarray(normalized_slopes(axis_basis, low, energies_v, derivative_step_v))
        ) / (2.0 * step)
    return jacobian


def _fine_gamma_trace(fixed_l1: Mapping[str, Any], nominal_energy: float) -> float:
    directions = fixed_l1.get("directions")
    if not isinstance(directions, Mapping):
        raise CandidateContractError("fixed-grid L1 result lacks directions")
    traces = []
    for direction in (-1, 1):
        energy_map = directions.get(str(direction))
        if not isinstance(energy_map, Mapping):
            raise CandidateContractError("fixed-grid L1 direction is missing")
        matches = [
            value for key, value in energy_map.items()
            if math.isclose(float(key), nominal_energy, rel_tol=0.0, abs_tol=1e-9)
        ]
        if len(matches) != 1 or not isinstance(matches[0], Mapping):
            raise CandidateContractError("fixed-grid nominal-energy L1 record is not unique")
        scales = matches[0].get("scales")
        if not isinstance(scales, list) or not scales:
            raise CandidateContractError("fixed-grid nominal-energy L1 scales are missing")
        trace = scales[-1].get("trace_half")
        if trace is None or not math.isfinite(float(trace)):
            raise CandidateContractError("fixed-grid nominal-energy trace-half is invalid")
        traces.append(float(trace))
    return float(sum(traces) / len(traces))


def _native_gamma_trace(
    native_l1: Mapping[str, Any], native_probe: Mapping[str, Any], nominal_energy: float,
) -> float:
    """Return the mean native-SIMION trace selector after identity checks."""

    if (
        native_l1.get("role") != "mrtof_native_simion_transverse_l1_analysis"
        or native_l1.get("status") != "native_l1_diagnostic_complete"
        or native_probe.get("role") != "mrtof_native_simion_transverse_l1_probe"
        or native_probe.get("status") != "prepared"
        or native_l1.get("source_native_l1_probe_contract_sha256")
        != file_sha256(Path(native_probe["_path"]))
    ):
        raise CandidateContractError("native fixed-grid L1 identity is invalid")
    if (
        not math.isclose(float(native_l1.get("nominal_energy_ev")), nominal_energy, abs_tol=1e-9)
        or not math.isclose(float(native_probe.get("nominal_energy_ev")), nominal_energy, abs_tol=1e-9)
        or not isinstance(native_l1.get("directions"), Mapping)
    ):
        raise CandidateContractError("native fixed-grid L1 nominal energy is incompatible")
    traces = []
    for direction in (-1, 1):
        record = native_l1["directions"].get(str(direction))
        if not isinstance(record, Mapping) or not bool(record.get("stable")):
            raise CandidateContractError("native fixed-grid L1 direction is not stable")
        trace = record.get("trace_half")
        if trace is None or not math.isfinite(float(trace)):
            raise CandidateContractError("native fixed-grid L1 trace-half is invalid")
        traces.append(float(trace))
    return float(sum(traces) / len(traces))


def _source_fixed_grid_gamma_trace(source: Mapping[str, Any]) -> float:
    """Return the frozen base selector measured by the source correction.

    A secant must compare the same measurement operator at both endpoints.
    In particular, a native-SIMION base selector cannot be silently replaced
    by the older sampled-field L1 diagnostic merely because both report a
    trace-half value.
    """

    value = source.get("fixed_grid_mean_directional_trace_half")
    if value is None or not math.isfinite(float(value)):
        raise CandidateContractError(
            "source correction lacks its authoritative fixed-grid gamma trace"
        )
    return float(value)


NATIVE_GAMMA_OPERATOR_ID = "native_simion_transverse_l1_mean_directional_trace_half_v1"
SAMPLED_GAMMA_OPERATOR_ID = "sampled_fixed_operating_field_l1_mean_directional_trace_half_v1"


def _source_gamma_operator_id(source: Mapping[str, Any]) -> str:
    """Return the frozen endpoint operator, with explicit legacy inference."""

    value = source.get("fixed_grid_gamma_operator_id")
    if value is None:
        inputs = source.get("inputs")
        if not isinstance(inputs, Mapping):
            raise CandidateContractError("source correction lacks its gamma operator identity")
        has_native = bool(inputs.get("native_l1_sha256")) and bool(
            inputs.get("native_l1_probe_sha256")
        )
        value = NATIVE_GAMMA_OPERATOR_ID if has_native else SAMPLED_GAMMA_OPERATOR_ID
    if value not in {NATIVE_GAMMA_OPERATOR_ID, SAMPLED_GAMMA_OPERATOR_ID}:
        raise CandidateContractError("source correction gamma operator identity is unsupported")
    return str(value)


def _l1_gamma_operator_id(l1: Mapping[str, Any], has_native_probe: bool) -> str:
    """Classify one measured L1 endpoint without permitting mixed semantics."""

    if l1.get("role") == "mrtof_native_simion_transverse_l1_analysis":
        if not has_native_probe:
            raise CandidateContractError("native L1 endpoint requires its frozen probe")
        return NATIVE_GAMMA_OPERATOR_ID
    if has_native_probe:
        raise CandidateContractError("sampled-field L1 endpoint cannot carry a native probe")
    return SAMPLED_GAMMA_OPERATOR_ID


def _measured_chord_gamma_root(
    *,
    base_voltages: np.ndarray,
    secant_voltages: np.ndarray,
    base_slopes: np.ndarray,
    secant_slopes: np.ndarray,
    base_gamma: float,
    secant_gamma: float,
    slope_gate: float,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Interpolate a bounded gamma root only between two measured fine-grid points."""

    denominator = secant_gamma - base_gamma
    if not math.isfinite(denominator) or abs(denominator) <= 1e-15:
        raise CandidateContractError("measured fixed-grid chord has no gamma leverage")
    fraction = -base_gamma / denominator
    if not 0.0 < fraction < 1.0:
        raise CandidateContractError("measured fixed-grid chord does not bracket gamma zero")
    proposal = base_voltages + fraction * (secant_voltages - base_voltages)
    slopes = base_slopes + fraction * (secant_slopes - base_slopes)
    if (
        np.any(proposal < lower_bounds)
        or np.any(proposal > upper_bounds)
        or float(np.max(np.abs(slopes))) > slope_gate
    ):
        raise CandidateContractError(
            "measured fixed-grid gamma chord root violates voltage or physical L0 gates"
        )
    return proposal, slopes, float(fraction)


def _bounded_physical_gate_secant(
    *, source_voltages: np.ndarray, tangent_per_e: np.ndarray, direction: float,
    initial_e_step_v: float, shrink_factor: float, maximum_shrinks: int,
    lower_bounds_v: np.ndarray, upper_bounds_v: np.ndarray,
    maximum_voltage_step_v: float, slope_gate_per_v: float,
    slope_model: Callable[[np.ndarray], np.ndarray],
) -> tuple[np.ndarray, np.ndarray, float, int]:
    """Choose a local diagnostic tangent step without forcing numerical zero."""
    if (
        source_voltages.shape != (4,) or tangent_per_e.shape != (4,)
        or direction not in (-1.0, 1.0) or initial_e_step_v <= 0.0
        or not 0.0 < shrink_factor < 1.0 or maximum_shrinks < 0
        or maximum_voltage_step_v <= 0.0 or slope_gate_per_v <= 0.0
    ):
        raise CandidateContractError("diagnostic corrected-L0 secant controls are invalid")
    delta_e = direction * initial_e_step_v
    for shrink_count in range(maximum_shrinks + 1):
        trial = source_voltages + tangent_per_e * delta_e
        slopes = np.asarray(slope_model(trial), dtype=float)
        if (
            slopes.shape == (3,) and np.all(np.isfinite(trial)) and np.all(np.isfinite(slopes))
            and np.all(trial >= lower_bounds_v) and np.all(trial <= upper_bounds_v)
            and float(np.max(np.abs(trial - source_voltages))) <= maximum_voltage_step_v
            and float(np.max(np.abs(slopes))) <= slope_gate_per_v
        ):
            return trial, slopes, float(delta_e), shrink_count
        delta_e *= shrink_factor
    raise CandidateContractError("no bounded physical-gate corrected-L0 diagnostic secant exists")


def build_correction_proposal(
    *,
    refinement_path: Path,
    family_path: Path,
    axis_basis_path: Path,
    l1_basis_path: Path,
    sampling_plan_path: Path,
    fixed_probe_contract_path: Path,
    fixed_period_path: Path,
    fixed_l1_path: Path,
    fixed_project_contract_path: Path,
    project_contract_path: Path,
    output_path: Path,
    gamma_gradient_source_path: Path | None = None,
    native_l1_path: Path | None = None,
    native_l1_probe_path: Path | None = None,
) -> dict[str, Any]:
    refinement = _object(refinement_path, "coarse L1 refinement")
    family = _object(family_path, "coarse L0 family")
    plan = _object(sampling_plan_path, "coarse L1 sampling plan")
    probe = _object(fixed_probe_contract_path, "fixed-grid period probe")
    period = _object(fixed_period_path, "fixed-grid period result")
    fixed_l1 = _object(fixed_l1_path, "fixed-grid L1 result")
    if (native_l1_path is None) != (native_l1_probe_path is None):
        raise CandidateContractError("native fixed-grid L1 analysis and probe must be supplied together")
    native_l1 = _object(native_l1_path, "native fixed-grid L1 result") if native_l1_path else None
    native_probe = _object(native_l1_probe_path, "native fixed-grid L1 probe") if native_l1_probe_path else None
    if native_probe is not None:
        native_probe["_path"] = str(native_l1_probe_path)
    fixed_contract = _object(fixed_project_contract_path, "fixed-grid project contract")
    contract = _object(project_contract_path, "project contract")
    inputs = refinement.get("inputs")
    if (
        refinement.get("role") != "mrtof_real_3d_mirror_l1_continuous_family_refinement"
        or not isinstance(inputs, Mapping)
        or inputs.get("family_sha256") != file_sha256(family_path)
        or inputs.get("axis_basis_sha256") != file_sha256(axis_basis_path)
        or inputs.get("response_basis_sha256") != file_sha256(l1_basis_path)
        or inputs.get("sampling_plan_sha256") != file_sha256(sampling_plan_path)
    ):
        raise CandidateContractError("coarse refinement input identity is inconsistent")
    root_index = int(probe.get("selected_root_index", -1))
    roots = refinement.get("roots")
    if not isinstance(roots, list) or not 0 <= root_index < len(roots):
        raise CandidateContractError("fixed-grid probe does not select one coarse root")
    voltages_a_e = [float(value) for value in probe.get("mirror_voltages_v", [])]
    if (
        len(voltages_a_e) != 5
        or voltages_a_e[0] != 0.0
        or probe.get("source_real_field_l1_sha256") != file_sha256(refinement_path)
    ):
        raise CandidateContractError("fixed-grid voltage point does not retain its coarse-family provenance")
    if (
        fixed_l1.get("inputs", {}).get("period_probe_contract_sha256")
        != file_sha256(fixed_probe_contract_path)
        or fixed_l1.get("inputs", {}).get("project_contract_sha256")
        != file_sha256(fixed_project_contract_path)
        or period.get("energy_centers_ev") != probe.get("energy_centers_ev")
        or float(period.get("derivative_step_ev")) != float(probe.get("derivative_step_ev"))
        or float(period.get("probe_y_mm")) != float(probe.get("probe_y_mm"))
    ):
        raise CandidateContractError("fixed-grid L0/L1 evidence does not share one point identity")
    if native_probe is not None and (
        native_probe.get("source_period_probe_contract_sha256")
        != file_sha256(fixed_probe_contract_path)
        or [float(value) for value in native_probe.get("mirror_voltages_v", [])]
        != voltages_a_e
    ):
        raise CandidateContractError("native fixed-grid L1 probe differs from the fixed-grid voltage point")
    requirements = contract["mirror"]["theory_requirements"]
    fixed_requirements = fixed_contract["mirror"]["theory_requirements"]
    for key in ("l1_screen_profile", "real_3d_l1_screen_profile"):
        if fixed_requirements.get(key) != requirements.get(key):
            raise CandidateContractError(f"current and fixed-grid {key} contracts differ")
    if (
        fixed_contract.get("particle_source", {}).get("species")
        != contract.get("particle_source", {}).get("species")
        or fixed_contract.get("simion", {}).get("trajectory_profiles")
        != contract.get("simion", {}).get("trajectory_profiles")
    ):
        raise CandidateContractError("current and fixed-grid particle or trajectory contracts differ")
    profile = requirements["fixed_grid_multifidelity_correction_profile"]
    if (
        profile.get("slope_discrepancy_model")
        != "locally_constant_0p25_minus_0p5_at_one_fixed_operating_point"
        or profile.get("gamma_selector_coordinate")
        != "mean_directional_trace_half_at_nominal_energy_and_largest_probe_scale"
    ):
        raise CandidateContractError("fixed-grid correction profile is unsupported")
    normalization = float(plan["basis_normalization_v"])
    _potential_axis, axis_basis = load_axis_response_basis_csv(
        axis_basis_path, normalization_v=normalization,
    )
    l1_basis = load_response_basis_csv(
        l1_basis_path,
        normalization_v=normalization,
        probe_y_mm=float(plan["slice_y_mm"]),
    )
    energies = tuple(float(value) for value in family["energy_centers_ev"])
    derivative_step = float(family["period_slope_derivative_step_ev"])
    voltages = np.asarray(voltages_a_e[1:], dtype=float)
    coarse_slopes = np.asarray(
        normalized_slopes(axis_basis, voltages, energies, derivative_step), dtype=float,
    )
    fine_slopes = np.asarray(period["simion_normalized_period_slopes_per_v"], dtype=float)
    slope_discrepancy = fine_slopes - coarse_slopes
    relative_step = float(
        requirements["real_3d_l0_voltage_family_profile"]["voltage_jacobian_relative_step"]
    )
    slope_jacobian = slope_voltage_jacobian(
        axis_basis, voltages, energies, derivative_step, relative_step,
    )
    l1 = requirements["l1_screen_profile"]
    real = requirements["real_3d_l1_screen_profile"]
    trajectory_id = str(real["screen_trajectory_profile_id"])
    trajectory = contract["simion"]["trajectory_profiles"][trajectory_id]
    species = contract["particle_source"]["species"]
    largest_scale = max(float(value) for value in l1["probe_convergence_scale_factors"])
    trace_controls = {
        "particle_mass_th": float(species["mass_th"]),
        "particle_charge_e": float(species["charge_e"]),
        "relative_tolerance": float(real["surrogate_relative_tolerance"]),
        "absolute_tolerance": float(real["surrogate_absolute_tolerance"]),
        "maximum_step_us": float(trajectory["maximum_step_us"]),
        "maximum_leg_time_us": float(real["maximum_leg_time_us"]),
        "central_plane_offset_mm": float(real["central_plane_offset_mm"]),
    }
    gamma_step = float(profile["gamma_gradient_voltage_step_v"])
    expected_input_hashes = {
        "refinement_sha256": file_sha256(refinement_path),
        "family_sha256": file_sha256(family_path),
        "axis_basis_sha256": file_sha256(axis_basis_path),
        "l1_basis_sha256": file_sha256(l1_basis_path),
        "sampling_plan_sha256": file_sha256(sampling_plan_path),
        "fixed_probe_contract_sha256": file_sha256(fixed_probe_contract_path),
        "fixed_period_sha256": file_sha256(fixed_period_path),
        "fixed_l1_sha256": file_sha256(fixed_l1_path),
        "fixed_project_contract_sha256": file_sha256(fixed_project_contract_path),
    }
    if native_l1_path is not None and native_l1_probe_path is not None:
        expected_input_hashes["native_l1_sha256"] = file_sha256(native_l1_path)
        expected_input_hashes["native_l1_probe_sha256"] = file_sha256(native_l1_probe_path)
    gamma_gradient_source_sha256 = None
    if gamma_gradient_source_path is not None:
        source = _object(gamma_gradient_source_path, "gamma-gradient source")
        source_inputs = source.get("inputs")
        source_numerics = source.get("numerics")
        if (
            source.get("role") != "mrtof_fixed_grid_multifidelity_voltage_correction"
            or not isinstance(source_inputs, Mapping)
            or any(source_inputs.get(key) != value for key, value in expected_input_hashes.items())
            or not isinstance(source_numerics, Mapping)
            or float(source_numerics.get("gamma_voltage_jacobian_step_v")) != gamma_step
            or source_numerics.get("gamma_trajectory_profile_id") != trajectory_id
            or float(source_numerics.get("gamma_probe_scale")) != largest_scale
        ):
            raise CandidateContractError("gamma-gradient source identity is incompatible")
        gamma_gradient = np.asarray(source.get("coarse_gamma_gradient_per_v"), dtype=float)
        raw_samples = source.get("gamma_gradient_samples")
        if gamma_gradient.shape != (4,) or not np.all(np.isfinite(gamma_gradient)) or not isinstance(raw_samples, list):
            raise CandidateContractError("gamma-gradient source data is invalid")
        gamma_samples = [
            (
                int(item["electrode_index_b_to_e"]),
                int(item["sign"]),
                float(item["mean_trace_half"]),
            )
            for item in raw_samples
        ]
        if len(gamma_samples) != 8:
            raise CandidateContractError("gamma-gradient source stencil is incomplete")
        maximum_workers = 0
        gamma_gradient_source_sha256 = file_sha256(gamma_gradient_source_path)
    else:
        jobs = []
        for index in range(4):
            for sign in (-1, 1):
                trial = voltages.copy()
                trial[index] += sign * gamma_step
                jobs.append((index, sign, tuple(float(value) for value in trial)))
        maximum_workers = min(
            len(jobs), int(l1["maximum_parallel_workers"]), os.cpu_count() or 1,
        )
        with ProcessPoolExecutor(
            max_workers=maximum_workers,
            initializer=_initialize_gamma_worker,
            initargs=(
                l1_basis,
                float(energies[1]),
                float(l1["position_probe_mm"]) * largest_scale,
                float(l1["angle_probe_rad"]) * largest_scale,
                trace_controls,
            ),
        ) as executor:
            gamma_samples = list(executor.map(_gamma_job, jobs))
        gamma_by_axis_sign = {(axis, sign): value for axis, sign, value in gamma_samples}
        gamma_gradient = np.asarray([
            (gamma_by_axis_sign[(index, 1)] - gamma_by_axis_sign[(index, -1)])
            / (2.0 * gamma_step)
            for index in range(4)
        ])
    fine_gamma = (
        _native_gamma_trace(native_l1, native_probe, float(energies[1]))
        if native_l1 is not None and native_probe is not None
        else _fine_gamma_trace(fixed_l1, float(energies[1]))
    )
    gamma_operator_id = _l1_gamma_operator_id(
        native_l1 if native_l1 is not None else fixed_l1,
        native_probe is not None,
    )
    correction = decompose_l0_l1_correction(
        slope_jacobian, gamma_gradient, fine_slopes, fine_gamma,
    )
    linear_delta = np.asarray(correction["voltage_correction_v"], dtype=float)
    maximum_step = float(profile["maximum_absolute_voltage_step_v"])
    bounds = family["voltage_bounds_v"]
    lower = np.asarray([float(bounds[group][0]) for group in GROUPS], dtype=float)
    upper = np.asarray([float(bounds[group][1]) for group in GROUPS], dtype=float)

    def corrected_slopes(trial: np.ndarray) -> np.ndarray:
        return (
            np.asarray(normalized_slopes(axis_basis, trial, energies, derivative_step))
            + slope_discrepancy
        )

    l0_cache: dict[float, tuple[np.ndarray, float]] = {}
    solver_residual_gate = float(
        profile["maximum_abs_corrected_l0_solver_residual_per_v"]
    )
    l0_start = np.clip(voltages[:3] + linear_delta[:3], lower[:3], upper[:3])
    l0_relative_step = float(family["numerics"]["voltage_jacobian_relative_step"])
    l0_maximum_function_evaluations = int(
        family["numerics"]["maximum_function_evaluations_per_e_slice"]
    )

    def corrected_l0_member(e_voltage: float) -> tuple[np.ndarray, float]:
        key = float(e_voltage)
        if key in l0_cache:
            return l0_cache[key]
        if l0_cache:
            nearest = min(l0_cache, key=lambda value: abs(value - key))
            start = l0_cache[nearest][0][:3].copy()
        else:
            start = l0_start.copy()
        trial = _solve_corrected_l0_slice(
            axis_basis, energies, derivative_step, slope_discrepancy, lower, upper,
            start, l0_relative_step,
            float(profile["corrected_l0_root_relative_tolerance"]),
            l0_maximum_function_evaluations, solver_residual_gate, key,
        )
        gamma_model = float(fine_gamma + gamma_gradient @ (trial - voltages))
        l0_cache[key] = (trial, gamma_model)
        return l0_cache[key]

    linear_e = float(voltages[3] + linear_delta[3])
    initial_half_width = float(profile["family_bracket_initial_half_width_v"])
    expansion_factor = float(profile["family_bracket_expansion_factor"])
    maximum_expansions = int(profile["family_bracket_maximum_expansions"])
    secant_shrink_factor = float(profile["diagnostic_secant_shrink_factor"])
    secant_maximum_shrinks = int(profile["diagnostic_secant_maximum_shrinks"])
    if initial_half_width <= 0.0 or expansion_factor <= 1.0 or maximum_expansions < 0:
        raise CandidateContractError("nonlinear family bracket controls are invalid")
    e_candidates = {float(voltages[3]), min(float(upper[3]), max(float(lower[3]), linear_e))}
    half_width = initial_half_width
    for _ in range(maximum_expansions + 1):
        half_width = min(half_width, maximum_step)
        e_candidates.add(max(float(lower[3]), linear_e - half_width))
        e_candidates.add(min(float(upper[3]), linear_e + half_width))
        if half_width >= maximum_step:
            break
        half_width *= expansion_factor
    candidate_values = sorted(e_candidates)
    l0_family_parallel_workers = min(
        len(candidate_values), int(l1["maximum_parallel_workers"]), os.cpu_count() or 1,
    )
    with ProcessPoolExecutor(
        max_workers=l0_family_parallel_workers,
        initializer=_initialize_l0_slice_worker,
        initargs=(
            axis_basis, energies, derivative_step, slope_discrepancy, lower, upper,
            l0_start, l0_relative_step,
            float(profile["corrected_l0_root_relative_tolerance"]),
            l0_maximum_function_evaluations, solver_residual_gate,
        ),
    ) as executor:
        independent_slices = list(executor.map(_l0_slice_job, candidate_values))
    evaluated = []
    for value, trial_values, _reason in independent_slices:
        if trial_values is None:
            evaluated.append((value, None, "l0_not_closed"))
            continue
        trial = np.asarray(trial_values, dtype=float)
        trace = float(fine_gamma + gamma_gradient @ (trial - voltages))
        l0_cache[value] = (trial, trace)
        evaluated.append((value, trace, "l0_closed"))
    brackets = []
    for left, right in zip(evaluated, evaluated[1:], strict=False):
        if left[1] is None or right[1] is None:
            continue
        if left[1] == 0.0 or right[1] == 0.0 or float(left[1]) * float(right[1]) < 0.0:
            brackets.append((left[0], right[0]))
    if not brackets:
        null = np.asarray(correction["l0_null_unit_vector"], dtype=float)
        if abs(float(null[3])) <= np.finfo(float).eps:
            raise CandidateContractError("coarse L0-family tangent has no E coordinate")
        tangent_per_e = null / float(null[3])
        gamma_per_e = float(gamma_gradient @ tangent_per_e)
        secant_direction = -1.0 if fine_gamma * gamma_per_e > 0.0 else 1.0
        secant_voltages, secant_corrected_slopes, secant_delta_e, secant_shrinks = (
            _bounded_physical_gate_secant(
                source_voltages=voltages, tangent_per_e=tangent_per_e,
                direction=secant_direction, initial_e_step_v=initial_half_width,
                shrink_factor=secant_shrink_factor,
                maximum_shrinks=secant_maximum_shrinks,
                lower_bounds_v=lower, upper_bounds_v=upper,
                maximum_voltage_step_v=maximum_step,
                slope_gate_per_v=float(family["maximum_abs_normalized_period_slope_per_v"]),
                slope_model=corrected_slopes,
            )
        )
        secant_coarse_slopes = np.asarray(normalized_slopes(
            axis_basis, secant_voltages, energies, derivative_step,
        ))
        result = {
            "schema_version": 1,
            "role": "mrtof_fixed_grid_multifidelity_voltage_correction",
            "status": "no_local_gamma_bracket__additional_fixed_grid_secant_required",
            "qualification": "local_one_point_discrepancy_model_exhausted__not_a_candidate_operating_point",
            "source_root_index": root_index,
            "source_mirror_voltages_v": voltages_a_e,
            "proposed_mirror_voltages_v": None,
            "voltage_correction_v": None,
            "linear_predictor_voltage_correction_v": linear_delta.tolist(),
            "energy_centers_ev": list(energies),
            "period_slope_derivative_step_ev": derivative_step,
            "coarse_normalized_period_slopes_per_v": coarse_slopes.tolist(),
            "fixed_grid_normalized_period_slopes_per_v": fine_slopes.tolist(),
            "fixed_minus_coarse_slope_discrepancy_per_v": slope_discrepancy.tolist(),
            "fixed_grid_mean_directional_trace_half": fine_gamma,
            "fixed_grid_gamma_operator_id": gamma_operator_id,
            "coarse_gamma_gradient_per_v": gamma_gradient.tolist(),
            "recommended_secant_fixed_grid_point": {
                "purpose": "measure_fixed_minus_coarse_discrepancy_along_the_corrected_L0_family",
                "mirror_voltages_v": [0.0, *secant_voltages.tolist()],
                "mirror_E_step_from_source_v": secant_delta_e,
                "coarse_normalized_period_slopes_per_v": secant_coarse_slopes.tolist(),
                "predicted_corrected_normalized_period_slopes_per_v": secant_corrected_slopes.tolist(),
                "diagnostic_secant_shrink_count": secant_shrinks,
                "predicted_linear_mean_trace_half": float(
                    fine_gamma + gamma_gradient @ (secant_voltages - voltages)
                ),
                "qualification": "diagnostic_secant_point_only__not_a_candidate_operating_point",
            },
            "gamma_gradient_samples": [
                {"electrode_index_b_to_e": axis, "sign": sign, "mean_trace_half": value}
                for axis, sign, value in gamma_samples
            ],
            "correction_decomposition": correction,
            "nonlinear_l0_family_evaluated_points": [
                {
                    "mirror_E_v": value,
                    "predicted_mean_trace_half": trace,
                    "status": status,
                }
                for value, trace, status in evaluated
            ],
            "numerics": {
                "gamma_voltage_jacobian_step_v": gamma_step,
                "gamma_trajectory_profile_id": trajectory_id,
                "gamma_probe_scale": largest_scale,
                "parallel_workers": maximum_workers,
                "l0_family_parallel_workers": l0_family_parallel_workers,
                "gamma_gradient_source_sha256": gamma_gradient_source_sha256,
                "maximum_abs_corrected_l0_solver_residual_per_v": solver_residual_gate,
                "corrected_l0_root_relative_tolerance": float(
                    profile["corrected_l0_root_relative_tolerance"]
                ),
            },
            "inputs": {
                **expected_input_hashes,
                "project_contract_sha256": file_sha256(project_contract_path),
            },
            "required_next_action": (
                "Evaluate at least one additional independent fixed-grid point along the "
                "coarse L0-family tangent, then fit a local secant discrepancy model."
            ),
            "limitations": [
                "The strict corrected L0 family has no gamma-selector bracket inside the declared trust region.",
                "Loose physical-gate L0 slices are not accepted as numerical gamma roots.",
                "No proposed voltage is published from this one-point discrepancy model.",
            ],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        return result
    bracket = min(
        brackets,
        key=lambda item: abs(0.5 * (item[0] + item[1]) - linear_e),
    )
    root_e = float(brentq(
        lambda value: corrected_l0_member(float(value))[1],
        bracket[0], bracket[1],
        xtol=float(requirements["l1_screen_profile"]["e_voltage_root_tolerance_v"]),
        maxiter=int(requirements["l1_screen_profile"]["maximum_root_iterations"]),
    ))
    proposal, predicted_gamma = corrected_l0_member(root_e)
    delta = proposal - voltages
    if max(abs(float(value)) for value in delta) > maximum_step:
        null = np.asarray(correction["l0_null_unit_vector"], dtype=float)
        if abs(float(null[3])) <= np.finfo(float).eps:
            raise CandidateContractError("coarse L0-family tangent has no E coordinate")
        tangent_per_e = null / float(null[3])
        secant_direction = 1.0 if root_e > voltages[3] else -1.0
        secant_voltages, secant_corrected_slopes, secant_delta_e, secant_shrinks = (
            _bounded_physical_gate_secant(
                source_voltages=voltages, tangent_per_e=tangent_per_e,
                direction=secant_direction, initial_e_step_v=initial_half_width,
                shrink_factor=secant_shrink_factor,
                maximum_shrinks=secant_maximum_shrinks,
                lower_bounds_v=lower, upper_bounds_v=upper,
                maximum_voltage_step_v=maximum_step,
                slope_gate_per_v=float(family["maximum_abs_normalized_period_slope_per_v"]),
                slope_model=corrected_slopes,
            )
        )
        secant_coarse_slopes = np.asarray(normalized_slopes(
            axis_basis, secant_voltages, energies, derivative_step,
        ))
        secant_gamma = float(fine_gamma + gamma_gradient @ (secant_voltages - voltages))
        result = {
            "schema_version": 1,
            "role": "mrtof_fixed_grid_multifidelity_voltage_correction",
            "status": "gamma_root_outside_local_trust_region__additional_fixed_grid_secant_required",
            "qualification": "local_one_point_discrepancy_model_extrapolation_forbidden__not_a_candidate_operating_point",
            "source_root_index": root_index,
            "source_mirror_voltages_v": voltages_a_e,
            "untrusted_gamma_root_mirror_voltages_v": [0.0, *proposal.tolist()],
            "untrusted_gamma_root_voltage_correction_v": delta.tolist(),
            "untrusted_gamma_root_maximum_absolute_voltage_correction_v": float(np.max(np.abs(delta))),
            "trust_region_maximum_absolute_voltage_step_v": maximum_step,
            "recommended_secant_fixed_grid_point": {
                "purpose": "measure_fixed_minus_coarse_discrepancy_before_extrapolating_the_gamma_selector",
                "mirror_voltages_v": [0.0, *secant_voltages.tolist()],
                "mirror_E_step_from_source_v": secant_delta_e,
                "coarse_normalized_period_slopes_per_v": secant_coarse_slopes.tolist(),
                "predicted_corrected_normalized_period_slopes_per_v": secant_corrected_slopes.tolist(),
                "predicted_linear_mean_trace_half": secant_gamma,
                "physical_l0_gate_satisfied": True,
                "diagnostic_secant_shrink_count": secant_shrinks,
                "qualification": "diagnostic_secant_point_only__not_a_candidate_operating_point",
            },
            "energy_centers_ev": list(energies),
            "period_slope_derivative_step_ev": derivative_step,
            "coarse_normalized_period_slopes_per_v": coarse_slopes.tolist(),
            "fixed_grid_normalized_period_slopes_per_v": fine_slopes.tolist(),
            "fixed_minus_coarse_slope_discrepancy_per_v": slope_discrepancy.tolist(),
            "fixed_grid_mean_directional_trace_half": fine_gamma,
            "fixed_grid_gamma_operator_id": gamma_operator_id,
            "coarse_gamma_gradient_per_v": gamma_gradient.tolist(),
            "nonlinear_l0_family_gamma_bracket_e_voltage_v": list(bracket),
            "nonlinear_l0_family_evaluated_points": [
                {"mirror_E_v": value, "predicted_mean_trace_half": trace, "status": status}
                for value, trace, status in evaluated
            ],
            "gamma_gradient_samples": [
                {"electrode_index_b_to_e": axis, "sign": sign, "mean_trace_half": value}
                for axis, sign, value in gamma_samples
            ],
            "correction_decomposition": correction,
            "numerics": {
                "gamma_voltage_jacobian_step_v": gamma_step,
                "gamma_trajectory_profile_id": trajectory_id,
                "gamma_probe_scale": largest_scale,
                "parallel_workers": maximum_workers,
                "l0_family_parallel_workers": l0_family_parallel_workers,
                "gamma_gradient_source_sha256": gamma_gradient_source_sha256,
                "maximum_abs_corrected_l0_solver_residual_per_v": solver_residual_gate,
                "corrected_l0_root_relative_tolerance": float(
                    profile["corrected_l0_root_relative_tolerance"]
                ),
            },
            "inputs": {
                **expected_input_hashes,
                "project_contract_sha256": file_sha256(project_contract_path),
            },
            "required_next_action": (
                "Evaluate the bounded diagnostic secant point on the fixed 0.25-mm grid, "
                "then fit the two-point discrepancy model before extrapolating gamma."
            ),
            "limitations": [
                "The one-point fixed-grid discrepancy model is not trusted at the nonlinear gamma root.",
                "The recommended bounded point is diagnostic only and does not qualify an operating voltage.",
            ],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return result
    for index, group in enumerate(GROUPS):
        lower, upper = (float(value) for value in bounds[group])
        if not lower <= proposal[index] <= upper:
            raise CandidateContractError(f"predicted {group} voltage is outside its envelope")
    if proposal[3] <= max(energies):
        raise CandidateContractError("predicted mirror E voltage does not retain reflection margin")
    predicted_corrected_slopes = corrected_slopes(proposal)
    gamma_trace_gate = math.sin(math.radians(
        float(requirements["l1_screen_profile"]["maximum_gamma_target_residual_degrees"])
    ))
    if abs(predicted_gamma) > gamma_trace_gate:
        raise CandidateContractError("nonlinear corrected family did not close the L1 gamma selector")
    result = {
        "schema_version": 1,
        "role": "mrtof_fixed_grid_multifidelity_voltage_correction",
        "status": "proposal_only__independent_fixed_grid_validation_required",
        "qualification": "local_one_point_discrepancy_model__not_a_candidate_operating_point",
        "source_root_index": root_index,
        "source_mirror_voltages_v": voltages_a_e,
        "proposed_mirror_voltages_v": [0.0, *proposal.tolist()],
        "voltage_correction_v": delta.tolist(),
        "linear_predictor_voltage_correction_v": linear_delta.tolist(),
        "maximum_absolute_voltage_correction_v": float(np.max(np.abs(delta))),
        "trust_region_maximum_absolute_voltage_step_v": maximum_step,
        "energy_centers_ev": list(energies),
        "period_slope_derivative_step_ev": derivative_step,
        "coarse_normalized_period_slopes_per_v": coarse_slopes.tolist(),
        "fixed_grid_normalized_period_slopes_per_v": fine_slopes.tolist(),
        "fixed_minus_coarse_slope_discrepancy_per_v": slope_discrepancy.tolist(),
        "predicted_corrected_normalized_period_slopes_per_v": predicted_corrected_slopes.tolist(),
        "fixed_grid_mean_directional_trace_half": fine_gamma,
        "fixed_grid_gamma_operator_id": gamma_operator_id,
        "coarse_gamma_gradient_per_v": gamma_gradient.tolist(),
        "predicted_corrected_mean_directional_trace_half": predicted_gamma,
        "nonlinear_l0_family_gamma_bracket_e_voltage_v": list(bracket),
        "nonlinear_l0_family_evaluated_points": [
            {
                "mirror_E_v": value,
                "predicted_mean_trace_half": trace,
                "status": status,
            }
            for value, trace, status in evaluated
        ],
        "gamma_gradient_samples": [
            {"electrode_index_b_to_e": axis, "sign": sign, "mean_trace_half": value}
            for axis, sign, value in gamma_samples
        ],
        "correction_decomposition": correction,
        "numerics": {
            "slope_voltage_jacobian_scheme": "three_point_central",
            "slope_voltage_jacobian_relative_step": relative_step,
            "gamma_voltage_jacobian_scheme": "three_point_central",
            "gamma_voltage_jacobian_step_v": gamma_step,
            "family_bracket_initial_half_width_v": initial_half_width,
            "family_bracket_expansion_factor": expansion_factor,
            "family_bracket_maximum_expansions": maximum_expansions,
            "maximum_abs_corrected_l0_solver_residual_per_v": solver_residual_gate,
            "corrected_l0_root_relative_tolerance": float(
                profile["corrected_l0_root_relative_tolerance"]
            ),
            "gamma_trace_acceptance_gate": gamma_trace_gate,
            "gamma_trajectory_profile_id": trajectory_id,
            "gamma_probe_scale": largest_scale,
            "parallel_workers": maximum_workers,
            "l0_family_parallel_workers": l0_family_parallel_workers,
            "gamma_gradient_source_sha256": gamma_gradient_source_sha256,
        },
        "inputs": {
            **expected_input_hashes,
            "project_contract_sha256": file_sha256(project_contract_path),
        },
        "limitations": [
            "One fixed-grid point identifies only a local constant discrepancy, not a 0.25-mm response family.",
            "Gamma remains an L1 selector along the corrected three-equation L0 family.",
            "The proposed voltage must be evaluated by a new independent fixed-grid SIMION run.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def build_secant_correction_proposal(
    *,
    family_path: Path,
    axis_basis_path: Path,
    sampling_plan_path: Path,
    source_correction_path: Path,
    base_probe_path: Path,
    base_period_path: Path,
    base_l1_path: Path,
    base_project_contract_path: Path,
    secant_point_path: Path,
    secant_probe_path: Path,
    secant_period_path: Path,
    secant_l1_path: Path,
    secant_l1_probe_path: Path | None,
    secant_project_contract_path: Path,
    project_contract_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Extend the fixed-grid discrepancy model and publish a validation proposal."""

    family = _object(family_path, "coarse L0 family")
    plan = _object(sampling_plan_path, "coarse L1 sampling plan")
    source = _object(source_correction_path, "one-point correction")
    base_probe = _object(base_probe_path, "base fixed-grid probe")
    base_period = _object(base_period_path, "base fixed-grid period result")
    _object(base_l1_path, "base fixed-grid L1 provenance result")
    base_contract = _object(base_project_contract_path, "base fixed-grid contract")
    point = _object(secant_point_path, "secant point receipt")
    secant_probe = _object(secant_probe_path, "secant fixed-grid probe")
    secant_period = _object(secant_period_path, "secant fixed-grid period result")
    secant_l1 = _object(secant_l1_path, "secant fixed-grid L1 result")
    secant_l1_probe = (
        _object(secant_l1_probe_path, "secant native L1 probe")
        if secant_l1_probe_path is not None else None
    )
    if secant_l1_probe is not None:
        secant_l1_probe["_path"] = str(secant_l1_probe_path)
    secant_contract = _object(secant_project_contract_path, "secant fixed-grid contract")
    contract = _object(project_contract_path, "project contract")
    requirements = contract["mirror"]["theory_requirements"]
    profile = requirements["fixed_grid_multifidelity_correction_profile"]
    if profile.get("secant_discrepancy_model") not in (
        "rank_one_fixed_minus_coarse_chord",
        "successive_constrained_fixed_minus_coarse_chords",
    ):
        raise CandidateContractError("fixed-grid secant discrepancy model is unsupported")
    source_status = source.get("status")
    first_chord = source_status in {
        "no_local_gamma_bracket__additional_fixed_grid_secant_required",
        "gamma_root_outside_local_trust_region__additional_fixed_grid_secant_required",
    }
    additional_chord = (
        source_status == "secant_proposal_only__independent_fixed_grid_validation_required"
    )
    source_inputs = source.get("inputs", {})
    source_refinement_sha256 = (
        source_inputs.get("refinement_sha256")
        if first_chord
        else source.get("source_refinement_sha256")
    )
    if (
        source.get("role") != "mrtof_fixed_grid_multifidelity_voltage_correction"
        or not (first_chord or additional_chord)
        or point.get("role") != "mrtof_fixed_grid_mirror_voltage_point"
        or point.get("source_correction_sha256") != file_sha256(source_correction_path)
        or point.get("source_family_sha256") != file_sha256(family_path)
        or point.get("source_refinement_sha256") != source_refinement_sha256
    ):
        raise CandidateContractError("secant receipt does not extend the source correction")
    base_input_keys = (
        {
            "probe": "fixed_probe_contract_sha256",
            "period": "fixed_period_sha256",
            "l1": "fixed_l1_sha256",
            "contract": "fixed_project_contract_sha256",
        }
        if first_chord
        else {
            "probe": "base_probe_sha256",
            "period": "base_period_sha256",
            "l1": "base_l1_sha256",
            "contract": "base_project_contract_sha256",
        }
    )
    if (
        source_inputs.get("family_sha256") != file_sha256(family_path)
        or source_inputs.get("axis_basis_sha256") != file_sha256(axis_basis_path)
        or source_inputs.get("sampling_plan_sha256") != file_sha256(sampling_plan_path)
        or source_inputs.get(base_input_keys["probe"]) != file_sha256(base_probe_path)
        or source_inputs.get(base_input_keys["period"]) != file_sha256(base_period_path)
        or source_inputs.get(base_input_keys["l1"]) != file_sha256(base_l1_path)
        or source_inputs.get(base_input_keys["contract"])
        != file_sha256(base_project_contract_path)
    ):
        raise CandidateContractError("source correction inputs do not match the base point")
    base_voltages_a_e = [float(value) for value in base_probe.get("mirror_voltages_v", [])]
    secant_voltages_a_e = [
        float(value) for value in secant_probe.get("mirror_voltages_v", [])
    ]
    if (
        len(base_voltages_a_e) != 5
        or len(secant_voltages_a_e) != 5
        or base_voltages_a_e != [float(value) for value in source["source_mirror_voltages_v"]]
        or secant_voltages_a_e != [float(value) for value in point["mirror_voltages_v"]]
        or base_voltages_a_e[0] != 0.0
        or secant_voltages_a_e[0] != 0.0
    ):
        raise CandidateContractError("fixed-grid secant voltage identity is inconsistent")
    identity_keys = ("energy_centers_ev", "derivative_step_ev", "probe_y_mm")
    for key in identity_keys:
        if base_probe.get(key) != secant_probe.get(key):
            raise CandidateContractError(f"fixed-grid secant {key} differs between endpoints")
    if (
        base_period.get("energy_centers_ev") != base_probe.get("energy_centers_ev")
        or secant_period.get("energy_centers_ev") != secant_probe.get("energy_centers_ev")
        or float(base_period.get("derivative_step_ev"))
        != float(base_probe.get("derivative_step_ev"))
        or float(secant_period.get("derivative_step_ev"))
        != float(secant_probe.get("derivative_step_ev"))
    ):
        raise CandidateContractError("fixed-grid period evidence differs from its probe")
    for frozen in (base_contract, secant_contract):
        frozen_requirements = frozen["mirror"]["theory_requirements"]
        for key in ("l1_screen_profile", "real_3d_l1_screen_profile"):
            if frozen_requirements.get(key) != requirements.get(key):
                raise CandidateContractError(f"fixed-grid {key} contract projection differs")
        if (
            frozen.get("particle_source", {}).get("species")
            != contract.get("particle_source", {}).get("species")
            or frozen.get("simion", {}).get("trajectory_profiles")
            != contract.get("simion", {}).get("trajectory_profiles")
        ):
            raise CandidateContractError("fixed-grid particle or trajectory projection differs")

    normalization = float(plan["basis_normalization_v"])
    _potential_axis, axis_basis = load_axis_response_basis_csv(
        axis_basis_path, normalization_v=normalization,
    )
    energies = tuple(float(value) for value in family["energy_centers_ev"])
    derivative_step = float(family["period_slope_derivative_step_ev"])
    if (
        list(energies) != base_probe["energy_centers_ev"]
        or derivative_step != float(base_probe["derivative_step_ev"])
    ):
        raise CandidateContractError("coarse and fixed-grid derivative identities differ")
    base_voltages = np.asarray(base_voltages_a_e[1:], dtype=float)
    secant_voltages = np.asarray(secant_voltages_a_e[1:], dtype=float)
    voltage_step = secant_voltages - base_voltages
    coarse_base = np.asarray(
        normalized_slopes(axis_basis, base_voltages, energies, derivative_step), dtype=float,
    )
    coarse_secant = np.asarray(
        normalized_slopes(axis_basis, secant_voltages, energies, derivative_step), dtype=float,
    )
    fine_base = np.asarray(base_period["simion_normalized_period_slopes_per_v"], dtype=float)
    fine_secant = np.asarray(
        secant_period["simion_normalized_period_slopes_per_v"], dtype=float,
    )
    discrepancy_base = fine_base - coarse_base
    discrepancy_step = (fine_secant - coarse_secant) - discrepancy_base
    if float(voltage_step @ voltage_step) <= np.finfo(float).eps:
        raise CandidateContractError("fixed-grid secant voltage chord is zero")
    preserved_steps: list[np.ndarray] = []
    if first_chord:
        discrepancy_jacobian = rank_one_secant_update(
            np.zeros((3, 4), dtype=float), voltage_step, discrepancy_step,
        )
    else:
        previous_discrepancy = np.asarray(
            source.get(
                "discrepancy_jacobian_per_v2",
                source.get("rank_one_discrepancy_jacobian_per_v2", []),
            ),
            dtype=float,
        )
        previous_step = np.asarray(
            source.get("secant_diagnostics", {}).get("voltage_step_v", []),
            dtype=float,
        )
        earlier_steps = np.asarray(
            source.get("secant_diagnostics", {}).get(
                "preserved_voltage_steps_v", [],
            ),
            dtype=float,
        )
        if earlier_steps.size == 0:
            earlier_steps = np.empty((0, 4), dtype=float)
        previous_secant_voltages = np.asarray(
            source.get("secant_mirror_voltages_v", [])[1:], dtype=float,
        )
        if (
            previous_discrepancy.shape != (3, 4)
            or previous_step.shape != (4,)
            or earlier_steps.ndim != 2
            or earlier_steps.shape[1] != 4
            or previous_secant_voltages.shape != (4,)
            or not np.allclose(
                previous_step, previous_secant_voltages - base_voltages,
                rtol=0.0, atol=1e-12,
            )
        ):
            raise CandidateContractError("source correction does not preserve its first chord")
        preserved_steps.extend(earlier_steps)
        preserved_steps.append(previous_step)
        if np.linalg.matrix_rank(np.asarray(preserved_steps)) != len(preserved_steps):
            raise CandidateContractError("source correction voltage chords are dependent")
        discrepancy_jacobian = constrained_secant_update(
            previous_discrepancy,
            preserved_steps,
            voltage_step,
            discrepancy_step,
        )
    relative_step = float(
        requirements["real_3d_l0_voltage_family_profile"]["voltage_jacobian_relative_step"]
    )
    coarse_jacobian = slope_voltage_jacobian(
        axis_basis, base_voltages, energies, derivative_step, relative_step,
    )
    model_jacobian = coarse_jacobian + discrepancy_jacobian
    fine_gamma_base = _source_fixed_grid_gamma_trace(source)
    source_gamma_operator_id = _source_gamma_operator_id(source)
    secant_gamma_operator_id = _l1_gamma_operator_id(
        secant_l1, secant_l1_probe is not None,
    )
    if secant_gamma_operator_id != source_gamma_operator_id:
        raise CandidateContractError(
            "fixed-grid secant endpoints use different gamma measurement operators"
        )
    if secant_l1.get("role") == "mrtof_native_simion_transverse_l1_analysis":
        if secant_l1_probe is None:
            raise CandidateContractError("secant native L1 requires its frozen probe contract")
        fine_gamma_secant = _native_gamma_trace(
            secant_l1, secant_l1_probe, energies[1],
        )
    else:
        if secant_l1_probe is not None:
            raise CandidateContractError("secant fixed-field L1 cannot carry a native probe")
        fine_gamma_secant = _fine_gamma_trace(secant_l1, energies[1])
    if first_chord:
        source_gamma_gradient = np.asarray(source["coarse_gamma_gradient_per_v"], dtype=float)
        fine_gamma_gradient = rank_one_secant_update(
            source_gamma_gradient,
            voltage_step,
            np.asarray(fine_gamma_secant - fine_gamma_base),
        )
    else:
        source_gamma_gradient = np.asarray(
            source["updated_fine_gamma_gradient_per_v"], dtype=float,
        )
        fine_gamma_gradient = constrained_secant_update(
            source_gamma_gradient,
            preserved_steps,
            voltage_step,
            np.asarray(fine_gamma_secant - fine_gamma_base),
        )
    linear = decompose_l0_l1_correction(
        model_jacobian, fine_gamma_gradient, fine_base, fine_gamma_base,
    )
    linear_start = base_voltages + np.asarray(linear["voltage_correction_v"], dtype=float)
    slope_gate = float(family["maximum_abs_normalized_period_slope_per_v"])
    gamma_gate = math.sin(math.radians(
        float(requirements["l1_screen_profile"]["maximum_gamma_target_residual_degrees"])
    ))
    solver_gate = float(profile["maximum_abs_corrected_l0_solver_residual_per_v"])
    maximum_step = float(profile["maximum_absolute_voltage_step_v"])
    bounds = family["voltage_bounds_v"]
    lower = np.maximum(
        np.asarray([float(bounds[group][0]) for group in GROUPS]),
        base_voltages - maximum_step,
    )
    upper = np.minimum(
        np.asarray([float(bounds[group][1]) for group in GROUPS]),
        base_voltages + maximum_step,
    )

    def corrected_slopes(trial: np.ndarray) -> np.ndarray:
        return (
            np.asarray(normalized_slopes(axis_basis, trial, energies, derivative_step))
            + discrepancy_base
            + discrepancy_jacobian @ (trial - base_voltages)
        )

    def gamma_model(trial: np.ndarray) -> float:
        return float(fine_gamma_base + fine_gamma_gradient @ (trial - base_voltages))

    proposal_slope_gate = solver_gate if first_chord else slope_gate
    solution = least_squares(
        lambda trial: np.concatenate((
            corrected_slopes(trial) / proposal_slope_gate,
            np.asarray((gamma_model(trial) / gamma_gate,)),
        )),
        np.clip(linear_start, lower, upper),
        bounds=(lower, upper),
        x_scale=np.maximum(np.abs(base_voltages), 1.0),
        jac="3-point",
        diff_step=relative_step,
        ftol=float(family["numerics"]["least_squares_relative_tolerance"]),
        xtol=float(family["numerics"]["least_squares_relative_tolerance"]),
        gtol=float(family["numerics"]["least_squares_relative_tolerance"]),
        max_nfev=int(family["numerics"]["maximum_function_evaluations_per_e_slice"]),
    )
    proposal = np.asarray(solution.x, dtype=float)
    predicted_slopes = corrected_slopes(proposal)
    predicted_gamma = gamma_model(proposal)
    proposal_strategy = "coarse_jacobian_plus_measured_rank_one_discrepancy"
    if (
        not solution.success
        or np.max(np.abs(predicted_slopes)) > proposal_slope_gate
        or abs(predicted_gamma) > gamma_gate
    ):
        proposal, predicted_slopes, chord_fraction = _measured_chord_gamma_root(
            base_voltages=base_voltages,
            secant_voltages=secant_voltages,
            base_slopes=fine_base,
            secant_slopes=fine_secant,
            base_gamma=fine_gamma_base,
            secant_gamma=fine_gamma_secant,
            slope_gate=slope_gate,
            lower_bounds=lower,
            upper_bounds=upper,
        )
        predicted_gamma = 0.0
        proposal_slope_gate = slope_gate
        proposal_strategy = "measured_fixed_grid_chord_gamma_root"
    else:
        chord_fraction = None
    if proposal[3] <= max(energies):
        raise CandidateContractError("two-point proposal does not retain the E reflection margin")
    correction = proposal - base_voltages
    chord_count = len(preserved_steps) + 1
    qualification = (
        "two_fixed_point_rank_one_discrepancy_model__not_a_candidate_operating_point"
        if first_chord
        else (
            f"{chord_count + 1}_fixed_point_{chord_count}_chord_"
            "constrained_discrepancy_model__not_a_candidate_operating_point"
        )
    )
    result = {
        "schema_version": 1,
        "role": "mrtof_fixed_grid_multifidelity_voltage_correction",
        "status": "secant_proposal_only__independent_fixed_grid_validation_required",
        "qualification": qualification,
        "source_root_index": int(source["source_root_index"]),
        "source_refinement_sha256": str(source_refinement_sha256),
        "source_mirror_voltages_v": base_voltages_a_e,
        "secant_mirror_voltages_v": secant_voltages_a_e,
        "proposed_mirror_voltages_v": [0.0, *proposal.tolist()],
        "voltage_correction_v": correction.tolist(),
        "maximum_absolute_voltage_correction_v": float(np.max(np.abs(correction))),
        "energy_centers_ev": list(energies),
        "period_slope_derivative_step_ev": derivative_step,
        "base_fixed_grid_normalized_period_slopes_per_v": fine_base.tolist(),
        "secant_fixed_grid_normalized_period_slopes_per_v": fine_secant.tolist(),
        "predicted_corrected_normalized_period_slopes_per_v": predicted_slopes.tolist(),
        "base_fixed_grid_mean_directional_trace_half": fine_gamma_base,
        "fixed_grid_mean_directional_trace_half": fine_gamma_base,
        "fixed_grid_gamma_operator_id": source_gamma_operator_id,
        "secant_fixed_grid_mean_directional_trace_half": fine_gamma_secant,
        "predicted_corrected_mean_directional_trace_half": predicted_gamma,
        "proposal_strategy": proposal_strategy,
        "measured_chord_fraction": chord_fraction,
        "coarse_slope_jacobian_per_v2": coarse_jacobian.tolist(),
        "discrepancy_jacobian_per_v2": discrepancy_jacobian.tolist(),
        "rank_one_discrepancy_jacobian_per_v2": (
            discrepancy_jacobian.tolist() if first_chord else None
        ),
        "updated_local_slope_jacobian_per_v2": model_jacobian.tolist(),
        "updated_fine_gamma_gradient_per_v": fine_gamma_gradient.tolist(),
        "correction_decomposition": linear,
        "secant_diagnostics": {
            "voltage_step_v": voltage_step.tolist(),
            "preserved_voltage_steps_v": [value.tolist() for value in preserved_steps],
            "independent_voltage_chord_count": chord_count,
            "voltage_chord_norm_v": float(np.linalg.norm(voltage_step)),
            "fine_slope_step_per_v": (fine_secant - fine_base).tolist(),
            "coarse_slope_step_per_v": (coarse_secant - coarse_base).tolist(),
            "coarse_local_jacobian_chord_prediction_per_v": (
                coarse_jacobian @ voltage_step
            ).tolist(),
            "discrepancy_step_per_v": discrepancy_step.tolist(),
            "updated_l0_jacobian_rank": int(np.linalg.matrix_rank(model_jacobian)),
            "updated_l0_jacobian_nullity": 4 - int(np.linalg.matrix_rank(model_jacobian)),
            "updated_l0_jacobian_singular_values": np.linalg.svd(
                model_jacobian, compute_uv=False,
            ).tolist(),
        },
        "numerics": {
            "slope_acceptance_gate_per_v": slope_gate,
            "gamma_trace_acceptance_gate": gamma_gate,
            "maximum_abs_corrected_l0_solver_residual_per_v": solver_gate,
            "proposal_slope_acceptance_gate_per_v": proposal_slope_gate,
            "proposal_slope_gate_semantics": (
                "physical_L0_gate_on_interpolated_measured_fixed_grid_chord"
                if proposal_strategy == "measured_fixed_grid_chord_gamma_root"
                else (
                    "single_chord_internal_numerical_closure"
                    if first_chord
                    else "physical_L0_gate_pending_independent_fixed_grid_validation"
                )
            ),
            "trust_region_maximum_absolute_voltage_step_v": maximum_step,
            "least_squares_evaluations": int(solution.nfev),
            "least_squares_cost": float(solution.cost),
        },
        "inputs": {
            "family_sha256": file_sha256(family_path),
            "axis_basis_sha256": file_sha256(axis_basis_path),
            "sampling_plan_sha256": file_sha256(sampling_plan_path),
            "source_correction_sha256": file_sha256(source_correction_path),
            "source_refinement_sha256": str(source_refinement_sha256),
            "base_probe_sha256": file_sha256(base_probe_path),
            "base_period_sha256": file_sha256(base_period_path),
            "base_l1_sha256": file_sha256(base_l1_path),
            "base_project_contract_sha256": file_sha256(base_project_contract_path),
            "secant_point_sha256": file_sha256(secant_point_path),
            "secant_probe_sha256": file_sha256(secant_probe_path),
            "secant_period_sha256": file_sha256(secant_period_path),
            "secant_l1_sha256": file_sha256(secant_l1_path),
            "secant_l1_probe_sha256": (
                file_sha256(secant_l1_probe_path)
                if secant_l1_probe_path is not None else None
            ),
            "secant_project_contract_sha256": file_sha256(secant_project_contract_path),
            "project_contract_sha256": file_sha256(project_contract_path),
        },
        "limitations": (
            [
                "One voltage chord identifies only a rank-one local discrepancy update, not a 0.25-mm response family.",
                "The coarse local Jacobian does not accurately predict the full 21-V curved-family chord.",
                "The proposal requires a third independent fixed-grid SIMION validation before acceptance.",
            ]
            if first_chord
            else [
                f"{chord_count} independent voltage chords constrain only {chord_count} directions of the local discrepancy Jacobian.",
                "The physical L0 gate is used only to decide whether another fixed-grid validation is worthwhile.",
                f"The proposal requires fixed-grid SIMION validation point {chord_count + 2} before acceptance.",
            ]
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    ensure_heavy_entry(
        "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
        "mirror_fixed_grid_voltage_correction",
        role="GATE",
        stage="theory_compute",
    )
    parser = argparse.ArgumentParser()
    for name in (
        "refinement", "family", "axis-basis", "l1-basis", "sampling-plan",
        "fixed-probe-contract", "fixed-period", "fixed-l1",
        "fixed-project-contract", "project-contract", "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--gamma-gradient-source", type=Path)
    parser.add_argument("--native-l1", type=Path)
    parser.add_argument("--native-l1-probe", type=Path)
    parser.add_argument("--secant-l1-probe", type=Path)
    for name in (
        "source-correction", "secant-point", "secant-probe-contract",
        "secant-period", "secant-l1", "secant-project-contract",
    ):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args(argv)
    secant_paths = (
        args.source_correction, args.secant_point, args.secant_probe_contract,
        args.secant_period, args.secant_l1, args.secant_project_contract,
    )
    if any(path is not None for path in secant_paths):
        if not all(path is not None for path in secant_paths):
            raise CandidateContractError("all fixed-grid secant inputs are required together")
        build_secant_correction_proposal(
            family_path=args.family,
            axis_basis_path=args.axis_basis,
            sampling_plan_path=args.sampling_plan,
            source_correction_path=args.source_correction,
            base_probe_path=args.fixed_probe_contract,
            base_period_path=args.fixed_period,
            base_l1_path=args.fixed_l1,
            base_project_contract_path=args.fixed_project_contract,
            secant_point_path=args.secant_point,
            secant_probe_path=args.secant_probe_contract,
            secant_period_path=args.secant_period,
            secant_l1_path=args.secant_l1,
            secant_l1_probe_path=args.secant_l1_probe,
            secant_project_contract_path=args.secant_project_contract,
            project_contract_path=args.project_contract,
            output_path=args.output,
        )
    else:
        build_correction_proposal(
            refinement_path=args.refinement,
            family_path=args.family,
            axis_basis_path=args.axis_basis,
            l1_basis_path=args.l1_basis,
            sampling_plan_path=args.sampling_plan,
            fixed_probe_contract_path=args.fixed_probe_contract,
            fixed_period_path=args.fixed_period,
            fixed_l1_path=args.fixed_l1,
            fixed_project_contract_path=args.fixed_project_contract,
            project_contract_path=args.project_contract,
            output_path=args.output,
            gamma_gradient_source_path=args.gamma_gradient_source,
            native_l1_path=args.native_l1,
            native_l1_probe_path=args.native_l1_probe,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
