"""Build the continuous SIMION Program from frozen oaTOF and multipole contracts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from typing import Any

from common.contracts.file_identity import file_sha256
from common.multipole.grounded_shield import require_grounded_potential
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.arm8_simion_solver_closure import (
    full_domain_piecewise_field_lua,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _lua_number(value: float) -> str:
    return format(float(value), ".17g")


def enable_official_global_segments(formal: str) -> str:
    """Enable SIMION's documented global segment dispatch for restart states."""
    declaration = "simion.workbench_program()"
    if formal.count(declaration) != 1:
        raise ValueError("formal Program must declare exactly one workbench")
    return formal.replace(
        declaration,
        declaration + "\nsimion.early_access(8.2)\nsim_segment_global = 1",
        1,
    )


def load_birth_times(path: Path) -> list[float]:
    """Load contiguous per-particle instrument birth times in microseconds."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("single-flight initial state is empty")
    id_column = (
        "particle_id" if "particle_id" in rows[0] else "simulation_particle_id"
    )
    actual_ids = [int(row[id_column]) for row in rows]
    if actual_ids != list(range(1, len(rows) + 1)):
        raise ValueError("single-flight initial-state particle IDs must be contiguous")
    values = [float(row["instrument_time_us"]) for row in rows]
    if any(value < 0 for value in values):
        raise ValueError("single-flight birth times must be non-negative")
    return values


def bind_oatof_adjustables(formal: str, oatof: dict[str, Any]) -> str:
    """Bind resolved geometry into Program defaults without SIMION CLI name limits."""
    geometry = oatof["geometry_mm"]
    accelerator = oatof["geometry_derivation"]["accelerator"]
    voltage = oatof["electrodes_V"]
    rings = oatof["rings"]
    coordinate = oatof["coordinate_convention"]
    values = {
        "V_repeller": voltage["repeller"],
        "V_grid1": voltage["grid1"],
        "V_mid": voltage["midgrid"],
        "V_backplate": voltage["backplate"],
        "accelerator_assembly_translation_z_mm": geometry["accelerator_repeller_z"],
        "accelerator_stage1_length_mm": accelerator["d1_mm"],
        "accelerator_stage2_length_mm": accelerator["d2_mm"],
        "accelerator_ring_count": rings["accelerator_count"],
        "accelerator_repeller_front_z_mm": geometry["accelerator_repeller_z"],
        "accelerator_grid1_z_mm": geometry["accelerator_grid1_z"],
        "accelerator_grid2_z_mm": geometry["accelerator_grid2_z"],
        "accelerator_focus_drift_mm": accelerator["focus_drift_after_grid2_mm"],
        "reflectron_entgrid_z_mm": geometry["L_flight"],
        "field_free_one_way_length_mm": geometry["L_flight"],
        "reflectron_stage1_length_mm": geometry["L_stage1"],
        "reflectron_stage2_length_mm": geometry["L_stage2"],
        "reflectron_stage1_ring_count": rings["stage1_count"],
        "reflectron_stage2_ring_count": rings["stage2_count"],
        "reflectron_midgrid_z_mm": geometry["L_flight"] + geometry["L_stage1"],
        "reflectron_backplate_z_mm": geometry["L_flight"] + geometry["L_reflectron"],
        "reflectron_grid_radius_mm": geometry["ring_outer_r"],
        "accelerator_axis_x_mm": coordinate["accelerator_axis_x"],
        "accelerator_bore_half_mm": geometry["accelerator_bore_half"],
        "accelerator_ring_width_mm": geometry["accelerator_ring_width"],
        "accelerator_insulation_gap_mm": geometry["accelerator_insulation_gap"],
        "accelerator_shield_wall_mm": geometry["accelerator_shield_wall"],
        "accelerator_rear_insulation_gap_mm": geometry["accelerator_rear_clearance"],
        "accelerator_repeller_thickness_mm": geometry["accelerator_repeller_thickness"],
        "accelerator_instance_z_mm": (
            geometry["accelerator_repeller_z"]
            - geometry["accelerator_repeller_thickness"]
            - geometry["accelerator_rear_clearance"]
            - geometry["accelerator_shield_wall"]
        ),
        "flight_tube_inner_radius_mm": geometry["flight_tube_r"],
        "flight_tube_shield_wall_mm": geometry["flight_tube_wall"],
        "flight_tube_near_endcap_gap_mm": geometry["shield_near_endcap_gap"],
        "flight_tube_far_endcap_gap_mm": geometry["shield_axial_gap"],
        "flight_tube_endcap_thickness_mm": geometry["shield_endcap_thickness"],
        "reflectron_backplate_thickness_mm": geometry["ring_thickness"],
    }
    bound = formal
    for name, value in values.items():
        pattern = rf"(?m)^(adjustable\s+{re.escape(name)}\s*=)[^\r\n]+$"
        bound, count = re.subn(pattern, rf"\g<1>{_lua_number(value)}", bound)
        if count != 1:
            raise ValueError(f"formal Program adjustable is not unique: {name}")
    return bound


def disable_redundant_ground_fast_adjust(formal: str) -> str:
    """Keep grounded single-electrode PAs read-only in parallel flights."""

    block = " r:fast_adjust(reflectron_voltages)\n t:fast_adjust{[1]=0}\n d:fast_adjust{[1]=0}"
    replacement = (
        " r:fast_adjust(reflectron_voltages)\n"
        " -- Flight-tube and detector PA0 are frozen at 0 V; re-adjusting them is\n"
        " -- redundant and unsafe when parallel SIMION processes share run inputs."
    )
    if formal.count(block) != 1:
        raise ValueError("formal grounded-PA fast-adjust block is not unique")
    return formal.replace(block, replacement)


def allow_accelerator_overlay_instance(formal: str) -> str:
    """Extend the frozen four-instance workbench assertion for local PA overlay."""

    assertion = (
        "assert(#simion.wb.instances==4, "
        "'formal workbench must contain four PA instances')"
    )
    replacement = (
        "assert(#simion.wb.instances==5, "
        "'overlay workbench must contain five PA instances')\n"
        " assert(simion.wb.instances[5].filename:match('accelerator_overlay%.pa0$'),\n"
        "   'instance 5 must be the boundary-coupled accelerator overlay')"
    )
    if formal.count(assertion) != 1:
        raise ValueError("formal workbench instance assertion is not unique")
    return formal.replace(assertion, replacement)


def build_extension(
    upstream: dict[str, Any],
    frontend: dict[str, Any],
    *,
    birth_times_us: list[float],
    terminate_after_pulse: bool = False,
    overlay: dict[str, Any] | None = None,
) -> str:
    if upstream.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("single-flight Program requires a multipole resolved design")
    if frontend.get("role") != "rf_oatof_simion_single_flight_frontend_contract":
        raise ValueError("single-flight Program requires a frontend contract")
    require_grounded_potential(
        upstream["axial_dc"]["upstream_shield_potential_V"], "multipole shield"
    )
    require_grounded_potential(
        frontend["junction_enclosure"]["shield_potential_V"], "frontend shield connection"
    )
    drive = upstream["drive"]
    if drive["waveform"] != "cosine":
        raise ValueError("single-flight Program currently requires the frozen cosine RF waveform")
    electrodes = upstream["segmentation"]["segmented_rod_array"]["electrodes"]
    unique: dict[int, dict[str, Any]] = {}
    for item in electrodes:
        unique[int(item["electrode_id"])] = item
    if set(unique) != set(range(1, 9)):
        raise ValueError("single-flight Program requires multipole electrodes 1 through 8")
    potentials = {
        int(item["electrode_id"]): float(item["potential_V"])
        for item in upstream["axial_dc"]["rod_electrodes"]
    }
    entrance_reference = upstream["axial_dc"]["entrance_reference_sleeve"]
    entrance_reference_v = float(entrance_reference["potential_V"])
    entrance_plate_v = float(upstream["axial_dc"]["entrance_plate_potential_V"])
    origin = frontend["instance_origin_mm"]
    overlay_origin = None
    overlay_active = None
    if overlay is not None:
        if overlay.get("role") != "rf_oatof_simion_accelerator_overlay_contract":
            raise ValueError("single-flight Program requires an accelerator overlay contract")
        if overlay["boundary_condition"]["mode"] != "coarse_electrode_basis_dirichlet_v1":
            raise ValueError("single-flight Program received an unknown overlay boundary mode")
        overlay_origin = overlay["instance_origin_mm"]
        overlay_active = overlay["active_bounds_mm"]
    handoff_x = frontend["source_exit_center_mm"]["x"]
    if not birth_times_us:
        raise ValueError("canonical instrument clock requires per-particle birth times")
    lines = [
        "",
        "-- BEGIN RF-OATOF SINGLE-FLIGHT EXTENSION",
        "adjustable single_flight_enable=1",
        "adjustable sf_ideal_accel_enable=0",
        "adjustable sf_ideal_accel_stage1_enable=0",
        "adjustable sf_ideal_accel_stage2_enable=0",
        "adjustable sf_arm8_global_field_enable=0",
        "local sf_stage1_env=assert(tonumber(os.getenv('OATOF_IDEAL_ACCEL_STAGE1_ENABLE') or '0'),'invalid stage1 env')",
        "local sf_stage2_env=assert(tonumber(os.getenv('OATOF_IDEAL_ACCEL_STAGE2_ENABLE') or '0'),'invalid stage2 env')",
        "local sf_refl_stage1_env=assert(tonumber(os.getenv('OATOF_IDEAL_REFLECTRON_STAGE1_ENABLE') or '0'),'invalid reflectron stage1 env')",
        "local sf_refl_stage2_env=assert(tonumber(os.getenv('OATOF_IDEAL_REFLECTRON_STAGE2_ENABLE') or '0'),'invalid reflectron stage2 env')",
        "local sf_arm8_global_env=assert(tonumber(os.getenv('OATOF_ARM8_GLOBAL_FIELD_ENABLE') or '0'),'invalid Arm8 global field env')",
        "assert((sf_stage1_env==0 or sf_stage1_env==1) and (sf_stage2_env==0 or sf_stage2_env==1),'ideal accelerator stage env must be binary')",
        "assert((sf_refl_stage1_env==0 or sf_refl_stage1_env==1) and (sf_refl_stage2_env==0 or sf_refl_stage2_env==1),'ideal reflectron stage env must be binary')",
        "assert(sf_arm8_global_env==0 or sf_arm8_global_env==1,'Arm8 global field env must be binary')",
        f"adjustable single_flight_rf_peak_v={_lua_number(drive['rf_amplitude_V_zero_to_peak_per_group'])}",
        f"adjustable single_flight_frequency_hz={_lua_number(drive['frequency_Hz'])}",
        "adjustable single_flight_rf_steps=160",
        "adjustable accelerator_ring_quadratic_V=0",
        "adjustable accelerator_ring_cubic_V=0",
        "local single_flight_particle_id_offset=assert(tonumber(os.getenv('OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET') or '0'),'invalid single-flight particle ID offset')",
        f"local single_flight_frontend_origin_x={_lua_number(origin['x'])}",
        f"local single_flight_frontend_origin_y={_lua_number(origin['y'])}",
        f"local single_flight_frontend_origin_z={_lua_number(origin['z'])}",
        f"local single_flight_overlay_enabled={1 if overlay is not None else 0}",
        f"local single_flight_overlay_origin_x={_lua_number(overlay_origin['x'] if overlay_origin else 0)}",
        f"local single_flight_overlay_origin_y={_lua_number(overlay_origin['y'] if overlay_origin else 0)}",
        f"local single_flight_overlay_origin_z={_lua_number(overlay_origin['z'] if overlay_origin else 0)}",
        f"local single_flight_overlay_active_x_min={_lua_number(overlay_active['x_min'] if overlay_active else 0)}",
        f"local single_flight_overlay_active_x_max={_lua_number(overlay_active['x_max'] if overlay_active else 0)}",
        f"local single_flight_overlay_active_y_min={_lua_number(overlay_active['y_min'] if overlay_active else 0)}",
        f"local single_flight_overlay_active_y_max={_lua_number(overlay_active['y_max'] if overlay_active else 0)}",
        f"local single_flight_overlay_active_z_min={_lua_number(overlay_active['z_min'] if overlay_active else 0)}",
        f"local single_flight_overlay_active_z_max={_lua_number(overlay_active['z_max'] if overlay_active else 0)}",
        f"local single_flight_handoff_x={_lua_number(handoff_x)}",
        "local single_flight_base_initialize_run=segment.initialize_run",
        "local single_flight_base_initialize=segment.initialize",
        "local single_flight_base_tstep_adjust=segment.tstep_adjust",
        "local single_flight_base_efield_adjust=segment.efield_adjust",
        "local single_flight_base_instance_adjust=segment.instance_adjust",
        "local single_flight_base_other_actions=segment.other_actions",
        "local single_flight_previous={}",
        "local single_flight_handoff_reported={}",
        "local single_flight_prepulse_reported={}",
        "local single_flight_grid1_forward_reported={}",
        "local single_flight_focus_forward_reported={}",
        "local single_flight_reflectron_entrance_reported={}",
        "local single_flight_reflectron_midgrid_reported={}",
        "local single_flight_reflectron_turning_reported={}",
        "local single_flight_reflectron_exit_reported={}",
        "-- Native plane landing follows SIMION Example test_plane lifecycle:",
        "-- tstep requests landing; other_actions observes the completed crossing.",
        "-- Position tolerance is state-comparison-only; positions are never changed.",
        "local single_flight_accel_plane_state={}",
        "local function single_flight_accel_state_for_current_particle()",
        "  local state=single_flight_accel_plane_state[ion_number]",
        "  if state==nil then",
        "    state={stage1=ion_pz_mm>=accelerator_grid1_z_mm and 'hitted' or 'approaching',stage2=ion_pz_mm>=accelerator_grid2_z_mm and 'hitted' or 'approaching',initialized_time=ion_time_of_flight,initialized_instance=ion_instance}",
        "    single_flight_accel_plane_state[ion_number]=state",
        "    if trajectory_log_enable~=0 then print(string.format('TRACE: accelerator_plane_hit_state ion=%d state=initialized t=%.12g z=%.17g instance=%d',ion_number,ion_time_of_flight,ion_pz_mm,ion_instance)) end",
        "  end",
        "  assert((state.stage1=='approaching' or state.stage1=='willhit' or state.stage1=='hitting' or state.stage1=='hitted') and (state.stage2=='approaching' or state.stage2=='willhit' or state.stage2=='hitting' or state.stage2=='hitted'),'accelerator plane state is invalid')",
        "  return state",
        "end",
        "local single_flight_birth_time_us={",
    ]
    if birth_times_us:
        for particle_id, value in enumerate(birth_times_us, start=1):
            lines.append(f"  [{particle_id}]={_lua_number(value)},")
    lines.extend([
        "}",
        f"local single_flight_terminate_after_pulse={1 if terminate_after_pulse else 0}",
        "local single_flight_omega=single_flight_frequency_hz*1e-6*2*math.pi",
        "local single_flight_rods={",
    ])
    for electrode_id in range(1, 9):
        item = unique[electrode_id]
        sign = 1 if int(item["electrode_group"]) == 1 else -1
        lines.append(
            f"  [{electrode_id}]={{dc={_lua_number(potentials[electrode_id])},sign={sign}}},"
        )
    lines.extend(
        [
            "}",
            "local function single_flight_instrument_time_us()",
            "  local global_particle_id=ion_number+single_flight_particle_id_offset",
            "  local birth=single_flight_birth_time_us[global_particle_id]",
            "  assert(birth~=nil,'absolute single-flight clock is missing particle birth time')",
            "  return birth+ion_time_of_flight",
            "end",
            "handoff_instrument_time_us=single_flight_instrument_time_us",
            "local function single_flight_trace_checkpoint(event,t,x,y,z,vx,vy,vz)",
            "  if trajectory_log_enable==0 then return end",
            "  local global_particle_id=ion_number+single_flight_particle_id_offset",
            "  local tof_since_pulse_us=t-handoff_pulse_time_us",
            "  local kinetic_energy_eV=0.0051821348263402529*ion_mass*(vx*vx+vy*vy+vz*vz)",
            "  print(string.format('TRACE: %s ion=%d particle_id=%d instrument_time_us=%.12g tof_since_pulse_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g kinetic_energy_eV=%.12g survival_status=alive',event,ion_number,global_particle_id,t,tof_since_pulse_us,x,y,z,vx,vy,vz,kinetic_energy_eV))",
            "end",
            "local function single_flight_pulse_is_on()",
            "  local instrument_time_us=single_flight_instrument_time_us()",
            "  return handoff_pulse_mode==0 or (handoff_pulse_mode==1 and",
            "    instrument_time_us>=handoff_pulse_time_us and",
            "    instrument_time_us<handoff_pulse_time_us+handoff_pulse_width_us)",
            "end",
            "local function single_flight_accelerator_ring_voltage(index)",
            "  local fraction=(6-index)/6",
            "  local endpoint_zero=fraction*(1-fraction)",
            "  return V_grid1*fraction+accelerator_ring_quadratic_V*endpoint_zero+",
            "    accelerator_ring_cubic_V*endpoint_zero*(2*fraction-1)",
            "end",
            "local function single_flight_set_frontend_voltages()",
            "  local instrument_time_us=single_flight_instrument_time_us()",
            "  local rf=single_flight_rf_peak_v*math.cos(single_flight_omega*instrument_time_us)",
            "  for id,item in pairs(single_flight_rods) do adj_elect[id]=item.dc+item.sign*rf end",
            "  adj_elect[9]=0",
            "  local pulse_on=single_flight_pulse_is_on()",
            "  adj_elect[10]=pulse_on and V_repeller or handoff_pulse_pre_all_v",
            "  adj_elect[11]=pulse_on and V_grid1 or handoff_pulse_pre_all_v",
            "  adj_elect[12]=pulse_on and single_flight_accelerator_ring_voltage(1) or handoff_pulse_pre_all_v",
            "  adj_elect[13]=pulse_on and single_flight_accelerator_ring_voltage(2) or handoff_pulse_pre_all_v",
            "  adj_elect[14]=pulse_on and single_flight_accelerator_ring_voltage(3) or handoff_pulse_pre_all_v",
            "  adj_elect[15]=pulse_on and single_flight_accelerator_ring_voltage(4) or handoff_pulse_pre_all_v",
            "  adj_elect[16]=pulse_on and single_flight_accelerator_ring_voltage(5) or handoff_pulse_pre_all_v",
            "  adj_elect[17]=0",
            f"  adj_elect[18]={_lua_number(entrance_reference_v)}",
            f"  adj_elect[19]={_lua_number(entrance_plate_v)}",
            "end",
            "function segment.initialize_run()",
            "  single_flight_base_initialize_run()",
            "  sf_ideal_accel_stage1_enable=sf_stage1_env",
            "  sf_ideal_accel_stage2_enable=sf_stage2_env",
            "  ideal_refl_stage1_enable=sf_refl_stage1_env",
            "  ideal_refl_stage2_enable=sf_refl_stage2_env",
            "  sf_arm8_global_field_enable=sf_arm8_global_env",
            "  assert(sf_ideal_accel_stage1_enable==sf_stage1_env and sf_ideal_accel_stage2_enable==sf_stage2_env,'ideal accelerator stage env was not applied')",
            "  if trajectory_log_enable~=0 then print(string.format('TRACE: pulse_resolution_accelerator_stage_mode stage1=%d stage2=%d',sf_ideal_accel_stage1_enable,sf_ideal_accel_stage2_enable)) end",
            "  if trajectory_log_enable~=0 then print(string.format('TRACE: pulse_resolution_reflectron_stage_mode stage1=%d stage2=%d',ideal_refl_stage1_enable,ideal_refl_stage2_enable)) end",
            "  if trajectory_log_enable~=0 then print(string.format('TRACE: pulse_resolution_arm8_global_field enabled=%d real_pa_blending=0',sf_arm8_global_field_enable)) end",
            "  if trajectory_log_enable~=0 then print('TRACE: pulse_resolution_overlay_policy ideal_stage_regions_disable_overlay_instance5=1 analytic_field_instance3=1') end",
            "  assert(single_flight_enable~=0,'single-flight Program requires explicit enable')",
            "  local ai=simion.wb.instances[3]",
            "  ai.x,ai.y,ai.z=single_flight_frontend_origin_x,single_flight_frontend_origin_y,single_flight_frontend_origin_z",
            "  ai.az,ai.el,ai.rt,ai.scale=0,0,0,1",
            "  local initial={}",
            "  for id,item in pairs(single_flight_rods) do initial[id]=item.dc end",
            "  initial[9]=0",
            "  initial[10]=0; initial[11]=0; initial[12]=0; initial[13]=0; initial[14]=0",
            "  initial[15]=0; initial[16]=0; initial[17]=0",
            f"  initial[18]={_lua_number(entrance_reference_v)}",
            f"  initial[19]={_lua_number(entrance_plate_v)}",
            "  ai.pa:fast_adjust(initial)",
            "  if single_flight_overlay_enabled~=0 then",
            "    local oi=simion.wb.instances[5]",
            "    assert(oi and oi.filename:match('accelerator_overlay%.pa0$'),'accelerator overlay instance is missing')",
            "    oi.x,oi.y,oi.z=single_flight_overlay_origin_x,single_flight_overlay_origin_y,single_flight_overlay_origin_z",
            "    oi.az,oi.el,oi.rt,oi.scale=0,0,0,1",
            "    oi.pa:fast_adjust(initial)",
            "  end",
            "  single_flight_previous={}; single_flight_handoff_reported={}; single_flight_prepulse_reported={}; single_flight_grid1_forward_reported={}; single_flight_focus_forward_reported={}; single_flight_accel_plane_state={}",
            "  single_flight_reflectron_entrance_reported={}; single_flight_reflectron_midgrid_reported={}; single_flight_reflectron_turning_reported={}; single_flight_reflectron_exit_reported={}",
            "  if trajectory_log_enable~=0 then",
            "    print(string.format('TRACE: single_flight_contract frontend_origin=(%.12g,%.12g,%.12g) handoff_x=%.12g rf_peak_v=%.12g frequency_hz=%.12g',ai.x,ai.y,ai.z,single_flight_handoff_x,single_flight_rf_peak_v,single_flight_frequency_hz))",
            "  end",
            "end",
            "function segment.fast_adjust()",
            "  if ion_instance==3 or (single_flight_overlay_enabled~=0 and ion_instance==5) then single_flight_set_frontend_voltages() end",
            "end",
            "function segment.instance_adjust()",
            "  if single_flight_base_instance_adjust then single_flight_base_instance_adjust() end",
            "  if single_flight_overlay_enabled==0 or ion_instance~=5 then return end",
            "  local di=simion.wb.instances[4]",
            "  local ideal_stage1_region=sf_ideal_accel_stage1_enable~=0 and ion_pz_mm>=accelerator_repeller_front_z_mm and ion_pz_mm<accelerator_grid1_z_mm",
            "  local ideal_stage2_region=sf_ideal_accel_stage2_enable~=0 and ion_pz_mm>=accelerator_grid1_z_mm and ion_pz_mm<accelerator_grid2_z_mm",
            "  if sf_arm8_global_field_enable~=0 or sf_ideal_accel_enable~=0 or ideal_stage1_region or ideal_stage2_region or di:inside_wc(ion_px_mm,ion_py_mm,ion_pz_mm) or",
            "      ion_px_mm<=single_flight_overlay_active_x_min or ion_px_mm>=single_flight_overlay_active_x_max or",
            "      ion_py_mm<=single_flight_overlay_active_y_min or ion_py_mm>=single_flight_overlay_active_y_max or",
            "      ion_pz_mm<=single_flight_overlay_active_z_min or ion_pz_mm>=single_flight_overlay_active_z_max then ion_instance=0 end",
            "end",
            "function segment.initialize()",
            "  single_flight_base_initialize()",
            "  local instrument_time_us=single_flight_instrument_time_us()",
            "  single_flight_accel_state_for_current_particle()",
            "  single_flight_previous[ion_number]={t=instrument_time_us,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}",
            "  print(string.format('TRACE: source_release ion=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g simion_native_kinetic_energy_eV=%.17g',ion_number,instrument_time_us,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_ke))",
            "end",
            "function segment.tstep_adjust()",
            "  single_flight_base_tstep_adjust()",
            "  if ion_instance==3 and single_flight_pulse_is_on() and ion_vz_mm>0 then",
            "    local state=single_flight_accel_state_for_current_particle()",
            "    local repeated_plane_evaluation=state.last_eval_time==ion_time_of_flight and state.last_eval_instance==ion_instance",
            "    if not repeated_plane_evaluation then",
            "    state.last_eval_time=ion_time_of_flight; state.last_eval_instance=ion_instance",
            "    local stage,next_plane,E=nil,nil,0",
            "    if (sf_ideal_accel_enable~=0 or sf_ideal_accel_stage1_enable~=0) and ion_pz_mm>=accelerator_repeller_front_z_mm and ion_pz_mm<accelerator_grid1_z_mm then stage='stage1'; next_plane=accelerator_grid1_z_mm; E=(V_repeller-V_grid1)/(accelerator_grid1_z_mm-accelerator_repeller_front_z_mm)",
            "    elseif (sf_ideal_accel_enable~=0 or sf_ideal_accel_stage2_enable~=0) and ion_pz_mm>=accelerator_grid1_z_mm and ion_pz_mm<accelerator_grid2_z_mm then stage='stage2'; next_plane=accelerator_grid2_z_mm; E=V_grid1/(accelerator_grid2_z_mm-accelerator_grid1_z_mm) end",
            "    if stage~=nil then",
            "      local status=state[stage]",
            "      local distance=next_plane-ion_pz_mm",
            "      local coordinate_tolerance=32*2.2204460492503131e-16*math.max(1,math.abs(next_plane))",
            "      if status=='willhit' and ion_vz_mm>0 and math.abs(distance)<=coordinate_tolerance then",
            "        state[stage]='hitting'; state[stage..'_zero_step_count']=(state[stage..'_zero_step_count'] or 0)+1",
            "        assert(state[stage..'_zero_step_count']==1,'accelerator plane hitting requested more than one zero-step confirmation')",
            "        ion_time_step=0",
            "      elseif status=='approaching' or status=='willhit' then",
            "      local acceleration=ion_charge*96.4853321233*E/ion_mass",
            "      local crossing_time",
            "      if math.abs(acceleration)>1e-15 then crossing_time=(-ion_vz_mm+math.sqrt(ion_vz_mm^2+2*acceleration*distance))/acceleration",
            "      else crossing_time=distance/ion_vz_mm end",
            "      assert(crossing_time>0,'accelerator plane crossing estimate made no representable time progress')",
            "      if ion_time_step>=crossing_time then state[stage]='willhit'; state[stage..'_request_time']=ion_time_of_flight; state[stage..'_request_z']=ion_pz_mm; ion_time_step=crossing_time end",
            "      end",
            "    end",
            "    end",
            "  end",
            "  if ion_instance==3 or (single_flight_overlay_enabled~=0 and ion_instance==5) then",
            "    local rf_step=1e6/single_flight_frequency_hz/single_flight_rf_steps",
            "    if ion_time_step>rf_step then ion_time_step=rf_step end",
            "  end",
            "end",
            "function segment.efield_adjust()",
            "  single_flight_base_efield_adjust()",
            "  if (sf_ideal_accel_enable==0 and sf_ideal_accel_stage1_enable==0 and sf_ideal_accel_stage2_enable==0) or ion_instance~=3 or",
            "      not single_flight_pulse_is_on() then return end",
            "  if math.abs(ion_px_mm-accelerator_axis_x_mm)>accelerator_bore_half_mm or",
            "      math.abs(ion_py_mm-accelerator_axis_y_mm)>accelerator_bore_half_mm then return end",
            "  local z,E=ion_pz_mm,nil",
            "  if z>=accelerator_repeller_front_z_mm and z<accelerator_grid1_z_mm and (sf_ideal_accel_enable~=0 or sf_ideal_accel_stage1_enable~=0) then",
            "    E=(V_repeller-V_grid1)/(accelerator_grid1_z_mm-accelerator_repeller_front_z_mm)",
            "  elseif z>=accelerator_grid1_z_mm and z<accelerator_grid2_z_mm and (sf_ideal_accel_enable~=0 or sf_ideal_accel_stage2_enable~=0) then",
            "    E=V_grid1/(accelerator_grid2_z_mm-accelerator_grid1_z_mm)",
            "  end",
            "  if E~=nil then",
            "    ion_dvoltsx_gu=0; ion_dvoltsy_gu=0; ion_dvoltsz_gu=0",
            "    ion_dvoltsz_gu=-E*simion.wb.instances[3].pa.dz_mm*simion.wb.instances[3].scale",
            "  end",
            "end",
            "function segment.other_actions()",
            "  single_flight_base_other_actions()",
            "  local p=single_flight_previous[ion_number]",
            "  local instrument_time_us=single_flight_instrument_time_us()",
            "  local plane_state=single_flight_accel_state_for_current_particle()",
            "  if p then",
            "    for _,stage in ipairs({'stage1','stage2'}) do",
            "      local plane=stage=='stage1' and accelerator_grid1_z_mm or accelerator_grid2_z_mm",
            "      local status=plane_state[stage]",
            "      local crossed=p.z<plane and ion_pz_mm>=plane and ion_vz_mm>0",
            "      if status=='willhit' and crossed then",
            "        assert(instrument_time_us>p.t,'accelerator plane crossing made no representable time progress')",
            "        plane_state[stage]='hitting'; plane_state[stage..'_oa_time']=instrument_time_us; plane_state[stage..'_oa_count']=(plane_state[stage..'_oa_count'] or 0)+1",
            "        assert(plane_state[stage..'_oa_count']==1,'accelerator plane crossing was observed more than once')",
            "        if trajectory_log_enable~=0 then print(string.format('TRACE: accelerator_plane_hit_state ion=%d stage=%s state=hitting t=%.12g z=%.17g oa_count=%d',ion_number,stage,instrument_time_us,ion_pz_mm,plane_state[stage..'_oa_count'])) end",
            "      elseif status=='hitting' then",
            "        if plane_state[stage..'_zero_step_count'] then",
            "          assert(ion_vz_mm>0 and (plane-ion_pz_mm)<=32*2.2204460492503131e-16*math.max(1,math.abs(plane)),'accelerator plane zero-step confirmation is outside the governed boundary tolerance')",
            "          plane_state[stage..'_oa_count']=(plane_state[stage..'_oa_count'] or 0)+1",
            "          assert(plane_state[stage..'_oa_count']==1,'accelerator plane zero-step confirmation was observed more than once')",
            "        end",
            "        plane_state[stage]='hitted'",
            "      end",
            "    end",
            "  end",
            "  if p and not single_flight_prepulse_reported[ion_number] and p.t<handoff_pulse_time_us and instrument_time_us>=handoff_pulse_time_us then",
            "    local f=(handoff_pulse_time_us-p.t)/(instrument_time_us-p.t)",
            "    local xc=p.x+f*(ion_px_mm-p.x); local yc=p.y+f*(ion_py_mm-p.y); local zc=p.z+f*(ion_pz_mm-p.z)",
            "    single_flight_prepulse_reported[ion_number]=true",
            "    if trajectory_log_enable~=0 then",
            "      print(string.format('TRACE: pre_pulse_state ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,handoff_pulse_time_us,xc,yc,zc,ion_vx_mm,ion_vy_mm,ion_vz_mm))",
            "    end",
            "  end",
            "  if p and not single_flight_handoff_reported[ion_number] and p.x<single_flight_handoff_x and ion_px_mm>=single_flight_handoff_x and ion_vx_mm>0 then",
            "    local f=(single_flight_handoff_x-p.x)/(ion_px_mm-p.x)",
            "    local tc=p.t+f*(instrument_time_us-p.t)",
            "    local yc=p.y+f*(ion_py_mm-p.y); local zc=p.z+f*(ion_pz_mm-p.z)",
            "    single_flight_handoff_reported[ion_number]=true",
            "    if trajectory_log_enable~=0 then",
            "      print(string.format('TRACE: single_flight_handoff ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,tc,single_flight_handoff_x,yc,zc,ion_vx_mm,ion_vy_mm,ion_vz_mm))",
            "    end",
            "  end",
            "  if p and not single_flight_grid1_forward_reported[ion_number] and p.z<accelerator_grid1_z_mm and ion_pz_mm>=accelerator_grid1_z_mm and ion_vz_mm>0 then",
            "    local f=(accelerator_grid1_z_mm-p.z)/(ion_pz_mm-p.z)",
            "    local tc=p.t+f*(instrument_time_us-p.t)",
            "    local xc=p.x+f*(ion_px_mm-p.x); local yc=p.y+f*(ion_py_mm-p.y)",
            "    single_flight_grid1_forward_reported[ion_number]=true",
            "    if trajectory_log_enable~=0 then",
            "      print(string.format('TRACE: accelerator_grid1_forward ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,tc,xc,yc,accelerator_grid1_z_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))",
            "    end",
            "  end",
            "  local focus_z=accelerator_grid2_z_mm+accelerator_focus_drift_mm",
            "  if p and not single_flight_focus_forward_reported[ion_number] and p.z<focus_z and ion_pz_mm>=focus_z and ion_vz_mm>0 then",
            "    local f=(focus_z-p.z)/(ion_pz_mm-p.z)",
            "    local tc=p.t+f*(instrument_time_us-p.t)",
            "    local xc=p.x+f*(ion_px_mm-p.x); local yc=p.y+f*(ion_py_mm-p.y)",
            "    single_flight_focus_forward_reported[ion_number]=true",
            "    if trajectory_log_enable~=0 then",
            "      print(string.format('TRACE: accelerator_focus_forward ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,tc,xc,yc,focus_z,ion_vx_mm,ion_vy_mm,ion_vz_mm))",
            "    end",
            "  end",
            "  if p and not single_flight_reflectron_entrance_reported[ion_number] and p.z<reflectron_entgrid_z_mm and ion_pz_mm>=reflectron_entgrid_z_mm and ion_vz_mm>0 then",
            "    local f=(reflectron_entgrid_z_mm-p.z)/(ion_pz_mm-p.z)",
            "    local tc=p.t+f*(instrument_time_us-p.t)",
            "    local xc=p.x+f*(ion_px_mm-p.x); local yc=p.y+f*(ion_py_mm-p.y)",
            "    local vxc=p.vx+f*(ion_vx_mm-p.vx); local vyc=p.vy+f*(ion_vy_mm-p.vy); local vzc=p.vz+f*(ion_vz_mm-p.vz)",
            "    single_flight_reflectron_entrance_reported[ion_number]=true",
            "    single_flight_trace_checkpoint('reflectron_entrance_forward',tc,xc,yc,reflectron_entgrid_z_mm,vxc,vyc,vzc)",
            "  end",
            "  if p and single_flight_reflectron_entrance_reported[ion_number] and not single_flight_reflectron_midgrid_reported[ion_number] and p.z<reflectron_midgrid_z_mm and ion_pz_mm>=reflectron_midgrid_z_mm and ion_vz_mm>0 then",
            "    local f=(reflectron_midgrid_z_mm-p.z)/(ion_pz_mm-p.z)",
            "    local tc=p.t+f*(instrument_time_us-p.t)",
            "    local xc=p.x+f*(ion_px_mm-p.x); local yc=p.y+f*(ion_py_mm-p.y)",
            "    local vxc=p.vx+f*(ion_vx_mm-p.vx); local vyc=p.vy+f*(ion_vy_mm-p.vy); local vzc=p.vz+f*(ion_vz_mm-p.vz)",
            "    single_flight_reflectron_midgrid_reported[ion_number]=true",
            "    single_flight_trace_checkpoint('reflectron_midgrid_forward',tc,xc,yc,reflectron_midgrid_z_mm,vxc,vyc,vzc)",
            "  end",
            "  if p and single_flight_reflectron_midgrid_reported[ion_number] and not single_flight_reflectron_turning_reported[ion_number] and p.vz>0 and ion_vz_mm<=0 then",
            "    local f=p.vz/(p.vz-ion_vz_mm)",
            "    local tc=p.t+f*(instrument_time_us-p.t)",
            "    local xc=p.x+f*(ion_px_mm-p.x); local yc=p.y+f*(ion_py_mm-p.y); local zc=p.z+f*(ion_pz_mm-p.z)",
            "    local vxc=p.vx+f*(ion_vx_mm-p.vx); local vyc=p.vy+f*(ion_vy_mm-p.vy)",
            "    single_flight_reflectron_turning_reported[ion_number]=true",
            "    single_flight_trace_checkpoint('reflectron_turning_point',tc,xc,yc,zc,vxc,vyc,0)",
            "  end",
            "  if p and single_flight_reflectron_turning_reported[ion_number] and not single_flight_reflectron_exit_reported[ion_number] and p.z>reflectron_entgrid_z_mm and ion_pz_mm<=reflectron_entgrid_z_mm and ion_vz_mm<0 then",
            "    local f=(reflectron_entgrid_z_mm-p.z)/(ion_pz_mm-p.z)",
            "    local tc=p.t+f*(instrument_time_us-p.t)",
            "    local xc=p.x+f*(ion_px_mm-p.x); local yc=p.y+f*(ion_py_mm-p.y)",
            "    local vxc=p.vx+f*(ion_vx_mm-p.vx); local vyc=p.vy+f*(ion_vy_mm-p.vy); local vzc=p.vz+f*(ion_vz_mm-p.vz)",
            "    single_flight_reflectron_exit_reported[ion_number]=true",
            "    single_flight_trace_checkpoint('reflectron_exit_return',tc,xc,yc,reflectron_entgrid_z_mm,vxc,vyc,vzc)",
            "  end",
            "  single_flight_previous[ion_number]={t=instrument_time_us,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}",
            "  if single_flight_terminate_after_pulse~=0 and instrument_time_us>=handoff_pulse_time_us then ion_splat=1 end",
            "end",
            "-- END RF-OATOF SINGLE-FLIGHT EXTENSION",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal", required=True, type=Path)
    parser.add_argument("--pulse-extension", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--frontend-contract", required=True, type=Path)
    parser.add_argument("--accelerator-overlay-contract", type=Path)
    parser.add_argument("--oatof", required=True, type=Path)
    parser.add_argument("--initial-global-state", required=True, type=Path)
    parser.add_argument("--arm8-global-field-contract", type=Path)
    parser.add_argument("--terminate-after-pulse", action="store_true")
    parser.add_argument("--global-segments", action="store_true")
    parser.add_argument(
        "--frontend-program-profile",
        default="combined_frontend",
        choices=("combined_frontend", "formal_accelerator"),
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    oatof = _load(args.oatof)
    formal = disable_redundant_ground_fast_adjust(bind_oatof_adjustables(
        args.formal.read_text(encoding="utf-8-sig"), oatof
    ))
    if args.global_segments:
        formal = enable_official_global_segments(formal)
    if args.accelerator_overlay_contract is not None:
        formal = allow_accelerator_overlay_instance(formal)
    pulse = args.pulse_extension.read_text(encoding="utf-8-sig")
    if formal.count("simion.workbench_program()") != 1 or "segment.fast_adjust" not in pulse:
        raise ValueError("frozen oaTOF Program inputs differ from the expected contract")
    extension = ""
    if args.frontend_program_profile == "combined_frontend":
        extension = build_extension(
            _load(args.upstream),
            _load(args.frontend_contract),
            birth_times_us=load_birth_times(args.initial_global_state),
            terminate_after_pulse=args.terminate_after_pulse,
            overlay=(
                _load(args.accelerator_overlay_contract)
                if args.accelerator_overlay_contract is not None
                else None
            ),
        )
    output = formal.rstrip() + "\n\n" + pulse.strip() + "\n" + extension
    if args.arm8_global_field_contract is not None:
        arm8_contract = _load(args.arm8_global_field_contract)
        if (
            arm8_contract.get("role") != "rf_oatof_arm8_simion_solver_closure_contract"
            or arm8_contract.get("potential", {}).get("real_pa_field_blending_allowed") is not False
        ):
            raise ValueError("Arm-8 global field contract is not a no-blending closure authority")
        output += "\n-- BEGIN REAL-BEAM ARM8 GLOBAL THEORETICAL FIELD\n"
        output += full_domain_piecewise_field_lua(
            arm8_contract["potential"],
            prefix="sf_arm8",
            enable_expression=(
                "sf_arm8_global_field_enable~=0 and single_flight_pulse_is_on()"
            ),
        )
        output += "\n-- END REAL-BEAM ARM8 GLOBAL THEORETICAL FIELD\n"
    if output.count("simion.workbench_program()") != 1:
        raise ValueError("combined single-flight Program must declare one workbench")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8", newline="\n")
    metadata = {
        "schema_version": 1,
        "role": "rf_oatof_simion_single_flight_program_build",
        "formal_sha256": file_sha256(args.formal),
        "pulse_extension_sha256": file_sha256(args.pulse_extension),
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
        "arm8_global_field_contract_sha256": (
            file_sha256(args.arm8_global_field_contract)
            if args.arm8_global_field_contract is not None
            else None
        ),
        "clock_basis": "canonical_instrument_time_us",
        "frontend_program_profile": args.frontend_program_profile,
        "terminate_after_pulse": args.terminate_after_pulse,
        "global_segments": args.global_segments,
        "output_sha256": file_sha256(args.output),
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_PROGRAM=PASS OUTPUT={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
