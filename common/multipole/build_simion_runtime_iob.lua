-- Rebind a structure-only one-PA template to the run-local PA and Program.
-- This is the single-instance counterpart of oa-TOF build_formal_iob.lua.

local iob_path = assert(arg[1], 'runtime IOB path is required')
local program_source = assert(arg[2], 'runtime Program source path is required')
local fly2_source = assert(arg[3], 'runtime Fly2 source path is required')
local pa_path = iob_path:gsub('%.[iI][oO][bB]$', '.pa0')
assert(pa_path ~= iob_path, 'runtime IOB must use the .iob extension')
local program_output = iob_path:gsub('%.[iI][oO][bB]$', '.lua')
local fly2_output = iob_path:gsub('%.[iI][oO][bB]$', '.fly2')

local function read_file(path, label)
  local stream = assert(io.open(path, 'rb'), 'cannot open ' .. label .. ': ' .. path)
  local content = stream:read('*a')
  stream:close()
  return content
end

local function write_file(path, content, label)
  local stream = assert(io.open(path, 'wb'), 'cannot write ' .. label .. ': ' .. path)
  stream:write(content)
  stream:close()
end

local program = read_file(program_source, 'runtime Program')
local fly2 = read_file(fly2_source, 'runtime Fly2')
assert(program:match('simion%.workbench_program%s*%('),
  'runtime Program is not a SIMION workbench program')

simion.command('"' .. iob_path .. '"')
local wb = assert(simion.wb, 'runtime Workbench did not load')
assert(#wb.instances == 1, 'runtime Workbench must contain one PA instance')
local instance = wb.instances[1]
local transform = {
  instance.x, instance.y, instance.z,
  instance.az, instance.el, instance.rt, instance.scale,
}
instance.pa:load(pa_path)
instance:_debug_update_size()
instance.x, instance.y, instance.z = transform[1], transform[2], transform[3]
instance.az, instance.el, instance.rt, instance.scale =
  transform[4], transform[5], transform[6], transform[7]
wb:save(iob_path)

-- wb:save may replace same-basename sidecars with minimal GUI stubs.
write_file(program_output, program, 'runtime Program')
write_file(fly2_output, fly2, 'runtime Fly2')
print('MULTIPOLE_RUNTIME_IOB_BUILD=PASS')
