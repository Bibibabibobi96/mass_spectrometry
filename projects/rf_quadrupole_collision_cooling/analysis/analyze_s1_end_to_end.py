"""Summarize the sparse RF -> physical S1 joint -> oaTOF detector chain."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np

try:
    from peak_metrics import AnalysisSettings, compute_detector_metrics, compute_peak_metrics
except ModuleNotFoundError:
    from projects.oa_tof.analysis.peak_metrics import AnalysisSettings, compute_detector_metrics, compute_peak_metrics


FIELDS = [
    "particle_id", "event", "frame_id", "clock_epoch_id",
    "instrument_time_us", "x_mm", "y_mm", "z_mm", "status",
]


def read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def analysis_settings(path: Path) -> tuple[AnalysisSettings, str]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    kde = contract["kde"]
    settings = AnalysisSettings(
        grid_points=int(kde["grid_points"]),
        bandwidth_multiplier=float(kde["bandwidth_multiplier"]),
        mode_threshold_fraction=float(kde["significant_mode_threshold_fraction"]),
    )
    return settings, hashlib.sha256(path.read_bytes()).hexdigest().upper()


def detector_geometry(path: Path) -> tuple[float, float, float, str]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    coordinates = contract["coordinate_convention"]
    geometry = contract["geometry_mm"]
    return (
        float(coordinates["detector_x"]),
        float(coordinates.get("detector_y", 0.0)),
        float(geometry["detector_radius"]),
        hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    )


def resolution_diagnostic(
    downstream: list[dict[str, str]], nominal_mass_amu: float, pulse_time_us: float,
    settings: AnalysisSettings, contract_sha256: str, detector_center_x_mm: float,
    detector_center_y_mm: float, detector_radius_mm: float,
    geometry_contract_sha256: str, figure_path: Path | None,
    frame_id: str, clock_epoch_id: str,
) -> dict[str, object]:
    crossings = [row for row in downstream if math.isfinite(float(row["InstrumentTimeUs"]))]
    hits = [row for row in crossings if row["Hit"].strip().lower() == "true"]
    result: dict[str, object] = {
        "status": "AVAILABLE" if len(hits) >= 3 else "INSUFFICIENT_HITS",
        "scope": "N<=100 pulse-referenced diagnostic only; not a Formal resolution claim",
        "reference_time_origin": "shared extraction pulse onset",
        "pulse_instrument_time_us": pulse_time_us,
        "nominal_mass_amu": nominal_mass_amu,
        "detector_crossings": len(crossings),
        "detector_hits": len(hits),
        "analysis_contract_sha256": contract_sha256,
        "geometry_contract_sha256": geometry_contract_sha256,
        "frame_id": frame_id,
        "clock_epoch_id": clock_epoch_id,
        "detector_local_frame": {
            "global_center_x_mm": detector_center_x_mm,
            "global_center_y_mm": detector_center_y_mm,
            "active_radius_mm": detector_radius_mm,
        },
        "formal_resolution_claim_allowed": False,
    }
    if len(hits) < 3:
        return result
    pulse_referenced_tof = np.asarray(
        [float(row["InstrumentTimeUs"]) - pulse_time_us for row in hits], dtype=float)
    if np.any(pulse_referenced_tof <= 0):
        raise ValueError("detector arrival precedes the shared extraction pulse")
    metrics, spectra = compute_peak_metrics(pulse_referenced_tof, nominal_mass_amu, settings)
    hit_x = np.asarray([float(row["XMm"]) - detector_center_x_mm for row in hits])
    hit_y = np.asarray([float(row["YMm"]) - detector_center_y_mm for row in hits])
    detector = compute_detector_metrics(hit_x, hit_y)
    result["canonical_peak_metrics"] = metrics
    result["detector_metrics"] = detector
    result["arrival_instrument_time_us"] = {
        "min": min(float(row["InstrumentTimeUs"]) for row in hits),
        "max": max(float(row["InstrumentTimeUs"]) for row in hits),
    }
    if figure_path is not None:
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.1))
        axes[0].plot(spectra["time_grid_us"], spectra["time_density_normalized"],
                     color="#2166ac", linewidth=2)
        axes[0].axvline(float(spectra["time_half_left_us"]), color="#cb181d",
                        linestyle="--", linewidth=1.2)
        axes[0].axvline(float(spectra["time_half_right_us"]), color="#cb181d",
                        linestyle="--", linewidth=1.2)
        axes[0].scatter(pulse_referenced_tof, np.full(len(hits), -0.035), marker="|",
                        color="#252525", s=30)
        axes[0].set(
            xlabel="Detector arrival time after pulse onset (µs)",
            ylabel="Normalized KDE density",
            title=(f"A  Pulse-referenced peak: FWHM={metrics['direct_fwhm_tof_ns']:.3g} ns, "
                   f"R={metrics['time_equivalent_resolution']:.3g}"),
        )
        axes[0].set_ylim(-0.08, 1.08)
        axes[0].grid(alpha=0.2)

        misses = [row for row in crossings if row["Hit"].strip().lower() != "true"]
        axes[1].scatter(hit_x, hit_y, s=16, color="#238b45", label="detector hit", alpha=0.8)
        if misses:
            axes[1].scatter([float(row["XMm"]) - detector_center_x_mm for row in misses],
                            [float(row["YMm"]) - detector_center_y_mm for row in misses],
                            s=18, marker="x",
                            color="#cb181d", label="crossing outside active radius")
        axes[1].add_patch(Circle((0, 0), detector_radius_mm, fill=False, linestyle="--",
                                 linewidth=1.4, edgecolor="#756bb1"))
        axes[1].set(xlabel="Detector x (mm)", ylabel="Detector y (mm)",
                    title=f"B  Detector plane: {len(hits)}/{len(downstream)} hits")
        axes[1].set_aspect("equal", adjustable="box")
        axes[1].grid(alpha=0.2)
        axes[1].legend(loc="best", fontsize=8)
        fig.suptitle(
            "RF-to-oaTOF downstream peak and detector diagnostic\n"
            f"frame={frame_id}; clock epoch={clock_epoch_id}"
        )
        fig.tight_layout()
        figure_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(figure_path, format="png", dpi=190)
        plt.close(fig)
    return result


def analyze(entry_path: Path, local_path: Path, downstream_path: Path, row_map_path: Path,
            events_output: Path, pulse_time_us: float | None = None,
            pulse_width_us: float | None = None, analysis_contract_path: Path | None = None,
            geometry_contract_path: Path | None = None,
            resolution_figure: Path | None = None) -> dict[str, object]:
    entries, local, downstream, mapping = map(read, (entry_path, local_path, downstream_path, row_map_path))
    if len(entries) != 100 or len(local) != 100:
        raise ValueError("S1 end-to-end analysis requires the complete N=100 upstream census")
    identities = {
        (row["frame_id"], row["clock_epoch_id"]) for row in entries + local
    }
    if len(identities) != 1 or any(not value for value in next(iter(identities))):
        raise ValueError("S1 end-to-end states must bind one frame and clock epoch")
    frame_id, clock_epoch_id = next(iter(identities))
    solver_to_particle = {int(row["solver_row_index"]): int(row["particle_id"]) for row in mapping}
    if len(downstream) != len(mapping):
        raise ValueError("SIMION downstream census differs from its row map")
    sparse: list[dict[str, object]] = []
    for row in entries:
        sparse.append({
            "particle_id": int(row["particle_id"]), "event": "rf_exit_entry",
            "frame_id": frame_id, "clock_epoch_id": clock_epoch_id,
            "instrument_time_us": row["instrument_time_us"], "x_mm": row["position_x_mm"],
            "y_mm": row["position_y_mm"], "z_mm": row["position_z_mm"], "status": "entered_s1",
        })
    for row in local:
        sparse.append({
            "particle_id": int(row["particle_id"]), "event": row["event"],
            "frame_id": frame_id, "clock_epoch_id": clock_epoch_id,
            "instrument_time_us": row["instrument_time_us"], "x_mm": row["x_mm"],
            "y_mm": row["y_mm"], "z_mm": row["z_mm"], "status": row["status"],
        })
    hits = 0
    for row in downstream:
        solver_index = int(row["Ion"])
        particle_id = solver_to_particle[solver_index]
        hit = row["Hit"].strip().lower() == "true"
        hits += int(hit)
        sparse.append({
            "particle_id": particle_id, "event": "detector_outcome",
            "frame_id": frame_id, "clock_epoch_id": clock_epoch_id,
            "instrument_time_us": row["InstrumentTimeUs"], "x_mm": row["XMm"],
            "y_mm": row["YMm"], "z_mm": "0", "status": "detector_hit" if hit else "lost",
        })
    events_output.parent.mkdir(parents=True, exist_ok=True)
    with events_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader(); writer.writerows(sparse)
    geometric = sum(row["event"] != "geometric_reject" for row in local)
    exits = sum(row["event"] == "local_joint_exit" for row in local)
    finite_detector_times = sum(math.isfinite(float(row["InstrumentTimeUs"])) for row in downstream)
    local_exit_ids = {int(row["particle_id"]) for row in local
                      if row["event"] == "local_joint_exit"}
    mapped_particle_ids = {int(row["particle_id"]) for row in mapping}
    downstream_solver_indices = {int(row["Ion"]) for row in downstream}
    mapped_solver_indices = set(solver_to_particle)
    birth_time_by_solver_index = {
        int(row["solver_row_index"]): float(row["solver_birth_time_us"]) for row in mapping
    }
    absolute_clock_monotonic = all(
        not math.isfinite(float(row["InstrumentTimeUs"]))
        or float(row["InstrumentTimeUs"]) >= birth_time_by_solver_index[int(row["Ion"])]
        for row in downstream
    )
    checks = {
        "complete_upstream_census": len(entries) == 100 and len(local) == 100,
        "local_exit_census_matches_downstream_input": exits == len(mapping),
        "original_particle_id_set_preserved": local_exit_ids == mapped_particle_ids,
        "solver_row_identity_complete": downstream_solver_indices == mapped_solver_indices,
        "absolute_clock_monotonic": absolute_clock_monotonic,
        "complete_downstream_census": len(downstream) == len(mapping),
        "minimum_detector_hit": hits >= 1,
    }
    result: dict[str, object] = {
        "schema_version": 1,
        "role": "rf_to_oatof_s1_physical_end_to_end_function_gate",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "rf_exit_particles": 100,
        "physical_port_accepted": geometric,
        "local_joint_exit": exits,
        "simion_downstream_emitted": len(downstream),
        "detector_plane_crossings": finite_detector_times,
        "detector_hits": hits,
        "end_to_end_detector_transmission": hits / 100,
        "downstream_detector_transmission": hits / len(downstream) if downstream else 0.0,
        "identity_and_clock": {
            "unique_original_particle_ids": len(mapped_particle_ids),
            "solver_rows": len(mapped_solver_indices),
            "original_particle_id_set_preserved": local_exit_ids == mapped_particle_ids,
            "absolute_instrument_clock_preserved": absolute_clock_monotonic,
        },
        "sparse_event_rows": len(sparse),
        "dense_trajectories_saved": False,
        "checks": checks,
        "physical_link_claim_allowed": False,
        "resolution_claim_allowed": False,
        "frame_id": frame_id,
        "clock_epoch_id": clock_epoch_id,
    }
    if pulse_time_us is not None:
        if (pulse_width_us is None or pulse_width_us <= 0 or analysis_contract_path is None
                or geometry_contract_path is None):
            raise ValueError("pulse resolution diagnostic requires pulse width and both oaTOF contracts")
        masses = {float(row["mass_amu"]) for row in entries}
        if len(masses) != 1:
            raise ValueError("S1 resolution diagnostic requires one explicit mass group")
        exit_times = [float(row["instrument_time_us"]) for row in local
                      if row["event"] == "local_joint_exit"]
        pulse_end = pulse_time_us + pulse_width_us
        result["pulse_continuation"] = {
            "pulse_start_us": pulse_time_us,
            "pulse_end_us": pulse_end,
            "local_exit_time_min_us": min(exit_times),
            "local_exit_time_max_us": max(exit_times),
            "exits_before_pulse": sum(value < pulse_time_us for value in exit_times),
            "exits_during_pulse": sum(pulse_time_us <= value < pulse_end for value in exit_times),
            "exits_after_pulse": sum(value >= pulse_end for value in exit_times),
            "remaining_pulse_at_exit_us": {
                "min": min(pulse_end - value for value in exit_times),
                "max": max(pulse_end - value for value in exit_times),
            },
            "downstream_program_uses_same_absolute_clock": True,
        }
        settings, contract_sha = analysis_settings(analysis_contract_path)
        detector_x, detector_y, detector_radius, geometry_sha = detector_geometry(
            geometry_contract_path)
        result["resolution_diagnostic"] = resolution_diagnostic(
            downstream, next(iter(masses)), pulse_time_us, settings, contract_sha,
            detector_x, detector_y, detector_radius, geometry_sha, resolution_figure,
            frame_id, clock_epoch_id,
        )
    return result


def plot_funnel(result: dict[str, object], output: Path) -> None:
    labels = ["RF exit", "inside port", "local exit", "detector hit"]
    values = [int(result[key]) for key in (
        "rf_exit_particles", "physical_port_accepted", "local_joint_exit", "detector_hits"
    )]
    colors = ["#2166ac", "#67a9cf", "#fdae61", "#238b45"]
    figure, axis = plt.subplots(figsize=(7.2, 4.6))
    bars = axis.bar(labels, values, color=colors)
    axis.bar_label(bars, labels=[f"{value}/100" for value in values], padding=3)
    axis.set(
        ylabel="Particles", ylim=(0, 108),
        title=(
            "RF to oaTOF S1 functional-chain census\n"
            f"frame={result['frame_id']}; epoch={result['clock_epoch_id']}"
        ),
    )
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, format="png", dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--downstream", type=Path, required=True)
    parser.add_argument("--row-map", type=Path, required=True)
    parser.add_argument("--events-output", type=Path, required=True)
    parser.add_argument("--figure", type=Path)
    parser.add_argument("--resolution-figure", type=Path)
    parser.add_argument("--pulse-time-us", type=float)
    parser.add_argument("--pulse-width-us", type=float)
    parser.add_argument("--analysis-contract", type=Path)
    parser.add_argument("--geometry-contract", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(
        args.entry, args.local, args.downstream, args.row_map, args.events_output,
        args.pulse_time_us, args.pulse_width_us, args.analysis_contract,
        args.geometry_contract, args.resolution_figure,
    )
    if args.figure is not None:
        plot_funnel(result, args.figure)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"S1_END_TO_END={result['status']} HITS={result['detector_hits']}/100")
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
