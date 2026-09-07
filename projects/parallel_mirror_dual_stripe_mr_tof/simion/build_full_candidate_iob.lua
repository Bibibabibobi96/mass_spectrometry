-- Create a one-instance IOB from the repository's structure-only one-PA seed.
-- Usage: simion.exe --nogui lua build_full_candidate_iob.lua SEED.iob PA0 OUTPUT.iob PROGRAM FLY2 ORIGIN_X ORIGIN_Y ORIGIN_Z
-- The three origins are resolved physical-to-PA translations supplied by the
-- geometry compiler; this adapter never re-derives them from hidden dimensions.
local function required_number(index, label)
  local text = assert(arg[index], label..' required')
  return assert(tonumber(text), label..' must be numeric')
end
local seed, pa_path, output, program, fly2 =
  assert(arg[1], 'structure-only seed iob required'), assert(arg[2], 'pa0 required'),
  assert(arg[3], 'output iob required'), assert(arg[4], 'program required'),
  assert(arg[5], 'fly2 required')
local origin_x = required_number(6, 'x origin')
local origin_y = required_number(7, 'y origin')
local origin_z = required_number(8, 'z origin')
assert(pa_path:match('%.pa0$'), 'workbench must load the solved pa0 array; PA# remains the geometry master')
assert(seed:match('%.iob$'), 'seed must have the .iob extension')
-- A same-basename Lua program causes SIMION's Lua command to enter a fly
-- loop.  The tracked instance seed is deliberately structure-only, so reject
-- any executable template rather than silently hanging the build.
local seed_program = seed:gsub('%.iob$', '.lua')
local probe = io.open(seed_program, 'rb')
assert(not probe, 'seed IOB must not have an adjacent Lua program: ' .. seed_program)
if probe then probe:close() end
simion.command('"' .. seed .. '"')
local wb = simion.wb
assert(wb and wb.filename, 'SIMION failed to load the structure-only IOB seed')
assert(#wb.instances == 1, 'one-instance seed must contain exactly one PA instance')
local instance = wb.instances[1]
instance.pa:load(pa_path)
-- SIMION 2020 retains the template instance bounds after PA replacement
-- unless this compatibility refresh is requested.  SIMION's distributed
-- magnetic-sector example uses the same method.  Fail closed rather than
-- saving an IOB whose physical extent is still that of the template.
assert(instance._debug_update_size, 'SIMION 2020 instance-size refresh unavailable')
instance:_debug_update_size()
-- PA coordinates are shifted only by the compiler-resolved project transform.
instance.x, instance.y, instance.z = origin_x, origin_y, origin_z
instance.az, instance.el, instance.rt, instance.scale = 0, 0, 0, 1
wb:save(output)
local function copy(source, target)
  local f = assert(io.open(source, 'rb')); local text = f:read('*a'); f:close()
  local g = assert(io.open(target, 'wb')); g:write(text); g:close()
end
copy(program, output:gsub('%.iob$', '.lua'))
copy(fly2, output:gsub('%.iob$', '.fly2'))
local sidecar = program:gsub('%.lua$', '.operating_point.lua')
local probe = assert(io.open(sidecar, 'rb'), 'program operating-point sidecar is required: ' .. sidecar)
probe:close()
copy(sidecar, output:gsub('%.iob$', '.operating_point.lua'))
print(string.format('IOB_BUILD: PASS instance=1 origin_mm=(%.12g,%.12g,%.12g)', origin_x, origin_y, origin_z))
