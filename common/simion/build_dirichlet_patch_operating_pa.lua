-- Refine one local operating-point PA from a solved parent operating PA.
-- Geometry, voltage grouping, origins, and mesh remain caller-owned.
-- Usage: ... RAW_LOCAL_PA# OUTPUT_LOCAL_PA0 SOURCE_OPERATING_PA0
--   SOURCE_ORIGIN_X,Y,Z PATCH_ORIGIN_X,Y,Z LOCAL_V1,...,LOCAL_VN [CONVERGENCE]
local raw_path=assert(arg[1],'raw local PA# required')
local output_path=assert(arg[2],'output local PA0 required')
local source_path=assert(arg[3],'solved parent operating PA0 required')
local source_origin_text=assert(arg[4],'source project origin required')
local patch_origin_text=assert(arg[5],'patch project origin required')
local voltage_text=assert(arg[6],'local electrode voltages required')
local convergence=arg[7] and assert(tonumber(arg[7]),'convergence must be numeric') or nil
assert(raw_path:match('%.pa#$') and output_path:match('%.pa0$') and source_path:match('%.pa0$'),
  'raw/output/source suffixes must be PA#/PA0/PA0')
assert(convergence==nil or convergence>0,'convergence must be positive')
local function numbers(text,label)
  local values={}
  for value in text:gmatch('[^,]+') do values[#values+1]=assert(tonumber(value),label..' contains a non-number') end
  return values
end
local source_origin=numbers(source_origin_text,'source origin')
local patch_origin=numbers(patch_origin_text,'patch origin')
local voltages=numbers(voltage_text,'local voltages')
assert(#source_origin==3 and #patch_origin==3,'source and patch origins must contain three values')
assert(#voltages>0,'at least one local voltage is required')
for index,value in ipairs(voltages) do
  assert(value==value and math.abs(value)<math.huge,'local voltage '..index..' must be finite')
end
simion.pas:close()
local source=assert(simion.pas:open(source_path),'cannot open solved parent operating PA')
local target=assert(simion.pas:open(raw_path),'cannot open raw local PA')
assert(source.dx_mm>0 and source.dy_mm>0 and source.dz_mm>0
  and target.dx_mm>0 and target.dy_mm>0 and target.dz_mm>0,'PA mesh spacing must be positive')
local physical_count,boundary_count=0,0
for z=0,target.nz-1 do for y=0,target.ny-1 do for x=0,target.nx-1 do
  local raw_value,is_physical=target:point(x,y,z)
  local boundary=x==0 or y==0 or z==0 or x==target.nx-1 or y==target.ny-1 or z==target.nz-1
  if is_physical then
    local identifier=math.floor(raw_value+0.5)
    assert(identifier>=0 and identifier<=#voltages,'raw local PA contains an undeclared electrode ID')
    target:point(x,y,z,identifier==0 and 0 or voltages[identifier],true)
    physical_count=physical_count+1
  elseif boundary then
    local px=patch_origin[1]+x*target.dx_mm
    local py=patch_origin[2]+y*target.dy_mm
    local pz=patch_origin[3]+z*target.dz_mm
    local sx=(px-source_origin[1])/source.dx_mm
    local sy=(py-source_origin[2])/source.dy_mm
    local sz=(pz-source_origin[3])/source.dz_mm
    assert(source:inside_vc(sx,sy,sz),'local boundary lies outside the parent operating PA')
    target:point(x,y,z,source:potential_vc(sx,sy,sz),true)
    boundary_count=boundary_count+1
  else
    target:point(x,y,z,0,false)
  end
end end end
target:save(output_path);target:close();source:close()
local solved=assert(simion.pas:open(output_path),'cannot reopen local operating PA')
if convergence then solved:refine{convergence=convergence} else solved:refine() end
solved:save(output_path);solved:close()
print(string.format('DIRICHLET_PATCH_OPERATING_PA=PASS physical_points=%d boundary_points=%d output=%s',
  physical_count,boundary_count,output_path))
