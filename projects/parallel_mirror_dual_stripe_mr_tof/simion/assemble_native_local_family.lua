-- Assemble one native SIMION Fast-Adjust family from already solved members.
--
-- This is a migration/pilot tool, not a Refine entry point.  The response
-- members must be freshly constructed standalone PA objects with the same
-- grid as the raw local geometry.  The raw PA# is used only to construct the
-- zero-voltage controller; no published cache path is opened by this script.
--
-- Usage:
--   simion --nogui --noprompt lua assemble_native_local_family.lua \
--     RAW.pa# OUTPUT.pa0 ID=RESPONSE.pa ID=RESPONSE.pa ...

local append_mode = arg[1] == '--append'
local raw_path, output
if not append_mode then
  raw_path = assert(arg[1], 'raw local PA# required')
  output = assert(arg[2], 'native family controller .pa0 required')
  assert(raw_path:match('%.[pP][aA]#$'), 'raw input must end in .pa#')
  assert(output:match('%.[pP][aA]0$'), 'output must end in .pa0')
  assert(raw_path ~= output, 'raw and controller paths must differ')
end

local function exists(path)
  local handle = io.open(path, 'rb')
  if handle then handle:close(); return true end
  return false
end

local function copy_bytes(source, destination)
  assert(source ~= destination, 'copy would overwrite its source')
  local input = assert(io.open(source, 'rb'), 'cannot read raw geometry: ' .. source)
  local payload = input:read('*a'); input:close()
  local output_file = assert(io.open(destination, 'wb'), 'cannot write native raw geometry: ' .. destination)
  output_file:write(payload); output_file:close()
end

local function finite(value, label)
  assert(type(value) == 'number' and value == value and
    math.abs(value) < math.huge, label .. ' must be finite')
  return value
end

local function copy_common(source, destination, label)
  assert(source ~= destination, label .. ' would overwrite its source')
  local input = assert(simion.pas:open(source), 'cannot open ' .. label .. ' source: ' .. source)
  local output_pa = assert(simion.pas:open(), 'cannot create ' .. label .. ' output')
  output_pa:size(input.nx, input.ny, input.nz)
  output_pa.symmetry = input.symmetry
  output_pa.dx_mm, output_pa.dy_mm, output_pa.dz_mm = input.dx_mm, input.dy_mm, input.dz_mm
  output_pa.potential_type = input.potential_type
  if input.potential_type == 'magnetic' then output_pa.ng = input.ng end
  local copied = pcall(function() output_pa:copy(input) end)
  if not copied then
    for x, y, z in input:points() do
      local potential, electrode = input:point(x, y, z)
      output_pa:point(x, y, z, finite(potential, label .. ' potential'), electrode)
    end
  end
  output_pa.refined = true
  output_pa.refinable = false
  output_pa:save(destination)
  output_pa:close()
  input:close()
  assert(exists(destination), label .. ' output was not written: ' .. destination)
end

