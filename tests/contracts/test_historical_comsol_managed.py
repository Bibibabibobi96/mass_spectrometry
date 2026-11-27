"""Actual Store/native owner with an inert Python cold-export process, never COMSOL."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.backends.comsol.historical_detector_extraction import extract_historical_detector
from msplatform.backends.simion.native_completion import retention_api
from msplatform.execution.context import ExecutionContext
from msplatform.execution.manifest_publication import publish_run_manifest
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.historical_comsol_detector import (
    publish_extracted_comsol_report, publish_failed_extracted_comsol_report,
)
from tests.contracts.test_historical_comsol_report import HistoricalComsolReportTests


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows managed source guard")
class HistoricalComsolManagedTests(unittest.TestCase):
    def test_inert_cold_owner_and_store_report(self):
        self.exercise(False)

    def test_failed_cold_preserves_complete_raw_cohort(self):
        self.exercise(True)

    def test_failed_source_and_successful_extraction_remain_distinct(self):
        self.exercise(False, source_failed=True)

    def test_missing_inner_launcher_does_not_publish_raw_csv(self):
        self.exercise(True, missing_launcher=True)

    def exercise(self, fail, source_failed=False, missing_launcher=False):
        with tempfile.TemporaryDirectory(prefix="cold-comsol-managed-") as temporary:
            root = Path(temporary)
            source = HistoricalComsolReportTests().make_source(root)
            (source / "run_manifest.json").unlink()
            (source / "comsol").mkdir()
            model = source / "comsol/model.mph"
            model.write_bytes(b"INERT-NOT-A-COMSOL-MODEL")
            saved = source / "comsol/model.mph.postprocess.json"
            saved.write_text(json.dumps(dict(schema_version=1, role="oatof_saved_particle_solution",
                particle_count=100, solution_tag="sol2", dataset_tag="pdset1", saved_model_bytes=model.stat().st_size,
                model_save_state="raw_complete", label="test")), encoding="utf-8")
            config_path = source / "run_config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["artifact_retention"] = {"policy_version": 1, "class": "solver_review",
                                            "reason": "inert source fixture"}
            execution_request = source / "inputs/execution_request.json"
            execution_request.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_request",
                package=dict(project="single_reflection_oa_tof_mass_analyzer", run_id=source.name, mode="design_candidate"))), encoding="utf-8")
            config["inputs"]["execution_request"] = str(execution_request)
            config_path.write_text(json.dumps(config), encoding="utf-8")
            from msplatform.backends.simion.native_stage_completion import append_native_stage_completion
            (source / "logs").mkdir(exist_ok=True)
            native = source / "logs/comsol_build_completion.json"
            native.write_text(json.dumps(dict(schema_version=1, role="comsol_launcher_completion", run_id=source.name,
                operations=[dict(operation_id="inert", observation=dict(exit_confirmed=True, returncode=0, process_id=111, process_started_at_utc_ticks=222))],
                host_release=dict(inherited=False, token="fixture", result=dict(status="released", token="fixture"), error=None))), encoding="utf-8")
            writer = {"operations": [], "resource_releases": []}
            append_native_stage_completion(writer, native, role="comsol_launcher_completion", run_id=source.name)
            completion = source / "results/execution_completion.json"
            completion.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_completion",
                project="single_reflection_oa_tof_mass_analyzer", run_id=source.name, status="failed" if source_failed else "success",
                writer_completion=writer, execution_request=file_record(execution_request), run_config=file_record(config_path))), encoding="utf-8")
            report = source / "logs/comsol_build.txt"
            report.write_text("STATUS=PASS\n", encoding="utf-8")
            publish_run_manifest(config_path, "failed" if source_failed else "success",
                output_paths=[source / "results/request.json", source / "results/events.csv", model, saved,
                              native, completion, report], retention_api=retention_api)
            stage = root / "stage.json"
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=40_000_000,
                process_tree_working_set_bytes=2_000_000_000, minimum_system_available_memory_bytes=100_000_000,
                compact_final_retained_bytes=30_000_000, automatic_retry_count=0)
            stage.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy", stages={
                "reextract_oatof_saved_solution": dict(limits=limits, artifact_retention={
                    "policy_version":1, "class":"solver_review", "reason":"inert software fixture"})})), encoding="utf-8")
            context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which("pwsh")), tools={"comsol_launcher":Path(sys.executable),
                "matlab_root":Path(sys.executable).parent}, host_state_path=root / "host.sqlite",
                policy_path=resource_path("host_resource_policy.json"), stage_policy_path=stage)
            store = ArtifactStore(root / "store", high_water_bytes=200_000_000, low_water_bytes=150_000_000, safety_bytes=0)
            original = RunSession.run_process
            script = """import json,sys
