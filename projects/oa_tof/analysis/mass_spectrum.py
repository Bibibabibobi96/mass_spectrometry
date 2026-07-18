"""Wide-range oa-TOF candidate mass-spectrum analysis.

This workflow intentionally reports calibration centroids and transmission,
not precision FWHM.  The economical per-species samples are too small to
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
import numpy as np
import pandas as pd

from reference_analysis import read_particle_table


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
            "detector_x_mm": pd.to_numeric(raw["XMm"], errors="coerce"),
            "detector_y_mm": pd.to_numeric(raw["YMm"], errors="coerce"),
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
                }
            )

    particles = pd.concat(combined_frames, ignore_index=True, sort=False)
    summary = pd.DataFrame(summary_rows)
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
    summary = summary.sort_values(["mz", "solver"]).reset_index(drop=True)
    particles.to_csv(output_dir / "mass_spectrum_particles.csv", index=False)
    summary.to_csv(output_dir / "mass_spectrum_summary.csv", index=False)

    colors = {"COMSOL": "#1f77b4", "SIMION": "#d62728"}
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    for solver in ("COMSOL", "SIMION"):
        selected = summary[summary["solver"] == solver]
        intensity = selected["relative_abundance"] * selected["transmission"]
        axes[0].vlines(
            selected["calibrated_centroid_mz"], 0, intensity,
            color=colors[solver], linewidth=2, alpha=0.75, label=solver,
        )
        axes[0].scatter(selected["calibrated_centroid_mz"], intensity, color=colors[solver], s=24)
        axes[1].plot(
            selected["mz"], selected["calibration_residual_ppm"], "o-",
            color=colors[solver], label=solver,
        )
    axes[0].set(xlabel="calibrated m/z", ylabel="relative detected intensity", title="oa-TOF wide-range candidate mass spectrum")
    axes[0].legend()
    axes[1].axhline(0, color="0.4", linewidth=1)
    axes[1].set(xlabel="nominal m/z", ylabel="calibration residual (ppm)", title="Five-point calibration residual")
    axes[1].legend()
    fig.savefig(output_dir / "mass_spectrum_comparison.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, len(mode["species"]), figsize=(16, 3.5), constrained_layout=True)
    for axis, item in zip(axes, mode["species"], strict=True):
        species_id = str(item["species_id"])
        nominal = float(item["mz"])
        for solver in ("COMSOL", "SIMION"):
            values = particles.loc[
                (particles["solver"] == solver) & (particles["species_id"] == species_id),
                "calibrated_mz",
            ]
            axis.hist(values - nominal, bins="auto", density=True, histtype="step", linewidth=1.5, color=colors[solver], label=solver)
        axis.axvline(0, color="0.4", linewidth=1)
        axis.set_title(f"m/z {nominal:g}")
        axis.set_xlabel("calibrated m/z - nominal")
    axes[0].set_ylabel("density")
    axes[-1].legend()
    fig.savefig(output_dir / "mass_peak_local_comparison.png", dpi=180)
    plt.close(fig)

    result = {
        "schema_version": 1,
        "status": "PASS",
        "role": "oa_tof_candidate_mass_spectrum_analysis",
        "resolution_claim_allowed": False,
        "python": platform.python_version(),
        "inputs": input_hashes,
        "calibration": calibrations,
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
