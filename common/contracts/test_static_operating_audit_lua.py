"""Exercise the reviewed cold auditor with a portable Lua PA API double."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from msplatform.backends.simion.resources import native_resource_path


class StaticOperatingAuditLuaTests(unittest.TestCase):
    def test_cold_read_and_explicit_refusals(self):
        lua = os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
        if not lua:
            self.skipTest('standalone Lua unavailable')
        audit = native_resource_path('audit_static_operating_pa.lua')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('world.pa', 'world.pa-surf'):
                (root/name).write_bytes(b'fixture')
            (root/'witness.csv').write_bytes(b'1,1,1,0.25,nil,nil\n')
            lua_path = lambda p: str(p).replace('\\', '/')
            script = root/'double.lua'
            script.write_text('''
local mode=arg[1]
local pa={nx=5,ny=5,nz=5,dx_mm=1,dy_mm=1,dz_mm=1,potential_type="electric",symmetry="3dplanar",debug_max_voltage=10}
if mode=="missing_max" then pa.debug_max_voltage=nil end
if mode=="nonnumeric_max" then pa.debug_max_voltage="invalid" end
assert(pa.max_voltage == nil)
if mode=="grid" then pa.nx=6 end
if mode=="overflow" then pa.debug_max_voltage=1e308 end
function pa:point(x,y,z)
  if x==1 then return mode=="voltage" and 6 or 5, mode~="metal" end
  if x==2 then return -3,true end
  return 0,false
end
function pa:surface_info() if mode=="surface" then return .5,nil,nil end return .25,nil,nil end
function pa:potential_vc() if mode=="nonfinite" then return 0/0 end return 1 end
function pa:field_vc() return 1,2,3 end
function pa:close() end
function pa:fast_adjust() error("forbidden Fast Adjust") end
function pa:refine() error("forbidden Refine") end
function pa:save() error("forbidden save") end
simion={pas={close=function() end,open=function() return pa end}}
local root=arg[2]
local f=assert(io.open(root.."/spec.lua","wb"))
f:write('return {assets={{domain_id="world",carrier_path="'..root..'/world.pa",surface_path="'..root..'/world.pa-surf",grid={nx=5,ny=5,nz=5,dx_mm=1,dy_mm=1,dz_mm=1},physical_samples={{gu={1,1,1},metal=true,expected_voltage_v=5},{gu={2,1,1},metal=true,expected_voltage_v=-3},{gu={3,1,1},metal=false}},surface_witnesses="'..root..'/witness.csv",sample_points_gu={{'..(mode=="outside" and "9" or "0.5")..',0.5,0.5}}}},output="'..root..'/report.json"}')
f:close();arg={[1]=root.."/spec.lua"};assert(loadfile(root.."/audit.lua"))()
''', encoding='utf-8')
            (root/'audit.lua').write_bytes(audit.read_bytes())
            for mode in ('pass', 'grid', 'metal', 'voltage', 'surface', 'nonfinite', 'outside', 'overflow', 'missing_max', 'nonnumeric_max', 'missing'):
                report = root/'report.json'
                report.unlink(missing_ok=True)
                surface = root/'world.pa-surf'
                if mode == 'missing':
                    surface.unlink()
                result = subprocess.run([str(lua), str(script), mode, lua_path(root)], cwd=root,
                                        capture_output=True, text=True, timeout=30, check=False)
                with self.subTest(mode=mode):
                    self.assertEqual(result.returncode == 0, mode == 'pass', result.stderr)
                    self.assertEqual(report.exists(), mode == 'pass')
