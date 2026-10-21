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
PHASE_SPACE_CAPABILITY_ID = "rf_oatof_accelerator_phase_space_evolution_v2"
GEOMETRY_TARGET_TICK_INTERVALS = 9

# The continuous frontend enters through the connector along global x and then
# turns into the oaTOF's global z axis.  Angles must follow that local path;
# using one global component for every checkpoint would manufacture a false
# gap trend at the 90-degree bend.
_CHECKPOINT_AXIAL_AXIS = {
    "source_release": "x",
    "local_aperture_pre": "y",
    "local_aperture_post": "y",
    "multipole_handoff": "x",
    "pre_pulse_state": "x",
    "accelerator_grid1_forward": "x",
    "accelerator_intermediate2_forward": "z",
    "local_accelerator_exit": "z",
    "accelerator_focus_forward": "z",
    "reflectron_entrance_forward": "z",
    "reflectron_midgrid_forward": "z",
    "reflectron_turning_point": "z",
    "reflectron_exit_return": "z",
    "detector_crossing": "z",
}


def _quantiles(values: np.ndarray) -> dict[str, float]:
    """Return the compact, distribution-complete summary used by all cohorts."""

    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise ValueError("distribution values must be a non-empty finite vector")
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "sample_std": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
        "p05": float(np.quantile(values, 0.05)),
        "p25": float(np.quantile(values, 0.25)),
        "p75": float(np.quantile(values, 0.75)),
        "p95": float(np.quantile(values, 0.95)),
    }


