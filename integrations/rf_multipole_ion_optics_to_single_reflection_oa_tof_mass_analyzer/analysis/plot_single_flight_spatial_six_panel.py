"""Plot six governed spatial snapshots from one continuous RF-to-oaTOF flight."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath
from matplotlib.patches import Circle, PathPatch, Rectangle
from matplotlib.ticker import MultipleLocator
import numpy as np
import pandas as pd


CAPABILITY_ID = "rf_oatof_single_flight_spatial_six_panel_v2"
PHASE_SPACE_CAPABILITY_ID = "rf_oatof_accelerator_pre_pulse_phase_space_v1"
GEOMETRY_TARGET_TICK_INTERVALS = 9


def _rectangular_frame_path(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    open_positive_y: bool = False,
) -> MplPath:
    """Build one solid rectangular frame with a clean inner-vacuum hole."""

    outer_x, outer_y, outer_width, outer_height = outer
    inner_x, inner_y, inner_width, inner_height = inner
    values = (*outer, *inner)
    if (
        not all(math.isfinite(value) for value in values)
        or min(outer_width, outer_height, inner_width, inner_height) <= 0
        or inner_x < outer_x
        or inner_y < outer_y
        or inner_x + inner_width > outer_x + outer_width
        or inner_y + inner_height > outer_y + outer_height
    ):
        raise ValueError("rectangular frame geometry is invalid")
    if open_positive_y:
        if abs(inner_y + inner_height - (outer_y + outer_height)) > 1e-9:
            raise ValueError("open rectangular frame must share its positive-y edge")
        vertices = (
            (outer_x, outer_y + outer_height),
            (outer_x, outer_y),
            (outer_x + outer_width, outer_y),
            (outer_x + outer_width, outer_y + outer_height),
            (inner_x + inner_width, inner_y + inner_height),
            (inner_x + inner_width, inner_y),
            (inner_x, inner_y),
            (inner_x, inner_y + inner_height),
            (outer_x, outer_y + outer_height),
        )
        return MplPath(
            vertices,
            [MplPath.MOVETO] + [MplPath.LINETO] * 7 + [MplPath.CLOSEPOLY],
        )
    outer_vertices = (
        (outer_x, outer_y),
        (outer_x + outer_width, outer_y),
        (outer_x + outer_width, outer_y + outer_height),
        (outer_x, outer_y + outer_height),
        (outer_x, outer_y),
    )
    # Reverse the inner contour so the nonzero fill rule leaves one clean hole.
    inner_vertices = (
        (inner_x, inner_y),
        (inner_x, inner_y + inner_height),
        (inner_x + inner_width, inner_y + inner_height),
        (inner_x + inner_width, inner_y),
        (inner_x, inner_y),
    )
    codes = [
        MplPath.MOVETO,
        MplPath.LINETO,
        MplPath.LINETO,
        MplPath.LINETO,
        MplPath.CLOSEPOLY,
    ] * 2
    return MplPath([*outer_vertices, *inner_vertices], codes)


def _apply_shared_nice_ticks(axes: tuple[plt.Axes, ...]) -> float:
    """Use one geometry-derived nice tick interval on every supplied axis."""

    if not axes:
        raise ValueError("at least one geometry axis is required")
    spans = [
        upper - lower
        for ax in axes
        for lower, upper in (ax.get_xlim(), ax.get_ylim())
    ]
    if not all(math.isfinite(span) and span > 0 for span in spans):
        raise ValueError("geometry display spans are invalid")
    raw_step = max(spans) / GEOMETRY_TARGET_TICK_INTERVALS
    exponent = math.floor(math.log10(raw_step))
    candidates = [
        multiplier * 10.0 ** candidate_exponent
        for candidate_exponent in (exponent - 1, exponent, exponent + 1)
        for multiplier in (1.0, 2.0, 2.5, 5.0, 10.0)
    ]
    step = min(candidates, key=lambda candidate: (abs(candidate - raw_step), candidate))
    for ax in axes:
        ax.xaxis.set_major_locator(MultipleLocator(step))
        ax.yaxis.set_major_locator(MultipleLocator(step))
    return step


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


def _cloud(
    ax: plt.Axes, rows: pd.DataFrame, x: str, y: str, *, size: float, label: str, color: str = "#2166ac"
) -> None:
    if not rows.empty:
        ax.scatter(
            rows[x],
            rows[y],
            s=size,
            color=color,
            alpha=0.48,
            edgecolors="none",
            label=f"{label} (N={len(rows)})",
            zorder=3,
        )


def _rod_cross_section(ax: plt.Axes, upstream: dict[str, Any], center_z: float) -> None:
    for rod in upstream["geometry_mm"]["rod_array"]["rods"]:
        # Canonical registration maps upstream local x->global y and y->global z.
        patch = Circle(
            (float(rod["center_x_mm"]), center_z + float(rod["center_y_mm"])),
            float(rod["radius_mm"]),
            facecolor="#d9d9d9",
            edgecolor="#252525",
            linewidth=0.8,
            zorder=6,
        )
        ax.add_patch(patch)


def _multipole_longitudinal(ax: plt.Axes, upstream: dict[str, Any], initial: pd.DataFrame, center_z: float) -> None:
    source_x = float(initial["position_x_mm"].median())
    rod_length = float(upstream["geometry_mm"]["rod_length"])
    rod_start = source_x + 1.5
    rod_end = rod_start + rod_length
    radius = float(upstream["geometry_mm"]["rod_radius"])
    centers = sorted(
        {round(center_z + float(rod["center_y_mm"]), 12) for rod in upstream["geometry_mm"]["rod_array"]["rods"]}
    )
    for zc in centers:
        ax.add_patch(
            Rectangle(
                (rod_start, zc - radius),
                rod_length,
                2 * radius,
                facecolor="#d9d9d9",
                edgecolor="#252525",
                linewidth=0.65,
                alpha=0.7,
                zorder=6,
            )
        )
    enclosure = upstream["geometry_mm"]["enclosure"]
    shield_radius = float(enclosure["shield_inner_radius_mm"])
    ax.plot([source_x - 1.0, rod_end + 2.5], [center_z - shield_radius] * 2, color="#525252", linewidth=1.0, zorder=7)
    ax.plot([source_x - 1.0, rod_end + 2.5], [center_z + shield_radius] * 2, color="#525252", linewidth=1.0, zorder=7)


def _accelerator(ax: plt.Axes, oatof: dict[str, Any], frontend: dict[str, Any]) -> None:
    geometry = oatof["geometry_mm"]
    center_x = float(oatof["coordinate_convention"]["accelerator_axis_x"])
    shield = _accelerator_shield_geometry(oatof, frontend)
    bore_half = float(geometry["accelerator_bore_half"])
    ring_width = float(geometry["accelerator_ring_width"])
    outer_half = bore_half + ring_width
    ring_thickness = float(geometry["accelerator_ring_thickness"])
    repeller = _repeller_body_geometry(oatof, frontend)
    repeller_thickness = repeller["thickness"]
    boundary_planes = _accelerator_boundary_planes(oatof, frontend)
    if min(bore_half, ring_width, ring_thickness, repeller_thickness) <= 0:
        raise ValueError("accelerator electrode dimensions must be positive")
    shield_path = _rectangular_frame_path(
        (
            shield["outer_x_min"],
            shield["outer_z_min"],
            shield["outer_width"],
            shield["outer_z_max"] - shield["outer_z_min"],
        ),
        (
            shield["inner_x_min"],
            shield["inner_z_min"],
            shield["inner_width"],
            shield["outer_z_max"] - shield["inner_z_min"],
        ),
        open_positive_y=True,
    )
    ax.add_patch(
        PathPatch(
            shield_path,
            facecolor="#d9d9d9",
            edgecolor="#525252",
            linewidth=1.0,
            linestyle="-",
            alpha=0.42,
            label="accelerator shield body",
            zorder=1,
        )
    )
    port = _connector_through_hole_geometry(oatof, frontend)
    ax.add_patch(
        Rectangle(
            (port["x_min"], port["z_min"]), port["wall"], port["height"],
            facecolor="white", edgecolor="#009E73", linewidth=1.3,
            alpha=0.62, label="connector through-hole", zorder=2.5,
        )
    )
    topology = oatof.get("accelerator_topology")
    if topology is None:
        grid1_z = float(geometry["accelerator_grid1_z"])
        count = int(oatof["rings"]["accelerator_count"])
        exit_z = float(geometry["accelerator_grid2_z"])
        pitch = (exit_z - grid1_z) / (count + 1)
        rings = [grid1_z + index * pitch for index in range(1, count + 1)]
    else:
        topology_id = str(topology["topology_id"])
        if frontend.get("accelerator_topology_id") != topology_id:
            raise ValueError("frontend and resolved accelerator topology differ")
        planes = topology["planes_global_z_mm"]
        if set(planes) != {"repeller", "intermediate1", "intermediate2", "exit"}:
            raise ValueError("three-zone accelerator planes are incomplete")
        rings = frontend["accelerator_local_region"].get("ring_z_mm")
        if not isinstance(rings, list) or len(rings) != int(oatof["rings"]["accelerator_count"]):
            raise ValueError("three-zone accelerator ring positions are incomplete")
        rings = [float(z_value) for z_value in rings]
    ax.add_patch(
        Rectangle(
            (center_x - outer_half, repeller["z_min"]),
            2 * outer_half,
            repeller_thickness,
            facecolor="#bdbdbd",
            edgecolor="#252525",
            linewidth=0.8,
            alpha=0.72,
            label="repeller body",
            zorder=6,
        )
    )
    for ring_index, z_value in enumerate(rings):
        for side_index, x_min in enumerate((center_x - outer_half, center_x + bore_half)):
            ax.add_patch(
                Rectangle(
                    (x_min, z_value - ring_thickness / 2),
                    ring_width,
                    ring_thickness,
                    facecolor="#bdbdbd",
                    edgecolor="#252525",
                    linewidth=0.8,
                    alpha=0.72,
                    label=(
                        "shaping ring body (inner/outer width)"
                        if ring_index == 0 and side_index == 0
                        else None
                    ),
                    zorder=6,
                )
            )
    for z_value, half_width in boundary_planes:
        ax.plot(
            [center_x - half_width, center_x + half_width],
            [z_value, z_value],
            color="#252525",
            linewidth=0.8,
            linestyle="--",
            zorder=7,
        )


def _accelerator_shield_geometry(
    oatof: dict[str, Any], frontend: dict[str, Any]
) -> dict[str, float]:
    """Resolve the plotted shield from the frozen frontend solid contract."""

    local = frontend["accelerator_local_region"]
    center_x = float(local["axis_x_mm"])
    center_y = float(local["axis_y_mm"])
    center_z = float(local["shield_center_z_mm"])
    outer_width = float(local["shield_outer_width_mm"])
    inner_width = float(local["shield_inner_width_mm"])
    span_z = float(local["shield_span_z_mm"])
    wall = float(local["shield_wall_mm"])
    outer_x_min = float(local["negative_x_face_mm"])
    outer_z_min = float(local["shield_back_z_mm"])
    outer_z_max = float(local["grid2_z_mm"])
    checks = (
        abs(center_x - float(oatof["coordinate_convention"]["accelerator_axis_x"])),
        abs(center_y),
        abs(wall - float(oatof["geometry_mm"]["accelerator_shield_wall"])),
        abs(outer_width - inner_width - 2 * wall),
        abs(outer_x_min - (center_x - outer_width / 2)),
        abs(center_z - (outer_z_min + outer_z_max) / 2),
        abs(span_z - (outer_z_max - outer_z_min)),
    )
    if min(outer_width, inner_width, span_z, wall) <= 0 or any(
        error > 1e-9 for error in checks
    ):
        raise ValueError("frontend accelerator shield geometry is inconsistent")
    return {
        "center_y": center_y,
        "outer_width": outer_width,
        "inner_width": inner_width,
        "wall": wall,
        "outer_x_min": outer_x_min,
        "inner_x_min": center_x - inner_width / 2,
        "outer_y_min": center_y - outer_width / 2,
        "inner_y_min": center_y - inner_width / 2,
        "outer_z_min": outer_z_min,
        "inner_z_min": outer_z_min + wall,
        "outer_z_max": outer_z_max,
    }


def _repeller_body_geometry(
    oatof: dict[str, Any], frontend: dict[str, Any]
) -> dict[str, float]:
    """Resolve a front-face repeller solid, extending away from accelerator vacuum."""

    local = frontend["accelerator_local_region"]
    front = float(local["repeller_front_z_mm"])
    thickness = float(local["repeller_thickness_mm"])
    grid1 = float(local["grid1_z_mm"])
    topology = oatof.get("accelerator_topology")
    if topology is None:
        expected_front = float(oatof["geometry_mm"]["accelerator_repeller_z"])
        expected_grid1 = float(oatof["geometry_mm"]["accelerator_grid1_z"])
    else:
        planes = topology["planes_global_z_mm"]
        expected_front = float(planes["repeller"])
        expected_grid1 = float(planes["intermediate1"])
    expected_thickness = float(
        oatof["geometry_mm"]["accelerator_repeller_thickness"]
    )
    vacuum_direction = math.copysign(1.0, grid1 - front) if grid1 != front else 0.0
    if (
        thickness <= 0
        or vacuum_direction == 0
        or abs(front - expected_front) > 1e-9
        or abs(grid1 - expected_grid1) > 1e-9
        or abs(thickness - expected_thickness) > 1e-9
    ):
        raise ValueError("frontend repeller face geometry is inconsistent")
    body_other_face = front - vacuum_direction * thickness
    return {
        "front_z": front,
        "thickness": thickness,
        "vacuum_direction": vacuum_direction,
        "z_min": min(front, body_other_face),
        "z_max": max(front, body_other_face),
    }


def _accelerator_boundary_planes(
    oatof: dict[str, Any], frontend: dict[str, Any]
) -> list[tuple[float, float]]:
    """Return each ideal grid plane with its separately governed half width."""

    geometry = oatof["geometry_mm"]
    local = frontend["accelerator_local_region"]
    electrode_width = float(local["electrode_width_mm"])
    expected_electrode_width = 2 * (
        float(geometry["accelerator_bore_half"])
        + float(geometry["accelerator_ring_width"])
    )
    exit_half_width = float(geometry["accelerator_exit_grid_half_width"])
    topology = oatof.get("accelerator_topology")
    if topology is None:
        expected = [
            (float(geometry["accelerator_grid1_z"]), electrode_width / 2),
            (float(geometry["accelerator_grid2_z"]), exit_half_width),
        ]
        observed_z = [float(local["grid1_z_mm"]), float(local["grid2_z_mm"])]
    else:
        planes = topology["planes_global_z_mm"]
        expected = [
            (float(planes["intermediate1"]), electrode_width / 2),
            (float(planes["intermediate2"]), electrode_width / 2),
            (float(planes["exit"]), exit_half_width),
        ]
        observed_z = [
            float(local["grid1_z_mm"]),
            float(local["intermediate2_z_mm"]),
            float(local["grid2_z_mm"]),
        ]
    if (
        not math.isfinite(electrode_width)
        or not math.isfinite(exit_half_width)
        or min(electrode_width, exit_half_width) <= 0
        or abs(electrode_width - expected_electrode_width) > 1e-9
        or any(abs(observed - plane[0]) > 1e-9 for observed, plane in zip(observed_z, expected))
    ):
        raise ValueError("frontend accelerator boundary-plane geometry is inconsistent")
    return expected


def _connector_through_hole_geometry(
    oatof: dict[str, Any], frontend: dict[str, Any]
) -> dict[str, float]:
    """Resolve the negative-x wall opening from the frozen frontend GEM contract."""

    local = frontend["accelerator_local_region"]
    source_exit = frontend["source_exit_center_mm"]
    shield = _accelerator_shield_geometry(oatof, frontend)
    values = {
        "x_min": float(local["negative_x_face_mm"]),
        "wall": float(local["shield_wall_mm"]),
        "center_y": float(local["port_center_y_mm"]),
        "center_z": float(local["port_center_z_mm"]),
        "width": float(local["numerical_port_width_mm"]),
        "height": float(local["numerical_port_height_mm"]),
    }
    if not all(math.isfinite(value) for value in values.values()) or min(
        values["wall"], values["width"], values["height"]
    ) <= 0:
        raise ValueError("connector through-hole geometry is invalid")
    x_max = values["x_min"] + values["wall"]
    y_min = values["center_y"] - values["width"] / 2
    y_max = values["center_y"] + values["width"] / 2
    z_min = values["center_z"] - values["height"] / 2
    z_max = values["center_z"] + values["height"] / 2
    outer_y_max = shield["outer_y_min"] + shield["outer_width"]
    checks = (
        abs(values["x_min"] - shield["outer_x_min"]),
        abs(x_max - shield["inner_x_min"]),
        abs(values["center_y"] - float(source_exit["y"])),
        abs(values["center_z"] - float(source_exit["z"])),
        abs(values["x_min"] - float(source_exit["x"])),
    )
    if (
        any(error > 1e-9 for error in checks)
        or y_min < shield["outer_y_min"] - 1e-9
        or y_max > outer_y_max + 1e-9
        or z_min < shield["outer_z_min"] - 1e-9
        or z_max > shield["outer_z_max"] + 1e-9
    ):
        raise ValueError("connector through-hole differs from the shield wall")
    return values | {"x_max": x_max, "y_min": y_min, "z_min": z_min}


def _accelerator_cross_section(
    ax: plt.Axes, oatof: dict[str, Any], frontend: dict[str, Any]
) -> None:
    geometry = oatof["geometry_mm"]
    center_x = float(oatof["coordinate_convention"]["accelerator_axis_x"])
    shield = _accelerator_shield_geometry(oatof, frontend)
    bore_half = float(geometry["accelerator_bore_half"])
    outer_half = bore_half + float(geometry["accelerator_ring_width"])
    exit_grid_half = float(geometry["accelerator_exit_grid_half_width"])
    shield_path = _rectangular_frame_path(
        (
            shield["outer_x_min"], shield["outer_y_min"],
            shield["outer_width"], shield["outer_width"],
        ),
        (
            shield["inner_x_min"], shield["inner_y_min"],
            shield["inner_width"], shield["inner_width"],
        ),
    )
    ax.add_patch(
        PathPatch(
            shield_path,
            facecolor="#d9d9d9",
            edgecolor="#525252",
            linewidth=1.2,
            linestyle="-",
            alpha=0.42,
            label="accelerator shield body",
            zorder=1,
        )
    )
    port = _connector_through_hole_geometry(oatof, frontend)
    ax.add_patch(
        Rectangle(
            (port["x_min"], port["y_min"]), port["wall"], port["width"],
            facecolor="white", edgecolor="#009E73", linewidth=1.3,
            alpha=0.62, label="connector through-hole", zorder=2.5,
        )
    )
    ring_width = outer_half - bore_half
    if ring_width <= 0:
        raise ValueError("accelerator shaping-ring projection is invalid")
    ring_path = _rectangular_frame_path(
        (center_x - outer_half, -outer_half, 2 * outer_half, 2 * outer_half),
        (center_x - bore_half, -bore_half, 2 * bore_half, 2 * bore_half),
    )
    ax.add_patch(
        PathPatch(
            ring_path,
            facecolor="#bdbdbd",
            edgecolor="#252525",
            linewidth=0.8,
            alpha=0.72,
            label="shaping ring body (inner/outer width)",
            zorder=8,
        )
    )
    ax.add_patch(
        Rectangle(
            (center_x - exit_grid_half, -exit_grid_half),
            2 * exit_grid_half, 2 * exit_grid_half,
            fill=False, edgecolor="#252525", linewidth=0.9,
            linestyle=":", label="exit-grid extent", zorder=9,
        )
    )


def _source_region_bounds(
    diagnostic: dict[str, Any],
) -> dict[str, dict[str, float | str | None]]:
    """Validate the analyzer-resolved default source-region diagnostic bounds."""

    bounds = diagnostic.get("bounds")
    if (
        diagnostic.get("role") != "layout_resolved_source_region_diagnostic"
        or diagnostic.get("claim_status") != "PROVISIONAL_DIAGNOSTIC_ONLY"
        or diagnostic.get("event") != "pre_pulse_state"
        or diagnostic.get("population_basis") != "pulse_eligible"
        or diagnostic.get("selection_uses_detector_outcome") is not False
        or not isinstance(bounds, dict)
        or set(bounds) != {"x", "y", "z"}
    ):
        raise ValueError("source-region diagnostic identity is invalid")
    for axis in ("x", "y", "z"):
        bound = bounds[axis]
        if not isinstance(bound, dict):
            raise ValueError("source-region diagnostic bound is invalid")
        values = [
            float(bound[name])
            for name in ("center_mm", "full_width_mm", "minimum_mm", "maximum_mm")
        ]
        center, width, minimum, maximum = values
        if (
            not all(math.isfinite(value) for value in values)
            or width <= 0
            or abs(minimum - (center - width / 2)) > 1e-9
            or abs(maximum - (center + width / 2)) > 1e-9
        ):
            raise ValueError("source-region diagnostic bound is invalid")
        if bound.get("center_binding") != f"particle_source.center_{axis}_mm":
            raise ValueError("source-region diagnostic center binding is invalid")
        expected_width_binding = "particle_source.size_z_mm" if axis == "z" else None
        if bound.get("full_width_binding") != expected_width_binding:
            raise ValueError("source-region diagnostic width binding is invalid")
    return bounds


def _source_region_longitudinal(
    ax: plt.Axes,
    diagnostic: dict[str, Any],
    oatof: dict[str, Any],
    frontend: dict[str, Any],
) -> None:
    bounds = _source_region_bounds(diagnostic)
    x_bound, z_bound = bounds["x"], bounds["z"]
    repeller = _repeller_body_geometry(oatof, frontend)
    source_min = float(z_bound["minimum_mm"])
    source_max = float(z_bound["maximum_mm"])
    vacuum_clearance = (
        source_min - repeller["front_z"]
        if repeller["vacuum_direction"] > 0
        else repeller["front_z"] - source_max
    )
    if vacuum_clearance < -1e-9:
        raise ValueError("ideal-source interval overlaps the repeller body")
    ax.add_patch(
        Rectangle(
            (float(x_bound["minimum_mm"]), float(z_bound["minimum_mm"])),
            float(x_bound["full_width_mm"]), float(z_bound["full_width_mm"]),
            facecolor="#56B4E9", edgecolor="#0072B2", linewidth=1.2,
            linestyle=":", alpha=0.25,
            label=(
                f"layout-resolved axial interval; provisional "
                f"{float(x_bound['full_width_mm']):g} mm transverse"
            ),
            zorder=2,
        )
    )


def _source_region_cross_section(
    ax: plt.Axes, diagnostic: dict[str, Any]
) -> None:
    bounds = _source_region_bounds(diagnostic)
    x_bound, y_bound = bounds["x"], bounds["y"]
    ax.add_patch(
        Rectangle(
            (float(x_bound["minimum_mm"]), float(y_bound["minimum_mm"])),
            float(x_bound["full_width_mm"]), float(y_bound["full_width_mm"]),
            facecolor="#56B4E9", edgecolor="#0072B2",
            linewidth=1.2, linestyle=":", alpha=0.25,
            label="provisional transverse source reference region",
            zorder=2,
        )
    )


def build_figure(
    initial: pd.DataFrame,
    checkpoints: pd.DataFrame,
    upstream: dict[str, Any],
    frontend: dict[str, Any],
    oatof: dict[str, Any],
    source_region_diagnostic: dict[str, Any],
) -> tuple[plt.Figure, dict[str, Any]]:
    required = {"particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm"}
    if missing := sorted(required - set(checkpoints.columns)):
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
    _cloud(ax_a, initial, "position_y_mm", "position_z_mm", size=size, label="released ions", color="#2b8cbe")
    # The frozen mother sample is defined on a 1 x 1 mm transverse source face.
    ax_a.add_patch(
        Rectangle(
            (-0.5, center_z - 0.5),
            1.0,
            1.0,
            fill=False,
            edgecolor="#d7301f",
            linewidth=1.4,
            linestyle="--",
            label="ideal source 1×1 mm",
            zorder=9,
        )
    )
    ax_a.set_aspect("equal", adjustable="box")
    ax_a.set(title="A  Ion release and octupole cross-section", xlabel="global y (mm)", ylabel="global z (mm)")

    _multipole_longitudinal(ax_b, upstream, initial, center_z)
    _cloud(ax_b, initial, "position_x_mm", "position_z_mm", size=size, label="released ions", color="#2b8cbe")
    ax_b.set(
        title="B  Release plane inside grounded multipole enclosure", xlabel="global x (mm)", ylabel="global z (mm)"
    )

    aperture = frontend["aperture"]
    _cloud(ax_c, handoff, "y_mm", "z_mm", size=size, label="multipole handoff", color="#1b9e77")
    ax_c.add_patch(
        Rectangle(
            (-float(aperture["width_mm"]) / 2, center_z - float(aperture["height_mm"]) / 2),
            float(aperture["width_mm"]),
            float(aperture["height_mm"]),
            fill=False,
            edgecolor="#d7301f",
            linewidth=1.4,
            label=(f"{float(aperture['width_mm']):g}×{float(aperture['height_mm']):g} mm aperture"),
            zorder=9,
        )
    )
    ax_c.set_aspect("equal", adjustable="box")
    ax_c.set(title="C  Grounded connector / oaTOF entrance handoff", xlabel="global y (mm)", ylabel="global z (mm)")

    _accelerator(ax_d, oatof, frontend)
    _source_region_longitudinal(ax_d, source_region_diagnostic, oatof, frontend)
    _cloud(ax_d, prepulse, "x_mm", "z_mm", size=size, label="immediately before pulse", color="#fdae61")
    ax_d.set_aspect("equal", adjustable="box")
    ax_d.set(title="D  Ion distribution in accelerator before pulse", xlabel="global x (mm)", ylabel="global z (mm)")

    _cloud(ax_e, accelerator_exit, "x_mm", "y_mm", size=size, label="local accelerator exit", color="#756bb1")
    _accelerator_cross_section(ax_e, oatof, frontend)
    _source_region_cross_section(ax_e, source_region_diagnostic)
    shared_tick_step = _apply_shared_nice_ticks((ax_d, ax_e))
    ax_e.set_aspect("equal", adjustable="box")
    ax_e.set(title="E  Local accelerator exit plane", xlabel="global x (mm)", ylabel="global y (mm)")

    _cloud(ax_f, detector, "x_mm", "y_mm", size=size, label="detector crossings", color="#238b45")
    detector_center = float(oatof["coordinate_convention"]["detector_x"])
    detector_radius = float(oatof["geometry_mm"]["detector_radius"])
    ax_f.add_patch(
        Circle((detector_center, 0.0), detector_radius, fill=False, edgecolor="#252525", linewidth=1.0, zorder=8)
    )
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
    source_bounds = _source_region_bounds(source_region_diagnostic)
    return figure, {
        "released": len(initial),
        "handoff": len(handoff),
        "pre_pulse": len(prepulse),
        "accelerator_exit": len(accelerator_exit),
        "detector": len(detector),
        "particle_marker_area_pt2": size,
        "source_region_diagnostic": {
            "profile_id": source_region_diagnostic["profile_id"],
            "claim_status": source_region_diagnostic["claim_status"],
            "event": source_region_diagnostic["event"],
            "population_basis": source_region_diagnostic["population_basis"],
            "bounds": source_bounds,
            "eligible_count": source_region_diagnostic["eligible_count"],
            "selected_count": source_region_diagnostic["selected_count"],
            "occupancy_fraction": source_region_diagnostic["occupancy_fraction"],
        },
        "accelerator_shared_tick_step_mm": shared_tick_step,
    }


def build_accelerator_phase_space_figure(
    checkpoints: pd.DataFrame,
) -> tuple[plt.Figure, dict[str, Any], pd.DataFrame]:
    """Plot detector-blind pre-pulse phase space from retained checkpoints."""

    required = {
        "particle_id",
        "event",
        "instrument_time_us",
        "x_mm",
        "y_mm",
        "z_mm",
        "vx_mm_per_us",
        "vy_mm_per_us",
        "vz_mm_per_us",
        "pulse_eligibility",
    }
    if missing := sorted(required - set(checkpoints.columns)):
        raise ValueError(f"checkpoint phase-space columns are missing: {', '.join(missing)}")
    prepulse = _event(checkpoints, "pre_pulse_state")
    if prepulse.empty or prepulse["particle_id"].duplicated().any():
        raise ValueError("pre-pulse phase space requires unique retained particles")
    numeric = (
        "x_mm",
        "y_mm",
        "z_mm",
        "vx_mm_per_us",
        "vy_mm_per_us",
        "vz_mm_per_us",
    )
    prepulse.loc[:, list(numeric)] = prepulse.loc[:, list(numeric)].apply(
        pd.to_numeric, errors="coerce"
    )
    numeric_values = prepulse.loc[:, list(numeric)]
    if (
        numeric_values.isna().any().any()
        or numeric_values.isin([math.inf, -math.inf]).any().any()
    ):
        raise ValueError("pre-pulse phase space contains non-finite coordinates")
    for axis in ("x", "y", "z"):
        prepulse[f"v{axis}_m_per_s"] = 1000.0 * prepulse[f"v{axis}_mm_per_us"]

    eligible = prepulse.loc[prepulse["pulse_eligibility"].eq("eligible")]
    excluded = prepulse.loc[~prepulse["pulse_eligibility"].eq("eligible")]
    size = marker_area(len(prepulse))
    figure, axes = plt.subplots(1, 3, figsize=(15.0, 4.6), constrained_layout=True)
    phase_axes = (
        ("x_mm", "vx_m_per_s", "x (mm)", "vx (m/s)"),
        ("y_mm", "vy_m_per_s", "y (mm)", "vy (m/s)"),
        ("z_mm", "vz_m_per_s", "z (mm)", "vz (m/s)"),
    )
    panel_metadata = []
    for ax, (position, velocity, position_label, velocity_label) in zip(
        axes, phase_axes, strict=True
    ):
        _cloud(
            ax,
            eligible,
            position,
            velocity,
            size=size,
            label="pulse eligible",
            color="#1b9e77",
        )
        _cloud(
            ax,
            excluded,
            position,
            velocity,
            size=size,
            label="not pulse eligible",
            color="#d95f02",
        )
        position_values = prepulse[position].to_numpy(dtype=float)
        velocity_values = prepulse[velocity].to_numpy(dtype=float)
        fit_metadata: dict[str, Any]
        if len(prepulse) >= 2 and float(np.ptp(position_values)) > 0:
            design = np.column_stack([np.ones(len(prepulse)), position_values])
            intercept, slope = np.linalg.lstsq(
                design, velocity_values, rcond=None
            )[0]
            predicted = intercept + slope * position_values
            residual = velocity_values - predicted
            residual_sum_squares = float(np.sum(residual**2))
            total_sum_squares = float(
                np.sum((velocity_values - np.mean(velocity_values)) ** 2)
            )
            r_squared = (
                1.0 - residual_sum_squares / total_sum_squares
                if total_sum_squares > 0
                else 1.0
            )
            fit_metadata = {
                "status": "computed",
                "population_basis": "all_retained_pre_pulse_particles",
                "particle_count": len(prepulse),
                "slope_m_per_s_per_mm": float(slope),
                "intercept_m_per_s": float(intercept),
                "r_squared": float(r_squared),
                "residual_rms_m_per_s": float(np.sqrt(np.mean(residual**2))),
                "residual_max_abs_m_per_s": float(np.max(np.abs(residual))),
            }
            line_x = np.asarray(
                [float(np.min(position_values)), float(np.max(position_values))]
            )
            ax.plot(
                line_x,
                intercept + slope * line_x,
                color="#252525",
                linewidth=1.2,
                label="linear fit (all retained pre-pulse)",
                zorder=5,
            )
            ax.text(
                0.02,
                0.98,
                (
                    f"slope={float(slope):.4g} m/s/mm\n"
                    f"R²={float(r_squared):.4g}\n"
                    f"residual RMS={fit_metadata['residual_rms_m_per_s']:.4g} m/s\n"
                    f"max|residual|={fit_metadata['residual_max_abs_m_per_s']:.4g} m/s"
                ),
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=7,
                bbox={
                    "boxstyle": "round,pad=0.25",
                    "facecolor": "white",
                    "edgecolor": "#636363",
                    "alpha": 0.82,
                },
                zorder=7,
            )
        else:
            fit_metadata = {
                "status": "not_computed",
                "reason": "fewer_than_two_particles_or_zero_position_span",
                "population_basis": "all_retained_pre_pulse_particles",
                "particle_count": len(prepulse),
                "slope_m_per_s_per_mm": None,
                "intercept_m_per_s": None,
                "r_squared": None,
                "residual_rms_m_per_s": None,
                "residual_max_abs_m_per_s": None,
            }
            ax.text(
                0.02,
                0.98,
                "linear fit not computed",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=7,
                bbox={"facecolor": "white", "edgecolor": "#636363", "alpha": 0.82},
                zorder=7,
            )
        panel_metadata.append(
            {
                "panel": (
                    f"{position.removesuffix('_mm')}-"
                    f"{velocity.removesuffix('_m_per_s')}"
                ),
                "position_column": position,
                "position_unit": "mm",
                "velocity_column": velocity,
                "velocity_unit": "m_per_s",
                "linear_fit": fit_metadata,
            }
        )
        ax.set(xlabel=position_label, ylabel=velocity_label)
        ax.grid(alpha=0.16, zorder=0)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, fontsize=7, loc="best", frameon=False)
    axes[0].set_title("A  x-vx")
    axes[1].set_title("B  y-vy")
    axes[2].set_title("C  z-vz")
    figure.suptitle(
        "Accelerator pre-pulse phase space (detector-blind retained checkpoint cohort)\n"
        f"capability={PHASE_SPACE_CAPABILITY_ID}",
        fontsize=12,
    )
    return figure, {
        "event": "pre_pulse_state",
        "population_basis": "all_retained_pre_pulse_particles",
        "selection_uses_detector_outcome": False,
        "pre_pulse_count": len(prepulse),
        "pulse_eligible_count": len(eligible),
        "not_pulse_eligible_count": len(excluded),
        "particle_marker_area_pt2": size,
        "panels": panel_metadata,
    }, prepulse.loc[
        :,
        [
            "particle_id",
            "event",
            "instrument_time_us",
            "x_mm",
            "y_mm",
            "z_mm",
            "vx_m_per_s",
            "vy_m_per_s",
            "vz_m_per_s",
            "pulse_eligibility",
        ],
    ].copy()


def write_accelerator_phase_space_outputs(
    checkpoints_path: Path,
    figure_path: Path,
    metadata_path: Path,
    data_path: Path,
) -> None:
    """Write one manifest-ready phase-space CSV/figure/metadata bundle."""

    phase_figure, phase_counts, phase_data = build_accelerator_phase_space_figure(
        pd.read_csv(checkpoints_path)
    )
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    phase_figure.savefig(figure_path, dpi=190)
    plt.close(phase_figure)
    phase_data.to_csv(data_path, index=False, lineterminator="\n")
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "role": "rf_oatof_accelerator_pre_pulse_phase_space_metadata",
                "capability_id": PHASE_SPACE_CAPABILITY_ID,
                "status": "success",
                "counts": phase_counts,
                "data": str(data_path.resolve()),
                "figure": str(figure_path.resolve()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", type=Path)
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--frontend", type=Path)
    parser.add_argument("--oatof", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--phase-space-output", type=Path)
    parser.add_argument("--phase-space-metadata", type=Path)
    parser.add_argument("--phase-space-data", type=Path)
    parser.add_argument("--phase-space-only", action="store_true")
    args = parser.parse_args()
    phase_outputs = (
        args.phase_space_output,
        args.phase_space_metadata,
        args.phase_space_data,
    )
    if args.phase_space_only:
        if not all(value is not None for value in phase_outputs):
            parser.error("phase-space-only requires figure, metadata and data outputs")
        assert args.phase_space_output is not None
        assert args.phase_space_metadata is not None
        assert args.phase_space_data is not None
        write_accelerator_phase_space_outputs(
            args.checkpoints,
            args.phase_space_output,
            args.phase_space_metadata,
            args.phase_space_data,
        )
        print(f"SINGLE_FLIGHT_PHASE_SPACE=PASS FIGURE={args.phase_space_output}")
        return 0
    spatial_inputs = (
        args.initial,
        args.upstream,
        args.frontend,
        args.oatof,
        args.output,
        args.metadata,
    )
    if not all(value is not None for value in spatial_inputs):
        parser.error("spatial six-panel mode requires all spatial inputs and outputs")
    assert args.initial is not None
    assert args.upstream is not None
    assert args.frontend is not None
    assert args.oatof is not None
    assert args.output is not None
    assert args.metadata is not None
    summary = _load(args.output.parent.parent / "summary.json")
    source_region_diagnostic = summary.get("source_region_diagnostic")
    if not isinstance(source_region_diagnostic, dict):
        parser.error("summary does not contain the default source-region diagnostic")
    figure, counts = build_figure(
        pd.read_csv(args.initial),
        pd.read_csv(args.checkpoints),
        _load(args.upstream),
        _load(args.frontend),
        _load(args.oatof),
        source_region_diagnostic,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=190)
    plt.close(figure)
    args.metadata.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "role": "rf_oatof_single_flight_spatial_six_panel_metadata",
                "capability_id": CAPABILITY_ID,
                "status": "success",
                "counts": counts,
                "figure": str(args.output.resolve()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if any(value is None for value in phase_outputs) and any(
        value is not None for value in phase_outputs
    ):
        parser.error("phase-space figure, metadata and data must be supplied together")
    if all(value is not None for value in phase_outputs):
        assert args.phase_space_output is not None
        assert args.phase_space_metadata is not None
        assert args.phase_space_data is not None
        write_accelerator_phase_space_outputs(
            args.checkpoints,
            args.phase_space_output,
            args.phase_space_metadata,
            args.phase_space_data,
        )
    print(f"SINGLE_FLIGHT_SIX_PANEL=PASS FIGURE={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
