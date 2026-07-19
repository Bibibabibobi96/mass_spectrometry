"""Wide-range oa-TOF candidate mass-spectrum analysis.

This workflow reports calibration centroids, transmission and diagnostic local
peak overlays.  It does not promote those overlays to precision FWHM claims or
replace the dedicated 524 Da formal resolution baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from peak_metrics import AnalysisSettings, compare_peak_shapes, compute_detector_metrics
from reference_analysis import (
    DEFAULT_DETECTOR_CENTER_X_MM,
    DEFAULT_DETECTOR_CENTER_Y_MM,
    read_particle_table,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_mode(path: Path) -> dict[str, Any]:
    mode = json.loads(path.read_text(encoding="utf-8-sig"))
    if mode.get("role") != "oa_tof_candidate_mass_spectrum_mode":
        raise ValueError("Not an oa-TOF candidate mass-spectrum mode")
    species = mode.get("species", [])
    if len(species) < 3:
        raise ValueError("A calibration spectrum requires at least three species")
    ids = [str(item["species_id"]) for item in species]
    if len(ids) != len(set(ids)):
        raise ValueError("species_id values must be unique")
    for item in species:
        mass = float(item["mass_amu"])
        charge = int(item["charge_state"])
        mz = float(item["mz"])
        if mass <= 0 or charge == 0 or mz <= 0:
            raise ValueError(f"Invalid species definition: {item}")
        if not np.isclose(mass / abs(charge), mz, rtol=0, atol=1e-12):
            raise ValueError(f"m/z is inconsistent for {item['species_id']}")
    return mode


def fit_calibration(mean_tof_us: np.ndarray, mz: np.ndarray) -> dict[str, Any]:
    """Fit sqrt(m/z)=slope*t+intercept and return residual diagnostics."""

    tof = np.asarray(mean_tof_us, dtype=float)
    target = np.asarray(mz, dtype=float)
    if tof.size < 3 or tof.size != target.size:
        raise ValueError("Calibration requires equal arrays with at least three points")
    slope, intercept = np.polyfit(tof, np.sqrt(target), 1)
    fitted_mz = (slope * tof + intercept) ** 2
    residual = fitted_mz - target
    return {
        "slope_sqrt_mz_per_us": float(slope),
        "intercept_sqrt_mz": float(intercept),
        "time_offset_us": float(-intercept / slope),
        "fitted_mz": fitted_mz,
        "residual_mz": residual,
        "residual_rms_mz": float(np.sqrt(np.mean(residual**2))),
        "residual_max_abs_mz": float(np.max(np.abs(residual))),
    }


def _normalized_simion_rows(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    required = {
        "Ion", "MassAmu", "ChargeState", "TofUs", "XMm", "YMm", "Hit"
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"SIMION mixed-species CSV lacks columns: {sorted(missing)}")
    hit = raw["Hit"].astype(str).str.lower().isin({"true", "1", "yes"})
    result = pd.DataFrame(
        {
            "particle_id": pd.to_numeric(raw["Ion"], errors="raise").astype(int),
            "mass_amu": pd.to_numeric(raw["MassAmu"], errors="raise"),
            "charge_state": pd.to_numeric(raw["ChargeState"], errors="raise").astype(int),
            "tof_us": pd.to_numeric(raw["TofUs"], errors="coerce"),
            "detector_x_mm": (
                pd.to_numeric(raw["XMm"], errors="coerce")
                - DEFAULT_DETECTOR_CENTER_X_MM
            ),
            "detector_y_mm": (
                pd.to_numeric(raw["YMm"], errors="coerce")
                - DEFAULT_DETECTOR_CENTER_Y_MM
            ),
            "hit": hit,
        }
    )
    for source, target in (
        ("X0Mm", "initial_x_mm"),
        ("Y0Mm", "initial_y_mm"),
        ("Z0Mm", "initial_z_mm"),
        ("EnergyEv", "initial_energy_eV"),
    ):
        if source in raw:
            result[target] = pd.to_numeric(raw[source], errors="coerce")
    if result["particle_id"].duplicated().any():
        raise ValueError("SIMION mixed-species particle IDs are not unique")
    return result


def _normalized_comsol_rows(path: Path) -> pd.DataFrame:
    result, _ = read_particle_table(path)
    return result.copy()


def _plot_mass_detector_landings(
    particles: pd.DataFrame,
    summary: pd.DataFrame,
    species: list[dict[str, Any]],
    output: Path,
) -> None:
    """Overlay COMSOL/SIMION detector impacts in one panel per mass."""

    coordinates = particles[["detector_x_mm", "detector_y_mm"]].to_numpy(dtype=float)
    if not np.all(np.isfinite(coordinates)):
        raise ValueError("Mass-spectrum detector coordinates contain non-finite values")
    extent = 1.08 * max(1.0, float(np.max(np.abs(coordinates))))
    column_count = min(3, len(species))
    row_count = int(np.ceil(len(species) / column_count))
    figure, grid = plt.subplots(
        row_count,
        column_count,
        figsize=(5.4 * column_count, 4.5 * row_count),
        constrained_layout=True,
        squeeze=False,
    )
    axes = grid.ravel()
    colors = {"COMSOL": "#1f77b4", "SIMION": "#d62728"}
    for axis, item in zip(axes, species, strict=False):
        species_id = str(item["species_id"])
        nominal = float(item["mz"])
        peak = particles.loc[particles["species_id"] == species_id]
        peak_summary = summary.loc[summary["species_id"] == species_id].set_index("solver")
        for solver in ("COMSOL", "SIMION"):
            solver_peak = peak.loc[peak["solver"] == solver]
            if solver == "COMSOL":
                axis.scatter(
                    solver_peak["detector_x_mm"], solver_peak["detector_y_mm"],
                    s=13, alpha=0.42, color=colors[solver], edgecolors="none",
                )
                centroid_marker = "X"
            else:
                axis.scatter(
                    solver_peak["detector_x_mm"], solver_peak["detector_y_mm"],
                    s=13, alpha=0.55, facecolors="none", edgecolors=colors[solver],
                    linewidths=0.65,
                )
                centroid_marker = "P"
            axis.scatter(
                peak_summary.loc[solver, "impact_centroid_x_mm"],
                peak_summary.loc[solver, "impact_centroid_y_mm"],
                marker=centroid_marker, s=75, linewidths=1.3,
                color=colors[solver], edgecolors="white", zorder=5,
            )
        axis.axhline(0.0, color="0.55", linewidth=0.8, linestyle="-.")
        axis.axvline(0.0, color="0.55", linewidth=0.8, linestyle="-.")
        axis.text(
            0.03, 0.97,
            f"RMS r C/S="
            f"{peak_summary.loc['COMSOL', 'impact_rms_radius_mm']:.3f}/"
            f"{peak_summary.loc['SIMION', 'impact_rms_radius_mm']:.3f} mm\n"
            f"centroid distance="
            f"{peak_summary['cross_solver_centroid_distance_mm'].iloc[0]:.3f} mm\n"
            f"N C/S={int(peak_summary.loc['COMSOL', 'detected'])}/"
            f"{int(peak_summary.loc['SIMION', 'detected'])}",
            transform=axis.transAxes, ha="left", va="top", fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.72, "edgecolor": "none", "pad": 2},
        )
        axis.set(
            title=f"m/z {nominal:g}",
            xlim=(-extent, extent), ylim=(-extent, extent),
            xlabel="Detector local x (mm)", ylabel="Detector local y (mm)",
        )
        axis.set_aspect("equal", adjustable="box")
        axis.grid(True, alpha=0.2)
    for axis in axes[len(species):]:
        axis.set_axis_off()
    legend_handles = [
        Line2D([0], [0], marker="o", linestyle="none", markersize=6,
               markerfacecolor=colors["COMSOL"], markeredgecolor="none",
               label="COMSOL impacts"),
        Line2D([0], [0], marker="o", linestyle="none", markersize=6,
               markerfacecolor="none", markeredgecolor=colors["SIMION"],
               label="SIMION impacts"),
        Line2D([0], [0], marker="X", linestyle="none", markersize=8,
               markerfacecolor=colors["COMSOL"], markeredgecolor="white",
               label="COMSOL centroid"),
        Line2D([0], [0], marker="P", linestyle="none", markersize=8,
               markerfacecolor=colors["SIMION"], markeredgecolor="white",
               label="SIMION centroid"),
        Line2D([0], [0], color="0.55", linewidth=0.8, linestyle="-.",
               label="detector axes (x=0 or y=0)"),
    ]
    figure.legend(
        handles=legend_handles, loc="lower center", bbox_to_anchor=(0.5, -0.055),
        ncol=5, frameon=True, borderaxespad=0,
    )
    figure.suptitle("oa-TOF detector landing: COMSOL and SIMION")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def analyze_mass_spectrum(
    mode_path: Path,
    comsol_dir: Path,
    simion_csv: Path,
    output_dir: Path,
) -> dict[str, Any]:
    mode = load_mode(mode_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    simion = _normalized_simion_rows(simion_csv)
    combined_frames: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []
    peak_shape_rows: list[dict[str, Any]] = []
    input_hashes = {
        "mode_config": sha256_file(mode_path),
        "simion_csv": sha256_file(simion_csv),
    }

    for item in mode["species"]:
        species_id = str(item["species_id"])
        mass = float(item["mass_amu"])
        charge = int(item["charge_state"])
        mz = float(item["mz"])
        emitted = int(item["particle_count"])
        abundance = float(item["relative_abundance"])
        comsol_path = comsol_dir / f"{species_id}.csv"
        if not comsol_path.is_file():
            raise FileNotFoundError(comsol_path)
        input_hashes[f"comsol_{species_id}"] = sha256_file(comsol_path)

        solver_frames = {
            "COMSOL": _normalized_comsol_rows(comsol_path),
            "SIMION": simion[
                np.isclose(simion["mass_amu"], mass, rtol=0, atol=1e-9)
                & (simion["charge_state"] == charge)
                & simion["hit"]
            ].copy(),
        }
        comparison, _ = compare_peak_shapes(
            solver_frames["COMSOL"]["tof_us"].to_numpy(dtype=float),
            solver_frames["SIMION"]["tof_us"].to_numpy(dtype=float),
            AnalysisSettings(),
        )
        peak_shape_rows.append(
            {
                "species_id": species_id,
                "mz": mz,
                "comsol_particles": comparison["left_particles"],
                "simion_particles": comparison["right_particles"],
                "simion_minus_comsol_mean_tof_ns": comparison[
                    "mean_tof_difference_right_minus_left_ns"
                ],
                "standardized_kde_overlap": comparison[
                    "standardized_kde_overlap"
                ],
                "standardized_ks_distance": comparison[
                    "standardized_ks_distance"
                ],
                "standardized_ks_pvalue": comparison[
                    "standardized_ks_pvalue"
                ],
            }
        )
        for solver, frame in solver_frames.items():
            if len(frame) < 3:
                raise ValueError(f"{solver} {species_id} has fewer than three hits")
            if solver == "COMSOL" and len(frame) > emitted:
                raise ValueError(f"COMSOL {species_id} has more hits than emitted particles")
            frame["solver"] = solver
            frame["species_id"] = species_id
            frame["mass_amu"] = mass
            frame["charge_state"] = charge
            frame["mz"] = mz
            frame["relative_abundance"] = abundance
            combined_frames.append(frame)
            mean_tof = float(frame["tof_us"].mean())
            std_tof = float(frame["tof_us"].std(ddof=1))
            summary_rows.append(
                {
                    "solver": solver,
                    "species_id": species_id,
                    "mass_amu": mass,
                    "charge_state": charge,
                    "mz": mz,
                    "emitted": emitted,
                    "detected": int(len(frame)),
                    "transmission": float(len(frame) / emitted),
                    "mean_tof_us": mean_tof,
                    "std_tof_ns": 1000.0 * std_tof,
                    "centroid_standard_error_ns": 1000.0 * std_tof / np.sqrt(len(frame)),
                    "relative_abundance": abundance,
                    **compute_detector_metrics(
                        frame["detector_x_mm"].to_numpy(dtype=float),
                        frame["detector_y_mm"].to_numpy(dtype=float),
                    ),
                }
            )

    particles = pd.concat(combined_frames, ignore_index=True, sort=False)
    summary = pd.DataFrame(summary_rows)
    peak_shapes = pd.DataFrame(peak_shape_rows).sort_values("mz").reset_index(drop=True)
    calibrations: dict[str, Any] = {}
    for solver in ("COMSOL", "SIMION"):
        selected = summary[summary["solver"] == solver].sort_values("mz")
        fit = fit_calibration(selected["mean_tof_us"].to_numpy(), selected["mz"].to_numpy())
        calibrations[solver] = {
            key: value for key, value in fit.items()
            if not isinstance(value, np.ndarray)
        }
        summary.loc[selected.index, "calibrated_centroid_mz"] = fit["fitted_mz"]
        summary.loc[selected.index, "calibration_residual_mz"] = fit["residual_mz"]
        summary.loc[selected.index, "calibration_residual_ppm"] = (
            1.0e6 * fit["residual_mz"] / selected["mz"].to_numpy()
        )
        mask = particles["solver"] == solver
        particles.loc[mask, "calibrated_mz"] = (
            fit["slope_sqrt_mz_per_us"] * particles.loc[mask, "tof_us"]
            + fit["intercept_sqrt_mz"]
        ) ** 2

    pivot = summary.pivot(index="species_id", columns="solver", values="mean_tof_us")
    summary["simion_minus_comsol_mean_tof_ns"] = summary["species_id"].map(
        1000.0 * (pivot["SIMION"] - pivot["COMSOL"])
    )
    centroid_x = summary.pivot(
        index="species_id", columns="solver", values="impact_centroid_x_mm"
    )
    centroid_y = summary.pivot(
        index="species_id", columns="solver", values="impact_centroid_y_mm"
    )
    centroid_distance = np.hypot(
        centroid_x["SIMION"] - centroid_x["COMSOL"],
        centroid_y["SIMION"] - centroid_y["COMSOL"],
    )
    summary["cross_solver_centroid_distance_mm"] = summary["species_id"].map(
        centroid_distance
    )
    summary = summary.sort_values(["mz", "solver"]).reset_index(drop=True)
    particles.to_csv(output_dir / "mass_spectrum_particles.csv", index=False)
    summary.to_csv(output_dir / "mass_spectrum_summary.csv", index=False)
    peak_shapes.to_csv(output_dir / "mass_peak_shape_comparison.csv", index=False)

    colors = {"COMSOL": "#1f77b4", "SIMION": "#d62728"}
    species_count = len(mode["species"])
    column_count = min(3, species_count)
    row_count = int(np.ceil(species_count / column_count))
    fig, grid = plt.subplots(
        row_count, column_count, figsize=(5.4 * column_count, 4.0 * row_count),
        constrained_layout=True, squeeze=False,
    )
    axes = grid.ravel()
    for axis, item in zip(axes, mode["species"], strict=False):
        species_id = str(item["species_id"])
        nominal = float(item["mz"])
        peak = particles.loc[particles["species_id"] == species_id]
        offsets = peak["calibrated_mz"].to_numpy(dtype=float) - nominal
        bin_edges = np.histogram_bin_edges(offsets, bins="auto")
        for solver in ("COMSOL", "SIMION"):
            values = peak.loc[peak["solver"] == solver, "calibrated_mz"] - nominal
            axis.hist(
                values, bins=bin_edges, density=True, histtype="step", linewidth=1.7,
                color=colors[solver], label=solver,
            )
            axis.axvline(
                float(values.mean()), color=colors[solver], linewidth=1.1,
                linestyle="--", alpha=0.9,
            )
        peak_summary = summary.loc[summary["species_id"] == species_id].set_index("solver")
        centroid_delta_ns = float(peak_summary["simion_minus_comsol_mean_tof_ns"].iloc[0])
        comsol_std_ns = float(peak_summary.loc["COMSOL", "std_tof_ns"])
        simion_std_ns = float(peak_summary.loc["SIMION", "std_tof_ns"])
        shape = peak_shapes.loc[peak_shapes["species_id"] == species_id].iloc[0]
        axis.text(
            0.03, 0.97,
            f"Δmean TOF={centroid_delta_ns:.3f} ns\n"
            f"σt COMSOL/SIMION={comsol_std_ns:.3f}/{simion_std_ns:.3f} ns\n"
            f"shape overlap={shape['standardized_kde_overlap']:.3f}; "
            f"KS={shape['standardized_ks_distance']:.3f}\n"
            f"N/solver={len(peak) // 2}",
            transform=axis.transAxes, ha="left", va="top", fontsize=8,
        )
        axis.axvline(0, color="0.4", linewidth=1)
        axis.set_title(f"m/z {nominal:g}")
        axis.set_xlabel("calibrated m/z - nominal (Da)")
        axis.set_ylabel("density")
        axis.grid(alpha=0.2)
    unused_axes = axes[species_count:]
    if len(unused_axes) > 0:
        centroid_axis = unused_axes[0]
        centroid_summary = (
            summary.loc[summary["solver"] == "COMSOL"]
            .sort_values("mz")
        )
        centroid_axis.plot(
            centroid_summary["mz"],
            centroid_summary["simion_minus_comsol_mean_tof_ns"],
            "o-", color="#6a3d9a", linewidth=1.5,
        )
        centroid_axis.axhline(0, color="0.4", linewidth=1)
        centroid_axis.set_title("cross-solver centroid closure")
        centroid_axis.set_xlabel("nominal m/z")
        centroid_axis.set_ylabel("SIMION - COMSOL mean TOF (ns)")
        centroid_axis.grid(alpha=0.25)
    for axis in unused_axes[1:]:
        axis.set_axis_off()
    legend_handles = [
        Line2D([0], [0], color=colors["COMSOL"], linewidth=1.7,
               label="COMSOL peak density"),
        Line2D([0], [0], color=colors["SIMION"], linewidth=1.7,
               label="SIMION peak density"),
        Line2D([0], [0], color="0.2", linewidth=1.1, linestyle="--",
               label="solver peak mean"),
        Line2D([0], [0], color="0.4", linewidth=1.0,
               label="nominal mass (Δm=0)"),
        Line2D([0], [0], color="#6a3d9a", linewidth=1.5, marker="o",
               label="SIMION − COMSOL mean TOF"),
    ]
    fig.legend(
        handles=legend_handles, loc="lower center", bbox_to_anchor=(0.5, -0.065),
        ncol=5, frameon=True, borderaxespad=0,
    )
    fig.suptitle("oa-TOF mass peaks: COMSOL and SIMION")
    fig.savefig(output_dir / "mass_spectrum_comparison.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    _plot_mass_detector_landings(
        particles, summary, mode["species"],
        output_dir / "mass_detector_landing_comparison.png",
    )

    result = {
        "schema_version": 2,
        "status": "PASS",
        "role": "oa_tof_candidate_mass_spectrum_analysis",
        "resolution_claim_allowed": False,
        "python": platform.python_version(),
        "inputs": input_hashes,
        "calibration": calibrations,
        "peak_shape_comparisons": peak_shapes.to_dict(orient="records"),
        "species": summary.to_dict(orient="records"),
    }
    (output_dir / "mass_spectrum_metrics.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode-config", required=True, type=Path)
    parser.add_argument("--comsol-dir", required=True, type=Path)
    parser.add_argument("--simion-csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze_mass_spectrum(
        args.mode_config.resolve(), args.comsol_dir.resolve(),
        args.simion_csv.resolve(), args.output.resolve()
    )
    print(
        "MASS_SPECTRUM_ANALYSIS=PASS "
        f"SPECIES={len(result['species']) // 2} OUTPUT={args.output.resolve()}"
    )


if __name__ == "__main__":
    main()
