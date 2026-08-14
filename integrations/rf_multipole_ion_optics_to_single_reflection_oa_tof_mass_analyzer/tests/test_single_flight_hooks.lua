-- Pure callback-neutral hook checks for SIMION's supported Lua CLI.

local pulse_path = assert(arg[1], 'pulse hook path is required')
local frontend_path = assert(arg[2], 'frontend hook path is required')
local pulse_module = assert(dofile(pulse_path), 'pulse hook did not return a module')
local frontend_module = assert(dofile(frontend_path), 'frontend hook did not return a module')

local function near(actual, expected, label)
  local tolerance = 1e-11 * math.max(1, math.abs(expected))
  assert(math.abs(actual-expected) <= tolerance,
    label .. ': expected ' .. expected .. ', got ' .. tostring(actual))
end

local clock_time, mode = 0, 1
local pulse = pulse_module.new{
  canonical_clock=function() return clock_time end,
  pulse_time_us=1,
  pulse_width_us=0.5,
  pulse_mode=function() return mode end,
}
clock_time = 0.25
near(pulse.instrument_time_us(), 0.25, 'injected canonical clock')
local before = pulse.state_at(0.75)
assert(not before.active and before.next_edge_us == 1, 'pre-pulse state is wrong')
near(pulse.cap_timestep_at(0.75, 1), 0.25, 'rising-edge landing')
local active = pulse.diagnostics_at(1.25)
assert(active.active and active.next_edge_us == 1.5, 'active pulse state is wrong')
near(active.tof_since_pulse_us, 0.25, 'cross-system TOF diagnostic')
near(pulse.cap_timestep_at(1.25, 1), 0.25, 'falling-edge landing')
mode = 0
assert(pulse.is_active_at(-10), 'always-on pulse mode is wrong')
mode = 2
assert(not pulse.is_active_at(1.25), 'held-off pulse mode is wrong')
near(pulse.cap_timestep_at(1.25, 1), 1, 'held-off timestep')

local writes = {}
local rf_drive = {
  timestep_cap_us=10,
  apply_at=function(time_us, setter)
    setter(1, 100 + time_us)
    setter(2, -100 - time_us)
  end,
}
local electrode_plan = {
  apply_at=function(time_us, pulse_state, setter)
    setter(41, pulse_state.active and 900 or 0)
    setter(77, time_us)
  end,
}
local frontend = frontend_module.new{
  rf_drive=rf_drive,
  pulse_hook=pulse,
  electrode_plan=electrode_plan,
  planes_z_mm={0, 2},
}
mode = 1
frontend.apply_at(1.25, function(id, voltage)
  writes[#writes+1] = {id=id, voltage=voltage}
end)
assert(#writes == 4 and writes[1].id == 1 and writes[2].id == 2 and
  writes[3].id == 41 and writes[4].id == 77,
  'frontend must write RF before the project-provided electrode plan')
near(writes[3].voltage, 900, 'project plan pulse voltage')

mode = 0
local state = frontend.initialize_particle(-0.25)
near(frontend.cap_timestep_at(2, -0.25, 1, 1, state), 0.25,
  'first plane landing request')
near(frontend.cap_timestep_at(2, -0.25, 1, 1, state), 1,
  'repeated plane evaluation must not request landing twice')
near(frontend.cap_timestep_at(2.25, -1e-16, 1, 1, state), 0,
  'unique zero-step confirmation')
local events = frontend.observe_step(
  {time_us=2, position_z_mm=-0.25, velocity_z_mm_per_us=1},
  {time_us=2.25, position_z_mm=0, velocity_z_mm_per_us=1}, state)
assert(#events == 1 and events[1].plane_index == 1 and
  state.planes[1].status == 'hitted', 'zero-step plane observation is wrong')

local crossing_state = frontend.initialize_particle(-0.5)
near(frontend.cap_timestep_at(3, -0.5, 1, 1, crossing_state), 0.5,
  'crossing plane request')
events = frontend.observe_step(
  {time_us=3, position_z_mm=-0.5, velocity_z_mm_per_us=1},
  {time_us=3.5, position_z_mm=0.01, velocity_z_mm_per_us=1}, crossing_state)
assert(#events == 1 and crossing_state.planes[1].status == 'hitting',
  'crossed plane must enter hitting state')
frontend.observe_step(
  {time_us=3.5, position_z_mm=0.01, velocity_z_mm_per_us=1},
  {time_us=3.6, position_z_mm=0.02, velocity_z_mm_per_us=1}, crossing_state)
assert(crossing_state.planes[1].status == 'hitted',
  'observed crossing must finish the official landing lifecycle')

local capped_drive = {
  timestep_cap_us=0.00625,
  apply_at=rf_drive.apply_at,
}
local capped_frontend = frontend_module.new{
  rf_drive=capped_drive, pulse_hook=pulse, electrode_plan=electrode_plan,
  planes_z_mm={0, 2},
}
near(capped_frontend.cap_timestep_at(4, 3, 1, 1,
  capped_frontend.initialize_particle(3)), 0.00625, 'RF timestep cap')

local ok = pcall(pulse_module.new, {canonical_clock=function() return 0 end,
  pulse_time_us=1, pulse_width_us=0, pulse_mode=function() return 1 end})
assert(not ok, 'zero pulse width was accepted')
ok = pcall(frontend_module.new, {rf_drive=rf_drive, pulse_hook=pulse,
  electrode_plan=electrode_plan, planes_z_mm={2, 0}})
assert(not ok, 'unordered planes were accepted')

print('SINGLE_FLIGHT_PURE_HOOKS=PASS')
