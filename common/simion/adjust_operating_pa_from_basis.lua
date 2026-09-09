-- Apply voltage deltas to one solved operating PA by linear superposition of
-- matching electrostatic response arrays.  This performs no Refine and owns no
-- device geometry, voltage choice, mesh, or Workbench placement.
-- Usage: ... BASE_PA0 OUTPUT_PA0 BASIS_PATHS_PIPE_SEPARATED
--   BASIS_VOLTAGES_COMMA_SEPARATED DELTA_VOLTAGES_COMMA_SEPARATED

local base_path=assert(arg[1],'base operating PA0 required')
local output_path=assert(arg[2],'output operating PA0 required')
local basis_text=assert(arg[3],'basis PA path list required')
local basis_voltage_text=assert(arg[4],'basis voltage list required')
local delta_text=assert(arg[5],'delta voltage list required')
assert(base_path:match('%.pa0$') and output_path:match('%.pa0$'),
  'base and output must be PA0 files')
assert(base_path~=output_path,'operating-point adjustment must not overwrite its base PA')

local function split(text,pattern,label)
  local values={}
  for value in text:gmatch(pattern) do values[#values+1]=value end
  assert(#values>0,label..' must not be empty')
  return values
end
local paths=split(basis_text,'[^|]+','basis path list')
local basis_voltages=split(basis_voltage_text,'[^,]+','basis voltage list')
local deltas=split(delta_text,'[^,]+','delta voltage list')
assert(#paths==#basis_voltages and #paths==#deltas,
  'basis paths, basis voltages, and voltage deltas must have equal length')
for index=1,#paths do
  basis_voltages[index]=assert(tonumber(basis_voltages[index]),'basis voltage must be numeric')
  deltas[index]=assert(tonumber(deltas[index]),'delta voltage must be numeric')
  assert(basis_voltages[index]==basis_voltages[index]
    and math.abs(basis_voltages[index])>0 and math.abs(basis_voltages[index])<math.huge,
    'basis voltage must be finite and nonzero')
  assert(deltas[index]==deltas[index] and math.abs(deltas[index])<math.huge,
    'delta voltage must be finite')
end

simion.pas:close()
local base=assert(simion.pas:open(base_path),'cannot open base operating PA')
base:save(output_path)
local nx,ny,nz=base.nx,base.ny,base.nz
local dx,dy,dz=base.dx_mm,base.dy_mm,base.dz_mm
base:close()
local target=assert(simion.pas:open(output_path),'cannot open copied operating PA')
local bases={}
for index,path in ipairs(paths) do
  local pa=assert(simion.pas:open(path),'cannot open response PA: '..path)
  assert(pa.nx==nx and pa.ny==ny and pa.nz==nz,'response PA shape differs from base')
  assert(pa.dx_mm==dx and pa.dy_mm==dy and pa.dz_mm==dz,'response PA mesh differs from base')
  bases[index]=pa
end
local maximum_abs_delta=0
for z=0,nz-1 do for y=0,ny-1 do for x=0,nx-1 do
  local potential,is_physical=target:point(x,y,z)
  local change=0
  for index,pa in ipairs(bases) do
    local response=pa:point(x,y,z)
    change=change+deltas[index]/basis_voltages[index]*response
  end
  maximum_abs_delta=math.max(maximum_abs_delta,math.abs(change))
  target:point(x,y,z,potential+change,is_physical)
end end end
target:save(output_path);target:close()
for _,pa in ipairs(bases) do pa:close() end
print(string.format('OPERATING_PA_BASIS_ADJUST=PASS responses=%d max_abs_node_delta_V=%.15g output=%s',
  #paths,maximum_abs_delta,output_path))
