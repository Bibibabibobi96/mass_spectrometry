-- Structure-only verifier for the shared one-PA multipole GUI container.
-- It opens an already copied IOB and never refines, flies, or applies voltage.

local report_path = assert(os.getenv('MULTIPOLE_TEMPLATE_REPORT'),
  'MULTIPOLE_TEMPLATE_REPORT is not set')
local iob_path = assert(os.getenv('MULTIPOLE_TEMPLATE_IOB'),
  'MULTIPOLE_TEMPLATE_IOB is not set')
local bundle_root = assert(os.getenv('MULTIPOLE_TEMPLATE_BUNDLE_ROOT'),
  'MULTIPOLE_TEMPLATE_BUNDLE_ROOT is not set')
local expected_pa_path = bundle_root .. '\\quad_monolithic.pa0'
local expected_pa_basename = 'quad_monolithic.pa0'
local tolerance = 1e-12

local report = assert(io.open(report_path, 'w'))
local function record(fmt, ...)
  local line = string.format(fmt, ...)
  report:write(line, '\n')
  report:flush()
  print(line)
end
local function close_to(actual, expected)
  return math.abs(actual - expected) <= tolerance
end
local function assert_vector(label, actual, expected)
  assert(close_to(actual[1], expected[1])
      and close_to(actual[2], expected[2])
      and close_to(actual[3], expected[3]),
    string.format('%s mismatch: actual=%.15g,%.15g,%.15g',
      label, actual[1], actual[2], actual[3]))
end
local function normalized(path)
  return path:gsub('/', '\\'):lower()
end

record('STAGE=report_opened')
record('STAGE=before_iob_open')
simion.command('"' .. iob_path .. '"')
record('STAGE=after_iob_open')
assert(simion.wb and #simion.wb.instances == 1,
  string.format('shared multipole layout requires one PA instance; actual=%d',
    simion.wb and #simion.wb.instances or -1))
local instance = simion.wb.instances[1]
assert(instance.filename == expected_pa_basename,
  'template PA reference must be the relative basename quad_monolithic.pa0')
local loaded_pa = assert(instance.pa,
  'template instance did not load a PA; run-local PA availability is required')
assert(loaded_pa.nx == 5 and loaded_pa.ny == 5 and loaded_pa.nz == 5,
  string.format('run-local placeholder PA dimensions mismatch: %dx%dx%d',
    loaded_pa.nx, loaded_pa.ny, loaded_pa.nz))
assert(close_to(loaded_pa.dx_mm, 1)
    and close_to(loaded_pa.dy_mm, 1)
    and close_to(loaded_pa.dz_mm, 1),
  'run-local placeholder PA cell dimensions must be 1 mm')

local transform = {
  instance.x, instance.y, instance.z,
  instance.az, instance.el, instance.rt, instance.scale,
}
local expected_transform = {0, 0, 0, -90, 0, 180, 1}
for index = 1, #expected_transform do
  assert(close_to(transform[index], expected_transform[index]),
    string.format('template transform field %d mismatch: actual=%.15g expected=%.15g',
      index, transform[index], expected_transform[index]))
end

local xx, xy, xz = instance:pa_to_wb_orient(1, 0, 0)
local yx, yy, yz = instance:pa_to_wb_orient(0, 1, 0)
local zx, zy, zz = instance:pa_to_wb_orient(0, 0, 1)
assert_vector('PA_X_IN_WB', {xx, xy, xz}, {0, 0, 1})
assert_vector('PA_Y_IN_WB', {yx, yy, yz}, {0, -1, 0})
assert_vector('PA_Z_IN_WB', {zx, zy, zz}, {1, 0, 0})

-- Registration independently compiles the frozen canonical GEM into this
-- run bundle.  The dimensions/cell checks above and this resolved-path check
-- bound the loaded PA to that independently derived run-local asset.
local loaded_pa_path = loaded_pa.filename
if type(loaded_pa_path) == 'string' and loaded_pa_path ~= '' then
  local absolute = loaded_pa_path:match('^%a:[\\/]') or loaded_pa_path:match('^[\\/]')
  if absolute then
    assert(normalized(loaded_pa_path) == normalized(expected_pa_path),
      'loaded PA path does not point to the run-local template bundle')
    record('LOADED_PA_PATH=%s', loaded_pa_path)
  else
    assert(normalized(loaded_pa_path) == normalized(expected_pa_basename),
      'loaded PA relative path is not the run-local placeholder basename')
    record('LOADED_PA_PATH_API=relative_basename')
  end
else
    record('LOADED_PA_PATH_API=unavailable')
end

record('INSTANCE_COUNT=1')
record('INSTANCE_1_FILE=%s', instance.filename)
record('LOADED_PA_DIMS=%d,%d,%d', loaded_pa.nx, loaded_pa.ny, loaded_pa.nz)
record('LOADED_PA_CELL_MM=%.15g,%.15g,%.15g',
  loaded_pa.dx_mm, loaded_pa.dy_mm, loaded_pa.dz_mm)
record('INSTANCE_1_TRANSFORM=%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g',
  transform[1], transform[2], transform[3], transform[4],
  transform[5], transform[6], transform[7])
record('INSTANCE_1_PA_X_IN_WB=%.15g,%.15g,%.15g', xx, xy, xz)
record('INSTANCE_1_PA_Y_IN_WB=%.15g,%.15g,%.15g', yx, yy, yz)
record('INSTANCE_1_PA_Z_IN_WB=%.15g,%.15g,%.15g', zx, zy, zz)
record('PHYSICAL_MODEL=false')
record('PROGRAM_EXECUTED=false')
record('PARTICLE_FLY_EXECUTED=false')
record('STATUS=PASS')
report:close()
