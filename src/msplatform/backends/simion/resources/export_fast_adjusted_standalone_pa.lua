-- Materialize one complete native Fast Adjust operating point as a detached PA.
--
-- The source family must live in a writable, disposable build-staging
-- directory.  Never open a published/cache family with this tool.
--
-- Usage:
--   simion --nogui --noprompt lua export_fast_adjusted_standalone_pa.lua \
--     SOURCE.pa0 OUTPUT.pa RECEIPT.json ID=V [ID=V ...]

local source = assert(arg[1], 'native family controller SOURCE.pa0 required')
local output = assert(arg[2], 'new standalone OUTPUT.pa required')
local receipt_path = assert(arg[3], 'boundary-mask restoration receipt required')

local function file_exists(path)
  local handle = io.open(path, 'rb')
  if handle then handle:close(); return true end
  return false
end

local function surface_path(path, suffix_pattern)
  return path:gsub(suffix_pattern, '.pa-surf')
end

local function finite_number(text, label)
  local value = tonumber(text)
  assert(value and value == value and value ~= math.huge and value ~= -math.huge,
         label .. ' must be finite')
  return value
end

assert(source ~= output, 'standalone export must not overwrite its source')
assert(source:match('%.[pP][aA]0$'), 'source must be a native .pa0 family controller')
assert(output:match('%.[pP][aA]$'), 'output must use the standalone .pa suffix')
assert(receipt_path:match('%.json$'), 'boundary-mask receipt must use the .json suffix')
assert(file_exists(source), 'source PA-family controller does not exist')
assert(not file_exists(output), 'standalone output already exists')
assert(not file_exists(receipt_path), 'boundary-mask receipt already exists')
assert(not file_exists(surface_path(source, '%.[pP][aA]0$')),
       'surface-enhanced PA families are unsupported; source must use surface=none')
assert(not file_exists(surface_path(output, '%.[pP][aA]$')),
       'standalone output surface companion already exists')

local voltages = {}
local supplied_count = 0
for index = 4, #arg do
  local electrode_text, voltage_text = arg[index]:match('^([1-9]%d*)=(.+)$')
  assert(electrode_text and voltage_text,
         'each operating-point entry must use the form positive_ID=V')
  local electrode = tonumber(electrode_text)
  assert(voltages[electrode] == nil, 'duplicate operating-point electrode ID')
  voltages[electrode] = finite_number(voltage_text, 'operating-point voltage')
  supplied_count = supplied_count + 1
end
assert(supplied_count > 0, 'complete operating-point ID=V table required')

simion.pas:close()
local source_pa = assert(simion.pas:open(source), 'cannot open native family controller')

-- A partial voltage table silently leaves omitted electrodes at an implicit
-- value.  Reject it by comparing with the controller's official inventory.
local expected = {}
local expected_count = 0
for _, electrode in ipairs(source_pa.electrode_numbers) do
  if electrode > 0 then
    expected[electrode] = true
    expected_count = expected_count + 1
  end
end
assert(expected_count > 0, 'source family has no positive adjustable electrodes')
assert(supplied_count == expected_count,
       'operating-point table is incomplete or contains an unknown electrode ID')
for electrode in pairs(voltages) do
  assert(expected[electrode], 'operating-point table contains an unknown electrode ID')
end
for electrode in pairs(expected) do
  assert(voltages[electrode] ~= nil,
         'operating-point table omits an adjustable electrode ID')
end

source_pa:fast_adjust(voltages)

-- Saving the family controller under another name can retain family semantics.
-- A new PA object establishes the standalone boundary explicitly.
local output_pa = assert(simion.pas:open(), 'cannot create standalone PA')
output_pa:size(source_pa.nx, source_pa.ny, source_pa.nz)
output_pa.symmetry = source_pa.symmetry
output_pa.dx_mm, output_pa.dy_mm, output_pa.dz_mm =
  source_pa.dx_mm, source_pa.dy_mm, source_pa.dz_mm
output_pa.potential_type = source_pa.potential_type
if source_pa.potential_type == 'magnetic' then output_pa.ng = source_pa.ng end

local copy_mode
if output_pa.copy then
  output_pa:copy(source_pa)
  copy_mode = 'native_copy'
else
  copy_mode = 'point_fallback'
  for x, y, z in source_pa:points() do
    local potential, is_electrode = source_pa:point(x, y, z)
    output_pa:point(x, y, z, potential, is_electrode)
  end
