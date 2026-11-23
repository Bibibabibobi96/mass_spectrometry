-- Synthetic callback regression in the supplier Lua VM: no PA or Fly.
-- Only SIMION's adjustable declaration is normalized; callbacks are production code.
local program_path, kernel_path, output_dir = assert(arg[1]), assert(arg[2]), assert(arg[3])
local file = assert(io.open(program_path, 'r'))
local source = file:read('*a'); file:close()
source = source:gsub('adjustable%s+([%w_]+)%s*=', '%1 =')
local function read(path)
  local input = assert(io.open(path)); local text = input:read('*a'); input:close(); return text
end
local function near(actual, expected) assert(math.abs(actual-expected)<1e-9, actual..' ~= '..expected) end
local function scenario(name, reference)
  local prefix = output_dir..'/'..name
  local config = {
    source_states={{t=7,x=0,y=0,z=4,vx=1,vy=0,vz=0,ke=2}},
    rf_peak_v=100,dc_amplitude_v=0,frequency_hz=1e6,phase_rad=0.3,waveform='sine',
    rf_steps_per_period=40,maximum_time_us=100,trajectory_plane_step_mm=1,
    rod_z_min_mm=0,rod_z_max_mm=1,rod_exit_plane_mm=1,handoff_plane_mm=2,
    census_plane_mm=4,census_radius_mm=20,radial_escape_radius_mm=100,
    rod_electrodes={{electrode_id=1,electrode_group=1,common_mode_v=0},
      {electrode_id=2,electrode_group=2,common_mode_v=0}},
    static_electrodes=reference and {{electrode_id=3,potential_v=0},
      {electrode_id=4,potential_v=0},{electrode_id=5,potential_v=-1500}} or {},
    particle_state_csv=prefix..'_particles.csv',summary_json=prefix..'_summary.json',
    mode='callback_fixture',operating_point='synthetic',parent_resolved_design_sha256='fixture',
  }
  if not reference then
    config.mechanical_exit_csv=prefix..'_exit.csv'
    config.mechanical_exit_plane_mm=1; config.mechanical_exit_guard_mm=5
    -- No mechanical aperture: the open rod envelope is not a physical hole.
  end
  local env = setmetatable({segment={},adj_elect={},sim_ions_count=1,ion_number=1,
    simion={workbench_program=function() end}}, {__index=_G})
  env._G=env
  env.os=setmetatable({getenv=function(key)
    if key=='MULTIPOLE_SIMION_RUN_CONFIG_LUA' then return 'fixture_config' end
    if key=='MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA' then return kernel_path end
    return os.getenv(key)
  end},{__index=os})
  env.dofile=function(path) if path=='fixture_config' then return config end return dofile(path) end
  local chunk=assert(loadstring(source,'@'..program_path));setfenv(chunk,env);chunk()
  local function state(t,x,y,vx,vy)
    env.ion_time_of_flight=t;env.ion_px_mm=x;env.ion_py_mm=0;env.ion_pz_mm=y
    env.ion_vx_mm=vx or 1;env.ion_vy_mm=0;env.ion_vz_mm=vy or 0;env.ion_ke=2
  end
  local function start()
    env.segment.initialize_run();state(7,0,4);env.segment.other_actions()
    env.segment.fast_adjust()
    if reference then near(env.adj_elect[5],-1500) else assert(env.adj_elect[3]==nil) end
  end
  local function finish(crossings,hits)
    env.segment.terminate_run()
    local summary=read(config.summary_json)
    assert(summary:find('"census_plane_crossings": '..crossings,1,true),summary)
    assert(summary:find('"hits": '..hits,1,true),summary)
    local rows=read(config.particle_state_csv)
    local _,terminals=rows:gsub(',terminal,','');assert(terminals==1,rows)
    return rows
  end
  return {env=env,state=state,start=start,finish=finish,config=config}
end
local curved=scenario('curved_bare',false);curved.start()
curved.state(10,3,5,2,10);curved.env.segment.other_actions()
curved.state(12,5,9,4,30);curved.env.segment.other_actions()
curved.env.segment.terminate();local rows=curved.finish(1,1)
local terminal=assert(rows:match('1,terminal,([^\n]+)'))
local columns={};for value in terminal:gmatch('[^,]+') do columns[#columns+1]=value end
near(tonumber(columns[3]),11);near(tonumber(columns[6]),4);near(tonumber(columns[7]),7)
near(tonumber(columns[9]),3000);near(tonumber(columns[10]),20000)
assert(read(curved.config.mechanical_exit_csv):find(',mechanical_exit,transmitted,none,',1,true))
-- A second run in the same loaded Program must reset the completed census.
curved.start();curved.state(10,3.9,5);curved.env.segment.other_actions()
curved.env.segment.terminate();curved.finish(0,0)
local reference=scenario('reference_terminate',true);reference.start()
reference.state(10,3.5,4);reference.env.segment.other_actions()
reference.state(11,4,6);reference.env.segment.terminate();reference.finish(1,1)
local fallback=scenario('fallback_unobserved',true);fallback.start()
fallback.state(10,3.99,4);fallback.env.segment.other_actions();fallback.finish(0,0)
print('SIMION_TRANSPORT_CALLBACK_TEST=PASS scenarios=4 repeat_runs=1 no_pa=true no_fly=true')
