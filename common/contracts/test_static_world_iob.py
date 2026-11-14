"""Static-world one-slot model/tracking roles with inert SIMION API double."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from common.contracts.test_dual_cone_iob import HARNESS, LUA
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value

@unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
class StaticWorldIobTests(unittest.TestCase):
    def test_distinct_static_tracking_build_reopen_and_bad_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=root/'world.pa0';raw.write_bytes(b'inert-solved-carrier')
            surface=root/'world.pa-surf';surface.write_bytes(b'inert-surface')
            witness=root/'world.csv';witness.write_text('0,0,0,.25,nil,nil\n')
            seed=root/'seed.iob';seed.write_bytes(b'inert-seed');iob=root/'instrument.iob'
            iob.with_suffix('.lua').write_text('-- INERT PROGRAM');iob.with_suffix('.fly2').write_text('particles{standard_beam{n=2}}')
            row=dict(role='world',instance_index=1,priority_number=1,path=str(raw),fractional_surface=str(surface),surface_witnesses=str(witness),response_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),rotation=[[1,0,0],[0,1,0],[0,0,1]],placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)])
            spec=dict(schema_version=1,role='static_world_tracking_iob',instances=[row],seed_iob=str(seed),output_iob=str(iob),response_fields=[],bootstrap_paths=[str(root/'iob_seed_placeholder_01.pa0')])
            request=root/'spec.lua';script=root/'harness.lua';native=root/'native.lua';native.write_text('return function(path)return path end')
            code=(HARNESS.replace('arg={arg[1],mode,arg[5]}','local resources=arg[5];arg={arg[1],mode,arg[4]}').replace("arg[3]..'/build_tracking_iob.lua'","resources..'/build_tracking_iob.lua'").replace("arg[3]..'/iob_core.lua'","resources..'/iob_core.lua'"))
            script.write_text(code);resources=native_resource_path('iob_core.lua').parent
            def run(mode,value):
                request.write_text('return '+lua_value(value))
                return subprocess.run([str(LUA),str(script),str(request),mode,'valid',str(native),str(resources)],cwd=root,capture_output=True,text=True,timeout=30)
            for mode,marker in [('build','STATIC_WORLD_TRACKING_IOB=PASS'),('verify','STATIC_WORLD_TRACKING_IOB_REOPEN=PASS')]:
                result=run(mode,spec);self.assertEqual(result.returncode,0,result.stderr);self.assertIn(marker,result.stdout)
            bad=copy.deepcopy(spec);bad['instances'][0]['path']=str(root/'wrong.pa#')
            result=run('verify',bad);self.assertNotEqual(result.returncode,0)

    def test_distinct_static_model_build_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=root/'world.pa#';raw.write_bytes(b'inert-raw')
            surface=root/'world.pa-surf';surface.write_bytes(b'inert-surface')
            witness=root/'world.csv';witness.write_text('0,0,0,.25,nil,nil\n')
            seed=root/'seed.iob';seed.write_bytes(b'inert-seed');iob=root/'model.iob';control=root/'empty.fly2';control.write_text('particles{coordinates=0,}')
            row=dict(role='world',instance_index=1,priority_number=1,path=str(raw),fractional_surface=str(surface),surface_witnesses=str(witness),response_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),rotation=[[1,0,0],[0,1,0],[0,0,1]],placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)])
            config=root/'configuration.lua';config.write_text('return '+lua_value(dict(schema_version=1,role='simion_model_drive',model_identity_sha256='a'*64,clock=dict(clock_epoch_id='test',authority_sha256='a'*64,phase_reference_instrument_time_us=0),groups=[dict(instance_id='item',electrode_group_id='body',kind='static',voltage_v=1.25,native_targets=[dict(domain='world',electrode_id=1)])])))
            names={'consumer':'model_drive.lua','rf_drive':'rf_drive.lua','pulse_hook':'single_flight_pulse_hook.lua','waveforms':'voltage_waveforms.lua'}
            model=dict(configuration=str(config),report=str(root/'readback.txt'),**{key:str(native_resource_path(name)) for key,name in names.items()})
            spec=dict(schema_version=1,role='neutral_world_model_iob_build',instances=[row],seed_iob=str(seed),output_iob=str(iob),empty_particle_control=str(control),bootstrap_paths=[str(root/'iob_seed_placeholder_01.pa0')],model=model)
            request=root/'spec.lua';script=root/'harness.lua';native=root/'native.lua';native.write_text('return function(path)return path end')
            code=(HARNESS.replace('arg={arg[1],mode,arg[5]}','local resources=arg[5];arg={arg[1],mode,arg[4]}').replace("arg[3]..'/build_model_iob.lua'","resources..'/build_model_iob.lua'").replace("arg[3]..'/iob_core.lua'","resources..'/iob_core.lua'"))
            script.write_text(code);resources=native_resource_path('iob_core.lua').parent
            for mode,marker in [('build_model','NEUTRAL_WORLD_MODEL_BUILD=PASS'),('verify_model','NEUTRAL_WORLD_MODEL_READBACK=PASS')]:
                request.write_text('return '+lua_value(spec));result=subprocess.run([str(LUA),str(script),str(request),mode,'valid',str(native),str(resources)],cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr);self.assertIn(marker,result.stdout)
            self.assertIn('1.25',(root/'readback.txt').read_text())
