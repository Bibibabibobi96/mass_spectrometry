"""Exercise neutral one-slot IOB transport with inert Lua PA stubs."""
from pathlib import Path
import copy
import subprocess
import tempfile
import unittest
from tests.contracts.test_dual_cone_iob import HARNESS, LUA
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value

@unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
class NeutralCollisionIobTests(unittest.TestCase):
    def test_build_reopen_and_reject_wrong_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); seed=root/'seed.iob';seed.write_bytes(b'inert-seed')
            raw=root/'body.pa#';raw.write_bytes(b'inert-raw')
            surface=root/'body.pa-surf';surface.write_bytes(b'inert-surface')
            witness=root/'surface.csv';witness.write_text('0,0,0,.25,nil,nil\n')
            control=root/'empty.fly2';control.write_text('particles{coordinates=0,}')
            row=dict(role='world',instance_index=1,priority_number=1,path=str(raw),fractional_surface=str(surface),surface_witnesses=str(witness),response_ids=[1],electrode_witness_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),rotation=[[1,0,0],[0,1,0],[0,0,1]],placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),physical_samples=[dict(gu=[1,0,0],metal=False)])
            spec=dict(schema_version=1,role='neutral_world_geometry_iob_build',instances=[row],seed_iob=str(seed),output_iob=str(root/'geometry.iob'),bootstrap_paths=[str(root/'iob_seed_placeholder_01.pa0')],empty_particle_control=str(control))
            request=root/'spec.lua';script=root/'harness.lua';script.write_text(HARNESS)
            resources=native_resource_path('iob_core.lua').parent
            def invoke(mode,value):
                request.write_text('return '+lua_value(value))
                return subprocess.run([str(LUA),str(script),str(request),mode,'valid','unused',str(resources)],cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30)
            for mode,marker in [('build_geometry','NEUTRAL_WORLD_GEOMETRY_IOB=PASS'),('verify_geometry','NEUTRAL_WORLD_GEOMETRY_IOB_REOPEN=PASS')]:
                result=invoke(mode,spec);self.assertEqual(result.returncode,0,result.stderr);self.assertIn(marker,result.stdout)
            bad=copy.deepcopy(spec);bad['instances'][0]['electrode_witness_ids']=[2]
            result=invoke('verify_geometry',bad);self.assertNotEqual(result.returncode,0);self.assertIn('undeclared electrode',result.stderr)
