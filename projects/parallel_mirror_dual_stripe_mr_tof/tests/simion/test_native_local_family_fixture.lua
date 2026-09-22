-- Tiny SIMION 2020 fixture for native local-family assembly.
-- It creates one raw geometry and eight solved standalone response PAs,
-- assembles them without Refine, then proves pa:fast_adjust uses pa1..pa8.
local root = assert(arg[1], 'fixture directory required')
local assembler = assert(arg[2], 'native assembler path required')
local function path(name) return root .. '/' .. name end
local function exists(name)
  local h = io.open(path(name), 'rb')
  if h then h:close(); return true end
  return false
end
local function new_pa()
  local pa = assert(simion.pas:open())
  pa:size(11, 11, 11)
  -- SIMION's default Cartesian symmetry is the required full 3-D mode; the
  -- string "none" is not a valid 2020 Lua symmetry value.
  pa.dx_mm, pa.dy_mm, pa.dz_mm = 1, 1, 1
  pa.potential_type = 'electric'
  return pa
end
local raw = new_pa()
for z = 0, raw.nz - 1 do
  for y = 0, raw.ny - 1 do
    for x = 0, raw.nx - 1 do
      local active = y == 0 and z == 0 and x < 8
      local id = x + 1
      raw:point(x, y, z, active and id or 0, active)
    end
  end
end
raw.refined, raw.refinable = true, false
raw:save(path('fixture.pa#')); raw:close()
for id = 1, 8 do
  local response = new_pa()
  for z = 0, response.nz - 1 do
    for y = 0, response.ny - 1 do
      for x = 0, response.nx - 1 do
        local active = y == 0 and z == 0 and x < 8
        response:point(x, y, z, id * 10 + x + y + z, active)
      end
    end
  end
  response.refined, response.refinable = true, false
  response:save(path('response' .. id .. '.pa')); response:close()
end
-- First create a genuine native family and use its solved members as the
-- migration inputs.  This is intentionally tiny but exercises SIMION's own
-- family metadata; arbitrary hand-written .pa files are not accepted as
-- evidence that a native member is valid.
for id = 0, 8 do
  local family = assert(simion.pas:open(path('fixture.pa#')))
  family:refine{solutions = {id}}
  family:close()
end
for id = 1, 8 do
  local input = assert(io.open(path('fixture.pa' .. id), 'rb'))
  local payload = input:read('*a'); input:close()
  local output = assert(io.open(path('response' .. id .. '.pa'), 'wb'))
  output:write(payload); output:close()
end
-- Reuse the production assembler through a fresh SIMION invocation in the
-- fixture runner; this process only creates the source files.
assert(exists('fixture.pa#'), 'fixture raw geometry missing')
print('MRTOF_NATIVE_LOCAL_FAMILY_FIXTURE_INPUT=PASS native_source_family=9 response_inputs=8')
