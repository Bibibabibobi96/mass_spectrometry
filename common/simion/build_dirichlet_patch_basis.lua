-- Refine one local electrostatic response with boundary values sampled from
-- one or more coarse response arrays.  This is device-neutral; geometry,
-- origins, voltage grouping, and mesh selection remain contract-owned.
--
-- Usage:
-- simion --nogui lua build_dirichlet_patch_basis.lua RAW_PA# OUTPUT_PA
--   SOURCE_PA_PATHS_PIPE_SEPARATED ACTIVE_RAW_IDS_COMMA_SEPARATED
--   SOURCE_PROJECT_ORIGIN_X,Y,Z PATCH_PROJECT_ORIGIN_X,Y,Z CONVERGENCE

local raw_path=assert(arg[1], 'raw local PA# required')
local output_path=assert(arg[2], 'output PA required')
local source_text=assert(arg[3], 'coarse response PA path list required')
local active_text=assert(arg[4], 'active raw electrode IDs required')
local source_origin_text=assert(arg[5], 'coarse project origin required')
local patch_origin_text=assert(arg[6], 'patch project origin required')
local convergence=assert(tonumber(arg[7]), 'positive convergence required')
assert(convergence>0, 'convergence must be positive')

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

local source_paths=source_text=='-' and {} or split(source_text, '[^|]+')
local active={}
for _,value in ipairs(active_text=='-' and {} or split(active_text, '[^,]+')) do
  local identifier=assert(tonumber(value), 'active ID is not numeric')
  assert(identifier==math.floor(identifier) and identifier>0, 'active ID must be a positive integer')
  active[identifier]=true
end
assert((#source_paths==0)==(next(active)==nil),
  'coarse response paths and active local IDs must either both be empty or both be present')
local source_origin=triple(source_origin_text, 'coarse project origin')
local patch_origin=triple(patch_origin_text, 'patch project origin')

local sources={}
for _,path in ipairs(source_paths) do
  local pa=assert(simion.pas:open(path), 'cannot open coarse response PA: '..path)
  assert(pa.dx_mm>0 and pa.dy_mm>0 and pa.dz_mm>0, 'coarse PA scale must be positive')
  sources[#sources+1]=pa
end
local target=assert(simion.pas:open(raw_path), 'cannot open raw local geometry PA')
assert(target.dx_mm>0 and target.dy_mm>0 and target.dz_mm>0, 'local PA scale must be positive')

local boundary_count,physical_count=0,0
for z=0,target.nz-1 do for y=0,target.ny-1 do for x=0,target.nx-1 do
  local raw_value,is_physical=target:point(x,y,z)
  local is_boundary=x==0 or y==0 or z==0 or x==target.nx-1 or y==target.ny-1 or z==target.nz-1
  if is_physical then
    local identifier=math.floor(raw_value+0.5)
    target:point(x,y,z,active[identifier] and 1 or 0,true)
    physical_count=physical_count+1
  elseif is_boundary then
    local px=patch_origin[1]+x*target.dx_mm
    local py=patch_origin[2]+y*target.dy_mm
    local pz=patch_origin[3]+z*target.dz_mm
    local potential=0
    for _,source in ipairs(sources) do
      local sx=(px-source_origin[1])/source.dx_mm
      local sy=(py-source_origin[2])/source.dy_mm
      local sz=(pz-source_origin[3])/source.dz_mm
      assert(source:inside_vc(sx,sy,sz), 'local boundary lies outside a coarse response PA')
      potential=potential+source:potential_vc(sx,sy,sz)
    end
    target:point(x,y,z,potential,true)
    boundary_count=boundary_count+1
  else
    target:point(x,y,z,0,false)
  end
end end end
target:save(output_path)
target:close()
for _,source in ipairs(sources) do source:close() end

local solved=assert(simion.pas:open(output_path), 'cannot reopen local response PA')
solved:refine{convergence=convergence}
solved:save(output_path)
solved:close()
print(string.format('DIRICHLET_PATCH_BASIS=PASS boundary_points=%d physical_points=%d output=%s',
  boundary_count,physical_count,output_path))
