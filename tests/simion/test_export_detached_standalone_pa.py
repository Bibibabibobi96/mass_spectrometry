from __future__ import annotations

import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

from msplatform.backends.simion.resources import native_resource_path


ROOT = Path(__file__).resolve().parent
EXPORTER = native_resource_path("export_detached_standalone_pa.lua")
SIMION = Path(os.environ.get("SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe"))
SOLVER_AUTHORIZED = os.environ.get("SIMION_SOLVER_TEST_AUTHORIZED") == "1"


class DetachedStandaloneStaticTest(unittest.TestCase):
    def test_contract_uses_new_object_and_rejects_native_responses(self) -> None:
        source = EXPORTER.read_text(encoding="utf-8")
        self.assertIn("simion.pas:open()", source)
        self.assertIn("output_pa:copy(source_pa)", source)
        self.assertIn("if output_pa.copy then", source)
        self.assertNotIn("pcall", source)
        self.assertIn("native PA-family response members are forbidden", source)
        self.assertIn("output must use the standalone .pa suffix", source)
        self.assertIn("surface offset transfer differs", source)
        self.assertNotIn(":refine", source)
        self.assertNotIn("source_pa:save(output)", source)


PORTABLE_HARNESS = r"""
local resource, source, output, scenario, workpoint = unpack(arg)
local nodes, surfaces, adjusted = {}, {}, 0
for z=0,1 do for y=0,1 do for x=0,1 do
  local key=x..','..y..','..z; nodes[key]={x+10*y+100*z,x==0}
end end end
if scenario=='enhanced' or scenario=='fallback' or scenario:match('^invalid') or scenario=='missing_surface' or scenario=='bad_transfer' or scenario=='workpoint' or scenario=='workpoint_fallback' then
  surfaces['0,0,0']={.25,nil,.75}; surfaces['1,1,1']={nil,.5,nil}
end
if scenario=='invalid' then surfaces['0,0,0']={1,nil,nil} end
if scenario=='invalid_zero' then surfaces['0,0,0']={0,nil,nil} end
if scenario=='invalid_nan' then surfaces['0,0,0']={0/0,nil,nil} end
if scenario=='bad_transfer' then surfaces['0,0,0']={.25,nil,.75} end
local function clone(t)local r={};for k,v in pairs(t) do r[k]=type(v)=='table' and clone(v) or v end;return r end
local function object(data, surf, output_object)
  local pa={nx=2,ny=2,nz=2,symmetry='3dplanar',dx_mm=.5,dy_mm=1,dz_mm=2,potential_type='electric',data=clone(data),surfaces=clone(surf)}
  function pa:size(x,y,z)self.nx=x;self.ny=y;self.nz=z end
  function pa:points()local i=-1;return function()i=i+1;if i>=8 then return nil end;return i%2,math.floor(i/2)%2,math.floor(i/4) end end
  function pa:point(x,y,z,...)local k=x..','..y..','..z;if select('#',...)>0 then local v,e=...;self.data[k]={v,e};return end;return unpack(assert(self.data[k])) end
  function pa:surface_info(x,y,z,...)local k=x..','..y..','..z;if select('#',...)>0 then local a,b,c=...;if scenario=='bad_transfer' then a=.5 end;self.surfaces[k]={a,b,c};return end;local v=self.surfaces[k] or {};return v[1],v[2],v[3] end
  function pa:fast_adjust(values) assert(not output_object);adjusted=adjusted+1;assert(adjusted==1);assert(values[1]==25 and values[2]==-12.5);self.data['0,0,0'][1]=values[1];nodes['0,0,0'][1]=values[1] end
  if output_object and scenario~='fallback' and scenario~='none_fallback' and scenario~='workpoint_fallback' then function pa:copy(other)self.data=clone(other.data) end end
  function pa:save(path)
    assert(output_object,'source must never be saved')
    if scenario=='workpoint' or scenario=='workpoint_fallback' then assert(adjusted==1,'workpoint not applied before save') end
    if scenario=='save_failure' then error('SIMULATED_SAVE_FAILURE') end
    for key,v in pairs(nodes) do assert(self.data[key][1]==v[1] and self.data[key][2]==v[2],'node mismatch') end
    for key,v in pairs(surfaces) do local a=self.surfaces[key] or {};for i=1,3 do assert(a[i]==v[i],'surface tuple mismatch') end end
    local f=assert(io.open(path,'wb'));f:write('INERT-OUTPUT');f:close()
    if next(surfaces) and scenario~='missing_surface' then local g=assert(io.open(path:gsub('%.pa$','.pa-surf'),'wb'));g:write('INERT-SURFACE');g:close() end
  end
  function pa:close()end
  return pa
end
simion={pas={}}
function simion.pas:close()end
function simion.pas:open(path)if path then assert(path==source);return object(nodes,surfaces,false) end;return object({}, {},true) end
arg={source,output,workpoint};local ok,err=pcall(assert(loadfile(resource)))
if scenario:match('^invalid') or scenario=='bad_transfer' or scenario=='missing_surface' or scenario=='save_failure' or scenario=='same' or scenario=='response' or scenario=='existing' or scenario=='companion' or scenario:match('^wp_invalid') or scenario=='wp_ordinary' or scenario=='wp_missing' then
  local expected=({invalid='invalid surface offset',invalid_zero='invalid surface offset',invalid_nan='invalid surface offset',bad_transfer='surface offset transfer differs',missing_surface='standalone surface companion was not written',save_failure='SIMULATED_SAVE_FAILURE',same='must not overwrite',response='ordinary .pa or controller-form .pa0',existing='output already exists',companion='output surface companion already exists',wp_invalid_empty='must be nonempty',wp_invalid_id='positive integer',wp_invalid_nan='must be finite',wp_invalid_extra='unknown fields',wp_invalid_type='native_voltages required',wp_ordinary='controller .pa0 source',wp_missing='cannot load frozen workpoint'})[scenario]
  assert(not ok and tostring(err):find(expected,1,true),tostring(err));print('EXPECTED_FAILURE');return
end
assert(ok,err);print('PORTABLE_SURFACE_TEST=PASS')
"""