def _phase_space_fit_diagnostics(
    position_mm: np.ndarray, velocity_m_per_s: np.ndarray
) -> dict[str, Any]:
    """Fit linear through cubic position--velocity diagnostics in native units.

    The polynomial coefficients use the uncentred physical position in mm:
    ``v = c0 + c1*z + c2*z^2 + c3*z^3``.  This makes the reported units
    explicit, but means the higher-order coefficients are origin-dependent.
    ``cubic_random_residual`` is the retained pointwise residual after the
    cubic least-squares fit; it is not a stochastic model assumption.
    """

    position = np.asarray(position_mm, dtype=float)
    velocity = np.asarray(velocity_m_per_s, dtype=float)
    if (
        position.ndim != 1
        or velocity.ndim != 1
        or position.size != velocity.size
        or position.size == 0
        or not np.isfinite(position).all()
        or not np.isfinite(velocity).all()
    ):
        raise ValueError("phase-space fit requires equal non-empty finite vectors")

    common = {
        "population_basis": "all_retained_checkpoint_particles",
        "particle_count": int(position.size),
        "position_unit": "mm",
        "velocity_unit": "m_per_s",
        "polynomial_basis": "velocity_m_per_s = sum(c_power * position_mm**power)",
    }
    if position.size < 2 or float(np.ptp(position)) == 0.0:
        return {
            "status": "not_computed",
            "reason": "fewer_than_two_particles_or_zero_position_span",
            **common,
            "slope_m_per_s_per_mm": None,
            "intercept_m_per_s": None,
            "r_squared": None,
            "residual_sigma_m_per_s": None,
            "residual_rms_m_per_s": None,
            "residual_max_abs_m_per_s": None,
            "residual_p95_abs_m_per_s": None,
            "quadratic_fit": None,
            "cubic_fit": None,
            "cubic_random_residual": None,
        }

    def polynomial(degree: int) -> dict[str, Any] | None:
        design = np.column_stack([position**power for power in range(degree + 1)])
        coefficients, _, rank, _ = np.linalg.lstsq(design, velocity, rcond=None)
        if int(rank) != degree + 1:
            return None
        residual = velocity - design @ coefficients
        rms = float(np.sqrt(np.mean(residual**2)))
        return {
            "degree": degree,
            "coefficients_m_per_s": {
                "constant": float(coefficients[0]),
                **{
                    (
                        "linear_per_mm" if power == 1
                        else "quadratic_per_mm2" if power == 2
                        else "cubic_per_mm3"
                    ):
                    float(coefficients[power])
                    for power in range(1, degree + 1)
                },
            },
            "residual_sigma_m_per_s": float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0,
            "residual_rms_m_per_s": rms,
            "residual_max_abs_m_per_s": float(np.max(np.abs(residual))),
            "residual_p95_abs_m_per_s": float(np.quantile(np.abs(residual), 0.95)),
        }

    linear = polynomial(1)
    assert linear is not None  # non-zero span guarantees a full-rank linear fit
    linear_residual_rms = float(linear["residual_rms_m_per_s"])
    total_sum_squares = float(np.sum((velocity - np.mean(velocity)) ** 2))
    residual_sum_squares = float(
        linear_residual_rms**2 * position.size
    )
    quadratic = polynomial(2)
    cubic = polynomial(3)

    def higher_order_payload(fit: dict[str, Any] | None) -> dict[str, Any]:
        if fit is None:
            return {
                "status": "not_computed",
                "reason": "insufficient_rank_or_particles_for_polynomial_degree",
            }
        rms = float(fit["residual_rms_m_per_s"])
        reduction = (
            None
            if linear_residual_rms == 0.0
            else float((linear_residual_rms - rms) / linear_residual_rms)
        )
        return {
            "status": "computed",
            **fit,
            "relative_linear_residual_rms_reduction": reduction,
        }

    cubic_payload = higher_order_payload(cubic)
    cubic_random_residual = (
        None
        if cubic is None
        else {
            "definition": "pointwise residual after the cubic least-squares fit",
            "sigma_m_per_s": cubic["residual_sigma_m_per_s"],
            "rms_m_per_s": cubic["residual_rms_m_per_s"],
            "max_abs_m_per_s": cubic["residual_max_abs_m_per_s"],
            "p95_abs_m_per_s": cubic["residual_p95_abs_m_per_s"],
        }
    )
    return {
        "status": "computed",
        **common,
        # Retain these legacy affine names for existing consumers.
        "slope_m_per_s_per_mm": linear["coefficients_m_per_s"]["linear_per_mm"],
        "intercept_m_per_s": linear["coefficients_m_per_s"]["constant"],
        "r_squared": (
            1.0 - residual_sum_squares / total_sum_squares
            if total_sum_squares > 0.0
            else 1.0
        ),
        "residual_sigma_m_per_s": linear["residual_sigma_m_per_s"],
        "residual_rms_m_per_s": linear_residual_rms,
        "residual_max_abs_m_per_s": linear["residual_max_abs_m_per_s"],
        "residual_p95_abs_m_per_s": linear["residual_p95_abs_m_per_s"],
        "quadratic_fit": higher_order_payload(quadratic),
        "cubic_fit": cubic_payload,
        "cubic_random_residual": cubic_random_residual,
    }


def _population_moments(values: np.ndarray) -> dict[str, float]:
    """Keep signed means and population SD separate from legacy sample SD."""
    return {"signed_mean": float(np.mean(values)), "population_std": float(np.std(values, ddof=0))}


