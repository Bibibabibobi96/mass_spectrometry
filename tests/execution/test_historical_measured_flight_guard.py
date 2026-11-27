"""Historical measured-flight identity requires actual stopped writer evidence."""
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.native_source_guard import guard_historical_measured_flight, guard_historical_joint_component
from msplatform.execution.owner import run_managed_stage
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from tests.contracts import test_execution_runtime


def _inert_flight(session):
    session.run_process('fixture',executable=Path(sys.executable),arguments=['-c','pass'],role='GATE',stage='software_tests',limits=None)
    output=session.declare_file(session.result_dir/'evidence.json','required_evidence')
    output.write_text('{}',encoding='utf-8')
    return dict(status='success',summary={'fixture':'INERT_ONLY'},output_paths=[str(output)],
        required_output_paths=[str(output)],retention_preserve_paths=[],manifest_extra_fields={})


@unittest.skipUnless(os.name=='nt' and os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'),'shared Windows host ledger required')
class HistoricalFlightGuardTests(unittest.TestCase):
    def test_real_owner_writer_proof_and_exact_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);helper=test_execution_runtime.NormalOwnerTests();policy=root/'capacity.json'
            policy.write_text(json.dumps(helper._policy()),encoding='utf-8')
            context=replace(helper._context(root),capacity_policy_path=policy,
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']))
            context.workspace.mkdir(parents=True)
            args=helper._arguments(root,_inert_flight)
            args.update(descriptor={'project':'instrument_assembly','mode':'prepared_joint','software':[]},
                run_id='20261127_170000__test__python__measured',expected_operation_ids=('fixture',),
                operation_dependencies={},action_record=file_record(Path(__file__),'required_evidence'),
                completion_api=no_particle_batch_completion_api)
            store=ArtifactStore(root/'store');result=run_managed_stage(context,artifact_store=store,**args)
            with guard_historical_measured_flight(result['manifest']) as source:
                record=source.output('results/evidence.json')
                with self.assertRaises(PermissionError): Path(record['path']).unlink()
                with self.assertRaises(ValueError): source.output('results/not-listed.json')
            bad=dict(result['manifest'],sha256='0'*64)
            with self.assertRaises(ValueError):
                with guard_historical_measured_flight(bad): pass

    def test_real_component_owner_proof_and_wrong_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); helper = test_execution_runtime.NormalOwnerTests(); policy = root / 'capacity.json'
            policy.write_text(json.dumps(helper._policy()), encoding='utf-8')
            context = replace(helper._context(root), capacity_policy_path=policy,
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']))
            context.workspace.mkdir(parents=True)
            args = helper._arguments(root, _inert_flight)
            args.update(descriptor={'project':'dual_pressure_rectilinear_ion_processor',
                'mode':'native_electrode_functional','software':[]},
                run_id='20261127_170001__test__python__component', expected_operation_ids=('fixture',),
                operation_dependencies={}, action_record=file_record(Path(__file__), 'required_evidence'),
                completion_api=no_particle_batch_completion_api)
            store = ArtifactStore(root/'store'); result = run_managed_stage(context, artifact_store=store, **args)
            with guard_historical_joint_component(result['manifest']) as source:
                record = source.output('results/evidence.json')
                with self.assertRaises(PermissionError): Path(record['path']).unlink()
            with self.assertRaises(ValueError):
                with guard_historical_measured_flight(result['manifest']): pass
