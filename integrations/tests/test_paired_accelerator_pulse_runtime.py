"""OA pulse materialization and actual Lua callbacks, without native fields/Fly."""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
import subprocess
import tempfile
import shutil
import unittest
from unittest.mock import patch

from integrations.workflows.paired_accelerator_pulse.runtime import (
    COLUMNS, ROW_PREFIX, collect_simion_batches, load_completed_pulse_stages, materialize_batches, materialize_simion_continuation,
    materialize_comsol_task, materialize_simion_batches, prepare_dispatch_request,
)

from common.contracts.particle_physics import AMU_KG
from common.contracts.write_run_manifest import build_run_manifest, file_record
from common.simion.particle_batching import plan_single_wave_batches
from common.simion.resource_scheduler import plan_simion_dispatch

ROOT=Path(__file__).resolve().parents[2]
LUA=Path("C:/Program Files/SIMION-2020/lua.exe")
ADAPTER=ROOT/"projects/single_reflection_oa_tof_mass_analyzer/simion/paired_accelerator_pulse.lua"


def fixture(root: Path) -> tuple[Path, Path, Path]:
    def write(name, value):
        p=root/name;p.write_text(json.dumps(value),encoding="utf-8");return p
    def record(path):
        return file_record(path)
    rows=[]
    for pid,birth in [(41,.041),(7,.007)]:
        state=dict(particle_id=pid,x_mm=0.,y_mm=0.,z_mm=0.,vx_mm_per_us=1.25,vy_mm_per_us=-.5,
                   vz_mm_per_us=2.,kinetic_energy_eV=1.)
        rows.extend([dict(state,event="source_release",instrument_time_us=birth),dict(state,event="pre_pulse_state",instrument_time_us=10.)])
    collection=write("collection.json",dict(schema_version=1,role="single_reflection_complete_mother_collection",
        phase="full_instrument",native_complete=True,clock_epoch_id="fixture_epoch",
        flight=dict(pulse=dict(mode="timed",time_us=10.,width_us=2.)),canonical_events=rows))
    grid=dict(dimensions=dict(nx=10,ny=11,nz=12),cell_mm_xyz=dict(x=.5,y=1.,z=.05),instance_origin_mm=dict(x=-1.,y=-5.,z=-2.))
    static=write("static.json",dict(native_geometry_compilation=dict(grid=grid)))
    publication=write("publication.json",dict(status="published",action_required="complete",cache_key="fixture_key",generation_directory=str(root/"published")))
    (root/"published").mkdir()
    write("published/cache_manifest.json",dict(files=[dict(name="paired_static_on.pa",bytes=1,sha256="A"*64)]))
    model=root/"inert_static.mph";model.write_bytes(b"INERT IDENTITY ONLY, NOT A NATIVE MODEL")
    source=root/"source.csv"
    with source.open("w",newline="") as out:
        keys=["particle_id","mass_amu","charge_state","x_mm","y_mm","z_mm","vx_m_per_s","vy_m_per_s","vz_m_per_s"]
        writer=csv.DictWriter(out,fieldnames=keys);writer.writeheader()
        for pid in [41,7]:writer.writerow(dict(particle_id=pid,mass_amu=100,charge_state=1,x_mm=0,y_mm=0,z_mm=0,vx_m_per_s=1250,vy_m_per_s=-500,vz_m_per_s=2000))
    plan=write("paired_accelerator_pulse_plan.json",dict(schema_version=1,role="paired_accelerator_pulse_plan",static_plan=record(static),
        model=record(model),source_csv=record(source),mass_kg=100*AMU_KG,frame_id="fixture_frame",source_instance_id="oatof",
        uncontinued_mother_particle_ids=[],selection_basis="all_recorded_timed_pre_pulse_states",selected_particle_ids=[41,7],particle_count=2,mass_amu=100,charge_state=1,
        source_time_us=10.,pulse=dict(on_us=10.,off_us=12.),off_electrode_voltages_v={"1":0},
        observation_times_us=[10.,11.,12.,13.],numerics=dict(maximum_step_us=.1,simion_trajectory_quality=19,relative_tolerance=1e-5,absolute_tolerance=1e-6),
        original_mother_particle_ids=[7,41],original_birth_times_us={"7":.007,"41":.041},clock_epoch_id="fixture_epoch",instrument_epoch_us=0.,
        input_records=dict(pre_pulse_collection=record(collection),simion_field_publication=record(publication))))
    return plan,root/"published/paired_static_on.pa",ROOT/"common/simion/assets/iob_instance_seeds/1_instance_seed.iob"


