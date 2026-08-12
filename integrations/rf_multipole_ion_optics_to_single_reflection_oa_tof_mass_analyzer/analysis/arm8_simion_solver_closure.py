"""Prepare and verify the independent SIMION Arm-8 one-dimensional closure.

This path deliberately does not reuse the real-beam counterfactual masks.  It
freezes one continuous, piecewise-linear potential over the complete analytic
path and a deterministic subset of the 1001-point analytic source authority.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    ATOMIC_MASS_CONSTANT_KG,
    ELEMENTARY_CHARGE_C,
    accelerator_state,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import (
    solve_coupled_reflectron_fields,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.verify_axial_ideal_closure import (
    segment_times_s,
)


ROLE = "rf_oatof_arm8_simion_solver_closure_contract"
ACCELERATOR_INSTANCE_MAPPINGS = {
    3: {"role": "frontend_accelerator", "rotation_deg": [0.0, 0.0, 0.0], "local_derivative_axis": "z", "global_z_sign": 1},
    5: {"role": "accelerator_overlay", "rotation_deg": [0.0, 0.0, 0.0], "local_derivative_axis": "z", "global_z_sign": 1},
}
LONGITUDINAL_EVENTS = (
    "grid1_forward",
    "grid2_forward",
    "focus_forward",
    "reflectron_entrance_forward",
    "reflectron_midgrid_forward",
    "turning_point",
    "reflectron_midgrid_return",
    "reflectron_exit_return",
    "theoretical_return_focus_plane",
)
EVENTS = (*LONGITUDINAL_EVENTS, "mechanical_detector_crossing")
CHECKPOINT_RE = re.compile(
    r"TRACE: arm8_solver_checkpoint ion=(?P<ion>\d+) analytic_id=(?P<aid>\d+) "
    r"event=(?P<event>\w+) t_us=(?P<t>[-+0-9.eE]+) "
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) "
    r"z_mm=(?P<z>[-+0-9.eE]+) vx_mm_us=(?P<vx>[-+0-9.eE]+) "
    r"vy_mm_us=(?P<vy>[-+0-9.eE]+) vz_mm_us=(?P<vz>[-+0-9.eE]+) "
    r"kinetic_energy_eV=(?P<ke>[-+0-9.eE]+)"
)
DETECTOR_RE = re.compile(
    r"TRACE: detector_crossing ion=(?P<ion>\d+) t=(?P<t>[-+0-9.eE]+) "
    r"x=(?P<x>[-+0-9.eE]+) y=(?P<y>[-+0-9.eE]+) "
    r"z=(?P<z>[-+0-9.eE]+)"
)
CLOCK_RE = re.compile(
    r"TRACE: arm8_analytic_clock ion=(?P<ion>\d+) analytic_id=(?P<aid>\d+) "
    r"birth_time_us=(?P<birth>[-+0-9.eE]+) "
    r"pulse_effective_time_us=(?P<pulse>[-+0-9.eE]+) fallback_allowed=0"
)


def transverse_speed_m_per_s(energy_ev: float, mass_amu: float) -> float:
    """Return the nonrelativistic speed for the frozen Fly2 injection energy."""

    return float(
        np.sqrt(2.0 * energy_ev * ELEMENTARY_CHARGE_C / (mass_amu * ATOMIC_MASS_CONSTANT_KG))
    )


def piecewise_potential_v(
    z_mm: float,
    planes: Mapping[str, float],
    fields: Mapping[str, float],
    boundary_potentials: Mapping[str, float],
) -> float:
    """Evaluate the declared continuous one-dimensional Arm-8 potential."""

    if planes["repeller"] <= z_mm <= planes["grid1"]:
        return boundary_potentials["repeller"] - fields["accelerator_stage1"] * (
            z_mm - planes["repeller"]
        )
    if planes["grid1"] <= z_mm <= planes["grid2"]:
        return boundary_potentials["grid1"] - fields["accelerator_stage2"] * (
            z_mm - planes["grid1"]
        )
    if planes["grid2"] <= z_mm <= planes["entrance"]:
        return boundary_potentials["grid2"]
    if planes["entrance"] <= z_mm <= planes["midgrid"]:
        return boundary_potentials["entrance"] + fields["reflectron_stage1"] * (
            z_mm - planes["entrance"]
        )
    if planes["midgrid"] <= z_mm <= planes["backplate"]:
        return boundary_potentials["midgrid"] + fields["reflectron_stage2"] * (
            z_mm - planes["midgrid"]
        )
    raise ValueError("z lies outside the declared Arm-8 potential domain")


def full_domain_piecewise_field_lua(
    values: Mapping[str, Any], *, prefix: str, enable_expression: str
) -> str:
    """Render the Arm-8 full-domain field override for a SIMION Program.

    The same implementation is used by the axial solver-closure Program and by
    real-beam paired screening.  Callers supply only the activation expression;
    the frozen Arm-8 planes, fields, instance mappings, and no-blending behavior
    remain identical.
    """

    if not re.fullmatch(r"[a-z][a-z0-9_]*", prefix):
        raise ValueError("Arm-8 Lua prefix must be a lowercase identifier")
    if not enable_expression.strip():
        raise ValueError("Arm-8 Lua enable expression is required")
    p = values["planes_mm"]
    f = values["fields_V_per_mm"]
    return f"""
