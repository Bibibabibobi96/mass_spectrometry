"""Resolve the manufactured MR-TOF fast-phase return contract.

The baseline declares the desired slow-return/fast-period ratio and path
symmetry.  Numerical consumers receive the derived whole- and half-cycle
counts and return side; no particular K value exists in source code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


OPPOSITE_MIRROR_TURN = "opposite_mirror_turn__z_reflected_nonoverlapping"


@dataclass(frozen=True)
class DriftPhaseContract:
    complete_oscillation_count: int
    return_phase: str
    phase_offset_periods: float
    target_period_ratio: float
    target_half_oscillation_count: int
    origin_mirror_side: int
    return_mirror_side: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_drift_phase_contract(contract: dict[str, Any]) -> DriftPhaseContract:
    """Derive the unique opposite-turn phase from the project baseline."""
    nominal = contract.get("nominal")
    if not isinstance(nominal, dict):
        raise CandidateContractError("MR-TOF nominal contract is missing")
    ratio_value = nominal.get("target_drift_period_ratio")
    if isinstance(ratio_value, bool):
        raise CandidateContractError(
            "nominal.target_drift_period_ratio must be a positive integer or half-integer"
        )
    try:
        ratio = float(ratio_value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(
            "nominal.target_drift_period_ratio must be a positive integer or half-integer"
        ) from error
    doubled = round(2.0 * ratio)
    if ratio <= 0.0 or abs(2.0 * ratio - doubled) > 1e-12:
        raise CandidateContractError(
            "nominal.target_drift_period_ratio must be a positive integer or half-integer"
        )
    phase = nominal.get("fast_path_symmetry")
    if phase != OPPOSITE_MIRROR_TURN:
        raise CandidateContractError(
            "manufactured MR-TOF requires the declared opposite-mirror-turn return phase"
        )
    count = int(ratio)
    phase_offset = ratio - count
    if phase_offset != 0.5:
        raise CandidateContractError(
            "z-reflected non-overlapping turn-to-turn paths require a half-integer period ratio"
        )
    half_cycles = int(doubled)
    return DriftPhaseContract(
        complete_oscillation_count=count,
        return_phase=phase,
        phase_offset_periods=phase_offset,
        target_period_ratio=ratio,
        target_half_oscillation_count=half_cycles,
        origin_mirror_side=1,
        return_mirror_side=-1,
    )
