"""Exercise repeat-Fly callback state with standalone Lua and a nonphysical HS1 stub.

No SIMION API, electric field, collision physics, or physical trajectory is run.
The stub models HS1's private initialization/timestep lifetime and shared PRNG
usage solely to reveal stale run state in the production callback wrapper.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import lua_literal
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection


PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = PROJECT.parents[1]

LUA_HARNESS = r'''
local random_state, seeds, imports, reset_calls = 0, {}, 0, 0
local plot_calls={}
local open_lens_checks,return_to_lp_checks=0,0
function seed(value) random_state=value;seeds[#seeds+1]=value end
function rand()
  random_state=(random_state*1103515245+12345)%2147483648
  return random_state/2147483648
end
segment={}
simion={wb={instances={{}}},workbench_program=function() end}
simion.experimental={plot_line_segment=function(...)
  assert(sim_trajectory_image_control==0,'outline drawing must follow trajectory retention setup')
  plot_calls[#plot_calls+1]={...}
end}
if arg[2]=='missing-api' then simion.experimental=nil end
simion.import=function(path)
  assert(path:match('collision_hs1%.lua$'),'unexpected imported module')
  imports=imports+1
  local initialized,max_timestep=false,nil
  local hs={segment={}}
  test_hs=hs
  hs.reset_run_state=function()
    initialized=false;max_timestep=nil
    reset_calls=reset_calls+1
  end
  hs.segment.initialize=function()
    if not initialized then
      if _random_seed~=0 then seed(_random_seed-1) end
      if hs.init then hs.init() end
      initialized=true
    end
  end
  hs.segment.tstep_adjust=function()
    if max_timestep and ion_time_step>max_timestep then ion_time_step=max_timestep end
  end
  hs.segment.other_actions=function()
    hs.segment.initialize()
    -- Deliberately nonphysical deterministic mutation exercises PRNG replay.
    ion_vx_mm=ion_vx_mm+rand()*1e-4
    max_timestep=.004
  end
  hs.segment.terminate=function() end
  -- Official HS1 registers these callbacks at the sole top-level import;
  -- reimporting during Fly would replace the project's event wrappers.
  for key,value in pairs(hs.segment) do segment[key]=value end
  return hs
end
sim_ions_count=2
adj_elect={}
ion_run=0
sim_grouped=1
sim_trajectory_image_control=3
sim_rerun_flym=1
local runtime_path=assert(arg[1])
local directory=assert(runtime_path:match('^(.*[/\\])'))
assert(loadfile(runtime_path))()
assert(#plot_calls==0,'outline must not be drawn during module load')
local config=dofile(directory..'frozen_config.lua')
local sources=dofile(directory..'source_states.lua')
local function project(x,y,z)
  if config.coordinate_transform then return -z,x,9.8-y end
  return x,y,z
end
local function put_local(x,y,z,vx,vy,vz)
  ion_px_mm,ion_py_mm,ion_pz_mm=project(x,y,z)
  if config.coordinate_transform then ion_vx_mm,ion_vy_mm,ion_vz_mm=-vz,vx,-vy
  else ion_vx_mm,ion_vy_mm,ion_vz_mm=vx,vy,vz end
end
if arg[2]=='missing-api' then
  local ok,message=pcall(segment.initialize_run)
  assert(not ok and tostring(message):match('numerical exit outline requires simion.experimental.plot_line_segment'),
    'missing drawing API must fail with a clear capability error')
  print('RUNTIME_OUTLINE_API_REQUIRED_PASS')
  return
end
local function contents(path)
  local handle=assert(io.open(path,'r'))
  local value=handle:read('*a');handle:close();return value
end
local function fly_again()
  -- Emulate changing GUI defaults before each click; reproducibility must be
  -- imposed at the run boundary rather than relying on previous GUI state.
  sim_grouped=1;sim_trajectory_image_control=3;sim_rerun_flym=1
  segment.initialize_run()
  assert(random_state==config.numerics.seed,'drawing must not consume collision PRNG values')
  assert(_gas_mass_amu==config.baseline.gas.mass_amu and
    _temperature_k==config.baseline.gas.temperature_k and
    _sigma_m2==config.baseline.gas.cross_section_m2 and
    _random_seed==config.numerics.seed+1,'replay must restore frozen collision inputs')
  assert(sim_grouped==0,'initialize_run must enforce sequential particle order')
  assert(sim_trajectory_image_control==0,'initialize_run must view and retain trajectories')
  assert(sim_rerun_flym==0,'initialize_run must disable automatic reruns')
  local first_timestep
  for id=1,sim_ions_count do
    local source=sources[id]
    ion_number=id;ion_splat=0;ion_time_of_flight=0
    put_local(source.x,source.y,source.z,source.vx,source.vy,source.vz)
    segment.initialize()
    ion_time_step=1
    segment.tstep_adjust()
    if id==1 then first_timestep=ion_time_step end
    segment.other_actions()
    -- Prescribed callback positions deliberately cross the open end-lens bore
    -- and return. This nonphysical excursion tests boundary ownership only:
    -- x=LP end is not itself metal; native SIMION owns actual electrode hits.
    local capture_time=config.baseline.schedule.capture_end_us
    local lp_end=config.baseline.geometry.guide_length_mm+
      config.baseline.geometry.hp_length_mm+config.baseline.geometry.lp_length_mm
    local times={100,capture_time,capture_time+100,capture_time+200,
      config.baseline.schedule.transfer_end_us,
      config.baseline.schedule.extraction_start_us,
      config.baseline.schedule.extraction_start_us+1}
    local xs={35,120,lp_end+0.1,170,170,170,170}
    for index,t in ipairs(times) do
      ion_time_of_flight=t
      local y=index==#times and config.baseline.geometry.extraction_end_y_mm+0.2 or source.y
      put_local(xs[index],y,source.z,source.vx,source.vy,source.vz)
      if index==2 then assert(test_hs.pressure()==config.baseline.gas.hp_pressure_pa, "HP pressure must use local region") end
      if index==4 then assert(test_hs.pressure()==config.baseline.gas.lp_pressure_pa, "LP pressure must use local region") end
      segment.fast_adjust()
      segment.other_actions()
      if t==capture_time+100 then
        assert(ion_splat==0,'open end-lens bore crossing must not be labeled an electrode hit')
        open_lens_checks=open_lens_checks+1
      elseif t==capture_time+200 then
        assert(ion_splat==0,'particle must remain active when returning through the open lens')
        return_to_lp_checks=return_to_lp_checks+1
      end
    end
    segment.terminate()
  end
  segment.terminate_run()
  return contents(directory..'events.csv'),contents(directory..'samples.csv'),first_timestep
end
local events1,samples1,dt1=fly_again()
ion_run=1
-- Simulate stale GUI-adjustable state; initialize_run must restore the same
-- scientific inputs before the second seeded collision module initialization.
_gas_mass_amu=999;_temperature_k=999;_sigma_m2=1;_random_seed=1
local events2,samples2,dt2=fly_again()
assert(imports==1,'HS1 workbench module must be imported exactly once outside Fly')
assert(reset_calls==2,'each Fly must explicitly reset private HS1 lifecycle state')
assert(open_lens_checks==2*sim_ions_count and return_to_lp_checks==2*sim_ions_count,
  'both repeated runs must preserve the open-lens excursion and return for every particle')
assert(#plot_calls==8,'each Fly must draw exactly four numerical exit edges')
local geom,projection=config.baseline.geometry,config.native_projection
local x0=geom.guide_length_mm+geom.hp_length_mm
local x1=x0+geom.lp_length_mm
local y=geom.extraction_end_y_mm
local z0,z1=projection.origin_mm[3],projection.maximum_mm[3]
local expected_edges={{x0,y,z0,x1,y,z0},{x1,y,z0,x1,y,z1},
  {x1,y,z1,x0,y,z1},{x0,y,z1,x0,y,z0}}
for index,call in ipairs(plot_calls) do
  local edge=expected_edges[(index-1)%4+1]
  local a,b,c=project(edge[1],edge[2],edge[3])
  local d,e,f=project(edge[4],edge[5],edge[6])
  local expected={a,b,c,d,e,f}
  for axis=1,6 do assert(call[axis]==expected[axis],'outline edge must use frozen geometry') end
  assert(#call==11 and call[7]==0 and call[8]==0 and call[9]==12 and call[10]==12 and call[11]==false,
    'outline must use zero drawing height, color 12, and no particle marks')
end
assert(events1==events2,'repeat Fly must reset seen/done/previous and collision PRNG')
assert(samples1==samples2,'repeat Fly must reset sample timeline')
assert(dt1==dt2,'repeat Fly must reset HS1 private max_timestep')
assert(#seeds>=2 and seeds[1]==config.numerics.seed and
  seeds[#seeds]==config.numerics.seed,'each run must initialize the declared PRNG seed')
local _,source_count=events2:gsub('source,','')
local _,terminal_count=events2:gsub('terminal,','')
assert(source_count==sim_ions_count and terminal_count==sim_ions_count,
  'every replay must emit full source and terminal identities')
-- Independent boundary checks use project coordinates but local acceptance rules.
segment.initialize_run()
ion_number=1;ion_time_of_flight=1;ion_splat=0
put_local(120,2.1,0,1,0,0)
assert(test_hs.pressure()==0,'outside local bore has no gas')
segment.other_actions()
assert(ion_splat==1,'local radial escape must terminate after project rotation')
segment.terminate_run()
assert(contents(directory..'events.csv'):match('radial_escape'),'local boundary reason must survive rotation')
print('RUNTIME_REPLAY_PASS imports='..imports..' seeds='..#seeds)
'''


class RuntimeReplayTests(unittest.TestCase):
    """One loaded production runtime must replay deterministically twice."""

    def run_runtime_fixture(self, mode: str) -> str:
        """Run isolated callback contracts without a vendor application or fields."""
        executable = os.environ.get("SIMION_LUA_EXE") or shutil.which("lua")
        if executable is None:
            installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "SIMION-2020/lua.exe"
            if installed.is_file():
                executable = str(installed)
        if executable is None:
            self.skipTest("Standalone Lua unavailable; set SIMION_LUA_EXE for replay contract test")
        config = {name: json.loads((PROJECT / "config" / f"{name}.json").read_text(encoding="utf-8"))
                  for name in ("baseline", "numerics", "source", "acceptance", "native_operating_point")}
        if mode == "transformed":
            config["coordinate_transform"] = json.loads((PROJECT / "config/coordinate_transform.json").read_text(encoding="utf-8"))
        config["native_projection"] = native_projection(config["baseline"], config["numerics"])
        with tempfile.TemporaryDirectory(prefix="ion_processor_replay_test_") as temporary:
            folder = Path(temporary)
            for name in ("runtime.lua", "native_drive.lua"):
                shutil.copyfile(PROJECT / "simion" / name, folder / name)
            shutil.copyfile(REPOSITORY / "common/multipole/simion_rf_drive.lua",
                            folder / "simion_rf_drive.lua")
            (folder / "frozen_config.lua").write_text("return " + lua_literal(config), encoding="utf-8")
            sources = [{"particle_id": index, "t": 0, "x": 1, "y": index * 0.01,
                        "z": 0, "vx": 1, "vy": 0, "vz": 0, "ke": 5} for index in (1, 2)]
            (folder / "source_states.lua").write_text("return " + lua_literal(sources), encoding="utf-8")
            (folder / "replay.lua").write_text(LUA_HARNESS, encoding="utf-8")
            unrelated = folder / "unrelated_gui_cwd"
            unrelated.mkdir()
            result = subprocess.run([executable, str(folder / "replay.lua"), str(folder / "runtime.lua"), mode], cwd=unrelated,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                                    check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_repeated_initialize_run_resets_state_and_draws_numerical_outline(self) -> None:
        self.assertIn("RUNTIME_REPLAY_PASS", self.run_runtime_fixture("replay"))

    def test_project_rotation_preserves_local_regions_boundaries_and_replay(self) -> None:
        self.assertIn("RUNTIME_REPLAY_PASS", self.run_runtime_fixture("transformed"))

    def test_missing_outline_api_fails_with_clear_capability_error(self) -> None:
        self.assertIn("RUNTIME_OUTLINE_API_REQUIRED_PASS", self.run_runtime_fixture("missing-api"))


if __name__ == "__main__":
    unittest.main()
