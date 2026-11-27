"""Public paired static source admission; no commercial solver is invoked."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.workflows.paired_accelerator_static_field.store_workflow import run_paired_static_comparison
from tests.components.single_reflection_oa_tof_mass_analyzer.analysis import test_paired_accelerator_static_field_prepare as preparation


class PairedStaticWorkflowAdmissionTests(unittest.TestCase):
    def test_successful_frozen_inputs_enter_store_owner_and_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = preparation.PairedAcceleratorStaticFieldPrepareTests()
            request = fixture._request(root)
            path = fixture._write_request(root, request)
            policy = root / 'policy.json'
            policy.write_text('{}', encoding='utf8')
            stage = {'artifact_retention': {}, 'limits': {}}
            def owner(context, **kwargs):
                self.assertEqual(kwargs['artifact_store'], 'store')
                self.assertEqual(len(kwargs['commitment_inputs']), 5)
                self.assertEqual(kwargs['expected_operation_ids'], ['paired_simion', 'paired_comsol', 'paired_analysis'])
                return {'status': 'owner_fixture'}
            with patch('msplatform.workflows.paired_accelerator_static_field.store_workflow.read_stage_policy', return_value=(stage, {'path': str(policy)})), \
                 patch('msplatform.workflows.paired_accelerator_static_field.store_workflow.run_managed_stage', side_effect=owner):
                result = run_paired_static_comparison(None, artifact_store='store', request_path=path,
                    run_id='paired-fixture', committed_new_bytes=1024)
                self.assertEqual(result['status'], 'owner_fixture')
                Path(request['source_records']['frontend_geometry']['path']).write_text('{}', encoding='utf8')
                with self.assertRaises(AssertionError):
                    run_paired_static_comparison(None, artifact_store='store', request_path=path,
                        run_id='paired-tampered', committed_new_bytes=1024)

    def test_rejects_unpublished_and_failed_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = preparation.PairedAcceleratorStaticFieldPrepareTests()
            request = fixture._request(root)
            path = fixture._write_request(root, request)
            parent = Path(request['source_records']['parent_manifest']['path'])
            document = json.loads(parent.read_text(encoding='utf8'))
            document['status'] = 'failed'
            parent.write_text(json.dumps(document), encoding='utf8')
            from msplatform.io.manifest_records import file_record
            request['source_records']['parent_manifest'] = file_record(parent, 'required_evidence')
            path.write_text(json.dumps(request), encoding='utf8')
            with patch('msplatform.workflows.paired_accelerator_static_field.store_workflow.read_stage_policy', return_value=({'artifact_retention': {}, 'limits': {}}, {})), \
                 patch('msplatform.workflows.paired_accelerator_static_field.store_workflow.run_managed_stage') as owner:
                with self.assertRaisesRegex(ValueError, 'successfully published'):
                    run_paired_static_comparison(None, artifact_store='store', request_path=path,
                        run_id='paired-failed', committed_new_bytes=1024)
                owner.assert_not_called()


    def test_action_projection_with_stubbed_native_leaves(self):
        """Real preparation and analysis; both vendor leaves explicitly stubbed."""
        import csv
        import subprocess
        import sys
        from types import SimpleNamespace
        from msplatform.io.manifest_records import file_record
        from msplatform.workflows.paired_accelerator_static_field import store_workflow as workflow

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author = root / 'author'; author.mkdir()
            fixture = preparation.PairedAcceleratorStaticFieldPrepareTests()
            request = fixture._request(author)
            request_path = fixture._write_request(author, request)
            run = root / 'run'; run.mkdir()
            class Session:
                run_dir = run
                input_dir = run / 'inputs'
                result_dir = run / 'results'
                log_dir = run / 'logs'
                run_id = 'inert'
                context = SimpleNamespace(workspace=root, python_executable=Path(sys.executable),
                    powershell_executable=Path(sys.executable), host_state_path=root/'host',
                    policy_path=root/'policy', tools={'comsol_launcher':Path(sys.executable), 'matlab_root':root})
                def declare_file(self, path, role):
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    return Path(path)
                def add_input(self, name, record): pass
                def run_process(self, name, **kwargs):
                    if name == 'paired_analysis':
                        subprocess.run([str(kwargs['executable']), *kwargs['arguments']], check=True, capture_output=True,
                            cwd=self.run_dir, timeout=30)
                        return
                    self.assert_comsol = name
                    output = self.run_dir / 'comsol'
                    points = list(csv.DictReader((self.input_dir/'bvp/paired_accelerator_field_points.csv').read_text(encoding='utf8').splitlines()))
                    fields = ['point_id','x_mm','y_mm','z_mm','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m']
                    with (output/'comsol_field_samples.csv').open('w', newline='', encoding='utf8') as stream:
                        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
                        for row in points: writer.writerow(dict(row, Ex_V_per_m=1, Ey_V_per_m=2, Ez_V_per_m=3))
                    model = output/'paired_accelerator_static.mph'; model.write_text('INERT MODEL', encoding='utf8')
                    (output/'comsol_field_native_facts.json').write_text(json.dumps(dict(backend='COMSOL',coordinate_unit='mm',
                        field_unit=['V/m']*3,point_count=len(points),plan_path=str(self.input_dir/'bvp/paired_accelerator_static_field_plan.json'),model_path=str(model),sample_path=str(output/'comsol_field_samples.csv'))), encoding='utf8')
                    (output/'comsol_field_solution.json').write_text(json.dumps(dict(role='oatof_paired_accelerator_static_field_solution',
                        schema_version=1,solution_tag='sol1',study_tag='std1',plan_path=str(self.input_dir/'bvp/paired_accelerator_static_field_plan.json'),model_path=str(model),status='solved_saved',solution_present=True,mesh_complete=True,tetrahedra=1)), encoding='utf8')
                    (self.log_dir/'paired_comsol.bootstrap.log').write_text('STATUS=PASS', encoding='utf8')
            session = Session()
            def simion(session, *, plan_record, **kwargs):
                plan = json.loads(Path(plan_record['path']).read_text(encoding='utf8'))
                points = list(csv.DictReader(Path(plan['sample_points']['path']).read_text(encoding='utf8').splitlines()))
                samples = session.log_dir/'simion.csv'; facts = session.log_dir/'simion.txt'
                samples.parent.mkdir(parents=True,exist_ok=True)
                fields = ['point_id','x_mm','y_mm','z_mm','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m']
                with samples.open('w',newline='',encoding='utf8') as stream:
                    writer = csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                    for row in points: writer.writerow(dict(row,Ex_V_per_m=1,Ey_V_per_m=2,Ez_V_per_m=3))
                facts.write_text('INERT',encoding='utf8')
                return dict(sample_record=file_record(samples,'required_evidence'),facts_record=file_record(facts,'required_evidence'),
                            cache_disposition='fixture',native_count=0)
            records = {name:file_record(Path(record['path']),'required_evidence') for name,record in request['source_records'].items()}
            with patch.object(workflow,'run_paired_static_simion',side_effect=simion), \
                 patch.object(workflow,'require_launcher_completion'):
                result = workflow._action(session,request_record=file_record(request_path,'required_evidence'),
                    source_records=records,source_base=author,limits={})
            self.assertEqual(result['status'],'success')
            self.assertEqual(result['summary']['qualification'],'descriptive_only_no_equivalence_tolerance')
            self.assertEqual(session.assert_comsol,'paired_comsol')
            metrics = json.loads((run/'results/comparison/accelerator_vector_field_metrics.json').read_text(encoding='utf8'))
            self.assertEqual(metrics['sample_points'],2)
            # The saved model is passed in place to the COMSOL launch, not copied.
            class StopAtNative(Exception): pass
            second = root/'run_saved'; second.mkdir()
            class SavedSession(Session):
                run_dir=second
                input_dir=second/'inputs'
                result_dir=second/'results'
                log_dir=second/'logs'
                def run_process(self, name, **kwargs):
                    self.native = (name, kwargs)
                    raise StopAtNative()
            prior_plan=run/'inputs/bvp/paired_accelerator_static_field_plan.json'
            prior_model=run/'comsol/paired_accelerator_static.mph'
            saved=dict(manifest=file_record(request_path,'required_evidence'),
                plan=file_record(prior_plan,'required_evidence'),
                solution=file_record(run/'comsol/comsol_field_solution.json','required_evidence'),
                model=file_record(prior_model,'required_evidence'),asset_id=None,claim_token=None,
                source_stage='solved_saved')
            other=SavedSession()
            with patch.object(workflow,'run_paired_static_simion',side_effect=simion):
                with self.assertRaises(StopAtNative):
                    workflow._action(other,request_record=file_record(request_path,'required_evidence'),
                        source_records=records,source_base=author,limits={},saved_model=saved)
            self.assertIn(str(prior_model),(second/'inputs/paired_comsol_task.m').read_text(encoding='utf8'))
            self.assertIn(saved['model'],other.native[1]['immutable_input_records'])
            self.assertFalse((second/'comsol/paired_accelerator_static.mph').exists())
            third=root/'run_samples';third.mkdir()
            class SamplesSession(Session):
                run_dir=third
                input_dir=third/'inputs'
                result_dir=third/'results'
                log_dir=third/'logs'
                def run_process(self, name, **kwargs):
                    if name!='paired_analysis':
                        raise AssertionError('completed samples must not invoke COMSOL')
                    return super().run_process(name,**kwargs)
            prior_samples=dict(plan=file_record(prior_plan,'required_evidence'),
                samples=file_record(run/'comsol/comsol_field_samples.csv','required_evidence'),
                facts=file_record(run/'comsol/comsol_field_native_facts.json','required_evidence'),asset_id=None)
            prior_model.unlink()
            with patch.object(workflow,'run_paired_static_simion',side_effect=simion):
                reused=workflow._action(SamplesSession(),request_record=file_record(request_path,'required_evidence'),
                    source_records=records,source_base=author,limits={},saved_samples=prior_samples)
            self.assertEqual(reused['summary']['comsol_native_count'],0)
            self.assertEqual(reused['summary']['comsol_source'],'completed_samples')
            fourth=root/'run_failure';fourth.mkdir()
            class FailureSession(Session):
                run_dir=fourth
                input_dir=fourth/'inputs'
                result_dir=fourth/'results'
                log_dir=fourth/'logs'
                def run_process(self,name,**kwargs):
                    (self.run_dir/'comsol/paired_accelerator_static.mph').write_bytes(b'INERT FAILURE EVIDENCE')
                    (self.run_dir/'comsol/comsol_field_solution.json').write_text('{}',encoding='utf8')
                    raise RuntimeError('simulated native failure')
            with patch.object(workflow,'run_paired_static_simion',side_effect=simion):
                with self.assertRaisesRegex(RuntimeError,'simulated native failure') as failure:
                    workflow._action(FailureSession(),request_record=file_record(request_path,'required_evidence'),
                        source_records=records,source_base=author,limits={})
            self.assertEqual({path.name for path in failure.exception.failure_output_paths},
                             {'paired_accelerator_static.mph','comsol_field_solution.json'})
