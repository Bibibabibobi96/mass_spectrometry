-- Initialize and boundary-couple a local accelerator fast-adjust PA family.
-- The coarse and fine arrays are axis-aligned in the same workbench frame.
-- Usage:
--   simion.exe --nogui --noprompt lua build_accelerator_overlay_basis.lua
--     coarse.pa0 fine.pa# coarse_ox coarse_oy coarse_oz
--     fine_ox fine_oy fine_oz maximum_electrode report.json

local coarse_pa0=assert(arg[1], 'coarse PA0 is required')
local fine_pa_sharp=assert(arg[2], 'fine PA# is required')
local coarse_origin={
  assert(tonumber(arg[3]), 'coarse origin x is invalid'),
  assert(tonumber(arg[4]), 'coarse origin y is invalid'),
  assert(tonumber(arg[5]), 'coarse origin z is invalid'),
}
local fine_origin={
  assert(tonumber(arg[6]), 'fine origin x is invalid'),
  assert(tonumber(arg[7]), 'fine origin y is invalid'),
  assert(tonumber(arg[8]), 'fine origin z is invalid'),
}
local maximum_electrode=assert(tonumber(arg[9]), 'maximum electrode is invalid')
local report_path=assert(arg[10], 'report path is required')
assert(maximum_electrode>=1 and maximum_electrode==math.floor(maximum_electrode),
  'maximum electrode must be a positive integer')
assert(coarse_pa0:match('%.pa0$'), 'coarse input must end in .pa0')
assert(fine_pa_sharp:match('%.pa#$'), 'fine input must end in .pa#')

local function indexed(path,index)
  if path:match('%.pa0$') then return path:gsub('0$',tostring(index)) end
  return path:gsub('#$',tostring(index))
end

-- A basis is a durable unit of work: it is safe to reuse only after SIMION
-- has saved the full array and this small receipt has been written.  The
-- cache staging directory is identity-bound by the caller, so receipts from a
-- different geometry, coarse boundary family, or builder cannot be reused.
local function receipt_path(index)
  return report_path .. '.basis_' .. tostring(index) .. '.complete'
end
local function exists(path)
  local file=io.open(path,'rb')
  if file==nil then return false end
  file:close()
  return true
end
local function write_receipt(index)
  local receipt=assert(io.open(receipt_path(index),'w'))
  receipt:write('complete\n')
  receipt:close()
end
local function copy_file(source,destination)
  local input=assert(io.open(source,'rb'),'cannot open PA template: '..source)
  local output=assert(io.open(destination,'wb'),'cannot create PA basis: '..destination)
  output:write(assert(input:read('*a'),'cannot read PA template: '..source))
  input:close()
  output:close()
end

-- Materialize ordinary PA members from the unrefined fast-adjust template.
-- Calling ``refine{}`` here would first solve every member with provisional
-- boundaries, then the runner would solve every member again after Dirichlet
-- projection.  The only field solve is the runner's later official-default
-- Refine, after each basis has its physical outer boundary.
local has_receipt=false
for basis=0,maximum_electrode do
  if exists(receipt_path(basis)) then has_receipt=true break end
end
if not has_receipt then
  -- Without a completed-basis receipt a prior process may have stopped while
  -- writing any member.  Replace the whole family from the immutable GEM
  -- template instead of trusting a partial array.
  for basis=0,maximum_electrode do
    copy_file(fine_pa_sharp,indexed(fine_pa_sharp,basis))
  end
else
  -- Keep receipt-protected arrays; materialize only a missing uncompleted
  -- member after an interruption.
  for basis=0,maximum_electrode do
    local fine_path=indexed(fine_pa_sharp,basis)
    if exists(receipt_path(basis)) then
      assert(exists(fine_path),'completed basis receipt lacks its PA array')
    elseif not exists(fine_path) then
      copy_file(fine_pa_sharp,fine_path)
    end
  end
end

