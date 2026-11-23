import copy
import struct
import tempfile
import unittest
from pathlib import Path
from msplatform.backends.comsol.assembly_scalar_fill import fill_invalid_scalar_pa
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from tests.contracts.test_assembly_scalar_fill import fixture

class PreparedSupportTests(unittest.TestCase):
    def test_reuse_workpoint_and_bad_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); projection,request,grid=fixture()
            p=root/'v.pa'; mask=root/'m.pa'; labels=root/'labels.csv'
            h=PaHeader(-2,1,200.,5,3,3,1<<28,1.,1.,1.)
            hm=PaHeader(-2,1,1.,5,3,3,1<<28,1.,1.,1.)
            p.write_bytes(h.pack()+struct.pack('<45d',-0.,*([0.]*44)))
            mask.write_bytes(hm.pack()+struct.pack('<45d',1.,1.,*([0.]*43)))
            a=fill_invalid_scalar_pa(p,mask,root/'a.pa',root/'am.pa',projection=projection,request=request,grid=grid,chunk_nodes=7,write_labels_path=labels)
            changed=copy.deepcopy(request);changed['group_voltages'][1]['voltage_v']=-77
            b=fill_invalid_scalar_pa(p,mask,root/'b.pa',root/'bm.pa',projection=projection,request=changed,grid=grid,chunk_nodes=7,read_labels_path=labels)
            self.assertEqual(a['filled_conductor_count'],b['filled_conductor_count'])
            self.assertEqual((root/'b.pa').read_bytes()[56:72],p.read_bytes()[56:72])
            self.assertEqual(struct.unpack_from('<d',(root/'b.pa').read_bytes(),56+8*21)[0],-77)
            for number,text in enumerate(('index,group_ordinal\n22,0\n21,0\n','index,group_ordinal\n1,0\n','index,group_ordinal\n22,999\n')):
                bad=root/f'bad{number}.csv';bad.write_text(text,encoding='utf-8')
                with self.assertRaises(ValueError):
                    fill_invalid_scalar_pa(p,mask,root/f'bad{number}.pa',root/f'badmask{number}.pa',projection=projection,request=request,grid=grid,chunk_nodes=7,read_labels_path=bad)

