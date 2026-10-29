"""Materialize explicit OA pulse batches; the public owner schedules and protects them.

No PA payloads are read/copied, no vendor process starts, and no asset/cache
identity is created here. Every batch shares the selected original ordinary PA.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from common.analysis.particle_events import group_particle_events, iter_particle_event_fields
from common.contracts.file_identity import canonical_json_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.simion.native_completion import (parse_fly_completed_line, require_one_fly_completion,
    frontend_batch_completion_path, validate_frontend_batch_completion)
from common.simion.batch_continuation import WholeUnitReplayUnit, build_whole_unit_replay_plan
from common.simion.particle_batching import batch_plan_from_dispatch
from integrations.runtime.single_flight_source import (
    binary64_serialization_close, canonical_clock_lua, lua_value, render_restart_fly2, select_timed_pre_pulse_states,
)


COLUMNS = [
    "particle_id", "native_particle_index", "event", "instrument_time_us", "requested_time_us",
    "x_mm", "y_mm", "z_mm", "vx_m_per_s", "vy_m_per_s", "vz_m_per_s",
    "state_present", "solver_raw_status", "original_birth_time_us", "terminal_reason",
]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


_IOB_TASK = r'''-- One-slot OA container preparation/reopen only; no PA save or adjustment.
local s=dofile(assert(arg[1]));local mode=assert(arg[2])
assert(s.schema_version==1 and s.role=='paired_accelerator_pulse_iob_build','invalid OA IOB spec')
assert(mode=='build' or mode=='verify','unsupported OA IOB task')
local originals={}
for _,path in ipairs({s.program,s.fly2}) do
 local f=assert(io.open(path,'rb'));originals[path]=f:read('*a');f:close()
end
-- Numerical quality belongs to the frozen workbench Program callbacks. A
-- command-script global is neither the Program context nor a saved IOB fact.
local program=originals[s.program]
assert(tonumber(program:match('trajectory_quality%s*=%s*(%d+)%s*[,}]'))==s.trajectory_quality,
 'frozen OA Program trajectory quality differs')
assert(program:find('function callbacks.load() sim_trajectory_quality=cfg.trajectory_quality end',1,true) and
 program:find('segment.load=callbacks.load',1,true) and
 program:find('segment.initialize_run=callbacks.initialize_run',1,true),
 'frozen OA Program must apply quality on load and initialize_run')
if mode=='build' then
 simion.command('"'..s.seed_iob..'"')
 assert(#simion.wb.instances==1,'one-slot public seed required')
 local item=simion.wb.instances[1]
 item.pa.filename=s.field_pa;item.pa:load();item:_debug_update_size()
 item.x,item.y,item.z=s.origin.x,s.origin.y,s.origin.z
 item.az,item.el,item.rt,item.scale=0,0,0,1
 simion.wb:load_particles(s.fly2)
 local ok,err=pcall(function() simion.wb:save(s.iob) end)
 for path,data in pairs(originals) do local f=assert(io.open(path,'wb'));f:write(data);f:close() end
 assert(ok,err)
else
 simion.command('"'..s.iob..'"')
end
assert(#simion.wb.instances==1,'saved OA workbench instance count differs')
local item=simion.wb.instances[1]
local function key(path) return path:gsub('\\','/'):lower() end
assert(key(item.pa.path)==key(s.field_pa),'saved OA field path differs')
for _,name in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
 assert(item.pa[name]==s.grid[name],'saved OA grid differs: '..name)
end
assert(item.x==s.origin.x and item.y==s.origin.y and item.z==s.origin.z and
 item.az==0 and item.el==0 and item.rt==0 and item.scale==1,'saved OA pose differs')
for path,data in pairs(originals) do
 local f=assert(io.open(path,'rb'));local actual=f:read('*a');f:close()
 assert(actual==data,'IOB task altered prepared companion: '..path)
end
print('PAIRED_ACCELERATOR_PULSE_IOB_'..mode:upper()..'=PASS INSTANCES=1 FLY=False')
'''


def _program(config: dict, particle_ids: list[int], source_time: float, code_root: Path) -> str:
    project = code_root / "projects/single_reflection_oa_tof_mass_analyzer/simion"
    components = {
        "pulse_math": code_root / "common/simion/voltage_waveforms.lua",
        "pulse_hook": code_root / "integrations/runtime/single_flight_pulse_hook.lua",
        "oa_adapter": project / "paired_accelerator_pulse.lua",
    }
    embedded = "\n".join(f"local {name}=(function()\n{path.read_text(encoding='utf-8')}\nend)()"
                         for name, path in components.items())
    return f'''simion.workbench_program()
sim_segment_global=1
{embedded}
local single_flight_source_particle_id={lua_value(particle_ids)}
local single_flight_particle_id_offset=0
local single_flight_time_origin_us={lua_value([source_time]*len(particle_ids))}
{canonical_clock_lua()}
local cfg={lua_value(config)}
local columns={lua_value(COLUMNS)}
local function emit(row)
 local values={{}}
 for i,key in ipairs(columns) do
  local value=row[key]
  if value==nil then values[i]=''
  elseif type(value)=='number' then values[i]=string.format('%.17g',value)
  else values[i]=value end
 end
 print('PAIRED_ACCELERATOR_PULSE_ROW='..table.concat(values,','))
end
local pulse=pulse_hook.new{{canonical_clock=single_flight_instrument_time_us,voltage_waveforms=pulse_math,
 pulse_time_us=cfg.on_us,pulse_width_us=cfg.off_us-cfg.on_us,pulse_mode=function() return 1 end}}
local callbacks=oa_adapter.new(cfg,{{clock=single_flight_instrument_time_us,
 row_index=single_flight_source_row_index,particle_id=single_flight_canonical_particle_id,
 restore_velocity=single_flight_restore_source_velocity,pulse=pulse,waveforms=pulse_math,emit=emit}})
segment.load=callbacks.load
segment.initialize_run=callbacks.initialize_run
segment.initialize=callbacks.initialize
segment.efield_adjust=callbacks.efield_adjust
segment.tstep_adjust=callbacks.tstep_adjust
segment.other_actions=callbacks.other_actions
segment.terminate=callbacks.terminate
segment.terminate_run=callbacks.terminate_run
'''


def materialize_simion_batches(
    plan_path: Path, output_dir: Path, batches: list[list[int]], *,
    field_pa: Path, code_root: Path, seed_iob: Path, batch_indices: list[int] | None = None,
) -> list[dict]:
    """Write one Program/FLY2/IOB task per external explicit ID slice.

    IDs may be noncontiguous; no row is renumbered or resampled. Batches must
    be disjoint. The caller owns coverage with any reused completed batches.
    Source CSV and original recorded states are each read once for this call.
    """
    plan_path, code_root = plan_path.resolve(), code_root.resolve()
    plan = _read(plan_path)
    if plan.get("schema_version") != 1 or plan.get("role") != "paired_accelerator_pulse_plan":
        raise ValueError("current paired accelerator pulse plan required")
    static = _read(Path(plan["static_plan"]["path"]))
    publication = _read(Path(plan["input_records"]["simion_field_publication"]["path"]))
    baseline = (Path(publication["generation_directory"])/"paired_static_on.pa").resolve()
    if field_pa.resolve() != baseline:
        raise ValueError("SIMION pulse requires the selected original baseline ON PA")
    if any(value != 0 for value in plan["off_electrode_voltages_v"].values()):
        raise ValueError("single-field pulse requires zero OFF voltages")
    collection = _read(Path(plan["input_records"]["pre_pulse_collection"]["path"]))
    decision_record = plan["input_records"].get("pulse_decision")
    selection = select_timed_pre_pulse_states(collection, _read(Path(decision_record["path"])) if decision_record else None)
    if selection["selected_particle_ids"] != plan["selected_particle_ids"] or selection["pulse_time_us"] != plan["source_time_us"]:
        raise ValueError("frozen selected source or absolute state time differs")
    if (selection["mother_particle_ids"] != plan["original_mother_particle_ids"]
            or {str(key):value for key,value in selection["original_birth_times_us"].items()} != plan["original_birth_times_us"]
            or selection["clock_epoch_id"] != plan["clock_epoch_id"]):
        raise ValueError("original source mother, birth metadata or clock identity differs")
    recorded = {int(row["particle_id"]): row for row in selection["selected_rows"]}
    with Path(plan["source_csv"]["path"]).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if [int(row["particle_id"]) for row in rows] != plan["selected_particle_ids"]:
        raise ValueError("Cartesian source CSV order/identity differs")
    source = {int(row["particle_id"]):row for row in rows}
    for pid, row in source.items():
        state = recorded[pid]
        if float(row["mass_amu"]) != plan["mass_amu"] or int(row["charge_state"]) != plan["charge_state"]:
            raise ValueError("Cartesian source species differs from the frozen plan")
        for axis in "xyz":
            position, velocity = float(row[f"{axis}_mm"]), float(row[f"v{axis}_m_per_s"])
            if (not math.isfinite(position) or not math.isfinite(velocity)
                    or position != float(state[f"{axis}_mm"])
                    or velocity != float(state[f"v{axis}_mm_per_us"])*1000):
                raise ValueError("Cartesian source6D differs from the recorded state")
    flattened = [value for batch in batches for value in batch]
    if (not batches or any(not batch for batch in batches) or any(type(value) is not int for value in flattened)
            or len(set(flattened)) != len(flattened) or not set(flattened) <= set(source)):
        raise ValueError("external batches must contain disjoint known particle IDs")
    quality = plan["numerics"]["simion_trajectory_quality"]
    if type(quality) is not int or not 1 <= quality <= 500:
        raise ValueError("explicit SIMION trajectory quality must be an integer1..500")
    if plan["pulse"]["on_us"]+(plan["pulse"]["off_us"]-plan["pulse"]["on_us"]) != plan["pulse"]["off_us"]:
        raise ValueError("shared pulse hook cannot represent the exact declared OFF edge")
    grid = static["native_geometry_compilation"]["grid"]
    shape = dict(grid["dimensions"], **{axis+"_mm":value for axis,value in zip(("dx","dy","dz"),
                 (grid["cell_mm_xyz"][a] for a in "xyz"), strict=True)})
    output_dir = output_dir.resolve()
    tasks = []
    indices = list(range(1,len(batches)+1)) if batch_indices is None else batch_indices
    if len(indices)!=len(batches) or len(set(indices))!=len(indices) or any(type(i) is not int or i<1 for i in indices):
        raise ValueError("batch indices must be distinct positive integers")
    for index, ids in zip(indices,batches,strict=True):
        directory = output_dir/f"batch_{index:04d}"
        directory.mkdir(parents=True)
        paths = {name:(directory/name).resolve() for name in ("paired_pulse.lua","paired_pulse.fly2","paired_pulse.iob","build_iob.lua","build_spec.lua")}
        fly_rows = [dict(particle_id=str(pid),instrument_time_us=str(plan["source_time_us"]),
                        mass_amu=source[pid]["mass_amu"],charge_state=source[pid]["charge_state"],
                        **{f"position_{a}_mm":source[pid][f"{a}_mm"] for a in "xyz"},
                        **{f"velocity_{a}_m_s":source[pid][f"v{a}_m_per_s"] for a in "xyz"}) for pid in ids]
        velocities = [[float(recorded[pid][f"v{a}_mm_per_us"]) for a in "xyz"] for pid in ids]
        if any(not math.isfinite(v) for vector in velocities for v in vector):
            raise ValueError("nonfinite original source velocity")
        config = dict(field_pa=baseline.as_posix(),grid=shape,origin=grid["instance_origin_mm"],
                      trajectory_quality=quality,maximum_step_us=plan["numerics"]["maximum_step_us"],
                      source_time_us=plan["source_time_us"],on_us=plan["pulse"]["on_us"],off_us=plan["pulse"]["off_us"],
                      observation_times_us=plan["observation_times_us"],particle_count=len(ids),
                      velocities_mm_per_us=velocities,
                      birth_times_us=[selection["original_birth_times_us"][pid] for pid in ids])
        _write(paths["paired_pulse.lua"],_program(config,ids,plan["source_time_us"],code_root))
        _write(paths["paired_pulse.fly2"],render_restart_fly2(fly_rows))
        spec = dict(schema_version=1,role="paired_accelerator_pulse_iob_build",field_pa=baseline.as_posix(),
                    grid=shape,origin=grid["instance_origin_mm"],trajectory_quality=quality,seed_iob=seed_iob.resolve().as_posix(),
                    program=paths["paired_pulse.lua"].as_posix(),fly2=paths["paired_pulse.fly2"].as_posix(),iob=paths["paired_pulse.iob"].as_posix())
        _write(paths["build_spec.lua"],"return "+lua_value(spec)+"\n")
        _write(paths["build_iob.lua"],_IOB_TASK)
        tasks.append(dict(batch_index=index,particle_ids=ids,particle_count=len(ids),
                          paths={key:str(value) for key,value in paths.items()},
                          original_mother_particle_ids=plan["original_mother_particle_ids"],
                          original_birth_times_us=plan["original_birth_times_us"],
                          clock_epoch_id=plan["clock_epoch_id"],instrument_epoch_us=plan["instrument_epoch_us"],
                          source_time_us=plan["source_time_us"],field_pa=str(baseline)))
    return tasks


def _json_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if _read(path)!=value:
            raise ValueError(f"refuse to replace frozen preparation: {path}")
        return
    _write(path,json.dumps(value,indent=2,allow_nan=False)+"\n")


def _fingerprint(record: dict) -> dict:
    if (type(record.get("bytes")) is not int or record["bytes"]<0
            or not isinstance(record.get("sha256"),str) or len(record["sha256"])!=64):
        raise ValueError("frozen pulse record lacks complete byte identity")
    return {key:record[key] for key in ("bytes","sha256")}


def _source_identity(plan: dict) -> dict:
    keys=("schema_version","role","particle_count","mass_amu","charge_state","source_time_us",
          "pulse","observation_times_us","off_electrode_voltages_v","clock_epoch_id",
          "instrument_epoch_us","frame_id","source_instance_id","original_mother_particle_ids",
          "original_birth_times_us","uncontinued_mother_particle_ids","selected_particle_ids","selection_basis")
    return {**{key:plan[key] for key in keys},"source_csv":_fingerprint(plan["source_csv"])}


def _pulse_identity(plan: dict) -> dict:
    """The saved CPT model depends on its own field and solver controls."""
    return dict(source=_source_identity(plan),mass_kg=plan["mass_kg"],
                model=_fingerprint(plan["model"]),numerics={key:plan["numerics"][key] for key in (
                    "maximum_step_us","relative_tolerance","absolute_tolerance")})


def _simion_numerics(plan: dict) -> dict:
    return {key:plan["numerics"][key] for key in ("maximum_step_us","simion_trajectory_quality")}


def _simion_field_identity(plan: dict) -> dict:
    """Read the selected immutable member metadata, never the PA payload."""
    record=plan["input_records"]["simion_field_publication"]
    verify_record("pulse SIMION publication",record)
    publication=_read(Path(record["path"]))
    if publication.get("status")!="published" or publication.get("action_required")!="complete":
        raise ValueError("published SIMION field required")
    manifest=_read(Path(publication["generation_directory"])/"cache_manifest.json")
    members=[row for row in manifest["files"] if row["name"]=="paired_static_on.pa"]
    if len(members)!=1:
        raise ValueError("selected original SIMION member is not unique")
    return _fingerprint(members[0])


def materialize_comsol_task(plan_path: Path,output_dir: Path,code_root: Path,saved_particle_model: Path | None=None) -> dict:
    """Generate the canonical backend call; an explicit saved model only exports."""
    plan_path,output_dir,code_root=plan_path.resolve(),output_dir.resolve(),code_root.resolve()
    output_dir.mkdir(parents=True,exist_ok=True)
    quote=lambda p: "'"+Path(p).as_posix().replace("'","''")+"'"
    folder=code_root/"projects/single_reflection_oa_tof_mass_analyzer/comsol"
    args=[quote(plan_path),quote(output_dir)]
    if saved_particle_model is not None:
        args.append(quote(saved_particle_model.resolve()))
    task=output_dir/"run_paired_pulse.m"
    _write(task,"addpath("+quote(folder)+");\nrun_paired_accelerator_pulse("+",".join(args)+");\n")
    return dict(matlab=str(task),plan=str(plan_path),output_dir=str(output_dir),
                saved_particle_model=str(saved_particle_model.resolve()) if saved_particle_model is not None else None)


def _case_identity(plan: dict) -> str:
    return canonical_json_sha256(dict(physics=_source_identity(plan),simion_numerics=_simion_numerics(plan),simion_field=_simion_field_identity(plan)))


def _verify_case_records(case: dict,bound, *,verify: bool=True) -> list[dict]:
    controls=[]
    for declared in case["control_records"]:
        actual=bound(record_path(declared),verify=verify)
        if _fingerprint(actual)!=_fingerprint(declared):
            raise ValueError("saved pulse controls differ from published identity")
        controls.append(actual)
    if Path(case["iob_path"]).resolve() not in {record_path(r) for r in controls}:
        raise ValueError("completed pulse batch lacks its bound saved IOB")
    declared=case["iob_reopen_record"]
    reopened=bound(record_path(declared),verify=verify)
    if _fingerprint(reopened)!=_fingerprint(declared):
        raise ValueError("saved pulse independent reopen fact identity differs")
    with record_path(reopened).open(encoding="utf-8-sig") as stream:
        facts=[line for line in stream if line.startswith("PAIRED_ACCELERATOR_PULSE_IOB_VERIFY=PASS")]
    if len(facts)!=1:
        raise ValueError("one published independent IOB reopen fact required")
    return [*controls,reopened]


def _validated_particle_source(source: dict) -> tuple[dict | None,dict | None]:
    """Verify the explicitly carried original producer, never traverse history."""
    if source.get("schema_version")!=1 or source.get("role")!="paired_accelerator_pulse_particle_source":
        raise ValueError("invalid original particle source receipt")
    for key in ("producer_manifest","producer_plan","solution"):
        verify_record("original particle "+key,source[key])
    manifest_path=record_path(source["producer_manifest"])
    require_completed_terminal_publication(manifest_path)
    producer=_read(manifest_path)
    if producer.get("project")!="instrument_assembly" or producer.get("status") not in ("success","failed","interrupted"):
        raise ValueError("original particle producer is not terminal")
    records=[*producer["inputs"].values(),*producer["outputs"]]
    for key in ("producer_plan","solution","model"):
        declared=source[key]
        matches=[r for r in records if record_path(r,base_dir=manifest_path.parent)==record_path(declared)]
        if not matches or any(_fingerprint(r)!=_fingerprint(declared) for r in matches):
            raise ValueError("original particle source is not producer-bound")
    original=_read(record_path(source["producer_plan"]))
    solution=_read(record_path(source["solution"]))
    if (solution.get("role")!="paired_accelerator_pulse_solution" or solution.get("status")!="solved_saved"
            or solution.get("solution_tag")!="sol_pulse" or Path(solution["plan_path"]).resolve()!=record_path(source["producer_plan"])
            or Path(solution["model_path"]).resolve()!=record_path(source["model"]) or source["model"].get("exists") is not True):
        raise ValueError("original particle solution fact differs from its source")
    return original,source


def load_completed_pulse_stages(plan_path: Path,predecessor_manifest: Path,snapshot_manifest: Path) -> dict:
    """Read actual optional completed stages, without native payload hashing.

    Each source claim is validated against its own frozen plan first. A
    changed dependency invalidates only its consumer; damaged evidence fails.
    Partial units remain inputs to the existing common continuation planner.
    """
    predecessor_manifest=predecessor_manifest.resolve()
    require_completed_terminal_publication(predecessor_manifest)
    if _fingerprint(file_record(predecessor_manifest))!=_fingerprint(file_record(snapshot_manifest)):
        raise ValueError("pulse parent manifest snapshot identity differs")
    manifest=_read(snapshot_manifest);base=predecessor_manifest.parent
    if manifest.get("role")!="simulation_run_manifest" or manifest.get("project")!="instrument_assembly" or manifest.get("status") not in ("success","failed","interrupted"):
        raise ValueError("terminal instrument_assembly pulse producer required")
    records=[*manifest["inputs"].values(),*manifest["outputs"]];verified=set()
    def bound(path: Path, *,verify: bool=True,optional: bool=False) -> dict | None:
        path=path.resolve();matches=[r for r in records if record_path(r,base_dir=base)==path]
        if not matches:
            if optional:
                return None
            raise ValueError(f"pulse source record not manifest-bound: {path}")
        if any(_fingerprint(r)!=_fingerprint(matches[0]) for r in matches):
            raise ValueError("pulse source record identities conflict")
        if verify and path not in verified:
            verify_record(path.name,matches[0],base_dir=base);verified.add(path)
        return matches[0]
    def published_log(declared: dict) -> dict:
        """Project only a log's stale transport path through this producer."""
        actual=bound(record_path(declared),optional=True)
        if actual is None:
            candidates=[*manifest["outputs"],*(r for key,r in manifest["inputs"].items() if key.startswith("completed_parent_"))]
            matches={record_path(r,base_dir=base):r for r in candidates
                     if r.get("exists") is True and _fingerprint(r)==_fingerprint(declared)}
            if len(matches)!=1:
                raise ValueError("published pulse log identity must bind exactly one canonical output or borrowed log")
            actual=bound(next(iter(matches)))
        if _fingerprint(actual)!=_fingerprint(declared):
            raise ValueError("published pulse log identity differs")
        return actual
    def completion_fact(phase: str, case: dict, stdout: Path) -> dict | None:
        expected=frontend_batch_completion_path(base,phase,case['case_id'])
        matches={record_path(r,base_dir=base) for r in records
                 if record_path(r,base_dir=base).name==expected.name
                 and record_path(r,base_dir=base).parent.name==phase
                 and record_path(r,base_dir=base).parent.parent.name=='frontend_batch_completion'}
        if len(matches)>1:
            raise ValueError('pulse batch completion has ambiguous manifest bindings')
        if not matches:
            return None
        path=next(iter(matches));fact=bound(path)
        validate_frontend_batch_completion(path,phase=phase,case_id=case['case_id'],
            stdout=stdout,count=case['count'],row_range=case['source_row_range'])
        return fact
    plans=[r for r in manifest["inputs"].values() if Path(r["path"]).name=="paired_accelerator_pulse_plan.json" and record_path(r,base_dir=base).is_relative_to(base)]
    if len(plans)!=1:
        raise ValueError("one published predecessor pulse plan required")
    old_plan_record=bound(record_path(plans[0],base_dir=base));previous=_read(record_path(old_plan_record))
    current=_read(plan_path)
    for record in (previous["source_csv"],previous["static_plan"]):
        actual=bound(record_path(record,base_dir=base))
        if _fingerprint(actual)!=_fingerprint(record):
            raise ValueError("predecessor pulse source/static metadata identity differs")
    verify_record("current static plan",current["static_plan"])
    result=dict(particle_model=None,particle_solution_fact=None,particle_source=None,particle_exports=None,simion_baseline=None,simion_replay=None,
                simion_workbench=None,simion_dispatch=None,simion_field=None,
                manifest=dict(file_record(snapshot_manifest),source_path=str(predecessor_manifest)),plan=old_plan_record,partial_units=[],replay_partial_units=[])
    original_source=None
    solution_record=bound(base/"comsol/paired_pulse_solution.json",optional=True)
    if solution_record is not None:
        solution=_read(record_path(solution_record))
        if (solution.get("schema_version")!=1 or solution.get("role")!="paired_accelerator_pulse_solution"
                or solution.get("status")!="solved_saved" or solution.get("solution_tag")!="sol_pulse"
                or Path(solution["plan_path"]).resolve()!=record_path(old_plan_record)):
            raise ValueError("declared saved particle solution does not bind its original plan")
        model=bound(Path(solution["model_path"]),verify=False)
        if model.get("exists") is not True:
            raise ValueError("saved native particle model record is absent")
        original_source=dict(schema_version=1,role="paired_accelerator_pulse_particle_source",
            producer_manifest=file_record(predecessor_manifest),producer_plan=old_plan_record,solution=solution_record,model=model)
        if _pulse_identity(previous)==_pulse_identity(current):
            result.update(particle_model=model,particle_solution_fact=solution_record,particle_source=original_source)
    else:
        receipt_record=bound(base/"inputs/completed_pulse_stages.json",optional=True)
        if receipt_record is not None:
            source=_read(record_path(receipt_record)).get("particle_source")
            if source is not None:
                original,original_source=_validated_particle_source(source)
                if _pulse_identity(original)==_pulse_identity(current):
                    result.update(particle_model=source["model"],particle_solution_fact=source["solution"],particle_source=source)
    native_record=bound(base/"comsol/paired_pulse_native_facts.json",optional=True)
    if native_record is not None:
        facts=_read(record_path(native_record))
        export_plan_record=bound(Path(facts["plan_path"]))
        export_plan=_read(record_path(export_plan_record))
        actual_times=facts.get("actual_observation_times_us")
        expected_times=export_plan["observation_times_us"]
        if (facts.get("role")!="paired_accelerator_pulse_native_facts" or facts.get("initial_complete") is not True
                or facts.get("particle_count")!=export_plan["particle_count"]
                or facts.get("observation_count")!=len(export_plan["observation_times_us"])
                or not isinstance(actual_times,list) or len(actual_times)!=len(expected_times)
                or any(not binary64_serialization_close(actual,expected) for actual,expected in zip(actual_times,expected_times,strict=True))):
            raise ValueError("declared completed particle export fact is invalid")
        particles=bound(base/"comsol/paired_pulse_particles.csv")
        initial=bound(base/"comsol/paired_pulse_initial.csv")
        if original_source is None:
            raise ValueError("completed particle exports lack their original solution source")
        if Path(facts["model_path"]).resolve()!=record_path(original_source["model"]):
            raise ValueError("particle exports name a different actual model")
        elif _pulse_identity(export_plan)==_pulse_identity(current):
            result["particle_exports"]=dict(particles=particles,initial=initial,native_facts=native_record,plan=export_plan_record)
    baseline_record=bound(base/"results/simion_pulse_baseline.json",optional=True)
    workbench_record=bound(base/"results/pulse_workbench.json",optional=True)
    dispatch_record=bound(base/"results/pulse.dispatch_plan.json",optional=True)
    if baseline_record is None and workbench_record is None:
        for record in manifest["outputs"]:
            if Path(record["path"]).name!="case_metadata.json":
                continue
            case=_read(record_path(bound(record_path(record))))
            log=bound(Path(case["stdout"]),verify=False,optional=True)
            if log is not None:
                with record_path(log).open(encoding="utf-8-sig") as stream:
                    if any(parse_fly_completed_line(line) is not None for line in stream):
                        raise ValueError("completed formal unit lacks fixed complete workbench; do not repeat it")
        return result
    previous_field=_simion_field_identity(previous)
    publication=_read(Path(previous["input_records"]["simion_field_publication"]["path"]))
    field=dict(path=str((Path(publication["generation_directory"])/"paired_static_on.pa").resolve()),
               **previous_field,cache_key=publication["cache_key"],generation_directory=publication["generation_directory"])
    same_simion=(_source_identity(previous)==_source_identity(current) and _simion_numerics(previous)==_simion_numerics(current)
                 and previous_field==_simion_field_identity(current))
    if workbench_record is None or dispatch_record is None:
        raise ValueError("published pulse units require their workbench and fixed dispatch")
    workbench=_read(record_path(workbench_record))
    if workbench.get('coverage')=='initial_formal_batch_only':
        provisional=bound(base/'results/pulse.provisional_dispatch_plan.json')
        dispatch=_read(record_path(provisional))
    else:
        dispatch=_read(record_path(dispatch_record))
    batch_plan=batch_plan_from_dispatch(dispatch)
    recovered_dispatch=None
    if batch_plan.get("coverage","complete_population")!="complete_population":
        from common.simion.resource_scheduler import plan_recovered_formal_followup
        provisional=bound(base/'results/pulse.provisional_dispatch_plan.json')
        initial=_read(record_path(provisional))
        if len(workbench['batches'])!=1:
            raise ValueError('provisional pulse workbench must contain its single formal batch')
        first=workbench['batches'][0]
        receipt=frontend_batch_completion_path(base,'pulse',first['case_id'])
        bound(receipt)
        validate_frontend_batch_completion(receipt,phase='pulse',case_id=first['case_id'],
            stdout=Path(first['stdout']),count=first['count'],row_range=first['source_row_range'])
        recovered_dispatch=plan_recovered_formal_followup(initial,_read(receipt))
        batch_plan=batch_plan_from_dispatch(recovered_dispatch)
    if (batch_plan["particle_count"]!=previous["particle_count"] or
            (recovered_dispatch is None and len(workbench["batches"])!=batch_plan["batch_count"])):
        raise ValueError("published workbench differs from its fixed dispatch")
    for case,batch in zip(sorted(workbench["batches"],key=lambda c:c["index"]),batch_plan["batches"]):
        low,high=batch["particle_id_min"],batch["particle_id_max"]
        if (case["index"]!=batch["index"] or case["count"]!=batch["count"] or case["source_row_range"]!=[low,high]
                or case["expected_particle_ids"]!=previous["selected_particle_ids"][low-1:high]):
            raise ValueError("predecessor batch changed its original source-row identity")
    expected_identity=_case_identity(previous);complete_records=[]
    for case in workbench["batches"]:
        if case["input_identity"]!=expected_identity:
            raise ValueError("predecessor pulse case input identity differs")
        stdout=Path(case["stdout"]);log_record=bound(stdout,verify=False,optional=True)
        complete=False;artifacts=[]
        if log_record is not None:
            with stdout.open(encoding="utf-8-sig") as stream:
                lines=list(stream)
            if any(parse_fly_completed_line(line) is not None for line in lines):
                native=require_one_fly_completion(lines)
                marker=f"PAIRED_ACCELERATOR_PULSE_CALLBACKS_COMPLETE particles={case['count']}"
                if native.splats!=case["count"] or sum(line.strip()==marker for line in lines)!=1:
                    raise ValueError("declared completed native pulse batch has invalid census")
                fact=completion_fact('pulse',case,stdout)
                if fact is not None:
                    artifacts=[bound(stdout),*_verify_case_records(case,bound),fact];complete=True
        if complete:
            complete_records.extend(artifacts)
        result["partial_units"].append(dict(key=case["case_id"],is_complete=complete,
            terminal_outputs=[str(record_path(r)) for r in artifacts] if complete else [str(stdout)]))
    if same_simion:
        result.update(simion_workbench=workbench_record,simion_dispatch=dispatch_record,simion_field=field)
        if recovered_dispatch is not None:
            result['recovered_dispatch']=recovered_dispatch
            for batch in batch_plan['batches'][1:]:
                low,high=batch['particle_id_min'],batch['particle_id_max']
                key=f"batch_{batch['index']:04d}__rows_{low:06d}_{high:06d}"
                result['partial_units'].append(dict(key=key,is_complete=False,terminal_outputs=[str(base/'logs'/f'{key}.missing')]))
        for case in workbench['batches']:
            stdout=Path(case.get('default_replay_stdout',base/'logs'/f"{case['case_id']}.replay.stdout.log"))
            log=bound(stdout,verify=False,optional=True)
            fact=completion_fact('pulse_replay',case,stdout) if log is not None else None
            complete=False;artifacts=[]
            if fact is not None:
                with stdout.open(encoding='utf-8-sig') as stream:
                    lines=list(stream)
                native=require_one_fly_completion(lines)
                marker=f"PAIRED_ACCELERATOR_PULSE_CALLBACKS_COMPLETE particles={case['count']}"
                if native.splats!=case['count'] or sum(line.strip()==marker for line in lines)!=1:
                    raise ValueError('declared completed pulse replay has invalid census')
                artifacts=[bound(stdout),fact,*_verify_case_records(case,bound)];complete=True
            result['replay_partial_units'].append(dict(key=case['case_id'],is_complete=complete,
                terminal_outputs=[str(record_path(r)) for r in artifacts] if complete else [str(stdout)]))
    if baseline_record is not None:
        baseline=_read(record_path(baseline_record))
        if (baseline.get("role")!="paired_accelerator_pulse_simion_collection" or baseline.get("native_complete") is not True
                or baseline.get("phase")!="baseline" or baseline.get("particle_ids")!=previous["selected_particle_ids"]
                or baseline.get("physical_identity")!=_source_identity(previous) or baseline.get("simion_field_identity")!=previous_field
                or baseline.get("simion_numerics")!=_simion_numerics(previous)):
            raise ValueError("declared complete SIMION baseline evidence is invalid")
        sample_record=bound(record_path(baseline["samples"]))
        if _fingerprint(sample_record)!=_fingerprint(baseline["samples"]):
            raise ValueError("SIMION baseline result identity differs")
        baseline_logs=[published_log(record) for record in baseline["logs"]]
        if same_simion and all(unit["is_complete"] for unit in result["partial_units"]):
            result["simion_baseline"]=dict(collection=baseline_record,samples=sample_record,logs=baseline_logs,
                workbench=workbench_record,dispatch=dispatch_record,field=field,control_records=complete_records)
    replay_record=bound(base/"results/simion_pulse_replay_comparison.json",optional=True)
    if replay_record is not None:
        replay=_read(record_path(replay_record))
        if (baseline_record is None or replay.get("role")!="paired_accelerator_pulse_saved_default_comparison" or replay.get("passed") is not True
                or replay.get("differences")!=[] or replay.get("physical_identity")!=_source_identity(previous)
                or replay.get("simion_field_identity")!=previous_field or replay.get("simion_numerics")!=_simion_numerics(previous)):
            raise ValueError("published SIMION replay completion evidence is invalid")
        replay_samples=bound(record_path(replay["replay_samples"]))
        if _fingerprint(replay_samples)!=_fingerprint(replay["replay_samples"]):
            raise ValueError("SIMION replay result identity differs")
        replay_logs=[published_log(record) for record in replay["logs"]]
        replay_facts=[]
        for case in workbench['batches']:
            fact=completion_fact('pulse_replay',case,Path(case['default_replay_stdout']))
            if fact is None:
                break
            replay_facts.append(fact)
        if same_simion and result['simion_baseline'] is not None and len(replay_facts)==len(workbench['batches']):
            result["simion_replay"]=dict(comparison=replay_record,samples=replay_samples,logs=replay_logs,completion_facts=replay_facts)
    return result