from pathlib import Path
r=Path(sys.argv[1]); model=sys.argv[2]; d=r/'results'; l=r/'logs'
e=d/'comsol_detector_events_test.csv'; q=d/'comsol_detector_events_test.analysis_request.json'
e.write_text('Ion,TofUs,XMm,YMm,Hit,Status,Event,DetectorRadiusMm,X0Mm,Y0Mm,Z0Mm\\n'+''.join(f'{i},{70+i*.00001},0,0,{i<74 if sys.argv[3] != "0" else True},unknown,freeze,0,0,0,0\\n' for i in range(1,101)))
q.write_text(json.dumps(dict(schema_version=1,role='oatof_comsol_detector_events_analysis_request',solver='COMSOL',label='test',nominal_mass_Da=524,raw_events_csv=str(e),analysis_output_dir=str(d/'analysis'),event_extraction={},aggregate_metrics_owner='python_reference_analysis')))
(d/'ms_oaTOF_ringstack_reflectron_test.png').write_bytes(b'inert')
(d/'cold_extraction.json').write_text(json.dumps(dict(native_particle_solve_count=0,native_field_solve_count=0,parent_model_saved=False,candidate_model_validation='passed',nP=100,nDet=100,model_path=model,raw_detector_events_path=str(e),analysis_request_path=str(q))))
(l/'cold_extraction.bootstrap.log').write_text('STATUS=PASS')
if sys.argv[5] == '0':
 (l/'cold_extraction.launcher.json').write_text(json.dumps(dict(schema_version=1,role='comsol_launcher_completion',run_id=sys.argv[4],operations=[dict(operation_id='inert-launcher',observation=dict(exit_confirmed=True,returncode=int(sys.argv[3]),process_id=111,process_started_at_utc_ticks=222))],host_release=dict(inherited=True,token='fixture',result=None,error=None))))
sys.exit(int(sys.argv[3]))
"""
            def transport(session, operation, **kwargs):
                return original(session, operation, executable=Path(sys.executable),
                    arguments=['-c', script, str(session.run_dir), str(model), '7' if fail else '0', session.run_id, '1' if missing_launcher else '0'], role='GATE',
                    stage='inert_cold_fixture', limits=kwargs['limits'],
                    immutable_input_records=kwargs['immutable_input_records'])
            with (patch.object(RunSession, 'run_process', transport),
                  patch('msplatform.backends.comsol.historical_detector_extraction.require_launcher_completion')):
                if fail:
                    from msplatform.execution.processes import ProcessExecutionError
                    with self.assertRaises(ProcessExecutionError) as caught:
                        extract_historical_detector(file_record(source / 'run_manifest.json'),
                            model_output='comsol/model.mph', context_output='comsol/model.mph.postprocess.json',
                            geometry_input='geometry', analysis_contract_input='analysis_contract', context=context, store=store,
                        source_status='failed' if source_failed else 'success')
                else:
                    product, run = extract_historical_detector(file_record(source / 'run_manifest.json'),
                        model_output='comsol/model.mph', context_output='comsol/model.mph.postprocess.json',
                        geometry_input='geometry', analysis_contract_input='analysis_contract', context=context, store=store,
                        source_status='failed' if source_failed else 'success')
            if fail:
                from msplatform.execution.native_source_guard import guard_stopped_store_evidence
                with store._db() as db:
                    rows = db.execute("SELECT path FROM assets WHERE path LIKE 'assets/native_stage/%' AND state='failed'").fetchall()
                self.assertEqual(len(rows), 1)
                manifests = list((store.root / rows[0][0]).rglob('run_manifest.json'))
                self.assertEqual(len(manifests), 1)
                with guard_stopped_store_evidence(store, file_record(manifests[0])) as (failed, hold):
                    self.assertEqual(failed['status'], 'failed')
                    selected = [row for row in failed['outputs'] if Path(row['path']).name in
                        {'comsol_detector_events_test.csv', 'comsol_detector_events_test.analysis_request.json'}]
                    if missing_launcher:
                        self.assertEqual(selected, [])
                        self.assertTrue(any("Stopped cold detector export is incomplete" in note
                                            for note in getattr(caught.exception, "__notes__", [])))
                        return
                    self.assertEqual(len(selected), 2, (failed["outputs"], getattr(caught.exception, "__notes__", [])))
                    hold(selected)
                    events = next(row for row in selected if row["path"].endswith(".csv"))
                    request = next(row for row in selected if row["path"].endswith(".json"))
                report_run, published = publish_failed_extracted_comsol_report(
                    file_record(manifests[0]), events_record=events, request_record=request,
                    store=store, reserve_bytes=20_000_000)
                self.assertEqual(published, store.inspect_run(report_run))
                metrics = json.loads((published / "results/metrics.json").read_text(encoding="utf-8"))
                self.assertEqual(metrics["metrics"]["particles"], 73)
                self.assertEqual(metrics["source_execution_status"], "failed")
                self.assertEqual(metrics["analysis_scope"], "historical_detector_observations_only")
                observation = metrics["detector_observation"]
                self.assertEqual((observation["expected_mother_count"], observation["raw_cohort_rows"],
                                  observation["detector_observed_count"], observation["unobserved_count"]),
                                 (100, 100, 73, 27))
                self.assertIn("no physical-loss inference", observation["unobserved_semantics"])
                provenance = json.loads((published / "inputs/native_product_provenance.json").read_text(encoding="utf-8"))
                self.assertEqual(provenance["source_execution_status"], "failed")
                self.assertEqual(model.read_bytes(), b"INERT-NOT-A-COMSOL-MODEL")
                return
            self.assertEqual(store.run_status(run)['execution_status'], 'succeeded')
            self.assertEqual(product.metadata['native_particle_solve_count'], 0)
            self.assertEqual(product.metadata['source_execution_status'], 'failed' if source_failed else 'success')
            report_run, report = publish_extracted_comsol_report(product.reference, store=store, reserve_bytes=20_000_000)
            self.assertEqual(report, store.inspect_run(report_run))
            analysis = json.loads((report / 'results/metrics.json').read_text())
            self.assertEqual(analysis['metrics']['particles'], 100)
            self.assertEqual(analysis['extraction_execution_status'], 'succeeded')
            self.assertEqual(analysis['source_execution_status'], 'failed' if source_failed else 'success')
            self.assertEqual(model.read_bytes(), b"INERT-NOT-A-COMSOL-MODEL")


if __name__ == '__main__':
    unittest.main()
