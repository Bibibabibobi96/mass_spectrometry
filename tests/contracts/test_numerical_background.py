"""Actual installed Lua background builders against inert small API doubles."""
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from msplatform.backends.simion.resources import native_resource_path

HARNESS=r'''
local build,reopen,output,pathres,scenario=unpack(arg)
local stored=nil;simion={pas={}}
local function object()
 local o={nx=0,ny=0,nz=0,data={}}
 function o:size(x,y,z) self.nx=x;self.ny=y;self.nz=z end
 function o:points() local i=-1;return function() i=i+1;if i<self.nx*self.ny*self.nz then return i%self.nx,math.floor(i/self.nx)%self.ny,math.floor(i/(self.nx*self.ny)) end end end
 function o:point(x,y,z,v,m) local k=x..','..y..','..z;if v~=nil then self.data[k]={v,m};return end;local a=self.data[k];return a[1],a[2] end
 function o:save(path) stored=self;local f=assert(io.open(path,'wb'));f:write('INERT');f:close() end
 function o:close() end
 return o
end
function simion.pas:open(path) if not path then return object() end return assert(stored) end
arg={output,'3','3','3','.5','1','1.5',pathres}
local ok,err=pcall(assert(loadfile(build)));assert(ok,err)
if scenario=='metal' then stored.data['1,1,1']={0,true} end
if scenario=='value' then stored.data['1,1,1']={1,false} end
if scenario=='pitch' then stored.dx_mm=2 end
ok,err=pcall(assert(loadfile(reopen)))
if scenario=='valid' then assert(ok,err);print('BACKGROUND_STUB=PASS') else assert(not ok,tostring(err));print('EXPECTED_FAILURE') end
'''

def _lua_provider():
    if 'SIMION_LUA_EXE' in os.environ:
        value=os.environ['SIMION_LUA_EXE']
        if not value: raise ValueError('explicit SIMION_LUA_EXE is empty')
        return value
    return shutil.which('lua') or shutil.which('lua5.1')


class NumericalBackgroundTests(unittest.TestCase):
    def test_explicit_bad_lua_provider_does_not_fallback(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'SIMION_LUA_EXE':'invalid-explicit-lua'}), patch('shutil.which') as fallback:
            self.assertEqual(_lua_provider(),'invalid-explicit-lua')
            fallback.assert_not_called()
        with patch.dict(os.environ, {'SIMION_LUA_EXE':''}), patch('shutil.which') as fallback:
            with self.assertRaisesRegex(ValueError,'explicit SIMION_LUA_EXE is empty'): _lua_provider()
            fallback.assert_not_called()

    def test_actual_builder_and_reopen_api(self):
        lua=_lua_provider()
        if not lua:self.skipTest('standalone Lua not available')
        build=native_resource_path('create_numerical_background.lua');reopen=native_resource_path('reopen_numerical_background.lua')
        for scenario in ('valid','metal','value','pitch'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);script=root/'harness.lua';script.write_text(HARNESS,encoding='utf8');path=root/'path.lua';path.write_text('return function(p)return p end',encoding='utf8')
                result=subprocess.run([lua,str(script),str(build),str(reopen),str(root/'background.pa'),str(path),scenario],cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30)
                self.assertEqual(result.returncode,0,result.stderr);self.assertIn('BACKGROUND_STUB=PASS' if scenario=='valid' else 'EXPECTED_FAILURE',result.stdout)