local {prefix}_repeller_z={p['repeller']:.17g}
local {prefix}_grid1_z={p['grid1']:.17g}
local {prefix}_grid2_z={p['grid2']:.17g}
local {prefix}_focus_z={p['focus']:.17g}
local {prefix}_entrance_z={p['entrance']:.17g}
local {prefix}_midgrid_z={p['midgrid']:.17g}
local {prefix}_backplate_z={p['backplate']:.17g}
local {prefix}_accel1_field={f['accelerator_stage1']:.17g}
local {prefix}_accel2_field={f['accelerator_stage2']:.17g}
local {prefix}_refl1_field={f['reflectron_stage1']:.17g}
local {prefix}_refl2_field={f['reflectron_stage2']:.17g}
local {prefix}_base_efield_adjust=segment.efield_adjust
function segment.efield_adjust()
  if not ({enable_expression}) then return {prefix}_base_efield_adjust() end
  local z=ion_pz_mm; local E=0
  if z>={prefix}_repeller_z and z<{prefix}_grid1_z then E={prefix}_accel1_field
  elseif z>={prefix}_grid1_z and z<{prefix}_grid2_z then E={prefix}_accel2_field
  elseif z>={prefix}_grid2_z and z<{prefix}_entrance_z then E=0
  elseif z>={prefix}_entrance_z and z<{prefix}_midgrid_z then E=-{prefix}_refl1_field
  elseif z>={prefix}_midgrid_z and z<={prefix}_backplate_z then E=-{prefix}_refl2_field
  else error('Arm8 particle escaped the declared full-domain piecewise potential') end
  ion_dvoltsx_gu=0; ion_dvoltsy_gu=0; ion_dvoltsz_gu=0
  local pi=simion.wb.instances[ion_instance]
  if z>={prefix}_entrance_z then
    assert(ion_instance==2, 'Arm8 reflectron field requires rotated reflectron instance 2')
    ion_dvoltsx_gu=-E*pi.pa.dx_mm*pi.scale
  elseif z<{prefix}_grid2_z then
    assert(ion_instance==3 or ion_instance==5, 'Arm8 accelerator field requires global-z frontend instance 3 or overlay instance 5')
    ion_dvoltsz_gu=-E*pi.pa.dz_mm*pi.scale
  end
