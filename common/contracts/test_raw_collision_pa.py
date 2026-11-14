"""Small owned PA-format input and inert Lua API-double; no SIMION."""
import os
import shutil
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from msplatform.backends.simion.resources import native_resource_path

RESOURCE=native_resource_path('raw_collision_pa.lua')
HARNESS=r"""
local resource,source,output,path_resource,scenario=unpack(arg)
local nodes,surf,stored={},{},{}
for z=0,2 do for y=0,2 do for x=0,2 do local k=x..','..y..','..z;local metal=(x==1 and y==1);nodes[k]={metal and (z+1) or 0,metal} end end end
surf['1,1,1']={.25,.5,.75}
local function clone(t)local a={};for k,v in pairs(t) do a[k]=type(v)=='table' and clone(v) or v end;return a end
local function object(data,surface,refinable)
 local o={nx=3,ny=3,nz=3,dx_mm=.5,dy_mm=1,dz_mm=1.5,symmetry='3dplanar',potential_type='electric',refinable=refinable,data=clone(data),surfaces=clone(surface)}
 function o:size(x,y,z)self.nx=x;self.ny=y;self.nz=z end
 function o:points()local i=-1;return function()i=i+1;if i>=self.nx*self.ny*self.nz then return nil end;return i%self.nx,math.floor(i/self.nx)%self.ny,math.floor(i/(self.nx*self.ny)) end end
 function o:point(x,y,z,value,metal)local k=x..','..y..','..z;if value~=nil then self.data[k]={value,metal};return end;local a=self.data[k] or {0,false};return a[1],a[2] end
 function o:surface_info(x,y,z,...)local k=x..','..y..','..z;local args={...};if select('#',...)>0 then self.surfaces[k]=args;return end;local a=self.surfaces[k] or {};return a[1],a[2],a[3] end
 function o:save(path)if scenario=='save_failure' then error('SIMULATED_SAVE_FAILURE') end;stored[path]={data=clone(self.data),surfaces=clone(self.surfaces),refinable=self.refinable};local f=assert(io.open(path,'wb'));f:write('INERT-API-DOUBLE');f:close();local g=assert(io.open(path:gsub('%.pa$','.pa-surf'),'wb'));g:write('INERT-SURFACE-DOUBLE');g:close();return nil end
 function o:close()end
 return o
end
simion={pas={}}
function simion.pas:close()end
function simion.pas:open(path)if not path then return object({}, {},true) end;if path==source then return object(nodes,surf,true) end;local a=assert(stored[path]);return object(a.data,a.surfaces,a.refinable) end
local function call(mode)arg={mode,source,output,path_resource};return pcall(assert(loadfile(resource))) end
if scenario=='source_vacuum' then nodes['0,0,0']={1,false} end
local ok,err=call('build')
if scenario=='save_failure' then assert(not ok and tostring(err):find('SIMULATED_SAVE_FAILURE',1,true));print('EXPECTED_FAILURE');return end
if scenario=='source_vacuum' or scenario=='companion' or scenario=='existing' then assert(not ok and tostring(err):find(scenario=='source_vacuum' and 'raw vacuum must be zero' or scenario=='companion' and 'raw geometry response family forbidden' or 'collision destination already exists',1,true));print('EXPECTED_FAILURE');return end
assert(ok,err)
if scenario=='value' then stored[output].data['1,1,1'][1]=99 end
if scenario=='flag' then stored[output].data['1,1,1'][2]=false end
if scenario=='surface' then stored[output].surfaces['1,1,1'][1]=.8 end
if scenario=='refinable' then stored[output].refinable=true end
ok,err=call('verify')
if scenario~='positive' then assert(not ok and tostring(err):find('differs',1,true));print('EXPECTED_FAILURE');return end
assert(ok,err);print('INERT_RAW_COLLISION_TEST=PASS')
"""


def _lua_provider():
    if 'SIMION_LUA_EXE' in os.environ:
        value=os.environ['SIMION_LUA_EXE']
        if not value: raise ValueError('explicit SIMION_LUA_EXE is empty')
        return value
    return shutil.which('lua') or shutil.which('lua5.1')


class RawCollisionContractTests(unittest.TestCase):
    def test_explicit_bad_lua_provider_does_not_fallback(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'SIMION_LUA_EXE':'invalid-explicit-lua'}), patch('shutil.which') as fallback:
            self.assertEqual(_lua_provider(),'invalid-explicit-lua')
            fallback.assert_not_called()
        with patch.dict(os.environ, {'SIMION_LUA_EXE':''}), patch('shutil.which') as fallback:
            with self.assertRaisesRegex(ValueError,'explicit SIMION_LUA_EXE is empty'): _lua_provider()
            fallback.assert_not_called()

    def test_owned_small_pa_and_inert_api_cases(self):
        lua=_lua_provider()
        if not lua:self.skipTest('standalone Lua not available')
        for case in ('positive','source_vacuum','companion','existing','value','flag','surface','refinable','save_failure'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);source=root/'source.pa#';out=root/'output.pa'
                values=[(2000+z+1) if x==1 and y==1 else 0 for z in range(3) for y in range(3) for x in range(3)]
                raw=struct.pack('<iidiiiiddd',-2,1,1000.,3,3,3,0,.5,1.,1.5)+struct.pack('<27d',*values)
                source.write_bytes(raw);(root/'source.pa-surf').write_bytes(b'INERT-SURFACE-DOUBLE')
                if case=='companion':(root/'source.pa1').write_bytes(b'forbidden')
                if case=='existing':out.write_bytes(b'foreign')
                path_resource=root/'path.lua';path_resource.write_text('return function(path)return path end',encoding='utf8')
                harness=root/'harness.lua';harness.write_text(HARNESS,encoding='utf8')
                result=subprocess.run([lua,str(harness),str(RESOURCE),str(source),str(out),str(path_resource),case],cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('INERT_RAW_COLLISION_TEST=PASS' if case=='positive' else 'EXPECTED_FAILURE',result.stdout)
                self.assertEqual(source.read_bytes(),raw)
                if case=='existing':self.assertEqual(out.read_bytes(),b'foreign')

    def test_solved_export_guard_is_unchanged(self):
        solved=native_resource_path('export_detached_standalone_pa.lua').read_text(encoding='utf8')
        self.assertIn('surface offset transfer differs',solved)
        self.assertIn('never .paN',solved)
