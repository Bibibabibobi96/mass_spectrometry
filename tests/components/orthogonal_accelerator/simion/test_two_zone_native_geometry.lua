-- Read-only SIMION 2020 native regression for a built two-zone PA family.
-- Arguments: raw.pa# adjusted.pa0 receipt.csv, then the builder's 24 numeric
-- arguments (builder argv[3..26]), copied from a frozen run contract.
-- Tests sampled material, open ring bores and all electrode voltages; the
-- production builder separately audits complete one-row ideal-grid topology.
assert(#arg == 27, 'PA#, PA0, receipt and all 24 numeric parameters required')
local raw_path, adjusted_path, receipt_path = arg[1], arg[2], arg[3]
local parameters = {}
for index = 4, 27 do
  local value = assert(tonumber(arg[index]), 'numeric parameter required')
  assert(value == value and math.abs(value) < math.huge, 'finite parameter required')
  parameters[index-1] = value
end
local xy, dz = parameters[3], parameters[4]
local bore, width, gap = parameters[5], parameters[6], parameters[7]
local rear, wall, margin = parameters[8], parameters[9], parameters[10]
local back_margin, phase = parameters[12], parameters[14]
local d1, d2, count = parameters[15], parameters[16], parameters[17]
local repeller_thickness, ring_thickness = parameters[18], parameters[19]
local repeller_v, grid1_v = parameters[21], parameters[22]
local half_inner = bore+width+gap
local half_span = half_inner+wall+margin
local z_min = -repeller_thickness-rear-wall-back_margin-phase
local samples = {}
local function sample(label, x, y, z, electrode_id, voltage)
  local function node(value, cell)
    -- Sampling uses the nearest existing raw node, never changes the geometry.
    return math.floor(value/cell+0.5)
  end
  samples[#samples+1] = {label=label, x=node(x+half_span,xy),
    y=node(y+half_span,xy), z=node(z-z_min,dz),
    id=electrode_id, voltage=voltage}
end
sample('repeller',0,0,-repeller_thickness/2,1,repeller_v)
sample('rear_clearance',0,0,-repeller_thickness-rear/2,0,0)
sample('rear_cap',0,0,-repeller_thickness-rear-wall/2,4+count,0)
sample('stage1_axis',0,0,d1/2,0,0)
sample('grid1',0,0,d1,2,grid1_v)
sample('grid2',0,0,d1+d2,3+count,0)
sample('shield_positive_x',half_inner+wall/2,0,d1/2,4+count,0)
sample('insulation_gap',bore+width+gap/2,0,d1/2,0,0)
for index=1,count do
  local center=d1+index*d2/(count+1)
  local voltage=tonumber(string.format('%.12g',grid1_v*(count+1-index)/(count+1)))
  sample('ring_'..index..'_material',bore+width/2,0,center,2+index,voltage)
  sample('ring_'..index..'_axis',0,0,center,0,0)
  sample('ring_'..index..'_inner_bore',bore/2,0,center,0,0)
  sample('ring_'..index..'_gap',bore+width/2,0,
    center+ring_thickness/2+(d2/(count+1)-ring_thickness)/2,0,0)
end
simion.pas:close()
local raw=assert(simion.pas:open(raw_path))
local dimensions={raw.nx,raw.ny,raw.nz}
local expected_nx=math.floor(2*half_span/xy+0.5)+1
local expected_nz=math.floor((d1+d2+parameters[20]+parameters[13]
  +repeller_thickness+rear+wall+back_margin)/dz+0.5)+1
assert(raw.nx==expected_nx and raw.ny==expected_nx and raw.nz==expected_nz,
  'raw PA dimensions differ from frozen numerical domain')
assert(raw.dx_mm==xy and raw.dy_mm==xy and raw.dz_mm==dz,
  'raw PA cells differ from frozen numerical contract')
for _,item in ipairs(samples) do
  local potential,electrode=raw:point(item.x,item.y,item.z)
  assert(electrode==(item.id~=0),item.label..': material/open-bore mismatch')
  if item.id~=0 then
    assert(math.abs(potential-item.id)<1e-9,item.label..': electrode ID mismatch')
  end
end
raw:close()
local adjusted=assert(simion.pas:open(adjusted_path))
assert(adjusted.nx==dimensions[1] and adjusted.ny==dimensions[2]
  and adjusted.nz==dimensions[3],'raw/adjusted dimensions differ')
-- SIMION 2020 can reopen a successfully refined/fast-adjusted PA0 with this
-- metadata false. Completion must be established by the builder's exit/log,
-- not by treating this in-memory flag as a persistent qualification record.
-- Official source: installed docs/simion.chm, lua_simion.pas.html#pa.refined
-- (reviewed 2026-09-03): flag is not stored in PA files; inferred on loading.
print('NATIVE_REOPENED_REFINED_METADATA='..tostring(adjusted.refined))
local output=assert(io.open(receipt_path,'w'))
output:write('label,x_gu,y_gu,z_gu,electrode_id,expected_voltage_v,actual_voltage_v\n')
for _,item in ipairs(samples) do
  local potential,electrode=adjusted:point(item.x,item.y,item.z)
  assert(electrode==(item.id~=0),item.label..': adjusted material mismatch')
  if item.id~=0 then
    -- SIMION's documented PA implementation starts max_voltage at 100000 V
    -- (same installed API page, pa:clear) but does not expose that internal
    -- member as a Lua property. This is an encoding scale, not a device value.
    -- Budget roundoff at that scale and at the explicit fixture voltages.
    local tolerance=16*2^-52*math.max(100000,math.abs(repeller_v),
      math.abs(grid1_v),math.abs(item.voltage))
    assert(math.abs(potential-item.voltage)<=tolerance,
      string.format('%s: voltage %.12g differs from %.12g',item.label,potential,item.voltage))
  end
  output:write(string.format('%s,%d,%d,%d,%d,%.12g,%.12g\n',item.label,
    item.x,item.y,item.z,item.id,item.voltage,potential))
end
output:close()
adjusted:close()
print(string.format('NATIVE_GEOMETRY=PASS samples=%d rings=%d dimensions=%dx%dx%d',
  #samples,count,dimensions[1],dimensions[2],dimensions[3]))
