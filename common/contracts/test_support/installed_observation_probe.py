"""Run with installed Python -I; the only input is frozen test fixture JSON."""
import copy,importlib.abc,json,os,subprocess,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from importlib.resources import files
blocked=[Path(value).resolve() for value in json.loads(sys.argv[2])]
def deny_author(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  candidate=Path(os.fsdecode(args[0])).resolve()
  if any(candidate.is_relative_to(root) for root in blocked): raise AssertionError('author read: '+str(candidate))
sys.addaudithook(deny_author)
class DenyAuthor(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'common','integrations','projects'}: raise AssertionError('author import: '+fullname)
sys.meta_path.insert(0,DenyAuthor())
from msplatform.backends.simion.artifacts import CompiledPreparedModel
from msplatform.backends.simion import operations
from msplatform.backends.simion.tracking_execution import plan_tracking_execution,_render_tracking_controls
from msplatform.backends.simion.tracking_units import slice_tracking_plan,tracking_applicability
from msplatform.backends.simion.tracking_execution import _collect_unit_field_observation
from msplatform.backends.simion import tracking_field_observation as observation_parser
from msplatform.backends.simion.native_plans import plan_solve_fields
from msplatform.backends.simion.field_bank import field_bank
from msplatform.backends.simion.field_identity import working_point_member_id
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution.resources import resource_path
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import OpenedArtifact

purelib=Path(__import__('sysconfig').get_path('purelib')).resolve()
import msplatform.backends.simion.tracking_execution as te
import msplatform.backends.simion.tracking_program as tp
for module in (operations,te,tp,observation_parser): assert Path(module.__file__).resolve().is_relative_to(purelib)
f=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); model=CompiledPreparedModel(json.dumps(f['model'],allow_nan=False)); packet=f['packet']; obs=f['observations']
clockfiles={k:Path(str(files('msplatform.examples').joinpath(n))) for k,n in [('clock_authority','instrument_clock_authority_v1.json'),('instrument_epoch','instrument_epoch_v1.json')]}
clocks={k:file_record(p,'required_evidence') for k,p in clockfiles.items()}
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory); model_path=root/'model.json';model_path.write_text(json.dumps(f['model']),encoding='utf-8')
 records={'compiled_model':file_record(model_path,'required_evidence'),**clocks}; meta={'backend':'simion','field_status':'available','source_status':'not_requested','model_identity_sha256':f['model']['model_identity_sha256'],'clock':f['model']['drive']['clock']}
 artifact=OpenedArtifact(kind='field_bundle',product_id='fields',reference={'manifest':{'path':str(root/'inert-manifest.json'),'bytes':123,'sha256':'D'*64}},metadata=meta,records=records,paths={k:Path(v['path']) for k,v in records.items()},producer={})
 context=SimpleNamespace(tools={'simion':Path(sys.executable)})
 common=dict(particles=packet,clock_records=clocks,propagation=f['policy'],numerics=f['numerics'])
 observed=plan_tracking_execution(model,observations=obs,unit_size=50,**common); plain=plan_tracking_execution(model,observations={'plane_observations':[]},unit_size=50,**common)
 assert observed['observations']==obs and tracking_applicability(observed)!=tracking_applicability(plain)
 before=copy.deepcopy((packet,obs))
 with patch('msplatform.execution.stage_policy.read_stage_policy',return_value=({'limits':{'transient_run_directory_bytes':1},'artifact_retention':{}},{})),patch('msplatform.execution.owner.run_managed_stage',return_value={'manifest':{}}) as owner,patch('msplatform.results.artifacts.open_artifact',return_value='published'):
  assert operations.track(artifact,packet,propagation=f['policy'],observations=obs,numerics=f['numerics'],context=context)=='published'
  assert owner.call_args.kwargs['payload']['observations']==obs and owner.call_args.kwargs['action'].keywords['observations']==obs
  operations.track(artifact,packet,propagation=f['policy'],observations={'plane_observations':[]},numerics=f['numerics'],context=context)
  assert owner.call_args.kwargs['payload']['observations']=={'plane_observations':[]}
 assert (packet,obs)==before
 for k,v in [('clock_epoch_id','wrong'),('source_instance_id','wrong'),('eligible_batch_anchor_particle_id',999999),('max_rows',17)]:
  bad=copy.deepcopy(obs);bad['native_field_observation'][k]=v
  with patch('msplatform.execution.owner.run_managed_stage') as owner:
   try: operations.track(artifact,packet,propagation=f['policy'],observations=bad,numerics=f['numerics'],context=context)
   except ValueError: pass
   else: raise AssertionError('invalid accepted '+k)
   owner.assert_not_called()
 numerical=copy.deepcopy(f['field_numerics']);numerical.pop('downstream_convergence_v')
 design=plan_solve_fields(model,numerics=numerical)['field_design'];domains=[d['domain_id'] for d in design['domains']]
 names={'analyzer_component_source':'oatof_analyzer_component.lua','pulse_hook_source':'single_flight_pulse_hook.lua','frontend_hook_source':'single_flight_frontend_hook.lua','rf_drive_kernel_source':'rf_drive.lua','voltage_waveforms_source':'voltage_waveforms.lua'}
 sources={k:native_resource_path(v).read_text(encoding='utf-8') for k,v in names.items()};sources['native_path_source']=resource_path('native_run_path.lua').read_text(encoding='utf-8')
 def record(name):return {'path':str(root/name),'exists':True,'bytes':123,'sha256':'A'*64}
 front={d:{working_point_member_id(p):record(('frontend' if d=='parent' else 'frontend_entrance_refinement')+'.'+working_point_member_id(p)+'.pa') for p in design['working_points']} for d in domains}
 downstream={}
 for role in ('flight_tube','reflectron','detector'):
  family=[record(role+s) for s in ('.pa#','.pa0','.pa1','.pa-surf')] if role!='reflectron' else []
  downstream[role]={'carrier_record':family[1] if family else record(role+'.pa'),'family_records':family}
 kwargs={'field_design':design,'stored_bank':field_bank(design,domains),'frontend_records':front,'downstream_assets':downstream,'downstream_receipt':record('audit.json'),'native_sources':sources}
 first=_render_tracking_controls(model,slice_tracking_plan(observed,observed['units'][0]),**kwargs);second=_render_tracking_controls(model,slice_tracking_plan(observed,observed['units'][1]),**kwargs)
 assert 'applied_field_observation_header' in first['program'] and first['build_metadata']['native_field_observation']['specification']==obs['native_field_observation']
 assert 'applied_field_observation_header' not in second['program'] and 'native_field_observation' not in second['build_metadata']
 assert 'instance_adjust_observation_header' in first['program'] and 'candidate_callback_not_accepted_field_selection' in first['program']
 assert 'instance_adjust_observation_header' not in second['program']
 plain_program=_render_tracking_controls(model,slice_tracking_plan(plain,plain['units'][0]),**kwargs)['program']
 assert 'instance_adjust_observation_header' not in plain_program
 # Inert callback values exercise the installed collection route; they are not native measurements.
 bound=first['build_metadata']['native_field_observation'];spec=bound['specification'];context=bound['context']
 anchor=spec['eligible_batch_anchor_particle_id'];ids=observed['units'][0]['expected_particle_ids']
 origin=next(row['instrument_time_us'] for row in observed['rows'] if row['particle_id']==anchor)
 bucket=next(item for item in spec['buckets'] if item['time_max_us']>origin)
 time=max(origin,(bucket['time_min_us']+bucket['time_max_us'])/2);assert time<bucket['time_max_us']
 zero=[0.,0.,0.];members=context['field_records'][spec['domain_id']]
 rf_records=[value for key,value in sorted(members.items()) if key.startswith('rf_reference')]
 query=dict(schema_version=1,role='single_reflection_applied_field_query',basis='efield_adjust_query_only',
  record_seq=1,callback_seq=1,bucket_id=bucket['bucket_id'],instrument_time_us=time,solver_elapsed_us=time-origin,
  particle_id=anchor,ion_number=ids.index(anchor)+1,instance_index=context['instance_index'],domain_id=spec['domain_id'],
  world_frame_id=context['world_frame_id'],world_position_mm=zero,grid_spacing_mm=[1.,1.,1.],instance_scale=1.,
  instance_rotation_deg=zero,entry_gradient_gu=zero,rf_members=[dict(coefficient_used=0.,native_field_gu=zero,native_path=r['path']) for r in rf_records],
  pulse_active_used=False,pulse_basis='not_applied_not_queried',pa_gu=zero,after_dynamic_gradient_gu=zero,
  region_override={'replace_all':False},after_region_gradient_gu=zero,final_gradient_gu=zero,actual_rf_phase_rad=0.,
  rf_phase_basis='unwrapped_kernel_phase_at',carrier_native_path=members['carrier_off']['path'],carrier_native_field_gu=zero)
 header=dict(schema_version=1,role='single_reflection_applied_field_observation_header',specification=spec,context=context)
 counts={item['bucket_id']:int(item['bucket_id']==bucket['bucket_id']) for item in spec['buckets']}
 summary=dict(schema_version=1,role='single_reflection_applied_field_observation_summary',rows=1,counts=counts,
  coverage_complete=False,stopped_by='native_end',deadline_seen=False)
 candidate_header=dict(schema_version=1,role='single_reflection_instance_candidate_observation',
  semantics='candidate_callback_not_accepted_field_selection',particle_id=anchor,max_rows=16,max_output_bytes=65536,
  policy='first_observation_per_candidate_output_pair_before_deadline')
 cases=[dict(expected_particle_ids=unit['expected_particle_ids'],build_metadata=controls['build_metadata'])
  for unit,controls in zip(observed['units'],(first,second),strict=True)]
 logs=[root/'anchor.log',root/'other.log'];logs[1].write_text('',encoding='utf-8')
 events=[('instance_adjust_observation_header',candidate_header),('applied_field_observation_header',header),
  ('applied_field_observation',query),('applied_field_observation_summary',summary)]
 logs[0].write_text(''.join('TRACE: '+name+' '+json.dumps(value)+'\n' for name,value in events),encoding='utf-8')
 collected=_collect_unit_field_observation(observed,cases,logs,lambda unit:bound)
 assert collected['status']=='INCONCLUSIVE' and collected['queries']==[query]
 assert collected['candidate_observations']['status']=='INCONCLUSIVE' and not collected['candidate_observations']['rows']
 collection_input=root/'collection-input.json'
 collection_input.write_text(json.dumps(dict(plan=observed,cases=cases,logs=list(map(str,logs)),metadata=bound)),encoding='utf-8')
 parser_path=Path(observation_parser.__file__).resolve();parser_backup=parser_path.with_name(parser_path.name+'.observation-held')
 if parser_backup.exists(): raise FileExistsError(parser_backup)
 parser_bytes=parser_path.read_bytes();parser_path.rename(parser_backup)
 try:
  code="import json,sys;from msplatform.backends.simion.tracking_execution import _collect_unit_field_observation;d=json.load(open(sys.argv[1],encoding='utf-8'));_collect_unit_field_observation(d['plan'],d['cases'],d['logs'],lambda unit:d['metadata'])"
  missing_parser=subprocess.run([sys.executable,'-I','-B','-c',code,str(collection_input)],cwd=root,capture_output=True,text=True,timeout=30)
  assert missing_parser.returncode!=0 and 'ModuleNotFoundError' in missing_parser.stderr and 'msplatform.backends.simion.tracking_field_observation' in missing_parser.stderr,missing_parser.stderr
 finally:
  parser_backup.rename(parser_path)
 assert parser_path.read_bytes()==parser_bytes
 module_path=Path(tp.__file__).resolve(); backup=module_path.with_name(module_path.name+'.observation-held')
 if backup.exists(): raise FileExistsError(backup)
 original=module_path.read_bytes(); module_path.rename(backup)
 try:
  missing=subprocess.run([sys.executable,'-I','-B','-c','import msplatform.backends.simion.tracking_program'],cwd=root,capture_output=True,text=True,timeout=30)
  assert missing.returncode!=0 and 'ModuleNotFoundError' in missing.stderr and 'msplatform.backends.simion.tracking_program' in missing.stderr,missing.stderr
 finally:
  backup.rename(module_path)
 assert module_path.read_bytes()==original
 print('INSTALLED_PUBLIC_OBSERVATION=PASS valid=1 default=1 invalid=4 eligible_units=1 missing_module=1 collection=1 missing_parser=1')
