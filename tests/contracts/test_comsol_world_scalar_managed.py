"""Actual managed owner with inert GATE child and synthetic writer validation boundary."""
import json
import os
from dataclasses import replace
from functools import partial
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from tests.contracts import test_execution_runtime as execution_fixture
from tests.contracts.test_assembly_scalar_fill import fixture
from msplatform.backends.comsol import assembly_field_export as subject, native_execution
from msplatform.backends.simion.standalone_pa_composition import HEADER
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from msplatform.storage.store import ArtifactStore

SOLUTION={'study_tag':'std1','solution_tag':'sol1','dataset_tag':'dset1','dataset_solution':'sol1','solution_empty':False,'solution_count':1,'stored_main_solutions':1,'solution_dofs':7}

def prepared_action(session):
    path=session.declare_file(session.result_dir/'prepared.mph','solver_native_binary')
    path.write_text('synthetic prepared model',encoding='utf-8')
    return dict(status='success',summary={'synthetic':True},output_paths=[str(path)],required_output_paths=[str(path)],retention_preserve_paths=[],manifest_extra_fields={'products':{'prepared':{'schema_version':1,'kind':'prepared_model','status':'complete','metadata':{},'data':{'model':file_record(path,'solver_native_binary')}}}})

def source_action(session, *, prepared):
    projection,request,_=fixture();projection['outer_box_mm']={'min':[-2,-2,-2],'max':[3,3,3]}
    values={'projection':projection,'request':request,'geometry_validation':{'position_mm':1e-6},'reopen_geometry':{'vacuum_domains':[1]},'reopen_solution':SOLUTION,'model':'synthetic model; no COMSOL'}
    records={};paths=[]
    for name,value in values.items():
        target=session.declare_file(session.result_dir/(name+('.mph' if name=='model' else '.json')),'solver_native_binary' if name=='model' else 'required_evidence')
        target.write_text(value if name=='model' else json.dumps(value),encoding='utf-8')
        records[name]=file_record(target,'solver_native_binary' if name=='model' else 'required_evidence');paths.append(str(target))
    frozen=session.declare_file(session.result_dir/'prepared_manifest.json','required_evidence')
    freeze_file(Path(prepared['manifest']['path']),frozen)
    records['prepared_manifest']=file_record(frozen,'required_evidence');paths.append(str(frozen))
    return dict(status='success',summary={'synthetic':True},output_paths=paths,required_output_paths=paths,retention_preserve_paths=[],manifest_extra_fields={'products':{'solution':{'schema_version':1,'kind':'field_solution','status':'complete','metadata':{'backend':'comsol','scope':'single_stationary_workpoint','field_status':'solved','native_reopen_verified':True,'solution':SOLUTION,'stationary_source':{'reference':prepared,'kind':'prepared_model'}},'data':records}}})

