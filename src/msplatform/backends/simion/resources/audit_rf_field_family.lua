-- Read-only original-producer fractional-family audit, no Refine/FastAdjust/save.
-- SIMION2020 docs/simion.chm::lua_simion.pas.html: pas:open, point,
-- potentials_minmax, electrode_numbers, surface_info, close and grid properties.
local spec=assert(dofile(assert(arg[1],'RF family audit spec required')))
local domains,details={},{}
local function finite(value)
  return type(value)=='number' and value==value and math.abs(value)<math.huge
end
for _,asset in ipairs(spec.assets) do
  for _,path in ipairs(asset.family_paths) do
    local file=assert(io.open(path,'rb'),'RF family member missing')
    assert(file:seek('end')>0,'RF family member empty');file:close()
  end
  simion.pas:close()
  local pa=assert(simion.pas:open(asset.carrier_path))
  assert(pa.potential_type=='electric' and pa.symmetry=='3dplanar','RF field type/symmetry differs')
  for key,wanted in pairs(asset.grid) do assert(pa[key]==wanted,'RF grid differs: '..key) end
  local found={}
  for _,eid in ipairs(pa.electrode_numbers) do found[eid]=true end
  for _,eid in ipairs(asset.response_ids) do assert(found[eid],'RF carrier electrode absent');found[eid]=nil end
  assert(next(found)==nil,'RF carrier has undeclared electrodes')
  local witnesses=assert(io.open(asset.surface_witnesses,'rb'))
  local checked,nonnil=0,0
  for line in witnesses:lines() do
    local x,y,z,sx,sy,sz=line:match('^(%d+),(%d+),(%d+),([^,]+),([^,]+),([^,]+)$')
    assert(x,'invalid original fractional witness')
    local ax,ay,az=pa:surface_info(tonumber(x),tonumber(y),tonumber(z))
    for k,actual in ipairs({{ax},{ay},{az}}) do
      local wanted=({sx,sy,sz})[k]
      if actual[1]~=nil then nonnil=nonnil+1 end
      assert((wanted=='nil' and actual[1]==nil) or (wanted~='nil' and actual[1]==tonumber(wanted)),
        'RF fractional surface readback differs')
    end
    checked=checked+1
  end
  witnesses:close();assert(checked>0,'RF fractional witness input empty')
  local node_rows={}
  for _,sample in ipairs(asset.physical_samples) do
    local voltage,metal=pa:point(unpack(sample.gu))
    assert(metal==(sample.metal~=false),'RF metal/vacuum geometry differs')
    assert(finite(voltage),'RF field witness potential nonfinite')
    node_rows[#node_rows+1]=string.format('{"gu":[%.17g,%.17g,%.17g],"metal":%s,"voltage_v":%.17g}',
      sample.gu[1],sample.gu[2],sample.gu[3],tostring(metal),voltage)
  end
  local low,high=pa:potentials_minmax()
  assert(finite(low) and finite(high),'RF carrier field is nonfinite')
  pa:close()
  local response_rows={}
  for _,eid in ipairs(asset.response_ids) do
    local path=asset.carrier_path:gsub('%.pa0$','.pa'..eid)
    local response=assert(simion.pas:open(path))
    assert(response.potential_type=='electric' and response.symmetry=='3dplanar','RF response type differs')
    for key,wanted in pairs(asset.grid) do assert(response[key]==wanted,'RF response grid differs') end
    local minimum,maximum=response:potentials_minmax()
    assert(finite(minimum) and finite(maximum),'RF response is nonfinite')
    response_rows[#response_rows+1]=string.format('{"native_electrode_id":%d,"minimum_v":%.17g,"maximum_v":%.17g}',eid,minimum,maximum)
    response:close()
  end
  domains[#domains+1]=string.format('%q',asset.domain_id)
  details[#details+1]=string.format('{"domain_id":%q,"carrier_minimum_v":%.17g,"carrier_maximum_v":%.17g,"fractional_witness_count":%d,"nonnil_surface_offsets":%d,"physical_witnesses":[%s],"responses":[%s]}',
    asset.domain_id,low,high,checked,nonnil,table.concat(node_rows,','),table.concat(response_rows,','))
end
simion.pas:close()
local previous=io.open(spec.output,'rb')
if previous then previous:close();error('refusing to overwrite RF audit') end
local output=assert(io.open(spec.output,'wb'))
output:write('{"role":"simion_rf_fractional_field_audit","status":"success","checked_domains":[',
  table.concat(domains,','),'],"checked_assets":[',table.concat(details,','),']}\n')
output:close()
print('INDEPENDENT_RF_FIELDS_READBACK=PASS REFINE=False FLY=False SOURCE=False SAVE=False')