class PairedPulseRuntimeTests(unittest.TestCase):
    def test_materializes_disjoint_original_id_batches_without_native_payload_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            original=Path.open
            def no_pa(path,*args,**kwargs):
                if path.suffix.lower() in (".pa",".pa0",".iob"):
                    raise AssertionError("materializer accessed a native payload")
                return original(path,*args,**kwargs)
            with patch.object(Path,"open",no_pa):
                tasks=materialize_simion_batches(plan,root/"batches",[[7],[41]],field_pa=pa,code_root=ROOT,seed_iob=seed)
            self.assertEqual([a["particle_ids"] for a in tasks],[[7],[41]])
            self.assertEqual(tasks[0]["original_mother_particle_ids"],[7,41])
            for task in tasks:
                self.assertEqual(task["field_pa"],str(pa.resolve()))
                self.assertFalse(Path(task["paths"]["paired_pulse.iob"]).exists())
                text=Path(task["paths"]["paired_pulse.lua"]).read_text()
                self.assertIn("single_flight_time_origin_us={10}",text)
                self.assertIn("single_flight_restore_source_velocity",text)
                self.assertNotIn("fast_adjust",text.lower())
                self.assertEqual(Path(task["paths"]["paired_pulse.fly2"]).read_text().count("standard_beam"),1)
                self.assertEqual(task["clock_epoch_id"],"fixture_epoch")
            with self.assertRaisesRegex(ValueError,"disjoint"):
                materialize_simion_batches(plan,root/"bad",[[7],[7]],field_pa=pa,code_root=ROOT,seed_iob=seed)
            with self.assertRaisesRegex(ValueError,"baseline"):
                materialize_simion_batches(plan,root/"wrong",[[7]],field_pa=root/"other.pa",code_root=ROOT,seed_iob=seed)

    def test_changed_source6d_is_rejected_without_adjusting_or_recropping(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            source=root/"source.csv";source.write_text(source.read_text().replace("1250","1251"))
            with self.assertRaisesRegex(ValueError,"source6D"):
                materialize_simion_batches(plan,root/"batch",[[7]],field_pa=pa,code_root=ROOT,seed_iob=seed)

    @unittest.skipUnless(LUA.is_file(),"standalone Lua unavailable")
    def test_real_lua_adapter_callbacks_keep_edges_clock_identity_and_raw_terminals(self):
        result=subprocess.run([str(LUA),str(ROOT/"projects/single_reflection_oa_tof_mass_analyzer/tests/simion/test_paired_accelerator_pulse.lua"),
            str(ADAPTER),str(ROOT/"common/simion/voltage_waveforms.lua"),str(ROOT/"integrations/runtime/single_flight_pulse_hook.lua")],
            cwd=ROOT,capture_output=True,text=True,check=False,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("PAIRED_ACCELERATOR_PULSE_CALLBACK_FIXTURE=PASS",result.stdout)

    @unittest.skipUnless(LUA.is_file(),"standalone Lua unavailable")
    def test_generated_program_emits_two_fly_evidence_without_overwriting_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            task=materialize_simion_batches(plan,root/"batch",[[41,7]],field_pa=pa,code_root=ROOT,seed_iob=seed)[0]
            harness=root/"program_harness.lua"
            harness.write_text(r'''simion={wb={instances={}}};segment={}
function simion.workbench_program() end
local pa={path=arg[2],potential_type='electric',nx=10,ny=11,nz=12,dx_mm=.5,dy_mm=1,dz_mm=.05}
function pa:inside_vc() return true end
function pa:field_vc() return 2,-3,4 end
local item={pa=pa,x=-1,y=-5,z=-2,az=0,el=0,rt=0,scale=1}
function item:wb_to_pa_coords(x,y,z) return (x+1)/.5,y+5,(z+2)/.05 end
simion.wb.instances[1]=item
dofile(arg[1]);sim_trajectory_quality=-1;segment.load();assert(sim_trajectory_quality==19)
for fly=1,2 do
sim_trajectory_quality=-1;segment.initialize_run();assert(sim_trajectory_quality==19)
for i=1,2 do
 ion_number=i;ion_instance=1;ion_time_of_flight=0;ion_splat=0
 ion_px_mm,ion_py_mm,ion_pz_mm=0,0,0;ion_vx_mm,ion_vy_mm,ion_vz_mm=0,0,0
 segment.initialize();assert(ion_vx_mm==1.25 and ion_vy_mm==-.5 and ion_vz_mm==2)
 segment.efield_adjust();assert(ion_dvoltsx_gu==-2)
 for elapsed=1,3 do ion_time_of_flight=elapsed;segment.other_actions() end
 assert(ion_splat==1)
 ion_splat=nil
 setmetatable(_G,{__index=function(_,key) if key=='ion_splat' then error('terminate must not read ion_splat') end end})
 segment.terminate()
 setmetatable(_G,nil)
end
segment.terminate_run()
end
print('GENERATED_PULSE_PROGRAM_FIXTURE=PASS')
''',encoding="utf-8")
            result=subprocess.run([str(LUA),str(harness),task["paths"]["paired_pulse.lua"],str(pa)],cwd=root,capture_output=True,text=True,timeout=20,check=False)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            payloads=[line[len(ROW_PREFIX):] for line in result.stdout.splitlines() if line.startswith(ROW_PREFIX)]
            rows=list(csv.DictReader(io.StringIO(",".join(COLUMNS)+"\n"+"\n".join(payloads))))
            self.assertEqual(rows[:len(rows)//2],rows[len(rows)//2:])
            self.assertFalse(list(root.rglob("paired_pulse_particles.csv")))
            sources=[a for a in rows if a["event"]=="source_state"]
            self.assertEqual([int(a["particle_id"]) for a in sources],[41,7,41,7])
            self.assertEqual([float(a["instrument_time_us"]) for a in sources],[10.,10.,10.,10.])
            self.assertEqual([float(a["original_birth_time_us"]) for a in sources],[.041,.007,.041,.007])
            self.assertEqual(len([a for a in rows if a["event"]=="observation"]),16)
            self.assertTrue(all(a["terminal_reason"]=="observation_window_complete" for a in rows if a["event"]=="terminal"))
            self.assertTrue(all(a["solver_raw_status"]=="" for a in rows if a["event"]=="terminal"))

    @unittest.skipUnless(LUA.is_file(),"standalone Lua unavailable")
    def test_materialized_iob_task_builds_and_reopens_one_slot_preserving_companions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            task=materialize_simion_batches(plan,root/"batch",[[41,7]],field_pa=pa,code_root=ROOT,seed_iob=seed)[0]
            program=Path(task["paths"]["paired_pulse.lua"]);fly=Path(task["paths"]["paired_pulse.fly2"])
            before=[program.read_bytes(),fly.read_bytes()]
            harness=root/"iob_harness.lua"
            harness.write_text(r'''-- Simulated API object behavior only; no native IOB/PA data.
local original_args=arg
local s=dofile(original_args[2])
local pa={path=s.field_pa,nx=10,ny=11,nz=12,dx_mm=.5,dy_mm=1,dz_mm=.05}
function pa:load() self.path=self.filename end
local item={pa=pa}
function item:_debug_update_size() end
simion={wb={instances={item}}}
function simion.command() end
function simion.wb:load_particles(path) assert(path==s.fly2) end
function simion.wb:save(path)
 local f=assert(io.open(path,'w'));f:write('INERT IOB API FIXTURE');f:close()
 for _,companion in ipairs({s.program,s.fly2}) do
  f=assert(io.open(companion,'w'));f:write('seed overwritten companion');f:close()
 end
end
-- A separate command context has no Program reserved-variable value.
assert(sim_trajectory_quality==nil)
arg={original_args[2],'build'};dofile(original_args[1])
assert(sim_trajectory_quality==nil,'builder wrote a command-context quality')
arg={original_args[2],'verify'};dofile(original_args[1])
assert(sim_trajectory_quality==nil,'verifier covered a missing saved quality by writing it')
''',encoding="utf-8")
            result=subprocess.run([str(LUA),str(harness),task["paths"]["build_iob.lua"],task["paths"]["build_spec.lua"]],
                                  cwd=ROOT,capture_output=True,text=True,check=False,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn("PAIRED_ACCELERATOR_PULSE_IOB_VERIFY=PASS",result.stdout)
            self.assertEqual([program.read_bytes(),fly.read_bytes()],before)
            # Wrong frozen Program quality is refused even though command-global Q is absent.
            program.write_text(program.read_text().replace("trajectory_quality=19,maximum_step_us", "trajectory_quality=20,maximum_step_us"))
            rejected=subprocess.run([str(LUA),str(harness),task["paths"]["build_iob.lua"],task["paths"]["build_spec.lua"]],
                cwd=ROOT,capture_output=True,text=True,check=False,timeout=20)
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn("frozen OA Program trajectory quality differs",rejected.stderr)

    def test_public_dispatch_and_retained_formal_case_reuse_exact_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            request=prepare_dispatch_request(root,plan,ROOT,pa)["request"]
            dispatch=plan_simion_dispatch(request,[],available_memory_bytes=40*1024**3,total_physical_memory_bytes=48*1024**3,logical_processors=16)
            self.assertEqual(dispatch["role"],"simion_repository_dispatch_plan")
            self.assertEqual(request["field_kind"],"electrostatic")
            full=plan_single_wave_batches(2,2)
            partial={**full,"batch_count":1,"batches":full["batches"][:1],"coverage":"initial_formal_batch_only"}
            first=materialize_batches(root,plan,partial,code_root=ROOT,field_pa=pa,seed_iob=seed)
            control=Path(first["batches"][0]["paths"]["paired_pulse.lua"])
            before=control.read_bytes()
            complete=materialize_batches(root,plan,full,code_root=ROOT,field_pa=pa,seed_iob=seed)
            self.assertEqual([c["expected_particle_ids"] for c in complete["batches"]],[[41],[7]])
            self.assertEqual(complete["pending_particle_ids"],[])
            self.assertIsNone(complete["gui_case"])
            self.assertEqual(control.read_bytes(),before)
            self.assertEqual(complete["batches"][0]["fly_arguments"][:3],["--nogui","--noprompt","fly"])
            control.write_text("tampered prepared Program")
            with self.assertRaisesRegex(AssertionError,"byte count|SHA-256"):
                materialize_batches(root,plan,full,code_root=ROOT,field_pa=pa,seed_iob=seed)

    def test_comsol_task_canonical_saved_model_branch_is_export_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,_,_=fixture(root)
            saved=root/"saved particle.mph"
            tasks=materialize_comsol_task(plan,root/"comsol",ROOT,saved_particle_model=saved)
            text=Path(tasks["matlab"]).read_text()
            self.assertIn(saved.resolve().as_posix(),text)
            self.assertIn("run_paired_accelerator_pulse(",text)
            self.assertNotIn(".run",text)
            self.assertFalse(saved.exists())

    @staticmethod
    def native_protocol_log(path: Path, ids: list[int], *, changed: bool=False) -> None:
        """Inert protocol fixture, never a native particle or field assertion."""
        lines=[]
        for index,pid in enumerate(ids,1):
            for event,time in [("source_state",10.),("observation",10.),("observation",11.),("observation",12.),("observation",13.),("terminal",13.)]:
                row=dict(particle_id=pid,native_particle_index=index,event=event,instrument_time_us=time,
                    requested_time_us="" if event=="terminal" else time,x_mm=.5 if changed and event=="observation" else 0.,y_mm=0.,z_mm=0.,
                    vx_m_per_s=1250.,vy_m_per_s=-500.,vz_m_per_s=2000.,state_present=1,
                    solver_raw_status="" if event=="terminal" else 0,original_birth_time_us=.041 if pid==41 else .007,
                    terminal_reason="observation_window_complete" if event=="terminal" else "")
                lines.append(ROW_PREFIX+",".join(str(row[k]) for k in COLUMNS))
        lines.extend([f"PAIRED_ACCELERATOR_PULSE_CALLBACKS_COMPLETE particles={len(ids)}",f"status,Fly completed. {len(ids)} splats, 1.25 seconds"])
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text("\n".join(lines)+"\n")

    def test_stdout_collector_preserves_baseline_and_rejects_changed_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            work=materialize_batches(root,plan,plan_single_wave_batches(2,2),code_root=ROOT,field_pa=pa,seed_iob=seed)
            for case in work["batches"]:
                self.native_protocol_log(Path(case["stdout"]),case["expected_particle_ids"])
                case["default_replay_stdout"]=str(root/f"logs/replay.{case['index']}.log")
                self.native_protocol_log(Path(case["default_replay_stdout"]),case["expected_particle_ids"])
            receipt=root/"workbench.json";receipt.write_text(json.dumps(work))
            log=Path(work["batches"][0]["stdout"]);valid=log.read_text()
            for invalid in (valid.replace("Fly completed. 1 splats", "Fly completed. 2 splats"),
                            valid.replace("CALLBACKS_COMPLETE particles=1", "CALLBACKS_COMPLETE particles=2")):
                log.write_text(invalid)
                with self.assertRaisesRegex(ValueError,"completion does not cover the explicit batch"):
                    collect_simion_batches(plan,receipt,root)
                self.assertFalse((root/"results/simion_pulse_baseline.csv").exists())
            log.write_text(valid)
            baseline=collect_simion_batches(plan,receipt,root)
            original=Path(baseline["samples"]["path"]).read_bytes()
            replay=collect_simion_batches(plan,receipt,root,phase="default_replay")
            self.assertTrue(replay["passed"])
            self.assertEqual(Path(baseline["samples"]["path"]).read_bytes(),original)
            # A second run uses fresh output ownership; changed physics cannot pass parity.
            other=root/"changed";other.mkdir();(other/"results").mkdir()
            shutil.copyfile(root/"results/simion_pulse_baseline.csv",other/"results/simion_pulse_baseline.csv")
            shutil.copyfile(root/"results/simion_pulse_baseline.json",other/"results/simion_pulse_baseline.json")
            for case in work["batches"]:
                self.native_protocol_log(Path(case["default_replay_stdout"]),case["expected_particle_ids"],changed=True)
            with self.assertRaisesRegex(ValueError,"replay differs"):
                collect_simion_batches(plan,receipt,other,phase="default_replay")
            self.assertTrue((other/"results/simion_pulse_replay_comparison.json").is_file())

    @staticmethod
    def publish(root: Path, plan: Path, *, status="failed",extra_inputs=None) -> tuple[Path,Path]:
        config=root/"run_config.json"
        config.write_text(json.dumps(dict(schema_version=1,project="instrument_assembly",mode="paired_accelerator_pulse",
            run_id="20261026_060000__test__python__pulse-recovery",inputs=dict(plan=str(plan),source=str(root/"source.csv"),static=str(root/"static.json"),**(extra_inputs or {})))))
        outputs=[p for folder in ("results","logs","simion","comsol") for p in (root/folder).rglob("*") if p.is_file()]
        manifest=root/"run_manifest.json";manifest.write_text(json.dumps(build_run_manifest(config,status,output_paths=outputs)))
        snapshot=root/"snapshot.json";shutil.copyfile(manifest,snapshot)
        return manifest,snapshot

    @staticmethod
    def saved_particle(root: Path,plan: Path) -> Path:
        (root/"comsol").mkdir()
        model=root/"comsol/paired_accelerator_pulse.mph";model.write_bytes(b"INERT MODEL IDENTITY NOT A NATIVE SOLUTION")
        (root/"comsol/paired_pulse_solution.json").write_text(json.dumps(dict(schema_version=1,role="paired_accelerator_pulse_solution",status="solved_saved",solution_tag="sol_pulse",plan_path=str(plan),model_path=str(model))))
        return model

    def saved_simion(self,root: Path,plan: Path,pa: Path,seed: Path, *, completed=(1,2),baseline=True,replay=True) -> dict:
        # Inert public fixed-dispatch and native protocol fixtures; no native solve.
        partition=plan_single_wave_batches(2,2)
        dispatch=dict(schema_version=1,role="simion_repository_dispatch_plan",particle_count=2,
            waves=[dict(coverage="complete_population",batches=partition["batches"])])
        work=materialize_batches(root,plan,dispatch,code_root=ROOT,field_pa=pa,seed_iob=seed)
        (root/"results").mkdir(exist_ok=True)
        (root/"results/pulse.dispatch_plan.json").write_text(json.dumps(dispatch))
        for case in work["batches"]:
            if case["index"] not in completed:
                continue
            iob=Path(case["iob_path"]);iob.write_bytes(b"INERT SAVED IOB PROTOCOL FIXTURE")
            case["control_records"].append(file_record(iob))
            reopened=root/f"logs/reopen.{case['index']}.log";reopened.parent.mkdir(exist_ok=True)
            reopened.write_text("PAIRED_ACCELERATOR_PULSE_IOB_VERIFY=PASS fixture-only\n")
            case["iob_reopen_record"]=file_record(reopened)
            self.native_protocol_log(Path(case["stdout"]),case["expected_particle_ids"])
            case["default_replay_stdout"]=str(root/f"logs/replay.{case['index']}.log")
            if replay:
                self.native_protocol_log(Path(case["default_replay_stdout"]),case["expected_particle_ids"])
        receipt=root/"results/pulse_workbench.json";receipt.write_text(json.dumps(work))
        if baseline:
            collect_simion_batches(plan,receipt,root)
        if replay:
            collect_simion_batches(plan,receipt,root,phase="default_replay")
        return work

    def test_saved_particle_stage_is_metadata_only_and_dependency_projected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,_,_=fixture(root)
            model=self.saved_particle(root,plan)
            manifest,snapshot=self.publish(root,plan)
            original=Path.open
            def no_native(path,*args,**kwargs):
                if path.suffix.lower() in (".mph",".pa"):
                    raise AssertionError("metadata loader opened a native payload")
                return original(path,*args,**kwargs)
            with patch.object(Path,"open",no_native):
                result=load_completed_pulse_stages(plan,manifest,snapshot)
            self.assertEqual(result["particle_model"]["path"],str(model))
            self.assertIsNone(result["simion_baseline"]);self.assertIsNone(result["simion_replay"])
            # A changed solve tolerance invalidates only CPT, while TQual is unrelated.
            document=json.loads(plan.read_text());document["numerics"]["maximum_step_us"]*=2
            changed=root/"changed_plan.json";changed.write_text(json.dumps(document))
            self.assertIsNone(load_completed_pulse_stages(changed,manifest,snapshot)["particle_model"])
            document=json.loads(plan.read_text());document["numerics"]["simion_trajectory_quality"]=20
            changed.write_text(json.dumps(document))
            self.assertEqual(load_completed_pulse_stages(changed,manifest,snapshot)["particle_model"]["path"],str(model))
            # ES model is authoritative; SIMION raster/audit metadata does not re-solve CPT.
            static=root/"changed_static.json";static.write_text(json.dumps(dict(audit_label="changed",raster_cell_mm=.25)))
            document["static_plan"]=file_record(static);changed.write_text(json.dumps(document))
            self.assertIsNotNone(load_completed_pulse_stages(changed,manifest,snapshot)["particle_model"])
            tampered=json.loads(snapshot.read_text());tampered["status"]="success";snapshot.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError,"snapshot identity"):
                load_completed_pulse_stages(plan,manifest,snapshot)

    def test_independent_completed_stages_and_backend_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            self.saved_simion(root,plan,pa,seed,replay=False)
            manifest,snapshot=self.publish(root,plan)
            baseline=load_completed_pulse_stages(plan,manifest,snapshot)
            self.assertIsNotNone(baseline["simion_baseline"])
            self.assertIsNone(baseline["simion_replay"]);self.assertIsNone(baseline["particle_model"])
            self.assertEqual(baseline["simion_baseline"]["field"]["path"],str(pa))
            # Only replay remains: append its actual protocol fixture and collection.
            work=json.loads((root/"results/pulse_workbench.json").read_text())
            for case in work["batches"]:
                self.native_protocol_log(Path(case["default_replay_stdout"]),case["expected_particle_ids"])
            collect_simion_batches(plan,root/"results/pulse_workbench.json",root,phase="default_replay")
            manifest,snapshot=self.publish(root,plan)
            both=load_completed_pulse_stages(plan,manifest,snapshot)
            self.assertIsNotNone(both["simion_replay"]);self.assertIsNone(both["particle_model"])
            model=self.saved_particle(root,plan);manifest,snapshot=self.publish(root,plan,status="success")
            self.assertEqual(load_completed_pulse_stages(plan,manifest,snapshot)["particle_model"]["path"],str(model))
            newer=root/"new_generation";newer.mkdir()
            (newer/"cache_manifest.json").write_text(json.dumps(dict(files=[dict(name="paired_static_on.pa",bytes=1,sha256="B"*64)])))
            publication=root/"new_publication.json";publication.write_text(json.dumps(dict(status="published",action_required="complete",generation_directory=str(newer))))
            updated=json.loads(plan.read_text());updated["input_records"]["simion_field_publication"]=file_record(publication)
            changed=root/"new_field_plan.json";changed.write_text(json.dumps(updated))
            reused=load_completed_pulse_stages(changed,manifest,snapshot)
            self.assertIsNone(reused["simion_baseline"]);self.assertIsNone(reused["simion_replay"])
            self.assertEqual(reused["particle_model"]["path"],str(model))
            updated=json.loads(plan.read_text());updated["numerics"]["relative_tolerance"]*=.1;changed.write_text(json.dumps(updated))
            reused=load_completed_pulse_stages(changed,manifest,snapshot)
            self.assertIsNone(reused["particle_model"]);self.assertIsNotNone(reused["simion_replay"])
            updated=json.loads(plan.read_text());updated["numerics"]["simion_trajectory_quality"]=20;changed.write_text(json.dumps(updated))
            reused=load_completed_pulse_stages(changed,manifest,snapshot)
            self.assertIsNotNone(reused["particle_model"]);self.assertIsNone(reused["simion_baseline"])
            broken=json.loads(manifest.read_text());broken["outputs"]=[r for r in broken["outputs"] if Path(r["path"]).name!="simion_pulse_baseline.csv"]
            manifest.write_text(json.dumps(broken));shutil.copyfile(manifest,snapshot)
            with self.assertRaisesRegex(ValueError,"not manifest-bound"):
                load_completed_pulse_stages(plan,manifest,snapshot)

    def test_partial_units_use_existing_public_whole_unit_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            work=self.saved_simion(root,plan,pa,seed,completed=(2,),baseline=False,replay=False)
            manifest,snapshot=self.publish(root,plan)
            stages=load_completed_pulse_stages(plan,manifest,snapshot)
            self.assertEqual([r["is_complete"] for r in stages["partial_units"]],[False,True])
            new=root/"new_run";new.mkdir()
            resumed=materialize_simion_continuation(plan,new,stages,code_root=ROOT,field_pa=pa,seed_iob=seed)
            continuation=json.loads(Path(resumed["continuation_plan_path"]).read_text())
            self.assertEqual([r["action"] for r in continuation["units"]],["replay","reuse"])
            self.assertEqual(resumed["workbench"]["batches"][1],work["batches"][1])
            self.assertTrue(Path(resumed["workbench"]["batches"][0]["paths"]["paired_pulse.lua"]).is_relative_to(new))
            self.assertFalse((new/"simion/pulse/batch_0002").exists())
            # Completed native proof may not silently become an incomplete unit.
            Path(work["batches"][1]["iob_reopen_record"]["path"]).write_text("tampered proof")
            with self.assertRaises((AssertionError,ValueError)):
                load_completed_pulse_stages(plan,manifest,snapshot)

    def test_original_particle_source_is_flat_across_export_consumer_and_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);producer=root/"producer";producer.mkdir()
            plan,_,_=fixture(producer);model=self.saved_particle(producer,plan)
            manifest,snapshot=self.publish(producer,plan)
            first=load_completed_pulse_stages(plan,manifest,snapshot)
            consumer=root/"export_consumer";consumer.mkdir();current,_,_=fixture(consumer)
            # Equal field/source science, different owned plan and result paths.
            (consumer/"inputs").mkdir()
            receipt=consumer/"inputs/completed_pulse_stages.json";receipt.write_text(json.dumps(first))
            (consumer/"comsol").mkdir()
            particles=consumer/"comsol/paired_pulse_particles.csv";particles.write_text("INERT EXPORT PROTOCOL FIXTURE\n")
            initial=consumer/"comsol/paired_pulse_initial.csv";initial.write_text("INERT INITIAL PROTOCOL FIXTURE\n")
            facts=consumer/"comsol/paired_pulse_native_facts.json"
            facts.write_text(json.dumps(dict(schema_version=1,role="paired_accelerator_pulse_native_facts",plan_path=str(current),model_path=str(model),initial_complete=True,particle_count=2,observation_count=4,actual_observation_times_us=[10.,11.,12.,13.])))
            next_manifest,next_snapshot=self.publish(consumer,current,extra_inputs=dict(completed_stages=str(receipt)))
            original=Path.open
            def no_native(path,*args,**kwargs):
                if path.suffix.lower() in (".mph",".pa"):
                    raise AssertionError("recovery opened a native payload")
                return original(path,*args,**kwargs)
            with patch.object(Path,"open",no_native):
                restored=load_completed_pulse_stages(current,next_manifest,next_snapshot)
            self.assertEqual(restored["particle_model"]["path"],str(model))
            self.assertEqual(restored["particle_source"],first["particle_source"])
            self.assertEqual(restored["particle_exports"]["particles"]["path"],str(particles))
            # Another analysis-only consumer carries the original producer directly.
            analysis=root/"analysis_consumer";analysis.mkdir();third,_,_=fixture(analysis)
            (analysis/"inputs").mkdir();carried=analysis/"inputs/completed_pulse_stages.json";carried.write_text(json.dumps(restored))
            (analysis/"comsol").mkdir()
            for item in (particles,initial,facts):shutil.copyfile(item,analysis/"comsol"/item.name)
            third_manifest,third_snapshot=self.publish(analysis,third,extra_inputs=dict(completed_stages=str(carried),export_plan=str(current)))
            with patch.object(Path,"open",no_native):
                final=load_completed_pulse_stages(third,third_manifest,third_snapshot)
            self.assertEqual(final["particle_source"]["producer_manifest"]["path"],str(manifest))
            self.assertIsNotNone(final["particle_exports"])
            # A declared completed export with lost binding must fail, not Compute.
            broken=json.loads(third_manifest.read_text());broken["outputs"]=[r for r in broken["outputs"] if Path(r["path"]).name!="paired_pulse_initial.csv"]
            third_manifest.write_text(json.dumps(broken));shutil.copyfile(third_manifest,third_snapshot)
            with self.assertRaisesRegex(ValueError,"not manifest-bound"):
                load_completed_pulse_stages(third,third_manifest,third_snapshot)

    def test_completed_exports_allow_binary64_time_readback_and_reject_changed_times(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,_,_=fixture(root)
            document=json.loads(plan.read_text());document["observation_times_us"]=[10.,60.]
            plan.write_text(json.dumps(document))
            model=self.saved_particle(root,plan)
            for name in ("paired_pulse_particles.csv","paired_pulse_initial.csv"):
                (root/"comsol"/name).write_text("INERT EXPORT PROTOCOL FIXTURE\n")
            readback=60*1e-6*1e6
            self.assertNotEqual(readback,60.)
            facts=dict(schema_version=1,role="paired_accelerator_pulse_native_facts",plan_path=str(plan),model_path=str(model),
                initial_complete=True,particle_count=2,observation_count=2,actual_observation_times_us=[10.,readback])
            fact_path=root/"comsol/paired_pulse_native_facts.json";fact_path.write_text(json.dumps(facts))
            manifest,snapshot=self.publish(root,plan)
            self.assertIsNotNone(load_completed_pulse_stages(plan,manifest,snapshot)["particle_exports"])
            for times in ([10.,60.+64*math.ulp(60.)],[readback,10.],[10.]):
                with self.subTest(times=times):
                    facts["actual_observation_times_us"]=times;fact_path.write_text(json.dumps(facts))
                    manifest,snapshot=self.publish(root,plan)
                    with self.assertRaisesRegex(ValueError,"completed particle export fact is invalid"):
                        load_completed_pulse_stages(plan,manifest,snapshot)

    def test_stale_replay_log_transport_path_projects_only_unique_published_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan,pa,seed=fixture(root)
            work=self.saved_simion(root,plan,pa,seed)
            comparison=root/"results/simion_pulse_replay_comparison.json"
            document=json.loads(comparison.read_text())
            # Add a non-scientific line to distinguish this replay log's identity.
            log=Path(work["batches"][0]["default_replay_stdout"])
            log.write_text(log.read_text()+"alias projection protocol fixture\n")
            identity=file_record(log);identity["path"]=str(root/"removed_execution_alias/logs/replay.log")
            document["logs"][0]=identity;comparison.write_text(json.dumps(document))
            manifest,snapshot=self.publish(root,plan)
            restored=load_completed_pulse_stages(plan,manifest,snapshot)
            self.assertEqual(restored["simion_replay"]["logs"][0]["path"],str(log))
            duplicate=root/"logs/duplicate.log";shutil.copyfile(log,duplicate)
            manifest,snapshot=self.publish(root,plan)
            with self.assertRaisesRegex(ValueError,"exactly one canonical output"):
                load_completed_pulse_stages(plan,manifest,snapshot)
            duplicate.unlink();log.write_text("changed canonical log")
            manifest,snapshot=self.publish(root,plan)
            with self.assertRaisesRegex(ValueError,"exactly one canonical output"):
                load_completed_pulse_stages(plan,manifest,snapshot)

    def test_borrowed_canonical_logs_preserve_original_owner_across_consumer_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);producer=root/"producer";producer.mkdir()
            plan,pa,seed=fixture(producer);work=self.saved_simion(producer,plan,pa,seed)
            comparison=producer/"results/simion_pulse_replay_comparison.json"
            document=json.loads(comparison.read_text())
            log=Path(work["batches"][0]["default_replay_stdout"])
            log.write_text(log.read_text()+"borrowed original log fixture\n")
            identity=file_record(log);identity["path"]=str(producer/"removed_alias/replay.log")
            document["logs"][0]=identity;comparison.write_text(json.dumps(document))
            manifest,snapshot=self.publish(producer,plan)
            first=load_completed_pulse_stages(plan,manifest,snapshot)
            consumer=root/"consumer";consumer.mkdir();current,_,_=fixture(consumer)
            (consumer/"results").mkdir()
            for item in (producer/"results").iterdir():shutil.copyfile(item,consumer/"results"/item.name)
            borrowed={}
            for index,item in enumerate((producer/"results").iterdir()):borrowed[f"completed_parent_{index}"]=str(item)
            for index,item in enumerate((producer/"logs").iterdir()):borrowed[f"completed_parent_log_{index}"]=str(item)
            for index,item in enumerate((producer/"simion").rglob("*")):
                if item.is_file():borrowed[f"borrowed_control_{index}"]=str(item)
            borrowed["completed_parent_duplicate_same_path"]=str(log)
            next_manifest,next_snapshot=self.publish(consumer,current,extra_inputs=borrowed)
            restored=load_completed_pulse_stages(current,next_manifest,next_snapshot)
            self.assertEqual(restored["simion_replay"]["logs"],first["simion_replay"]["logs"])
            self.assertIsNotNone(restored["simion_baseline"])
            self.assertTrue(all(Path(r["path"]).is_relative_to(producer) for r in restored["simion_replay"]["logs"]))
            self.assertFalse((consumer/"logs").exists())
            # An arbitrary input key cannot grant the narrow borrowed-log authority.
            config=json.loads((consumer/"run_config.json").read_text())
            config["inputs"]={key if value!=str(log) else "unrelated_log":value for key,value in config["inputs"].items()}
            (consumer/"run_config.json").write_text(json.dumps(config))
            broken=build_run_manifest(consumer/"run_config.json","failed",output_paths=list((consumer/"results").iterdir()))
            next_manifest.write_text(json.dumps(broken));shutil.copyfile(next_manifest,next_snapshot)
            with self.assertRaisesRegex(ValueError,"exactly one canonical output or borrowed log"):
                load_completed_pulse_stages(current,next_manifest,next_snapshot)
