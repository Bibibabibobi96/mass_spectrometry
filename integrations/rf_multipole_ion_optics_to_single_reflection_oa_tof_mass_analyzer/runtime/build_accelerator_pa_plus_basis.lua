-- Boundary-couple a PA+ solution family from a source fast-adjust family.
-- mode_spec format: "solution:source=coefficient,source=coefficient;...".
-- The caller supplies physical-source terms for accelerator main and identity
-- PA+-mode terms for the nested entrance-local replacement.

local source_pa0=assert(arg[1], 'source PA0 is required')
local fine_pa_sharp=assert(arg[2], 'fine PA# is required')
local source_origin={assert(tonumber(arg[3])),assert(tonumber(arg[4])),assert(tonumber(arg[5]))}
local fine_origin={assert(tonumber(arg[6])),assert(tonumber(arg[7])),assert(tonumber(arg[8]))}
local mode_spec=assert(arg[9], 'PA+ mode specification is required')
local report_path=assert(arg[10], 'report path is required')
assert(source_pa0:match('%.pa0$'), 'source input must end in .pa0')
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
    source_arrays[term.id]=simion.pas:open(indexed(source_pa0,term.id))
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
report:write(string.format('{\n  "schema_version": 1,\n  "role": "simion_accelerator_pa_plus_basis_build",\n  "status": "pass",\n  "boundary_traversal": "disjoint_six_faces_v1",\n  "duplicate_boundary_writes": 0,\n  "mode_count": %d,\n  "boundary_point_write_count": %d\n}\n',#modes,total_boundary_points))
report:close()
print(string.format('ACCELERATOR_PA_PLUS_BASIS=PASS MODE_COUNT=%d BOUNDARY_WRITES=%d',#modes,total_boundary_points))
