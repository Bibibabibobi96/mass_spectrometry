"""Synthetic software fixtures for bounded native observation parsing."""
import copy,json,tempfile,unittest
from pathlib import Path
from msplatform.backends.simion import tracking_field_observation as module
class ObservationTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)
  self.spec={'eligible_batch_anchor_particle_id':11,'domain_id':'parent','deadline_us':100.,'max_output_bytes':1048576,'buckets':[{'bucket_id':'b'+str(i),'time_min_us':i*10.,'time_max_us':i*10.+9.} for i in range(8)]}
  self.ctx={'eligible_batch_particle_ids':[11],'instance_index':3,'world_frame_id':'world','rf_sources':[{'name':'rf'}],'field_records':{'parent':{'carrier_off':{'path':'carrier.pa'},'rf_reference':{'path':'rf.pa'}}}}
  self.source={11:{'instrument_time_us':5.},77:{'instrument_time_us':19.}}
  self.cases=[{'expected_particle_ids':[11],'build_metadata':{}},{'expected_particle_ids':[77],'build_metadata':{}}]
 def row(self,index):
  bucket=index//2;t=bucket*10.+6.;v=[0.,0.,0.]
  return dict(schema_version=1,role='single_reflection_applied_field_query',basis='efield_adjust_query_only',record_seq=index+1,callback_seq=index+1,bucket_id='b'+str(bucket),instrument_time_us=t,solver_elapsed_us=t-5.,particle_id=11,ion_number=1,instance_index=3,domain_id='parent',world_frame_id='world',world_position_mm=v,grid_spacing_mm=[1.,1.,1.],instance_scale=1.,instance_rotation_deg=v,entry_gradient_gu=v,rf_members=[dict(coefficient_used=0.,native_field_gu=v,native_path='rf.pa')],pulse_active_used=False,pulse_basis='not_applied_not_queried',pa_gu=v,after_dynamic_gradient_gu=v,region_override={'replace_all':False},after_region_gradient_gu=v,final_gradient_gu=v,actual_rf_phase_rad=0.,rf_phase_basis='unwrapped_kernel_phase_at',carrier_native_path='carrier.pa',carrier_native_field_gu=v)
 def lines(self,rows):
  h={'schema_version':1,'role':'single_reflection_applied_field_observation_header','specification':self.spec,'context':self.ctx}
  ch={'schema_version':1,'role':'single_reflection_instance_candidate_observation','semantics':'candidate_callback_not_accepted_field_selection','particle_id':11,'max_rows':16,'max_output_bytes':65536,'policy':'first_observation_per_candidate_output_pair_before_deadline'}
  c={'schema_version':1,'role':'single_reflection_instance_candidate','semantics':'candidate_callback_not_accepted_field_selection','record_seq':1,'particle_id':11,'ion_number':1,'instrument_time_us':6.,'solver_elapsed_us':1.,'world_position_mm':[0.,0.,0.],'candidate_instance':5,'output_instance':0}
  counts={'b'+str(i):sum(r['bucket_id']=='b'+str(i) for r in rows) for i in range(8)}
  summary={'schema_version':1,'role':'single_reflection_applied_field_observation_summary','rows':len(rows),'counts':counts,'coverage_complete':all(v==2 for v in counts.values()),'stopped_by':'native_end','deadline_seen':False}
  events=[('instance_adjust_observation_header',ch),('applied_field_observation_header',h),('instance_adjust_observation',c)]+[('applied_field_observation',x) for x in rows]+[('applied_field_observation_summary',summary)]
  return ''.join('TRACE: '+name+' '+json.dumps(x)+'\n' for name,x in events)
 def parse(self,text):
  a=self.path/'anchor.log';b=self.path/'other.log';a.write_text(text);b.write_text('')
  return module.collect_native_field_observations([a,b],self.cases,self.source,self.spec,lambda case:self.ctx)
 def test_full_sparse_ids_and_candidate(self):
  got=self.parse(self.lines([self.row(i) for i in range(16)]))
  self.assertEqual(got['status'],'RECORDED');self.assertEqual(len(got['queries']),16);self.assertEqual(got['candidate_observations']['rows'][0]['output_instance'],0)
 def test_distinct_birth_origins_with_sparse_ids(self):
  self.cases=[{'expected_particle_ids':[11,77],'build_metadata':{}}];self.ctx['eligible_batch_particle_ids']=[11,77]
  row=self.row(4);row.update(record_seq=1,callback_seq=1,particle_id=77,ion_number=2,instrument_time_us=26.,solver_elapsed_us=7.)
  a=self.path/'both.log';a.write_text(self.lines([row]));got=module.collect_native_field_observations([a],self.cases,self.source,self.spec,lambda case:self.ctx)
  self.assertEqual(got['queries'][0]['particle_id'],77);self.assertEqual(got['queries'][0]['instrument_time_us'],26.)
 def test_duplicate_candidate_pair_rejected(self):
  text=self.lines([]);candidate=next(line for line in text.splitlines() if 'TRACE: instance_adjust_observation {' in line)
  repeated=candidate.replace('"record_seq": 1','"record_seq": 2')
  text=text.replace(candidate+'\n',candidate+'\n'+repeated+'\n')
  with self.assertRaisesRegex(ValueError,'duplicate instance candidate'):self.parse(text)
 def test_wrong_native_source_refused(self):
  row=self.row(0);row['rf_members'][0]['native_path']='tampered.pa'
  with self.assertRaisesRegex(ValueError,'native member name differs'):self.parse(self.lines([row]))
 def test_json_context_integer_keys_match_native_wire(self):
  self.ctx['native_group_mapping']={1:'group_one'}
  got=self.parse(self.lines([self.row(0)]))
  self.assertEqual(got['queries'][0]['particle_id'],11)
 def test_public_unit_adapter_generated_and_reused_context(self):
  from msplatform.backends.simion.tracking_execution import _collect_unit_field_observation
  a=self.path/'anchor.log';b=self.path/'other.log';a.write_text(self.lines([self.row(0)]));b.write_text('')
  metadata={'specification':self.spec,'context':self.ctx}
  cases=[dict(self.cases[0],build_metadata={'native_field_observation':metadata}),self.cases[1]]
  for action in ('run','reuse'):
   units=[{'expected_particle_ids':[11],'action':action},{'expected_particle_ids':[77],'action':'run'}]
   plan={'units':units,'observations':{'native_field_observation':self.spec},'rows':[dict(particle_id=k,**v) for k,v in self.source.items()]}
   observed=_collect_unit_field_observation(plan,cases,[a,b],lambda unit:metadata)
   self.assertEqual(observed['status'],'INCONCLUSIVE');self.assertEqual(observed['candidate_observations']['rows'][0]['particle_id'],11)
  bad=copy.deepcopy(metadata);bad['context']['world_frame_id']='tampered'
  with self.assertRaisesRegex(ValueError,'context differs'):_collect_unit_field_observation(plan,cases,[a,b],lambda unit:bad)
 def test_actual_lua_generated_header_and_rows(self):
  import subprocess
  from unittest.mock import patch
  from integrations.tests import test_single_reflection_program as original
  if not original.LUA.is_file():self.skipTest('inert Lua interpreter unavailable')
  case=original.SingleReflectionProgramTests('test_bounded_field_observer_preserves_actual_callback_math_and_records_final_overrides')
  case.setUp();self.addCleanup(case.doCleanups)
  build=case.build;run=subprocess.run;metadata=[];outputs=[]
  def capture_build(*args,**kwargs):
   value={};kwargs['build_metadata']=value
   if kwargs.get('field_observation') is not None:
    kwargs['field_observation']=copy.deepcopy(kwargs['field_observation'])
    kwargs['field_observation']['evidence_context']['field_records']={'parent':{'carrier_off':{'path':'C:/inert/front.pa'},'rf_reference':{'path':'C:/inert/rf.pa'},'pulse_delta':{'path':'C:/inert/delta.pa'}}}
   result=build(*args,**kwargs)
   if kwargs.get('field_observation') is not None:metadata.append(value)
   return result
  def capture_run(*args,**kwargs):
   result=run(*args,**kwargs);outputs.append(result.stdout);return result
  with patch.object(case,'build',side_effect=capture_build),patch.object(original.subprocess,'run',side_effect=capture_run):
   case.test_bounded_field_observer_preserves_actual_callback_math_and_records_final_overrides()
  actual=next(x for x in outputs if 'TRACE: applied_field_observation_header ' in x and 'OBSERVATION_READ_COUNTS' in x)
  bound=metadata[0]['native_field_observation'];spec=bound['specification'];context=bound['context']
  log=self.path/'generated.log';log.write_text(actual,encoding='utf8')
  observed=module.collect_native_field_observations([log],[{'expected_particle_ids':[11,77],'build_metadata':{}}],{11:{'instrument_time_us':.25},77:{'instrument_time_us':2.5}},spec,lambda case:context)
  self.assertEqual(observed['status'],'RECORDED');self.assertEqual(len(observed['queries']),16)
  self.assertEqual({row['particle_id'] for row in observed['queries']},{11,77})
 def test_empty_windows_inconclusive(self):
  got=self.parse(self.lines([]));self.assertEqual(got['status'],'INCONCLUSIVE');self.assertEqual(len(got['missing_buckets']),8)
 def test_candidate_header_without_callback_is_inconclusive(self):
  text='\n'.join(line for line in self.lines([]).splitlines() if not line.startswith('TRACE: instance_adjust_observation '))+'\n'
  got=self.parse(text)['candidate_observations']
  self.assertEqual(got['status'],'INCONCLUSIVE');self.assertIsNotNone(got['header']);self.assertEqual(got['rows'],[])
 def test_clock_double_birth_rejected(self):
  row=self.row(0);row['solver_elapsed_us']+=5.
  with self.assertRaisesRegex(ValueError,'clock differs'):self.parse(self.lines([row]))
 def test_context_tamper_rejected(self):
  text=self.lines([self.row(0)]).replace('"world_frame_id": "world"','"world_frame_id": "wrong"',1)
  with self.assertRaisesRegex(ValueError,'header differs'):self.parse(text)
 def test_duplicate_json_and_nonfinite_refused(self):
  text=self.lines([self.row(0)]).replace('"record_seq": 1','"record_seq": 1, "record_seq": 1',1)
  with self.assertRaisesRegex(ValueError,'duplicate'):self.parse(text)
  row=self.row(0);row['actual_rf_phase_rad']=float('nan')
  with self.assertRaisesRegex(ValueError,'nonfinite'):self.parse(self.lines([row]))
if __name__=='__main__':unittest.main()
