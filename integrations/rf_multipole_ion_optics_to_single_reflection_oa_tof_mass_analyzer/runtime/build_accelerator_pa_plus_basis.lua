-- Boundary-couple a PA+ solution family from solved source responses.
-- mode_spec format: "solution:source=coefficient,source=coefficient;...".
-- The caller supplies physical-source terms for accelerator main and identity
-- PA+-mode terms for the nested entrance-local replacement.
--
-- The default source policy consumes a text map of detached standalone PAs:
--   standalone_pa_mode_map_v1
--   36<TAB>C:\short\accelerator_main.response_36.pa
-- Native source.pa0 sibling lookup remains available only when the caller
-- explicitly passes writable_staging_native_family_v1 as argument 11.  It is
-- for an unpublished writable build staging family, never a published cache.

local source_input=assert(arg[1], 'source response input is required')
local fine_pa_sharp=assert(arg[2], 'fine PA# is required')
local source_origin={assert(tonumber(arg[3])),assert(tonumber(arg[4])),assert(tonumber(arg[5]))}
local fine_origin={assert(tonumber(arg[6])),assert(tonumber(arg[7])),assert(tonumber(arg[8]))}
local mode_spec=assert(arg[9], 'PA+ mode specification is required')
local report_path=assert(arg[10], 'report path is required')
local source_policy=arg[11] or 'standalone_mode_map_v1'
assert(source_policy=='standalone_mode_map_v1' or
       source_policy=='writable_staging_native_family_v1',
  'source response policy is unsupported')
assert(fine_pa_sharp:match('%.pa#$'), 'fine input must end in .pa#')

local function indexed(path,index)
  if path:match('%.pa0$') then return path:gsub('0$',tostring(index)) end
  return path:gsub('#$',tostring(index))
