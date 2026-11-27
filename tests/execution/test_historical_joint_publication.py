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
    for name, record in receipt["outputs"].items():
        receipt["outputs"][name]=file_record(source/Path(record["path"]).name)
    write(source_receipt,receipt)
    prep=dict(fixture.prepared)
    prep["source_receipt"]=file_record(source_receipt)
    for key in ("trajectory_contract","operating_point","reference_materialization","field_binding"):
        original=Path(prep[key]["path"]); target=out/original.name;shutil.copyfile(original,target);prep[key]=file_record(target)
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
    def test_real_owner_sources_and_store_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); helper=test_execution_runtime.NormalOwnerTests();policy=root/"capacity.json"
            policy.write_text(json.dumps(helper._policy()),encoding="utf-8")
            context=replace(helper._context(root),capacity_policy_path=policy,
                host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]))
            context.workspace.mkdir(parents=True)
            fixture=test_recorded_joint_diagnostics.RecordedJointDiagnosticsTests(
                methodName="test_full_pipeline_preserves_mother_raw_branches_losses_and_figures")
            fixture.setUp();self.addCleanup(fixture.doCleanups)
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
