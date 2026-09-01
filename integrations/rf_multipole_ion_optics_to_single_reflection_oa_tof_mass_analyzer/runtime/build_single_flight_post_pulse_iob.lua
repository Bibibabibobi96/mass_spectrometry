-- Build the five-instance handoff consumer IOB.
-- Slots: flight tube, reflectron, accelerator main, detector, entrance local.
-- The upstream multipole and connector are intentionally absent because every
-- accepted restart state is already inside the accelerator-local/main union.
--
-- Usage:
--   simion ... lua build_single_flight_post_pulse_iob.lua
--     formal.iob container5.iob output.iob flight.pa0 reflectron.pa0 main.pa0
--     detector.pa0 local.pa0 main_ox main_oy main_oz local_ox local_oy local_oz

local formal=assert(arg[1], 'formal IOB is required')
local container=assert(arg[2], 'five-instance container IOB is required')
local output=assert(arg[3], 'output IOB is required')
local pa_paths={
  assert(arg[4], 'flight-tube PA0 is required'),
  assert(arg[5], 'reflectron PA0 is required'),
  assert(arg[6], 'accelerator-main PA0 is required'),
  assert(arg[7], 'detector PA0 is required'),
  assert(arg[8], 'accelerator entrance-local PA0 is required'),
}
local main_origin={
  assert(tonumber(arg[9]), 'accelerator-main origin x is invalid'),
  assert(tonumber(arg[10]), 'accelerator-main origin y is invalid'),
  assert(tonumber(arg[11]), 'accelerator-main origin z is invalid'),
}
local local_origin={
  assert(tonumber(arg[12]), 'entrance-local origin x is invalid'),
  assert(tonumber(arg[13]), 'entrance-local origin y is invalid'),
  assert(tonumber(arg[14]), 'entrance-local origin z is invalid'),
}

simion.command('"'..formal..'"')
assert(#simion.wb.instances==4 or #simion.wb.instances==5,
  'formal single-flight IOB must contain four or five instances')
local transforms={}
for _,index in ipairs({1,2,4}) do
  local item=simion.wb.instances[index]
  transforms[index]={x=item.x,y=item.y,z=item.z,az=item.az,el=item.el,rt=item.rt,
    scale=item.scale,nz_use=item.nz_use}
end
transforms[3]={x=main_origin[1],y=main_origin[2],z=main_origin[3],
  az=0,el=0,rt=0,scale=1,nz_use=0}
transforms[5]={x=local_origin[1],y=local_origin[2],z=local_origin[3],
  az=0,el=0,rt=0,scale=1,nz_use=0}

simion.command('"'..container..'"')
assert(#simion.wb.instances==5,'SIMION container must contain exactly five instances')
for index=1,5 do
  local item=simion.wb.instances[index]
  local transform=transforms[index]
  item.filename=pa_paths[index]
  item.pa:load()
  item:_debug_update_size()
  item.x,item.y,item.z=transform.x,transform.y,transform.z
  item.az,item.el,item.rt,item.scale=transform.az,transform.el,transform.rt,transform.scale
  if item.pa.nz==1 and transform.nz_use~=nil then item.nz_use=transform.nz_use end
end
simion.wb:save(output)
print(string.format(
  'SINGLE_FLIGHT_POST_PULSE_IOB=PASS INSTANCES=%d ROLES=flight_tube,reflectron,accelerator_main,detector,accelerator_entrance_local',
  #simion.wb.instances))
