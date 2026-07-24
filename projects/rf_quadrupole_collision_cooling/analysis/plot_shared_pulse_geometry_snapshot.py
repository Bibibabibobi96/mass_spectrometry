"""Plot the standard parameterized RF-to-oaTOF state at pulse onset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.artist import Artist
from matplotlib.patches import Circle, Rectangle
import numpy as np
import pandas as pd

from common.contracts.rigid_transform import (
    FramedPosition,
    FramedVector,
    RigidTransform,
    relative_transform,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPATIAL_REGISTRATION = (
    PROJECT_ROOT / "config" / "resolved_rf_to_oatof_s2_spatial_registration.json"
)


def accelerator_geometry(
    baseline: dict,
    joint: dict,
    registration: dict,
) -> dict[str, object]:
    """Validate and prepare oaTOF geometry in the resolved instrument frame."""
    geometry = baseline["geometry_mm"]
    source = baseline["particle_source"]
    rings = baseline["rings"]
    port = joint["port_sweep"]
    target = joint["physical_boundaries"]["target_entry_surface"]
    resolved_target = registration["resolved_surfaces"]["target_entry"][
        "in_instrument_frame"
    ]
    frame_id = baseline["coordinate_convention"]["frame_id"]
    if (
        registration.get("role") != "resolved_spatial_registration_do_not_edit"
        or registration.get("instrument_frame_id") != frame_id
        or target.get("frame_id") != frame_id
        or resolved_target.get("frame_id") != frame_id
    ):
        raise ValueError("pulse geometry frame differs from resolved S2 authority")
    target_center = np.asarray(target["center_mm"], dtype=float)
    resolved_center = np.asarray(resolved_target["center_mm"], dtype=float)
    target_normal = np.asarray(target["outward_normal"], dtype=float)
    resolved_normal = np.asarray(resolved_target["normal"], dtype=float)
    if (
        not np.allclose(target_center, resolved_center, rtol=0, atol=1e-12)
        or not np.allclose(target_normal, resolved_normal, rtol=0, atol=1e-12)
        or not np.isclose(
            float(port["center_z_mm"]), target_center[2], rtol=0, atol=1e-12
        )
    ):
        raise ValueError("physical port differs from resolved target-entry surface")

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
        "frame_id": frame_id,
        "target_entry_center": {
            axis: float(target_center[index]) for index, axis in enumerate("xyz")
        },
        "target_entry_normal": {
            axis: float(target_normal[index]) for index, axis in enumerate("xyz")
        },
        "source_exit_center": {
            axis: float(
                registration["resolved_surfaces"]["source_exit"][
                    "in_instrument_frame"
                ]["center_mm"][index]
            )
            for index, axis in enumerate("xyz")
        },
        "port_center_y": float(target_center[1]),
        "port_center_z": float(target_center[2]),
        "port_width_y": float(port["selected_n100_candidate_full_width_y_mm"]),
        "port_height_z": float(port["full_height_z_mm"]),
        "detector_center_x": float(baseline["coordinate_convention"]["detector_x"]),
        "detector_center_y": float(
            baseline["coordinate_convention"].get("detector_y", 0.0)
        ),
        "detector_radius": float(geometry["detector_radius"]),
        "source_center": {axis: float(source[f"center_{axis}_mm"]) for axis in "xyz"},
        "source_size": {axis: float(source[f"size_{axis}_mm"]) for axis in "xyz"},
    }


def _filled_rect(ax, xy, width, height, **kwargs) -> None:
    ax.add_patch(Rectangle(xy, width, height, **kwargs))


def registered_chain_geometry(
    baseline: dict,
    joint: dict,
    registration: dict,
    rf_resolved: dict,
    s2_contract: dict,
) -> dict[str, object]:
    """Resolve RF, S2 and accelerator geometry into the oa component frame."""
    result = accelerator_geometry(baseline, joint, registration)
    if rf_resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("RF geometry is not an authoritative resolved design")
    if s2_contract.get("role") != "rf_to_oatof_s2_passive_grounded_connector_candidate":
        raise ValueError("S2 connector geometry contract role is invalid")

    source_pose = RigidTransform.from_contract(
        registration["component_poses"]["rf_quadrupole_component"]
    )
    target_pose = RigidTransform.from_contract(
        registration["component_poses"]["oatof_global"]
    )
    source_to_target = relative_transform(source_pose, target_pose)
    instrument_to_target = target_pose.inverse()
    source_frame = source_to_target.from_frame_id
    instrument_frame = instrument_to_target.from_frame_id

    def source_point(values: list[float]) -> np.ndarray:
        position = FramedPosition(source_frame, tuple(float(value) for value in values))
        return np.asarray(source_to_target.transform_position(position).coordinates_mm)

    def instrument_point(values: list[float]) -> np.ndarray:
        position = FramedPosition(
            instrument_frame, tuple(float(value) for value in values)
        )
        return np.asarray(
            instrument_to_target.transform_position(position).coordinates_mm
        )

    source_axis = np.asarray(source_to_target.transform_vector(
        FramedVector(source_frame, (0.0, 0.0, 1.0))
    ).components)
    if not np.allclose(source_axis, (1.0, 0.0, 0.0), rtol=0, atol=1e-12):
        raise ValueError("RF axial direction is not registered to oa +x")

    rf_geometry = rf_resolved["geometry_mm"]
    rods = []
    for rod in rf_geometry["rod_array"]["rods"]:
        start = source_point([
            rod["center_x_mm"], rod["center_y_mm"], rod["z_min_mm"]
        ])
        end = source_point([
            rod["center_x_mm"], rod["center_y_mm"], rod["z_max_mm"]
        ])
        if not np.allclose(start[1:], end[1:], rtol=0, atol=1e-12):
            raise ValueError("registered RF rod is not parallel to oa x")
        rods.append({
            "rod_id": int(rod["rod_id"]),
            "x_min": float(min(start[0], end[0])),
            "x_max": float(max(start[0], end[0])),
            "center_y": float(start[1]),
            "center_z": float(start[2]),
            "radius": float(rod["radius_mm"]),
        })
    if len(rods) != int(rf_resolved["identity"]["electrode_count"]):
        raise ValueError("resolved RF rod count differs from design identity")

    entrance_interface = rf_resolved["interfaces_mm"]["entrance"]
    exit_interface = rf_resolved["interfaces_mm"]["exit"]
    shield_start = source_point(
        [0.0, 0.0, entrance_interface["plate_z_max_mm"]]
    )
    shield_end = source_point([0.0, 0.0, exit_interface["plate_z_min_mm"]])
    plate_start = source_point([0.0, 0.0, exit_interface["plate_z_min_mm"]])
    plate_end = source_point([0.0, 0.0, exit_interface["plate_z_max_mm"]])
    source_surface = instrument_point(list(
        registration["resolved_surfaces"]["source_exit"][
            "in_instrument_frame"
        ]["center_mm"]
    ))
    target_surface = instrument_point(list(
        registration["resolved_surfaces"]["target_entry"][
            "in_instrument_frame"
        ]["center_mm"]
    ))
    expected_source_surface = source_point([
        0.0, 0.0, exit_interface["connector_z_max_mm"]
    ])
    if not np.allclose(
        source_surface, expected_source_surface, rtol=0, atol=1e-12
    ):
        raise ValueError("RF exit surface differs from resolved registration")

    connector = s2_contract["passive_connector_geometry"]
    downstream = connector["downstream_entry_aperture"]
    connector_extent = connector["axial_extent_x_mm"]
    connector_start = instrument_point([
        connector_extent[0], downstream["center_mm"][1], downstream["center_mm"][2]
    ])
    connector_end = instrument_point([
        connector_extent[1], downstream["center_mm"][1], downstream["center_mm"][2]
    ])
    downstream_center = instrument_point(list(downstream["center_mm"]))
    if (
        not np.allclose(connector_start[1:], connector_end[1:], rtol=0, atol=1e-12)
        or not np.allclose(downstream_center, target_surface, rtol=0, atol=1e-12)
        or not np.isclose(
            abs(connector_end[0] - connector_start[0]),
            float(connector["length_mm"]), rtol=0, atol=1e-12,
        )
    ):
        raise ValueError("S2 connector differs from resolved interface surfaces")

    result["target_entry_center"] = {
        axis: float(target_surface[index]) for index, axis in enumerate("xyz")
    }
    result["port_center_y"] = float(target_surface[1])
    result["port_center_z"] = float(target_surface[2])
    result["rf_chain"] = {
        "rods": rods,
        "rod_count": len(rods),
        "rod_end_x": float(max(rod["x_max"] for rod in rods)),
        "axis_center_y": float(source_surface[1]),
        "axis_center_z": float(source_surface[2]),
        "shield_inner_radius": float(
            joint["local_domain"]["rf_shield_inner_radius_mm"]
        ),
        "shield_wall": float(
            joint["local_domain"]["rf_shield_numerical_wall_thickness_mm"]
        ),
        "shield_x_min": float(min(shield_start[0], shield_end[0])),
        "shield_x_max": float(max(shield_start[0], shield_end[0])),
        "exit_plate_x_min": float(min(plate_start[0], plate_end[0])),
        "exit_plate_x_max": float(max(plate_start[0], plate_end[0])),
        "source_exit_x": float(source_surface[0]),
        "source_exit_aperture_radius": float(exit_interface["aperture_radius_mm"]),
        "connector_x_min": float(min(connector_start[0], connector_end[0])),
        "connector_x_max": float(max(connector_start[0], connector_end[0])),
        "connector_length": float(connector["length_mm"]),
        "connector_center_y": float(connector_start[1]),
        "connector_center_z": float(connector_start[2]),
        "connector_radius": float(connector["cavity"]["inner_radius_mm"]),
        "target_entry_x": float(target_surface[0]),
    }
    return result


def _geometry_artist(
    artist: Artist, semantic_id: str, label: str | None = None
) -> Artist:
    """Attach one stable semantic identity and an optional legend label."""
    artist.set_gid(semantic_id)
    if label is not None:
        artist.set_label(label)
    return artist


def add_accelerator_geometry_outlines(
    ax: plt.Axes,
    geometry: dict[str, object],
    horizontal_axis: str,
) -> dict[str, list[Artist]]:
    """Draw the minimum authoritative accelerator section for one projection."""
    if horizontal_axis not in {"x", "y"}:
        raise ValueError("accelerator projection must use x or y")
    center = float(
        geometry["center_x"]
        if horizontal_axis == "x"
        else geometry["port_center_y"]
    )
    names = (
        "shield_inner_half", "shield_outer_half", "shield_wall",
        "shield_z_min", "shield_z_max", "ring_outer_half", "bore_half",
        "ring_thickness", "repeller_z", "repeller_thickness",
        "grid1_z", "grid1_half", "grid2_z", "grid2_half",
        "port_center_z", "port_width_y", "port_height_z",
    )
    values = {name: float(geometry[name]) for name in names}
    ring_centers = [float(value) for value in geometry["ring_centers_z"]]
    if (
        not np.isfinite([center, *values.values(), *ring_centers]).all()
        or values["shield_outer_half"] <= values["shield_inner_half"]
        or values["ring_outer_half"] <= values["bore_half"]
        or not ring_centers
    ):
        raise ValueError("accelerator outline geometry is invalid")

    artists: dict[str, list[Artist]] = {
        "shield": [], "rings": [], "repeller": [], "grids": [], "port": []
    }
    z_min = values["shield_z_min"]
    z_max = values["shield_z_max"]
    inner = values["shield_inner_half"]
    outer = values["shield_outer_half"]
    shield_parts = (
        (center - outer, z_min, outer - inner, z_max - z_min),
        (center + inner, z_min, outer - inner, z_max - z_min),
        (center - outer, z_min, 2 * outer, values["shield_wall"]),
    )
    for index, (x0, z0, width, height) in enumerate(shield_parts):
        patch = Rectangle(
            (x0, z0), width, height, facecolor="#bdbdbd",
            edgecolor="#636363", alpha=0.48, linewidth=1.0, zorder=1,
        )
        _geometry_artist(
            patch, f"accelerator:{horizontal_axis}:shield:{index}",
            "grounded accelerator shield" if index == 0 else None,
        )
        ax.add_patch(patch)
        artists["shield"].append(patch)

    ring_side = values["ring_outer_half"] - values["bore_half"]
    for ring_index, ring_z in enumerate(ring_centers):
        for side_index, x0 in enumerate(
            (center - values["ring_outer_half"], center + values["bore_half"])
        ):
            patch = Rectangle(
                (x0, ring_z - values["ring_thickness"] / 2),
                ring_side, values["ring_thickness"], facecolor="#3182bd",
                edgecolor="#08519c", alpha=0.72, linewidth=0.8, zorder=2,
            )
            _geometry_artist(
                patch,
                f"accelerator:{horizontal_axis}:ring:{ring_index}:{side_index}",
                (
                    f"graded ring electrodes (N={len(ring_centers)})"
                    if ring_index == 0 and side_index == 0 else None
                ),
            )
            ax.add_patch(patch)
            artists["rings"].append(patch)

    repeller = Rectangle(
        (
            center - values["ring_outer_half"],
            values["repeller_z"] - values["repeller_thickness"] / 2,
        ),
        2 * values["ring_outer_half"], values["repeller_thickness"],
        facecolor="#3182bd", edgecolor="#08519c", alpha=0.72,
        linewidth=0.8, zorder=2,
    )
    _geometry_artist(
        repeller, f"accelerator:{horizontal_axis}:repeller", "repeller electrode"
    )
    ax.add_patch(repeller)
    artists["repeller"].append(repeller)

    for name in ("grid1", "grid2"):
        line = ax.plot(
            [center - values[f"{name}_half"], center + values[f"{name}_half"]],
            [values[f"{name}_z"], values[f"{name}_z"]],
            color="#6a51a3", linestyle="-.", linewidth=1.2, zorder=2.5,
            label="grid electrodes" if name == "grid1" else None,
        )[0]
        _geometry_artist(line, f"accelerator:{horizontal_axis}:{name}")
        artists["grids"].append(line)

    port_z0 = values["port_center_z"] - values["port_height_z"] / 2
    if horizontal_axis == "y":
        port = Rectangle(
            (
                float(geometry["port_center_y"]) - values["port_width_y"] / 2,
                port_z0,
            ),
            values["port_width_y"], values["port_height_z"], fill=False,
            edgecolor="#cb181d", linestyle=":", linewidth=1.5, zorder=3,
        )
    else:
        port = Rectangle(
            (center - outer, port_z0), outer - inner, values["port_height_z"],
            facecolor="white", edgecolor="#cb181d", linestyle=":",
            linewidth=1.5, zorder=3,
        )
    _geometry_artist(
        port, f"accelerator:{horizontal_axis}:physical_port",
        "physical entry aperture",
    )
    ax.add_patch(port)
    artists["port"].append(port)
    if horizontal_axis == "x":
        ax.annotate(
            "oa target wall / entry port\n"
            f"{values['port_width_y']:.3g} y × {values['port_height_z']:.3g} z mm",
            (center - outer, float(geometry["port_center_z"])),
            xytext=(8, 14), textcoords="offset points", fontsize=8,
            arrowprops={"arrowstyle": "->", "color": "#cb181d"}, zorder=8,
        )
    return artists


def add_rf_s2_geometry_outlines(
    ax: plt.Axes,
    geometry: dict[str, object],
    projection: str,
) -> dict[str, list[Artist]]:
    """Draw registered RF and S2 geometry once per diagnostically useful view."""
    if projection not in {"xz", "yz"}:
        raise ValueError("RF/S2 projection must be xz or yz")
    chain = geometry["rf_chain"]
    rods = chain["rods"]
    artists: dict[str, list[Artist]] = {
        "rods": [], "shield": [], "exit_plate": [], "connector": [],
        "clear_aperture": [],
    }
    if projection == "xz":
        for index, rod in enumerate(rods):
            patch = Rectangle(
                (float(rod["x_min"]), float(rod["center_z"]) - float(rod["radius"])),
                float(rod["x_max"]) - float(rod["x_min"]),
                2 * float(rod["radius"]), facecolor="#74a9cf",
                edgecolor="#0570b0", alpha=0.55, linewidth=0.8, zorder=1.6,
            )
            _geometry_artist(
                patch, f"rf:xz:rod:{rod['rod_id']}",
                f"RF rods (N={chain['rod_count']}; 2 overlap in x–z projection)"
                if index == 0 else None,
            )
            ax.add_patch(patch)
            artists["rods"].append(patch)

        axis_z = float(chain["axis_center_z"])
        inner = float(chain["shield_inner_radius"])
        wall = float(chain["shield_wall"])
        for side_index, z0 in enumerate((axis_z - inner - wall, axis_z + inner)):
            patch = Rectangle(
                (float(chain["shield_x_min"]), z0),
                float(chain["shield_x_max"]) - float(chain["shield_x_min"]),
                wall, facecolor="#d9d9d9", edgecolor="#737373",
                alpha=0.55, linewidth=0.8, zorder=1,
            )
            _geometry_artist(
                patch, f"rf:xz:numerical_shield:{side_index}",
                "RF numerical shield" if side_index == 0 else None,
            )
            ax.add_patch(patch)
            artists["shield"].append(patch)

        aperture = float(chain["source_exit_aperture_radius"])
        outer = inner + wall
        for side_index, z0 in enumerate((axis_z - outer, axis_z + aperture)):
            patch = Rectangle(
                (float(chain["exit_plate_x_min"]), z0),
                float(chain["exit_plate_x_max"]) - float(chain["exit_plate_x_min"]),
                outer - aperture, facecolor="#969696", edgecolor="#525252",
                alpha=0.68, linewidth=0.8, zorder=1.8,
            )
            _geometry_artist(
                patch, f"rf:xz:exit_plate:{side_index}",
                "RF exit annular plate" if side_index == 0 else None,
            )
            ax.add_patch(patch)
            artists["exit_plate"].append(patch)

        if float(chain["connector_length"]) > 0:
            for side_index, z in enumerate(
                (
                    float(chain["connector_center_z"])
                    - float(chain["connector_radius"]),
                    float(chain["connector_center_z"])
                    + float(chain["connector_radius"]),
                )
            ):
                line = ax.plot(
                    [float(chain["connector_x_min"]), float(chain["connector_x_max"])],
                    [z, z], color="#31a354", linewidth=1.4, zorder=2.8,
                    label="S2 passive connector" if side_index == 0 else None,
                )[0]
                _geometry_artist(line, f"s2:xz:connector:{side_index}")
                artists["connector"].append(line)
        ax.annotate(
            "rod end", (float(chain["rod_end_x"]), axis_z),
            xytext=(-24, 12), textcoords="offset points", fontsize=8,
            arrowprops={"arrowstyle": "->", "color": "#0570b0"}, zorder=8,
        )
        ax.annotate(
            "RF source surface", (float(chain["source_exit_x"]), axis_z),
            xytext=(-36, -20), textcoords="offset points", fontsize=8,
            arrowprops={"arrowstyle": "->", "color": "#525252"}, zorder=8,
        )
    else:
        for index, rod in enumerate(rods):
            patch = Circle(
                (float(rod["center_y"]), float(rod["center_z"])),
                float(rod["radius"]), fill=False,
                edgecolor="#0570b0", alpha=0.85, linewidth=1.0, zorder=1.6,
            )
            _geometry_artist(
                patch, f"rf:yz:rod:{rod['rod_id']}",
                f"RF rod cross-sections (N={chain['rod_count']})"
                if index == 0 else None,
            )
            ax.add_patch(patch)
            artists["rods"].append(patch)
        shield = Circle(
            (float(chain["axis_center_y"]), float(chain["axis_center_z"])),
            float(chain["shield_inner_radius"]) + float(chain["shield_wall"]),
            fill=False, edgecolor="#737373", linewidth=1.0, zorder=1,
        )
        _geometry_artist(
            shield, "rf:yz:numerical_shield", "RF numerical shield outer boundary"
        )
        ax.add_patch(shield)
        artists["shield"].append(shield)
        clear = Circle(
            (float(chain["axis_center_y"]), float(chain["axis_center_z"])),
            float(chain["source_exit_aperture_radius"]), fill=False,
            edgecolor="#525252", linestyle="--", linewidth=1.2, zorder=2.5,
        )
        _geometry_artist(clear, "rf:yz:clear_aperture", "RF/S2 clear aperture")
        ax.add_patch(clear)
        artists["clear_aperture"].append(clear)
    return artists


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
    port_center_y = float(geometry["port_center_y"])
    y_edge_distance = (
        (classified["y_mm"] - port_center_y).abs()
        - float(geometry["port_width_y"]) / 2
    ).abs()
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
    masks = pd.DataFrame({
        "active_at_pulse": classified["active_at_pulse"].astype(bool),
        "port_wall_loss": classified["frozen_port_loss_before_pulse"].astype(bool),
        "accelerator_loss": classified[
            "frozen_accelerator_loss_before_pulse"
        ].astype(bool),
    })
    membership = masks.sum(axis=1)
    if not membership.eq(1).all():
        bad_ids = classified.loc[membership.ne(1), "particle_id"].astype(int).tolist()
        raise ValueError(
            "pulse snapshot classes are not mutually exclusive and exhaustive: "
            f"particle_ids={bad_ids}"
        )
    classified["snapshot_class"] = np.select(
        [masks["active_at_pulse"], masks["port_wall_loss"]],
        ["active_at_pulse", "port_wall_loss"],
        default="accelerator_loss",
    )
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


def prepare_snapshot_data(
    capture_path: Path,
    events_path: Path,
    baseline_path: Path,
    joint_path: Path,
    registration_path: Path = DEFAULT_SPATIAL_REGISTRATION,
) -> tuple[pd.DataFrame, dict[str, object], str, str]:
    """Validate source states and prepare mutually exclusive snapshot classes."""
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
    numeric_columns = ["instrument_time_us", "x_mm", "y_mm", "z_mm"]
    if not np.isfinite(
        capture[numeric_columns].apply(pd.to_numeric, errors="raise").to_numpy(float)
    ).all():
        raise ValueError("pulse capture contains non-finite time or position")
    identities = capture[["frame_id", "clock_epoch_id"]].drop_duplicates()
    if len(identities) != 1 or identities.iloc[0].astype(str).str.strip().eq("").any():
        raise ValueError("standard pulse snapshot requires one frame and clock epoch")
    frame_id = str(identities.iloc[0]["frame_id"])
    clock_epoch_id = str(identities.iloc[0]["clock_epoch_id"])
    if not {"frame_id", "clock_epoch_id"}.issubset(events.columns):
        raise ValueError("pulse event census is missing frame or clock epoch")
    if (
        not events["frame_id"].eq(frame_id).all()
        or not events["clock_epoch_id"].eq(clock_epoch_id).all()
    ):
        raise ValueError("pulse event census frame or clock epoch changed")
    capture = add_sparse_loss_positions(capture, events)

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    joint = json.loads(joint_path.read_text(encoding="utf-8"))
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    g = accelerator_geometry(baseline, joint, registration)
    if frame_id != g["frame_id"]:
        raise ValueError("pulse capture frame differs from geometry authority")
    capture = classify_snapshot(capture, events, g)
    if not capture["snapshot_class"].eq("active_at_pulse").any():
        raise ValueError("standard pulse snapshot requires an active pulse cohort")
    center = g["source_center"]
    size = g["source_size"]
    inside = np.logical_and.reduce([
        np.abs(capture[f"{axis}_mm"].to_numpy(float) - float(center[axis]))
        <= float(size[axis]) / 2 + 1e-12
        for axis in "xyz"
    ])
    capture["inside_oatof_ideal_reference_volume"] = inside
    return capture, g, frame_id, clock_epoch_id


def build_shared_pulse_geometry_figure(
    capture: pd.DataFrame,
    g: dict[str, object],
    frame_id: str,
    clock_epoch_id: str,
) -> tuple[plt.Figure, dict[str, plt.Axes]]:
    """Render the prepared shared-pulse geometry without writing files."""
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
    port_y0 = g["port_center_y"] - g["port_width_y"] / 2

    shield_color = "#bdbdbd"
    electrode_color = "#3182bd"
    grid_color = "#31a354"
    ion_color = "#d95f0e"
    ideal_color = "#756bb1"
    marker_areas = particle_marker_areas(len(capture))

    fig, (ax_xz, ax_xy) = plt.subplots(1, 2, figsize=(15.5, 7.2))

    # The checkpoint figure consumes this same authoritative section primitive.
    add_accelerator_geometry_outlines(ax_xz, g, "x")

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
                   xy=(cx - outer + wall / 2, g["port_center_y"]),
                   xytext=(cx - outer + 2.0, g["port_center_y"] + 3.0),
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
    return fig, {"injection_acceleration": ax_xz, "injection_cross": ax_xy}


def export_snapshot(
    figure: plt.Figure,
    figure_path: Path,
    metadata_path: Path,
    metadata: dict[str, object],
) -> None:
    """Export one validated PNG and its machine-readable metadata."""
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(figure_path, format="png", dpi=190)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def plot_snapshot(
    capture_path: Path,
    events_path: Path,
    baseline_path: Path,
    joint_path: Path,
    figure_path: Path,
    metadata_path: Path,
    registration_path: Path = DEFAULT_SPATIAL_REGISTRATION,
) -> dict[str, object]:
    """Prepare, render and export the standard run-diagnostic snapshot."""
    capture, g, frame_id, clock_epoch_id = prepare_snapshot_data(
        capture_path, events_path, baseline_path, joint_path, registration_path
    )
    active = capture[capture["snapshot_class"].eq("active_at_pulse")]
    frozen_port_loss = capture[capture["snapshot_class"].eq("port_wall_loss")]
    frozen_accelerator_loss = capture[
        capture["snapshot_class"].eq("accelerator_loss")
    ]
    pulse_time = float(capture["instrument_time_us"].iloc[0])
    marker_areas = particle_marker_areas(len(capture))
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
        "classification_denominator": int(len(capture)),
        "classification_is_mutually_exclusive_and_exhaustive": True,
        "frozen_loss_positions_plotted_separately": True,
        "active_inside_ideal_reference_volume": int(pd.to_numeric(
            active.get("inside_oatof_ideal_reference_volume", pd.Series(dtype=int)),
            errors="coerce").fillna(0).astype(bool).sum()),
        "active_ideal_reference_volume_denominator": int(len(active)),
        "active_ideal_reference_volume_fraction": float(pd.to_numeric(
            active.get("inside_oatof_ideal_reference_volume", pd.Series(dtype=int)),
            errors="coerce").fillna(0).astype(bool).mean()),
        "planes": ["x-z injection-acceleration", "x-y injection-cross-plane"],
        "geometry_sources": {
            "accelerator": str(baseline_path),
            "physical_port": str(joint_path),
            "resolved_registration": str(registration_path),
        },
        "geometry_mm": g,
        "plot_style": {
            "particle_marker_area_pt2": marker_areas,
            "marker_scaling_rule": "base_area_times_min(1,sqrt(100/snapshot_rows))",
        },
        "dense_trajectories_saved": False,
    }
    figure, _ = build_shared_pulse_geometry_figure(
        capture, g, frame_id, clock_epoch_id
    )
    try:
        export_snapshot(figure, figure_path, metadata_path, metadata)
    finally:
        plt.close(figure)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--oatof-baseline", type=Path, required=True)
    parser.add_argument("--joint-contract", type=Path, required=True)
    parser.add_argument(
        "--resolved-registration",
        type=Path,
        default=DEFAULT_SPATIAL_REGISTRATION,
    )
    parser.add_argument("--figure", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    result = plot_snapshot(
        args.capture, args.events, args.oatof_baseline, args.joint_contract,
        args.figure, args.metadata, args.resolved_registration,
    )
    print(f"SHARED_PULSE_GEOMETRY_SNAPSHOT=PASS ACTIVE={result['particles_active_at_pulse']} "
          f"PORT_LOSS={result['frozen_port_losses_before_pulse']} "
          f"ACCELERATOR_LOSS={result['frozen_accelerator_losses_before_pulse']}")


if __name__ == "__main__":
    main()
