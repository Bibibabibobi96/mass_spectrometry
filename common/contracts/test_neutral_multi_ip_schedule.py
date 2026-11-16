"""Two canonical independent IP schedules in one neutral model; no native solve."""
import copy
import json
import unittest
from pathlib import Path
from common.contracts import test_neutral_ip_primitives as fixture
from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.backends.simion.model import RF_PHYSICS, compile_prepared_model, require_prepared_model
from msplatform.backends.simion.generic_scalar_binding import compile_linear_terms
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.io.file_identity import file_sha256

ROOT=Path(fixture.__file__).resolve().parents[2]
class MultiIpScheduleTests(unittest.TestCase):
 def test_real_two_ips_and_span(self):
  fixture.CanonicalIpNeutralTests.setUpClass();case=fixture.CanonicalIpNeutralTests(methodName='runTest')
  raw=json.loads((ROOT/'common/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
  other=copy.deepcopy(raw['component_requests']['ion_processor'])
  for key in other['design']['baseline']['schedule']:other['design']['baseline']['schedule'][key]+=10
  component=resolve_component(other)
  recipe=copy.deepcopy(case.assembly.composition_plan['recipe']);extra=copy.deepcopy(recipe['instances'][0]);extra['instance_id']='second_ip';extra['transform']['translation_mm'][0]+=20;recipe['instances'].append(extra);recipe['connections']=[]
  assembly=assemble(recipe,{'ion_processor':case.component,'second_ip':component});geometry=case.compile_complete(assembly)
  self.assertEqual(len(geometry.frontend_geometry['members']),30)
  clock={'clock_epoch_id':'instrument_clock_epoch_v1','authority_sha256':file_sha256(ROOT/'src/msplatform/examples/instrument_epoch_v1.json')}
  point=json.loads((ROOT/'projects/dual_pressure_rectilinear_ion_processor/config/native_operating_point.json').read_text(encoding='utf8'))
  drives={};schedules={}
  for instance in ('ion_processor','second_ip'):
   electrodes=assembly.components_resolved[instance]['projection']['electrodes']
   drives[instance]={e['name']:{'kind':'ip_schedule','schedule_index':e['electrode_id']} for e in electrodes}
   schedules[instance]={'baseline':assembly.components_source[instance]['baseline'],'native_operating_point':point,'clock':clock}
  drive={'groups':drives,'clock':dict(clock,phase_reference_instrument_time_us=0.),'ip_schedules':schedules}
  model=compile_prepared_model(geometry,assembly.components_resolved,drive=drive,physics=RF_PHYSICS);document=require_prepared_model(model)
  self.assertEqual(len(document['native_drive_rows']),30);self.assertEqual(set(document['drive']['ip_schedules']),set(drives))
  from msplatform.backends.simion.rf_tracking_execution import prepare_neutral_ip_hs1
  from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasSource, GasSpecies, GasState
  from msplatform.io.manifest_records import file_record
  from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import HS1_SOURCE_FIXTURE
  from unittest.mock import patch
  import tempfile
  def box(lo,hi):return BoxDomain(lo,hi,(True,True,True),(True,True,True))
  baseline=schedules['ion_processor']['baseline']
  outer=GasFieldSpec(field_id='outer',frame_id=baseline['clock']['frame_id'],representation='uniform',composition_id='ion_processor_explicit_single_gas',composition=(GasSpecies('ion_processor_model_gas',baseline['gas']['mass_amu'],1),),domain=box((-10000,)*3,(10000,)*3),source=GasSource('prescribed','test',()),uniform_state=GasState('vacuum',0,baseline['gas']['temperature_k'],(0,0,0)))
  domain=geometry.frontend_geometry['domain']
  grid={'frame_id':domain['frame_id'],'origin_mm':domain['minimum_mm'],'pitch_mm':[b-a for a,b in zip(domain['minimum_mm'],domain['maximum_mm'],strict=True)],'dimensions':[2,2,2]}
  with tempfile.TemporaryDirectory() as temp:
   vendor=Path(temp)/'vendor.lua';vendor.write_text(HS1_SOURCE_FIXTURE,encoding='utf8')
   request={'bath_domain':box((0,-10,-10),(211,10,10)),'outer':outer,'vendor_record':file_record(vendor),'numerics':{'seed':42,'hs1_steps_per_mfp':20}}
   with patch('msplatform.execution.owner.run_managed_stage') as blocked:
    with self.assertRaisesRegex(ValueError,'one selected IP placement'):
     prepare_neutral_ip_hs1(model,request,basis={'grid':grid})
    blocked.assert_not_called()
  for mutation in ('missing','extra','clock','mixed'):
   bad=copy.deepcopy(drive)
   if mutation=='missing':bad['ip_schedules'].pop('second_ip')
   if mutation=='extra':bad['ip_schedules']['missing']=bad['ip_schedules']['second_ip']
   if mutation=='clock':bad['ip_schedules']['second_ip']['clock']['authority_sha256']='0'*64
   if mutation=='mixed':bad['ip_schedule']=bad['ip_schedules']['ion_processor']
   with self.subTest(mutation=mutation),self.assertRaises((ValueError,KeyError)):compile_prepared_model(geometry,assembly.components_resolved,drive=bad,physics=RF_PHYSICS)
  snapshot={'composition_plan':assembly.composition_plan,'components_resolved':assembly.components_resolved,'components_source':assembly.components_source}
  projection=project_assembly_geometry(snapshot,outer_box_mm={'min':[-1000]*3,'max':[1000]*3});groups=[(x['instance_id'],x['electrode_group_id']) for x in projection['electrode_groups']]
  operator={'relative_permittivity':1.,'exterior':{'kind':'potential','voltage_v':0.},'mesh':{'global_automatic_level':5,'electrode_hmax_mm':4.},'study':{'kind':'stationary'}};samples={}
  for index,key in enumerate(groups):
   request=validate_request(projection,dict(group_voltages=[dict(instance_id=i,electrode_group_id=g,voltage_v=float((i,g)==key)) for i,g in groups],**operator))
   samples[str(index)]={'request':request,'weights':[dict(instance_id=i,electrode_group_id=g,weight=float((i,g)==key)) for i,g in groups]}
  plan=compile_linear_terms(projection,document['drive'],samples);self.assertEqual(sum(x.startswith('schedule_') for x in plan['terms']),30)
  with self.assertRaisesRegex(ValueError,'span'):compile_linear_terms(projection,document['drive'],dict(list(samples.items())[1:]))

  # Rename and declaration reorder preserve instance-scoped physical authority.
  from msplatform.backends.simion.operations import compile_geometry
  rename={'ion_processor':'z_first','second_ip':'a_second'}
  new_recipe=copy.deepcopy(recipe);new_recipe['instances'].reverse()
  for row in new_recipe['instances']:row['instance_id']=rename[row['instance_id']]
  renamed=assemble(new_recipe,{'z_first':case.component,'a_second':component});old_geo=geometry.frontend_geometry
  numerics={k:copy.deepcopy(old_geo[k]) for k in ('domain','pitch_mm','boundary','metal_witnesses','void_witnesses')};numerics['representation']='neutral_world_collision'
  for row in numerics['metal_witnesses']:row['instance_id']=rename[row['instance_id']]
  renamed_geometry=compile_geometry(renamed,numerics=numerics)
  renamed_drive=copy.deepcopy(drive);renamed_drive['groups']={rename[k]:v for k,v in drive['groups'].items()};renamed_drive['ip_schedules']={rename[k]:v for k,v in drive['ip_schedules'].items()}
  renamed_model=compile_prepared_model(renamed_geometry,renamed.components_resolved,drive=renamed_drive,physics=RF_PHYSICS)
  for old,new in rename.items():self.assertEqual(document['drive']['ip_schedules'][old],renamed_model.document['drive']['ip_schedules'][new])
  self.assertEqual(len(renamed_geometry.frontend_geometry['members']),30)

  # Generated Program executes both distinct schedules through the shared Lua drive.
  import ast,os,shutil,subprocess,tempfile
  from msplatform.backends.simion.rf_tracking_program import render_rf_controls
  from msplatform.backends.simion.resources import native_resource_path
  from msplatform.backends.simion.source import lua_value
  private=Path(__file__).resolve().parents[2]/'src/msplatform/backends/simion/resources/model_drive.lua'
  names=('scalar_field_adapter.lua','generic_scalar_field.lua','model_drive.lua','rf_drive.lua','rf_tracking.lua','single_flight_pulse_hook.lua','voltage_waveforms.lua','native_drive.lua')
  resources={name:(private if name=='model_drive.lua' else native_resource_path(name)).read_text(encoding='utf8') for name in names}
  bases={name:dict(grid=dict(frame_id='world',origin_mm=[0,0,0],pitch_mm=[1,1,1],dimensions=[3,3,3]),records={'field_v':{'path':'basis_'+name},'field_valid':{'path':'basis_'+name+'_field_valid'}},ideal_sheet_projection=[]) for name in samples}
  binding=dict(role='generic_linear_scalar_admission',model_identity_sha256=document['model_identity_sha256'],bases=bases,weights={name:item['weights'] for name,item in samples.items()})
  row=dict(particle_id=7,instrument_time_us=0.,particle_birth_time_us=0.,velocity_x_m_s=1.,velocity_y_m_s=2.,velocity_z_m_s=3.)
  flight=dict(flight=dict(tracking_kind='neutral_sampled',has_ip_schedule=True,maximum_step_us=1.,rf_steps_per_period=80,trajectory_quality=17,grouped=0),rows=[row],absolute_deadlines_us_by_particle_id={7:8000.},observations=dict(plane_observations=[]),propagation=dict(consumed_plane_events=[],stop=None))
  rendered=render_rf_controls(model,flight,assets={},native_sources=resources,scalar_bindings=binding,slot_domains=[None,'world'])
  tree=ast.parse((ROOT/'common/contracts/test_ip_mr_tracking_program.py').read_text(encoding='utf8'));prefix=next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prefix' for t in n.targets)).replace('BG_INDEX','2')
  edges=[document['drive']['ip_schedules'][x]['baseline']['schedule']['capture_end_us'] for x in ('ion_processor','second_ip')];self.assertNotEqual(*edges)
  cap=1e6/document['drive']['ip_schedules']['ion_processor']['baseline']['electric']['rf_frequency_hz']/80;epsilon=cap/4
  suffix="\nsegment.initialize_run();segment.initialize();local values=rf_consumer.evaluate_at(1505);local a,b={},{};for _,r in ipairs(values) do if r.instance_id=='ion_processor' then a[r.electrode_group_id]=r.voltage_v else b[r.electrode_group_id]=r.voltage_v end end;local diff=false;for k,v in pairs(a) do if v~=b[k] then diff=true end end;assert(diff);"
  for edge in edges:suffix += 'ion_time_of_flight='+lua_value(edge-epsilon)+';ion_time_step=1;segment.tstep_adjust();assert(math.abs(ion_time_step-'+lua_value(epsilon)+')<1e-9);'
  suffix += "print('MULTI_IP_PROGRAM=PASS')\n"
  lua=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua5.1') or shutil.which('lua')
  if not lua:raise FileNotFoundError('portable Lua required')
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'check.lua';path.write_text(prefix+'\n'+rendered['program'].replace('adjustable ','')+suffix,encoding='utf8')
   result= subprocess.run([lua,str(path)],cwd=temp,capture_output=True,text=True,encoding='utf8',timeout=30);self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('MULTI_IP_PROGRAM=PASS',result.stdout)

  # The actual model readback wrapper must sample edges from both schedules.
  from msplatform.backends.simion.model import render_model_configuration
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);wrapper=root/'build_model_iob.lua';wrapper.write_text((private.parent/'build_model_iob.lua').read_text(encoding='utf8'),encoding='utf8')
   (root/'iob_core.lua').write_text('return function() end\n',encoding='utf8')
   config=root/'configuration.lua';config.write_text(render_model_configuration(model),encoding='utf8')
   native_path=root/'native_path.lua';native_path.write_text('return function(path) return path end\n',encoding='utf8')
   spec={'role':'neutral_world_model_iob_build','seed_iob':str(root/'seed.iob'),'output_iob':str(root/'model.iob'),'bootstrap_paths':[],'instances':[{'role':'world','path':str(root/'world.pa')}],
     'model':{'configuration':str(config),'report':str(root/'readback.txt'),'consumer':str(private),'rf_drive':str(native_resource_path('rf_drive.lua')),'pulse_hook':str(native_resource_path('single_flight_pulse_hook.lua')),'waveforms':str(native_resource_path('voltage_waveforms.lua')),'native_drive':str(native_resource_path('native_drive.lua'))}}
   request=root/'spec.lua';request.write_text('return '+lua_value(spec),encoding='utf8')
   result=subprocess.run([lua,str(wrapper),str(request),'verify_model',str(native_path)],cwd=temp,capture_output=True,text=True,encoding='utf8',timeout=30)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   readback=(root/'readback.txt').read_text(encoding='utf8')
   for edge in edges:self.assertIn('time_us='+str(edge),readback)
   self.assertIn('GROUPS=30',result.stdout)