def plan_simion_replay_continuation(stages: dict, run: Path) -> dict | None:
    """Reuse only manifest-bound complete replay units from the fixed predecessor."""
    rows=stages.get('replay_partial_units',[])
    if not rows or not any(row['is_complete'] for row in rows):
        return None
    parent=Path(stages['manifest']['source_path']).parent
    directory=run.resolve()/'inputs/pulse_replay_continuation'
    units=[WholeUnitReplayUnit(row['key'],tuple(Path(p) for p in row['terminal_outputs']),row['is_complete']) for row in rows]
    plan=build_whole_unit_replay_plan(predecessor_run_dir=parent,output_dir=directory,units=units)
    return dict(plan=plan,plan_record=file_record(directory/'simion_whole_unit_replay_plan.json'))


def prepare_dispatch_request(run: Path,plan_path: Path,code_root: Path,field_pa: Path) -> dict:
    """Bind a request for the existing public scheduler/profile mechanism."""
    run,code_root=run.resolve(),code_root.resolve()
    plan=_read(plan_path);static=_read(Path(plan["static_plan"]["path"]))
    publication=_read(Path(plan["input_records"]["simion_field_publication"]["path"]))
    generation=Path(publication["generation_directory"])
    if field_pa.resolve()!=(generation/"paired_static_on.pa").resolve():
        raise ValueError("dispatch field differs from frozen original ON field")
    members=[r for r in _read(generation/"cache_manifest.json")["files"] if r["name"]=="paired_static_on.pa"]
    if len(members)!=1:
        raise ValueError("original standalone field metadata is ambiguous")
    code={name:_fingerprint(file_record(code_root/name)) for name in (
        "integrations/workflows/paired_accelerator_pulse/runtime.py","integrations/runtime/single_flight_source.py",
        "integrations/runtime/single_flight_pulse_hook.lua","common/simion/voltage_waveforms.lua",
        "projects/single_reflection_oa_tof_mass_analyzer/simion/paired_accelerator_pulse.lua")}
    request=dict(solver="SIMION",field_kind="electrostatic",independent_particles=True,
                 particle_count=plan["particle_count"],trajectory_quality=plan["numerics"]["simion_trajectory_quality"],
                 frontend_cell_mm_xyz=static["native_geometry_compilation"]["grid"]["cell_mm_xyz"],
                 frontend_pa0_sha256=members[0]["sha256"],workload_topology_id="paired_oa_one_ordinary_on_pa_v1",
                 field_loading_policy_id="readonly_on_pa_direct_off_zero_v1",
                 case_input_sha256=canonical_json_sha256(dict(physics=_source_identity(plan),simion_numerics=_simion_numerics(plan),code=code)))
    path=run/"inputs/pulse_dispatch_request.json";_json_once(path,request)
    return dict(dispatch_request_path=str(path),particle_count=plan["particle_count"],request=request)


