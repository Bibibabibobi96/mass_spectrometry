"""Solver-free batch projections and full-ID merge contracts; no physics claim."""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from common.contracts import verify_run_manifest, write_run_manifest
from common.contracts.file_identity import file_sha256
from common.simion.particle_batching import batch_plan_from_dispatch
from common.simion.resource_scheduler import plan_simion_dispatch, plan_adaptive_followup
from projects.dual_pressure_rectilinear_ion_processor.analysis import batching, functional
from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget import STEP_COLUMNS, IMPULSE_COLUMNS

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
        self.config["native_timing"]=functional.derive_native_timing(self.config["baseline"])
        self.config["native_projection"]=functional.native_projection(self.config["baseline"],self.config["numerics"])
        self.field=Path(self.temp.name)/"native"
        self.field.mkdir()
        (self.field/"processor.pa0").write_bytes(b"inert field fixture")
        self.manifest=self.field/"run_manifest.json"
        functional.write_json(self.manifest,dict(inputs={},outputs=[dict(path=str(self.field/"processor.pa0"),sha256="A"*64)]))
        self.config["native_field"]=dict(directory=str(self.field),source_manifest=str(self.manifest))
        for name in ("processor.lua","collision_hs1.lua","native_drive.lua","simion_rf_drive.lua","voltage_waveforms.lua","extraction_force_audit.lua","processor.iob"):
            (self.run/"simion"/name).write_bytes(b"inert frozen control "+name.encode())
        self.save_config()
        functional.write_json(self.run/"inputs/execution_profiles.json",functional.read_json(PROJECT/"config/execution_profiles.json"))
        functional.write_json(self.run/"run_config.json",dict(inputs={}))

    def save_config(self) -> None:
        functional.write_json(self.run/"inputs/resolved_model.json",self.config)

    def publishable_config(self) -> None:
        functional.write_json(self.run/"run_config.json", dict(
            schema_version=2, run_id="20261017_120000__test__simion__manifest-fixture",
            project=functional.PROJECT, mode="native_electrode_functional",
            project_root=str(self.run),
            inputs=dict(model="inputs/resolved_model.json", runtime=str(self.run/"simion/processor.lua")),
            artifact_retention=dict(policy_version=1, **{"class":"solver_review"}, reason="Inert native output fixture")))

    def verify_published_manifest(self) -> None:
        with patch.object(sys, "argv", ["verifier", str(self.run/"run_manifest.json")]):
            verify_run_manifest.main()

    def test_frozen_inputs_are_read_once_per_publication_stage_and_generated_assets_remain_outputs(self) -> None:
        self.publishable_config()
        field = self.run/"simion/processor.pa0"
        field.write_bytes(b"inert generated native field")
        checkpoint = self.run/"results/native_field_preparation.json"
        checkpoint.write_text('{"status":"prepared"}', encoding="utf-8")
        runtime = (self.run/"simion/processor.lua").resolve()
        with patch.object(write_run_manifest, "file_sha256", wraps=file_sha256) as reader:
            manifest = batching.publish_manifest(self.run,"success")
            self.assertEqual(sum(Path(call.args[0]).resolve()==runtime for call in reader.call_args_list),1)
            reader.reset_mock()
            self.verify_published_manifest()
            self.assertEqual(sum(Path(call.args[0]).resolve()==runtime for call in reader.call_args_list),1)
        inputs = {Path(record["path"]).resolve() for record in manifest["inputs"].values()}
        outputs = {Path(record["path"]).resolve():record for record in manifest["outputs"]}
        self.assertFalse(inputs & outputs.keys())
        self.assertIn((self.run/"inputs/resolved_model.json").resolve(), inputs)
        self.assertEqual(outputs[field.resolve()]["retention_role"],"solver_native_binary")
        self.assertIn(checkpoint.resolve(), outputs)

    def test_input_tampering_fails_full_verifier_without_duplicate_output(self) -> None:
        self.publishable_config()
        batching.publish_manifest(self.run,"success")
        runtime = self.run/"simion/processor.lua"
        payload = runtime.read_bytes()
        runtime.write_bytes(payload[:-1]+b"!")
        with self.assertRaisesRegex(AssertionError,"SHA-256 changed"):
            self.verify_published_manifest()

    def test_many_worker_outputs_use_public_manifest_api_without_argv(self) -> None:
        self.publishable_config()
        for index in range(300):
            path=self.run/"results"/("worker_"+str(index)+"_"+"x"*90+".csv")
            path.write_text("particle_id\n1\n",encoding="utf-8")
        (self.run/"run_manifest.json").write_text("{}",encoding="utf-8")
        (self.run/"results/.private").write_text("private",encoding="utf-8")
        manifest = batching.publish_manifest(self.run,"failed")
        outputs = [Path(record["path"]) for record in manifest["outputs"]]
        self.assertEqual(len([path for path in outputs if path.name.startswith("worker_")]),300)
        self.assertGreater(sum(len(str(path)) for path in outputs),32767)
        self.assertFalse(any(path.name in {"run_manifest.json","run_config.json",".private"} for path in outputs))
        with patch.object(sys,"argv",["verifier",str(self.run/"run_manifest.json"),"--require-status","failed"]):
            verify_run_manifest.main()

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
        before = batching.prepare_request(self.run)["case_input_sha256"]
        self.config["native_timing"]["primary_quench_us"] += .001
        self.save_config()
        self.assertNotEqual(before, batching.prepare_request(self.run)["case_input_sha256"])

    def test_trajectory_output_policy_is_frozen_in_worker_and_resource_identity(self) -> None:
        initial, _ = self.planning()
        before=batching.prepare_request(self.run)
        self.materialize(initial)
        self.assertEqual((self.run/"simion_batch_0001/voltage_waveforms.lua").read_bytes(),
                         (self.run/"simion/voltage_waveforms.lua").read_bytes())
        text=(self.run/"simion_batch_0001/frozen_config.lua").read_text()
        self.assertIn('["retain_trajectories"]=false', text)
        self.assertIn('["native_timing"]='+functional.lua_literal(self.config["native_timing"]),text)
        profile=functional.read_json(self.run/"inputs/execution_profiles.json")
        profile["profiles"][0]["retain_batch_trajectories"]=True
        functional.write_json(self.run/"inputs/execution_profiles.json",profile)
        after=batching.prepare_request(self.run)
        self.assertNotEqual(before["case_input_sha256"],after["case_input_sha256"])
        self.assertNotEqual(before["field_loading_policy_id"],after["field_loading_policy_id"])

    def test_waveform_dependency_is_part_of_whole_unit_identity(self) -> None:
        before = batching.prepare_request(self.run)["case_input_sha256"]
        (self.run/"simion/voltage_waveforms.lua").write_bytes(b"changed frozen arithmetic")
        self.assertNotEqual(before, batching.prepare_request(self.run)["case_input_sha256"])

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
            from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget import STEP_COLUMNS, IMPULSE_COLUMNS
            batching._csv(folder/"extraction_steps.csv", list(STEP_COLUMNS), [])
            batching._csv(folder/"extraction_impulses.csv", list(IMPULSE_COLUMNS), [])
            batching._csv(folder/"collision_rng_seeds.csv",["particle_id","global_particle_id","seed"],seeds)
            batching._csv(folder/"hs1_bound_parameters.csv",["phase",*expected],[dict(phase=phase,**expected) for phase in ("before_init","after_init")])
            (self.run/f"logs/flight_batch_{batch['index']:04d}.log").write_text(f"INERT FIXTURE\nION_PROCESSOR_END\nstatus,Fly completed. {batch['count']} splats, 2.19 seconds\n",encoding="utf-8")

    def test_public_merge_restores_full_ids_and_seed_audit(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        real_open = Path.open
        writes = []
        def track_open(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if any(flag in mode for flag in ("w", "a", "x")):
                self.assertNotEqual(path.name, "events_id_first.csv")
                if path == self.run/"simion/events.csv":
                    writes.append(path)
            return real_open(path, *args, **kwargs)
        with patch.object(Path, "open", track_open):
            result=batching.merge_batches(self.run,self.run/"results/batches.json")
        self.assertEqual(writes, [self.run/"simion/events.csv"])
        self.assertFalse(list(self.run.rglob("events_id_first.csv")))
        self.assertEqual(result["particle_count"],100)
        fields,events=batching._rows(self.run/"simion/events.csv")
        self.assertEqual(fields[0],"event")
        self.assertEqual([int(r["particle_id"]) for r in events if r["event"]=="terminal"],list(range(1,101)))
        _,seeds=batching._rows(self.run/"simion/collision_rng_seeds.csv")
        self.assertEqual([int(r["global_particle_id"]) for r in seeds],list(range(1,101)))
        self.assertEqual(len(batching._rows(self.run/"simion/hs1_bound_parameters.csv")[1]),2)

    def test_injected_merge_preserves_original_sparse_ids_and_seeds_without_rebasing(self) -> None:
        _, complete = self.planning()
        plan = self.materialize(complete)
        self.populate(plan)
        original = [2+3*index for index in range(100)]
        self.config["injected_source"] = dict(particle_ids=original, mother_particle_count=120)
        self.save_config()
        for batch in plan["batches"]:
            folder = self.run/f"simion_batch_{batch['index']:04d}"
            for name in ("events.csv", "samples.csv", "collision_rng_seeds.csv"):
                fields, rows = batching._rows(folder/name)
                for row in rows:
                    pid = original[batch["simion_particle_id_offset"] + int(row["particle_id"]) - 1]
                    row["particle_id"] = pid
                    if name == "collision_rng_seeds.csv":
                        row.update(global_particle_id=pid, seed=self.config["numerics"]["seed"]+pid-1)
                batching._csv(folder/name, fields, rows)
        result = batching.merge_batches(self.run, self.run/"results/batches.json")
        self.assertEqual(result["particle_count"], 100)
        _, events = batching._rows(self.run/"simion/events.csv")
        self.assertEqual([int(row["particle_id"]) for row in events if row["event"] == "terminal"], original)
        _, seeds = batching._rows(self.run/"simion/collision_rng_seeds.csv")
        self.assertEqual([int(row["global_particle_id"]) for row in seeds], original)

    def test_merge_requires_unique_native_completion_and_matching_count(self) -> None:
        _, complete = self.planning()
        plan = self.materialize(complete)
        first = plan["batches"][0]
        count = first["count"]
        fact = f"status,Fly completed. {count} splats, 2.19 seconds\n"
        cases = [
            ("ION_PROCESSOR_END\n", "exactly one"),
            ("ION_PROCESSOR_END\n" + fact + fact, "exactly one"),
            (f"ION_PROCESSOR_END\nstatus,Fly completed. {count+1} splats, 2.19 seconds\n", "splats differ"),
            (fact, "completion sentinel"),
        ]
        for text, error in cases:
            with self.subTest(error=error, text=text):
                self.populate(plan)
                log = self.run/f"logs/flight_batch_{first['index']:04d}.log"
                log.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, error):
                    batching.merge_batches(self.run, self.run/"results/batches.json")
                self.assertFalse((self.run/"results/batch_merge_receipt.json").exists())

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

    def test_force_csv_merge_rebases_only_particle_ids_and_preserves_protocol(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        expected=[]
        for batch in plan["batches"]:
            folder=self.run/f"simion_batch_{batch['index']:04d}"
            step={key:0 for key in STEP_COLUMNS}
            step.update(particle_id=1,step_index=2,start_t_us=7500,end_t_us=7500.01,pressure_pa=.2)
            batching._csv(folder/"extraction_steps.csv",list(STEP_COLUMNS),[step])
            impulses=[]
            for electrode in range(1,16):
                row={key:0 for key in IMPULSE_COLUMNS}
                row.update(particle_id=1,step_index=2,electrode_id=electrode,start_t_us=7500,end_t_us=7500.01,unit_integral_ex_us_per_mm=electrode*.001)
                impulses.append(row)
            batching._csv(folder/"extraction_impulses.csv",list(IMPULSE_COLUMNS),impulses)
            expected.append(batch["particle_id_min"])
        batching.merge_batches(self.run,self.run/"results/batches.json")
        fields,steps=batching._rows(self.run/"simion/extraction_steps.csv")
        self.assertEqual(tuple(fields),STEP_COLUMNS)
        self.assertEqual([int(r["particle_id"]) for r in steps],expected)
        self.assertTrue(all(r["step_index"]=="2" and r["start_t_us"]=="7500" for r in steps))
        fields,impulses=batching._rows(self.run/"simion/extraction_impulses.csv")
        self.assertEqual(tuple(fields),IMPULSE_COLUMNS)
        self.assertEqual([int(r["particle_id"]) for r in impulses],[pid for pid in expected for _ in range(15)])
        for offset in range(0,len(impulses),15):
            self.assertEqual([int(r["electrode_id"]) for r in impulses[offset:offset+15]],list(range(1,16)))
            self.assertAlmostEqual(float(impulses[offset+14]["unit_integral_ex_us_per_mm"]),.015)

    def test_force_csv_rejects_reordered_header_and_foreign_local_id(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        folder=self.run/"simion_batch_0001"
        for name,columns in (("extraction_steps.csv",STEP_COLUMNS),("extraction_impulses.csv",IMPULSE_COLUMNS)):
            with self.subTest(file=name,case="header"):
                swapped=list(columns);swapped[1],swapped[2]=swapped[2],swapped[1]
                batching._csv(folder/name,swapped,[])
                with self.assertRaisesRegex(ValueError,"force-audit header"):
                    batching.merge_batches(self.run,self.run/"results/batches.json")
                self.populate(plan)
            with self.subTest(file=name,case="foreign ID"):
                row={key:0 for key in columns};row["particle_id"]=plan["batches"][0]["count"]+1
                batching._csv(folder/name,list(columns),[row])
                with self.assertRaisesRegex(ValueError,"foreign batch force-audit ID"):
                    batching.merge_batches(self.run,self.run/"results/batches.json")
                self.populate(plan)
    def test_worker_archive_preserves_exact_bytes_and_all_loss_ids(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        originals = {}
        for batch in plan["batches"]:
            folder = self.run/f"simion_batch_{batch['index']:04d}"
            fields, events = batching._rows(folder/"events.csv")
            # Keep an explicit rejected/lost particle as well as every timeout.
            events[-1]["reason"] = "electrode_splat"
            batching._csv(folder/"events.csv", fields, events)
            for name in ("events.csv", "samples.csv", "extraction_steps.csv", "extraction_impulses.csv"):
                originals[(folder/name).relative_to(self.run).as_posix()] = (folder/name).read_bytes()
        batching.merge_batches(self.run,self.run/"results/batches.json")
        found = {}
        archives = list((self.run/"results").glob("merged_worker_csv_batch_*.zip"))
        self.assertEqual(len(archives), len(plan["batches"]))
        for archive in archives:
            with zipfile.ZipFile(archive) as bundle:
                self.assertIsNone(bundle.testzip())
                for name in bundle.namelist():
                    self.assertNotIn(name, found)
                    found[name] = bundle.read(name)
                    self.assertFalse((self.run/name).exists())
        self.assertEqual(found, originals)
        receipt = functional.read_json(self.run/"results/merged_worker_csv_archive_receipt.json")
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual({name for batch in receipt["batches"] for name in batch["removed_files"]}, set(originals))
        _, events = batching._rows(self.run/"simion/events.csv")
        terminals = [row for row in events if row["event"] == "terminal"]
        self.assertEqual([int(row["particle_id"]) for row in terminals], list(range(1,101)))
        self.assertEqual(sum(row["reason"] == "electrode_splat" for row in terminals), len(plan["batches"]))
        for batch in plan["batches"]:
            folder=self.run/f"simion_batch_{batch['index']:04d}"
            for name in ("collision_rng_seeds.csv", "hs1_bound_parameters.csv", "batch_input.json", "processor.lua"):
                self.assertTrue((folder/name).is_file())

    def test_corrupt_worker_archive_cannot_remove_any_source(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        originals = {path: path.read_bytes() for path in self.run.glob("simion_batch_*/*.csv")}
        verifier = batching._verify_worker_archive
        def corrupt_then_verify(archive: Path, records: list[dict]) -> None:
            # A structurally valid zip and valid CRC still must fail byte/SHA identity.
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for record in records:
                    bundle.writestr(record["path"], b"corrupted evidence")
            verifier(archive, records)
        with patch.object(batching, "_verify_worker_archive", side_effect=corrupt_then_verify):
            with self.assertRaisesRegex(ValueError, "archive identity differs"):
                batching.merge_batches(self.run,self.run/"results/batches.json")
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list((self.run/"results").glob("merged_worker_csv_batch_*_archive_plan.json")))

    def test_worker_archive_false_flag_preserves_plain_worker_csv(self) -> None:
        profile = functional.read_json(self.run/"inputs/execution_profiles.json")
        profile["profiles"][0]["archive_merged_worker_csv"] = False
        functional.write_json(self.run/"inputs/execution_profiles.json", profile)
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        batching.merge_batches(self.run,self.run/"results/batches.json")
        self.assertFalse(list((self.run/"results").glob("merged_worker_csv_batch_*.zip")))
        for batch in plan["batches"]:
            for name in ("events.csv", "samples.csv"):
                self.assertTrue((self.run/f"simion_batch_{batch['index']:04d}"/name).is_file())

    def test_worker_archive_removal_failure_preserves_archive_and_progress(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        remover = batching.remove_recorded_files
        def fail_after_one(root: Path, records: list[dict]):
            yield from remover(root, records[:1])
            raise OSError("injected removal interruption")
        with patch.object(batching, "remove_recorded_files", side_effect=fail_after_one):
            with self.assertRaisesRegex(OSError, "injected removal"):
                batching.merge_batches(self.run,self.run/"results/batches.json")
        archived = functional.read_json(self.run/"results/merged_worker_csv_batch_0001_archive_plan.json")
        receipt = functional.read_json(self.run/"results/merged_worker_csv_batch_0001_archive_receipt.json")
        self.assertEqual(receipt["status"], "removal_failed")
        self.assertEqual(receipt["removed_files"], [archived["source_files"][0]["path"]])
        batching._verify_worker_archive(self.run/"results/merged_worker_csv_batch_0001.zip", archived["source_files"])
        for record in archived["source_files"][1:]:
            self.assertTrue((self.run/record["path"]).is_file())

    def test_worker_archive_removes_first_raw_before_second_sample_is_opened(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        first=self.run/f"simion_batch_{plan['batches'][0]['index']:04d}"
        second=self.run/f"simion_batch_{plan['batches'][1]['index']:04d}"/"samples.csv"
        real_open=Path.open
        merge_started=False
        observed=[]
        def tracked_open(path, *args, **kwargs):
            nonlocal merge_started
            if path == self.run/"simion/samples.csv":
                merge_started=True
            if merge_started and path == second:
                self.assertFalse((first/"samples.csv").exists())
                self.assertFalse((first/"events.csv").exists())
                self.assertTrue((self.run/"results/merged_worker_csv_batch_0001.zip").is_file())
                observed.append(True)
            return real_open(path, *args, **kwargs)
        with patch.object(Path, "open", tracked_open):
            batching.merge_batches(self.run,self.run/"results/batches.json")
        self.assertTrue(observed)

    def test_later_canonical_merge_failure_retains_earlier_archive_and_remaining_raw(self) -> None:
        _,complete=self.planning();plan=self.materialize(complete);self.populate(plan)
        original = (self.run/"simion_batch_0001/samples.csv").read_bytes()
        real_merge = batching.merge_rebased_particle_csvs
        def fail_later(sources, output):
            if output != self.run/"simion/samples.csv":
                return real_merge(sources, output)
            iterator = iter(sources)
            real_merge([next(iterator)], output)
            next(iterator)  # Archives the first consumed source before yielding the second.
            raise ValueError("injected later canonical merge failure")
        with patch.object(batching, "merge_rebased_particle_csvs", side_effect=fail_later):
            with self.assertRaisesRegex(ValueError, "later canonical"):
                batching.merge_batches(self.run,self.run/"results/batches.json")
        with zipfile.ZipFile(self.run/"results/merged_worker_csv_batch_0001.zip") as bundle:
            self.assertEqual(bundle.read("simion_batch_0001/samples.csv"), original)
        self.assertFalse((self.run/"simion_batch_0001/samples.csv").exists())
        self.assertTrue((self.run/"simion_batch_0002/samples.csv").exists())
        self.assertFalse((self.run/"results/batch_merge_receipt.json").exists())
        self.assertFalse((self.run/"results/merged_worker_csv_archive_receipt.json").exists())

    def test_worker_archive_policy_requires_explicit_frozen_boolean(self) -> None:
        profile = functional.read_json(self.run/"inputs/execution_profiles.json")
        for value in (None, "true", 1):
            profile["profiles"][0]["archive_merged_worker_csv"] = value
            functional.write_json(self.run/"inputs/execution_profiles.json", profile)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "must be boolean"):
                batching.prepare_request(self.run)
        del profile["profiles"][0]["archive_merged_worker_csv"]
        functional.write_json(self.run/"inputs/execution_profiles.json", profile)
        with self.assertRaises(KeyError):
            batching.prepare_request(self.run)


if __name__=="__main__":unittest.main()
