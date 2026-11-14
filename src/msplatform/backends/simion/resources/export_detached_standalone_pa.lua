-- Detach one already-solved ordinary/controller PA into a fresh standalone PA.
--
-- This is a build-stage migration tool for a retained operating PA whose
-- historical filename ends in .pa0. It must never be used to disguise a
-- native response member (.paN, N > 0) as standalone.
--
-- Usage:
--   simion --nogui --noprompt lua export_detached_standalone_pa.lua \
--     SOURCE.pa0 OUTPUT.pa [WORKPOINT.lua]

local source = assert(arg[1], 'solved source PA required')
local output = assert(arg[2], 'new standalone output PA required')
local workpoint_path = arg[3]

local function file_exists(path)
  local handle = io.open(path, 'rb')
  if handle then handle:close(); return true end
  return false
end

local function surface_path(path)
  return path:gsub('%.[pP][aA]0?$', '.pa-surf')
end

assert(source ~= output, 'standalone detachment must not overwrite its source')
assert(source:match('%.[pP][aA]0?$'),
       'source must be an ordinary .pa or controller-form .pa0, never .paN')
assert(not source:match('%.[pP][aA][1-9]%d*$'),
       'native PA-family response members are forbidden')
assert(output:match('%.[pP][aA]$'), 'output must use the standalone .pa suffix')
if workpoint_path then
  assert(source:match('%.[pP][aA]0$'), 'workpoint requires controller .pa0 source')
end
assert(file_exists(source), 'source PA does not exist')
assert(not file_exists(output), 'standalone output already exists')
local source_has_surface = file_exists(surface_path(source))
assert(not file_exists(surface_path(output)),
       'standalone output surface companion already exists')

simion.pas:close()
local source_pa = assert(simion.pas:open(source), 'cannot open source PA')
if workpoint_path then
  local workpoint = assert(loadfile(workpoint_path), 'cannot load frozen workpoint')()
  assert(type(workpoint) == 'table' and type(workpoint.native_voltages) == 'table', 'workpoint native_voltages required')
  for key in pairs(workpoint) do assert(key == 'native_voltages', 'workpoint has unknown fields') end
  local count = 0
  for id, value in pairs(workpoint.native_voltages) do
    assert(type(id) == 'number' and id > 0 and id < math.huge and id % 1 == 0, 'workpoint native electrode ID must be a positive integer')
    assert(type(value) == 'number' and value == value and math.abs(value) < math.huge, 'workpoint voltage must be finite')
    count = count + 1
  end
  assert(count > 0, 'workpoint native_voltages must be nonempty')
  -- The producer has already checked exact family/model coverage. Lua table
  -- keys are unique after evaluation; overwritten duplicate literals cannot be detected here.
  source_pa:fast_adjust(workpoint.native_voltages)
end
local output_pa = assert(simion.pas:open(), 'cannot create standalone output PA')
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

-- A saved enhanced source carries a companion. Transfer each actual nonempty
-- offset tuple after the full node copy; nil components stay nil. SIMION 2020
-- documents each nonnil component in the open interval (0,1).
local surface_nodes = 0
if source_has_surface then
  assert(source_pa.surface_info and output_pa.surface_info, 'surface_info API required for enhanced source')
  local function valid_offset(value)
    return value == nil or (type(value) == 'number' and value == value and value > 0 and value < 1)
  end
  for x, y, z in source_pa:points() do
    local sx, sy, sz = source_pa:surface_info(x, y, z)
    assert(valid_offset(sx) and valid_offset(sy) and valid_offset(sz), 'invalid surface offset')
    if sx ~= nil or sy ~= nil or sz ~= nil then
      output_pa:surface_info(x, y, z, sx, sy, sz)
      surface_nodes = surface_nodes + 1
    end
    local ax, ay, az = output_pa:surface_info(x, y, z)
    assert(ax == sx and ay == sy and az == sz, 'surface offset transfer differs')
  end
end

-- These in-memory flags document intent, but SIMION 2020 does not persist
-- pa.refined reliably. Persistent qualification comes from the owning build
-- receipt, byte manifest, and independent reopen/node checks.
output_pa.refined = true
output_pa.refinable = false
output_pa:save(output)
output_pa:close()
source_pa:close()
assert(file_exists(output), 'standalone output was not written')
if source_has_surface and surface_nodes > 0 then
  assert(file_exists(surface_path(output)), 'standalone surface companion was not written')
end

print(string.format(
  'DETACHED_STANDALONE_PA_EXPORT=PASS copy_mode=%s source=%s output=%s',
  copy_mode, source, output))
