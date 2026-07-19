"""Diagnose RF-phase and transverse differences from independent solver tracks."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from rfquad_contract import diagnostic_planes, load as load_contract


def load_tracks(path: Path) -> dict[int, dict[str, np.ndarray]]:
    grouped: dict[int, list[dict[str, str]]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            grouped.setdefault(int(row["particle_id"]), []).append(row)
    if sorted(grouped) != list(range(1, len(grouped) + 1)):
        raise ValueError(f"{path} does not contain contiguous fixed particle IDs")
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
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--comsol-trajectory", type=Path, required=True)
    parser.add_argument("--simion-trajectory", type=Path, required=True)
    parser.add_argument("--output-label", required=True)
    args = parser.parse_args()
    results = args.run_dir.resolve() / "results"
    resolved, interface = load_contract()
    geometry = resolved["geometry_mm"]
    planes = diagnostic_planes(resolved, interface)
    comsol, simion = load_tracks(args.comsol_trajectory), load_tracks(args.simion_trajectory)
    particle_ids = sorted(comsol)
    if particle_ids != sorted(simion):
        raise ValueError("COMSOL and SIMION trajectory particle IDs differ")
    step = geometry["simion_cell_mm"]
    z = np.arange(planes["first_common_plane"], planes["detector_front"] + 1e-9, step)
    period_us = 1e6 / resolved["mode"]["rf"]["frequency_Hz"]

    dt, distance = [], []
    for particle_id in particle_ids:
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
    rod = (z >= geometry["rod_z_min"]) & (z <= geometry["rod_z_max"])
    plane_metrics: dict[str, dict[str, float]] = {}
    for name, plane in planes.items():
        index = int(np.argmin(np.abs(z - plane)))
        plane_metrics[name] = {
            "axial_z_mm": plane,
            "mean_delta_time_us": float(np.mean(dt[:, index])),
            "mean_wrapped_phase_deg": float(np.mean(wrapped_phase_deg[:, index])),
            "mean_transverse_distance_mm": float(np.mean(distance[:, index])),
        }
    abs_phase = np.abs(wrapped_phase_deg[:, rod]).ravel()
    rod_distance = distance[:, rod].ravel()
    mean_distance = np.mean(distance, axis=0)
    onset: dict[str, float | None] = {}
    for threshold in (0.01, 0.05, 0.1, 0.2):
        indices = np.flatnonzero(mean_distance >= threshold)
        onset[f"mean_distance_ge_{threshold:g}_mm_z_mm"] = float(z[indices[0]]) if indices.size else None
    summary = {
        "status": "PASS",
        "rf_period_us": period_us,
        "rod_samples": int(abs_phase.size),
        "rod_abs_wrapped_phase_deg_mean": float(np.mean(abs_phase)),
        "rod_abs_wrapped_phase_deg_p95": float(np.percentile(abs_phase, 95)),
        "rod_phase_distance_pearson_r": float(np.corrcoef(abs_phase, rod_distance)[0, 1]),
        "transverse_difference_onset": onset,
        "plane_metrics": plane_metrics,
        "interpretation": "Correlation is descriptive only; this diagnostic does not alter either field or trajectory.",
    }
    output = results / "cross_solver"
    output.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.output_label}"
    summary_path = output / f"transport_no_collision_phase_diagnostics{suffix}.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    figure, axes = plt.subplots(1, 2, figsize=(11, 4.6), constrained_layout=True)
    axes[0].plot(z, np.mean(dt, axis=0) * 1e3, color="tab:red", label="mean Δt")
    axes[0].fill_between(z, *(np.percentile(dt, [5, 95], axis=0) * 1e3), color="tab:red", alpha=0.18, label="5–95%")
    axes[0].axvspan(geometry["rod_z_min"], geometry["rod_z_max"], color="0.9")
    axes[0].set(title="Arrival-time difference at common axial position", xlabel="axial z (mm)", ylabel="COMSOL − SIMION Δt (ns)")
    axes[0].grid(True, alpha=0.3); axes[0].legend()
    axes[1].scatter(abs_phase, rod_distance, s=5, alpha=0.22, color="tab:blue")
    axes[1].set(title=f"Rod region: |wrapped phase| vs transverse distance\nr={summary['rod_phase_distance_pearson_r']:.3f}", xlabel="|wrapped RF phase difference| (deg)", ylabel="same-ID transverse distance (mm)")
    axes[1].grid(True, alpha=0.3)
    figure.savefig(output / f"transport_no_collision_phase_diagnostics{suffix}.png", dpi=190)
    print(f"STATUS=PASS SUMMARY={summary_path}")


if __name__ == "__main__":
    main()
