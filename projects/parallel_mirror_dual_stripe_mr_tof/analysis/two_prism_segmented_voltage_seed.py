"""Bounded solver-neutral seed search for the manufactured P1/P2 pair.

This is a thin iteration layer over the authoritative segmented transport
evaluator.  It never replaces an invalid trajectory topology with a numeric
penalty: every center and central-difference sample must be a complete legal
P1--negative-mirror--P2--low-field-reference--positive-mirror-turn--Stripe trajectory.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    ConstraintClassification,
    classify_constraint_system,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
    TransportNumerics,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
    RESIDUAL_NAMES,
    UNKNOWN_NAMES,
    natural_two_prism_scales,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_transport import (
    TwoPrismSegmentedVoltagePairDiagnostic,
    evaluate_two_prism_segmented_voltage_pair,
)


@dataclass(frozen=True)
class VoltagePairEvaluation:
    """One retained transport evaluation, including invalid topology evidence."""

    purpose: str
    prism_voltages_v: tuple[float, float]
    residuals: tuple[float, float] | None
    scaled_residual_norm_2: float | None
    topology_signature: tuple[Any, ...] | None
    transport_diagnostic: TwoPrismSegmentedVoltagePairDiagnostic | None
    failure: str | None


@dataclass(frozen=True)
class VoltageSeedIteration:
    """One central-difference definition and the bounded step it proposed."""

    index: int
    center_evaluation_index: int
    central_difference_evaluation_indices: tuple[int, int, int, int]
    physical_jacobian_rows: tuple[tuple[float, float], tuple[float, float]] | None
    classification: ConstraintClassification | None
    undamped_correction_v: tuple[float, float] | None
    bounded_correction_v: tuple[float, float] | None
    proposed_voltages_v: tuple[float, float] | None
    backtracking_evaluation_indices: tuple[int, ...]
    accepted_evaluation_index: int | None
    accepted_step_scale: float | None
    outcome: str


@dataclass(frozen=True)
class TwoPrismSegmentedVoltageSeedResult:
    """Complete bounded-search result; non-convergence remains publishable evidence."""

    status: str
    reason: str
    unknown_names: tuple[str, str]
    residual_names: tuple[str, str]
    parameter_scales_v: tuple[float, float]
    residual_scales: tuple[float, float]
    physical_residual_tolerances: tuple[float, float]
    evaluations: tuple[VoltagePairEvaluation, ...]
    iterations: tuple[VoltageSeedIteration, ...]
    selected_evaluation_index: int | None
    selected_prism_voltages_v: tuple[float, float] | None
    selected_transport_diagnostic: TwoPrismSegmentedVoltagePairDiagnostic | None
    final_classification: ConstraintClassification | None


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CandidateContractError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise CandidateContractError(f"{label} must be a positive integer")
    return value


def _nonnegative_integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise CandidateContractError(f"{label} must be a nonnegative integer")
    return value


def _exact_pair_mapping(
    values: Mapping[int, Any], prism_ids: tuple[int, int], label: str,
) -> tuple[float, float]:
    if not isinstance(values, Mapping) or set(values) != set(prism_ids):
        raise CandidateContractError(f"{label} keys must be exactly the two prism electrode IDs")
    return tuple(_finite(values[item], f"{label} {item}") for item in prism_ids)  # type: ignore[return-value]


def _prism_ids(contract: dict[str, Any]) -> tuple[int, int]:
    try:
        result = (
            int(contract["prism_transport"]["first_prism"]["electrode_id"]),
            int(contract["prism_transport"]["second_prism"]["electrode_id"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("contract lacks the ordered P1/P2 electrode IDs") from error
    if result[0] == result[1]:
        raise CandidateContractError("P1 and P2 electrode IDs must be distinct")
    return result


def _event_signature(result: Any) -> tuple[Any, ...]:
    return tuple(
        (
            event.kind,
            event.name,
            event.region_name,
            event.entering,
            event.transmitted,
        )
        for event in result.events
    )


def selected_positive_mirror_turn_identity(
    diagnostic: TwoPrismSegmentedVoltagePairDiagnostic,
) -> tuple[Any, ...]:
    """Identify the selected turn by its adjacent physical boundary history."""
    stage_c = diagnostic.stage_c_low_field_reference_to_positive_mirror_turn
    stage_d = diagnostic.stage_d_positive_mirror_turn_to_first_stripe_pass
    if stage_c is None or not stage_c.events:
        raise CandidateContractError("positive-mirror turn identity requires stage-C events")
    turn = stage_c.events[-1]
    if (
        turn.kind != "stop"
        or turn.name != "first_post_P2_positive_mirror_turn"
        or stage_c.status != "stopped_at_positive_mirror_turn"
    ):
        raise CandidateContractError("stage C does not terminate at the selected positive-mirror turn")
    if any(event.kind == "interface" for event in stage_c.events):
        raise CandidateContractError("selected positive-mirror turn must precede every Stripe interface")
    if stage_d is None or stage_d.status != "stopped_after_first_positive_stripe_pass":
        raise CandidateContractError("positive-mirror turn identity requires a complete stage-D Stripe pass")
    interfaces = tuple(event for event in stage_d.events if event.kind == "interface")
    if len(interfaces) != 2:
        raise CandidateContractError("stage D must contain exactly one Stripe entry/exit pair")
    following = interfaces[0]
    if following.entering is not True or following.transmitted is not True:
        raise CandidateContractError("the interface following the selected turn must be a Stripe entry")
    return (
        "selected_positive_mirror_turn_identity_v2",
        ("positive_mirror_turn_ordinal_after_p2_reference", 1),
        ("stage_c_boundary_sequence", _event_signature(stage_c)),
        ("stage_d_first_stripe_pass_sequence", _event_signature(stage_d)),
        (
            "immediately_following_interface",
            following.name,
            following.region_name,
            following.entering,
            following.transmitted,
        ),
    )


def two_prism_legacy_topology_signature(
    diagnostic: TwoPrismSegmentedVoltagePairDiagnostic,
) -> tuple[Any, ...]:
    """Return the pre-turn-identity signature retained for old receipt lookup."""
    return (
        diagnostic.qualification,
        diagnostic.inferred_negative_mirror_pre_reflection,
        diagnostic.stripe_entrance_region_name,
        _event_signature(diagnostic.stage_a_p1_to_interface),
        _event_signature(diagnostic.stage_b_p1_exit_to_p2_low_field_reference),
    )


def two_prism_topology_signature(
    diagnostic: TwoPrismSegmentedVoltagePairDiagnostic,
) -> tuple[Any, ...]:
    """Return the strict path identity, including the selected turn branch."""
    return (
        "two_prism_topology_signature_v2",
        two_prism_legacy_topology_signature(diagnostic),
        selected_positive_mirror_turn_identity(diagnostic),
    )


def _topology_signature(diagnostic: TwoPrismSegmentedVoltagePairDiagnostic) -> tuple[Any, ...]:
    """Compatibility alias for callers predating the public topology API."""
    return two_prism_topology_signature(diagnostic)


def solve_two_prism_segmented_voltage_seed(
    contract: dict[str, Any],
    *,
    source: ProjectPhaseSpaceState,
    particle_mass_th: float,
    charge_state: int,
    mirror_design: MirrorL0Design,
    selected_axial_energy_per_charge_v: float,
    target_slow_kinetic_energy_per_charge_v: float,
    target_p2_reference_tangent_ratio: float,
    stripe_bias_v_by_set_name: Mapping[str, float],
    numerics: TransportNumerics,
    stage_a_maximum_reduced_time_mm_per_sqrt_v: float,
    stage_b_maximum_reduced_time_mm_per_sqrt_v: float,
    prism_voltage_bounds_v_by_electrode_id: Mapping[int, Sequence[float]],
    initial_prism_voltage_pairs_v: Sequence[Sequence[float]],
    central_difference_step_v_by_electrode_id: Mapping[int, float],
    maximum_iterations: int,
    maximum_transport_evaluations: int,
    trust_step_v_by_electrode_id: Mapping[int, float],
    maximum_backtracking_reductions: int,
    backtracking_factor: float,
    minimum_scaled_residual_norm_decrease: float,
    physical_residual_tolerance_by_name: Mapping[str, float],
    relative_singular_value_rank_tolerance: float,
    scaled_compatibility_tolerance: float,
) -> TwoPrismSegmentedVoltageSeedResult:
    """Search a bounded P1/P2 seed while preserving one legal topology.

    Every scientific and numerical control is an explicit caller input.  A
    failed transport is retained as evidence and immediately rejects a
    central-difference neighborhood; it is never converted into a residual.
    """
    prism_ids = _prism_ids(contract)
    parameter_scales_raw, residual_scales_raw = natural_two_prism_scales(contract)
    parameter_scales = tuple(_finite(value, "parameter scale") for value in parameter_scales_raw)
    residual_scales = tuple(_finite(value, "residual scale") for value in residual_scales_raw)
    if len(parameter_scales) != 2 or len(residual_scales) != 2 or min(*parameter_scales, *residual_scales) <= 0.0:
        raise CandidateContractError("natural P1/P2 scales must contain two positive values each")

    if not isinstance(prism_voltage_bounds_v_by_electrode_id, Mapping) or set(prism_voltage_bounds_v_by_electrode_id) != set(prism_ids):
        raise CandidateContractError("voltage-bound keys must be exactly the two prism electrode IDs")
    bounds = []
    for prism_id in prism_ids:
        pair = prism_voltage_bounds_v_by_electrode_id[prism_id]
        if not isinstance(pair, Sequence) or isinstance(pair, (str, bytes)) or len(pair) != 2:
            raise CandidateContractError("each prism voltage bound must contain lower and upper values")
        lower, upper = (_finite(pair[0], "lower voltage bound"), _finite(pair[1], "upper voltage bound"))
        if lower >= upper:
            raise CandidateContractError("each prism voltage domain must have positive width")
        bounds.append((lower, upper))
    fd_steps = _exact_pair_mapping(
        central_difference_step_v_by_electrode_id, prism_ids, "central-difference step",
    )
    trust_steps = _exact_pair_mapping(trust_step_v_by_electrode_id, prism_ids, "trust step")
    if min(*fd_steps, *trust_steps) <= 0.0:
        raise CandidateContractError("central-difference and trust steps must be positive")
    if not isinstance(physical_residual_tolerance_by_name, Mapping) or set(physical_residual_tolerance_by_name) != set(RESIDUAL_NAMES):
        raise CandidateContractError("physical residual tolerance keys must match the two residual names")
    residual_tolerances = tuple(
        _finite(physical_residual_tolerance_by_name[name], f"{name} tolerance")
        for name in RESIDUAL_NAMES
    )
    if min(residual_tolerances) <= 0.0:
        raise CandidateContractError("physical residual tolerances must be positive")
    iteration_budget = _positive_integer(maximum_iterations, "iteration budget")
    evaluation_budget = _positive_integer(maximum_transport_evaluations, "transport evaluation budget")
    backtracking_reductions = _nonnegative_integer(
        maximum_backtracking_reductions, "maximum backtracking reductions",
    )
    shrink = _finite(backtracking_factor, "backtracking factor")
    minimum_decrease = _finite(
        minimum_scaled_residual_norm_decrease,
        "minimum scaled residual-norm decrease",
    )
    if not 0.0 < shrink < 1.0 or minimum_decrease <= 0.0:
        raise CandidateContractError(
            "backtracking factor must lie in (0, 1) and minimum decrease must be positive"
        )
    rank_tolerance = _finite(
        relative_singular_value_rank_tolerance, "relative singular-value rank tolerance",
    )
    compatibility_tolerance = _finite(
        scaled_compatibility_tolerance, "scaled compatibility tolerance",
    )
    if not 0.0 < rank_tolerance < 1.0 or compatibility_tolerance < 0.0:
        raise CandidateContractError("rank or compatibility tolerance is invalid")
    if not initial_prism_voltage_pairs_v:
        raise CandidateContractError("initial voltage coverage must be nonempty")
    initial_pairs = []
    for pair in initial_prism_voltage_pairs_v:
        if not isinstance(pair, Sequence) or isinstance(pair, (str, bytes)) or len(pair) != 2:
            raise CandidateContractError("each initial voltage pair must contain P1 and P2")
        voltage_pair = tuple(_finite(value, "initial prism voltage") for value in pair)
        if any(not bounds[index][0] <= voltage_pair[index] <= bounds[index][1] for index in range(2)):
            raise CandidateContractError("initial prism voltage lies outside its explicit domain")
        initial_pairs.append(voltage_pair)
    if len(set(initial_pairs)) != len(initial_pairs):
        raise CandidateContractError("initial voltage coverage must not contain duplicates")

    evaluations: list[VoltagePairEvaluation] = []
    iterations: list[VoltageSeedIteration] = []

    def finish(
        status: str,
        reason: str,
        selected_index: int | None,
        classification: ConstraintClassification | None,
    ) -> TwoPrismSegmentedVoltageSeedResult:
        selected = evaluations[selected_index] if selected_index is not None else None
        return TwoPrismSegmentedVoltageSeedResult(
            status,
            reason,
            tuple(UNKNOWN_NAMES),
            tuple(RESIDUAL_NAMES),
            parameter_scales,  # type: ignore[arg-type]
            residual_scales,  # type: ignore[arg-type]
            residual_tolerances,  # type: ignore[arg-type]
            tuple(evaluations),
            tuple(iterations),
            selected_index,
            selected.prism_voltages_v if selected else None,
            selected.transport_diagnostic if selected else None,
            classification,
        )

    def evaluate(pair: tuple[float, float], purpose: str) -> int | None:
        if len(evaluations) >= evaluation_budget:
            return None
        voltage_map = {prism_ids[index]: pair[index] for index in range(2)}
        try:
            diagnostic = evaluate_two_prism_segmented_voltage_pair(
                contract,
                source=source,
                particle_mass_th=particle_mass_th,
                charge_state=charge_state,
                mirror_design=mirror_design,
                selected_axial_energy_per_charge_v=selected_axial_energy_per_charge_v,
                target_slow_kinetic_energy_per_charge_v=target_slow_kinetic_energy_per_charge_v,
                target_p2_reference_tangent_ratio=target_p2_reference_tangent_ratio,
                prism_bias_v_by_electrode_id=voltage_map,
                stripe_bias_v_by_set_name=stripe_bias_v_by_set_name,
                numerics=numerics,
                stage_a_maximum_reduced_time_mm_per_sqrt_v=stage_a_maximum_reduced_time_mm_per_sqrt_v,
                stage_b_maximum_reduced_time_mm_per_sqrt_v=stage_b_maximum_reduced_time_mm_per_sqrt_v,
            )
            residual_by_name = dict(diagnostic.voltage_residuals)
            if set(residual_by_name) != set(RESIDUAL_NAMES):
                raise CandidateContractError("transport returned a different residual system")
            residuals = tuple(_finite(residual_by_name[name], name) for name in RESIDUAL_NAMES)
            scaled_norm = float(np.linalg.norm(np.asarray(residuals) / np.asarray(residual_scales)))
            record = VoltagePairEvaluation(
                purpose, pair, residuals, scaled_norm, two_prism_topology_signature(diagnostic), diagnostic, None,
            )
        except CandidateContractError as error:
            record = VoltagePairEvaluation(purpose, pair, None, None, None, None, str(error))
        evaluations.append(record)
        return len(evaluations) - 1

    valid_initial_indices = []
    for pair in initial_pairs:
        index = evaluate(pair, "initial_coverage")
        if index is None:
            return finish(
                "evaluation_budget_exhausted",
                "transport evaluation budget ended during initial coverage",
                None,
                None,
            )
        if evaluations[index].failure is None:
            valid_initial_indices.append(index)
    if not valid_initial_indices:
        return finish(
            "no_valid_initial_topology",
            "no initial coverage point completed the required physical topology",
            None,
            None,
        )
    ordered_initial_indices = sorted(
        valid_initial_indices,
        # Physics residual remains the primary criterion.  Equivalent feasible
        # P1/P2 seeds then use the smaller voltage envelope deterministically.
        key=lambda index: (
            evaluations[index].scaled_residual_norm_2,
            max(abs(value) for value in evaluations[index].prism_voltages_v),
            sum(abs(value) for value in evaluations[index].prism_voltages_v),
            evaluations[index].prism_voltages_v,
        ),
    )
    initial_neighborhood_position = 0
    selected_index = ordered_initial_indices[initial_neighborhood_position]
    selecting_initial_neighborhood = True
    final_classification = None
    solver_iteration = 0

    while solver_iteration < iteration_budget:
        center = evaluations[selected_index]
        assert center.residuals is not None and center.topology_signature is not None
        center_pair = np.asarray(center.prism_voltages_v, dtype=float)
        perturbation_indices = []
        derivative_columns = []
        neighborhood_failure = None
        for axis in range(2):
            step = fd_steps[axis]
            minus = center_pair.copy()
            plus = center_pair.copy()
            minus[axis] -= step
            plus[axis] += step
            if minus[axis] < bounds[axis][0] or plus[axis] > bounds[axis][1]:
                neighborhood_failure = "symmetric perturbation leaves the explicit voltage domain"
                break
            pair_indices = []
            for direction, trial in (("minus", minus), ("plus", plus)):
                index = evaluate(tuple(float(value) for value in trial), f"jacobian_{axis}_{direction}")
                if index is None:
                    iterations.append(VoltageSeedIteration(
                        len(iterations), selected_index,
                        tuple([*perturbation_indices, *pair_indices]),
                        None, None, None, None, None, (), None, None,
                        "evaluation_budget_exhausted_during_neighborhood",
                    ))
                    return finish(
                        "evaluation_budget_exhausted",
                        "transport evaluation budget ended during central differences",
                        selected_index,
                        final_classification,
                    )
                pair_indices.append(index)
                trial_evaluation = evaluations[index]
                if (
                    trial_evaluation.failure is not None
                    or trial_evaluation.topology_signature != center.topology_signature
                ):
                    neighborhood_failure = (
                        "central-difference sample failed or changed the center trajectory topology"
                    )
                    break
            perturbation_indices.extend(pair_indices)
            if neighborhood_failure is not None:
                break
            minus_residuals = np.asarray(evaluations[pair_indices[0]].residuals, dtype=float)
            plus_residuals = np.asarray(evaluations[pair_indices[1]].residuals, dtype=float)
            derivative_columns.append((plus_residuals - minus_residuals) / (2.0 * step))
        if neighborhood_failure is not None:
            iterations.append(VoltageSeedIteration(
                len(iterations), selected_index, tuple(perturbation_indices),
                None, None, None, None, None, (), None, None,
                "initial_neighborhood_rejected" if selecting_initial_neighborhood
                else "active_branch_neighborhood_lost",
            ))
            if selecting_initial_neighborhood:
                initial_neighborhood_position += 1
                if initial_neighborhood_position < len(ordered_initial_indices):
                    selected_index = ordered_initial_indices[initial_neighborhood_position]
                    continue
                return finish(
                    "all_initial_neighborhoods_invalid",
                    "every valid initial coverage point lacks a same-topology central-difference neighborhood",
                    None,
                    None,
                )
            return finish(
                "invalid_topology_neighborhood",
                neighborhood_failure,
                selected_index,
                final_classification,
            )
        selecting_initial_neighborhood = False
        jacobian = np.column_stack(derivative_columns)
        classification = classify_constraint_system(
            UNKNOWN_NAMES,
            RESIDUAL_NAMES,
            jacobian_rows=jacobian.tolist(),
            residuals=center.residuals,
            parameter_scales=parameter_scales,
            residual_scales=residual_scales,
            relative_rank_tolerance=rank_tolerance,
            compatibility_tolerance=compatibility_tolerance,
        )
        final_classification = classification
        if classification.status != "square_exact":
            iterations.append(VoltageSeedIteration(
                len(iterations), selected_index, tuple(perturbation_indices),
                tuple(tuple(float(value) for value in row) for row in jacobian),
                classification, None, None, None, (), None, None,
                "definition_rejected",
            ))
            return finish(
                classification.status,
                f"local P1/P2 system is not square exact: {classification.reason}",
                selected_index,
                classification,
            )
        if all(abs(center.residuals[index]) <= residual_tolerances[index] for index in range(2)):
            iterations.append(VoltageSeedIteration(
                len(iterations), selected_index, tuple(perturbation_indices),
                tuple(tuple(float(value) for value in row) for row in jacobian),
                classification, (0.0, 0.0), (0.0, 0.0), center.prism_voltages_v,
                (), selected_index, 0.0, "converged",
            ))
            return finish(
                "converged",
                "both physical residuals satisfy their explicit tolerances at a square-exact point",
                selected_index,
                classification,
            )
        scaled_jacobian = (
            jacobian
            * np.asarray(parameter_scales)[np.newaxis, :]
            / np.asarray(residual_scales)[:, np.newaxis]
        )
        scaled_rhs = -np.asarray(center.residuals) / np.asarray(residual_scales)
        scaled_correction = np.linalg.solve(scaled_jacobian, scaled_rhs)
        undamped = np.asarray(parameter_scales) * scaled_correction
        bounded = np.clip(undamped, -np.asarray(trust_steps), np.asarray(trust_steps))
        if not np.any(bounded):
            return finish(
                "trust_step_stalled",
                "the trust-bounded correction has no nonzero coordinate",
                selected_index,
                classification,
            )
        trial_indices = []
        accepted_index = None
        accepted_scale = None
        accepted_delta = None
        accepted_pair = None
        legal_trial_count = 0
        lower_bounds = np.asarray([item[0] for item in bounds])
        upper_bounds = np.asarray([item[1] for item in bounds])
        for reduction in range(backtracking_reductions + 1):
            scale = shrink**reduction
            proposed = np.clip(center_pair + scale * bounded, lower_bounds, upper_bounds)
            actual_delta = proposed - center_pair
            if not np.any(actual_delta):
                continue
            proposed_pair = tuple(float(value) for value in proposed)
            next_index = evaluate(
                proposed_pair, f"bounded_newton_backtrack_{reduction}",
            )
            if next_index is None:
                iterations.append(VoltageSeedIteration(
                    len(iterations),
                    selected_index,
                    tuple(perturbation_indices),
                    tuple(tuple(float(value) for value in row) for row in jacobian),
                    classification,
                    tuple(float(value) for value in undamped),
                    tuple(float(value) for value in bounded),
                    None,
                    tuple(trial_indices),
                    None,
                    None,
                    "evaluation_budget_exhausted_during_backtracking",
                ))
                return finish(
                    "evaluation_budget_exhausted",
                    "transport evaluation budget ended during bounded-step backtracking",
                    selected_index,
                    classification,
                )
            trial_indices.append(next_index)
            candidate = evaluations[next_index]
            if candidate.failure is not None or candidate.topology_signature != center.topology_signature:
                continue
            legal_trial_count += 1
            assert candidate.scaled_residual_norm_2 is not None
            assert center.scaled_residual_norm_2 is not None
            decrease = center.scaled_residual_norm_2 - candidate.scaled_residual_norm_2
            if decrease >= minimum_decrease:
                accepted_index = next_index
                accepted_scale = scale
                accepted_delta = actual_delta
                accepted_pair = proposed_pair
                break
        iterations.append(VoltageSeedIteration(
            len(iterations),
            selected_index,
            tuple(perturbation_indices),
            tuple(tuple(float(value) for value in row) for row in jacobian),
            classification,
            tuple(float(value) for value in undamped),
            tuple(float(value) for value in (accepted_delta if accepted_delta is not None else bounded)),
            accepted_pair,
            tuple(trial_indices),
            accepted_index,
            accepted_scale,
            "step_accepted" if accepted_index is not None else "backtracking_rejected",
        ))
        if accepted_index is None:
            if legal_trial_count == 0:
                return finish(
                    "backtracking_exhausted_all_invalid_topology",
                    "every nonzero bounded-step trial failed or changed the legal trajectory topology",
                    selected_index,
                    classification,
                )
            return finish(
                "backtracking_exhausted_no_sufficient_decrease",
                "no legal bounded-step trial achieved the explicit scaled residual-norm decrease",
                selected_index,
                classification,
            )
        selected_index = accepted_index
        solver_iteration += 1

    return finish(
        "iteration_budget_exhausted",
        "iteration budget ended before both physical residual tolerances were satisfied",
        selected_index,
        final_classification,
    )
