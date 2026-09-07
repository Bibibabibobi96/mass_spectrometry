-- Build the compact four-instance pre-pulse IOB.
-- Slots are consecutive by physical traversal: coarse frontend, upstream RF
-- fine PA, zero-field first-zone collision geometry, then the field-bearing
-- entrance-local replacement.  The local PA has the highest overlap priority,
-- exactly as it does in continuous full flight.  Downstream hardware is
-- deliberately absent from this detector-blind handoff producer.
--
-- Usage:
--   simion ... lua build_single_flight_pre_pulse_iob.lua container.iob output.iob
--     coarse.pa0 upstream.pa0 entrance-zero-field.pa0 entrance-local.pa0
--     coarse_ox coarse_oy coarse_oz upstream_ox upstream_oy upstream_oz
--     entrance_ox entrance_oy entrance_oz local_ox local_oy local_oz

local container=assert(arg[1], 'four-instance container IOB is required')
local output=assert(arg[2], 'output IOB is required')
local pa_paths={
  assert(arg[3], 'coarse frontend PA0 is required'),
  assert(arg[4], 'upstream bridge PA0 is required'),
  assert(arg[5], 'zero-field entrance PA0 is required'),
  assert(arg[6], 'field-bearing entrance-local PA0 is required'),
}
local origins={
  {assert(tonumber(arg[7]), 'coarse origin x is invalid'),assert(tonumber(arg[8]), 'coarse origin y is invalid'),assert(tonumber(arg[9]), 'coarse origin z is invalid')},
  {assert(tonumber(arg[10]), 'upstream origin x is invalid'),assert(tonumber(arg[11]), 'upstream origin y is invalid'),assert(tonumber(arg[12]), 'upstream origin z is invalid')},
  {assert(tonumber(arg[13]), 'entrance origin x is invalid'),assert(tonumber(arg[14]), 'entrance origin y is invalid'),assert(tonumber(arg[15]), 'entrance origin z is invalid')},
  {assert(tonumber(arg[16]), 'entrance-local origin x is invalid'),assert(tonumber(arg[17]), 'entrance-local origin y is invalid'),assert(tonumber(arg[18]), 'entrance-local origin z is invalid')},
}

simion.command('"'..container..'"')
assert(#simion.wb.instances==4, 'pre-pulse container must contain exactly four instances')
for index=1,4 do
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
  'SINGLE_FLIGHT_PRE_PULSE_IOB=PASS INSTANCES=%d ROLES=coarse_frontend,upstream_bridge,accelerator_entrance_zero_field,accelerator_entrance_aperture_local',
  #simion.wb.instances))
