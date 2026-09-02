"""Build the continuous SIMION Program from frozen oaTOF and multipole contracts."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
from typing import Any

from common.contracts.file_identity import file_sha256
from common.multipole.grounded_shield import require_grounded_potential
from common.multipole.simion_geometry import segmented_rod_electrode_ids
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract import (
    ROD_ELECTRODE_IDS,
    require_published_frontend_electrodes,
    resolve_frontend_electrode_topology,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    resolved_region_field_hook_lua,
    validate_resolved_region_field_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pure_boundary_validator import (
    validate_pure_lua_component_source,
)

SOURCE_RELEASE_MODES = (
    "continuous_frontend",
    "continuous_frontend_handoff",
    "pre_pulse_restart",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _lua_number(value: float) -> str:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Lua numeric value must be finite")
    return format(result, ".17g")


def reflectron_fast_adjust_assignments(oatof: dict[str, Any]) -> list[str]:
    """Compile the resolved reflectron ring voltages into SIMION fastadj input."""

    rings = oatof.get("rings")
    voltages = oatof.get("electrodes_V")
    if not isinstance(rings, dict) or not isinstance(voltages, dict):
        raise ValueError("resolved oaTOF reflectron rings or voltages are missing")
    stage1_count = rings.get("stage1_count")
    stage2_count = rings.get("stage2_count")
    if (
        isinstance(stage1_count, bool)
        or isinstance(stage2_count, bool)
        or not isinstance(stage1_count, int)
        or not isinstance(stage2_count, int)
        or stage1_count < 1
        or stage2_count < 1
    ):
        raise ValueError("resolved reflectron ring counts must be positive integers")
    midgrid = float(voltages.get("midgrid"))
    backplate = float(voltages.get("backplate"))
    if not math.isfinite(midgrid) or not math.isfinite(backplate):
        raise ValueError("resolved reflectron voltages must be finite")

    assignments = ["1=0"]
    for ring_index in range(1, stage1_count + 1):
        electrode = 1 + ring_index
        voltage = midgrid * ring_index / (stage1_count + 1)
        assignments.append(f"{electrode}={_lua_number(voltage)}")
    midgrid_electrode = 2 + stage1_count
    assignments.append(f"{midgrid_electrode}={_lua_number(midgrid)}")
    for ring_index in range(1, stage2_count + 1):
        electrode = midgrid_electrode + ring_index
        voltage = midgrid + (backplate - midgrid) * ring_index / (stage2_count + 1)
        assignments.append(f"{electrode}={_lua_number(voltage)}")
    assignments.append(
        f"{3 + stage1_count + stage2_count}={_lua_number(backplate)}"
    )
    assignments.append(f"{4 + stage1_count + stage2_count}=0")
    return assignments


def _lua_value(value: object) -> str:
    """Serialize a validated Python contract fragment as deterministic Lua."""
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _lua_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, list):
        return "{" + ",".join(_lua_value(item) for item in value) + "}"
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Lua contract key is not one identifier: {key!r}")
            items.append(f"{key}={_lua_value(item)}")
        return "{" + ",".join(items) + "}"
    raise ValueError(f"unsupported Lua contract value: {type(value).__name__}")


def load_initial_state(path: Path) -> tuple[list[float], list[int]]:
    """Load canonical clocks and retained state-row identities.

    A restart can reindex its SIMION rows while preserving the mother-cohort
    identity in the separate row map.  The state-file ID is therefore only
    validated locally; the row map is the authority for source IDs.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("single-flight initial state is empty")
    id_column = (
        "particle_id" if "particle_id" in rows[0] else "simulation_particle_id"
    )
    actual_ids = [int(row[id_column]) for row in rows]
    if any(value <= 0 for value in actual_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ValueError("single-flight initial-state particle IDs must be unique and positive")
    values = [float(row["instrument_time_us"]) for row in rows]
    if any(value < 0 for value in values):
        raise ValueError("single-flight birth times must be non-negative")
    return values, actual_ids


def load_row_map(path: Path, expected_row_count: int) -> list[int]:
    """Load the explicit SIMION-row to canonical-source-ID authority."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["simulation_particle_id", "source_particle_id"]:
            raise ValueError("single-flight row map columns differ")
        rows = list(reader)
    simulation_ids = [int(row["simulation_particle_id"]) for row in rows]
    source_ids = [int(row["source_particle_id"]) for row in rows]
    if simulation_ids != list(range(1, len(rows) + 1)):
        raise ValueError("single-flight simulation row IDs must be contiguous and ordered")
    if len(rows) != expected_row_count:
        raise ValueError("single-flight row map count differs from initial-state row count")
    if any(value <= 0 for value in source_ids) or len(set(source_ids)) != len(source_ids):
        raise ValueError("single-flight row map source IDs must be unique and positive")
    return source_ids


def resolve_domain_split_program_contract(
    upstream: dict[str, Any], accelerator: dict[str, Any]
) -> dict[str, Any]:
    """Validate two disjoint fine PA domains around a coarse connector sleeve."""

    collision_only = (
        upstream.get("role") == "rf_oatof_simion_pre_pulse_connector_collision_contract"
        and accelerator.get("boundary_condition", {}).get("mode")
        == "geometry_collision_zero_field_v1"
    )
    accelerator_zero_field = (
        not collision_only
        and upstream.get("role") == "rf_oatof_simion_upstream_bridge_contract"
        and accelerator.get("role") == "rf_oatof_simion_accelerator_main_contract"
        and accelerator.get("boundary_condition", {}).get("mode")
        == "geometry_collision_zero_field_v1"
    )
    expected = (
        (upstream, "rf_oatof_simion_pre_pulse_connector_collision_contract" if collision_only else "rf_oatof_simion_upstream_bridge_contract", "upstream"),
        (accelerator, "rf_oatof_simion_accelerator_main_contract", "accelerator"),
    )
    normalized: dict[str, Any] = {}
    for document, role, label in expected:
        if document.get("role") != role or (
            not collision_only
            and not accelerator_zero_field
            and document.get("status") != "bridge_coupling_required"
        ):
            raise ValueError(f"domain split {label} contract identity differs")
        split = document.get("domain_split")
        bounds = document.get("instance_bounds_mm")
        if not isinstance(split, dict) or not isinstance(bounds, dict):
            raise ValueError(f"domain split {label} geometry is missing")
        if (
            not collision_only
            and not accelerator_zero_field
            and split.get("partition_policy_id") != "grounded_sleeve_disjoint_fine_domains_v1"
        ):
            raise ValueError(f"domain split {label} partition policy differs")
        try:
            upstream_end_x = float(split["upstream_end_x_mm"])
            accelerator_start_x = float(split["accelerator_start_x_mm"])
            x_min = float(bounds["x_min"])
            x_max = float(bounds["x_max"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"domain split {label} axial bounds are invalid") from error
        if not all(math.isfinite(value) for value in (upstream_end_x, accelerator_start_x, x_min, x_max)):
            raise ValueError(f"domain split {label} axial bounds are invalid")
        normalized[label] = {
            "instance_bounds_mm": bounds,
            "instance_origin_mm": document.get("instance_origin_mm"),
            "upstream_end_x_mm": upstream_end_x,
            "accelerator_start_x_mm": accelerator_start_x,
        }
    if not math.isclose(normalized["upstream"]["upstream_end_x_mm"], normalized["accelerator"]["upstream_end_x_mm"], abs_tol=1e-9) or not math.isclose(normalized["upstream"]["accelerator_start_x_mm"], normalized["accelerator"]["accelerator_start_x_mm"], abs_tol=1e-9):
        raise ValueError("domain split fine-domain endpoints differ")
    if normalized["upstream"]["upstream_end_x_mm"] >= normalized["upstream"]["accelerator_start_x_mm"]:
        raise ValueError("domain split fine domains overlap or omit the coarse sleeve")
    upstream_bounds = normalized["upstream"]["instance_bounds_mm"]
    accelerator_bounds = normalized["accelerator"]["instance_bounds_mm"]
    if not collision_only and not math.isclose(
        float(upstream_bounds["x_max"]),
        normalized["upstream"]["upstream_end_x_mm"],
        abs_tol=1e-9,
    ):
        raise ValueError("upstream fine PA must stop at the coarse-sleeve boundary")
    if not collision_only and not accelerator_zero_field and not math.isclose(
        float(accelerator_bounds["x_min"]),
        normalized["upstream"]["accelerator_start_x_mm"],
        abs_tol=1e-9,
    ):
        raise ValueError("accelerator fine PA must start at the coarse-sleeve boundary")
    for label in ("upstream", "accelerator"):
        origin = normalized[label]["instance_origin_mm"]
        if not isinstance(origin, dict) or set(origin) != {"x", "y", "z"}:
            raise ValueError(f"domain split {label} PA origin is invalid")
    pa_plus_solution_model = None
    if not accelerator_zero_field:
        candidate = accelerator.get("pa_plus_solution_model")
        if (
            not isinstance(candidate, dict)
            or candidate.get("model_id") != "three_zone_linear_ring_pa_plus_v1"
            or candidate.get("mode_count") != 14
            or not isinstance(candidate.get("modes"), list)
            or len(candidate["modes"]) != 14
            or candidate.get("voltage_control_policy", {}).get("policy_id")
            != "three_zone_linear_ring_interpolation_v1"
            or candidate["voltage_control_policy"].get(
                "per_ring_independent_adjustment_supported"
            ) is not False
        ):
            raise ValueError("domain split accelerator PA+ solution model is invalid")
        pa_plus_solution_model = candidate
        if not all(math.isfinite(float(origin[axis])) for axis in ("x", "y", "z")):
            raise ValueError(f"domain split {label} PA origin is invalid")
    return {
        "upstream_instance_index": 2,
        "accelerator_instance_index": 3,
        "upstream_end_x_mm": normalized["upstream"]["upstream_end_x_mm"],
        "accelerator_start_x_mm": normalized["upstream"]["accelerator_start_x_mm"],
        "upstream_bounds_mm": normalized["upstream"]["instance_bounds_mm"],
        "accelerator_bounds_mm": normalized["accelerator"]["instance_bounds_mm"],
        "upstream_origin_mm": normalized["upstream"]["instance_origin_mm"],
        "accelerator_origin_mm": normalized["accelerator"]["instance_origin_mm"],
        "accelerator_zero_field": accelerator_zero_field,
        "pa_plus_solution_model": pa_plus_solution_model,
    }


_SUCCESSOR_CALLBACKS = (
    "load",
    "initialize_run",
    "efield_adjust",
    "fast_adjust",
    "instance_adjust",
    "initialize",
    "tstep_adjust",
    "other_actions",
    "terminate",
)


def _successor_analyzer_config(
    oatof: dict[str, Any],
    frontend: dict[str, Any],
    region_field_contract: dict[str, Any],
) -> dict[str, Any]:
    geometry = oatof["geometry_mm"]
    derivation = oatof["geometry_derivation"]["accelerator"]
    coordinate = oatof["coordinate_convention"]
    voltage = oatof["electrodes_V"]
    rings = oatof["rings"]
    marker = oatof["simion_detector_marker"]
    electrodes = frontend["electrodes"]
    frontend_topology_id = frontend.get("accelerator_topology_id")
    three_zone = frontend_topology_id is not None
    topology = oatof.get("accelerator_topology") if three_zone else None
    region_topology = region_field_contract["semantic"].get(
        "accelerator_topology"
    )
    if three_zone:
        if (
            not isinstance(frontend_topology_id, str)
            or not frontend_topology_id
            or topology != region_topology
            or topology.get("topology_id") != frontend_topology_id
        ):
            raise ValueError(
                "frontend, oaTOF and region-field three-zone topologies must match exactly"
            )
        planes = topology["planes_global_z_mm"]
        accelerator_repeller_z = float(planes["repeller"])
        accelerator_grid1_z = float(planes["intermediate1"])
        accelerator_intermediate2_z = float(planes["intermediate2"])
        accelerator_grid2_z = float(planes["exit"])
        accelerator_potentials = topology["potentials_v"]
    else:
        if frontend_topology_id is not None or region_topology is not None:
            raise ValueError("two-zone frontend must not publish a three-zone topology")
        accelerator_repeller_z = float(geometry["accelerator_repeller_z"])
        accelerator_grid1_z = float(geometry["accelerator_grid1_z"])
        accelerator_grid2_z = float(geometry["accelerator_grid2_z"])
    accelerator_instance_z = (
        accelerator_repeller_z
        - float(geometry["accelerator_repeller_thickness"])
        - float(geometry["accelerator_rear_clearance"])
        - float(geometry["accelerator_shield_wall"])
    )
    near_bore_z = (
        accelerator_instance_z
        - float(geometry["shield_near_endcap_gap"])
    )
    near_outer_z = near_bore_z - float(geometry["shield_endcap_thickness"])
    backplate_z = (
        float(geometry["L_flight"])
        + float(geometry["L_stage1"])
        + float(geometry["L_stage2"])
    )
    far_outer_z = (
        backplate_z
        + float(geometry["ring_thickness"])
        + float(geometry["shield_axial_gap"])
        + float(geometry["shield_endcap_thickness"])
    )
    accelerator_axis_y = float(coordinate.get("accelerator_axis_y", 0.0))
    detector_x = float(coordinate["detector_x"])
    detector_y = -accelerator_axis_y
    analyzer_geometry = {
        "accelerator_axis_x_mm": float(coordinate["accelerator_axis_x"]),
        "accelerator_axis_y_mm": accelerator_axis_y,
        "accelerator_instance_z_mm": accelerator_instance_z,
        "accelerator_repeller_front_z_mm": accelerator_repeller_z,
        "accelerator_grid1_z_mm": accelerator_grid1_z,
        "accelerator_grid2_z_mm": accelerator_grid2_z,
        "reflectron_axis_x_mm": 0.0,
        "reflectron_axis_y_mm": 0.0,
        "reflectron_entgrid_z_mm": float(geometry["L_flight"]),
        "reflectron_midgrid_z_mm": float(geometry["L_flight"])
        + float(geometry["L_stage1"]),
        "reflectron_backplate_z_mm": backplate_z,
        "detector_x_mm": detector_x,
        "detector_y_mm": detector_y,
        "detector_z_mm": accelerator_grid2_z
        + float(derivation["focus_drift_after_grid2_mm"]),
        "detector_radius_mm": float(geometry["detector_radius"]),
        "detector_marker_front_margin_z_mm": float(marker["front_margin_z_mm"]),
        "detector_marker_back_margin_z_mm": float(marker["back_margin_z_mm"]),
        "detector_marker_absorber_thickness_mm": float(marker["absorber_thickness_mm"]),
        "diagnostic_return_plane_z_mm": 20.5,
        "flight_tube_near_outer_z_mm": near_outer_z,
        "flight_tube_far_outer_z_mm": far_outer_z,
    }
    analyzer_voltages = {
        "repeller_v": float(voltage["repeller"]),
        "grid1_v": float(voltage["grid1"]),
        "mid_v": float(voltage["midgrid"]),
        "backplate_v": float(voltage["backplate"]),
    }
    analyzer_electrodes = {
        "repeller": int(electrodes["accelerator_repeller_id"]),
        "grid1": int(electrodes["accelerator_grid1_id"]),
        "rings": [int(item) for item in electrodes["accelerator_ring_ids"]],
        "grid2": int(electrodes["accelerator_grid2_id"]),
    }
    if three_zone:
        analyzer_geometry.update(
            {
                "accelerator_intermediate2_z_mm": accelerator_intermediate2_z,
                "accelerator_ring_z_mm": list(
                    frontend["accelerator_local_region"]["ring_z_mm"]
                ),
            }
        )
        analyzer_voltages.update(
            {
                "repeller_v": float(accelerator_potentials["repeller"]),
                "grid1_v": float(accelerator_potentials["intermediate1"]),
                "intermediate2_v": float(accelerator_potentials["intermediate2"]),
                "exit_v": float(accelerator_potentials["exit"]),
            }
        )
        analyzer_electrodes["intermediate2"] = int(
            electrodes["accelerator_intermediate2_id"]
        )
    return {
        "accelerator_topology_id": resolve_frontend_electrode_topology(
            electrodes
        )["topology_id"],
        "instance_roles": {
            "flight_tube": 1,
            "reflectron": 2,
            "accelerator": 3,
            "detector": 4,
        },
        "instance_filenames": {
            "flight_tube": "flight_tube_ground.pa0",
            "reflectron": "reflectron.pa0",
            "accelerator": "accelerator.pa0",
            "detector": "detector_ground.pa0",
        },
        "geometry": analyzer_geometry,
        "field_modes": {
            "ideal_accelerator": False,
            "ideal_accelerator_axial": False,
            "ideal_drift_axial": False,
            "ideal_reflectron_stage1": False,
            "ideal_reflectron_stage1_axial": False,
            "ideal_reflectron_stage2": False,
            "ideal_reflectron_stage2_axial": False,
        },
        "voltages": analyzer_voltages,
        "accelerator_ring_count": int(rings["accelerator_count"]),
        "electrode_ids": analyzer_electrodes,
        "reflectron_stage1_ring_count": int(rings["stage1_count"]),
        "reflectron_stage2_ring_count": int(rings["stage2_count"]),
        "detector": {
            "tstep_enabled": True,
            "capture_arm_distance_mm": float(marker["capture_arm_distance_mm"]),
            "capture_depth_mm": float(marker["capture_depth_mm"]),
            "marker_absorber_thickness_mm": float(marker["absorber_thickness_mm"]),
        },
        "diagnostics": {"max_tof_us": 90.0, "log_stride": 1000},
    }


def build_successor_program(
    upstream: dict[str, Any],
    frontend: dict[str, Any],
    oatof: dict[str, Any],
    region_field_contract: dict[str, Any],
    *,
    birth_times_us: list[float],
    particle_ids: list[int] | None = None,
    analyzer_component_source: str,
    pulse_hook_source: str,
    frontend_hook_source: str,
    rf_drive_kernel_source: str,
    source_release_mode: str | None = None,
    terminate_after_pulse: bool = False,
    pre_pulse_time_series_contract: dict[str, Any] | None = None,
    overlay: dict[str, Any] | None = None,
    intermediate_overlay: dict[str, Any] | None = None,
    accelerator_entrance_local: dict[str, Any] | None = None,
    domain_split: dict[str, Any] | None = None,
    domain_split_main_pa_only_axis_field: bool = False,
    domain_split_local_axis_field: bool = False,
    rf_steps_per_period: int = 160,
    global_segments: bool = False,
    include_total_axis_field_exporter: bool = False,
) -> str | tuple[str, str]:
    """Assemble the callback-neutral components behind one SIMION callback set."""
    if upstream.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("single-flight Program requires a multipole resolved design")
    if frontend.get("role") != "rf_oatof_simion_single_flight_frontend_contract":
        raise ValueError("single-flight Program requires a frontend contract")
    require_published_frontend_electrodes(frontend.get("electrodes", {}))
    require_grounded_potential(
        upstream["axial_dc"]["upstream_shield_potential_V"], "multipole shield"
    )
    require_grounded_potential(
        frontend["junction_enclosure"]["shield_potential_V"],
        "frontend shield connection",
    )
    if not birth_times_us or any(not math.isfinite(item) or item < 0 for item in birth_times_us):
        raise ValueError("canonical instrument clock requires nonnegative birth times")
    if particle_ids is None:
        particle_ids = list(range(1, len(birth_times_us) + 1))
    if (
        len(particle_ids) != len(birth_times_us)
        or any(item <= 0 for item in particle_ids)
        or len(set(particle_ids)) != len(particle_ids)
    ):
        raise ValueError("single-flight canonical particle IDs are invalid")
    if source_release_mode is None:
        source_release_mode = "continuous_frontend"
    if source_release_mode not in SOURCE_RELEASE_MODES:
        raise ValueError("single-flight source release mode is unsupported")
    rf_enabled = source_release_mode != "pre_pulse_restart"
    if isinstance(rf_steps_per_period, bool) or not isinstance(rf_steps_per_period, int) or rf_steps_per_period <= 0:
        raise ValueError("RF steps per period must be one positive integer")
    screening = pre_pulse_time_series_contract is not None
    natural_pre_pulse_archive = (
        screening
        and pre_pulse_time_series_contract is not None
        and pre_pulse_time_series_contract.get("schema_version") == 7
    )
    pre_pulse_collision_only = (
        screening
        and domain_split is not None
        and source_release_mode == "continuous_frontend_handoff"
        and pre_pulse_time_series_contract is not None
        and pre_pulse_time_series_contract.get("schema_version") == 5
    )
    pre_pulse_entry_geometry = (
        screening
        and domain_split is not None
        and source_release_mode == "continuous_frontend"
        and bool(domain_split.get("accelerator_zero_field"))
    )
    pre_pulse_accelerator_zero_field = (
        pre_pulse_collision_only or pre_pulse_entry_geometry
    )
    post_pulse_handoff_minimal = (
        source_release_mode == "pre_pulse_restart"
        and domain_split is not None
        and accelerator_entrance_local is not None
        and not screening
    )
    reduced_post_accelerator_iob = (
        post_pulse_handoff_minimal or domain_split_local_axis_field
    )
    sample_times_us: list[float] = []
    # Kept defined for non-screening Programs; the generated Lua only reads
    # them for the v7 natural archive branch.
    grid_origin_us = 0.0
    grid_step_us = 1.0
    if screening:
        contract = pre_pulse_time_series_contract
        assert contract is not None
        required = {
            "role": "rf_oatof_pre_pulse_time_series_screening_contract",
            "mode": "real_pa_rf_pre_pulse_time_series",
            "active_scope": "pre_pulse_frontend_accelerator",
            "pulse_disabled": True,
            "resolution_claim_allowed": False,
        }
        if (
            contract.get("schema_version") not in {1, 2, 3, 4, 5, 6, 7}
            or any(contract.get(key) != value for key, value in required.items())
        ):
            raise ValueError("pre-pulse time-series screening contract mode differs")
        if contract.get("prohibited_outputs") != [
            "detector_crossing",
            "resolution_metrics",
            "single_flight_spatial_six_panel",
        ]:
            raise ValueError("pre-pulse time-series prohibited outputs differ")
        if natural_pre_pulse_archive:
            trace_policy = contract.get("trace_policy")
            grid = contract.get("rf_time_grid")
            if (
                contract.get("terminate_at_window_end") is not False
                or trace_policy != {
                    "mode": "natural_trajectory_native_rf_grid_v1",
                    "terminal_event": "geometry_collision_v1",
                    "retention_class": "rebuildable_trajectory_payload",
                }
                or not isinstance(grid, dict)
                or grid.get("time_grid_profile_id")
                != "natural_pre_pulse_native_rf_grid_v1"
            ):
                raise ValueError("natural pre-pulse archive contract differs")
            try:
                grid_origin_us = float(grid["grid_origin_us"])
                grid_step_us = float(grid["step_us"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("natural pre-pulse archive grid is invalid") from exc
            if not (
                math.isfinite(grid_origin_us)
                and grid_origin_us >= 0.0
                and math.isfinite(grid_step_us)
                and grid_step_us > 0.0
            ):
                raise ValueError("natural pre-pulse archive grid is invalid")
        else:
            raw_times = contract.get("sample_times_us")
            if not isinstance(raw_times, list) or not raw_times:
                raise ValueError("pre-pulse time-series requires sample times")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in raw_times
            ):
                raise ValueError("pre-pulse time-series sample times must be finite")
            sample_times_us = [float(value) for value in raw_times]
            if any(right <= left for left, right in zip(sample_times_us, sample_times_us[1:])):
                raise ValueError("pre-pulse time-series sample times must be strictly increasing")
            if sample_times_us[0] < max(birth_times_us):
                raise ValueError("pre-pulse time-series starts before the last source birth")
            grid_origin_us = 0.0
            grid_step_us = 0.0
        if terminate_after_pulse:
            raise ValueError("pre-pulse time-series requires non-restart execution")
    for label, candidate in (
        ("accelerator", overlay),
        ("intermediate", intermediate_overlay),
    ):
        if candidate is not None and candidate.get("role") != "rf_oatof_simion_accelerator_overlay_contract":
            raise ValueError(
                f"single-flight Program requires a valid {label} accelerator overlay contract"
            )
    if accelerator_entrance_local is not None:
        local = accelerator_entrance_local
        expected_local_basis_ids = list(
            resolve_frontend_electrode_topology(frontend["electrodes"])[
                "basis_electrode_ids"
            ]
        )
        if (
            local.get("schema_version") != 1
            or local.get("role")
            != "rf_oatof_simion_accelerator_entrance_aperture_local_contract"
            or local.get("electrodes") != frontend.get("electrodes")
            or local.get("boundary_condition", {}).get("mode")
            != "accelerator_main_electrode_basis_dirichlet_v1"
            or local.get("boundary_condition", {}).get("source_role")
            != "rf_oatof_simion_accelerator_main_contract"
            or local.get("boundary_condition", {}).get("basis_electrode_ids")
            != expected_local_basis_ids
            or local.get("replacement_semantics")
            != {
                "mode": "highest_priority_complete_local_replacement_v1",
                "field_superposition_prohibited": True,
                "parent_role": "rf_oatof_simion_accelerator_main_contract",
            }
        ):
            raise ValueError(
                "single-flight Program requires a valid accelerator entrance local contract"
            )
        if domain_split is not None and (local.get("pa_plus_solution_model") != domain_split.get("pa_plus_solution_model") or (
            local.get("boundary_condition", {}).get("pa_plus_mode_ids")
            != domain_split.get("pa_plus_solution_model", {}).get("mode_ids")
        )):
            raise ValueError("accelerator entrance local PA+ model differs from accelerator main")
        for key in ("instance_origin_mm", "active_bounds_mm", "cell_mm_xyz"):
            if not isinstance(local.get(key), dict):
                raise ValueError(
                    "accelerator entrance local placement contract is incomplete"
                )
        bounds = local["active_bounds_mm"]
        if any(
            not math.isfinite(float(bounds.get(f"{axis}_{side}", math.nan)))
            for axis in ("x", "y", "z")
            for side in ("min", "max")
        ) or any(
            float(bounds[f"{axis}_max"]) <= float(bounds[f"{axis}_min"])
            for axis in ("x", "y", "z")
        ):
            raise ValueError("accelerator entrance local active bounds are invalid")
        if any(
            not math.isfinite(float(local["instance_origin_mm"].get(axis, math.nan)))
            for axis in ("x", "y", "z")
        ) or any(
            not math.isfinite(float(local["cell_mm_xyz"].get(axis, math.nan)))
            or float(local["cell_mm_xyz"][axis]) <= 0
            for axis in ("x", "y", "z")
        ):
            raise ValueError(
                "accelerator entrance local placement contract is incomplete"
            )
        if intermediate_overlay is not None:
            raise ValueError(
                "accelerator entrance local and legacy intermediate2 overlay are mutually exclusive"
            )
    if intermediate_overlay is not None and domain_split is None:
        if overlay is None:
            raise ValueError("intermediate accelerator overlay requires an entrance overlay")
        if overlay.get("region_id") != "entrance":
            raise ValueError("two-overlay Program requires an entrance primary overlay")
        if intermediate_overlay.get("region_id") != "intermediate2":
            raise ValueError("two-overlay Program requires an intermediate2 secondary overlay")
    three_zone = frontend.get("accelerator_topology_id") is not None
    governed_overlay = (
        accelerator_entrance_local
        if accelerator_entrance_local is not None
        else intermediate_overlay
        if domain_split is not None
        else overlay
    )
    if domain_split_main_pa_only_axis_field and (
        domain_split is None
        or not include_total_axis_field_exporter
        or overlay is not None
        or intermediate_overlay is not None
        or accelerator_entrance_local is not None
        or screening
    ):
        raise ValueError(
            "main-PA-only domain split is permitted only for overlay-free axis-field export"
        )
    if domain_split_local_axis_field and (
        domain_split is None
        or not include_total_axis_field_exporter
        or accelerator_entrance_local is None
        or screening
    ):
        raise ValueError(
            "local domain split is permitted only for entrance-local axis-field export"
        )
    if three_zone and not pre_pulse_accelerator_zero_field and not domain_split_main_pa_only_axis_field and (
        governed_overlay is None
        or (
            accelerator_entrance_local is None
            and frontend["accelerator_local_region"].get("intermediate2_grid_provider")
            != "accelerator_overlay"
        )
        or not math.isfinite(float(governed_overlay["cell_mm_xyz"]["z"]))
        or float(governed_overlay["cell_mm_xyz"]["z"]) <= 0
    ):
        raise ValueError(
            "three-zone single-flight Program requires the governed accelerator overlay with a positive grid"
        )
    if (
        domain_split is not None
        and not pre_pulse_accelerator_zero_field
        and not domain_split_main_pa_only_axis_field
        and not reduced_post_accelerator_iob
    ):
        required_domain_keys = {
            "upstream_instance_index", "accelerator_instance_index",
            "upstream_end_x_mm", "accelerator_start_x_mm",
            "upstream_bounds_mm", "accelerator_bounds_mm",
            "upstream_origin_mm", "accelerator_origin_mm",
        }
        if (
            not isinstance(domain_split, dict)
            or (
                frozenset(domain_split) not in {
                    frozenset(required_domain_keys),
                    frozenset(required_domain_keys | {"accelerator_zero_field"}),
                    frozenset(required_domain_keys | {"pa_plus_solution_model"}),
                    frozenset(required_domain_keys | {"accelerator_zero_field", "pa_plus_solution_model"}),
                }
            )
            or domain_split["upstream_instance_index"] != 2
            or domain_split["accelerator_instance_index"] != 3
            or overlay is not None
            or (
                not pre_pulse_accelerator_zero_field
                and not domain_split_main_pa_only_axis_field
                and intermediate_overlay is None
                and accelerator_entrance_local is None
            )
        ):
            raise ValueError("domain-split Program contract is incomplete")
    if accelerator_entrance_local is not None and (
        domain_split is None or screening or domain_split_main_pa_only_axis_field
    ):
        raise ValueError(
            "accelerator entrance local is permitted only in ordinary domain-split full flight"
        )
    validate_resolved_region_field_contract(region_field_contract)
    sources = {
        "analyzer component": analyzer_component_source,
        "pulse hook": pulse_hook_source,
        "frontend hook": frontend_hook_source,
        "RF drive kernel": rf_drive_kernel_source,
    }
    normalized = {
        name: validate_pure_lua_component_source(
            source.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n"), name
        )
        for name, source in sources.items()
    }
    region_hook = validate_pure_lua_component_source(
        resolved_region_field_hook_lua(region_field_contract),
        "resolved region field hook",
    )
    drive = upstream["drive"]
    if drive["waveform"] not in {"sine", "cosine"}:
        raise ValueError("single-flight Program RF waveform must be sine or cosine")
    rod_ids = segmented_rod_electrode_ids(
        upstream["segmentation"]["segmented_rod_array"]
    )
    if rod_ids != list(ROD_ELECTRODE_IDS):
        raise ValueError("single-flight Program requires multipole electrodes 1 through 8")
    electrode_rows = {
        int(item["electrode_id"]): item
        for item in upstream["segmentation"]["segmented_rod_array"]["electrodes"]
    }
    potentials = {
        int(item["electrode_id"]): float(item["potential_V"])
        for item in upstream["axial_dc"]["rod_electrodes"]
    }
    rf_electrodes = []
    for electrode_id in ROD_ELECTRODE_IDS:
        group = int(electrode_rows[electrode_id]["electrode_group"])
        rf_electrodes.append(
            {
                "electrode_id": electrode_id,
                "electrode_group": group,
                "polarity": 1 if group == 1 else -1,
                "common_mode_v": potentials[electrode_id],
            }
        )
    analyzer_config = _successor_analyzer_config(oatof, frontend, region_field_contract)
    # The PA basis namespace is derived from the frozen frontend contract and
    # shared by accelerator_main and its entrance-local replacement.  Basis
    # zero is SIMION's non-electrode background and the grounded shield is a
    # fixed zero-volt boundary; every *other* physical electrode, including
    # RF rod 1, must remain present for the PA+ projection source table.
    grounded_shield_id = int(frontend["electrodes"]["grounded_shield_id"])
    dynamic_basis_electrode_ids = [
        int(electrode_id)
        for electrode_id in resolve_frontend_electrode_topology(
            frontend["electrodes"]
        )["basis_electrode_ids"]
        if int(electrode_id) not in {0, grounded_shield_id}
    ]
    # The pre-pulse entrance zone is intentionally geometry-only: its
    # accelerator-main contract retains the reusable PA+ model as metadata,
    # but sets it to null because no accelerator field is loaded.  Do not
    # dereference or wire PA+ modes in this legitimate zero-field phase.
    pa_plus_model = (
        None
        if pre_pulse_accelerator_zero_field
        else domain_split.get("pa_plus_solution_model")
        if domain_split is not None
        else None
    )
    pa_plus_modes = [
        {
            "mode_id": int(mode["mode_id"]),
            # A PA+ solution is already the weighted electrode shape.  Its
            # adjustable value is the independent source electrode voltage;
            # the ring weights belong to the PA+ geometry, not to runtime
            # voltage accumulation.
            "source_electrode_id": int(mode["source_physical_electrode_id"]),
            "terms": [
                {"electrode_id": int(electrode_id), "coefficient": float(coefficient)}
                for electrode_id, coefficient in mode["physical_electrode_coefficients"].items()
            ],
        }
        for mode in (pa_plus_model or {}).get("modes", [])
    ]
    pa_plus_modes_lua = _lua_value(pa_plus_modes)
    pre_pulse_compact_iob = pre_pulse_entry_geometry
    if pre_pulse_compact_iob:
        # In the pre-pulse-only IOB there is no downstream flight hardware.
        # Keep the three loaded PA instances contiguous in physical order:
        # coarse frontend, upstream RF fine PA, then zero-field entrance.
        analyzer_config["instance_roles"] = {
            "flight_tube": 1,
            "reflectron": 2,
            "accelerator": 3,
            "detector": 4,
        }
    if (
        domain_split is not None
        and not pre_pulse_accelerator_zero_field
        and not domain_split_main_pa_only_axis_field
        and not reduced_post_accelerator_iob
    ):
        # The continuous seven-instance IOB uses slots 1--3 for the coarse,
        # upstream, and main accelerator domains.  The downstream formal
        # hardware follows in slots 4, 5, and 7; the local aperture replacement
        # deliberately keeps slot 6 for highest-priority overlap semantics.
        analyzer_config["instance_roles"] = {
            "accelerator": 3,
            "flight_tube": 4,
            "reflectron": 5,
            "detector": 7,
        }
    analyzer_config["domain_split"] = domain_split is not None
    overlay_specs: list[dict[str, Any]] = []
    if (
        domain_split is not None
        and not pre_pulse_accelerator_zero_field
        and not domain_split_main_pa_only_axis_field
    ):
        if accelerator_entrance_local is not None:
            overlay_specs.append(
                {
                    "role": "accelerator_entrance_aperture_local",
                    "instance_index": 5 if reduced_post_accelerator_iob else 6,
                    "filename": "accelerator_entrance_local.pa0",
                    "origin_mm": accelerator_entrance_local["instance_origin_mm"],
                    "bounds_mm": accelerator_entrance_local["active_bounds_mm"],
                }
            )
        else:
            overlay_specs.append(
                {
                    "role": "accelerator_intermediate_overlay",
                    "instance_index": 6,
                    "filename": "accelerator_intermediate_overlay.pa0",
                    "origin_mm": intermediate_overlay["instance_origin_mm"],
                    "bounds_mm": intermediate_overlay["active_bounds_mm"],
                }
            )
    elif overlay is not None:
        if intermediate_overlay is None:
            overlay_specs.append(
                {
                    "role": "accelerator_overlay",
                    "instance_index": 5,
                    "filename": "accelerator_overlay.pa0",
                    "origin_mm": overlay["instance_origin_mm"],
                    "bounds_mm": overlay["active_bounds_mm"],
                }
            )
        else:
            overlay_specs.append(
                {
                    "role": "accelerator_entrance_overlay",
                    "instance_index": 5,
                    "filename": "accelerator_entrance_overlay.pa0",
                    "origin_mm": overlay["instance_origin_mm"],
                    "bounds_mm": overlay["active_bounds_mm"],
                }
            )
            overlay_specs.append(
                {
                    "role": "accelerator_intermediate_overlay",
                    "instance_index": 6,
                    "filename": "accelerator_intermediate_overlay.pa0",
                    "origin_mm": intermediate_overlay["instance_origin_mm"],
                    "bounds_mm": intermediate_overlay["active_bounds_mm"],
                }
            )
    overlay_roles = {
        str(item["role"]): int(item["instance_index"])
        for item in overlay_specs
    }
    overlay_filenames = {
        str(item["role"]): str(item["filename"])
        for item in overlay_specs
    }
    domain_active_roles = (
        # A continuous source retains the coarse and upstream RF domains and
        # reaches only the raw, zero-field entrance geometry.  A terminal
        # handoff has already left the multipole, so it uses just the two raw
        # geometry domains.  Neither mode loads a refined accelerator field.
        ["accelerator", "upstream_bridge"]
        if pre_pulse_collision_only
        else ["coarse_frontend", "upstream_bridge", "accelerator"]
        if pre_pulse_entry_geometry
        else ["accelerator", *overlay_roles]
        if reduced_post_accelerator_iob
        else ["coarse_frontend", "accelerator", "upstream_bridge", *overlay_roles]
        if domain_split is not None
        else ["accelerator", *overlay_roles]
    )
    domain_accelerator_filename = (
        "accelerator_entrance_zero_field.pa0"
        if pre_pulse_accelerator_zero_field
        else "accelerator_main.pa0"
        if domain_split is not None
        else "accelerator.pa0"
    )
    # The analyzer component validates the physical Workbench payload before
    # the Program's separate role map is consulted.  Keep both views derived
    # from the same resolved domain contract.
    analyzer_config["instance_filenames"]["accelerator"] = (
        domain_accelerator_filename
    )
    formal_iob_config = (
        {
            "instance_roles": {
                "coarse_frontend": 1,
                "upstream_bridge": 2,
                "accelerator": 3,
            },
            "instance_filenames": {
                "coarse_frontend": "coarse_frontend.pa0",
                "accelerator": domain_accelerator_filename,
                "upstream_bridge": "upstream_bridge.pa0",
            },
            "pre_pulse_active_roles": domain_active_roles,
            "accelerator_overlays": [],
        }
        if pre_pulse_compact_iob
        else {
        "instance_roles": {
            **(
                {"flight_tube": 1}
                if reduced_post_accelerator_iob or domain_split is None
                else {"coarse_frontend": 1, "upstream_bridge": 2}
            ),
            "reflectron": 2 if reduced_post_accelerator_iob or domain_split is None else 5,
            "accelerator": 3,
            "detector": 4 if reduced_post_accelerator_iob or domain_split is None else 7,
            **overlay_roles,
        },
        "instance_filenames": {
            **(
                {"flight_tube": "flight_tube_ground.pa0"}
                if reduced_post_accelerator_iob or domain_split is None
                else {
                    "coarse_frontend": "coarse_frontend.pa0",
                    "upstream_bridge": "upstream_bridge.pa0",
                }
            ),
            "reflectron": "reflectron.pa0",
            "accelerator": domain_accelerator_filename,
            "detector": "detector_ground.pa0",
            **overlay_filenames,
        },
        "pre_pulse_active_roles": domain_active_roles,
        "accelerator_overlays": [
            {
                "role": str(item["role"]),
                "instance_index": int(item["instance_index"]),
                "filename": str(item["filename"]),
            }
            for item in overlay_specs
        ],
        }
    )
    formal_iob_config_lua = _lua_value(formal_iob_config)
    analyzer_config_static = dict(analyzer_config)
    analyzer_config_static.pop("diagnostics")
    analyzer_config_lua = _lua_value(analyzer_config_static)[:-1] + (
        ",diagnostics={max_tof_us=diagnostic_max_tof_us,"
        "log_stride=trajectory_log_stride}}"
    )
    geometry = analyzer_config["geometry"]
    pulse_voltage_lua = (
        "{pre_all_v=handoff_pulse_pre_all_v,repeller_v=V_repeller,"
        "grid1_v=V_grid1,intermediate2_v=V_intermediate2,exit_v=V_exit}"
        if three_zone
        else "{pre_all_v=handoff_pulse_pre_all_v,repeller_v=V_repeller,grid1_v=V_grid1}"
    )
    initial_voltage_lua = pulse_voltage_lua.replace(
        "pre_all_v=handoff_pulse_pre_all_v", "pre_all_v=0"
    )
    three_zone_adjustables = (
        f"adjustable V_intermediate2={_lua_number(analyzer_config['voltages']['intermediate2_v'])}\n"
        f"adjustable V_exit={_lua_number(analyzer_config['voltages']['exit_v'])}\n"
        if three_zone
        else ""
    )
    intermediate2_local = (
        "local accelerator_intermediate2_z_mm="
        f"{_lua_number(geometry['accelerator_intermediate2_z_mm'])}\n"
        if three_zone
        else ""
    )
    accelerator_planes_lua = (
        "{accelerator_grid1_z_mm,accelerator_intermediate2_z_mm,"
        "accelerator_grid2_z_mm}"
        if three_zone
        else "{accelerator_grid1_z_mm,accelerator_grid2_z_mm}"
    )
    intermediate2_crossing_lua = (
        "  _,tc,xc,yc,vxc,vyc,vzc=crossing(accelerator_intermediate2_z_mm,1)\n"
        "  if tc and not reported.intermediate2 then reported.intermediate2=true\n"
        "    if trajectory_log_enable~=0 then print(string.format('TRACE: accelerator_intermediate2_forward ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,tc,xc,yc,accelerator_intermediate2_z_mm,vxc,vyc,vzc)) end\n"
        "  end\n"
        if three_zone
        else ""
    )
    electrodes = frontend["electrodes"]
    accelerator_instance_index = 3
    detector_instance_index = 4
    origin = (
        domain_split["accelerator_origin_mm"]
        if domain_split is not None
        else frontend["instance_origin_mm"]
    )
    active_field_instance_indices = (
        ([] if pre_pulse_collision_only else
        [1, 2] if pre_pulse_entry_geometry else
         [accelerator_instance_index, *[int(item["instance_index"]) for item in overlay_specs]]
         if reduced_post_accelerator_iob else
         [1, 2, 3, *[int(item["instance_index"]) for item in overlay_specs]])
        if domain_split is not None
        else [3, *[int(item["instance_index"]) for item in overlay_specs]]
    )
    # The coarse and upstream domains retain physical electrode solutions,
    # whereas accelerator_main and its complete entrance replacement consume
    # PA+ modes.  SIMION harmlessly ignores an adjustment number absent from a
    # particular instance, so one fast-adjust callback can drive both families
    # without coupling their geometry or duplicating a voltage schedule.
    pa_plus_instance_indices = (
        [accelerator_instance_index, *[int(item["instance_index"]) for item in overlay_specs]]
        if pa_plus_modes
        else []
    )
    pre_pulse_scope_instance_indices = (
        [1, 2, 3] if pre_pulse_entry_geometry else active_field_instance_indices
    )
    overlay_specs_lua = _lua_value(overlay_specs)
    active_field_instance_indices_lua = _lua_value(active_field_instance_indices)
    pre_pulse_scope_instance_indices_lua = _lua_value(pre_pulse_scope_instance_indices)
    entrance_reference_v = float(
        upstream["axial_dc"]["entrance_reference_sleeve"]["potential_V"]
    )
    entrance_plate_v = float(upstream["axial_dc"]["entrance_plate_potential_V"])
    birth_table = "{" + ",".join(
        f"[{index}]={_lua_number(value)}"
        for index, value in enumerate(birth_times_us, start=1)
    ) + "}"
    particle_id_table = "{" + ",".join(
        f"[{index}]={value}" for index, value in enumerate(particle_ids, start=1)
    ) + "}"
    screening_sample_table = "{" + ",".join(
        f"[{index}]={_lua_number(value)}"
        for index, value in enumerate(sample_times_us, start=1)
    ) + "}"
    embedded_components = [
        ("single_flight_analyzer_component", normalized["analyzer component"]),
        ("single_flight_pulse_component", normalized["pulse hook"]),
        ("single_flight_frontend_component", normalized["frontend hook"]),
    ]
    if rf_enabled:
        embedded_components.append(
            ("single_flight_rf_kernel", normalized["RF drive kernel"])
        )
    embedded_components.append(("single_flight_region_field", region_hook))
    embedded = "\n".join(
        f"local {name}=(function()\n{source}\nend)()"
        for name, source in embedded_components
    )
    rf_adjustable = (
        f"adjustable single_flight_rf_steps={rf_steps_per_period}\n"
        if rf_enabled else ""
    )
    screening_rf_assert = (
        f"    assert(single_flight_rf_steps=={int(rf_steps_per_period)},\n"
        "      'pre-pulse time-series screening requires the frozen native solver RF step count')\n"
        if rf_enabled and screening else ""
    )
    rf_initializer = (
        f"""    rf=single_flight_rf_kernel.new{{waveform={json.dumps(drive['waveform'])},frequency_hz=single_flight_frequency_hz,
      phase_rad=single_flight_phase_rad,rf_amplitude_v=single_flight_rf_peak_v,rf_scale=single_flight_rf_scale,
      common_mode_scale=single_flight_common_mode_scale,group_dc_v={{[1]=single_flight_dc_amplitude_v,[2]=-single_flight_dc_amplitude_v}},
      rf_steps_per_period=single_flight_rf_steps,electrodes={_lua_value(rf_electrodes)}}}
"""
        if rf_enabled else ""
    )
    rf_static_apply = (
        "    rf.apply_static(function(id,value) initial[id]=value end)\n"
        if rf_enabled else ""
    )
    rf_config = "rf" if rf_enabled else "false"
    global_setup = "\nsimion.early_access(8.2)\nsim_segment_global=1" if global_segments else ""
    program = f"""simion.workbench_program(){global_setup}
{embedded}
adjustable V_repeller={_lua_number(analyzer_config['voltages']['repeller_v'])}
adjustable V_grid1={_lua_number(analyzer_config['voltages']['grid1_v'])}
{three_zone_adjustables}adjustable V_mid={_lua_number(oatof['electrodes_V']['midgrid'])}
adjustable V_backplate={_lua_number(oatof['electrodes_V']['backplate'])}
adjustable trajectory_quality=8
adjustable trajectory_log_enable={1 if screening else 0}
adjustable trajectory_log_stride=1000
adjustable diagnostic_max_tof_us=90
adjustable handoff_pulse_mode={2 if screening else 1}
adjustable handoff_pulse_time_us=0
adjustable handoff_pulse_width_us=1
adjustable handoff_pulse_pre_all_v=0
adjustable single_flight_enable=1
adjustable single_flight_rf_peak_v={_lua_number(drive['rf_amplitude_V_zero_to_peak_per_group'])}
adjustable single_flight_frequency_hz={_lua_number(drive['frequency_Hz'])}
adjustable single_flight_phase_rad={_lua_number(drive['phase_rad'])}
adjustable single_flight_dc_amplitude_v={_lua_number(drive['dc_amplitude_V_per_group'])}
adjustable single_flight_rf_scale=1
adjustable single_flight_common_mode_scale=1
{rf_adjustable}local single_flight_rf_enabled={1 if rf_enabled else 0}
local accelerator_repeller_front_z_mm={_lua_number(geometry['accelerator_repeller_front_z_mm'])}
local accelerator_grid1_z_mm={_lua_number(geometry['accelerator_grid1_z_mm'])}
{intermediate2_local}local accelerator_grid2_z_mm={_lua_number(geometry['accelerator_grid2_z_mm'])}
local reflectron_entgrid_z_mm={_lua_number(geometry['reflectron_entgrid_z_mm'])}
local reflectron_midgrid_z_mm={_lua_number(geometry['reflectron_midgrid_z_mm'])}
local reflectron_backplate_z_mm={_lua_number(geometry['reflectron_backplate_z_mm'])}
local single_flight_birth_time_us={birth_table}
local single_flight_source_particle_id={particle_id_table}
local single_flight_particle_id_offset=assert(tonumber(os.getenv('OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET') or '0'),'invalid single-flight particle ID offset')
local single_flight_terminate_after_pulse={1 if terminate_after_pulse else 0}
local single_flight_pre_pulse_time_series={1 if screening else 0}
local single_flight_pre_pulse_natural_archive={1 if natural_pre_pulse_archive else 0}
local single_flight_pre_pulse_sample_times_us={screening_sample_table}
local single_flight_pre_pulse_next_sample={{}}
local single_flight_pre_pulse_grid_origin_us={_lua_number(grid_origin_us)}
local single_flight_pre_pulse_grid_step_us={_lua_number(grid_step_us)}
  local single_flight_overlay_enabled={1 if overlay_specs else 0}
  local single_flight_overlays={overlay_specs_lua}
local single_flight_active_field_instances={active_field_instance_indices_lua}
local single_flight_pre_pulse_scope_instances={pre_pulse_scope_instance_indices_lua}
local single_flight_domain_split_enabled={1 if domain_split is not None else 0}
local single_flight_pre_pulse_collision_only={1 if pre_pulse_collision_only else 0}
local single_flight_pre_pulse_accelerator_zero_field={1 if pre_pulse_accelerator_zero_field else 0}
local single_flight_accelerator_instance_index={3 if pre_pulse_compact_iob else 3}
local single_flight_flight_tube_instance_index={int(analyzer_config['instance_roles']['flight_tube'])}
local single_flight_reflectron_instance_index={int(analyzer_config['instance_roles']['reflectron'])}
local single_flight_detector_instance_index={int(analyzer_config['instance_roles']['detector'])}
local single_flight_post_pulse_handoff_minimal={1 if reduced_post_accelerator_iob else 0}
local single_flight_analyzer=nil
local single_flight_pulse=nil
local single_flight_frontend=nil
local single_flight_particle_state={{}}
local single_flight_analyzer_initialized={{}}
local single_flight_previous={{}}
local single_flight_reported={{}}
local single_flight_accelerator_pa_override=os.getenv('OATOF_ACCELERATOR_PA_OVERRIDE')
local single_flight_accelerator_pa_override_loaded=false
local function single_flight_source_row_index()
  return ion_number+single_flight_particle_id_offset
end
local function single_flight_canonical_particle_id()
  local particle_id=single_flight_source_particle_id[single_flight_source_row_index()]
  assert(particle_id~=nil,'explicit single-flight row map is missing a source particle ID')
  return particle_id
end
local function single_flight_instrument_time_us()
  local birth=single_flight_birth_time_us[single_flight_source_row_index()]
  assert(birth~=nil,'absolute single-flight clock is missing particle birth time')
  return birth+ion_time_of_flight
end
handoff_instrument_time_us=single_flight_instrument_time_us
local single_flight_pa_plus_modes={pa_plus_modes_lua}
local single_flight_pa_plus_instance_indices={_lua_value(pa_plus_instance_indices)}
local single_flight_pa_plus_source={{}}
local function single_flight_is_pa_plus_instance(index)
  for _,pa_plus_index in ipairs(single_flight_pa_plus_instance_indices) do
    if index==pa_plus_index then return true end
  end
  return false
end
local function single_flight_project_pa_plus(source)
  local values={{}}
  for _,mode in ipairs(single_flight_pa_plus_modes) do
    values[mode.mode_id]=assert(source[mode.source_electrode_id],
      'PA+ source voltage is missing independent electrode '..mode.source_electrode_id)
  end
  return values
end
local function single_flight_set_electrode(id,value)
  -- ``adj_elect`` is scoped to the PA currently traversed by the ion.  The
  -- coarse/upstream families expose physical IDs, whereas PA+ exposes only
  -- compact mode IDs.  Never write a physical ID into a PA+ array: SIMION
  -- treats that as an absent electrode, not as a harmless no-op.
  if not single_flight_is_pa_plus_instance(ion_instance) then
    adj_elect[id]=value
    return
  end
  single_flight_pa_plus_source[id]=value
  for mode_id,mode_value in pairs(single_flight_project_pa_plus(single_flight_pa_plus_source)) do
    adj_elect[mode_id]=mode_value
  end
end
local single_flight_trace_path=os.getenv('OATOF_PRE_PULSE_RAW_TRACE_PATH')
local single_flight_trace_stream=nil
if single_flight_trace_path~=nil and single_flight_trace_path~='' then
  single_flight_trace_stream=assert(io.open(single_flight_trace_path,'w'))
end
local function single_flight_write_trace(record)
  if single_flight_trace_stream~=nil then
    single_flight_trace_stream:write(record,'\\n')
  else
    print(record)
  end
end
local function single_flight_trace_checkpoint(event,t,x,y,z,vx,vy,vz)
  if trajectory_log_enable==0 then return end
  local particle_id=single_flight_canonical_particle_id()
  local energy=0.0051821348263402529*ion_mass*(vx*vx+vy*vy+vz*vz)
  single_flight_write_trace(string.format('TRACE: %s ion=%d particle_id=%d instrument_time_us=%.12g tof_since_pulse_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g kinetic_energy_eV=%.12g survival_status=alive',
    event,ion_number,particle_id,t,t-handoff_pulse_time_us,x,y,z,vx,vy,vz,energy))
end
local function single_flight_require_analyzer_particle(elapsed)
  if not single_flight_analyzer_initialized[ion_number] then
    single_flight_analyzer.initialize_particle{{particle_id=single_flight_canonical_particle_id(),elapsed_us=elapsed,
      x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm}}
    single_flight_analyzer_initialized[ion_number]=true
  end
end
local function single_flight_require_particle_state()
  local state=single_flight_particle_state[ion_number]
  if state==nil then
    local time=single_flight_instrument_time_us()
    state={{frontend=single_flight_frontend.initialize_particle(ion_pz_mm),
      previous={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}}}
    single_flight_particle_state[ion_number]=state
  end
  return state
end
local function single_flight_apply_plan(pa,plan)
  local values={{}}
  for _,item in ipairs(plan) do values[item.electrode_id]=item.voltage_v end
  pa:fast_adjust(values)
end
local function single_flight_exact_basename(value,label)
  assert(type(value)=='string',label..' filename must be a string')
  local basename=value:gsub('\\\\','/'):match('([^/]+)$')
  assert(basename and basename~='',label..' basename is missing')
  return basename
end
local function single_flight_assert_formal_iob_roles(config)
  if single_flight_pre_pulse_time_series~=0 then
    for _,role in ipairs(config.pre_pulse_active_roles) do
      local index=config.instance_roles[role]
      local item=assert(simion.wb.instances[index],
        'pre-pulse screening '..role..' instance is missing')
      assert(single_flight_exact_basename(item.filename,
        'formal IOB role '..role)==config.instance_filenames[role],
        'formal IOB role '..role..' filename differs')
    end
    return
  end
  local role_count=0
  for _ in pairs(config.instance_roles) do role_count=role_count+1 end
  assert(#simion.wb.instances==role_count,
    'formal single-flight IOB instance count differs')
  for role,index in pairs(config.instance_roles) do
    assert(single_flight_exact_basename(simion.wb.instances[index].filename,
      'formal IOB role '..role)==config.instance_filenames[role],
      'formal IOB role '..role..' filename differs')
  end
end
local function single_flight_overlay_for_instance(instance_index)
  for _,overlay in ipairs(single_flight_overlays) do
    if overlay.instance_index==instance_index then return overlay end
  end
  return nil
end
local function single_flight_is_overlay_instance(instance_index)
  return single_flight_overlay_for_instance(instance_index)~=nil
end
local function single_flight_is_active_field_instance(instance_index)
  for _,index in ipairs(single_flight_active_field_instances) do
    if index==instance_index then return true end
  end
  return false
end
local function single_flight_is_pre_pulse_scope_instance(instance_index)
  for _,index in ipairs(single_flight_pre_pulse_scope_instances) do
    if index==instance_index then return true end
  end
  return false
end
local function single_flight_instance_state(instance)
  return {{filename=instance.filename,nx=instance.pa.nx,ny=instance.pa.ny,
    nz=instance.pa.nz,dx_mm=instance.pa.dx_mm,dy_mm=instance.pa.dy_mm,
    dz_mm=instance.pa.dz_mm,scale=instance.scale}}
end
local function single_flight_workbench_state(active_scope)
  if active_scope=='pre_pulse_frontend_accelerator' then
    return {{active_scope=active_scope,instances={{
      [single_flight_accelerator_instance_index]=single_flight_instance_state(assert(simion.wb.instances[single_flight_accelerator_instance_index],
        'pre-pulse screening accelerator instance is missing'))}}}}
  end
  local instances={{}}
  for index=1,#simion.wb.instances do
    local instance=simion.wb.instances[index]
    instances[index]=single_flight_instance_state(instance)
  end
  return {{instances=instances}}
end
local function single_flight_apply_placement(instance,placement)
  instance.x,instance.y,instance.z=placement.x_mm,placement.y_mm,placement.z_mm
  instance.az,instance.el,instance.rt,instance.scale=placement.az_deg,placement.el_deg,placement.rt_deg,placement.scale
end
local function single_flight_project_electrode_plan()
  return {{apply_at=function(_,pulse_state,setter)
    setter({int(electrodes['grounded_shield_id'])},0)
    local plan=single_flight_analyzer.accelerator_electrode_write_plan(
      pulse_state.active and 'on' or 'off',
      {pulse_voltage_lua})
    for _,item in ipairs(plan) do setter(item.electrode_id,item.voltage_v) end
    setter({int(electrodes['entrance_reference_sleeve_id'])},{_lua_number(entrance_reference_v)})
    setter({int(electrodes['entrance_plate_id'])},{_lua_number(entrance_plate_v)})
  end}}
end
function segment.load()
  sim_trajectory_quality=trajectory_quality
  local path=os.getenv('OATOF_SIMION_PROGRAM_LOAD_REPORT')
  if path and path~='' then local report=assert(io.open(path,'w')); report:write(string.format('TRAJECTORY_QUALITY=%g\\nSTATUS=PASS\\n',sim_trajectory_quality)); report:close() end
end
function segment.initialize_run()
  assert(single_flight_enable~=0,'single-flight Program requires explicit enable')
  if single_flight_pre_pulse_time_series~=0 then
    assert(handoff_pulse_mode==2,
      'pre-pulse time-series screening requires the existing held-off pulse mode')
{screening_rf_assert}
  end
  sim_trajectory_quality=trajectory_quality
  local analyzer_config={analyzer_config_lua}
  local formal_iob_config={formal_iob_config_lua}
  single_flight_assert_formal_iob_roles(formal_iob_config)
  local ai=simion.wb.instances[analyzer_config.instance_roles.accelerator]
  if single_flight_domain_split_enabled~=0 then
    assert(not single_flight_accelerator_pa_override or
      single_flight_accelerator_pa_override=='',
      'domain-split Program must use its accelerator-main PA, not a monolithic override')
  elseif single_flight_accelerator_pa_override and single_flight_accelerator_pa_override~='' and
      not single_flight_accelerator_pa_override_loaded then
    ai.pa:load(single_flight_accelerator_pa_override)
    ai:_debug_update_size()
    single_flight_accelerator_pa_override_loaded=true
  end
  if single_flight_domain_split_enabled==0 and single_flight_accelerator_pa_override and
      single_flight_accelerator_pa_override~='' then
    assert(single_flight_exact_basename(single_flight_accelerator_pa_override,
      'accelerator override')=='frontend.pa0',
      'accelerator override payload basename differs')
    analyzer_config.instance_filenames.accelerator='frontend.pa0'
  end
  single_flight_analyzer=single_flight_analyzer_component.new(analyzer_config)
  local active_scope=single_flight_pre_pulse_time_series~=0 and
    'pre_pulse_frontend_accelerator' or 'full_flight'
  local initialized=single_flight_analyzer.initialize_workbench(
    single_flight_workbench_state(active_scope))
  if single_flight_pre_pulse_time_series==0 and
      (single_flight_domain_split_enabled==0 or single_flight_post_pulse_handoff_minimal~=0) then
    single_flight_apply_placement(simion.wb.instances[1],initialized.placements.flight_tube)
  end
  if single_flight_pre_pulse_time_series==0 then
    single_flight_apply_placement(simion.wb.instances[single_flight_reflectron_instance_index],initialized.placements.reflectron)
  end
  single_flight_apply_placement(ai,initialized.placements.accelerator)
  ai.x,ai.y,ai.z={_lua_number(origin['x'])},{_lua_number(origin['y'])},{_lua_number(origin['z'])}
  if single_flight_pre_pulse_time_series==0 then
    single_flight_apply_placement(simion.wb.instances[single_flight_detector_instance_index],initialized.placements.detector)
  end
  if single_flight_pre_pulse_accelerator_zero_field==0 and #single_flight_pa_plus_modes==0 then
    single_flight_apply_plan(ai.pa,initialized.static_electrode_plans.legacy_accelerator_characterization)
  end
  if single_flight_pre_pulse_time_series==0 then
    single_flight_apply_plan(simion.wb.instances[single_flight_reflectron_instance_index].pa,initialized.static_electrode_plans.reflectron)
  end
  local rf=false
{rf_initializer}
    single_flight_pulse=single_flight_pulse_component.new{{canonical_clock=single_flight_instrument_time_us,
      pulse_time_us=handoff_pulse_time_us,pulse_width_us=handoff_pulse_width_us,pulse_mode=function() return handoff_pulse_mode end}}
    single_flight_frontend=single_flight_frontend_component.new{{rf_drive={rf_config},pulse_hook=single_flight_pulse,
      electrode_plan=single_flight_project_electrode_plan(),planes_z_mm={accelerator_planes_lua}}}
    local initial={{}}
{rf_static_apply}
    -- PA+ projection runs before SIMION creates the first ion.  Preserve RF's
    -- static source values above, and seed any remaining physical electrodes
    -- so every compact PA+ mode receives a complete source vector.  The first
    -- normal fast-adjust callback replaces this neutral seed with the frozen
    -- pulse/RF state for the ion's actual instrument time.
    for _,physical_id in ipairs({_lua_value(dynamic_basis_electrode_ids)}) do
      if initial[physical_id]==nil then initial[physical_id]=0 end
    end
    initial[{int(electrodes['grounded_shield_id'])}]=0
    for _,item in ipairs(single_flight_analyzer.accelerator_electrode_write_plan('off',
        {initial_voltage_lua})) do initial[item.electrode_id]=item.voltage_v end
    initial[{int(electrodes['entrance_reference_sleeve_id'])}]={_lua_number(entrance_reference_v)}
    initial[{int(electrodes['entrance_plate_id'])}]={_lua_number(entrance_plate_v)}
    single_flight_pa_plus_source=initial
    local initial_pa_plus=single_flight_project_pa_plus(initial)
    -- ``adj_elect`` exists only inside SIMION's fast-adjust callback.  Seed
    -- the already loaded PA families explicitly here, choosing their native
    -- basis namespace; the later dynamic callback writes both namespaces.
    for _,index in ipairs(single_flight_active_field_instances) do
      local active_instance=assert(simion.wb.instances[index],
        'active domain field instance is missing')
      active_instance.pa:fast_adjust(
        single_flight_is_pa_plus_instance(index) and initial_pa_plus or initial)
    end
    for _,overlay in ipairs(single_flight_overlays) do
      local oi=assert(simion.wb.instances[overlay.instance_index],
        'accelerator overlay instance is missing')
      assert(single_flight_exact_basename(oi.filename,
        overlay.role)==overlay.filename,
        'accelerator overlay filename differs')
      oi.x,oi.y,oi.z=overlay.origin_mm.x,overlay.origin_mm.y,overlay.origin_mm.z
      oi.az,oi.el,oi.rt,oi.scale=0,0,0,1
    end
  single_flight_particle_state={{}}
  single_flight_analyzer_initialized={{}}
  single_flight_previous={{}}
  single_flight_reported={{}}
end
function segment.efield_adjust()
  if single_flight_pre_pulse_time_series~=0 and single_flight_pre_pulse_collision_only==0 then
    assert(single_flight_is_pre_pulse_scope_instance(ion_instance),
      'pre-pulse screening particle escaped its frontend/accelerator active scope')
  end
  -- SIMION invokes this callback while an ion traverses the vacuum gap between
  -- non-overlapping PA instances.  There is no PA field to adjust in that gap.
  local instance=simion.wb.instances[ion_instance]
  if instance==nil then return end
  local state={{z_mm=ion_pz_mm,instance_id=ion_instance,instance_dx_mm=instance.pa.dx_mm,
    instance_dz_mm=instance.pa.dz_mm,instance_scale=instance.scale}}
  local base=single_flight_analyzer.efield_adjust(state)
  state.pulse_active=single_flight_pulse.is_active_at(single_flight_instrument_time_us())
  local result=single_flight_region_field.apply(base,state)
  if result then
    if result.replace_all then ion_dvoltsx_gu=0; ion_dvoltsy_gu=0; ion_dvoltsz_gu=0 end
    if result.dvoltsx_gu~=nil then ion_dvoltsx_gu=result.dvoltsx_gu end
    if result.dvoltsy_gu~=nil then ion_dvoltsy_gu=result.dvoltsy_gu end
    if result.dvoltsz_gu~=nil then ion_dvoltsz_gu=result.dvoltsz_gu end
  end
end
function segment.fast_adjust()
  if single_flight_is_active_field_instance(ion_instance) then
    -- The detector-blind pre-pulse contract holds the extraction pulse off.
    -- Its accelerator and grounded-boundary voltages were consequently
    -- materialized once in initialize_run.  Updating those same static
    -- electrodes at every RF step makes SIMION retain every accelerator basis
    -- array, although only the eight rod bases vary.  Preserve the identical
    -- static table and update just the RF rods while screening.  Full flight
    -- continues to apply the complete pulse-dependent electrode plan.
    if single_flight_pre_pulse_time_series~=0 then
      if rf then rf.apply_at(single_flight_instrument_time_us(),single_flight_set_electrode) end
    else
      single_flight_frontend.apply_at(single_flight_instrument_time_us(),single_flight_set_electrode)
    end
  end
end
function segment.instance_adjust()
  local overlay=single_flight_overlay_for_instance(ion_instance)
  if overlay==nil then return end
  local b=overlay.bounds_mm
  if single_flight_pre_pulse_time_series~=0 then
    if ion_px_mm<=b.x_min or ion_px_mm>=b.x_max or
        ion_py_mm<=b.y_min or ion_py_mm>=b.y_max or
        ion_pz_mm<=b.z_min or ion_pz_mm>=b.z_max then ion_instance=0 end
    return
  end
  local detector=simion.wb.instances[single_flight_detector_instance_index]
  if detector:inside_wc(ion_px_mm,ion_py_mm,ion_pz_mm) or
      ion_px_mm<=b.x_min or ion_px_mm>=b.x_max or
      ion_py_mm<=b.y_min or ion_py_mm>=b.y_max or
      ion_pz_mm<=b.z_min or ion_pz_mm>=b.z_max then ion_instance=0 end
end
function segment.initialize()
  local time=single_flight_instrument_time_us()
  if single_flight_pre_pulse_time_series==0 then
    single_flight_require_analyzer_particle(ion_time_of_flight)
  end
  single_flight_particle_state[ion_number]={{frontend=single_flight_frontend.initialize_particle(ion_pz_mm),
    previous={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}}}
  single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
    vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
  single_flight_reported[ion_number]={{}}
  single_flight_pre_pulse_next_sample[ion_number]=1
  single_flight_write_trace(string.format('TRACE: source_release ion=%d particle_id=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g simion_native_kinetic_energy_eV=%.17g',ion_number,single_flight_canonical_particle_id(),time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_ke))
end
function segment.tstep_adjust()
  local analyzer_dt=nil
  if single_flight_pre_pulse_time_series==0 then
    analyzer_dt=single_flight_analyzer.tstep_adjust{{x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
      vx_mm_per_us=ion_vx_mm,vy_mm_per_us=ion_vy_mm,vz_mm_per_us=ion_vz_mm,
      detector_cell_dx_mm=simion.wb.instances[single_flight_detector_instance_index].pa.dx_mm}}
  end
  if analyzer_dt and ion_time_step>analyzer_dt then ion_time_step=analyzer_dt end
  local time=single_flight_instrument_time_us()
  if single_flight_pre_pulse_time_series~=0 then
    local next_index=single_flight_pre_pulse_next_sample[ion_number] or 1
    local next_time=nil
    if single_flight_pre_pulse_natural_archive~=0 then
      -- The release position is recorded separately by initialize().  Start
      -- grid states at the next RF tick, then advance only from the persisted
      -- discrete index below.  Re-deriving this from a binary float on every
      -- SIMION step can skip a tick after accumulated roundoff.
      if next_index==1 then next_index=2 end
      next_time=single_flight_pre_pulse_grid_origin_us+(next_index-1)*single_flight_pre_pulse_grid_step_us
    else
      next_time=single_flight_pre_pulse_sample_times_us[next_index]
    end
    if next_time and time<next_time and ion_time_step>next_time-time then
      ion_time_step=next_time-time
    end
  end
  local pulse_capped=single_flight_pulse.cap_timestep_at(time,ion_time_step)
  if ion_time_step>pulse_capped then ion_time_step=pulse_capped end
  if single_flight_is_active_field_instance(ion_instance) then
    local state=single_flight_require_particle_state()
    local capped=single_flight_frontend.cap_timestep_at(time,ion_pz_mm,ion_vz_mm,ion_time_step,state.frontend)
    if ion_time_step>capped then ion_time_step=capped end
  end
end
function segment.other_actions()
  local time=single_flight_instrument_time_us()
  if single_flight_pre_pulse_time_series==0 then
    single_flight_require_analyzer_particle(ion_time_of_flight)
  end
  local state=single_flight_require_particle_state()
  local current={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}
  single_flight_frontend.observe_step(state.previous,current,state.frontend)
  state.previous=current
  local p=single_flight_previous[ion_number]
  if single_flight_pre_pulse_time_series~=0 then
    local next_index=single_flight_pre_pulse_next_sample[ion_number] or 1
    local sample_time=nil
    if single_flight_pre_pulse_natural_archive~=0 then
      local raw_index=(time-single_flight_pre_pulse_grid_origin_us)/single_flight_pre_pulse_grid_step_us
      local native_index=math.floor(raw_index+0.5)+1
      sample_time=single_flight_pre_pulse_grid_origin_us+(native_index-1)*single_flight_pre_pulse_grid_step_us
      if native_index>=next_index then next_index=native_index end
    else
      sample_time=single_flight_pre_pulse_sample_times_us[next_index]
    end
    while sample_time and time>=sample_time do
      local x,y,z,vx,vy,vz=ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm
      -- SIMION may shorten a final step to resolve a geometry collision.  That
      -- endpoint is a terminal observation, not a state on the native RF grid:
      -- retain it through segment.terminate and do not relabel it as a grid
      -- sample.  All emitted time-series rows therefore remain native-grid
      -- states; no interpolated state is ever manufactured here.  Keep the
      -- historic finite-window contract strict, since its scheduled samples
      -- are required landings rather than a natural trajectory archive.
      if single_flight_pre_pulse_natural_archive~=0 and
          math.abs(time-sample_time)>1e-9*math.max(1,math.abs(sample_time)) then break end
      -- Lua doubles and SIMION's time accumulator can differ by a few ULP at
      -- a requested RF landing.  This is still the same native grid event;
      -- keep the stored canonical grid time and retain the actual clock in
      -- its separate column.  The tolerance matches the preceding guard so
      -- a genuine shortened collision endpoint is never relabelled.
      assert(math.abs(time-sample_time)<=1e-9*math.max(1,math.abs(sample_time)),
        'pre-pulse time-series sample did not land on its native SIMION timestep')
      local energy=0.0051821348263402529*ion_mass*(vx*vx+vy*vy+vz*vz)
      if trajectory_log_enable~=0 then
        single_flight_write_trace(string.format('TRACE: pre_pulse_time_series_state ion=%d particle_id=%d sample_index=%d instrument_time_us=%.17g actual_instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g kinetic_energy_eV=%.17g survival_status=alive',
          ion_number,single_flight_canonical_particle_id(),next_index,sample_time,time,x,y,z,vx,vy,vz,energy))
      end
      next_index=next_index+1
      single_flight_pre_pulse_next_sample[ion_number]=next_index
      if single_flight_pre_pulse_natural_archive~=0 then
        sample_time=nil
      else
        sample_time=single_flight_pre_pulse_sample_times_us[next_index]
      end
    end
    single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
      vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
    if single_flight_pre_pulse_natural_archive==0 and next_index>#{screening_sample_table} then ion_splat=1 end
    return
  end
  local reported=single_flight_reported[ion_number] or {{}}
  single_flight_reported[ion_number]=reported
  local function crossing(plane,direction)
    if not p then return nil end
    local crossed=direction>0 and p.z<plane and ion_pz_mm>=plane and ion_vz_mm>0 or
      direction<0 and p.z>plane and ion_pz_mm<=plane and ion_vz_mm<0
    if not crossed then return nil end
    local fraction=(plane-p.z)/(ion_pz_mm-p.z)
    return fraction,p.t+fraction*(time-p.t),p.x+fraction*(ion_px_mm-p.x),
      p.y+fraction*(ion_py_mm-p.y),p.vx+fraction*(ion_vx_mm-p.vx),
      p.vy+fraction*(ion_vy_mm-p.vy),p.vz+fraction*(ion_vz_mm-p.vz)
  end
  if p and not reported.pre_pulse and p.t<handoff_pulse_time_us and time>=handoff_pulse_time_us then
    local f=(handoff_pulse_time_us-p.t)/(time-p.t)
    reported.pre_pulse=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: pre_pulse_state ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',
      ion_number,handoff_pulse_time_us,p.x+f*(ion_px_mm-p.x),p.y+f*(ion_py_mm-p.y),p.z+f*(ion_pz_mm-p.z),ion_vx_mm,ion_vy_mm,ion_vz_mm)) end
  end
  if handoff_pulse_mode==1 and not reported.pulse and time>=handoff_pulse_time_us then
    local pulse_x,pulse_y,pulse_z=ion_px_mm,ion_py_mm,ion_pz_mm
    local pulse_vx,pulse_vy,pulse_vz=ion_vx_mm,ion_vy_mm,ion_vz_mm
    if p and p.t<handoff_pulse_time_us and time>p.t then
      local f=(handoff_pulse_time_us-p.t)/(time-p.t)
      pulse_x=p.x+f*(ion_px_mm-p.x); pulse_y=p.y+f*(ion_py_mm-p.y); pulse_z=p.z+f*(ion_pz_mm-p.z)
      pulse_vx=p.vx+f*(ion_vx_mm-p.vx); pulse_vy=p.vy+f*(ion_vy_mm-p.vy); pulse_vz=p.vz+f*(ion_vz_mm-p.vz)
    end
    reported.pulse=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: handoff_pulse_on ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',
      ion_number,handoff_pulse_time_us,pulse_x,pulse_y,pulse_z,pulse_vx,pulse_vy,pulse_vz)) end
  end
  local handoff_x={_lua_number(frontend['source_exit_center_mm']['x'])}
  if p and not reported.handoff and p.x<handoff_x and ion_px_mm>=handoff_x and ion_vx_mm>0 then
    local f=(handoff_x-p.x)/(ion_px_mm-p.x); local tc=p.t+f*(time-p.t)
    reported.handoff=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: single_flight_handoff ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',
      ion_number,tc,handoff_x,p.y+f*(ion_py_mm-p.y),p.z+f*(ion_pz_mm-p.z),ion_vx_mm,ion_vy_mm,ion_vz_mm)) end
  end
  local _,tc,xc,yc,vxc,vyc,vzc=crossing(accelerator_grid1_z_mm,1)
  if tc and not reported.grid1 then reported.grid1=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: accelerator_grid1_forward ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,tc,xc,yc,accelerator_grid1_z_mm,vxc,vyc,vzc)) end
  end
{intermediate2_crossing_lua}  _,tc,xc,yc,vxc,vyc,vzc=crossing(accelerator_grid2_z_mm,1)
  if tc and not reported.local_exit then reported.local_exit=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: local_accelerator_exit ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,tc,xc,yc,accelerator_grid2_z_mm,vxc,vyc,vzc)) end
  end
  local focus_z=accelerator_grid2_z_mm+{_lua_number(oatof['geometry_derivation']['accelerator']['focus_drift_after_grid2_mm'])}
  _,tc,xc,yc,vxc,vyc,vzc=crossing(focus_z,1)
  if tc and not reported.focus then reported.focus=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: accelerator_focus_forward ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,tc,xc,yc,focus_z,vxc,vyc,vzc)) end
  end
  _,tc,xc,yc,vxc,vyc,vzc=crossing(reflectron_entgrid_z_mm,1)
  if tc and not reported.reflectron_entrance then reported.reflectron_entrance=true
    single_flight_trace_checkpoint('reflectron_entrance_forward',tc,xc,yc,reflectron_entgrid_z_mm,vxc,vyc,vzc)
  end
  _,tc,xc,yc,vxc,vyc,vzc=crossing(reflectron_midgrid_z_mm,1)
  if tc and reported.reflectron_entrance and not reported.reflectron_midgrid then reported.reflectron_midgrid=true
    single_flight_trace_checkpoint('reflectron_midgrid_forward',tc,xc,yc,reflectron_midgrid_z_mm,vxc,vyc,vzc)
  end
  if p and reported.reflectron_midgrid and not reported.reflectron_turning and p.vz>0 and ion_vz_mm<=0 then
    local f=p.vz/(p.vz-ion_vz_mm); reported.reflectron_turning=true
    single_flight_trace_checkpoint('reflectron_turning_point',p.t+f*(time-p.t),
      p.x+f*(ion_px_mm-p.x),p.y+f*(ion_py_mm-p.y),p.z+f*(ion_pz_mm-p.z),
      p.vx+f*(ion_vx_mm-p.vx),p.vy+f*(ion_vy_mm-p.vy),0)
  end
  _,tc,xc,yc,vxc,vyc,vzc=crossing(reflectron_entgrid_z_mm,-1)
  if tc and reported.reflectron_turning and not reported.reflectron_exit then reported.reflectron_exit=true
    single_flight_trace_checkpoint('reflectron_exit_return',tc,xc,yc,reflectron_entgrid_z_mm,vxc,vyc,vzc)
  end
  single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
    vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
  local result=single_flight_analyzer.other_actions{{particle_id=single_flight_canonical_particle_id(),elapsed_us=ion_time_of_flight,x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,vz_mm_per_us=ion_vz_mm}}
  if trajectory_log_enable~=0 then
    for _,event in ipairs(result.events) do
      if event.kind=='diagnostic_return_plane' then
        print(string.format('TRACE: diagnostic_return_plane ion=%d t=%.12g x=%.12g y=%.12g z=%.12g vz=%.12g zmax=%.12g',
          ion_number,event.elapsed_us,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vz_mm,event.max_z_mm))
      end
    end
  end
  if result.splat or (single_flight_terminate_after_pulse~=0 and time>=handoff_pulse_time_us) then ion_splat=1 end
