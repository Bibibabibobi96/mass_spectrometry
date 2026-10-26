-- SIMION 2020 ordinary operating-field audit. Bounded physical samples are
-- not a field/mesh convergence qualification. One PA is open at a time.
-- Usage: simion --nogui --noprompt lua THIS.lua specification.tsv report.json
local input=assert(io.open(assert(arg[1],'audit specification required'),'r'))
local output=assert(arg[2],'audit report required')
assert(input:read('*l')=='frontend_working_fields_audit_v2','invalid audit specification')
local grid,raw_path,domain,boundary
local samples,working,voltages={},{},{}
local kinds,physical_ids={},nil
local function fields(line)
  local result={}
  for value in (line..'\t'):gmatch('(.-)\t') do result[#result+1]=value end
  return result
end
for line in input:lines() do
  local row=fields(line)
  if row[1]=='domain' then
    assert(not domain and #row==2 and (row[2]=='parent' or row[2]=='entrance_refinement'),'invalid domain');domain=row[2]
  elseif row[1]=='boundary' then
    assert(not boundary and #row==2,'invalid boundary');boundary=row[2]
  elseif row[1]=='grid' then
    assert(not grid and #row==7,'invalid grid')
    grid={};for i=2,7 do grid[#grid+1]=assert(tonumber(row[i])) end
  elseif row[1]=='raw' then
    assert(not raw_path and #row==2 and row[2]:match('%.pa#$'),'invalid raw PA#')
    raw_path=row[2]
  elseif row[1]=='electrodes' then
    assert(not physical_ids and #row==2,'invalid physical electrode namespace')
    physical_ids={};for token in row[2]:gmatch('[^,]+') do
      local id=assert(tonumber(token));assert(id>=1 and id==math.floor(id) and not physical_ids[id],'invalid electrode ID')
      physical_ids[id]=true
    end
  elseif row[1]=='physical' then
    assert(#row==6,'invalid physical sample')
    samples[#samples+1]={label=row[2],id=assert(tonumber(row[3])),
      x=assert(tonumber(row[4])),y=assert(tonumber(row[5])),z=assert(tonumber(row[6]))}
  elseif row[1]=='working' then
    assert(#row==3 and not working[row[2]] and row[3]:match('%.pa$'),'invalid working field')
    working[row[2]]=row[3];kinds[#kinds+1]=row[2]
  elseif row[1]=='voltages' then
    assert(#row==3 and not voltages[row[2]],'invalid voltage table')
    local values={};for value in row[3]:gmatch('[^,]+') do values[#values+1]=assert(tonumber(value)) end
    assert(#values>0,'complete physical voltage table required');voltages[row[2]]=values
  else error('unknown audit row') end
end
input:close()
assert(grid and raw_path and domain and physical_ids and #samples>0,'incomplete physical audit')
assert(boundary==(domain=='parent' and 'native_zero_neumann' or 'parent_dirichlet'),'invalid domain boundary')
local function finite(value) return type(value)=='number' and value==value and math.abs(value)<math.huge end
local function same_voltage(actual,expected)
  -- A PA round-trip can change the final binary64 value by a few ulps.  This
  -- is an audit of the imposed physical electrode potential, not a request
  -- for byte-identical decimal reserialization.
  local tolerance=math.max(1e-9,math.abs(expected)*1e-12)
  return math.abs(actual-expected)<=tolerance
end
local labels,ids={},{}
for _,sample in ipairs(samples) do
  assert(not labels[sample.label] and sample.id>=1 and sample.id==math.floor(sample.id),'invalid physical sample identity')
  assert(physical_ids[sample.id],'sample declares a nonexistent electrode')
  labels[sample.label]=true;ids[sample.id]=true
end
assert(#kinds==1 and (kinds[1]=='carrier_off' or kinds[1]=='rf_reference' or kinds[1]=='pulse_delta'),
  'one physical working member required')
local max_id=0;for id in pairs(physical_ids) do max_id=math.max(max_id,id) end
for _,kind in ipairs(kinds) do
  local values=assert(voltages[kind],'missing actual voltage table')
  assert(#values==max_id,'native voltage parameter index extent differs')
  for id,value in ipairs(values) do
    assert(finite(value),'nonfinite electrode voltage')
    assert(physical_ids[id] or value==0,'unused native parameter slot is nonzero')
  end
end
local function check_grid(pa)
  assert(pa.potential_type=='electric','electrostatic PA required')
  assert(pa.nx==grid[1] and pa.ny==grid[2] and pa.nz==grid[3],'PA dimensions differ')
  assert(pa.dx_mm==grid[4] and pa.dy_mm==grid[5] and pa.dz_mm==grid[6],'PA mesh differs')
end
simion.pas:close()
local raw=assert(simion.pas:open(raw_path),'cannot open raw geometry')
check_grid(raw)
for _,sample in ipairs(samples) do
  local value,metal=raw:point(sample.x,sample.y,sample.z)
  assert(finite(value) and metal and value==sample.id,'raw physical ID differs: '..sample.label)
end
raw:close()
local count=0;for _ in pairs(working) do count=count+1 end
assert(count==#kinds,'working field count differs')
for _,kind in ipairs(kinds) do
  local values=assert(voltages[kind],'missing actual voltage table')
  local pa=assert(simion.pas:open(assert(working[kind],'missing working kind')))
  check_grid(pa)
  for _,sample in ipairs(samples) do
    local value,metal=pa:point(sample.x,sample.y,sample.z)
    -- Conducting node potentials are the actual input doubles, not a unity
    -- normalization or an assumed 10000 V PA+ solution reference.
    assert(finite(value) and metal and same_voltage(value,values[sample.id]),
      'working physical potential/metal differs: '..kind..' '..sample.label)
  end
  pa:close()
end
local report=assert(io.open(output,'w'))
report:write('{"schema_version":1,"role":"single_reflection_frontend_working_fields_audit",')
report:write('"status":"pass","physical_samples":'..#samples..',"working_points":'..#kinds..',')
report:write('"domain_id":"'..domain..'","boundary_policy":"'..boundary..'","validation_scope":"grid_and_physical_metal_voltage_samples_only"}\n')
report:close()
print('FRONTEND_WORKING_FIELDS_AUDIT=PASS physical_samples='..#samples..' working_points='..#kinds)
