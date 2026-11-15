"""Explicit empty-surface converter tests using the existing inert PA double."""
import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from msplatform.backends.simion.resources import native_resource_path
from common.contracts.test_raw_collision_pa import HARNESS

class EmptySurfaceConversionTests(unittest.TestCase):
 def test_empty_and_rejections(self):
  lua=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua5.1')
  if not lua: self.fail('explicit Lua required')
  resource=native_resource_path('raw_collision_pa.lua')
  code=HARNESS.replace("surf['1,1,1']={.25,.5,.75}","if scenario=='nonzero' then surf['1,1,1']={.25,.5,.75} end")
  code=code.replace("local g=assert(io.open(path:gsub('%.pa$','.pa-surf'),'wb'));g:write('INERT-SURFACE-DOUBLE');g:close();return nil end", "return nil end")
  code=code.replace("arg={mode,source,output,path_resource}","arg={mode,source,output,path_resource,source:gsub('%.pa#$','.json')}")
  code=code[:code.index("if scenario=='source_vacuum'")]+"local ok,err=call('build');if not ok then print('EXPECTED_ERROR '..tostring(err));return end;local ok2,err2=call('verify');if not ok2 then error(err2) end;print('EMPTY_PAIR=PASS')\n"
  for scenario in ('empty','nonzero','missingproof','wronggrid','unexpected_companion','missingpresent'):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);src=root/'source.pa#';out=root/'output.pa';src.write_bytes(b'raw')
    state=dict(schema_version=1,mode='present' if scenario=='missingpresent' else 'empty',grid=[4,3,3] if scenario=='wronggrid' else [3,3,3],pitch=[.5,1,1.5],scanned_nodes=None if scenario=='missingpresent' else 36 if scenario=='wronggrid' else 27,offset_nodes=None if scenario=='missingpresent' else 0)
    if scenario!='missingproof':(root/'source.json').write_text(json.dumps(state,separators=(',',':')))
    if scenario=='unexpected_companion':(root/'source.pa-surf').write_bytes(b'unexpected')
    path=root/'path.lua';path.write_text('return function(path)return path end')
    script=root/'harness.lua';script.write_text(code)
    r=subprocess.run([str(lua),str(script),str(resource),str(src),str(out),str(path),scenario],cwd=root,capture_output=True,text=True,timeout=30)
    self.assertEqual(r.returncode,0,r.stderr)
    expected={'empty':'EMPTY_PAIR=PASS','nonzero':'physical metal and fractional surface evidence required','missingproof':'surface state missing','wronggrid':'surface state/grid differs','unexpected_companion':'empty source has unexpected companion','missingpresent':'required input missing'}[scenario]
    self.assertIn(expected,r.stdout)

if __name__=='__main__':unittest.main()