end
""".strip()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _authorities(receipt: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        receipt.get("receipt_role")
        != "axial_ideal_arm8_solver_independent_analytic_closure"
        or receipt.get("status") != "pass"
        or receipt.get("arm_id") != "axial_source_all_ideal"
        or not receipt.get("all_assertions_passed")
        or receipt.get("qualification", {}).get("solver_result") is not False
    ):
        raise ValueError("analytic Arm-8 receipt is not a passing solver-independent authority")
    contract_record = receipt["inputs"]["contract"]
    geometry_record = receipt["inputs"]["resolved_geometry"]
    contract_path = Path(contract_record["path"]).resolve()
    geometry_path = Path(geometry_record["path"]).resolve()
    if file_sha256(contract_path) != contract_record["sha256"]:
        raise ValueError("analytic Arm-8 contract SHA differs")
    if file_sha256(geometry_path) != geometry_record["sha256"]:
        raise ValueError("analytic Arm-8 geometry SHA differs")
    return _load(contract_path), _load(geometry_path)


def _selected_ids(authority_count: int, solver_count: int) -> list[int]:
    if solver_count == 1:
        return [(authority_count + 1) // 2]
    if solver_count < 3 or solver_count > authority_count:
        raise ValueError("solver sample count must be 1 or lie in [3, analytic sample count]")
    if (authority_count - 1) % (solver_count - 1):
        raise ValueError("solver subset must be an endpoint-preserving uniform analytic-ID stride")
    stride = (authority_count - 1) // (solver_count - 1)
    return list(range(1, authority_count + 1, stride))


def _physics(
    contract: Mapping[str, Any], geometry: Mapping[str, Any]
) -> tuple[Any, Any, dict[str, float]]:
    source = contract["source"]
    theory = contract["theory"]
    geom = geometry["geometry_mm"]
    electrodes = geometry["electrodes_V"]
    derivation = geometry["geometry_derivation"]["accelerator"]
    accelerator = accelerator_state(
        float(electrodes["repeller"]),
        float(electrodes["grid1"]),
        float(derivation["d1_mm"]),
        float(derivation["d2_mm"]),
        exit_v=float(electrodes["grid2"]),
    )
    reflectron = solve_coupled_reflectron_fields(
        accelerator,
        float(geom["L_stage1"]),
        float(geom["L_flight"]),
        float(geom["L_flight"]),
        energy_min_v=float(theory["energy_envelope_min_V"]),
        energy_max_v=float(theory["energy_envelope_max_V"]),
        stage2_margin_fraction=float(theory["reflectron_stage2_margin_fraction"]),
        stage2_margin_mm=float(theory["reflectron_stage2_margin_mm"]),
    )
    planes = {
        "repeller": float(geom["accelerator_repeller_z"]),
        "grid1": float(geom["accelerator_grid1_z"]),
        "grid2": float(geom["accelerator_grid2_z"]),
        "focus": float(geom["accelerator_focus_z"]),
        "entrance": float(geom["L_flight"]),
        "midgrid": float(geom["L_flight"]) + float(geom["L_stage1"]),
        "backplate": float(geom["L_flight"]) + float(geom["L_stage1"])
        + reflectron.required_stage2_depth_mm,
    }
    if float(source["initial_axial_velocity_m_per_s"]) != 0.0:
        raise ValueError("Arm-8 longitudinal closure requires initial vz=0")
    return accelerator, reflectron, planes


def _reference_rows(
    analytic_contract: Mapping[str, Any],
    axial_geometry: Mapping[str, Any],
    layout_geometry: Mapping[str, Any],
    ids: list[int],
) -> list[dict[str, Any]]:
    source = analytic_contract["source"]
    count = int(source["sample_count"])
    width = float(source["release_full_width_mm"])
    accelerator, reflectron, planes = _physics(analytic_contract, axial_geometry)
    all_release = np.linspace(
        accelerator.release_position_mm - width / 2.0,
        accelerator.release_position_mm + width / 2.0,
        count,
    )
    rows: list[dict[str, Any]] = []
    source_x = float(layout_geometry["coordinate_convention"]["accelerator_axis_x"])
    injection_energy_ev = float(
        layout_geometry["single_flight_layout_derivation"]["target_injection_energy_eV"]
    )
    vx_mm_us = transverse_speed_m_per_s(
        injection_energy_ev, float(source["mass_to_charge_Th"])
    ) / 1000.0
    for simulation_id, analytic_id in enumerate(ids, start=1):
        release = float(all_release[analytic_id - 1])
        segments = segment_times_s(
            release, accelerator, reflectron, float(source["mass_to_charge_Th"])
        )
        energy = accelerator.repeller_relative_v - accelerator.field1_v_per_mm * release
        turn_depth = (
            energy - reflectron.stage1_voltage_drop_v
        ) / reflectron.stage2_field_v_per_mm
        cumulative_us = np.cumsum(
            [
                segments["accelerator_stage1_s"],
                segments["accelerator_stage2_s"],
                segments["accelerator_exit_to_focus_s"],
                segments["focus_to_reflectron_entrance_s"],
                segments["reflectron_stage1_outbound_s"],
                segments["reflectron_stage2_outbound_to_turn_s"],
                segments["reflectron_stage2_return_s"],
                segments["reflectron_stage1_return_s"],
                segments["reflectron_exit_to_return_focus_s"],
            ]
        ) * 1.0e6
        z_values = (
            planes["grid1"], planes["grid2"], planes["focus"], planes["entrance"],
            planes["midgrid"], planes["midgrid"] + turn_depth,
            planes["midgrid"], planes["entrance"], planes["focus"],
        )
        for event, time_us, z_mm in zip(LONGITUDINAL_EVENTS, cumulative_us, z_values, strict=True):
            rows.append(
                {
                    "simulation_particle_id": simulation_id,
                    "analytic_particle_id": analytic_id,
                    "event": event,
                    "expected_pulse_effective_time_us": float(time_us),
                    "expected_z_mm": float(z_mm),
                    "expected_x_mm": source_x + vx_mm_us * float(time_us),
                    "expected_exit_energy_eV": energy if event in {"grid2_forward", "focus_forward"} else "",
                    "expected_turn_depth_mm": turn_depth if event == "turning_point" else "",
                }
            )
        rows.append(
            {
                **rows[-1],
                "event": "mechanical_detector_crossing",
            }
        )
    return rows


def _lua_program(formal: str, values: Mapping[str, Any]) -> str:
    stride = values["analytic_id_stride"]
    analytic_ids = values["analytic_particle_ids"]
    zero_clock_rows = "\n".join(f"  [{analytic_id}]=0," for analytic_id in analytic_ids)
    field_override = full_domain_piecewise_field_lua(
        values, prefix="arm8", enable_expression="arm8_solver_closure_enable~=0"
    )
    extension = f"""
