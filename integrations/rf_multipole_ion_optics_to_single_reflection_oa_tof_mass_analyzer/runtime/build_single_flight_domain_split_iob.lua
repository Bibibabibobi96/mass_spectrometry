-- Build a structural six-instance IOB for the long-gap domain-split design.
--
-- This uses the same SIMION-distributed six-slot container as the existing
-- two-local-overlay builder.  It replaces every PA and preserves the governed
-- Formal transforms for flight, reflectron, accelerator and detector.  It
-- deliberately does not attach a Program/Fly2: a runnable domain-split IOB
-- additionally requires a Program that selects exactly one PA in every
-- overlap and applies the common bridge electrode bases before Refine.
--
-- Usage:
--   simion.exe --nogui --noprompt lua build_single_flight_domain_split_iob.lua
--     formal.iob container6.iob output.iob coarse-frontend.pa0 reflectron.pa0
--     accelerator-main.pa0 detector.pa0 upstream.pa0 intermediate2.pa0
--     coarse_ox coarse_oy coarse_oz accelerator_ox accelerator_oy accelerator_oz
--     upstream_ox upstream_oy upstream_oz intermediate_ox intermediate_oy intermediate_oz

local formal=assert(arg[1], 'formal IOB is required')
local container=assert(arg[2], 'six-instance container IOB is required')
local output=assert(arg[3], 'output IOB is required')
local pa_paths={
  assert(arg[4], 'coarse frontend PA0 is required'),
  assert(arg[5], 'reflectron PA0 is required'),
  assert(arg[6], 'accelerator-main PA0 is required'),
  assert(arg[7], 'detector PA0 is required'),
  assert(arg[8], 'upstream bridge PA0 is required'),
  assert(arg[9], 'intermediate2 overlay PA0 is required'),
}
local coarse_origin={
  assert(tonumber(arg[10]), 'coarse frontend origin x is invalid'),
  assert(tonumber(arg[11]), 'coarse frontend origin y is invalid'),
  assert(tonumber(arg[12]), 'coarse frontend origin z is invalid'),
}
local accelerator_origin={
  assert(tonumber(arg[13]), 'accelerator main origin x is invalid'),
  assert(tonumber(arg[14]), 'accelerator main origin y is invalid'),
  assert(tonumber(arg[15]), 'accelerator main origin z is invalid'),
}
local upstream_origin={
  assert(tonumber(arg[16]), 'upstream bridge origin x is invalid'),
  assert(tonumber(arg[17]), 'upstream bridge origin y is invalid'),
  assert(tonumber(arg[18]), 'upstream bridge origin z is invalid'),
}
local intermediate_origin={
  assert(tonumber(arg[19]), 'intermediate2 overlay origin x is invalid'),
  assert(tonumber(arg[20]), 'intermediate2 overlay origin y is invalid'),
  assert(tonumber(arg[21]), 'intermediate2 overlay origin z is invalid'),
}

simion.command('"'..formal..'"')
assert(#simion.wb.instances==4 or #simion.wb.instances==5,
  'formal single-flight IOB must contain four or five instances')
local transforms={}
for _,index in ipairs({2,4}) do
  local item=simion.wb.instances[index]
  transforms[index]={
    x=item.x,y=item.y,z=item.z,az=item.az,el=item.el,rt=item.rt,
    scale=item.scale,nz_use=item.nz_use,
  }
end

simion.command('"'..container..'"')
assert(#simion.wb.instances==6,'SIMION container must contain exactly six instances')
for index=1,6 do
  local item=simion.wb.instances[index]
  item.pa:load(pa_paths[index])
  item:_debug_update_size()
  local transform=transforms[index] or ((index==1) and {
    x=coarse_origin[1],y=coarse_origin[2],z=coarse_origin[3],
    az=0,el=0,rt=0,scale=1,nz_use=0,
  } or (index==3) and {
    x=accelerator_origin[1],y=accelerator_origin[2],z=accelerator_origin[3],
    az=0,el=0,rt=0,scale=1,nz_use=0,
  } or (index==5) and {
    x=upstream_origin[1],y=upstream_origin[2],z=upstream_origin[3],
    az=0,el=0,rt=0,scale=1,nz_use=0,
  } or {
    x=intermediate_origin[1],y=intermediate_origin[2],z=intermediate_origin[3],
    az=0,el=0,rt=0,scale=1,nz_use=0,
  })
  item.x,item.y,item.z=transform.x,transform.y,transform.z
  item.az,item.el,item.rt,item.scale=transform.az,transform.el,transform.rt,transform.scale
  if item.pa.nz==1 and transform.nz_use~=nil then item.nz_use=transform.nz_use end
end
simion.wb:save(output)
print(string.format(
  'SINGLE_FLIGHT_DOMAIN_SPLIT_IOB=STRUCTURAL_ONLY INSTANCES=%d ROLES=coarse_frontend,reflectron,accelerator_main,detector,upstream,intermediate2',
  #simion.wb.instances))
