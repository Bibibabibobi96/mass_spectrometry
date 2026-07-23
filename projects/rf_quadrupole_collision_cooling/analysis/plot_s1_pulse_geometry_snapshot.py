"""Plot the standard parameterized RF-to-oaTOF state at pulse onset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd


def accelerator_geometry(baseline: dict, joint: dict) -> dict[str, object]:
    geometry = baseline["geometry_mm"]
    source = baseline["particle_source"]
    rings = baseline["rings"]
    port = joint["port_sweep"]

    center_x = float(baseline["coordinate_convention"]["accelerator_axis_x"])
    bore_half = float(geometry["accelerator_bore_half"])
    ring_outer_half = bore_half + float(geometry["accelerator_ring_width"])
    shield_inner_half = ring_outer_half + float(geometry["accelerator_insulation_gap"])
    shield_wall = float(geometry["accelerator_shield_wall"])
    shield_outer_half = shield_inner_half + shield_wall
    repeller_z = float(geometry["accelerator_repeller_z"])
    grid1_z = float(geometry["accelerator_grid1_z"])
    grid2_z = float(geometry["accelerator_grid2_z"])
    repeller_thickness = float(geometry["accelerator_repeller_thickness"])
    ring_thickness = float(geometry["accelerator_ring_thickness"])
    rear_clearance = float(geometry["accelerator_rear_clearance"])
    ring_count = int(rings["accelerator_count"])
    ring_centers = [grid1_z + k * (grid2_z - grid1_z) / (ring_count + 1)
                    for k in range(1, ring_count + 1)]

    return {
        "center_x": center_x,
        "bore_half": bore_half,
        "ring_outer_half": ring_outer_half,
        "shield_inner_half": shield_inner_half,
        "shield_outer_half": shield_outer_half,
        "shield_wall": shield_wall,
        "shield_z_min": repeller_z - repeller_thickness - rear_clearance - shield_wall,
        "shield_bore_z_min": repeller_z - repeller_thickness - rear_clearance,
        "shield_z_max": grid2_z,
        "repeller_z": repeller_z,
        "repeller_thickness": repeller_thickness,
        "grid1_z": grid1_z,
        "grid2_z": grid2_z,
        "grid1_half": ring_outer_half,
        "grid2_half": shield_inner_half,
        "ring_thickness": ring_thickness,
        "ring_centers_z": ring_centers,
        "port_center_z": float(port["center_z_mm"]),
        "port_width_y": float(port["selected_n100_candidate_full_width_y_mm"]),
        "port_height_z": float(port["full_height_z_mm"]),
        "source_center": {axis: float(source[f"center_{axis}_mm"]) for axis in "xyz"},
        "source_size": {axis: float(source[f"size_{axis}_mm"]) for axis in "xyz"},
    }


def _filled_rect(ax, xy, width, height, **kwargs) -> None:
    ax.add_patch(Rectangle(xy, width, height, **kwargs))


def particle_marker_areas(snapshot_rows: int) -> dict[str, float]:
    """Return point areas that remain readable for N=100 and denser snapshots."""
    scale = min(1.0, np.sqrt(100.0 / max(snapshot_rows, 1)))
    return {"active": 16.0 * scale, "port_loss": 18.0 * scale,
            "accelerator_loss": 28.0 * scale}


def classify_snapshot(capture: pd.DataFrame, events: pd.DataFrame,
                      geometry: dict[str, object]) -> pd.DataFrame:
    required = {"particle_id", "event", "status", "terminal_reason"}
    if not required.issubset(events.columns):
        raise ValueError("particle event table is missing terminal-classification columns")
    classified = capture.merge(events[list(required)], on="particle_id", how="left",
                               validate="one_to_one")
    if classified[["event", "status", "terminal_reason"]].isna().any().any():
        raise ValueError("pulse snapshot particle IDs are not a subset of the event table")
    cx = float(geometry["center_x"])
    outer_face = cx - float(geometry["shield_outer_half"])
    inner_face = cx - float(geometry["shield_inner_half"])
    y_edge_distance = (classified["y_mm"].abs() - float(geometry["port_width_y"]) / 2).abs()
    z_low = float(geometry["port_center_z"]) - float(geometry["port_height_z"]) / 2
    z_high = float(geometry["port_center_z"]) + float(geometry["port_height_z"]) / 2
    z_edge_distance = np.minimum((classified["z_mm"] - z_low).abs(),
                                 (classified["z_mm"] - z_high).abs())
    tolerance_mm = 1e-8
    legacy_port_loss = (
        classified["status"].eq("lost")
        & classified["terminal_reason"].eq("electrode_or_boundary")
        & classified["x_mm"].between(outer_face - tolerance_mm, inner_face + tolerance_mm)
        & (np.minimum(y_edge_distance, z_edge_distance) <= tolerance_mm)
    )
    if "active_at_pulse" in classified:
        classified["active_at_pulse"] = pd.to_numeric(
            classified["active_at_pulse"], errors="raise").astype(bool)
        inactive = ~classified["active_at_pulse"]
        classified["frozen_port_loss_before_pulse"] = inactive & (
            classified["event"].eq("downstream_entry_wall") | legacy_port_loss)
    else:
        classified["frozen_port_loss_before_pulse"] = legacy_port_loss
    dx = (classified["x_mm"] - cx).abs()
    ay = classified["y_mm"].abs()
    terminal_wall_loss = (
        classified["status"].eq("lost")
        & classified["terminal_reason"].eq("electrode_or_boundary")
    )
    repeller_hit = (
        (classified["z_mm"] - float(geometry["repeller_z"])).abs() <= tolerance_mm
    ) & (dx <= float(geometry["ring_outer_half"]) + tolerance_mm) & (
        ay <= float(geometry["ring_outer_half"]) + tolerance_mm
    )
    grid_hit = pd.Series(False, index=classified.index)
    for name in ("grid1", "grid2"):
        grid_hit |= (
            (classified["z_mm"] - float(geometry[f"{name}_z"])).abs() <= tolerance_mm
        ) & (dx <= float(geometry[f"{name}_half"]) + tolerance_mm) & (
            ay <= float(geometry[f"{name}_half"]) + tolerance_mm
        )
    ring_hit = pd.Series(False, index=classified.index)
    square_radius = np.maximum(dx, ay)
    for ring_z in geometry["ring_centers_z"]:
        ring_hit |= (
            (classified["z_mm"] - float(ring_z)).abs()
            <= float(geometry["ring_thickness"]) / 2 + tolerance_mm
        ) & (square_radius >= float(geometry["bore_half"]) - tolerance_mm) & (
            square_radius <= float(geometry["ring_outer_half"]) + tolerance_mm
        )
    legacy_accelerator_loss = (
        terminal_wall_loss & ~classified["frozen_port_loss_before_pulse"]
        & (repeller_hit | grid_hit | ring_hit))
    if "active_at_pulse" in classified:
        classified["frozen_accelerator_loss_before_pulse"] = inactive & (
            classified["terminal_reason"].eq("accelerator_electrode_or_boundary")
            | legacy_accelerator_loss)
    else:
        classified["frozen_accelerator_loss_before_pulse"] = legacy_accelerator_loss
        classified["active_at_pulse"] = ~(
            classified["frozen_port_loss_before_pulse"]
            | classified["frozen_accelerator_loss_before_pulse"])
    return classified


def add_sparse_loss_positions(capture: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Add one terminal loss position when S3 stores only active pulse states."""
    required = {"active_at_pulse", "x_mm", "y_mm", "z_mm"}
    if not required.issubset(events.columns):
        return capture
    missing = events[~events["particle_id"].isin(capture["particle_id"])].copy()
    if missing.empty:
        return capture
    inactive = pd.to_numeric(missing["active_at_pulse"], errors="raise").astype(bool)
    missing = missing[~inactive].copy()
    if missing.empty:
        return capture
    pulse_time = float(capture["instrument_time_us"].iloc[0])
    additions = pd.DataFrame(index=missing.index, columns=capture.columns)
    additions["particle_id"] = missing["particle_id"]
    additions["instrument_time_us"] = pulse_time
    for coordinate in ("x_mm", "y_mm", "z_mm"):
        additions[coordinate] = missing[coordinate]
    if "inside_oatof_ideal_reference_volume" in additions:
        additions["inside_oatof_ideal_reference_volume"] = False
    if "active_at_pulse" in additions:
        additions["active_at_pulse"] = False
    return pd.concat([capture, additions], ignore_index=True)