end
function segment.terminate()
  local time=single_flight_instrument_time_us()
  if single_flight_pre_pulse_time_series~=0 then
    if trajectory_log_enable~=0 then
      local next_index=single_flight_pre_pulse_next_sample[ion_number] or 1
      local terminal_reason=single_flight_pre_pulse_natural_archive~=0 and 'geometry_collision' or
        (next_index>#{screening_sample_table} and 'window_complete' or 'splat')
      single_flight_write_trace(string.format('TRACE: pre_pulse_screening_terminal ion=%d particle_id=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g terminal_reason=%s',
        ion_number,single_flight_canonical_particle_id(),time,ion_px_mm,ion_py_mm,ion_pz_mm,
        ion_vx_mm,ion_vy_mm,ion_vz_mm,terminal_reason))
    end
    return
  end
  if handoff_pulse_mode==1 and trajectory_log_enable~=0 then
    print(string.format('TRACE: handoff_terminal_raw ion=%d instance=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',
      ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))
  end
  single_flight_require_analyzer_particle(ion_time_of_flight)
  local result=single_flight_analyzer.terminate{{particle_id=single_flight_canonical_particle_id(),instance_id=ion_instance,
    elapsed_us=ion_time_of_flight,x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
    vx_mm_per_us=ion_vx_mm,vy_mm_per_us=ion_vy_mm,vz_mm_per_us=ion_vz_mm,
    detector_cell_dx_mm=simion.wb.instances[single_flight_detector_instance_index].pa.dx_mm}}
  if trajectory_log_enable~=0 and result then
    if result.kind=='detector_crossing' then
      print(string.format('TRACE: detector_crossing ion=%d t=%.12g x=%.12g y=%.12g z=%.12g r=%.12g zmax=%.12g',
        ion_number,result.elapsed_us,result.x_mm,result.y_mm,result.z_mm,result.radius_mm,result.max_z_mm))
      print(string.format('TRACE: detector_hit_entity ion=%d instance=4',ion_number))
    elseif result.kind=='non_detector_splat' then
      print(string.format('TRACE: non_detector_splat ion=%d instance=%d t=%.12g x=%.12g y=%.12g z=%.12g zmax=%.12g',
        ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,result.max_z_mm))
    end
  end
end
"""
    if program.count("simion.workbench_program()") != 1:
        raise ValueError("combined single-flight Program must declare one workbench")
    for callback in _SUCCESSOR_CALLBACKS:
        count = len(re.findall(rf"function\s+segment\.{callback}\s*\(", program))
        if count != 1:
            raise ValueError(f"combined single-flight Program callback {callback} count is {count}")
    if not include_total_axis_field_exporter:
        return program
    # The exporter uses the same highest-priority local domain as the runnable
    # IOB.  In the shared-main profile this is the entrance-local PA; the
    # intermediate2 sheet itself remains part of accelerator_main.
    if governed_overlay is None and not domain_split_main_pa_only_axis_field:
        raise ValueError("total-axis exporter requires a governed three-zone overlay")
    static_analyzer_config_lua = _lua_value(analyzer_config)
    axis_planes_export_lua = _lua_value(
        [
            geometry["accelerator_grid1_z_mm"],
            *(
                [geometry["accelerator_intermediate2_z_mm"]]
                if three_zone
                else []
            ),
            geometry["accelerator_grid2_z_mm"],
        ]
    )
    active_voltage_lua = _lua_value(
        {
            "pre_all_v": 0.0,
            "repeller_v": analyzer_config["voltages"]["repeller_v"],
            "grid1_v": analyzer_config["voltages"]["grid1_v"],
            **(
                {
                    "intermediate2_v": analyzer_config["voltages"]["intermediate2_v"],
                    "exit_v": analyzer_config["voltages"]["exit_v"],
                }
                if three_zone
                else {}
            ),
        }
    )
    rf_export_initializer = (
        f"local rf=single_flight_rf_kernel.new{{waveform={json.dumps(drive['waveform'])},"
        f"frequency_hz={_lua_number(drive['frequency_Hz'])},"
        f"phase_rad={_lua_number(drive['phase_rad'])},"
        f"rf_amplitude_v={_lua_number(drive['rf_amplitude_V_zero_to_peak_per_group'])},"
        "rf_scale=1,common_mode_scale=1,"
        f"group_dc_v={{[1]={_lua_number(drive['dc_amplitude_V_per_group'])},"
        f"[2]={_lua_number(-drive['dc_amplitude_V_per_group'])}}},"
        f"rf_steps_per_period={rf_steps_per_period},electrodes={_lua_value(rf_electrodes)}}}"
        if rf_enabled
        else "local rf=false"
    )
    exporter_workbench_initialization = (
        """-- Domain split keeps accelerator_main in slot 3.  Do not replay the
-- legacy whole-accelerator PA override here: that PA is absent by design.
local function instance_state(instance)
  return {filename=instance.filename,nx=instance.pa.nx,ny=instance.pa.ny,
    nz=instance.pa.nz,dx_mm=instance.pa.dx_mm,dy_mm=instance.pa.dy_mm,
    dz_mm=instance.pa.dz_mm,scale=instance.scale}
end
local function apply_placement(instance,placement)
  instance.x,instance.y,instance.z=placement.x_mm,placement.y_mm,placement.z_mm
  instance.az,instance.el,instance.rt,instance.scale=placement.az_deg,placement.el_deg,
    placement.rt_deg,placement.scale
end
local initialized=analyzer.initialize_workbench({active_scope='pre_pulse_frontend_accelerator',
  instances={[ACCELERATOR_INSTANCE_INDEX]=instance_state(ai)})
apply_placement(ai,initialized.placements.accelerator)""".replace(
            "ACCELERATOR_INSTANCE_INDEX", str(accelerator_instance_index)
        )
        if domain_split is not None
        else """local frontend_pa=assert(os.getenv('OATOF_ACCELERATOR_PA_OVERRIDE'),
  'missing run-local frontend PA override')
ai.pa:load(frontend_pa)
ai:_debug_update_size()
-- The run-local frontend PA has different extents from the container
-- placeholder.  Fly'm recomputes placements after that load, so the static
-- exporter must do the same before querying the total Workbench field.
analyzer_config.instance_filenames.accelerator='frontend.pa0'
local function instance_state(instance)
  return {filename=instance.filename,nx=instance.pa.nx,ny=instance.pa.ny,
    nz=instance.pa.nz,dx_mm=instance.pa.dx_mm,dy_mm=instance.pa.dy_mm,
    dz_mm=instance.pa.dz_mm,scale=instance.scale}
end
local function apply_placement(instance,placement)
  instance.x,instance.y,instance.z=placement.x_mm,placement.y_mm,placement.z_mm
  instance.az,instance.el,instance.rt,instance.scale=placement.az_deg,placement.el_deg,
    placement.rt_deg,placement.scale
end
local workbench_instances={}
for index=1,4 do workbench_instances[index]=instance_state(simion.wb.instances[index]) end
local initialized=analyzer.initialize_workbench({instances=workbench_instances})
apply_placement(simion.wb.instances[1],initialized.placements.flight_tube)
apply_placement(simion.wb.instances[2],initialized.placements.reflectron)
apply_placement(ai,initialized.placements.accelerator)"""
    )
    exporter = f"""-- Generated C3 total-field exporter.  It is a top-level SIMION Lua script,
-- not a Workbench Program callback: SIMION's documented wb field API is only
-- queried after this script loads the frozen runtime IOB and reproduces its
-- post-pulse fast-adjust plan.
{embedded}
local output_path=assert(os.getenv('OATOF_TOTAL_AXIS_FIELD_CSV'),'missing output path')
local iob_path=assert(os.getenv('OATOF_TOTAL_AXIS_FIELD_IOB'),'missing runtime IOB path')
local pulse_time_us=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_PULSE_TIME_US')),'missing pulse time')
local pulse_width_us=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_PULSE_WIDTH_US')),'missing pulse width')
assert(pulse_width_us>0,'pulse width must be positive')
-- This is a standalone Lua diagnostic, not a Workbench Program.  SIMION only
-- permits the Workbench Program declaration in files it auto-executes during
-- Fly'm; declaring one here fails before any field can be sampled.
simion.command('"'..iob_path..'"')
assert(#simion.wb.instances=={5 if domain_split_main_pa_only_axis_field or reduced_post_accelerator_iob else 6 if domain_split is not None else 4 + len(overlay_specs)},
  'C3 total-field exporter IOB instance count differs')
for index=1,#simion.wb.instances do
  local item=simion.wb.instances[index]
  assert(item.x and item.y and item.z and item.az and item.el and item.rt and item.scale,
    'C3 total-field exporter found an incomplete IOB transform')
  print(string.format(
    'TOTAL_AXIS_FIELD_INSTANCE index=%d x_mm=%.12g y_mm=%.12g z_mm=%.12g az_deg=%.12g el_deg=%.12g rt_deg=%.12g scale=%.12g',
    index,item.x,item.y,item.z,item.az,item.el,item.rt,item.scale))
end
local analyzer_config={static_analyzer_config_lua}
local analyzer=single_flight_analyzer_component.new(analyzer_config)
{rf_export_initializer}
local pulse=single_flight_pulse_component.new{{canonical_clock=function() return pulse_time_us end,
  pulse_time_us=pulse_time_us,pulse_width_us=pulse_width_us,pulse_mode=function() return 1 end}}
local function electrode_plan()
  return {{apply_at=function(_,pulse_state,setter)
    setter({int(electrodes['grounded_shield_id'])},0)
    local plan=analyzer.accelerator_electrode_write_plan(pulse_state.active and 'on' or 'off',
      {active_voltage_lua})
    for _,item in ipairs(plan) do setter(item.electrode_id,item.voltage_v) end
    setter({int(electrodes['entrance_reference_sleeve_id'])},{_lua_number(entrance_reference_v)})
    setter({int(electrodes['entrance_plate_id'])},{_lua_number(entrance_plate_v)})
  end}}
end
local frontend=single_flight_frontend_component.new{{rf_drive=rf,pulse_hook=pulse,
  electrode_plan=electrode_plan(),planes_z_mm={axis_planes_export_lua}}}
local active={{}}
local pa_plus_modes={pa_plus_modes_lua}
frontend.apply_at(pulse_time_us,function(id,value) active[id]=value end)
local function pa_adjustments(ids)
  local values={{}}
  for _,id in ipairs(ids) do
    assert(active[id]~=nil,'frozen post-pulse adjustment is missing electrode '..id)
    values[id]=active[id]
  end
  for _,mode in ipairs(pa_plus_modes) do
    values[mode.mode_id]=assert(active[mode.source_electrode_id],
      'frozen PA+ adjustment is missing independent electrode '..mode.source_electrode_id)
  end
  return values
end
local ai=assert(simion.wb.instances[{accelerator_instance_index}],'accelerator instance is missing')
local overlay_specs={overlay_specs_lua}
for _,overlay in ipairs(overlay_specs) do
  assert(simion.wb.instances[overlay.instance_index],
    'accelerator overlay instance is missing')
end
{exporter_workbench_initialization}
-- The runnable Program immediately replaces the nominal placement of the
-- run-local frontend PA after it is loaded.  The field-only IOB begins from
-- the same container, so it must replay this exact frozen transform before
-- querying the workbench total field.  Omitting it can leave the sampling
-- axis outside the physical accelerator even though the top-level Lua exits
-- successfully.
ai.x,ai.y,ai.z={_lua_number(origin['x'])},{_lua_number(origin['y'])},{_lua_number(origin['z'])}
{'' if domain_split is not None else f'apply_placement(simion.wb.instances[{detector_instance_index}],initialized.placements.detector)'}
for _,overlay in ipairs(overlay_specs) do
  local oi=simion.wb.instances[overlay.instance_index]
  oi.x,oi.y,oi.z=overlay.origin_mm.x,overlay.origin_mm.y,overlay.origin_mm.z
  oi.az,oi.el,oi.rt,oi.scale=0,0,0,1
end
print(string.format(
  'TOTAL_AXIS_FIELD_ACCELERATOR_POSTPLACEMENT x_mm=%.12g y_mm=%.12g z_mm=%.12g az_deg=%.12g el_deg=%.12g rt_deg=%.12g scale=%.12g',
  ai.x,ai.y,ai.z,ai.az,ai.el,ai.rt,ai.scale))
for _,overlay in ipairs(overlay_specs) do
  local oi=simion.wb.instances[overlay.instance_index]
  print(string.format(
    'TOTAL_AXIS_FIELD_OVERLAY_POSTPLACEMENT index=%d x_mm=%.12g y_mm=%.12g z_mm=%.12g az_deg=%.12g el_deg=%.12g rt_deg=%.12g scale=%.12g',
    overlay.instance_index,oi.x,oi.y,oi.z,oi.az,oi.el,oi.rt,oi.scale))
end
for _,item in ipairs(initialized.static_electrode_plans.legacy_accelerator_characterization) do
  active[item.electrode_id]=item.voltage_v
end
for _,item in ipairs(initialized.static_electrode_plans.reflectron) do
  active[item.electrode_id]=item.voltage_v
end
-- Fly'm applies the time-dependent frontend plan after the static seed.
frontend.apply_at(pulse_time_us,function(id,value) active[id]=value end)
-- ``potential_wc`` and ``field_wc`` below receive these frozen electrode
-- tables explicitly.  Do not also call PA ``fast_adjust`` here: a local
-- domain intentionally lacks some remote electrodes, while the explicit
-- query table is the complete and authoritative post-pulse state.
local ai_values=pa_adjustments({_lua_value(dynamic_basis_electrode_ids)})
local oi_values=pa_adjustments({_lua_value(dynamic_basis_electrode_ids)})
-- wb:efield and wb:epotential deliberately ignore time-dependent user
-- programming.  Reproduce the frozen Program's instance_adjust predicate,
-- then provide the selected PA its frozen post-pulse electrode table
-- explicitly.  The static IOB priority alone is insufficient because the
-- Program suppresses overlay points outside its active bounds.  As in Fly'm,
-- overlapping PA fields must not be added.
local function frozen_axis_field(x,y,z)
local detector=simion.wb.instances[{detector_instance_index}]
local instance_number={accelerator_instance_index}
  for _,overlay in ipairs(overlay_specs) do
    local b=overlay.bounds_mm
    local inside_overlay=not detector:inside_wc(x,y,z) and
      x>b.x_min and x<b.x_max and y>b.y_min and y<b.y_max and
      z>b.z_min and z<b.z_max
    if inside_overlay then
      assert(instance_number==3,'C3 overlay active bounds overlap')
      instance_number=overlay.instance_index
    end
  end
  local instance=simion.wb.instances[instance_number]
  local values=(instance_number==3) and ai_values or oi_values
  assert(instance:inside_wc(x,y,z),
    'runtime-selected C3 PA does not contain the axis point; instance='..instance_number)
  local potential=instance:potential_wc(x,y,z,values)
  local ex,ey,ez=instance:field_wc(x,y,z,values)
  assert(potential and ex and ey and ez,
    'frozen PA field is undefined on C3 axis for instance '..instance_number)
  return potential,ex,ey,ez,instance_number
end
local z_start={_lua_number(geometry['accelerator_repeller_front_z_mm'])}
local z_end={_lua_number(geometry['accelerator_grid2_z_mm'])}
local z_step=ai.pa.dz_mm
assert(z_step>0 and z_end>z_start,'axis interval is invalid')
-- The exported interval is deliberately an integer number of accelerator
-- z-cells.  Round the quotient before adding the inclusive endpoint: ceil
-- can turn an exact integer into N+1 after binary roundoff and duplicate the
-- final clamped sample.
local count=math.floor((z_end-z_start)/z_step+0.5)+1
local output=assert(io.open(output_path,'w'))
output:write('sample_index,x_mm,y_mm,z_mm,potential_V,Ex_V_per_mm,Ey_V_per_mm,Ez_V_per_mm\\n')
for index=1,count do
  local z=(index==count) and z_end or z_start+(index-1)*z_step
  local potential,ex,ey,ez,instance_number=frozen_axis_field(
    {_lua_number(geometry['accelerator_axis_x_mm'])},{_lua_number(geometry['accelerator_axis_y_mm'])},z)
  output:write(string.format('%d,%.12g,%.12g,%.12g,%.15g,%.15g,%.15g,%.15g\\n',index,
    {_lua_number(geometry['accelerator_axis_x_mm'])},{_lua_number(geometry['accelerator_axis_y_mm'])},z,
    potential,ex,ey,ez))
  print(string.format('TOTAL_AXIS_FIELD_SAMPLE index=%d active_instance=%d',index,instance_number))
end
output:close()
print(string.format('TOTAL_AXIS_FIELD=PASS INSTANCES=%d POINTS=%d PULSE_TIME_US=%.12g',
  #simion.wb.instances,count,pulse_time_us))
"""
    return program, exporter


def main() -> int:
    mode_parser = argparse.ArgumentParser(add_help=False)
    mode_parser.add_argument("--reflectron-fast-adjust-oatof", type=Path)
    mode_parser.add_argument("--reflectron-fast-adjust-output", type=Path)
    mode_args, _ = mode_parser.parse_known_args()
    if mode_args.reflectron_fast_adjust_oatof is not None:
        if mode_args.reflectron_fast_adjust_output is None:
            mode_parser.error(
                "--reflectron-fast-adjust-oatof requires "
                "--reflectron-fast-adjust-output"
            )
        output = mode_args.reflectron_fast_adjust_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "rf_oatof_reflectron_fast_adjust_assignments",
                    "assignments": reflectron_fast_adjust_assignments(
                        _load(mode_args.reflectron_fast_adjust_oatof)
                    ),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"REFLECTRON_FAST_ADJUST_ASSIGNMENTS=PASS OUTPUT={output}")
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyzer-component", required=True, type=Path)
    parser.add_argument("--pulse-hook", required=True, type=Path)
    parser.add_argument("--frontend-hook", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--frontend-contract", required=True, type=Path)
    parser.add_argument("--accelerator-overlay-contract", type=Path)
    parser.add_argument("--intermediate-accelerator-overlay-contract", type=Path)
    parser.add_argument("--accelerator-entrance-local-contract", type=Path)
    parser.add_argument("--upstream-bridge-contract", type=Path)
    parser.add_argument("--accelerator-main-contract", type=Path)
    parser.add_argument("--domain-split-main-pa-only-axis-field", action="store_true")
    parser.add_argument("--domain-split-local-axis-field", action="store_true")
    parser.add_argument("--oatof", required=True, type=Path)
    parser.add_argument("--initial-global-state", required=True, type=Path)
    parser.add_argument("--particle-row-map", required=True, type=Path)
    parser.add_argument("--resolved-region-field-contract", required=True, type=Path)
    parser.add_argument("--rf-drive-kernel", required=True, type=Path)
    parser.add_argument("--rf-steps-per-period", required=True, type=int)
    parser.add_argument(
        "--source-release-mode",
        choices=SOURCE_RELEASE_MODES,
        default=None,
    )
    parser.add_argument("--terminate-after-pulse", action="store_true")
    parser.add_argument("--pre-pulse-time-series-contract", type=Path)
    parser.add_argument("--global-segments", action="store_true")
    parser.add_argument("--total-axis-field-exporter-output", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    oatof = _load(args.oatof)
    region_field_contract = _load(args.resolved_region_field_contract)
    validate_resolved_region_field_contract(region_field_contract)
    birth_times, state_row_ids = load_initial_state(args.initial_global_state)
    row_map_ids = load_row_map(args.particle_row_map, len(state_row_ids))
    split_paths = (args.upstream_bridge_contract, args.accelerator_main_contract)
    if any(path is not None for path in split_paths) and any(path is None for path in split_paths):
        raise ValueError(
            "domain-split Program requires both upstream-bridge and accelerator-main contracts"
        )
    domain_split = (
        resolve_domain_split_program_contract(
            _load(args.upstream_bridge_contract), _load(args.accelerator_main_contract)
        )
        if args.upstream_bridge_contract is not None
        else None
    )
    built = build_successor_program(
        _load(args.upstream),
        _load(args.frontend_contract),
        oatof,
        region_field_contract,
        birth_times_us=birth_times,
        particle_ids=row_map_ids,
        analyzer_component_source=args.analyzer_component.read_text(encoding="utf-8-sig"),
        pulse_hook_source=args.pulse_hook.read_text(encoding="utf-8-sig"),
        frontend_hook_source=args.frontend_hook.read_text(encoding="utf-8-sig"),
        rf_drive_kernel_source=args.rf_drive_kernel.read_text(encoding="utf-8-sig"),
        source_release_mode=args.source_release_mode,
        terminate_after_pulse=args.terminate_after_pulse,
        pre_pulse_time_series_contract=(
            _load(args.pre_pulse_time_series_contract)
            if args.pre_pulse_time_series_contract is not None
            else None
        ),
        overlay=(
            _load(args.accelerator_overlay_contract)
            if args.accelerator_overlay_contract is not None
            else None
        ),
        intermediate_overlay=(
            _load(args.intermediate_accelerator_overlay_contract)
            if args.intermediate_accelerator_overlay_contract is not None
            else None
        ),
        accelerator_entrance_local=(
            _load(args.accelerator_entrance_local_contract)
            if args.accelerator_entrance_local_contract is not None
            else None
        ),
        domain_split=domain_split,
        domain_split_main_pa_only_axis_field=args.domain_split_main_pa_only_axis_field,
        domain_split_local_axis_field=args.domain_split_local_axis_field,
        rf_steps_per_period=args.rf_steps_per_period,
        global_segments=args.global_segments,
        include_total_axis_field_exporter=(
            args.total_axis_field_exporter_output is not None
        ),
    )
    if args.total_axis_field_exporter_output is None:
        output = built
        exporter = None
    else:
        output, exporter = built
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8", newline="\n")
    if exporter is not None:
        args.total_axis_field_exporter_output.parent.mkdir(parents=True, exist_ok=True)
        args.total_axis_field_exporter_output.write_text(
            exporter, encoding="utf-8", newline="\n"
        )
    metadata = {
        "schema_version": 1,
        "role": "rf_oatof_simion_single_flight_program_build",
        "analyzer_component_sha256": file_sha256(args.analyzer_component),
        "pulse_hook_sha256": file_sha256(args.pulse_hook),
        "frontend_hook_sha256": file_sha256(args.frontend_hook),
        "upstream_sha256": file_sha256(args.upstream),
        "frontend_contract_sha256": file_sha256(args.frontend_contract),
        "accelerator_overlay_contract_sha256": (
            file_sha256(args.accelerator_overlay_contract)
            if args.accelerator_overlay_contract is not None
            else None
        ),
        "intermediate_accelerator_overlay_contract_sha256": (
            file_sha256(args.intermediate_accelerator_overlay_contract)
            if args.intermediate_accelerator_overlay_contract is not None
            else None
        ),
        "accelerator_entrance_local_contract_sha256": (
            file_sha256(args.accelerator_entrance_local_contract)
            if args.accelerator_entrance_local_contract is not None
            else None
        ),
        "upstream_bridge_contract_sha256": (
            file_sha256(args.upstream_bridge_contract)
            if args.upstream_bridge_contract is not None
            else None
        ),
        "accelerator_main_contract_sha256": (
            file_sha256(args.accelerator_main_contract)
            if args.accelerator_main_contract is not None
            else None
        ),
        "domain_split_main_pa_only_axis_field": (
            args.domain_split_main_pa_only_axis_field
        ),
        "oatof_sha256": file_sha256(args.oatof),
        "initial_global_state_sha256": (
            file_sha256(args.initial_global_state)
            if args.initial_global_state is not None
            else None
        ),
        "particle_row_map_sha256": file_sha256(args.particle_row_map),
        "resolved_region_field_contract_sha256": file_sha256(
            args.resolved_region_field_contract
        ),
        "resolved_region_field_semantic_sha256": region_field_contract[
            "semantic_sha256"
        ],
        "resolved_region_field_profile_id": region_field_contract["semantic"][
            "canonical_profile_id"
        ],
        "rf_drive_kernel_sha256": file_sha256(args.rf_drive_kernel),
        "rf_steps_per_period": args.rf_steps_per_period,
        "source_release_mode": args.source_release_mode or "continuous_frontend",
        "clock_basis": "canonical_instrument_time_us",
        "terminate_after_pulse": args.terminate_after_pulse,
        "pre_pulse_time_series_contract_sha256": (
            file_sha256(args.pre_pulse_time_series_contract)
            if args.pre_pulse_time_series_contract is not None
            else None
        ),
        "global_segments": args.global_segments,
        "total_axis_field_exporter_sha256": (
            file_sha256(args.total_axis_field_exporter_output)
            if args.total_axis_field_exporter_output is not None
            else None
        ),
        "output_sha256": file_sha256(args.output),
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_PROGRAM=PASS OUTPUT={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
