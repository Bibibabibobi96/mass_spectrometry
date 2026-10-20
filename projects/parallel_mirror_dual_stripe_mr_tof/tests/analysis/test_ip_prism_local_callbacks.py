"""Execute the real local Lua program with callback-specific reserved permissions.

Uses a plain Lua interpreter, inert PA queries and synthetic callback states;
does not launch SIMION or claim a trajectory/field validation.
The strict load-setting restriction reproduces this workflow's headless
wb:load/save_reload failure, not a universal SIMION callback permission matrix.
"""
from __future__ import annotations

import csv
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROGRAM = Path(__file__).resolve().parents[2]/"simion/ip_prism_local.lua"
LUA = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"


HARNESS = r'''
local program,mode,expected_image=arg[1],arg[2],tonumber(arg[3])
local callback,request_count=nil,0
local splat=0
local settings={sim_trajectory_quality=-99,sim_trajectory_image_control=-99}
local env={segment={},sim_ions_count=(mode=='mixed' and 3 or 1),ion_number=1,
 ion_time_of_flight=0,ion_time_step=.1}
local pa={}
function pa:potential_vc(...) return .5 end
env.simion={workbench_program=function() end,wb={instances={{pa=pa}}}}
setmetatable(env,{
 __index=function(_,key)
  if key=='ion_splat' then return splat end
  if settings[key]~=nil then return settings[key] end
  return _G[key]
 end,
 __newindex=function(target,key,value)
  if settings[key]~=nil then
   assert(callback=='initialize_run',key..' is not writable in '..tostring(callback))
   settings[key]=value
  elseif key=='ion_splat' then
   assert(callback=='other_actions','ion_splat is not writable in '..tostring(callback))
   splat=value;request_count=request_count+1
  else rawset(target,key,value) end
 end
})
-- Check that an existing value cannot bypass the proxy's permission check.
callback='terminate'
assert(not pcall(function() env.ion_splat=1 end))
assert(splat==0 and request_count==0)
callback='load'
for key in pairs(settings) do assert(not pcall(function() env[key]=8 end)) end
callback=nil
local chunk=assert(loadfile(program));setfenv(chunk,env);chunk()
local function invoke(name)
 callback=name;if env.segment[name] then env.segment[name]() end;callback=nil
end
invoke('load')
assert(settings.sim_trajectory_quality==-99 and settings.sim_trajectory_image_control==-99,'IOB load must leave settings untouched')
local function particle(index,kind)
 env.ion_number=index;env.ion_time_of_flight=0;splat=0
 invoke('initialize')
 invoke('tstep_adjust');assert(env.ion_time_step==.005)
 local before=request_count
 if kind=='native' then
  env.ion_time_of_flight=.2
  env.ion_px_mm=.3;env.ion_py_mm=.4;env.ion_pz_mm=-.2
  splat=-4 -- vendor termination, not a user-program write
 elseif kind=='exit' then
  env.ion_time_of_flight=.5
  env.ion_px_mm=1.25;env.ion_py_mm=.5;env.ion_pz_mm=-2
  invoke('other_actions')
  assert(splat==1 and request_count==before+1,'exit must request splat in other_actions')
 elseif kind=='timeout' then
  env.ion_time_of_flight=2
  env.ion_pz_mm=-.5
  invoke('other_actions')
  assert(splat==1 and request_count==before+1,'timeout must request splat in other_actions')
 else error('unknown fixture mode') end
 invoke('terminate');invoke('terminate') -- duplicate callback must not duplicate terminal
 if kind=='native' then
  assert(splat==-4 and request_count==before,'native splat code must remain untouched')
 else assert(request_count==before+1,'terminate may not request another splat') end
end
for run=1,(mode=='mixed' and 2 or 1) do
 invoke('initialize_run')
 assert(settings.sim_trajectory_quality==8 and settings.sim_trajectory_image_control==expected_image,'run initialization must enforce Q8 and declared image control')
 if mode=='mixed' then
  particle(1,'native');particle(2,'exit');particle(3,'timeout')
 else particle(1,mode) end
 invoke('terminate_run')
end
print('CALLBACK_PERMISSIONS=PASS requests='..request_count)
print('RUN_SETTINGS=PASS Q='..settings.sim_trajectory_quality..' image='..settings.sim_trajectory_image_control)
'''