def plot_snapshot(capture_path: Path, events_path: Path, baseline_path: Path, joint_path: Path,
                  figure_path: Path, metadata_path: Path) -> dict[str, object]:
    capture = pd.read_csv(capture_path)
    events = pd.read_csv(events_path)
    required = {
        "particle_id", "frame_id", "clock_epoch_id", "instrument_time_us",
        "x_mm", "y_mm", "z_mm",
    }
    if not required.issubset(capture.columns):
        raise ValueError("pulse capture table is missing required position columns")
    if capture.empty or capture["instrument_time_us"].nunique() != 1:
        raise ValueError("standard pulse snapshot requires one non-empty shared-time state")
    identities = capture[["frame_id", "clock_epoch_id"]].drop_duplicates()
    if len(identities) != 1 or identities.iloc[0].astype(str).str.strip().eq("").any():
        raise ValueError("standard pulse snapshot requires one frame and clock epoch")
    frame_id = str(identities.iloc[0]["frame_id"])
    clock_epoch_id = str(identities.iloc[0]["clock_epoch_id"])
    capture = add_sparse_loss_positions(capture, events)

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    joint = json.loads(joint_path.read_text(encoding="utf-8"))
    g = accelerator_geometry(baseline, joint)
    capture = classify_snapshot(capture, events, g)
    active = capture[capture["active_at_pulse"]]
    frozen_port_loss = capture[capture["frozen_port_loss_before_pulse"]]
    frozen_accelerator_loss = capture[
        capture["frozen_accelerator_loss_before_pulse"]]
    cx = g["center_x"]
    inner = g["shield_inner_half"]
    outer = g["shield_outer_half"]
    wall = g["shield_wall"]
    zmin = g["shield_z_min"]
    zmax = g["shield_z_max"]
    port_z0 = g["port_center_z"] - g["port_height_z"] / 2
    port_y0 = -g["port_width_y"] / 2

    shield_color = "#bdbdbd"
    electrode_color = "#3182bd"
    grid_color = "#31a354"
    ion_color = "#d95f0e"
    ideal_color = "#756bb1"
    marker_areas = particle_marker_areas(len(capture))

    fig, (ax_xz, ax_xy) = plt.subplots(1, 2, figsize=(15.5, 7.2))

    # x-z projection: grounded shield, integrated rear cap, physical port,
    # repeller, two grids and five square-annular graded electrodes.
    shield_height = zmax - zmin
    _filled_rect(ax_xz, (cx - outer, zmin), wall, shield_height,
                 facecolor=shield_color, edgecolor="#636363", alpha=0.75, zorder=1)
    _filled_rect(ax_xz, (cx + inner, zmin), wall, shield_height,
                 facecolor=shield_color, edgecolor="#636363", alpha=0.75, zorder=1)
    _filled_rect(ax_xz, (cx - inner, zmin), 2 * inner, wall,
                 facecolor=shield_color, edgecolor="#636363", alpha=0.75, zorder=1)
    _filled_rect(ax_xz, (cx - outer, port_z0), wall, g["port_height_z"],
                 facecolor="white", edgecolor="#cb181d", linewidth=1.8, zorder=4)

    ring_left_x = cx - g["ring_outer_half"]
    ring_side_width = g["ring_outer_half"] - g["bore_half"]
    for ring_z in g["ring_centers_z"]:
        for ring_x in (ring_left_x, cx + g["bore_half"]):
            _filled_rect(ax_xz, (ring_x, ring_z - g["ring_thickness"] / 2),
                         ring_side_width, g["ring_thickness"], facecolor=electrode_color,
                         edgecolor="#08519c", alpha=0.62, zorder=2)
    _filled_rect(ax_xz, (cx - g["ring_outer_half"],
                         g["repeller_z"] - g["repeller_thickness"]),
                 2 * g["ring_outer_half"], g["repeller_thickness"],
                 facecolor=electrode_color, edgecolor="#08519c", alpha=0.7, zorder=2)
    for grid_z, grid_half, label in (
        (g["grid1_z"], g["grid1_half"], "grid1"),
        (g["grid2_z"], g["grid2_half"], "grid2"),
    ):
        ax_xz.plot([cx - grid_half, cx + grid_half], [grid_z, grid_z], color=grid_color,
                   linewidth=1.5, linestyle="-.", zorder=2)
        ax_xz.text(cx + grid_half + 0.35, grid_z, label, va="center", fontsize=8,
                   color="#006d2c")

    source_center = g["source_center"]
    source_size = g["source_size"]
    _filled_rect(ax_xz,
                 (source_center["x"] - source_size["x"] / 2,
                  source_center["z"] - source_size["z"] / 2),
                 source_size["x"], source_size["z"], fill=False, edgecolor=ideal_color,
                 linewidth=2.0, linestyle="--", zorder=5)
    ax_xz.scatter(active["x_mm"], active["z_mm"], s=marker_areas["active"], c=ion_color,
                  edgecolors="white", linewidths=0.35, alpha=0.85, zorder=6)
    ax_xz.scatter(frozen_port_loss["x_mm"], frozen_port_loss["z_mm"],
                  s=marker_areas["port_loss"], c="#cb181d", marker="x",
                  linewidths=0.8, alpha=0.75, zorder=7)
    ax_xz.scatter(frozen_accelerator_loss["x_mm"],
                  frozen_accelerator_loss["z_mm"], s=marker_areas["accelerator_loss"],
                  c="#252525", marker="X", linewidths=0.55, alpha=0.9, zorder=8)
    ax_xz.annotate(f"physical port\n{g['port_width_y']:.3g} y × {g['port_height_z']:.3g} z mm",
                   xy=(cx - outer + wall / 2, g["port_center_z"]),
                   xytext=(cx - outer + 2.0, g["port_center_z"] + 3.1),
                   arrowprops={"arrowstyle": "->", "color": "#cb181d"}, fontsize=9)
    ax_xz.set(xlabel="RF injection axis, x (mm)", ylabel="oa acceleration axis, z (mm)",
              title="A  Injection–acceleration plane (x–z)")

    # x-y projection. All five rings share the same square-annular envelope.
    for xy, width, height in (
        ((cx - outer, -outer), 2 * outer, wall),
        ((cx - outer, inner), 2 * outer, wall),
        ((cx - outer, -inner), wall, 2 * inner),
        ((cx + inner, -inner), wall, 2 * inner),
    ):
        _filled_rect(ax_xy, xy, width, height, facecolor=shield_color,
                     edgecolor="#636363", alpha=0.75, zorder=1)
    _filled_rect(ax_xy, (cx - outer, port_y0), wall, g["port_width_y"],
                 facecolor="white", edgecolor="#cb181d", linewidth=1.8, zorder=4)
    _filled_rect(ax_xy, (cx - g["ring_outer_half"], -g["ring_outer_half"]),
                 2 * g["ring_outer_half"], 2 * g["ring_outer_half"], fill=False,
                 edgecolor=electrode_color, linewidth=2.0, zorder=2)
    _filled_rect(ax_xy, (cx - g["bore_half"], -g["bore_half"]),
                 2 * g["bore_half"], 2 * g["bore_half"], fill=False,
                 edgecolor=electrode_color, linewidth=1.5, linestyle="-", zorder=2)
    _filled_rect(ax_xy,
                 (source_center["x"] - source_size["x"] / 2,
                  source_center["y"] - source_size["y"] / 2),
                 source_size["x"], source_size["y"], fill=False, edgecolor=ideal_color,
                 linewidth=2.0, linestyle="--", zorder=5)
    ax_xy.scatter(active["x_mm"], active["y_mm"], s=marker_areas["active"], c=ion_color,
                  edgecolors="white", linewidths=0.35, alpha=0.85, zorder=6)
    ax_xy.scatter(frozen_port_loss["x_mm"], frozen_port_loss["y_mm"],
                  s=marker_areas["port_loss"], c="#cb181d", marker="x",
                  linewidths=0.8, alpha=0.75, zorder=7)
    ax_xy.scatter(frozen_accelerator_loss["x_mm"],
                  frozen_accelerator_loss["y_mm"], s=marker_areas["accelerator_loss"],
                  c="#252525", marker="X", linewidths=0.55, alpha=0.9, zorder=8)
    ax_xy.annotate(f"physical port\n{g['port_width_y']:.3g} y × {g['port_height_z']:.3g} z mm",
                   xy=(cx - outer + wall / 2, 0.0), xytext=(cx - outer + 2.0, 3.0),
                   arrowprops={"arrowstyle": "->", "color": "#cb181d"}, fontsize=9)
    ax_xy.text(cx, g["ring_outer_half"] + 0.6,
               f"projection of {len(g['ring_centers_z'])} graded ring electrodes",
               ha="center", va="bottom", fontsize=8, color="#08519c")
    ax_xy.set(xlabel="RF injection axis, x (mm)", ylabel="transverse axis, y (mm)",
              title="B  Injection cross-plane (x–y)")

    xmin = min(float(capture["x_mm"].min()), cx - outer) - 1.5
    xmax = max(float(capture["x_mm"].max()), cx + outer) + 1.5
    ax_xz.set_xlim(xmin, xmax)
    ax_xy.set_xlim(xmin, xmax)
    ax_xz.set_ylim(zmin - 1.5, zmax + 1.5)
    ax_xy.set_ylim(-outer - 1.5, outer + 1.5)
    for ax in (ax_xz, ax_xy):
        ax.set_aspect("equal", adjustable="box")
        ax.grid(alpha=0.18)

    legend = [
        Line2D([], [], marker="o", linestyle="None", markerfacecolor=ion_color,
               markeredgecolor="white", label="ions immediately before pulse"),
        Line2D([], [], marker="x", linestyle="None", color="#cb181d",
               label="pre-pulse port-wall loss"),
        Line2D([], [], marker="X", linestyle="None", color="#252525",
               label="pre-pulse accelerator loss"),
        Rectangle((0, 0), 1, 1, facecolor=shield_color, edgecolor="#636363",
                  alpha=0.75, label="grounded accelerator shield"),
        Rectangle((0, 0), 1, 1, fill=False, edgecolor=electrode_color,
                  linewidth=2, label="accelerator electrode projection"),
        Line2D([], [], color=grid_color, linestyle="-.", label="grid electrode"),
        Rectangle((0, 0), 1, 1, fill=False, edgecolor=ideal_color,
                  linestyle="--", linewidth=2, label="ideal source bounds"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=4, frameon=False, fontsize=9)
    pulse_time = float(capture["instrument_time_us"].iloc[0])
    fig.suptitle(f"RF-to-oaTOF state immediately before shared pulse: "
                 f"t = {pulse_time:.6f} µs (left limit), active = {len(active)} "
                 f"(port loss = {len(frozen_port_loss)}, accelerator loss = "
                 f"{len(frozen_accelerator_loss)})\n"
                 f"frame={frame_id}; clock epoch={clock_epoch_id}", fontsize=14)
    fig.tight_layout(rect=(0, 0.1, 1, 0.94))
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, format="png", dpi=190)
    plt.close(fig)

    metadata = {
        "schema_version": 1,
        "role": "rf_to_oatof_standard_pulse_geometry_snapshot",
        "status": "PASS",
        "pulse_instrument_time_us": pulse_time,
        "frame_id": frame_id,
        "clock_epoch_id": clock_epoch_id,
        "state_time_semantics": "left_limit_immediately_before_pulse_t_pulse_minus",
        "state_continuity_note": "Position and velocity are continuous at the finite field step; frozen pre-pulse losses are classified separately and plotted, but excluded from the active cohort.",
        "snapshot_rows": int(len(capture)),
        "particles_active_at_pulse": int(len(active)),
        "frozen_port_losses_before_pulse": int(len(frozen_port_loss)),
        "frozen_accelerator_losses_before_pulse": int(len(frozen_accelerator_loss)),
        "frozen_loss_positions_plotted_separately": True,
        "active_inside_ideal_reference_volume": int(pd.to_numeric(
            active.get("inside_oatof_ideal_reference_volume", pd.Series(dtype=int)),
            errors="coerce").fillna(0).astype(bool).sum()),
        "planes": ["x-z injection-acceleration", "x-y injection-cross-plane"],
        "geometry_sources": {
            "accelerator": str(baseline_path),
            "physical_port": str(joint_path),
        },
        "geometry_mm": g,
        "plot_style": {
            "particle_marker_area_pt2": marker_areas,
            "marker_scaling_rule": "base_area_times_min(1,sqrt(100/snapshot_rows))",
        },
        "dense_trajectories_saved": False,
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--oatof-baseline", type=Path, required=True)
    parser.add_argument("--joint-contract", type=Path, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    result = plot_snapshot(args.capture, args.events, args.oatof_baseline, args.joint_contract,
                           args.figure, args.metadata)
    print(f"S1_PULSE_GEOMETRY_SNAPSHOT=PASS ACTIVE={result['particles_active_at_pulse']} "
          f"PORT_LOSS={result['frozen_port_losses_before_pulse']} "
          f"ACCELERATOR_LOSS={result['frozen_accelerator_losses_before_pulse']}")


if __name__ == "__main__":
    main()