def _integration_component_diagnostics(
    rows: pd.DataFrame, position: np.ndarray, velocity: np.ndarray | None, axis: str,
    *, frame_id: str = "oatof_global_cartesian",
) -> dict[str, Any]:
    """Describe integration-global components; no MR frame mapping is implied."""
    result: dict[str, Any] = {
        "frame": frame_id, "mr_frame_mapping": "native_mr_frame" if frame_id == "mrtof_global_cartesian" else "not_bound",
        "standard_deviation_ddof": 0,
        "space_population_sigma_mm": {
            name: float(np.std(position[:, i], ddof=0)) for i, name in enumerate("xyz")
        },
        "theta_x_deg": None, "theta_y_deg": None,
        "angle_unavailable_reason": "checkpoint_propagation_axis_is_not_z_or_velocity_unavailable",
    }
    # Named local components prevent incoming +y angles being confused with
    # outgoing OA -z angles. The existing z aliases remain unchanged.
    result["local_transverse_angles_deg"] = None
    result["local_angle_definition"] = f"atan2(v_component, abs(v_{axis})); signed degrees"
    if velocity is not None:
        axial = "xyz".index(axis)
        if np.any(np.abs(velocity[:, axial]) <= 1.0e-12):
            result["angle_unavailable_reason"] = "zero_axial_velocity_present"
        else:
            result["local_transverse_angles_deg"] = {
                f"theta_{name}_{axis}": _population_moments(
                    np.degrees(np.arctan2(velocity[:, i], np.abs(velocity[:, axial])))
                ) for i, name in enumerate("xyz") if name != axis
            }
            if axis == "z":
                for name in ("x", "y"):
                    result[f"theta_{name}_deg"] = result["local_transverse_angles_deg"][f"theta_{name}_z"]
                result["angle_unavailable_reason"] = None
    for field, label in (("instrument_time_us", "instrument_time_us"), ("kinetic_energy_eV", "kinetic_energy_eV")):
        result[label] = None
        result[label + "_unavailable_reason"] = "canonical_column_missing"
        if field in rows:
            values = pd.to_numeric(rows[field], errors="coerce").to_numpy(dtype=float)
            if not np.isfinite(values).all():
                raise ValueError(f"checkpoint contains non-finite {field}")
            result[label] = _population_moments(values)
            result[label + "_unavailable_reason"] = None
    return result


