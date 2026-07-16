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


def _r_squared(observed: np.ndarray, fitted: np.ndarray) -> float:
    residual = float(np.sum((observed - fitted) ** 2))
    total = float(np.sum((observed - np.mean(observed)) ** 2))
    if total <= 0:
        raise ValueError("R-squared requires a nonconstant response")
    return 1.0 - residual / total


def _correlation(a: np.ndarray, b: np.ndarray) -> float | None:
    if np.std(a, ddof=1) <= 0 or np.std(b, ddof=1) <= 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def compute_source_mapping_metrics(
    tof_us: np.ndarray,
    initial_x_mm: np.ndarray,
    initial_y_mm: np.ndarray,
    initial_z_mm: np.ndarray,
    initial_energy_eV: np.ndarray,
    z_bins: int = 10,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Quantify initial-condition to TOF mapping without solver-specific APIs."""

    tof = _as_valid_sample(tof_us, "tof_us")
    predictors = {
        "initial_x_mm": np.asarray(initial_x_mm, dtype=float).reshape(-1),
        "initial_y_mm": np.asarray(initial_y_mm, dtype=float).reshape(-1),
        "initial_z_mm": np.asarray(initial_z_mm, dtype=float).reshape(-1),
        "initial_energy_eV": np.asarray(initial_energy_eV, dtype=float).reshape(-1),
    }
    for name, values in predictors.items():
        if values.size != tof.size:
            raise ValueError(f"{name} length differs from tof_us")
        if not np.all(np.isfinite(values)):
            raise ValueError(f"{name} contains non-finite values")
    if z_bins < 2:
        raise ValueError("z_bins must be at least 2")

    x = predictors["initial_x_mm"]
    y = predictors["initial_y_mm"]
    z = predictors["initial_z_mm"]
    energy = predictors["initial_energy_eV"]
    xc, yc = x - np.mean(x), y - np.mean(y)
    zc, ec = z - np.mean(z), energy - np.mean(energy)

    linear_design = np.column_stack((np.ones(tof.size), xc, yc, zc, ec))
    linear_fit = linear_design @ np.linalg.lstsq(linear_design, tof, rcond=None)[0]
    quadratic_design = np.column_stack((linear_design, zc**2))
    quadratic_fit = quadratic_design @ np.linalg.lstsq(
        quadratic_design, tof, rcond=None
    )[0]
    z_only_design = np.column_stack((np.ones(tof.size), zc, zc**2))
    z_only_coefficients = np.linalg.lstsq(z_only_design, tof, rcond=None)[0]
    z_only_fit = z_only_design @ z_only_coefficients

    curvature = float(z_only_coefficients[2])
    vertex_z_mm = (
        float(np.mean(z) - z_only_coefficients[1] / (2.0 * curvature))
        if abs(curvature) > np.finfo(float).eps
        else None
    )
    vertex_inside = bool(
        vertex_z_mm is not None and np.min(z) <= vertex_z_mm <= np.max(z)
    )

    source_design = np.column_stack((np.ones(tof.size), z, z**2, energy, x, y))
    source_fit = source_design @ np.linalg.lstsq(source_design, tof, rcond=None)[0]
    metrics = {
        "particles": int(tof.size),
        "linear_all_predictors_r_squared": _r_squared(tof, linear_fit),
        "quadratic_z_plus_linear_predictors_r_squared": _r_squared(
            tof, quadratic_fit
        ),
        "z_only_quadratic_r_squared": _r_squared(tof, z_only_fit),
        "source_z2_energy_xy_fit_r_squared": _r_squared(tof, source_fit),
        "z_curvature_us_per_mm2": curvature,
        "quadratic_vertex_z_mm": vertex_z_mm,
        "vertex_inside_source": vertex_inside,
        "corr_tof_initial_x": _correlation(tof, x),
        "corr_tof_initial_y": _correlation(tof, y),
        "corr_tof_initial_z": _correlation(tof, z),
        "corr_tof_initial_energy": _correlation(tof, energy),
    }

    edges = np.linspace(float(np.min(z)), float(np.max(z)), z_bins + 1)
    indices = np.searchsorted(edges, z, side="right") - 1
    indices[z == edges[-1]] = z_bins - 1
    counts = np.zeros(z_bins, dtype=int)
    means = np.full(z_bins, np.nan)
    standard_deviations_ns = np.full(z_bins, np.nan)
    for index in range(z_bins):
        selected = tof[indices == index]
        counts[index] = selected.size
        if selected.size:
            means[index] = float(np.mean(selected))
        if selected.size > 1:
            standard_deviations_ns[index] = float(np.std(selected, ddof=1) * 1.0e3)

    z_plot = np.linspace(float(np.min(z)), float(np.max(z)), 401)
    zc_plot = z_plot - np.mean(z)
    arrays = {
        "z_bin_center_mm": 0.5 * (edges[:-1] + edges[1:]),
        "z_bin_particle_count": counts,
        "z_bin_mean_tof_us": means,
        "z_bin_std_tof_ns": standard_deviations_ns,
        "z_plot_mm": z_plot,
        "z_quadratic_fit_tof_us": z_only_coefficients[0]
        + z_only_coefficients[1] * zc_plot
        + z_only_coefficients[2] * zc_plot**2,
    }
    return metrics, arrays


def _bootstrap_resolution_batch(
    tof_batch_us: np.ndarray,
    nominal_mass_Da: float,
    settings: AnalysisSettings,
) -> np.ndarray:
    """Vectorized canonical direct-FWHM resolution for bootstrap batches."""

    means = np.mean(tof_batch_us, axis=1, keepdims=True)
    apparent_mass = nominal_mass_Da * (tof_batch_us / means) ** 2
    sample_std = np.std(apparent_mass, axis=1, ddof=1)
    sample_range = np.ptp(apparent_mass, axis=1)
    padding = np.maximum(0.20 * sample_range, 4.0 * sample_std)
    padding = np.maximum(padding, np.finfo(float).eps)
    lower = np.min(apparent_mass, axis=1) - padding
    upper = np.max(apparent_mass, axis=1) + padding
    fractions = np.linspace(0.0, 1.0, settings.grid_points)
    grids = lower[:, None] + (upper - lower)[:, None] * fractions[None, :]
    bandwidth = (
        settings.bandwidth_multiplier
        * sample_std
        * apparent_mass.shape[1] ** (-1.0 / 5.0)
    )
    result = np.full(apparent_mass.shape[0], np.nan)
    valid = np.isfinite(bandwidth) & (bandwidth > 0)
    valid_rows = np.flatnonzero(valid)
    if valid_rows.size == 0:
        return result
    scaled = (
        grids[valid_rows, :, None] - apparent_mass[valid_rows, None, :]
    ) / bandwidth[valid_rows, None, None]
    np.square(scaled, out=scaled)
    scaled *= -0.5
    np.exp(scaled, out=scaled)
    densities = np.mean(scaled, axis=2) / (
        np.sqrt(2.0 * np.pi) * bandwidth[valid_rows, None]
    )
    for local_row, row in enumerate(valid_rows):
        try:
            width, _, _, _ = half_height_width(grids[row], densities[local_row])
        except ValueError:
            continue
        result[row] = nominal_mass_Da / width
    return result


def bootstrap_resolution_difference(
    left_tof_us: np.ndarray,
    right_tof_us: np.ndarray,
    nominal_mass_Da: float,
    resamples: int = 5000,
    seed: int = 20260715,
    settings: AnalysisSettings | None = None,
    batch_size: int = 16,
) -> dict[str, Any]:
    """Paired bootstrap CI for absolute cross-solver R difference percentage."""

    settings = settings or AnalysisSettings()
    left = _as_valid_sample(left_tof_us, "left_tof_us")
    right = _as_valid_sample(right_tof_us, "right_tof_us")
    if left.size != right.size:
        raise ValueError("Paired bootstrap requires equal particle counts")
    if resamples <= 0 or batch_size <= 0:
        raise ValueError("resamples and batch_size must be positive")

    rng = np.random.default_rng(seed)
    differences = np.full(resamples, np.nan)
    for start in range(0, resamples, batch_size):
        stop = min(start + batch_size, resamples)
        indices = rng.integers(0, left.size, size=(stop - start, left.size))
        left_resolution = _bootstrap_resolution_batch(left[indices], nominal_mass_Da, settings)
        right_resolution = _bootstrap_resolution_batch(
            right[indices], nominal_mass_Da, settings
        )
        differences[start:stop] = (
            np.abs(left_resolution - right_resolution) / right_resolution * 100.0
        )
    finite = differences[np.isfinite(differences)]
    if finite.size < 0.95 * resamples:
        raise ValueError(
            f"Only {finite.size}/{resamples} finite bootstrap replicates were obtained"
        )
    percentiles = np.percentile(finite, [2.5, 50.0, 97.5])
    return {
        "method": "paired particle-index bootstrap using canonical direct KDE FWHM",
        "seed": int(seed),
        "resamples_requested": int(resamples),
        "resamples_valid": int(finite.size),
        "absolute_resolution_difference_pct_p2p5": float(percentiles[0]),
        "absolute_resolution_difference_pct_median": float(percentiles[1]),
        "absolute_resolution_difference_pct_p97p5": float(percentiles[2]),
    }
