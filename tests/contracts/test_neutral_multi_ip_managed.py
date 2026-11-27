"""Two complete canonical IPs through public model/field owners; inert leaves only."""
import copy
import json
import os
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.contracts import test_neutral_ip_primitives as ip_fixture
from tests.contracts.test_ip_mr_tracking_producer_admission import retained_on_failure
from tests.contracts import test_sfi_scalar_binding as scalar_fixture
from tests.contracts.test_support.sfi_scalar_owner_fixture import make_context, publish_fixture
from tests.contracts.test_support.generic_scalar_owner_harness import make_inert
from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.simion import operations
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.backends.simion.rf_tracking_execution import admit_neutral_sampled_tracking_fields
from msplatform.execution.run_session import RunSession
from msplatform.io.file_identity import file_sha256
from msplatform.results.artifacts import open_artifact

ROOT=Path(__file__).resolve().parents[2]
@unittest.skipUnless(os.name=='nt','Windows owner required')
class MultiIpPublicFieldTests(unittest.TestCase):
 @patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
 def test_two_ip_public_model_and_field_admission(self):
  ip_fixture.CanonicalIpNeutralTests.setUpClass();case=ip_fixture.CanonicalIpNeutralTests(methodName='runTest')
  raw=json.loads((ROOT/'tests/contracts/test_support/ip_mr_current_requests.json').read_text(encoding='utf8'))
  other=copy.deepcopy(raw['component_requests']['ion_processor'])
  for key in other['design']['baseline']['schedule']:other['design']['baseline']['schedule'][key]+=10
  component=resolve_component(other);recipe=copy.deepcopy(case.assembly.composition_plan['recipe'])
  second=copy.deepcopy(recipe['instances'][0]);second['instance_id']='renamed_second';second['transform']['translation_mm'][0]+=20
  recipe['instances']=[second,recipe['instances'][0]];recipe['connections']=[]
  assembly=assemble(recipe,{'ion_processor':case.component,'renamed_second':component})
  large=case.compile_complete(assembly);g=large.frontend_geometry;offset=[9960,7745,9990]
  witnesses=[dict(instance_id=x['instance_id'],electrode_group_id=x['electrode_group_id'],gu=[n-d for n,d in zip(x['gu'],offset,strict=True)]) for x in g['metal_witnesses']]
  frame=assembly.composition_plan['assembly_frame_id'];num=dict(representation='neutral_world_collision',domain=dict(frame_id=frame,minimum_mm=[-4,-225.5,-1],maximum_mm=[24,-34,7]),pitch_mm=.1,boundary='native_zero_neumann',metal_witnesses=witnesses,void_witnesses=[[0,0,0],[40,1907,40]])
  compiled=operations.compile_geometry(assembly,numerics=num);self.assertEqual(len(compiled.frontend_geometry['members']),30)
  snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
  projection=project_assembly_geometry(snapshot,outer_box_mm={'min':[-1000]*3,'max':[1000]*3});groups=[(r['instance_id'],r['electrode_group_id']) for r in projection['electrode_groups']]
  self.assertEqual(len(groups),30)
  clock=dict(clock_epoch_id='instrument_clock_epoch_v1',authority_sha256=file_sha256(ROOT/'src/msplatform/examples/instrument_epoch_v1.json'))
  point=json.loads((ROOT/'src/msplatform/components/ion_processor/config/native_operating_point.json').read_text(encoding='utf8'))
  group_drive={};schedules={}
  for name in ('ion_processor','renamed_second'):
   group_drive[name]={e['name']:dict(kind='ip_schedule',schedule_index=e['electrode_id']) for e in assembly.components_resolved[name]['projection']['electrodes']}
   schedules[name]=dict(baseline=assembly.components_source[name]['baseline'],native_operating_point=point,clock=clock)
  drive=dict(groups=group_drive,clock={'phase_reference_instrument_time_us':0.},clock_authority={'example_resource':'instrument_clock_authority_v1.json'},ip_schedules=schedules)
  with retained_on_failure() as directory:
   context,budget,retention=make_context(Path(directory))
   capacity=json.loads(context.capacity_policy_path.read_text(encoding='utf8'));capacity['target_gib']=4;context.capacity_policy_path.write_text(json.dumps(capacity),encoding='utf8')
   policy=json.loads(context.stage_policy_path.read_text(encoding='utf8'))
   for stage in ('build_geometry','prepare_model','solve_fields'):
    policy['stages'][stage]=copy.deepcopy(policy['stages']['track']);policy['stages'][stage]['limits']['transient_run_directory_bytes']=1073741824;policy['stages'][stage]['limits']['compact_final_retained_bytes']=1073741824
   policy['stages']['solve_fields']['limits']['reserved_run_payload_bytes']=1073741824;context.stage_policy_path.write_text(json.dumps(policy),encoding='utf8')
   fixture=scalar_fixture.SfiScalarAdmissionTests(methodName='runTest');fixture.projection=projection;fixture.snapshot=snapshot
   fixture.publish=lambda name,kind,data,metadata,inputs=None,linked=None:publish_fixture(context,budget,retention,name=name,kind=kind,data=data,metadata=metadata,inputs=inputs,linked=linked)
   geometry=fixture.make_geometry();samples={};operator=dict(relative_permittivity=1.,exterior={'kind':'potential','voltage_v':0.},mesh={'global_automatic_level':9,'electrode_hmax_mm':5.},study={'kind':'stationary'})
   grid=dict(frame_id=frame,origin_mm=[-12.,-400.,-9.],pitch_mm=[10.,100.,6.],dimensions=[5,5,5],block_points=125,study_tag='std1',solution_tag='sol1',dataset_tag='dset1',point_count=125,maximum_mm=[28.,0.,15.],coordinate_sanity_mm=1e-6)
   header=PaHeader(-2,1,10000.,5,5,5,1<<28,10.,100.,6.).pack();zero=header+bytes(1000);valid=header+struct.pack('<125d',*([1.]*125))
   for index,key in enumerate(groups):
    request=validate_request(projection,dict(group_voltages=[dict(instance_id=i,electrode_group_id=k,voltage_v=float((i,k)==key)) for i,k in groups],**operator))
    data=dict(projection=projection,request=request,geometry_validation={'position_mm':1e-6},reopen_geometry={'vacuum_domains':[1]},reopen_solution={'solution':scalar_fixture.SOLUTION},model=b'inert fixture model')
    solution=fixture.publish('multi-solution-'+str(index),'field_solution',data,dict(backend='comsol',scope='single_stationary_workpoint',field_status='solved',native_reopen_verified=True,solution=scalar_fixture.SOLUTION));source=open_artifact(solution,expected_kind='field_solution')
    report=dict(status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(source.data_path('model')),vacuum_domains=[1],fem_valid=125,invalid_count=0,solution_readback=scalar_fixture.SOLUTION,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'},**grid)
    data=dict(projection=projection,grid=grid,request=request,reopen_solution={'solution':scalar_fixture.SOLUTION},geometry_validation={'position_mm':1e-6},reopen_geometry={'vacuum_domains':[1]},report=report,field_v=zero,field_valid=valid)
    ref=fixture.publish('multi-sample-'+str(index),'scalar_field_samples',data,dict(backend='comsol',scope='assembly_world_scalar_samples',field_status='sampled',frame_id=frame),linked={'field_solution_manifest':solution['manifest'],'field_solution_model':source.data_records['model']})
    samples[str(index)]=dict(reference=ref,request=request,weights=[dict(instance_id=i,electrode_group_id=k,weight=float((i,k)==key)) for i,k in groups])
   original=RunSession.run_process;calls=[];field_guards=[];tracking_guards=[];fail_verify=[False];live_refs=[];live_checks=[]
   inert=make_inert(self,compiled,original,calls,field_guards,tracking_guards,fail_verify,live_refs,live_checks,directory,context)
   with patch.object(RunSession,'run_process',new=inert):
    built=operations.build_geometry(compiled,context=context)
    wrong=copy.deepcopy(drive);wrong['ip_schedules']['renamed_second']['clock']['authority_sha256']='0'*64
    with patch('msplatform.execution.owner.run_managed_stage') as blocked:
     with self.assertRaises(ValueError):operations.prepare_model(built,drive=wrong,physics=RF_PHYSICS,context=context)
     blocked.assert_not_called()
    model=operations.prepare_model(built,drive=drive,physics=RF_PHYSICS,context=context)
    manifest=json.loads(Path(model.reference['manifest']['path']).read_text(encoding='utf8'))
    self.assertIn('model_source_native_drive.lua',manifest['inputs'])
    specs=[v for k,v in manifest['inputs'].items() if k.startswith('model_spec_')]
    self.assertTrue(any('native_drive' in Path(v['path']).read_text(encoding='utf8') for v in specs))
    missing=dict(list(samples.items())[1:])
    with patch('msplatform.execution.owner.run_managed_stage') as blocked:
     with self.assertRaisesRegex(ValueError,'span'):operations.solve_fields(model,numerics={},context=context,scalar_field_basis=dict(geometry_artifact=geometry,operator=operator,samples=missing))
     blocked.assert_not_called()
    field=operations.solve_fields(model,numerics={},context=context,scalar_field_basis=dict(geometry_artifact=geometry,operator=operator,samples=samples))
    admitted=admit_neutral_sampled_tracking_fields(field.reference)
    self.assertEqual(set(admitted['basis']['bases']),set(samples));self.assertEqual(len(admitted['model'].document['native_drive_rows']),30)
    self.assertEqual(set(admitted['model'].document['drive']['ip_schedules']),{'ion_processor','renamed_second'})
    self.assertEqual(admitted['model'].document['drive']['ip_schedules']['renamed_second']['baseline']['schedule']['capture_end_us'],1510)
   self.assertEqual(len(field_guards),6)
   from msplatform.execution.capacity_protection import load_capacity_protection_leases
   self.assertEqual(load_capacity_protection_leases(context.workspace/'artifacts')['audit'],[])
