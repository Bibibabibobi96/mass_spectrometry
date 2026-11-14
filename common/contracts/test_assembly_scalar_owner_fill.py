"""Inert owner-boundary tests exercising actual private scalar PA fill."""
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common.contracts.test_assembly_scalar_fill import fixture
from msplatform.backends.comsol import assembly_field_export as subject
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.io.manifest_records import file_record, verify_record

class ScalarOwnerFillTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for n in ('inputs','results','logs','original','native'): (self.root/n).mkdir()
        self.projection,self.request,self.grid=fixture()
        self.grid.update(block_points=10,study_tag='std1',solution_tag='sol1',dataset_tag='dset1',coordinate_sanity_mm=1e-6)
        self.solution={'study_tag':'std1','solution_tag':'sol1','dataset_tag':'dset1','dataset_solution':'sol1','solution_empty':False,'solution_count':1,'stored_main_solutions':1,'solution_dofs':7}
        data={'projection':self.projection,'request':self.request,'geometry_validation':{'position_mm':1e-6},'reopen_geometry':{'vacuum_domains':[1]},'reopen_solution':self.solution}
        paths={}
        for name,value in data.items():
            path=self.root/'original'/f'{name}.json';path.write_text(json.dumps(value),encoding='utf-8');paths[name]=path
        paths['model']=self.root/'original/model.mph';paths['model'].write_bytes(b'dummy model, never loaded')
        self.source=SimpleNamespace(data_path=lambda n:paths[n],data_locations=paths,data_records={n:file_record(p,'solver_native_binary' if n=='model' else 'required_evidence') for n,p in paths.items()})
        self.writer=self.root/'native/simion_pa_save.m';self.writer.write_bytes(b'fixture writer');self.writer_record=file_record(self.writer,'required_evidence')
        self.context=SimpleNamespace(workspace=self.root,python_executable=self.root/'python',powershell_executable=self.root/'pwsh',host_state_path=self.root/'state',policy_path=self.root/'policy',tools={'comsol_launcher':self.root/'comsol','matlab_root':self.root})
        self.inputs={};self.calls=[];self.session=SimpleNamespace(expected_operation_ids=('export_world_scalar',),input_dir=self.root/'inputs',result_dir=self.root/'results',log_dir=self.root/'logs',run_dir=self.root,context=self.context,run_id='inert',declare_file=lambda p,r:p,add_input=lambda n,r:self.inputs.update({n:r}))
        self.mode='normal';self.session.run_process=self.simulate
    def simulate(self,operation,**kwargs):
        self.calls.append((operation,kwargs))
        if self.mode=='tamper':
            record=next(r for r in kwargs['immutable_input_records'] if 'scalar_support' in r['path'])
            Path(record['path']).write_bytes(b'tampered')
        for record in kwargs['immutable_input_records']:verify_record('mock native guard',record)
        hp=PaHeader(-2,1,200.,5,3,3,1<<28,1,1,1);hm=PaHeader(-2,1,1.,5,3,3,1<<28,1,1,1)
        values=[0.]*45;values[0]=-0.;mask=[0.]*45;mask[0]=1.
        if self.mode=='vacuum':mask=[1.]*45;mask[22]=0.
        for name,header,data in [('field_v.pa',hp,values),('field_valid.pa',hm,mask)]:
            (self.root/'scalar'/name).write_bytes(header.pack()+b''.join(struct.pack('<d',v) for v in data))
        (self.root/'logs/export_world_scalar.bootstrap.log').write_text('STATUS=PASS',encoding='utf-8')
        row=dict(self.grid,status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(self.source.data_locations['model']),vacuum_domains=[1],fem_valid=int(sum(mask)),invalid_count=45-int(sum(mask)),solution_readback=self.solution,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'})
        (self.root/'results/export_world_scalar.json').write_text(json.dumps(row),encoding='utf-8')
    def action(self,enabled):
        with patch.object(subject,'freeze_native_sources',return_value=(self.root/'native/launcher.ps1',[])),patch.object(subject,'declare_runtime_files'),patch.object(subject,'require_launcher_completion'):
            return subject.execute_export(self.session,source=self.source,manifest_record={'path':'synthetic'},grid=self.grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,writer_authority=self.writer_record,writer=self.writer_record,limits={},fill_conductor_interiors=enabled)
    def test_false_keeps_raw_export(self):
        product=self.action(False)['manifest_extra_fields']['products']['samples'];self.assertNotIn('conductor_support',product['data']);self.assertEqual(len(self.calls),1)
        self.assertEqual(Path(product['data']['field_v']['path']).name,'field_v.pa')
    def test_true_real_fill_and_finite_bits(self):
        product=self.action(True)['manifest_extra_fields']['products']['samples'];data=product['data'];self.assertEqual(len(self.calls),1)
        before=Path(data['sampled_field_v']['path']).read_bytes();after=Path(data['field_v']['path']).read_bytes()
        self.assertEqual(before[56:64],after[56:64]);self.assertEqual(after[56:64],struct.pack('<d',-0.))
        self.assertEqual(struct.unpack_from('<d',after,56+8*21)[0],-100.)
        self.assertGreater(json.loads(Path(data['conductor_support']['path']).read_text())['result']['filled_conductor_count'],0)
        self.assertEqual(len([key for key in self.inputs if key.startswith('scalar_support_original_')]),5)
    def test_vacuum_missing_stays_invalid(self):
        self.mode='vacuum';data=self.action(True)['manifest_extra_fields']['products']['samples']['data']
        self.assertEqual(struct.unpack_from('<d',Path(data['field_valid']['path']).read_bytes(),56+8*22)[0],0.)
    def test_bad_request_before_native(self):
        self.request['group_voltages'].pop();self.source.data_locations['request'].write_text(json.dumps(self.request),encoding='utf-8')
        self.source.data_records['request']=file_record(self.source.data_locations['request'],'required_evidence')
        with self.assertRaisesRegex(ValueError,'coverage'):self.action(True)
        self.assertFalse(self.calls)
    def test_tampered_code_fails_and_no_product(self):
        self.mode='tamper'
        with self.assertRaises(AssertionError):self.action(True)
        self.assertEqual(len(self.calls),1)
    def test_fill_error_does_not_return_product(self):
        with patch('msplatform.backends.comsol.assembly_scalar_fill.fill_invalid_scalar_pa',side_effect=ValueError('support failure')):
            with self.assertRaisesRegex(ValueError,'support failure') as caught:self.action(True)
        self.assertTrue(any(str(x).endswith('field_v.pa') for x in caught.exception.failure_output_paths))
    def test_missing_code_fails_before_native(self):
        from msplatform.components import shape_query
        with patch.object(shape_query, '__file__', str(self.root/'absent.py')), self.assertRaises(FileNotFoundError):
            self.action(True)
        self.assertFalse(self.calls)
    def test_missing_module_fails_before_native(self):
        import builtins
        actual = builtins.__import__
        def missing(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'msplatform.components' and 'shape_query' in fromlist:
                raise ImportError('selected shape query unavailable')
            return actual(name, globals, locals, fromlist, level)
        with patch('builtins.__import__', side_effect=missing), self.assertRaisesRegex(ImportError, 'selected shape query unavailable'):
            self.action(True)
        self.assertFalse(self.calls)
    def test_public_opt_in_is_frozen_in_payload_and_action(self):
        self.projection['outer_box_mm']={'min':[-2,-2,-2],'max':[3,3,3]}
        self.source.data_locations['projection'].write_text(json.dumps(self.projection),encoding='utf-8')
        self.source.metadata={'backend':'comsol','scope':'single_stationary_workpoint','field_status':'solved','native_reopen_verified':True,'solution':self.solution}
        self.source.reference={'manifest':{'path':'source'}}
        self.source.manifest_location=self.root/'source.json'
        (self.root/'comsol').write_bytes(b'fixture')
        grid=dict(self.grid);grid.pop('point_count');grid.pop('coordinate_sanity_mm')
        stage={'limits':{'transient_run_directory_bytes':1},'artifact_retention':{}}
        for enabled in (False,True):
            with self.subTest(enabled=enabled),patch.object(subject,'open_artifact',side_effect=[self.source,'published']),patch.object(subject,'validate_solution_readback'),patch.object(subject,'resolve_published_writer',return_value=(self.writer_record,self.writer_record)),patch.object(subject,'read_stage_policy',return_value=(stage,{})),patch.object(subject,'resolve_model_source_manifests',return_value=({'path':'source'},None)),patch.object(subject,'run_managed_stage',return_value={'manifest':{}}) as owner:
                self.assertEqual(subject.export_world_scalar(None,grid=grid,writer_manifest={},context=self.context,fill_conductor_interiors=enabled),'published')
                self.assertIs(owner.call_args.kwargs['payload']['fill_conductor_interiors'],enabled)
                self.assertIs(owner.call_args.kwargs['action'].keywords['fill_conductor_interiors'],enabled)
    def test_public_bad_group_refuses_before_owner(self):
        self.projection['outer_box_mm']={'min':[-2,-2,-2],'max':[3,3,3]}
        self.source.data_locations['projection'].write_text(json.dumps(self.projection),encoding='utf-8')
        self.request['group_voltages'].pop();self.source.data_locations['request'].write_text(json.dumps(self.request),encoding='utf-8')
        self.source.metadata={'backend':'comsol','scope':'single_stationary_workpoint','field_status':'solved','native_reopen_verified':True,'solution':self.solution}
        grid=dict(self.grid);grid.pop('point_count');grid.pop('coordinate_sanity_mm')
        with patch.object(subject,'open_artifact',return_value=self.source),patch.object(subject,'validate_solution_readback'),patch.object(subject,'run_managed_stage') as owner:
            with self.assertRaisesRegex(ValueError,'coverage'):subject.export_world_scalar(None,grid=grid,writer_manifest={},context=self.context,fill_conductor_interiors=True)
        owner.assert_not_called()
    def test_boolean_policy_is_exact(self):
        with self.assertRaisesRegex(ValueError,'boolean'):subject.export_world_scalar(None,grid={},writer_manifest={},context=None,fill_conductor_interiors=1)
