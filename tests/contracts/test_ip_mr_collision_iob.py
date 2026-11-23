"""Five-slot IOB Lua readback against inert API doubles; no native claim."""
import copy
import json
import os
import shutil
import pathlib
import subprocess
import tempfile
import unittest
from msplatform.backends.simion.source import lua_value
from msplatform.backends.simion.resources import native_resource_path
from tests.contracts.test_dual_cone_iob import HARNESS

class CollisionIobTests(unittest.TestCase):
 def test_saved_iob_inert_build_reopen_and_refusals(self):
  lua=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
  if not lua:self.skipTest('standalone Lua not available')
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);seed=root/'seed.iob';seed.write_bytes(b'inert');out=root/'out.iob';control=root/'empty.fly2';control.write_text('particles{coordinates=0,}')
   names=['vacuum','rf','ip','analyzer','detector'];rows=[]
   for i,name in enumerate(names,1):
    pa=root/(name+'.pa');pa.write_bytes(b'inert');r=dict(role=name,instance_index=i,priority_number=i,path=str(pa),grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),rotation=[[1,0,0],[0,1,0],[0,0,1]],placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)])
    if i>1:
     side=pa.with_suffix('.pa-surf');side.write_bytes(b'inert');w=root/(name+'.csv');w.write_text('0,0,0,.25,nil,nil\n');r.update(fractional_surface=str(side),surface_witnesses=str(w))
    rows.append(r)
   spec=dict(schema_version=1,role='ip_mr_collision_iob_build',collision_roles=dict(zip(('background','rf','ip','analyzer','detector'),names)),instances=rows,seed_iob=str(seed),output_iob=str(out),empty_particle_control=str(control),bootstrap_paths=[str(root/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1,6)])
   code=(HARNESS.replace("electrode_numbers=spec.instances[1].response_ids}","electrode_numbers={},refinable=false}")
    .replace('function result:point(x,y,z)return 1,x==0 end',"function result:point(x,y,z)if (self.path or self.filename or ''):find('vacuum',1,true) then if failure=='background' then return 0,true end;return 0,false end;return 1,x==0 end\n function result:points()local i=-1;return function() i=i+1;if i<27 then return i%3,math.floor(i/3)%3,math.floor(i/9) end end end")
    .replace("function result:surface_info()if failure=='surface' then return .5,nil,nil end;return .25,nil,nil end", 'function result:surface_info()if (self.path or self.filename or ""):find("detector",1,true) and failure:find("empty",1,true) then if failure=="empty_nonzero" then return .5,nil,nil end;return nil,nil,nil end;if failure=="surface" then return .5,nil,nil end;return .25,nil,nil end')
    .replace('getmetatable(instances).__len=function()return 1 end','getmetatable(instances).__len=function()return #spec.instances end')
    .replace(" local row=spec.instances[1]\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[1]", " for i,row in ipairs(spec.instances) do\n local path=mode:match('^verify')and row.path or spec.bootstrap_paths[i]")
    .replace(' slots[1]=item\nend'," if failure=='foreign_path' and i==3 then item.pa.path=item.pa.path..'.foreign' end\n slots[i]=item\n end\nend")
    .replace("arg={arg[1],mode,arg[5]}","arg={arg[1],mode,arg[5]}")
    .replace("arg[3]..'/iob_core.lua'", "arg[3]..'/iob_core.lua'"))
   # Model a readable file whose end-position query overflows native Lua's offset.
   code = r'''local real_open=io.open
local emulate=arg[3]=='negative_seek'
io.open=function(path, mode)
 local f,err=real_open(path,mode)
 if f and emulate and mode=='rb' and path:match('rf%.pa$') then
  return {read=function(_, ...) return f:read(...) end,
          close=function(_) return f:close() end,
          seek=function(_) return -1 end}
 end
 return f,err
end
''' + code
   script=root/'harness.lua';script.write_text(code);request=root/'spec.lua'
   def run(mode,value,failure='valid'):
    request.write_text('return '+lua_value(value),encoding='utf8')
    return subprocess.run([str(lua),str(script),str(request),mode,failure,'unused',str(native_resource_path('iob_core.lua').parent)],cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30)
   for mode,marker in [('build_geometry','IP_MR_COLLISION_IOB=PASS'),('verify_geometry','IP_MR_COLLISION_IOB_REOPEN=PASS')]:
    p=run(mode,spec);self.assertEqual(p.returncode,0,p.stderr);self.assertIn(marker,p.stdout)
   result=run('verify_geometry',spec,'negative_seek');self.assertEqual(result.returncode,0,result.stderr)
   rf=pathlib.Path(rows[1]['path']);rf.write_bytes(b'')
   result=run('verify_geometry',spec,'negative_seek');self.assertNotEqual(result.returncode,0)
   self.assertIn('RF geometry input empty: path',result.stderr);self.assertIn(str(rf),result.stderr)
   rf.write_bytes(b'inert')
   bad=copy.deepcopy(spec);bad['instances'].pop(2)
   p=run('verify_geometry',bad);self.assertNotEqual(p.returncode,0);self.assertIn('requires five actual slots',p.stderr)
   bad=copy.deepcopy(spec);bad['instances'][0]['priority_number']=5
   p=run('verify_geometry',bad);self.assertNotEqual(p.returncode,0);self.assertIn('actual slot order differs',p.stderr)
   p=run('verify_geometry',spec,'foreign_path');self.assertNotEqual(p.returncode,0);self.assertIn('saved PA path differs',p.stderr)
   p=run('verify_geometry',spec,'background');self.assertNotEqual(p.returncode,0);self.assertIn('only zero vacuum nodes',p.stderr)
   p=run('verify_geometry',spec,'surface');self.assertNotEqual(p.returncode,0);self.assertIn('fractional surface readback differs',p.stderr)
   out.unlink(missing_ok=True);out.with_suffix('.fly2').unlink(missing_ok=True)
   detector=spec['instances'][4];Path=pathlib.Path
   state=root/'detector_surface_state.json';side=Path(detector['fractional_surface']);side.unlink()
   Path(detector['surface_witnesses']).write_text('0,0,0,nil,nil,nil\n')
   detector['surface_state']=str(state)
   proof=dict(schema_version=1,mode='empty',grid=[3,3,3],pitch=[1,1,1],scanned_nodes=27,offset_nodes=0)
   state.write_text(json.dumps(proof,separators=(',',':')))
   for mode in ('build_geometry','verify_geometry'):
    result=run(mode,spec,'empty');self.assertEqual(result.returncode,0,result.stderr)
   result=run('verify_geometry',spec,'empty_nonzero');self.assertNotEqual(result.returncode,0)
   proof['grid']=[4,3,3];state.write_text(json.dumps(proof,separators=(',',':')))
   result=run('verify_geometry',spec,'empty');self.assertNotEqual(result.returncode,0)
   proof['grid']=[3,3,3];proof['offset_nodes']=1;state.write_text(json.dumps(proof,separators=(',',':')))
   result=run('verify_geometry',spec,'empty');self.assertNotEqual(result.returncode,0)
   proof['offset_nodes']=0
   state.unlink();result=run('verify_geometry',spec,'empty');self.assertNotEqual(result.returncode,0)
   proof['grid']=[3,3,3];state.write_text(json.dumps(proof,separators=(',',':')));side.write_bytes(b'unexpected')
   result=run('verify_geometry',spec,'empty');self.assertNotEqual(result.returncode,0)
   detector.pop('surface_state');side.write_bytes(b'inert');Path(detector['surface_witnesses']).write_text('0,0,0,.25,nil,nil\n')
   bad=copy.deepcopy(spec);bad['collision_roles']['rf']='foreign'
   p=run('verify_geometry',bad);self.assertNotEqual(p.returncode,0);self.assertIn('actual slot order differs',p.stderr)