local total_boundary_points=0
for basis=0,maximum_electrode do
  local coarse_path=indexed(coarse_pa0,basis)
  local fine_path=indexed(fine_pa_sharp,basis)
  if exists(receipt_path(basis)) then
    assert(exists(fine_path),'completed basis receipt lacks its PA array')
    local resumed=simion.pas:open(fine_path)
    assert(resumed.nx>=3 and resumed.ny>=3 and resumed.nz>=3,
      'completed accelerator-overlay basis has fewer than three points')
    local count=2*resumed.ny*resumed.nz + 2*(resumed.nx-2)*resumed.nz +
      2*(resumed.nx-2)*(resumed.ny-2)
    simion.pas:close()
    total_boundary_points=total_boundary_points+count
    print(string.format('OVERLAY_BASIS: basis=%d resumed=true fine=%s',basis,fine_path))
  else
  simion.pas:close()
  local coarse=simion.pas:open(coarse_path)
  local fine=simion.pas:open(fine_path)
  assert(fine.nx>=3 and fine.ny>=3 and fine.nz>=3,
    'accelerator-overlay PA must have at least three points on every axis')
  local count=0
  local function copy(ix,iy,iz)
    local wx=fine_origin[1]+ix*fine.dx_mm
    local wy=fine_origin[2]+iy*fine.dy_mm
    local wz=fine_origin[3]+iz*fine.dz_mm
    local cx=(wx-coarse_origin[1])/coarse.dx_mm
    local cy=(wy-coarse_origin[2])/coarse.dy_mm
    local cz=(wz-coarse_origin[3])/coarse.dz_mm
    assert(coarse:inside_vc(cx,cy,cz),string.format(
      'fine boundary escapes coarse PA basis=%d world=(%.12g,%.12g,%.12g)',
      basis,wx,wy,wz))
    local value=coarse:potential_vc(cx,cy,cz)
    assert(value==value and math.abs(value)<math.huge,
      'coarse boundary interpolation returned a non-finite value')
    fine:point(ix,iy,iz,value,true)
    count=count+1
  end

  -- The six faces are disjoint: x owns all edges/corners, y omits x edges,
  -- and z omits both x and y edges.  This retains exactly the legacy surface
  -- values without allocating a string key and hash-table entry per point.
  for iz=0,fine.nz-1 do for iy=0,fine.ny-1 do
    copy(0,iy,iz); copy(fine.nx-1,iy,iz)
  end end
  for iz=0,fine.nz-1 do for ix=1,fine.nx-2 do
    copy(ix,0,iz); copy(ix,fine.ny-1,iz)
  end end
  for iy=1,fine.ny-2 do for ix=1,fine.nx-2 do
    copy(ix,iy,0); copy(ix,iy,fine.nz-1)
  end end
  local expected=2*fine.ny*fine.nz + 2*(fine.nx-2)*fine.nz +
    2*(fine.nx-2)*(fine.ny-2)
  assert(count==expected, 'disjoint accelerator-overlay boundary traversal is incomplete')
  fine:save()
  write_receipt(basis)
  total_boundary_points=total_boundary_points+count
  print(string.format(
    'OVERLAY_BASIS: basis=%d boundary_points=%d coarse=%s fine=%s',
    basis,count,coarse_path,fine_path))
  end
end
simion.pas:close()

local report=assert(io.open(report_path,'w'))
report:write(string.format(
  '{\n  "schema_version": 4,\n  "role": "simion_accelerator_overlay_basis_build",\n  "status": "pass",\n  "boundary_traversal": "disjoint_six_faces_v1",\n  "duplicate_boundary_writes": 0,\n  "maximum_electrode_id": %d,\n  "basis_array_count": %d,\n  "boundary_point_write_count": %d\n}\n',
  maximum_electrode,maximum_electrode+1,total_boundary_points))
report:close()
print(string.format(
  'ACCELERATOR_OVERLAY_BASIS=PASS BASIS_COUNT=%d BOUNDARY_WRITES=%d',
  maximum_electrode+1,total_boundary_points))
