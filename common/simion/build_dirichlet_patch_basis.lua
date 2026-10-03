-- Refine one pre-biased local electrostatic response with boundary values
-- sampled from one or more coarse response arrays.  The GEM compiler has
-- already written the physical electrodes at their final basis voltages.
-- Only the six boundary faces need Lua work; interior nodes remain untouched.
--
-- Usage:
-- simion --nogui lua build_dirichlet_patch_basis.lua PREBIASED_PA
--   SOURCE_PA_PATHS_OR_PATH_COEFFICIENTS_PIPE_SEPARATED SOURCE_PROJECT_ORIGIN_X,Y,Z
--   PATCH_PROJECT_ORIGIN_X,Y,Z

local output_path=assert(arg[1], 'pre-biased local PA required')
local source_text=assert(arg[2], 'coarse response PA path list required')
local source_origin_text=assert(arg[3], 'coarse project origin required')
local patch_origin_text=assert(arg[4], 'patch project origin required')
local boundary_mode=arg[5] or 'six_faces'
assert(boundary_mode=='six_faces' or boundary_mode=='x_mirror_five_faces', 'invalid boundary mode')
assert(arg[6]==nil, 'unexpected extra argument')

local function split(text, separator_pattern)
  local values={}
  for value in text:gmatch(separator_pattern) do values[#values+1]=value end
  return values
end

local function triple(text, label)
  local values={}
  for value in text:gmatch('[^,]+') do
    local number=assert(tonumber(value), label..' contains a non-number')
    values[#values+1]=number
  end
  assert(#values==3, label..' must contain three values')
  return values
end

local source_paths=split(source_text, '[^|]+')
assert(#source_paths>0, 'at least one coarse response PA is required')
local source_origin=triple(source_origin_text, 'coarse project origin')
local patch_origin=triple(patch_origin_text, 'patch project origin')

local sources={}
for _,entry in ipairs(source_paths) do
  local path,coefficient_text=entry:match('^(.*),([^,]+)$')
  local coefficient=coefficient_text and tonumber(coefficient_text) or nil
  if coefficient==nil then path,coefficient=entry,1 end
  assert(coefficient==coefficient and math.abs(coefficient)<math.huge,
    'coarse response coefficient must be finite')
  local pa=assert(simion.pas:open(path), 'cannot open coarse response PA: '..path)
  assert(pa.dx_mm>0 and pa.dy_mm>0 and pa.dz_mm>0, 'coarse PA scale must be positive')
  sources[#sources+1]={pa=pa,coefficient=coefficient}
end

local target=assert(simion.pas:open(output_path), 'cannot open pre-biased local response PA')
assert(target.dx_mm>0 and target.dy_mm>0 and target.dz_mm>0,
  'local PA scale must be positive')
target.refined=false
target.refinable=true

local boundary_count,physical_count=0,0
local function set_boundary(x,y,z)
  local _,is_physical=target:point(x,y,z)
  if is_physical then
    physical_count=physical_count+1
  else
    local px=patch_origin[1]+x*target.dx_mm
    local py=patch_origin[2]+y*target.dy_mm
    local pz=patch_origin[3]+z*target.dz_mm
    local potential=0
    for _,source in ipairs(sources) do
      local sx=(px-source_origin[1])/source.pa.dx_mm
      local sy=(py-source_origin[2])/source.pa.dy_mm
      local sz=(pz-source_origin[3])/source.pa.dz_mm
      assert(source.pa:inside_vc(sx,sy,sz), 'local boundary lies outside a coarse response PA')
      potential=potential+source.coefficient*source.pa:potential_vc(sx,sy,sz)
    end
    target:point(x,y,z,potential,true)
    boundary_count=boundary_count+1
  end
end
for z=0,target.nz-1 do for y=0,target.ny-1 do
  if boundary_mode=='six_faces' then set_boundary(0,y,z) end
  set_boundary(target.nx-1,y,z)
end end
local open_x_start = boundary_mode=='x_mirror_five_faces' and 0 or 1
for z=0,target.nz-1 do for x=open_x_start,target.nx-2 do
  set_boundary(x,0,z); set_boundary(x,target.ny-1,z)
end end
for y=1,target.ny-2 do for x=open_x_start,target.nx-2 do
  set_boundary(x,y,0); set_boundary(x,y,target.nz-1)
end end
target:save(output_path)
for _,source in ipairs(sources) do source.pa:close() end
target:refine()
target:save(output_path)
target:close()
print(string.format('DIRICHLET_PATCH_BASIS=PASS boundary_points=%d physical_boundary_points=%d boundary_mode=%s native_basis_voltage=10000 output=%s',
  boundary_count,physical_count,boundary_mode,output_path))
