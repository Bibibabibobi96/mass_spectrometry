"""Solver-free batch projections and full-ID merge contracts; no physics claim."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.simion.particle_batching import batch_plan_from_dispatch
from common.simion.resource_scheduler import plan_simion_dispatch, plan_adaptive_followup
from projects.dual_pressure_rectilinear_ion_processor.analysis import batching, functional

PROJECT=Path(__file__).resolve().parents[1]


class BatchingTests(unittest.TestCase):
    """Exercise real public planning/merge with inert files, never SIMION."""

    def setUp(self) -> None:
        self.temp=tempfile.TemporaryDirectory(prefix="ion_processor_batch_")
        self.addCleanup(self.temp.cleanup)
        self.run=Path(self.temp.name)/"run"
        for name in ("inputs","simion","results","logs"):(self.run/name).mkdir(parents=True)
        self.config={name:functional.read_json(PROJECT/"config"/f"{name}.json") for name in ("baseline","numerics","source","native_operating_point")}
        self.config["coordinate_transform"]=functional.read_json(PROJECT/"config/coordinate_transform.json")
        self.config["native_projection"]=functional.native_projection(self.config["baseline"],self.config["numerics"])
        self.field=Path(self.temp.name)/"native"
        self.field.mkdir()
        (self.field/"processor.pa0").write_bytes(b"inert field fixture")
        self.manifest=self.field/"run_manifest.json"
        functional.write_json(self.manifest,dict(inputs={},outputs=[dict(path=str(self.field/"processor.pa0"),sha256="A"*64)]))
        self.config["native_field"]=dict(directory=str(self.field),source_manifest=str(self.manifest))
        for name in ("processor.lua","collision_hs1.lua","native_drive.lua","simion_rf_drive.lua","processor.iob"):
            (self.run/"simion"/name).write_bytes(b"inert frozen control "+name.encode())
        self.save_config()
        functional.write_json(self.run/"inputs/execution_profiles.json",functional.read_json(PROJECT/"config/execution_profiles.json"))
        functional.write_json(self.run/"run_config.json",dict(inputs={}))

    def save_config(self) -> None:
        functional.write_json(self.run/"inputs/resolved_model.json",self.config)

    def test_many_worker_outputs_use_public_manifest_api_without_argv(self) -> None:
        for index in range(300):
            path=self.run/"results"/("worker_"+str(index)+"_"+"x"*90+".csv")
            path.write_text("particle_id\n1\n",encoding="utf-8")
        (self.run/"run_manifest.json").write_text("{}",encoding="utf-8")
        (self.run/"results/.private").write_text("private",encoding="utf-8")
        with patch.object(batching,"build_run_manifest",return_value={"status":"failed"}) as build:
            batching.publish_manifest(self.run,"failed")
        args,kwargs=build.call_args
        self.assertEqual(args,(self.run/"run_config.json","failed"))
        outputs=kwargs["output_paths"]
        self.assertEqual(len([path for path in outputs if path.name.startswith("worker_")]),300)
        self.assertGreater(sum(len(str(path)) for path in outputs),32767)
        self.assertFalse(any(path.name in {"run_manifest.json","run_config.json",".private"} for path in outputs))
        self.assertEqual(functional.read_json(self.run/"run_manifest.json"),{"status":"failed"})

    def planning(self) -> tuple[dict,dict]:
        request=batching.prepare_request(self.run)
        initial=plan_simion_dispatch(request,[],available_memory_bytes=24*1024**3,total_physical_memory_bytes=48*1024**3)
        complete=plan_adaptive_followup(initial,3*1024**3,observed_cpu_percent=10,available_memory_bytes=20*1024**3,total_physical_memory_bytes=48*1024**3)
        return initial,complete

    def materialize(self,dispatch: dict) -> dict:
        plan=batch_plan_from_dispatch(dispatch)
        functional.write_json(self.run/"results/batches.json",plan)
        batching.materialize_batches(self.run,self.run/"results/batches.json")
        return plan

    def test_public_formal_first_replan_retains_live_first_inputs(self) -> None:
        initial,complete=self.planning()
        self.assertEqual(initial["waves"][0]["batches"][0]["count"],10)
        self.assertEqual(initial["estimation"]["observation_seconds"],45)
        self.materialize(initial)
        first=self.run/"simion_batch_0001"
        before=(first/"frozen_config.lua").read_bytes()
        (first/"events.csv").write_text("live worker sentinel",encoding="utf-8")
        plan=self.materialize(complete)
        self.assertEqual((first/"events.csv").read_text(),"live worker sentinel")
        self.assertEqual((first/"frozen_config.lua").read_bytes(),before)
        self.assertEqual(plan["batches"][0],initial["waves"][0]["batches"][0])
        for batch in plan["batches"]:
            folder=self.run/f"simion_batch_{batch['index']:04d}"
            self.assertEqual((folder/"processor.iob").read_bytes(),(self.run/"simion/processor.iob").read_bytes())
            relative=os.path.relpath(self.field/"processor.pa0",self.run/"simion")
            self.assertEqual((folder/relative).resolve(),(self.field/"processor.pa0").resolve())
            receipt=functional.read_json(folder/"batch_input.json")
            self.assertEqual(receipt["source_global_ids"],list(range(batch["particle_id_min"],batch["particle_id_max"]+1)))
            self.assertIn('[1]={t=0', (folder/"source_states.lua").read_text())
        changed=copy.deepcopy(plan);changed["batches"][0]["count"]+=1
        functional.write_json(self.run/"results/changed.json",changed)
        with self.assertRaises(ValueError):batching.materialize_batches(self.run,self.run/"results/changed.json")

    def test_resource_identity_separates_source_and_coordinate_contract(self) -> None:
        initial=batching.prepare_request(self.run)["case_input_sha256"]
        self.config["source"]["species"]["mass_amu"]+=1
        self.save_config()
        changed=batching.prepare_request(self.run)["case_input_sha256"]
        self.assertNotEqual(initial,changed)
        self.config["coordinate_transform"]["translation_mm"][2]+=0.1
        self.save_config()
        self.assertNotEqual(changed,batching.prepare_request(self.run)["case_input_sha256"])

    def test_trajectory_output_policy_is_frozen_in_worker_and_resource_identity(self) -> None:
        initial, _ = self.planning()
        before=batching.prepare_request(self.run)
        self.materialize(initial)
        text=(self.run/"simion_batch_0001/frozen_config.lua").read_text()
        self.assertIn('["retain_trajectories"]=false', text)
        profile=functional.read_json(self.run/"inputs/execution_profiles.json")
        profile["profiles"][0]["retain_batch_trajectories"]=True
        functional.write_json(self.run/"inputs/execution_profiles.json",profile)
        after=batching.prepare_request(self.run)
        self.assertNotEqual(before["case_input_sha256"],after["case_input_sha256"])
        self.assertNotEqual(before["field_loading_policy_id"],after["field_loading_policy_id"])

    def test_local_native_field_requires_preflight_vendor_templates(self) -> None:
        self.config["native_field"]=dict(directory=str(self.run/"simion"),source_manifest=None)
        (self.run/"simion/processor.pa0").write_bytes(b"inert local field")
        self.save_config()
        request=batching.prepare_request(self.run)
        meta=functional.read_json(self.run/"inputs/batch_iob_preparation.json")
        self.assertTrue(meta["requires_vendor_templates"])
        self.assertEqual(meta["template_count"],100)
        script=(self.run/"simion/build_batch_iobs.lua").read_text()
        self.assertEqual(script.count("wb:load("),1)
        self.assertEqual(script.count("wb:save("),100)
        self.assertNotIn("refine",script.lower())
        self.assertNotIn("fast_adjust",script)
        initial=plan_simion_dispatch(request,[])
        with self.assertRaisesRegex(ValueError,"receipt|template"):
            self.materialize(initial)
        # Inert template stands for the vendor-produced IOB only in this fixture.
        (self.run/"simion_batch_0001/processor.iob").write_bytes(b"native template fixture")
        self.materialize(initial)
        self.assertEqual((self.run/"simion_batch_0001/processor.iob").read_bytes(),b"native template fixture")

    def vendor_template_fixture(self) -> dict:
        self.config["native_field"] = dict(directory=str(self.run/"simion"), source_manifest=None)
        (self.run/"simion/processor.pa0").write_bytes(b"inert local native field")
        self.save_config()
        request = batching.prepare_request(self.run)
        folder = self.run/"simion_batch_0001"
        (folder/"processor.iob").write_bytes(b"vendor-rebased IOB fixture differs from canonical")
        for name in ("processor.lua", "processor.fly2"):
            canonical = self.run/"simion"/name
            if not canonical.exists():
                canonical.write_bytes(b"inert full master particle fixture")
            (folder/name).write_bytes(canonical.read_bytes())
        return plan_simion_dispatch(request, [])

    def test_vendor_save_three_file_template_is_verified_then_sliced(self) -> None:
        initial = self.vendor_template_fixture()
        folder = self.run/"simion_batch_0001"
        original_iob = (folder/"processor.iob").read_bytes()
        master_fly2 = (self.run/"simion/processor.fly2").read_bytes()
        self.materialize(initial)
        self.assertEqual((folder/"processor.iob").read_bytes(), original_iob)
        self.assertEqual((folder/"processor.lua").read_bytes(), (self.run/"simion/processor.lua").read_bytes())
        self.assertNotEqual((folder/"processor.fly2").read_bytes(), master_fly2)
        self.assertEqual((self.run/"simion/processor.fly2").read_bytes(), master_fly2)
        self.assertTrue((folder/"batch_input.json").is_file())

    def test_vendor_template_drift_or_unknown_file_is_rejected_before_overwrite(self) -> None:
        initial = self.vendor_template_fixture()
        folder = self.run/"simion_batch_0001"
        for name in ("processor.lua", "processor.fly2", "unexpected.txt"):
            with self.subTest(name=name):
                path = folder/name
                original = path.read_bytes() if path.exists() else None
                path.write_bytes(b"unapproved vendor companion fixture")
                with self.assertRaisesRegex(ValueError, "companion differs|without an immutable"):
                    self.materialize(initial)
                self.assertEqual(path.read_bytes(), b"unapproved vendor companion fixture")
                self.assertFalse((folder/"frozen_config.lua").exists())
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def populate(self,plan: dict) -> None:
        fields=["event","particle_id","reason","t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us"]
        sample_fields=["particle_id",*fields[3:]]
        expected=dict(gas_mass_amu=28,temperature_k=300,pressure_pa=0,sigma_m2=2.27e-18,mean_free_path_mm=-1,steps_per_mfp=20,random_seed=43,mark_collisions=0,trace_level=0)
        for batch in plan["batches"]:
            folder=self.run/f"simion_batch_{batch['index']:04d}"
            rows=[];samples=[];seeds=[]
            for local in range(1,batch["count"]+1):
                global_id=batch["simion_particle_id_offset"]+local
                base=dict(particle_id=local,reason="none",t_us=0,x_mm=global_id,y_mm=0,z_mm=0,vx_mm_us=1,vy_mm_us=0,vz_mm_us=0)
                rows.extend([{**base,"event":"source"},{**base,"event":"terminal","t_us":10,"reason":"timeout"}])
                samples.append({key:base[key] for key in sample_fields})
                seeds.append(dict(particle_id=local,global_particle_id=global_id,seed=41+global_id))
            batching._csv(folder/"events.csv",fields,rows)
            batching._csv(folder/"samples.csv",sample_fields,samples)
            batching._csv(folder/"collision_rng_seeds.csv",["particle_id","global_particle_id","seed"],seeds)
            batching._csv(folder/"hs1_bound_parameters.csv",["phase",*expected],[dict(phase=phase,**expected) for phase in ("before_init","after_init")])
            (self.run/f"logs/flight_batch_{batch['index']:04d}.log").write_text("INERT FIXTURE\nION_PROCESSOR_END\n",encoding="utf-8")

    def test_public_merge_restores_full_ids_and_seed_audit(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        result=batching.merge_batches(self.run,self.run/"results/batches.json")
        self.assertEqual(result["particle_count"],100)
        fields,events=batching._rows(self.run/"simion/events.csv")
        self.assertEqual(fields[0],"event")
        self.assertEqual([int(r["particle_id"]) for r in events if r["event"]=="terminal"],list(range(1,101)))
        _,seeds=batching._rows(self.run/"simion/collision_rng_seeds.csv")
        self.assertEqual([int(r["global_particle_id"]) for r in seeds],list(range(1,101)))
        self.assertEqual(len(batching._rows(self.run/"simion/hs1_bound_parameters.csv")[1]),2)

    def test_merge_rejects_missing_terminal_and_wrong_global_seed(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        folder=self.run/"simion_batch_0001"
        fields,events=batching._rows(folder/"events.csv")
        batching._csv(folder/"events.csv",fields,events[:-1])
        with self.assertRaisesRegex(ValueError,"close"):
            batching.merge_batches(self.run,self.run/"results/batches.json")
        self.populate(plan)
        fields,seeds=batching._rows(folder/"collision_rng_seeds.csv");seeds[0]["global_particle_id"]="99"
        batching._csv(folder/"collision_rng_seeds.csv",fields,seeds)
        with self.assertRaisesRegex(ValueError,"RNG"):
            batching.merge_batches(self.run,self.run/"results/batches.json")


if __name__=="__main__":unittest.main()
