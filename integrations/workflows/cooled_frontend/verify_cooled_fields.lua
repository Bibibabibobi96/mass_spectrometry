-- SIMION 2020 PA point API, as used by verify_local_frontend_fields.lua.
-- Bounded ordinary-working-field checks; not a field-convergence certificate.
local input = assert(io.open(assert(arg[1], 'specification required'), 'r'))
assert(input:read('*l') == 'cooled_working_field_verification_v1', 'invalid verification schema')
local grid, fields, samples = nil, {}, {}
local kinds = {'carrier_off','rf_differential_unit','entry_close_delta','release_delta',
  'pulse_delta','inner_auxiliary_unit','hp_common_unit'}
local allowed = {}; for _,kind in ipairs(kinds) do allowed[kind]=true end
local function split(line)
  local result = {}
  for value in (line..'\t'):gmatch('(.-)\t') do result[#result+1] = value end
  return result
end
for line in input:lines() do
  local row = split(line)
  if row[1] == 'grid' then
    assert(not grid and #row == 7, 'invalid grid')
    grid = {}; for i=2,7 do grid[i-1] = assert(tonumber(row[i])) end
  elseif row[1] == 'field' then
    assert(#row == 3 and allowed[row[2]] and not fields[row[2]] and row[3]:match('%.pa$'), 'invalid ordinary field')
    fields[row[2]] = row[3]
  elseif row[1] == 'metal' then
    assert(#row == 7, 'invalid physical sample')
    samples[row[2]] = samples[row[2]] or {}
    samples[row[2]][#samples[row[2]]+1] = row
  else error('unknown verification row') end
end
input:close()
local function close(a,b)
  -- Same imposed-voltage PA serialization budget as
  -- single_reflection_flight/audit_frontend_working_fields.lua.
  return type(a)=='number' and a==a and math.abs(a-b)<=math.max(1e-9,math.abs(b)*1e-12)
end
local report = assert(io.open(assert(arg[2], 'report required'), 'w'))
assert(grid, 'grid required')
simion.pas:close()
local count=0; for _ in pairs(fields) do count=count+1 end
assert(count>0 and count<=#kinds, 'one or more declared working members required')
for _,kind in ipairs(kinds) do if fields[kind] then
  local pa = assert(simion.pas:open(assert(fields[kind], 'working field missing')))
  assert(pa.potential_type=='electric' and pa.nx==grid[1] and pa.ny==grid[2] and pa.nz==grid[3], 'field grid/type differs')
  assert(pa.dx_mm==grid[4] and pa.dy_mm==grid[5] and pa.dz_mm==grid[6], 'field mesh differs')
  assert(samples[kind] and #samples[kind]>0, 'physical samples required')
  for _,row in ipairs(samples[kind]) do
    local x,y,z,v=assert(tonumber(row[4])),assert(tonumber(row[5])),assert(tonumber(row[6])),assert(tonumber(row[7]))
    assert(x>=0 and x<pa.nx and y>=0 and y<pa.ny and z>=0 and z<pa.nz, 'sample outside field')
    local value,metal=pa:point(x,y,z)
    assert(metal and close(value,v), 'physical metal/working voltage differs: '..kind..'/'..row[3])
    report:write(string.format('%s\t%s\t%.17g\n',kind,row[3],value))
  end
  for _,x in ipairs{0,pa.nx-1} do for _,y in ipairs{0,pa.ny-1} do for _,z in ipairs{0,pa.nz-1} do
    local value,metal=pa:point(x,y,z)
    assert(not metal and close(value,0), 'zero-Dirichlet far corner potential or physical mask differs')
  end end end
  pa:close()
end end
report:write('COOLED_WORKING_FIELDS=PASS scope=grid_provider_metal_samples_working_voltages_far_corners\n')
report:close()
print('COOLED_WORKING_FIELDS=PASS')
