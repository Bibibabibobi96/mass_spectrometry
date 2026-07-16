-- Run fly inside a dedicated non-GUI SIMION Lua process.  This avoids the
-- interactive GUI command dispatcher and makes completion/exit deterministic.

local iob = assert(os.getenv('RFQUAD_SIMION_IOB'), 'RFQUAD_SIMION_IOB is not set')
local particles = assert(os.getenv('RFQUAD_SIMION_FLY2'), 'RFQUAD_SIMION_FLY2 is not set')
local quality = assert(os.getenv('RFQUAD_SIMION_QUALITY'), 'RFQUAD_SIMION_QUALITY is not set')
local steps = assert(os.getenv('RFQUAD_SIMION_STEPS'), 'RFQUAD_SIMION_STEPS is not set')

local function quote(value)
  return '"' .. value:gsub('"', '\\"') .. '"'
end

local command = table.concat({
  'fly',
  '--trajectory-quality', quality,
  '--particles', quote(particles),
  '--programs 1',
  '--retain-trajectories 0',
  '--adjustable', quote('transport_rf_steps_per_period=' .. steps),
  quote(iob)
}, ' ')

print('RFQUAD_FLY_COMMAND ' .. command)
simion.command(command)
