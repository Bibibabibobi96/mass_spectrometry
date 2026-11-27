from __future__ import annotations
from msplatform.backends.simion.native_completion import retention_api as _manifest_retention_api
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from msplatform.contracts.machine_contracts import load_json
from msplatform.workflows.oa_candidate.candidate_source_closure import freeze_candidate_source_closure
from msplatform.workflows.oa_candidate import run_candidate_workflow as candidate_workflow
from tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_support.candidate_fixtures import CandidateFixtures, PROJECT_ROOT, REPO_ROOT
from tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_candidate_workflow import (
    cold_export_failed_child_fixture,
    postprocess_source_fixture,
)


class CandidatePostprocessTests(unittest.TestCase):
    def test_stopped_scientific_gate_failure_preserves_complete_raw_exports(self):
        from types import SimpleNamespace
        from msplatform.backends.simion.native_stage_completion import append_native_stage_completion
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        from msplatform.workflows.oa_candidate import candidate_comsol_stage
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root/"source",cold=True)
            selected=select_postprocess_parent(parent,artifact)
            closure=freeze_candidate_source_closure(root/"code",artifact/"projects"/"single_reflection_oa_tof_mass_analyzer", science_root=REPO_ROOT,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            child=root/"child"
            for name in ("inputs","logs","results"):
                (child/name).mkdir(parents=True,exist_ok=True)
            plan={"run_id":child.name,"run_root":str(child),"context_sha256":"software-fixture",
                "writer_completion":{"operations":[],"resource_releases":[]},"postprocess_evidence":{},
                "host_context": dict(workspace=str(root), python_executable=sys.executable,
                    host_state_path=str(root / "TEST_ONLY_HOST.sqlite3"),
                    policy_path=str(PROJECT_ROOT.parents[1] / "src/msplatform/execution/resources/host_resource_policy.json")),
                "execution_run_directory": str(child),
                "source_execution_context":{"schema_version":1,"role":"run_source_execution_context",
                    "child_run_directory":str(child),"request_sha256":"software-fixture",
                    "sources":[{"target_directory":str(parent),"execution_directory":str(parent),
                        "input_paths":[selected["model_record"]["path"],selected["context_record"]["path"]]}]}}
            before={str(path):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            def stopped_export(command,log,actual_plan,receipt,role):
                import csv
                events=child/"results/comsol_detector_events_Fixture.csv"
                with events.open("w",encoding="utf-8",newline="") as stream:
                    writer=csv.writer(stream)
                    writer.writerow(["Ion","TofUs","XMm","YMm","Hit","Status","Event","DetectorRadiusMm","X0Mm","Y0Mm","Z0Mm"])
                    writer.writerows([index+1,40+index*.001,0,0,index!=99,"detector_hit" if index!=99 else "unresolved","crossing" if index!=99 else "no_plane_event",0,0,0,0] for index in range(100))
                request=child/"results/comsol_detector_events_Fixture.analysis_request.json"
                request.write_text(json.dumps({"schema_version":1,"role":"oatof_comsol_detector_events_analysis_request",
                    "solver":"COMSOL","label":"Fixture","nominal_mass_Da":524,"raw_events_csv":str(events),
                    "analysis_output_dir":str(child/"results/analysis"),"event_extraction":"solver_native_detector_crossing_or_freeze",
                    "aggregate_metrics_owner":"python_reference_analysis"}),encoding="utf-8")
                observed=load_json(parent/"logs/comsol_build_completion.json")
                observed["run_id"]=child.name
                receipt.write_text(json.dumps(observed),encoding="utf-8")
                append_native_stage_completion(actual_plan["writer_completion"],receipt,role=role,run_id=child.name)
                raise RuntimeError("EVENT_WINDOW_SENTINEL nP=100 nDet=99 complete=99")
            with mock.patch.dict(os.environ, {
                "MASS_SPECTROMETRY_HOST_CONTEXT_JSON": json.dumps(dict(workspace=str(root), python_executable=sys.executable,
                    host_state_path=str(root / "TEST_ONLY_HOST.sqlite3"), policy_path=str(PROJECT_ROOT.parents[1] / "src/msplatform/execution/resources/host_resource_policy.json"))),
                "MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY": str(child),
            }), \
                    mock.patch.object(candidate_comsol_stage,"analyze_detector_request") as analyze:
                with self.assertRaisesRegex(RuntimeError,"EVENT_WINDOW_SENTINEL"):
                    candidate_comsol_stage.execute_saved_postprocess(selected,child,closure,plan,
                        runtime=SimpleNamespace(_run_command=lambda *args,**kwargs:None,_run_managed_stage_command=stopped_export))
            analyze.assert_not_called()
            self.assertTrue(plan["postprocess_evidence"]["detector_exports_ready"])
            self.assertNotIn("writer_completion_unconfirmed",plan["postprocess_evidence"])
            self.assertTrue(Path(plan["postprocess_evidence"]["raw_events_csv"]).is_file())
            self.assertEqual(before,{str(path):path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_csv_child_science_aliases_require_original_consensus(self):
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        for conflict in (False,True):
            with self.subTest(conflict=conflict),tempfile.TemporaryDirectory() as directory:
                artifact,science,child,_=cold_export_failed_child_fixture(Path(directory),resolved_alias=True,science_alias_conflict=conflict)
                if conflict:
                    with self.assertRaisesRegex(ValueError,"manifest aliases disagree"):
                        select_postprocess_parent(child,artifact)
                else:
                    selected=select_postprocess_parent(child,artifact)
                    self.assertIsNotNone(selected["exports"])
                    self.assertIsNone(selected["model_record"])


    def test_completion_request_content_identity_rejects_rebound_records(self):
        from msplatform.execution.retention import verify_record
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent

        for case in ("role_only", "same_bytes_wrong_path", "wrong_bytes", "wrong_hash"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                def author_request(request):
                    self.assertNotIn("retention_role", request)
                    if case == "same_bytes_wrong_path":
                        duplicate = Path(directory) / "same_request_bytes.json"
                        duplicate.write_bytes(Path(request["path"]).read_bytes())
                        self.assertEqual(duplicate.read_bytes(), Path(request["path"]).read_bytes())
                        request["path"] = str(duplicate)
                    elif case == "wrong_bytes":
                        request["bytes"] += 1
                    elif case == "wrong_hash":
                        request["sha256"] = "0" * 64
                    return request

                artifact, parent, _, _ = postprocess_source_fixture(
                    Path(directory), cold=True, request_record_transform=author_request)
                manifest = load_json(parent / "run_manifest.json")
                self.assertIn("retention_role", manifest["inputs"]["execution_request"])
                completion_record = next(record for record in manifest["outputs"]
                                         if Path(record["path"]).name == "execution_completion.json")
                # Author before the first seal; test the nested binding, not outer corruption.
                verify_record("published completion", completion_record, base_dir=parent)
                if case == "role_only":
                    self.assertIsNone(select_postprocess_parent(parent, artifact)["exports"])
                elif case == "same_bytes_wrong_path":
                    with self.assertRaisesRegex(ValueError, "Public completion and original request/config identity differ"):
                        select_postprocess_parent(parent, artifact)
                else:
                    with self.assertRaisesRegex(AssertionError, "original completion request.*(?:byte count|SHA-256) changed"):
                        select_postprocess_parent(parent, artifact)

    def test_saved_dependency_aliases_require_complete_identity_consensus(self):
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        cases = (("same", None, None), ("case_normalized", "sha256", "lower"),
                 ("bytes_conflict", "bytes", -1), ("sha_conflict", "sha256", "0" * 64),
                 ("missing_alias", "exists", False))
        for name, field, value in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                artifact, parent, _, _ = postprocess_source_fixture(Path(directory), cold=True, resolved_alias=True)
                manifest_path = parent / "run_manifest.json"
                manifest = load_json(manifest_path)
                aliases = manifest["inputs"]
                self.assertEqual(aliases["candidate_resolved_geometry.json"]["path"],
                                 aliases["simion_candidate_input_001"]["path"])
                if field:
                    alias = aliases["simion_candidate_input_001"]
                    alias[field] = alias[field].lower() if value == "lower" else value
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                before = {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                if name in {"same", "case_normalized"}:
                    selected = select_postprocess_parent(parent, artifact)
                    self.assertIsNone(selected["exports"])
                else:
                    with self.assertRaisesRegex(ValueError, "Saved dependency.*manifest"):
                        select_postprocess_parent(parent, artifact)
                self.assertEqual(before, {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_saved_inventory_duplicates_are_preserved_until_guarded_cold_read(self):
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        cases = (("duplicate", [0, 1e-6, 1e-6, 2e-6], True),
                 ("all_equal", [0, 0], False), ("decreasing", [0, 1e-6, 0], False),
                 ("nonfinite", [0, float("nan"), 1e-6], False))
        for name, times, accepted in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                artifact, parent, _, _ = postprocess_source_fixture(Path(directory), cold=True, solution_times=times)
                before = {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                if accepted:
                    selection = select_postprocess_parent(parent, artifact)
                    self.assertIsNone(selection["exports"])
                    context = load_json(parent / "comsol/model.mph.postprocess.json")
                    self.assertEqual(context["solution_times_s"], times)
                else:
                    with self.assertRaisesRegex(ValueError, "original finite increasing solution times"):
                        select_postprocess_parent(parent, artifact)
                self.assertEqual(before, {str(path): path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_native_execution_paths_use_actual_public_owner_and_preserve_identity(self):
        from tests.contracts.test_support.run_artifact_workflow import CALLBACK, RunArtifactWorkflowFixture
        from msplatform.workflows.oa_candidate.prepare_candidate_run import candidate_native_execution_relative_paths
        relative = "inputs/code/" + "deep/" * 26 + "actual_native_task.m"
        declared = candidate_native_execution_relative_paths({"sources": []}, code_relative_root=Path("inputs/code"))
        self.assertIn("inputs/native_run_config.json", declared)
        extra = """    from msplatform.workflows.oa_candidate.run_candidate_workflow import _native_stage_execution_view, _persist_native_json_paths, _run_command
    import subprocess
    task = root / payload['native_relative']
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text('% inert task, never executed', encoding='utf-8')
    source = root / 'inputs/source.ion'
    source.write_text('original-source', encoding='utf-8')
    native_config = root / 'run_config.json'
    doc = json.loads(native_config.read_text(encoding='utf-8-sig'))
    doc['inputs']['particle_table'] = str(source)
    native_config.write_text(json.dumps(doc), encoding='utf-8')
    frozen_before = native_config.read_bytes()
    argv, env = _native_stage_execution_view([sys.executable, str(task)], {'OATOF_CANDIDATE_RUN_CONFIG_PATH':str(native_config)}, {'run_root':str(root)})
    assert len(argv[1]) <= 259 and argv[1] != str(task)
    assert Path(argv[1]).read_bytes() == task.read_bytes()
    transport = json.loads(Path(env['OATOF_CANDIDATE_RUN_CONFIG_PATH']).read_text(encoding='utf-8'))
    assert transport['inputs']['particle_table'] != str(source)
    assert Path(transport['inputs']['particle_table']).read_bytes() == source.read_bytes()
    assert native_config.read_bytes() == frozen_before
    observed = subprocess.run([sys.executable, '-I', '-B', '-c', 'pass'], cwd=os.environ['MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY'], capture_output=True, text=True, encoding='utf-8', check=True)
    failed_log = Path(os.environ['MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY']) / 'logs/inert_failed.log'
    try:
        _run_command([sys.executable, '-I', '-B', '-c', "print('inert diagnostic');raise SystemExit(17)"], failed_log)
    except RuntimeError as error:
        assert 'exit code 17' in str(error)
        assert str(root / 'logs/inert_failed.log') in str(error) and str(failed_log) not in str(error)
    else:
        raise AssertionError('Expected inert child failure was not propagated')
    native_request = root / 'results/inert.analysis_request.json'
    native_request.write_text(json.dumps({'path':argv[1]}), encoding='utf-8')
    _persist_native_json_paths({'run_root':str(root)})
    assert json.loads(native_request.read_text(encoding='utf-8'))['path'] == str(task)
    config = json.loads(config_path.read_text(encoding='utf-8'))
"""
        callback = CALLBACK.replace('    counter = Path(payload["counter_path"])', extra + '    counter = Path(payload["counter_path"])')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = RunArtifactWorkflowFixture()
            with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_EXECUTION_ROOT": str(root / "x")}):
                result, run, _, outcome = fixture.invoke_fixture(root, {"native_relative":relative}, callback_text=callback, expected_execution_relative_paths=[relative, *declared])
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr + json.dumps(result) + "\n".join(path.read_text(encoding="utf-8",errors="replace") for path in (run / "logs").glob("*.log")))
            self.assertTrue(result['execution_alias_removed'])
            self.assertIn('inert diagnostic', (run / 'logs/inert_failed.log').read_text(encoding='utf-8'))
            persisted = load_json(run / 'inputs/native_run_config.json')
            self.assertEqual(persisted['inputs']['particle_table'], str(run / 'inputs/source.ion'))

    def test_native_runtime_reservation_uses_frozen_budget_and_csv_stays_light(self):
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for cold in (False,True):
                with self.subTest(cold=cold):
                    artifact,parent,_,_=postprocess_source_fixture(root/str(cold),cold=cold)
                    before={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                    selected=select_postprocess_parent(parent,artifact)
                    budget=load_json(Path(selected["budget_record"]["path"]))["artifact_capacity"]
                    self.assertEqual(selected["native_runtime_bytes"],budget["comsol_bytes"] if cold else 0)
                    self.assertEqual(selected["new_bytes"],budget["evidence_bytes"]+(budget["comsol_bytes"] if cold else 0))
                    self.assertEqual(before,{str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()})
            artifact,parent,_,_=postprocess_source_fixture(root/"insufficient",cold=True,comsol_bytes=2)
            with self.assertRaisesRegex(ValueError,"COLD_RUNTIME_RESERVATION_INSUFFICIENT"):
                select_postprocess_parent(parent,artifact)

    def test_normal_comsol_commands_transport_the_owner_runtime_directory(self):
        from types import SimpleNamespace
        from msplatform.workflows.oa_candidate import candidate_comsol_stage as adapter
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/"run";(run/"logs").mkdir(parents=True)
            execution=root/"execution";execution.mkdir()
            closure=freeze_candidate_source_closure(run/"inputs/code",root/"artifacts", science_root=REPO_ROOT,
                resolved_contract=PROJECT_ROOT/"config/resolved_geometry.json",
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            request=run/"analysis_request.json";request.write_text("{}",encoding="utf-8")
            commands=[]
            def observe(command,log,plan,receipt,role,environment):
                commands.append(command)
                report=Path(command[command.index("-ReportPath")+1])
                report.write_text("STATUS=PASS\nPYTHON_ANALYSIS_REQUEST="+str(request)+"\n",encoding="utf-8")
            runtime=SimpleNamespace(_verify_frozen_cad_python=lambda *args:sys.executable,_run_managed_stage_command=observe,
                _record_candidate_native_completion=lambda *args:True)
            stage={"environment":{},"report_path":str(run/"logs/build.txt"),"model_path":str(run/"model.mph"),"contract_path":str(PROJECT_ROOT/"config/resolved_geometry.json")}
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution),"MASS_SPECTROMETRY_HOST_CONTEXT_JSON": json.dumps(dict(workspace=str(root), python_executable=sys.executable, host_state_path=str(root / "TEST_ONLY_HOST.sqlite3"), policy_path=str(PROJECT_ROOT.parents[1] / "src/msplatform/execution/resources/host_resource_policy.json")))}), \
                    mock.patch.object(adapter,"analyze_detector_request",return_value=run/"analysis_receipt.json"):
                adapter.execute_comsol_stage(stage,{"execution_source_closure":closure,"run_root":str(run),"run_id":run.name,
                "host_context":CandidateFixtures.host_context(run),"execution_run_directory":str(execution)},sys.executable,runtime=runtime)
            self.assertEqual(len(commands),2)
            from msplatform.workflows.oa_candidate.candidate_cad_stage import execute_cad_stage
            def stop_cad(command,*args):
                commands.append(command)
                raise RuntimeError("STOP_AT_CAD_NATIVE_BOUNDARY")
            runtime._run_managed_stage_command=stop_cad
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution),"MASS_SPECTROMETRY_HOST_CONTEXT_JSON": json.dumps(dict(workspace=str(root), python_executable=sys.executable, host_state_path=str(root / "TEST_ONLY_HOST.sqlite3"), policy_path=str(PROJECT_ROOT.parents[1] / "src/msplatform/execution/resources/host_resource_policy.json")))}):
                with self.assertRaisesRegex(RuntimeError,"STOP_AT_CAD_NATIVE_BOUNDARY"):
                    execute_cad_stage(dict(stage,output_dir=str(run/"cad")),
                        {"execution_source_closure":closure,"run_root":str(run),"run_id":run.name,
                         "host_context":CandidateFixtures.host_context(run),"execution_run_directory":str(execution)},sys.executable,runtime=runtime)
            self.assertEqual(len(commands),3)
            self.assertEqual([command[command.index("-RunDir")+1] for command in commands],[str(execution)]*3)
            self.assertFalse((run/"model.mph").exists())
            self.assertFalse((run/"cad/oaTOF_solidworks_export_report.json").exists())




    def test_sealed_exports_need_no_model_and_unknown_writer_is_rejected(self):
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            artifact,parent,config,outputs=postprocess_source_fixture(Path(directory))
            selected=select_postprocess_parent(parent,artifact)
            self.assertIsNone(selected["model_record"])
            self.assertIsNone(selected["context_record"])
            self.assertEqual(selected["exports"]["events"]["path"],str(outputs[0]))
            self.assertFalse(list(parent.rglob("*.mph")))
            artifact,parent,_,_=postprocess_source_fixture(Path(directory)/"unknown",unknown=True)
            with self.assertRaisesRegex(ValueError,"SOURCE_WRITER_UNCONFIRMED"):
                select_postprocess_parent(parent,artifact)

    def test_declared_missing_csv_is_not_silently_replaced_by_cold_solve(self):
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            artifact,parent,_,outputs=postprocess_source_fixture(Path(directory))
            outputs[0].unlink()
            with self.assertRaisesRegex(ValueError,"missing or incomplete"):
                select_postprocess_parent(parent,artifact)

    def test_frozen_only_analyzer_consumes_small_export_and_parent_is_unchanged(self):
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        from msplatform.workflows.oa_candidate.candidate_comsol_stage import execute_saved_postprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            before={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            selected=select_postprocess_parent(parent,artifact)
            frozen=freeze_candidate_source_closure(root/"code",artifact/"projects"/"single_reflection_oa_tof_mass_analyzer", science_root=REPO_ROOT,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            child=root/"child"
            (child/"inputs").mkdir(parents=True)
            (child/"logs").mkdir()
            with mock.patch.object(candidate_workflow,"_run_managed_stage_command",side_effect=AssertionError("native must not start")):
                result=execute_saved_postprocess(selected,child,frozen,
                    {"host_context":CandidateFixtures.host_context(child)},runtime=candidate_workflow)
            self.assertEqual(result["native_launch_count"],0)
            self.assertFalse(result["parent_model_saved"])
            self.assertTrue(Path(result["analysis_receipt"]).is_file())
            self.assertEqual(before,{str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()})



    def test_cold_dispatch_projects_actual_task_but_keeps_frozen_request_canonical(self):
        from msplatform.workflows.oa_candidate.candidate_comsol_stage import execute_saved_postprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            child=root/"child"
            (child/"inputs").mkdir(parents=True)
            (child/"logs").mkdir()
            frozen=freeze_candidate_source_closure(child/"inputs/code",root/"artifacts", science_root=REPO_ROOT,
                resolved_contract=PROJECT_ROOT/"config/resolved_geometry.json",
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            selection={"exports":None,"model_record":{"path":str(root/"parent/model.mph")},
                "context_record":{"path":str(root/"parent/model.mph.postprocess.json")},"parent":str(root/"parent")}
            observed=[]
            def stop(command,log,plan,receipt,role):
                observed.append(command)
                raise RuntimeError("STOP_AT_NATIVE_BOUNDARY")
            execution=root/"execution"
            execution.mkdir()
            source_execution=root/"source_execution"
            source_execution.mkdir()
            plan={"context_sha256":"a"*64,
                "host_context": dict(workspace=str(root), python_executable=sys.executable,
                    host_state_path=str(root / "TEST_ONLY_HOST.sqlite3"),
                    policy_path=str(PROJECT_ROOT.parents[1] / "src/msplatform/execution/resources/host_resource_policy.json")),
                "execution_run_directory": str(execution),
                "source_execution_context":{
                "schema_version":1,"role":"run_source_execution_context","request_sha256":"a"*64,
                "child_run_directory":str(child),"execution_root":str(root),"sources":[{
                    "target_directory":selection["parent"],"execution_directory":str(source_execution),
                    "execution_alias":str(source_execution),"input_paths":[selection["model_record"]["path"],selection["context_record"]["path"]]}]}}
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution),"MASS_SPECTROMETRY_HOST_CONTEXT_JSON": json.dumps(dict(workspace=str(root), python_executable=sys.executable, host_state_path=str(root / "TEST_ONLY_HOST.sqlite3"), policy_path=str(PROJECT_ROOT.parents[1] / "src/msplatform/execution/resources/host_resource_policy.json")))}), \
                    mock.patch.object(candidate_workflow,"_run_managed_stage_command",side_effect=stop):
                with self.assertRaisesRegex(RuntimeError,"STOP_AT_NATIVE_BOUNDARY"):
                    execute_saved_postprocess(selection,child,frozen,plan,runtime=candidate_workflow)
            command=observed[0]
            self.assertEqual(command[command.index("-TaskScript")+1],str(execution/"inputs/cold_postprocess.m"))
            self.assertEqual(command[command.index("-StartupAttempts")+1],"1")
            self.assertEqual(command[command.index("-RunDir")+1],str(execution))
            request=load_json(child/"inputs/cold_request.json")
            self.assertEqual(request["output_dir"],str(child/"results"))
            self.assertEqual(request["child_run_directory"],str(child))
            self.assertEqual(request["model_path"],selection["model_record"]["path"])
            task=(child/"inputs/cold_postprocess.m").read_text(encoding="utf-8")
            self.assertIn(str(source_execution/"model.mph"),task)
            self.assertIn(str(source_execution/"model.mph.postprocess.json"),task)
            self.assertFalse((child/"results/cold_postprocess_result.json").exists())


    def test_postprocess_export_parent_rejects_missing_unknown_and_tampered_exports(self):
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        for case in ("missing","unknown","tampered","wrong_source"):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                artifact,_,parent,events=cold_export_failed_child_fixture(Path(directory),unknown=case=="unknown",wrong_source=case=="wrong_source")
                if case=="missing":
                    events.unlink()
                elif case=="tampered":
                    content=events.read_text(encoding="utf-8")
                    events.write_text(content.replace("detector_hit","detector_bad",1),encoding="utf-8",newline="")
                with self.assertRaises((ValueError,AssertionError)):
                    select_postprocess_parent(parent,artifact)


    def test_flat_exporter_cannot_substitute_another_science_owner(self):
        from msplatform.execution.capacity_ledger import record_capacity_object
        from msplatform.execution.retention import file_record
        from msplatform.execution.manifest_publication import publish_run_manifest
        from msplatform.workflows.oa_candidate.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,science,_,_=postprocess_source_fixture(root/"science")
            foreign_root,_,foreign,_=cold_export_failed_child_fixture(root/"foreign")
            source=select_postprocess_parent(science,artifact)
            other=select_postprocess_parent(foreign,foreign_root)
            source["exports"]=other["exports"]
            source["export_source_reference"]=other["export_source_reference"]
            parent=artifact/"projects"/"single_reflection_oa_tof_mass_analyzer"/"runs/20261031_134000__analysis__python__wrong-exporter"
            (parent/"inputs").mkdir(parents=True)
            (parent/"results").mkdir()
            selection=parent/"inputs/postprocess_source_selection.json"
            selection.write_text(json.dumps(source),encoding="utf-8")
            request=parent/"inputs/execution_request.json"
            request.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_request",
                "package":{"project":"single_reflection_oa_tof_mass_analyzer","run_id":parent.name,"mode":"candidate_comsol_postprocess"}}),encoding="utf-8")
            config=parent/"run_config.json"
            config.write_text(json.dumps({"schema_version":2,"project":"single_reflection_oa_tof_mass_analyzer","run_id":parent.name,
                "mode":"candidate_comsol_postprocess","project_root":str(PROJECT_ROOT),
                "inputs":{"execution_request":str(request),"postprocess_source_selection":str(selection)},
                "provenance":{"science_reference":source["science_reference"]},
                "artifact_retention":{"policy_version":1,"class":"compact","reason":None},
                "capacity_ledger_lifecycle":{"schema_version":1,"enabled":True,"artifact_root":str(artifact),"light_evidence_budget_bytes":67108864}}),encoding="utf-8")
            completion=parent/"results/execution_completion.json"
            completion.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_completion",
                "project":"single_reflection_oa_tof_mass_analyzer","run_id":parent.name,"status":"failed","execution_request":file_record(request),
                "run_config":file_record(config),"writer_completion":{"operations":[],"resource_releases":[]},
                "summary":{"source_identity_verified":True}}),encoding="utf-8")
            publish_run_manifest(config,"failed",output_paths=[completion], retention_api=_manifest_retention_api)
            record_capacity_object(artifact,path=parent,object_class="light_evidence",bytes_count=sum(
                path.stat().st_size for path in parent.rglob("*") if path.is_file()),owner="single_reflection_oa_tof_mass_analyzer")
            before={str(path):path.read_bytes() for owner in (science,foreign,parent) for path in owner.rglob("*") if path.is_file()}
            with self.assertRaisesRegex(ValueError,"CSV exporter scientific source binding differs"):
                select_postprocess_parent(parent,artifact)
            self.assertEqual(before,{str(path):path.read_bytes() for owner in (science,foreign,parent) for path in owner.rglob("*") if path.is_file()})
