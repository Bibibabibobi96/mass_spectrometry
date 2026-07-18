"""Plot aligned RF-quadrupole transport diagnostics from solver trajectory CSVs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle
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
        time = np.array([float(row["time_us"]) for row in rows])
        x = np.array([float(row["transverse_x_mm"]) for row in rows])
        y = np.array([float(row["transverse_y_mm"]) for row in rows])
        r = np.array([float(row["r_mm"]) for row in rows])
        unique, indices = np.unique(z, return_index=True)
        tracks[particle_id] = {"z": unique, "time": time[indices], "x": x[indices], "y": y[indices], "r": r[indices]}
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
    parser.add_argument("--comsol-trajectory", type=Path, required=True)
    parser.add_argument("--simion-trajectory", type=Path, required=True)
    parser.add_argument("--output-label", required=True)
    args = parser.parse_args()
    artifact = args.workspace / "artifacts/projects/rf_quadrupole_collision_cooling"
    result_dir = artifact / "results"
    tracks = {"COMSOL": load_tracks(args.comsol_trajectory), "SIMION": load_tracks(args.simion_trajectory)}
    particle_ids = sorted(tracks["COMSOL"])
    if particle_ids != sorted(tracks["SIMION"]):
        raise ValueError("COMSOL and SIMION trajectory particle IDs differ")
    output_dir = result_dir / "cross_solver"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.output_label}"
    def output_path(stem: str) -> Path:
        return output_dir / f"{stem}{suffix}.png"
    resolved, interface = load_contract()
    geometry = resolved["geometry_mm"]
    plane_contract = diagnostic_planes(resolved, interface)
    r0 = geometry["field_radius_r0"]
    rod_start, rod_end = geometry["rod_z_min"], geometry["rod_z_max"]
    detector_plane = plane_contract["detector_front"]
    step = geometry["simion_cell_mm"]
    common_z = np.arange(plane_contract["first_common_plane"], detector_plane + 1e-9, step)
    rf_period_us = 1e6 / resolved["mode"]["rf"]["frequency_Hz"]

    # 1. r(z) envelope, in identical axes for the two solvers.
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True, sharex=True, sharey=True)
    for axis, (solver, solver_tracks) in zip(axes, tracks.items(), strict=True):
        for particle_id, track in solver_tracks.items():
            axis.plot(track["z"], track["r"], linewidth=0.75, alpha=0.7,
                      label=f"individual ion (n={len(particle_ids)})" if particle_id == particle_ids[0] else None)
        axis.axvspan(rod_start, rod_end, color="0.9", label="rod section")
        axis.axhline(r0, color="black", linestyle="--", linewidth=1.1, label="r0")
        axis.set(title=f"{solver}: radial trajectory envelope", xlabel="axial z (mm)", ylabel="r (mm)", ylim=(0, r0 * 1.08))
        axis.grid(True, alpha=0.25)
    axes[0].legend(loc="upper left", fontsize=8)
    figure.savefig(output_path("transport_no_collision_r_vs_z"), dpi=190)
    plt.close(figure)

    # 2. Same-ID Delta r(z), evaluated on the common PA/COMSOL axial grid.
    delta_r = []
    for particle_id in particle_ids:
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
    figure.savefig(output_path("transport_no_collision_delta_r_vs_z"), dpi=190)
    plt.close(figure)

    # 3. Same-ID time/phase offset at the same physical axial plane.
    delta_time = []
    for particle_id in particle_ids:
        comsol_time = np.interp(common_z, tracks["COMSOL"][particle_id]["z"], tracks["COMSOL"][particle_id]["time"])
        simion_time = np.interp(common_z, tracks["SIMION"][particle_id]["z"], tracks["SIMION"][particle_id]["time"])
        delta_time.append(comsol_time - simion_time)
    delta_time_array = np.array(delta_time)
    figure, axis = plt.subplots(figsize=(9.5, 4.8), constrained_layout=True)
    for values in delta_time_array:
        axis.plot(common_z, values, color="tab:blue", alpha=0.24, linewidth=0.8)
    mean_delta_time = np.mean(delta_time_array, axis=0)
    axis.plot(common_z, mean_delta_time, color="tab:red", linewidth=2.0, label="mean Δt (COMSOL − SIMION)")
    axis.axhline(0, color="black", linewidth=0.8)
    axis.axvspan(rod_start, rod_end, color="0.9", label="rod section")
    axis.set(title="Same-ID time offset at common axial planes", xlabel="common axial z (mm)", ylabel="Δt (µs)")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.savefig(output_path("transport_no_collision_delta_time_vs_z"), dpi=190)
    plt.close(figure)

    # 4. Comparable transverse distributions at four physical planes.
    # The first common plane is one baseline PA cell downstream of the source.
    planes = [(plane_contract["first_common_plane"], "entrance"),
              (plane_contract["rod_midpoint"], "rod midpoint"),
              (plane_contract["rod_exit"], "rod exit"),
              (detector_plane, "detector front")]
    figure, axes = plt.subplots(2, 2, figsize=(9.5, 9.0), constrained_layout=True, sharex=True, sharey=True)
    plane_metrics: dict[str, dict[str, float]] = {}
    for axis, (plane, label) in zip(axes.flat, planes, strict=True):
        c_points = np.array([at_plane(tracks["COMSOL"][particle_id], plane)[:2] for particle_id in particle_ids])
        s_points = np.array([at_plane(tracks["SIMION"][particle_id], plane)[:2] for particle_id in particle_ids])
        axis.scatter(c_points[:, 0], c_points[:, 1], facecolors="none", edgecolors="tab:orange", s=52, linewidths=1.2, label="COMSOL")
        axis.scatter(s_points[:, 0], s_points[:, 1], color="tab:blue", marker="x", s=34, linewidths=1.0, label="SIMION")
        aperture = geometry["detector_radius"] if plane == detector_plane else r0
        axis.add_patch(Circle((0, 0), aperture, fill=False, color="black", linestyle="--", linewidth=1.0))
        axis.axhline(0, color="0.85", linewidth=0.7)
        axis.axvline(0, color="0.85", linewidth=0.7)
        axis.set_aspect("equal", adjustable="box")
        limit = r0 * 1.05
        axis.set(title=f"{label}: z={plane:g} mm", xlabel="PA / COMSOL x (mm)", ylabel="PA / COMSOL y (mm)", xlim=(-limit, limit), ylim=(-limit, limit))
        displacement = np.sqrt(np.sum((c_points - s_points) ** 2, axis=1))
        plane_metrics[label] = {
            "axial_z_mm": plane,
            "paired_transverse_distance_mean_mm": float(np.mean(displacement)),
            "paired_transverse_distance_max_mm": float(np.max(displacement)),
        }
    axes[0, 0].legend(loc="upper right")
    figure.suptitle("Comparable transverse distributions at transport milestones\ndashed circle = r0 in rod region, detector aperture at final plane")
    figure.savefig(output_path("transport_no_collision_key_plane_distributions"), dpi=190)
    plt.close(figure)

    summary = {
        "r0_mm": r0,
        "rod_z_range_mm": [rod_start, rod_end],
        "common_axial_grid_step_mm": step,
        "delta_r_mean_max_mm": float(np.max(np.mean(delta_r_array, axis=0))),
        "delta_r_p95_max_mm": float(np.max(np.percentile(delta_r_array, 95, axis=0))),
        "rf_period_us": rf_period_us,
        "detector_delta_time_us_mean": float(np.mean(delta_time_array[:, -1])),
        "detector_delta_time_us_max_abs": float(np.max(np.abs(delta_time_array[:, -1]))),
        "detector_mean_phase_offset_deg": float((np.mean(delta_time_array[:, -1]) / rf_period_us * 360) % 360),
        "key_planes": plane_metrics,
    }
    summary_path = output_dir / f"transport_no_collision_trajectory_diagnostics{suffix}.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"STATUS=PASS OUTPUT={output_dir} SUMMARY={summary_path}")


if __name__ == "__main__":
    main()
