-- Export one solved response from a private PA family as a true standalone PA.
--
-- The caller must create/refine the complete source family in a writable,
-- disposable build-staging directory.  Never point this helper at an immutable
-- cache generation or at a family copied from a published cache.
--
-- Usage:
--   simion --nogui --noprompt lua export_standalone_pa.lua SOURCE.paN OUTPUT.pa

local source = assert(arg[1], 'source PA-family member required')
local output = assert(arg[2], 'standalone output PA required')

local function file_exists(path)
  local handle = io.open(path, 'rb')
  if handle then handle:close(); return true end
  return false
end

assert(source ~= output, 'standalone export must not overwrite its source')
assert(source:match('%.[pP][aA]%d+$'), 'source must be a native .paN family member')
assert(output:match('%.[pP][aA]$'), 'output must use the standalone .pa suffix')
assert(file_exists(source), 'source PA-family member does not exist')
assert(not file_exists(output), 'standalone output already exists')

-- Fractional surface data live beside a PA family rather than in ordinary
-- node values.  Neither pa:copy nor the point fallback is authorized to drop
-- that data, so this exporter deliberately supports surface=none only.
local surface_path = source:gsub('%.[pP][aA]%d+$', '.pa-surf')
assert(not file_exists(surface_path),
       'surface-enhanced PA families are unsupported; source must use surface=none')

simion.pas:close()
local source_pa = assert(simion.pas:open(source), 'cannot open source PA-family member')
local output_pa = assert(simion.pas:open(), 'cannot create standalone PA')
output_pa:size(source_pa.nx, source_pa.ny, source_pa.nz)
output_pa.symmetry = source_pa.symmetry
output_pa.dx_mm, output_pa.dy_mm, output_pa.dz_mm =
  source_pa.dx_mm, source_pa.dy_mm, source_pa.dz_mm
output_pa.potential_type = source_pa.potential_type
if source_pa.potential_type == 'magnetic' then output_pa.ng = source_pa.ng end

local copied = pcall(function() output_pa:copy(source_pa) end)
local copy_mode = 'native_copy'
if not copied then
  copy_mode = 'point_fallback'
  for x, y, z in source_pa:points() do
    local potential, is_electrode = source_pa:point(x, y, z)
    output_pa:point(x, y, z, potential, is_electrode)
  end
end

-- This is a solved response, not a geometry definition to be refined again.
output_pa.refined = true
output_pa.refinable = false
output_pa:save(output)
output_pa:close()
source_pa:close()

print(string.format(
  'STANDALONE_PA_EXPORT=PASS copy_mode=%s source=%s output=%s',
  copy_mode, source, output))
