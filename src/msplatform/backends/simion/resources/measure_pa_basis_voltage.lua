-- Measure the active physical-electrode voltage carried by one solved basis PA.
-- The raw PA distinguishes geometry electrodes from Dirichlet boundary nodes,
-- both of which are marked physical in the solved local array.
-- Usage: simion --nogui lua measure_pa_basis_voltage.lua BASIS_PA RAW_PA ACTIVE_ID OUTPUT_CSV

local input_path=assert(arg[1], 'basis PA required')
local raw_path=assert(arg[2], 'raw PA required')
local active_id=assert(tonumber(arg[3]), 'active raw electrode ID required')
local output_path=assert(arg[4], 'output CSV required')
assert(active_id==math.floor(active_id) and active_id>0,'active raw electrode ID must be positive')
local pa=assert(simion.pas:open(input_path),'cannot open basis PA')
local raw=assert(simion.pas:open(raw_path),'cannot open raw PA')
assert(pa.nx==raw.nx and pa.ny==raw.ny and pa.nz==raw.nz,'basis and raw PA shapes differ')
local reference=nil
local minimum=nil
local maximum=nil
local nonzero_physical_count=0
for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
  local raw_value,is_geometry_electrode=raw:point(x,y,z)
  if is_geometry_electrode and math.floor(raw_value+0.5)==active_id then
    local value,is_physical=pa:point(x,y,z)
    assert(is_physical,'active raw electrode is not physical in solved basis')
    if reference==nil then reference=value end
    minimum=minimum and math.min(minimum,value) or value
    maximum=maximum and math.max(maximum,value) or value
    nonzero_physical_count=nonzero_physical_count+1
  end
end end end
pa:close();raw:close()
assert(reference~=nil and reference~=0,'basis PA has no active physical electrode voltage')
local scale=math.max(1,math.abs(minimum),math.abs(maximum))
assert(math.abs(maximum-minimum)<=1e-6*scale,
  string.format('basis PA physical voltage spread is too large: min=%.15g max=%.15g',minimum,maximum))
reference=(minimum+maximum)/2
local output=assert(io.open(output_path,'w'))
output:write('basis_voltage_V,minimum_physical_voltage_V,maximum_physical_voltage_V,nonzero_physical_nodes\n')
output:write(string.format('%.15g,%.15g,%.15g,%d\n',reference,minimum,maximum,nonzero_physical_count))
output:close()
print(string.format('PA_BASIS_VOLTAGE=PASS voltage=%.15g active_id=%d physical_nodes=%d output=%s',
  reference,active_id,nonzero_physical_count,output_path))
