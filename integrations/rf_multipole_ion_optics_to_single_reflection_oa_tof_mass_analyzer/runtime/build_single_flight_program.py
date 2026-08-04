"""Build the continuous SIMION Program from frozen oaTOF and multipole contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
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


def build_extension(
    upstream: dict[str, Any], frontend: dict[str, Any]
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
    origin = frontend["instance_origin_mm"]
    handoff_x = frontend["source_exit_center_mm"]["x"]
    lines = [
        "",
        "-- BEGIN RF-OATOF SINGLE-FLIGHT EXTENSION",
        "adjustable single_flight_enable=1",
        f"adjustable single_flight_rf_peak_v={_lua_number(drive['rf_amplitude_V_zero_to_peak_per_group'])}",
        f"adjustable single_flight_frequency_hz={_lua_number(drive['frequency_Hz'])}",
        "adjustable single_flight_rf_steps=160",
        f"local single_flight_frontend_origin_x={_lua_number(origin['x'])}",
        f"local single_flight_frontend_origin_y={_lua_number(origin['y'])}",
        f"local single_flight_frontend_origin_z={_lua_number(origin['z'])}",
        f"local single_flight_handoff_x={_lua_number(handoff_x)}",
        "local single_flight_base_initialize_run=segment.initialize_run",
        "local single_flight_base_initialize=segment.initialize",
        "local single_flight_base_tstep_adjust=segment.tstep_adjust",
        "local single_flight_base_other_actions=segment.other_actions",
        "local single_flight_previous={}",
        "local single_flight_handoff_reported={}",
        "local single_flight_omega=single_flight_frequency_hz*1e-6*2*math.pi",
        "local single_flight_rods={",
    ]
    for electrode_id in range(1, 9):
        item = unique[electrode_id]
        sign = 1 if int(item["electrode_group"]) == 1 else -1
        lines.append(
            f"  [{electrode_id}]={{dc={_lua_number(potentials[electrode_id])},sign={sign}}},"
        )
    lines.extend(
        [
            "}",
            "local function single_flight_set_frontend_voltages()",
            "  local rf=single_flight_rf_peak_v*math.cos(single_flight_omega*ion_time_of_flight)",
            "  for id,item in pairs(single_flight_rods) do adj_elect[id]=item.dc+item.sign*rf end",
            "  adj_elect[9]=0",
            "  local pulse_on=handoff_pulse_mode==0 or (handoff_pulse_mode==1 and",
            "    ion_time_of_flight>=handoff_pulse_time_us and",
            "    ion_time_of_flight<handoff_pulse_time_us+handoff_pulse_width_us)",
            "  adj_elect[10]=pulse_on and V_repeller or handoff_pulse_pre_all_v",
            "  adj_elect[11]=pulse_on and V_grid1 or handoff_pulse_pre_all_v",
            "  adj_elect[12]=pulse_on and V_grid1*5/6 or handoff_pulse_pre_all_v",
            "  adj_elect[13]=pulse_on and V_grid1*4/6 or handoff_pulse_pre_all_v",
            "  adj_elect[14]=pulse_on and V_grid1*3/6 or handoff_pulse_pre_all_v",
            "  adj_elect[15]=pulse_on and V_grid1*2/6 or handoff_pulse_pre_all_v",
            "  adj_elect[16]=pulse_on and V_grid1*1/6 or handoff_pulse_pre_all_v",
            "  adj_elect[17]=0",
            f"  adj_elect[18]={_lua_number(entrance_reference_v)}",
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
            "  single_flight_previous[ion_number]={t=ion_time_of_flight,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm}",
            "  if trajectory_log_enable~=0 then",
            "    print(string.format('TRACE: source_release ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,ion_time_of_flight,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))",
            "  end",
            "end",
            "function segment.tstep_adjust()",
            "  single_flight_base_tstep_adjust()",
            "  if ion_instance==3 then",
            "    local rf_step=1e6/single_flight_frequency_hz/single_flight_rf_steps",
            "    if ion_time_step>rf_step then ion_time_step=rf_step end",
            "  end",
            "end",
            "function segment.other_actions()",
            "  single_flight_base_other_actions()",
            "  local p=single_flight_previous[ion_number]",
            "  if p and not single_flight_prepulse_reported[ion_number] and p.t<handoff_pulse_time_us and ion_time_of_flight>=handoff_pulse_time_us then",
            "    local f=(handoff_pulse_time_us-p.t)/(ion_time_of_flight-p.t)",
            "    local xc=p.x+f*(ion_px_mm-p.x); local yc=p.y+f*(ion_py_mm-p.y); local zc=p.z+f*(ion_pz_mm-p.z)",
            "    single_flight_prepulse_reported[ion_number]=true",
            "    if trajectory_log_enable~=0 then",
            "      print(string.format('TRACE: pre_pulse_state ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,handoff_pulse_time_us,xc,yc,zc,ion_vx_mm,ion_vy_mm,ion_vz_mm))",
            "    end",
            "  end",
            "  if p and not single_flight_handoff_reported[ion_number] and p.x<single_flight_handoff_x and ion_px_mm>=single_flight_handoff_x and ion_vx_mm>0 then",
            "    local f=(single_flight_handoff_x-p.x)/(ion_px_mm-p.x)",
            "    local tc=p.t+f*(ion_time_of_flight-p.t)",
            "    local yc=p.y+f*(ion_py_mm-p.y); local zc=p.z+f*(ion_pz_mm-p.z)",
            "    single_flight_handoff_reported[ion_number]=true",
            "    if trajectory_log_enable~=0 then",
            "      print(string.format('TRACE: single_flight_handoff ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',ion_number,tc,single_flight_handoff_x,yc,zc,ion_vx_mm,ion_vy_mm,ion_vz_mm))",
            "    end",
            "  end",
            "  single_flight_previous[ion_number]={t=ion_time_of_flight,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm}",
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
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    formal = args.formal.read_text(encoding="utf-8-sig")
    pulse = args.pulse_extension.read_text(encoding="utf-8-sig")
    if formal.count("simion.workbench_program()") != 1 or "segment.fast_adjust" not in pulse:
        raise ValueError("frozen oaTOF Program inputs differ from the expected contract")
    extension = build_extension(_load(args.upstream), _load(args.frontend_contract))
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
        "output_sha256": file_sha256(args.output),
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_PROGRAM=PASS OUTPUT={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
