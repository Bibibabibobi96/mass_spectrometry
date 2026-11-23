"""Portable proof that raw-geometry empty surface requires exhaustive native reads."""
import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from msplatform.backends.simion.resources import native_resource_path

class EmptySurfaceProducerTests(unittest.TestCase):
    def test_present_empty_and_bad_missing(self):
        lua=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1') or 'C:/Program Files/SIMION-2020/lua.exe'
        if not lua: self.fail('explicit standalone Lua required')
        source=native_resource_path('build_frontend_geometry.lua')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'build.lua').write_bytes(source.read_bytes())
            (p/'gem2pa_geometry.lua').write_text('return {gem2pa=function(g,o) local f=assert(io.open(o,"wb")); f:write("pa");f:close() end}')
            script=p/'test.lua';script.write_text('''
local mode=arg[1];local root=arg[2];local surf=root..'/test.pa-surf'
if mode=='present' then local f=assert(io.open(surf,'wb'));f:write('real-surface');f:close() end
local pa={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,potential_type='electric'}
function pa:point(x,y,z) return x==1 and y==1 and z==1 and 7 or 0,x==1 and y==1 and z==1 end
function pa:surface_info(x,y,z) if mode=='bad' and x==1 and y==1 and z==1 then return .5,nil,nil end return nil,nil,nil end
function pa:points() local n=-1;return function() n=n+1;if n<27 then return n%3,math.floor(n/3)%3,math.floor(n/9) end end end
function pa:close() end
simion={pas={close=function() end,open=function() return pa end}}
local f=assert(io.open(root..'/spec.lua','wb'))
f:write('return {schema_version=1,role="simion_frontend_raw_geometry",domain_id="x",gem="'..root..'/x.gem",output="'..root..'/test.pa#",grid={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1},physical_samples={{label="m",gu={1,1,1},electrode_id=7}},fractional_surface="'..surf..'",surface_witnesses="'..root..'/w.csv",surface_state="'..root..'/state.json"}')
f:close();arg={root..'/spec.lua'};assert(loadfile(root..'/build.lua'))()
''')
            for mode in ('present','empty','bad'):
                for name in ('test.pa#','test.pa-surf','w.csv','state.json'):(p/name).unlink(missing_ok=True)
                r=subprocess.run([str(lua),str(script),mode,str(p).replace('\\','/')],cwd=p,capture_output=True,text=True,timeout=30)
                with self.subTest(mode=mode):
                    self.assertEqual(r.returncode==0,mode!='bad',r.stderr)
                    if mode!='bad':
                        state=json.loads((p/'state.json').read_text());self.assertEqual(state['mode'],mode)
                        self.assertEqual(state['scanned_nodes'],27 if mode=='empty' else None)
                        self.assertEqual(state['offset_nodes'],0 if mode=='empty' else None)
                    else:self.assertFalse((p/'state.json').exists())

if __name__ == '__main__': unittest.main()
