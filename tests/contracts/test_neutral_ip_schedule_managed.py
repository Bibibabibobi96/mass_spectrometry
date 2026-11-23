"""Canonical IP public owner chain; all native leaves and samples are inert."""
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
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.simion import operations
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.execution.run_session import RunSession
from msplatform.results.artifacts import open_artifact

ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(os.name=='nt','Windows owner required')
class CanonicalNeutralScheduleManagedTests(unittest.TestCase):
 @patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
 def test_public_schedule_field_and_original_birth_tracking(self):
  ip_fixture.CanonicalIpNeutralTests.setUpClass();case=ip_fixture.CanonicalIpNeutralTests(methodName='runTest');assembly=case.assembly
  large=case.compile_complete(assembly);g=large.frontend_geometry;offset=[9960,7745,9990]
  witnesses=[dict(instance_id=x['instance_id'],electrode_group_id=x['electrode_group_id'],gu=[n-d for n,d in zip(x['gu'],offset,strict=True)]) for x in g['metal_witnesses']]
  frame=assembly.composition_plan['assembly_frame_id'];num=dict(representation='neutral_world_collision',domain=dict(frame_id=frame,minimum_mm=[-4,-225.5,-1],maximum_mm=[5.6,-34,7]),pitch_mm=.1,boundary='native_zero_neumann',metal_witnesses=witnesses,void_witnesses=[[0,0,0],[40,1907,40]])
  compiled=operations.compile_geometry(assembly,numerics=num)
  snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
  projection=project_assembly_geometry(snapshot,outer_box_mm={'min':[-1000]*3,'max':[1000]*3})
  groups=[(row['instance_id'],row['electrode_group_id']) for row in projection['electrode_groups']]
  electrodes=assembly.components_resolved['ion_processor']['projection']['electrodes']
  rows={e['name']:dict(kind='ip_schedule',schedule_index=e['electrode_id']) for e in electrodes}
  point=json.loads((ROOT/'src/msplatform/components/dual_pressure_rectilinear_ion_processor/config/native_operating_point.json').read_text(encoding='utf8'))
  with retained_on_failure() as directory:
   context,budget,retention=make_context(Path(directory));policy=json.loads(context.stage_policy_path.read_text(encoding='utf8'))
   for stage in ('build_geometry','prepare_model','solve_fields'):
    policy['stages'][stage]=copy.deepcopy(policy['stages']['track'])
    policy['stages'][stage]['limits']['transient_run_directory_bytes']=536870912
    policy['stages'][stage]['limits']['compact_final_retained_bytes']=536870912
   policy['stages']['solve_fields']['limits']['reserved_run_payload_bytes']=268435456
   context.stage_policy_path.write_text(json.dumps(policy),encoding='utf8')
   fixture=scalar_fixture.SfiScalarAdmissionTests(methodName='runTest');fixture.projection=projection;fixture.snapshot=snapshot
   fixture.publish=lambda name,kind,data,metadata,inputs=None,linked=None:publish_fixture(context,budget,retention,name=name,kind=kind,data=data,metadata=metadata,inputs=inputs,linked=linked)
   geometry=fixture.make_geometry();samples={};window_samples={};operator=dict(relative_permittivity=1.,exterior={'kind':'potential','voltage_v':0.},mesh={'global_automatic_level':9,'electrode_hmax_mm':5.},study={'kind':'stationary'})
   grid=dict(frame_id=frame,origin_mm=[-12.,-400.,-9.],pitch_mm=[4.,100.,6.],dimensions=[5,5,5],block_points=125,study_tag='std1',solution_tag='sol1',dataset_tag='dset1',point_count=125,maximum_mm=[4.,0.,15.],coordinate_sanity_mm=1e-6)
   header=PaHeader(-2,1,10000.,5,5,5,1<<28,4.,100.,6.).pack();zero=header+bytes(1000);valid=header+struct.pack('<125d',*([1.]*125))
   for index,key in enumerate(groups):
    request=validate_request(projection,dict(group_voltages=[dict(instance_id=i,electrode_group_id=k,voltage_v=float((i,k)==key)) for i,k in groups],**operator))
    data=dict(projection=projection,request=request,geometry_validation={'position_mm':1e-6},reopen_geometry={'vacuum_domains':[1]},reopen_solution={'solution':scalar_fixture.SOLUTION},model=b'inert fixture model')
    solution_ref=fixture.publish('ip-solution-'+str(index),'field_solution',data,dict(backend='comsol',scope='single_stationary_workpoint',field_status='solved',native_reopen_verified=True,solution=scalar_fixture.SOLUTION))
    source=open_artifact(solution_ref,expected_kind='field_solution')
    report=dict(status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(source.data_path('model')),vacuum_domains=[1],fem_valid=125,invalid_count=0,solution_readback=scalar_fixture.SOLUTION,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'},**grid)
    sample_data=dict(projection=projection,grid=grid,request=request,reopen_solution={'solution':scalar_fixture.SOLUTION},geometry_validation={'position_mm':1e-6},reopen_geometry={'vacuum_domains':[1]},report=report,field_v=zero,field_valid=valid)
    ref=fixture.publish('ip-sample-'+str(index),'scalar_field_samples',sample_data,dict(backend='comsol',scope='assembly_world_scalar_samples',field_status='sampled',frame_id=frame),linked={'field_solution_manifest':solution_ref['manifest'],'field_solution_model':source.data_records['model']})
    samples[str(index)]=dict(reference=ref,request=request,weights=[dict(instance_id=i,electrode_group_id=k,weight=float((i,k)==key)) for i,k in groups])
    # A separately sampled window extends beyond base x=4 into the same collision world.
    window_grid=dict(grid,origin_mm=[3.5,-400.,-9.],pitch_mm=[.5,100.,6.],maximum_mm=[5.5,0.,15.])
    window_header=PaHeader(-2,1,10000.,5,5,5,1<<28,.5,100.,6.).pack()
    window_report=dict(report,**window_grid)
    window_data=dict(sample_data,grid=window_grid,report=window_report,field_v=window_header+bytes(1000),field_valid=window_header+struct.pack('<125d',*([1.]*125)))
    window_samples[str(index)]=fixture.publish('ip-window-sample-'+str(index),'scalar_field_samples',window_data,dict(backend='comsol',scope='assembly_world_scalar_samples',field_status='sampled',frame_id=frame),linked={'field_solution_manifest':solution_ref['manifest'],'field_solution_model':source.data_records['model']})
   original=RunSession.run_process;calls=[];field_guards=[];tracking_guards=[];fail_verify=[False];live_refs=[];live_checks=[]
   inert=make_inert(self,compiled,original,calls,field_guards,tracking_guards,fail_verify,live_refs,live_checks,directory,context)
   from msplatform.io.file_identity import file_sha256
   identity=dict(clock_epoch_id='instrument_clock_epoch_v1',authority_sha256=file_sha256(ROOT/'src/msplatform/examples/instrument_epoch_v1.json'))
   drive=dict(groups={'ion_processor':rows},clock={'phase_reference_instrument_time_us':0.},clock_authority={'example_resource':'instrument_clock_authority_v1.json'},ip_schedule=dict(baseline=assembly.components_source['ion_processor']['baseline'],native_operating_point=point,clock=identity))
   fail_fly=[False]
   def guarded_inert(session,operation_id,*,immutable_input_records=(),**kwargs):
    if fail_fly[0] and operation_id=='track_fly':
     return original(session,operation_id,executable=Path(__import__('sys').executable),arguments=['-I','-B','-c','raise SystemExit(7)'],role='GATE',stage='inert_failed_fly',limits=kwargs['limits'],immutable_input_records=immutable_input_records)
    return inert(session,operation_id,immutable_input_records=immutable_input_records,**kwargs)
   with patch.object(RunSession,'run_process',new=guarded_inert):
    built=operations.build_geometry(compiled,context=context)
    model=operations.prepare_model(built,drive=drive,physics=RF_PHYSICS,context=context)
    field=operations.solve_fields(model,numerics={},context=context,scalar_field_basis=dict(geometry_artifact=geometry,operator=operator,samples=samples,refinement_windows=[dict(name='outside_base',active_box_mm=[[4.25,4.75],[-200,-150],[0,6]],samples=window_samples)]))
    from tests.contracts.test_simion_rf_tracking import rf_tracking_case
    from tests.contracts.test_component_particle_state import valid_row
    from msplatform.assembly.handoff import HandoffMother
    from msplatform.backends.simion.source import project_source_states
    from msplatform.contracts.clock import ClockIdentity
    from msplatform.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
    from msplatform.io.manifest_records import file_record
    _,_,_,_,propagation,numerics=rf_tracking_case()
    rows=[];records={}
    for pid,mass,charge,weight in [(7,100.,1,2.5),(91,200.,-2,4.)]:
     row=valid_row(pid)
     row.update(parent_particle_id=None,source_component_id='ion_processor',target_component_id='ion_processor',frame_id='dual_pressure_ion_processor_local_v1',
      clock_epoch_id=identity['clock_epoch_id'],state_event='source_birth',instrument_time_us=1.25,
      lineage_birth_time_us=1.25,particle_birth_time_us=1.25,lineage_age_us=0.,particle_age_us=0.,last_component_elapsed_time_us=0.,
      species_id='species_'+str(pid),mass_amu=mass,charge_state=charge,mass_to_charge_Th=mass_to_charge_th(mass,charge),particle_weight=weight,
      phase_reference_id=None,phase_rad=None,kinetic_energy_eV=kinetic_energy_ev(mass,*[row['velocity_'+axis+'_m_s'] for axis in 'xyz']))
     rows.append(row);records[pid]=dict(row,source_component_entry_time_us=1.25)
    fates=[dict(particle_id=pid,category='released') for pid in records]
    clock_records={name:file_record(ROOT/'src/msplatform/examples'/filename,'required_evidence') for name,filename in
     [('clock_authority','instrument_clock_authority_v1.json'),('instrument_epoch','instrument_epoch_v1.json')]}
    project_source_states(rows,mother=HandoffMother(records,fates),clock=ClockIdentity(**identity),state_kind='source_birth',clock_records=clock_records)
    packet=dict(schema_version=1,role='canonical_release_realization',state_kind='source_birth',rows=rows,
     mother=dict(records=records,fates=fates),clock=identity,realization=dict(spec=dict(particle_count=2)))
    wrong_clock=copy.deepcopy(packet);wrong_clock['clock']['authority_sha256']='0'*64
    with patch('msplatform.execution.owner.run_managed_stage') as blocked:
     with self.assertRaisesRegex(ValueError,'handoff clock epoch or authority differs'):
      operations.track(field,wrong_clock,propagation=propagation,observations={'plane_observations':[]},numerics=numerics,context=context)
     blocked.assert_not_called()
    with patch('msplatform.execution.owner.run_managed_stage') as blocked:
     with self.assertRaises(ValueError):operations.track(field,packet,propagation=propagation,observations={'plane_observations':[]},numerics=numerics,context=context,recovery_reference={'path':'relative'})
     blocked.assert_not_called()
    trajectory=operations.track(field,packet,propagation=propagation,observations={'plane_observations':[]},numerics=numerics,context=context)
    self.assertEqual(len(tracking_guards),3)
    from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasSource, GasSpecies, GasState
    from msplatform.io.manifest_records import file_record
    from tests.projects.dual_pressure_rectilinear_ion_processor.test_functional import HS1_SOURCE_FIXTURE
    def box(lo,hi):return BoxDomain(lo,hi,(True,True,True),(True,True,True))
    baseline=assembly.components_source['ion_processor']['baseline']
    outer=GasFieldSpec(field_id='outer',frame_id=baseline['clock']['frame_id'],representation='uniform',composition_id='ion_processor_explicit_single_gas',composition=(GasSpecies('ion_processor_model_gas',baseline['gas']['mass_amu'],1),),domain=box((-10000,-10000,-10000),(10000,10000,10000)),source=GasSource('prescribed','test',()),uniform_state=GasState('vacuum',0,baseline['gas']['temperature_k'],(0,0,0)))
    vendor=Path(directory)/'hs1_vendor.lua';vendor.write_text(HS1_SOURCE_FIXTURE,encoding='utf8')
    hs1={'bath_domain':box((0,-10,-10),(211,10,10)),'outer':outer,'vendor_record':file_record(vendor),'numerics':{'seed':42,'hs1_steps_per_mfp':20}}
    hs1_propagation=copy.deepcopy(propagation);hs1_propagation['dynamics']['collisions']='hs1'
    from msplatform.backends.simion.rf_tracking_execution import admit_neutral_sampled_tracking_fields, prepare_neutral_ip_hs1
    actual_admission=admit_neutral_sampled_tracking_fields(field.reference)
    self.assertEqual(actual_admission['basis']['bases']['0']['refinement_windows'][0]['active_box_mm'],[[4.25,4.75],[-200,-150],[0,6]])
    gas=prepare_neutral_ip_hs1(actual_admission['model'],hs1,basis=actual_admission['basis'])
    self.assertEqual(gas['identity']['common_world_domain']['maximum_mm'][0],4.75)
    from dataclasses import replace
    too_small=dict(hs1,outer=replace(outer,domain=box((-1,-1,-1),(1,1,1))))
    with self.assertRaisesRegex(ValueError,'complete parent box'):
     operations.track(field,packet,propagation=hs1_propagation,observations={'plane_observations':[]},numerics=dict(numerics,grouped=0),context=context,hs1_request=too_small)
    from msplatform.workflows.multipole_ip.continuous import track_existing_fields
    with patch('msplatform.execution.owner.run_managed_stage') as blocked:
     with self.assertRaises((ValueError,TypeError,KeyError)):
      track_existing_fields(fields={},particles=packet,propagation=hs1_propagation,observations={'plane_observations':[]},tracking_numerics=dict(numerics,grouped=0),context=context,hs1_request=hs1)
     with self.assertRaisesRegex(ValueError,'handoff clock epoch or authority differs'):
      track_existing_fields(fields=field,particles=wrong_clock,propagation=hs1_propagation,observations={'plane_observations':[]},tracking_numerics=dict(numerics,grouped=0),context=context,hs1_request=hs1)
     blocked.assert_not_called()
    hs1_trajectory=track_existing_fields(fields=field,particles=packet,propagation=hs1_propagation,observations={'plane_observations':[]},tracking_numerics=dict(numerics,grouped=0),context=context,hs1_request=hs1)
    self.assertEqual(len(tracking_guards),6)
    hs1_collection=json.loads(hs1_trajectory.data_path('collection').read_text(encoding='utf8'))
    self.assertEqual([r['particle_id'] for r in hs1_collection['native_terminals']],[7,91])
    self.assertEqual(len(hs1_collection['original_mother']['mother_records']),2)
    from msplatform.io.manifest_records import record_path
    from msplatform.backends.simion.resources import native_resource_path
    manifest_path=Path(hs1_trajectory.reference['manifest']['path'])
    hs1_manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    inputs=hs1_manifest['inputs']
    names=('hs1_vendor_original','hs1_vendor','hs1_bath','hs1_outer','hs1_identity',
           'resource_collision_hs1_gas.lua','resource_rf_ip_gas_selection.lua','resource_rf_ip_tracking_hs1.lua')
    self.assertTrue(set(names) <= set(inputs))
    paths={name:record_path(inputs[name],base_dir=manifest_path.parent).resolve() for name in names}
    for name,path in paths.items():
     self.assertEqual(file_sha256(path).lower(),inputs[name]['sha256'].lower())
    self.assertEqual(file_sha256(paths['hs1_vendor_original']).lower(),file_sha256(vendor).lower())
    self.assertEqual(paths['hs1_vendor_original'].read_bytes(),vendor.read_bytes())
    identity=json.loads(paths['hs1_identity'].read_text(encoding='utf8'))
    for name,key in (('hs1_vendor','vendor_adapted_sha256'),('hs1_bath','bath_runtime_sha256'),('hs1_outer','outer_runtime_sha256')):
     self.assertEqual(file_sha256(paths[name]).lower(),identity[key].lower())
    for name in names[-3:]:
     self.assertEqual(file_sha256(paths[name]).lower(),file_sha256(native_resource_path(name.removeprefix('resource_'))).lower())
    for guard in tracking_guards[3:6]:self.assertTrue({str(path) for path in paths.values()} <= guard)
    from msplatform.execution.processes import ProcessExecutionError
    fail_fly[0]=True
    with self.assertRaises(ProcessExecutionError):operations.track(field,packet,propagation=propagation,observations={'plane_observations':[]},numerics=numerics,context=context)
   collection=json.loads(trajectory.data_path('collection').read_text(encoding='utf8'))
   self.assertEqual([r['particle_id'] for r in collection['native_terminals']],[7,91]);self.assertEqual(len(collection['original_mother']['mother_records']),2)
   self.assertEqual(calls[-2:],['build_tracking_iob','verify_tracking_iob'])
   self.assertEqual(len(tracking_guards),8)
   selected_paths={str(open_artifact(row['reference'],expected_kind='scalar_field_samples').data_path(key).resolve()) for row in samples.values() for key in ('field_v','field_valid','grid')}
   selected_paths.update(str(open_artifact(ref,expected_kind='scalar_field_samples').data_path(key).resolve()) for ref in window_samples.values() for key in ('field_v','field_valid','grid'))
   for guard in tracking_guards:self.assertTrue(selected_paths <= guard)
   from msplatform.execution.capacity_protection import load_capacity_protection_leases
   self.assertEqual(load_capacity_protection_leases(context.workspace/'artifacts')['audit'],[])
   # The public owner chain accepts the same schedule in instance-keyed form.
   keyed_drive=copy.deepcopy(drive)
   keyed_drive['ip_schedules']={'ion_processor':keyed_drive.pop('ip_schedule')}
   fail_fly[0]=False
   with patch.object(RunSession,'run_process',new=guarded_inert):
    keyed_model=operations.prepare_model(built,drive=keyed_drive,physics=RF_PHYSICS,context=context)
    keyed_field=operations.solve_fields(keyed_model,numerics={},context=context,scalar_field_basis=dict(geometry_artifact=geometry,operator=operator,samples=samples,refinement_windows=[dict(name='outside_base',active_box_mm=[[4.25,4.75],[-200,-150],[0,6]],samples=window_samples)]))
    keyed_admission=admit_neutral_sampled_tracking_fields(keyed_field.reference)
    keyed_gas=prepare_neutral_ip_hs1(keyed_admission['model'],hs1,basis=keyed_admission['basis'])
    self.assertEqual(keyed_gas['identity'],gas['identity'])
    keyed_trajectory=operations.track(keyed_field,packet,propagation=hs1_propagation,observations={'plane_observations':[]},numerics=dict(numerics,grouped=0),context=context,hs1_request=hs1)
    keyed_collection=json.loads(keyed_trajectory.data_path('collection').read_text(encoding='utf8'))
    self.assertEqual([r['particle_id'] for r in keyed_collection['native_terminals']],[7,91])
   self.assertEqual(load_capacity_protection_leases(context.workspace/'artifacts')['audit'],[])
