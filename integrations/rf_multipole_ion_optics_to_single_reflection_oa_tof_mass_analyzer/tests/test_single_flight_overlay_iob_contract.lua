-- Probe the load-before-Program contract of a production-built five-instance IOB.
-- The successor Program's own initialize_run contract verifies the post-load state.
-- Usage: simion.exe --nogui --noprompt lua this.lua IOB

local iob_path=assert(arg[1],'production-built overlay IOB is required')

local function basename(value)
  assert(type(value)=='string','instance filename must be a string')
  return assert(value:gsub('\\','/'):match('([^/]+)$'),'instance basename is missing')
end

simion.command('"'..iob_path..'"')
local expected={
  'flight_tube_ground.pa0',
  'reflectron.pa0',
  'accelerator.pa0',
  'detector_ground.pa0',
  'accelerator_overlay.pa0',
}
assert(#simion.wb.instances==#expected,'production overlay IOB instance count differs')
for index,name in ipairs(expected) do
  assert(basename(simion.wb.instances[index].filename)==name,
    'production overlay IOB pre-load slot '..index..' differs')
end
print('PRODUCTION_OVERLAY_IOB_PRELOAD_CONTRACT=PASS SLOT3=accelerator.pa0 SLOT5=accelerator_overlay.pa0')