class DetachedStandalonePortableTest(unittest.TestCase):
    def test_copy_fallback_surface_and_refusals(self) -> None:
        lua = os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
        if not lua:
            self.skipTest('standalone Lua unavailable')
        for scenario in ('none','none_fallback','empty_surface','enhanced','fallback','invalid','invalid_zero','invalid_nan','bad_transfer','missing_surface','save_failure','same','response','existing','companion','workpoint','workpoint_fallback','wp_invalid_empty','wp_invalid_id','wp_invalid_nan','wp_invalid_extra','wp_invalid_type','wp_ordinary','wp_missing'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source = root / ('source.pa1' if scenario == 'response' else 'source.pa' if scenario == 'wp_ordinary' else 'source.pa0')
                output = source if scenario == 'same' else root / 'output.pa'
                source.write_bytes(b'INERT-SOURCE')
                if scenario in ('empty_surface','enhanced','fallback','invalid','invalid_zero','invalid_nan','bad_transfer','missing_surface','workpoint','workpoint_fallback'):
                    (root / 'source.pa-surf').write_bytes(b'INERT-SOURCE-SURFACE')
                if scenario == 'existing': output.write_bytes(b'FOREIGN')
                if scenario == 'companion': (root / 'output.pa-surf').write_bytes(b'FOREIGN-SURFACE')
                workpoint = root / 'workpoint.lua'
                payloads = {'workpoint':'return {native_voltages={[1]=25,[2]=-12.5}}',
                            'workpoint_fallback':'return {native_voltages={[1]=25,[2]=-12.5}}',
                            'wp_invalid_empty':'return {native_voltages={}}',
                            'wp_invalid_id':'return {native_voltages={[1.5]=25}}',
                            'wp_invalid_nan':'return {native_voltages={[1]=0/0}}',
                            'wp_invalid_extra':'return {native_voltages={[1]=25},extra=true}',
                            'wp_invalid_type':'return {native_voltages=false}',
                            'wp_ordinary':'return {native_voltages={[1]=25,[2]=-12.5}}'}
                if scenario in payloads: workpoint.write_text(payloads[scenario], encoding='utf8')
                harness = root / 'harness.lua'; harness.write_text(PORTABLE_HARNESS, encoding='utf8')
                result = subprocess.run([lua, str(harness), str(EXPORTER), str(source), str(output), scenario, *([str(workpoint)] if scenario in payloads or scenario=='wp_missing' else [])], cwd=root,
                    capture_output=True, text=True, encoding='utf8', timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('PORTABLE_SURFACE_TEST=PASS' if scenario in ('none','none_fallback','empty_surface','enhanced','fallback','workpoint','workpoint_fallback') else 'EXPECTED_FAILURE',result.stdout)
                self.assertEqual(source.read_bytes(),b'INERT-SOURCE')
                if scenario.startswith('wp_') and scenario not in ('workpoint','workpoint_fallback'):
                    self.assertFalse(output.exists())
                if scenario=='existing': self.assertEqual(output.read_bytes(),b'FOREIGN')
                if scenario=='companion': self.assertEqual((root/'output.pa-surf').read_bytes(),b'FOREIGN-SURFACE')

BUILD_SOURCE = r"""
local root = assert(arg[1])
local sep = package.config:sub(1, 1)
local source = root .. sep .. 'source.pa0'
simion.pas:close()
local pa = assert(simion.pas:open())
pa:size(5, 4, 3)
pa.symmetry = '3dplanar'
pa.dx_mm, pa.dy_mm, pa.dz_mm = 0.5, 1.0, 2.0
for x, y, z in pa:points() do
  pa:point(x, y, z, x + 10*y + 100*z, x == 0 or x == 4)
end
pa:save(source)
pa:close()
print('DETACHED_SOURCE_BUILD=PASS')
"""


CHECK_OUTPUT = r"""
local output = assert(arg[1])
simion.pas:close()
local reopened = assert(simion.pas:open(output))
assert(#simion.pas == 1, 'detached output associated another PA')
assert(reopened.nx == 5 and reopened.ny == 4 and reopened.nz == 3)
assert(reopened.dx_mm == 0.5 and reopened.dy_mm == 1.0 and reopened.dz_mm == 2.0)
for x, y, z in reopened:points() do
  local potential, electrode = reopened:point(x, y, z)
  assert(potential == x + 10*y + 100*z, 'detached potential differs')
  assert(electrode == (x == 0 or x == 4), 'detached electrode flag differs')
end
reopened:close()
print('DETACHED_STANDALONE_REAL=PASS')
"""


@unittest.skipUnless(
    SIMION.is_file() and SOLVER_AUTHORIZED,
    "real SIMION regression requires the public host lease and explicit authorization",
)
class DetachedStandaloneAuthorizedTest(unittest.TestCase):
    def test_real_detachment_reopens_without_siblings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="simion_detached_pa_") as temporary:
            root = Path(temporary)
            builder = root / "build.lua"
            checker = root / "check.lua"
            builder.write_text(BUILD_SOURCE, encoding="utf-8")
            checker.write_text(CHECK_OUTPUT, encoding="utf-8")
            command = [str(SIMION), "--nogui", "--noprompt", "lua"]
            built = subprocess.run(
                [*command, str(builder), str(root)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
                timeout=60,
            )
            self.assertIn("DETACHED_SOURCE_BUILD=PASS", built.stdout)
            exported = subprocess.run(
                [*command, str(EXPORTER), str(root / "source.pa0"), str(root / "output.pa")],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
                timeout=60,
            )
            self.assertIn("DETACHED_STANDALONE_PA_EXPORT=PASS", exported.stdout)
            checked = subprocess.run(
                [*command, str(checker), str(root / "output.pa")],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
                timeout=60,
            )
            self.assertIn("DETACHED_STANDALONE_REAL=PASS", checked.stdout)
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["build.lua", "check.lua", "output.pa", "source.pa0"],
            )


if __name__ == "__main__":
    unittest.main()
