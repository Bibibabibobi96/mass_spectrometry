-- Build the seven-instance continuous full-flight IOB for a long-gap,
-- three-zone accelerator.  Every instance is physical: the coarse bridge,
-- upstream fine PA, main accelerator, flight tube, reflectron, aperture-local
-- replacement, and detector.  The local PA deliberately occupies slot 6 so it
-- has higher priority than the main accelerator in their overlap.
--
-- The container is a version-controlled GUI seed.  SIMION 2020 exposes no
-- supported Lua API to add arbitrary Workbench instances, so the seed carries
-- only the instance count; this builder replaces every placeholder PA.
--
-- Usage:
--   simion ... lua build_single_flight_full_iob.lua formal.iob container7.iob
--     output.iob coarse.pa0 upstream.pa0 main.pa0 flight.pa0 reflectron.pa0
--     local.pa0 detector.pa0 coarse_ox coarse_oy coarse_oz upstream_ox ...

local formal=assert(arg[1], 'formal IOB is required')
local container=assert(arg[2], 'seven-instance container IOB is required')
local output=assert(arg[3], 'output IOB is required')
local pa_paths={
  assert(arg[4], 'coarse frontend PA0 is required'),
  assert(arg[5], 'upstream bridge PA0 is required'),
  assert(arg[6], 'accelerator-main PA0 is required'),
  assert(arg[7], 'flight-tube PA0 is required'),
  assert(arg[8], 'reflectron PA0 is required'),
  assert(arg[9], 'accelerator entrance aperture-local PA0 is required'),
  assert(arg[10], 'detector PA0 is required'),
}
local function origin(offset, label)
  return {
    assert(tonumber(arg[offset]), label..' origin x is invalid'),
    assert(tonumber(arg[offset+1]), label..' origin y is invalid'),
    assert(tonumber(arg[offset+2]), label..' origin z is invalid'),
  }
end
local coarse_origin=origin(11, 'coarse frontend')
local upstream_origin=origin(14, 'upstream bridge')
local main_origin=origin(17, 'accelerator main')
local local_origin=origin(20, 'accelerator entrance local')

-- Flight tube, reflectron, and detector retain the verified formal transforms.
simion.command('"'..formal..'"')
assert(#simion.wb.instances==4 or #simion.wb.instances==5,
  'formal single-flight IOB must contain four or five instances')
local transforms={}
for formal_index,slot in pairs({[1]=4,[2]=5,[4]=7}) do
  local item=simion.wb.instances[formal_index]
  transforms[slot]={x=item.x,y=item.y,z=item.z,az=item.az,el=item.el,rt=item.rt,
    scale=item.scale,nz_use=item.nz_use}
end
for slot,point in pairs({[1]=coarse_origin,[2]=upstream_origin,[3]=main_origin,[6]=local_origin}) do
  transforms[slot]={x=point[1],y=point[2],z=point[3],az=0,el=0,rt=0,scale=1,nz_use=0}
end

simion.command('"'..container..'"')
assert(#simion.wb.instances==7, 'full-flight container must contain exactly seven instances')
for index=1,7 do
  local item=simion.wb.instances[index]
  local transform=assert(transforms[index], 'full-flight transform is missing')
  item.pa:load(pa_paths[index])
  item.pa.filename=pa_paths[index]
  item:_debug_update_size()
  item.x,item.y,item.z=transform.x,transform.y,transform.z
  item.az,item.el,item.rt,item.scale=transform.az,transform.el,transform.rt,transform.scale
  if item.pa.nz==1 and transform.nz_use~=nil then item.nz_use=transform.nz_use end
end
simion.wb:save(output)
print(string.format(
  'SINGLE_FLIGHT_FULL_IOB=PASS INSTANCES=%d ROLES=coarse_frontend,upstream_bridge,accelerator_main,flight_tube,reflectron,accelerator_entrance_aperture_local,detector',
  #simion.wb.instances))
