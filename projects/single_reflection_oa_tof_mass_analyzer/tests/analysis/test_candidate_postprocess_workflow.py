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
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import freeze_candidate_source_closure
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate as candidate_entry
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as candidate_workflow
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_support.candidate_fixtures import PROJECT_ROOT
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_candidate_workflow import (
    cold_export_failed_child_fixture,
    postprocess_public_entry,
    postprocess_source_fixture,
)


class CandidatePostprocessTests(unittest.TestCase):
    def test_stopped_scientific_gate_failure_preserves_complete_raw_exports(self):
        from types import SimpleNamespace
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root/"source",cold=True)
            selected=select_postprocess_parent(parent,artifact)
            closure=freeze_candidate_source_closure(root/"code",artifact/"projects"/PROJECT_ROOT.name,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            child=root/"child"
            for name in ("inputs","logs","results"):
                (child/name).mkdir(parents=True,exist_ok=True)
            plan={"run_id":child.name,"run_root":str(child),"context_sha256":"software-fixture",
                "writer_completion":{"operations":[],"resource_releases":[]},"postprocess_evidence":{},
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
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(child)}), \
                    mock.patch.object(candidate_comsol_stage,"analyze_detector_request") as analyze:
                with self.assertRaisesRegex(RuntimeError,"EVENT_WINDOW_SENTINEL"):
                    candidate_comsol_stage.execute_saved_postprocess(selected,child,closure,plan,
                        runtime=SimpleNamespace(_run_command=lambda *args:None,_run_managed_stage_command=stopped_export))
            analyze.assert_not_called()
            self.assertTrue(plan["postprocess_evidence"]["detector_exports_ready"])
            self.assertNotIn("writer_completion_unconfirmed",plan["postprocess_evidence"])
            self.assertTrue(Path(plan["postprocess_evidence"]["raw_events_csv"]).is_file())
            self.assertEqual(before,{str(path):path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_csv_child_science_aliases_require_original_consensus(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
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

    def test_cold_prepared_plan_uses_public_native_view_and_prelaunch_failure_has_no_receipt(self):
        from common.contracts.test_support.run_artifact_workflow import CALLBACK, RunArtifactWorkflowFixture
        from msplatform.execution.retention import file_record
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        extra = '''    from unittest import mock
    from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow, candidate_comsol_stage
    def inert_saved(selection, child, closure, plan, *, runtime):
        assert plan['run_root'] == str(root.resolve())
        argv, environment = workflow._native_stage_execution_view([sys.executable, '-I', '-B', '-c', 'pass'],
            {'OATOF_CANDIDATE_MODEL_PATH':selection['model_record']['path']}, plan)
        assert environment['OATOF_CANDIDATE_MODEL_PATH']
        writer_before = json.dumps(plan['writer_completion'], sort_keys=True)
        wrong = dict(plan, run_root=str(root.parent / 'different-owner'))
        with mock.patch.object(workflow, '_run_command') as command, mock.patch.object(workflow, 'append_native_stage_completion') as append:
            try:
                workflow._run_managed_stage_command(argv, root/'logs/not-launched.log', wrong,
                    root/'logs/not-launched.json', 'comsol_launcher_completion', environment)
            except ValueError as error:
                assert 'active public run context' in str(error)
            else:
                raise AssertionError('Mismatched owner must fail before process admission')
            command.assert_not_called()
            append.assert_not_called()
        assert json.dumps(plan['writer_completion'], sort_keys=True) == writer_before
        (root/'results/cold_native_view_probe.json').write_text(json.dumps({'run_root':plan['run_root'],
            'writer_unchanged':True,'prelaunch_command_calls':0,'prelaunch_receipt_calls':0}), encoding='utf-8')
        return {}
    with mock.patch.object(candidate_comsol_stage, 'execute_saved_postprocess', side_effect=inert_saved):
        workflow.execute_prepared_postprocess(config_path, session_path, request_path, root/'results/cold_completion.json')
    cold_completion = json.loads((root/'results/cold_completion.json').read_text(encoding='utf-8'))
    assert cold_completion['status'] == 'success', cold_completion
    assert cold_completion['writer_completion'] == {'operations':[],'resource_releases':[]}
    config = json.loads(config_path.read_text(encoding='utf-8'))
'''
        callback = CALLBACK.replace('    counter = Path(payload["counter_path"])', extra + '    counter = Path(payload["counter_path"])')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, parent, _, _ = postprocess_source_fixture(root / "source", cold=True)
            selected = select_postprocess_parent(parent, artifact)
            closure = freeze_candidate_source_closure(root / "code", artifact / "projects" / PROJECT_ROOT.name,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT / "config/analysis_contract.json")
            selection = root / "selection.json"
            selection.write_text(json.dumps(selected), encoding="utf-8")
            before = {str(path):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            fixture = RunArtifactWorkflowFixture()
            (root / "owner").mkdir()
            result, run, _, outcome = fixture.invoke_fixture(root / "owner", {
                "postprocess_selection":file_record(selection),"execution_source_closure":closure,
                "fixture_commitment_bytes":8*1024*1024}, callback_text=callback,
                source_references=selected["source_references"],
                native_input_paths=[selected["model_record"]["path"], selected["context_record"]["path"]])
            self.assertEqual(outcome.returncode,0,outcome.stdout+outcome.stderr+json.dumps(result))
            probe=load_json(run/"results/cold_native_view_probe.json")
            self.assertTrue(probe["writer_unchanged"])
            self.assertEqual(probe["run_root"],str(run.resolve()))
            self.assertEqual(before,{str(path):path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_completion_request_content_identity_rejects_rebound_records(self):
        from msplatform.execution.retention import verify_record
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent

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
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
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
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
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
        from common.contracts.test_support.run_artifact_workflow import CALLBACK, RunArtifactWorkflowFixture
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import candidate_native_execution_relative_paths
        relative = "inputs/code/" + "deep/" * 26 + "actual_native_task.m"
        declared = candidate_native_execution_relative_paths({"sources": []}, code_relative_root=Path("inputs/code"))
        self.assertIn("inputs/native_run_config.json", declared)
        extra = """    from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import _native_stage_execution_view, _persist_native_json_paths, _run_command
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
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent,prepare_postprocess_request
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
                    with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_ARTIFACT_ROOT":str(artifact)}):
                        request=prepare_postprocess_request(parent,"20261031_151000__analysis__python__runtime-budget")
                    self.assertEqual(request["capacity"]["committed_new_bytes"],selected["new_bytes"])
                    self.assertEqual(before,{str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()})
            artifact,parent,_,_=postprocess_source_fixture(root/"insufficient",cold=True,comsol_bytes=2)
            with self.assertRaisesRegex(ValueError,"COLD_RUNTIME_RESERVATION_INSUFFICIENT"):
                select_postprocess_parent(parent,artifact)

    def test_normal_comsol_commands_transport_the_owner_runtime_directory(self):
        from types import SimpleNamespace
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage as adapter
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/"run";(run/"logs").mkdir(parents=True)
            execution=root/"execution";execution.mkdir()
            closure=freeze_candidate_source_closure(run/"inputs/code",root/"artifacts",
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
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution)}), \
                    mock.patch.object(adapter,"analyze_detector_request",return_value=run/"analysis_receipt.json"):
                adapter.execute_comsol_stage(stage,{"execution_source_closure":closure,"run_root":str(run),"run_id":run.name},sys.executable,runtime=runtime)
            self.assertEqual(len(commands),2)
            from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_cad_stage import execute_cad_stage
            def stop_cad(command,*args):
                commands.append(command)
                raise RuntimeError("STOP_AT_CAD_NATIVE_BOUNDARY")
            runtime._run_managed_stage_command=stop_cad
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution)}):
                with self.assertRaisesRegex(RuntimeError,"STOP_AT_CAD_NATIVE_BOUNDARY"):
                    execute_cad_stage(dict(stage,output_dir=str(run/"cad")),
                        {"execution_source_closure":closure,"run_root":str(run),"run_id":run.name},sys.executable,runtime=runtime)
            self.assertEqual(len(commands),3)
            self.assertEqual([command[command.index("-RunDir")+1] for command in commands],[str(execution)]*3)
            self.assertFalse((run/"model.mph").exists())
            self.assertFalse((run/"cad/oaTOF_solidworks_export_report.json").exists())

    def test_original_cli_postprocess_is_explicit_and_rejects_new_science(self):
        argv = ["run_candidate.py","--postprocess-from","parent","--run-id","new"]
        for extra in (["--request","request.json"],["--particle-source-seed","0"],["--reuse-parent","other"],
                      ["--resume-finalization","old"],["--simion-exe","simion.exe"],["--dry-run"]):
            with self.subTest(extra=extra), mock.patch.object(sys,"argv",argv+extra), \
                    mock.patch.object(candidate_entry,"prepare_execution") as prepare:
                with self.assertRaises(SystemExit):
                    candidate_entry.main()
                prepare.assert_not_called()
        with mock.patch.object(sys,"argv",argv), mock.patch.object(candidate_workflow,"run_candidate_postprocess",
                return_value=(Path("child"),{"scope":"comsol_postprocessing_only"})) as execute, \
                mock.patch.object(candidate_entry,"prepare_execution") as prepare:
            candidate_entry.main()
        execute.assert_called_once_with(Path("parent"),"new")
        prepare.assert_not_called()

    def test_sealed_exports_need_no_model_and_unknown_writer_is_rejected(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
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
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            artifact,parent,_,outputs=postprocess_source_fixture(Path(directory))
            outputs[0].unlink()
            with self.assertRaisesRegex(ValueError,"missing or incomplete"):
                select_postprocess_parent(parent,artifact)

    def test_frozen_only_analyzer_consumes_small_export_and_parent_is_unchanged(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_comsol_stage import execute_saved_postprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            before={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            selected=select_postprocess_parent(parent,artifact)
            frozen=freeze_candidate_source_closure(root/"code",artifact/"projects"/PROJECT_ROOT.name,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            child=root/"child"
            (child/"inputs").mkdir(parents=True)
            (child/"logs").mkdir()
            with mock.patch.object(candidate_workflow,"_run_managed_stage_command",side_effect=AssertionError("native must not start")):
                result=execute_saved_postprocess(selected,child,frozen,{},runtime=candidate_workflow)
            self.assertEqual(result["native_launch_count"],0)
            self.assertFalse(result["parent_model_saved"])
            self.assertTrue(Path(result["analysis_receipt"]).is_file())
            self.assertEqual(before,{str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_original_cli_child_and_finalization_resume_use_public_owner_zero_native(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            before={str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            invoke=postprocess_public_entry(root,artifact)
            child_id="20261031_122000__analysis__python__candidate-postprocess"
            first=invoke(["--postprocess-from",str(parent),"--run-id",child_id])
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            child=artifact/"projects"/PROJECT_ROOT.name/"runs"/child_id
            summary=load_json(child/"summary.json")
            self.assertEqual(summary["scope"],"comsol_postprocessing_only")
            self.assertEqual(summary["evidence"]["native_launch_count"],0)
            self.assertEqual(summary["native_particle_solve_count"],0)
            self.assertFalse(list(child.rglob("*.mph")))
            completion=(child/"results/execution_completion.json").read_bytes()
            resumed=invoke(["--resume-finalization",str(child)])
            self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
            self.assertEqual(completion,(child/"results/execution_completion.json").read_bytes())
            self.assertEqual(before,{str(path.relative_to(parent)):path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    def test_postprocess_failure_preserves_source_identity_and_reports_original_recovery_cli(self):
        from msplatform.execution.retention import file_record
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import candidate_comsol_stage
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            selected=select_postprocess_parent(parent,artifact)
            closure=freeze_candidate_source_closure(root/"code",artifact/"projects"/PROJECT_ROOT.name,
                resolved_contract=Path(selected["inputs"]["contract_path"]["path"]),
                analysis_contract=PROJECT_ROOT/"config/analysis_contract.json")
            child=root/"child"
            (child/"inputs").mkdir(parents=True)
            (child/"logs").mkdir()
            selection_path=root/"selection.json"
            selection_path.write_text(json.dumps(selected),encoding="utf-8")
            request=child/"inputs/execution_request.json"
            request.write_text(json.dumps({"payload":{"postprocess_selection":file_record(selection_path),
                "execution_source_closure":closure}}),encoding="utf-8")
            config=child/"run_config.json"
            config.write_text(json.dumps({"schema_version":2,"inputs":{"execution_request":str(request)},
                "parameters":{},"paths":{"sentinel":"preserved"}}),encoding="utf-8")
            session=root/"session.json"
            session.write_text(json.dumps({"protected_paths":[str(child),str(parent)],"artifact_root":str(artifact)}),encoding="utf-8")
            completion=child/"results/execution_completion.json"
            (child/"results").mkdir()
            with mock.patch.object(candidate_comsol_stage,"execute_saved_postprocess",side_effect=RuntimeError("PLOT_FAILURE_SENTINEL")):
                candidate_workflow.execute_prepared_postprocess(config,session,request,completion)
            actual=load_json(completion)
            self.assertEqual(actual["status"],"failed")
            self.assertEqual(actual["summary"]["data_validity"],"unknown")
            self.assertTrue(actual["summary"]["source_identity_verified"])
            self.assertEqual(actual["exception"]["message"],"PLOT_FAILURE_SENTINEL")
            self.assertIn("--postprocess-from",actual["summary"]["recovery_action"])
            self.assertIn("--resume-finalization",actual["summary"]["resume_finalization_command"])
            self.assertEqual(load_json(config)["paths"],{"sentinel":"preserved"})
            self.assertFalse(actual["summary"]["recovery_requires_terminal_publication"])
            self.assertIn(str(parent),actual["summary"]["recovery_action"])
            # Only the consumer's unknown-writer hint is checked here; the
            # stopped/release fault matrix remains at the public validator.
            unknown=child.parent/"unknown-child"
            (unknown/"inputs").mkdir(parents=True)
            (unknown/"logs").mkdir()
            (unknown/"results").mkdir()
            unknown_config=unknown/"run_config.json"
            unknown_request=unknown/"inputs/execution_request.json"
            unknown_request.write_bytes(request.read_bytes())
            unknown_config.write_text(json.dumps({"schema_version":2,"inputs":{"execution_request":str(unknown_request)},
                "parameters":{},"paths":{"sentinel":"preserved"}}),encoding="utf-8")
            unknown_session=unknown/"session.json"
            unknown_session.write_text(json.dumps({"protected_paths":[str(unknown),str(parent)],"artifact_root":str(artifact)}),encoding="utf-8")
            def unknown_export(_selection,_root,_closure,plan,*,runtime):
                plan["postprocess_evidence"]["writer_completion_unconfirmed"]=True
                raise RuntimeError("POSTPROCESS_EXPORT_WRITER_UNCONFIRMED")
            unknown_completion=unknown/"results/execution_completion.json"
            with mock.patch.object(candidate_comsol_stage,"execute_saved_postprocess",side_effect=unknown_export):
                candidate_workflow.execute_prepared_postprocess(unknown_config,unknown_session,unknown_request,unknown_completion)
            blocked=load_json(unknown_completion)
            self.assertEqual(blocked["summary"]["recovery_action"],"inspect_original_writer_completion; retain current protections")
            self.assertFalse(blocked["summary"]["recovery_requires_terminal_publication"])
            self.assertEqual(blocked["required_output_paths"],[])

    def test_cold_dispatch_projects_actual_task_but_keeps_frozen_request_canonical(self):
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_comsol_stage import execute_saved_postprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            child=root/"child"
            (child/"inputs").mkdir(parents=True)
            (child/"logs").mkdir()
            frozen=freeze_candidate_source_closure(child/"inputs/code",root/"artifacts",
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
            plan={"context_sha256":"a"*64,"source_execution_context":{
                "schema_version":1,"role":"run_source_execution_context","request_sha256":"a"*64,
                "child_run_directory":str(child),"execution_root":str(root),"sources":[{
                    "target_directory":selection["parent"],"execution_directory":str(source_execution),
                    "execution_alias":str(source_execution),"input_paths":[selection["model_record"]["path"],selection["context_record"]["path"]]}]}}
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY":str(execution)}), \
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

    def test_failed_cold_export_child_reanalyzes_via_original_cli_without_model_or_comsol(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,science,parent,_=cold_export_failed_child_fixture(root)
            before={str(path):path.read_bytes() for folder in (science,parent) for path in folder.rglob("*") if path.is_file()}
            selected=select_postprocess_parent(parent,artifact)
            self.assertIsNone(selected["model_record"])
            self.assertEqual(len(selected["source_references"]),2)
            invoke=postprocess_public_entry(root,artifact)
            author_stage=root/"author/projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_comsol_stage.py"
            author_stage.write_text(author_stage.read_text(encoding="utf-8")+"\n# Explicit software-only cold-export/analysis-failure consumer fixture.\n_fixture_original_saved_postprocess = execute_saved_postprocess\n\ndef execute_saved_postprocess(selection, root, closure, plan, *, runtime):\n    if root.name != '20261031_123500__analysis__comsol__cold-analysis-failure':\n        return _fixture_original_saved_postprocess(selection, root, closure, plan, runtime=runtime)\n    import json, subprocess, sys\n    from types import SimpleNamespace\n    from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion\n    fake_model = Path(selection['parent'])/'inert_fixture_not_a_model.mph'\n    fake_context = Path(selection['parent'])/'inert_fixture_not_a_model.mph.postprocess.json'\n    cold = dict(selection, exports=None, model_record={'path':str(fake_model)}, context_record={'path':str(fake_context)})\n    plan['source_execution_context'] = {\n        'schema_version':1,'role':'run_source_execution_context','request_sha256':plan['context_sha256'],\n        'child_run_directory':str(root),'sources':[{'target_directory':selection['parent'],\n        'execution_directory':selection['parent'],'input_paths':[str(fake_model),str(fake_context)]}]}\n    def software_export(command, log, selected_plan, receipt_path, role):\n        # The process below is actual Python, never MATLAB/COMSOL. Its tiny data\n        # and closed release shape are explicit native-boundary fixture facts.\n        observed = subprocess.run([sys.executable,'-I','-B','-c','pass'],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)\n        assert observed.returncode == 0\n        receipt={'schema_version':1,'role':role,'run_id':root.name,\n            'fixture':'SOFTWARE_ONLY_NOT_A_COMSOL_RUN',\n            'operations':[{'operation_id':'inert-software-export','observation':{'exit_confirmed':True,'returncode':observed.returncode}}],\n            'host_release':{'inherited':False,'token':'fixture-closed-release',\n            'result':{'status':'released','token':'fixture-closed-release'},'error':None}}\n        receipt_path.write_text(json.dumps(receipt),encoding='utf-8')\n        append_native_stage_completion(selected_plan['writer_completion'],receipt_path,role=role,run_id=root.name)\n        events=root/'results/comsol_detector_events_Fixture.csv'\n        events.write_bytes(Path(selection['exports']['events']['path']).read_bytes())\n        request=root/'results/comsol_detector_events_Fixture.analysis_request.json'\n        document=json.loads(Path(selection['exports']['request']['path']).read_text(encoding='utf-8'))\n        document.update(raw_events_csv=str(events),analysis_output_dir=str(root/'results/detector_analysis'))\n        request.write_text(json.dumps(document),encoding='utf-8')\n        result={'candidate_model_validation':'passed','model_path':str(fake_model),'raw_detector_events_path':str(events),\n            'analysis_request_path':str(request),'analysis_output_dir':document['analysis_output_dir']}\n        (root/'results/cold_postprocess_result.json').write_text(json.dumps(result),encoding='utf-8')\n        (root/'logs/cold_postprocess.txt').write_text('STATUS=PASS\\n',encoding='utf-8')\n        (root/'logs/inert_cold_boundary.txt').write_text('one software-only invocation\\n',encoding='utf-8')\n    def fail_analysis(*args, **kwargs):\n        raise RuntimeError('ANALYSIS_AFTER_COMPLETED_COLD_EXPORT')\n    original_analyzer=globals()['analyze_detector_request']\n    globals()['analyze_detector_request']=fail_analysis\n    try:\n        return _fixture_original_saved_postprocess(cold,root,closure,plan,\n            runtime=SimpleNamespace(_run_command=runtime._run_command,_run_managed_stage_command=software_export))\n    finally:\n        globals()['analyze_detector_request']=original_analyzer\n",encoding="utf-8")
            failed_id="20261031_123500__analysis__comsol__cold-analysis-failure"
            failed=invoke(["--postprocess-from",str(parent),"--run-id",failed_id])
            self.assertNotEqual(failed.returncode,0)
            failed_child=artifact/"projects"/PROJECT_ROOT.name/"runs"/failed_id
            failed_summary=load_json(failed_child/"summary.json")
            self.assertEqual(failed_summary["status"],"failed")
            self.assertIn("ANALYSIS_AFTER_COMPLETED_COLD_EXPORT",failed_summary["failure_reason"])
            self.assertTrue(failed_summary["evidence"]["detector_exports_ready"])
            self.assertTrue(failed_summary["recovery_requires_terminal_publication"])
            self.assertIn('--postprocess-from "'+str(failed_child)+'"',failed_summary["recovery_action"])
            self.assertTrue((failed_child/"logs/inert_cold_boundary.txt").is_file())
            self.assertEqual(load_json(failed_child/"run_manifest.json")["status"],"failed")
            failed_bytes={str(path):path.read_bytes() for path in failed_child.rglob("*") if path.is_file()}
            select_postprocess_parent(failed_child,artifact)
            run_id="20261031_124000__analysis__python__postprocess-retry"
            first=invoke(["--postprocess-from",str(failed_child),"--run-id",run_id])
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            child=artifact/"projects"/PROJECT_ROOT.name/"runs"/run_id
            summary=load_json(child/"summary.json")
            self.assertEqual(summary["evidence"]["native_launch_count"],0)
            self.assertEqual(summary["native_particle_solve_count"],0)
            completion=(child/"results/execution_completion.json").read_bytes()
            resumed=invoke(["--resume-finalization",str(child)])
            self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
            self.assertEqual(completion,(child/"results/execution_completion.json").read_bytes())
            self.assertEqual(before,{str(path):path.read_bytes() for folder in (science,parent) for path in folder.rglob("*") if path.is_file()})
            self.assertFalse(list(root.rglob("*.mph")))
            self.assertEqual(failed_bytes,{str(path):path.read_bytes() for path in failed_child.rglob("*") if path.is_file()})
            self.assertFalse((child/"logs/inert_cold_boundary.txt").exists())
            again=select_postprocess_parent(child,artifact)
            self.assertEqual(len(again["source_references"]),3)
            self.assertEqual(again["science_reference"],selected["science_reference"])
            self.assertEqual(again["export_source_reference"]["manifest_record"]["path"],str(failed_child/"run_manifest.json"))

    def test_postprocess_export_parent_rejects_missing_unknown_and_tampered_exports(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
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

    def test_public_request_declares_native_files_only_for_cold_scope(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import prepare_candidate_run as preparation
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,parent,_,_=postprocess_source_fixture(root)
            selected=preparation.select_postprocess_parent(parent,artifact)
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_ARTIFACT_ROOT":str(artifact),
                                            "MASS_SPECTROMETRY_EXECUTION_ROOT":str(root/"execution")}):
                csv_request=preparation.prepare_postprocess_request(parent,"20261031_132000__analysis__python__prepared-csv")
                self.assertNotIn("native_input_paths",csv_request["prepared"])
                cold=dict(selected,exports=None,model_record={"path":str(parent/"model.mph")},
                          context_record={"path":str(parent/"model.mph.postprocess.json")})
                # This tests request transport only. The real selector/owner,
                # not this mocked scientific selection, owns admission.
                with mock.patch.object(preparation,"select_postprocess_parent",return_value=cold):
                    cold_request=preparation.prepare_postprocess_request(parent,"20261031_133000__analysis__comsol__prepared-cold")
                self.assertEqual(cold_request["prepared"]["native_input_paths"],
                    [cold["model_record"]["path"],cold["context_record"]["path"]])
                self.assertEqual(cold_request["capacity"]["source_references"],selected["source_references"])
                self.assertIn("retention_role", selected["budget_record"])
                for request in (csv_request, cold_request):
                    budget_record = request["capacity"]["commitment_inputs"][1]
                    self.assertEqual(set(budget_record), {"path", "exists", "bytes", "sha256"})
                    for key in ("path", "exists", "bytes", "sha256"):
                        self.assertEqual(budget_record[key], selected["budget_record"][key])

    def test_flat_exporter_cannot_substitute_another_science_owner(self):
        from common.contracts.capacity_ledger import record_capacity_object
        from msplatform.execution.retention import file_record
        from msplatform.execution.manifest_publication import publish_run_manifest
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,science,_,_=postprocess_source_fixture(root/"science")
            foreign_root,_,foreign,_=cold_export_failed_child_fixture(root/"foreign")
            source=select_postprocess_parent(science,artifact)
            other=select_postprocess_parent(foreign,foreign_root)
            source["exports"]=other["exports"]
            source["export_source_reference"]=other["export_source_reference"]
            parent=artifact/"projects"/PROJECT_ROOT.name/"runs/20261031_134000__analysis__python__wrong-exporter"
            (parent/"inputs").mkdir(parents=True)
            (parent/"results").mkdir()
            selection=parent/"inputs/postprocess_source_selection.json"
            selection.write_text(json.dumps(source),encoding="utf-8")
            request=parent/"inputs/execution_request.json"
            request.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_request",
                "package":{"project":PROJECT_ROOT.name,"run_id":parent.name,"mode":"candidate_comsol_postprocess"}}),encoding="utf-8")
            config=parent/"run_config.json"
            config.write_text(json.dumps({"schema_version":2,"project":PROJECT_ROOT.name,"run_id":parent.name,
                "mode":"candidate_comsol_postprocess","project_root":str(PROJECT_ROOT),
                "inputs":{"execution_request":str(request),"postprocess_source_selection":str(selection)},
                "provenance":{"science_reference":source["science_reference"]},
                "artifact_retention":{"policy_version":1,"class":"compact","reason":None},
                "capacity_ledger_lifecycle":{"schema_version":1,"enabled":True,"artifact_root":str(artifact),"light_evidence_budget_bytes":67108864}}),encoding="utf-8")
            completion=parent/"results/execution_completion.json"
            completion.write_text(json.dumps({"schema_version":1,"role":"run_artifact_workflow_completion",
                "project":PROJECT_ROOT.name,"run_id":parent.name,"status":"failed","execution_request":file_record(request),
                "run_config":file_record(config),"writer_completion":{"operations":[],"resource_releases":[]},
                "summary":{"source_identity_verified":True}}),encoding="utf-8")
            publish_run_manifest(config,"failed",output_paths=[completion], retention_api=_manifest_retention_api)
            record_capacity_object(artifact,path=parent,object_class="light_evidence",bytes_count=sum(
                path.stat().st_size for path in parent.rglob("*") if path.is_file()),owner=PROJECT_ROOT.name)
            before={str(path):path.read_bytes() for owner in (science,foreign,parent) for path in owner.rglob("*") if path.is_file()}
            with self.assertRaisesRegex(ValueError,"CSV exporter scientific source binding differs"):
                select_postprocess_parent(parent,artifact)
            self.assertEqual(before,{str(path):path.read_bytes() for owner in (science,foreign,parent) for path in owner.rglob("*") if path.is_file()})