class ManagedScalarOwnerTests(unittest.TestCase):
    @patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
    def test_real_owner_inert_export(self):
        for case in ('true','false','late_failure','tamper'):
            with self.subTest(case=case),tempfile.TemporaryDirectory(prefix='scalar-owner-managed-') as directory:
                root=Path(directory);helper=execution_fixture.NormalOwnerTests();cap=root/'capacity.json';cap.write_text(json.dumps(helper._policy()),encoding='utf-8')
                context=replace(helper._context(root),capacity_policy_path=cap,host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),tools={'comsol_launcher':Path(sys.executable),'matlab_root':root})
                context.workspace.mkdir(parents=True)
                limits={'wall_clock_seconds':120,'transient_run_directory_bytes':64*1024**2,'process_tree_working_set_bytes':1024**3,'minimum_system_available_memory_bytes':1,'compact_final_retained_bytes':64*1024**2,'automatic_retry_count':0}
                retention={'policy_version':1,'class':'solver_review','reason':'inert scalar managed owner test'}
                policy=root/'stages.json';policy.write_text(json.dumps({'schema_version':1,'role':'execution_stage_policy','stages':{'export_assembly_world_scalar':{'limits':limits,'artifact_retention':retention}}}),encoding='utf-8');context=replace(context,stage_policy_path=policy)
                store=ArtifactStore(root/'store')
                args=helper._arguments(root,prepared_action);args.update(retention=retention,run_id='20261114_120000__build__python__synthetic-prepared',action_record=file_record(Path(__file__),'required_evidence'),completion_api=no_particle_batch_completion_api)
                prepared=run_managed_stage(context,artifact_store=store,**args)
                prepared_ref={'manifest':prepared['manifest'],'product_id':'prepared'}
                args=helper._arguments(root,partial(source_action,prepared=prepared_ref));args.update(retention=retention,run_id='20261114_120000__build__python__synthetic-field',action_record=file_record(Path(__file__),'required_evidence'),completion_api=no_particle_batch_completion_api)
                source_result=run_managed_stage(context,artifact_store=store,**args);source=open_artifact({'manifest':source_result['manifest'],'product_id':'solution'},expected_kind='field_solution')
                original={n:source.data_path(n).read_bytes() for n in ('model','request','projection')}
                _,_,grid=fixture();grid.update(block_points=7,study_tag='std1',solution_tag='sol1',dataset_tag='dset1');grid.pop('point_count')
                if case=='true':
                    with self.assertRaisesRegex(Exception,'explicit ArtifactStore'):
                        subject.export_world_scalar(source,grid=grid,context=context)
                    sentinel=object()
                    def grid_probe(*args,**kwargs):
                        from msplatform.execution.native_artifact_controls import current_native_artifact_scope
                        (current_native_artifact_scope()['work_directory']/'probe.txt').write_text('grid probe',encoding='utf-8')
                        return sentinel
                    with patch.object(subject,'_export_world_scalar_guarded',side_effect=grid_probe) as invoke:
                        self.assertIs(subject.export_world_scalar_grids(source,grids={'one':grid,'two':grid},context=context,artifact_store=store),sentinel)
                        self.assertEqual(set(invoke.call_args.kwargs['grids']),{'one','two'})
                values=[0.]*45;values[0]=-0.;mask=[0.]*45;mask[0]=1.
                if case=='late_failure':mask[-1]=.5
                sample=root/'potential.pa';valid=root/'valid.pa';sample.write_bytes(bytes(HEADER.size)+b''.join(struct.pack('<d',x) for x in values));valid.write_bytes(bytes(HEADER.size)+b''.join(struct.pack('<d',x) for x in mask))
                resolved=subject.validate_grid(grid,json.loads(source.data_path('projection').read_text()),SOLUTION);resolved['coordinate_sanity_mm']=1e-6
                report=dict(resolved,status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(source.data_path('model')),vacuum_domains=[1],fem_valid=1,invalid_count=44,solution_readback=SOLUTION,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'})
                report_path=root/'report.json';report_path.write_text(json.dumps(report),encoding='utf-8')
                (context.workspace/'scalar-inert-control.json').write_text(json.dumps({'case':case,'potential':str(sample),'mask':str(valid),'report':str(report_path)}),encoding='utf-8')
                def sources(session,names):
                    launcher,records=native_execution.freeze_native_sources(session,names)
                    target=session.declare_file(session.input_dir/'native_sources/inert_scalar_launcher.ps1','required_evidence')
                    freeze_file(Path(__file__).parent/'test_support/assembly_scalar_export_launcher.ps1',target)
                    record=file_record(target,'required_evidence');session.add_input('inert_launcher',record)
                    return target,[*records,record]
                original_run=RunSession.run_process
                def transport(session,operation_id,**kwargs):
                    self.assertEqual((operation_id,kwargs['role'],kwargs['stage']),('export_world_scalar','COMSOL','solver'))
                    self.assertEqual(Path(kwargs['arguments'][2]).resolve(),(session.input_dir/'native_sources/inert_scalar_launcher.ps1').resolve())
                    records=kwargs['immutable_input_records']
                    keys=[str(Path(record['path']).resolve()).casefold() for record in records]
                    self.assertEqual(len(keys),len(set(keys)))
                    if case=='true':
                        with self.assertRaises(PermissionError): source.data_path('model').unlink()
                        self.assertTrue(any('scalar_pa_encoder' in path for path in keys))
                        self.assertTrue(any('scalar_support' in path for path in keys))
                    kwargs.update(role='GATE',stage='assembly_scalar_inert_transport')
                    return original_run(session,operation_id,**kwargs)
                with patch.object(subject,'freeze_native_sources',side_effect=sources),patch.object(RunSession,'run_process',new=transport):
                    if case in ('true','false'):
                        product=subject.export_world_scalar(source,grid=grid,context=context,fill_conductor_interiors=case=='true',artifact_store=store)
                        run_dir=product.manifest_location.parent;manifest=json.loads(product.manifest_location.read_text(encoding='utf-8-sig'));self.assertEqual(manifest['status'],'success')
                        self.assertEqual('conductor_support' in product.data_records,case=='true')
                        if case=='true':
                            self.assertEqual(struct.unpack_from('<d',product.data_path('field_v').read_bytes(),56+8*21)[0],-100.)
                            self.assertEqual(product.data_path('sampled_field_v').read_bytes()[HEADER.size:],sample.read_bytes()[HEADER.size:])
                    else:
                        with self.assertRaises(Exception) as caught:subject.export_world_scalar(source,grid=grid,context=context,fill_conductor_interiors=True,artifact_store=store)
                        self.assertRegex(str(caught.exception),'(?i)(binary|immutable|denied|access|exit|changed|zero or one)')
                        manifests=list(store.root.glob('assets/native_stage/*/*/runs/*assembly-scalar*/run_manifest.json'));self.assertEqual(len(manifests),1)
                        run_dir=manifests[0].parent;manifest=json.loads(manifests[0].read_text(encoding='utf-8-sig'));self.assertEqual(manifest['status'],'failed');self.assertNotIn('samples',manifest.get('products',{}))
                        if case=='late_failure':
                            partial_output=run_dir/'scalar/field_v_filled.pa'
                            self.assertFalse(partial_output.exists())
                            self.assertEqual((run_dir/'scalar/field_v.pa').read_bytes(),sample.read_bytes())
                            self.assertEqual((run_dir/'scalar/field_valid.pa').read_bytes(),valid.read_bytes())
                            self.assertTrue((run_dir/'results/export_world_scalar.json').is_file())
                            result_paths=list(store.root.glob('work/*/native-result-'+run_dir.name+'.json'))
                            self.assertEqual(len(result_paths),1)
                            result_path=result_paths[0]
                            owner_result=json.loads(result_path.read_text(encoding='utf-8-sig'))
                            self.assertEqual(owner_result['status'],'failed')
                            self.assertIn('scalar validity payload must contain only zero or one',owner_result['exception']['message'])
                            self.assertIn('scalar validity payload must contain only zero or one',str(caught.exception))
                completion=json.loads((run_dir/'results/execution_completion.json').read_text(encoding='utf-8-sig'))
                self.assertEqual([x['operation_id'] for x in completion['writer_completion']['operations']],['export_world_scalar'])
                release=completion['writer_completion']['resource_releases'][0]['completion_receipt']['host_release']
                self.assertEqual(release['result'],{'status':'released','token':release['token']})
                self.assertTrue(completion['writer_completion']['operations'][0]['observation']['exit_confirmed'])
                for n,data in original.items():self.assertEqual(source.data_path(n).read_bytes(),data)

if __name__=='__main__':unittest.main()
