"""Compare registered RF-exit and pre-pulse oaTOF states by particle ID."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import numpy as np
import pandas as pd

from common.contracts import particle_physics
from common.contracts.rigid_transform import (
    FramedPosition,
    FramedVector,
    RigidTransform,
)

try:
    from plot_shared_pulse_geometry_snapshot import (
        add_accelerator_geometry_outlines,
        add_rf_s2_geometry_outlines,
        particle_marker_areas,
        registered_chain_geometry,
    )
except ModuleNotFoundError:
    from projects.rf_quadrupole_collision_cooling.analysis.plot_shared_pulse_geometry_snapshot import (
        add_accelerator_geometry_outlines,
        add_rf_s2_geometry_outlines,
        particle_marker_areas,
        registered_chain_geometry,
    )


AXES = ("x", "y", "z")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPATIAL_REGISTRATION = (
    PROJECT_ROOT / "config" / "resolved_rf_to_oatof_s2_spatial_registration.json"
)
DEFAULT_RF_RESOLVED_GEOMETRY = PROJECT_ROOT / "config" / "resolved_design_official.json"


def load_json(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object."""
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    """Return the uppercase SHA-256 identity of one input file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _require_columns(data: pd.DataFrame, required: set[str], role: str) -> None:
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"{role} is missing columns: {', '.join(missing)}")
    if data.empty:
        raise ValueError(f"{role} is empty")
    if data["particle_id"].duplicated().any():
        raise ValueError(f"{role} contains duplicate particle IDs")


def _instrument_to_target_transform(
    registration: dict[str, Any],
) -> RigidTransform:
    pose = registration["component_poses"]["oatof_global"]
    return RigidTransform.from_contract(pose).inverse()


def _registered_local_state(data: pd.DataFrame, registration: dict[str, Any],
                            position_prefix: str, velocity_prefix: str) -> pd.DataFrame:
    """Transform an instrument-frame state into the registered oaTOF local frame."""
    expected_frame = registration["instrument_frame_id"]
    if "frame_id" in data and not data["frame_id"].eq(expected_frame).all():
        raise ValueError("checkpoint frame_id differs from the S2 instrument frame")
    positions = data[[f"{position_prefix}{axis}_mm" for axis in AXES]].to_numpy(float)
    velocities = data[[f"{velocity_prefix}{axis}_m_s" for axis in AXES]].to_numpy(float)
    if not np.isfinite(positions).all() or not np.isfinite(velocities).all():
        raise ValueError("checkpoint contains non-finite position or velocity")
    transform = _instrument_to_target_transform(registration)
    result = data.copy()
    local_positions = np.asarray([
        transform.transform_position(
            FramedPosition(expected_frame, tuple(position))
        ).coordinates_mm
        for position in positions
    ])
    local_velocities = np.asarray([
        transform.transform_vector(
            FramedVector(expected_frame, tuple(velocity), "polar")
        ).components
        for velocity in velocities
    ])
    for index, axis in enumerate(AXES):
        result[f"local_{axis}_mm"] = local_positions[:, index]
        result[f"local_v{axis}_m_s"] = local_velocities[:, index]
    return result


def _registered_local_positions(data: pd.DataFrame,
                                registration: dict[str, Any]) -> pd.DataFrame:
    expected_frame = registration["instrument_frame_id"]
    if "frame_id" in data and not data["frame_id"].eq(expected_frame).all():
        raise ValueError("terminal frame_id differs from the S2 instrument frame")
    positions = data[[f"{axis}_mm" for axis in AXES]].to_numpy(float)
    if not np.isfinite(positions).all():
        raise ValueError("terminal census contains non-finite loss positions")
    transform = _instrument_to_target_transform(registration)
    result = data.copy()
    local_positions = np.asarray([
        transform.transform_position(
            FramedPosition(expected_frame, tuple(position))
        ).coordinates_mm
        for position in positions
    ])
    for index, axis in enumerate(AXES):
        result[f"terminal_local_{axis}_mm"] = local_positions[:, index]
    return result


def _energy_eV(data: pd.DataFrame) -> np.ndarray:
    masses = data["mass_amu"].to_numpy(float)
    velocities = data[[f"local_v{axis}_m_s" for axis in AXES]].to_numpy(float)
    return np.fromiter(
        (
            particle_physics.kinetic_energy_ev(float(mass), *velocity)
            for mass, velocity in zip(masses, velocities, strict=True)
        ),
        dtype=float,
        count=len(data),
    )


def _axis_distribution(data: pd.DataFrame, prefix: str, unit: str) -> dict[str, Any]:
    values: dict[str, Any] = {"unit": unit}
    for axis in AXES:
        sample = data[f"{prefix}{axis}{unit}"].to_numpy(float)
        centroid = float(np.mean(sample))
        deviation = sample - centroid
        values[axis] = {
            "centroid": centroid,
            "rms_about_centroid": float(np.sqrt(np.mean(deviation ** 2))),
            "p95_abs_about_centroid": float(np.percentile(np.abs(deviation), 95)),
        }
    return values


def _sample_covariance(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2:
        return None
    return float(np.cov(left, right, ddof=1)[0, 1])


def _phase_space_metrics(data: pd.DataFrame, frame_id: str) -> dict[str, Any]:
    positions = data[[f"local_{axis}_mm" for axis in AXES]].to_numpy(float)
    velocities = data[[f"local_v{axis}_m_s" for axis in AXES]].to_numpy(float)
    covariance = np.full((3, 3), np.nan)
    if len(data) >= 2:
        covariance = np.cov(positions.T, velocities.T, ddof=1)[:3, 3:]
    projected: dict[str, Any] = {}
    for index, axis in enumerate(AXES):
        position = positions[:, index]
        velocity = velocities[:, index]
        cov = _sample_covariance(position, velocity)
        emittance = None
        if cov is not None:
            determinant = np.var(position, ddof=1) * np.var(velocity, ddof=1) - cov ** 2
            emittance = float(np.sqrt(max(0.0, determinant)))
        projected[axis] = {"position_velocity_rms_emittance_mm_m_per_s": emittance}
        if axis != "x" and np.all(velocities[:, 0] > 0) and len(data) >= 2:
            slope = velocity / velocities[:, 0]
            slope_cov = _sample_covariance(position, slope)
            determinant = np.var(position, ddof=1) * np.var(slope, ddof=1) - slope_cov ** 2
            projected[axis]["geometric_rms_emittance_mm_rad"] = float(
                np.sqrt(max(0.0, determinant)))
    return {
        "covariance_r_v_mm_m_per_s": {
            "row_axes": list(AXES), "column_axes": list(AXES),
            "row_frame_id": frame_id, "column_frame_id": frame_id,
            "row_unit": "mm", "column_unit": "m/s",
            "values": [[None if not np.isfinite(value) else float(value) for value in row]
                       for row in covariance],
        },
        "projected_emittance": projected,
    }


def summarize_checkpoint(
    data: pd.DataFrame, source: dict[str, Any], frame_id: str
) -> dict[str, Any] | None:
    """Compute full-sample beam metrics without filtering its tails."""
    if data.empty:
        return None
    energy = _energy_eV(data)
    vx = data["local_vx_m_s"].to_numpy(float)
    vy = data["local_vy_m_s"].to_numpy(float)
    vz = data["local_vz_m_s"].to_numpy(float)
    if np.any(vx <= 0):
        raise ValueError("checkpoint direction metrics require positive +x guide velocity")
    theta_y = np.degrees(np.arctan2(vy, vx))
    theta_z = np.degrees(np.arctan2(vz, np.hypot(vx, vy)))
    total_angle = np.degrees(np.arctan2(np.hypot(vy, vz), vx))
    inside = np.logical_and.reduce([
        np.abs(data[f"local_{axis}_mm"].to_numpy(float)
               - float(source[f"center_{axis}_mm"]))
        <= float(source[f"size_{axis}_mm"]) / 2 + 1e-12 for axis in AXES
    ])
    result = {
        "particles": int(len(data)),
        "position": _axis_distribution(data, "local_", "_mm"),
        "velocity": _axis_distribution(data, "local_v", "_m_s"),
        "energy_eV": {
            "mean": float(np.mean(energy)),
            "sample_std": float(np.std(energy, ddof=1)) if len(energy) >= 2 else None,
        },
        "direction_divergence_deg": {
            "theta_y_mean": float(np.mean(theta_y)),
            "theta_y_rms": float(np.sqrt(np.mean(theta_y ** 2))),
            "theta_z_mean": float(np.mean(theta_z)),
            "theta_z_rms": float(np.sqrt(np.mean(theta_z ** 2))),
            "total_rms": float(np.sqrt(np.mean(total_angle ** 2))),
            "total_p95": float(np.percentile(np.abs(total_angle), 95)),
        },
        "ideal_reference_volume": {
            "inside": int(np.sum(inside)),
            "fraction": float(np.mean(inside)),
            "denominator": int(len(data)),
        },
    }
    result.update(_phase_space_metrics(data, frame_id))
    return result


def _prepare_states(exit_state: pd.DataFrame, capture: pd.DataFrame,
                    terminal: pd.DataFrame, schedule: dict[str, Any],
                    registration: dict[str, Any]) -> tuple[pd.DataFrame, float, set[int]]:
    exit_required = {
        "particle_id", "frame_id", "clock_epoch_id", "instrument_time_us", "mass_amu",
        "charge_state", "position_x_mm", "position_y_mm", "position_z_mm",
        "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s",
    }
    capture_required = {
        "particle_id", "frame_id", "clock_epoch_id", "instrument_time_us",
        "x_mm", "y_mm", "z_mm",
        "vx_m_s", "vy_m_s", "vz_m_s",
    }
    terminal_required = {
        "particle_id", "frame_id", "clock_epoch_id",
        "event", "status", "terminal_reason",
    }
    _require_columns(exit_state, exit_required, "source-exit state")
    _require_columns(capture, capture_required, "pulse-left-limit state")
    _require_columns(terminal, terminal_required, "terminal census")
    source_ids = set(exit_state["particle_id"].astype(int))
    if set(terminal["particle_id"].astype(int)) != source_ids:
        raise ValueError("terminal census must contain every source-exit particle exactly once")
    if not set(capture["particle_id"].astype(int)).issubset(source_ids):
        raise ValueError("pulse-left-limit state contains an unknown particle ID")
    if exit_state["clock_epoch_id"].nunique() != 1:
        raise ValueError("source-exit state contains multiple clock epochs")
    clock_epoch = exit_state["clock_epoch_id"].iloc[0]
    if not terminal["frame_id"].eq(registration["instrument_frame_id"]).all():
        raise ValueError("terminal census frame differs from the S2 instrument frame")
    if not terminal["clock_epoch_id"].eq(clock_epoch).all():
        raise ValueError("terminal census clock epoch changed")
    pulse_time = float(schedule["derived_pulse_time_us"])
    if not np.allclose(capture["instrument_time_us"], pulse_time, rtol=0, atol=1e-9):
        raise ValueError("pulse-left-limit rows do not share the scheduled global time")
    if "active_at_pulse" in capture and not pd.to_numeric(
            capture["active_at_pulse"], errors="raise").astype(bool).all():
        raise ValueError("pulse-left-limit state contains an inactive particle")
    cohort = {int(value) for value in schedule["selected_cohort"]["particle_ids"]}
    if not cohort.issubset(source_ids):
        raise ValueError("pulse schedule cohort contains an unknown particle ID")

    exit_local = _registered_local_state(
        exit_state, registration, "position_", "velocity_")
    capture_full = capture.merge(
        exit_state[["particle_id", "mass_amu", "charge_state"]],
        on="particle_id", how="left", validate="one_to_one")
    capture_local = _registered_local_state(capture_full, registration, "", "v")
    if not capture_local["clock_epoch_id"].eq(clock_epoch).all():
        raise ValueError("checkpoint clock epoch changed")

    table = exit_local[[
        "particle_id", "instrument_time_us", "mass_amu", "charge_state",
        *[f"local_{axis}_mm" for axis in AXES],
        *[f"local_v{axis}_m_s" for axis in AXES],
    ]].rename(columns={
        "instrument_time_us": "exit_instrument_time_us",
        **{f"local_{axis}_mm": f"exit_local_{axis}_mm" for axis in AXES},
        **{f"local_v{axis}_m_s": f"exit_local_v{axis}_m_s" for axis in AXES},
    })
    delta_us = pulse_time - table["exit_instrument_time_us"]
    if (delta_us < 0).any():
        raise ValueError("pulse time precedes a source-exit event")
    for axis in AXES:
        table[f"ballistic_local_{axis}_mm"] = (
            table[f"exit_local_{axis}_mm"]
            + table[f"exit_local_v{axis}_m_s"] * delta_us / 1000.0)
        table[f"ballistic_local_v{axis}_m_s"] = table[f"exit_local_v{axis}_m_s"]
    capture_columns = ["particle_id", *[f"local_{axis}_mm" for axis in AXES],
                       *[f"local_v{axis}_m_s" for axis in AXES]]
    capture_columns += [name for name in ("inside_oatof_ideal_reference_volume",
                                         "active_at_pulse") if name in capture_local]
    capture_local = capture_local[capture_columns].rename(columns={
        **{f"local_{axis}_mm": f"capture_local_{axis}_mm" for axis in AXES},
        **{f"local_v{axis}_m_s": f"capture_local_v{axis}_m_s" for axis in AXES},
    })
    table = table.merge(capture_local, on="particle_id", how="left", validate="one_to_one")
    terminal_columns = ["particle_id", "event", "status", "terminal_reason"]
    if all(f"{axis}_mm" in terminal for axis in AXES):
        terminal = _registered_local_positions(terminal, registration)
        terminal_columns += [f"terminal_local_{axis}_mm" for axis in AXES]
    table = table.merge(terminal[terminal_columns], on="particle_id", how="left",
                        validate="one_to_one")
    table["scheduler_cohort"] = table["particle_id"].astype(int).isin(cohort)
    table["active_at_pulse"] = table["capture_local_x_mm"].notna()
    for axis in AXES:
        table[f"capture_minus_ballistic_{axis}_mm"] = (
            table[f"capture_local_{axis}_mm"] - table[f"ballistic_local_{axis}_mm"])
        table[f"capture_minus_ballistic_v{axis}_m_s"] = (
            table[f"capture_local_v{axis}_m_s"]
            - table[f"ballistic_local_v{axis}_m_s"])
    return table, pulse_time, cohort


def _validate_s2_aperture(
    s2_contract: dict[str, Any], geometry: dict[str, Any]
) -> None:
    aperture = s2_contract["passive_connector_geometry"][
        "downstream_entry_aperture"
    ]
    center = np.asarray(aperture["center_mm"], dtype=float)
    expected = np.asarray([
        geometry["target_entry_center"][axis] for axis in AXES
    ])
    if (
        aperture.get("shape") != "rectangle"
        or not np.allclose(center, expected, rtol=0, atol=1e-12)
        or not np.isclose(
            float(aperture["full_width_y_mm"]),
            float(geometry["port_width_y"]), rtol=0, atol=1e-12,
        )
        or not np.isclose(
            float(aperture["full_height_z_mm"]),
            float(geometry["port_height_z"]), rtol=0, atol=1e-12,
        )
    ):
        raise ValueError("S2 aperture differs from shared physical-port authority")


def _prepare_chain_states(
    table: pd.DataFrame,
    s2_entry: pd.DataFrame,
    local_exit: pd.DataFrame,
    row_map: pd.DataFrame,
    downstream: pd.DataFrame,
    registration: dict[str, Any],
    geometry: dict[str, Any],
    clock_epoch_id: str,
) -> pd.DataFrame:
    """Join all physical checkpoints and assign exhaustive final outcomes."""
    s2_required = {
        "particle_id", "frame_id", "clock_epoch_id", "first_forward_oatof_entry",
        "position_x_mm", "position_y_mm", "position_z_mm",
        "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s",
    }
    local_required = {
        "particle_id", "frame_id", "clock_epoch_id",
        "position_x_mm", "position_y_mm", "position_z_mm",
        "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s",
    }
    map_required = {"solver_row_index", "particle_id"}
    downstream_required = {
        "Ion", "InstrumentTimeUs", "XMm", "YMm", "Hit",
    }
    _require_columns(s2_entry, s2_required, "S2 oa-entry state")
    _require_columns(local_exit, local_required, "S3 local-exit state")
    _require_columns(row_map, map_required, "SIMION row map")
    missing_downstream = downstream_required - set(downstream.columns)
    if missing_downstream or downstream.empty:
        raise ValueError(
            "SIMION downstream state is missing columns: "
            + ", ".join(sorted(missing_downstream))
        )
    source_ids = set(table["particle_id"].astype(int))
    if set(s2_entry["particle_id"].astype(int)) != source_ids:
        raise ValueError("S2 oa-entry census must contain every RF-exit ID")
    for role, state in (("S2 oa-entry", s2_entry), ("S3 local-exit", local_exit)):
        if (
            not state["frame_id"].eq(registration["instrument_frame_id"]).all()
            or not state["clock_epoch_id"].eq(clock_epoch_id).all()
        ):
            raise ValueError(f"{role} frame or clock epoch changed")

    s2_local = _registered_local_state(
        s2_entry, registration, "position_", "velocity_"
    )
    entry_mask = pd.to_numeric(
        s2_local["first_forward_oatof_entry"], errors="raise"
    ).astype(bool)
    entry = s2_local.loc[entry_mask, [
        "particle_id", *[f"local_{axis}_mm" for axis in AXES]
    ]].rename(columns={
        **{f"local_{axis}_mm": f"s2_entry_local_{axis}_mm" for axis in AXES},
    })
    target = geometry["target_entry_center"]
    if not np.allclose(
        entry["s2_entry_local_x_mm"], float(target["x"]), rtol=0, atol=1e-9
    ):
        raise ValueError("S2 oa-entry positions do not lie on the physical plane")
    inside = (
        (entry["s2_entry_local_y_mm"] - float(target["y"])).abs()
        <= float(geometry["port_width_y"]) / 2 + 1e-12
    ) & (
        (entry["s2_entry_local_z_mm"] - float(target["z"])).abs()
        <= float(geometry["port_height_z"]) / 2 + 1e-12
    )
    if not inside.all():
        raise ValueError("S2 transmitted entry lies outside the physical aperture")
    table = table.merge(entry, on="particle_id", how="left", validate="one_to_one")
    table["inside_physical_aperture_at_s2_entry"] = table[
        "s2_entry_local_x_mm"
    ].notna()

    local = _registered_local_state(
        local_exit, registration, "position_", "velocity_"
    )[["particle_id", *[f"local_{axis}_mm" for axis in AXES]]].rename(columns={
        **{f"local_{axis}_mm": f"local_exit_local_{axis}_mm" for axis in AXES},
    })
    local_ids = set(local["particle_id"].astype(int))
    active_ids = set(table.loc[table["active_at_pulse"], "particle_id"].astype(int))
    if not local_ids.issubset(active_ids):
        raise ValueError("S3 local-exit IDs are not a subset of pulse-active IDs")
    table = table.merge(local, on="particle_id", how="left", validate="one_to_one")
    table["reached_local_accelerator_exit"] = table[
        "local_exit_local_x_mm"
    ].notna()

    if row_map["solver_row_index"].duplicated().any() or row_map["particle_id"].duplicated().any():
        raise ValueError("SIMION row map identities are not unique")
    solver_to_particle = dict(zip(
        pd.to_numeric(row_map["solver_row_index"], errors="raise").astype(int),
        pd.to_numeric(row_map["particle_id"], errors="raise").astype(int),
        strict=True,
    ))
    if set(solver_to_particle.values()) != local_ids:
        raise ValueError("SIMION row map differs from S3 local-exit IDs")
    downstream = downstream.copy()
    downstream["solver_row_index"] = pd.to_numeric(
        downstream["Ion"], errors="raise"
    ).astype(int)
    if downstream["solver_row_index"].duplicated().any():
        raise ValueError("SIMION downstream state contains duplicate solver rows")
    if set(downstream["solver_row_index"]) != set(solver_to_particle):
        raise ValueError("SIMION downstream rows differ from the frozen row map")
    downstream["particle_id"] = downstream["solver_row_index"].map(solver_to_particle)
    downstream["downstream_detector_crossing"] = np.isfinite(pd.to_numeric(
        downstream["InstrumentTimeUs"], errors="coerce"
    ))
    downstream["downstream_detector_hit"] = downstream["Hit"].astype(str).str.lower().eq("true")
    if (downstream["downstream_detector_hit"] & ~downstream["downstream_detector_crossing"]).any():
        raise ValueError("SIMION detector hit lacks a finite detector crossing")
    downstream["detector_plane_x_mm"] = pd.to_numeric(
        downstream["XMm"], errors="coerce"
    ) - float(geometry["detector_center_x"])
    downstream["detector_plane_y_mm"] = pd.to_numeric(
        downstream["YMm"], errors="coerce"
    ) - float(geometry["detector_center_y"])
    table = table.merge(downstream[[
        "particle_id", "downstream_detector_crossing", "downstream_detector_hit",
        "detector_plane_x_mm", "detector_plane_y_mm",
    ]], on="particle_id", how="left", validate="one_to_one")
    table[["downstream_detector_crossing", "downstream_detector_hit"]] = table[[
        "downstream_detector_crossing", "downstream_detector_hit"
    ]].fillna(False).astype(bool)

    entry_ids = set(table.loc[
        table["inside_physical_aperture_at_s2_entry"], "particle_id"
    ].astype(int))
    if not active_ids.issubset(entry_ids):
        raise ValueError("pulse-active IDs are not a subset of S2 oa-entry IDs")
    conditions = [
        ~table["inside_physical_aperture_at_s2_entry"],
        table["inside_physical_aperture_at_s2_entry"] & ~table["active_at_pulse"],
        table["active_at_pulse"] & ~table["reached_local_accelerator_exit"],
        table["reached_local_accelerator_exit"] & table["downstream_detector_hit"],
        table["reached_local_accelerator_exit"] & ~table["downstream_detector_hit"],
    ]
    labels = [
        "physical_port_wall_loss", "pre_pulse_loss", "active_local_exit_loss",
        "detector_hit", "local_exit_without_detector_hit",
    ]
    memberships = np.column_stack([condition.to_numpy(bool) for condition in conditions])
    if not np.sum(memberships, axis=1).astype(int).tolist() == [1] * len(table):
        bad_ids = table.loc[np.sum(memberships, axis=1) != 1, "particle_id"].tolist()
        raise ValueError(f"particle outcomes are not exhaustive: particle_ids={bad_ids}")
    table["particle_outcome"] = np.select(conditions, labels, default="unclassified")
    if table["particle_outcome"].eq("unclassified").any():
        raise ValueError("particle outcome classification left unclassified rows")
    return table


def _state_view(table: pd.DataFrame, state: str, mask: pd.Series) -> pd.DataFrame:
    columns = ["particle_id", "mass_amu", "charge_state"]
    result = table.loc[mask, columns].copy()
    for axis in AXES:
        result[f"local_{axis}_mm"] = table.loc[mask, f"{state}_local_{axis}_mm"]
        result[f"local_v{axis}_m_s"] = table.loc[mask, f"{state}_local_v{axis}_m_s"]
    return result


def _residual_metrics(table: pd.DataFrame) -> dict[str, Any]:
    matched = table[table["active_at_pulse"]]
    result: dict[str, Any] = {"matched_particles": int(len(matched))}
    for quantity, suffix in (("position", "_mm"), ("velocity", "_m_s")):
        axes: dict[str, Any] = {"unit": suffix.removeprefix("_")}
        for axis in AXES:
            column = (f"capture_minus_ballistic_{axis}_mm" if quantity == "position"
                      else f"capture_minus_ballistic_v{axis}_m_s")
            values = matched[column].to_numpy(float)
            axes[axis] = {
                "mean": float(np.mean(values)),
                "rms": float(np.sqrt(np.mean(values ** 2))),
                "p95_abs": float(np.percentile(np.abs(values), 95)),
            }
        result[quantity] = axes
    return result


def analyze_checkpoints(exit_path: Path, capture_path: Path, terminal_path: Path,
                        s2_entry_path: Path, local_exit_path: Path,
                        row_map_path: Path, downstream_path: Path,
                        schedule_path: Path, baseline_path: Path, s2_path: Path,
                        joint_path: Path, contract_path: Path,
                        registration_path: Path = DEFAULT_SPATIAL_REGISTRATION,
                        rf_resolved_path: Path = DEFAULT_RF_RESOLVED_GEOMETRY,
                        ) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    """Return metrics, the full-ID comparison table and plotting geometry."""
    contract = load_json(contract_path)
    if contract.get("schema_version") != 2:
        raise ValueError("checkpoint diagnostic contract schema is invalid")
    exit_state = pd.read_csv(exit_path)
    capture = pd.read_csv(capture_path)
    terminal = pd.read_csv(terminal_path)
    s2_entry = pd.read_csv(s2_entry_path)
    local_exit = pd.read_csv(local_exit_path)
    row_map = pd.read_csv(row_map_path)
    downstream = pd.read_csv(downstream_path)
    schedule = load_json(schedule_path)
    baseline = load_json(baseline_path)
    s2_contract = load_json(s2_path)
    joint = load_json(joint_path)
    registration = load_json(registration_path)
    rf_resolved = load_json(rf_resolved_path)
    if registration.get("role") != "resolved_spatial_registration_do_not_edit":
        raise ValueError("checkpoint spatial registration is not authoritative")
    geometry = registered_chain_geometry(
        baseline, joint, registration, rf_resolved, s2_contract
    )
    _validate_s2_aperture(s2_contract, geometry)
    table, pulse_time, cohort = _prepare_states(
        exit_state, capture, terminal, schedule, registration)
    clock_epoch_id = str(exit_state["clock_epoch_id"].iloc[0])
    table = _prepare_chain_states(
        table, s2_entry, local_exit, row_map, downstream,
        registration, geometry, clock_epoch_id,
    )
    source = baseline["particle_source"]
    all_mask = pd.Series(True, index=table.index)
    cohort_mask = table["scheduler_cohort"]
    active_mask = table["active_at_pulse"]
    groups = {
        "exit_all": summarize_checkpoint(
            _state_view(table, "exit", all_mask), source,
            contract["frame_contract"]["analysis_frame"],
        ),
        "ballistic_all_exit": summarize_checkpoint(
            _state_view(table, "ballistic", all_mask), source,
            contract["frame_contract"]["analysis_frame"],
        ),
        "ballistic_scheduler_cohort": summarize_checkpoint(
            _state_view(table, "ballistic", cohort_mask), source,
            contract["frame_contract"]["analysis_frame"],
        ),
        "capture_all_active": summarize_checkpoint(
            _state_view(table, "capture", active_mask), source,
            contract["frame_contract"]["analysis_frame"],
        ),
        "capture_scheduler_cohort": summarize_checkpoint(
            _state_view(table, "capture", active_mask & cohort_mask), source,
            contract["frame_contract"]["analysis_frame"],
        ),
    }
    loss_counts = (table.loc[~active_mask].groupby(
        ["event", "terminal_reason"], dropna=False).size())
    metrics = {
        "schema_version": 1,
        "role": "rf_to_oatof_same_id_checkpoint_diagnostic",
        "status": "PASS",
        "analysis_frame": contract["frame_contract"]["analysis_frame"],
        "input_frame": registration["instrument_frame_id"],
        "clock_epoch_id": clock_epoch_id,
        "pulse_instrument_time_us": pulse_time,
        "state_time_semantics": "capture is the left limit immediately before t_pulse",
        "population_counts": {
            "source_exit_all": int(len(table)),
            "scheduler_cohort": int(len(cohort)),
            "capture_all_active": int(active_mask.sum()),
            "capture_scheduler_cohort": int((active_mask & cohort_mask).sum()),
            "capture_outside_scheduler_cohort": int((active_mask & ~cohort_mask).sum()),
            "scheduler_cohort_lost_before_pulse": int((cohort_mask & ~active_mask).sum()),
            "all_exit_lost_before_pulse": int((~active_mask).sum()),
            "s2_oatof_entry": int(table["inside_physical_aperture_at_s2_entry"].sum()),
            "local_accelerator_exit": int(table["reached_local_accelerator_exit"].sum()),
            "detector_crossing": int(table["downstream_detector_crossing"].sum()),
            "detector_hit": int(table["downstream_detector_hit"].sum()),
        },
        "stage_membership": {
            "denominator": int(len(table)),
            "sets_are_nested_not_additive": True,
            "rf_exit": int(len(table)),
            "s2_oatof_entry": int(table["inside_physical_aperture_at_s2_entry"].sum()),
            "pulse_active": int(table["active_at_pulse"].sum()),
            "local_accelerator_exit": int(table["reached_local_accelerator_exit"].sum()),
            "detector_hit": int(table["downstream_detector_hit"].sum()),
        },
        "exclusive_particle_outcomes": {
            "denominator": int(len(table)),
            "classes_are_mutually_exclusive_and_exhaustive": True,
            "counts": {
                str(name): int(count)
                for name, count in table["particle_outcome"].value_counts().items()
            },
        },
        "loss_counts": [
            {"event": str(event), "terminal_reason": str(reason), "particles": int(count)}
            for (event, reason), count in loss_counts.items()
        ],
        "checkpoint_metrics": groups,
        "capture_minus_ballistic_same_id_residual": _residual_metrics(table),
        "ballistic_model": {
            "equation": "r(t_pulse)=r_exit+v_exit*(t_pulse-t_exit)",
            "uses_global_particle_clock": True,
            "uses_true_three_dimensional_velocity": True,
            "field_forces_included": False,
            "prediction_is_not_a_replacement_for_comsol_capture": True,
        },
        "source_identities": {
            "exit_state": {"path": str(exit_path.resolve()), "sha256": sha256(exit_path)},
            "capture_state": {"path": str(capture_path.resolve()), "sha256": sha256(capture_path)},
            "terminal_census": {"path": str(terminal_path.resolve()), "sha256": sha256(terminal_path)},
            "s2_oatof_entry_state": {"path": str(s2_entry_path.resolve()), "sha256": sha256(s2_entry_path)},
            "local_accelerator_exit_state": {"path": str(local_exit_path.resolve()), "sha256": sha256(local_exit_path)},
            "simion_row_map": {"path": str(row_map_path.resolve()), "sha256": sha256(row_map_path)},
            "simion_downstream_state": {"path": str(downstream_path.resolve()), "sha256": sha256(downstream_path)},
            "pulse_schedule": {"path": str(schedule_path.resolve()), "sha256": sha256(schedule_path)},
            "s2_contract": {"path": str(s2_path.resolve()), "sha256": sha256(s2_path)},
            "registration": {
                "path": str(registration_path.resolve()),
                "sha256": sha256(registration_path),
            },
            "rf_resolved_geometry": {
                "path": str(rf_resolved_path.resolve()),
                "sha256": sha256(rf_resolved_path),
            },
            "oatof_baseline": {"path": str(baseline_path.resolve()), "sha256": sha256(baseline_path)},
            "joint_geometry": {"path": str(joint_path.resolve()), "sha256": sha256(joint_path)},
        },
        "scientific_scope": {
            "particles_removed_from_metrics": 0,
            "dense_trajectories_used": False,
            "timing_sweep_included": False,
            "n1000_included": False,
            "active_optics_included": False,
            "stage_passed": False,
            "formal_gate_passed": False,
        },
    }
    return metrics, table, geometry


def _add_reference_boxes(ax_xz: plt.Axes, ax_yz: plt.Axes,
                         geometry: dict[str, Any]) -> None:
    center = geometry["source_center"]
    size = geometry["source_size"]
    ideal_style = {"fill": False, "edgecolor": "#756bb1", "linestyle": "--",
                   "linewidth": 1.7, "label": "ideal source volume", "zorder": 3}
    ax_xz.add_patch(Rectangle(
        (center["x"] - size["x"] / 2, center["z"] - size["z"] / 2),
        size["x"], size["z"], **ideal_style))
    ax_yz.add_patch(Rectangle(
        (center["y"] - size["y"] / 2, center["z"] - size["z"] / 2),
        size["y"], size["z"], **ideal_style))


def _plot_state_planes(axes: tuple[plt.Axes, plt.Axes], table: pd.DataFrame,
                       geometry: dict[str, Any]) -> None:
    """Plot registered chain checkpoints and mutually exclusive loss locations."""
    ax_xz, ax_yz = axes
    add_rf_s2_geometry_outlines(ax_xz, geometry, "xz")
    add_rf_s2_geometry_outlines(ax_yz, geometry, "yz")
    add_accelerator_geometry_outlines(ax_xz, geometry, "x")
    add_accelerator_geometry_outlines(ax_yz, geometry, "y")
    _add_reference_boxes(ax_xz, ax_yz, geometry)
    marker = particle_marker_areas(len(table))["active"]
    states = (
        ("exit", pd.Series(True, index=table.index), "#0072B2", "o",
         f"RF exit (N={len(table)})"),
        ("s2_entry", table["inside_physical_aperture_at_s2_entry"],
         "#56B4E9", "^", "S2 / oa entry"),
        ("capture", table["active_at_pulse"], "#E69F00", "s", "S3 pulse left limit"),
        ("local_exit", table["reached_local_accelerator_exit"],
         "#009E73", "D", "local accelerator exit"),
    )
    for ax, horizontal, vertical in (
        (ax_xz, "x", "z"), (ax_yz, "y", "z"),
    ):
        for state, mask, color, symbol, label in states:
            ax.scatter(
                table.loc[mask, f"{state}_local_{horizontal}_mm"],
                table.loc[mask, f"{state}_local_{vertical}_mm"],
                s=marker, marker=symbol, linewidths=0.55, edgecolors="#202020",
                color=color, alpha=0.78, label=label, rasterized=True, zorder=6,
            )
        for outcome, color, symbol, label in (
            ("physical_port_wall_loss", "#D55E00", "x", "physical port wall loss"),
            ("pre_pulse_loss", "#252525", "X", "pre-pulse accelerator/boundary loss"),
            ("active_local_exit_loss", "#CC79A7", "P", "active local-exit loss"),
        ):
            mask = table["particle_outcome"].eq(outcome)
            ax.scatter(
                table.loc[mask, f"terminal_local_{horizontal}_mm"],
                table.loc[mask, f"terminal_local_{vertical}_mm"],
                s=marker * 1.1, marker=symbol, linewidths=0.75,
                color=color, label=label, rasterized=True, zorder=7,
            )
        ax.grid(alpha=0.18)
        ax.set_aspect("equal", adjustable="box")
    ax_xz.set(xlabel="Registered oa guide axis, x (mm)",
              ylabel="Registered oa acceleration axis, z (mm)",
              title="A  Registered chain checkpoints (x–z)")
    ax_yz.set(xlabel="Registered oa transverse axis, y (mm)",
              ylabel="Registered oa acceleration axis, z (mm)",
              title="B  Physical aperture and losses (y–z)")


def _plot_detector_plane(ax: plt.Axes, table: pd.DataFrame,
                         geometry: dict[str, Any]) -> None:
    crossing = table["downstream_detector_crossing"]
    hit = table["downstream_detector_hit"]
    ax.add_patch(Circle(
        (0, 0), float(geometry["detector_radius"]), fill=False,
        linestyle="--", linewidth=1.2, color="#756bb1", label="active radius",
    ))
    ax.scatter(
        table.loc[crossing & ~hit, "detector_plane_x_mm"],
        table.loc[crossing & ~hit, "detector_plane_y_mm"],
        marker="x", color="#D55E00", label="crossing outside active radius",
    )
    ax.scatter(
        table.loc[hit, "detector_plane_x_mm"],
        table.loc[hit, "detector_plane_y_mm"],
        marker="*", s=48, edgecolors="#202020", linewidths=0.5,
        color="#009E73", label="detector hit",
    )
    ax.set(
        xlabel="Detector-plane x − center (mm)",
        ylabel="Detector-plane y − center (mm)",
        title=("C  Downstream detector state "
               f"({int(hit.sum())}/{int(table['reached_local_accelerator_exit'].sum())})"),
    )
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.18)
    ax.legend(fontsize=7, loc="best")


def build_checkpoint_figure(metrics: dict[str, Any], table: pd.DataFrame,
                            geometry: dict[str, Any]
                            ) -> tuple[plt.Figure, dict[str, plt.Axes]]:
    """Build the six-panel full-chain run diagnostic without saving it."""
    figure, grid = plt.subplots(2, 3, figsize=(17.4, 10.4), constrained_layout=True)
    axes = {
        "chain_xz": grid[0, 0], "aperture_yz": grid[0, 1],
        "detector": grid[0, 2], "ballistic_residual": grid[1, 0],
        "exclusive_outcomes": grid[1, 1], "stage_membership": grid[1, 2],
    }
    _plot_state_planes((axes["chain_xz"], axes["aperture_yz"]), table, geometry)
    _plot_detector_plane(axes["detector"], table, geometry)
    active = table[table["active_at_pulse"]]
    residual_styles = {
        "x": {"color": "#0072B2", "marker": "o"},
        "y": {"color": "#E69F00", "marker": "s"},
        "z": {"color": "#009E73", "marker": "^"},
    }
    marker_size = np.sqrt(particle_marker_areas(len(table))["active"])
    for axis in AXES:
        style = residual_styles[axis]
        axes["ballistic_residual"].plot(
            active["particle_id"], active[f"capture_minus_ballistic_{axis}_mm"],
            linestyle="none", marker=style["marker"], markersize=marker_size,
            markeredgecolor="#202020", markeredgewidth=0.45,
            color=style["color"], label=f"{axis} residual (Δ{axis})",
            rasterized=True)
    axes["ballistic_residual"].axhline(0, color="#555555", linewidth=0.8)
    axes["ballistic_residual"].set(xlabel="Particle ID",
                   ylabel="COMSOL capture − ballistic prediction (mm)",
                   title=f"D  Same-ID pulse residual (N={len(active)})")
    axes["ballistic_residual"].legend(
        title="Position component", loc="best", ncol=3, frameon=True,
        facecolor="white", framealpha=0.88, fontsize=8, title_fontsize=8)
    axes["ballistic_residual"].grid(alpha=0.18)

    denominator = int(metrics["exclusive_particle_outcomes"]["denominator"])
    outcome_order = [
        ("physical_port_wall_loss", "port wall loss"),
        ("pre_pulse_loss", "pre-pulse loss"),
        ("active_local_exit_loss", "active local-exit loss"),
        ("local_exit_without_detector_hit", "local exit; no detector hit"),
        ("detector_hit", "detector hit"),
    ]
    outcome_counts = metrics["exclusive_particle_outcomes"]["counts"]
    labels = [label for _, label in outcome_order]
    values = [int(outcome_counts.get(key, 0)) for key, _ in outcome_order]
    axes["exclusive_outcomes"].barh(
        labels, values,
        color=["#D55E00", "#252525", "#CC79A7", "#56B4E9", "#009E73"],
        hatch=["//", "xx", "..", "--", "++"], edgecolor="#202020",
        linewidth=0.5,
    )
    for index, value in enumerate(values):
        axes["exclusive_outcomes"].text(
            value, index, f" {value}/{denominator}", va="center", fontsize=8
        )
    axes["exclusive_outcomes"].set(
        xlabel=f"Mutually exclusive particles (denominator N={denominator})",
        title="E  Exhaustive final outcomes",
    )
    axes["exclusive_outcomes"].set_xlim(0, max(values + [1]) * 1.23)

    membership = metrics["stage_membership"]
    stage_labels = ["RF exit", "S2 / oa entry", "pulse active", "local exit", "detector hit"]
    stage_values = [membership[key] for key in (
        "rf_exit", "s2_oatof_entry", "pulse_active",
        "local_accelerator_exit", "detector_hit",
    )]
    axes["stage_membership"].plot(
        range(len(stage_values)), stage_values, color="#0072B2", linewidth=1.1,
        marker="o", markerfacecolor="white", markeredgecolor="#0072B2",
    )
    axes["stage_membership"].set_xticks(range(len(stage_labels)), stage_labels, rotation=20)
    axes["stage_membership"].set(
        ylabel=f"Nested membership (of N={denominator})",
        title="F  Stage membership (not additive)", ylim=(0, denominator * 1.08),
    )
    for index, value in enumerate(stage_values):
        axes["stage_membership"].text(index, value, f"{value}/{denominator}",
                                      ha="center", va="bottom", fontsize=8)
    axes["stage_membership"].grid(axis="y", alpha=0.18)
    legend_items: dict[str, Any] = {}
    for axis in (axes["chain_xz"], axes["aperture_yz"]):
        handles, labels = axis.get_legend_handles_labels()
        legend_items.update(zip(labels, handles, strict=True))
    figure.legend(legend_items.values(), legend_items.keys(),
                  loc="outside lower center", ncol=4, frameon=False, fontsize=8)
    figure.suptitle(
        "RF exit → S2 port → S3 pulse → local exit → oaTOF detector diagnostic "
        f"(t = {metrics['pulse_instrument_time_us']:.6f} µs)\n"
        f"frame={metrics['analysis_frame']}; input={metrics['input_frame']}; "
        f"clock epoch={metrics['clock_epoch_id']}; source denominator N={denominator}",
        fontsize=13)
    return figure, axes


def export_checkpoint_figure(figure: plt.Figure, output: Path) -> None:
    """Export one run-diagnostic PNG without changing its prepared data."""
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, format="png", dpi=190)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exit-state", type=Path, required=True)
    parser.add_argument("--capture-state", type=Path, required=True)
    parser.add_argument("--terminal-census", type=Path, required=True)
    parser.add_argument("--s2-entry-state", type=Path, required=True)
    parser.add_argument("--local-exit-state", type=Path, required=True)
    parser.add_argument("--downstream-row-map", type=Path, required=True)
    parser.add_argument("--downstream-state", type=Path, required=True)
    parser.add_argument("--pulse-schedule", type=Path, required=True)
    parser.add_argument("--oatof-baseline", type=Path, required=True)
    parser.add_argument("--s2-contract", type=Path, required=True)
    parser.add_argument(
        "--resolved-registration",
        type=Path,
        default=DEFAULT_SPATIAL_REGISTRATION,
    )
    parser.add_argument("--rf-resolved-geometry", type=Path, required=True)
    parser.add_argument("--joint-contract", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--particles", type=Path, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    args = parser.parse_args()
    metrics, table, geometry = analyze_checkpoints(
        args.exit_state, args.capture_state, args.terminal_census,
        args.s2_entry_state, args.local_exit_state,
        args.downstream_row_map, args.downstream_state,
        args.pulse_schedule, args.oatof_baseline, args.s2_contract,
        args.joint_contract, args.contract, args.resolved_registration,
        args.rf_resolved_geometry)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.particles.parent.mkdir(parents=True, exist_ok=True)
    args.figure.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    table.to_csv(args.particles, index=False)
    figure, _ = build_checkpoint_figure(metrics, table, geometry)
    try:
        export_checkpoint_figure(figure, args.figure)
    finally:
        plt.close(figure)
    counts = metrics["population_counts"]
    print("RF_OATOF_CHECKPOINTS=PASS "
          f"EXIT={counts['source_exit_all']} COHORT={counts['scheduler_cohort']} "
          f"ACTIVE={counts['capture_all_active']} LOSS={counts['all_exit_lost_before_pulse']}")


if __name__ == "__main__":
    main()