def materialize_batches(run: Path,plan_path: Path,dispatch: dict, *,code_root: Path,field_pa: Path,seed_iob: Path,
                        materialize_case_ids: set[str] | None=None) -> dict:
    """Map public source-row intervals to original IDs; reuse existing controls."""
    run=run.resolve();plan=_read(plan_path)
    batch_plan=batch_plan_from_dispatch(dispatch) if dispatch.get("role")=="simion_repository_dispatch_plan" else dispatch
    if (batch_plan.get("role")!="simion_single_wave_particle_batch_plan" or batch_plan.get("particle_count")!=plan["particle_count"]
            or batch_plan.get("batch_count")!=len(batch_plan["batches"])):
        raise ValueError("public dispatch population differs from the frozen source")
    identity=_case_identity(plan);cases=[];seen=[];missing=[]
    for index,batch in enumerate(batch_plan["batches"],1):
        low,high=batch["particle_id_min"],batch["particle_id_max"]
        if (any(type(v) is not int for v in (low,high,batch["count"],batch["index"])) or batch["index"]!=index
                or not 1<=low<=high<=plan["particle_count"] or batch["count"]!=high-low+1):
            raise ValueError("invalid public source-row interval")
        seen.extend(range(low,high+1));ids=plan["selected_particle_ids"][low-1:high]
        directory=run/f"simion/pulse/batch_{index:04d}"
        receipt=directory/"case_metadata.json"
        name=f"batch_{index:04d}__rows_{low:06d}_{high:06d}"
        if materialize_case_ids is not None and name not in materialize_case_ids:
            continue
        if receipt.exists():
            case=_read(receipt)
            if case.get("case_id")!=name or case.get("expected_particle_ids")!=ids or case.get("input_identity")!=identity:
                raise ValueError("retained formal batch controls differ from current inputs")
            for record in case["control_records"]:
                verify_record("retained batch control",record)
            cases.append(case)
        else:
            missing.append((batch,ids,name,receipt))
    coverage=batch_plan.get("coverage","complete_population")
    if (seen!=sorted(set(seen)) or coverage not in ("complete_population","initial_formal_batch_only")
            or coverage=="complete_population" and seen!=list(range(1,plan["particle_count"]+1))
            or coverage=="initial_formal_batch_only" and (len(batch_plan["batches"])!=1 or seen!=list(range(1,len(seen)+1)))):
        raise ValueError("public batch coverage overlaps or omits its declared population")
    if missing:
        tasks=materialize_simion_batches(plan_path,run/"simion/pulse",[entry[1] for entry in missing],
             code_root=code_root,field_pa=field_pa,seed_iob=seed_iob,batch_indices=[entry[0]["index"] for entry in missing])
        for task,(batch,ids,name,receipt) in zip(tasks,missing,strict=True):
            paths=task["paths"];directory=Path(paths["paired_pulse.iob"]).parent
            case=dict(index=batch["index"],case_id=name,count=len(ids),expected_particle_ids=ids,source_row_range=[batch["particle_id_min"],batch["particle_id_max"]],
                simion_particle_id_offset=0,merge_offset=0,working_directory=str(directory),environment={},
                stdout=str(run/f"logs/pulse.{name}.stdout.log"),stderr=str(run/f"logs/pulse.{name}.stderr.log"),
                fly_arguments=["--nogui","--noprompt","fly",paths["paired_pulse.iob"]],
                iob_builder_arguments=["--nogui","--noprompt","lua",paths["build_iob.lua"],paths["build_spec.lua"],"build"],
                reopen_arguments=["--nogui","--noprompt","lua",paths["build_iob.lua"],paths["build_spec.lua"],"verify"],
                iob_path=paths["paired_pulse.iob"],receipt_path=str(receipt),paths=paths,input_identity=identity,
                control_records=[file_record(Path(paths[name])) for name in ("paired_pulse.lua","paired_pulse.fly2","build_iob.lua","build_spec.lua")])
            _json_once(receipt,case);cases.append(case)
    return dict(schema_version=1,role="paired_accelerator_pulse_batch_materialization",coverage=coverage,
                scheduled_particle_ids=[plan["selected_particle_ids"][i-1] for i in seen],
                pending_particle_ids=[pid for i,pid in enumerate(plan["selected_particle_ids"],1) if i not in seen],
                batches=sorted(cases,key=lambda c:c["index"]),gui_case=None)


