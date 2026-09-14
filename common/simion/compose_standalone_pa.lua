-- Compose detached solved PAs without opening or creating a native PA family.
--
-- Usage:
--   simion --nogui --noprompt lua compose_standalone_pa.lua \
--     BASE.pa OUTPUT.pa RESPONSE.pa,COEFFICIENT [RESPONSE.pa,COEFFICIENT ...]

local base_path = assert(arg[1], 'standalone BASE.pa required')
local output_path = assert(arg[2], 'new standalone OUTPUT.pa required')

local function file_exists(path)
  local handle = io.open(path, 'rb')
  if handle then handle:close(); return true end
  return false
end

local function standalone_surface_path(path)
  return path:gsub('%.[pP][aA]$', '.pa-surf')
end

local function finite_number(text, label)
  local value = tonumber(text)
  assert(value and value == value and value ~= math.huge and value ~= -math.huge,
         label .. ' must be finite')
  return value
end

local function require_standalone_input(path, role)
  assert(path:match('%.[pP][aA]$'), role .. ' must use the standalone .pa suffix')
  assert(file_exists(path), role .. ' does not exist')
  assert(not file_exists(standalone_surface_path(path)),
         role .. ' uses unsupported surface metadata; surface=none is required')
end

assert(base_path ~= output_path, 'composition must not overwrite its base')
require_standalone_input(base_path, 'base PA')
assert(output_path:match('%.[pP][aA]$'), 'output must use the standalone .pa suffix')
assert(not file_exists(output_path), 'standalone output already exists')
assert(not file_exists(standalone_surface_path(output_path)),
       'standalone output surface companion already exists')

local responses = {}
local seen_paths = {}
for index = 3, #arg do
  -- Greedy path capture permits commas inside a Windows path; the final comma
  -- separates the coefficient.
  local path, coefficient_text = arg[index]:match('^(.*),([^,]+)$')
  assert(path and path ~= '' and coefficient_text,
         'each response entry must use the form PATH.pa,COEFFICIENT')
  require_standalone_input(path, 'response PA')
  assert(path ~= output_path, 'composition must not overwrite a response PA')
  assert(not seen_paths[path], 'duplicate response PA path')
  seen_paths[path] = true
  responses[#responses + 1] = {
    path = path,
    coefficient = finite_number(coefficient_text, 'response coefficient'),
  }
end
assert(#responses > 0, 'at least one standalone response is required')

local function same_grid(left, right)
  return left.nx == right.nx and left.ny == right.ny and left.nz == right.nz and
    left.symmetry == right.symmetry and
    left.dx_mm == right.dx_mm and left.dy_mm == right.dy_mm and
    left.dz_mm == right.dz_mm and left.potential_type == right.potential_type and
    (left.potential_type ~= 'magnetic' or left.ng == right.ng)
end

simion.pas:close()
local base_pa = assert(simion.pas:open(base_path), 'cannot open standalone base PA')
local output_pa = assert(simion.pas:open(), 'cannot create standalone output PA')
output_pa:size(base_pa.nx, base_pa.ny, base_pa.nz)
output_pa.symmetry = base_pa.symmetry
output_pa.dx_mm, output_pa.dy_mm, output_pa.dz_mm =
  base_pa.dx_mm, base_pa.dy_mm, base_pa.dz_mm
output_pa.potential_type = base_pa.potential_type
if base_pa.potential_type == 'magnetic' then output_pa.ng = base_pa.ng end

local copied = pcall(function() output_pa:copy(base_pa) end)
local copy_mode = 'native_copy'
if not copied then
  copy_mode = 'point_fallback'
  for x, y, z in base_pa:points() do
    local potential, is_electrode = base_pa:point(x, y, z)
    output_pa:point(x, y, z, potential, is_electrode)
  end
end
base_pa:close()

-- SIMION 2020 provides native whole-PA copy/scale operations, but no documented
-- bulk operation that adds several PA arrays.  Keep all responses open and
-- traverse the output grid exactly once; otherwise N responses cause N full
-- reads and N full writes of a multi-gigabyte output. potential_add changes
-- only the potential and leaves the base electrode flag intact. The explicit
-- fallback reads and writes the same preserved flag once per output node.
local native_add = output_pa.potential_add ~= nil
local add_mode = native_add and 'native_potential_add' or 'point_fallback'
for _, response in ipairs(responses) do
  response.pa = assert(simion.pas:open(response.path),
                       'cannot open standalone response PA')
  assert(same_grid(output_pa, response.pa),
         'response PA grid, symmetry, or potential type differs from the base')
end

for x, y, z in output_pa:points() do
  local delta = 0
  for _, response in ipairs(responses) do
    if response.coefficient ~= 0 then
      delta = delta + response.coefficient * response.pa:potential(x, y, z)
    end
  end
  if delta ~= 0 then
    if native_add then
      output_pa:potential_add(x, y, z, delta)
    else
      local potential, is_electrode = output_pa:point(x, y, z)
      output_pa:point(x, y, z, potential + delta, is_electrode)
    end
  end
end

for _, response in ipairs(responses) do
  response.pa:close()
end

output_pa.refined = true
output_pa.refinable = false
output_pa:save(output_path)
output_pa:close()
assert(file_exists(output_path), 'standalone output was not written')

print(string.format(
  'STANDALONE_PA_COMPOSITION=PASS responses=%d copy_mode=%s add_mode=%s output=%s',
  #responses, copy_mode, add_mode, output_path))