@unittest.skipUnless(Path(LUA).is_file(), "Plain Lua 5.1 interpreter required; never starts SIMION")
class LocalCallbackPermissionsTests(unittest.TestCase):
    def execute(self, mode: str, *, gui: bool = False) -> tuple[list[dict], list[dict], str]:
        with tempfile.TemporaryDirectory(prefix="ip_callback_permissions_") as directory:
            root = Path(directory)
            program = root/"local.lua"
            shutil.copyfile(PROGRAM, program)
            ids = [91, 7, 203] if mode == "mixed" else [91]
            sources = ",".join("{particle_id=%d,mass_amu=524,charge_state=1,t_us=100,x_mm=.25,y_mm=-.5,z_mm=0,vx_mm_us=1,vy_mm_us=2,vz_mm_us=-4}" % pid for pid in ids)
            (root/"case_config.lua").write_text("return {case_id='permissions',trajectory_quality=8,source_epoch_us=100,"
                "pitch_mm={.1,.2,.1},box_mm={0,-2,-3,2,2,1},source={"+sources+"},sample_interval_us=.01,"
                "maximum_step_us=.005,maximum_flight_us=1,observation_planes={{name='p1_exit',z_mm=-1}}"
                + (",frontend={schema_version=1,role='ip_prism_local_frontend',trajectory_image_control=0}" if gui else "")
                + "}\n", encoding="utf-8")
            harness = root/"harness.lua"
            harness.write_text(HARNESS, encoding="utf-8")
            result = subprocess.run([LUA, str(harness), str(program), mode, "0" if gui else "3"], cwd=root, capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            def read(name):
                with (root/name).open(encoding="utf-8", newline="") as stream:
                    return list(csv.DictReader(stream))
            return read("events.csv"), read("samples.csv"), result.stdout

    def test_load_rejects_settings_but_batch_run_initializes_q8_image3(self) -> None:
        _, _, output = self.execute("native")
        self.assertIn("RUN_SETTINGS=PASS Q=8 image=3", output)

    def test_gui_initializes_q8_image0_without_load_write(self) -> None:
        _, _, output = self.execute("native", gui=True)
        self.assertIn("RUN_SETTINGS=PASS Q=8 image=0", output)

    def test_native_termination_records_once_without_reserved_write(self) -> None:
        events, _, output = self.execute("native")
        terminal = [r for r in events if r["event"] == "terminal"]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]["reason"], "solver_stop")
        self.assertEqual(terminal[0]["particle_id"], "91")
        self.assertAlmostEqual(float(terminal[0]["t_us"]), 100.2)
        self.assertEqual(float(terminal[0]["z_mm"]), -.2)
        self.assertIn("CALLBACK_PERMISSIONS=PASS requests=0", output)

    def test_exit_requests_stop_only_in_other_actions_and_preserves_plane_interpolation(self) -> None:
        events, samples, output = self.execute("exit")
        terminal = [r for r in events if r["event"] == "terminal"]
        planes = [r for r in events if r["event"] == "plane"]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(len(planes), 1)
        self.assertEqual(terminal[0]["reason"], "reached_exit")
        for key, expected in (("t_us", 100.25), ("x_mm", .75), ("y_mm", 0.), ("z_mm", -1.)):
            self.assertEqual(float(terminal[0][key]), expected)
            self.assertEqual(terminal[0][key], planes[0][key])
        self.assertEqual(float(samples[-1]["t_us"]), 100.5)
        self.assertIn("CALLBACK_PERMISSIONS=PASS requests=1", output)

    def test_timeout_requests_stop_only_in_other_actions(self) -> None:
        events, _, output = self.execute("timeout")
        terminal = [r for r in events if r["event"] == "terminal"]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]["reason"], "timeout")
        self.assertEqual(float(terminal[0]["t_us"]), 102.)
        self.assertEqual(float(terminal[0]["z_mm"]), -.5)
        self.assertIn("CALLBACK_PERMISSIONS=PASS requests=1", output)

    def test_mixed_original_ids_and_repeated_run_keep_exactly_one_terminal_each(self) -> None:
        events, _, output = self.execute("mixed")
        births = [r for r in events if r["event"] == "birth"]
        terminal = [r for r in events if r["event"] == "terminal"]
        self.assertEqual([r["particle_id"] for r in births], ["91", "7", "203"])
        self.assertEqual([(r["particle_id"], r["reason"]) for r in terminal],
                         [("91", "solver_stop"), ("7", "reached_exit"), ("203", "timeout")])
        self.assertEqual(output.count("IP_PRISM_LOCAL_FLIGHT=PASS"), 2)
        self.assertIn("CALLBACK_PERMISSIONS=PASS requests=4", output)


if __name__ == "__main__":
    unittest.main()
