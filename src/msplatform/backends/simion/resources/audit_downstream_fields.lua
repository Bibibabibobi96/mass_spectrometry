-- Read-only native domain and operating-point audit. Never Refine/Fast Adjust.
-- SIMION2020 docs/simion.chm::lua_simion.pas.html documents symmetry,
-- potential_type, potentials_minmax(), potential(), and close().  The native
-- family builders deliberately retain refinable PA0 members; their successful
-- native build records establish the completed Refine boundary.
local spec=assert(dofile(assert(arg[1], 'audit spec required')))
local rows={}
local function close_enough(actual,expected,label)
  assert(type(actual)=='number' and actual==actual and
    math.abs(actual-expected)<=1e-8*math.max(1,math.abs(expected)),label..' differs')
end
for _,asset in ipairs(spec.assets) do
  for _,path in ipairs(asset.family_paths) do
    local member=assert(io.open(path,'rb'),'missing native family member: '..path)
    member:close()
  end
  simion.pas:close()
  local pa=assert(simion.pas:open(asset.carrier_path))
  assert(pa.potential_type=='electric','PA must be electric')
  assert(pa.symmetry==asset.symmetry,'PA symmetry differs')
  for key,value in pairs(asset.grid) do close_enough(pa[key],value,key) end
  if asset.role=='reflectron' then
    assert(pa.refinable==false,'reflectron must be a detached operating PA')
    for _,sample in ipairs(asset.endpoint_samples) do
      close_enough(pa:potential(sample.x,0,0),sample.voltage,'reflectron endpoint potential')
    end
  else
    local minimum,maximum=pa:potentials_minmax()
    close_enough(minimum,0,'grounded minimum')
    close_enough(maximum,0,'grounded maximum')
    assert(#pa.electrode_numbers==1 and pa.electrode_numbers[1]==1,
      'native grounded family must have its single physical electrical group')
  end
  pa:close()
  local values={}
  for _,key in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
    values[#values+1]=string.format('%q:%.17g',key,asset.grid[key])
  end
  rows[#rows+1]=string.format('{"role":%q,"grid":{%s}}',asset.role,table.concat(values,','))
end
simion.pas:close()
local existing=io.open(spec.output,'rb')
if existing then existing:close();error('refusing to overwrite native audit') end
local output=assert(io.open(spec.output,'wb'))
output:write('{"role":"single_reflection_downstream_native_audit","status":"success","checked_assets":[',
  table.concat(rows,','),']}\n')
output:close()
print('DOWNSTREAM_NATIVE_AUDIT=PASS')