def _checkpoint_distribution_summary(
    rows: pd.DataFrame, event: str, *, frame_id: str = "oatof_global_cartesian",
    propagation_axis: str | None = None,
) -> dict[str, Any]:
    """Summarize one detector-blind checkpoint using its local propagation axis."""

    axis = propagation_axis or _CHECKPOINT_AXIAL_AXIS.get(event)
    if axis not in {"x", "y", "z"}:
        raise ValueError("checkpoint propagation axis is invalid")
    if axis is None:
        raise ValueError(f"checkpoint axis is not registered: {event}")
    position_fields = ("x_mm", "y_mm", "z_mm")
    numeric = rows.loc[:, list(position_fields)].apply(pd.to_numeric, errors="coerce")
    if numeric.empty or numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError(f"checkpoint {event} has non-finite position values")
    # Detector crossing is intentionally detector-blind: the detector contract
    # publishes position and TOF, but no post-detector velocity/energy fields.
    # Keep its spatial distribution while reporting angle and z–vz as not
    # available, rather than treating the deliberate omission as bad data.
    phase_space_available = event != "detector_crossing"
    if phase_space_available:
        velocity_fields = ("vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us")
        velocities = rows.loc[:, list(velocity_fields)].apply(pd.to_numeric, errors="coerce")
        if velocities.isna().any().any() or not np.isfinite(velocities.to_numpy()).all():
            raise ValueError(f"checkpoint {event} has non-finite phase-space values")
    else:
        velocities = None
    position = numeric.loc[:, ["x_mm", "y_mm", "z_mm"]].to_numpy(dtype=float)
    axial_index = {"x": 0, "y": 1, "z": 2}[axis]
    transverse = [index for index in range(3) if index != axial_index]
    centered = position - np.median(position, axis=0)
    transverse_radius = np.hypot(centered[:, transverse[0]], centered[:, transverse[1]])
    velocity = None if velocities is None else 1000.0 * velocities.to_numpy(dtype=float)
    axial_speed = None if velocity is None else velocity[:, axial_index]
    transverse_speed = None if velocity is None else np.hypot(velocity[:, transverse[0]], velocity[:, transverse[1]])
    # At the reflectron turning plane axial velocity is exactly zero.  Its
    # direction is undefined, so expose it honestly rather than emitting 90°.
    angle = None if axial_speed is None or np.all(np.abs(axial_speed) <= 1.0e-12) else np.degrees(
        np.arctan2(transverse_speed, np.abs(axial_speed))
    )
    z = position[:, 2]
    vz = None if velocity is None else velocity[:, 2]
    if vz is not None:
        zvz = _phase_space_fit_diagnostics(z, vz)
        if zvz["status"] == "not_computed":
            # Preserve the legacy checkpoint reason while exposing the richer
            # null-valued diagnostics from the common fitting implementation.
            zvz["reason"] = "zero_z_span_or_single_particle"
    else:
        zvz = {
            "status": "not_computed",
            "reason": "detector_blind_or_zero_z_span_or_single_particle",
        }
    return {
        "event": event,
        "integration_frame_components": _integration_component_diagnostics(rows, position, velocity, axis, frame_id=frame_id),
        "particle_count": int(len(rows)),
        "local_propagation_axis": axis,
        "space_mm": {name: _quantiles(position[:, index]) for index, name in enumerate(("x", "y", "z"))},
        "velocity_m_per_s": None if velocity is None else {
            name: _quantiles(velocity[:, index]) for index, name in enumerate(("vx", "vy", "vz"))
        },
        "transverse_radius_mm": _quantiles(transverse_radius),
        "total_off_axis_angle_deg": None if angle is None else _quantiles(angle),
        "z_vz_affine": zvz,
    }


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
    source_region_diagnostic: dict[str, Any] | None,
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
    _cloud(
        ax_b,
        initial,
        "position_x_mm",
        "position_z_mm",
        size=size,
        label="released ions",
        color="#2b8cbe",
    )
    axial_positions = pd.to_numeric(
        initial["position_x_mm"], errors="raise"
    ).to_numpy(dtype=float)
    if not np.isfinite(axial_positions).all():
        raise ValueError("release axial coordinates are non-finite")
    ax_b.set_title(
        "B  Ion release in grounded multipole enclosure\n"
        f"multipole axial full width: {np.ptp(axial_positions):.4g} mm"
    )
    ax_b.set(xlabel="global x (mm)", ylabel="global z (mm)")

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
    if source_region_diagnostic is not None:
        _source_region_longitudinal(ax_d, source_region_diagnostic, oatof, frontend)
    else:
        ax_d.text(
            0.02, 0.02,
            "source-region diagnostic: not applicable\nterminal-handoff continuation",
            transform=ax_d.transAxes, fontsize=7, va="bottom",
        )
    _cloud(ax_d, prepulse, "x_mm", "z_mm", size=size, label="immediately before pulse", color="#fdae61")
    ax_d.set_aspect("equal", adjustable="box")
    ax_d.set(title="D  Ion distribution in accelerator before pulse", xlabel="global x (mm)", ylabel="global z (mm)")

    _cloud(ax_e, accelerator_exit, "x_mm", "y_mm", size=size, label="local accelerator exit", color="#756bb1")
    _accelerator_cross_section(ax_e, oatof, frontend)
    if source_region_diagnostic is not None:
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
        "RF multipole → grounded connector → oaTOF spatial checkpoints\n"
        f"small markers preserve geometry visibility; capability={CAPABILITY_ID}",
        fontsize=12,
    )
    source_metadata: dict[str, Any]
    if source_region_diagnostic is None:
        source_metadata = {
            "status": "NOT_APPLICABLE",
            "reason": "terminal_handoff_continuation_has_no_source_region_checkpoint",
        }
    else:
        source_bounds = _source_region_bounds(source_region_diagnostic)
        source_metadata = {
            "profile_id": source_region_diagnostic["profile_id"],
            "claim_status": source_region_diagnostic["claim_status"],
            "event": source_region_diagnostic["event"],
            "population_basis": source_region_diagnostic["population_basis"],
            "bounds": source_bounds,
            "eligible_count": source_region_diagnostic["eligible_count"],
            "selected_count": source_region_diagnostic["selected_count"],
            "occupancy_fraction": source_region_diagnostic["occupancy_fraction"],
        }
    release_metadata = {
        "coordinate_frame": "oatof_global_cartesian",
        "multipole_axial_axis": "global_x",
        "particle_count": int(len(initial)),
        "multipole_axial_min_mm": float(np.min(axial_positions)),
        "multipole_axial_max_mm": float(np.max(axial_positions)),
        "multipole_axial_full_width_mm": float(np.ptp(axial_positions)),
    }
    return figure, {
        "released": len(initial),
        "handoff": len(handoff),
        "pre_pulse": len(prepulse),
        "accelerator_exit": len(accelerator_exit),
        "detector": len(detector),
        "particle_marker_area_pt2": size,
        "source_region_diagnostic": source_metadata,
        "release_coordinates": release_metadata,
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
        fit_metadata = _phase_space_fit_diagnostics(
            position_values, velocity_values
        ) | {"population_basis": "all_retained_pre_pulse_particles"}
        if fit_metadata["status"] == "computed":
            slope = float(fit_metadata["slope_m_per_s_per_mm"])
            intercept = float(fit_metadata["intercept_m_per_s"])
            r_squared = float(fit_metadata["r_squared"])
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


def write_checkpoint_evolution_outputs(
    checkpoints_path: Path, figure_path: Path, metadata_path: Path, data_path: Path,
    *, frame_id: str = "oatof_global_cartesian", checkpoint_axes: dict[str, str] | None = None,
) -> None:
    """Write detector-blind diagnostics in the explicitly declared native frame."""

    checkpoints = pd.read_csv(checkpoints_path)
    summaries = []
    for event in _CHECKPOINT_AXIAL_AXIS:
        rows = checkpoints.loc[checkpoints["event"].eq(event)]
        if not rows.empty:
            summaries.append(_checkpoint_distribution_summary(
                rows, event, frame_id=frame_id, propagation_axis=(checkpoint_axes or {}).get(event)))
    if not summaries:
        raise ValueError("checkpoint evolution requires at least one registered checkpoint")

    def fit_value(summary: dict[str, Any], *path: str) -> Any:
        value: Any = summary["z_vz_affine"]
        for name in path:
            if not isinstance(value, dict):
                return None
            value = value.get(name)
        return value

    table = pd.DataFrame(
        {
            "event": [item["event"] for item in summaries],
            "particle_count": [item["particle_count"] for item in summaries],
            "local_propagation_axis": [item["local_propagation_axis"] for item in summaries],
            "transverse_radius_p95_mm": [item["transverse_radius_mm"]["p95"] for item in summaries],
            "angle_p95_deg": [None if item["total_off_axis_angle_deg"] is None else item["total_off_axis_angle_deg"]["p95"] for item in summaries],
            "z_vz_residual_rms_m_per_s": [item["z_vz_affine"].get("residual_rms_m_per_s") for item in summaries],
            "z_vz_k_m_per_s_per_mm": [fit_value(item, "slope_m_per_s_per_mm") for item in summaries],
            "z_vz_intercept_m_per_s": [fit_value(item, "intercept_m_per_s") for item in summaries],
            "z_vz_linear_residual_sigma_m_per_s": [fit_value(item, "residual_sigma_m_per_s") for item in summaries],
            "z_vz_linear_residual_max_abs_m_per_s": [fit_value(item, "residual_max_abs_m_per_s") for item in summaries],
            "z_vz_linear_residual_p95_abs_m_per_s": [fit_value(item, "residual_p95_abs_m_per_s") for item in summaries],
            "z_vz_quadratic_coefficient_m_per_s_per_mm2": [fit_value(item, "quadratic_fit", "coefficients_m_per_s", "quadratic_per_mm2") for item in summaries],
            "z_vz_quadratic_residual_sigma_m_per_s": [fit_value(item, "quadratic_fit", "residual_sigma_m_per_s") for item in summaries],
            "z_vz_quadratic_residual_rms_m_per_s": [fit_value(item, "quadratic_fit", "residual_rms_m_per_s") for item in summaries],
            "z_vz_quadratic_relative_linear_residual_rms_reduction": [fit_value(item, "quadratic_fit", "relative_linear_residual_rms_reduction") for item in summaries],
            "z_vz_cubic_coefficient_m_per_s_per_mm3": [fit_value(item, "cubic_fit", "coefficients_m_per_s", "cubic_per_mm3") for item in summaries],
            "z_vz_cubic_residual_sigma_m_per_s": [fit_value(item, "cubic_fit", "residual_sigma_m_per_s") for item in summaries],
            "z_vz_cubic_residual_rms_m_per_s": [fit_value(item, "cubic_fit", "residual_rms_m_per_s") for item in summaries],
            "z_vz_cubic_relative_linear_residual_rms_reduction": [fit_value(item, "cubic_fit", "relative_linear_residual_rms_reduction") for item in summaries],
            "z_vz_cubic_random_residual_sigma_m_per_s": [fit_value(item, "cubic_random_residual", "sigma_m_per_s") for item in summaries],
            "z_vz_cubic_random_residual_rms_m_per_s": [fit_value(item, "cubic_random_residual", "rms_m_per_s") for item in summaries],
        }
    )
    for component in ("x", "y"):
        for moment in ("signed_mean", "population_std"):
            table[f"theta_{component}_{moment}_deg"] = [
                None if item["integration_frame_components"][f"theta_{component}_deg"] is None
                else item["integration_frame_components"][f"theta_{component}_deg"][moment]
                for item in summaries
            ]
    for component in ("x", "z"):
        for moment in ("signed_mean", "population_std"):
            table[f"theta_{component}_y_{moment}_deg"] = [
                None if item["local_propagation_axis"] != "y" or item["integration_frame_components"]["local_transverse_angles_deg"] is None
                else item["integration_frame_components"]["local_transverse_angles_deg"][f"theta_{component}_y"][moment]
                for item in summaries
            ]
    for component in "xyz":
        table[f"sigma_{component}_mm"] = [item["integration_frame_components"]["space_population_sigma_mm"][component] for item in summaries]
    for key in ("instrument_time_us", "kinetic_energy_eV"):
        for moment in ("signed_mean", "population_std"):
            table[f"{key}_{moment}"] = [None if item["integration_frame_components"][key] is None else item["integration_frame_components"][key][moment] for item in summaries]
    table["sigma_t_ns"] = 1000.0 * pd.to_numeric(table["instrument_time_us_population_std"], errors="coerce")
    figure, axes = plt.subplots(4, 2, figsize=(13.5, 14.0), constrained_layout=True)
    x = np.arange(len(table))
    labels = table["event"].str.replace("_", "\n", regex=False)
    series = (
        (axes[0, 0], "particle_count", "retained particle count"),
        (axes[0, 1], "transverse_radius_p95_mm", "transverse radius P95 (mm)"),
        (axes[1, 0], "angle_p95_deg", "off-axis angle P95 (deg)"),
        (axes[1, 1], "z_vz_residual_rms_m_per_s", "z–vz residual RMS (m/s)"),
    )
    for axis, column, ylabel in series:
        values = table[column].to_numpy(dtype=float)
        axis.plot(x, values, marker="o", linewidth=1.4, color="#1b9e77")
        axis.set(ylabel=ylabel, xticks=x, xticklabels=labels)
        axis.tick_params(axis="x", labelsize=7)
        axis.grid(alpha=0.18)
    exit_rows = checkpoints.loc[checkpoints["event"].eq("local_accelerator_exit")]
    exit_summary = next((item for item in summaries if item["event"] == "local_accelerator_exit"), None)
    for ax, component in zip(axes[2], ("x", "y"), strict=True):
        available = exit_summary is not None and exit_summary["integration_frame_components"][f"theta_{component}_deg"] is not None
        if available:
            angles = np.degrees(np.arctan2(exit_rows[f"v{component}_mm_per_us"].to_numpy(dtype=float), np.abs(exit_rows["vz_mm_per_us"].to_numpy(dtype=float))))
            ax.scatter(exit_rows[f"{component}_mm"], angles, s=marker_area(len(exit_rows)), color="#0072B2", marker="o")
        else:
            ax.text(0.5, 0.5, "Exit component angle unavailable", ha="center", va="center", transform=ax.transAxes)
        ax.set(xlabel=f"{frame_id}: {component} (mm)" if frame_id != "oatof_global_cartesian" else f"Integration global {component} (mm)", ylabel=f"Signed theta_{component} (deg)", title=f"OA exit: all observed IDs, N={len(exit_rows)}; " + ("native MR coordinates" if frame_id == "mrtof_global_cartesian" else "MR mapping pending"))
        ax.grid(alpha=0.16)
    time_axis, arrival_axis = axes[3]
    time_axis.plot(x, table["sigma_t_ns"], marker="s", linewidth=1.4, color="#D55E00")
    time_axis.set(ylabel="Arrival-time sigma (ns, ddof=0)", xticks=x, xticklabels=labels,
                  title="Each checkpoint's observed population; counts shown above")
    time_axis.tick_params(axis="x", labelsize=7)
    time_axis.grid(alpha=0.16)
    arrival = None if exit_summary is None else exit_summary["integration_frame_components"]["instrument_time_us"]
    if arrival is not None:
        # ECDF retains every exit, including tails, without bins or a Gaussian fit.
        delta_t_ns = 1000.0 * (np.sort(exit_rows["instrument_time_us"].to_numpy(dtype=float)) - arrival["signed_mean"])
        cumulative_fraction = np.arange(1, len(delta_t_ns) + 1) / len(delta_t_ns)
        arrival_axis.step(delta_t_ns, cumulative_fraction, where="post", color="#0072B2", linewidth=1.4)
        arrival_axis.scatter(delta_t_ns, cumulative_fraction, s=marker_area(len(delta_t_ns)), color="#0072B2")
        arrival_axis.set_title(f"OA exit: N={len(delta_t_ns)}; sigma_t={1000.0 * arrival['population_std']:.6g} ns")
    else:
        arrival_axis.text(.5, .5, "Exit arrival times unavailable", ha="center", va="center", transform=arrival_axis.transAxes)
    arrival_axis.set(xlabel="Exit arrival time minus exit mean (ns)", ylabel="Cumulative fraction of observed exits", ylim=(0, 1.02))
    arrival_axis.grid(alpha=0.16)
    figure.suptitle(
        "Detector-blind accelerator/checkpoint phase-space evolution\n"
        f"capability={PHASE_SPACE_CAPABILITY_ID}", fontsize=12,
    )
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(figure_path, dpi=190)
    plt.close(figure)
    table.to_csv(data_path, index=False, lineterminator="\n")
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "role": "rf_oatof_accelerator_checkpoint_evolution_metadata",
                "capability_id": PHASE_SPACE_CAPABILITY_ID,
                "status": "success",
                "selection_uses_detector_outcome": False,
                "checkpoints": summaries,
                "exit_phase_portrait": {"event": "local_accelerator_exit", "particle_ids": exit_rows["particle_id"].tolist(), "population_basis": "all_observed_exit_ids_not_detector_selected", "frame": frame_id, "mr_frame_mapping": "native_mr_frame" if frame_id == "mrtof_global_cartesian" else "not_bound", "angle_definition": "atan2(v_component, abs(v_z)); signed degrees"},
                "time_panels": {"checkpoint_sigma_column": "sigma_t_ns", "standard_deviation_ddof": 0,
                    "checkpoint_population_basis": "each_checkpoint_observed_ids; not a paired cohort",
                    "exit_distribution": "ECDF of all observed exits; no filtering, bins, smoothing or Gaussian fit",
                    "exit_time_transform": "1000 * (instrument_time_us - exit_population_mean_us)",
                    "exit_mean_time_us": None if arrival is None else arrival["signed_mean"],
                    "exit_particle_ids": exit_rows["particle_id"].tolist(),
                    "scope": "Recorded plane-crossing times; not a simultaneous cloud, downstream time focus or MR resolution"},
                "data": str(data_path.resolve()),
                "figure": str(figure_path.resolve()),
            }, indent=2,
        ) + "\n", encoding="utf-8", newline="\n",
    )


