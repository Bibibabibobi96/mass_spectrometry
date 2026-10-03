-- Reconstruct a private native Fast Adjust family from one raw PA# and
-- manifest-bound standalone response objects.  Published .paN members are
-- never accepted by this helper.
--
-- Usage:
--   ... --controller RAW.pa# OUTPUT.pa0 EXPECTED_COUNT
--   ... --append RESPONSE.pa OUTPUT.paN

local mode = assert(arg[1], 'mode is required')

local function exists(path)
  local handle = io.open(path, 'rb')
  if handle then handle:close(); return true end
  return false
end

local function finite(value, label)
  assert(type(value) == 'number' and value == value and math.abs(value) < math.huge,
    label .. ' must be finite')
  return value
end

local function copy_standalone(source, destination)
  assert(source:match('%.[pP][aA]$'), 'response source must be a standalone .pa')
  assert(destination:match('%.[pP][aA][1-9]%d*$'), 'response destination must use a positive .paN suffix')
  assert(not exists(destination), 'native response output already exists')
  local input = assert(simion.pas:open(source), 'cannot open standalone response: ' .. source)
  assert(input.refinable ~= true, 'standalone response must not be refinable')
  local output = assert(simion.pas:open(), 'cannot create native response object')
  output:size(input.nx, input.ny, input.nz)
  output.symmetry = input.symmetry
  output.dx_mm, output.dy_mm, output.dz_mm = input.dx_mm, input.dy_mm, input.dz_mm
  output.potential_type = input.potential_type
  if input.potential_type == 'magnetic' then output.ng = input.ng end
  local copied = pcall(function() output:copy(input) end)
  if not copied then
    for x, y, z in input:points() do
      local potential, electrode = input:point(x, y, z)
      output:point(x, y, z, finite(potential, 'response potential'), electrode)
    end
  end
  output.refined = true
  output.refinable = false
  output:save(destination)
  output:close(); input:close()
  assert(exists(destination), 'native response output was not written')
end

if mode == '--append' then
  assert(#arg == 3, 'append requires one standalone source and one native destination')
  copy_standalone(assert(arg[2]), assert(arg[3]))
  print('NATIVE_FAST_ADJUST_RESPONSE_APPEND=PASS destination=' .. arg[3])
  return
end

assert(mode == '--controller', 'mode must be --controller or --append')
local raw_path = assert(arg[2], 'raw PA# is required')
local output = assert(arg[3], 'controller PA0 is required')
local expected_count = assert(tonumber(arg[4]), 'expected response count is required')
assert(expected_count == math.floor(expected_count) and expected_count > 0,
  'expected response count must be a positive integer')
assert(raw_path:match('%.[pP][aA]#$'), 'raw input must end in .pa#')
assert(output:match('%.[pP][aA]0$'), 'controller output must end in .pa0')
assert(raw_path == output:gsub('%.[pP][aA]0$', '.pa#'),
  'raw and controller must share one private family prefix')
assert(not exists(output), 'controller output already exists')
local raw = assert(simion.pas:open(raw_path), 'cannot open private raw PA#')
assert(raw.nx >= 3 and raw.ny >= 3 and raw.nz >= 3, 'native family grid is too small')
raw:refine{solutions={0}}
raw:close()
assert(exists(output), 'solutions={0} did not create the controller')
local controller = assert(simion.pas:open(output), 'cannot reopen private controller')
local inventory = controller.electrode_numbers
assert(type(inventory) == 'table' and #inventory == expected_count,
  'controller adjustable inventory count differs')
local seen = {}
for _, identifier in ipairs(inventory) do
  assert(type(identifier) == 'number' and identifier == math.floor(identifier)
    and identifier >= 1 and identifier <= expected_count,
    'controller adjustable inventory is invalid')
  assert(not seen[identifier], 'controller adjustable inventory contains duplicates')
  seen[identifier] = true
end
for identifier = 1, expected_count do
  assert(seen[identifier], 'controller is missing adjustable electrode ' .. identifier)
end
controller:close()
print(string.format('NATIVE_FAST_ADJUST_CONTROLLER=PASS responses=%d', expected_count))
