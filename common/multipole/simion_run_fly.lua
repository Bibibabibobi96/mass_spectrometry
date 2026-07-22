-- Run fly inside a dedicated non-GUI SIMION Lua process.  This avoids the
-- interactive GUI command dispatcher and makes completion/exit deterministic.

local config_path = assert(os.getenv('MULTIPOLE_SIMION_RUN_CONFIG_LUA'), 'MULTIPOLE_SIMION_RUN_CONFIG_LUA is not set')
local config = assert(dofile(config_path), 'run config did not return a table')
local iob = assert(config.iob, 'run config iob is missing')
local particles = assert(config.fly2, 'run config fly2 is missing')
local quality = assert(config.trajectory_quality, 'run config trajectory_quality is missing')
local steps = assert(config.rf_steps_per_period, 'run config rf_steps_per_period is missing')

local function quote(value)
  return '"' .. value:gsub('"', '\\"') .. '"'
end

local parts = {
  'fly',
  '--trajectory-quality', quality,
  '--particles', quote(particles),
  '--programs 1',
  '--retain-trajectories 0',
  '--adjustable', quote('transport_rf_steps_per_period=' .. steps),
  quote(iob)
}
local command = table.concat(parts, ' ')

print('MULTIPOLE_FLY_COMMAND ' .. command)
simion.command(command)