def materialize_simion_continuation(plan_path: Path,run: Path,stages: dict, *,code_root: Path,field_pa: Path,seed_iob: Path) -> dict | None:
    """Delegate immutable complete units to the sole public continuation planner."""
    if stages["simion_workbench"] is None:
        return None
    if stages["simion_baseline"] is not None:
        raise ValueError("complete baseline needs only its missing replay, not batch continuation")
    run=run.resolve();source=Path(stages["manifest"]["source_path"]).parent
    units=[WholeUnitReplayUnit(row["key"],tuple(Path(p) for p in row["terminal_outputs"]),row["is_complete"]) for row in stages["partial_units"]]
    directory=run/"inputs/pulse_continuation"
    planned=build_whole_unit_replay_plan(predecessor_run_dir=source,output_dir=directory,units=units)
    replay={row["key"] for row in planned["units"] if row["action"]=="replay"}
    parent_workbench=_read(record_path(stages["simion_workbench"]))
    dispatch=stages.get('recovered_dispatch') or _read(record_path(stages["simion_dispatch"]))
    dispatch_path=record_path(stages["simion_dispatch"])
    if stages.get('recovered_dispatch') is not None:
        dispatch_path=directory/'recovered_dispatch_plan.json'
        _json_once(dispatch_path,dispatch)
    workbench=materialize_batches(run,plan_path,dispatch,code_root=code_root,field_pa=field_pa,seed_iob=seed_iob,materialize_case_ids=replay)
    units_by_key={unit['key']:unit for unit in planned['units']}
    workbench["batches"].extend({**case,'continuation_source':units_by_key[case['case_id']]}
        for case in parent_workbench["batches"] if case["case_id"] not in replay)
    workbench["batches"].sort(key=lambda case:case["index"])
    return dict(fixed_dispatch_plan_path=str(dispatch_path),
                continuation_plan_path=str(directory/"simion_whole_unit_replay_plan.json"),
                continuation_record=file_record(directory/"simion_whole_unit_replay_plan.json"),
                workbench=workbench,field=stages["simion_field"])


