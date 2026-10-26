"""Unweighted centered population moments of two already selected quantities.

Callers own sample selection, units, scientific models and qualification.
"""
from __future__ import annotations

import math

import numpy as np


def population_pair_moments(first: np.ndarray, second: np.ndarray) -> dict[str, float | None]:
    """Return ddof=0 variances, covariance and Pearson correlation.

    Empty pairs have null moments; singleton pairs have zero variances and
    covariance. Correlation is null when either quantity is constant.
    No clipping, weighting, unit conversion or particle selection is performed.
    """
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if first.ndim != 1 or second.shape != first.shape:
        raise ValueError("population moments require equally sized one-dimensional pairs")
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError("population moments require finite pairs")
    if not len(first):
        return {key: None for key in ("variance_first", "variance_second", "covariance", "correlation")}
    first_centered, second_centered = first - first.mean(), second - second.mean()
    variance_first = float(np.mean(first_centered**2))
    variance_second = float(np.mean(second_centered**2))
    covariance = float(np.mean(first_centered * second_centered))
    denominator = math.sqrt(variance_first * variance_second)
    return dict(variance_first=variance_first, variance_second=variance_second,
                covariance=covariance, correlation=covariance / denominator if denominator else None)
