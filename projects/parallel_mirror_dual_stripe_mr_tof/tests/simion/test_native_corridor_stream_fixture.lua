-- Tiny production->append->delete fixture for the corridor stream runner.
-- It uses the real MR-TOF physical response groups but a tiny 11^3 geometry.
-- Usage: simion --nogui --noprompt lua this.lua DIRECTORY
local root = assert(arg[1], 'fixture directory required')
local groups = {{2,7},{3,8},{4,9},{5,10},{11,12},{13,14},{16},{17}}
local node_ids = {2,7,3,8,4,9,5,10,11,12,13,14,16,17}
local function path(name) return root .. '/' .. name end
local function new_pa()
  local pa = assert(simion.pas:open()); pa:size(11,11,11)
  pa.dx_mm, pa.dy_mm, pa.dz_mm = 1,1,1; pa.potential_type='electric'; return pa
end
local raw = new_pa()
for z=0,raw.nz-1 do for y=0,raw.ny-1 do for x=0,raw.nx-1 do
  local flat = x + y*raw.nx + z*raw.nx*raw.ny + 1
  local id = node_ids[flat]
  local active = id ~= nil
  raw:point(x,y,z,active and id or 0,active)
end end end
raw.refined,raw.refinable=true,false; raw:save(path('coarse.pa#')); raw:close()
local corridor = new_pa()
for z=0,corridor.nz-1 do for y=0,corridor.ny-1 do for x=0,corridor.nx-1 do
  local flat=x+y*corridor.nx+z*corridor.nx*corridor.ny+1
  local active=flat<=8
  corridor:point(x,y,z,active and flat or 0,active)
end end end
corridor.refined,corridor.refinable=true,false; corridor:save(path('corridor.pa#')); corridor:close()
for response_id,physical_ids in ipairs(groups) do
  local response = new_pa()
  for z=0,response.nz-1 do for y=0,response.ny-1 do for x=0,response.nx-1 do
    local flat = x + y*response.nx + z*response.nx*response.ny + 1
    local id = node_ids[flat]
    local active = id ~= nil
    local belongs = false
    for _,physical_id in ipairs(physical_ids) do if id==physical_id then belongs=true end end
    response:point(x,y,z,active and belongs and 10000 or 0,active)
  end end end
  response.refined,response.refinable=true,false
  response:save(path('coarse_response'..response_id..'.pa')); response:close()
end
print('MRTOF_NATIVE_CORRIDOR_STREAM_FIXTURE=PASS coarse_basis=8 full_corridor_workers=0')
