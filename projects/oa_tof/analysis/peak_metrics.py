"""Canonical solver-independent oa-TOF peak metrics.

This module contains numerical definitions only.  File parsing, plotting and
workflow orchestration live in ``reference_analysis.py`` so the metrics can be
tested without a GUI or artifact workspace.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy import stats


FWHM_FACTOR = 2.0 * np.sqrt(2.0 * np.log(2.0))


@dataclass(frozen=True)
class AnalysisSettings:
    """Versioned numerical settings mirrored by analysis_contract.json."""

    grid_points: int = 4001
    bandwidth_multiplier: float = 1.06
    mode_threshold_fraction: float = 0.10
    standardized_grid_min: float = -6.0
    standardized_grid_max: float = 6.0
    standardized_grid_points: int = 2001

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["bandwidth_rule"] = (
            "bandwidth_multiplier*sample_standard_deviation*N^(-1/5)"
        )
        result["half_height_interpolation"] = "linear"
        return result


def _as_valid_sample(values: np.ndarray, name: str) -> np.ndarray:
    sample = np.asarray(values, dtype=float).reshape(-1)
    if sample.size < 3:
        raise ValueError(f"{name} requires at least three samples")
    if not np.all(np.isfinite(sample)):
        raise ValueError(f"{name} contains non-finite values")
    if np.std(sample, ddof=1) <= 0:
        raise ValueError(f"{name} has zero variance")
    return sample


def _kde_density(
    sample: np.ndarray,
    grid: np.ndarray,
    settings: AnalysisSettings,
) -> np.ndarray:
    factor = settings.bandwidth_multiplier * sample.size ** (-1.0 / 5.0)
    estimator = stats.gaussian_kde(sample, bw_method=factor)
    return np.asarray(estimator(grid), dtype=float)


def _spectrum_grid(sample: np.ndarray, settings: AnalysisSettings) -> np.ndarray:
    sample_std = float(np.std(sample, ddof=1))
    sample_range = float(np.ptp(sample))
    padding = max(0.20 * sample_range, 4.0 * sample_std, np.finfo(float).eps)
    return np.linspace(
        float(np.min(sample)) - padding,
        float(np.max(sample)) + padding,
        settings.grid_points,
    )


def _linear_crossing(
    x1: float, y1: float, x2: float, y2: float, target: float
) -> float:
    if y2 == y1:
        return 0.5 * (x1 + x2)
    return x1 + (target - y1) * (x2 - x1) / (y2 - y1)


def half_height_width(
    grid: np.ndarray, density: np.ndarray
) -> tuple[float, float, float, int]:
    """Return direct FWHM, left/right crossings and the global peak index."""

    peak_index = int(np.argmax(density))
    half_height = 0.5 * float(density[peak_index])
    left_candidates = np.flatnonzero(density[: peak_index + 1] <= half_height)
    right_candidates = np.flatnonzero(density[peak_index:] <= half_height)
    if left_candidates.size == 0 or right_candidates.size == 0:
        raise ValueError("KDE grid does not bracket both half-height crossings")

    left_below = int(left_candidates[-1])
    right_below = peak_index + int(right_candidates[0])
    if left_below >= peak_index or right_below <= peak_index:
        raise ValueError("Degenerate half-height bracket")

    left = _linear_crossing(
        float(grid[left_below]),
        float(density[left_below]),
        float(grid[left_below + 1]),
        float(density[left_below + 1]),
        half_height,
    )
    right = _linear_crossing(
        float(grid[right_below - 1]),
        float(density[right_below - 1]),
        float(grid[right_below]),
        float(density[right_below]),
        half_height,
    )
    return right - left, left, right, peak_index


def _significant_mode_count(
    density: np.ndarray, threshold_fraction: float
) -> int:
    peak = float(np.max(density))
    local_maximum = (density[1:-1] > density[:-2]) & (
        density[1:-1] >= density[2:]
    )
    significant = density[1:-1] >= threshold_fraction * peak
    return int(np.count_nonzero(local_maximum & significant))


def compute_peak_metrics(
    tof_us: np.ndarray,
    nominal_mass_Da: float,
    settings: AnalysisSettings | None = None,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Compute canonical direct-FWHM and shape metrics from detector TOFs."""

    settings = settings or AnalysisSettings()
    tof = _as_valid_sample(tof_us, "tof_us")
    if np.any(tof <= 0):
        raise ValueError("tof_us must be positive")
    if not np.isfinite(nominal_mass_Da) or nominal_mass_Da <= 0:
        raise ValueError("nominal_mass_Da must be positive")

    mean_tof_us = float(np.mean(tof))
    apparent_mass = nominal_mass_Da * (tof / mean_tof_us) ** 2

    time_grid = _spectrum_grid(tof, settings)
    time_density = _kde_density(tof, time_grid, settings)
    time_fwhm_us, time_left, time_right, time_peak_index = half_height_width(
        time_grid, time_density
    )

    mass_grid = _spectrum_grid(apparent_mass, settings)
    mass_density = _kde_density(apparent_mass, mass_grid, settings)
    mass_fwhm_Da, mass_left, mass_right, mass_peak_index = half_height_width(
        mass_grid, mass_density
    )

    std_tof_us = float(np.std(tof, ddof=1))
    std_mass_Da = float(np.std(apparent_mass, ddof=1))
    mass_peak_Da = float(mass_grid[mass_peak_index])
    left_hwhm_Da = mass_peak_Da - mass_left
    right_hwhm_Da = mass_right - mass_peak_Da
    skewness = float(stats.skew(tof, bias=False))
    excess_kurtosis = float(stats.kurtosis(tof, fisher=True, bias=False))
    standardized = (tof - mean_tof_us) / std_tof_us

    metrics: dict[str, Any] = {
        "particles": int(tof.size),
        "nominal_mass_Da": float(nominal_mass_Da),
        "mean_tof_us": mean_tof_us,
        "std_tof_ns": std_tof_us * 1.0e3,
        "direct_fwhm_tof_ns": time_fwhm_us * 1.0e3,
        "gaussian_proxy_fwhm_tof_ns": FWHM_FACTOR * std_tof_us * 1.0e3,
        "time_equivalent_resolution": mean_tof_us / (2.0 * time_fwhm_us),
        "mean_apparent_mass_Da": float(np.mean(apparent_mass)),
        "std_apparent_mass_Da": std_mass_Da,
        "kde_peak_mass_Da": mass_peak_Da,
        "direct_fwhm_mass_Da": mass_fwhm_Da,
        "gaussian_proxy_fwhm_mass_Da": FWHM_FACTOR * std_mass_Da,
        "mass_resolution": float(nominal_mass_Da / mass_fwhm_Da),
        "tof_skewness": skewness,
        "tof_excess_kurtosis": excess_kurtosis,
        "left_hwhm_mass_Da": left_hwhm_Da,
        "right_hwhm_mass_Da": right_hwhm_Da,
        "hwhm_asymmetry_right_over_left": right_hwhm_Da / left_hwhm_Da,
        "significant_kde_modes": _significant_mode_count(
            mass_density, settings.mode_threshold_fraction
        ),
        "tail_fraction_outside_3sigma": float(
            np.mean(np.abs(standardized) > 3.0)
        ),
        "direct_vs_gaussian_mass_fwhm_difference_pct": 100.0
        * (mass_fwhm_Da - FWHM_FACTOR * std_mass_Da)
        / (FWHM_FACTOR * std_mass_Da),
        "direct_mass_vs_time_resolution_difference_pct": 100.0
        * (
            nominal_mass_Da / mass_fwhm_Da
            - mean_tof_us / (2.0 * time_fwhm_us)
        )
        / (nominal_mass_Da / mass_fwhm_Da),
    }

    spectra = {
        "tof_us": tof,
        "apparent_mass_Da": apparent_mass,
        "time_grid_us": time_grid,
        "time_density": time_density,
        "time_density_normalized": time_density / np.max(time_density),
        "time_half_left_us": np.asarray(time_left),
        "time_half_right_us": np.asarray(time_right),
        "time_peak_us": np.asarray(time_grid[time_peak_index]),
        "mass_grid_Da": mass_grid,
        "mass_density": mass_density,
        "mass_density_normalized": mass_density / np.max(mass_density),
        "mass_half_left_Da": np.asarray(mass_left),
        "mass_half_right_Da": np.asarray(mass_right),
        "mass_peak_Da": np.asarray(mass_peak_Da),
    }
    return metrics, spectra


