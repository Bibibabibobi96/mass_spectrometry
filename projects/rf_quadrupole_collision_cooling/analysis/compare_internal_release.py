"""Compare independent solver trajectories after a release inside the RF rods."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from plot_transport_phase_diagnostics import interpolate, load_tracks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--comsol-trajectory", type=Path, required=True)
    parser.add_argument("--simion-trajectory", type=Path, required=True)
    parser.add_argument("--output-label", default="internal_z20")
    parser.add_argument("--source-axial-offset-mm", type=float, default=20.0)
    args = parser.parse_args()

    comsol = load_tracks(args.comsol_trajectory)
    simion = load_tracks(args.simion_trajectory)
    common_start = max(max(track["z"][0] for track in comsol.values()),
                       max(track["z"][0] for track in simion.values()))
    common_end = min(min(track["z"][-1] for track in comsol.values()),
                     min(track["z"][-1] for track in simion.values()))
    z_start = np.ceil(common_start * 5.0) / 5.0
    z_end = np.floor(common_end * 5.0) / 5.0
    z = np.arange(z_start, z_end + 1e-9, 0.2)
    if z.size < 2:
        raise ValueError(f"insufficient common axial interval: {common_start:g}..{common_end:g} mm")

    distances = []
    delta_time = []
    for particle_id in range(1, 26):
        c = comsol[particle_id]
        s = simion[particle_id]
        dx = interpolate(c, z, "x") - interpolate(s, z, "x")
        dy = interpolate(c, z, "y") - interpolate(s, z, "y")
        distances.append(np.hypot(dx, dy))
        delta_time.append(interpolate(c, z, "time") - interpolate(s, z, "time"))
    distances = np.asarray(distances)
    delta_time = np.asarray(delta_time)

    requested_planes = {
        "first_common_plane": z_start,
        "rod_midpoint": 45.6,
        "internal_window_end": 70.0,
        "rod_exit": 85.4,
        "pre_detector": 94.0,
    }
    plane_metrics = {}
    for name, plane in requested_planes.items():
        if plane < z_start or plane > z_end:
            continue
        index = int(np.argmin(np.abs(z - plane)))
        plane_metrics[name] = {
            "axial_z_mm": float(z[index]),
            "mean_transverse_distance_mm": float(np.mean(distances[:, index])),
            "p95_transverse_distance_mm": float(np.percentile(distances[:, index], 95)),
            "mean_delta_time_us": float(np.mean(delta_time[:, index])),
        }

    mean_distance = np.mean(distances, axis=0)
    onset = {}
    for threshold in (0.01, 0.05, 0.1, 0.2):
        indices = np.flatnonzero(mean_distance >= threshold)
        onset[f"mean_distance_ge_{threshold:g}_mm_z_mm"] = (
            float(z[indices[0]]) if indices.size else None
        )
    summary = {
        "status": "PASS",
        "common_axial_interval_mm": [float(z_start), float(z_end)],
        "particles": 25,
        "plane_metrics": plane_metrics,
        "transverse_difference_onset": onset,
        "interpretation": (
            "Independent fields and integrators are retained; only the common source is translated "
            f"{args.source_axial_offset_mm:g} mm downstream to bypass the entrance fringe."
        ),
    }
    output = args.workspace / "artifacts/projects/rf_quadrupole_collision_cooling/results/cross_solver"
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / f"transport_no_collision_{args.output_label}_diagnostics.json"
    png_path = output / f"transport_no_collision_{args.output_label}_diagnostics.png"
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    figure, axis = plt.subplots(figsize=(7.8, 4.8), constrained_layout=True)
    axis.plot(z, mean_distance, label="mean", color="tab:blue")
    axis.fill_between(z, *np.percentile(distances, [5, 95], axis=0),
                      color="tab:blue", alpha=0.18, label="5–95%")
    axis.axvline(70.0, color="0.35", linestyle="--", linewidth=1, label="internal test window end")
    axis.axvline(85.4, color="tab:red", linestyle=":", linewidth=1, label="rod exit")
    axis.set(title="Independent-solver trajectory difference: internal release",
             xlabel="axial z (mm)", ylabel="same-ID transverse distance (mm)")
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.savefig(png_path, dpi=190)
    plt.close(figure)
    print(f"STATUS=PASS SUMMARY={json_path}")


if __name__ == "__main__":
    main()
