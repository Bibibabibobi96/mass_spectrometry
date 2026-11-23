"""Managed multi-product publication through a real inert GATE Python child."""
import json,os,struct,sys,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from tests.contracts import test_comsol_world_scalar_managed as base
from tests.contracts import test_execution_runtime as runtime_fixture
from tests.contracts.test_assembly_scalar_fill import fixture
from msplatform.backends.comsol import assembly_field_export as subject
from msplatform.backends.simion.standalone_pa_composition import HEADER, PaHeader
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.run_session import RunSession
from msplatform.execution.inputs import freeze_file
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.processes import ProcessExecutionError
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from msplatform.execution.capacity_protection import load_capacity_protection_leases

class ScalarMultiGridManagedTests(unittest.TestCase):
 @patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
 def test_public_products_real_child_and_second_grid_failure(self):
  with tempfile.TemporaryDirectory(prefix='scalar-multi-managed-') as directory:
   root=Path(directory);helper=runtime_fixture.NormalOwnerTests();cap=root/'capacity.json';cap.write_text(json.dumps(helper._policy()),encoding='utf8')
   context=replace(helper._context(root),capacity_policy_path=cap,host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),tools={'comsol_launcher':Path(sys.executable),'matlab_root':root});context.workspace.mkdir(parents=True)
   limits={'wall_clock_seconds':120,'transient_run_directory_bytes':64*1024**2,'process_tree_working_set_bytes':1024**3,'minimum_system_available_memory_bytes':1,'compact_final_retained_bytes':64*1024**2,'automatic_retry_count':0};retention={'policy_version':1,'class':'solver_review','reason':'inert multi-grid managed test'}
   policy=root/'stage.json';policy.write_text(json.dumps({'schema_version':1,'role':'execution_stage_policy','stages':{'export_assembly_world_scalar':{'limits':limits,'artifact_retention':retention}}}),encoding='utf8');context=replace(context,stage_policy_path=policy)
   kwargs=helper._arguments(root,base.source_action);kwargs.update(retention=retention,run_id='20261115_000201__test__python__synthetic-field',action_record=file_record(Path(base.__file__),'required_evidence'),completion_api=no_particle_batch_completion_api)
   produced=run_managed_stage(context,**kwargs);source=open_artifact({'manifest':produced['manifest'],'product_id':'solution'},expected_kind='field_solution')
   before={name:source.data_path(name).read_bytes() for name in ('projection','request','model')}
   _,_,grid=fixture();grid.update(block_points=7,study_tag='std1',solution_tag='sol1',dataset_tag='dset1');grid.pop('point_count')
   grids={n:dict(grid,origin_mm=[-2+0.5*i,-1,-1]) for i,n in enumerate(('one','two','three'))}
   header=PaHeader(-2,1,1.,5,3,3,1<<28,1.,1.,1.).pack()
   potential=bytes(HEADER.size)+struct.pack('<45d',-0.,*([0.]*44));mask=bytes(HEADER.size)+struct.pack('<45d',1.,*([0.]*44))
   actual=RunSession.run_process;mode={'fail':False};observed=[]
   def transport(session,operation_id,**kw):
    self.assertEqual((operation_id,kw['role'],kw['stage']),('export_world_scalar','COMSOL','solver'))
    original=Path(__file__).parent/'test_support/inert_multigrid_leaf.py';leaf=session.declare_file(session.input_dir/'test_support/inert_multigrid_leaf.py','required_evidence');leaf.parent.mkdir(parents=True,exist_ok=True);freeze_file(original,leaf);leaf_record=file_record(leaf,'required_evidence');session.add_input('inert_leaf',leaf_record)
    control=session.declare_file(session.input_dir/'test_control.json','required_evidence');control.write_text(json.dumps({'batch_spec':str(session.input_dir/'world-grid-batch.json'),'potential_hex':potential.hex(),'mask_hex':mask.hex(),'model':str(source.data_locations['model']),'solution':base.SOLUTION,'batch_report':str(session.result_dir/'export_world_scalar_batch.json'),'bootstrap':str(session.log_dir/'export_world_scalar.bootstrap.log'),'completion':str(session.log_dir/'export_world_scalar.launcher.json'),'run_id':session.run_id,'fail_second':mode['fail']}),encoding='utf8');control_record=file_record(control,'required_evidence');session.add_input('inert_control',control_record)
    observed.append(operation_id)
    return actual(session,operation_id,executable=Path(sys.executable),arguments=['-I','-B',str(leaf),str(control)],role='GATE',stage='inert_multigrid',limits=kw['limits'],immutable_input_records=[*kw['immutable_input_records'],leaf_record,control_record])
   with patch.object(RunSession,'run_process',new=transport):
    products=subject.export_world_scalar_grids(source.reference,grids=grids,context=context)
    self.assertEqual(set(products),set(grids));self.assertEqual(observed,['export_world_scalar'])
    for name,item in products.items():
     reopened=open_artifact(item.reference,expected_kind='scalar_field_samples');self.assertEqual(reopened.metadata['compute_calls_requested'],0)
     self.assertEqual(reopened.data_path('field_v').read_bytes(),header+potential[HEADER.size:]);self.assertEqual(reopened.data_path('field_valid').read_bytes(),header+mask[HEADER.size:])
     row=json.loads(reopened.data_path('report').read_text(encoding='utf8'));self.assertEqual(row['origin_mm'],grids[name]['origin_mm']);self.assertEqual(row['compute_calls'],0)
    mode['fail']=True
    with self.assertRaises(ProcessExecutionError):subject.export_world_scalar_grids(source.reference,grids=grids,context=context)
    mode['fail']=False
    with patch.object(subject,'declare_runtime_files',side_effect=ValueError('injected diagnostic cleanup failure')):
     with self.assertRaisesRegex(ValueError,'injected diagnostic cleanup failure'):
      subject.export_world_scalar_grids(source.reference,grids=grids,context=context)
    calls=[];actual_finalize=subject.finalize_scalar_pair
    def fail_second(*args,**kwargs):
     calls.append(True)
     if len(calls)==2:raise OSError('injected second header finalization failure')
     return actual_finalize(*args,**kwargs)
    with patch.object(subject,'finalize_scalar_pair',side_effect=fail_second):
     with self.assertRaisesRegex(OSError,'injected second header finalization failure'):
      subject.export_world_scalar_grids(source.reference,grids=grids,context=context)
    self.assertEqual(len(calls),2)
   runs=list((context.workspace/'artifacts/projects/instrument_assembly/runs').glob('*assembly-scalar-*/run_manifest.json'));self.assertEqual(len(runs),4)
   docs=[json.loads(p.read_text(encoding='utf-8-sig')) for p in runs];self.assertCountEqual([x['status'] for x in docs],['success','failed','failed','failed'])
   for path,doc in zip(runs,docs,strict=True):
    completion=json.loads((path.parent/'results/execution_completion.json').read_text(encoding='utf-8-sig'))['writer_completion'];self.assertEqual(len(completion['operations']),1);self.assertTrue(completion['operations'][0]['observation']['exit_confirmed']);self.assertEqual(completion['resource_releases'][0]['completion_receipt']['host_release']['result']['status'],'released')
    if doc['status']=='failed':
     self.assertFalse(doc.get('products'));self.assertTrue((path.parent/'results/export_world_scalar_one.json').is_file());self.assertTrue((path.parent/'scalar/one/field_v.pa').is_file())
     second=(path.parent/'results/export_world_scalar_two.json').exists()
     if second:
      for name in ('one','two','three'):
       self.assertTrue((path.parent/'results'/('export_world_scalar_'+name+'.json')).is_file())
       for leaf in ('field_v.pa','field_valid.pa'):self.assertTrue((path.parent/'scalar'/name/leaf).is_file())
      output_paths={str(Path(r['path']).resolve()) for r in doc['outputs']}
      for name in ('one','two','three'):
       self.assertIn(str((path.parent/'results'/('export_world_scalar_'+name+'.json')).resolve()),output_paths)
       for leaf in ('field_v.pa','field_valid.pa'):self.assertIn(str((path.parent/'scalar'/name/leaf).resolve()),output_paths)
     else:self.assertFalse((path.parent/'results/export_world_scalar_three.json').exists())
   self.assertEqual(before,{name:source.data_path(name).read_bytes() for name in before});self.assertEqual(load_capacity_protection_leases(context.workspace/'artifacts')['audit'],[])
   print('MULTIGRID_MANAGED_RECEIPT='+json.dumps({'products':len(products),'real_child_operations':len(observed),'statuses':['success','failed','failed','failed'],'source_unchanged':True,'lease_audit':[],'native_solver':False}),flush=True)
