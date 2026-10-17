"""Official in-memory PA crop consumer tests; ordinary Lua, no native PA/Fly."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[4]
ADAPTER = REPO / "projects/parallel_mirror_dual_stripe_mr_tof/simion/scalar_field_adapter.lua"
LUA = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"


@unittest.skipUnless(LUA.is_file(), "standalone vendor Lua unavailable")
class NativeMemoryConsumerCropTest(unittest.TestCase):
    def test_full_and_cropped_values_gradients_mirror_halo_fractional_and_reuse(self):
        fixture = r'''
local items={};local opens,crops=0,0
local function make_pa(path)
 local p={path=path,symmetry='3dplanar[x]',nx=51,ny=21,nz=21,dx_mm=.04,dy_mm=.2,dz_mm=.02}
 local fractional={x=.25,y=.5,z=.75}
 local factor=path:find('base') and 2 or 1
 function p:potential(x,y,z)
  assert(x>=0 and x<self.nx and y>=0 and y<self.ny and z>=0 and z<self.nz)
  return factor*(x*x+y*y+z*z)
 end
 function p:potential_vc(x,y,z)return factor*(x*x+y*y+z*z) end
 function p:field_vc(x,y,z)return -2*factor*x,-2*factor*y,-2*factor*z end
 function p:inside_vc(x,y,z)return math.abs(x)<self.nx and y>=0 and y<self.ny and z>=0 and z<self.nz end
 function p:surface_info()return fractional.x,fractional.y,fractional.z end
 function p:save()error('no source or consumer save permitted')end
 function p:refine()error('consumer crop must not Refine')end
 function p:electrode()error('consumer must not change electrode flags')end
 function p:close()error('shared PA must not close')end
 function p:crop(x,y,z,nx,ny,nz,persist)
  assert(x==0 and y==0 and z==0 and persist==false)
  assert(nx==32 and ny==20 and nz==20 and self.nx==51)
  crops=crops+1;self.nx=nx+1;self.ny=ny+1;self.nz=nz+1
 end
 return p
end
local container=newproxy(true);local mt=getmetatable(container)
mt.__len=function()return #items end
mt.__index=function(_,k)
 if k=='open' then return function(_,path)opens=opens+1;local p=make_pa(path);items[#items+1]=p;return p end end
 return items[k]
end
simion={pas=container,wb={instances={}},early_access=function()end,
 experimental={make_efield_adjust=function(f)return f end}}
local function level(path)
 return {mode='native_static_pa',scalar_pa=path,origin_mm={0,-2,90},pitch_mm={.04,.2,.02},dimensions={51,21,21},symmetry='x'}
end
local b=level('C:/sealed/base.pa');local w=level('C:/sealed/mirror.pa')
w.name='positive_integer_grid_a';w.active_box_mm={{-1,1},{-1,1},{90.1,90.3}};b.refinement_windows={w}
local apply=assert(loadfile(arg[1]))()
local full=apply(b,'raw_sample')
assert(opens==2 and crops==0)
local points={{-1,0,90.2},{0,0,90.2},{1,0,90.2},{-.99,.5,90.25},{.99,-.5,90.15}}
local expected={}
for i,p in ipairs(points) do expected[i]={full(unpack(p))} end
assert(expected[3][2]==-1250, "mirror route or axis scaling differs from quadratic oracle")
local fallback={full(1.2,0,90.2)}
assert(fallback[2]==-3000, "outside-active route must remain the base field")
local node_before=items[2]:potential(26,10,10)
local fractional_before={items[2]:surface_info(26,10,10)}
w.memory_consumer_crop={source_dimensions={51,21,21},consumer_dimensions={33,21,21},start_grid={0,0,0},width_grid={32,20,20}}
local cropped=apply(b,'raw_sample')
assert(opens==2 and crops==1 and items[2].nx==33)
assert(items[2].path=='C:/sealed/mirror.pa' and items[2]:potential(26,10,10)==node_before)
local fractional_after={items[2]:surface_info(26,10,10)}
for i=1,3 do assert(fractional_before[i]==fractional_after[i])end
for i,p in ipairs(points) do
 local actual={cropped(unpack(p))}
 for j=1,4 do assert(actual[j]==expected[i][j], 'full/crop V or gradient differs')end
end
assert(expected[1][2]==-expected[3][2] and expected[1][1]==expected[3][1], 'native x mirror changed')
local routed_fallback={cropped(1.2,0,90.2)}
for j=1,4 do assert(routed_fallback[j]==fallback[j])end
local again=apply(b,'raw_sample')
assert(opens==2 and crops==1, 'second factory must reuse cropped PA without another open/crop')
local actual={again(1,0,90.2)}
for j=1,4 do assert(actual[j]==expected[3][j])end
local original_crop=w.memory_consumer_crop
w.memory_consumer_crop={source_dimensions={51,21,21},consumer_dimensions={25,21,21},start_grid={0,0,0},width_grid={24,20,20}}
assert(not pcall(apply,b,'raw_sample'), 'cropped active box without derivative halo must fail')
w.memory_consumer_crop=original_crop
original_crop.start_grid[1]=1
assert(not pcall(apply,b,'raw_sample'), 'crop must retain original world origin')
original_crop.start_grid[1]=0
w.name='other_window'
assert(not pcall(apply,b,'raw_sample'), 'only explicit frozen mirror windows may use crop')
w.name='positive_integer_grid_a'
simion.wb.instances={{pa=items[2]}}
assert(not pcall(apply,b,'raw_sample'), 'must reject any WB-owned mirror PA')
simion.wb.instances={}
print('NATIVE_MEMORY_CONSUMER_CROP_PASS source_file_unchanged=true no_save=true no_refine=true')
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "consumer_crop.lua"
            script.write_text(fixture, encoding="utf-8", newline="\n")
            result = subprocess.run([str(LUA), str(script), str(ADAPTER)], cwd=REPO,
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("NATIVE_MEMORY_CONSUMER_CROP_PASS", result.stdout)
            self.assertIn("performed=true source_nx=51 consumer_nx=33 save=false refine=false", result.stdout)
            self.assertIn("performed=false source_nx=51 consumer_nx=33 save=false refine=false", result.stdout)


if __name__ == "__main__":
    unittest.main()