class PreparedSupportOwnerTests(unittest.TestCase):
    def test_owner_reuses_bound_support_and_refuses_changed_mask(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from tests.contracts import test_assembly_scalar_owner_fill as fixtures
        from msplatform.backends.comsol import assembly_field_export as owner
        from msplatform.io.manifest_records import file_record
        a=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export'); a.setUp(); self.addCleanup(a.doCleanups)
        def call(f, **kwargs):
            with patch.object(owner,'freeze_native_sources',return_value=(f.root/'native/launcher.ps1',[])),patch.object(owner,'declare_runtime_files'),patch.object(owner,'require_launcher_completion'):
                return owner.execute_export(f.session,source=f.source,manifest_record={'path':'synthetic'},grid=f.grid,baseline={'vacuum_domains':[1]},solution_identity=f.solution,limits={},fill_conductor_interiors=True,**kwargs)
        first=call(a,publish_prepared_support=True)['manifest_extra_fields']['products']['samples']['data']
        manifest=a.root/'producer.json';manifest.write_text('{}',encoding='utf-8')
        source=SimpleNamespace(reference={'manifest':file_record(manifest,'required_evidence')},data_records=first,data_locations={k:Path(v['path']) for k,v in first.items()},data_path=lambda key:Path(first[key]['path']))
        b=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');b.setUp();self.addCleanup(b.doCleanups)
        b.request['group_voltages'][1]['voltage_v']=-77
        b.grid.update(block_points=7, study_tag='study2', solution_tag='solution2',
                      dataset_tag='dataset2', coordinate_sanity_mm=2e-6)
        b.solution.update(study_tag='study2', solution_tag='solution2',
                          dataset_tag='dataset2', dataset_solution='solution2')
        b.source.data_locations['reopen_solution'].write_text(json.dumps(b.solution),encoding='utf-8')
        b.source.data_records['reopen_solution']=file_record(b.source.data_locations['reopen_solution'],'required_evidence')
        public_grid={key:value for key,value in b.grid.items() if key not in ('point_count','coordinate_sanity_mm')}
        projection_with_box=dict(b.projection,outer_box_mm={'min':[-2,-1,-1],'max':[2,1,1]})
        owner.validate_grid(public_grid,projection_with_box,b.solution)
        b.source.data_locations['request'].write_text(json.dumps(b.request),encoding='utf-8')
        b.source.data_records['request']=file_record(b.source.data_locations['request'],'required_evidence')
        result=call(b,support_source=source)['manifest_extra_fields']['products']['samples']['data']
        self.assertEqual(struct.unpack_from('<d',Path(result['field_v']['path']).read_bytes(),56+8*21)[0],-77)
        reused=json.loads(Path(result['conductor_support']['path']).read_text(encoding='utf-8'))['result']
        original=json.loads(Path(first['conductor_support']['path']).read_text(encoding='utf-8'))['result']
        self.assertEqual(reused['classifications'],original['classifications'])
        self.assertEqual(reused['prepared_support_manifest'],source.reference['manifest'])
        c=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');c.setUp();self.addCleanup(c.doCleanups);c.mode='vacuum'
        with self.assertRaisesRegex(ValueError,'identity differs') as caught: call(c,support_source=source)
        self.assertTrue(any(str(p).endswith('field_valid.pa') for p in caught.exception.failure_output_paths))
        descriptor=json.loads(Path(first['conductor_support']['path']).read_text(encoding='utf-8'))
        for number,key in enumerate(('projection_sha256','raw_mask_sha256','grid','support_code_sha256','groups')):
            with self.subTest(key=key):
                d=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');d.setUp();self.addCleanup(d.doCleanups)
                altered=copy.deepcopy(descriptor);altered['prepared_identity'][key]='mismatch'
                bad=d.root/'altered.json';bad.write_text(json.dumps(altered),encoding='utf-8')
                records=dict(first);records['conductor_support']=file_record(bad,'required_evidence')
                other=SimpleNamespace(reference=source.reference,data_records=records,data_locations={k:Path(v['path']) for k,v in records.items()},data_path=lambda name, data=records:Path(data[name]['path']))
                with self.assertRaisesRegex(ValueError,'identity differs'):call(d,support_source=other)
        d=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');d.setUp();self.addCleanup(d.doCleanups)
        tampered=d.root/'labels.csv';tampered.write_bytes(Path(first['prepared_support_labels']['path']).read_bytes())
        records=dict(first);records['prepared_support_labels']=file_record(tampered,'required_evidence')
        tampered.write_text('index,group_ordinal\n',encoding='utf-8')
        badsource=SimpleNamespace(reference=source.reference,data_records=records,data_locations={k:Path(v['path']) for k,v in records.items()},data_path=lambda name:Path(records[name]['path']))
        with self.assertRaisesRegex(AssertionError, "changed"):call(d,support_source=badsource)
        d=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');d.setUp();self.addCleanup(d.doCleanups)
        corrupt=copy.deepcopy(descriptor);corrupt['result']['classifications']['interior']+=1
        altered=d.root/'bad-counts.json';altered.write_text(json.dumps(corrupt),encoding='utf-8')
        records=dict(first);records['conductor_support']=file_record(altered,'required_evidence')
        badcounts=SimpleNamespace(reference=source.reference,data_records=records,data_locations={k:Path(v['path']) for k,v in records.items()},data_path=lambda name:Path(records[name]['path']))
        with self.assertRaisesRegex(ValueError,'classification accounting differs'):call(d,support_source=badcounts)

    def test_physical_grid_identity_components(self):
        from msplatform.backends.comsol.assembly_field_export import _classification_grid_identity
        _,_,grid=fixture()
        grid.update(block_points=10,study_tag='s',solution_tag='v',dataset_tag='d',coordinate_sanity_mm=1e-6)
        identity=_classification_grid_identity(grid)
        other=copy.deepcopy(grid);other.update(block_points=1,study_tag='other',solution_tag='other',dataset_tag='other',coordinate_sanity_mm=2e-6)
        self.assertEqual(identity,_classification_grid_identity(other))
        for key,value in (('frame_id','other'),('origin_mm',[1,0,0]),('pitch_mm',[2,1,1]),('dimensions',[4,3,3]),('point_count',44)):
            with self.subTest(key=key):
                other=copy.deepcopy(grid);other[key]=value
                self.assertNotEqual(identity,_classification_grid_identity(other))

class OfflineScalarDerivationTests(unittest.TestCase):
    def test_direct_action_no_native_and_borrowed_guard(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from tests.contracts import test_assembly_scalar_owner_fill as fixtures
        from msplatform.backends.comsol import assembly_field_export as owner
        from msplatform.io.manifest_records import file_record
        producer=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');producer.setUp();self.addCleanup(producer.doCleanups)
        input_manifest=producer.root/'input-manifest.json';input_manifest.write_text('{}',encoding='utf-8')
        with patch.object(owner,'freeze_native_sources',return_value=(producer.root/'native/launcher.ps1',[])),patch.object(owner,'declare_runtime_files'),patch.object(owner,'require_launcher_completion'):
            result=owner.execute_export(producer.session,source=producer.source,manifest_record=file_record(input_manifest,'required_evidence'),grid=producer.grid,baseline={'vacuum_domains':[1]},solution_identity=producer.solution,limits={},fill_conductor_interiors=False)['manifest_extra_fields']['products']['samples']
        data=result['data'];manifest=producer.root/'sample-manifest.json';manifest.write_text('{}',encoding='utf-8')
        source=SimpleNamespace(reference={'manifest':file_record(manifest,'required_evidence')},metadata=result['metadata'],data_records=data,data_locations={k:Path(v['path']) for k,v in data.items()},data_path=lambda key:Path(data[key]['path']))
        consumer=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');consumer.setUp();self.addCleanup(consumer.doCleanups)
        consumer.session.expected_operation_ids=()
        before={k:source.data_path(k).read_bytes() for k in ('field_v','field_valid','report')}
        required=('grid','projection','request','geometry_validation','reopen_geometry','reopen_solution','report','field_solution_manifest')
        grid=json.loads(source.data_path('grid').read_text(encoding='utf-8'));projection=json.loads(source.data_path('projection').read_text(encoding='utf-8'));request=json.loads(source.data_path('request').read_text(encoding='utf-8'));report=json.loads(source.data_path('report').read_text(encoding='utf-8'))
        with patch.object(consumer.session,'run_process',side_effect=AssertionError('native forbidden')):
            derived=owner._execute_scalar_derivation(consumer.session,source=source,raw_names=('field_v','field_valid'),required=required,grid=grid,projection=projection,request=request,report=report,support_source=None,publish_prepared_support=True)
        product=derived['manifest_extra_fields']['products']['samples'];self.assertEqual(product['metadata']['native_operations_requested'],0)
        self.assertEqual(before,{k:source.data_path(k).read_bytes() for k in before})
        self.assertNotIn(str(source.data_path('field_v')),derived['output_paths'])
        self.assertEqual(product['data']['report']['sha256'],data['report']['sha256'])
        third=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');third.setUp();self.addCleanup(third.doCleanups);third.session.expected_operation_ids=()
        bad=third.root/'borrowed.pa';bad.write_bytes(source.data_path('field_v').read_bytes())
        replacement=file_record(bad,'solver_native_binary');bad.write_bytes(b'altered')
        records=dict(data);records['field_v']=replacement
        broken=SimpleNamespace(reference=source.reference,metadata=source.metadata,data_records=records,data_locations={k:Path(v['path']) for k,v in records.items()},data_path=lambda key:Path(records[key]['path']))
        with self.assertRaisesRegex(AssertionError,'changed'):
            owner._execute_scalar_derivation(third.session,source=broken,raw_names=('field_v','field_valid'),required=required,grid=grid,projection=projection,request=request,report=report,support_source=None,publish_prepared_support=True)
        self.assertEqual(before,{k:source.data_path(k).read_bytes() for k in before})

    def test_historical_writer_pair_missing_and_tamper_refuse(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.comsol import assembly_field_export as owner
        from msplatform.io.manifest_records import file_record, verify_record
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);names=('field_v','field_valid','grid','projection','request',
                'geometry_validation','reopen_geometry','reopen_solution','report','field_solution_manifest',
                'writer','writer_manifest')
            records={}
            for name in names:
                path=root/(name+'.dat');path.write_bytes(name.encode());records[name]=file_record(path,'required_evidence')
            source=SimpleNamespace(producer={'status':'success'},metadata={'backend':'comsol',
                'scope':'assembly_world_scalar_samples','field_status':'sampled'},data_records=records)
            def data_path(name):
                verify_record(name,source.data_records[name]);return Path(source.data_records[name]['path'])
            source.data_path=data_path
            with patch.object(owner,'open_artifact',return_value=source):
                for missing in ('writer','writer_manifest'):
                    saved=source.data_records.pop(missing)
                    with self.subTest(missing=missing),self.assertRaisesRegex(ValueError,'incomplete published writer provenance'):
                        owner.derive_world_scalar_support({},context=None)
                    source.data_records[missing]=saved
                Path(records['writer']['path']).write_bytes(b'change')
                with self.assertRaisesRegex(AssertionError,'SHA-256 changed'):
                    owner.derive_world_scalar_support({},context=None)

    def test_nested_solution_readback_required(self):
        from msplatform.backends.comsol.assembly_field_export import _published_solution_readback
        from tests.contracts.test_comsol_world_scalar_managed import SOLUTION
        grid={'study_tag':'std1','solution_tag':'sol1','dataset_tag':'dset1'}
        self.assertEqual(_published_solution_readback({'solution':SOLUTION},grid),SOLUTION)
        with self.assertRaisesRegex(ValueError,'nested'):_published_solution_readback(SOLUTION,grid)

    def test_native_fill_failure_keeps_original_report(self):
        from unittest.mock import patch
        from tests.contracts import test_assembly_scalar_owner_fill as fixtures
        f=fixtures.ScalarOwnerFillTests('test_false_keeps_raw_export');f.setUp();self.addCleanup(f.doCleanups)
        with patch('msplatform.backends.comsol.assembly_scalar_fill.fill_invalid_scalar_pa',side_effect=ValueError('late failure')):
            with self.assertRaisesRegex(ValueError,'late failure') as caught:f.action(True)
        self.assertTrue(any(str(p).endswith('export_world_scalar.json') for p in caught.exception.failure_output_paths))

class OriginalSourceStatusTests(unittest.TestCase):
    def test_failed_original_producer_refused(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.simion import scalar_sample_binding as binding
        derived=SimpleNamespace(metadata={'derivation':'offline_from_published_raw_samples','original_samples_reference':{'manifest':{},'product_id':'samples'}})
        original=SimpleNamespace(metadata={},producer={'status':'failed'})
        with patch.object(binding,'open_artifact',return_value=original):
            with self.assertRaisesRegex(ValueError,'producer must be successful'):binding.original_sample_source(derived)

    def test_failed_immediate_and_support_producers_refused(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.comsol import assembly_field_export as owner
        failed=SimpleNamespace(producer={'status':'failed'})
        with patch.object(owner,'open_artifact',return_value=failed):
            with self.assertRaisesRegex(ValueError,'source samples producer must be successful'):
                owner.derive_world_scalar_support({},context=None)
            with self.assertRaisesRegex(ValueError,'prepared support producer must be successful'):
                owner.export_world_scalar({},grid={},context=None,fill_conductor_interiors=True,prepared_support={})
