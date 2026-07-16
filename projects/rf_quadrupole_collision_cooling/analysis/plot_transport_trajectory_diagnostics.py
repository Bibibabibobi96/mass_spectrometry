"""Plot aligned RF-quadrupole transport diagnostics from solver trajectory CSVs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle


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
        x = np.array([float(row["transverse_x_mm"]) for row in rows])
        y = np.array([float(row["transverse_y_mm"]) for row in rows])
        r = np.array([float(row["r_mm"]) for row in rows])
        unique, indices = np.unique(z, return_index=True)
        tracks[particle_id] = {"z": unique, "x": x[indices], "y": y[indices], "r": r[indices]}
    return tracks


def at_plane(track: dict[str, np.ndarray], plane_mm: float) -> tuple[float, float, float]:
    z = track["z"]
    tolerance_mm = 1e-6
    if plane_mm < z[0] - tolerance_mm or plane_mm > z[-1] + tolerance_mm:
        raise ValueError(f"plane {plane_mm} mm lies outside trajectory [{z[0]}, {z[-1]}] mm")
    sample_plane = min(max(plane_mm, z[0]), z[-1])
    return tuple(float(np.interp(sample_plane, z, track[key])) for key in ("x", "y", "r"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.workspace / "artifacts/projects/rf_quadrupole_collision_cooling"
    result_dir = artifact / "results"
    tracks = {
        "COMSOL": load_tracks(result_dir / "comsol/transport_no_collision_trajectory_samples.csv"),
        "SIMION": load_tracks(result_dir / "simion/transport_no_collision_trajectory_samples_baseline.csv"),
    }
    output_dir = result_dir / "cross_solver"
    output_dir.mkdir(parents=True, exist_ok=True)
    r0 = 4.0
    rod_start, rod_end = 5.8, 85.4
    detector_plane = 94.8  # SIMION fractional-surface terminal plane
    common_z = np.arange(0.2, detector_plane + 1e-9, 0.2)

    # 1. r(z) envelope, in identical axes for the two solvers.
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True, sharex=True, sharey=True)
    for axis, (solver, solver_tracks) in zip(axes, tracks.items(), strict=True):
        for particle_id, track in solver_tracks.items():
            axis.plot(track["z"], track["r"], linewidth=0.75, alpha=0.7,
                      label="individual ion (n=25)" if particle_id == 1 else None)
        axis.axvspan(rod_start, rod_end, color="0.9", label="rod section")
        axis.axhline(r0, color="black", linestyle="--", linewidth=1.1, label="r0")
        axis.set(title=f"{solver}: radial trajectory envelope", xlabel="axial z (mm)", ylabel="r (mm)", ylim=(0, r0 * 1.08))
        axis.grid(True, alpha=0.25)
    axes[0].legend(loc="upper left", fontsize=8)
    figure.savefig(output_dir / "transport_no_collision_r_vs_z.png", dpi=190)
    plt.close(figure)

    # 2. Same-ID Delta r(z), evaluated on the common PA/COMSOL axial grid.
    delta_r = []
    for particle_id in range(1, 26):
        comsol_r = np.interp(common_z, tracks["COMSOL"][particle_id]["z"], tracks["COMSOL"][particle_id]["r"])
        simion_r = np.interp(common_z, tracks["SIMION"][particle_id]["z"], tracks["SIMION"][particle_id]["r"])
        delta_r.append(np.abs(comsol_r - simion_r))
    delta_r_array = np.array(delta_r)
    figure, axis = plt.subplots(figsize=(9.5, 4.8), constrained_layout=True)
    for particle_id, values in enumerate(delta_r_array, start=1):
        axis.plot(common_z, values, color="tab:blue", alpha=0.24, linewidth=0.8)
    axis.plot(common_z, np.mean(delta_r_array, axis=0), color="tab:red", linewidth=2.0, label="mean |Δr|")
    axis.plot(common_z, np.percentile(delta_r_array, 95, axis=0), color="tab:orange", linewidth=1.6, label="95th percentile |Δr|")
    axis.axvspan(rod_start, rod_end, color="0.9", label="rod section")
    axis.set(title="Same-ID transverse-radius discrepancy along transport axis", xlabel="common axial z (mm)", ylabel="|r_COMSOL − r_SIMION| (mm)")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.savefig(output_dir / "transport_no_collision_delta_r_vs_z.png", dpi=190)
    plt.close(figure)

    # 3. Comparable transverse distributions at four physical planes.
    # 0.2 mm is the first common sampling plane: COMSOL stores release at
    # z=0.0100 mm whereas SIMION's source is exactly z=0.
    planes = [(0.2, "entrance"), (45.6, "rod midpoint"), (85.4, "rod exit"), (detector_plane, "detector front")]
    figure, axes = plt.subplots(2, 2, figsize=(9.5, 9.0), constrained_layout=True, sharex=True, sharey=True)
    plane_metrics: dict[str, dict[str, float]] = {}
    for axis, (plane, label) in zip(axes.flat, planes, strict=True):
        c_points = np.array([at_plane(tracks["COMSOL"][particle_id], plane)[:2] for particle_id in range(1, 26)])
        s_points = np.array([at_plane(tracks["SIMION"][particle_id], plane)[:2] for particle_id in range(1, 26)])
        axis.scatter(c_points[:, 0], c_points[:, 1], facecolors="none", edgecolors="tab:orange", s=52, linewidths=1.2, label="COMSOL")
        axis.scatter(s_points[:, 0], s_points[:, 1], color="tab:blue", marker="x", s=34, linewidths=1.0, label="SIMION")
        aperture = 3.6 if plane == detector_plane else r0
        axis.add_patch(Circle((0, 0), aperture, fill=False, color="black", linestyle="--", linewidth=1.0))
        axis.axhline(0, color="0.85", linewidth=0.7)
        axis.axvline(0, color="0.85", linewidth=0.7)
        axis.set_aspect("equal", adjustable="box")
        axis.set(title=f"{label}: z={plane:g} mm", xlabel="PA / COMSOL x (mm)", ylabel="PA / COMSOL y (mm)", xlim=(-4.2, 4.2), ylim=(-4.2, 4.2))
        displacement = np.sqrt(np.sum((c_points - s_points) ** 2, axis=1))
        plane_metrics[label] = {
            "axial_z_mm": plane,
            "paired_transverse_distance_mean_mm": float(np.mean(displacement)),
            "paired_transverse_distance_max_mm": float(np.max(displacement)),
        }
    axes[0, 0].legend(loc="upper right")
    figure.suptitle("Comparable transverse distributions at transport milestones\ndashed circle = r0 in rod region, detector aperture at final plane")
    figure.savefig(output_dir / "transport_no_collision_key_plane_distributions.png", dpi=190)
    plt.close(figure)

    summary = {
        "r0_mm": r0,
        "rod_z_range_mm": [rod_start, rod_end],
        "common_axial_grid_step_mm": 0.2,
        "delta_r_mean_max_mm": float(np.max(np.mean(delta_r_array, axis=0))),
        "delta_r_p95_max_mm": float(np.max(np.percentile(delta_r_array, 95, axis=0))),
        "key_planes": plane_metrics,
    }
    summary_path = output_dir / "transport_no_collision_trajectory_diagnostics.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"STATUS=PASS OUTPUT={output_dir} SUMMARY={summary_path}")


if __name__ == "__main__":
    main()
