-- Run one already-materialized MR-TOF Workbench through SIMION's Fly command.
-- Usage: simion.exe --nogui lua run_iob_flight.lua RUN.iob
local iob = assert(arg[1], 'usage: RUN.iob')
assert(iob:match('%.iob$'), 'flight input must be an IOB')
local program = iob:gsub('%.iob$', '.lua')
local fly2 = iob:gsub('%.iob$', '.fly2')
local operating_point = iob:gsub('%.iob$', '.operating_point.lua')
for _, path in ipairs({program, fly2, operating_point}) do
  local file = assert(io.open(path, 'rb'), 'missing run-local Workbench companion: '..path)
  file:close()
end
-- SIMION 2020 official geometry_optimization example uses this supported
-- command path for headless Workbench flying.
simion.command('fly "'..iob..'"')
print('IOB_FLIGHT: PASS iob='..iob)
