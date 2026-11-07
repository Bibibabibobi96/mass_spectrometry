"""Polynomial diagnostics for longitudinal position (mm) and velocity (mm/us)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class LongitudinalPolynomialFit:
    """Common diagnostics and residuals; consumers own extra report fields."""

    metrics: dict[str, Any]
    residual_mm_per_us: np.ndarray


def fit_longitudinal_polynomial(
    z_mm: np.ndarray, vz_mm_per_us: np.ndarray, degree: int
) -> LongitudinalPolynomialFit:
    """Fit velocity against position with the existing NumPy polyfit convention.

    Callers validate finite paired samples and select an identifiable degree
    (at least one). NumPy fit errors and rank warnings propagate unchanged.
    Residual sigma uses the sample convention, ddof=1; no noise or physical
    qualification is inferred from the model-conditioned residual.
    """
    coefficients = np.polyfit(z_mm, vz_mm_per_us, degree)
    residual = vz_mm_per_us - np.polyval(coefficients, z_mm)
    metrics: dict[str, Any] = {
        "degree": degree,
        "coefficients_descending_power": [float(value) for value in coefficients],
        "coefficient_units_descending_power": [
            "mm_per_us_per_mm" if power == 1 else (
                "mm_per_us" if power == 0 else f"mm_per_us_per_mm{power}"
            )
            for power in range(degree, -1, -1)
        ],
        "residual_sample_sigma_mm_per_us": float(np.std(residual, ddof=1)),
        "residual_rms_mm_per_us": float(np.sqrt(np.mean(residual**2))),
        "residual_max_abs_mm_per_us": float(np.max(np.abs(residual))),
        "intercept_mm_per_us": float(coefficients[-1]),
        "k_per_us": float(coefficients[-2]),
    }
    if degree >= 2:
        metrics["quadratic_coefficient_per_mm_us"] = float(coefficients[-3])
    if degree >= 3:
        metrics["cubic_coefficient_per_mm2_us"] = float(coefficients[-4])
    return LongitudinalPolynomialFit(metrics, residual)
