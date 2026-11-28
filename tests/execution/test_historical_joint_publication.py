"""Real owner/Store lifecycle with inert, synthetic historical records."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.owner import run_managed_stage
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.historical_joint_analysis import publish_joint_analysis
from tests.contracts import test_execution_runtime
from tests.components.multi_reflection_tof.analysis import test_recorded_joint_diagnostics


def _gate(session):
    session.run_process("fixture", executable=Path(sys.executable), arguments=["-c", "pass"],
                        role="GATE", stage="software_tests", limits=None)


def _component(session):
    _gate(session)
    paths=[]
    for name in ("events.csv", "samples.csv"):
        path=session.declare_file(session.artifact_run_dir/"simion"/name, "required_evidence")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("particle_id,t_us,x_mm\n9,0,1\n9,21,2\n1,22,3\n", encoding="utf-8")
        paths.append(str(path))
    return dict(status="success",summary={"fixture":"INERT_ONLY"},output_paths=paths,
                required_output_paths=paths,retention_preserve_paths=[],manifest_extra_fields={})


def _joint(session, *, fixture, component):
    _gate(session)
    out=session.result_dir
    source=out/"measured_source"
    shutil.copytree(fixture.source, source)
    def write(path, value): path.write_text(json.dumps(value)+"\n",encoding="utf-8")
    component_path=out/"component.json"
    write(component_path,dict(source_run=str(Path(component["manifest"]["path"]).parent),
        inputs={"run_manifest.json":component["manifest"]}))
    handoff=out/"handoff.json";write(handoff,dict(inputs=dict(component_receipt=file_record(component_path))))
    source_receipt=source/"source_receipt.json"
    receipt=json.loads(source_receipt.read_text(encoding="utf-8"))
    receipt["inputs"]={"handoff_receipt":file_record(handoff)}
    receipt["outputs"].pop("upstream_clock_authority", None)
    for name, record in receipt["outputs"].items():
        receipt["outputs"][name]=file_record(source/Path(record["path"]).name)
    write(source_receipt,receipt)
    prep=dict(fixture.prepared)
    prep["measured_source_directory"]=str(source)
    prep["source_receipt"]=file_record(source_receipt)
    for key in ("trajectory_contract","operating_point","reference_materialization","field_binding"):
        original=Path(prep[key]["path"]); target=out/original.name;shutil.copyfile(original,target)
        if key=="trajectory_contract":
            document=json.loads(target.read_text(encoding="utf-8"))
            peak=document.get("peak_analysis") or {}
            reference=peak.get("common_time_reference") or {}
            if reference:
                original_timing=Path(reference["timing"]["path"]); copied_timing=out/original_timing.name
                shutil.copyfile(original_timing,copied_timing)
                document["peak_analysis"]["common_time_reference"]["timing"]=file_record(copied_timing)
                write(target,document)
        prep[key]=file_record(target)
    log=out/"merged.log";shutil.copyfile(fixture.log,log)
    batch=out/"batch.json";write(batch,dict(schema_version=1,role="mrtof_measured_source_batch",
        count=2,original_particle_ids=[1,7],solver_epoch_instrument_time_us=prep["solver_epoch_instrument_time_us"],
        outputs=dict(source=file_record(source/"source.fly2"))))
    preparation=out/"prepared_joint_trial.json"
    prep.update(source_mode="measured_population",launched_particle_count=2)
    write(preparation,prep)
    merge=out/"batch_log_merge_receipt.json"
    write(merge,dict(schema_version=1,role="mrtof_measured_batch_log_merge",status="success",
        all_batch_losses_retained=True,id_rebasing_applied=False,original_particle_ids=[1,7],particle_count=2,
        mother_particle_count=3,solver_epoch_instrument_time_us=prep["solver_epoch_instrument_time_us"],
        preparation=file_record(preparation),merged_log=file_record(log),
        batches=[dict(log=file_record(log),batch_receipt=file_record(batch),fly2=file_record(source/"source.fly2"))]))
    paths=[path for path in out.rglob("*") if path.is_file()]
    for path in paths:session.declare_file(path,"required_evidence")
    return dict(status="success",summary={"fixture":"INERT_ONLY"},output_paths=list(map(str,paths)),
                required_output_paths=list(map(str,paths)),retention_preserve_paths=[],manifest_extra_fields={})


@unittest.skipUnless(os.name=="nt" and os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"),"shared Windows host ledger required")
class HistoricalJointPublicationTests(unittest.TestCase):
    def test_real_owner_sources_contract_freezing_and_store_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); helper=test_execution_runtime.NormalOwnerTests();policy=root/"capacity.json"
            policy.write_text(json.dumps(helper._policy()),encoding="utf-8")
            context=replace(helper._context(root),capacity_policy_path=policy,
                host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]))
            context.workspace.mkdir(parents=True)
            fixture=test_recorded_joint_diagnostics.RecordedJointDiagnosticsTests(
                methodName="test_full_pipeline_preserves_mother_raw_branches_losses_and_figures")
            fixture.setUp();self.addCleanup(fixture.doCleanups)
            from msplatform.analysis.peak_metrics import AnalysisSettings
            original_contract=Path(fixture.prepared["trajectory_contract"]["path"])
            baseline=json.loads(original_contract.read_text(encoding="utf-8"))
            baseline["simion"].update(default_trajectory_profile_id="fixture",
                trajectory_profiles=dict(fixture=dict(trajectory_quality=3,maximum_step_us=.002,purpose="fixture")))
            timing=root/"timing.json"
            timing.write_text(json.dumps(dict(schema_version=1,role="native_electrode_timing",
                pulse_start_us=7500)),encoding="utf-8")
            source_receipt=json.loads((fixture.source/"source_receipt.json").read_text(encoding="utf-8"))
            baseline["peak_analysis"]=dict(method_id="common_gaussian_kde_time_v2",
                resolution_definition="mean_tof_us/(2*direct_fwhm_tof_us)",
                time_basis="instrument_arrival_minus_common_extraction_pulse_us",
                settings=vars(AnalysisSettings()),common_time_reference=dict(
                    clock_epoch_id=source_receipt["clock_epoch_id"],timing=file_record(timing),
                    field="pulse_start_us"))
            original_contract.write_text(json.dumps(baseline),encoding="utf-8")
            store=ArtifactStore(root/"store")
            def stage(action, project, mode, run_id):
                args=helper._arguments(root,action)
                args.update(descriptor=dict(project=project,mode=mode,software=[]),run_id=run_id,
                    expected_operation_ids=("fixture",),operation_dependencies={},
                    action_record=file_record(Path(__file__),"required_evidence"),
                    completion_api=no_particle_batch_completion_api,committed_new_bytes=100_000_000)
                return run_managed_stage(context,artifact_store=store,**args)
            component=stage(_component,"dual_pressure_rectilinear_ion_processor","native_electrode_functional",
                            "20261127_190000__test__python__component")
            from functools import partial
            source=stage(partial(_joint,fixture=fixture,component=component),"instrument_assembly","prepared_joint",
                         "20261127_190001__test__python__joint")
            result=publish_joint_analysis(context,source_manifest=Path(source["manifest"]["path"]),
                ancestor_manifests=(Path(component["manifest"]["path"]),),analysis_contract=None,
                artifact_store=store,committed_new_bytes=100_000_000,
                run_id="20261127_190002__test__python__analysis",
                retention=dict(policy_version=1,**{"class":"compact"},reason=None))
            self.assertEqual(result["diagnostics"]["counts"]["mother_source"],3)
            self.assertEqual(result["diagnostics"]["counts"]["detected"],1)
            self.assertTrue(store.inspect_run(result["store_run_id"]).is_dir())

            original_bytes=original_contract.read_bytes()
            contract=json.loads(original_bytes)
            author=root/"author-analysis.json"
            author.write_text(json.dumps(contract),encoding="utf-8")
            author_bytes=author.read_bytes()
            published=publish_joint_analysis(context,source_manifest=Path(source["manifest"]["path"]),
                ancestor_manifests=(Path(component["manifest"]["path"]),),analysis_contract=author,
                artifact_store=store,committed_new_bytes=100_000_000,
                run_id="20261127_190003__test__python__analysis-contract",
                retention=dict(policy_version=1,**{"class":"compact"},reason=None))
            frozen=published["diagnostics"]["analysis_contract_provenance"]["contract"]
            self.assertEqual(frozen["sha256"],file_record(author)["sha256"])
            self.assertNotEqual(Path(frozen["path"]),author)
            manifest_path=Path(published["manifest"]["path"])
            manifest=json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            frozen_input=manifest["inputs"]["analysis_contract"]
            self.assertEqual(Path(frozen_input["path"]).read_bytes(),author_bytes)
            author.unlink()
            self.assertEqual(Path(frozen_input["path"]).read_bytes(),author_bytes)
            self.assertEqual(original_contract.read_bytes(),original_bytes)


def stopped_source_fixture(workspace, *, status="failed", owner="instrument_assembly", complete=True,
                           writers_stopped=True):
    from msplatform.backends.simion.native_completion import retention_api
    from msplatform.execution.manifest_publication import build_run_manifest

    root = workspace / "artifacts"
    run = root / "assemblies/instrument_assembly/runs/20261022_120000__test__simion__source"
    results = run / "results"
    results.mkdir(parents=True)
    logs = run / "logs"
    logs.mkdir()
    inputs = run / "inputs"
    inputs.mkdir()
    recording = dict(schema_version=1, mode="every_step", retention_class="solver_review",
                     reason="Synthetic analysis lifecycle regression", output_budget_bytes=1048576)
    contract = workspace / "new_analysis_contract.json"
    contract.write_text(json.dumps(dict(simion=dict(trajectory_recording=recording),
                                       peak_analysis=dict(test="explicit"))))
    preparation = results / "prepared_joint_trial.json"
    expected = [index for index in range(1, 101) if index not in {24, 64, 80}]
    preparation.write_text(json.dumps(dict(schema_version=1, role="mrtof_prepared_joint_trial",
        source_mode="measured_population", expected_particle_ids=expected, mother_particle_count=100,
        launched_particle_count=97, solver_epoch_instrument_time_us=7500.63364160348,
        protected_paths=[str(run)])))
    log = logs / "native_two_prism_flight.log"
    log.write_text("INERT NATIVE LOG FIXTURE; no commercial flight executed\n")
    batch_receipt = results / "batch_receipt.json"
    batch_receipt.write_text(json.dumps(dict(original_particle_ids=expected)))
    fly = results / "joint.fly2"
    fly.write_text("INERT LAUNCHED STATE FIXTURE\n")
    merge = results / "batch_log_merge_receipt.json"
    merge.write_text(json.dumps(dict(schema_version=1, role="mrtof_measured_batch_log_merge",
        status="success" if complete else "incomplete", preparation=file_record(preparation),
        merged_log=file_record(log), particle_count=97, mother_particle_count=100,
        original_particle_ids=expected, all_batch_losses_retained=True, id_rebasing_applied=False,
        solver_epoch_instrument_time_us=7500.63364160348,
        batches=[dict(log=file_record(log), batch_receipt=file_record(batch_receipt), fly2=file_record(fly))])))
    summary = run / "summary.json"
    summary.write_text(json.dumps(dict(status=status, failure_stage="automatic_joint_diagnostics",
                                       writers_stopped=writers_stopped)))
    request = inputs / "execution_request.json"
    request.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_request",
        package=dict(project=owner, mode="prepared_joint", run_id=run.name))))
    config = run / "run_config.json"
    config.write_text(json.dumps(dict(schema_version=2, run_id=run.name, project=owner, mode="prepared_joint",
        inputs=dict(execution_request=str(request)),
        artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason=recording["reason"]))))
    completion = results / "execution_completion.json"
    completion.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_completion",
        run_id=run.name, project=owner, status=status, run_config=file_record(config),
        execution_request=file_record(request), writer_completion=dict(
            operations=[dict(operation_id="native_flight", resource_release_id="native_flight",
                observation=dict(exit_confirmed=True, returncode=0, process_id=1234,
                                 process_started_at_utc_ticks=1))],
            resource_releases=[dict(release_id="native_flight", completion_receipt=dict(host_release=dict(
                inherited=True, token="fixture-host-token", result=None, error=None)))]))))
    manifest = build_run_manifest(config, status, output_paths=[preparation, log, batch_receipt, fly, merge, summary, completion],
                                  retention_api=retention_api)
    (run / "run_manifest.json").write_text(json.dumps(manifest))
    return run, contract


@unittest.skipUnless(os.name == "nt", "Windows source write exclusion required")
class HistoricalJointAdmissionTests(unittest.TestCase):
    def _reject(self, source, contract, message):
        before = {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}
        with self.assertRaisesRegex((ValueError, AssertionError, FileNotFoundError), message):
            publish_joint_analysis(None, source_manifest=source / "run_manifest.json",
                ancestor_manifests=(), analysis_contract=contract, artifact_store=None,
                committed_new_bytes=1, run_id="20261128_120000__test__python__rejected",
                retention=dict(policy_version=1, **{"class": "compact"}, reason=None))
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_wrong_owner_and_incomplete_native_fail_before_store(self):
        for owner, complete, message in (("multi_reflection_tof", True, "source must be a historical joint flight"),
                                         ("instrument_assembly", False, "complete original-ID")):
            with self.subTest(owner=owner, complete=complete), tempfile.TemporaryDirectory() as directory:
                source, contract = stopped_source_fixture(Path(directory), owner=owner, complete=complete)
                self._reject(source, contract, message)

    def test_unstopped_missing_and_tampered_sources_fail_before_store(self):
        cases = (("unstopped", "writer stop is not confirmed"),
                 ("missing", "prepared_joint_trial"),
                 ("tampered", "guarded file SHA-256 does not match"))
        for scenario, message in cases:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                source, contract = stopped_source_fixture(Path(directory), writers_stopped=scenario != "unstopped")
                preparation = source / "results/prepared_joint_trial.json"
                if scenario == "missing":
                    preparation.unlink()
                elif scenario == "tampered":
                    preparation.write_text(preparation.read_text().replace(
                        "measured_population", "measured_populatioX"))
                self._reject(source, contract, message)

    def test_contract_without_recording_budget_fails_before_store(self):
        with tempfile.TemporaryDirectory() as directory:
            source, contract = stopped_source_fixture(Path(directory))
            contract.write_text(json.dumps(dict(simion={}, peak_analysis={})))
            self._reject(source, contract, "retained-observation budget")
