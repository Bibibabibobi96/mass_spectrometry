"""Ordinary-Lua passive audit contracts and independent quadrature references."""
from __future__ import annotations

import csv
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]

HARNESS = r'''
local module=assert(loadfile(arg[1]))()
local mode=arg[3]
function rand() error('passive field audit must not consume random numbers') end
function seed() error('passive field audit must not seed random numbers') end
ion_time_step=.123;ion_time_of_flight=456;ion_px_mm=7;ion_vx_mm=8
local c={baseline={geometry={lp_center_mm=2},clock={epoch_us=10}},
 native_projection={grid_mm=1,origin_mm={0,0,0},electrode_ids={}},
 native_timing={primary_quench_us=0,side_quench_us=2,pulse_start_us=2}}
for id=1,15 do c.native_projection.electrode_ids[id]=id end
local calls,onehots,drive_calls=0,{},{}
local pa={inside_vc=function(self,x,y,z)
 assert(x==x and y==y and z==z)
 return mode~='outside'
end}
function pa:field_vc(x,y,z,voltages)
 calls=calls+1
 assert(#voltages==15,'complete explicit voltage vector required')
 local total,active=0,0
 for id=1,15 do
  assert(type(voltages[id])=='number')
  total=total+id*voltages[id]
  if voltages[id]~=0 then active=active+1 end
 end
 if active==1 then
  for id=1,15 do if voltages[id]==1 then onehots[id]=true end end
 end
 if mode=='reconstruction-error' and active>1 then total=total+1 end
 if mode=='hermite' then total=total*x end
 return total,2*total,-3*total
end
local drive={voltages=function(config,t,rf)
 assert(rf==10+t,'RF must use the absolute frozen clock')
 drive_calls[#drive_calls+1]=t
 local v={};for id=1,15 do v[id]=0 end
 if mode=='quartic' then v[1]=t^4
 elseif mode=='switch' then v[1]=t<.5 and 1 or 2
 elseif mode=='reconstruction-error' then v[1]=1;v[2]=1
 else v[1]=2;v[2]=-1 end
 if mode=='hermite' then v[1]=1;v[2]=0 end
 return v
end}
local rf={differential_at=function(t) return t end}
if mode=='switch' then c.native_timing.side_quench_us=.5;c.native_timing.pulse_start_us=.5 end
if mode=='rotated' then
 c.native_projection.grid_mm=.1
 c.coordinate_transform={rotation={{0,0,-1},{1,0,0},{0,-1,0}},translation_mm={0,0,9.8}}
end
local function state(t,x,y,z,vx,vy,vz)
 return {t=t,x=x,y=y,z=z,vx=vx,vy=vy,vz=vz}
end
if mode=='outside' then
 local ok,message=pcall(module.new,c,pa,drive,rf,arg[2])
 assert(not ok and tostring(message):match('outside native PA'))
 print('OUTSIDE_REFUSED');return
end
local audit=module.new(c,pa,drive,rf,arg[2])
assert(calls==15,'pre-Fly warmup must query all response bases')
for id=1,15 do assert(onehots[id],'missing warmed electrode '..id) end
local pre=state(0,0,0,0,0,0,0)
local post=state(0,0,0,0,.01,.02,.03)
audit:observe(1,pre,post,.2)
assert(pre.vx==0 and post.vx==.01,'observation must not mutate its states')
if mode=='switch' then
 local p=state(.5,1,0,0,.1,.2,.3)
 audit:observe(1,p,p,.2)
 local q=state(1,2,0,0,.2,.4,.6)
 audit:observe(1,q,q,0)
elseif mode=='hermite' then
 -- Independent exact trajectory x=t^3; endpoint derivatives 0 and 3.
 -- Reset the anchor to zero velocity in a new particle to test cubic path.
 local zero=state(0,0,0,0,0,0,0)
 audit:observe(2,zero,zero,0)
 local last=state(1,1,0,0,3,0,0)
 audit:observe(2,last,last,0)
else
 local before=state(1,1,0,0,.1,.2,.3)
 local after=state(1,1,0,0,.13,.24,.35)
 audit:observe(1,before,after,0)
 assert(before.vx==.1 and after.vx==.13)
end
audit:close();audit:close()
assert(ion_time_step==.123 and ion_time_of_flight==456 and ion_px_mm==7 and ion_vx_mm==8,
 'passive field audit must not modify reserved particle state or timestep')
assert(module.left_limit(.5)<.5 and module.left_limit(.5)+2^-54==.5,
 'left voltage evaluation must use the immediately preceding binary64')
print('PASSIVE_FORCE_AUDIT_PASS')
'''


