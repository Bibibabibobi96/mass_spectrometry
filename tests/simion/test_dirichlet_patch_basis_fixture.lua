-- Tiny native donor -> six-face boundary -> Refine fixture.
-- Usage: simion --nogui --noprompt lua this.lua prepare|verify DIRECTORY
local mode=assert(arg[1], 'mode required')
local root=assert(arg[2], 'fixture directory required')
local function path(name) return root..'/'..name end
if mode=='prepare' then
  local donor=assert(simion.pas:open()); donor:size(9,9,9)
  donor.dx_mm,donor.dy_mm,donor.dz_mm=1,1,1
  for z=0,8 do for y=0,8 do for x=0,8 do
    donor:point(x,y,z,10000*(x+y+z)/24,false)
  end end end
  donor.refined,donor.refinable=true,false
  donor:save(path('donor.pa')); donor:close()
  local gem=assert(io.open(path('target.gem'),'wb'))
  gem:write('pa_define(7,7,7,planar,none,electrostatic,,1,1,1,surface=none)\n')
  gem:write('e(10000) { box3D(3,3,3,3,3,3) }\n')
  gem:close()
  local mirror=assert(io.open(path('target_mirror.gem'),'wb'))
  mirror:write('pa_define(4,7,7,planar,x,electrostatic,,1,1,1,surface=none)\n')
  mirror:write('e(10000) { box3D(2,3,3,2,3,3) }\n')
  mirror:close()
  print('DIRICHLET_PATCH_FIXTURE=PREPARED native_basis_voltage=10000')
elseif mode=='verify' then
  local target=assert(simion.pas:open(path('target.pa')),'target PA missing')
  local low,low_electrode=target:point(0,0,0)
  local high,high_electrode=target:point(6,6,6)
  local center,center_electrode=target:point(3,3,3)
  assert(low_electrode and high_electrode and center_electrode,'Dirichlet or center electrode flag missing')
  assert(math.abs(low-1250)<1e-6,'low boundary voltage is not the native donor value')
  assert(math.abs(high-8750)<1e-6,'high boundary voltage is not the native donor value')
  assert(math.abs(center-10000)<1e-6,'pre-biased center electrode changed')
  target:close()
  print('DIRICHLET_PATCH_FIXTURE=PASS boundary_scale=1 native_basis_voltage=10000')
elseif mode=='verify_scaled' then
  local target=assert(simion.pas:open(path('target.pa')),'target PA missing')
  local low=target:potential(0,0,0)
  local high=target:potential(6,6,6)
  local center=target:potential(3,3,3)
  assert(math.abs(low-625)<1e-6,'scaled low boundary voltage differs')
  assert(math.abs(high-4375)<1e-6,'scaled high boundary voltage differs')
  assert(math.abs(center-10000)<1e-6,'scaled pre-biased electrode changed')
  target:close()
  print('DIRICHLET_PATCH_FIXTURE=PASS boundary_scale=0.5 native_basis_voltage=10000')
elseif mode=='verify_mirror' then
  local target=assert(simion.pas:open(path('target_mirror.pa')),'mirrored target PA missing')
  local _,symmetry_plane_electrode=target:point(0,3,3)
  local mirror_y_edge,mirror_y_edge_electrode=target:point(0,0,3)
  local mirror_z_edge,mirror_z_edge_electrode=target:point(0,3,0)
  local outer,outer_electrode=target:point(3,3,3)
  local center,center_electrode=target:point(2,3,3)
  assert(not symmetry_plane_electrode,'x mirror plane interior was replaced by a Dirichlet electrode')
  assert(mirror_y_edge_electrode and math.abs(mirror_y_edge-1250)<1e-6,'x mirror/y boundary edge was omitted')
  assert(mirror_z_edge_electrode and math.abs(mirror_z_edge-1250)<1e-6,'x mirror/z boundary edge was omitted')
  assert(outer_electrode and math.abs(outer-3750)<1e-6,'outer donor boundary differs')
  assert(center_electrode and math.abs(center-10000)<1e-6,'mirrored pre-biased electrode changed')
  target:close()
  print('DIRICHLET_PATCH_FIXTURE=PASS boundary_mode=x_mirror_five_faces')
else
  error('mode must be prepare, verify, verify_scaled or verify_mirror')
end