end
local function parse_modes(text)
  local result={}
  for entry in text:gmatch('[^;]+') do
    local mode_id,terms=entry:match('^(%d+):(.+)$')
    assert(mode_id and terms,'invalid PA+ mode specification')
    local parsed={id=tonumber(mode_id),terms={}}
    for term in terms:gmatch('[^,]+') do
      local source_id,weight=term:match('^(%d+)=([%+%-%.%deE]+)$')
      assert(source_id and weight,'invalid PA+ source term')
      table.insert(parsed.terms,{id=tonumber(source_id),weight=tonumber(weight)})
    end
    assert(#parsed.terms>0,'PA+ mode needs at least one source term')
    table.insert(result,parsed)
  end
  assert(#result>0,'PA+ mode specification is empty')
  return result
end
local modes=parse_modes(mode_spec)

local function parse_standalone_mode_map(path,modes_to_resolve)
  local handle=assert(io.open(path,'r'),'cannot open standalone source mode map: '..path)
  local header=handle:read('*l')
  assert(header=='standalone_pa_mode_map_v1','standalone source mode map header differs')
  local paths={}
  local path_ids={}
  for line in handle:lines() do
    assert(line~='','standalone source mode map contains an empty line')
    local id_text,response_path=line:match('^(%d+)\t(.+)$')
    assert(id_text and response_path,'standalone source mode map entry is invalid')
    local id=tonumber(id_text)
    assert(paths[id]==nil,'standalone source mode map repeats a response id')
    local lower=response_path:lower()
    assert(lower:match('%.pa$') and not lower:match('%.pa%d+$') and
           not lower:match('%.pa0$') and not lower:match('%.pa[+_]$'),
      'standalone source response must use the exact .pa suffix')
    assert(path_ids[lower]==nil,'standalone source mode map repeats a PA path')
    local response=assert(io.open(response_path,'rb'),
      'standalone source response is missing: '..response_path)
    response:close()
    paths[id]=response_path
    path_ids[lower]=id
  end
  handle:close()
  local required={}
  local required_count=0
  for _,mode in ipairs(modes_to_resolve) do
    for _,term in ipairs(mode.terms) do
      if required[term.id]==nil then
        required[term.id]=true
        required_count=required_count+1
      end
      assert(paths[term.id]~=nil,
        'standalone source mode map lacks a required response id')
    end
  end
  local mapped_count=0
  for id,_ in pairs(paths) do
    mapped_count=mapped_count+1
    assert(required[id], 'standalone source mode map contains an unused response id')
  end
  assert(mapped_count==required_count,
    'standalone source mode map does not exactly cover required responses')
  return paths
end

local standalone_paths=nil
if source_policy=='standalone_mode_map_v1' then
  standalone_paths=parse_standalone_mode_map(source_input,modes)
else
  assert(source_input:lower():match('%.pa0$'),
    'writable staging native-family source must end in .pa0')
end

local function source_path(id)
  if standalone_paths~=nil then return standalone_paths[id] end
  return indexed(source_input,id)
end

-- A mode array is an ordinary PA file selected by the adjacent .pa+ map.
-- Copy the unrefined GEM result directly instead of calling `refine` merely
-- to materialize files: every boundary value below replaces that provisional
-- solution, and the runner subsequently performs exactly one official-default
-- refine per completed mode.
local function exists(path)
  local file=io.open(path,'rb')
  if file==nil then return false end
  file:close()
  return true
end
local function copy_file(source,destination)
  local input=assert(io.open(source,'rb'),'cannot open PA template: '..source)
  local output=assert(io.open(destination,'wb'),'cannot create PA mode: '..destination)
  output:write(assert(input:read('*a'),'cannot read PA template: '..source))
  input:close()
  output:close()
end
for _,mode in ipairs(modes) do
  local fine_path=indexed(fine_pa_sharp,mode.id)
  if not exists(fine_path) then copy_file(fine_pa_sharp,fine_path) end
end

local total_boundary_points=0
for _,mode in ipairs(modes) do
  local source_arrays={}
  for _,term in ipairs(mode.terms) do
    source_arrays[term.id]=assert(simion.pas:open(source_path(term.id)),
      'cannot open solved source response')
  end
  local fine=simion.pas:open(indexed(fine_pa_sharp,mode.id))
  assert(fine.nx>=3 and fine.ny>=3 and fine.nz>=3,
    'PA+ fine PA must have at least three points on every axis')
  local reference_source=source_arrays[mode.terms[1].id]
  local count=0
  local function copy(ix,iy,iz)
    local wx=fine_origin[1]+ix*fine.dx_mm
    local wy=fine_origin[2]+iy*fine.dy_mm
    local wz=fine_origin[3]+iz*fine.dz_mm
    local cx=(wx-source_origin[1])/reference_source.dx_mm
    local cy=(wy-source_origin[2])/reference_source.dy_mm
    local cz=(wz-source_origin[3])/reference_source.dz_mm
    local value=0
    for _,term in ipairs(mode.terms) do
      local source=source_arrays[term.id]
      assert(source:inside_vc(cx,cy,cz),'fine boundary escapes source PA')
      value=value+term.weight*source:potential_vc(cx,cy,cz)
    end
    fine:point(ix,iy,iz,value,true)
    count=count+1
  end
  for iz=0,fine.nz-1 do for iy=0,fine.ny-1 do copy(0,iy,iz); copy(fine.nx-1,iy,iz) end end
  for iz=0,fine.nz-1 do for ix=1,fine.nx-2 do copy(ix,0,iz); copy(ix,fine.ny-1,iz) end end
  for iy=1,fine.ny-2 do for ix=1,fine.nx-2 do copy(ix,iy,0); copy(ix,iy,fine.nz-1) end end
  local expected=2*fine.ny*fine.nz+2*(fine.nx-2)*fine.nz+2*(fine.nx-2)*(fine.ny-2)
  assert(count==expected,'disjoint PA+ boundary traversal is incomplete')
  fine:save()
  simion.pas:close()
  total_boundary_points=total_boundary_points+count
end
local report=assert(io.open(report_path,'w'))
report:write(string.format('{\n  "schema_version": 1,\n  "role": "simion_accelerator_pa_plus_basis_build",\n  "status": "pass",\n  "source_response_policy": "%s",\n  "boundary_traversal": "disjoint_six_faces_v1",\n  "duplicate_boundary_writes": 0,\n  "mode_count": %d,\n  "boundary_point_write_count": %d\n}\n',source_policy,#modes,total_boundary_points))
report:close()
print(string.format('ACCELERATOR_PA_PLUS_BASIS=PASS MODE_COUNT=%d BOUNDARY_WRITES=%d',#modes,total_boundary_points))
