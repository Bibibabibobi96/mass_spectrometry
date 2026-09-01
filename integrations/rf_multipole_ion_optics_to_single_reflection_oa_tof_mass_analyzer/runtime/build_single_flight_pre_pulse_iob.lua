-- Build the compact three-instance pre-pulse IOB.
-- Slots are consecutive by physical traversal: coarse frontend, upstream RF
-- fine PA, then zero-field entrance geometry.  Downstream hardware is
-- deliberately absent from this detector-blind handoff producer.
--
-- Usage:
--   simion ... lua build_single_flight_pre_pulse_iob.lua container.iob output.iob
--     coarse.pa0 upstream.pa0 entrance-zero-field.pa0
--     coarse_ox coarse_oy coarse_oz upstream_ox upstream_oy upstream_oz
--     entrance_ox entrance_oy entrance_oz

local container=assert(arg[1], 'three-instance container IOB is required')
local output=assert(arg[2], 'output IOB is required')
local pa_paths={
  assert(arg[3], 'coarse frontend PA0 is required'),
  assert(arg[4], 'upstream bridge PA0 is required'),
  assert(arg[5], 'zero-field entrance PA0 is required'),
}
local origins={
  {assert(tonumber(arg[6]), 'coarse origin x is invalid'),assert(tonumber(arg[7]), 'coarse origin y is invalid'),assert(tonumber(arg[8]), 'coarse origin z is invalid')},
  {assert(tonumber(arg[9]), 'upstream origin x is invalid'),assert(tonumber(arg[10]), 'upstream origin y is invalid'),assert(tonumber(arg[11]), 'upstream origin z is invalid')},
  {assert(tonumber(arg[12]), 'entrance origin x is invalid'),assert(tonumber(arg[13]), 'entrance origin y is invalid'),assert(tonumber(arg[14]), 'entrance origin z is invalid')},
}

simion.command('"'..container..'"')
assert(#simion.wb.instances==3, 'pre-pulse container must contain exactly three instances')
for index=1,3 do
  local item=simion.wb.instances[index]
  item.pa.filename=pa_paths[index]
  item.pa:load()
  item:_debug_update_size()
  item.x,item.y,item.z=origins[index][1],origins[index][2],origins[index][3]
  item.az,item.el,item.rt,item.scale=0,0,0,1
  if item.pa.nz==1 then item.nz_use=0 end
end
simion.wb:save(output)
print(string.format(
  'SINGLE_FLIGHT_PRE_PULSE_IOB=PASS INSTANCES=%d ROLES=coarse_frontend,upstream_bridge,accelerator_entrance_zero_field',
  #simion.wb.instances))
