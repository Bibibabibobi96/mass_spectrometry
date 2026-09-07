-- Create named Fast-Adjust solution arrays only for electrodes in one PA.
-- Usage: simion.exe --nogui lua build_component_basis.lua PA# IDS
local master=assert(arg[1], 'PA# master required')
local requested=assert(arg[2], 'comma-separated IDs required')
assert(master:match('%.pa#$'), 'PA# master required')
local geometry=assert(simion.pas:open(master))
local present,max_id={},0
for z=0,geometry.nz-1 do for y=0,geometry.ny-1 do for x=0,geometry.nx-1 do
  local id,electrode=geometry:point(x,y,z)
  if electrode then
    assert(id>0 and id==math.floor(id), 'raw PA must contain positive integer electrode IDs')
    present[id]=true; max_id=math.max(max_id,id)
  end
end end end
geometry:close()
for text in requested:gmatch('[^,]+') do
  local id=assert(tonumber(text),'invalid solution ID')
  assert(id==math.floor(id) and id>0 and id<=max_id,'solution ID out of physical namespace range')
  local pa=assert(simion.pas:open(master))
  local path=master:gsub('%.pa#$','.pa'..id)
  if present[id] then
    pa:refine{solutions={id}}
  else
    -- SIMION 2020 rejects refine of an absent electrode ID. A hole in the
    -- stable namespace has identically zero response, not another electrode.
    -- Use official potential/set + save APIs; retain the same material mask.
    for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
      pa:potential(x,y,z,0)
    end end end
    pa:save(path)
    print('COMPONENT_BASIS ZERO_RESPONSE_UNUSED_ID id='..id)
  end
  pa:close()
  assert(io.open(path,'rb'),'basis output missing: '..path)
  print('COMPONENT_BASIS PASS id='..id)
end
