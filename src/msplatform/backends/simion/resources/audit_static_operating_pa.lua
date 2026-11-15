-- Read-only cold audit of an already adjusted standalone electrostatic PA.
-- SIMION 2020 docs/simion.chm::lua_simion.pas.html: point, surface_info,
-- potential_vc, field_vc and grid properties. Official examples/pa2text/lua/pa2text.lua
-- reads the stored encoding limit as debug_max_voltage. Never Refine, Fast Adjust or save.
local spec=assert(dofile(assert(arg[1],'static operating audit spec required')))
local function finite(v) return type(v)=='number' and v==v and math.abs(v)<math.huge end
local function nonempty(path)
  local f=assert(io.open(path,'rb'),'required standalone input missing: '..path)
  local first=f:read(1);assert(f:close());assert(first~=nil,'required standalone input empty')
end
local prior=io.open(spec.output,'rb');if prior then prior:close();error('audit output already exists') end
assert(type(spec.assets)=='table' and #spec.assets>0,'explicit static assets required')
local domains,seen={},{}
for _,asset in ipairs(spec.assets) do
  assert(type(asset.domain_id)=='string' and not seen[asset.domain_id],'distinct domain required')
  seen[asset.domain_id]=true
  assert(asset.carrier_path:match('%.pa$'),'standalone .pa required, never a family')
  assert(asset.surface_path==asset.carrier_path:gsub('%.pa$','.pa-surf'),'standalone surface companion differs')
  local mode=asset.surface_mode or 'present'
  assert(mode=='present' or mode=='empty','unknown surface mode')
  nonempty(asset.carrier_path)
  if mode=='present' then nonempty(asset.surface_path)
  else local sidecar=io.open(asset.surface_path,'rb');assert(not sidecar,'empty surface forbids companion') end
  simion.pas:close()
  local pa=assert(simion.pas:open(asset.carrier_path))
  assert(pa.potential_type=='electric' and pa.symmetry=='3dplanar','static PA type/symmetry differs')
  for _,key in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
    assert(finite(asset.grid[key]) and pa[key]==asset.grid[key],'static grid differs: '..key)
  end
  assert(type(asset.physical_samples)=='table' and #asset.physical_samples>0,'physical witnesses required')
  local metal_count,void_count=0,0
  for _,sample in ipairs(asset.physical_samples) do
    assert(type(sample.metal)=='boolean' and #sample.gu==3,'explicit physical witness required')
    local voltage,metal=pa:point(unpack(sample.gu))
    assert(metal==sample.metal and finite(voltage),'static metal/vacuum witness differs')
    if sample.metal then
      metal_count=metal_count+1
      local expected=sample.expected_voltage_v
      assert(finite(expected) and finite(pa.debug_max_voltage) and pa.debug_max_voltage>0,'finite static workpoint required')
      -- Official ordinary PA encodes metal as V + 2*max_voltage. Bound only
      -- binary64 addition/subtraction roundoff; this is not a field tolerance.
      local u=2^-53;local gamma2=2*u/(1-2*u)
      local bound=gamma2*(math.abs(expected)+4*math.abs(pa.debug_max_voltage))
      assert(finite(bound),'static encoding roundoff bound overflow')
      assert(math.abs(voltage-expected)<=bound,'static electrode voltage differs')
    else void_count=void_count+1 end
  end
  assert(metal_count>0 and void_count>0,'metal and vacuum witnesses required')
  local witness=assert(io.open(asset.surface_witnesses,'rb'))
  local count=0
  for line in witness:lines() do
    local x,y,z,sx,sy,sz=line:match('^(%d+),(%d+),(%d+),([^,]+),([^,]+),([^,]+)$')
    assert(x,'invalid canonical surface witness')
    local ax,ay,az=pa:surface_info(tonumber(x),tonumber(y),tonumber(z))
    for i,row in ipairs({{ax},{ay},{az}}) do
      local expected=({sx,sy,sz})[i];local actual=row[1]
      assert((expected=='nil' and actual==nil) or (expected~='nil' and finite(tonumber(expected)) and actual==tonumber(expected)),
        'static surface witness differs')
    end
    count=count+1
  end
  assert(witness:close())
  assert(count>0,'surface witnesses empty')
  if mode=='empty' then
    local scanned=0
    for x,y,z in pa:points() do
      local sx,sy,sz=pa:surface_info(x,y,z)
      assert(sx==nil and sy==nil and sz==nil,'empty surface contains an offset')
      scanned=scanned+1
    end
    assert(scanned==pa.nx*pa.ny*pa.nz,'empty surface scan incomplete')
  end
  assert(type(asset.sample_points_gu)=='table' and #asset.sample_points_gu>0,'explicit field samples required')
  for _,point in ipairs(asset.sample_points_gu) do
    assert(#point==3 and finite(point[1]) and finite(point[2]) and finite(point[3]),'finite sample coordinates required')
    for i,key in ipairs({'nx','ny','nz'}) do assert(point[i]>=0 and point[i]<=pa[key]-1,'sample outside PA') end
    local v=pa:potential_vc(unpack(point));local x,y,z=pa:field_vc(unpack(point))
    assert(finite(v) and finite(x) and finite(y) and finite(z),'static field sample nonfinite')
  end
  pa:close();domains[#domains+1]=string.format('%q',asset.domain_id)
end
simion.pas:close()
local output=assert(io.open(spec.output,'wb'))
output:write('{"role":"simion_static_operating_field_audit","status":"success","checked_domains":[',table.concat(domains,','),']}\n')
assert(output:close())
print('STATIC_OPERATING_FIELDS_READBACK=PASS REFINE=False FAST_ADJUST=False FLY=False SAVE=False')
