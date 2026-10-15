"""Sampled mirror axis fields and period mathematics used by fixed-grid correction."""
from __future__ import annotations

import csv
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.integrate import IntegrationWarning, quad
from scipy.interpolate import CubicSpline, PPoly

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


GROUPS = ("mirror_B", "mirror_C", "mirror_D", "mirror_E")


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
