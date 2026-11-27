"""Plots for normalized single-reflection peak reports."""
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


def plot_single(
    frame: pd.DataFrame,
    metrics: dict[str, Any],
    spectra: dict[str, np.ndarray],
    label: str,
    output: Path,
    *,
    result_schema_version: int,
) -> None:
    resolution_key = {3: "mass_resolution", 4: "nominal_mass_resolution_fwhm"}[result_schema_version]
    figure, axes = plt.subplots(2, 2, figsize=(12.5, 8.0), constrained_layout=True)

    time_axis = axes[0, 0]
    time_axis.plot(
        spectra["time_grid_us"], spectra["time_density_normalized"], linewidth=1.8
    )
    time_axis.axhline(0.5, color="0.4", linestyle=":")
    time_axis.axvline(float(spectra["time_half_left_us"]), color="0.4", linestyle="--")
    time_axis.axvline(float(spectra["time_half_right_us"]), color="0.4", linestyle="--")
    time_axis.set(xlabel="TOF [us]", ylabel="Normalized intensity", title="Intensity-time spectrum")
    time_axis.grid(True, alpha=0.3)

    mass_axis = axes[0, 1]
    mass_axis.plot(
        spectra["mass_grid_Da"], spectra["mass_density_normalized"], linewidth=1.8
    )
    mass_axis.axhline(0.5, color="0.4", linestyle=":")
    mass_axis.axvline(float(spectra["mass_half_left_Da"]), color="0.4", linestyle="--")
    mass_axis.axvline(float(spectra["mass_half_right_Da"]), color="0.4", linestyle="--")
    mass_axis.set(
        xlabel="Nominal-relative apparent mass [Da]",
        ylabel="Normalized intensity",
        title=f"Direct FWHM={metrics['direct_fwhm_mass_Da']:.8g} Da; R={metrics[resolution_key]:.1f}",
    )
    mass_axis.grid(True, alpha=0.3)

    qq_axis = axes[1, 0]
    standardized = np.sort(
        (spectra["tof_us"] - np.mean(spectra["tof_us"]))
        / np.std(spectra["tof_us"], ddof=1)
    )
    probabilities = (np.arange(1, standardized.size + 1) - 0.5) / standardized.size
    normal_quantiles = stats.norm.ppf(probabilities)
    qq_axis.scatter(normal_quantiles, standardized, s=8, alpha=0.5)
    limits = [min(normal_quantiles[0], standardized[0]), max(normal_quantiles[-1], standardized[-1])]
    qq_axis.plot(limits, limits, "k--", linewidth=1.0)
    qq_axis.set(
        xlabel="Normal quantile",
        ylabel="Observed standardized TOF",
        title=f"Q-Q: skew={metrics['tof_skewness']:.3f}, excess kurtosis={metrics['tof_excess_kurtosis']:.3f}",
    )
    qq_axis.grid(True, alpha=0.3)

    impact_axis = axes[1, 1]
    if {"detector_x_mm", "detector_y_mm"}.issubset(frame.columns):
        impact = impact_axis.hexbin(
            frame["detector_x_mm"],
            frame["detector_y_mm"],
            gridsize=45,
            mincnt=1,
            cmap="viridis",
        )
        figure.colorbar(impact, ax=impact_axis, label="Impacts per hexagon")
        impact_axis.set_aspect("equal", adjustable="box")
        impact_axis.set(
            xlabel="Detector local x [mm]",
            ylabel="Detector local y [mm]",
            title="Detector-plane impact density",
        )
        impact_axis.grid(True, alpha=0.2)
    else:
        impact_axis.axis("off")
        impact_axis.text(
            0.5,
            0.5,
            "Detector coordinates are not present\nin this source table.",
            ha="center",
            va="center",
        )

    figure.suptitle(
        f"{label}: N={metrics['particles']}, mean TOF={metrics['mean_tof_us']:.9f} us"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=200, facecolor="white")
    plt.close(figure)



def plot_source_mapping(
    frame: pd.DataFrame,
    arrays: dict[str, np.ndarray],
    metrics: dict[str, Any],
    output: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(10.5, 6.5), constrained_layout=True)
    points = axis.scatter(
        frame["initial_z_mm"],
        frame["tof_us"],
        c=frame["initial_energy_eV"],
        s=14,
        alpha=0.45,
        cmap="viridis",
    )
    axis.plot(
        arrays["z_plot_mm"],
        arrays["z_quadratic_fit_tof_us"],
        color="black",
        linewidth=2.0,
        label="z-only quadratic fit",
    )
    vertex = metrics["quadratic_vertex_z_mm"]
    if metrics["vertex_inside_source"] and vertex is not None:
        axis.axvline(vertex, color="red", linestyle="--", label="quadratic vertex")
    figure.colorbar(points, ax=axis, label="Initial energy [eV]")
    axis.set(
        xlabel="Initial z [mm]",
        ylabel="Detector TOF [us]",
        title=(
            "Initial-z to TOF mapping: "
            f"quadratic R²={metrics['z_only_quadratic_r_squared']:.4f}"
        ),
    )
    axis.grid(True, alpha=0.3)
    axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220, facecolor="white")
    plt.close(figure)
