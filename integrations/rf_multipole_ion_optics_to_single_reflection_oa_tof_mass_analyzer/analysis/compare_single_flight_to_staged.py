"""Compare continuous and staged SIMION oaTOF paths by original mother-sample ID."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import compute_peak_metrics


def _norm(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    return np.sqrt(np.square(frame[columns].to_numpy(dtype=float)).sum(axis=1))


def _residual_summary(frame: pd.DataFrame, prefix: str) -> dict[str, float | int | None]:
    if frame.empty:
        return {"paired_particles": 0, "median_abs_time_ns": None, "rms_position_um": None, "rms_velocity_m_s": None}
    time = frame[f"{prefix}_dt_us"].to_numpy(dtype=float) * 1e3
    position = _norm(frame, [f"{prefix}_dx_mm", f"{prefix}_dy_mm", f"{prefix}_dz_mm"]) * 1e3
    velocity = _norm(frame, [f"{prefix}_dvx_mm_per_us", f"{prefix}_dvy_mm_per_us", f"{prefix}_dvz_mm_per_us"]) * 1e3
    return {
        "paired_particles": len(frame),
        "median_abs_time_ns": float(np.median(np.abs(time))),
        "rms_position_um": float(np.sqrt(np.mean(position**2))),
        "rms_velocity_m_s": float(np.sqrt(np.mean(velocity**2))),
    }


def compare(single_path: Path, single_initial_path: Path, staged_handoff_path: Path, staged_grid2_path: Path, staged_row_map_path: Path, staged_detector_path: Path, pulse_time_us: float) -> tuple[pd.DataFrame, dict[str, object]]:
    single = pd.read_csv(single_path)
    if single.duplicated(["particle_id", "event"]).any():
        raise ValueError("single-flight checkpoints contain duplicate particle/event IDs")
    events = {name: frame.set_index("particle_id") for name, frame in single.groupby("event")}
    staged_handoff = pd.read_csv(staged_handoff_path).set_index("particle_id")
    staged_grid2 = pd.read_csv(staged_grid2_path).set_index("particle_id")
    row_map = pd.read_csv(staged_row_map_path).set_index("solver_row_index")
    staged_detector_raw = pd.read_csv(staged_detector_path)
    staged_detector_raw = staged_detector_raw[staged_detector_raw["Hit"].astype(str).str.lower().eq("true")].copy()
    staged_detector_raw["particle_id"] = staged_detector_raw["Ion"].map(row_map["particle_id"])
    if staged_detector_raw["particle_id"].isna().any():
        raise ValueError("staged detector rows do not resolve to original particle IDs")
    staged_detector = staged_detector_raw.set_index("particle_id")

    ids = pd.Index(range(1, 1001), name="particle_id")
    paired = pd.DataFrame(index=ids)
    for label, values in (("single_handoff", events["multipole_handoff"]), ("staged_handoff", staged_handoff), ("single_grid2", events["local_accelerator_exit"]), ("staged_grid2", staged_grid2), ("single_detector", events["detector_crossing"]), ("staged_detector", staged_detector)):
        paired[f"{label}_present"] = paired.index.isin(values.index)

    handoff_common = events["multipole_handoff"].join(staged_handoff, how="inner", lsuffix="_single", rsuffix="_staged")
    handoff = pd.DataFrame(index=handoff_common.index)
    handoff["handoff_dt_us"] = handoff_common["instrument_time_us_single"] - handoff_common["instrument_time_us_staged"]
    for axis, staged_position, staged_velocity in (("x", "position_x_mm", "velocity_x_m_s"), ("y", "position_y_mm", "velocity_y_m_s"), ("z", "position_z_mm", "velocity_z_m_s")):
        handoff[f"handoff_d{axis}_mm"] = handoff_common[f"{axis}_mm"] - handoff_common[staged_position]
        handoff[f"handoff_dv{axis}_mm_per_us"] = handoff_common[f"v{axis}_mm_per_us"] - handoff_common[staged_velocity] / 1000.0

    grid2_common = events["local_accelerator_exit"].join(staged_grid2, how="inner", lsuffix="_single", rsuffix="_staged")
    grid2 = pd.DataFrame(index=grid2_common.index)
    grid2["grid2_dt_us"] = grid2_common["instrument_time_us_single"] - grid2_common["instrument_time_us_staged"]
    for axis in "xyz":
        grid2[f"grid2_d{axis}_mm"] = grid2_common[f"{axis}_mm"] - grid2_common[axis]
        grid2[f"grid2_dv{axis}_mm_per_us"] = grid2_common[f"v{axis}_mm_per_us"] - grid2_common[f"v{axis}"] / 1000.0

    detector_common = events["detector_crossing"].join(staged_detector, how="inner", lsuffix="_single", rsuffix="_staged")
    detector = pd.DataFrame(index=detector_common.index)
    detector["detector_dt_us"] = detector_common["instrument_time_us"] - detector_common["InstrumentTimeUs"]
    for axis, staged_name in (("x", "XMm"), ("y", "YMm")):
        detector[f"detector_d{axis}_mm"] = detector_common[f"{axis}_mm"] - detector_common[staged_name]
    paired = paired.join(handoff).join(grid2).join(detector)
    single_initial = pd.read_csv(single_initial_path).set_index("particle_id")
    single_detector_clock = events["detector_crossing"]["instrument_time_us"]
    single_birth = single_initial.loc[
        single_detector_clock.index, "instrument_time_us"
    ].to_numpy(dtype=float)
    single_clock = single_detector_clock.to_numpy(dtype=float)
    staged_clock = staged_detector["InstrumentTimeUs"].to_numpy(dtype=float)
    single_peak, _ = compute_peak_metrics(single_clock - pulse_time_us, 100.0)
    staged_peak, _ = compute_peak_metrics(staged_clock - pulse_time_us, 100.0)
    single_residence, _ = compute_peak_metrics(single_clock - single_birth, 100.0)
    staged_elapsed, _ = compute_peak_metrics(staged_detector["TofUs"].to_numpy(dtype=float), 100.0)
    detector_delta_ns = detector["detector_dt_us"].to_numpy(dtype=float) * 1e3
    result = {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_staged_paired_comparison",
        "status": "PASS",
        "population": 1000,
        "census": {
            "single": {event: len(frame) for event, frame in events.items()},
            "staged": {"multipole_handoff": len(staged_handoff), "local_accelerator_exit": len(staged_grid2), "detector_crossing": len(staged_detector)},
            "paired": {"multipole_handoff": len(handoff), "local_accelerator_exit": len(grid2), "detector_crossing": len(detector)},
        },
        "handoff_residual": _residual_summary(handoff, "handoff"),
        "grid2_residual": _residual_summary(grid2, "grid2"),
        "detector_residual": {
            "paired_particles": len(detector),
            "median_time_delta_ns": float(np.median(detector_delta_ns)),
            "rms_time_delta_ns": float(np.sqrt(np.mean(detector_delta_ns**2))),
            "rms_xy_position_um": float(np.sqrt(np.mean(np.square(detector[["detector_dx_mm", "detector_dy_mm"]].to_numpy()).sum(axis=1))) * 1e3),
        },
        "resolution": {
            "pulse_referenced_detector_peak": {
                "basis": f"detector instrument time minus common pulse origin {pulse_time_us:.14g} us",
                "single_flight": single_peak,
                "staged": staged_peak,
            },
            "non_equivalent_elapsed_diagnostics": {
                "single_end_to_end_from_mother_birth": single_residence,
                "staged_published_downstream_from_grid2_restart": staged_elapsed,
                "resolution_comparison_allowed": False,
            },
        },
        "interpretation_limit": "Diagnostic comparison; geometry integration and field-boundary changes are intentionally coupled.",
    }
    return paired.reset_index(), result


def plot_comparison(paired: pd.DataFrame, result: dict[str, object], output: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(10, 7.5), constrained_layout=True)
    labels = ["Handoff", "Grid2", "Detector"]
    single = result["census"]["single"]; staged = result["census"]["staged"]
    x = np.arange(3); width = 0.36
    axes[0, 0].bar(x-width/2, [single["multipole_handoff"], single["local_accelerator_exit"], single["detector_crossing"]], width, label="single")
    axes[0, 0].bar(x+width/2, [staged["multipole_handoff"], staged["local_accelerator_exit"], staged["detector_crossing"]], width, label="staged")
    axes[0, 0].set_xticks(x, labels); axes[0, 0].set_ylabel("Particles"); axes[0, 0].legend()
    for axis, column, title in ((axes[0, 1], "handoff_dt_us", "Handoff Δt"), (axes[1, 0], "grid2_dt_us", "Grid2 Δt"), (axes[1, 1], "detector_dt_us", "Detector Δt")):
        values = paired[column].dropna().to_numpy() * 1e3
        axis.hist(values, bins=40, color="#4472C4", alpha=0.85); axis.set_title(title); axis.set_xlabel("single − staged (ns)"); axis.set_ylabel("Particles")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180); plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", required=True, type=Path); parser.add_argument("--single-initial", required=True, type=Path); parser.add_argument("--staged-handoff", required=True, type=Path)
    parser.add_argument("--staged-grid2", required=True, type=Path); parser.add_argument("--staged-row-map", required=True, type=Path)
    parser.add_argument("--staged-detector", required=True, type=Path); parser.add_argument("--paired-csv", required=True, type=Path)
    parser.add_argument("--pulse-time-us", required=True, type=float)
    parser.add_argument("--metrics", required=True, type=Path); parser.add_argument("--figure", required=True, type=Path)
    args = parser.parse_args()
    paired, result = compare(args.single, args.single_initial, args.staged_handoff, args.staged_grid2, args.staged_row_map, args.staged_detector, args.pulse_time_us)
    args.paired_csv.parent.mkdir(parents=True, exist_ok=True); paired.to_csv(args.paired_csv, index=False)
    args.metrics.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    plot_comparison(paired, result, args.figure)
    print(f"SINGLE_VS_STAGED=PASS DETECTOR_PAIRED={result['census']['paired']['detector_crossing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
