"""Saved-world scalar contract checks without native solver execution."""
import struct
import sys
import unittest
from pathlib import Path

from msplatform.backends.comsol import assembly_field_export as subject

HERE = Path(__file__).resolve().parent

class WorldScalarTests(unittest.TestCase):
    def setUp(self):
        self.projection={'assembly_frame_id':'world','outer_box_mm':{'min':[-2,-2,-2],'max':[2,2,2]}}
        self.solution={'study_tag':'std1','solution_tag':'sol1','dataset_tag':'dset1','dataset_solution':'sol1','solution_empty':False,'solution_count':1,'stored_main_solutions':1,'solution_dofs':5830174.0}
        self.grid={'frame_id':'world','origin_mm':[-1,-1,-1],'pitch_mm':[1,1,1],'dimensions':[3,3,3],'block_points':5,'study_tag':'std1','solution_tag':'sol1','dataset_tag':'dset1'}
    def test_explicit_world_grid_and_rejections(self):
        value=subject.validate_grid(self.grid,self.projection,self.solution)
        self.assertEqual(value['point_count'],27);self.assertEqual(value['maximum_mm'],[1,1,1])
        for key,replacement in [('frame_id','other'),('dataset_tag','wrong'),('pitch_mm',[1,0,1]),('dimensions',[2,3,3]),('origin_mm',[-3,-1,-1]),('block_points',0)]:
            bad=dict(self.grid);bad[key]=replacement
            with self.subTest(key=key),self.assertRaises(ValueError):subject.validate_grid(bad,self.projection,self.solution)
    def test_actual_report_refuses_compute_and_invalid_identity(self):
        grid=subject.validate_grid(self.grid,self.projection,self.solution);grid['coordinate_sanity_mm']=1e-6;model=HERE/'source.mph'
        row=dict(grid,status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',coordinate_witness={'status':'verified','index':1,'requested_mm':[-1,-1,-1],'actual_mm':[-1,-1,-1],'geometry_length_unit':'mm'},model_path=str(model),vacuum_domains=1,fem_valid=20,invalid_count=7,solution_readback=self.solution)
        subject._check_report(row,grid=grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,model=model)
        for key,value in [('compute_calls',1),('coordinate_mapping','mirror'),('invalid_count',6),('filled_conductor_count',1)]:
            with self.subTest(key=key),self.assertRaises(ValueError):subject._check_report(dict(row,**{key:value}),grid=grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,model=model)
        witness=row['coordinate_witness']
        for changed in (dict(witness,index=0),dict(witness,actual_mm=[0,-1,-1]),dict(witness,geometry_length_unit=''),dict(witness,status='unexpected')):
            with self.assertRaisesRegex(ValueError,'coordinate'):
                subject._check_report(dict(row,coordinate_witness=changed),grid=grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,model=model)
        zero_grid=dict(grid,coordinate_sanity_mm=0)
        subject._check_report(row,grid=zero_grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,model=model)
        mismatch=dict(witness,actual_mm=[-1+1e-12,-1,-1])
        with self.assertRaisesRegex(ValueError,'coordinate'):
            subject._check_report(dict(row,coordinate_witness=mismatch),grid=zero_grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,model=model)
        insufficient={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'}
        subject._check_report(dict(row,coordinate_witness=insufficient),grid=grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,model=model)
        wrong=dict(self.solution,solution_dofs=5830175.0)
        with self.assertRaisesRegex(ValueError,'solution readback'):subject._check_report(dict(row,solution_readback=wrong),grid=grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,model=model)

    def test_inert_action_borrows_model_and_rejects_compute_report(self):
        import json
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.io.manifest_records import file_record
        grid=subject.validate_grid(self.grid,self.projection,self.solution);grid['coordinate_sanity_mm']=1e-6
        for unexpected_compute in (False,True):
            with self.subTest(unexpected_compute=unexpected_compute), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                for name in ('inputs','results','logs','original'):(root/name).mkdir()
                original={}
                for name in ('projection','request','geometry_validation','reopen_geometry','reopen_solution','model'):
                    path=root/'original'/(name+('.mph' if name=='model' else '.json'))
                    path.write_text('fixture',encoding='utf8');original[name]=path
                source=SimpleNamespace(data_path=lambda name:original[name],data_locations=original,
                    data_records={name:file_record(path,'solver_native_binary' if name=='model' else 'required_evidence') for name,path in original.items()})
                writer=root/'simion_pa_save.m';writer.write_text('synthetic',encoding='utf8');writer_record=file_record(writer,'required_evidence')
                context=SimpleNamespace(workspace=root,python_executable=root/'python',powershell_executable=root/'pwsh',host_state_path=root/'state',policy_path=root/'policy',tools={'comsol_launcher':root/'comsol','matlab_root':root})
                historical_writer={key:value for key,value in writer_record.items() if key != 'retention_role'}
                inputs={};calls=[]
                def add_input(name, record):
                    if name in ('field_solution_manifest', 'borrowed_model_origin_manifest', 'pa_writer_source_manifest', 'pa_writer_source'):
                        self.assertEqual(record['retention_role'], 'required_evidence')
                    inputs[name]=record
                session=SimpleNamespace(expected_operation_ids=('export_world_scalar',),input_dir=root/'inputs',result_dir=root/'results',log_dir=root/'logs',run_dir=root,context=context,run_id='inert',declare_file=lambda path,role:path,add_input=add_input)
                def simulate(operation,**kwargs):
                    calls.append((operation,kwargs))
                    for name in ('field_v.pa','field_valid.pa'):
                        data = -1. if name == 'field_v.pa' else 0.
                        header = struct.pack('<iidiiiiddd', -2, 1, 1., 3, 3, 3, 1 << 28, 1., 1., 1.)
                        (root/'scalar'/name).write_bytes(header + struct.pack('<27d', *([data] * 27)))
                    (root/'logs/export_world_scalar.bootstrap.log').write_text('STATUS=PASS',encoding='utf8')
                    row=dict(grid,status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=int(unexpected_compute),filled_conductor_count=0,coordinate_mapping='world_identity',coordinate_witness={'status':'verified','index':1,'requested_mm':[-1,-1,-1],'actual_mm':[-1,-1,-1],'geometry_length_unit':'mm'},model_path=str(original['model']),vacuum_domains=[1],fem_valid=20,invalid_count=7,solution_readback=self.solution)
                    (root/'results/export_world_scalar.json').write_text(json.dumps(row),encoding='utf8')
                session.run_process=simulate
                with patch.object(subject,'freeze_native_sources',return_value=(root/'native/launcher.ps1',[])),patch.object(subject,'declare_runtime_files'),patch.object(subject,'require_launcher_completion'),patch.object(subject,'_validate_scalar_pa',wraps=subject._validate_scalar_pa) as checked:
                    if unexpected_compute:
                        with self.assertRaisesRegex(ValueError,'report differs'):
                            subject.execute_export(session,source=source,manifest_record=historical_writer,grid=grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,writer_authority=historical_writer,writer=historical_writer,limits={})
                    else:
                        result=subject.execute_export(session,source=source,manifest_record=historical_writer,grid=grid,baseline={'vacuum_domains':[1]},solution_identity=self.solution,writer_authority=historical_writer,writer=historical_writer,limits={},origin_manifest=historical_writer)
                        for name in ('field_solution_manifest', 'borrowed_model_origin_manifest', 'pa_writer_source_manifest', 'pa_writer_source'):
                            self.assertEqual(inputs[name], writer_record)
                        self.assertEqual(inputs['field_solution_model'], source.data_records['model'])
                        self.assertNotIn('retention_role', historical_writer)
                        product=result['manifest_extra_fields']['products']['samples']
                        self.assertEqual(product['kind'],'scalar_field_samples')
                        self.assertEqual([call.args[0].name for call in checked.call_args_list], ['field_v.pa', 'field_valid.pa'])
                        self.assertEqual(product['metadata']['scientific_qualification'],'not_granted')
                        self.assertIn(str(original['model']),[record['path'] for record in calls[0][1]['immutable_input_records']])
                        self.assertEqual(inputs['borrowed_model_origin_manifest'],writer_record)
                        self.assertEqual(inputs['borrowed_model_origin_frozen']['sha256'],writer_record['sha256'])
                        self.assertIn(historical_writer,calls[0][1]['immutable_input_records'])
                        self.assertFalse((root/'inputs/solution/model').exists())
                        self.assertEqual(product['data']['request'],inputs['solution_request'])

    def test_scalar_pa_structure_and_grid_refusals(self):
        import tempfile
        grid=subject.validate_grid(self.grid,self.projection,self.solution)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'field.pa'
            def pa(*, mode=-2, symmetry=1, dims=(3,3,3), flags=1 << 28, pitch=(1.,1.,1.), value=0.):
                path.write_bytes(struct.pack('<iidiiiiddd',mode,symmetry,1.,*dims,flags,*pitch)
                                 + struct.pack('<%dd' % (dims[0]*dims[1]*dims[2]), *([value]*(dims[0]*dims[1]*dims[2]))))
            for value in (0.,-1.):
                pa(value=value);subject._validate_scalar_pa(path,grid)
            for change in ({'dims':(4,3,3)},{'pitch':(0.5,1.,1.)},{'flags':0},
                           {'flags':(1 << 28) | 1},{'flags':(1 << 28) | 16},
                           {'mode':-1},{'symmetry':0}):
                with self.subTest(change=change):
                    pa(**change)
                    with self.assertRaises(ValueError):subject._validate_scalar_pa(path,grid)
            pa();path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):subject._validate_scalar_pa(path,grid)
            path.write_bytes(b'')
            with self.assertRaises(ValueError):subject._validate_scalar_pa(path,grid)

    def test_published_writer_authority_rejects_missing_tamper_and_unreviewed(self):
        import hashlib
        import json
        import tempfile
        from unittest.mock import patch
        from msplatform.io.manifest_records import file_record
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'inputs').mkdir();writer=root/'inputs/simion_pa_save.m';writer.write_bytes(b'example adapted source')
            record=file_record(writer,'required_evidence')
            manifest=root/'run_manifest.json'
            def write_manifest(inputs, **changes):
                value={'role':'simulation_run_manifest','project':'parallel_mirror_dual_stripe_mr_tof','status':'success','inputs':inputs}
                value.update(changes);manifest.write_text(json.dumps(value),encoding='utf8')
                return file_record(manifest,'required_evidence')
            authority=write_manifest({'writer':record})
            with patch.object(subject,'_REVIEWED_ADAPTED_WRITER_SHA256',hashlib.sha256(writer.read_bytes()).hexdigest().upper()):
                accepted,selected=subject.resolve_published_writer(authority)
                self.assertEqual(accepted,authority);self.assertEqual(selected['sha256'],record['sha256'])
                tampered=bytearray(writer.read_bytes());tampered[0]^=1;writer.write_bytes(tampered)
                with self.assertRaisesRegex(AssertionError,'SHA-256 changed'):subject.resolve_published_writer(authority)
                writer.write_bytes(b'example adapted source')
                writer.unlink()
                with self.assertRaisesRegex(AssertionError,'missing'):subject.resolve_published_writer(authority)
                writer.write_bytes(b'example adapted source')
                with patch.object(subject,'_REVIEWED_ADAPTED_WRITER_SHA256','0'*64),self.assertRaisesRegex(ValueError,'not the reviewed'):
                    subject.resolve_published_writer(authority)
                duplicate=write_manifest({'writer':record,'another':record})
                with self.assertRaisesRegex(ValueError,'exactly one'):subject.resolve_published_writer(duplicate)
                failed=write_manifest({'writer':record},status='failed')
                with self.assertRaisesRegex(ValueError,'successful published'):subject.resolve_published_writer(failed)
                authority=write_manifest({'writer':record})
                journal=root/'.run_terminal_publication.json';journal.write_text('{}',encoding='utf8')
                with self.assertRaisesRegex(ValueError,'terminal publication is incomplete'):subject.resolve_published_writer(authority)

