"""Centered population moments of already selected quantities.

Callers own sample selection, units, scientific models and qualification.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class PopulationMoments:
    """Population moments in input-column order, without unit conversion.

    Each row is one caller-selected observation, not necessarily a distinct
    particle. ``effective_sample_count`` is (sum w)^2 / sum(w^2), a relative
    weight concentration measure, not a count of independent physical ions.
    Empty input has zero counts/weight sum and null mean/covariance.
    """

    sample_count: int
    weight_sum: float
    effective_sample_count: float
    mean: np.ndarray | None
    covariance: np.ndarray | None


def population_moments(values: np.ndarray, weights: np.ndarray | None = None) -> PopulationMoments:
    """Return means and centered covariance for finite rows of variables.

    ``values`` must have shape (observations, variables), with at least one
    variable. Optional weights are finite, strictly positive relative weights,
    one per row; omitted weights are one. Covariance divides by sum(weights)
    (ddof=0), with no unbiased correction, clipping or removal of rows. Variable
    units remain unchanged; covariance units are the product of column units.
    Shape, invalid weights, nonfinite inputs/results raise ValueError. No I/O.
    """
    if np.iscomplexobj(values):
        raise ValueError("population moments require real values")
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or values.shape[1] == 0:
        raise ValueError("population moments require a two-dimensional array with at least one variable")
    if not np.isfinite(values).all():
        raise ValueError("population moments require finite values")
    count, dimension = values.shape
    normalized = None
    weight_sum, effective = float(count), float(count)
    if weights is not None:
        supplied = np.asarray(weights)
        if (supplied.shape != (count,) or supplied.dtype.kind not in "iuf" or
                any(isinstance(value, (bool, np.bool_)) for value in np.asarray(weights, dtype=object).flat)):
            raise ValueError("relative weights must be one numeric value per observation, without booleans")
        supplied = supplied.astype(float)
        if not np.isfinite(supplied).all() or np.any(supplied <= 0):
            raise ValueError("relative weights must be finite and strictly positive")
        with np.errstate(over="ignore"):
            weight_sum = float(supplied.sum())
        if not math.isfinite(weight_sum):
            raise ValueError("relative weight sum must be finite")
        if count:
            normalized = supplied / weight_sum
            effective = float(1. / np.sum(normalized**2))
    if not count:
        return PopulationMoments(0, 0., 0., None, None)
    # Columnwise means/products preserve the existing two-variable reduction
    # order and avoid allocating an observations-by-variables-squared array.
    with np.errstate(over="ignore", invalid="ignore"):
        mean = np.array([np.average(values[:, i], weights=normalized) for i in range(dimension)])
        centered = values - mean
        covariance = np.empty((dimension, dimension))
        for i in range(dimension):
            for j in range(i, dimension):
                covariance[i, j] = covariance[j, i] = np.average(centered[:, i] * centered[:, j], weights=normalized)
    if not np.isfinite(mean).all() or not np.isfinite(covariance).all():
        raise ValueError("population moments exceed the finite numeric range")
    return PopulationMoments(count, weight_sum, effective, mean, covariance)


def population_pair_moments(first: np.ndarray, second: np.ndarray) -> dict[str, float | None]:
    """Return ddof=0 variances, covariance and Pearson correlation.

    Empty pairs have null moments; singleton pairs have zero variances and
    covariance. Correlation is null when either quantity is constant.
    No clipping, weighting, unit conversion or particle selection is performed.
    """
    first, second = np.asarray(first), np.asarray(second)
    if first.ndim != 1 or second.shape != first.shape:
        raise ValueError("population moments require equally sized one-dimensional pairs")
    moments = population_moments(np.column_stack((first, second)))
    if moments.covariance is None:
        return {key: None for key in ("variance_first", "variance_second", "covariance", "correlation")}
    variance_first = float(moments.covariance[0, 0])
    variance_second = float(moments.covariance[1, 1])
    covariance = float(moments.covariance[0, 1])
    denominator = math.sqrt(variance_first * variance_second)
    return dict(variance_first=variance_first, variance_second=variance_second,
                covariance=covariance, correlation=covariance / denominator if denominator else None)
