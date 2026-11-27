import os,sys,json,struct,unittest,tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from msplatform.backends.comsol import assembly_field_export as subject, native_execution
from tests.contracts import test_comsol_world_scalar_managed as base
from tests.contracts import test_execution_runtime as execution_fixture
from tests.contracts.test_assembly_scalar_fill import fixture
from msplatform.backends.simion.standalone_pa_composition import HEADER
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.run_session import RunSession
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.inputs import freeze_file
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from msplatform.storage.store import ArtifactStore
from msplatform.execution.capacity_protection import load_capacity_protection_leases, path_is_protected

class SupportOwner(unittest.TestCase):
 @patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
 def test_owner_publication_reuse_and_failure(self):
  with tempfile.TemporaryDirectory(prefix='support-owner-') as directory:
   root=Path(directory);helper=execution_fixture.NormalOwnerTests();cap=root/'capacity.json';cap.write_text(json.dumps(helper._policy()))
   context=replace(helper._context(root),capacity_policy_path=cap,host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),tools={'comsol_launcher':Path(sys.executable),'matlab_root':root});context.workspace.mkdir(parents=True)
   limits={'wall_clock_seconds':120,'transient_run_directory_bytes':64*1024**2,'process_tree_working_set_bytes':1024**3,'minimum_system_available_memory_bytes':1,'compact_final_retained_bytes':64*1024**2,'automatic_retry_count':0};retention={'policy_version':1,'class':'solver_review','reason':'inert managed support lifecycle'}
   policy=root/'stages.json';policy.write_text(json.dumps({'schema_version':1,'role':'execution_stage_policy','stages':{'export_assembly_world_scalar':{'limits':limits,'artifact_retention':retention}}}));context=replace(context,stage_policy_path=policy)
   def nested_source_action(session):
    result=base.source_action(session)
    records=result['manifest_extra_fields']['products']['solution']['data']
    path=Path(records['reopen_solution']['path'])
    path.write_text(json.dumps({'solution':base.SOLUTION}),encoding='utf-8')
    records['reopen_solution']=file_record(path,'required_evidence')
    return result
   def create_source(i):
    args=helper._arguments(root,nested_source_action);args.update(retention=retention,run_id=f'20261114_12000{i}__build__python__synthetic-field',action_record=file_record(Path(__file__),'required_evidence'),completion_api=no_particle_batch_completion_api)
    if i==2:
     def changed():
      p,r,g=fixture();r['group_voltages'][1]['voltage_v']=-77;return p,r,g
     with patch.object(base,'fixture',side_effect=changed): result=run_managed_stage(context,**args)
    else:result=run_managed_stage(context,**args)
    return open_artifact({'manifest':result['manifest'],'product_id':'solution'},expected_kind='field_solution')
   source1=create_source(1);source2=create_source(2)
   _,_,grid=fixture();grid.update(block_points=7,study_tag='std1',solution_tag='sol1',dataset_tag='dset1');grid.pop('point_count')
   sample=root/'potential.pa';valid=root/'valid.pa';sample.write_bytes(bytes(HEADER.size)+struct.pack('<45d',-0.,*([0.]*44)));valid.write_bytes(bytes(HEADER.size)+struct.pack('<45d',1.,*([0.]*44)))
   def control(source,changed=False):
    if changed:valid.write_bytes(bytes(HEADER.size)+struct.pack('<45d',*([1.]*44),0.))
    resolved=subject.validate_grid(grid,json.loads(source.data_path('projection').read_text()),base.SOLUTION);resolved['coordinate_sanity_mm']=1e-6
    n=44 if not changed else 1
    row=dict(resolved,status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(source.data_path('model')),vacuum_domains=[1],fem_valid=45-n,invalid_count=n,solution_readback=base.SOLUTION,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'})
    rp=root/'report.json';rp.write_text(json.dumps(row));(context.workspace/'scalar-inert-control.json').write_text(json.dumps({'case':'normal','potential':str(sample),'mask':str(valid),'report':str(rp)}))
   def sources(session,names):
    _,records=native_execution.freeze_native_sources(session,names);target=session.declare_file(session.input_dir/'native_sources/inert_scalar_launcher.ps1','required_evidence');freeze_file(Path(base.__file__).parent/'test_support/assembly_scalar_export_launcher.ps1',target);record=file_record(target,'required_evidence');session.add_input('inert_launcher',record);return target,[*records,record]
   real=RunSession.run_process; observations=[]; live_leases=[]; first=None
   def transport(session,operation_id,**kwargs):
    self.assertEqual((operation_id,kwargs['role'],kwargs['stage']),('export_world_scalar','COMSOL','solver'));self.assertEqual(Path(kwargs['arguments'][2]).resolve(),(session.input_dir/'native_sources/inert_scalar_launcher.ps1').resolve());observations.append([x['path'] for x in kwargs['immutable_input_records']]);
    if first is not None:
     view=load_capacity_protection_leases(context.workspace/'artifacts');self.assertTrue(path_is_protected(first.manifest_location,view['protected_paths']));live_leases.append(view['audit'])
    kwargs.update(role='GATE',stage='assembly_scalar_inert_transport');return real(session,operation_id,**kwargs)
   with patch.object(subject,'freeze_native_sources',side_effect=sources),patch.object(RunSession,'run_process',new=transport):
    control(source1);raw1=subject.export_world_scalar(source1,grid=grid,context=context,fill_conductor_interiors=False)
    control(source2);raw2=subject.export_world_scalar(source2,grid=grid,context=context,fill_conductor_interiors=False)
    control(source2,True);raw3=subject.export_world_scalar(source2,grid=grid,context=context,fill_conductor_interiors=False)
   offline=replace(context,tools={})
   store=ArtifactStore(root/'offline-store')
   original={k:raw1.data_path(k).read_bytes() for k in ('field_v','field_valid','report')}
   actual_postprocess=subject._postprocess_scalar
   def traced_postprocess(session,**kwargs):
    for path in kwargs['outputs']:
     with self.assertRaises(PermissionError):Path(path).unlink()
    if kwargs['support_source'] is not None:
     with self.assertRaises(PermissionError):first.manifest_location.unlink()
    live_leases.append(True)
    return actual_postprocess(session,**kwargs)
   with patch.object(RunSession,'run_process',side_effect=AssertionError('native forbidden')),patch.object(subject,'_postprocess_scalar',side_effect=traced_postprocess):
    first=subject.derive_world_scalar_support(raw1,context=offline,publish_prepared_support=True,artifact_store=store)
    chain=subject.derive_world_scalar_support(first,context=offline,artifact_store=store)
    self.assertEqual(chain.metadata['original_samples_reference'],raw1.reference)
    second=subject.derive_world_scalar_support(raw2,context=offline,prepared_support=first.reference,artifact_store=store)
    self.assertEqual(struct.unpack_from('<d',second.data_path('field_v').read_bytes(),56+8*21)[0],-77)
    with self.assertRaisesRegex(ValueError,'identity differs'):
     subject.derive_world_scalar_support(raw3,context=offline,prepared_support=first.reference,artifact_store=store)
   for k,v in original.items():self.assertEqual(raw1.data_path(k).read_bytes(),v)
   manifests=list((context.workspace/'artifacts/assemblies/instrument_assembly/runs').glob('*assembly-scalar*/run_manifest.json'))+list(store.root.glob('assets/native_stage/*/*/runs/*assembly-scalar*/run_manifest.json'));statuses=[json.loads(x.read_text(encoding='utf-8-sig'))['status'] for x in manifests];self.assertCountEqual(statuses,['success','success','success','success','success','success','failed'])
   for m in manifests:
    d=json.loads(m.read_text(encoding='utf-8-sig'))
    if d['status']=='failed':self.assertNotIn('samples',d.get('products',{}))
    completion=json.loads((m.parent/'results/execution_completion.json').read_text(encoding='utf-8-sig'))['writer_completion']
    if 'assembly-scalar-derive-' in m.parent.name:
     self.assertEqual(completion['operations'],[]);self.assertEqual(completion['resource_releases'],[])
    else:
     self.assertEqual(len(completion['operations']),1);self.assertTrue(completion['operations'][0]['observation']['exit_confirmed'])
     self.assertEqual(completion['resource_releases'][0]['completion_receipt']['host_release']['result']['status'],'released')
   self.assertEqual(load_capacity_protection_leases(context.workspace/'artifacts')['audit'],[])
   self.assertEqual(len(live_leases),4)
   print('MANAGED_SUPPORT_RECEIPTS='+json.dumps({'statuses':statuses,'producer_guarded':True,'source_unchanged':True,'live_source_protection_checks':len(live_leases),'lease_audit':[]}),flush=True)
