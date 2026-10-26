"""Pure reference preparation and sealed-field identity regressions; no Fly."""
from __future__ import annotations

import json
import itertools
import math
from pathlib import Path
import stat
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from common.contracts import write_run_manifest as manifest_records
from common.contracts.write_run_manifest import file_record
from integrations.tests.test_cooled_frontend import cooled_request_fixture, publish_inert_fields
from integrations.tests.test_local_frontend_workflow import REPO
from integrations.workflows.cooled_frontend.prepare import prepare_cooled_frontend
from integrations.workflows.cooled_frontend.runtime import _verified_small_record, fields
from integrations.workflows.cooled_frontend import reference, runtime
from integrations.workflows.local_frontend import runtime as shared
from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.simion.particle_batching import plan_single_wave_batches


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding="utf-8")


class SharedFieldIdentityTests(unittest.TestCase):
    def setUp(self):
        # Reference science fixtures use an unmanaged inert cache. Durable pin
        # behavior is exercised with the real governed cache in test_cooled_frontend.
        validate = runtime.validate_pa_family_cache_generation
        pin_boundary = patch.object(runtime, "validate_pa_family_cache_generation",
            side_effect=lambda *a, **k: {} if k.get("require_publication_pin") else validate(*a, **k))
        pin_boundary.start()
        self.addCleanup(pin_boundary.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace=Path(self.temp.name)
        self.addCleanup(self.make_writable)
        self.request_path,self.request=cooled_request_fixture(self.workspace)
        self.owner=self.workspace/"artifacts/integrations/test_integration/runs/field_owner"
        prepare_cooled_frontend(self.request_path,self.owner,REPO,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")
        receipt=publish_inert_fields(self.owner,self.workspace/"cache")
        records=receipt["working_points"]
        profile=self.owner/"inputs/cooled_field_design_profile.json"
        write(profile,{k:receipt["receipt"][k] for k in ("geometry_record","field_plan_record")})
        manifest=self.owner/"run_manifest.json"
        config=self.owner/"run_config.json";write(config,dict(run_id="field_owner",project="instrument_assembly"))
        write(manifest,dict(status="success",run_config=file_record(config),inputs=dict(
            field_profile=file_record(profile),field_stage=file_record(Path(receipt["receipt_path"])),
            geometry=receipt["receipt"]["geometry_record"],field_plan=receipt["receipt"]["field_plan_record"],
            cache_identity=receipt["receipt"]["cache_identity_record"]),outputs=records))
        self.envelope=dict(schema_version=1,role="rf_oatof_cooled_frontend_field_source",
            field_stage_receipt_record=file_record(Path(receipt["receipt_path"])),
            source_owner_manifest_record=file_record(manifest),source_owner_profile_record=file_record(profile))
        for key in ("field_stage_receipt_record","source_owner_manifest_record","source_owner_profile_record"):
            self.envelope[key]["path"]=Path(self.envelope[key]["path"]).relative_to(self.workspace).as_posix()

    def make_writable(self):
        for path in self.workspace.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IREAD|stat.S_IWRITE)

    def test_published_fields_survive_failed_postprocessing_with_frozen_provenance(self):
        manifest=self.owner/"run_manifest.json"
        owner=json.loads(manifest.read_text());owner["status"]="failed";write(manifest,owner)
        self.envelope["source_owner_manifest_record"]=file_record(manifest)
        envelope=self.workspace/"artifacts/field_source.json";write(envelope,self.envelope)
        self.request["field_source"]=file_record(envelope);write(self.request_path,self.request)
        consumer=self.workspace/"artifacts/integrations/test_integration/runs/failed_postprocess_source"
        prepare_cooled_frontend(self.request_path,consumer,REPO,self.workspace,run_id="20261022_120000__build__python__cooled-fixture")
        with patch.object(runtime,"file_sha256",wraps=runtime.file_sha256) as checked:
            resolved=fields(consumer)
        self.assertEqual(len(resolved["records"]),7)
        self.assertEqual((consumer/"inputs/cooled_field_source_manifest.json").read_bytes(),manifest.read_bytes())
        self.assertEqual((consumer/"inputs/cooled_field_source_run_config.json").read_bytes(),(self.owner/"run_config.json").read_bytes())
        self.assertFalse(any(Path(call.args[0]).suffix==".pa" for call in checked.call_args_list))
        stage=json.loads(Path(resolved["receipt"]["path"]).read_text())
        transaction=runtime.load_pa_family_cache_transaction(self.workspace/"cache",stage["cache_key"])
        with patch.object(runtime,"load_pa_family_cache_transaction",return_value=dict(transaction,status="building")):
            with self.assertRaisesRegex(ValueError,"not published"):
                fields(consumer)

    def test_fields_hashes_each_distinct_geometry_and_plan_once(self):
        envelope=self.workspace/"artifacts/field_source.json";write(envelope,self.envelope)
        self.request["field_source"]=file_record(envelope);write(self.request_path,self.request)
        consumer=self.workspace/"artifacts/integrations/test_integration/runs/distinct_fields"
        prepare_cooled_frontend(self.request_path,consumer,REPO,self.workspace,
            run_id="20261022_120000__build__python__distinct-fields")
        for run in (self.owner,consumer):
            with patch.object(runtime,"file_sha256",wraps=runtime.file_sha256) as checked:
                resolved=fields(run)
            hashed=[Path(call.args[0]).resolve() for call in checked.call_args_list]
            for name in ("frontend.gem","cooled_field_plan.json"):
                distinct={(self.owner/"inputs"/name).resolve(),(run/"inputs"/name).resolve()}
                for path in distinct:
                    self.assertEqual(hashed.count(path),1)
                path=run/"inputs"/name;content=path.read_bytes()
                path.write_bytes(content+b"\n")
                try:
                    with self.assertRaisesRegex(ValueError,"frozen small-file identity differs|pressure control changed"):
                        fields(run)
                finally:
                    path.write_bytes(content)
            self.assertEqual(resolved["records"],fields(self.owner)["records"])
        # A shared consumer must still check the producer's separate authority.
        authority=self.owner/"inputs/frontend.gem";content=authority.read_bytes()
        authority.write_bytes(content+b"\n")
        try:
            with self.assertRaisesRegex(ValueError,"frozen small-file identity differs"):
                fields(consumer)
        finally:
            authority.write_bytes(content)

    def test_relative_identity_without_explicit_root_fails(self):
        record=self.envelope["source_owner_manifest_record"]
        with self.assertRaisesRegex(ValueError,"explicit workspace"):
            _verified_small_record(record)
        self.assertEqual(_verified_small_record(record,self.workspace),self.owner/"run_manifest.json")

    def test_workspace_relative_nested_records_and_input_receipt_are_accepted(self):
        envelope_path=self.workspace/"artifacts/field_source.json"
        write(envelope_path,self.envelope)
        self.request["field_source"]=file_record(envelope_path)
        write(self.request_path,self.request)
        consumer=self.workspace/"artifacts/integrations/test_integration/runs/reference"
        prepare_cooled_frontend(self.request_path,consumer,REPO,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")
        self.assertEqual(len(fields(consumer)["records"]),7)
        frozen=json.loads((consumer/"inputs/cooled_experiment.json").read_text())["field_source"]
        self.assertEqual(Path(frozen["path"]),consumer/"inputs/cooled_field_source.json")
        self.assertEqual((consumer/"inputs/cooled_field_source.json").read_bytes(),envelope_path.read_bytes())

    def test_authored_envelope_is_frozen_and_other_repo_paths_are_rejected(self):
        repository=self.workspace/"simulation_repo"
        authored=repository/"integrations/config/experiments/cooled_frontend/source.json"
        write(authored,self.envelope)
        record=file_record(authored);record["path"]=authored.relative_to(self.workspace).as_posix()
        self.request["field_source"]=record
        write(self.request_path,self.request)
        run=self.workspace/"artifacts/integrations/test_integration/runs/authored_consumer"
        prepare_cooled_frontend(self.request_path,run,repository,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")
        authored.unlink()
        self.assertEqual(len(fields(run)["records"]),7)
        denied=repository/"other/source.json";write(denied,self.envelope)
        self.request["field_source"]=file_record(denied);write(self.request_path,self.request)
        with self.assertRaisesRegex(ValueError,"workspace artifact identity"):
            prepare_cooled_frontend(self.request_path,None,repository,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")

    def test_two_trial_cases_and_shared_dispatch_keep_mother_source_untouched(self):
        envelope=self.workspace/"artifacts/field_source.json";write(envelope,self.envelope)
        self.request["field_source"]=file_record(envelope);write(self.request_path,self.request)
        run=self.workspace/"artifacts/integrations/test_integration/runs/multitrial"
        prepare_cooled_frontend(self.request_path,run,REPO,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")
        before=(run/"inputs/release_global.csv").read_bytes()
        ctx=shared._context(run,field_provider=fields)
        ctx.update(conditioner=shared._load(run/"inputs/conditioner_contract.json"),cooled_drive=shared._load(run/"inputs/cooled_drive.json"),
            experiment=shared._load(run/"inputs/cooled_experiment.json"),voltage_calibration=dict(inner_correction_v=0.,release_hp_common_correction_v=0.),
            hs1_source="-- pure test only; not native HS1\n",cooled_module_source=(REPO/"integrations/workflows/cooled_frontend/cooled_frontend.lua").read_text())
        row={k:float(v) for k,v in ctx["rows"][0].items()};row.update(particle_id=1,charge_state=1,instrument_time_us=100.,position_y_mm=28.)
        data=dict(source_rows=[row],voltage_calibration=ctx["voltage_calibration"],field_stage_receipt_record=fields(run)["receipt"])
        write(run/"inputs/cooled_reference_source.json",data)
        shared._write_once(run/"inputs/cooled_reference_release.csv",reference._csv_text(shared.GLOBAL_COLUMNS,[row]))
        times=[0.,100.,110.,115.,120.]
        with (patch.object(runtime,"context",return_value=ctx) as contexts,
              patch.object(reference,"prepare_reference",return_value=data),
              patch.object(shared,"_context",side_effect=AssertionError("reference context must not be built twice"))):
            first=reference.materialize_batches(run,"trial_a",plan_single_wave_batches(1,1),110.,times)
            second=reference.materialize_batches(run,"trial_b",plan_single_wave_batches(1,1),115.,times)
            self.assertEqual(contexts.call_count,2)
            self.assertNotEqual(first["batches"][0]["iob_path"],second["batches"][0]["iob_path"])
            self.assertEqual(first["mother_count"],100);self.assertEqual(first["simulated_count"],1)
            self.assertFalse(first["mother_population_flight"])
            dispatch=reference.prepare_dispatch_request(run,"trial_a",110.,times)
            self.assertEqual(dispatch["request"]["particle_count"],1)
            self.assertEqual(dispatch["request"]["workload_topology_id"],reference.TOPOLOGY)
            with self.assertRaisesRegex(ValueError,"refusing to change frozen"):
                reference.materialize_batches(run,"trial_a",plan_single_wave_batches(1,1),111.,times)
        self.assertEqual((run/"inputs/release_global.csv").read_bytes(),before)
        self.assertFalse((run/"inputs/local_runtime__extraction.json").exists())

    def test_held_off_reference_has_no_production_decision_or_source_copies(self):
        envelope=self.workspace/"artifacts/field_source.json";write(envelope,self.envelope)
        self.request["field_source"]=file_record(envelope);write(self.request_path,self.request)
        run=self.workspace/"artifacts/integrations/test_integration/runs/held_off"
        prepare_cooled_frontend(self.request_path,run,REPO,self.workspace,run_id="20261022_120000__build__python__cooled-fixture")
        hs=run/"inputs/cooled_collision_hs1.lua";hs.write_text("-- pure HS1 identity fixture")
        write(run/"inputs/cooled_hs1_identity.json",dict(adapted=file_record(hs)))
        release=self.request["drive"]["release_start_us"]
        phase=dict(role="cooled_reference_phase",pulse_mode=2,pulse_time_us=None,release_start_us=release,
                   voltage_calibration=dict(inner_correction_v=0.,release_hp_common_correction_v=0.),
                   field_identity=dict(field_stage_receipt_record=fields(run)["receipt"]))
        ctx=runtime.context(run,reference_phase=phase)
        self.assertNotIn("decision",ctx)
        self.assertEqual(ctx["cooled_drive"],self.request["drive"])
        self.assertEqual(ctx["fields"]["records"],fields(run)["records"])
        self.assertEqual(ctx["experiment"]["pressure_scale"],0)
        self.assertEqual(ctx["flight_horizon_us"],release+ctx["numerics"]["maximum_flight_us"])
        for name in ("cooled_frontend.lua","cooled_program.py","cooled_runtime.py"):
            self.assertFalse((run/"inputs/local_program_sources"/name).exists())
        for name in ("cooled_module","cooled_program.py","cooled_runtime.py"):
            self.assertTrue(Path(ctx["code_records"][name]["path"]).is_relative_to(REPO))
        before=(run/"inputs/release_global.csv").read_bytes()
        row={key:float(value) for key,value in ctx["rows"][0].items()};row.update(particle_id=1,instrument_time_us=release)
        from integrations.workflows.cooled_frontend.program import build_program
        ctx["rows"]=[row]
        case_rows=[{key:format(float(value),".17g") for key,value in row.items()}]
        runtime_phase=dict(schema_version=1,role="rf_oatof_cooled_reference_runtime_phase",phase="held_off",
                           pulse_time_us=None,pulse_mode=2,shared_times_us=[release,release+1.])
        expected=shared._case(run,"extraction","cold_reference__held_off",case_rows,ctx,runtime_phase,program_builder=build_program)
        expected_controls={key:Path(expected[key]).read_bytes() for key in ("program_path","particle_input")}
        write(run/"inputs/cooled_reference_phase__held_off.json",runtime_phase)
        with (patch.object(runtime,"fields",wraps=fields) as checked_fields,
              patch.object(shared,"_context",side_effect=AssertionError("validated context must be reused"))):
            case=runtime.materialize_reference_case(run,ctx,runtime_phase)
        checked_fields.assert_not_called()
        for key,value in expected_controls.items():
            self.assertEqual(Path(case[key]).read_bytes(),value)
        wrong_phase=dict(phase,field_identity=dict(field_stage_receipt_record=dict(ctx["fields"]["receipt"],sha256="0"*64)))
        with patch.object(runtime,"fields",wraps=fields) as checked_fields:
            with self.assertRaisesRegex(ValueError,"different actual fields"):
                runtime.context(run,reference_phase=wrong_phase)
        checked_fields.assert_called_once_with(run)
        program=Path(case["program_path"]).read_text()
        self.assertIn("pulse_mode=function() return 2 end",program)
        role=json.loads((run/"inputs/cooled_reference_role__held_off.json").read_text())
        self.assertIsNone(role["reference_phase"]["pulse_time_us"])
        self.assertNotIn("temporary_decision",role)
        self.assertEqual((run/"inputs/release_global.csv").read_bytes(),before)
        # A production context validates each closed identity once and reuses
        # that record when declaring code inputs; no second file hash is needed.
        decision_path=run/"inputs/cooled_common_pulse_decision.json"
        write(decision_path,dict(schema_version=1,role="actual_field_reference_exit_centering",
            actual_pulse_time_us=release+1.,release_start_us=release,
            voltage_calibration=phase["voltage_calibration"],field_identity=phase["field_identity"]))
        experiment_path=run/"inputs/cooled_experiment.json"
        experiment=shared._load(experiment_path)
        experiment["common_pulse_decision"]=file_record(decision_path)
        write(experiment_path,experiment)
        with (patch.object(runtime,"file_sha256",wraps=runtime.file_sha256) as validated,
              patch.object(manifest_records,"file_sha256",wraps=manifest_records.file_sha256) as recorded):
            production=runtime.context(run)
        hashed=[Path(call.args[0]).resolve() for digest in (validated,recorded) for call in digest.call_args_list]
        for name,path in (("hs1",hs),("common_pulse_decision",decision_path)):
            self.assertEqual(hashed.count(path.resolve()),1)
            self.assertEqual(production["code_records"][name],file_record(path))
            content=path.read_bytes()
            path.write_bytes(content+b"\n")
            try:
                with self.assertRaisesRegex(ValueError,"frozen small-file identity differs"):
                    runtime.context(run)
            finally:
                path.write_bytes(content)
        source=run/"inputs/release_global.csv"
        source.write_bytes(before.replace(b"\n1,",b"\n2,",1))
        self.assertNotEqual(source.read_bytes(),before)
        try:
            with self.assertRaisesRegex(ValueError,"complete ordered original source"):
                runtime.context(run)
        finally:
            source.write_bytes(before)

    def test_mesh_reuses_verified_author_identities_without_changing_physical_inputs(self):
        from integrations.tests.test_cooled_frontend_mesh_check import mesh_request_fixture
        from integrations.workflows.cooled_frontend import mesh_check

        envelope=self.workspace/"artifacts/field_source.json";write(envelope,self.envelope)
        request=mesh_request_fixture()
        source_record,envelope_record=file_record(self.request_path),file_record(envelope)
        request.update(source_request_record=source_record,field_source_record=envelope_record)
        path=self.workspace/"mesh_request.json";write(path,request)
        for prepare in (False,True):
            run=self.workspace/"artifacts/integrations/test_integration/runs/mesh_reuse" if prepare else None
            with (patch.object(runtime,"file_sha256",wraps=runtime.file_sha256) as checked,
                  patch.object(manifest_records,"file_sha256",wraps=manifest_records.file_sha256) as recorded):
                result=mesh_check.prepare_mesh_check(path,run,REPO,self.workspace,
                    run_id="20261022_120000__build__python__mesh-reuse" if prepare else None)
            hashed=[Path(call.args[0]).resolve() for digest in (checked,recorded) for call in digest.call_args_list]
            self.assertEqual(hashed.count(self.request_path.resolve()),1)
            # fields(run) owns its independent consumption boundary in Prepare.
            self.assertEqual(hashed.count(envelope.resolve()),2 if prepare else 1)
            if prepare:
                identity=shared._load(run/"inputs/mesh_parent_identity.json")
                plan=shared._load(run/"inputs/cooled_field_plan.json")
                self.assertEqual(identity["source_request_record"],source_record)
                self.assertEqual(identity["field_source_record"],envelope_record)
                self.assertEqual(plan["dirichlet_parent"]["field_source_record"],envelope_record)
                self.assertEqual(shared._load(run/"inputs/cooled_experiment.json")["field_source"],envelope_record)
                self.assertEqual((run/"inputs/release_global.csv").read_bytes(),
                                 (self.owner/"inputs/release_global.csv").read_bytes())
                self.assertEqual(plan["stage_endpoint_voltages_v"],
                                 shared._load(self.owner/"inputs/cooled_field_plan.json")["stage_endpoint_voltages_v"])
            else:
                self.assertEqual(result["source_request_record"],source_record)
                self.assertEqual(result["field_source_record"],envelope_record)
        for changed in (self.request_path,envelope):
            content=changed.read_bytes();changed.write_bytes(content+b"\n")
            try:
                with patch.object(mesh_check,"prepare_cooled_frontend",wraps=prepare_cooled_frontend) as compiler:
                    with self.assertRaisesRegex(ValueError,"frozen small-file identity differs"):
                        mesh_check.prepare_mesh_check(path,None,REPO,self.workspace)
                compiler.assert_not_called()
            finally:
                changed.write_bytes(content)

    def test_reference_probes_are_hashed_once_and_must_belong_to_the_owner(self):
        from integrations.tests.test_cooled_frontend_field_design import harmonic_response_fixture, design_arguments
        from integrations.workflows.cooled_frontend.field_design import design_voltage_controls

        responses=harmonic_response_fixture()
        design=design_voltage_controls(responses,**design_arguments())
        self.assertTrue(design["calibrated_closed_well"]["equilibrium_within_sample_bounds"])
        self.assertTrue(design["calibrated_closed_well"]["locally_positive_effective_curvature"])
        # The published analysis adds this status to the pure design result.
        design["design_status"]="proposal_computed"
        records={}
        for kind,values in responses.items():
            probe=self.owner/"results/cooled_field_probe"/(kind+".csv")
            probe.parent.mkdir(parents=True,exist_ok=True)
            values.to_csv(probe,index=False)
            records[kind]=file_record(probe)
        design.update(native_probe_records=records,
                      target_record=file_record(self.owner/"inputs/cooled_design_targets.json"))
        design_path=self.owner/"results/cooled_field_design/voltage_design.json";write(design_path,design)
        manifest_path=self.owner/"run_manifest.json";owner=shared._load(manifest_path)
        retained=[*owner["outputs"],file_record(design_path),*records.values()]
        envelope=self.workspace/"artifacts/field_source.json"
        for omit_probe in (False,True):
            owner["outputs"]=[record for record in retained
                              if not omit_probe or record!=records["carrier_off"]]
            write(manifest_path,owner)
            self.envelope["source_owner_manifest_record"]=file_record(manifest_path)
            write(envelope,self.envelope)
            self.request["field_source"]=file_record(envelope);write(self.request_path,self.request)
            run=self.workspace/"artifacts/integrations/test_integration/runs"/("missing_probe" if omit_probe else "reference_reuse")
            prepare_cooled_frontend(self.request_path,run,REPO,self.workspace,
                run_id="20261022_120000__build__python__reference-reuse")
            if omit_probe:
                with self.assertRaisesRegex(ValueError,"not bound by sealed field owner outputs"):
                    reference.prepare_reference(run)
                self.assertFalse((run/"inputs/cooled_reference_source.json").exists())
                continue
            before=(run/"inputs/release_global.csv").read_bytes()
            with (patch.object(runtime,"file_sha256",wraps=runtime.file_sha256) as checked,
                  patch.object(manifest_records,"file_sha256",wraps=manifest_records.file_sha256) as recorded):
                result=reference.prepare_reference(run)
            hashed=[Path(call.args[0]).resolve() for digest in (checked,recorded) for call in digest.call_args_list]
            for record in records.values():
                self.assertEqual(hashed.count(Path(record["path"]).resolve()),1)
            self.assertEqual(hashed.count(design_path.resolve()),1)
            expected,_=reference.cold_reference_state(design,responses["rf_differential_unit"],
                shared._load(run/"inputs/guide_contract.json"),release_start_us=self.request["drive"]["release_start_us"],
                mass_amu=524.,charge_state=1)
            self.assertEqual(result["source_rows"],[expected])
            self.assertEqual((run/"inputs/cooled_reference_release.csv").read_text(),
                             reference._csv_text(shared.GLOBAL_COLUMNS,[expected]))
            self.assertEqual((run/"inputs/release_global.csv").read_bytes(),before)
            probe=Path(records["carrier_off"]["path"]);content=probe.read_bytes();probe.write_bytes(content+b"\n")
            try:
                with self.assertRaisesRegex(ValueError,"frozen small-file identity differs"):
                    reference.prepare_reference(run)
            finally:
                probe.write_bytes(content)

    def test_production_decision_requires_successful_bound_artifact_owner(self):
        owner=self.workspace/"artifacts/projects/instrument_assembly/runs/reference_owner"
        decision=owner/"results/common_pulse_decision.json";write(decision,dict(role="actual_field_reference_exit_centering"))
        self.request["common_pulse_decision"]=file_record(decision);write(self.request_path,self.request)
        manifest=owner/"run_manifest.json"
        write(manifest,dict(role="simulation_run_manifest",status="checkpoint",inputs={},outputs=[file_record(decision)]))
        with self.assertRaisesRegex(ValueError,"successful sealed producer"):
            prepare_cooled_frontend(self.request_path,None,REPO,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")
        write(manifest,dict(role="simulation_run_manifest",status="success",inputs={},outputs=[]))
        with self.assertRaisesRegex(ValueError,"not bound"):
            prepare_cooled_frontend(self.request_path,None,REPO,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")
        write(manifest,dict(role="simulation_run_manifest",status="success",inputs={},outputs=[file_record(decision)]))
        self.assertEqual(prepare_cooled_frontend(self.request_path,None,REPO,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")["status"],"validated")
        write(owner/".run_terminal_publication.json",{})
        with self.assertRaisesRegex(ValueError,"terminal publication is incomplete"):
            prepare_cooled_frontend(self.request_path,None,REPO,self.workspace, run_id="20261022_120000__build__python__cooled-fixture")


class ReferenceTrialTests(unittest.TestCase):
    def test_each_native_trial_keeps_clock_without_duplicating_complete_events(self):
        for count in (0, 1, 2):
            with self.subTest(exit_count=count), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                source = run / "source.csv"
                source.write_text("particle_id\n1\n", encoding="utf-8")
                materialized = run / "results/trial_a_reference_batches.json"
                case = dict(source_record=file_record(source), program_record={"path": "pure_fixture.lua"}, stdout="raw_native.log")
                write(materialized, dict(batches=[case], receipt_path=str(materialized)))
                write(run / "inputs/cooled_reference_phase__trial_a.json", dict(pulse_time_us=123.))
                events = [dict(event="local_accelerator_exit", y_mm=42., instrument_time_us=124.) for _ in range(count)]
                logs = [{"path": "raw_native.log"}]
                with patch.object(reference, "parse_local_logs", return_value=(events, logs)), \
                     patch.object(reference, "_validate_lifetimes", return_value={"complete": True}):
                    result = reference.collect_trial(run, "trial_a")
                self.assertEqual(result["pulse_time_us"], 123.)
                self.assertEqual(result["status"], "exit_observed" if count == 1 else "no_unique_exit")
                self.assertEqual("exit_y_mm" in result, count == 1)
                self.assertNotIn("all_native_events", result["evidence"])
                self.assertEqual(result["evidence"]["raw_logs"], logs)
                saved = json.loads((run / "results/trial_a_reference_trial.json").read_text())
                self.assertEqual(saved["pulse_time_us"], 123.)
                self.assertNotIn("all_native_events", saved["evidence"])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 unavailable")
    def test_reference_orchestration_saves_negative_trial_and_stops_before_next_flight(self):
        code = r"""param($Support,$Root,$Negative)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Support
$script:flights=0;$script:released=0
function Invoke-FrontendRuntimePython {
 param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 if($Name-eq'reference_prepare'){return @{working_points=@(@{path='field.pa';bytes=1;sha256='A'});initial_trials=@(@{phase='trial_a';pulse_time_us=110},@{phase='trial_b';pulse_time_us=115});shared_times_path='times';metadata_path='metadata';mother_count=100}}
 if($Name-eq'reference_collect_held_off'){return @{status='window_observed';arrival_window=@{initial_trials=@(@{phase='trial_a';pulse_time_us=110},@{phase='trial_b';pulse_time_us=115})}}}
 if($Name-like'reference_collect_*'){return @{status=$(if($Negative-eq'True'){'no_unique_exit'}else{'exit_observed'});phase=$Name.Replace('reference_collect_','');pulse_time_us=$(if($script:flights-eq2){110}elseif($script:flights-eq3){115}else{112});exit_y_mm=0;evidence=@{raw_logs=@('native.log')}}}
 if($Name-like'reference_proposal_*'){return @{proposal_time_us=112;native_check_required=($Negative-eq'secant');reference_trials=@(@{status='exit_observed';pulse_time_us=115;exit_y_mm=0})}}
 if($Name-eq'reference_freeze_decision'){return @{decision=@{actual_pulse_time_us=115}}}
 throw "unexpected stage $Name"
}
function Protect-ImmutablePaSource {param($Source,$ExpectedBytes,$ExpectedSha256)}
function Unprotect-ImmutablePaSource {param($Source) $script:released++}
function Get-HostResourceBudget {param($Role,$Stage) return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes) return @{}}
function Invoke-FrontendFlightPhase {param($RunDirectory,$ProjectRunsRoot,$RepoRoot,$Python,$RuntimeModule,$SimionExe,$Limits,$Phase,$PulseTimeUs,$SharedTimesPath) $script:flights++}
function Write-RunJson {param($Path,$Value,$Depth) ConvertTo-Json -InputObject $Value -Depth $Depth|Set-Content -LiteralPath $Path}
$lease=@{};$caught=$false
try{$null=Invoke-CooledReferenceCalibration -Package @{run_dir=$Root;artifact_run_dir=$Root;input_dir=$Root;result_dir=$Root} -RepoRoot repo -Python python -SimionExe forbidden -Limits @{} -ProjectRunsRoot runs -HostLease ([ref]$lease)}
catch{if($_.Exception.Message-notlike'*no unique measured exit*'){throw};$caught=$true}
$trials=@(Get-Content (Join-Path $Root 'reference_observed_trials.json') -Raw|ConvertFrom-Json)
@{flights=$script:flights;released=$script:released;caught=$caught;trial_count=$trials.Count;pulse=$trials[0].pulse_time_us;verified=(Test-Path (Join-Path $Root 'reference_verified_trial.json'))}|ConvertTo-Json -Compress
"""
        for negative in (True, False, "secant"):
            with self.subTest(negative=negative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                script = root / "fixture.ps1"
                script.write_text(code, encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script),
                    str(REPO / "integrations/workflows/cooled_frontend/reference_support.ps1"), str(root), str(negative)],
                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                observed = json.loads(result.stdout)
                self.assertEqual(observed["flights"], 4 if negative == "secant" else 2 if negative else 3)
                self.assertEqual(observed["trial_count"], 3 if negative == "secant" else 1 if negative else 2)
                self.assertEqual(observed["pulse"], 110)
                self.assertEqual(observed["caught"], negative is True)
                self.assertEqual(observed["verified"], negative is not True)
                self.assertEqual(observed["released"], 1)


class ReferenceTheoryTests(unittest.TestCase):
    def test_measured_trilinear_field_sets_micromotion_with_correct_units_and_sign(self):
        points=[]
        for i,(x,y,z) in enumerate(itertools.product((-1.,0.,1.),repeat=3)):
            points.append(dict(name=f"well_{i}",x_mm=x,y_mm=y,z_mm=z,ex_v_per_mm=x+2*y,ey_v_per_mm=3*z,ez_v_per_mm=4*x-y))
        samples=pd.DataFrame(points)
        position=[.2,.3,.4]
        for actual,expected in zip(reference.interpolate_unit_rf(samples,position),[.8,1.2,.5],strict=True):
            self.assertAlmostEqual(actual,expected)
        well=dict(equilibrium_within_sample_bounds=True,locally_positive_effective_curvature=True,equilibrium_mr_mm=position,
                  fit_sample_bounds_mr_mm=dict(min_mm=[-1.,-1.,-1.],max_mm=[1.,1.,1.]))
        design=dict(design_status="proposal_computed",calibrated_closed_well=well)
        guide=dict(drive=dict(frequency_hz=1e6,phase_rad=math.pi/2,rf_amplitude_v=2.))
        row,evidence=reference.cold_reference_state(design,samples,guide,release_start_us=1.,mass_amu=2.,charge_state=1)
        factor=ELEMENTARY_CHARGE_C*2*1000/(2*AMU_KG*2*math.pi*1e6)
        self.assertAlmostEqual(row["velocity_y_m_s"],1.2*factor)
        self.assertEqual(row["instrument_time_us"],1.)
        self.assertEqual(evidence["secular_velocity_m_s"],[0.,0.,0.])
        well["equilibrium_mr_mm"]=[1.1,0.,0.]
        with self.assertRaisesRegex(ValueError,"outside actual fit"):
            reference.cold_reference_state(design,samples,guide,release_start_us=1.,mass_amu=2.,charge_state=1)

    def test_native_window_requires_supported_forward_branch_and_provider_duration(self):
        frontend=dict(accelerator_local_region=dict(first_gap_bounds_mm=dict(
            x_min=-1.,x_max=1.,y_min=0.,y_max=20.,z_min=-1.,z_max=1.)))
        source=dict(mass_amu=524.,charge_state=1)
        rows=[dict(event="local_trajectory",instrument_time_us=t,x_mm=0.,y_mm=t-100.,z_mm=0.,vy_mm_per_us=1.,raw_line_number=i)
              for i,t in enumerate((100.,105.,110.,115.),1)]
        passage=[dict(event="local_aperture_pre",instrument_time_us=99.,vy_mm_per_us=1.),
                 dict(event="local_aperture_post",instrument_time_us=100.,vy_mm_per_us=1.)]
        with patch.object(reference,"_nominal_extraction_duration",return_value=3.) as oracle:
            window=reference.native_arrival_window(passage+rows,frontend,source)
        oracle.assert_called_once_with(frontend,source)
        self.assertEqual([r["pulse_time_us"] for r in window["initial_trials"]],[107.,110.])
        self.assertEqual(window["center_time_us"],110.)
        self.assertEqual(window["early_time_bracket"],rows[1:3])
        self.assertEqual(window["aperture_post"],passage[1])
        with patch.object(reference,"_nominal_extraction_duration",return_value=3.), self.assertRaisesRegex(ValueError,"aperture"):
            reference.native_arrival_window(rows,frontend,source)
        for invalid in (rows[:2], [{**r,"vy_mm_per_us":-1.} for r in rows],
                        [{**r,"x_mm":2.} for r in rows],rows+rows):
            with patch.object(reference,"_nominal_extraction_duration",return_value=3.), self.assertRaises(ValueError):
                reference.native_arrival_window(passage+invalid,frontend,source)
        reversed_branch=[dict(row) for row in rows]
        reversed_branch[0]["vy_mm_per_us"]=-1.
        with patch.object(reference,"_nominal_extraction_duration",return_value=3.), self.assertRaisesRegex(ValueError,"reversed"):
            reference.native_arrival_window(passage+reversed_branch,frontend,source)
        with patch.object(reference,"_nominal_extraction_duration",return_value=20.), self.assertRaisesRegex(ValueError,"support"):
            reference.native_arrival_window(rows,frontend,source)


if __name__=="__main__":
    unittest.main()
