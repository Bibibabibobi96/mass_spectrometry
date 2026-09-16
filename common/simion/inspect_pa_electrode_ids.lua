-- Inventory geometry-electrode IDs in one raw SIMION PA without solving it.
-- Usage: simion --nogui lua inspect_pa_electrode_ids.lua RAW_PA OUTPUT_CSV

local raw_path=assert(arg[1], 'raw PA required')
local output_path=assert(arg[2], 'output CSV required')
local raw=assert(simion.pas:open(raw_path), 'cannot open raw PA')
local counts={}
for z=0,raw.nz-1 do for y=0,raw.ny-1 do for x=0,raw.nx-1 do
  local value,is_electrode=raw:point(x,y,z)
  if is_electrode then
    local identifier=math.floor(value+0.5)
    assert(identifier>=0 and math.abs(value-identifier)<=1e-9,
      'raw PA geometry electrode ID must be a nonnegative integer')
    counts[identifier]=(counts[identifier] or 0)+1
  end
end end end
raw:close()
local identifiers={}
for identifier in pairs(counts) do identifiers[#identifiers+1]=identifier end
table.sort(identifiers)
assert(#identifiers>0, 'raw PA contains no geometry electrodes')
local output=assert(io.open(output_path,'w'))
output:write('electrode_id,physical_nodes\n')
for _,identifier in ipairs(identifiers) do
  output:write(string.format('%d,%d\n',identifier,counts[identifier]))
end
output:close()
print(string.format('PA_ELECTRODE_INVENTORY=PASS electrode_ids=%d output=%s',
  #identifiers,output_path))