def build_local_shared_time_figure(
    active_rows: pd.DataFrame, status_counts: list[dict[str, Any]], *, frame_id: str,
) -> tuple[plt.Figure, np.ndarray]:
    """Display only actual active states; lifecycle counts come from analysis.

    This is a coordinate scatter, not a field or trajectory interpolation.
    Its caller declares the observer frame and any display-time subset.
    """
    if not frame_id or not status_counts:
        raise ValueError("shared-time figure requires a frame and declared time panels")
    figure, axes = plt.subplots(2, len(status_counts), figsize=(3.5 * len(status_counts), 6.2),
                                squeeze=False, sharex=True, sharey="row", constrained_layout=True)
    for column, counts in enumerate(status_counts):
        time = float(counts["instrument_time_us"])
        # Census validates the actual clock against this declared target; retain
        # the native clock and state while grouping by its requested observation.
        rows = active_rows.loc[active_rows["requested_time_us"].eq(time)]
        if len(rows) != counts["active"]:
            raise ValueError("shared-time plotted population differs from the census")
        for ax, transverse in zip(axes[:, column], ("x", "y"), strict=True):
            if len(rows):
                ax.scatter(rows["z_mm"], rows[f"{transverse}_mm"], s=marker_area(len(rows)),
                           color="#0072B2", marker="o")
            else:
                ax.text(.5, .5, "No active particles", transform=ax.transAxes, ha="center")
            ax.set(xlabel=f"{frame_id}: z (mm)", ylabel=f"{frame_id}: {transverse} (mm)")
            ax.set_aspect("auto")
            ax.grid(alpha=.15)
        axes[0, column].set_title(f"t = {time:.6g} us; active N={counts['active']}\n"
            f"Not born {counts['not_born']}; exited {counts['already_exit']}\n"
            f"Lost {counts['already_loss']}; unsupported {counts['numerical_unsupported']}", fontsize=9)
    figure.suptitle("Actual shared-clock active distributions; common axis limits\nDisplay aspect ratio only; terminal positions are not carried forward")
    return figure, axes


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
    parser.add_argument("--evolution-output", type=Path)
    parser.add_argument("--evolution-metadata", type=Path)
    parser.add_argument("--evolution-data", type=Path)
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
    if source_region_diagnostic is not None and not isinstance(
        source_region_diagnostic, dict
    ):
        parser.error("summary source-region diagnostic is invalid")
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
    evolution_outputs = (args.evolution_output, args.evolution_metadata, args.evolution_data)
    if any(value is None for value in evolution_outputs) and any(value is not None for value in evolution_outputs):
        parser.error("checkpoint-evolution figure, metadata and data must be supplied together")
    if all(value is not None for value in evolution_outputs):
        assert args.evolution_output is not None
        assert args.evolution_metadata is not None
        assert args.evolution_data is not None
        write_checkpoint_evolution_outputs(
            args.checkpoints, args.evolution_output, args.evolution_metadata, args.evolution_data,
        )
    print(f"SINGLE_FLIGHT_SIX_PANEL=PASS FIGURE={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
