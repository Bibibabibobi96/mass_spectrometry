-- Create only the immutable native corridor raw/controller pair.
-- A caller appends pa1..pa8 one at a time; no response payload is retained here.
local raw_path = assert(arg[1], 'raw corridor PA# required')
local output = assert(arg[2], 'corridor controller PA0 required')
assert(raw_path:match('%.pa#$'), 'raw corridor input must end in .pa#')
assert(output:match('%.pa0$'), 'corridor controller must end in .pa0')
local function exists(path)
  local f = io.open(path, 'rb'); if f then f:close(); return true end; return false
end
local prefix = output:gsub('%.pa0$', '')
local native_raw = prefix .. '.pa#'
assert(not exists(output), 'corridor controller destination already exists')
assert(raw_path == native_raw,
  'controller PA# and PA0 must share one scratch prefix; cross-prefix copying is forbidden')
local raw = assert(simion.pas:open(native_raw), 'cannot open corridor raw PA#')
assert(raw.nx >= 3 and raw.ny >= 3 and raw.nz >= 3, 'corridor PA grid is too small')
raw:refine{solutions={0}}
raw:close()
assert(exists(output), 'controller refine did not create PA0')
local controller = assert(simion.pas:open(output), 'cannot reopen corridor controller')
local inventory = controller.electrode_numbers
assert(type(inventory) == 'table' and #inventory == 8, 'corridor controller must expose local IDs 1..8')
local seen = {}
for _, id in ipairs(inventory) do
  assert(type(id) == 'number' and id >= 1 and id <= 8 and id == math.floor(id),
    'invalid corridor electrode inventory')
  assert(not seen[id], 'duplicate corridor electrode ID: ' .. id)
  seen[id] = true
end
for id = 1, 8 do
  assert(seen[id], 'corridor controller is missing local electrode ID ' .. id)
end
controller:close()
print('MRTOF_NATIVE_CORRIDOR_CONTROLLER=PASS inventory=1..8')
