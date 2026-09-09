-- Remap the electrode-number namespace of a raw PA without changing its
-- geometry.  Mapping syntax is OLD:NEW,OLD:NEW; NEW=0 retains a grounded
-- electrode node.  Every encountered raw electrode ID must be declared.
-- Usage: simion --nogui lua remap_pa_electrode_ids.lua INPUT_PA OUTPUT_PA MAP

local input_path=assert(arg[1], 'input PA required')
local output_path=assert(arg[2], 'output PA required')
local map_text=assert(arg[3], 'electrode mapping required')
local mapping={}
for item in map_text:gmatch('[^,]+') do
  local old_text,new_text=item:match('^([^:]+):([^:]+)$')
  local old_id=assert(tonumber(old_text), 'mapping has invalid source ID')
  local new_id=assert(tonumber(new_text), 'mapping has invalid target ID')
  assert(old_id==math.floor(old_id) and old_id>0, 'source ID must be a positive integer')
  assert(new_id==math.floor(new_id) and new_id>=0, 'target ID must be a non-negative integer')
  assert(mapping[old_id]==nil, 'source ID appears more than once')
  mapping[old_id]=new_id
end
assert(next(mapping)~=nil, 'electrode mapping may not be empty')

local pa=assert(simion.pas:open(input_path), 'cannot open input PA')
local counts={}
for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
  local value,electrode=pa:point(x,y,z)
  if electrode then
    local old_id=math.floor(value+0.5)
    local new_id=mapping[old_id]
    assert(new_id~=nil, 'raw electrode ID is absent from mapping: '..old_id)
    pa:point(x,y,z,new_id,true)
    counts[new_id]=(counts[new_id] or 0)+1
  end
end end end
pa:save(output_path)
pa:close()
print('PA_ELECTRODE_REMAP=PASS output='..output_path)
