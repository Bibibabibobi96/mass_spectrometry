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
if mode=="grid" or mode=="empty_grid" then pa.nx=6 end
if mode=="overflow" then pa.debug_max_voltage=1e308 end
function pa:point(x,y,z)
  if x==1 then return mode=="voltage" and 6 or 5, mode~="metal" end
  if x==2 then return -3,true end
  return 0,false
end
function pa:surface_info() if mode=="empty" or mode=="empty_grid" then return nil,nil,nil end if mode=="empty_offset" then return .25,nil,nil end if mode=="surface" then return .5,nil,nil end return .25,nil,nil end
function pa:points() local n=-1;return function() n=n+1;if n>=125 then return nil end;return n%5,math.floor(n/5)%5,math.floor(n/25) end end
function pa:potential_vc() if mode=="nonfinite" then return 0/0 end return 1 end
function pa:field_vc() return 1,2,3 end
function pa:close() end
function pa:fast_adjust() error("forbidden Fast Adjust") end
function pa:refine() error("forbidden Refine") end
function pa:save() error("forbidden save") end
simion={pas={close=function() end,open=function() return pa end}}
local root=arg[2]
local f=assert(io.open(root.."/spec.lua","wb"))
f:write('return {assets={{domain_id="world",carrier_path="'..root..'/world.pa",surface_path="'..root..'/world.pa-surf",grid={nx=5,ny=5,nz=5,dx_mm=1,dy_mm=1,dz_mm=1},physical_samples={{gu={1,1,1},metal=true,expected_voltage_v=5},{gu={2,1,1},metal=true,expected_voltage_v=-3},{gu={3,1,1},metal=false}},surface_witnesses="'..root..'/witness.csv",surface_mode="'..(mode:match("^empty") and "empty" or "present")..'",sample_points_gu={{'..(mode=="outside" and "9" or "0.5")..',0.5,0.5}}}},output="'..root..'/report.json"}')
f:close();arg={[1]=root.."/spec.lua"};assert(loadfile(root.."/audit.lua"))()
''', encoding='utf-8')
            (root/'audit.lua').write_bytes(audit.read_bytes())
            for mode in ('pass', 'grid', 'metal', 'voltage', 'surface', 'nonfinite', 'outside', 'overflow', 'missing_max', 'nonnumeric_max', 'missing', 'empty', 'empty_offset', 'empty_grid'):
                report = root/'report.json'
                report.unlink(missing_ok=True)
                surface = root/'world.pa-surf'
                if mode == 'missing' or mode.startswith('empty'):
                    surface.unlink(missing_ok=True)
                if mode.startswith('empty'):
                    (root/'witness.csv').write_bytes(b'1,1,1,nil,nil,nil\n')
                result = subprocess.run([str(lua), str(script), mode, lua_path(root)], cwd=root,
                                        capture_output=True, text=True, timeout=30, check=False)
                with self.subTest(mode=mode):
                    self.assertEqual(result.returncode == 0, mode in ('pass','empty'), result.stderr)
                    self.assertEqual(report.exists(), mode in ('pass','empty'))

    def test_family_empty_surface_scans_real_offsets(self):
        lua = os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
        if not lua: self.skipTest('standalone Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('world.pa#','world.pa0','world.pa1'):(root/name).write_bytes(b'fixture')
            (root/'witness.csv').write_text('1,1,1,nil,nil,nil\n')
            (root/'audit.lua').write_bytes(native_resource_path('audit_rf_field_family.lua').read_bytes())
            script=root/'family.lua'
            script.write_text('''
local mode,root=arg[1],arg[2]
local pa={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,potential_type="electric",symmetry="3dplanar",electrode_numbers={1}}
function pa:points() local n=-1;return function() n=n+1;if n>=27 then return nil end;return n%3,math.floor(n/3)%3,math.floor(n/9) end end
function pa:surface_info(x,y,z) if mode=="hidden_offset" and x==2 then return .5,nil,nil end return nil,nil,nil end
function pa:point(x,y,z) return 0,x==1 end
function pa:potentials_minmax() return 0,0 end
function pa:close() end
simion={pas={close=function()end,open=function()return pa end}}
local f=assert(io.open(root.."/spec.lua","wb"))
f:write('return {assets={{domain_id="world",carrier_path="'..root..'/world.pa0",family_paths={"'..root..'/world.pa#","'..root..'/world.pa0","'..root..'/world.pa1"},response_ids={1},grid={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1},physical_samples={{gu={1,1,1},metal=true}},surface_witnesses="'..root..'/witness.csv",surface_mode="empty"}},output="'..root..'/report.json"}')
f:close();arg={[1]=root.."/spec.lua"};assert(loadfile(root.."/audit.lua"))()
''',encoding='utf8')
            for mode in ('empty','hidden_offset','unexpected_sidecar'):
                (root/'report.json').unlink(missing_ok=True)
                if mode=='unexpected_sidecar':(root/'world.pa-surf').write_bytes(b'unexpected')
                result=subprocess.run([str(lua),str(script),mode,str(root).replace('\\','/')],cwd=root,capture_output=True,text=True,timeout=30)
                with self.subTest(mode=mode):
                    self.assertEqual(result.returncode==0,mode=='empty',result.stderr)
                    self.assertEqual((root/'report.json').exists(),mode=='empty')