class SourceProtectionTests(unittest.TestCase):
    def test_owned_and_borrowed_model_source_references_and_failures(self):
        import json
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.io.manifest_records import file_record
        class OwnerReached(Exception):
            pass
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            model=root/'model.mph';model.write_bytes(b'synthetic')
            model_record=file_record(model,'solver_native_binary')
            origin_path=root/'origin.json'
            current_path=root/'current.json'
            projection_path=root/'projection.json'
            baseline_path=root/'baseline.json'
            validation_path=root/'validation.json'
            projection={'assembly_frame_id':'world','outer_box_mm':{'min':[-2,-2,-2],'max':[2,2,2]}}
            projection_path.write_text(json.dumps(projection));baseline_path.write_text('{}');validation_path.write_text(json.dumps({'position_mm':1e-6}))
            solution={'study_tag':'std1','solution_tag':'sol1','dataset_tag':'dset1','dataset_solution':'sol1',
                      'solution_empty':False,'solution_count':1,'stored_main_solutions':1,'solution_dofs':5830174.0}
            grid={'frame_id':'world','origin_mm':[-1,-1,-1],'pitch_mm':[1,1,1],'dimensions':[3,3,3],
                  'block_points':5,'study_tag':'std1','solution_tag':'sol1','dataset_tag':'dset1'}
            def write(path,value):
                path.write_text(json.dumps(value),encoding='utf8');return file_record(path,'required_evidence')
            origin=write(origin_path,{'role':'simulation_run_manifest','status':'failed','outputs':[model_record]})
            def source_for(value):
                current=write(current_path,value)
                return SimpleNamespace(reference={'manifest':current},manifest_location=current_path,
                    data_records={'model':model_record},metadata={'backend':'comsol','scope':'single_stationary_workpoint',
                    'field_status':'solved','native_reopen_verified':True,'solution':solution},
                    data_path=lambda name: {'projection':projection_path,'reopen_geometry':baseline_path,'geometry_validation':validation_path}[name])
            context=SimpleNamespace(tools={'comsol_launcher':Path(sys.executable),'matlab_root':root})
            captured=[]
            def owner(*args,**kwargs):
                captured.append(kwargs);raise OwnerReached()
            def invoke(source):
                with patch.object(subject,'open_artifact',return_value=source),patch.object(subject,'resolve_published_writer',return_value=({},{})),patch.object(subject,'read_stage_policy',return_value=({'limits':{'transient_run_directory_bytes':1},'artifact_retention':{}},{})),patch.object(subject,'run_managed_stage',side_effect=owner):
                    with self.assertRaises(OwnerReached):
                        subject.export_world_scalar({},grid=grid,writer_manifest={},context=context)
            owned=source_for({'inputs':{},'outputs':[model_record]})
            invoke(owned)
            self.assertEqual(len(captured[-1]['source_references']),1)
            validation_path.write_text(json.dumps({'position_mm':0}))
            invoke(owned)
            self.assertEqual(captured[-1]['action'].keywords['grid']['coordinate_sanity_mm'],0)
            validation_path.write_text(json.dumps({'position_mm':1e-6}))
            borrowed_doc={'inputs':{'borrowed_solution':model_record,'failed_manifest':origin},'outputs':[]}
            borrowed=source_for(borrowed_doc)
            invoke(borrowed)
            self.assertEqual(captured[-1]['source_references'],[{'manifest_record':borrowed.reference['manifest']},{'manifest_record':origin}])
            self.assertEqual(captured[-1]['action'].keywords['origin_manifest'],origin)
            for changed in ({'inputs':{'borrowed_solution':model_record},'outputs':[]},
                            {'inputs':{'borrowed_solution':dict(model_record,sha256='0'*64),'failed_manifest':origin},'outputs':[]}):
                with self.subTest(changed=changed),self.assertRaises((ValueError,TypeError)):
                    subject.resolve_model_source_manifests(source_for(changed))
            bad_origin=write(origin_path,{'role':'simulation_run_manifest','status':'failed','outputs':[]})
            with self.assertRaisesRegex(ValueError,'exact failed producer output'):
                subject.resolve_model_source_manifests(source_for({'inputs':{'borrowed_solution':model_record,'failed_manifest':bad_origin},'outputs':[]}))
            tampered=source_for(borrowed_doc)
            origin_path.write_text('tampered')
            with self.assertRaises(AssertionError):subject.resolve_model_source_manifests(tampered)

if __name__ == '__main__': unittest.main()