-- BEGIN ARM8 FULL-DOMAIN PIECEWISE IDEAL SOLVER CLOSURE
adjustable arm8_solver_closure_enable=1
adjustable arm8_analytic_id_offset=0
{field_override}
local arm8_id_stride={stride}
local arm8_birth_time_us_by_analytic_id={{
{zero_clock_rows}
}}
local arm8_pulse_effective_time_us_by_analytic_id={{
{zero_clock_rows}
}}
local function arm8_analytic_id()
  return 1+arm8_analytic_id_offset+(ion_number-1)*arm8_id_stride
end
local arm8_base_initialize_run=segment.initialize_run
function segment.initialize_run()
  if arm8_solver_closure_enable~=0 then
    single_flight_absolute_birth_clock=0
  end
  arm8_base_initialize_run()
end
local arm8_base_initialize=segment.initialize
local arm8_previous={{}}; local arm8_phase={{}}
local function arm8_emit(event,t,x,y,z)
  local aid=arm8_analytic_id()
  print(string.format('TRACE: arm8_solver_checkpoint ion=%d analytic_id=%d event=%s t_us=%.15g x_mm=%.15g y_mm=%.15g z_mm=%.15g vx_mm_us=%.15g vy_mm_us=%.15g vz_mm_us=%.15g kinetic_energy_eV=%.15g',ion_number,aid,event,t or ion_time_of_flight,x or ion_px_mm,y or ion_py_mm,z or ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_ke))
end
local function arm8_emit_plane(event,plane,previous)
  local dz=ion_pz_mm-previous.z
  assert(dz~=0, 'Arm8 fixed-plane checkpoint requires a nonzero crossing step')
  local fraction=(plane-previous.z)/dz
  local t=previous.t+fraction*(ion_time_of_flight-previous.t)
  local x=previous.x+fraction*(ion_px_mm-previous.x)
  local y=previous.y+fraction*(ion_py_mm-previous.y)
  arm8_emit(event,t,x,y,plane)
end
function segment.initialize()
  if arm8_solver_closure_enable~=0 then
    local aid=arm8_analytic_id()
    local birth=arm8_birth_time_us_by_analytic_id[aid]
    local pulse=arm8_pulse_effective_time_us_by_analytic_id[aid]
    assert(birth~=nil, 'Arm8 analytic clock is missing particle birth time')
    assert(pulse~=nil, 'Arm8 analytic clock is missing pulse-effective time')
    assert(birth==0 and pulse==0, 'Arm8 analytic closure requires zero time origins')
    print(string.format('TRACE: arm8_analytic_clock ion=%d analytic_id=%d birth_time_us=%.15g pulse_effective_time_us=%.15g fallback_allowed=0',ion_number,aid,birth,pulse))
  end
  arm8_base_initialize(); arm8_phase[ion_number]=1
  arm8_previous[ion_number]={{t=ion_time_of_flight,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vz=ion_vz_mm}}
end
local arm8_base_other_actions=segment.other_actions
local arm8_base_tstep_adjust=segment.tstep_adjust
function segment.tstep_adjust()
  arm8_base_tstep_adjust()
  if arm8_solver_closure_enable==0 then return end
  local q=arm8_phase[ion_number]
  if q==3 and ion_vz_mm>0 and ion_pz_mm<arm8_focus_z then
    local dt=(arm8_focus_z-ion_pz_mm)/ion_vz_mm
    if dt>0 and ion_time_step>dt then ion_time_step=dt end
  end
end
function segment.other_actions()
  arm8_base_other_actions()
  if arm8_solver_closure_enable==0 then return end
  local n=ion_number; local q=arm8_phase[n]; local prev=arm8_previous[n]
  local names={{'grid1_forward','grid2_forward','focus_forward','reflectron_entrance_forward','reflectron_midgrid_forward'}}
  local planes={{arm8_grid1_z,arm8_grid2_z,arm8_focus_z,arm8_entrance_z,arm8_midgrid_z}}
  if q<=5 and prev.z<planes[q] and ion_pz_mm>=planes[q] and ion_vz_mm>0 then arm8_emit_plane(names[q],planes[q],prev); q=q+1
  elseif q==6 and prev.vz>0 and ion_vz_mm<=0 then arm8_emit('turning_point'); q=7
  elseif q==7 and prev.z>arm8_midgrid_z and ion_pz_mm<=arm8_midgrid_z and ion_vz_mm<0 then arm8_emit_plane('reflectron_midgrid_return',arm8_midgrid_z,prev); q=8
  elseif q==8 and prev.z>arm8_entrance_z and ion_pz_mm<=arm8_entrance_z and ion_vz_mm<0 then arm8_emit_plane('reflectron_exit_return',arm8_entrance_z,prev); q=9
  elseif q==9 and prev.z>arm8_focus_z and ion_pz_mm<=arm8_focus_z and ion_vz_mm<0 then arm8_emit_plane('theoretical_return_focus_plane',arm8_focus_z,prev); q=10 end
  arm8_phase[n]=q; arm8_previous[n]={{t=ion_time_of_flight,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vz=ion_vz_mm}}
