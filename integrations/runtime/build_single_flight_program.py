"""Project file boundary around the sole installed tracking Program renderer."""

from __future__ import annotations
import csv
import math
from pathlib import Path
from msplatform.execution.resources import resource_path
from typing import Any, Mapping
from msplatform.backends.simion.tracking_program import (
    _DIAGNOSTIC_RETURN_PLANE_Z_MM as _DIAGNOSTIC_RETURN_PLANE_Z_MM,
    _SUCCESSOR_DIAGNOSTICS as _SUCCESSOR_DIAGNOSTICS,
    FIELD_OBSERVATION_BUCKETS as FIELD_OBSERVATION_BUCKETS,
    STANDALONE_DYNAMIC_FIELD_BANK_ROLE as STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION as STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION as STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
    DOWNSTREAM_STATIC_ASSET_ROLE as DOWNSTREAM_STATIC_ASSET_ROLE,
    DOWNSTREAM_STATIC_ASSET_REPRESENTATION as DOWNSTREAM_STATIC_ASSET_REPRESENTATION,
    _DOWNSTREAM_STATIC_ROLES as _DOWNSTREAM_STATIC_ROLES,
    _SUCCESSOR_CALLBACKS as _SUCCESSOR_CALLBACKS,

    validate_native_field_observation as validate_native_field_observation,
    _instrument_native_field_observation as _instrument_native_field_observation,
    _ordinary_standalone_pa_basename as _ordinary_standalone_pa_basename,
    _resolve_standalone_dynamic_field_bank as _resolve_standalone_dynamic_field_bank,
    _resolve_downstream_static_assets as _resolve_downstream_static_assets,
    _upstream_rod_drive as _upstream_rod_drive,
    _rf_kernel_electrodes as _rf_kernel_electrodes,
    resolve_standalone_dynamic_operating_coefficients as resolve_standalone_dynamic_operating_coefficients,
    _bind_standalone_dynamic_field_paths as _bind_standalone_dynamic_field_paths,
    project_program_paths as project_program_paths,
    _standalone_dynamic_field_lua as _canonical__standalone_dynamic_field_lua,
    _canonical_bare_runtime_projection as _canonical_bare_runtime_projection,
    _native_field_analyzer_config as _native_field_analyzer_config,
    validate_native_flight as validate_native_flight,
    build_successor_program as _canonical_build_successor_program,
    build_local_frontend_program as _canonical_build_local_frontend_program,
)


