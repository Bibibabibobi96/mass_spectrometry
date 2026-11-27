"""Recorded RF/OA/TOF checkpoint summaries and detector-blind figures.

Protocol event axes and the original numerical/report conventions are retained.
This adapter consumes recorded data only and never launches a solver.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PHASE_SPACE_CAPABILITY_ID = "rf_oatof_accelerator_phase_space_evolution_v2"


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


def marker_area(particle_count: int) -> float:
    """Keep N=1000 clouds legible without hiding geometry or source bounds."""

    return max(2.0, min(10.0, 44.0 / max(particle_count, 1) ** 0.5))


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