end
-- END ARM8 FULL-DOMAIN PIECEWISE IDEAL SOLVER CLOSURE
"""
    return formal.rstrip() + "\n" + extension.lstrip()


def prepare(analytic_receipt_path: Path, layout_geometry_path: Path, formal_program: Path, output_dir: Path, solver_count: int) -> dict[str, Any]:
    receipt = _load(analytic_receipt_path)
    analytic_contract, axial_geometry = _authorities(receipt)
    geometry = _load(layout_geometry_path)
    layout = geometry.get("single_flight_layout_derivation", {})
    if (
        layout.get("layout_profile_id") != "symmetric_10ev_injection_diagnostic"
        or float(layout.get("target_injection_energy_eV", float("nan"))) != 10.0
    ):
        raise ValueError("Arm-8 detector closure requires symmetric_10ev_injection_diagnostic geometry")
    for key in ("accelerator_repeller_z", "accelerator_grid1_z", "accelerator_grid2_z", "accelerator_focus_z", "L_flight", "L_stage1"):
        if float(geometry["geometry_mm"][key]) != float(axial_geometry["geometry_mm"][key]):
            raise ValueError(f"layout geometry changes the frozen axial authority: {key}")
    authority_count = int(analytic_contract["source"]["sample_count"])
    ids = _selected_ids(authority_count, solver_count)
    accelerator, reflectron, planes = _physics(analytic_contract, axial_geometry)
    stride = ids[1] - ids[0] if len(ids) > 1 else 1
    analytic_id_offset = ids[0] - 1
    output_dir.mkdir(parents=True, exist_ok=True)
    values = {
        "planes_mm": planes,
        "fields_V_per_mm": {
            "accelerator_stage1": accelerator.field1_v_per_mm,
            "accelerator_stage2": accelerator.field2_v_per_mm,
            "drift": 0.0,
            "reflectron_stage1": reflectron.stage1_field_v_per_mm,
            "reflectron_stage2": reflectron.stage2_field_v_per_mm,
        },
        "analytic_id_stride": stride,
        "analytic_particle_ids": ids,
        "boundary_potentials_V": {
            "repeller": accelerator.repeller_relative_v,
            "grid1": accelerator.intermediate_relative_v,
            "grid2": 0.0,
            "entrance": 0.0,
            "midgrid": reflectron.stage1_voltage_drop_v,
            "backplate": reflectron.stage1_voltage_drop_v
            + reflectron.stage2_field_v_per_mm * reflectron.required_stage2_depth_mm,
        },
    }
    reference_rows = _reference_rows(analytic_contract, axial_geometry, geometry, ids)
    reference_path = output_dir / "arm8_expected_checkpoints.csv"
    with reference_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(reference_rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(reference_rows)
    source_state = output_dir / "arm8_source_state.csv"
    source_ion = output_dir / "arm8_source.ion"
    source_columns = ["simulation_particle_id", "analytic_particle_id", "pulse_effective_time_us", "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state"]
    # Recover release z from the analytic uniform grid rather than a solver outcome.
    all_release = np.linspace(
        planes["repeller"] + accelerator.release_position_mm - float(analytic_contract["source"]["release_full_width_mm"]) / 2,
        planes["repeller"] + accelerator.release_position_mm + float(analytic_contract["source"]["release_full_width_mm"]) / 2,
        authority_count,
    )
    injection_energy_ev = float(layout["target_injection_energy_eV"])
    vx_m_s = transverse_speed_m_per_s(
        injection_energy_ev, float(analytic_contract["source"]["mass_to_charge_Th"])
    )
    with source_state.open("w", encoding="utf-8", newline="") as state_handle, source_ion.open("w", encoding="utf-8", newline="") as ion_handle:
        writer = csv.DictWriter(state_handle, fieldnames=source_columns, lineterminator="\n"); writer.writeheader()
        ion_writer = csv.writer(ion_handle, lineterminator="\n")
        for simulation_id, analytic_id in enumerate(ids, start=1):
            z = float(all_release[analytic_id - 1])
            writer.writerow({"simulation_particle_id": simulation_id, "analytic_particle_id": analytic_id, "pulse_effective_time_us": 0, "x_mm": geometry["coordinate_convention"]["accelerator_axis_x"], "y_mm": 0, "z_mm": format(z, ".17g"), "vx_m_s": format(vx_m_s, ".17g"), "vy_m_s": 0, "vz_m_s": 0, "mass_amu": analytic_contract["source"]["mass_to_charge_Th"], "charge_state": 1})
            ion_writer.writerow([0, analytic_contract["source"]["mass_to_charge_Th"], 1, geometry["coordinate_convention"]["accelerator_axis_x"], 0, format(z, ".17g"), 0, 0, injection_energy_ev, 1, 3])
    program_path = output_dir / "arm8_full_domain_piecewise_ideal.lua"
    program_path.write_text(_lua_program(formal_program.read_text(encoding="utf-8-sig"), values), encoding="utf-8", newline="\n")
    return_times = np.asarray([float(row["expected_pulse_effective_time_us"]) for row in reference_rows if row["event"] == "theoretical_return_focus_plane"])
    peak = None
    if solver_count >= 3:
        peak, _ = compute_peak_metrics(
            return_times, float(analytic_contract["source"]["mass_to_charge_Th"])
        )
    source_x = float(geometry["coordinate_convention"]["accelerator_axis_x"])
    detector_x = float(geometry["coordinate_convention"]["detector_x"])
    detector_radius = float(geometry["geometry_mm"]["detector_radius"])
    predicted_detector_x = np.asarray(
        [float(row["expected_x_mm"]) for row in reference_rows if row["event"] == "mechanical_detector_crossing"]
    )
    predicted_detector_radius = np.abs(predicted_detector_x - detector_x)
    if np.any(predicted_detector_radius > detector_radius):
        raise ValueError("the frozen 10 eV +x transport misses the mechanical detector disk")
    result = {
        "schema_version": 1,
        "role": ROLE,
        "arm_id": "axial_source_all_ideal",
        "claim_scope": "simion_solver_closure_preparation_not_a_solver_result",
        "analytic_receipt": {"path": str(analytic_receipt_path.resolve()), "sha256": file_sha256(analytic_receipt_path)},
        "source": {"analytic_authority_count": authority_count, "solver_count": solver_count, "selection_rule": (f"analytic_center_id_{ids[0]}" if solver_count == 1 else f"analytic_ids_1_to_{authority_count}_inclusive_stride_{stride}"), "analytic_particle_ids": ids, "analytic_id_offset": analytic_id_offset, "mass_amu": float(analytic_contract["source"]["mass_to_charge_Th"]), "charge_state": 1, "transverse_injection_authority": "symmetric_10ev_injection_diagnostic_target_energy_plus_global_x", "transverse_energy_eV": injection_energy_ev, "vx_m_s": vx_m_s, "vy_m_s": 0.0, "vz_m_s": 0.0, "pulse_effective_time_us": 0.0},
        "clock": {
            "time_zero": "pulse_effective_time",
            "analytic_particle_ids": ids,
            "entries": [
                {
                    "analytic_particle_id": analytic_id,
                    "birth_time_us": 0.0,
                    "pulse_effective_time_us": 0.0,
                }
                for analytic_id in ids
            ],
            "fallback_allowed": False,
            "inherited_real_beam_absolute_birth_clock_used": False,
        },
        "layout_geometry": {"path": str(layout_geometry_path.resolve()), "sha256": file_sha256(layout_geometry_path), "layout_profile_id": layout["layout_profile_id"]},
        "closure_layers": {
            "longitudinal_solver_closure": {
                "status": "prepared",
                "terminal_event": "theoretical_return_focus_plane",
                "terminal_plane_z_mm": planes["focus"],
                "qualification": "one_dimensional_longitudinal_only_not_a_detector_hit",
            },
            "full_instrument_detector_closure": {
                "status": "prepared",
                "detector_event_authority": "formal_oatof_ideal_grounded_lua_detector_PA_splat",
                "source_axis_x_mm": source_x,
                "mechanical_detector_center_x_mm": detector_x,
                "mechanical_detector_radius_mm": detector_radius,
                "minimum_centerline_gap_to_active_disk_mm": abs(detector_x - source_x) - detector_radius,
                "declared_transverse_velocity_m_per_s": vx_m_s,
                "required_centerline_displacement_mm": detector_x - source_x,
                "predicted_x_mm_min": float(np.min(predicted_detector_x)),
                "predicted_x_mm_max": float(np.max(predicted_detector_x)),
                "predicted_radius_mm_max": float(np.max(predicted_detector_radius)),
                "preflight_assertion": "all declared z-grid particles intersect the mechanical detector disk",
            },
        },
        "potential": {**values, "instance_coordinate_mapping": {"accelerator": {"global_field_axis": "z", "accepted_workbench_instances": ACCELERATOR_INSTANCE_MAPPINGS, "evidence": "five-instance overlay builder freezes instance 5 az=el=rt=0 and scale=1; overlay contract bounds are expressed directly in oatof_global"}, "reflectron": {"workbench_instance": 2, "az_deg": -90.0, "global_field_axis": "z", "local_derivative_axis": "x"}, "flight_tube_and_detector": {"field": "zero_in_declared_ideal_model"}}, "coverage": ["accelerator_stage1", "accelerator_stage2", "field_free_drift_outbound_and_return", "reflectron_stage1_outbound_and_return", "reflectron_stage2_outbound_and_return"], "real_pa_field_blending_allowed": False, "continuity_residual_max_abs_V": 0.0},
        "expected_center": {"analytic_particle_id": (authority_count + 1) // 2, "exit_energy_eV": 2000.0, "turning_depth_mm": receipt["longitudinal_return_focus"]["center_turning_depth_in_stage2_mm"], "pulse_effective_tof_us": receipt["longitudinal_return_focus"]["center_segment_times_us"]["total_us"]},
        "expected_subset_peak": ({"particles": solver_count, "direct_fwhm_tof_ns": peak["direct_fwhm_tof_ns"], "mass_resolution": peak["mass_resolution"]} if peak is not None else {"particles": 1, "status": "not_applicable_single_particle_smoke"}),
        "files": {},
    }
    for name, path in {"source_state": source_state, "ion": source_ion, "expected_checkpoints": reference_path, "program": program_path}.items():
        result["files"][name] = {"path": path.name, "sha256": file_sha256(path)}
    contract_path = output_dir / "arm8_simion_solver_closure_contract.json"
    contract_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def verify_log(contract_path: Path, log_paths: list[Path], output_path: Path) -> dict[str, Any]:
    contract = _load(contract_path)
    if contract.get("role") != ROLE:
        raise ValueError("Arm-8 solver contract role differs")
    base = contract_path.parent
    expected_path = base / contract["files"]["expected_checkpoints"]["path"]
    if file_sha256(expected_path) != contract["files"]["expected_checkpoints"]["sha256"]:
        raise ValueError("Arm-8 expected checkpoint identity differs")
    with expected_path.open(encoding="utf-8-sig", newline="") as handle:
        expected = {(int(r["analytic_particle_id"]), r["event"]): r for r in csv.DictReader(handle)}
    observed: dict[tuple[int, str], dict[str, float]] = {}
    observed_sequences: dict[int, list[str]] = {}
    observed_clocks: dict[int, tuple[int, float, float]] = {}
    for path in log_paths:
        if not path.is_file():
            raise ValueError(f"Arm-8 solver log is missing: {path}")
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            clock = CLOCK_RE.search(line)
            if clock:
                analytic_id = int(clock["aid"])
                if analytic_id in observed_clocks:
                    raise ValueError(f"duplicate Arm-8 analytic clock: {analytic_id}")
                observed_clocks[analytic_id] = (
                    int(clock["ion"]),
                    float(clock["birth"]),
                    float(clock["pulse"]),
                )
                continue
            match = CHECKPOINT_RE.search(line)
            if match:
                key = (int(match["aid"]), match["event"])
                if key in observed:
                    raise ValueError(f"duplicate Arm-8 solver checkpoint: {key}")
                observed[key] = {
                    name: float(match[name])
                    for name in ("t", "x", "y", "z", "vx", "vy", "vz", "ke")
                }
                observed_sequences.setdefault(key[0], []).append(key[1])
                continue
            detector = DETECTOR_RE.search(line)
            if detector:
                ion_number = int(detector["ion"])
                analytic_id = 1 + int(contract["source"].get("analytic_id_offset", 0)) + (ion_number - 1) * int(
                    contract["potential"]["analytic_id_stride"]
                )
                detector_observation = {
                    "t": float(detector["t"]),
                    "x": float(detector["x"]),
                    "y": float(detector["y"]),
                    "z": float(detector["z"]),
                    "vx": float("nan"),
                    "vy": float("nan"),
                    "vz": float("nan"),
                    "ke": float("nan"),
                }
                sequence = observed_sequences.setdefault(analytic_id, [])
                return_key = (analytic_id, "theoretical_return_focus_plane")
                if return_key not in observed:
                    observed[return_key] = dict(detector_observation)
                    sequence.append(return_key[1])
                key = (analytic_id, "mechanical_detector_crossing")
                if key in observed:
                    raise ValueError(f"duplicate Arm-8 solver checkpoint: {key}")
                observed[key] = detector_observation
                sequence.append(key[1])
    clock_contract = contract["clock"]
    analytic_ids = [int(value) for value in contract["source"]["analytic_particle_ids"]]
    if clock_contract.get("fallback_allowed") is not False:
        raise ValueError("Arm-8 analytic clock fallback must be forbidden")
    if [int(value) for value in clock_contract["analytic_particle_ids"]] != analytic_ids:
        raise ValueError("Arm-8 analytic clock IDs differ from source IDs")
    if len(clock_contract["entries"]) != len(analytic_ids):
        raise ValueError("Arm-8 analytic clock length differs from source IDs")
    if set(observed_clocks) != set(analytic_ids):
        raise ValueError("Arm-8 analytic clock population differs")
    for simulation_id, analytic_id in enumerate(analytic_ids, start=1):
        ion_number, birth_time_us, pulse_effective_time_us = observed_clocks[analytic_id]
        if ion_number != simulation_id or birth_time_us != 0.0 or pulse_effective_time_us != 0.0:
            raise ValueError(f"Arm-8 analytic clock differs for analytic particle {analytic_id}")
    if set(observed) != set(expected):
        raise ValueError("Arm-8 solver checkpoint population differs")
    for analytic_id in contract["source"]["analytic_particle_ids"]:
        if observed_sequences.get(int(analytic_id)) != list(EVENTS):
            raise ValueError(f"Arm-8 solver event order differs for analytic particle {analytic_id}")
    time_errors_ns=[]; x_errors=[]; z_errors=[]; energy_errors=[]; turn_errors=[]
    return_times=[]
    for key, reference in expected.items():
        actual=observed[key]
        time_errors_ns.append(abs(actual["t"]-float(reference["expected_pulse_effective_time_us"]))*1000)
        x_errors.append(abs(actual["x"]-float(reference["expected_x_mm"])))
        z_errors.append(abs(actual["z"]-float(reference["expected_z_mm"])))
        if reference["expected_exit_energy_eV"]:
            transverse_energy_ev = (
                0.5
                * float(contract["source"]["mass_amu"])
                * ATOMIC_MASS_CONSTANT_KG
                * (actual["vx"] * 1000.0) ** 2
                / ELEMENTARY_CHARGE_C
            )
            energy_errors.append(
                abs(
                    actual["ke"]
                    - transverse_energy_ev
                    - float(reference["expected_exit_energy_eV"])
                )
            )
        if reference["expected_turn_depth_mm"]:
            turn_errors.append(abs((actual["z"]-contract["potential"]["planes_mm"]["midgrid"])-float(reference["expected_turn_depth_mm"])))
        if key[1]=="theoretical_return_focus_plane": return_times.append(actual["t"])
    peak = None
    if len(return_times) >= 3:
        peak, _ = compute_peak_metrics(np.asarray(return_times), 100.0)
    tolerances={"time_ns":0.5,"position_mm":0.01,"energy_eV":0.1,"turn_depth_mm":0.01,"fwhm_ns":0.02}
    peak_passed = peak is None or abs(peak["direct_fwhm_tof_ns"]-contract["expected_subset_peak"]["direct_fwhm_tof_ns"])<=tolerances["fwhm_ns"]
    passed=(max(time_errors_ns)<=tolerances["time_ns"] and max(x_errors)<=tolerances["position_mm"] and max(z_errors)<=tolerances["position_mm"] and max(energy_errors)<=tolerances["energy_eV"] and max(turn_errors)<=tolerances["turn_depth_mm"] and peak_passed)
    result={"schema_version":1,"role":"rf_oatof_arm8_simion_solver_closure_result","status":"pass" if passed else "fail","arm_id":"axial_source_all_ideal","claim_scope":("simion_center_particle_smoke_not_a_resolution_result" if peak is None else "simion_longitudinal_and_mechanical_detector_solver_closure_not_formal_resolution_qualification"),"terminal_event":"theoretical_return_focus_plane","full_instrument_detector_closure_status":"pass" if passed else "fail","contract_sha256":file_sha256(contract_path),"particles":len(return_times),"events_per_particle":len(EVENTS),"maximum_errors":{"time_ns":max(time_errors_ns),"x_position_mm":max(x_errors),"z_position_mm":max(z_errors),"exit_energy_eV":max(energy_errors),"turn_depth_mm":max(turn_errors)},"pulse_effective_peak":peak,"tolerances":tolerances,"all_assertions_passed":passed,"formal_gate_passed":False}
    output_path.parent.mkdir(parents=True,exist_ok=True);output_path.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest="command",required=True)
    prep=sub.add_parser("prepare");prep.add_argument("--analytic-receipt",required=True,type=Path);prep.add_argument("--layout-geometry",required=True,type=Path);prep.add_argument("--formal-program",required=True,type=Path);prep.add_argument("--output-dir",required=True,type=Path);prep.add_argument("--solver-count",type=int,default=101)
    verify=sub.add_parser("verify-log");verify.add_argument("--contract",required=True,type=Path);verify.add_argument("--log",required=True,action="append",type=Path);verify.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.command=="prepare": prepare(args.analytic_receipt,args.layout_geometry,args.formal_program,args.output_dir,args.solver_count);return 0
    result=verify_log(args.contract,args.log,args.output);return 0 if result["all_assertions_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