ROW_PREFIX="PAIRED_ACCELERATOR_PULSE_ROW="


def collect_simion_batches(plan_path: Path,workbench_receipt_path: Path,run: Path, *,phase: str="baseline") -> dict:
    """Collect actual native rows once; preserve unknown stops and original IDs.

    Only declared observation-window stopping is classified. This is neither
    collision-entity inference nor a COMSOL/SIMION equivalence verdict.
    """
    if phase not in ("baseline","default_replay"):
        raise ValueError("unsupported pulse collection phase")
    plan=_read(plan_path);workbench=_read(workbench_receipt_path);run=run.resolve()
    with Path(plan["source_csv"]["path"]).open(encoding="utf-8-sig",newline="") as stream:
        source={int(r["particle_id"]):r for r in csv.DictReader(stream)}
    all_rows=[];logs=[];seen=set();unknown=[]
    for case in workbench["batches"]:
        ids=case["expected_particle_ids"]
        if seen.intersection(ids):
            raise ValueError("pulse batch populations overlap")
        seen.update(ids)
        log=Path(case["stdout"] if phase=="baseline" else case["default_replay_stdout"])
        with log.open(encoding="utf-8-sig") as stream:
            lines=list(stream)
        native=require_one_fly_completion(lines)
        marker=f"PAIRED_ACCELERATOR_PULSE_CALLBACKS_COMPLETE particles={len(ids)}"
        if native.splats!=len(ids) or sum(line.strip()==marker for line in lines)!=1:
            raise ValueError("pulse native completion does not cover the explicit batch")
        rows=[next(csv.reader([line[len(ROW_PREFIX):].rstrip("\r\n")])) for line in lines if line.startswith(ROW_PREFIX)]
        if any(len(row)!=len(COLUMNS) for row in rows):
            raise ValueError("pulse native row columns differ")
        records=[dict(zip(COLUMNS,row,strict=True)) for row in rows]
        grouped={pid:[] for pid in ids}
        for row in records:
            pid=int(row["particle_id"]);index=int(row["native_particle_index"])
            if not 1<=index<=len(ids) or ids[index-1]!=pid or pid not in grouped:
                raise ValueError("pulse native row changed source identity")
            if row["event"] not in ("source_state","observation","terminal"):
                raise ValueError("unsupported native pulse event")
            grouped[pid].append(row)
        for pid,events in grouped.items():
            if (not events or events[0]["event"]!="source_state" or events[-1]["event"]!="terminal"
                    or sum(r["event"]=="source_state" for r in events)!=1 or sum(r["event"]=="terminal" for r in events)!=1):
                raise ValueError("pulse source/terminal census is incomplete")
            start,terminal=events[0],events[-1]
            expected={"instrument_time_us":plan["source_time_us"],"original_birth_time_us":plan["original_birth_times_us"][str(pid)],
                      **{a+"_mm":float(source[pid][a+"_mm"]) for a in "xyz"},
                      **{"v"+a+"_m_per_s":float(source[pid]["v"+a+"_m_per_s"]) for a in "xyz"}}
            if any(not binary64_serialization_close(float(start[key]),value) for key,value in expected.items()):
                raise ValueError("native pulse initial6D/time/birth differs from the frozen source")
            if terminal["terminal_reason"] not in ("unknown","observation_window_complete"):
                raise ValueError("pulse terminal invented a physical stop classification")
            if terminal["terminal_reason"]=="unknown":
                unknown.append(pid)
            observations=[row for row in events if row["event"]=="observation"]
            requested=[float(row["requested_time_us"]) for row in observations]
            if (len(set(requested))!=len(requested) or not set(requested)<=set(plan["observation_times_us"])
                    or any(not binary64_serialization_close(float(row["instrument_time_us"]),float(row["requested_time_us"])) for row in observations)
                    or terminal["terminal_reason"]=="observation_window_complete" and requested!=plan["observation_times_us"]):
                raise ValueError("native pulse observations missed or duplicated declared absolute times")
        logs.append(file_record(log));all_rows.extend(records)
    if seen!=set(plan["selected_particle_ids"]):
        raise ValueError("native pulse batches do not cover the frozen selected population")
    output=run/f"results/simion_pulse_{phase}.csv"
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=COLUMNS,lineterminator="\n");writer.writeheader();writer.writerows(all_rows)
    result=dict(schema_version=1,role="paired_accelerator_pulse_simion_collection",phase=phase,native_complete=True,
        particle_count=len(seen),particle_ids=plan["selected_particle_ids"],physical_identity=_source_identity(plan),
        simion_numerics=_simion_numerics(plan),
        simion_field_identity=_simion_field_identity(plan),
        unknown_stop_particle_ids=sorted(unknown),logs=logs,samples=file_record(output),
        claim="native pulse callback/census only; no numerical-equivalence or collision-entity qualification")
    if phase=="baseline":
        _json_once(run/"results/simion_pulse_baseline.json",result)
        return result
    original=_read(run/"results/simion_pulse_baseline.json")
    if (original["physical_identity"]!=result["physical_identity"] or original["simion_field_identity"]!=result["simion_field_identity"]
            or original["simion_numerics"]!=result["simion_numerics"]):
        raise ValueError("saved-default replay source or SIMION field differs from baseline")
    with (run/"results/simion_pulse_baseline.csv").open(encoding="utf-8",newline="") as stream:
        baseline=list(csv.DictReader(stream))
    ids=plan["selected_particle_ids"]
    left=group_particle_events(baseline,ids,key=lambda row:int(row["particle_id"]))
    right=group_particle_events(all_rows,ids,key=lambda row:int(row["particle_id"]))
    differences=[]
    fields=[key for key in COLUMNS if key!="native_particle_index"]
    for pid,index,key,a,b in iter_particle_event_fields(left,right,particle_ids=ids,fields=fields):
        if index==-1:
            differences.append(dict(particle_id=pid,field="event_count"))
            continue
        if a==b:
            continue
        try:
            close=binary64_serialization_close(float(a),float(b))
        except ValueError:
            close=False
        if not close:
            differences.append(dict(particle_id=pid,event_index=index,field=key,before=a,after=b))
    comparison=dict(schema_version=1,role="paired_accelerator_pulse_saved_default_comparison",passed=not differences,
        physical_identity=_source_identity(plan),simion_numerics=result["simion_numerics"],simion_field_identity=result["simion_field_identity"],replay_samples=result["samples"],logs=logs,differences=differences,
        numerical_allowance="existing32ULP binary64 serialization only",claim="deterministic saved-default parity only; no field equivalence")
    _json_once(run/"results/simion_pulse_replay_comparison.json",comparison)
    if differences:
        raise ValueError("saved-default pulse replay differs; comparison evidence retained")
    return comparison


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare-dispatch","materialize-batches"))
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--phase",choices=("pulse",),required=True)
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--code-root",type=Path,required=True)
    parser.add_argument("--field-pa",type=Path,required=True)
    parser.add_argument("--seed-iob",type=Path,required=True)
    parser.add_argument("--batch-plan",type=Path)
    args=parser.parse_args()
    if args.action=="prepare-dispatch":
        if args.batch_plan is not None:
            parser.error("prepare-dispatch does not consume a batch plan")
        result=prepare_dispatch_request(args.run,args.plan,args.code_root,args.field_pa)
    else:
        if args.batch_plan is None:
            parser.error("materialize-batches requires the public batch plan")
        result=materialize_batches(args.run,args.plan,_read(args.batch_plan),code_root=args.code_root,field_pa=args.field_pa,seed_iob=args.seed_iob)
    print(json.dumps(result,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
