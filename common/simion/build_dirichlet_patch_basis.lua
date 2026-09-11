-- Refine one local electrostatic response with boundary values sampled from
-- one or more coarse response arrays.  This is device-neutral; geometry,
-- origins, voltage grouping, and mesh selection remain contract-owned.
--
-- Usage:
-- simion --nogui lua build_dirichlet_patch_basis.lua RAW_PA# OUTPUT_PA
--   SOURCE_PA_PATHS_PIPE_SEPARATED ACTIVE_RAW_IDS_COMMA_SEPARATED
--   SOURCE_PROJECT_ORIGIN_X,Y,Z PATCH_PROJECT_ORIGIN_X,Y,Z RESERVED_DASH
--   SOURCE_RAW_PA# SOURCE_ACTIVE_IDS_COMMA_SEPARATED

local raw_path=assert(arg[1], 'raw local PA# required')
local output_path=assert(arg[2], 'output PA required')
local source_text=assert(arg[3], 'coarse response PA path list required')
local active_text=assert(arg[4], 'active raw electrode IDs required')
local source_origin_text=assert(arg[5], 'coarse project origin required')
local patch_origin_text=assert(arg[6], 'patch project origin required')
assert(arg[7]==nil or arg[7]=='-', 'argument 7 is reserved and must be omitted or "-"')
local source_raw_path=arg[8]
local source_active_text=arg[9]

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

local function legacy_source_basis_voltage(pa)
  -- Compatibility path for callers without a source raw PA.  Physical
  -- Dirichlet faces can precede geometry electrodes, so contract-aware callers
  -- must supply source_raw_path and source_active_text below.
  for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
    local value,is_physical=pa:point(x,y,z)
    if is_physical and math.abs(value)>1e-12 then return value end
  end end end
  error('coarse response PA has no non-zero physical basis node')
end

local basis_voltage=nil
if #sources>0 and source_raw_path and source_raw_path~='-' then
  assert(source_active_text and source_active_text~='-',
    'source active electrode IDs are required with the source raw PA')
  local source_active_ids={}
  for _,value in ipairs(split(source_active_text, '[^,]+')) do
    local identifier=assert(tonumber(value), 'source active electrode ID is not numeric')
    assert(identifier==math.floor(identifier) and identifier>0,
      'source active electrode ID must be a positive integer')
    source_active_ids[#source_active_ids+1]=identifier
  end
  assert(#source_active_ids==#sources,
    'source active electrode IDs must align one-to-one with coarse response paths')
  local source_raw=assert(simion.pas:open(source_raw_path), 'cannot open source raw geometry PA')
  local measurements={}
  local source_index_by_id={}
  for index,identifier in ipairs(source_active_ids) do
    assert(source_index_by_id[identifier]==nil, 'source active electrode IDs must be unique')
    source_index_by_id[identifier]=index
    measurements[index]={minimum=nil,maximum=nil,count=0}
    local source=sources[index]
    assert(source.nx==source_raw.nx and source.ny==source_raw.ny and source.nz==source_raw.nz,
      'coarse response PA and source raw PA shapes differ')
  end
  for z=0,source_raw.nz-1 do for y=0,source_raw.ny-1 do for x=0,source_raw.nx-1 do
    local raw_value,is_geometry_electrode=source_raw:point(x,y,z)
    if is_geometry_electrode then
      local index=source_index_by_id[math.floor(raw_value+0.5)]
      if index then
        local value,is_physical=sources[index]:point(x,y,z)
        assert(is_physical, 'active source geometry electrode is not physical in solved basis')
        local item=measurements[index]
        item.minimum=item.minimum and math.min(item.minimum,value) or value
        item.maximum=item.maximum and math.max(item.maximum,value) or value
        item.count=item.count+1
      end
    end
  end end end
  source_raw:close()
  for index,item in ipairs(measurements) do
    assert(item.count>0, 'source raw PA has no nodes for an active source electrode ID')
    local scale=math.max(1,math.abs(item.minimum),math.abs(item.maximum))
    assert(math.abs(item.maximum-item.minimum)<=1e-6*scale,
      'coarse response PA active geometry-electrode voltage spread is too large')
    local value=(item.minimum+item.maximum)/2
    assert(math.abs(value)>1e-12, 'coarse response PA active geometry-electrode voltage is zero')
    if basis_voltage==nil then basis_voltage=value else
      local comparison_scale=math.max(1,math.abs(basis_voltage),math.abs(value))
      assert(math.abs(value-basis_voltage)<=1e-12*comparison_scale,
        'coarse response PA basis voltages differ')
    end
  end
else
  for _,source in ipairs(sources) do
    local value=legacy_source_basis_voltage(source)
    if basis_voltage==nil then basis_voltage=value else
      local scale=math.max(1,math.abs(basis_voltage),math.abs(value))
      assert(math.abs(value-basis_voltage)<=1e-12*scale,
        'coarse response PA basis voltages differ')
    end
  end
end
if #sources==0 then basis_voltage=0 end
local target=assert(simion.pas:open(raw_path), 'cannot open raw local geometry PA')
assert(target.dx_mm>0 and target.dy_mm>0 and target.dz_mm>0, 'local PA scale must be positive')

local boundary_count,physical_count=0,0
for z=0,target.nz-1 do for y=0,target.ny-1 do for x=0,target.nx-1 do
  local raw_value,is_physical=target:point(x,y,z)
  local is_boundary=x==0 or y==0 or z==0 or x==target.nx-1 or y==target.ny-1 or z==target.nz-1
  if is_physical then
    local identifier=math.floor(raw_value+0.5)
    target:point(x,y,z,active[identifier] and basis_voltage or 0,true)
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
solved:refine()
solved:save(output_path)
solved:close()
print(string.format('DIRICHLET_PATCH_BASIS=PASS boundary_points=%d physical_points=%d basis_voltage=%.15g output=%s',
  boundary_count,physical_count,basis_voltage,output_path))
