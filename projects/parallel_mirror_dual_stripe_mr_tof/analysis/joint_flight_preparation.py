"""Compile a measured-source MR workbench and new field-build inputs, without Fly."""
from __future__ import annotations

import json
import math
import copy
import csv
from pathlib import Path
import re
import subprocess
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform

from common.contracts.frozen_inputs import freeze_file
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import (
    REPO, verified_reference,
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _lua(value: Any) -> str:
    """Serialize the finite generated workbench contract, never executable user text."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return json.dumps(value, allow_nan=False)
    if isinstance(value, list):
        return "{" + ",".join(_lua(item) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join("[" + _lua(key) + "]=" + _lua(item) for key, item in value.items()) + "}"
    raise TypeError(f"Unsupported workbench contract value {type(value).__name__}")


INTERFACE_AUDIT_LUA = r'''-- Read-only field queries; no workbench Fly, PA save, or Refine.
local offset=(arg[1]=='--') and 1 or 0
local r=assert(loadfile(assert(arg[1+offset])))()
if r.role=='mrtof_event_field_query' then
 local sample=assert(loadfile(r.adapter))()(r.joint_level,'raw_sample')
 local out=assert(io.open(r.output,'w'))
 out:write('sample_id,phi_v,ex_v_mm,ey_v_mm,ez_v_mm\n')
 for _,p in ipairs(r.points) do
  local values={sample(unpack(p.position_mm))}
  assert(#values==4,'complete actual scalar V/E required')
  out:write(p.sample_id)
  for _,value in ipairs(values) do
   assert(type(value)=='number' and value==value and math.abs(value)<math.huge,'nonfinite event field')
   out:write(string.format(',%.17g',value))
  end
  out:write('\n')
 end
 out:close()
 print('MRTOF_EVENT_FIELD_AUDIT=PASS samples='..#r.points)
 return
end
local c=assert(loadfile(r.config))()
local b=c.baseline
local waveforms=assert(loadfile(r.waveforms))()
local drive=assert(loadfile(r.drive))(waveforms)
local rf=assert(loadfile(r.kernel))().new{
 waveform='cosine',frequency_hz=b.electric.rf_frequency_hz,
 phase_rad=b.clock.rf_phase_rad,rf_amplitude_v=b.electric.rf_peak_to_peak_v/2,
 rf_scale=1,common_mode_scale=1,group_dc_v={0,0},rf_steps_per_period=c.numerics.rf_steps_per_period,
 electrodes={{electrode_id=1,electrode_group=1,polarity=1,common_mode_v=0}}}
-- Same explicit native voltage basis APIs as frozen probe_native_field.lua.
local pa=simion.pas:open(r.source_pa0)
for a,key in ipairs({'nx','ny','nz'}) do
 local expected=math.floor((c.native_projection.maximum_mm[a]-c.native_projection.origin_mm[a])/c.native_projection.grid_mm+0.5)+1
 assert(pa[key]==expected,'native source basis dimensions differ from frozen projection')
end
local sample=assert(loadfile(r.adapter))()(r.joint_level,'raw_sample')
local out=assert(io.open(r.output,'w'))
out:write('sample_id,source_phi_v,source_ex_local_v_mm,source_ey_local_v_mm,source_ez_local_v_mm,joint_phi_v,joint_ex_v_mm,joint_ey_v_mm,joint_ez_v_mm,source_elapsed_us,source_rf_differential_v')
for id=1,15 do out:write(',source_electrode_'..id..'_v') end
out:write('\n')
for _,p in ipairs(r.points) do
 local t=p.instrument_time_us-b.clock.epoch_us
 assert(t>=0,'source query precedes component epoch')
 local rf_value=rf.differential_at(p.instrument_time_us)
 local v=drive.voltages(c,t,rf_value)
 assert(#v==15,'source voltage basis must contain 15 electrodes')
 local q={}
 for a=1,3 do q[a]=(p.local_mm[a]-c.native_projection.origin_mm[a])/c.native_projection.grid_mm end
 for a,key in ipairs({'nx','ny','nz'}) do
  assert(math.floor(q[a])-1>=0 and math.ceil(q[a])+1<pa[key],'native source query lacks gradient halo')
 end
 assert(pa:inside_vc(unpack(q)),'native interface query outside source PA')
 local phi=pa:potential_vc(q[1],q[2],q[3],v)
 local ex,ey,ez=pa:field_vc(q[1],q[2],q[3],v)
 local j,jx,jy,jz=sample(unpack(p.position_mm))
 local values={phi,ex/c.native_projection.grid_mm,ey/c.native_projection.grid_mm,ez/c.native_projection.grid_mm,j,jx,jy,jz,t,rf_value}
 for id=1,15 do values[#values+1]=v[id] end
 for _,value in ipairs(values) do assert(type(value)=='number' and value==value and math.abs(value)<math.huge,'nonfinite interface field') end
 out:write(p.sample_id)
 for _,value in ipairs(values) do out:write(string.format(',%.17g',value)) end
 out:write('\n')
end
out:close()
print('MRTOF_INTERFACE_FIELD_AUDIT=PASS samples='..#r.points)
'''


def audit_field_coverage(points: list[dict], windows: list[dict]) -> dict:
    """Prove the actual first-match route and native gradient halo for every point."""
    winners = []
    for point in points:
        position = point["position_mm"]
        winner = next(((rank, window) for rank, window in enumerate(windows)
                       if all(lo <= x <= hi for x, (lo, hi) in zip(position, window["active_box_mm"]))), None)
        if winner is None or winner[1]["name"] != "ion_processor_local":
            raise ValueError("interface audit is not entirely routed through the IP fine field")
        rank, window = winner
        grid = window["grid"]
        for axis, x in enumerate(position):
            q = (x-grid["origin_mm"][axis])/grid["pitch_mm"][axis]
            if axis == 0:
                if grid["symmetry"] != "x" or grid["origin_mm"][0] != 0:
                    raise ValueError("IP fine audit requires its declared x symmetry")
                q = abs(q)
            if ((axis != 0 and math.floor(q)-1 < 0)
                    or math.ceil(q)+1 >= grid["dimensions"][axis]):
                raise ValueError("interface audit lacks the flight adapter gradient halo")
        winners.append(rank)
    if not winners or len(set(winners)) != 1:
        raise ValueError("interface audit requires one actual flight field route")
    return dict(first_match_rank_zero_based=winners[0], field_name="ion_processor_local",
                sample_count=len(points), active_box_and_gradient_halo_verified=True)


def prepare_interface_field_audit(*, source_run: Path, handoff: dict, source_directory: Path,
                                binding: dict, native: dict, runtime: Path, output: Path) -> dict:
    """Freeze source field authors and compile same-point, actual-clock queries."""
    model = _read(source_run / "inputs/resolved_model.json")
    local_to_mr = RigidTransform.from_contract(model["coordinate_transform"]).then(
        RigidTransform.from_contract(handoff["rigid_transform"]))
    inverse = local_to_mr.inverse()
    canonical = source_directory / "component_particle_state.csv"
    with canonical.open(encoding="utf-8-sig", newline="") as handle:
        states = list(csv.DictReader(handle))
    species = {(float(row["mass_amu"]), int(row["charge_state"])) for row in states}
    if len(species) != 1 or next(iter(species))[1] <= 0:
        raise ValueError("interface centroid energy ledger requires one positive-ion species")
    mass, charge = next(iter(species))
    points = []
    for row in states:
        points.append(dict(sample_id=str(int(row["particle_id"])),
                           instrument_time_us=float(row["instrument_time_us"]),
                           position_mm=[float(row[f"position_{axis}_mm"]) for axis in "xyz"],
                           velocity_m_s=[float(row[f"velocity_{axis}_m_s"]) for axis in "xyz"]))
    if not points:
        raise ValueError("no measured interface particles")
    centroid = dict(sample_id="centroid", instrument_time_us=sum(p["instrument_time_us"] for p in points)/len(points),
                    **{key: [sum(p[key][a] for p in points)/len(points) for a in range(3)]
                       for key in ("position_mm", "velocity_m_s")})
    for point in [*points, centroid]:
        point["local_mm"] = list(inverse.transform_position(FramedPosition(
            inverse.from_frame_id, point["position_mm"])).coordinates_mm)
        point["kinetic_energy_per_charge_ev"] = kinetic_energy_ev(mass, *point["velocity_m_s"])/charge
    points.append(centroid)
    coverage = audit_field_coverage(points, binding["refinement_windows"])
    level = native["refinement_windows"][coverage["first_match_rank_zero_based"]]
    manifest = _read(source_run / "run_manifest.json")
    records = {}
    for record in [*manifest.get("inputs", {}).values(), *manifest["outputs"]]:
        if not record.get("exists"):
            continue
        path = record_path(record, base_dir=source_run)
        if path in records and (records[path]["bytes"] != record["bytes"]
                or str(records[path]["sha256"]).upper() != str(record["sha256"]).upper()):
            raise ValueError("conflicting source interface manifest identity: " + str(path))
        records[path] = {**record, "path": str(path)}
    field_directory = (source_run / "simion").resolve()
    basis_records = records
    field_authority = {}
    declaration = model.get("native_field")
    if declaration is not None:
        if declaration.get("source_manifest") is None:
            if Path(declaration["directory"]).resolve() != field_directory:
                raise ValueError("fresh native field directory differs from source run")
        else:
            consumption_path = (source_run / "inputs/native_field_consumption.json").resolve()
            if consumption_path not in records:
                raise ValueError("native field consumption is not manifest-bound: " + str(consumption_path))
            consumption_record = records[consumption_path]
            verify_record("native field consumption", consumption_record)
            consumption = _read(consumption_path)
            if ({key: value for key, value in consumption.items() if key != "verification"} != declaration
                    or declaration.get("consumer_projection_id") != "ion_processor_native_field_v1"
                    or "RUN_MANIFEST_VERIFY=PASS" not in consumption.get("verification", "")
                    or "PROJECTION=ion_processor_native_field_v1" not in consumption.get("verification", "")):
                raise ValueError("native field consumption differs from resolved declaration or verified projection")
            field_manifest_path = Path(declaration["source_manifest"]).resolve()
            if field_manifest_path not in records:
                raise ValueError("native field source manifest is not bound by source run: " + str(field_manifest_path))
            field_manifest_record = records[field_manifest_path]
            if str(field_manifest_record["sha256"]).upper() != str(declaration["source_manifest_sha256"]).upper():
                raise ValueError("native field source manifest identity differs from consumption")
            verify_record("native field source manifest", field_manifest_record)
            field_manifest = _read(field_manifest_path)
            if (field_manifest.get("project") != "dual_pressure_rectilinear_ion_processor"
                    or field_manifest.get("status") not in {"success", "failed"}):
                raise ValueError("native field source must be an explicit terminal IP run")
            field_directory = Path(declaration["directory"]).resolve()
            if field_directory != field_manifest_path.parent / "simion":
                raise ValueError("native field directory differs from declared producer")
            basis_records = {}
            for record in field_manifest["outputs"]:
                path = record_path(record, base_dir=field_manifest_path.parent)
                if path in basis_records:
                    raise ValueError("native field producer repeats published PA identity: " + str(path))
                basis_records[path] = {**record, "path": str(path)}
            field_authority = dict(consumption=consumption_record, producer_manifest=field_manifest_record)
    audit = output / "interface_audit"
    audit.mkdir()
    frozen = {}
    for name in ("frozen_config.lua", "native_drive.lua", "simion_rf_drive.lua", "voltage_waveforms.lua"):
        original = source_run / "simion" / name
        if original.resolve() not in records:
            raise ValueError("source interface field control is not manifest-bound: " + name)
        verify_record("source interface field control", records[original.resolve()], base_dir=source_run)
        frozen[name] = freeze_file(original, audit / name)
    basis = []
    for index in range(16):
        path = field_directory / f"processor.pa{index}"
        if path not in basis_records or not basis_records[path].get("exists"):
            raise ValueError("source PA basis is not manifest-bound: " + str(path))
        record = basis_records[path]
        if declaration is not None and declaration.get("source_manifest") is not None:
            if (path not in records or records[path].get("bytes") != record.get("bytes")
                    or str(records[path].get("sha256")).upper() != str(record.get("sha256")).upper()):
                raise ValueError("consumed PA basis differs from declared producer: " + str(path))
        if not path.is_file() or path.stat().st_size != record["bytes"]:
            raise ValueError("source PA basis is missing or changed in size")
        basis.append(record)
    request = dict(schema_version=1, role="mrtof_interface_field_audit_request", points=points,
                   mass_amu=mass, charge_state=charge, local_to_mr=local_to_mr.to_contract(), coverage=coverage,
                   centroid_definition="mean_crossing_position_velocity_and_absolute_time__not_a_simultaneous_bunch",
                   joint_level=level, inputs=dict(source_manifest=freeze_file(source_run / "run_manifest.json", audit / "source_manifest.json"),
                       source_states=file_record(canonical), source_resolved_model=file_record(source_run / "inputs/resolved_model.json"),
                       source_controls=frozen, source_basis=basis, source_field_authority=field_authority,
                       joint_binding=file_record(output / "static_field_binding.json"),
                       joint_scalar_adapter=file_record(runtime / "mrtof_candidate.scalar_field_adapter.lua")),
                   source_basis_identity_check="sealed_manifest_identity_and_current_size__read_only_handles_during_query")
    _write(audit / "request.json", request)
    execution = dict(points=points, config=frozen["frozen_config.lua"]["path"], drive=frozen["native_drive.lua"]["path"],
                     kernel=frozen["simion_rf_drive.lua"]["path"], waveforms=frozen["voltage_waveforms.lua"]["path"], source_pa0=basis[0]["path"], joint_level=level,
                     adapter=str(runtime / "mrtof_candidate.scalar_field_adapter.lua"), output=str(audit / "raw_field_samples.csv"))
    (audit / "request.lua").write_text("return " + _lua(execution) + "\n", encoding="utf-8", newline="\n")
    (audit / "query.lua").write_text(INTERFACE_AUDIT_LUA, encoding="utf-8", newline="\n")
    return dict(request=file_record(audit / "request.json"), program=str(audit / "query.lua"),
                lua_request=str(audit / "request.lua"), raw_output=execution["output"],
                guard_paths=[record["path"] for record in basis], report=str(audit / "interface_energy_field_audit.json"))


def summarize_interface_field_audit(directory: Path) -> dict:
    """Report gauge-separated potential/field residuals and centroid energy bookkeeping."""
    request = _read(directory / "request.json")
    transform = RigidTransform.from_contract(request["local_to_mr"])
    with (directory / "raw_field_samples.csv").open(encoding="utf-8-sig", newline="") as handle:
        raw = list(csv.DictReader(handle))
    if [row["sample_id"] for row in raw] != [p["sample_id"] for p in request["points"]]:
        raise ValueError("interface field sample IDs/order do not close")
    rows = []
    for point, sample in zip(request["points"], raw):
        values = {key: float(value) for key, value in sample.items() if key != "sample_id"}
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("nonfinite interface audit values")
        source_field = transform.transform_vector(FramedVector(transform.from_frame_id,
            [values[f"source_e{axis}_local_v_mm"] for axis in "xyz"])).components
        delta = [values[f"joint_e{axis}_v_mm"]-source_field[a] for a, axis in enumerate("xyz")]
        phi, joint_phi = values["source_phi_v"], values["joint_phi_v"]
        k = point["kinetic_energy_per_charge_ev"]
        rows.append(dict(point, source_phi_v=phi, joint_phi_v=joint_phi, delta_phi_v=joint_phi-phi,
                         source_field_mr_v_mm=list(source_field), delta_field_v_mm=delta,
                         source_elapsed_us=values["source_elapsed_us"], source_rf_differential_v=values["source_rf_differential_v"],
                         source_electrode_voltages_v15=[values[f"source_electrode_{index}_v"] for index in range(1,16)],
                         source_k_over_q_plus_phi_v=k+phi, joint_k_over_q_plus_phi_v=k+joint_phi))
    particles, centroid = rows[:-1], rows[-1]
    offset = sum(row["delta_phi_v"] for row in particles)/len(particles)
    for row in rows:
        row["delta_phi_without_constant_v"] = row["delta_phi_v"]-offset
    result = dict(schema_version=1, role="mrtof_interface_energy_field_audit", status="reported",
                  energy_acceptance="not_declared", tolerance=None, physical_matching_qualified=False,
                  scope="same_registered_points_and_absolute_times__not_energy_conservation_or_joint_flight_qualification",
                  units=dict(position="mm",time="absolute_instrument_us",potential="V",field="V/mm",energy_per_charge="eV/q"),
                  particle_count=len(particles), inputs=dict(request=file_record(directory / "request.json"),
                    raw_samples=file_record(directory / "raw_field_samples.csv")), coverage=request["coverage"],
                  mean_delta_phi_constant_v=offset,
                  max_abs_delta_phi_without_constant_v=max(abs(row["delta_phi_without_constant_v"]) for row in particles),
                  max_delta_field_norm_v_mm=max(math.sqrt(sum(v*v for v in row["delta_field_v_mm"])) for row in particles),
                  centroid=dict(definition=request["centroid_definition"],
                    kinetic_energy_of_mean_velocity_ev_per_q=centroid["kinetic_energy_per_charge_ev"],
                    mean_particle_kinetic_energy_ev_per_q=sum(row["kinetic_energy_per_charge_ev"] for row in particles)/len(particles),
                    velocity_spread_energy_ev_per_q=sum(row["kinetic_energy_per_charge_ev"] for row in particles)/len(particles)-centroid["kinetic_energy_per_charge_ev"],
                    mean_source_k_over_q_plus_phi_v=sum(row["source_k_over_q_plus_phi_v"] for row in particles)/len(particles),
                    mean_joint_k_over_q_plus_phi_v=sum(row["joint_k_over_q_plus_phi_v"] for row in particles)/len(particles),
                    field_sample=centroid), samples=particles)
    _write(directory / "interface_energy_field_audit.json", result)
    return result


def prepare_event_field_audit(controller_projection: Path, candidate_binding: Path,
                              output_directory: Path) -> dict:
    """Compile actual electrostatic queries for a completed measured centroid probe.

    The caller runs each returned Lua job through the public SIMION preparation
    lease. This compiler and the reducer never launch SIMION or change a field.
    """
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding
    projection = _read(controller_projection)
    if projection.get("role") != "mrtof_measured_exit_centroid_controller_projection":
        raise ValueError("actual measured centroid controller projection required")
    for key, record in projection["inputs"].items():
        verify_record("event audit " + key, record)
    event_record = projection["outputs"]["probe_event_states"]
    verify_record("probe event states", event_record)
    preparation = _read(Path(projection["inputs"]["preparation"]["path"]))
    bound = preparation["field_binding"]
    verify_record("probe actual field binding", bound)
    candidate_record = file_record(candidate_binding)
    if any(candidate_record[key] != bound[key] for key in ("bytes", "sha256")):
        raise ValueError("event audit candidate differs from the actual probe field binding")
    verify_record("probe actual scalar adapter", preparation["field_consumer_adapter"])
    if preparation.get("source_mode") != "centroid_probe" or preparation["expected_particle_ids"] != [1]:
        raise ValueError("constructed N1 probe identity required")
    binding = load_binding(candidate_binding)
    if binding.get("mode") != "native_static_pa" or binding.get("response_terms"):
        raise ValueError("event audit requires actual materialized native scalar fields")
    with Path(event_record["path"]).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    keys = [*[f"{axis}_mm" for axis in "xyz"], *[f"v{axis}_mm_us" for axis in "xyz"]]
    events = [event for event in projection["observation"]["events"] if all(key in event for key in keys)]
    if len(rows) != len(events):
        raise ValueError("event CSV and actual observed 6D states differ")
    source = projection["materialization"]["source_center_state"]
    source_receipt = _read(Path(projection["inputs"]["source_receipt"]["path"]))
    if source_receipt.get("role") != "mrtof_measured_exit_centroid_probe_source":
        raise ValueError("constructed probe source receipt required")
    canonical = source_receipt["outputs"]["component_particle_state"]
    verify_record("probe canonical centroid",canonical)
    with Path(canonical["path"]).open(encoding="utf-8-sig",newline="") as handle:
        canonical_rows = list(csv.DictReader(handle))
    if len(canonical_rows) != 1:
        raise ValueError("canonical N1 centroid source required")
    actual_source = canonical_rows[0]
    if (int(actual_source["particle_id"]) != 1
            or any(float(actual_source[f"position_{axis}_mm"]) != source["position_mm"][a]
                or float(actual_source[f"velocity_{axis}_m_s"])/1000 != source["velocity_mm_per_us"][a]
                for a,axis in enumerate("xyz"))
            or any(float(actual_source[key]) != float(source[key]) for key in ("instrument_time_us","mass_amu","charge_state"))):
        raise ValueError("projection centroid differs from canonical source 6D/time/species")
    mass, charge = float(source["mass_amu"]), int(source["charge_state"])
    if mass <= 0 or charge <= 0:
        raise ValueError("event energy ledger requires a positive-ion species")
    points = [dict(sample_id="source_centroid", event="source_centroid",
        instrument_time_us=float(source["instrument_time_us"]), position_mm=list(source["position_mm"]),
        velocity_mm_per_us=list(source["velocity_mm_per_us"]),
        velocity_m_s=[float(actual_source[f"velocity_{axis}_m_s"]) for axis in "xyz"])]
    for index, (row, event) in enumerate(zip(rows, events), 1):
        if (row["event"] != event["kind"] or float(row["instrument_time_us"]) != event["t_us"]
                or any(float(row[key]) != event[key] for key in keys)):
            raise ValueError("event CSV and actual observed 6D states differ")
        points.append(dict(sample_id=f"event_{index:06d}", event=row["event"],
            instrument_time_us=float(row["instrument_time_us"]),
            position_mm=[float(row[f"{a}_mm"]) for a in "xyz"],
            velocity_mm_per_us=[float(row[f"v{a}_mm_us"]) for a in "xyz"],
            velocity_m_s=[float(row[f"v{a}_mm_us"])*1000 for a in "xyz"]))
    levels = [*binding["refinement_windows"], binding]
    jobs: dict[int, dict] = {}
    for point in points:
        if not all(math.isfinite(v) for v in [point["instrument_time_us"], *point["position_mm"], *point["velocity_m_s"]]):
            raise ValueError("nonfinite actual event state")
        if point["instrument_time_us"] < points[0]["instrument_time_us"]:
            raise ValueError("observed event precedes canonical probe birth")
        selected = next(((rank, level) for rank, level in enumerate(levels[:-1])
            if all(lo <= x <= hi for x, (lo, hi) in zip(point["position_mm"], level["active_box_mm"]))),
            (len(levels)-1, binding))
        rank, level = selected
        grid = level["grid"]
        for axis, x in enumerate(point["position_mm"]):
            q = (x-grid["origin_mm"][axis])/grid["pitch_mm"][axis]
            if axis == 0:
                if grid["symmetry"] != "x" or grid["origin_mm"][0] != 0:
                    raise ValueError("event audit requires declared native x symmetry")
                q = abs(q)
            if (axis != 0 and math.floor(q)-1 < 0) or math.ceil(q)+1 >= grid["dimensions"][axis]:
                raise ValueError("event field query lacks the actual native gradient halo")
        point["kinetic_energy_per_charge_ev"] = kinetic_energy_ev(mass,*point["velocity_m_s"])/charge
        point["field_rank_zero_based"] = rank
        point["field_name"] = level.get("name", "global_fallback")
        jobs.setdefault(rank,dict(level=level,points=[]))["points"].append(point)
    output_directory.mkdir(parents=True,exist_ok=False)
    inputs = dict(projection=freeze_file(controller_projection, output_directory / "controller_projection.json"),
        event_states=freeze_file(Path(event_record["path"]),output_directory / "probe_event_states.csv"),
        preparation=freeze_file(Path(projection["inputs"]["preparation"]["path"]),output_directory / "probe_preparation.json"),
        source_receipt=freeze_file(Path(projection["inputs"]["source_receipt"]["path"]),output_directory / "probe_source_receipt.json"),
        canonical_source=freeze_file(Path(canonical["path"]),output_directory / "probe_component_particle_state.csv"),
        flight_log=freeze_file(Path(projection["inputs"]["log"]["path"]),output_directory / "probe_flight.log"),
        candidate_binding=freeze_file(candidate_binding,output_directory / "candidate_binding.json"),
        audit_implementation=freeze_file(Path(__file__),output_directory / "joint_flight_preparation.py"),
        scalar_adapter=freeze_file(Path(preparation["field_consumer_adapter"]["path"]),output_directory / "scalar_field_adapter.lua"))
    (output_directory / "query.lua").write_text(INTERFACE_AUDIT_LUA,encoding="utf-8",newline="\n")
    compiled = []
    for rank, job in jobs.items():
        level = job["level"]
        grid = level["grid"]
        descriptor = dict(mode="native_static_pa",scalar_pa=level["sources"]["scalar_pa"],**grid)
        lua_path = output_directory / f"field_{rank:02d}.lua"
        raw = output_directory / f"field_{rank:02d}_samples.csv"
        lua_path.write_text("return " + _lua(dict(role="mrtof_event_field_query",adapter=inputs["scalar_adapter"]["path"],
            joint_level=descriptor,points=job["points"],output=str(raw.resolve())))+"\n",encoding="utf-8",newline="\n")
        compiled.append(dict(rank_zero_based=rank,name=job["points"][0]["field_name"],
            scalar_field_identity=level["records"]["scalar_pa"], active_box_mm=level.get("active_box_mm"), grid=grid,
            point_ids=[point["sample_id"] for point in job["points"]], request=file_record(lua_path),
            program=str((output_directory / "query.lua").resolve()),raw_output=str(raw.resolve()),
            guard_path=descriptor["scalar_pa"]))
    request = dict(schema_version=1,role="mrtof_actual_probe_event_field_audit_request",inputs=inputs,
        points=points,jobs=compiled,mass_amu=mass,charge_state=charge,
        routing="actual_first_match_inclusive_windows_then_global_fallback__one_native_level_per_vendor_job",
        source_baseline="explicit_constructed_probe_canonical_birth__same_candidate_actual_phi__not_a_synthetic_flight_event",
        qualification="observed_N1_actual_electrostatic_potential_only_no_population_or_matching_qualification")
    _write(output_directory / "event_audit_request.json",request)
    return request


def summarize_event_field_audit(directory: Path) -> dict:
    """Join actual native V/E queries to original 6D states; never assume phi=0."""
    request = _read(directory / "event_audit_request.json")
    for key, record in request["inputs"].items():
        verify_record("event audit frozen " + key,record)
    samples = {}
    raw_records = []
    for job in request["jobs"]:
        verify_record("event audit query",job["request"])
        path = Path(job["raw_output"])
        with path.open(encoding="utf-8-sig",newline="") as handle:
            rows = list(csv.DictReader(handle))
        if [row["sample_id"] for row in rows] != job["point_ids"]:
            raise ValueError("actual field query IDs or routes do not close")
        for row in rows:
            if row["sample_id"] in samples:
                raise ValueError("duplicate actual field sample")
            values = {key:float(value) for key,value in row.items() if key != "sample_id"}
            if not all(math.isfinite(v) for v in values.values()):
                raise ValueError("nonfinite actual event phi/E")
            samples[row["sample_id"]] = values
        raw_records.append(file_record(path))
    if set(samples) != {point["sample_id"] for point in request["points"]}:
        raise ValueError("actual event field population does not close")
    ledger = [dict(point,**samples[point["sample_id"]],
        k_over_q_plus_phi_v=point["kinetic_energy_per_charge_ev"]+samples[point["sample_id"]]["phi_v"])
        for point in request["points"]]
    baseline = ledger[0]["k_over_q_plus_phi_v"]
    for row in ledger:
        row["delta_h_from_source_centroid_v"] = row["k_over_q_plus_phi_v"]-baseline
    result = dict(schema_version=1,role="mrtof_actual_probe_event_energy_field_audit",status="reported",
        energy_acceptance="not_declared",tolerance=None,physical_matching_qualified=False,
        potential_authority="actual_materialized_scalar_native_PA__scalar_adapter_raw_sample",
        energy_definition="H_over_q=K_over_q+actual_electrostatic_phi__not_effective_Psi",
        inputs=dict(request=file_record(directory / "event_audit_request.json"),raw_samples=raw_records),
        samples=ledger,source_centroid_h_over_q_v=baseline)
    _write(directory / "event_energy_field_audit.json",result)
    return result


def collision_workbench_layout(binding: dict[str, Any]) -> dict[str, Any]:
    """Project the loader-verified IP collision topology without changing fields."""
    roles = ["global_fallback", "native_corridor", "ion_processor_collision", "detector"]
    overlay = binding.get("collision_overlay")
    if overlay is not None:
        if (overlay.get("schema_version") != 1 or overlay.get("role") != "mrtof_analyzer_collision_overlay"
                or not binding.get("source_descriptor_path")):
            raise ValueError("Collision patch requires the verified overlay descriptor")
        roles.append("analyzer_collision_patch")
    if [item["role"] for item in binding["instances"]] != roles:
        raise ValueError("IP collision instances differ from the verified four/five-role topology")
    priority = dict(schema_version=1, role="mrtof_native_corridor_iob_priority_contract",
        accelerator_provider="dual_pressure_rectilinear_ion_processor",
        instances=[dict(role=role, priority_number=index) for index, role in enumerate(roles, 1)])
    if overlay is not None:
        priority["collision_overlay"] = dict(overlay, pa_path=binding["instances"][4]["pa_path"])
    return dict(roles=roles, priority=priority,
        seed=str(REPO / f"common/simion/assets/iob_instance_seeds/{len(roles)}_instance_seed.iob"))


def render_measured_operating_point(reference_path: Path, source_directory: Path, native_field: dict, *, numerics: dict[str, float],
                                    field_assets_verified: bool = False, source_identity_verified: bool = False) -> str:
    """Retain the MR core operating point, removing every OA launch-only field."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import PS_GROUPS

    voltages = native_field["analyzer_voltages_v"]
    # Finalization may bind a closed P/S candidate after the design was frozen.
    # The sealed field, rather than its historical sidecar, owns these settings.
    ps = {name: voltages[ids[0]-1] for name, ids in PS_GROUPS.items()}
    return (
        "-- Generated measured-state handoff; old OA fields are not consumed.\n"
        "local t=assert(loadfile(" + _lua(str(reference_path)) + "))()\n"
        "t.accelerator_provider='dual_pressure_rectilinear_ion_processor'\n"
        "t.measured_source_directory=" + _lua(str(source_directory)) + "\n"
        + "".join("t." + name + "=" + _lua(numerics[name]) + "\n"
                  for name in ("trajectory_quality", "maximum_step_us", "full_path_timeout_us")) +
        "t.field_assembly_verified=" + _lua(field_assets_verified) + ";t.measured_source_matches_workpoint=" + _lua(source_identity_verified) + "\n"
        "t.accelerator_voltages_v=nil;t.accelerator_ring_voltages_v=nil\n"
        "t.accelerator_exit_plane_project_z_mm=nil\n"
        "t.measured_source_match_scope='provider_configuration_identity_only'\n"
        "t.energy_target_acceptance='not_declared';t.six_dimensional_match_qualified=false;t.time_focus_qualified=false\n"
        "t.runtime_fast_adjust_enable=false;t.runtime_accelerator_field_gate_enable=false\n"
        "t.accelerator_pulse_mode='static';t.accelerator_safe_exit_only=false\n"
        "t.stripe_biases_v=" + _lua([ps["s1"], ps["s2"]]) + "\n"
        "t.prism_voltages_v=" + _lua([ps["p1"], ps["p2"]]) + "\n"
        "t.accelerator_pulse_off_time_us=nil;t.static_field=" + _lua(native_field) + "\nreturn t\n"
    )


def freeze_field_reference(reference_run: Path, inputs: Path, *, compiler_contract: dict[str, Any]) -> dict[str, Any]:
    """Bind only original field geometry/voltage/grid authors; never open old PA."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import resolve_trajectory_profile
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import resolve_drift_phase_contract
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import _full_path_timeout_us

    materialization_path = verified_reference(reference_run, "results/two_prism_trial_materialization.json")
    materialization_record = freeze_file(materialization_path, inputs / "reference_materialization.json")
    materialization = _read(Path(materialization_record["path"]))
    if materialization["inputs"]["contract_sha256"].upper() != compiler_contract["sha256"].upper():
        raise ValueError("MR materialization does not bind its compiler contract")
    contract = _read(Path(compiler_contract["path"]))
    profile = resolve_trajectory_profile(contract)
    if any(materialization["trajectory_profile"][name] != profile[name]
           for name in ("trajectory_quality", "maximum_step_us")):
        raise ValueError("MR materialization numerics differ from its reference trajectory profile")
    phase = resolve_drift_phase_contract(contract)
    if materialization["target_drift_period_ratio"] != phase.target_period_ratio:
        raise ValueError("MR materialization drift phase differs from its compiler contract")
    timeout = _full_path_timeout_us(contract, contract["particle_source"], phase.target_period_ratio)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("MR compiler contract must derive a positive finite full path timeout")
    binding_path = verified_reference(reference_run, "simion/static_field_binding.json")
    frozen = {"binding": freeze_file(binding_path, inputs / "reference_field_binding.json"),
              "reference_materialization": materialization_record,
              "numerics": dict(trajectory_quality=profile["trajectory_quality"],
                               maximum_step_us=profile["maximum_step_us"], full_path_timeout_us=timeout)}
    binding = _read(binding_path)
    operating = verified_reference(reference_run, "simion/mrtof_three_component_candidate.operating_point.lua")
    operating_record = freeze_file(operating, inputs / "reference_operating_point.lua")
    # This sealed generated sidecar has one explicit 20-slot static voltage
    # vector. Read that named vector, not a stale parent response's base values.
    matches = re.findall(r"\banalyzer_voltages_v\s*=\s*\{([^{}]+)\}", operating.read_text(encoding="utf-8-sig"))
    if len(matches) != 1:
        raise ValueError("reference sidecar must publish one explicit analyzer voltage vector")
    values = [float(token.strip()) for token in matches[0].split(",")]
    if len(values) != 20 or not all(math.isfinite(v) for v in values):
        raise ValueError("reference analyzer voltage projection requires 20 finite values")
    frozen["analyzer_electrode_voltages_v"] = values
    frozen["operating_point_authority"] = operating_record
    _write(inputs / "reference_operating_voltage_projection.json", {
        "schema_version": 1, "role": "mrtof_frozen_operating_voltage_projection",
        "source": operating_record, "field": "static_field.analyzer_voltages_v",
        "analyzer_electrode_voltages_v": values,
    })
    for key in ("geometry_authority", "voltage_authority", "numerical_plan"):
        source = Path(binding["parent"][key + "_path"])
        owner = Path(binding["parent"]["manifest"]).parent
        verified_reference(owner, source.relative_to(owner).as_posix())
        frozen[key] = freeze_file(source, inputs / ("field_" + key + ".json"))
    windows = []
    for index, window in enumerate(binding["refinement_windows"]):
        source = Path(window["numerical_plan_path"])
        owner = Path(window["manifest"]).parent
        verified_reference(owner, source.relative_to(owner).as_posix())
        record = freeze_file(source, inputs / f"field_window_{index}_plan.json")
        frozen_window = dict(name=window["name"], numerical_plan=record,
                             active_box_mm=window["active_box_mm"], grid=window["grid"])
        numerical = _read(source)
        if "full_solve_plan_path" in numerical:
            full = Path(numerical["full_solve_plan_path"])
            verified_reference(owner, full.relative_to(owner).as_posix())
            frozen_window["full_solve_numerical_plan"] = freeze_file(full, inputs / f"field_window_{index}_full_solve_plan.json")
        windows.append(frozen_window)
    frozen["refinement_windows"] = windows
    return frozen


def project_provider_voltages(source: dict, request: dict, inputs: Path, lua_executable: Path) -> dict:
    """Evaluate the sole provider Lua schedule with RF=0; no field or flight API."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import derive_lift_seed
    if lua_executable.name.lower() not in {"lua", "lua.exe"} or not lua_executable.is_file():
        raise ValueError("an explicit plain Lua interpreter is required; no SIMION solver fallback")
    baseline, point = copy.deepcopy(source["baseline"]), copy.deepcopy(source["native_operating_point"])
    point["lift_v"] = derive_lift_seed(source, request)
    baseline["electric"]["lift_v"] = point["lift_v"]
    dependency = _read(inputs / "accelerator_dependency.json")
    schedule_source = (REPO / dependency["provider_voltage_schedule"]).resolve()
    if schedule_source != (REPO / "projects/dual_pressure_rectilinear_ion_processor/simion/native_drive.lua").resolve():
        raise ValueError("provider voltage schedule must belong to the selected IP component")
    schedule = freeze_file(schedule_source,
                           inputs / "provider_native_drive.lua")
    waveforms_source = (REPO / dependency["provider_voltage_waveforms"]).resolve()
    if waveforms_source != (REPO / "common/simion/voltage_waveforms.lua").resolve():
        raise ValueError("provider voltage waveforms must be the declared common module")
    waveforms = freeze_file(waveforms_source, inputs / "provider_voltage_waveforms.lua")
    when = max(baseline["schedule"]["lift_end_us"], source["native_timing"]["pulse_start_us"])
    config = dict(baseline=baseline, native_operating_point=point, native_timing=source["native_timing"])
    program = inputs / "provider_voltage_evaluation.lua"
    program.write_text("local waveforms=assert(loadfile(" + _lua(waveforms["path"]) + "))()\n"
                       "local d=assert(loadfile(" + _lua(schedule["path"]) + "))(waveforms)\n"
                       "local v=d.voltages(" + _lua(config) + "," + _lua(when) + ",0)\n"
                       "local out={} for i=1,15 do out[i]=string.format('%.17g',assert(v[i])) end\n"
                       "assert(#v==15);print(table.concat(out,','))\n", encoding="utf-8", newline="\n")
    evaluation = subprocess.run([str(lua_executable), str(program)], cwd=REPO,
                                capture_output=True, text=True, timeout=30, check=True)
    values = [float(token) for token in evaluation.stdout.strip().split(",")]
    if len(values) != 15 or not all(math.isfinite(v) for v in values):
        raise ValueError("provider native schedule did not return 15 finite electrode voltages")
    result = dict(values_v15=values, source_native_drive=schedule, source_voltage_waveforms=waveforms, evaluation_time_us=when,
                  basis="post_extraction_pulse_held_rf_zero", evaluated_native_operating_point=point,
                  evaluated_baseline_lift_v=baseline["electric"]["lift_v"], plain_lua=file_record(lua_executable))
    _write(inputs / "provider_voltage_projection.json", result)
    return result
