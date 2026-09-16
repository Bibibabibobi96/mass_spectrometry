"""Topology-safe one-dimensional P2 solve at one fixed P1 value.

The caller supplies one already legal P1/P2 anchor, an analytic P2 predictor,
and a transport evaluator.  The algorithm never interpolates residuals across
an invalid trajectory or a changed event signature.  If the analytic proposal
lies beyond the connected legal branch, it localizes the topology boundary and
reports the last reachable angle residual instead of manufacturing a root.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


TrialEvaluator = Callable[[tuple[float, float]], Mapping[str, Any]]
VoltagePredictor = Callable[[Mapping[str, Any]], float]


@dataclass(frozen=True)
class AngleSliceControls:
    p2_bounds_v: tuple[float, float]
    angle_ratio_root_tolerance: float
    p2_root_tolerance_v: float
    topology_boundary_tolerance_v: float
    maximum_evaluations: int

    def validate(self) -> None:
        if (
            len(self.p2_bounds_v) != 2
            or not all(math.isfinite(value) for value in self.p2_bounds_v)
            or self.p2_bounds_v[0] >= self.p2_bounds_v[1]
        ):
            raise CandidateContractError("P2 bounds must contain two increasing finite voltages")
        for label, value in (
            ("angle-ratio root tolerance", self.angle_ratio_root_tolerance),
            ("P2 root tolerance", self.p2_root_tolerance_v),
            ("topology-boundary tolerance", self.topology_boundary_tolerance_v),
        ):
            if not math.isfinite(value) or value <= 0.0:
                raise CandidateContractError(f"{label} must be finite and positive")
        if type(self.maximum_evaluations) is not int or self.maximum_evaluations < 2:
            raise CandidateContractError("maximum evaluations must be an integer of at least two")


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


def _legal_residuals(
    record: Mapping[str, Any], expected_signature_sha256: str,
    expected_continuity_signature_sha256: str | None = None,
) -> tuple[float, float] | None:
    if record.get("status") != "legal_topology":
        return None
    if expected_signature_sha256 not in (
        record.get("topology_signature_sha256"),
        record.get("legacy_topology_signature_sha256"),
    ):
        return None
    if (
        expected_continuity_signature_sha256 is not None
        and record.get("topology_signature_sha256") != expected_continuity_signature_sha256
    ):
        return None
    residuals = record.get("residual_vector")
    if not isinstance(residuals, Sequence) or isinstance(residuals, (str, bytes)) or len(residuals) != 2:
        raise CandidateContractError("legal P1/P2 trial must expose exactly two residuals")
    return (
        _finite(residuals[0], "positive-mirror-turn y residual"),
        _finite(residuals[1], "P2-reference signed-tangent-ratio residual"),
    )


def solve_p2_angle_slice_from_legal_anchor(
    evaluator: TrialEvaluator,
    predictor: VoltagePredictor,
    *,
    legal_anchor_pair_v: tuple[float, float],
    expected_signature_sha256: str,
    controls: AngleSliceControls,
) -> dict[str, Any]:
    """Solve the angle condition or locate its preceding topology boundary."""
    controls.validate()
    if not expected_signature_sha256:
        raise CandidateContractError("expected topology signature is required")
    p1_v, anchor_p2_v = (
        _finite(legal_anchor_pair_v[0], "anchor P1 voltage"),
        _finite(legal_anchor_pair_v[1], "anchor P2 voltage"),
    )
    if not controls.p2_bounds_v[0] <= anchor_p2_v <= controls.p2_bounds_v[1]:
        raise CandidateContractError("anchor P2 voltage lies outside the discovery domain")
    evaluations: list[Mapping[str, Any]] = []
    continuity_signature_sha256: str | None = None

    def evaluate(
        p2_v: float,
    ) -> tuple[Mapping[str, Any], tuple[float, float] | None]:
        if len(evaluations) >= controls.maximum_evaluations:
            raise CandidateContractError("P2 angle-slice evaluation budget exhausted")
        record = evaluator((p1_v, p2_v))
        evaluations.append(record)
        return record, _legal_residuals(
            record, expected_signature_sha256, continuity_signature_sha256,
        )

    anchor, anchor_residuals = evaluate(anchor_p2_v)
    if anchor_residuals is None:
        raise CandidateContractError("declared P2 anchor is not legal on the expected topology")
    continuity_signature_sha256 = str(anchor.get("topology_signature_sha256") or "")
    if not continuity_signature_sha256:
        raise CandidateContractError("declared P2 anchor lacks selected-turn continuity identity")
    anchor_y_residual, anchor_angle_residual = anchor_residuals
    if abs(anchor_angle_residual) <= controls.angle_ratio_root_tolerance:
        return {
            "status": "angle_root_reached_at_anchor",
            "p1_voltage_v": p1_v,
            "analytic_predicted_p2_voltage_v": anchor_p2_v,
            "selected_p2_voltage_v": anchor_p2_v,
            "selected_positive_mirror_turn_y_residual_mm": anchor_y_residual,
            "selected_angle_ratio_residual": anchor_angle_residual,
            "evaluation_count": len(evaluations),
            "evaluations": list(evaluations),
        }
    predicted_p2_v = _finite(predictor(anchor), "analytic predicted P2 voltage")
    if not controls.p2_bounds_v[0] <= predicted_p2_v <= controls.p2_bounds_v[1]:
        return {
            "status": "analytic_prediction_outside_p2_domain",
            "p1_voltage_v": p1_v,
            "analytic_predicted_p2_voltage_v": predicted_p2_v,
            "selected_p2_voltage_v": None,
            "selected_angle_ratio_residual": None,
            "evaluation_count": len(evaluations),
            "evaluations": list(evaluations),
        }
    proposal, proposal_residuals = evaluate(predicted_p2_v)
    if (
        proposal_residuals is not None
        and abs(proposal_residuals[1]) <= controls.angle_ratio_root_tolerance
    ):
        return {
            "status": "angle_root_reached_at_analytic_prediction",
            "p1_voltage_v": p1_v,
            "analytic_predicted_p2_voltage_v": predicted_p2_v,
            "selected_p2_voltage_v": predicted_p2_v,
            "selected_positive_mirror_turn_y_residual_mm": proposal_residuals[0],
            "selected_angle_ratio_residual": proposal_residuals[1],
            "evaluation_count": len(evaluations),
            "evaluations": list(evaluations),
        }

    legal_voltage = anchor_p2_v
    legal_y_residual = anchor_y_residual
    legal_angle_residual = anchor_angle_residual
    remote_voltage = predicted_p2_v
    remote_residuals = proposal_residuals
    remote_is_same_topology = proposal_residuals is not None
    if (
        remote_is_same_topology
        and legal_angle_residual * remote_residuals[1] > 0.0
    ):
        return {
            "status": "analytic_prediction_legal_without_angle_enclosure",
            "p1_voltage_v": p1_v,
            "analytic_predicted_p2_voltage_v": predicted_p2_v,
            "selected_p2_voltage_v": remote_voltage,
            "selected_positive_mirror_turn_y_residual_mm": remote_residuals[0],
            "selected_angle_ratio_residual": remote_residuals[1],
            "evaluation_count": len(evaluations),
            "evaluations": list(evaluations),
        }

    while len(evaluations) < controls.maximum_evaluations:
        interval = abs(remote_voltage - legal_voltage)
        tolerance = (
            controls.p2_root_tolerance_v
            if remote_is_same_topology
            else controls.topology_boundary_tolerance_v
        )
        if interval <= tolerance:
            break
        midpoint = 0.5 * (legal_voltage + remote_voltage)
        _record, midpoint_residuals = evaluate(midpoint)
        if midpoint_residuals is None:
            remote_voltage = midpoint
            remote_residuals = None
            remote_is_same_topology = False
            continue
        midpoint_y_residual, midpoint_angle_residual = midpoint_residuals
        if abs(midpoint_angle_residual) <= controls.angle_ratio_root_tolerance:
            return {
                "status": "angle_root_reached_by_bisection",
                "p1_voltage_v": p1_v,
                "analytic_predicted_p2_voltage_v": predicted_p2_v,
                "selected_p2_voltage_v": midpoint,
                "selected_positive_mirror_turn_y_residual_mm": midpoint_y_residual,
                "selected_angle_ratio_residual": midpoint_angle_residual,
                "evaluation_count": len(evaluations),
                "evaluations": list(evaluations),
            }
        if remote_is_same_topology:
            assert remote_residuals is not None
            if legal_angle_residual * midpoint_angle_residual <= 0.0:
                remote_voltage, remote_residuals = midpoint, midpoint_residuals
            else:
                legal_voltage = midpoint
                legal_y_residual = midpoint_y_residual
                legal_angle_residual = midpoint_angle_residual
        else:
            legal_voltage = midpoint
            legal_y_residual = midpoint_y_residual
            legal_angle_residual = midpoint_angle_residual

    status = (
        "angle_root_bracket_iteration_limit"
        if remote_is_same_topology
        else "topology_boundary_before_angle_root"
    )
    return {
        "status": status,
        "p1_voltage_v": p1_v,
        "analytic_predicted_p2_voltage_v": predicted_p2_v,
        "selected_p2_voltage_v": None,
        "selected_angle_ratio_residual": None,
        "last_legal_p2_voltage_v": legal_voltage,
        "last_legal_positive_mirror_turn_y_residual_mm": legal_y_residual,
        "last_legal_angle_ratio_residual": legal_angle_residual,
        "remote_p2_voltage_v": remote_voltage,
        "evaluation_count": len(evaluations),
        "evaluations": list(evaluations),
    }
