-- Run one already-materialized MR-TOF Workbench through SIMION's Fly command.
-- Usage: simion.exe --nogui lua run_iob_flight.lua RUN.iob [PARTICLES.fly2]
local iob = assert(arg[1], 'usage: RUN.iob')
local particles = arg[2]
assert(iob:match('%.iob$'), 'flight input must be an IOB')
local program = iob:gsub('%.iob$', '.lua')
local fly2 = iob:gsub('%.iob$', '.fly2')
local operating_point = iob:gsub('%.iob$', '.operating_point.lua')
for _, path in ipairs({program, fly2, operating_point}) do
  local file = assert(io.open(path, 'rb'), 'missing run-local Workbench companion: '..path)
  file:close()
end
if particles then
  assert(particles:match('%.fly2$'), 'particle override must be a Fly2 file')
  local file = assert(io.open(particles, 'rb'), 'missing particle override: '..particles)
  file:close()
end
-- SIMION 2020 official geometry_optimization example uses this supported
-- command path for headless Workbench flying.
local particle_option = particles and (' --particles="'..particles..'"') or ''
simion.command('fly'..particle_option..' "'..iob..'"')
print('IOB_FLIGHT: PASS iob='..iob)
