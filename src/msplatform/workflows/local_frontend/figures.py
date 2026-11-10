"""Shared-clock local frontend figures from frozen provider geometry.

Actual sections, explicitly labelled projections and terminal anchors remain
distinct; this reader never resolves hardware or propagates ended particles.
"""
from __future__ import annotations

import math
from typing import Any

from msplatform.workflows.single_reflection_flight import checkpoint_diagnostics

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import numpy as np
import pandas as pd


def _local_geometry_sections(frontend: dict[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    """Read frozen provider CSG in MR coordinates; never resolve new hardware.

    Boxes retain their subtractive cutouts. Rods remain circular cylinders;
    their transverse footprints are explicitly projections, not solid slices.
    """
    if frontend.get("native_frame_id") != "mrtof_global_cartesian":
        raise ValueError("local geometry requires frozen MRTOF-native frontend geometry")
    local = frontend["accelerator_local_region"]
    canonical = local["canonical_electrodes"]
    transform = local["accelerator_component"]["transform"]
    rotation = np.asarray(transform["rotation"], dtype=float)
    translation = np.asarray(transform["translation_mm"], dtype=float)
    if rotation.shape != (3, 3) or translation.shape != (3,) or not np.all(np.isfinite(rotation)) or not np.all(np.isfinite(translation)):
        raise ValueError("finite frozen accelerator transform required")
    # Current providers use signed axis permutations; enclosing boxes would be
    # scientifically wrong for a freely rotated electrode.
    if not np.allclose(np.abs(rotation).sum(axis=0), 1) or not np.allclose(np.abs(rotation).sum(axis=1), 1) or not np.all(np.isclose(rotation, 0) | np.isclose(np.abs(rotation), 1)):
        raise ValueError("geometry sections require an axis-aligned provider pose")

    def box(center, widths):
        return {f"{a}_{side}_mm": float(center[i]) + sign * float(widths[i]) / 2
                for i, a in enumerate("xyz") for side, sign in (("min", -1), ("max", 1))}

    def world(raw):
        corners = np.array([[raw[f"x_{a}_mm"], raw[f"y_{b}_mm"], raw[f"z_{c}_mm"]]
                            for a in ("min", "max") for b in ("min", "max") for c in ("min", "max")])
        mapped = corners @ rotation.T + translation
        if not np.all(np.isfinite(mapped)):
            raise ValueError("nonfinite frozen geometry box")
        return np.stack((mapped.min(axis=0), mapped.max(axis=0)))

    solids = []
    def add(name, raw, holes=()):
        solids.append(dict(name=name, bounds=world(raw), holes=[world(h) for h in holes]))

    if canonical["coordinate_frame"] == "sectioned_accelerator_cartesian":
        g = canonical["geometry"]
        if g["cross_section"] != "square":
            raise ValueError("cylindrical OA needs a section renderer; square CSG cannot substitute")
        center = [g["axis_x_mm"], g["axis_y_mm"], g["shield_center_z_mm"]]
        outer = box(center, [g["shield_outer_width_mm"]] * 2 + [g["shield_span_z_mm"]])
        cavity = box(center, [g["shield_inner_width_mm"]] * 2 + [g["shield_span_z_mm"]])
        wall = g["shield_wall_mm"]
        port = box([g["negative_x_face_mm"] + wall/2, g["port_center_y_mm"], g["port_center_z_mm"]],
                   [wall, g["numerical_port_width_mm"], g["numerical_port_height_mm"]])
        add("Shield", outer, [cavity, port])
        add("Shield", box([center[0], center[1], g["shield_back_z_mm"] + wall/2],
                          [g["shield_outer_width_mm"]] * 2 + [wall]))
        for z in g["ring_z_mm"]:
            add("Rings", box([center[0], center[1], z], [g["electrode_width_mm"]]*2 + [g["ring_thickness_mm"]]),
                [box([center[0], center[1], z], [g["bore_width_mm"]]*2 + [g["ring_thickness_mm"]])])
        sheets = [(sheet["name"], world(sheet["sheet_box_mm"])) for sheet in canonical["ideal_sheets"]]
    elif canonical["coordinate_frame"] == "accelerator_centered_transverse_local_z_mm":
        enclosure = canonical["grounded_enclosure"]
        entry = enclosure["side_entry"]
        center = entry["center_mm"]
        port = box(center, [2*entry["half_width_x_mm"],
                           enclosure["outer_box_mm"]["y_max_mm"]-enclosure["outer_box_mm"]["y_min_mm"],
                           2*entry["half_width_z_mm"]])
        # The side aperture removes the entry wall only, not its opposite wall.
        port["y_min_mm"] = enclosure["outer_box_mm"]["y_min_mm"]
        port["y_max_mm"] = enclosure["cavity_box_mm"]["y_min_mm"]
        add("Shield", enclosure["outer_box_mm"], [enclosure["cavity_box_mm"], enclosure["exit_opening_box_mm"], port])
        sheets = []
        for support in canonical["grid_supports"]:
            add("Grid supports", support["frame_outer_box_mm"], [support["aperture_box_mm"]])
            sheet = support["ideal_sheet_mm"]
            sheets.append(("Ideal grid", world({**sheet, "z_min_mm": sheet["z_mm"], "z_max_mm": sheet["z_mm"]})))
        for ring in canonical["rings"]:
            add("Rings", ring["outer_box_mm"], [ring["aperture_box_mm"]])
    else:
        raise ValueError("unsupported frozen canonical electrode geometry")
    add("Repeller", canonical["repeller"]["solid_box_mm"])
    guide = frontend["guide_contract"]["rod_array"]["rods"]
    pose = frontend["guide_registration"]
    gr = np.asarray(pose["rotation_upstream_to_downstream"], dtype=float)
    gt = np.asarray(pose["translation_mm"], dtype=float)
    if gr.shape != (3, 3) or not np.allclose(gr[:, 2], [0, 1, 0]) or not np.allclose(gr @ gr.T, np.eye(3)):
        raise ValueError("frozen rods must be circular cylinders along native +y")
    rods = [dict(start=gr @ np.array([r["center_x_mm"], r["center_y_mm"], r["z_min_mm"]]) + gt,
                 stop=gr @ np.array([r["center_x_mm"], r["center_y_mm"], r["z_max_mm"]]) + gt,
                 radius=float(r["radius_mm"]), rod_id=r["physical_electrode_id"]) for r in guide]
    if not rods or any(r["radius"] <= 0 for r in rods):
        raise ValueError("positive-radius frozen rods required")
    return solids, [dict(name=n, bounds=b) for n, b in sheets], rods


def _draw_local_geometry(ax, solids, sheets, rods, transverse, cut):
    """Draw OA central CSG sections plus declared orthographic rod footprints."""
    index, omitted = (0, 1) if transverse == "x" else (1, 0)
    colors = {"Shield": "#B5B5B5", "Repeller": "#D55E00", "Rings": "#8AA9BA", "Grid supports": "#8AA9BA"}
    seen = set()
    for solid in solids:
        bounds = solid["bounds"]
        if not bounds[0, omitted] <= cut <= bounds[1, omitted]:
            continue
        pieces = [(bounds[0, 2], bounds[1, 2], bounds[0, index], bounds[1, index])]
        for hole in solid["holes"]:
            if not hole[0, omitted] <= cut <= hole[1, omitted]:
                continue
            updated = []
            for x0, x1, y0, y1 in pieces:
                a, b = max(x0, hole[0, 2]), min(x1, hole[1, 2])
                c, d = max(y0, hole[0, index]), min(y1, hole[1, index])
                if a >= b or c >= d:
                    updated.append((x0, x1, y0, y1))
                else:
                    updated.extend([(x0, a, y0, y1), (b, x1, y0, y1), (a, b, y0, c), (a, b, d, y1)])
            pieces = updated
        for x0, x1, y0, y1 in pieces:
            if x1 <= x0 or y1 <= y0:
                continue
            label = solid["name"] if solid["name"] not in seen else None
            patch = Rectangle((x0, y0), x1-x0, y1-y0, facecolor=colors[solid["name"]], edgecolor="#606060", linewidth=.45, label=label, zorder=1)
            patch.set_gid("local_geometry_" + solid["name"].lower().replace(" ", "_"))
            ax.add_patch(patch)
            seen.add(solid["name"])
    for sheet in sheets:
        b = sheet["bounds"]
        line, = ax.plot([b[0, 2], b[1, 2]], [b[0, index], b[1, index]], color="#6B4C9A", lw=1,
                        label="Ideal transparent grids" if "grid" not in seen else None, zorder=2)
        line.set_gid("local_geometry_grid_" + sheet["name"])
        seen.add("grid")
    for number, rod in enumerate(rods):
        a, b, radius = rod["start"], rod["stop"], rod["radius"]
        kwargs = dict(facecolor="#E4B66E", edgecolor="#B08038", linewidth=.5, alpha=.3, zorder=.5,
                      label="Rod projections" if number == 0 else None)
        patch = (Circle((a[2], a[0]), radius, **kwargs) if transverse == "x" else
                 Rectangle((a[2]-radius, a[1]), 2*radius, b[1]-a[1], **kwargs))
        patch.set_gid(f"local_geometry_projected_rod_{rod['rod_id']}")
        ax.add_patch(patch)
    ax.text(.02, .02, f"OA section: {'y' if transverse == 'x' else 'x'} = {cut:g} mm\nParticles and rods: projections",
            transform=ax.transAxes, fontsize=7, va="bottom", zorder=11,
            bbox=dict(facecolor="white", edgecolor="none", alpha=.8))


def build_local_shared_time_figure(
    active_rows: pd.DataFrame, status_counts: list[dict[str, Any]], *, frame_id: str,
    frontend_contract: dict[str, Any], terminal_rows: pd.DataFrame,
) -> tuple[plt.Figure, np.ndarray]:
    """Display active states and cumulative actual terminal anchors with geometry.

    This is a coordinate scatter, not a field or trajectory interpolation.
    Its caller declares the observer frame and any display-time subset.
    """
    if frontend_contract.get("conditioner_contract") is not None:
        raise ValueError("conditioner/cooled analysis has been withdrawn")
    if not frame_id or not status_counts:
        raise ValueError("shared-time figure requires a frame and declared time panels")
    if frame_id != "mrtof_global_cartesian":
        raise ValueError("local geometry and particles must share the native MRTOF frame")
    terminal_classes = {
        "exit": ("#00845A", "s", "Exited (last position)"),
        "native_stop_unresolved": ("#B42532", "x", "Splat / native stop (cause unresolved)"),
        "timeout": ("#000000", "+", "Timeout (last position)"),
    }
    if not terminal_rows.empty:
        if not set(terminal_rows["terminal_class"]) <= set(terminal_classes):
            raise ValueError("unknown local terminal class")
        if terminal_rows["particle_id"].duplicated().any() or not np.isfinite(
            terminal_rows[["instrument_time_us", "x_mm", "y_mm", "z_mm"]].to_numpy(dtype=float)
        ).all():
            raise ValueError("terminal markers require unique IDs and finite actual states")
    solids, sheets, rods = _local_geometry_sections(frontend_contract)
    local = frontend_contract["accelerator_local_region"]
    center = local.get("axis_center_mm", local["accelerator_component"]["transform"]["translation_mm"])
    figure, axes = plt.subplots(2, len(status_counts), figsize=(3.5 * len(status_counts), 6.2),
                                squeeze=False, sharex=True, sharey="row", constrained_layout=True)
    for column, counts in enumerate(status_counts):
        time = float(counts["instrument_time_us"])
        # Census validates the actual clock against this declared target; retain
        # the native clock and state while grouping by its requested observation.
        rows = active_rows.loc[active_rows["requested_time_us"].eq(time)]
        if len(rows) != counts["active"]:
            raise ValueError("shared-time plotted population differs from the census")
        # Match the census's existing 32-ULP serialization allowance. Markers
        # retain the original terminal coordinates; they are not propagated.
        terminal = terminal_rows if terminal_rows.empty else terminal_rows.loc[
            terminal_rows["instrument_time_us"].map(
                lambda end: time >= end or abs(time-end) <= 32*math.ulp(max(1., abs(time), abs(end)))
            )
        ]
        for ax, transverse in zip(axes[:, column], ("x", "y"), strict=True):
            cut_mm = center[1 if transverse == "x" else 0]
            _draw_local_geometry(ax, solids, sheets, rods, transverse, cut_mm)
            if len(rows):
                ax.scatter(rows["z_mm"], rows[f"{transverse}_mm"], s=checkpoint_diagnostics.marker_area(len(rows)),
                           color="#0069A8", marker="o", zorder=10, label="Still flying")
            else:
                ax.text(.5, .5, "No active particles", transform=ax.transAxes, ha="center")
            for kind, (color, marker, label) in terminal_classes.items():
                stopped = terminal if terminal.empty else terminal.loc[terminal["terminal_class"].eq(kind)]
                if len(stopped):
                    artist = ax.scatter(stopped["z_mm"], stopped[f"{transverse}_mm"], s=24,
                                        color=color, marker=marker, linewidths=.8, zorder=12,
                                        facecolors="none" if kind == "exit" else color, label=label)
                    artist.set_gid("local_terminal_" + kind)
            ax.set(xlabel=f"{frame_id}: z (mm)", ylabel=f"{frame_id}: {transverse} (mm)")
            ax.set_aspect("auto")
            ax.grid(alpha=.15)
        axes[0, column].set_title(f"t = {time:.6g} us; active N={counts['active']}\n"
            f"Not born {counts['not_born']}; exited {counts['already_exit']}\n"
            f"Non-exit terminal {counts['already_loss']}; unsupported {counts['numerical_unsupported']}", fontsize=9)
    for ax in axes.flat:
        ax.autoscale_view()
        ax.margins(.04)
    legend = {}
    for ax in [a for panel in axes.flat for a in (panel, *panel.child_axes)]:
        handles, labels = ax.get_legend_handles_labels()
        legend.update(zip(labels, handles))
    figure.legend(legend.values(), legend.keys(), loc="outside lower center", ncol=4, fontsize=8)
    figure.suptitle("Shared-clock distributions with actual component geometry; common axis limits\n"
                    "Display aspect ratio only; terminal markers are cumulative last positions, not flying particles")
    return figure, axes
