"""Plot six governed spatial snapshots from one continuous RF-to-oaTOF flight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import pandas as pd


CAPABILITY_ID = "rf_oatof_single_flight_spatial_six_panel_v1"


def marker_area(particle_count: int) -> float:
    """Keep N=1000 clouds legible without hiding geometry or source bounds."""

    return max(2.0, min(10.0, 44.0 / max(particle_count, 1) ** 0.5))


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def _event(checkpoints: pd.DataFrame, name: str) -> pd.DataFrame:
    return checkpoints.loc[checkpoints["event"].eq(name)].copy()


def _cloud(ax: plt.Axes, rows: pd.DataFrame, x: str, y: str, *, size: float,
           label: str, color: str = "#2166ac") -> None:
    if not rows.empty:
        ax.scatter(rows[x], rows[y], s=size, color=color, alpha=0.48,
                   edgecolors="none", label=f"{label} (N={len(rows)})", zorder=3)


def _rod_cross_section(ax: plt.Axes, upstream: dict[str, Any], center_z: float) -> None:
    for rod in upstream["geometry_mm"]["rod_array"]["rods"]:
        # Canonical registration maps upstream local x->global y and y->global z.
        patch = Circle((float(rod["center_x_mm"]), center_z + float(rod["center_y_mm"])),
                       float(rod["radius_mm"]), facecolor="#d9d9d9",
                       edgecolor="#252525", linewidth=0.8, zorder=6)
        ax.add_patch(patch)


def _multipole_longitudinal(ax: plt.Axes, upstream: dict[str, Any],
                            initial: pd.DataFrame, center_z: float) -> None:
    source_x = float(initial["position_x_mm"].median())
    rod_length = float(upstream["geometry_mm"]["rod_length"])
    rod_start = source_x + 1.5
    rod_end = rod_start + rod_length
    radius = float(upstream["geometry_mm"]["rod_radius"])
    centers = sorted({round(center_z + float(rod["center_y_mm"]), 12)
                      for rod in upstream["geometry_mm"]["rod_array"]["rods"]})
    for zc in centers:
        ax.add_patch(Rectangle((rod_start, zc-radius), rod_length, 2*radius,
                               facecolor="#d9d9d9", edgecolor="#252525",
                               linewidth=0.65, alpha=0.7, zorder=6))
    enclosure = upstream["geometry_mm"]["enclosure"]
    shield_radius = float(enclosure["shield_inner_radius_mm"])
    ax.plot([source_x-1.0, rod_end+2.5], [center_z-shield_radius]*2,
            color="#525252", linewidth=1.0, zorder=7)
    ax.plot([source_x-1.0, rod_end+2.5], [center_z+shield_radius]*2,
            color="#525252", linewidth=1.0, zorder=7)


def _accelerator(ax: plt.Axes, oatof: dict[str, Any]) -> None:
    geometry = oatof["geometry_mm"]
    center_x = float(oatof["coordinate_convention"]["accelerator_axis_x"])
    width = 2 * (float(geometry["accelerator_bore_half"]) +
                 float(geometry["accelerator_ring_width"]))
    zs = [float(geometry["accelerator_repeller_z"]),
          float(geometry["accelerator_grid1_z"])]
    count = int(oatof["rings"]["accelerator_count"])
    pitch = (float(geometry["accelerator_grid2_z"])-zs[1])/(count+1)
    zs.extend(zs[1] + index*pitch for index in range(1, count+1))
    zs.append(float(geometry["accelerator_grid2_z"]))
    for index, z_value in enumerate(zs):
        style = "--" if index in {1, len(zs)-1} else "-"
        ax.plot([center_x-width/2, center_x+width/2], [z_value, z_value],
                color="#252525", linewidth=0.8, linestyle=style, zorder=7)


def build_figure(initial: pd.DataFrame, checkpoints: pd.DataFrame,
                 upstream: dict[str, Any], frontend: dict[str, Any],
                 oatof: dict[str, Any]) -> tuple[plt.Figure, dict[str, int | float]]:
    required = {"particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm"}
    if missing := sorted(required-set(checkpoints.columns)):
        raise ValueError(f"checkpoint columns are missing: {', '.join(missing)}")
    if initial.empty or initial["particle_id"].duplicated().any():
        raise ValueError("initial global state must contain unique particles")
    size = marker_area(len(initial))
    handoff = _event(checkpoints, "multipole_handoff")
    prepulse = _event(checkpoints, "pre_pulse_state")
    accelerator_exit = _event(checkpoints, "local_accelerator_exit")
    detector = _event(checkpoints, "detector_crossing")
    center_z = float(frontend["source_exit_center_mm"]["z"])

    figure, axes = plt.subplots(2, 3, figsize=(16.0, 9.4), constrained_layout=True)
    ax_a, ax_b, ax_c, ax_d, ax_e, ax_f = axes.flat

    _rod_cross_section(ax_a, upstream, center_z)
    _cloud(ax_a, initial, "position_y_mm", "position_z_mm", size=size,
           label="released ions", color="#2b8cbe")
    # The frozen mother sample is defined on a 1 x 1 mm transverse source face.
    ax_a.add_patch(Rectangle((-0.5, center_z-0.5), 1.0, 1.0, fill=False,
                             edgecolor="#d7301f", linewidth=1.4, linestyle="--",
                             label="ideal source 1×1 mm", zorder=9))
    ax_a.set_aspect("equal", adjustable="box")
    ax_a.set(title="A  Ion release and octupole cross-section",
             xlabel="global y (mm)", ylabel="global z (mm)")

    _multipole_longitudinal(ax_b, upstream, initial, center_z)
    _cloud(ax_b, initial, "position_x_mm", "position_z_mm", size=size,
           label="released ions", color="#2b8cbe")
    ax_b.set(title="B  Release plane inside grounded multipole enclosure",
             xlabel="global x (mm)", ylabel="global z (mm)")

    aperture = frontend["aperture"]
    _cloud(ax_c, handoff, "y_mm", "z_mm", size=size, label="multipole handoff",
           color="#1b9e77")
    ax_c.add_patch(Rectangle((-float(aperture["width_mm"])/2,
                              center_z-float(aperture["height_mm"])/2),
                             float(aperture["width_mm"]), float(aperture["height_mm"]),
                             fill=False, edgecolor="#d7301f", linewidth=1.4,
                             label=(f'{float(aperture["width_mm"]):g}×'
                                    f'{float(aperture["height_mm"]):g} mm aperture'),
                             zorder=9))
    ax_c.set_aspect("equal", adjustable="box")
    ax_c.set(title="C  Grounded connector / oaTOF entrance handoff",
             xlabel="global y (mm)", ylabel="global z (mm)")

    _accelerator(ax_d, oatof)
    _cloud(ax_d, prepulse, "x_mm", "z_mm", size=size,
           label="immediately before pulse", color="#fdae61")
    ax_d.set(title="D  Ion distribution in accelerator before pulse",
             xlabel="global x (mm)", ylabel="global z (mm)")

    _cloud(ax_e, accelerator_exit, "x_mm", "y_mm", size=size,
           label="local accelerator exit", color="#756bb1")
    bore = float(oatof["geometry_mm"]["accelerator_exit_grid_half_width"])
    accelerator_axis_x = float(oatof["coordinate_convention"]["accelerator_axis_x"])
    ax_e.add_patch(Rectangle((accelerator_axis_x-bore, -bore), 2*bore, 2*bore, fill=False,
                             edgecolor="#252525", linewidth=1.0, zorder=8))
    ax_e.set_aspect("equal", adjustable="box")
    ax_e.set(title="E  Local accelerator exit plane",
             xlabel="global x (mm)", ylabel="global y (mm)")

    _cloud(ax_f, detector, "x_mm", "y_mm", size=size,
           label="detector crossings", color="#238b45")
    detector_center = float(oatof["coordinate_convention"]["detector_x"])
    detector_radius = float(oatof["geometry_mm"]["detector_radius"])
    ax_f.add_patch(Circle((detector_center, 0.0), detector_radius, fill=False,
                          edgecolor="#252525", linewidth=1.0, zorder=8))
    ax_f.set_aspect("equal", adjustable="box")
    ax_f.set(title="F  Detector active plane", xlabel="global x (mm)", ylabel="global y (mm)")

    for ax in axes.flat:
        ax.grid(alpha=0.16, zorder=0)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, fontsize=7, loc="best", frameon=False)
    figure.suptitle(
        "Continuous octupole → grounded connector → oaTOF spatial checkpoints\n"
        f"small markers preserve geometry visibility; capability={CAPABILITY_ID}",
        fontsize=12,
    )
    return figure, {
        "released": len(initial), "handoff": len(handoff),
        "pre_pulse": len(prepulse), "accelerator_exit": len(accelerator_exit),
        "detector": len(detector), "particle_marker_area_pt2": size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", required=True, type=Path)
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--frontend", required=True, type=Path)
    parser.add_argument("--oatof", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    figure, counts = build_figure(
        pd.read_csv(args.initial), pd.read_csv(args.checkpoints), _load(args.upstream),
        _load(args.frontend), _load(args.oatof),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=190)
    plt.close(figure)
    args.metadata.write_text(json.dumps({
        "schema_version": 1, "role": "rf_oatof_single_flight_spatial_six_panel_metadata",
        "capability_id": CAPABILITY_ID, "status": "success", "counts": counts,
        "figure": str(args.output.resolve()),
    }, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_SIX_PANEL=PASS FIGURE={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
