-- Generate an independent standalone-response fixture for native-family
-- migration.  The response values are explicitly normalized to the SIMION
-- 10,000-V family basis and include non-zero Dirichlet boundary nodes.
-- Usage: ... lua test_native_local_family_standalone_fixture.lua DIRECTORY [missing_id]
local root = assert(arg[1], 'fixture directory required')
local missing = tonumber(arg[2] or '')
local function path(name) return root .. '/' .. name end
local function new_pa()
  local pa = assert(simion.pas:open())
  pa:size(11, 11, 11)
  pa.dx_mm, pa.dy_mm, pa.dz_mm = 1, 1, 1
  pa.potential_type = 'electric'
  return pa
end
local raw = new_pa()
for z = 0, raw.nz - 1 do
  for y = 0, raw.ny - 1 do
    for x = 0, raw.nx - 1 do
      local id = x + 1
      local active = y == 0 and z == 0 and x < 8 and id ~= missing
      raw:point(x, y, z, active and id or 0, active)
    end
  end
end
raw.refined, raw.refinable = true, false
raw:save(path('standalone.pa#')); raw:close()
for id = 1, 8 do
  local response = new_pa()
  for z = 0, response.nz - 1 do
    for y = 0, response.ny - 1 do
      for x = 0, response.nx - 1 do
        local boundary = y == 0 or y == response.ny - 1 or z == 0 or z == response.nz - 1
        local active = y == 0 and z == 0 and x < 8 and x + 1 ~= missing
        -- 10,000 V basis: a 4.1 kV Fast Adjust must produce 0.41 of
        -- this response at every node, including the synthetic boundary.
        response:point(x, y, z, 10000 * (id + 0.01 * x + 0.001 * y + 0.0001 * z),
          boundary or active)
      end
    end
  end
  response.refined, response.refinable = true, false
  response:save(path('standalone_response' .. id .. '.pa')); response:close()
end
print(string.format('MRTOF_NATIVE_LOCAL_STANDALONE_FIXTURE=PASS missing_id=%s nonzero_dirichlet=true basis_v=10000', missing or 'none'))
