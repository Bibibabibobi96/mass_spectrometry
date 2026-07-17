"""Compare representative COMSOL and SIMION particle trajectories.

The comparison reports both same-time position differences and same-z transverse
differences.  The latter separates a different longitudinal phase/TOF from a
different geometric ray path.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "config" / "resolved_geometry.json"


TRACE_PATTERN = re.compile(
    r"^TRACE: (?P<particle_id>\d+),(?P<time_us>[-+0-9.eE]+),"
    r"(?P<x_mm>[-+0-9.eE]+),(?P<y_mm>[-+0-9.eE]+),"
    r"(?P<z_mm>[-+0-9.eE]+),(?P<vx_mm_us>[-+0-9.eE]+),"
    r"(?P<vy_mm_us>[-+0-9.eE]+),(?P<vz_mm_us>[-+0-9.eE]+),"
    r"(?P<instance>\d+),(?P<event>\w+)$"
)
CROSSING_PATTERN = re.compile(
    r"^TRACE: detector_crossing ion=(?P<particle_id>\d+) "
    r"t=(?P<time_us>[-+0-9.eE]+) x=(?P<x_mm>[-+0-9.eE]+) "
    r"y=(?P<y_mm>[-+0-9.eE]+) z=(?P<z_mm>[-+0-9.eE]+) "
    r"r=(?P<radius_mm>[-+0-9.eE]+) zmax=(?P<zmax_mm>[-+0-9.eE]+)$"
)


def parse_simion_log(path: Path, particle_ids: set[int]) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    crossings: list[dict[str, float | int | str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = TRACE_PATTERN.match(line)
        if match and int(match["particle_id"]) in particle_ids:
            row: dict[str, float | int | str] = {
                key: float(value)
                for key, value in match.groupdict().items()
                if key not in {"particle_id", "instance", "event"}
            }
            row.update(
                particle_id=int(match["particle_id"]),
                instance=int(match["instance"]),
                event=match["event"],
            )
            rows.append(row)
            continue
        match = CROSSING_PATTERN.match(line)
        if match and int(match["particle_id"]) in particle_ids:
            crossings.append(
                {
                    "particle_id": int(match["particle_id"]),
                    "time_us": float(match["time_us"]),
                    "x_mm": float(match["x_mm"]),
                    "y_mm": float(match["y_mm"]),
                    "z_mm": float(match["z_mm"]),
                    "vx_mm_us": np.nan,
                    "vy_mm_us": np.nan,
                    "vz_mm_us": np.nan,
                    "instance": 4,
                    "event": "detector_crossing",
                    "zmax_mm": float(match["zmax_mm"]),
                }
            )
    if not rows or not crossings:
        raise ValueError(f"Missing selected TRACE rows or detector crossings in {path}")
    frame = pd.concat([pd.DataFrame(rows), pd.DataFrame(crossings)], ignore_index=True)
    return frame.sort_values(["particle_id", "time_us"]).reset_index(drop=True)


def _phase_labels(
    time_us: np.ndarray,
    z_mm: np.ndarray,
    accelerator_exit_z_mm: float,
    reflectron_entrance_z_mm: float,
) -> np.ndarray:
    turn_index = int(np.argmax(z_mm))
    before_turn = np.arange(len(z_mm)) <= turn_index
    phases = np.full(len(z_mm), "reflectron", dtype=object)
    phases[before_turn & (z_mm <= accelerator_exit_z_mm)] = "accelerator"
    phases[before_turn & (z_mm > accelerator_exit_z_mm) & (z_mm < reflectron_entrance_z_mm)] = "outbound_drift"
    phases[(~before_turn) & (z_mm < reflectron_entrance_z_mm) & (z_mm > accelerator_exit_z_mm)] = "return_drift"
    phases[(~before_turn) & (z_mm <= accelerator_exit_z_mm)] = "detector_leg"
    return phases


def _crossing_time(
    time_us: np.ndarray, z_mm: np.ndarray, target_mm: float, direction: int
) -> float:
    delta = z_mm - target_mm
    products = delta[:-1] * delta[1:]
    indices = np.flatnonzero(products <= 0)
    if direction > 0:
        indices = indices[z_mm[indices + 1] >= z_mm[indices]]
    else:
        indices = indices[z_mm[indices + 1] <= z_mm[indices]]
    if not len(indices):
        return float("nan")
    index = int(indices[0] if direction > 0 else indices[-1])
    z0, z1 = z_mm[index : index + 2]
    t0, t1 = time_us[index : index + 2]
    if z1 == z0:
        return float(t0)
    return float(t0 + (target_mm - z0) * (t1 - t0) / (z1 - z0))


def _same_z_transverse(
    simion: pd.DataFrame, comsol: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    output_z: list[np.ndarray] = []
    output_dx: list[np.ndarray] = []
    output_dy: list[np.ndarray] = []
    for before_turn in (True, False):
        sim_turn = int(np.argmax(simion["z_mm"].to_numpy()))
        com_turn = int(np.argmax(comsol["z_mm"].to_numpy()))
        sim = simion.iloc[: sim_turn + 1] if before_turn else simion.iloc[sim_turn:]
        com = comsol.iloc[: com_turn + 1] if before_turn else comsol.iloc[com_turn:]
        com = com.sort_values("z_mm").drop_duplicates("z_mm")
        z = sim["z_mm"].to_numpy()
        valid = (z >= com["z_mm"].min()) & (z <= com["z_mm"].max())
        z = z[valid]
        if not len(z):
            continue
        output_z.append(z)
        output_dx.append(
            sim.loc[sim.index[valid], "x_mm"].to_numpy()
            - np.interp(z, com["z_mm"], com["x_mm"])
        )
        output_dy.append(
            sim.loc[sim.index[valid], "y_mm"].to_numpy()
            - np.interp(z, com["z_mm"], com["y_mm"])
        )
    return np.concatenate(output_z), np.concatenate(output_dx), np.concatenate(output_dy)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("comsol", type=Path)
    parser.add_argument("simion_log", type=Path)
    parser.add_argument("--arrivals", type=Path, required=True)
    parser.add_argument("--particle-ids", default="18,52,97")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    geometry = contract["geometry_mm"]

    particle_ids = [int(value) for value in args.particle_ids.split(",")]
    selected = set(particle_ids)
    comsol = pd.read_csv(args.comsol)
    simion = parse_simion_log(args.simion_log, selected)
    arrivals = pd.read_csv(args.arrivals).set_index("particle_id")
    initial_columns = {"initial_x_mm", "initial_y_mm", "initial_z_mm"}
    if not initial_columns <= set(arrivals.columns):
        raise ValueError(f"Arrival/source CSV misses {sorted(initial_columns)}")
    initial_rows = []
    for particle_id in particle_ids:
        source = arrivals.loc[particle_id]
        initial_rows.append(
            {
                "particle_id": particle_id,
                "time_us": 0.0,
                "x_mm": source["initial_x_mm"],
                "y_mm": source["initial_y_mm"],
                "z_mm": source["initial_z_mm"],
                "vx_mm_us": np.nan,
                "vy_mm_us": np.nan,
                "vz_mm_us": np.nan,
                "instance": 2,
                "event": "initial",
            }
        )
    simion = pd.concat([pd.DataFrame(initial_rows), simion], ignore_index=True)
    simion = simion.sort_values(["particle_id", "time_us"]).reset_index(drop=True)

    metrics: dict[str, object] = {"status": "PASS", "particles": {}}
    merged_outputs: list[pd.DataFrame] = []
    figure, axes = plt.subplots(
        3, len(particle_ids), figsize=(5.2 * len(particle_ids), 11), squeeze=False,
        constrained_layout=True,
    )

    for column, particle_id in enumerate(particle_ids):
        c = comsol[comsol["particle_id"] == particle_id].sort_values("time_us")
        s = simion[simion["particle_id"] == particle_id].sort_values("time_us")
        if c.empty or s.empty:
            raise ValueError(f"Particle {particle_id} is absent from one trajectory source")
        comsol_arrival = float(arrivals.loc[particle_id, "COMSOL_tof_us"])
        simion_arrival = float(arrivals.loc[particle_id, "SIMION_tof_us"])
        common_end = min(comsol_arrival, simion_arrival)
        dynamic = s[s["time_us"] <= common_end].copy()
        for coordinate in ("x_mm", "y_mm", "z_mm"):
            dynamic[f"COMSOL_{coordinate}"] = np.interp(
                dynamic["time_us"], c["time_us"], c[coordinate]
            )
            dynamic[f"delta_{coordinate}"] = (
                dynamic[coordinate] - dynamic[f"COMSOL_{coordinate}"]
            )
        dynamic["same_time_position_error_mm"] = np.sqrt(
            dynamic["delta_x_mm"] ** 2
            + dynamic["delta_y_mm"] ** 2
            + dynamic["delta_z_mm"] ** 2
        )
        dynamic["phase"] = _phase_labels(
            dynamic["time_us"].to_numpy(), dynamic["z_mm"].to_numpy(),
            geometry["accelerator_grid2_z"], geometry["L_flight"]
        )
        merged_outputs.append(dynamic)

        _, same_z_dx, same_z_dy = _same_z_transverse(s, c[c["time_us"] <= comsol_arrival])
        same_z_error = np.sqrt(same_z_dx**2 + same_z_dy**2)
        phase_metrics = {}
        for phase, group in dynamic.groupby("phase", sort=False):
            phase_metrics[str(phase)] = {
                "points": int(len(group)),
                "same_time_position_rms_mm": float(
                    np.sqrt(np.mean(group["same_time_position_error_mm"] ** 2))
                ),
                "same_time_position_max_mm": float(
                    group["same_time_position_error_mm"].max()
                ),
                "same_time_delta_z_mean_mm": float(group["delta_z_mm"].mean()),
            }

        c_dynamic = c[c["time_us"] <= comsol_arrival]
        milestones = {}
        for name, target, direction in (
            ("accelerator_exit_outbound", geometry["accelerator_grid2_z"], 1),
            ("reflectron_entrance_outbound", geometry["L_flight"], 1),
            ("reflectron_entrance_return", geometry["L_flight"], -1),
            ("detector_plane", geometry["detector_z"], -1),
        ):
            c_time = _crossing_time(
                c_dynamic["time_us"].to_numpy(), c_dynamic["z_mm"].to_numpy(),
                target, direction,
            )
            if name == "detector_plane":
                c_time = comsol_arrival
                s_time = simion_arrival
            else:
                s_time = _crossing_time(
                    s["time_us"].to_numpy(), s["z_mm"].to_numpy(), target, direction
                )
            milestones[name] = {
                "COMSOL_time_us": c_time,
                "SIMION_time_us": s_time,
                "SIMION_minus_COMSOL_ns": 1000.0 * (s_time - c_time),
            }

        simion_zmax = float(s["zmax_mm"].dropna().iloc[-1])
        metrics["particles"][str(particle_id)] = {
            "COMSOL_arrival_us": comsol_arrival,
            "SIMION_arrival_us": simion_arrival,
            "arrival_difference_ns": 1000.0 * (simion_arrival - comsol_arrival),
            "COMSOL_zmax_mm": float(c_dynamic["z_mm"].max()),
            "SIMION_zmax_mm": simion_zmax,
            "SIMION_minus_COMSOL_zmax_mm": simion_zmax - float(c_dynamic["z_mm"].max()),
            "same_z_transverse_rms_mm": float(np.sqrt(np.mean(same_z_error**2))),
            "same_z_transverse_max_mm": float(np.max(same_z_error)),
            "same_time_by_phase": phase_metrics,
            "milestones": milestones,
        }

        axes[0, column].plot(c_dynamic["time_us"], c_dynamic["z_mm"], label="COMSOL")
        axes[0, column].scatter(s["time_us"], s["z_mm"], s=10, label="SIMION")
        axes[0, column].set(title=f"Particle {particle_id}: longitudinal phase", xlabel="Time [us]", ylabel="z [mm]")
        axes[1, column].plot(c_dynamic["z_mm"], c_dynamic["x_mm"], label="COMSOL")
        axes[1, column].scatter(s["z_mm"], s["x_mm"], s=10, label="SIMION")
        axes[1, column].set(title="Geometric ray path", xlabel="z [mm]", ylabel="x [mm]")
        axes[2, column].plot(dynamic["time_us"], 1.0e3 * dynamic["delta_z_mm"], label="delta z")
        axes[2, column].plot(
            dynamic["time_us"], 1.0e3 * np.sqrt(dynamic["delta_x_mm"] ** 2 + dynamic["delta_y_mm"] ** 2),
            label="transverse delta",
        )
        axes[2, column].set(title="SIMION - COMSOL at same time", xlabel="Time [us]", ylabel="Difference [um]")
        for row in range(3):
            axes[row, column].grid(True, alpha=0.3)
            axes[row, column].legend()

    args.output.mkdir(parents=True, exist_ok=True)
    pd.concat(merged_outputs, ignore_index=True).to_csv(
        args.output / "trajectory_comparison_samples.csv", index=False
    )
    (args.output / "trajectory_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    figure.savefig(
        args.output / "representative_trajectory_comparison.png", dpi=220,
        facecolor="white",
    )
    plt.close(figure)
    print("TRAJECTORY_COMPARISON_STATUS=PASS")


if __name__ == "__main__":
    main()
