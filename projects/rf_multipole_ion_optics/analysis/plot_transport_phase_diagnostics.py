"""Diagnose RF-phase and transverse differences from independent solver tracks."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from common.contracts.write_run_manifest import file_record
from projects.rf_multipole_ion_optics.analysis.rfquad_contract import (
    DEFAULT_INTERFACE, DEFAULT_REQUEST, DEFAULT_RESOLVED, load as load_contract,
)
from projects.rf_multipole_ion_optics.analysis.transport_diagnostics import diagnostic_planes


def load_tracks(path: Path) -> dict[int, dict[str, np.ndarray]]:
    """Read finite, unambiguous forward tracks in their recorded sample order."""
    grouped: dict[int, list[dict[str, str]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"particle_id", "axial_z_mm", "time_us", "transverse_x_mm", "transverse_y_mm"}
        if not reader.fieldnames or not required <= set(reader.fieldnames) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{path} requires unique trajectory columns: {sorted(required)}")
        for row in reader:
            particle_id = int(row["particle_id"])
            if particle_id <= 0:
                raise ValueError(f"{path} requires positive original integer particle IDs")
            grouped.setdefault(particle_id, []).append(row)
    if not grouped:
        raise ValueError(f"{path} contains no observed trajectories")
    tracks: dict[int, dict[str, np.ndarray]] = {}
    for particle_id, rows in grouped.items():
        track = {
            key: np.array([float(row[column]) for row in rows])
            for key, column in (("z", "axial_z_mm"), ("time", "time_us"),
                                ("x", "transverse_x_mm"), ("y", "transverse_y_mm"))
        }
        if len(rows) < 2 or any(not np.all(np.isfinite(values)) for values in track.values()):
            raise ValueError(f"{path} particle {particle_id} requires at least two finite samples")
        if np.any(np.diff(track["z"]) <= 0) or np.any(np.diff(track["time"]) <= 0):
            raise ValueError(f"{path} particle {particle_id} has ambiguous or non-forward recorded samples")
        tracks[particle_id] = track
    return tracks


def interpolate(track: dict[str, np.ndarray], z: np.ndarray, key: str) -> np.ndarray:
    if not np.all(np.isfinite(z)) or np.any(z < track["z"][0]) or np.any(z > track["z"][-1]):
        raise ValueError("diagnostic grid is outside an observed trajectory support interval")
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
    step = 0.2
    z = np.arange(planes["first_common_plane"], planes["detector_front"] + 1e-9, step)
    period_us = 1e6 / resolved["drive"]["frequency_Hz"]

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
    if not abs_phase.size:
        raise ValueError("diagnostic grid contains no rod-region observations")
    correlation_status = "zero_variance" if np.ptp(abs_phase) == 0 or np.ptp(rod_distance) == 0 else "computed"
    correlation = float(np.corrcoef(abs_phase, rod_distance)[0, 1]) if correlation_status == "computed" else None
    if correlation is not None and not np.isfinite(correlation):
        raise ValueError("RF phase correlation is nonfinite")
    mean_distance = np.mean(distance, axis=0)
    onset: dict[str, float | None] = {}
    for threshold in (0.01, 0.05, 0.1, 0.2):
        indices = np.flatnonzero(mean_distance >= threshold)
        onset[f"mean_distance_ge_{threshold:g}_mm_z_mm"] = float(z[indices[0]]) if indices.size else None
    summary = {
        "status": "PASS",
        "schema_version": 1,
        "role": "observed_transport_phase_diagnostics",
        "rf_period_us": period_us,
        "rod_samples": int(abs_phase.size),
        "rod_abs_wrapped_phase_deg_mean": float(np.mean(abs_phase)),
        "rod_abs_wrapped_phase_deg_p95": float(np.percentile(abs_phase, 95)),
        "rod_phase_distance_pearson_r": correlation,
        "rod_phase_distance_correlation_status": correlation_status,
        "transverse_difference_onset": onset,
        "plane_metrics": plane_metrics,
        "interpretation": "Correlation is descriptive only; this diagnostic does not alter either field or trajectory.",
        "analysis_metadata": {
            "method_id": "observed_forward_track_linear_axial_grid_v1",
            "qualification": "descriptive_only",
            "observed_particle_ids": particle_ids,
            "sample_relationship": "same_recorded_ids__common_source_identity_unspecified",
            "mother_cohort": "unspecified",
            "frame": "unspecified",
            "clock": "unspecified",
            "units": {"axial_position": "mm", "transverse_distance": "mm", "time": "us", "phase": "degree"},
            "display_grid": {"step_mm": step, "first_mm": float(z[0]), "last_mm": float(z[-1]),
                             "count": int(z.size), "plane_selection": "nearest_display_grid_sample"},
            "observed_support_mm": {solver: {str(pid): [float(track["z"][0]), float(track["z"][-1])]
                                               for pid, track in tracks.items()}
                                    for solver, tracks in (("COMSOL", comsol), ("SIMION", simion))},
            "inputs": {"comsol_trajectory": file_record(args.comsol_trajectory.resolve()),
                       "simion_trajectory": file_record(args.simion_trajectory.resolve())},
            "diagnostic_design_inputs": {"resolved": file_record(DEFAULT_RESOLVED),
                                         "request": file_record(DEFAULT_REQUEST),
                                         "interface": file_record(DEFAULT_INTERFACE)},
            "design_binding": "current_default_diagnostic_design__not_evidence_of_trajectory_source_design",
        },
    }
    summary_text = json.dumps(summary, indent=2, allow_nan=False) + "\n"
    output = results / "cross_solver"
    output.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.output_label}"
    summary_path = output / f"transport_no_collision_phase_diagnostics{suffix}.json"
    summary_path.write_text(summary_text, encoding="utf-8")

    figure, axes = plt.subplots(1, 2, figsize=(11, 4.6), constrained_layout=True)
    axes[0].plot(z, np.mean(dt, axis=0) * 1e3, color="tab:red", label="mean Δt")
    axes[0].fill_between(z, *(np.percentile(dt, [5, 95], axis=0) * 1e3), color="tab:red", alpha=0.18, label="5–95%")
    axes[0].axvspan(geometry["rod_z_min"], geometry["rod_z_max"], color="0.9")
    axes[0].set(title="Arrival-time difference at common axial position", xlabel="axial z (mm)", ylabel="COMSOL − SIMION Δt (ns)")
    axes[0].grid(True, alpha=0.3); axes[0].legend()
    axes[1].scatter(abs_phase, rod_distance, s=5, alpha=0.22, color="tab:blue")
    correlation_label = f"r={correlation:.3f}" if correlation is not None else f"r unavailable ({correlation_status})"
    axes[1].set(title=f"Rod region: |wrapped phase| vs transverse distance\n{correlation_label}", xlabel="|wrapped RF phase difference| (deg)", ylabel="same-ID transverse distance (mm)")
    axes[1].grid(True, alpha=0.3)
    figure.savefig(output / f"transport_no_collision_phase_diagnostics{suffix}.png", dpi=190)
    plt.close(figure)
    print(f"STATUS=PASS SUMMARY={summary_path}")


if __name__ == "__main__":
    main()
