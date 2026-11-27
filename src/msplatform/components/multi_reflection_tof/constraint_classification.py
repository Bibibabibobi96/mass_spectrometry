"""MR numerical constraint-rank and compatibility classification."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from msplatform.components.multi_reflection_tof.candidate_contract import CandidateContractError


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class ConstraintClassification:
    """Rank-based determination state for a declared nonlinear solve at one trial."""

    unknown_count: int
    declared_constraint_count: int
    independent_constraint_rank: int | None
    augmented_rank: int | None
    nullity: int | None
    redundant_constraint_count: int | None
    singular_values: tuple[float, ...] | None
    condition_number_2: float | None
    scaled_irreducible_residual_norm_2: float | None
    scaled_residual_norm_2: float | None
    status: str
    reason: str


def classify_constraint_system(
    unknown_names: Sequence[str],
    constraint_names: Sequence[str],
    *,
    jacobian_rows: Sequence[Sequence[float]] | None = None,
    residuals: Sequence[float] | None = None,
    parameter_scales: Sequence[float] | None = None,
    residual_scales: Sequence[float] | None = None,
    relative_rank_tolerance: float = 1e-10,
    compatibility_tolerance: float = 1e-8,
) -> ConstraintClassification:
    """Classify a locally linearized solve with a scaled SVD.

    Without a numerical Jacobian, the result is deliberately ``rank_unverified``.
    The SVD is applied to ``diag(1/r_scale) J diag(p_scale)``.  When a residual
    is supplied, its projection on the Jacobian's left null space is the part
    that no local parameter correction can remove.  This distinguishes a
    square determined system from an overdetermined but consistent system and
    from a locally incompatible one.
    """
    unknowns = tuple(unknown_names)
    constraints = tuple(constraint_names)
    if not unknowns or not constraints or any(not isinstance(name, str) or not name for name in unknowns + constraints):
        raise CandidateContractError("constraint classification needs nonempty named unknowns and constraints")
    if len(set(unknowns)) != len(unknowns) or len(set(constraints)) != len(constraints):
        raise CandidateContractError("constraint classification names must be unique")
    if jacobian_rows is None:
        return ConstraintClassification(
            len(unknowns), len(constraints), None, None, None, None, None, None,
            None, None, "rank_unverified",
            "a numerical Jacobian is required before determination can be claimed",
        )
    if len(jacobian_rows) != len(constraints):
        raise CandidateContractError("Jacobian must have one row per declared constraint")
    matrix = np.asarray(jacobian_rows, dtype=float)
    if matrix.shape != (len(constraints), len(unknowns)) or not np.all(np.isfinite(matrix)):
        raise CandidateContractError("each finite Jacobian row must have one element per declared unknown")
    p_scales = np.ones(len(unknowns)) if parameter_scales is None else np.asarray(parameter_scales, dtype=float)
    r_scales = np.ones(len(constraints)) if residual_scales is None else np.asarray(residual_scales, dtype=float)
    if p_scales.shape != (len(unknowns),) or r_scales.shape != (len(constraints),):
        raise CandidateContractError("classification scales must match the named parameters and constraints")
    if not np.all(np.isfinite(p_scales)) or not np.all(np.isfinite(r_scales)) or np.any(p_scales <= 0.0) or np.any(r_scales <= 0.0):
        raise CandidateContractError("classification scales must be finite and positive")
    rank_tolerance = _finite(relative_rank_tolerance, "relative rank tolerance")
    consistency_tolerance = _finite(compatibility_tolerance, "compatibility tolerance")
    if not 0.0 < rank_tolerance < 1.0 or consistency_tolerance < 0.0:
        raise CandidateContractError("rank and compatibility tolerances are invalid")
    scaled_matrix = matrix * p_scales[np.newaxis, :] / r_scales[:, np.newaxis]
    left_vectors, singular_values, _right_vectors = np.linalg.svd(scaled_matrix, full_matrices=True)
    threshold = rank_tolerance * (float(singular_values[0]) if singular_values.size else 1.0)
    rank = int(np.count_nonzero(singular_values > threshold))
    nullity = len(unknowns) - rank
    redundancy = len(constraints) - rank
    finite_singular_values = singular_values[singular_values > threshold]
    condition = (
        float(finite_singular_values[0] / finite_singular_values[-1])
        if rank == len(unknowns) and finite_singular_values.size
        else math.inf
    )
    augmented_rank: int | None = None
    irreducible_norm: float | None = None
    scaled_residual_norm: float | None = None
    if residuals is not None:
        if len(residuals) != len(constraints):
            raise CandidateContractError("residual vector must have one value per declared constraint")
        scaled_residual = np.asarray([_finite(value, "residual") for value in residuals]) / r_scales
        scaled_residual_norm = float(np.linalg.norm(scaled_residual))
        left_null = left_vectors[:, rank:]
        irreducible_norm = float(np.linalg.norm(left_null.T @ scaled_residual))
        augmented_rank = rank + int(irreducible_norm > consistency_tolerance)
        if irreducible_norm > consistency_tolerance:
            return ConstraintClassification(
                len(unknowns), len(constraints), rank, augmented_rank, nullity, redundancy,
                tuple(float(value) for value in singular_values), condition,
                irreducible_norm, scaled_residual_norm, "locally_incompatible",
                "the scaled residual has a component outside the local Jacobian column space",
            )
    if rank < len(unknowns):
        status = "underdetermined"
        reason = "independent constraints leave one or more local physical degrees of freedom"
    elif len(constraints) == len(unknowns):
        status = "square_exact"
        reason = "a square full-rank local system determines every declared physical degree of freedom"
    else:
        status = "overdetermined_consistent"
        reason = "the full-column-rank overdetermined system is locally consistent within the declared scaled tolerance"
    return ConstraintClassification(
        len(unknowns), len(constraints), rank, augmented_rank, nullity, redundancy,
        tuple(float(value) for value in singular_values), condition,
        irreducible_norm, scaled_residual_norm, status, reason,
    )
