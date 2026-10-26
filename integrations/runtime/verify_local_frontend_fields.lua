-- Reopen ordinary responses using the SIMION 2020 PA API. This is a bounded
-- format/basis sample check, not a field accuracy or convergence certificate.
-- Usage: simion --nogui --noprompt lua THIS.lua specification.tsv output.tsv
local specification = assert(arg[1], 'verification specification required')
local output = assert(arg[2], 'verification output required')
local input = assert(io.open(specification, 'r'))
assert(input:read('*l') == 'local_frontend_response_verification_v4', 'invalid verification schema')
local function fields(line)
  local result = {}
  for value in (line .. '\t'):gmatch('(.-)\t') do result[#result + 1] = value end
  return result
end
local grid, responses, samples, model, mode_ids = nil, {}, {}, nil, {}
local physical = {}
local physical_count,rod_count
local supported_models = {two_zone_linear_ring_bare_octupole_pa_plus_v1=5,
  three_zone_linear_ring_bare_octupole_pa_plus_v1=6,
  three_zone_linear_ring_segmented_through_exit_pa_plus_v1=6}
for line in input:lines() do
  local row = fields(line)
  if row[1] == 'model' then
    assert(not model and supported_models[row[2]], 'unsupported or duplicate model declaration')
    model = row[2]
    local count = assert(tonumber(row[3]), 'invalid declared mode count')
    assert(count == supported_models[model] and #row == count + 3, 'mode count differs from supported model')
    local seen = {}
    for index=4,#row do
      local id=assert(tonumber(row[index]), 'invalid declared mode ID')
      assert(id>0 and id%1==0 and not seen[row[index]], 'invalid or repeated declared mode ID')
      if #mode_ids>0 then assert(id>tonumber(mode_ids[#mode_ids]), 'mode IDs must increase') end
      seen[row[index]]=true;mode_ids[#mode_ids+1]=row[index]
    end
  elseif row[1] == 'grid' then
    assert(not grid and #row == 7, 'invalid grid declaration')
    grid = {}
    for i = 2, 7 do grid[i - 1] = assert(tonumber(row[i]), 'invalid grid number') end
  elseif row[1] == 'response' then
    assert(#row == 3 and not responses[row[2]], 'duplicate response')
    assert(row[3]:match('%.pa$'), 'only ordinary standalone response inputs allowed')
    responses[row[2]] = row[3]
  elseif row[1] == 'physical_count' then
    assert(#row==3 and not physical_count, 'invalid physical count declaration')
    physical_count=assert(tonumber(row[2]));rod_count=assert(tonumber(row[3]))
  elseif row[1] == 'physical' then
    assert(#row==7 and not physical[row[2]], 'duplicate or malformed physical piece')
    local eid=assert(tonumber(row[3]), 'invalid physical electrode ID')
    assert(eid>0 and eid%1==0, 'invalid physical electrode ID')
    physical[row[2]]={id=eid,kind=row[4],x=tonumber(row[5]),y=tonumber(row[6]),z=tonumber(row[7])}
  elseif row[1] == 'sample' then
    assert(#row == 9, 'invalid sample declaration')
    samples[#samples + 1] = row
  else error('unknown verification row') end
end
input:close()
assert(grid and #samples > 0, 'incomplete verification specification')
local count = 0
for _ in pairs(responses) do count = count + 1 end
assert(model and count == #mode_ids, 'response count differs from declared model')
for _,id in ipairs(mode_ids) do assert(responses[id], 'declared response mode missing') end
assert(next(physical), 'explicit physical sample set required')
local actual_count,actual_rods=0,0
for _,body in pairs(physical) do actual_count=actual_count+1;if body.kind=='rod' then actual_rods=actual_rods+1 end end
assert(actual_count==physical_count and actual_rods==rod_count and rod_count>0,'declared physical piece coverage differs')
if arg[3]=='raw' then
  simion.pas:close()
  local pa=assert(simion.pas:open(assert(arg[4], 'raw template path required')))
  for label,body in pairs(physical) do
    assert(body.x and body.y and body.z, 'invalid raw sample coordinate')
    local value,metal=pa:point(body.x,body.y,body.z)
    assert(metal and value==body.id, 'raw physical electrode ID differs: '..label)
  end
  pa:close()
  local report=assert(io.open(output,'w'));report:write('RAW_PHYSICAL_IDS=PASS\n');report:close()
  print('RAW_PHYSICAL_IDS=PASS');return
end
local report = assert(io.open(output, 'w'))
report:write('frontend_mode_normalization_v4\n')
report:write(string.format('physical_count\t%d\t%d\n',physical_count,rod_count))
for label,body in pairs(physical) do
  report:write(string.format('physical\t%s\t%d\t%s\n',label,body.id,body.kind))
end
report:write('measurements\n')
report:write('mode_id\tlabel\tx_gu\ty_gu\tz_gu\tpotential_v\telectrode\texpected_coefficient\tbasis_reference_v\tnormalized_coefficient\tpolicy\n')
local function finite(value) return type(value) == 'number' and value == value and math.abs(value) < math.huge end
-- Existing declared-basis ratio check, not a field-convergence tolerance.
local function close(a, b) return finite(a) and math.abs(a - b) <= 1e-9 * math.max(1, math.abs(b)) end
simion.pas:close()
for _,id in ipairs(mode_ids) do
  local path=responses[id]
  local pa = assert(simion.pas:open(path), 'cannot reopen ordinary response')
  assert(pa.potential_type == 'electric', 'response must be electrostatic')
  assert(pa.nx == grid[1] and pa.ny == grid[2] and pa.nz == grid[3], 'response dimensions differ')
  assert(close(pa.dx_mm, grid[4]) and close(pa.dy_mm, grid[5]) and close(pa.dz_mm, grid[6]), 'response mesh differs')
  local observed, declared, anchor, values = 0, {}, nil, {}
  for _, row in ipairs(samples) do
    if row[2] == id then
      local x, y, z = assert(tonumber(row[4])), assert(tonumber(row[5])), assert(tonumber(row[6]))
      assert(x >= 0 and x < pa.nx and y >= 0 and y < pa.ny and z >= 0 and z < pa.nz, 'sample outside PA')
      local value, metal = pa:point(x, y, z)
      assert(finite(value), 'nonfinite sample potential')
      local expected = tonumber(row[8])
      assert(expected or row[8] == 'any', 'invalid expected coefficient')
      if row[7] ~= 'any' then assert(metal == (row[7] == '1'), 'sample electrode flag differs: ' .. row[3]) end
      assert(row[9] == 'declared_sample' or row[9] == 'unity_anchor', 'invalid sample policy')
      if row[9] == 'unity_anchor' then
        assert(not anchor and expected == 1 and metal and value ~= 0, 'invalid or duplicate physical unity anchor')
        anchor = value
      end
      local body=physical[row[3]]
      if body then
        assert(not declared[row[3]], 'duplicate physical piece sample')
        assert(x==body.x and y==body.y and z==body.z and metal, 'physical sample declaration differs')
        declared[row[3]]=true
      elseif row[7]=='1' then error('undeclared physical metal sample: '..row[3]) end
      values[#values+1] = {row=row,value=value,metal=metal,x=x,y=y,z=z,expected=expected}
      observed = observed + 1
    end
  end
  for label in pairs(physical) do assert(declared[label], 'missing physical piece sample: '..label) end
  assert(anchor and finite(anchor), 'each response requires a measured physical unity anchor')
  for _, sample in ipairs(values) do
    local ratio = sample.value / anchor
    assert(finite(ratio), 'nonfinite normalized sample')
    if sample.expected then assert(close(ratio, sample.expected), 'physical basis ratio differs: ' .. sample.row[3]) end
    report:write(string.format('%s\t%s\t%.17g\t%.17g\t%.17g\t%.17g\t%s\t%s\t%.17g\t%.17g\t%s\n',
      id,sample.row[3],sample.x,sample.y,sample.z,sample.value,tostring(sample.metal),sample.row[8],anchor,ratio,sample.row[9]))
  end
  pa:close()
end
report:close()
print('LOCAL_FRONTEND_RESPONSE_VERIFICATION=PASS model='..model..' modes='..#mode_ids..' scope=grid_and_declared_samples_only normalization=measured_physical_unity_anchor')
