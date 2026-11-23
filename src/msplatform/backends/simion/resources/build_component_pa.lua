-- Build one independently refined MR-TOF PA component.
-- Usage: simion.exe --nogui lua build_component_pa.lua GEM PA# MMGU_X MMGU_Y MMGU_Z IDS INITIALIZE [BASIS_START BASIS_END]
local source=assert(arg[1], 'GEM input required')
local output=assert(arg[2], 'PA# output required')
local mmgu_x=assert(tonumber(arg[3]), 'mmgu_x required')
local mmgu_y=assert(tonumber(arg[4]), 'mmgu_y required')
local mmgu_z=assert(tonumber(arg[5]), 'mmgu_z required')
local requested=assert(arg[6], 'comma-separated stable electrode IDs required')
local initialize=assert(tonumber(arg[7]), 'explicit field initialization (0 or 1) required')
local basis_start=tonumber(arg[8] or '0')
local basis_end=tonumber(arg[9] or '0')
assert(initialize==0 or initialize==1, 'field initialization must be 0 or 1')
assert(basis_start>=0 and basis_end>=basis_start and basis_end<=30,
  'basis range must be 0,0 or an increasing physical-electrode range')
assert(source:match('%.gem$') and output:match('%.pa#$'), 'expected GEM and PA# paths')
assert(mmgu_x>0 and mmgu_y>0 and mmgu_z>0, 'all mesh spacings must be positive')
local ids={}
for value in requested:gmatch('[^,]+') do
  local id=assert(tonumber(value), 'invalid electrode ID')
  assert(id==math.floor(id) and id>0 and id<=30, 'electrode ID out of range')
  ids[#ids+1]=id
end
assert(#ids>0, 'at least one electrode ID is required')
local staged=output:gsub('%.pa#$','.source.gem')
local input=assert(io.open(source,'rb')); local body=input:read('*a'); input:close()
local copied=assert(io.open(staged,'wb')); copied:write(body); copied:close()
_G.var={mmgu_x=mmgu_x,mmgu_y=mmgu_y,mmgu_z=mmgu_z}
simion.command(string.format('gem2pa %q %q',staged,output))
_G.var=nil
os.remove(staged); os.remove(staged:gsub('%.gem$','.processed.gem'))
local pa=assert(simion.pas:open(output)); local counts={}; local y_rows={}; local z_planes={}
for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
  local potential,electrode=pa:point(x,y,z)
  if electrode then
    counts[potential]=(counts[potential] or 0)+1
    if potential==23 or potential==24 then
      y_rows[potential]=y_rows[potential] or {}; y_rows[potential][y]=true
      z_planes[potential]=z_planes[potential] or {}; z_planes[potential][z]=true
    end
  end
end end end
for _,id in ipairs(ids) do
  print(string.format('COMPONENT_BUILD raw_electrode_points id=%d count=%d',id,counts[id] or 0))
  assert((counts[id] or 0)>0,'required electrode has no raw PA points: '..id)
end
for _,id in ipairs({23,24}) do
  if counts[id] then
    local ny,nz=0,0
    for _ in pairs(y_rows[id]) do ny=ny+1 end
    for _ in pairs(z_planes[id]) do nz=nz+1 end
    assert(nz==1,'ideal grid '..id..' occupies '..nz..' raw z planes')
    print(string.format('COMPONENT_BUILD ideal_grid id=%d y_rows=%d z_planes=%d',id,ny,nz))
  end
end
print(string.format('COMPONENT_BUILD dimensions=%dx%dx%d mm_per_gu=(%.12g,%.12g,%.12g)',pa.nx,pa.ny,pa.nz,mmgu_x,mmgu_y,mmgu_z))
if initialize==0 then
  -- Keep the detector's material mask, but remove raw GEM ID-as-voltage values.
  -- Official SIMION 8.1+ pa:potential setter preserves electrode flags;
  -- see lua_simion.pas documentation and the installed collision_hs1/make.lua.
  for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
    pa:potential(x,y,z,0)
  end end end
  pa:save(output)
end
pa:close()
if initialize~=0 then
  local solved=assert(simion.pas:open(output)); solved:refine{solutions={0}}; solved:close()
  assert(io.open(output:gsub('%.pa#$','.pa0'),'rb'),'PA0 was not created')
else
  -- The three-component IOB loads the raw zero-voltage detector PA directly.
  -- Do not create a misleading PA0 or invoke Refine for this terminal mask.
  print('COMPONENT_BUILD GEOMETRY_ONLY_ZERO_VOLTAGE_RAW_PA')
end
if basis_end>0 then
  for solution=basis_start,basis_end do
    local basis=assert(simion.pas:open(output))
    basis:refine{solutions={solution}}
    basis:close()
    local path=output:gsub('%.pa#$','.pa'..solution)
    assert(io.open(path,'rb'),'basis array was not created: '..path)
    print(string.format('COMPONENT_BUILD initialized_basis_array=%d PASS',solution))
  end
end
print('COMPONENT_BUILD PASS')