def load_initial_state(path: Path) -> tuple[list[float], list[int], list[list[float]]]:
    """Load canonical clocks, retained row IDs and velocities in mm/us.

    A restart can reindex its SIMION rows while preserving the mother-cohort
    identity in the separate row map.  The state-file ID is therefore only
    validated locally; the row map is the authority for source IDs.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("single-flight initial state is empty")
    id_column = "particle_id" if "particle_id" in rows[0] else "simulation_particle_id"
    actual_ids = [int(row[id_column]) for row in rows]
    if any(value <= 0 for value in actual_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ValueError("single-flight initial-state particle IDs must be unique and positive")
    values = [float(row["instrument_time_us"]) for row in rows]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("single-flight birth times must be non-negative")
    velocities = [[float(row[f"velocity_{axis}_m_s"]) / 1000.0 for axis in "xyz"] for row in rows]
    if any(not math.isfinite(value) for velocity in velocities for value in velocity):
        raise ValueError("single-flight initial velocities must be finite")
    return values, actual_ids, velocities


def _standalone_dynamic_field_lua(
    specs: list[dict[str, Any]], *, native_path_projection: bool = True, native_path_source: str | None = None
) -> str:
    return _canonical__standalone_dynamic_field_lua(
        specs,
        native_path_projection=native_path_projection,
        native_path_source=native_path_source if native_path_source is not None else _native_path_source(),
    )


def build_successor_program(
    multipoles_by_instance: dict[str, dict],
    frontend: dict[str, Any],
    oatof: dict[str, Any],
    *,
    frontend_geometry: dict[str, Any],
    flight: Mapping[str, Any],
    birth_times_us: list[float],
    particle_ids: list[int] | None = None,
    initial_velocities_mm_per_us: list[list[float]],
    analyzer_component_source: str,
    pulse_hook_source: str,
    frontend_hook_source: str,
    rf_drive_kernel_source: str,
    voltage_waveforms_source: str,
    standalone_dynamic_field_bank: dict[str, Any],
    standalone_dynamic_field_paths: dict[str, dict[str, Any]],
    downstream_static_fields: dict[str, Any],
    build_metadata: dict[str, Any] | None = None,
    native_path_projection: bool = True,
    native_path_source: str | None = None,
    field_observation: dict | None = None,
    plane_observations: list[dict] | None = None,
    consumed_plane_events: list[dict] | None = None,
    original_birth_times_us: list[float] | None = None,
    absolute_deadlines_us: list[float] | None = None,
    propagation_stop: dict | None = None,
) -> str:
    return _canonical_build_successor_program(
        multipoles_by_instance,
        frontend,
        oatof,
        frontend_geometry=frontend_geometry,
        flight=flight,
        birth_times_us=birth_times_us,
        particle_ids=particle_ids,
        initial_velocities_mm_per_us=initial_velocities_mm_per_us,
        analyzer_component_source=analyzer_component_source,
        pulse_hook_source=pulse_hook_source,
        frontend_hook_source=frontend_hook_source,
        rf_drive_kernel_source=rf_drive_kernel_source,
        voltage_waveforms_source=voltage_waveforms_source,
        standalone_dynamic_field_bank=standalone_dynamic_field_bank,
        standalone_dynamic_field_paths=standalone_dynamic_field_paths,
        downstream_static_fields=downstream_static_fields,
        build_metadata=build_metadata,
        native_path_projection=native_path_projection,
        native_path_source=native_path_source if native_path_source is not None else _native_path_source(),
        field_observation=field_observation,
        plane_observations=plane_observations,
        consumed_plane_events=consumed_plane_events,
        original_birth_times_us=original_birth_times_us,
        absolute_deadlines_us=absolute_deadlines_us,
        propagation_stop=propagation_stop,
    )


def build_local_frontend_program(
    upstream: dict[str, Any],
    frontend: dict[str, Any],
    *,
    birth_times_us: list[float],
    particle_ids: list[int],
    initial_velocities_mm_per_us: list[list[float]],
    pulse_time_us: float,
    pulse_width_us: float,
    maximum_flight_us: float,
    maximum_step_us: float,
    shared_times_us: list[float],
    trajectory_cadence_us: float,
    standalone_dynamic_field_bank: dict[str, Any],
    standalone_dynamic_field_paths: dict[str, dict[str, Any]],
    rf_drive_kernel_source: str,
    pulse_hook_source: str,
    frontend_hook_source: str,
    voltage_waveforms_source: str,
    rf_steps_per_period: int,
    trajectory_quality: int,
    pulse_mode: int = 1,
) -> str:
    return _canonical_build_local_frontend_program(
        upstream,
        frontend,
        birth_times_us=birth_times_us,
        particle_ids=particle_ids,
        initial_velocities_mm_per_us=initial_velocities_mm_per_us,
        pulse_time_us=pulse_time_us,
        pulse_width_us=pulse_width_us,
        maximum_flight_us=maximum_flight_us,
        maximum_step_us=maximum_step_us,
        shared_times_us=shared_times_us,
        trajectory_cadence_us=trajectory_cadence_us,
        standalone_dynamic_field_bank=standalone_dynamic_field_bank,
        standalone_dynamic_field_paths=standalone_dynamic_field_paths,
        rf_drive_kernel_source=rf_drive_kernel_source,
        pulse_hook_source=pulse_hook_source,
        frontend_hook_source=frontend_hook_source,
        voltage_waveforms_source=voltage_waveforms_source,
        rf_steps_per_period=rf_steps_per_period,
        trajectory_quality=trajectory_quality,
        pulse_mode=pulse_mode,
        native_path_source=_native_path_source(),
    )


def _native_path_source():
    return resource_path("native_run_path.lua").read_text(encoding="utf-8-sig")