class ExtractionForceAuditTests(unittest.TestCase):
    def run_case(self, mode: str) -> tuple[list[dict], list[dict]]:
        executable = os.environ.get("SIMION_LUA_EXE") or shutil.which("lua")
        if executable is None:
            installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
            executable = str(installed) if installed.is_file() else None
        if executable is None:
            self.skipTest("ordinary Lua unavailable; no SIMION solver process is used")
        with tempfile.TemporaryDirectory(prefix="ip_force_audit_") as directory:
            folder = Path(directory)
            script = folder / "audit_test.lua"
            script.write_text(HARNESS, encoding="utf-8")
            result = subprocess.run([executable, str(script), str(PROJECT / "simion/extraction_force_audit.lua"),
                                     folder.as_posix()+"/", mode], cwd=folder, capture_output=True,
                                    text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if mode == "outside":
                self.assertIn("OUTSIDE_REFUSED", result.stdout)
                return [], []
            self.assertIn("PASSIVE_FORCE_AUDIT_PASS", result.stdout)
            tables = []
            for name in ("extraction_steps.csv", "extraction_impulses.csv"):
                with (folder / name).open(newline="", encoding="utf-8") as stream:
                    tables.append(list(csv.DictReader(stream)))
            return tables[0], tables[1]

    def test_exact_step_velocity_and_collision_jumps_are_separate(self):
        steps, impulses = self.run_case("constant")
        self.assertEqual(len(steps), 2)
        self.assertEqual(len(impulses), 30)
        self.assertEqual(steps[0]["start_t_us"], steps[0]["end_t_us"])
        row = steps[1]
        self.assertAlmostEqual(float(row["end_pre_vx_mm_us"])-float(row["start_post_vx_mm_us"]), .09)
        self.assertAlmostEqual(float(row["end_post_vx_mm_us"])-float(row["end_pre_vx_mm_us"]), .03)
        self.assertEqual(float(row["pressure_pa"]), 0)
        by_id = {int(r["electrode_id"]):r for r in impulses if r["step_index"] == "2"}
        self.assertAlmostEqual(float(by_id[1]["integral_ex_v_us_per_mm"]), 2)
        self.assertAlmostEqual(float(by_id[2]["integral_ex_v_us_per_mm"]), -2)
        self.assertAlmostEqual(float(by_id[15]["unit_integral_ex_us_per_mm"]), 15)
        self.assertTrue(all(float(r["max_reconstruction_error_v_per_mm"]) == 0 for r in impulses))

    def test_quartic_time_response_has_independent_simpson_difference(self):
        _, impulses = self.run_case("quartic")
        row = next(r for r in impulses if r["step_index"] == "2" and r["electrode_id"] == "1")
        # Integral t^4 is 1/5. Composite Simpson errors are h^4-scaled:
        # fine error=1/1920; coarse error=1/120.
        self.assertAlmostEqual(float(row["integral_ex_v_us_per_mm"]), .2+1/1920)
        self.assertAlmostEqual(float(row["fine_minus_coarse_ex_v_us_per_mm"]), -1/128)
        self.assertAlmostEqual(float(row["unit_integral_ex_us_per_mm"]), 1)

    def test_cubic_hermite_path_with_linear_field_integrates_exactly(self):
        _, impulses = self.run_case("hermite")
        row = next(r for r in impulses if r["particle_id"] == "2" and r["step_index"] == "2" and r["electrode_id"] == "1")
        self.assertAlmostEqual(float(row["integral_ex_v_us_per_mm"]), .25)
        self.assertAlmostEqual(float(row["fine_minus_coarse_ex_v_us_per_mm"]), 0)

    def test_pulse_endpoint_uses_left_voltage_and_next_interval_right_voltage(self):
        _, impulses = self.run_case("switch")
        active = [r for r in impulses if r["electrode_id"] == "1"]
        self.assertAlmostEqual(float(active[1]["integral_ex_v_us_per_mm"]), .5)
        self.assertAlmostEqual(float(active[2]["integral_ex_v_us_per_mm"]), 1)

    def test_world_rotation_and_gu_to_mm_conversion(self):
        _, impulses = self.run_case("rotated")
        row = next(r for r in impulses if r["step_index"] == "2" and r["electrode_id"] == "1")
        self.assertAlmostEqual(float(row["integral_ex_v_us_per_mm"]), 60)
        self.assertAlmostEqual(float(row["integral_ey_v_us_per_mm"]), 20)
        self.assertAlmostEqual(float(row["integral_ez_v_us_per_mm"]), -40)

    def test_reconstruction_error_is_reported_without_redistributing_integrals(self):
        _, impulses = self.run_case("reconstruction-error")
        rows = [r for r in impulses if r["step_index"] == "2"]
        self.assertTrue(all(float(r["max_reconstruction_error_v_per_mm"]) == 3 for r in rows))
        self.assertAlmostEqual(sum(float(r["integral_ex_v_us_per_mm"]) for r in rows), 3)

    def test_outside_pa_is_not_silently_zero_filled(self):
        self.run_case("outside")


if __name__ == "__main__":
    unittest.main()
