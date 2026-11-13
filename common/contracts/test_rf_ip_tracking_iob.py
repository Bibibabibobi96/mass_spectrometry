"""Continuous RF-IP tracking workbench projection."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from common.contracts.test_dual_cone_iob import HARNESS, LUA
from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.backends.simion.source import lua_value


@unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
class RfIpTrackingIobTests(unittest.TestCase):
    def test_joint_one_parent_build_reopen_and_mapping_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); seed=root/'seed/one.iob';seed.parent.mkdir();seed.write_bytes(structural_seed_path(1).read_bytes())
            output=root/'instrument.iob';output.with_suffix('.lua').write_text('-- inert Program');output.with_suffix('.fly2').write_text('particles{standard_beam{n=1}}')
            raw=root/'parent.pa0';raw.write_bytes(b'INERT_PA');surface=root/'parent.pa-surf';surface.write_bytes(b'INERT_SURFACE')
            witness=root/'surface.csv';witness.write_text('0,0,0,.25,nil,nil\n')
            row=dict(role='parent',instance_index=1,priority_number=1,path=str(raw),fractional_surface=str(surface),
                surface_witnesses=str(witness),response_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),
                rotation=[[1,0,0],[0,1,0],[0,0,1]],placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),
                physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=0),dict(gu=[1,0,0],metal=False)])
            spec=dict(schema_version=1,role='rf_ip_tracking_iob',instances=[row],seed_iob=str(seed),output_iob=str(output),
                bootstrap_paths=[str(seed.parent/'iob_seed_placeholder_01.pa0')],response_fields=[])
            request=root/'spec.lua';script=root/'harness.lua';native_path=root/'native_path.lua';native_path.write_text('return function(path)return path end')
            code=(HARNESS.replace("arg={arg[1],mode,arg[5]}", "local resources=arg[5];arg={arg[1],mode,arg[4]}")
                  .replace("arg[3]..'/build_tracking_iob.lua'", "resources..'/build_tracking_iob.lua'"))
            script.write_text(code,encoding='utf-8');resources=native_resource_path('iob_core.lua').parent
            def call(mode, fault='valid'):
                request.write_text('return '+lua_value(spec),encoding='utf-8')
                return subprocess.run([str(LUA),str(script),str(request),mode,fault,str(native_path),str(resources)],cwd=root,
                    capture_output=True,text=True,encoding='utf-8',timeout=30)
            for mode,marker in [('build','RF_IP_TRACKING_IOB=PASS'),('verify','RF_IP_TRACKING_IOB_REOPEN=PASS')]:
                result=call(mode);self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn(marker,result.stdout)
                self.assertFalse((seed.parent/'iob_seed_placeholder_01.pa0').exists())
            result=call('verify','mapping');self.assertNotEqual(result.returncode,0);self.assertIn('undeclared electrode',result.stderr)
