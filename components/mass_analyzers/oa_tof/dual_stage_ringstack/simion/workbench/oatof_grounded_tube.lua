-- SIMION automatically associates this same-basename program with the IOB.
simion.workbench_program()
adjustable ideal_grid_epsilon_mm = 0.01
local grids = {{name='grid1',z=3.0},{name='grid2',z=19.83},
  {name='entgrid',z=619.83},{name='midgrid',z=739.83}}
local last_z, jumped = {}, {}
local function key(n,g) return tostring(n)..':'..g.name end
function segment.initialize() last_z[ion_number] = ion_pz_mm end
function segment.other_actions()
  local n,z,vz = ion_number,ion_pz_mm,ion_vz_mm
  local zp,eps = last_z[n] or z,ideal_grid_epsilon_mm
  for _,g in ipairs(grids) do
    local k=key(n,g); local dir=vz >= 0 and 1 or -1
    local pre,post=g.z-dir*eps,g.z+dir*eps
    if jumped[k] and math.abs(z-g.z)>4*eps then jumped[k]=nil end
    local crossed=(dir>0 and zp<pre and z>=pre) or (dir<0 and zp>pre and z<=pre)
    if not jumped[k] and crossed then
      if math.abs(vz)<1e-12 then error('grid jump attempted with vz=0') end
      ion_time_of_flight=ion_time_of_flight+math.abs(post-z)/math.abs(vz)
      ion_pz_mm=post; jumped[k]=true; break
    end
  end
  last_z[n]=ion_pz_mm
end
