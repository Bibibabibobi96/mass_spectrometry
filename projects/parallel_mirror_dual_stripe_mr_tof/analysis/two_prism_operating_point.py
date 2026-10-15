"""Shared measured P1/P2 response and frozen-problem helpers.

The independent historical operating-point audit CLI is retired; current
staged and segmented consumers retain their shared mathematical inputs.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    classify_constraint_system,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


RESIDUAL_NAMES = (
    "P1_P2_positive_mirror_turn_y_mm",
    "P1_P2_P2_shield_low_field_signed_vy_over_vz",
)
UNKNOWN_NAMES = ("prism_1_voltage_v", "prism_2_voltage_v")


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise CandidateContractError(f"expected a JSON object in {path}")
    return value


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _same_frozen_problem(trials: Sequence[dict[str, Any]]) -> None:
    fields = (
        "source_identity",
        "target_positive_mirror_turn_y_mm",
        "target_low_field_tangent_ratio_vy_over_vz",
        "p2_low_field_reference_section",
    )
    for field in fields:
        if any(trial[field] != trials[0][field] for trial in trials[1:]):
            raise CandidateContractError(f"P1/P2 trials do not share the same frozen {field}")
    for field in ("prism_handoff_target", "residual_names", "residual_scales"):
        if any(trial.get(field) != trials[0].get(field) for trial in trials[1:]):
            raise CandidateContractError(f"P1/P2 trials differ in frozen {field}")
    if any("frozen_problem" in trial for trial in trials):
        if any(trial.get("frozen_problem") != trials[0].get("frozen_problem")
               for trial in trials[1:]):
            raise CandidateContractError("P1/P2 trials do not share the same frozen field problem")


def natural_two_prism_scales(
    contract: dict[str, Any],
) -> tuple[list[float], list[float]]:
    """Return the shared P1/P2 parameter and residual scales."""
    try:
        energy = contract["prism_transport"]["energy_partition"]
        slow_energy = _finite(energy["drift_kinetic_energy_ev"], "drift energy")
        fast_energy = _finite(energy["fast_reflection_kinetic_energy_ev"], "fast energy")
        drift_length = _finite(
            contract["dual_stripe_l0"]["manufactured_design_abs_drift_length_L_mm"],
            "manufactured drift length",
        )
    except KeyError as error:
        raise CandidateContractError("contract lacks natural P1/P2 scaling inputs") from error
    if slow_energy <= 0.0 or fast_energy <= 0.0 or drift_length <= 0.0:
        raise CandidateContractError("natural P1/P2 scaling inputs must be positive")
    voltage_scale = math.sqrt(slow_energy * fast_energy)
    return [voltage_scale, voltage_scale], [drift_length, math.sqrt(slow_energy / fast_energy)]


def measured_prism_jacobian(
    seed: dict[str, Any], p1_trial: dict[str, Any], p2_trial: dict[str, Any],
    contract: dict[str, Any], *, positive_steps: bool = False,
) -> tuple[np.ndarray, list[float], dict[str, Any]]:
    """Reuse the measured two-column model; signed real stencils are explicit."""
    _same_frozen_problem((seed, p1_trial, p2_trial))
    seed_v = np.asarray(seed["prism_voltages_v"], dtype=float)
    seed_r = np.asarray(seed["residual_vector"], dtype=float)
    if seed_v.shape != (2,) or seed_r.shape != (2,) or not (
            np.all(np.isfinite(seed_v)) and np.all(np.isfinite(seed_r))):
        raise CandidateContractError("P1/P2 seed must contain two finite voltages and residuals")
    columns, steps = [], []
    for axis, trial in enumerate((p1_trial, p2_trial)):
        delta = np.asarray(trial["prism_voltages_v"], dtype=float) - seed_v
        residual = np.asarray(trial["residual_vector"], dtype=float)
        if (delta.shape != (2,) or residual.shape != (2,)
                or not np.all(np.isfinite(delta)) or not np.all(np.isfinite(residual))
                or delta[1-axis] != 0.0 or delta[axis] == 0.0
                or (positive_steps and delta[axis] < 0.0)):
            raise CandidateContractError("P1/P2 Jacobian trial must change only its named axis")
        steps.append(float(delta[axis]))
        columns.append((residual - seed_r) / delta[axis])
    jacobian = np.column_stack(columns)
    parameter_scales, residual_scales = natural_two_prism_scales(contract)
    names = tuple(seed.get("residual_names", RESIDUAL_NAMES))
    if seed.get("prism_handoff_target") is not None:
        residual_scales = seed["residual_scales"]
    classification = classify_constraint_system(
        UNKNOWN_NAMES, names, jacobian_rows=jacobian.tolist(),
        residuals=seed_r.tolist(), parameter_scales=parameter_scales,
        residual_scales=residual_scales,
        relative_rank_tolerance=_finite(
            contract["dual_stripe_l0"]["determination_numerics"]["relative_singular_value_rank_tolerance"],
            "relative singular-value rank tolerance"),
    )
    if classification.status != "square_exact":
        raise CandidateContractError(f"P1/P2 finite-3-D Jacobian is not square exact: {classification.status}")
    return jacobian, steps, asdict(classification)
