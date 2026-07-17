"""Diagnose RF-phase and transverse differences from independent solver tracks."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load_tracks(path: Path) -> dict[int, dict[str, np.ndarray]]:
    grouped: dict[int, list[dict[str, str]]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            grouped.setdefault(int(row["particle_id"]), []).append(row)
    if sorted(grouped) != list(range(1, 26)):
        raise ValueError(f"{path} does not contain fixed particle IDs 1..25")
    tracks: dict[int, dict[str, np.ndarray]] = {}
    for particle_id, rows in grouped.items():
        rows.sort(key=lambda row: float(row["axial_z_mm"]))
        z = np.array([float(row["axial_z_mm"]) for row in rows])
        unique, index = np.unique(z, return_index=True)
        tracks[particle_id] = {
            "z": unique,
            "time": np.array([float(row["time_us"]) for row in rows])[index],
            "x": np.array([float(row["transverse_x_mm"]) for row in rows])[index],
            "y": np.array([float(row["transverse_y_mm"]) for row in rows])[index],
        }
    return tracks


def interpolate(track: dict[str, np.ndarray], z: np.ndarray, key: str) -> np.ndarray:
    return np.interp(z, track["z"], track[key])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--comsol-trajectory", type=Path)
    parser.add_argument("--simion-trajectory", type=Path)
    args = parser.parse_args()
    results = args.workspace / "artifacts/projects/rf_quadrupole_collision_cooling/results"
    comsol_path = args.comsol_trajectory or results / "comsol/transport_no_collision_trajectory_samples.csv"
    simion_path = args.simion_trajectory or results / "simion/transport_no_collision_trajectory_samples_single_particle_diag_simion80.csv"
    comsol, simion = load_tracks(comsol_path), load_tracks(simion_path)
    z = np.arange(0.2, 94.8 + 1e-9, 0.2)
    period_us = 1e6 / 1.1e6

    dt, distance = [], []
    for particle_id in range(1, 26):
        c_time = interpolate(comsol[particle_id], z, "time")
        s_time = interpolate(simion[particle_id], z, "time")
        dx = interpolate(comsol[particle_id], z, "x") - interpolate(simion[particle_id], z, "x")
        dy = interpolate(comsol[particle_id], z, "y") - interpolate(simion[particle_id], z, "y")
        dt.append(c_time - s_time)
        distance.append(np.hypot(dx, dy))
    dt = np.array(dt)
    distance = np.array(distance)
    phase_deg = dt / period_us * 360.0
    wrapped_phase_deg = (phase_deg + 180.0) % 360.0 - 180.0
    rod = (z >= 5.8) & (z <= 85.4)
    plane_metrics: dict[str, dict[str, float]] = {}
    for name, plane in (("entrance", 0.2), ("rod_midpoint", 45.6), ("rod_exit", 85.4), ("detector_front", 94.8)):
        index = int(round((plane - 0.2) / 0.2))
        plane_metrics[name] = {
            "axial_z_mm": plane,
            "mean_delta_time_us": float(np.mean(dt[:, index])),
            "mean_wrapped_phase_deg": float(np.mean(wrapped_phase_deg[:, index])),
            "mean_transverse_distance_mm": float(np.mean(distance[:, index])),
        }
    abs_phase = np.abs(wrapped_phase_deg[:, rod]).ravel()
    rod_distance = distance[:, rod].ravel()
    summary = {
        "status": "PASS",
        "rf_period_us": period_us,
        "rod_samples": int(abs_phase.size),
        "rod_abs_wrapped_phase_deg_mean": float(np.mean(abs_phase)),
        "rod_abs_wrapped_phase_deg_p95": float(np.percentile(abs_phase, 95)),
        "rod_phase_distance_pearson_r": float(np.corrcoef(abs_phase, rod_distance)[0, 1]),
        "plane_metrics": plane_metrics,
        "interpretation": "Correlation is descriptive only; this diagnostic does not alter either field or trajectory.",
    }
    output = results / "cross_solver"
    output.mkdir(parents=True, exist_ok=True)
    (output / "transport_no_collision_phase_diagnostics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    figure, axes = plt.subplots(1, 2, figsize=(11, 4.6), constrained_layout=True)
    axes[0].plot(z, np.mean(dt, axis=0) * 1e3, color="tab:red", label="mean Δt")
    axes[0].fill_between(z, *(np.percentile(dt, [5, 95], axis=0) * 1e3), color="tab:red", alpha=0.18, label="5–95%")
    axes[0].axvspan(5.8, 85.4, color="0.9")
    axes[0].set(title="Arrival-time difference at common axial position", xlabel="axial z (mm)", ylabel="COMSOL − SIMION Δt (ns)")
    axes[0].grid(True, alpha=0.3); axes[0].legend()
    axes[1].scatter(abs_phase, rod_distance, s=5, alpha=0.22, color="tab:blue")
    axes[1].set(title=f"Rod region: |wrapped phase| vs transverse distance\nr={summary['rod_phase_distance_pearson_r']:.3f}", xlabel="|wrapped RF phase difference| (deg)", ylabel="same-ID transverse distance (mm)")
    axes[1].grid(True, alpha=0.3)
    figure.savefig(output / "transport_no_collision_phase_diagnostics.png", dpi=190)
    print(f"STATUS=PASS SUMMARY={output / 'transport_no_collision_phase_diagnostics.json'}")


if __name__ == "__main__":
    main()
