"""Plot a coordinate-aware loss atlas for the RF-to-oaTOF S1 function chain."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import pandas as pd


TERMINAL_RE = re.compile(
    r"handoff_terminal_raw ion=(\d+) instance=(\d+) instrument_time_us=([-+0-9.eE]+) "
    r"x_mm=([-+0-9.eE]+) y_mm=([-+0-9.eE]+) z_mm=([-+0-9.eE]+)"
)


def parse_terminal_log(path: Path, row_map: pd.DataFrame) -> pd.DataFrame:
    solver_to_particle = dict(zip(row_map["solver_row_index"].astype(int), row_map["particle_id"].astype(int)))
    rows = []
    for match in TERMINAL_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
        solver_index, instance = int(match[1]), int(match[2])
        rows.append({
            "solver_row_index": solver_index,
            "particle_id": solver_to_particle[solver_index],
            "instance": instance,
            "instrument_time_us": float(match[3]),
            "x_mm": float(match[4]), "y_mm": float(match[5]), "z_mm": float(match[6]),
            "detector_hit": instance == 4,
        })
    result = pd.DataFrame(rows)
    if len(result) != len(row_map) or result["particle_id"].nunique() != len(row_map):
        raise ValueError("SIMION terminal log does not contain one state per downstream particle")
    return result


def plot(entry_path: Path, local_path: Path, row_map_path: Path, simion_log: Path,
         output: Path) -> dict[str, int | str]:
    entry = pd.read_csv(entry_path)
    local = pd.read_csv(local_path)
    row_map = pd.read_csv(row_map_path)
    terminals = parse_terminal_log(simion_log, row_map)
    if len(entry) != 100 or len(local) != 100:
        raise ValueError("loss atlas requires the complete N=100 upstream census")
    identities = entry[["frame_id", "clock_epoch_id"]].drop_duplicates()
    if len(identities) != 1 or identities.iloc[0].astype(str).str.strip().eq("").any():
        raise ValueError("loss atlas requires one frame and clock epoch")
    frame_id = str(identities.iloc[0]["frame_id"])
    clock_epoch_id = str(identities.iloc[0]["clock_epoch_id"])
    local_by_id = local.set_index("particle_id")
    entry = entry.copy()
    entry["event"] = entry["particle_id"].map(local_by_id["event"])
    exits = local[local["event"] == "local_joint_exit"].copy()
    fate = terminals.set_index("particle_id")["detector_hit"]
    exits["detector_hit"] = exits["particle_id"].map(fate)
    stopped = local[local["event"] == "terminal"]
    rejected = entry[entry["event"] == "geometric_reject"]
    accepted = entry[entry["event"] != "geometric_reject"]

    hit_color, loss_color, reject_color, exit_color = "#238b45", "#d95f0e", "#636363", "#3182bd"
    figure, axes = plt.subplots(2, 3, figsize=(16, 9.5))

    ax = axes[0, 0]
    ax.scatter(accepted["position_y_mm"], accepted["position_z_mm"], s=24, c=exit_color,
               alpha=0.75, label="inside port (88)")
    ax.scatter(rejected["position_y_mm"], rejected["position_z_mm"], s=38, c=reject_color,
               marker="x", label="geometric reject (12)")
    ax.add_patch(Rectangle((-0.5, -18.42918680341103 - 0.45), 1.0, 0.9, fill=False,
                           color="#54278f", linewidth=2.0, label="1.0 x 0.9 mm port"))
    ax.set(xlabel="y at port (mm)", ylabel="z at port (mm)", title="A  Physical-port acceptance: 100 -> 88")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[0, 1]
    ax.scatter(stopped["x_mm"], stopped["z_mm"], s=28, c=loss_color, marker="x",
               label="local stop (60)")
    ax.scatter(exits["x_mm"], exits["z_mm"], s=25, c=exit_color, label="local exit (28)")
    ax.axvline(-67.8, color="#54278f", linestyle="--", linewidth=1, label="port outer face")
    ax.axhline(4.86981319658897, color="#238b45", linestyle=":", linewidth=1, label="local exit plane")
    ax.set(xlabel="x (mm)", ylabel="z (mm)", title="B  COMSOL local endpoints: 88 -> 28")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[0, 2]
    ax.scatter(stopped["y_mm"], stopped["z_mm"], s=28, c=loss_color, marker="x",
               label="electrode/boundary stop")
    ax.scatter(exits["y_mm"], exits["z_mm"], s=25, c=exit_color, label="local exit")
    ax.axhline(4.86981319658897, color="#238b45", linestyle=":", linewidth=1)
    ax.set(xlabel="y (mm)", ylabel="z (mm)", title="C  Local loss coordinates (y-z)")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[1, 0]
    for is_hit, color, label in ((True, hit_color, "detector hit (9)"),
                                 (False, loss_color, "downstream loss (19)")):
        rows = exits[exits["detector_hit"] == is_hit]
        ax.scatter(rows["x_mm"], rows["y_mm"], s=42, c=color,
                   marker="o" if is_hit else "x", label=label)
    ax.scatter([-48.8], [0], marker="+", s=90, c="black", label="oa axis")
    ax.add_patch(Rectangle((-53.8, -5), 10, 10, fill=False, color="#969696", linestyle="--",
                           label="accelerator bore projection"))
    ax.set(xlabel="x at local exit (mm)", ylabel="y at local exit (mm)",
           title="D  Local-exit position colored by final fate")
    ax.legend(fontsize=8); ax.grid(alpha=0.22); ax.set_aspect("equal", adjustable="datalim")

    ax = axes[1, 1]
    exits["radius_from_oa_axis_mm"] = ((exits["x_mm"] + 48.8) ** 2 + exits["y_mm"] ** 2) ** 0.5
    exits["transverse_speed_m_s"] = (exits["vx_m_s"] ** 2 + exits["vy_m_s"] ** 2) ** 0.5
    for is_hit, color, label in ((True, hit_color, "hit"), (False, loss_color, "lost")):
        rows = exits[exits["detector_hit"] == is_hit]
        ax.scatter(rows["radius_from_oa_axis_mm"], rows["transverse_speed_m_s"], s=42,
                   c=color, marker="o" if is_hit else "x", label=label)
    ax.set(xlabel="radial offset from oa axis at local exit (mm)",
           ylabel="transverse speed sqrt(vx^2+vy^2) (m/s)",
           title="E  Local-exit phase space colored by final fate")
    ax.legend(fontsize=8); ax.grid(alpha=0.22)

    ax = axes[1, 2]
    for is_hit, color, marker, label in ((True, hit_color, "o", "detector instance (9)"),
                                         (False, loss_color, "x", "near flight boundary (19)")):
        rows = terminals[terminals["detector_hit"] == is_hit]
        ax.scatter(rows["x_mm"], rows["y_mm"], s=42, c=color, marker=marker, label=label)
    ax.add_patch(Circle((48.8, 0), 40, fill=False, color="#54278f", linewidth=1.8,
                        label="40 mm detector active radius"))
    ax.scatter([48.8], [0], marker="+", s=90, c="black")
    ax.set(xlabel="terminal x (mm)", ylabel="terminal y (mm)",
           title="F  SIMION terminal x-y projection: 28 -> 9\n"
                 "hits at z≈0; losses at z=-49.929 mm")
    ax.legend(fontsize=8); ax.grid(alpha=0.22); ax.set_aspect("equal", adjustable="datalim")

    figure.suptitle(
        "RF -> oaTOF physical-port loss atlas (N=100, sparse endpoints only)\n"
        f"frame={frame_id}; clock epoch={clock_epoch_id}",
        fontsize=16,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.965))
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, format="png", dpi=190)
    plt.close(figure)
    return {
        "rf_exit": 100, "inside_port": len(accepted), "local_exit": len(exits),
        "detector_hit": int(terminals["detector_hit"].sum()),
        "frame_id": frame_id, "clock_epoch_id": clock_epoch_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--row-map", type=Path, required=True)
    parser.add_argument("--simion-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    counts = plot(args.entry, args.local, args.row_map, args.simion_log, args.output)
    if args.summary is not None:
        result = {
            "schema_version": 1,
            "role": "rf_to_oatof_s1_coordinate_loss_atlas",
            "status": "PASS",
            "frame_id": counts["frame_id"],
            "clock_epoch_id": counts["clock_epoch_id"],
            "counts": counts,
            "panels": [
                "physical_port_yz_acceptance",
                "comsol_local_xz_endpoints",
                "comsol_local_yz_endpoints",
                "local_exit_xy_colored_by_detector_fate",
                "local_exit_radial_phase_space_colored_by_detector_fate",
                "simion_terminal_xy_with_detector_radius",
            ],
            "dense_trajectories_used": False,
            "source_data": "sparse entry, local endpoint, row-map and SIMION terminal events only",
        }
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("S1_LOSS_ATLAS=PASS " + " ".join(f"{key.upper()}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    main()
