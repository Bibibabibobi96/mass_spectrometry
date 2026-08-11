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


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _lua_number(value: float) -> str:
    return format(float(value), ".17g")


def load_birth_times(path: Path) -> list[float]:
    """Load contiguous per-particle instrument birth times in microseconds."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("single-flight initial state is empty")
    actual_ids = [int(row["particle_id"]) for row in rows]
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


def build_extension(
    upstream: dict[str, Any],
    frontend: dict[str, Any],
    *,
    birth_times_us: list[float] | None = None,
    clock_basis: str = "legacy_relative_time",
    terminate_after_pulse: bool = False,
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
    handoff_x = frontend["source_exit_center_mm"]["x"]
    if clock_basis not in {"legacy_relative_time", "absolute_birth_time"}:
        raise ValueError(f"unknown single-flight clock basis: {clock_basis}")
    if clock_basis == "absolute_birth_time" and not birth_times_us:
        raise ValueError("absolute birth clock requires per-particle birth times")
    lines = [
        "",
        "-- BEGIN RF-OATOF SINGLE-FLIGHT EXTENSION",
        "adjustable single_flight_enable=1",
        "adjustable sf_ideal_accel_enable=0",
        f"adjustable single_flight_rf_peak_v={_lua_number(drive['rf_amplitude_V_zero_to_peak_per_group'])}",
        f"adjustable single_flight_frequency_hz={_lua_number(drive['frequency_Hz'])}",
        "adjustable single_flight_rf_steps=160",
        "local single_flight_particle_id_offset=assert(tonumber(os.getenv('OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET') or '0'),'invalid single-flight particle ID offset')",
        f"local single_flight_frontend_origin_x={_lua_number(origin['x'])}",
        f"local single_flight_frontend_origin_y={_lua_number(origin['y'])}",
        f"local single_flight_frontend_origin_z={_lua_number(origin['z'])}",
        f"local single_flight_handoff_x={_lua_number(handoff_x)}",
        "local single_flight_base_initialize_run=segment.initialize_run",
        "local single_flight_base_initialize=segment.initialize",
        "local single_flight_base_tstep_adjust=segment.tstep_adjust",
        "local single_flight_base_efield_adjust=segment.efield_adjust",
        "local single_flight_base_other_actions=segment.other_actions",
        "local single_flight_previous={}",
        "local single_flight_handoff_reported={}",
        "local single_flight_birth_time_us={",
    ]
    if birth_times_us:
        for particle_id, value in enumerate(birth_times_us, start=1):
            lines.append(f"  [{particle_id}]={_lua_number(value)},")
    lines.extend([
        "}",
        f"local single_flight_absolute_birth_clock={1 if clock_basis == 'absolute_birth_time' else 0}",
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
            "  if single_flight_absolute_birth_clock==0 then return ion_time_of_flight end",
            "  local global_particle_id=ion_number+single_flight_particle_id_offset",
            "  local birth=single_flight_birth_time_us[global_particle_id]",
            "  assert(birth~=nil,'absolute single-flight clock is missing particle birth time')",
            "  return birth+ion_time_of_flight",
            "end",
            "handoff_instrument_time_us=single_flight_instrument_time_us",
            "local function single_flight_pulse_is_on()",
            "  local instrument_time_us=single_flight_instrument_time_us()",
            "  return handoff_pulse_mode==0 or (handoff_pulse_mode==1 and",
            "    instrument_time_us>=handoff_pulse_time_us and",
            "    instrument_time_us<handoff_pulse_time_us+handoff_pulse_width_us)",
            "end",
            "local function single_flight_set_frontend_voltages()",
            "  local instrument_time_us=single_flight_instrument_time_us()",
            "  local rf=single_flight_rf_peak_v*math.cos(single_flight_omega*instrument_time_us)",
            "  for id,item in pairs(single_flight_rods) do adj_elect[id]=item.dc+item.sign*rf end",
            "  adj_elect[9]=0",
            "  local pulse_on=single_flight_pulse_is_on()",
            "  adj_elect[10]=pulse_on and V_repeller or handoff_pulse_pre_all_v",
            "  adj_elect[11]=pulse_on and V_grid1 or handoff_pulse_pre_all_v",
            "  adj_elect[12]=pulse_on and V_grid1*5/6 or handoff_pulse_pre_all_v",
            "  adj_elect[13]=pulse_on and V_grid1*4/6 or handoff_pulse_pre_all_v",
            "  adj_elect[14]=pulse_on and V_grid1*3/6 or handoff_pulse_pre_all_v",
            "  adj_elect[15]=pulse_on and V_grid1*2/6 or handoff_pulse_pre_all_v",
            "  adj_elect[16]=pulse_on and V_grid1*1/6 or handoff_pulse_pre_all_v",
            "  adj_elect[17]=0",
            f"  adj_elect[18]={_lua_number(entrance_reference_v)}",
            f"  adj_elect[19]={_lua_number(entrance_plate_v)}",
            "end",
            "function segment.initialize_run()",
            "  single_flight_base_initialize_run()",
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
            "  single_flight_previous={}; single_flight_handoff_reported={}; single_flight_prepulse_reported={}",
            "  if trajectory_log_enable~=0 then",
            "    print(string.format('TRACE: single_flight_contract frontend_origin=(%.12g,%.12g,%.12g) handoff_x=%.12g rf_peak_v=%.12g frequency_hz=%.12g',ai.x,ai.y,ai.z,single_flight_handoff_x,single_flight_rf_peak_v,single_flight_frequency_hz))",
            "  end",
            "end",
            "function segment.fast_adjust()",
            "  if ion_instance==3 then single_flight_set_frontend_voltages() end",
            "end",
            "function segment.initialize()",
            "  single_flight_base_initialize()",
            "  local instrument_time_us=single_flight_instrument_time_us()",
            "  single_flight_previous[ion_number]={t=instrument_time_us,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm}",
            "  if trajectory_log_enable~=0 then",
            "    print(string.format('TRACE: source_release ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,instrument_time_us,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))",
            "  end",
            "end",
            "function segment.tstep_adjust()",
            "  single_flight_base_tstep_adjust()",
            "  if ion_instance==3 then",
            "    local rf_step=1e6/single_flight_frequency_hz/single_flight_rf_steps",
            "    if ion_time_step>rf_step then ion_time_step=rf_step end",
            "  end",
            "end",
            "function segment.efield_adjust()",
            "  single_flight_base_efield_adjust()",
            "  if sf_ideal_accel_enable==0 or ion_instance~=3 or",
            "      not single_flight_pulse_is_on() then return end",
            "  if math.abs(ion_px_mm-accelerator_axis_x_mm)>accelerator_bore_half_mm or",
            "      math.abs(ion_py_mm-accelerator_axis_y_mm)>accelerator_bore_half_mm then return end",
            "  local z,E=ion_pz_mm,nil",
            "  if z>=accelerator_repeller_front_z_mm and z<accelerator_grid1_z_mm then",
            "    E=(V_repeller-V_grid1)/(accelerator_grid1_z_mm-accelerator_repeller_front_z_mm)",
            "  elseif z>=accelerator_grid1_z_mm and z<accelerator_grid2_z_mm then",
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
            "  single_flight_previous[ion_number]={t=instrument_time_us,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm}",
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
    parser.add_argument("--oatof", required=True, type=Path)
    parser.add_argument("--initial-global-state", type=Path)
    parser.add_argument("--terminate-after-pulse", action="store_true")
    parser.add_argument(
        "--frontend-program-profile",
        default="combined_frontend",
        choices=("combined_frontend", "formal_accelerator"),
    )
    parser.add_argument(
        "--clock-basis",
        default="legacy_relative_time",
        choices=("legacy_relative_time", "absolute_birth_time"),
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    oatof = _load(args.oatof)
    formal = bind_oatof_adjustables(
        args.formal.read_text(encoding="utf-8-sig"), oatof
    )
    pulse = args.pulse_extension.read_text(encoding="utf-8-sig")
    if formal.count("simion.workbench_program()") != 1 or "segment.fast_adjust" not in pulse:
        raise ValueError("frozen oaTOF Program inputs differ from the expected contract")
    extension = ""
    if args.frontend_program_profile == "combined_frontend":
        extension = build_extension(
            _load(args.upstream),
            _load(args.frontend_contract),
            birth_times_us=(
                load_birth_times(args.initial_global_state)
                if args.initial_global_state is not None
                else None
            ),
            clock_basis=args.clock_basis,
            terminate_after_pulse=args.terminate_after_pulse,
        )
    output = formal.rstrip() + "\n\n" + pulse.strip() + "\n" + extension
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
        "oatof_sha256": file_sha256(args.oatof),
        "initial_global_state_sha256": (
            file_sha256(args.initial_global_state)
            if args.initial_global_state is not None
            else None
        ),
        "clock_basis": args.clock_basis,
        "frontend_program_profile": args.frontend_program_profile,
        "terminate_after_pulse": args.terminate_after_pulse,
        "output_sha256": file_sha256(args.output),
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_PROGRAM=PASS OUTPUT={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
