"""Exercise repeat-Fly callback state with standalone Lua and a nonphysical HS1 stub.

No SIMION API, electric field, collision physics, or physical trajectory is run.
SIMION adjustable declarations are removed only for this nonphysical fixture;
this test cannot prove vendor lexical binding. The stub models HS1's private initialization/timestep lifetime and shared PRNG
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
local expected_image_control=arg[2]=='csv-batch' and 3 or 0
local open_lens_checks,return_to_lp_checks=0,0
function seed(value) random_state=value;seeds[#seeds+1]=value end
function rand()
  random_state=(random_state*1103515245+12345)%2147483648
  return random_state/2147483648
end
segment={}
simion={wb={instances={{}}},workbench_program=function() end}
local force_queries=0
simion.wb.instances[1].pa={
 inside_vc=function(self,x,y,z)
  assert(x==x and y==y and z==z,'force query coordinates must be finite')
  return true -- Inert PA covers prescribed, deliberately nonphysical excursions.
 end,
 field_vc=function(self,x,y,z,voltages)
  assert(#voltages==15,'runtime must pass the complete native voltage vector')
  force_queries=force_queries+1
  local total=0;for id=1,15 do total=total+voltages[id]*id end
  return total,2*total,-total
 end,
}
simion.experimental={plot_line_segment=function(...)
  assert(sim_trajectory_image_control==expected_image_control,'outline follows frozen output policy')
  plot_calls[#plot_calls+1]={...}
end}
if arg[2]=='missing-api' then simion.experimental=nil end
simion.import=function(path)
  assert(path:match('collision_hs1%.lua$'),'unexpected imported module')
  imports=imports+1
  local initialized,max_timestep=false,nil
  local hs={segment={}}
  hs.bound_parameters=function()
    return {gas_mass_amu=arg[2]=='bound-mismatch' and 4 or _gas_mass_amu,
      temperature_k=_temperature_k,pressure_pa=_pressure_pa,sigma_m2=_sigma_m2,
      mean_free_path_mm=_mean_free_path_mm,steps_per_mfp=_steps_per_MFP,
      random_seed=_random_seed,mark_collisions=_mark_collisions,trace_level=_trace_level}
  end
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
if arg[2]=='bound-mismatch' then
  local ok,message=pcall(segment.initialize_run)
  assert(not ok and tostring(message):match('HS1 binding mismatch: gas_mass_amu'),
    'module readback mismatch must stop before particle integration')
  local receipt=assert(io.open(directory..'hs1_bound_parameters.csv'))
  local text=receipt:read('*a');receipt:close()
  assert(text:match('before_init,4,'),'retain observed binding before failing closed')
  print('RUNTIME_HS1_MISMATCH_REFUSED_PASS');return
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
if arg[2]=='injected' then
  segment.initialize_run()
  for id=1,sim_ions_count do
    local s=sources[id]
    local original=config.injected_source.particle_ids[id]
    ion_number=id;ion_splat=0;ion_time_of_flight=s.t
    put_local(s.x,s.y,s.z,s.vx,s.vy,s.vz)
    segment.initialize();ion_time_step=1;segment.tstep_adjust()
    assert(random_state==config.numerics.seed+original-1,'upstream RNG must use original sparse ID')
    segment.fast_adjust();segment.other_actions()
    ion_time_of_flight=s.t+1
    segment.terminate()
  end
  segment.terminate_run()
  local events=contents(directory..'events.csv')
  local seeds_csv=contents(directory..'collision_rng_seeds.csv')
  for id,s in ipairs(sources) do
    local original=config.injected_source.particle_ids[id]
    assert(events:match('source,'..original..',none,'..tostring(s.t)),
      'source event must preserve original ID and absolute arrival')
    assert(seeds_csv:match(string.format('%d,%d,%d',original,original,config.numerics.seed+original-1)),
      'seed receipt must retain original identity without batch rebasing')
  end
  print('RUNTIME_INJECTED_ID_ARRIVAL_PASS');return
end
if arg[2]=='upstream-source' then
  segment.initialize_run()
  assert(force_queries>=15,'all native response bases must be observed before Fly')
  local origin=config.native_projection.origin_mm[1]
  local upstream=config.numerical_boundaries.upstream_exit_x_mm
  local function inside_callback(x)
    -- Outside the native PA no segment is invoked, including terminate.
    assert(x>origin,'fixture must never supply an outside-PA callback')
    segment.other_actions()
  end
  for id=1,sim_ions_count do
    local source=sources[id]
    ion_number=id;ion_splat=0;ion_time_of_flight=0
    assert(source.x<0 and source.x>upstream,'fixture must start upstream of guide inside PA')
    put_local(source.x,source.y,source.z,source.vx,source.vy,source.vz)
    segment.initialize();inside_callback(source.x)
    assert(ion_splat==0,'valid upstream source must survive its first callback')
    put_local(upstream,0,0,1,0,0)
    ion_time_step=0.002;segment.tstep_adjust()
    assert(ion_time_step>0,'on-plane inward travel must not create a zero timestep')
    inside_callback(upstream)
    assert(ion_splat==0,'inward motion on the plane must remain alive')
    ion_time_of_flight=1
    put_local(upstream+0.001,0,0,-1,0,0);inside_callback(upstream+0.001)
    ion_time_step=1;segment.tstep_adjust()
    assert(ion_time_step>0 and ion_time_step<=0.001000001,
      'negative flight must land on the internal observation before leaving PA')
    ion_time_of_flight=ion_time_of_flight+ion_time_step
    local endpoint=id==1 and upstream or upstream-config.native_projection.grid_mm/2
    put_local(endpoint,0,0,-1,0,0);inside_callback(endpoint)
    assert(ion_splat==1,'arrival exactly on the inside observation must terminate')
    -- No synthetic terminate callback. The next ion must activate cleanly.
  end
  segment.terminate_run()
  local _,count=contents(directory..'events.csv'):gsub('terminal,%d+,backward_escape,','')
  assert(count==sim_ions_count,'record one numerical backward escape per particle')
  print('RUNTIME_UPSTREAM_SOURCE_PASS');return
end
if arg[2]=='unfinished-interleaving' then
  segment.initialize_run()
  ion_number=1;ion_splat=0;ion_time_of_flight=0
  put_local(1,0,0,1,0,0);segment.initialize();segment.other_actions()
  ion_number=2
  local ok,message=pcall(segment.tstep_adjust)
  assert(not ok and tostring(message):match('unfinished particle interleaving'),
    'missing terminal must remain a hard error, never silently reseed')
  print('RUNTIME_UNFINISHED_INTERLEAVING_REFUSED_PASS');return
end
local function fly_again(preinitialize)
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
  assert(sim_trajectory_image_control==expected_image_control,'initialize_run must restore frozen output policy')
  assert(sim_rerun_flym==0,'initialize_run must disable automatic reruns')
  local first_timestep
  if preinitialize then
    -- Official SIMION lifecycle: create all particles and call initialize for
    -- each, before any sequential particle enters trajectory integration.
    local before_resets,before_seeds=reset_calls,#seeds
    for id=1,sim_ions_count do
      ion_number=id;segment.initialize()
    end
    assert(reset_calls==before_resets and #seeds==before_seeds,
      'creation callbacks must not own the active collision RNG or HS1 reset')
    rand() -- Model unrelated source-creation RNG use, not a physical collision.
  end
  for id=1,sim_ions_count do
    local source=sources[id]
    ion_number=id;ion_splat=0;ion_time_of_flight=0
    put_local(source.x,source.y,source.z,source.vx,source.vy,source.vz)
    if not preinitialize then segment.initialize();rand() end
    ion_time_step=1
    segment.tstep_adjust()
    local offset=config.execution_batch and config.execution_batch.particle_id_offset or 0
    assert(random_state==config.numerics.seed+offset+id-1,
      'actual integration activation must own the canonical particle seed')
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
      config.native_timing.primary_quench_us,
      config.baseline.schedule.extraction_start_us+1}
    local xs={35,120,lp_end+0.1,170,170,170,170}
    for index,t in ipairs(times) do
      ion_time_of_flight=t
      local y=index==#times and config.baseline.geometry.extraction_end_y_mm+0.2 or source.y
      put_local(xs[index],y,source.z,source.vx,source.vy,source.vz)
      if index==2 then assert(test_hs.pressure()==config.baseline.gas.hp_pressure_pa, "HP pressure must use local region") end
      if index==4 then assert(test_hs.pressure()==config.baseline.gas.lp_pressure_pa, "LP pressure must use local region") end
      if index==6 then
        for _,boundary in ipairs({config.baseline.schedule.lift_end_us,
          config.native_timing.primary_quench_us,config.native_timing.pulse_start_us}) do
          ion_time_of_flight=boundary-0.001;ion_time_step=1
          segment.tstep_adjust()
          assert(math.abs(ion_time_step-0.001)<1e-9,'timestep must land at lift/quench/pulse boundary')
          for _,offset in ipairs({0,0.001}) do
            ion_time_of_flight=boundary+offset;ion_time_step=1
            segment.tstep_adjust()
            assert(ion_time_step>0,'exact/past timing edges must not request a zero step')
          end
        end
        ion_time_of_flight=t
      end
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
local events1,samples1,dt1=fly_again(true)
ion_run=1
-- Simulate stale GUI-adjustable state; initialize_run must restore the same
-- scientific inputs before the second seeded collision module initialization.
_gas_mass_amu=999;_temperature_k=999;_sigma_m2=1;_random_seed=1
local events2,samples2,dt2=fly_again(false)
assert(imports==1,'HS1 workbench module must be imported exactly once outside Fly')
assert(reset_calls==2*(1+sim_ions_count),'each Fly must explicitly reset private HS1 lifecycle state')
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
local receipt=contents(directory..'collision_rng_seeds.csv')
local offset=config.execution_batch and config.execution_batch.particle_id_offset or 0
assert(receipt:match(string.format('1,%d,%d',offset+1,config.numerics.seed+offset)),
 'seed audit must preserve the canonical global ID')
assert(receipt:match(string.format('2,%d,%d',offset+2,config.numerics.seed+offset+1)),
 'each particle must have its own audited seed')
assert(#seeds>=2 and seeds[1]==config.numerics.seed and
  seeds[#seeds]==config.numerics.seed+sim_ions_count-1+(config.execution_batch and config.execution_batch.particle_id_offset or 0),'each canonical particle must initialize its own declared seed')
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
local census_ok,census_message=pcall(segment.terminate_run)
assert(not census_ok and tostring(census_message):match('lacks recorded terminal for particle 2'),
 'missing native terminal callbacks must fail closed, not fabricate a state')
assert(contents(directory..'events.csv'):match('radial_escape'),'local boundary reason must survive rotation')
segment.initialize_run()
for id=1,sim_ions_count do
 ion_number=id;ion_time_of_flight=0;ion_splat=0
 local s=sources[id];put_local(s.x,s.y,s.z,s.vx,s.vy,s.vz)
 segment.initialize();segment.other_actions()
 local plane=config.numerical_boundaries.downstream_exit_x_mm
 ion_time_of_flight=4100;put_local(plane-0.001,0,0,1,0,0)
 segment.other_actions()
 ion_time_step=1;segment.tstep_adjust()
 assert(ion_time_step<=0.001000001,'near-boundary step must resolve the numerical exit')
 ion_time_of_flight=4100.02;put_local(plane+0.01,0,0,1,0,0)
 segment.other_actions();segment.terminate()
 assert(ion_splat==1,'downstream numerical escape must be recorded before leaving the PA')
end
segment.terminate_run()
assert(contents(directory..'events.csv'):match('downstream_domain_exit'),'domain escape is not a metal collision')
local domain_terminal_count=0
for line in contents(directory..'events.csv'):gmatch('[^\n]+') do
 if line:match('^terminal,%d+,downstream_domain_exit,') then
  local fields={};for value in line:gmatch('[^,]+') do fields[#fields+1]=value end
  local axis=config.coordinate_transform and 6 or 5
  assert(math.abs(tonumber(fields[axis])-config.numerical_boundaries.downstream_exit_x_mm)<1e-10,
   'interpolated numerical exit must lie on its frozen plane')
  local t=tonumber(fields[4])
  assert(math.abs(t-(4100+0.02/11))<1e-9,'domain crossing time must use the recorded integration bracket')
  domain_terminal_count=domain_terminal_count+1
 end
end
assert(domain_terminal_count==sim_ions_count,'record each domain terminal exactly once')
print('RUNTIME_PREINITIALIZED_PARTICLES_PASS')
print('RUNTIME_TERMINAL_CENSUS_PASS')
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
        if mode == "zero-alignment":
            config["baseline"]["electric"]["rf_quench_alignment"] = "next_cosine_zero"
        from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import derive_native_timing
        config["native_timing"] = derive_native_timing(config["baseline"])
        if mode in {"transformed", "upstream-source"}:
            config["coordinate_transform"] = json.loads((PROJECT / "config/coordinate_transform.json").read_text(encoding="utf-8"))
        if mode == "upstream-source":
            # A distinct lower bound detects a hardcoded replacement for zero.
            config["baseline"]["native_geometry"]["domain_start_x_mm"] = -3.7
        config["source"]["particle_count"] = 2
        if mode == "injected":
            config["injected_source"] = dict(particle_ids=[2, 42])
        if mode in {"offset", "csv-batch"}:
            config["source"]["particle_count"] = 100
            config["execution_batch"] = {"particle_id_offset": 50, "particle_id_min": 51, "particle_id_max": 52, "retain_trajectories": mode != "csv-batch"}
        config["native_projection"] = native_projection(config["baseline"], config["numerics"])
        from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import derive_numerical_boundaries
        config["numerical_boundaries"]=derive_numerical_boundaries(config["native_projection"])
        with tempfile.TemporaryDirectory(prefix="ion_processor_replay_test_") as temporary:
            folder = Path(temporary)
            for name in ("runtime.lua", "native_drive.lua", "extraction_force_audit.lua"):
                if name == "runtime.lua":
                    # Syntax adapter for standalone Lua only; real SIMION evidence
                    # is required to prove adjustable binding.
                    text = (PROJECT / "simion" / name).read_text(encoding="utf-8")
                    (folder / name).write_text(text.replace("adjustable ", ""), encoding="utf-8")
                else:
                    shutil.copyfile(PROJECT / "simion" / name, folder / name)
            shutil.copyfile(REPOSITORY / "common/simion/rf_drive.lua",
                            folder / "simion_rf_drive.lua")
            shutil.copyfile(REPOSITORY / "common/simion/voltage_waveforms.lua",
                            folder / "voltage_waveforms.lua")
            (folder / "frozen_config.lua").write_text("return " + lua_literal(config), encoding="utf-8")
            sources = [{"particle_id": index, "t": 0, "x": 1, "y": index * 0.01,
                        "z": 0, "vx": 1, "vy": 0, "vz": 0, "ke": 5} for index in (1, 2)]
            if mode == "injected":
                for index, state in enumerate(sources):
                    state["t"] = 43.02 + index*.4
            if mode == "upstream-source":
                for state in sources:
                    state["x"] = config["native_projection"]["origin_mm"][0] + 0.5
            (folder / "source_states.lua").write_text("return " + lua_literal(sources), encoding="utf-8")
            (folder / "replay.lua").write_text(LUA_HARNESS, encoding="utf-8")
            unrelated = folder / "unrelated_gui_cwd"
            unrelated.mkdir()
            result = subprocess.run([executable, str(folder / "replay.lua"), str(folder / "runtime.lua"), mode], cwd=unrelated,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                                    check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_injected_sparse_identity_and_absolute_arrival(self) -> None:
        self.assertIn("RUNTIME_INJECTED_ID_ARRIVAL_PASS", self.run_runtime_fixture("injected"))

    def test_repeated_initialize_run_resets_state_and_draws_numerical_outline(self) -> None:
        self.assertIn("RUNTIME_REPLAY_PASS", self.run_runtime_fixture("replay"))

    def test_zero_alignment_preserves_lift_quench_pulse_clamps(self) -> None:
        self.assertIn("RUNTIME_REPLAY_PASS", self.run_runtime_fixture("zero-alignment"))

    def test_all_creation_callbacks_precede_sequential_flight_without_rng_leak(self) -> None:
        self.assertIn("RUNTIME_PREINITIALIZED_PARTICLES_PASS", self.run_runtime_fixture("preinitialize"))

    def test_project_rotation_preserves_local_regions_boundaries_and_replay(self) -> None:
        self.assertIn("RUNTIME_REPLAY_PASS", self.run_runtime_fixture("transformed"))

    def test_upstream_source_stops_inside_pa_without_outside_or_terminate_callback(self) -> None:
        self.assertIn("RUNTIME_UPSTREAM_SOURCE_PASS", self.run_runtime_fixture("upstream-source"))

    def test_unfinished_particle_interleaving_remains_refused(self) -> None:
        self.assertIn("RUNTIME_UNFINISHED_INTERLEAVING_REFUSED_PASS", self.run_runtime_fixture("unfinished-interleaving"))

    def test_nonzero_batch_offset_sets_canonical_particle_seeds(self) -> None:
        self.assertIn("RUNTIME_REPLAY_PASS", self.run_runtime_fixture("offset"))

    def test_csv_batch_suppresses_only_vendor_dense_trajectory_output(self) -> None:
        self.assertIn("RUNTIME_REPLAY_PASS", self.run_runtime_fixture("csv-batch"))

    def test_actual_hs1_readback_mismatch_refuses_integration(self) -> None:
        self.assertIn("RUNTIME_HS1_MISMATCH_REFUSED_PASS", self.run_runtime_fixture("bound-mismatch"))

    def test_missing_outline_api_fails_with_clear_capability_error(self) -> None:
        self.assertIn("RUNTIME_OUTLINE_API_REQUIRED_PASS", self.run_runtime_fixture("missing-api"))


if __name__ == "__main__":
    unittest.main()
