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
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    resolved_region_field_hook_lua,
    validate_resolved_region_field_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pure_boundary_validator import (
    validate_pure_lua_component_source,
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
    """Load canonical clocks and source IDs in frozen source-row order."""
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


def load_row_map(path: Path, expected_source_ids: list[int]) -> list[int]:
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
    if source_ids != expected_source_ids:
        raise ValueError("single-flight row map differs from canonical source-row order")
    return source_ids


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
    three_zone = frontend_topology_id == "three_zone_accelerator_ideal_v1"
    topology = oatof.get("accelerator_topology") if three_zone else None
    region_topology = region_field_contract["semantic"].get(
        "accelerator_topology"
    )
    if three_zone:
        if topology != region_topology or topology.get("topology_id") != frontend_topology_id:
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
        "accelerator_topology_id": (
            "three_zone_frontend_v1" if three_zone else "two_zone_frontend_v1"
        ),
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
    restart_context: dict[str, Any] | None = None,
    analyzer_component_source: str,
    pulse_hook_source: str,
    frontend_hook_source: str,
    rf_drive_kernel_source: str,
    source_release_mode: str | None = None,
    terminate_after_pulse: bool = False,
    pre_pulse_time_series_contract: dict[str, Any] | None = None,
    overlay: dict[str, Any] | None = None,
    rf_steps_per_period: int = 160,
    global_segments: bool = False,
) -> str:
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
    staged_restart = restart_context is not None
    if source_release_mode is None:
        source_release_mode = (
            "staged_grid2_restart" if staged_restart else "continuous_frontend"
        )
    if source_release_mode not in {
        "continuous_frontend",
        "pre_pulse_restart",
        "staged_grid2_restart",
    }:
        raise ValueError("single-flight source release mode is unsupported")
    if source_release_mode == "staged_grid2_restart" and not staged_restart:
        raise ValueError("staged grid2 source release requires its restart context")
    if source_release_mode != "staged_grid2_restart" and staged_restart:
        raise ValueError("restart context requires staged grid2 source release mode")
    rf_enabled = source_release_mode != "pre_pulse_restart"
    if staged_restart:
        required_restart = {
            "role": "rf_oatof_staged_grid2_restart_context",
            "source_release_mode": "staged_grid2_restart",
            "population_mode": "staged_grid2_restart",
            "state_event": "local_accelerator_exit",
            "frame_id": "oatof_global",
            "clock_basis": "canonical_instrument_time_us",
            "position_projection_applied": False,
            "skip_frontend_runtime_writes": True,
            "skip_pulse_runtime_writes": True,
            "skip_accelerator_runtime_writes": True,
            "preserve_analyzer_static_pa_initialization": True,
            "preserve_downstream_base_then_override_field_semantics": True,
            "preserve_detector_elapsed_semantics": True,
            "resolution_claim_allowed": False,
        }
        if any(restart_context.get(key) != value for key, value in required_restart.items()):
            raise ValueError("staged grid2 restart context differs from the supported contract")
        start_instance = restart_context.get("simion_start_instance")
        if start_instance not in (3, 5):
            raise ValueError("staged grid2 restart instance must be explicitly 3 or 5")
        if not isinstance(restart_context.get("clock_epoch_id"), str) or not restart_context["clock_epoch_id"]:
            raise ValueError("staged grid2 restart requires one explicit clock epoch")
        validation = restart_context.get("source_release_validation")
        velocity = validation.get("velocity") if isinstance(validation, dict) else None
        energy = validation.get("derived_energy") if isinstance(validation, dict) else None
        budget = (
            validation.get("loader_authorization_budget")
            if isinstance(validation, dict) else None
        )
        sha_keys = (
            "canonical_source_sha256", "solver_executable_sha256",
            "production_renderer_sha256",
        )
        if (
            not isinstance(validation, dict)
            or validation.get("role")
            != "rf_oatof_resolved_source_release_validation"
            or validation.get("representation")
            != "standard_beam_direct_velocity_vector"
            or validation.get("identity_position_clock_policy")
            != "ordered_id_row_map_position_clock_exact"
            or validation.get("native_ion_ke_role") != "diagnostic_only"
            or not isinstance(budget, dict)
            or not isinstance(budget.get("path"), str)
            or not budget["path"]
            or not isinstance(budget.get("sha256"), str)
            or re.fullmatch(r"[A-F0-9]{64}", budget["sha256"]) is None
            or any(
                not isinstance(validation.get(key), str)
                or re.fullmatch(r"[A-F0-9]{64}", validation[key]) is None
                for key in sha_keys
            )
            or not isinstance(velocity, dict)
            or isinstance(velocity.get("relative_bound"), bool)
            or not isinstance(velocity.get("relative_bound"), (int, float))
            or not math.isfinite(float(velocity["relative_bound"]))
            or float(velocity["relative_bound"]) <= 0
            or velocity.get("absolute_floor_m_per_s") != 0
            or velocity.get("zero_speed_must_be_exact") is not True
            or not isinstance(energy, dict)
            or isinstance(energy.get("relative_bound"), bool)
            or not isinstance(energy.get("relative_bound"), (int, float))
            or not math.isfinite(float(energy["relative_bound"]))
            or float(energy["relative_bound"]) <= 0
            or energy.get("absolute_floor_eV") != 0
            or energy.get("zero_energy_must_be_exact") is not True
            or energy.get("authority")
            != "actual_velocity_plus_canonical_mass_common_function"
        ):
            raise ValueError(
                "staged grid2 restart requires resolved population v2 validation"
            )
        if (start_instance == 5) != (overlay is not None):
            raise ValueError(
                "staged grid2 restart instance/overlay mapping differs: "
                "instance 3 requires no overlay and instance 5 requires one overlay"
            )
    if isinstance(rf_steps_per_period, bool) or not isinstance(rf_steps_per_period, int) or rf_steps_per_period <= 0:
        raise ValueError("RF steps per period must be one positive integer")
    screening = pre_pulse_time_series_contract is not None
    sample_times_us: list[float] = []
    if screening:
        contract = pre_pulse_time_series_contract
        assert contract is not None
        required = {
            "role": "rf_oatof_pre_pulse_time_series_screening_contract",
            "mode": "real_pa_rf_pre_pulse_time_series",
            "active_scope": "pre_pulse_frontend_accelerator",
            "pulse_disabled": True,
            "terminate_at_window_end": True,
            "resolution_claim_allowed": False,
        }
        if (
            contract.get("schema_version") not in {1, 2}
            or any(contract.get(key) != value for key, value in required.items())
        ):
            raise ValueError("pre-pulse time-series screening contract mode differs")
        if contract.get("prohibited_outputs") != [
            "detector_crossing",
            "resolution_metrics",
            "single_flight_spatial_six_panel",
        ]:
            raise ValueError("pre-pulse time-series prohibited outputs differ")
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
        if terminate_after_pulse or staged_restart:
            raise ValueError("pre-pulse time-series requires non-restart execution")
    if overlay is not None and overlay.get("role") != "rf_oatof_simion_accelerator_overlay_contract":
        raise ValueError("single-flight Program requires an accelerator overlay contract")
    three_zone = frontend.get("accelerator_topology_id") == (
        "three_zone_accelerator_ideal_v1"
    )
    if three_zone and staged_restart:
        raise ValueError(
            "three-zone single-flight Program does not support the legacy staged-grid2 restart"
        )
    if three_zone and (
        overlay is None
        or frontend["accelerator_local_region"].get("intermediate2_grid_provider")
        != "accelerator_overlay"
        or float(overlay["cell_mm_xyz"]["z"]) != 0.05
    ):
        raise ValueError(
            "three-zone single-flight Program requires the governed z=0.05 mm accelerator overlay"
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
    formal_iob_config = {
        "instance_roles": {
            "flight_tube": 1,
            "reflectron": 2,
            "accelerator": 3,
            "detector": 4,
            **({"accelerator_overlay": 5} if overlay is not None else {}),
        },
        "instance_filenames": {
            "flight_tube": "flight_tube_ground.pa0",
            "reflectron": "reflectron.pa0",
            "accelerator": "accelerator.pa0",
            "detector": "detector_ground.pa0",
            **(
                {"accelerator_overlay": "accelerator_overlay.pa0"}
                if overlay is not None else {}
            ),
        },
    }
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
    restart_reported_lua = (
        "{pre_pulse=true,pulse=true,handoff=true,grid1=true,"
        "intermediate2=true,local_exit=true}"
        if three_zone
        else "{pre_pulse=true,pulse=true,handoff=true,grid1=true,local_exit=true}"
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
    origin = frontend["instance_origin_mm"]
    overlay_origin = overlay["instance_origin_mm"] if overlay is not None else {"x": 0, "y": 0, "z": 0}
    overlay_bounds = overlay["active_bounds_mm"] if overlay is not None else {
        "x_min": 0, "x_max": 0, "y_min": 0, "y_max": 0, "z_min": 0, "z_max": 0
    }
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
adjustable trajectory_log_enable=0
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
local single_flight_staged_grid2_restart={1 if staged_restart else 0}
local single_flight_staged_grid2_start_instance={int(restart_context['simion_start_instance']) if staged_restart else 0}
local single_flight_terminate_after_pulse={1 if terminate_after_pulse else 0}
local single_flight_pre_pulse_time_series={1 if screening else 0}
local single_flight_pre_pulse_sample_times_us={screening_sample_table}
local single_flight_pre_pulse_next_sample={{}}
local single_flight_overlay_enabled={1 if overlay is not None else 0}
local single_flight_overlay_origin={_lua_value(overlay_origin)}
local single_flight_overlay_bounds={_lua_value(overlay_bounds)}
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
local function single_flight_set_electrode(id,value) adj_elect[id]=value end
local function single_flight_trace_checkpoint(event,t,x,y,z,vx,vy,vz)
  if trajectory_log_enable==0 then return end
  local particle_id=single_flight_canonical_particle_id()
  local energy=0.0051821348263402529*ion_mass*(vx*vx+vy*vy+vz*vz)
  print(string.format('TRACE: %s ion=%d particle_id=%d instrument_time_us=%.12g tof_since_pulse_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g kinetic_energy_eV=%.12g survival_status=alive',
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
    local accelerator_index=config.instance_roles.accelerator
    local accelerator=assert(simion.wb.instances[accelerator_index],
      'pre-pulse screening accelerator instance is missing')
    assert(single_flight_exact_basename(accelerator.filename,
      'formal IOB role accelerator')==config.instance_filenames.accelerator,
      'formal IOB role accelerator filename differs')
    if single_flight_overlay_enabled~=0 then
      local overlay_index=config.instance_roles.accelerator_overlay
      local overlay_instance=assert(simion.wb.instances[overlay_index],
        'pre-pulse screening accelerator overlay instance is missing')
      assert(single_flight_exact_basename(overlay_instance.filename,
        'formal IOB role accelerator_overlay')==
        config.instance_filenames.accelerator_overlay,
        'formal IOB role accelerator_overlay filename differs')
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
local function single_flight_instance_state(instance)
  return {{filename=instance.filename,nx=instance.pa.nx,ny=instance.pa.ny,
    nz=instance.pa.nz,dx_mm=instance.pa.dx_mm,dy_mm=instance.pa.dy_mm,
    dz_mm=instance.pa.dz_mm,scale=instance.scale}}
end
local function single_flight_workbench_state(active_scope)
  if active_scope=='pre_pulse_frontend_accelerator' then
    return {{active_scope=active_scope,instances={{
      [3]=single_flight_instance_state(assert(simion.wb.instances[3],
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
  if single_flight_accelerator_pa_override and single_flight_accelerator_pa_override~='' and
      not single_flight_accelerator_pa_override_loaded then
    ai.pa:load(single_flight_accelerator_pa_override)
    ai:_debug_update_size()
    single_flight_accelerator_pa_override_loaded=true
  end
  if single_flight_accelerator_pa_override and
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
  if single_flight_pre_pulse_time_series==0 then
    single_flight_apply_placement(simion.wb.instances[1],initialized.placements.flight_tube)
    single_flight_apply_placement(simion.wb.instances[2],initialized.placements.reflectron)
  end
  single_flight_apply_placement(ai,initialized.placements.accelerator)
  ai.x,ai.y,ai.z={_lua_number(origin['x'])},{_lua_number(origin['y'])},{_lua_number(origin['z'])}
  if single_flight_pre_pulse_time_series==0 then
    single_flight_apply_placement(simion.wb.instances[4],initialized.placements.detector)
  end
  single_flight_apply_plan(ai.pa,initialized.static_electrode_plans.legacy_accelerator_characterization)
  if single_flight_pre_pulse_time_series==0 then
    single_flight_apply_plan(simion.wb.instances[2].pa,initialized.static_electrode_plans.reflectron)
  end
  if single_flight_staged_grid2_restart==0 then
    local rf=false
{rf_initializer}
    single_flight_pulse=single_flight_pulse_component.new{{canonical_clock=single_flight_instrument_time_us,
      pulse_time_us=handoff_pulse_time_us,pulse_width_us=handoff_pulse_width_us,pulse_mode=function() return handoff_pulse_mode end}}
    single_flight_frontend=single_flight_frontend_component.new{{rf_drive={rf_config},pulse_hook=single_flight_pulse,
      electrode_plan=single_flight_project_electrode_plan(),planes_z_mm={accelerator_planes_lua}}}
    local initial={{}}
{rf_static_apply}
    initial[{int(electrodes['grounded_shield_id'])}]=0
    for _,item in ipairs(single_flight_analyzer.accelerator_electrode_write_plan('off',
        {initial_voltage_lua})) do initial[item.electrode_id]=item.voltage_v end
    initial[{int(electrodes['entrance_reference_sleeve_id'])}]={_lua_number(entrance_reference_v)}
    initial[{int(electrodes['entrance_plate_id'])}]={_lua_number(entrance_plate_v)}
    ai.pa:fast_adjust(initial)
    if single_flight_overlay_enabled~=0 then
      local oi=assert(simion.wb.instances[5],'accelerator overlay instance is missing')
      assert(single_flight_exact_basename(oi.filename,
        'accelerator overlay')=='accelerator_overlay.pa0',
        'instance 5 must be the accelerator overlay')
      oi.x,oi.y,oi.z=single_flight_overlay_origin.x,single_flight_overlay_origin.y,single_flight_overlay_origin.z
      oi.az,oi.el,oi.rt,oi.scale=0,0,0,1
      oi.pa:fast_adjust(initial)
    end
  end
  single_flight_particle_state={{}}
  single_flight_analyzer_initialized={{}}
  single_flight_previous={{}}
  single_flight_reported={{}}
end
function segment.efield_adjust()
  if single_flight_pre_pulse_time_series~=0 then
    assert(ion_instance==3 or (single_flight_overlay_enabled~=0 and ion_instance==5),
      'pre-pulse screening particle escaped its frontend/accelerator active scope')
  end
  local instance=assert(simion.wb.instances[ion_instance],'field callback requires one PA instance')
  local state={{z_mm=ion_pz_mm,instance_id=ion_instance,instance_dx_mm=instance.pa.dx_mm,
    instance_dz_mm=instance.pa.dz_mm,instance_scale=instance.scale}}
  local base=single_flight_analyzer.efield_adjust(state)
  state.pulse_active=single_flight_staged_grid2_restart~=0 or single_flight_pulse.is_active_at(single_flight_instrument_time_us())
  local result=single_flight_region_field.apply(base,state)
  if result then
    if result.replace_all then ion_dvoltsx_gu=0; ion_dvoltsy_gu=0; ion_dvoltsz_gu=0 end
    if result.dvoltsx_gu~=nil then ion_dvoltsx_gu=result.dvoltsx_gu end
    if result.dvoltsy_gu~=nil then ion_dvoltsy_gu=result.dvoltsy_gu end
    if result.dvoltsz_gu~=nil then ion_dvoltsz_gu=result.dvoltsz_gu end
  end
end
function segment.fast_adjust()
  if single_flight_staged_grid2_restart~=0 then return end
  if ion_instance==3 or (single_flight_overlay_enabled~=0 and ion_instance==5) then
    single_flight_frontend.apply_at(single_flight_instrument_time_us(),single_flight_set_electrode)
  end
end
function segment.instance_adjust()
  if single_flight_overlay_enabled==0 or ion_instance~=5 then return end
  local b=single_flight_overlay_bounds
  if single_flight_pre_pulse_time_series~=0 then
    if ion_px_mm<=b.x_min or ion_px_mm>=b.x_max or
        ion_py_mm<=b.y_min or ion_py_mm>=b.y_max or
        ion_pz_mm<=b.z_min or ion_pz_mm>=b.z_max then ion_instance=0 end
    return
  end
  local detector=simion.wb.instances[4]
  if detector:inside_wc(ion_px_mm,ion_py_mm,ion_pz_mm) or
      ion_px_mm<=b.x_min or ion_px_mm>=b.x_max or
      ion_py_mm<=b.y_min or ion_py_mm>=b.y_max or
      ion_pz_mm<=b.z_min or ion_pz_mm>=b.z_max then ion_instance=0 end
end
function segment.initialize()
  local time=single_flight_instrument_time_us()
  if single_flight_staged_grid2_restart~=0 then
    assert(ion_instance==single_flight_staged_grid2_start_instance,
      'staged grid2 particle did not start in the contract-bound PA instance')
  end
  if single_flight_pre_pulse_time_series==0 then
    single_flight_require_analyzer_particle(ion_time_of_flight)
  end
  if single_flight_staged_grid2_restart==0 then
    single_flight_particle_state[ion_number]={{frontend=single_flight_frontend.initialize_particle(ion_pz_mm),
      previous={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}}}
  end
  single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
    vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
  single_flight_reported[ion_number]=single_flight_staged_grid2_restart~=0 and
    {restart_reported_lua} or {{}}
  single_flight_pre_pulse_next_sample[ion_number]=1
  print(string.format('TRACE: source_release ion=%d particle_id=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g simion_native_kinetic_energy_eV=%.17g',ion_number,single_flight_canonical_particle_id(),time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_ke))
  if single_flight_staged_grid2_restart~=0 then
    single_flight_trace_checkpoint('local_accelerator_exit',time,ion_px_mm,ion_py_mm,ion_pz_mm,
      ion_vx_mm,ion_vy_mm,ion_vz_mm)
  end
end
function segment.tstep_adjust()
  local analyzer_dt=nil
  if single_flight_pre_pulse_time_series==0 then
    analyzer_dt=single_flight_analyzer.tstep_adjust{{x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
      vx_mm_per_us=ion_vx_mm,vy_mm_per_us=ion_vy_mm,vz_mm_per_us=ion_vz_mm,
      detector_cell_dx_mm=simion.wb.instances[4].pa.dx_mm}}
  end
  if analyzer_dt and ion_time_step>analyzer_dt then ion_time_step=analyzer_dt end
  local time=single_flight_instrument_time_us()
  if single_flight_pre_pulse_time_series~=0 then
    local next_index=single_flight_pre_pulse_next_sample[ion_number] or 1
    local next_time=single_flight_pre_pulse_sample_times_us[next_index]
    if next_time and time<next_time and ion_time_step>next_time-time then
      ion_time_step=next_time-time
    end
  end
  if single_flight_staged_grid2_restart==0 then
    local pulse_capped=single_flight_pulse.cap_timestep_at(time,ion_time_step)
    if ion_time_step>pulse_capped then ion_time_step=pulse_capped end
  end
  if single_flight_staged_grid2_restart==0 and (ion_instance==3 or (single_flight_overlay_enabled~=0 and ion_instance==5)) then
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
  if single_flight_staged_grid2_restart==0 then
    local state=single_flight_require_particle_state()
    local current={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}
    single_flight_frontend.observe_step(state.previous,current,state.frontend)
    state.previous=current
  end
  local p=single_flight_previous[ion_number]
  if single_flight_pre_pulse_time_series~=0 then
    local next_index=single_flight_pre_pulse_next_sample[ion_number] or 1
    while single_flight_pre_pulse_sample_times_us[next_index] and
        time>=single_flight_pre_pulse_sample_times_us[next_index] do
      local sample_time=single_flight_pre_pulse_sample_times_us[next_index]
      local x,y,z,vx,vy,vz=ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm
      assert(math.abs(time-sample_time)<=1e-12*math.max(1,math.abs(sample_time)),
        'pre-pulse time-series sample did not land on its native SIMION timestep')
      local energy=0.0051821348263402529*ion_mass*(vx*vx+vy*vy+vz*vz)
      if trajectory_log_enable~=0 then
        print(string.format('TRACE: pre_pulse_time_series_state ion=%d particle_id=%d sample_index=%d instrument_time_us=%.17g actual_instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g kinetic_energy_eV=%.17g survival_status=alive',
          ion_number,single_flight_canonical_particle_id(),next_index,sample_time,time,x,y,z,vx,vy,vz,energy))
      end
      next_index=next_index+1
      single_flight_pre_pulse_next_sample[ion_number]=next_index
    end
    single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
      vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
    if next_index>#{screening_sample_table} then ion_splat=1 end
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
  if single_flight_pre_pulse_time_series~=0 then return end
  if handoff_pulse_mode==1 and trajectory_log_enable~=0 then
    print(string.format('TRACE: handoff_terminal_raw ion=%d instance=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',
      ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))
  end
  single_flight_require_analyzer_particle(ion_time_of_flight)
  local result=single_flight_analyzer.terminate{{particle_id=single_flight_canonical_particle_id(),instance_id=ion_instance,
    elapsed_us=ion_time_of_flight,x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
    vx_mm_per_us=ion_vx_mm,vy_mm_per_us=ion_vy_mm,vz_mm_per_us=ion_vz_mm,
    detector_cell_dx_mm=simion.wb.instances[4].pa.dx_mm}}
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
    return program


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyzer-component", required=True, type=Path)
    parser.add_argument("--pulse-hook", required=True, type=Path)
    parser.add_argument("--frontend-hook", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--frontend-contract", required=True, type=Path)
    parser.add_argument("--accelerator-overlay-contract", type=Path)
    parser.add_argument("--oatof", required=True, type=Path)
    parser.add_argument("--initial-global-state", required=True, type=Path)
    parser.add_argument("--particle-row-map", required=True, type=Path)
    parser.add_argument("--restart-context", type=Path)
    parser.add_argument("--resolved-region-field-contract", required=True, type=Path)
    parser.add_argument("--rf-drive-kernel", required=True, type=Path)
    parser.add_argument("--rf-steps-per-period", required=True, type=int)
    parser.add_argument(
        "--source-release-mode",
        choices=("continuous_frontend", "pre_pulse_restart", "staged_grid2_restart"),
        default=None,
    )
    parser.add_argument("--terminate-after-pulse", action="store_true")
    parser.add_argument("--pre-pulse-time-series-contract", type=Path)
    parser.add_argument("--global-segments", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    oatof = _load(args.oatof)
    region_field_contract = _load(args.resolved_region_field_contract)
    validate_resolved_region_field_contract(region_field_contract)
    birth_times, source_ids = load_initial_state(args.initial_global_state)
    row_map_ids = load_row_map(args.particle_row_map, source_ids)
    restart_context = _load(args.restart_context) if args.restart_context else None
    output = build_successor_program(
        _load(args.upstream),
        _load(args.frontend_contract),
        oatof,
        region_field_contract,
        birth_times_us=birth_times,
        particle_ids=row_map_ids,
        restart_context=restart_context,
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
        rf_steps_per_period=args.rf_steps_per_period,
        global_segments=args.global_segments,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8", newline="\n")
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
        "oatof_sha256": file_sha256(args.oatof),
        "initial_global_state_sha256": (
            file_sha256(args.initial_global_state)
            if args.initial_global_state is not None
            else None
        ),
        "particle_row_map_sha256": file_sha256(args.particle_row_map),
        "restart_context_sha256": (
            file_sha256(args.restart_context) if args.restart_context else None
        ),
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
        "source_release_mode": (
            args.source_release_mode
            or ("staged_grid2_restart" if restart_context is not None else "continuous_frontend")
        ),
        "clock_basis": "canonical_instrument_time_us",
        "terminate_after_pulse": args.terminate_after_pulse,
        "pre_pulse_time_series_contract_sha256": (
            file_sha256(args.pre_pulse_time_series_contract)
            if args.pre_pulse_time_series_contract is not None
            else None
        ),
        "global_segments": args.global_segments,
        "output_sha256": file_sha256(args.output),
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_PROGRAM=PASS OUTPUT={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
