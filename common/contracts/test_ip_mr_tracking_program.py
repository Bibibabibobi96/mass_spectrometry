"""Private IP–MR emitted callback tests; inert PA/HS1, no native claim."""
import copy
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts import test_ip_mr_model as models
from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model
from msplatform.backends.simion.resources import native_resource_path

from msplatform.backends.simion import rf_tracking_program as renderer
LUA = Path(os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1') or 'C:/Program Files/SIMION-2020/lua.exe')


class IpMrProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        models.RfIpMrModelTests.setUpClass()
        cls.model = compile_prepared_model(models.RfIpMrModelTests.compiled,
            models.RfIpMrModelTests.compiled.components_resolved,
            drive=models.RfIpMrModelTests.drive,physics=RF_IP_PHYSICS)
        cls.three_model = compile_prepared_model(models.IpMrModelTests.compiled,
            models.IpMrModelTests.compiled.components_resolved,
            drive=models.IpMrModelTests.drive,physics=RF_IP_PHYSICS)

    def fixture(self,root):
        document=self.model.document
        names=list(document['geometry']['frontend_geometry']['asset_components'])
        rows=[row for row in document['native_drive_rows'] if row['kind']=='ip_schedule']
        keys=['carrier']+['ip_'+str(row['schedule_index']) for row in rows]
        if any(row['kind']=='rf' for row in document['native_drive_rows']): keys.append('rf_reference')
        def item(name):
            return dict(grid=dict(origin_mm=[0.,0.,0.],pitch_mm=[1.,1.,1.],dimensions=[3,3,3]),
                records={key:dict(path='C:/inert/'+name+'_'+key,bytes=1,sha256='0'*64,exists=True)
                    for key in ('field_v','field_valid','grid')},ideal_sheet_projection=[])
        groups=[dict(instance_id=row['instance_id'],electrode_group_id=row['electrode_group_id'],
            schedule_index=row['schedule_index'],coefficient='model_drive.evaluate_at.voltage_v') for row in rows]
        rf=next((row for row in document['native_drive_rows'] if row['kind']=='rf'),None)
        rf_identity=(dict(instance_id=rf['instance_id'],waveform=rf['waveform'],frequency_hz=rf['frequency_hz'],
            phase_rad=rf['phase_rad'],coefficient='dimensionless_rf_waveform') if rf else None)
        basis=dict(schema_version=1,role='ip_mr_scalar_basis_binding',
            model_identity_sha256=document['model_identity_sha256'],bases={name:item(name) for name in keys},
            ip_groups=groups,rf=rf_identity)
        hs1={key:str(root/(key+'.lua')) for key in ('vendor_path','bath_path','outer_path')}
        hs1.update(query_frame_id=document['native_frame_id'],numerics=dict(seed=40,hs1_steps_per_mfp=20))
        gas="return {sample=function() return {status='vacuum',pressure_pa=0,temperature_k=300,bulk_velocity_m_s={0,0,0}} end}"
        (root/'bath_path.lua').write_text(gas,encoding='utf8')
        (root/'outer_path.lua').write_text(gas,encoding='utf8')
        row=dict(particle_id=7,instrument_time_us=4.,particle_birth_time_us=4.,velocity_x_m_s=1.,velocity_y_m_s=2.,velocity_z_m_s=3.)
        plan=dict(flight=dict(tracking_kind='ip_mr',maximum_step_us=.001,rf_steps_per_period=80,
                             trajectory_quality=17,grouped=0),rows=[row],absolute_deadlines_us_by_particle_id={7:204.},
            hs1=hs1,observations=dict(plane_observations=[]),propagation=dict(consumed_plane_events=[],stop=None))
        resources={name:native_resource_path(name).read_text(encoding='utf8') for name in
            ('scalar_field_adapter.lua','ip_mr_scalar_field.lua','rf_ip_tracking_hs1.lua')}
        resources['rf_ip_tracking_hs1.lua']=resources['rf_ip_tracking_hs1.lua'].replace('adjustable ','')
        return basis,names,plan,resources

    def test_four_asset_callback(self):
        self.exercise(self.model)

    def test_three_asset_callback(self):
        self.exercise(self.three_model)

    def exercise(self,model):
        self.model=model
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);basis,names,plan,resources=self.fixture(root)
            bindings=copy.deepcopy(basis)
            for name,item in bindings['bases'].items():
                item['refinement_windows']=[]
                for window in ('first','second'):
                    level=copy.deepcopy(item)
                    level.pop('refinement_windows',None)
                    level.update(name=window,active_box_mm=[[.5,1.5]]*3);level['grid'].update(origin_mm=[-1.,-1.,-1.],dimensions=[5,5,5])
                    for key,record in level['records'].items(): record['path']='C:/inert/'+name+'_'+window+'_'+key
                    item['refinement_windows'].append(level)
            before=copy.deepcopy((bindings,plan,names))
            result=renderer.render_rf_controls(self.model,plan,assets={},native_sources=resources,
                scalar_bindings=bindings,slot_domains=[*names,None])
            self.assertEqual((bindings,plan,names),before)
            self.assertEqual(len(result['immutable_input_records']),(17 if 'rf_reference' in bindings['bases'] else 16)*9)
            self.assertIn('ip_mr_scalar(instance,ion_px_mm,ion_py_mm,ion_pz_mm,single_flight_instrument_time_us())',result['program'])
            bad=copy.deepcopy(bindings);bad['bases'].pop('ip_1')
            with self.assertRaisesRegex(ValueError,'coverage'):renderer.render_rf_controls(self.model,plan,assets={},native_sources=resources,scalar_bindings=bad,slot_domains=[*names,None])
            with self.assertRaisesRegex(ValueError,'slot domains'):renderer.render_rf_controls(self.model,plan,assets={},native_sources=resources,scalar_bindings=bindings,slot_domains=[names[0]]*len(names)+[None])
            with self.assertRaisesRegex(ValueError,'slot domains'):renderer.render_rf_controls(self.model,plan,assets={},native_sources=resources,scalar_bindings=bindings,slot_domains=names)
            changed=copy.deepcopy(bindings);changed['ip_groups'][0]['schedule_index']=2
            with self.assertRaisesRegex(ValueError,'group/index'):renderer.render_rf_controls(self.model,plan,assets={},native_sources=resources,scalar_bindings=changed,slot_domains=[*names,None])
            unadmitted=copy.deepcopy(bindings);unadmitted['model_identity_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'matching admitted'):renderer.render_rf_controls(self.model,plan,assets={},native_sources=resources,scalar_bindings=unadmitted,slot_domains=[*names,None])
            self.assertTrue(LUA.is_file())
            prefix = r'''
segment={}; simion={pas={},experimental={},wb={instances={}}}
function simion.workbench_program() end
function simion.early_access() end
local calls=0;local chosen_first=0;local chosen_second=0;local invalid=false;local invalid_path=nil;local init_count=0;local seeds={}
function seed(n) seeds[#seeds+1]=n end
function simion.pas:open(path)
 local n=(path:find('_first_',1,true) or path:find('_second_',1,true)) and 5 or 3
 return {path=path,symmetry='3dplanar',nx=n,ny=n,nz=n,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,
  potential=function(self) if path:find('_field_valid',1,true) and (invalid or path==invalid_path) then return 0 end return 1 end,
  potential_vc=function() return 1 end,electrode=function() end}
end
simion.experimental.field_array=function(t) return {efield=function() calls=calls+1;if t.V.path:find('_first_',1,true) then chosen_first=chosen_first+1 elseif t.V.path:find('_second_',1,true) then chosen_second=chosen_second+1 end;return 1,2,3 end} end
local hs={segment={}}
function hs.reset_run_state() end
function hs.bound_parameters() return {gas_mass_amu=_gas_mass_amu,temperature_k=_temperature_k,pressure_pa=_pressure_pa,
 sigma_m2=_sigma_m2,mean_free_path_mm=_mean_free_path_mm,steps_per_mfp=_steps_per_MFP,random_seed=_random_seed,
 mark_collisions=_mark_collisions,trace_level=_trace_level} end
function hs.segment.initialize() init_count=init_count+1 end
function hs.segment.tstep_adjust() end
function hs.segment.other_actions() end
function simion.import() return hs end
ion_number=1;ion_time_of_flight=0;ion_instance=1;ion_px_mm=1;ion_py_mm=1;ion_pz_mm=1
ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0;ion_mass=100;ion_charge=1;ion_splat=0;ion_time_step=.001
simion.wb.instances[1]={scale=2,pa={dx_mm=.5,dy_mm=1,dz_mm=2},wb_to_pa_orient=function(self,x,y,z) return y,-x,z end}
adj_elect=setmetatable({}, {__newindex=function() error("background fast_adjust wrote electrode") end})
simion.wb.instances[2]={scale=1,pa={dx_mm=1,dy_mm=1,dz_mm=1},wb_to_pa_orient=function(self,x,y,z) return x,y,z end}
for i=3,BG_INDEX do simion.wb.instances[i]=simion.wb.instances[2] end
'''
            suffix = r'''
segment.initialize_run();assert(init_count==1 and seeds[#seeds]==40)
ion_instance=BG_INDEX;segment.fast_adjust();ion_instance=1
segment.initialize();segment.tstep_adjust();segment.tstep_adjust()
assert(init_count==2 and seeds[#seeds]==46)
calls=0;segment.efield_adjust();assert(calls==EXPECTED_SUPPORTS);assert(chosen_first==EXPECTED_SUPPORTS and chosen_second==0)
local x1,y1,z1=ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu
ion_instance=2;calls=0;segment.efield_adjust();assert(calls==EXPECTED_SUPPORTS)
local x2,y2,z2=ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu
for slot=3,BG_INDEX do ion_instance=slot;calls=0;segment.efield_adjust();assert(calls==EXPECTED_SUPPORTS) end
ion_instance=2
assert(math.abs(x1-2*x2)<1e-8 and math.abs(y1+2*x2)<1e-8 and math.abs(z1-4*z2)<1e-8)
local schedule=rf_model_config.ip_schedule.baseline.schedule
local edges={schedule.capture_end_us,schedule.transfer_end_us,schedule.lift_end_us,schedule.terminal_us}
for _,edge in ipairs(edges) do
 if edge>=4 then
  for _,time in ipairs({edge-1e-7,edge,edge+1e-7}) do
   ion_time_of_flight=time-4;calls=0;segment.efield_adjust();assert(calls==EXPECTED_SUPPORTS)
   local total=1;local values=rf_consumer.evaluate_at(time)
   for i,row in ipairs(rf_model_config.groups) do if row.kind=='ip_schedule' then total=total+values[i].voltage_v end end
   if RF_PRESENT then
    for _,row in ipairs(rf_model_config.groups) do if row.kind=='rf' then
      local wave=rf_kernel.compile_physical{waveform=row.waveform,frequency_hz=row.frequency_hz,phase_rad=row.phase_rad,rf_amplitude_v=1,rf_scale=1}
      total=total+wave.differential_at(time);break end end
   end
   assert(math.abs(ion_dvoltsx_gu+total)<1e-7*(1+math.abs(total)))
  end
 end
end
local values=rf_consumer.evaluate_at(single_flight_instrument_time_us());local zero_index=nil
for i,row in ipairs(rf_model_config.groups) do if row.kind=='ip_schedule' and values[i].voltage_v==0 then zero_index=row.schedule_index;break end end
assert(zero_index,"fixture must expose a zero IP coefficient")
if zero_index then
 invalid_path='C:/inert/ip_'..zero_index..'_first_field_valid'
 local ok,err=pcall(segment.efield_adjust);assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN',1,true));invalid_path=nil
end
invalid=true;local ok,err=pcall(segment.efield_adjust);assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN',1,true))
invalid=false;ion_instance=99;ok,err=pcall(segment.efield_adjust);assert(not ok and string.find(err,'selected instance required',1,true))
ion_time_of_flight=0;segment.initialize_run();segment.initialize();segment.tstep_adjust();assert(seeds[#seeds]==46)
print('IP_MR_PROGRAM_INERT_LUA=PASS')
'''
            suffix=suffix.replace('EXPECTED_SUPPORTS',str(17 if 'rf_reference' in bindings['bases'] else 16)).replace('RF_PRESENT','true' if 'rf_reference' in bindings['bases'] else 'false').replace('BG_INDEX',str(len(names)+1))
            prefix=prefix.replace('BG_INDEX',str(len(names)+1))
            script=root/'check.lua';script.write_text(prefix+result['program']+suffix,encoding='utf8')
            run=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30,check=False)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('IP_MR_PROGRAM_INERT_LUA=PASS',run.stdout)