-- Stream one protected standalone private copy at a time. This reuses exactly
-- the same new-object export as complete assembly, without retaining a second
-- eight-response bank while the native execution family is being assembled.
if append_mode then
  local source = assert(arg[2], 'standalone response required')
  local destination = assert(arg[3], 'native response destination required')
  assert(#arg == 3 and source:match('%.pa$'), 'append requires one standalone .pa source')
  assert(destination:match('%.pa[1-8]$'), 'append destination must be native .pa1..pa8')
  assert(not exists(destination), 'native response output already exists')
  copy_common(source, destination, 'streamed response')
  print('MRTOF_NATIVE_CORRIDOR_APPEND=PASS source=' .. source .. ' destination=' .. destination)
  return
end

local prefix = output:gsub('%.[pP][aA]0$', '')
local native_raw = prefix .. '.pa#'
assert(not exists(output), 'native family controller destination already exists')
-- A native controller carries solver family metadata.  A manually zeroed PA
-- is not sufficient: SIMION reports no adjustable inventory and rejects
-- Fast Adjust.  One tiny `solutions={0}` refine creates only that controller;
-- all voltage response members below are reused without another Refine.
if raw_path ~= native_raw then
  assert(not exists(native_raw), 'native family destination already contains a raw/controller member')
  copy_bytes(raw_path, native_raw)
end
local raw = assert(simion.pas:open(native_raw), 'cannot open staged raw local geometry')
assert(raw.nx >= 3 and raw.ny >= 3 and raw.nz >= 3, 'native family grid is too small')
assert(raw.dx_mm > 0 and raw.dy_mm > 0 and raw.dz_mm > 0, 'native family mesh must be positive')
local raw_nx, raw_ny, raw_nz = raw.nx, raw.ny, raw.nz
local raw_dx, raw_dy, raw_dz = raw.dx_mm, raw.dy_mm, raw.dz_mm
raw:refine{solutions={0}}
raw:close()
assert(exists(output), 'native family controller was not written by solutions={0}')

local seen = {}
local count = 0
for index = 3, #arg do
  local id_text, source = arg[index]:match('^([1-9]%d*)=(.+)$')
  local id = assert(tonumber(id_text), 'response assignment must use ID=PATH')
  assert(id == math.floor(id) and id >= 1 and id <= 8, 'local response ID must be in 1..8')
  assert(not seen[id], 'duplicate local response ID: ' .. id)
  assert(source:match('%.[pP][aA]$'), 'response source must be a standalone .pa: ' .. source)
  assert(exists(source), 'response source is missing: ' .. source)
  local destination = prefix .. '.pa' .. id
  assert(not exists(destination), 'native response output already exists: ' .. destination)
  local check = assert(simion.pas:open(source), 'cannot inspect response source: ' .. source)
  assert(check.nx == raw_nx and check.ny == raw_ny and check.nz == raw_nz,
    'response grid dimensions differ for local ID ' .. id)
  assert(check.dx_mm == raw_dx and check.dy_mm == raw_dy and check.dz_mm == raw_dz,
    'response mesh differs for local ID ' .. id)
  -- SIMION 2020 does not persist the `refined` boolean consistently for a
  -- standalone PA.  The producer-side contract proves it was solved; here
  -- the important safety property is that the migration never receives a
  -- refinable writable response.
  assert(check.refinable ~= true, 'response remains refinable for local ID ' .. id)
  check:close()
  copy_common(source, destination, 'response ' .. id)
  seen[id] = true
  count = count + 1
end
assert(count > 0, 'at least one response member is required')
for id = 1, 8 do
  assert(seen[id], 'native migration requires the complete local response namespace 1..8')
end

-- Reopen the controller with its family members and exercise the official
-- Fast Adjust path.  This catches the tempting but invalid “rename .pa to
-- .paN” migration before a real PA is handed to an IOB.
local adjusted = assert(simion.pas:open(output), 'cannot reopen native family controller')
local inventory = adjusted.electrode_numbers
assert(type(inventory) == 'table' and #inventory > 0, 'controller has no adjustable electrode inventory')
assert(#inventory == 8, 'native local controller must expose exactly local IDs 1..8')
for _, id in ipairs(inventory) do
  assert(id >= 1 and id <= 8 and id == math.floor(id),
    'fixed/absent physical IDs leaked into native local inventory')
end
local values = {}
for _, id in ipairs(inventory) do
  if id > 0 then values[id] = (id == 1) and 4000 or ((id == 2) and -2500 or 0) end
end
adjusted:fast_adjust(values)
local probe = assert(adjusted:point(5, 5, 5))
local response_one = assert(simion.pas:open(assert(arg[3]):match('^1=(.+)$')))
local response_two = assert(simion.pas:open(assert(arg[4]):match('^2=(.+)$')))
local one = response_one:point(5, 5, 5)
local two = response_two:point(5, 5, 5)
local expected = one * 0.4 + two * -0.25
response_one:close(); response_two:close()
assert(math.abs(probe - expected) < 1e-6,
  string.format('native Fast Adjust response mismatch: got %.17g expected %.17g', probe, expected))
adjusted:close()
local reopened = assert(simion.pas:open(output), 'cannot reopen assembled native family')
reopened:fast_adjust({[1] = 2000, [2] = 1500})
local reopened_probe = assert(reopened:point(5, 5, 5))
assert(math.abs(reopened_probe - (one * 0.2 + two * 0.15)) < 1e-6,
  'native Fast Adjust did not survive controller close/reopen')
reopened:close()
print(string.format('MRTOF_NATIVE_LOCAL_FAMILY_ASSEMBLY=PASS controller=%s responses=%d fast_adjust=verified inventory=%d', output, count, #inventory))
