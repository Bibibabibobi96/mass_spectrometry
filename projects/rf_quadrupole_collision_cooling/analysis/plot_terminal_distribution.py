"""Render comparable terminal-position diagnostics for COMSOL and SIMION."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import Circle
from rfquad_contract import load as load_contract


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["event"] == "terminal"]
    rows.sort(key=lambda row: int(row["particle_id"]))
    if not rows or len({int(row["particle_id"]) for row in rows}) != len(rows):
        raise ValueError(f"{path} has missing or duplicate terminal events")
    return rows


def number(row: dict[str, str], key: str) -> float:
    return float(row[key])


def terminal_coordinates(row: dict[str, str]) -> tuple[float, float, float]:
    return (
        number(row, "transverse_x_mm"),
        number(row, "transverse_y_mm"),
        number(row, "axial_z_mm"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comsol-state", type=Path, required=True)
    parser.add_argument("--simion-state", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    inputs = {
        "COMSOL": args.comsol_state,
        "SIMION": args.simion_state,
    }
    resolved, _ = load_contract()
    detector_radius = resolved["geometry_mm"]["detector_radius"]
    plot_limit = max(resolved["geometry_mm"]["field_radius_r0"], detector_radius) * 1.05
    data = {solver: load_rows(path) for solver, path in inputs.items()}
    ids = {
        solver: [int(row["particle_id"]) for row in rows]
        for solver, rows in data.items()
    }
    if ids["COMSOL"] != ids["SIMION"]:
        raise ValueError("COMSOL and SIMION terminal particle IDs differ")
    endpoints = {
        solver: [terminal_coordinates(row) for row in rows]
        for solver, rows in data.items()
    }
    axial = [point[2] for points in endpoints.values() for point in points]
    norm = Normalize(vmin=min(axial), vmax=max(axial))
    cmap = plt.get_cmap("viridis")
    figure, axes = plt.subplots(2, 2, figsize=(11, 9), constrained_layout=True)
    endpoint_axes = [axes[0, 0], axes[0, 1]]

    summary: dict[str, object] = {"detector_radius_mm": detector_radius, "solvers": {}}
    for axis, (solver, rows) in zip(endpoint_axes, data.items(), strict=True):
        points = endpoints[solver]
        transverse_x = [point[0] for point in points]
        transverse_y = [point[1] for point in points]
        terminal_axial = [point[2] for point in points]
        hits = [row["status"] == "transmitted" and row["terminal_reason"] == "acceptance_detector" for row in rows]
        colors = [cmap(norm(value)) for value in terminal_axial]
        for index, (x, y, color, hit) in enumerate(zip(transverse_x, transverse_y, colors, hits), start=1):
            axis.scatter(x, y, s=52, c=[color], marker="o" if hit else "x", linewidths=1.3, zorder=3)
            axis.annotate(str(index), (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7)
        axis.add_patch(Circle((0, 0), detector_radius, fill=False, color="black", linestyle="--", linewidth=1.1))
        axis.axhline(0, color="0.8", linewidth=0.7, zorder=0)
        axis.axvline(0, color="0.8", linewidth=0.7, zorder=0)
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlim(-plot_limit, plot_limit)
        axis.set_ylim(-plot_limit, plot_limit)
        axis.set_title(f"{solver}: terminal transverse position")
        axis.set_xlabel("PA / COMSOL x (mm)")
        axis.set_ylabel("PA / COMSOL y (mm)")
        summary["solvers"][solver] = {
            "particles": len(rows),
            "hits": sum(hits),
            "terminal_axial_min_mm": min(terminal_axial),
            "terminal_axial_max_mm": max(terminal_axial),
            "max_terminal_radius_mm": max((x * x + y * y) ** 0.5 for x, y in zip(transverse_x, transverse_y)),
        }

    comsol_points = endpoints["COMSOL"]
    simion_points = endpoints["SIMION"]
    dx = [c[0] - s[0] for c, s in zip(comsol_points, simion_points, strict=True)]
    dy = [c[1] - s[1] for c, s in zip(comsol_points, simion_points, strict=True)]
    paired_distance = [math.hypot(x, y) for x, y in zip(dx, dy, strict=True)]
    vector_axis = axes[1, 0]
    vector_axis.add_patch(Circle((0, 0), detector_radius, fill=False, color="black", linestyle="--", linewidth=1.1))
    vector_axis.scatter([point[0] for point in simion_points], [point[1] for point in simion_points],
                        c="tab:blue", s=26, label="SIMION terminal", zorder=2)
    vector_axis.quiver([point[0] for point in simion_points], [point[1] for point in simion_points], dx, dy,
                       angles="xy", scale_units="xy", scale=1, color="tab:red", width=0.004, label="SIMION → COMSOL")
    vector_axis.axhline(0, color="0.8", linewidth=0.7, zorder=0)
    vector_axis.axvline(0, color="0.8", linewidth=0.7, zorder=0)
    vector_axis.set(xlim=(-plot_limit, plot_limit), ylim=(-plot_limit, plot_limit), aspect="equal", title="Paired terminal displacement",
                    xlabel="PA / COMSOL x (mm)", ylabel="PA / COMSOL y (mm)")
    vector_axis.legend(loc="upper right")

    error_axis = axes[1, 1]
    particle_ids = [int(row["particle_id"]) for row in data["COMSOL"]]
    error_axis.scatter(particle_ids, paired_distance, color="tab:red", s=34)
    error_axis.plot(particle_ids, paired_distance, color="tab:red", alpha=0.45)
    error_axis.axhline(sum(paired_distance) / len(paired_distance), color="0.3", linestyle="--", label="mean")
    error_axis.set(title="Paired transverse terminal difference", xlabel="fixed particle ID",
                   ylabel="|COMSOL − SIMION| (mm)")
    error_axis.grid(True, alpha=0.3)
    error_axis.legend()

    colorbar = figure.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=endpoint_axes, shrink=0.86)
    colorbar.set_label("terminal axial position, PA / COMSOL z (mm)")
    figure.suptitle("RF quadrupole no-collision terminal diagnostics\n○ detector hit; × non-detector termination; dashed circle = detector aperture")
    summary["comparison"] = {
        "paired_terminal_distance_mean_mm": sum(paired_distance) / len(paired_distance),
        "paired_terminal_distance_max_mm": max(paired_distance),
    }

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"transport_no_collision_terminal_distribution_{args.label}.png"
    summary_path = output_dir / f"transport_no_collision_terminal_distribution_{args.label}.json"
    figure.savefig(image_path, dpi=180)
    plt.close(figure)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"STATUS=PASS IMAGE={image_path} SUMMARY={summary_path}")


if __name__ == "__main__":
    main()