def compute_detector_metrics(
    detector_x_mm: np.ndarray, detector_y_mm: np.ndarray
) -> dict[str, float]:
    x = np.asarray(detector_x_mm, dtype=float).reshape(-1)
    y = np.asarray(detector_y_mm, dtype=float).reshape(-1)
    if x.size != y.size or x.size == 0:
        raise ValueError("detector x/y arrays must have equal nonzero length")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("detector coordinates contain non-finite values")
    radius = np.hypot(x, y)
    return {
        "impact_centroid_x_mm": float(np.mean(x)),
        "impact_centroid_y_mm": float(np.mean(y)),
        "impact_rms_radius_mm": float(np.sqrt(np.mean(radius**2))),
        "impact_r95_mm": float(np.quantile(radius, 0.95, method="linear")),
        "impact_max_radius_mm": float(np.max(radius)),
    }


def compare_peak_shapes(
    left_tof_us: np.ndarray,
    right_tof_us: np.ndarray,
    settings: AnalysisSettings | None = None,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Compare standardized peak structure independently of absolute width."""

    settings = settings or AnalysisSettings()
    left = _as_valid_sample(left_tof_us, "left_tof_us")
    right = _as_valid_sample(right_tof_us, "right_tof_us")
    left_standardized = (left - np.mean(left)) / np.std(left, ddof=1)
    right_standardized = (right - np.mean(right)) / np.std(right, ddof=1)
    grid = np.linspace(
        settings.standardized_grid_min,
        settings.standardized_grid_max,
        settings.standardized_grid_points,
    )
    left_density = _kde_density(left_standardized, grid, settings)
    right_density = _kde_density(right_standardized, grid, settings)
    ks_result = stats.ks_2samp(left_standardized, right_standardized)
    paired_correlation: float | None = None
    if left.size == right.size:
        paired_correlation = float(np.corrcoef(left_standardized, right_standardized)[0, 1])

    comparison = {
        "left_particles": int(left.size),
        "right_particles": int(right.size),
        "mean_tof_difference_right_minus_left_ns": float(
            (np.mean(right) - np.mean(left)) * 1.0e3
        ),
        "standardized_kde_overlap": float(
            np.trapezoid(np.minimum(left_density, right_density), grid)
        ),
        "standardized_ks_distance": float(ks_result.statistic),
        "standardized_ks_pvalue": float(ks_result.pvalue),
        "paired_standardized_tof_correlation": paired_correlation,
    }
    spectra = {
        "standardized_grid": grid,
        "left_density": left_density,
        "right_density": right_density,
        "left_density_normalized": left_density / np.max(left_density),
        "right_density_normalized": right_density / np.max(right_density),
        "left_standardized_tof": left_standardized,
        "right_standardized_tof": right_standardized,
    }
    return comparison, spectra