end

-- Dirichlet basis construction deliberately marks every outer boundary node
-- as an electrode.  The detached operating PA must retain those potentials,
-- but only the same-prefix raw PA# is authoritative for physical geometry.
-- Restore flags on six disjoint faces so edges and corners are visited once.
local template_path = source:gsub('0$', '#')
assert(file_exists(template_path), 'same-prefix physical geometry PA# is missing')
local template_pa = assert(simion.pas:open(template_path),
                           'cannot open same-prefix physical geometry PA#')
assert(output_pa.nx == template_pa.nx and output_pa.ny == template_pa.ny and
       output_pa.nz == template_pa.nz,
       'standalone output and physical geometry dimensions differ')
assert(output_pa.dx_mm == template_pa.dx_mm and
       output_pa.dy_mm == template_pa.dy_mm and
       output_pa.dz_mm == template_pa.dz_mm,
       'standalone output and physical geometry cell sizes differ')
assert(output_pa.nx >= 3 and output_pa.ny >= 3 and output_pa.nz >= 3,
       'standalone boundary restoration requires at least three points per axis')
local boundary_points, physical_flags, cleared_flags = 0, 0, 0
local function restore_boundary_flag(ix, iy, iz)
  local physical = template_pa:electrode(ix, iy, iz)
  local exported = output_pa:electrode(ix, iy, iz)
  assert(not physical or exported,
         'standalone export lost a physical boundary electrode')
  if physical then
    physical_flags = physical_flags + 1
  elseif exported then
    output_pa:electrode(ix, iy, iz, false)
    cleared_flags = cleared_flags + 1
  end
  boundary_points = boundary_points + 1
end
for iz = 0, output_pa.nz - 1 do
  for iy = 0, output_pa.ny - 1 do
    restore_boundary_flag(0, iy, iz)
    restore_boundary_flag(output_pa.nx - 1, iy, iz)
  end
end
for iz = 0, output_pa.nz - 1 do
  for ix = 1, output_pa.nx - 2 do
    restore_boundary_flag(ix, 0, iz)
    restore_boundary_flag(ix, output_pa.ny - 1, iz)
  end
end
for iy = 1, output_pa.ny - 2 do
  for ix = 1, output_pa.nx - 2 do
    restore_boundary_flag(ix, iy, 0)
    restore_boundary_flag(ix, iy, output_pa.nz - 1)
  end
end
local expected_boundary_points =
  2 * output_pa.ny * output_pa.nz +
  2 * (output_pa.nx - 2) * output_pa.nz +
  2 * (output_pa.nx - 2) * (output_pa.ny - 2)
assert(boundary_points == expected_boundary_points,
       'disjoint standalone boundary traversal is incomplete')

output_pa.refined = true
output_pa.refinable = false
output_pa:save(output)
output_pa:close()
source_pa:close()
template_pa:close()
assert(file_exists(output), 'standalone output was not written')

local function basename(path)
  return path:match('[^/\\]+$') or path
end
local function json_string(text)
  return text:gsub('\\', '\\\\'):gsub('"', '\\"')
end
local receipt = assert(io.open(receipt_path, 'w'))
receipt:write(string.format(
  '{"schema_version":1,"role":"simion_fast_adjusted_standalone_pa_export",' ..
  '"policy_id":"physical_geometry_boundary_flags_v1","status":"pass",' ..
  '"potential_operation":"unchanged_official_electrode_setter",' ..
  '"source_controller_basename":"%s","physical_template_basename":"%s",' ..
  '"output_basename":"%s","adjustable_electrode_count":%d,' ..
  '"boundary_points":%d,"physical_boundary_flags":%d,' ..
  '"cleared_synthetic_boundary_flags":%d,"copy_mode":"%s"}\n',
  json_string(basename(source)), json_string(basename(template_path)),
  json_string(basename(output)), supplied_count,
  boundary_points, physical_flags, cleared_flags, copy_mode))
receipt:close()

print(string.format(
  'FAST_ADJUSTED_STANDALONE_PA=PASS electrodes=%d copy_mode=%s boundary_points=%d physical_flags=%d cleared_flags=%d source=%s output=%s receipt=%s',
  supplied_count, copy_mode, boundary_points, physical_flags, cleared_flags,
  source, output, receipt_path))
