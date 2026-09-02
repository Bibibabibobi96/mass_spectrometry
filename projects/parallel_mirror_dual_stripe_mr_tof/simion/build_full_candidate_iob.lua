-- Create a one-instance IOB from an official SIMION example template.
-- Usage: simion.exe --nogui lua build_full_candidate_iob.lua TEMPLATE.iob PA0 OUTPUT.iob PROGRAM FLY2 Z_SHIFT
local template, pa_path, output, program, fly2, z_shift =
  assert(arg[1], 'template iob required'), assert(arg[2], 'pa0 required'),
  assert(arg[3], 'output iob required'), assert(arg[4], 'program required'),
  assert(arg[5], 'fly2 required'), tonumber((assert(arg[6], 'z shift required')))
simion.command('"'..template..'"')
local wb = simion.wb
assert(#wb.instances == 1, 'official template must contain one PA instance')
local instance = wb.instances[1]
instance.pa:load(pa_path)
instance:_debug_update_size()
-- PA coordinates are shifted to the documented project origin.  This keeps
-- local z=+0.129186803411 mm (the two-zone first focus) at project z=0.
-- The CAD-resolved Candidate PA spans 180 x 680 x 900 mm.  This placement
-- maps its geometric centre to the project origin before applying the
-- accelerator focus correction; the prior 700-mm value incorrectly translated
-- every z coordinate by +100 mm.
instance.x, instance.y, instance.z = -90, -340, -450 + z_shift
instance.az, instance.el, instance.rt, instance.scale = 0, 0, 0, 1
wb:save(output)
local function copy(source, target)
  local f = assert(io.open(source, 'rb')); local text = f:read('*a'); f:close()
  local g = assert(io.open(target, 'wb')); g:write(text); g:close()
end
copy(program, output:gsub('%.iob$', '.lua'))
copy(fly2, output:gsub('%.iob$', '.fly2'))
print(string.format('IOB_BUILD: PASS instance=1 origin_mm=(-90,-340,%.12g)', -450 + z_shift))
