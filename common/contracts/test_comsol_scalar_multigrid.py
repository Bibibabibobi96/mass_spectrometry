"""Inert scalar batch owner; no COMSOL execution or qualification."""
import json
import struct
import unittest
from pathlib import Path
from unittest.mock import patch
from common.contracts import test_assembly_scalar_owner_fill as fixtures
from msplatform.backends.comsol import assembly_field_export as subject
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.io.manifest_records import verify_record

class ScalarMultiGridTests(unittest.TestCase):
    def prepare(self):
        f=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');f.setUp();self.addCleanup(f.doCleanups)
        return f
    def run_batch(self,f,mode='normal'):
        def native(operation,**kwargs):
            f.calls.append((operation,kwargs))
            for record in kwargs['immutable_input_records']: verify_record('inert native input',record)
            spec=json.loads((f.root/'inputs/world-grid-batch.json').read_text(encoding='utf8'))
            for index,entry in enumerate(spec['entries']):
                g=json.loads(Path(entry['grid_path']).read_text(encoding='utf8'))
                hp=PaHeader(-2,1,200.,5,3,3,1<<28,1,1,1);hm=PaHeader(-2,1,1.,5,3,3,1<<28,1,1,1)
                vals=[0.]*45;vals[0]=-0.;mask=[0.]*45;mask[0]=1.
                if index==1 and mode=='fail_second':raise ValueError('second grid failed')
                for name,h,data in [('field_v.pa',hp,vals),('field_valid.pa',hm,mask)]:
                    (Path(entry['output_directory'])/name).write_bytes(h.pack()+struct.pack('<45d',*data))
                report=dict(g,status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(f.source.data_locations['model']),vacuum_domains=[1],fem_valid=1,invalid_count=44,solution_readback=f.solution,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'})
                Path(entry['report_path']).write_text(json.dumps(report),encoding='utf8')
                if index==0 and mode=='tamper':
                    Path(entry['grid_path']).write_text('{}',encoding='utf8')
                    for record in kwargs['immutable_input_records']: verify_record('inert post-input',record)
            (f.root/'logs/export_world_scalar.bootstrap.log').write_text('STATUS=PASS',encoding='utf8')
            (f.root/'results/export_world_scalar_batch.json').write_text(json.dumps({'status':'success','scope':'assembly_world_scalar_grid_batch','grid_count':3,'compute_calls':0}),encoding='utf8')
        f.session.run_process=native
        cleanup_error=ValueError('diagnostic preservation failed') if mode=='cleanup_failure' else None
        with patch.object(subject,'freeze_native_sources',return_value=(f.root/'native/launcher.ps1',[])),patch.object(subject,'declare_runtime_files',side_effect=cleanup_error),patch.object(subject,'require_launcher_completion'):
            return subject.execute_export(f.session,source=f.source,manifest_record={'path':'synthetic'},grid=f.grid,baseline={'vacuum_domains':[1]},solution_identity=f.solution,writer_authority=f.writer_record,writer=f.writer_record,limits={},grids={name:dict(f.grid,origin_mm=[-2+index,-1,-1]) for index,name in enumerate(('one','two','three'))})
    def test_one_process_three_products_match_single(self):
        references=[]
        for index in range(3):
            single=self.prepare();single.grid['origin_mm']=[-2+index,-1,-1]
            references.append(single.action(False)['manifest_extra_fields']['products']['samples'])
        batch=self.prepare();result=self.run_batch(batch);products=result['manifest_extra_fields']['products']
        self.assertEqual(set(products),{'samples_one','samples_two','samples_three'});self.assertEqual(len(batch.calls),1)
        for product,reference in zip(products.values(),references,strict=True):
            for key in ('field_v','field_valid'):
                self.assertEqual(Path(product['data'][key]['path']).read_bytes(),Path(reference['data'][key]['path']).read_bytes())
            first=json.loads(Path(reference['data']['report']['path']).read_text());second=json.loads(Path(product['data']['report']['path']).read_text())
            first.pop('model_path');second.pop('model_path');self.assertEqual(first,second)
        self.assertEqual(len({product['data']['field_v']['path'] for product in products.values()}),3)
    def test_second_failure_preserves_first_grid(self):
        f=self.prepare()
        with self.assertRaisesRegex(ValueError,'second grid failed') as caught:self.run_batch(f,mode='fail_second')
        names={Path(p).name for p in caught.exception.failure_output_paths}
        self.assertIn('export_world_scalar_one.json',names);self.assertIn('field_v.pa',names)
    def test_completed_grids_preserved_when_diagnostic_cleanup_fails(self):
        f=self.prepare()
        with self.assertRaisesRegex(ValueError,'diagnostic preservation failed') as caught:
            self.run_batch(f,mode='cleanup_failure')
        paths={str(p) for p in caught.exception.failure_output_paths}
        for name in ('one','two','three'):
            self.assertIn(str(f.root/'results'/('export_world_scalar_'+name+'.json')),paths)
            self.assertIn(str(f.root/'scalar'/name/'field_v.pa'),paths)
            self.assertIn(str(f.root/'scalar'/name/'field_valid.pa'),paths)
    def test_tampered_grid_refuses_and_keeps_earlier_output(self):
        f=self.prepare()
        with self.assertRaisesRegex(AssertionError,'changed') as caught:self.run_batch(f,mode='tamper')
        self.assertTrue(any(Path(p).name=='export_world_scalar_one.json' for p in caught.exception.failure_output_paths))
    def test_bad_names_refuse_before_source_open(self):
        for value in ({}, {'Bad/name':{}}):
            with self.subTest(value=value),patch.object(subject,'open_artifact',side_effect=AssertionError('should not open')):
                with self.assertRaises(ValueError):subject.export_world_scalar_grids({},grids=value,writer_manifest={},context=None)

    def test_duplicate_mapping_names_refused(self):
        from collections.abc import Mapping
        class Duplicate(Mapping):
            def __iter__(self):return iter(('one','one'))
            def __len__(self):return 2
            def __getitem__(self,key):return {}
        with patch.object(subject,'open_artifact',side_effect=AssertionError('should not open')):
            with self.assertRaisesRegex(ValueError,'unique'):
                subject.export_world_scalar_grids({},grids=Duplicate(),writer_manifest={},context=None)
    def test_public_named_products_and_capacity_refusal(self):
        f=self.prepare();f.projection['outer_box_mm']={'min':[-10,-10,-10],'max':[10,10,10]}
        f.source.data_locations['projection'].write_text(json.dumps(f.projection),encoding='utf8')
        f.source.metadata={'backend':'comsol','scope':'single_stationary_workpoint','field_status':'solved','native_reopen_verified':True,'solution':f.solution}
        (f.root/'comsol').write_bytes(b'inert')
        base={key:value for key,value in f.grid.items() if key not in ('point_count','coordinate_sanity_mm')}
        grids={name:dict(base,origin_mm=[-2+i,-1,-1]) for i,name in enumerate(('one','two','three','four'))}
        stage={'limits':{'transient_run_directory_bytes':1000000,'compact_final_retained_bytes':1000000},'artifact_retention':{}}
        with patch.object(subject,'open_artifact',side_effect=[f.source,'one-product','two-product','three-product','four-product']),patch.object(subject,'resolve_published_writer',return_value=(f.writer_record,f.writer_record)),patch.object(subject,'read_stage_policy',return_value=(stage,{})),patch.object(subject,'resolve_model_source_manifests',return_value=({'path':'source'},None)),patch.object(subject,'run_managed_stage',return_value={'manifest':{}}) as owner:
            actual=subject.export_world_scalar_grids({},grids=grids,writer_manifest={},context=f.context)
        self.assertEqual(actual,{'one':'one-product','two':'two-product','three':'three-product','four':'four-product'})
        self.assertEqual(owner.call_args.kwargs['expected_operation_ids'],('export_world_scalar',))
        self.assertEqual(list(owner.call_args.kwargs['payload']['grids']),['one','two','three','four'])
        stage['limits']['transient_run_directory_bytes']=1
        with patch.object(subject,'open_artifact',return_value=f.source),patch.object(subject,'resolve_published_writer',return_value=(f.writer_record,f.writer_record)),patch.object(subject,'read_stage_policy',return_value=(stage,{})),patch.object(subject,'run_managed_stage') as owner:
            with self.assertRaisesRegex(ValueError,'minimum'):subject.export_world_scalar_grids({},grids=grids,writer_manifest={},context=f.context)
            owner.assert_not_called()
