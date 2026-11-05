-- Detach one already-solved ordinary/controller PA into a fresh standalone PA.
--
-- This is a build-stage migration tool for a retained operating PA whose
-- historical filename ends in .pa0. It must never be used to disguise a
-- native response member (.paN, N > 0) as standalone.
--
-- Usage:
--   simion --nogui --noprompt lua export_detached_standalone_pa.lua \
--     SOURCE.pa0 OUTPUT.pa

local source = assert(arg[1], 'solved source PA required')
local output = assert(arg[2], 'new standalone output PA required')

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
assert(file_exists(source), 'source PA does not exist')
assert(not file_exists(output), 'standalone output already exists')
assert(not file_exists(surface_path(source)),
       'surface-enhanced source PAs are unsupported; surface=none is required')
assert(not file_exists(surface_path(output)),
       'standalone output surface companion already exists')

simion.pas:close()
local source_pa = assert(simion.pas:open(source), 'cannot open source PA')
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

-- These in-memory flags document intent, but SIMION 2020 does not persist
-- pa.refined reliably. Persistent qualification comes from the owning build
-- receipt, byte manifest, and independent reopen/node checks.
output_pa.refined = true
output_pa.refinable = false
output_pa:save(output)
output_pa:close()
source_pa:close()
assert(file_exists(output), 'standalone output was not written')

print(string.format(
  'DETACHED_STANDALONE_PA_EXPORT=PASS copy_mode=%s source=%s output=%s',
  copy_mode, source, output))
