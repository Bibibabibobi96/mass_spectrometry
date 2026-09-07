-- Restore physical geometry flags after Dirichlet-constrained basis solving.
-- Apply only to writable run-local copies, never to an immutable cache.
-- SIMION2020 official electrode(x,y,z,bool) preserves decoded potential;
-- see installed examples/magnetic_potential/current_sphere_3dp.lua.
local template_path=assert(arg[1],'run-local geometry PA# is required')
local mode_spec=assert(arg[2],'comma-separated solution IDs are required')
local report_path=assert(arg[3],'boundary mask receipt is required')
assert(template_path:match('%.pa#$'),'geometry template must end in .pa#')
local modes={}
for token in mode_spec:gmatch('[^,]+') do
  local id=assert(tonumber(token),'invalid solution ID')
  assert(id>0 and id==math.floor(id),'solution ID must be a positive integer')
  modes[#modes+1]=id
end
assert(#modes>0,'solution IDs are empty')
local receipts={}
for _,id in ipairs(modes) do
  simion.pas:close()
  local template=simion.pas:open(template_path)
  local fine=simion.pas:open((template_path:gsub('#$',tostring(id))))
  assert(fine.nx==template.nx and fine.ny==template.ny and fine.nz==template.nz,
    'basis and geometry dimensions differ')
  assert(fine.dx_mm==template.dx_mm and fine.dy_mm==template.dy_mm and fine.dz_mm==template.dz_mm,
    'basis and geometry cell sizes differ')
  local visited,changed=0,0
  local function restore(ix,iy,iz)
    local physical=template:electrode(ix,iy,iz)
    local electrode=fine:electrode(ix,iy,iz)
    assert(not physical or electrode,'basis lost a physical boundary electrode')
    if not physical and electrode then
      fine:electrode(ix,iy,iz,false)
      changed=changed+1
    end
    visited=visited+1
  end
  for iz=0,fine.nz-1 do for iy=0,fine.ny-1 do restore(0,iy,iz); restore(fine.nx-1,iy,iz) end end
  for iz=0,fine.nz-1 do for ix=1,fine.nx-2 do restore(ix,0,iz); restore(ix,fine.ny-1,iz) end end
  for iy=1,fine.ny-2 do for ix=1,fine.nx-2 do restore(ix,iy,0); restore(ix,iy,fine.nz-1) end end
  local expected=2*fine.ny*fine.nz+2*(fine.nx-2)*fine.nz+2*(fine.nx-2)*(fine.ny-2)
  assert(visited==expected,'boundary traversal is incomplete')
  if changed>0 then fine:save() end
  simion.pas:close()
  receipts[#receipts+1]=string.format('{"mode_id":%d,"boundary_points":%d,"restored_flags":%d}',id,visited,changed)
  print(string.format('PA_PLUS_BOUNDARY_MASK_MODE=PASS MODE=%d RESTORED_FLAGS=%d',id,changed))
end
local report=assert(io.open(report_path,'w'))
report:write('{"schema_version":1,"role":"simion_pa_plus_boundary_mask_restoration",'..
  '"policy_id":"physical_geometry_boundary_flags_v1","status":"pass",'..
  '"potential_operation":"unchanged_official_electrode_setter","modes":['..table.concat(receipts,',')..']}\n')
report:close()
print('PA_PLUS_BOUNDARY_MASK=PASS')
