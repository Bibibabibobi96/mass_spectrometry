"""Topology-preserving continuation of the current segmented P1/P2 branch.

The inner problem solves the P2-shield signed-tangent-ratio residual for P2
at fixed P1.  The outer continuation follows only one frozen event signature
and observes the first positive-mirror-turn y residual on that one-dimensional
branch.  Invalid trajectories and signature changes are boundaries, never
numerical penalty values.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Callable, Sequence

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


TrialEvaluator = Callable[[tuple[float, float]], dict[str, Any]]


@dataclass(frozen=True)
class ContinuationControls:
    p1_bounds_v: tuple[float, float]
    p2_bounds_v: tuple[float, float]
    angle_ratio_tolerance: float
    positive_turn_y_tolerance_mm: float
    p2_root_tolerance_v: float
    initial_p1_step_v: float
    minimum_p1_step_v: float
    maximum_p1_step_v: float
    p1_step_growth_factor: float
    p2_initial_half_width_v: float
    p2_bracket_expansion_factor: float
    p2_bracket_maximum_expansions: int
    maximum_inner_iterations: int
    maximum_outer_iterations: int
    maximum_transport_evaluations: int
    maximum_nodes_per_direction: int

    def validate(self) -> None:
        for label, bounds in (("P1", self.p1_bounds_v), ("P2", self.p2_bounds_v)):
            if len(bounds) != 2 or not all(math.isfinite(value) for value in bounds):
                raise CandidateContractError(f"{label} bounds must contain two finite values")
            if bounds[0] >= bounds[1]:
                raise CandidateContractError(f"{label} bounds must have positive width")
        positive = {
            "angle-ratio root tolerance": self.angle_ratio_tolerance,
            "positive-turn y root tolerance": self.positive_turn_y_tolerance_mm,
            "P2 root tolerance": self.p2_root_tolerance_v,
            "initial P1 step": self.initial_p1_step_v,
            "minimum P1 step": self.minimum_p1_step_v,
            "maximum P1 step": self.maximum_p1_step_v,
            "P1 step growth factor": self.p1_step_growth_factor,
            "P2 initial half width": self.p2_initial_half_width_v,
            "P2 bracket expansion factor": self.p2_bracket_expansion_factor,
        }
        for label, value in positive.items():
            if not math.isfinite(value) or value <= 0.0:
                raise CandidateContractError(f"{label} must be finite and positive")
        if not self.minimum_p1_step_v <= self.initial_p1_step_v <= self.maximum_p1_step_v:
            raise CandidateContractError("P1 step limits do not contain the initial step")
        if self.p1_step_growth_factor < 1.0:
            raise CandidateContractError("P1 step growth factor must be at least one")
        if self.p2_bracket_expansion_factor <= 1.0:
            raise CandidateContractError("P2 bracket expansion factor must exceed one")
        for label, value in (
            ("P2 bracket maximum expansions", self.p2_bracket_maximum_expansions),
            ("maximum inner iterations", self.maximum_inner_iterations),
            ("maximum outer iterations", self.maximum_outer_iterations),
            ("maximum transport evaluations", self.maximum_transport_evaluations),
            ("maximum nodes per direction", self.maximum_nodes_per_direction),
        ):
            if type(value) is not int or value <= 0:
                raise CandidateContractError(f"{label} must be a positive integer")


class _Budget:
    def __init__(self, evaluator: TrialEvaluator, maximum: int) -> None:
        self._evaluator = evaluator
        self.maximum = maximum
        self.count = 0

    def evaluate(self, pair: tuple[float, float]) -> dict[str, Any]:
        if self.count >= self.maximum:
            raise CandidateContractError("continuation transport evaluation budget exhausted")
        self.count += 1
        return self._evaluator(pair)


def _accepted_trial(
    record: dict[str, Any], *, expected_signature_sha256: str,
    expected_continuity_signature_sha256: str | None = None,
) -> tuple[float, float]:
    if record.get("status") != "legal_topology":
        raise CandidateContractError("continuation trial left the legal topology")
    current_signature = record.get("topology_signature_sha256")
    legacy_signature = record.get("legacy_topology_signature_sha256")
    if expected_signature_sha256 not in (current_signature, legacy_signature):
        raise CandidateContractError("continuation trial changed topology signature")
    if (
        expected_continuity_signature_sha256 is not None
        and current_signature != expected_continuity_signature_sha256
    ):
        raise CandidateContractError("continuation trial changed selected-turn identity")
    residuals = record.get("residual_vector")
    if not isinstance(residuals, Sequence) or len(residuals) != 2:
        raise CandidateContractError(
            "continuation trial must expose positive-turn y and P2-reference angle residuals"
        )
    try:
        y_residual, angle_residual = (float(residuals[0]), float(residuals[1]))
    except (TypeError, ValueError) as error:
        raise CandidateContractError("continuation residuals must be finite") from error
    if not math.isfinite(y_residual) or not math.isfinite(angle_residual):
        raise CandidateContractError("continuation residuals must be finite")
    return y_residual, angle_residual


def _node(pair: tuple[float, float], y_residual: float, angle_residual: float) -> dict[str, float]:
    return {
        "p1_voltage_v": pair[0],
        "p2_voltage_v": pair[1],
        "positive_mirror_turn_y_residual_mm": y_residual,
        "p2_reference_signed_tangent_ratio_residual": angle_residual,
    }


def tangent_ratio_tolerance_from_angle_degrees(
    target_tangent_ratio: float,
    angle_tolerance_deg: float,
) -> float:
    """Convert a symmetric angular tolerance to a conservative ratio tolerance."""
    if not math.isfinite(target_tangent_ratio):
        raise CandidateContractError("target tangent ratio must be finite")
    if not math.isfinite(angle_tolerance_deg) or angle_tolerance_deg <= 0.0:
        raise CandidateContractError("angle tolerance in degrees must be finite and positive")
    target_angle = math.atan(target_tangent_ratio)
    delta = math.radians(angle_tolerance_deg)
    if abs(target_angle) + delta >= 0.5 * math.pi:
        raise CandidateContractError("angle tolerance crosses a tangent singularity")
    return max(
        abs(math.tan(target_angle - delta) - target_tangent_ratio),
        abs(math.tan(target_angle + delta) - target_tangent_ratio),
    )


def _solve_primary_root(
    budget: _Budget,
    *,
    p1_v: float,
    p2_bracket_v: tuple[float, float],
    expected_signature_sha256: str,
    controls: ContinuationControls,
    residual_index: int,
    residual_tolerance: float,
    residual_label: str,
) -> dict[str, float]:
    lower, upper = p2_bracket_v
    if not controls.p2_bounds_v[0] <= lower < upper <= controls.p2_bounds_v[1]:
        raise CandidateContractError("P2 angle-root bracket lies outside the voltage domain")
    lower_pair = (p1_v, lower)
    upper_pair = (p1_v, upper)
    lower_record = budget.evaluate(lower_pair)
    upper_record = budget.evaluate(upper_pair)
    lower_residuals = _accepted_trial(
        lower_record, expected_signature_sha256=expected_signature_sha256,
    )
    upper_residuals = _accepted_trial(
        upper_record, expected_signature_sha256=expected_signature_sha256,
    )
    continuity_signature = lower_record.get("topology_signature_sha256")
    if not continuity_signature or upper_record.get("topology_signature_sha256") != continuity_signature:
        raise CandidateContractError("P2 root bracket crosses a selected-turn identity boundary")
    lower_g = lower_residuals[residual_index]
    upper_g = upper_residuals[residual_index]
    if abs(lower_g) <= residual_tolerance:
        return _node(lower_pair, *lower_residuals)
    if abs(upper_g) <= residual_tolerance:
        return _node(upper_pair, *upper_residuals)
    if lower_g * upper_g > 0.0:
        raise CandidateContractError(f"P2 bracket does not enclose the {residual_label} root")
    for _ in range(controls.maximum_inner_iterations):
        midpoint = 0.5 * (lower + upper)
        pair = (p1_v, midpoint)
        residuals = _accepted_trial(
            budget.evaluate(pair), expected_signature_sha256=expected_signature_sha256,
            expected_continuity_signature_sha256=str(continuity_signature),
        )
        g_value = residuals[residual_index]
        if (
            abs(g_value) <= residual_tolerance
            or 0.5 * (upper - lower) <= controls.p2_root_tolerance_v
        ):
            return _node(pair, *residuals)
        if lower_g * g_value <= 0.0:
            upper, upper_g = midpoint, g_value
        else:
            lower, lower_g = midpoint, g_value
    raise CandidateContractError(f"P2 {residual_label} root exceeded the inner iteration limit")


def _solve_angle_root(
    budget: _Budget,
    *,
    p1_v: float,
    p2_bracket_v: tuple[float, float],
    expected_signature_sha256: str,
    controls: ContinuationControls,
) -> dict[str, float]:
    return _solve_primary_root(
        budget, p1_v=p1_v, p2_bracket_v=p2_bracket_v,
        expected_signature_sha256=expected_signature_sha256, controls=controls,
        residual_index=1, residual_tolerance=controls.angle_ratio_tolerance,
        residual_label="angle-ratio",
    )


def _solve_positive_turn_y_root(
    budget: _Budget,
    *,
    p1_v: float,
    p2_bracket_v: tuple[float, float],
    expected_signature_sha256: str,
    controls: ContinuationControls,
) -> dict[str, float]:
    return _solve_primary_root(
        budget, p1_v=p1_v, p2_bracket_v=p2_bracket_v,
        expected_signature_sha256=expected_signature_sha256, controls=controls,
        residual_index=0, residual_tolerance=controls.positive_turn_y_tolerance_mm,
        residual_label="positive-mirror-turn-y",
    )


def _correct_primary_root(
    budget: _Budget,
    *,
    p1_v: float,
    predicted_p2_v: float,
    expected_signature_sha256: str,
    controls: ContinuationControls,
    residual_index: int,
    residual_tolerance: float,
    residual_label: str,
) -> dict[str, float]:
    center_pair = (p1_v, predicted_p2_v)
    center_record = budget.evaluate(center_pair)
    center_residuals = _accepted_trial(
        center_record, expected_signature_sha256=expected_signature_sha256,
    )
    continuity_signature = center_record.get("topology_signature_sha256")
    if not continuity_signature:
        raise CandidateContractError("continuation trial lacks a selected-turn continuity identity")
    center_g = center_residuals[residual_index]
    if abs(center_g) <= residual_tolerance:
        return _node(center_pair, *center_residuals)
    legal_samples = [(predicted_p2_v, center_g)]
    blocked_sides: set[str] = set()
    half_width = controls.p2_initial_half_width_v
    for _ in range(controls.p2_bracket_maximum_expansions + 1):
        lower = max(controls.p2_bounds_v[0], predicted_p2_v - half_width)
        upper = min(controls.p2_bounds_v[1], predicted_p2_v + half_width)
        for side, value in (("lower", lower), ("upper", upper)):
            if side in blocked_sides or value == predicted_p2_v:
                continue
            try:
                residuals = _accepted_trial(
                    budget.evaluate((p1_v, value)),
                    expected_signature_sha256=expected_signature_sha256,
                    expected_continuity_signature_sha256=str(continuity_signature),
                )
                g_value = residuals[residual_index]
            except CandidateContractError:
                blocked_sides.add(side)
                continue
            legal_samples.append((value, g_value))
        ordered = sorted({value: residual for value, residual in legal_samples}.items())
        for (left, left_g), (right, right_g) in zip(ordered, ordered[1:]):
            if left_g * right_g <= 0.0:
                return _solve_primary_root(
                    budget, p1_v=p1_v, p2_bracket_v=(left, right),
                    expected_signature_sha256=expected_signature_sha256, controls=controls,
                    residual_index=residual_index,
                    residual_tolerance=residual_tolerance,
                    residual_label=residual_label,
                )
        if lower == controls.p2_bounds_v[0] and upper == controls.p2_bounds_v[1]:
            break
        if blocked_sides == {"lower", "upper"}:
            break
        half_width *= controls.p2_bracket_expansion_factor
    raise CandidateContractError(
        f"no same-topology P2 bracket encloses the {residual_label} root"
    )


def _correct_angle_root(
    budget: _Budget,
    *,
    p1_v: float,
    predicted_p2_v: float,
    expected_signature_sha256: str,
    controls: ContinuationControls,
) -> dict[str, float]:
    return _correct_primary_root(
        budget, p1_v=p1_v, predicted_p2_v=predicted_p2_v,
        expected_signature_sha256=expected_signature_sha256, controls=controls,
        residual_index=1, residual_tolerance=controls.angle_ratio_tolerance,
        residual_label="angle-ratio",
    )


def _correct_positive_turn_y_root(
    budget: _Budget,
    *,
    p1_v: float,
    predicted_p2_v: float,
    expected_signature_sha256: str,
    controls: ContinuationControls,
) -> dict[str, float]:
    return _correct_primary_root(
        budget, p1_v=p1_v, predicted_p2_v=predicted_p2_v,
        expected_signature_sha256=expected_signature_sha256, controls=controls,
        residual_index=0, residual_tolerance=controls.positive_turn_y_tolerance_mm,
        residual_label="positive-mirror-turn-y",
    )


def solve_position_slice_from_legal_anchor(
    evaluator: TrialEvaluator,
    *,
    legal_anchor_pair_v: tuple[float, float],
    expected_signature_sha256: str,
    controls: ContinuationControls,
) -> dict[str, Any]:
    """Solve one topology-preserving P2 position slice at the anchor P1."""
    controls.validate()
    if not expected_signature_sha256:
        raise CandidateContractError("expected topology signature is required")
    p1_v, p2_v = legal_anchor_pair_v
    if not controls.p1_bounds_v[0] <= p1_v <= controls.p1_bounds_v[1]:
        raise CandidateContractError("position-slice P1 lies outside the voltage domain")
    if not controls.p2_bounds_v[0] <= p2_v <= controls.p2_bounds_v[1]:
        raise CandidateContractError("position-slice P2 lies outside the voltage domain")
    budget = _Budget(evaluator, controls.maximum_transport_evaluations)
    node = _correct_positive_turn_y_root(
        budget,
        p1_v=p1_v,
        predicted_p2_v=p2_v,
        expected_signature_sha256=expected_signature_sha256,
        controls=controls,
    )
    return {
        "status": "position_root_found",
        "node": node,
        "transport_evaluation_count": budget.count,
        "position_tolerance_reached": (
            abs(node["positive_mirror_turn_y_residual_mm"])
            <= controls.positive_turn_y_tolerance_mm
        ),
        "angle_tolerance_reached": (
            abs(node["p2_reference_signed_tangent_ratio_residual"])
            <= controls.angle_ratio_tolerance
        ),
    }


def solve_position_domain_slice(
    evaluator: TrialEvaluator,
    *,
    p1_v: float,
    allowed_signature_sha256: Sequence[str],
    p2_scan_count: int,
    controls: ContinuationControls,
) -> dict[str, Any]:
    """Scan one fixed-P1 voltage domain and refine same-topology y roots."""
    controls.validate()
    if not controls.p1_bounds_v[0] <= p1_v <= controls.p1_bounds_v[1]:
        raise CandidateContractError("position-domain P1 lies outside the voltage domain")
    if type(p2_scan_count) is not int or p2_scan_count < 2:
        raise CandidateContractError("P2 scan count must be an integer of at least two")
    allowed = {str(value) for value in allowed_signature_sha256 if str(value)}
    if not allowed:
        raise CandidateContractError("at least one allowed topology signature is required")
    budget = _Budget(evaluator, controls.maximum_transport_evaluations)
    lower, upper = controls.p2_bounds_v
    scan: list[dict[str, Any]] = []
    legal: list[tuple[int, float, str, tuple[float, float]]] = []
    for index in range(p2_scan_count):
        p2_v = lower + index * (upper - lower) / (p2_scan_count - 1)
        record = budget.evaluate((p1_v, p2_v))
        signature = record.get("topology_signature_sha256")
        legacy_signature = record.get("legacy_topology_signature_sha256")
        if (
            record.get("status") == "legal_topology"
            and (signature in allowed or legacy_signature in allowed)
        ):
            residuals = _accepted_trial(
                record, expected_signature_sha256=str(signature),
            )
            legal.append((index, p2_v, str(signature), residuals))
            scan.append({
                "p2_voltage_v": p2_v,
                "status": "legal_topology",
                "topology_signature_sha256": signature,
                "legacy_topology_signature_sha256": legacy_signature,
                "positive_mirror_turn_y_residual_mm": residuals[0],
                "p2_reference_signed_tangent_ratio_residual": residuals[1],
            })
        else:
            scan.append({
                "p2_voltage_v": p2_v,
                "status": str(record.get("status", "invalid_topology")),
                "topology_signature_sha256": signature,
            })
    roots: list[dict[str, float]] = []
    for _index, p2_v, _signature, residuals in legal:
        if abs(residuals[0]) <= controls.positive_turn_y_tolerance_mm:
            roots.append(_node((p1_v, p2_v), *residuals))
    for left, right in zip(legal, legal[1:]):
        left_index, left_p2, left_signature, left_residuals = left
        right_index, right_p2, right_signature, right_residuals = right
        if (
            right_index != left_index + 1
            or left_signature != right_signature
            or left_residuals[0] * right_residuals[0] > 0.0
        ):
            continue
        try:
            root = _solve_positive_turn_y_root(
                budget,
                p1_v=p1_v,
                p2_bracket_v=(left_p2, right_p2),
                expected_signature_sha256=left_signature,
                controls=controls,
            )
        except CandidateContractError:
            continue
        roots.append(root)
    unique_roots = {
        (root["p1_voltage_v"], root["p2_voltage_v"]): root
        for root in roots
    }
    ordered_roots = sorted(
        unique_roots.values(),
        key=lambda root: abs(root["p2_reference_signed_tangent_ratio_residual"]),
    )
    return {
        "status": "position_root_found" if ordered_roots else "no_position_root_bracketed",
        "p1_voltage_v": p1_v,
        "p2_scan_count": p2_scan_count,
        "scan": scan,
        "roots": ordered_roots,
        "best_root": ordered_roots[0] if ordered_roots else None,
        "joint_tolerance_reached": any(
            abs(root["p2_reference_signed_tangent_ratio_residual"])
            <= controls.angle_ratio_tolerance
            for root in ordered_roots
        ),
        "transport_evaluation_count": budget.count,
    }


def solve_adaptive_position_domain_slice(
    evaluator: TrialEvaluator,
    *,
    p1_v: float,
    allowed_signature_sha256: Sequence[str],
    p2_scan_count: int,
    refinement_levels: int,
    refinement_candidate_count: int,
    controls: ContinuationControls,
) -> dict[str, Any]:
    """Adaptively classify low-|y| and topology-boundary P2 intervals.

    Midpoint evaluations only classify previously unresolved intervals.  A root
    solve is attempted only after two adjacent *legal* samples have the same
    event signature and bracket y=0.  Illegal samples and signature changes are
    retained as physical topology boundaries; they are never converted to a
    residual or interpolated across.
    """
    controls.validate()
    if not controls.p1_bounds_v[0] <= p1_v <= controls.p1_bounds_v[1]:
        raise CandidateContractError("adaptive position-domain P1 lies outside the voltage domain")
    if type(p2_scan_count) is not int or p2_scan_count < 2:
        raise CandidateContractError("P2 scan count must be an integer of at least two")
    if type(refinement_levels) is not int or refinement_levels <= 0:
        raise CandidateContractError("adaptive refinement levels must be a positive integer")
    if type(refinement_candidate_count) is not int or refinement_candidate_count <= 0:
        raise CandidateContractError("adaptive candidate count must be a positive integer")
    allowed = {str(value) for value in allowed_signature_sha256 if str(value)}
    if not allowed:
        raise CandidateContractError("at least one allowed topology signature is required")

    budget = _Budget(evaluator, controls.maximum_transport_evaluations)
    samples: dict[float, dict[str, Any]] = {}

    def evaluate_at(p2_v: float) -> dict[str, Any]:
        if p2_v in samples:
            return samples[p2_v]
        record = budget.evaluate((p1_v, p2_v))
        signature = record.get("topology_signature_sha256")
        legacy_signature = record.get("legacy_topology_signature_sha256")
        if (
            record.get("status") == "legal_topology"
            and (signature in allowed or legacy_signature in allowed)
        ):
            residuals = _accepted_trial(record, expected_signature_sha256=str(signature))
            sample = {
                "p2_voltage_v": p2_v,
                "status": "legal_topology",
                "topology_signature_sha256": str(signature),
                "legacy_topology_signature_sha256": legacy_signature,
                "positive_mirror_turn_y_residual_mm": residuals[0],
                "p2_reference_signed_tangent_ratio_residual": residuals[1],
            }
        else:
            sample = {
                "p2_voltage_v": p2_v,
                "status": str(record.get("status", "invalid_topology")),
                "topology_signature_sha256": signature,
            }
        samples[p2_v] = sample
        return sample

    lower, upper = controls.p2_bounds_v
    for index in range(p2_scan_count):
        evaluate_at(lower + index * (upper - lower) / (p2_scan_count - 1))

    refinement_history: list[dict[str, Any]] = []
    for level in range(refinement_levels):
        ordered = [samples[key] for key in sorted(samples)]
        legal = [item for item in ordered if item["status"] == "legal_topology"]
        if not legal:
            break
        lowest = sorted(
            legal,
            key=lambda item: (
                abs(item["positive_mirror_turn_y_residual_mm"]),
                abs(item["p2_reference_signed_tangent_ratio_residual"]),
                item["p2_voltage_v"],
            ),
        )[:refinement_candidate_count]
        low_voltages = {item["p2_voltage_v"] for item in lowest}
        selected: list[tuple[float, float, str]] = []
        for left, right in zip(ordered, ordered[1:]):
            left_legal = left["status"] == "legal_topology"
            right_legal = right["status"] == "legal_topology"
            reason = None
            if left_legal != right_legal:
                reason = "legal_invalid_topology_boundary"
            elif left_legal and right_legal:
                if left["topology_signature_sha256"] != right["topology_signature_sha256"]:
                    reason = "signature_boundary"
                elif (
                    left["positive_mirror_turn_y_residual_mm"]
                    * right["positive_mirror_turn_y_residual_mm"] <= 0.0
                ):
                    reason = "same_signature_y_bracket"
                elif (
                    left["p2_voltage_v"] in low_voltages
                    or right["p2_voltage_v"] in low_voltages
                ):
                    reason = "low_abs_y_neighborhood"
            if reason is not None:
                selected.append((left["p2_voltage_v"], right["p2_voltage_v"], reason))
        new_points: list[dict[str, Any]] = []
        for left_v, right_v, reason in selected:
            midpoint = 0.5 * (left_v + right_v)
            if midpoint in samples:
                continue
            try:
                sample = evaluate_at(midpoint)
            except CandidateContractError as error:
                if "budget exhausted" in str(error):
                    break
                raise
            new_points.append({"p2_voltage_v": midpoint, "reason": reason, "status": sample["status"]})
        refinement_history.append({
            "level": level + 1,
            "selected_interval_count": len(selected),
            "new_sample_count": len(new_points),
            "new_samples": new_points,
        })
        if not new_points or budget.count >= budget.maximum:
            break

    ordered = [samples[key] for key in sorted(samples)]
    legal = [item for item in ordered if item["status"] == "legal_topology"]
    roots: list[dict[str, float]] = []
    for item in legal:
        if abs(item["positive_mirror_turn_y_residual_mm"]) <= controls.positive_turn_y_tolerance_mm:
            roots.append(_node(
                (p1_v, item["p2_voltage_v"]),
                item["positive_mirror_turn_y_residual_mm"],
                item["p2_reference_signed_tangent_ratio_residual"],
            ))
    for left, right in zip(ordered, ordered[1:]):
        if left["status"] != "legal_topology" or right["status"] != "legal_topology":
            continue
        if left["topology_signature_sha256"] != right["topology_signature_sha256"]:
            continue
        if (
            left["positive_mirror_turn_y_residual_mm"]
            * right["positive_mirror_turn_y_residual_mm"] > 0.0
        ):
            continue
        try:
            roots.append(_solve_positive_turn_y_root(
                budget,
                p1_v=p1_v,
                p2_bracket_v=(left["p2_voltage_v"], right["p2_voltage_v"]),
                expected_signature_sha256=left["topology_signature_sha256"],
                controls=controls,
            ))
        except CandidateContractError:
            continue
    unique_roots = {
        (root["p1_voltage_v"], root["p2_voltage_v"]): root
        for root in roots
    }
    ordered_roots = sorted(
        unique_roots.values(),
        key=lambda root: (
            abs(root["p2_reference_signed_tangent_ratio_residual"]),
            abs(root["positive_mirror_turn_y_residual_mm"]),
        ),
    )
    best_legal = min(
        legal,
        key=lambda item: (
            abs(item["positive_mirror_turn_y_residual_mm"]),
            abs(item["p2_reference_signed_tangent_ratio_residual"]),
        ),
        default=None,
    )
    boundaries = []
    for left, right in zip(ordered, ordered[1:]):
        left_legal = left["status"] == "legal_topology"
        right_legal = right["status"] == "legal_topology"
        if left_legal != right_legal or (
            left_legal and right_legal
            and left["topology_signature_sha256"] != right["topology_signature_sha256"]
        ):
            boundaries.append({
                "p2_interval_v": [left["p2_voltage_v"], right["p2_voltage_v"]],
                "width_v": right["p2_voltage_v"] - left["p2_voltage_v"],
                "left_status": left["status"],
                "right_status": right["status"],
                "left_signature_sha256": left.get("topology_signature_sha256"),
                "right_signature_sha256": right.get("topology_signature_sha256"),
            })
    return {
        "status": "position_root_found" if ordered_roots else "no_position_root_bracketed",
        "p1_voltage_v": p1_v,
        "p2_scan_count": p2_scan_count,
        "adaptive_refinement_levels_requested": refinement_levels,
        "adaptive_refinement_candidate_count": refinement_candidate_count,
        "refinement_history": refinement_history,
        "scan": ordered,
        "roots": ordered_roots,
        "best_root": ordered_roots[0] if ordered_roots else None,
        "best_legal_sample": best_legal,
        "topology_boundary_brackets": boundaries,
        "joint_tolerance_reached": any(
            abs(root["p2_reference_signed_tangent_ratio_residual"])
            <= controls.angle_ratio_tolerance
            for root in ordered_roots
        ),
        "transport_evaluation_count": budget.count,
    }


def _predict_p2(nodes: Sequence[dict[str, float]], p1_v: float) -> float:
    if len(nodes) < 2:
        return nodes[-1]["p2_voltage_v"]
    first, second = nodes[-2], nodes[-1]
    delta_p1 = second["p1_voltage_v"] - first["p1_voltage_v"]
    if delta_p1 == 0.0:
        return second["p2_voltage_v"]
    slope = (second["p2_voltage_v"] - first["p2_voltage_v"]) / delta_p1
    return second["p2_voltage_v"] + slope * (p1_v - second["p1_voltage_v"])


def _trace_direction(
    budget: _Budget,
    *,
    seed: dict[str, float],
    direction: int,
    expected_signature_sha256: str,
    controls: ContinuationControls,
) -> dict[str, Any]:
    nodes = [seed]
    step = controls.initial_p1_step_v
    terminal = "maximum_nodes_reached"
    while len(nodes) <= controls.maximum_nodes_per_direction:
        current = nodes[-1]
        candidate_p1 = current["p1_voltage_v"] + direction * step
        if not controls.p1_bounds_v[0] <= candidate_p1 <= controls.p1_bounds_v[1]:
            terminal = "p1_voltage_domain_boundary"
            break
        predicted_p2 = _predict_p2(nodes, candidate_p1)
        if not controls.p2_bounds_v[0] <= predicted_p2 <= controls.p2_bounds_v[1]:
            terminal = "p2_voltage_domain_boundary"
            break
        try:
            candidate = _correct_angle_root(
                budget, p1_v=candidate_p1, predicted_p2_v=predicted_p2,
                expected_signature_sha256=expected_signature_sha256, controls=controls,
            )
        except CandidateContractError as error:
            if "budget exhausted" in str(error):
                terminal = "transport_budget_exhausted"
                break
            step *= 0.5
            if step < controls.minimum_p1_step_v:
                terminal = "topology_boundary_or_unbracketed_angle_root"
                break
            continue
        nodes.append(candidate)
        step = min(step * controls.p1_step_growth_factor, controls.maximum_p1_step_v)
        if abs(candidate["positive_mirror_turn_y_residual_mm"]) <= controls.positive_turn_y_tolerance_mm:
            terminal = "joint_root_tolerance_reached"
            break
        if (
            nodes[-2]["positive_mirror_turn_y_residual_mm"]
            * candidate["positive_mirror_turn_y_residual_mm"] < 0.0
        ):
            terminal = "positive_turn_y_root_bracketed"
            break
    return {"direction": direction, "terminal_status": terminal, "nodes": nodes[1:]}


def _trace_y_zero_direction(
    budget: _Budget,
    *,
    seed: dict[str, float],
    direction: int,
    expected_signature_sha256: str,
    controls: ContinuationControls,
) -> dict[str, Any]:
    """Continue the y=0 branch and retain angle as a reported diagnostic."""
    nodes = [seed]
    step = controls.initial_p1_step_v
    terminal = "maximum_nodes_reached"
    while len(nodes) <= controls.maximum_nodes_per_direction:
        current = nodes[-1]
        candidate_p1 = current["p1_voltage_v"] + direction * step
        if not controls.p1_bounds_v[0] <= candidate_p1 <= controls.p1_bounds_v[1]:
            terminal = "p1_voltage_domain_boundary"
            break
        predicted_p2 = _predict_p2(nodes, candidate_p1)
        if not controls.p2_bounds_v[0] <= predicted_p2 <= controls.p2_bounds_v[1]:
            terminal = "p2_voltage_domain_boundary"
            break
        try:
            candidate = _correct_positive_turn_y_root(
                budget, p1_v=candidate_p1, predicted_p2_v=predicted_p2,
                expected_signature_sha256=expected_signature_sha256, controls=controls,
            )
        except CandidateContractError as error:
            if "budget exhausted" in str(error):
                terminal = "transport_budget_exhausted"
                break
            step *= 0.5
            if step < controls.minimum_p1_step_v:
                terminal = "topology_boundary_or_unbracketed_y_root"
                break
            continue
        nodes.append(candidate)
        step = min(step * controls.p1_step_growth_factor, controls.maximum_p1_step_v)
    return {"direction": direction, "terminal_status": terminal, "nodes": nodes[1:]}


def _refine_joint_root(
    budget: _Budget,
    *,
    bracket: tuple[dict[str, float], dict[str, float]],
    expected_signature_sha256: str,
    controls: ContinuationControls,
) -> dict[str, float]:
    lower, upper = sorted(bracket, key=lambda item: item["p1_voltage_v"])
    lower_y = lower["positive_mirror_turn_y_residual_mm"]
    upper_y = upper["positive_mirror_turn_y_residual_mm"]
    if lower_y * upper_y > 0.0:
        raise CandidateContractError("positive-turn-y bracket does not enclose the joint root")
    for _ in range(controls.maximum_outer_iterations):
        if abs(lower_y) <= controls.positive_turn_y_tolerance_mm:
            return lower
        if abs(upper_y) <= controls.positive_turn_y_tolerance_mm:
            return upper
        p1_value = 0.5 * (lower["p1_voltage_v"] + upper["p1_voltage_v"])
        fraction = (
            (p1_value - lower["p1_voltage_v"])
            / (upper["p1_voltage_v"] - lower["p1_voltage_v"])
        )
        predicted_p2 = lower["p2_voltage_v"] + fraction * (
            upper["p2_voltage_v"] - lower["p2_voltage_v"]
        )
        midpoint = _correct_angle_root(
            budget, p1_v=p1_value, predicted_p2_v=predicted_p2,
            expected_signature_sha256=expected_signature_sha256, controls=controls,
        )
        midpoint_y = midpoint["positive_mirror_turn_y_residual_mm"]
        if abs(midpoint_y) <= controls.positive_turn_y_tolerance_mm:
            return midpoint
        if lower_y * midpoint_y <= 0.0:
            upper, upper_y = midpoint, midpoint_y
        else:
            lower, lower_y = midpoint, midpoint_y
    raise CandidateContractError("joint P1/P2 root exceeded the outer iteration limit")


def continue_angle_zero_branch(
    evaluator: TrialEvaluator,
    *,
    expected_signature_sha256: str,
    initial_p1_v: float,
    initial_p2_bracket_v: tuple[float, float],
    controls: ContinuationControls,
) -> dict[str, Any]:
    """Trace both directions of one legal P2-reference-angle-zero branch."""
    controls.validate()
    if not expected_signature_sha256:
        raise CandidateContractError("expected topology signature is required")
    if not controls.p1_bounds_v[0] <= initial_p1_v <= controls.p1_bounds_v[1]:
        raise CandidateContractError("initial P1 voltage lies outside the voltage domain")
    budget = _Budget(evaluator, controls.maximum_transport_evaluations)
    seed = _solve_angle_root(
        budget, p1_v=initial_p1_v, p2_bracket_v=initial_p2_bracket_v,
        expected_signature_sha256=expected_signature_sha256, controls=controls,
    )
    negative = _trace_direction(
        budget, seed=seed, direction=-1, expected_signature_sha256=expected_signature_sha256,
        controls=controls,
    )
    positive = _trace_direction(
        budget, seed=seed, direction=1, expected_signature_sha256=expected_signature_sha256,
        controls=controls,
    )
    all_nodes = list(reversed(negative["nodes"])) + [seed] + positive["nodes"]
    refined_joint_root = None
    for direction_result in (negative, positive):
        if direction_result["terminal_status"] == "positive_turn_y_root_bracketed":
            direction_nodes = [seed] + direction_result["nodes"]
            refined_joint_root = _refine_joint_root(
                budget, bracket=(direction_nodes[-2], direction_nodes[-1]),
                expected_signature_sha256=expected_signature_sha256, controls=controls,
            )
            break
    y_values = [node["positive_mirror_turn_y_residual_mm"] for node in all_nodes]
    joint_candidates = [
        node for node in all_nodes
        if abs(node["positive_mirror_turn_y_residual_mm"]) <= controls.positive_turn_y_tolerance_mm
        and abs(node["p2_reference_signed_tangent_ratio_residual"]) <= controls.angle_ratio_tolerance
    ]
    if refined_joint_root is not None:
        joint_candidates.append(refined_joint_root)
    return {
        "solve_mode": "angle_then_y",
        "qualification": "solver_neutral_single_topology_branch_continuation_only",
        "expected_topology_signature_sha256": expected_signature_sha256,
        "seed": seed,
        "negative_direction": negative,
        "positive_direction": positive,
        "nodes": all_nodes,
        "transport_evaluation_count": budget.count,
        "positive_mirror_turn_y_residual_range_mm": [min(y_values), max(y_values)],
        "joint_root_tolerance_reached": bool(joint_candidates),
        "joint_root_candidates": joint_candidates,
    }


def continue_y_zero_branch(
    evaluator: TrialEvaluator,
    *,
    expected_signature_sha256: str,
    initial_p1_v: float,
    initial_p2_bracket_v: tuple[float, float],
    controls: ContinuationControls,
) -> dict[str, Any]:
    """Trace y=0 and test the declared practical angular tolerance."""
    controls.validate()
    if not expected_signature_sha256:
        raise CandidateContractError("expected topology signature is required")
    if not controls.p1_bounds_v[0] <= initial_p1_v <= controls.p1_bounds_v[1]:
        raise CandidateContractError("initial P1 voltage lies outside the voltage domain")
    budget = _Budget(evaluator, controls.maximum_transport_evaluations)
    seed = _solve_positive_turn_y_root(
        budget, p1_v=initial_p1_v, p2_bracket_v=initial_p2_bracket_v,
        expected_signature_sha256=expected_signature_sha256, controls=controls,
    )
    negative = _trace_y_zero_direction(
        budget, seed=seed, direction=-1, expected_signature_sha256=expected_signature_sha256,
        controls=controls,
    )
    positive = _trace_y_zero_direction(
        budget, seed=seed, direction=1, expected_signature_sha256=expected_signature_sha256,
        controls=controls,
    )
    all_nodes = list(reversed(negative["nodes"])) + [seed] + positive["nodes"]
    angle_values = [
        node["p2_reference_signed_tangent_ratio_residual"] for node in all_nodes
    ]
    y_values = [node["positive_mirror_turn_y_residual_mm"] for node in all_nodes]
    best = min(
        all_nodes,
        key=lambda node: (
            abs(node["p2_reference_signed_tangent_ratio_residual"]),
            abs(node["positive_mirror_turn_y_residual_mm"]),
        ),
    )
    joint_candidates = [
        node for node in all_nodes
        if abs(node["positive_mirror_turn_y_residual_mm"])
        <= controls.positive_turn_y_tolerance_mm
        and abs(node["p2_reference_signed_tangent_ratio_residual"])
        <= controls.angle_ratio_tolerance
    ]
    return {
        "solve_mode": "y_then_angle_diagnostic",
        "qualification": (
            "solver_neutral_single_topology_y_zero_branch_with_declared_search_tolerances"
        ),
        "expected_topology_signature_sha256": expected_signature_sha256,
        "seed": seed,
        "negative_direction": negative,
        "positive_direction": positive,
        "nodes": all_nodes,
        "transport_evaluation_count": budget.count,
        "positive_mirror_turn_y_residual_range_mm": [min(y_values), max(y_values)],
        "p2_reference_signed_tangent_ratio_residual_range": [
            min(angle_values), max(angle_values),
        ],
        "minimum_abs_angle_residual_node": best,
        "angle_ratio_acceptance_tolerance": controls.angle_ratio_tolerance,
        "joint_search_tolerance_reached": bool(joint_candidates),
        "joint_search_tolerance_candidates": joint_candidates,
    }


def main() -> None:
    from common.contracts.file_identity import file_sha256
    from common.host_resource_python import ensure_heavy_entry
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_exit_transport_source import (
        materialize_accelerator_exit_transport_source,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_exact_k_operating_point import (
        load_managed_exact_k_operating_point,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
        TransportNumerics,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
        natural_two_prism_scales,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage import (
        _evaluate,
        _initialize_worker,
        _load_stripe_seed,
        validate_accelerator_exit_source_binding,
    )

    ensure_heavy_entry(
        "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
        "two_prism_segmented_voltage_continuation",
        role="GATE", stage="theory_compute",
    )
    parser = argparse.ArgumentParser()
    for name in (
        "contract", "exact-k-manifest", "stripe-seed-manifest",
        "accelerator-exit-observation", "accelerator-exit-source-receipt",
        "coverage-summary", "source-receipt-output", "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--expected-observation-sha256", required=True)
    parser.add_argument("--expected-topology-signature-sha256", required=True)
    parser.add_argument(
        "--solve-mode",
        choices=("angle_then_y", "y_then_angle_diagnostic"),
        default="angle_then_y",
    )
    for name in (
        "initial-p1-v", "initial-p2-lower-v", "initial-p2-upper-v",
        "p1-min-v", "p1-max-v", "p2-min-v", "p2-max-v",
        "angle-tolerance-deg", "positive-turn-y-tolerance-mm", "p2-root-tolerance-v",
        "initial-p1-step-v", "minimum-p1-step-v", "maximum-p1-step-v",
        "p1-step-growth-factor", "p2-initial-half-width-v",
        "p2-bracket-expansion-factor", "relative-tolerance", "absolute-tolerance",
        "max-step", "root-time-tolerance", "boundary-root-tolerance",
        "momentum-tolerance", "normal-energy-tolerance",
        "stage-a-maximum-reduced-time", "stage-b-maximum-reduced-time",
    ):
        parser.add_argument(f"--{name}", type=float, required=True)
    for name in (
        "p2-bracket-maximum-expansions", "maximum-inner-iterations",
        "maximum-outer-iterations", "maximum-transport-evaluations",
        "maximum-nodes-per-direction", "event-samples-per-step", "maximum-steps",
    ):
        parser.add_argument(f"--{name}", type=int, required=True)
    args = parser.parse_args()

    coverage = json.loads(args.coverage_summary.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(coverage, dict)
        or coverage.get("schema_version") != 1
        or coverage.get("role") != "mrtof_two_prism_segmented_voltage_branch_coverage"
        or coverage.get("status") != "coverage_complete"
    ):
        raise CandidateContractError("coverage summary identity is invalid")
    branch_ids = {
        branch.get("topology_signature_sha256")
        for branch in coverage.get("coverage", {}).get("combined", {}).get("branches", [])
        if isinstance(branch, dict)
    }
    if args.expected_topology_signature_sha256 not in branch_ids:
        raise CandidateContractError("expected topology signature is absent from coverage")
    expected_inputs = coverage.get("inputs", {})
    for label, path, expected in (
        ("contract", args.contract, expected_inputs.get("contract_sha256")),
        ("exact-K manifest", args.exact_k_manifest, expected_inputs.get("exact_k_manifest_sha256")),
        ("Stripe manifest", args.stripe_seed_manifest, expected_inputs.get("stripe_seed", {}).get("manifest_sha256")),
        ("accelerator exit observation", args.accelerator_exit_observation, expected_inputs.get("accelerator_exit_observation_sha256")),
        ("accelerator exit source receipt", args.accelerator_exit_source_receipt, expected_inputs.get("accelerator_exit_source_receipt", {}).get("sha256")),
    ):
        if file_sha256(path).lower() != str(expected).lower():
            raise CandidateContractError(f"{label} differs from the coverage input")

    managed = load_managed_exact_k_operating_point(args.exact_k_manifest, args.contract)
    species = managed.contract.get("particle_source", {}).get("species", {})
    mass = float(species.get("mass_th"))
    charge = species.get("charge_e")
    if not math.isfinite(mass) or type(charge) is not int or charge == 0:
        raise CandidateContractError("contract species is invalid")
    source, source_receipt = materialize_accelerator_exit_transport_source(
        observation_path=args.accelerator_exit_observation,
        expected_observation_sha256=args.expected_observation_sha256,
        expected_particle_mass_th=mass, expected_charge_state=charge,
        receipt_path=args.source_receipt_output,
    )
    source_binding = validate_accelerator_exit_source_binding(
        source_receipt_path=args.accelerator_exit_source_receipt,
        source_handoff_receipt=source_receipt, managed=managed,
    )
    stripe_biases, slow_energy, target_tangent_ratio, stripe_identity = _load_stripe_seed(
        args.stripe_seed_manifest, exact_k_manifest_path=args.exact_k_manifest,
        managed=managed,
    )
    prism_ids = (
        int(managed.contract["prism_transport"]["first_prism"]["electrode_id"]),
        int(managed.contract["prism_transport"]["second_prism"]["electrode_id"]),
    )
    numerics = TransportNumerics(
        args.relative_tolerance, args.absolute_tolerance, args.max_step,
        args.event_samples_per_step, args.root_time_tolerance,
        args.boundary_root_tolerance, args.momentum_tolerance,
        args.normal_energy_tolerance, args.maximum_steps,
    )
    _, residual_scales = natural_two_prism_scales(managed.contract)
    angle_ratio_tolerance = tangent_ratio_tolerance_from_angle_degrees(
        target_tangent_ratio, args.angle_tolerance_deg,
    )
    context = {
        "contract": managed.contract, "source": source, "mass": mass, "charge": charge,
        "mirror_design": managed.design, "axial_energy": managed.axial_energy_per_charge_v,
        "slow_energy": slow_energy, "stripe_biases": stripe_biases, "prism_ids": prism_ids,
        "target_tangent_ratio": target_tangent_ratio,
        "numerics": numerics, "stage_a": args.stage_a_maximum_reduced_time,
        "stage_b": args.stage_b_maximum_reduced_time,
        "residual_scales": tuple(residual_scales),
    }
    controls = ContinuationControls(
        p1_bounds_v=(args.p1_min_v, args.p1_max_v),
        p2_bounds_v=(args.p2_min_v, args.p2_max_v),
        angle_ratio_tolerance=angle_ratio_tolerance,
        positive_turn_y_tolerance_mm=args.positive_turn_y_tolerance_mm,
        p2_root_tolerance_v=args.p2_root_tolerance_v,
        initial_p1_step_v=args.initial_p1_step_v,
        minimum_p1_step_v=args.minimum_p1_step_v,
        maximum_p1_step_v=args.maximum_p1_step_v,
        p1_step_growth_factor=args.p1_step_growth_factor,
        p2_initial_half_width_v=args.p2_initial_half_width_v,
        p2_bracket_expansion_factor=args.p2_bracket_expansion_factor,
        p2_bracket_maximum_expansions=args.p2_bracket_maximum_expansions,
        maximum_inner_iterations=args.maximum_inner_iterations,
        maximum_outer_iterations=args.maximum_outer_iterations,
        maximum_transport_evaluations=args.maximum_transport_evaluations,
        maximum_nodes_per_direction=args.maximum_nodes_per_direction,
    )
    _initialize_worker(context)
    continuation = (
        continue_angle_zero_branch
        if args.solve_mode == "angle_then_y"
        else continue_y_zero_branch
    )
    result = continuation(
        _evaluate,
        expected_signature_sha256=args.expected_topology_signature_sha256,
        initial_p1_v=args.initial_p1_v,
        initial_p2_bracket_v=(args.initial_p2_lower_v, args.initial_p2_upper_v),
        controls=controls,
    )
    output = {
        "schema_version": 1,
        "role": "mrtof_two_prism_segmented_voltage_branch_continuation",
        "status": "continuation_complete",
        "qualification": "solver_neutral_single_topology_branch_continuation_only__not_a_3d_voltage_solution",
        "inputs": {
            "coverage_summary_sha256": file_sha256(args.coverage_summary).lower(),
            "contract_sha256": file_sha256(args.contract).lower(),
            "exact_k_manifest_sha256": file_sha256(args.exact_k_manifest).lower(),
            "stripe_seed": stripe_identity,
            "accelerator_exit_source_receipt": source_binding,
            "materialized_source_receipt_sha256": file_sha256(args.source_receipt_output).lower(),
        },
        "controls": {
            "solve_mode": args.solve_mode,
            "angle_tolerance_deg": args.angle_tolerance_deg,
            "derived_angle_ratio_tolerance": angle_ratio_tolerance,
            "continuation": asdict(controls),
            "transport_numerics": asdict(numerics),
        },
        "continuation": result,
        "limitations": [
            "Only the frozen event signature is traced; termination does not prove global nonexistence.",
            "The projected y-z hard-boundary model does not qualify finite-3D transmission or resolution.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "MRTOF_TWO_PRISM_SEGMENTED_CONTINUATION=PASS "
        f"nodes={len(result['nodes'])} evaluations={result['transport_evaluation_count']}"
    )


if __name__ == "__main__":
    main()
