-- Verify a complete native corridor family and exercise Fast Adjust.
local controller_path = assert(arg[1], 'corridor controller PA0 required')
local native_reference_voltage = 10000
local prefix = controller_path:gsub('%.pa0$', '')
local function exists(path)
  local f = io.open(path, 'rb'); if f then f:close(); return true end; return false
end
for id = 1, 8 do assert(exists(prefix .. '.pa' .. id), 'corridor member is missing: ' .. id) end
local family = assert(simion.pas:open(controller_path), 'cannot open corridor controller')
local inventory = family.electrode_numbers
assert(type(inventory) == 'table' and #inventory == 8, 'corridor inventory is incomplete at final verification')
local seen = {}
for _, id in ipairs(inventory) do
  assert(type(id) == 'number' and id == math.floor(id) and id >= 1 and id <= 8,
    'corridor inventory contains an invalid local electrode ID')
  assert(not seen[id], 'corridor inventory contains duplicate local electrode ID ' .. id)
  seen[id] = true
end
for id = 1, 8 do assert(seen[id], 'corridor inventory is missing local electrode ID ' .. id) end
local function complete_values()
  local values = {}
  for id = 1, 8 do values[id] = 0 end
  return values
end
local probes = {}
for _, fx in ipairs{0.25, 0.5, 0.75} do
  for _, fy in ipairs{0.25, 0.5, 0.75} do
    for _, fz in ipairs{0.25, 0.5, 0.75} do
      probes[#probes + 1] = {
        math.floor((family.nx - 1) * fx + 0.5),
        math.floor((family.ny - 1) * fy + 0.5),
        math.floor((family.nz - 1) * fz + 0.5),
      }
    end
  end
end
local function close_enough(observed, expected)
  return math.abs(observed - expected) <= 2e-6 * math.max(1, math.abs(expected))
end
local responses = {}
local signal_count = 0
for id = 1, 8 do
  local response = assert(simion.pas:open(prefix .. '.pa' .. id),
    'cannot open corridor response member ' .. id)
  local minimum, maximum = response:potentials_minmax()
  assert(math.abs(maximum - native_reference_voltage) <= 2e-6 * native_reference_voltage,
    string.format('corridor response %d is not a canonical 10000 V native basis: min=%.17g max=%.17g',
      id, minimum, maximum))
  assert(minimum >= -2e-6 * native_reference_voltage,
    string.format('corridor response %d has an invalid negative basis minimum: %.17g', id, minimum))
  local samples = {}
  for index, probe in ipairs(probes) do
    local expected = assert(response:point(probe[1], probe[2], probe[3]))
    samples[index] = expected
    if math.abs(expected) > 1e-8 then signal_count = signal_count + 1 end
  end
  responses[id] = samples
  response:close()
end
assert(signal_count > 0, 'corridor Fast Adjust probes contain no response signal')

local combination = {4000, -2500, 1750, 900, -25, 50, 225, -180}
local values = complete_values()
for id = 1, 8 do values[id] = combination[id] end
family:fast_adjust(values)
for index, probe in ipairs(probes) do
  local expected = 0
  for id = 1, 8 do
    expected = expected + combination[id] * responses[id][index] / native_reference_voltage
  end
  local observed = assert(family:point(probe[1], probe[2], probe[3]))
  assert(close_enough(observed, expected), string.format(
    'corridor Fast Adjust linear-combination mismatch: probe=%d observed=%.17g expected=%.17g',
    index, observed, expected))
end
family:close()

local reopened = assert(simion.pas:open(controller_path), 'cannot reopen corridor controller')
local reopen_combination = {-1700, 3100, 825, -475, 63, -41, -215, 340}
values = complete_values()
for id = 1, 8 do values[id] = reopen_combination[id] end
reopened:fast_adjust(values)
for index, probe in ipairs(probes) do
  local expected = 0
  for id = 1, 8 do
    expected = expected + reopen_combination[id] * responses[id][index] / native_reference_voltage
  end
  local observed = assert(reopened:point(probe[1], probe[2], probe[3]))
  assert(close_enough(observed, expected), string.format(
    'corridor Fast Adjust reopen mismatch: probe=%d observed=%.17g expected=%.17g',
    index, observed, expected))
end
reopened:close()
print(string.format('MRTOF_NATIVE_CORRIDOR_FAMILY_PROBES=PASS count=%d', #probes))
print('MRTOF_NATIVE_CORRIDOR_FAMILY_VERIFY=PASS members=pa0..pa8 fast_adjust=verified')
