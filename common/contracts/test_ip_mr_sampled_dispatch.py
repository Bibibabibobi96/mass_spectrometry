"""Public sampled-field dispatch with registered test-only source producers."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from common.contracts.test_support import ip_mr_sampled_field_fixture as fixture
from common.contracts.test_support.sfi_scalar_owner_fixture import publish_fixture
from msplatform.backends.simion import operations as subject
from msplatform.contracts.machine_contracts import ContractError
from msplatform.results.artifacts import OpenedArtifact, open_artifact

class SampledDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        host_token=patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
        host_token.start()
        cls.addClassCleanup(host_token.stop)
        cls.root=Path(tempfile.mkdtemp(prefix='ip-mr-dispatch-fixture-'))
        cls.manager=fixture.build_sampled_field_fixture(cls.root)
        cls.selected=cls.manager.__enter__()
        f=cls.selected;cls.context=f['context'];cls.model=f['model_reference']
        cls.selection=dict(f['scalar_field_basis'],collision_priority_evidence=f['priority_evidence'])
        cls.product=publish_fixture(cls.context,f['budget'],f['retention'],name='dispatch-fields',kind='field_bundle',data={'inert_receipt':{'scope':'test_only_dispatch_not_field_science'}},metadata={'field_representation':'assembly_sampled_basis_with_collision_geometry'})
        path=f['stage_policy_path'];policy=json.loads(path.read_text(encoding='utf8'))
        policy['stages']['solve_fields']=dict(limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=6442450944,process_tree_working_set_bytes=536870912,minimum_system_available_memory_bytes=1,compact_final_retained_bytes=16777216,automatic_retry_count=0,reserved_run_payload_bytes=6442450944),artifact_retention=f['retention'])
        path.write_text(json.dumps(policy),encoding='utf8');cls.policy=policy

    @classmethod
    def tearDownClass(cls):
        cls.manager.__exit__(None,None,None)
        print('DISPATCH_FIXTURE_RETAINED',cls.root,flush=True)

    def setUp(self):
        self.selected['stage_policy_path'].write_text(json.dumps(self.policy),encoding='utf8')

    def opened_field(self,reference,*,expected_kind):
        self.assertEqual(reference['product_id'],'fields')
        return open_artifact(self.product,expected_kind=expected_kind)

    def test_actual_artifacts_relative_references_and_dispatch(self):
        def relative(reference,kind):
            absolute=Path(reference['manifest']['path'])
            ref={'manifest':dict(reference['manifest'],path='run_manifest.json'),'product_id':reference['product_id']}
            def resolve(record,base):return absolute if record['path']=='run_manifest.json' else Path(record['path'])
            result=open_artifact(ref,expected_kind=kind,resolver=resolve)
            self.assertFalse(Path(result.reference['manifest']['path']).is_absolute());return result
        selection=dict(self.selection,geometry_artifact=relative(self.selection['geometry_artifact'],'geometry_artifact'))
        selection['samples']=dict(selection['samples'],carrier=relative(selection['samples']['carrier'],'scalar_field_samples'))
        model=relative(self.model,'prepared_model')
        with patch('msplatform.execution.owner.run_managed_stage',return_value={'manifest':self.product['manifest']}) as owner, patch.object(subject.artifact_reader,'open_artifact',side_effect=self.opened_field):
            result=subject.solve_fields(model,numerics={},context=self.context,scalar_field_basis=selection)
        self.assertIsInstance(result,OpenedArtifact);self.assertEqual(result.metadata['field_representation'],'assembly_sampled_basis_with_collision_geometry')
        options=owner.call_args.kwargs;ids=options['expected_operation_ids']
        self.assertEqual(ids,self.selected['expected_operation_ids']);self.assertEqual(len(ids),12)
        self.assertEqual(options['operation_dependencies'][ids[-1]],[ids[-2]])
        self.assertEqual(options['payload']['scalar_field_basis'],self.selection)
        self.assertGreaterEqual(len(options['source_references']),19)
        self.assertEqual(options['action'].func.__name__,'execute_ip_mr_sampled_fields')
        json.dumps(options['payload'],allow_nan=False)
        self.assertFalse((self.context.execution_root/'sampled-fields-plan').exists())

    def test_bad_selection_before_owner(self):
        with patch('msplatform.execution.owner.run_managed_stage') as owner:
            for options in (dict(numerics={'refine':1},scalar_field_basis=self.selection),dict(numerics={},scalar_field_basis=self.selection,reuse_fields={'invalid':True}),dict(numerics={},scalar_field_basis={'samples':{}}),dict(numerics={},scalar_field_basis=dict(self.selection,samples=[])),dict(numerics={},scalar_field_basis=dict(self.selection,collision_priority_evidence={})),dict(numerics={},scalar_field_basis=dict(self.selection,refinement_windows=[{'samples':[]}]))):
                with self.subTest(options=options),self.assertRaises(ContractError):subject.solve_fields(self.model,context=self.context,**options)
            owner.assert_not_called()

    def test_both_insufficient_limits_before_owner(self):
        path=self.selected['stage_policy_path']
        with patch('msplatform.execution.owner.run_managed_stage') as owner:
            for key in ('reserved_run_payload_bytes','transient_run_directory_bytes'):
                policy=copy.deepcopy(self.policy);limits=policy['stages']['solve_fields']['limits'];limits[key]=16777216
                if key=='transient_run_directory_bytes':limits['reserved_run_payload_bytes']=16777216
                path.write_text(json.dumps(policy),encoding='utf8')
                with self.subTest(limit=key),self.assertRaisesRegex(ContractError,'collision output lower bound'):subject.solve_fields(self.model,numerics={},context=self.context,scalar_field_basis=self.selection)
            owner.assert_not_called()

    def test_original_branch_unchanged(self):
        source=SimpleNamespace(artifact=SimpleNamespace(reference={'manifest':{'path':'model-manifest'},'product_id':'model'}),model=SimpleNamespace(document={'geometry':{'frontend_geometry':{'role':'simion_independent_rf_geometry'}}}))
        graph=dict(expected_operation_ids=('existing_operation',),operation_dependencies={})
        with patch('msplatform.backends.simion.field_closure.load_field_model',return_value=source), patch('msplatform.backends.simion.field_execution.plan_fields_execution',return_value=graph), patch('msplatform.execution.owner.run_managed_stage',return_value={'manifest':self.product['manifest']}) as owner, patch.object(subject.artifact_reader,'open_artifact',side_effect=self.opened_field):
            subject.solve_fields(self.model,numerics={'existing':1},context=self.context)
        self.assertEqual(owner.call_args.kwargs['payload']['numerics'],{'existing':1})
        self.assertNotIn('scalar_field_basis',owner.call_args.kwargs['payload'])
        self.assertEqual(owner.call_args.kwargs['action'].func.__name__,'execute_fields')
